"""
Todoist tools: task completion trends, load analysis, project activity, decision fatigue signal.
Write tools: create_todoist_task, update_todoist_task, close_todoist_task, get_todoist_projects.
"""
import json
import logging
import os
import urllib.request
import urllib.parse
import urllib.error
import boto3
from datetime import datetime, timedelta
from collections import defaultdict

from mcp.config import USER_PREFIX, logger
from mcp.core import query_source, decimal_to_float
from mcp.helpers import pearson_r

# ── Todoist API client ────────────────────────────────────────────────────────

_TODOIST_BASE = "https://api.todoist.com/api/v1"
_SECRET_NAME = os.environ.get("SECRET_NAME", "life-platform/api-keys")
_REGION = os.environ.get("AWS_REGION", "us-west-2")
_todoist_token_cache = None


def _get_todoist_token():
    global _todoist_token_cache
    if _todoist_token_cache:
        return _todoist_token_cache
    client = boto3.client("secretsmanager", region_name=_REGION)
    resp = client.get_secret_value(SecretId=_SECRET_NAME)
    secret = json.loads(resp["SecretString"])
    _todoist_token_cache = secret.get("todoist_api_token") or secret.get("todoist")
    return _todoist_token_cache


def _todoist_request(method, path, payload=None):
    """Make an authenticated Todoist API request. Returns parsed JSON."""
    token = _get_todoist_token()
    url = _TODOIST_BASE + path
    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Todoist API {method} {path} → {e.code}: {body}")


def _list_all_tasks(filter_str=None):
    """Fetch all active tasks (paginated). Optional Todoist filter string."""
    all_tasks = []
    cursor = None
    while True:
        params = {"limit": 200}
        if filter_str:
            params["filter"] = filter_str
        if cursor:
            params["cursor"] = cursor
        path = "/tasks?" + urllib.parse.urlencode(params)
        result = _todoist_request("GET", path)
        items = result.get("items", result.get("results", result)) if isinstance(result, dict) else result
        if not isinstance(items, list):
            break
        all_tasks.extend(items)
        cursor = result.get("next_cursor") if isinstance(result, dict) else None
        if not cursor or not items:
            break
    return all_tasks

# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_todoist_range(days=30):
    """Fetch todoist records for the last N days. Returns list of day items."""
    end = datetime.utcnow().date()
    start = end - timedelta(days=days - 1)
    return query_source("todoist", str(start), str(end))


def _rolling_avg(series, window=7):
    """Compute rolling average for a list of (date, value) tuples."""
    result = []
    values = [v for _, v in series]
    for i, (date, val) in enumerate(series):
        window_vals = values[max(0, i - window + 1): i + 1]
        result.append((date, round(sum(window_vals) / len(window_vals), 1)))
    return result


# ── Tools ─────────────────────────────────────────────────────────────────────

def get_task_completion_trend(days: int = 30):
    """
    Task completion trend over the last N days.
    Returns daily completed count, 7-day rolling average, and summary stats.
    Useful for identifying productive streaks and low-output periods.
    """
    try:
        days = min(max(int(days), 7), 90)
        items = _get_todoist_range(days)
        if not items:
            return {"error": "No Todoist data available", "days_requested": days}

        series = []
        for item in sorted(items, key=lambda x: x.get("date", "")):
            date = item.get("date", "")
            count = int(item.get("completed_count", 0))
            series.append((date, count))

        rolling = _rolling_avg(series, window=7)
        values = [v for _, v in series]
        avg = round(sum(values) / len(values), 1) if values else 0
        peak = max(values) if values else 0
        zero_days = sum(1 for v in values if v == 0)

        # Streak: current consecutive days with >=1 completion
        streak = 0
        for _, v in reversed(series):
            if v > 0:
                streak += 1
            else:
                break

        return {
            "days_analyzed": len(series),
            "summary": {
                "average_completions_per_day": avg,
                "peak_day": peak,
                "zero_completion_days": zero_days,
                "current_completion_streak": streak,
            },
            "daily_series": [
                {"date": d, "completed": v, "rolling_7d_avg": r}
                for (d, v), (_, r) in zip(series, rolling)
            ],
        }
    except Exception as e:
        logger.error(f"get_task_completion_trend error: {e}")
        return {"error": str(e)}


def get_task_load_summary(days: int = 7):
    """
    Current task load snapshot: active count, overdue count, due-today count,
    priority breakdown, and recent daily completion rate.
    The decision fatigue signal — high active + high overdue = cognitive overhead.
    """
    try:
        items = _get_todoist_range(days)
        if not items:
            return {"error": "No Todoist data available"}

        # Most recent day is the current snapshot
        latest = sorted(items, key=lambda x: x.get("date", ""), reverse=True)[0]
        recent = sorted(items, key=lambda x: x.get("date", ""))

        recent_completions = [int(i.get("completed_count", 0)) for i in recent]
        avg_recent = round(sum(recent_completions) / len(recent_completions), 1) if recent_completions else 0

        active = int(latest.get("active_count", 0))
        overdue = int(latest.get("overdue_count", 0))
        due_today = int(latest.get("due_today_count", 0))
        priority = latest.get("priority_breakdown", {})
        by_project = latest.get("completions_by_project", {})

        # Cognitive load signal
        if overdue > 30:
            load_signal = "HIGH — significant overdue backlog, decision fatigue risk"
        elif overdue > 15:
            load_signal = "ELEVATED — moderate overdue backlog"
        elif overdue > 5:
            load_signal = "MODERATE — some overdue tasks"
        else:
            load_signal = "LOW — system clear"

        return {
            "snapshot_date": latest.get("date"),
            "active_tasks": active,
            "overdue_tasks": overdue,
            "due_today": due_today,
            "load_signal": load_signal,
            "priority_breakdown": {
                "p1_urgent": int(priority.get("p1_urgent", 0)),
                "p2_high": int(priority.get("p2_high", 0)),
                "p3_medium": int(priority.get("p3_medium", 0)),
                "p4_normal": int(priority.get("p4_normal", 0)),
            },
            "recent_completions": {
                "days": days,
                "average_per_day": avg_recent,
                "total": sum(recent_completions),
                "daily": [{"date": i.get("date"), "completed": int(i.get("completed_count", 0))} for i in recent],
            },
            "completions_by_project_yesterday": dict(sorted(by_project.items(), key=lambda x: x[1], reverse=True)),
        }
    except Exception as e:
        logger.error(f"get_task_load_summary error: {e}")
        return {"error": str(e)}


def get_project_activity(days: int = 30):
    """
    Completion breakdown by project over the last N days.
    Shows which life domains are getting attention and which are being neglected.
    Cross-reference with Life OS project structure (Health, Finance, Growth, Home, Relationships).
    """
    try:
        days = min(max(int(days), 7), 90)
        items = _get_todoist_range(days)
        if not items:
            return {"error": "No Todoist data available"}

        project_totals = defaultdict(int)

        for item in items:
            by_proj = item.get("completions_by_project", {})
            for proj, count in by_proj.items():
                project_totals[proj] += int(count)

        total_completions = sum(project_totals.values())
        ranked = sorted(project_totals.items(), key=lambda x: x[1], reverse=True)

        return {
            "days_analyzed": len(items),
            "total_completions": total_completions,
            "by_project": [
                {
                    "project": proj,
                    "completions": count,
                    "pct_of_total": round(count / total_completions * 100, 1) if total_completions else 0,
                    "avg_per_day": round(count / len(items), 1),
                }
                for proj, count in ranked
            ],
            "attention_gap": [proj for proj, count in ranked[-3:]] if len(ranked) > 3 else [],
        }
    except Exception as e:
        logger.error(f"get_project_activity error: {e}")
        return {"error": str(e)}


def get_decision_fatigue_signal(days: int = 30):
    """
    Correlates Todoist task load (active + overdue count) with Habitify T0 habit
    completion rate. Identifies the task-count threshold above which habit compliance drops.
    Roadmap item #34 — the knowing-doing gap made quantifiable.
    Requires both Todoist and Habitify data for the same date range.
    """
    try:
        days = min(max(int(days), 14), 60)
        todoist_items = _get_todoist_range(days)
        if not todoist_items:
            return {"error": "No Todoist data available"}

        # Build todoist load series by date
        todo_by_date = {}
        for item in todoist_items:
            date = item.get("date", "")
            if date:
                active = int(item.get("active_count", 0))
                overdue = int(item.get("overdue_count", 0))
                todo_by_date[date] = {
                    "load_score": active + (overdue * 2),  # overdue weighted 2x
                    "active": active,
                    "overdue": overdue,
                    "completed": int(item.get("completed_count", 0)),
                }

        # Pull habit scores for same range
        end = datetime.utcnow().date()
        start = end - timedelta(days=days - 1)
        habit_items = query_source("habit_scores", str(start), str(end))

        if not habit_items:
            return {
                "error": "No habit_scores data available — Habitify integration required for full analysis",
                "todoist_summary": {
                    "days_with_data": len(todo_by_date),
                    "avg_active_tasks": round(
                        sum(v["active"] for v in todo_by_date.values()) / len(todo_by_date), 1
                    ) if todo_by_date else 0,
                    "avg_overdue_tasks": round(
                        sum(v["overdue"] for v in todo_by_date.values()) / len(todo_by_date), 1
                    ) if todo_by_date else 0,
                }
            }

        habit_by_date = {}
        for item in habit_items:
            date = item.get("date", "")
            if date:
                t0_total = int(item.get("t0_total", 0))
                t0_completed = int(item.get("t0_completed", 0))
                if t0_total > 0:
                    habit_by_date[date] = round(t0_completed / t0_total * 100, 1)

        # Align dates
        shared_dates = sorted(set(todo_by_date.keys()) & set(habit_by_date.keys()))
        if len(shared_dates) < 7:
            return {"error": f"Insufficient overlapping data — only {len(shared_dates)} shared dates (need >=7)"}

        load_series = [todo_by_date[d]["load_score"] for d in shared_dates]
        habit_series = [habit_by_date[d] for d in shared_dates]
        completed_series = [todo_by_date[d]["completed"] for d in shared_dates]

        r_load_habits = pearson_r(load_series, habit_series)
        r_completed_habits = pearson_r(completed_series, habit_series)

        sorted_by_load = sorted(zip(load_series, habit_series), key=lambda x: x[0])
        median_load = sorted_by_load[len(sorted_by_load) // 2][0]
        low_load_habit_avg = round(
            sum(h for l, h in sorted_by_load if l <= median_load) /
            max(sum(1 for l, _ in sorted_by_load if l <= median_load), 1), 1
        )
        high_load_habit_avg = round(
            sum(h for l, h in sorted_by_load if l > median_load) /
            max(sum(1 for l, _ in sorted_by_load if l > median_load), 1), 1
        )

        return {
            "days_analyzed": len(shared_dates),
            "correlation": {
                "task_load_vs_habit_compliance": round(r_load_habits, 3),
                "tasks_completed_vs_habit_compliance": round(r_completed_habits, 3),
                "interpretation": (
                    "Strong negative: high task load reliably suppresses habits"
                    if r_load_habits < -0.4
                    else "Moderate negative: task load may affect habits"
                    if r_load_habits < -0.2
                    else "Weak relationship — task load not strongly affecting habits"
                ),
            },
            "load_threshold_analysis": {
                "median_load_score": median_load,
                "habit_compliance_low_load": f"{low_load_habit_avg}%",
                "habit_compliance_high_load": f"{high_load_habit_avg}%",
                "drop_when_overloaded": f"{round(low_load_habit_avg - high_load_habit_avg, 1)}pp",
            },
            "daily_detail": [
                {
                    "date": d,
                    "load_score": todo_by_date[d]["load_score"],
                    "active": todo_by_date[d]["active"],
                    "overdue": todo_by_date[d]["overdue"],
                    "habit_t0_pct": habit_by_date[d],
                }
                for d in shared_dates
            ],
        }
    except Exception as e:
        logger.error(f"get_decision_fatigue_signal error: {e}")
        return {"error": str(e)}


def get_todoist_day(date: str = None):
    """
    Full Todoist snapshot for a specific date (default: yesterday).
    Returns completed tasks list with project names, overdue/active counts,
    priority breakdown, and completions by project.
    """
    try:
        if not date:
            date = (datetime.utcnow().date() - timedelta(days=1)).strftime("%Y-%m-%d")

        items = query_source("todoist", date, date)
        if not items:
            return {"error": f"No Todoist data for {date}"}

        item = items[0]
        return {
            "date": date,
            "completed_count": int(item.get("completed_count", 0)),
            "active_count": int(item.get("active_count", 0)),
            "overdue_count": int(item.get("overdue_count", 0)),
            "due_today_count": int(item.get("due_today_count", 0)),
            "priority_breakdown": item.get("priority_breakdown", {}),
            "completions_by_project": item.get("completions_by_project", {}),
            "completed_tasks": item.get("completed_tasks", []),
            "tasks_due_today": item.get("tasks_due_today", []),
        }
    except Exception as e:
        logger.error(f"get_todoist_day error: {e}")
        return {"error": str(e)}


# ── Write tools ────────────────────────────────────────────────────────────────────

def get_todoist_projects():
    """
    List all Todoist projects with their IDs and names.
    Required before creating or moving tasks — use project_id from this response.
    """
    try:
        result = _todoist_request("GET", "/projects")
        projects = result.get("items", result.get("results", result)) if isinstance(result, dict) else result
        return {
            "projects": [
                {"id": str(p.get("id", "")), "name": p.get("name", ""), "color": p.get("color", "")}
                for p in projects
            ]
        }
    except Exception as e:
        logger.error(f"get_todoist_projects error: {e}")
        return {"error": str(e)}


def list_todoist_tasks(filter_str: str = None, limit: int = 200):
    """
    List active Todoist tasks. Use filter_str for Todoist filter syntax.
    Examples: 'overdue', 'today', 'p1', '#Health & Body', 'no date'.
    Returns task IDs, names, project names, due dates, and recurrence strings.
    Use this to inspect tasks before updating them.
    """
    try:
        tasks = _list_all_tasks(filter_str)
        tasks = tasks[:limit]
        return {
            "count": len(tasks),
            "tasks": [
                {
                    "id": str(t.get("id", "")),
                    "content": t.get("content", ""),
                    "project_id": str(t.get("project_id", "")),
                    "due": t.get("due"),
                    "priority": t.get("priority", 4),
                    "labels": t.get("labels", []),
                    "description": t.get("description", ""),
                }
                for t in tasks
            ],
        }
    except Exception as e:
        logger.error(f"list_todoist_tasks error: {e}")
        return {"error": str(e)}


def update_todoist_task(task_id: str, due_string: str = None, due_date: str = None,
                        content: str = None, description: str = None,
                        priority: int = None, project_id: str = None):
    """
    Update an existing Todoist task. Provide task_id plus any fields to change.
    due_string: Todoist natural language e.g. 'every! week', 'every! month', 'Mar 15 every! month'.
                Use 'every!' (with exclamation) to reschedule from completion date, NOT from original due date.
                This prevents pile-up when tasks are missed.
    due_date:   Hard date override YYYY-MM-DD (use for first-fire date when also setting recurrence via due_string).
    priority:   1=urgent, 2=high, 3=medium, 4=normal (Todoist uses 4=p1 internally but API accepts 1-4).
    Returns the updated task.
    """
    try:
        payload = {}
        if content is not None:
            payload["content"] = content
        if description is not None:
            payload["description"] = description
        if priority is not None:
            payload["priority"] = priority
        if project_id is not None:
            payload["project_id"] = project_id
        if due_string is not None:
            payload["due_string"] = due_string
        if due_date is not None:
            payload["due_date"] = due_date
        if not payload:
            return {"error": "No fields provided to update"}
        result = _todoist_request("POST", f"/tasks/{task_id}", payload)
        return {
            "updated": True,
            "task_id": task_id,
            "content": result.get("content", ""),
            "due": result.get("due"),
            "priority": result.get("priority"),
        }
    except Exception as e:
        logger.error(f"update_todoist_task error: {e}")
        return {"error": str(e)}


def create_todoist_task(content: str, project_id: str = None, due_string: str = None,
                        due_date: str = None, priority: int = 4, description: str = None,
                        labels: list = None):
    """
    Create a new Todoist task.
    content:    Task name/title.
    project_id: Get from get_todoist_projects(). Defaults to Inbox.
    due_string: e.g. 'every! Sunday', 'every! month', 'Mar 20'.
                Always use 'every!' for recurring tasks (completion-based scheduling).
    due_date:   YYYY-MM-DD for a specific one-time date.
    priority:   1=urgent, 2=high, 3=medium, 4=normal.
    """
    try:
        payload = {"content": content, "priority": priority}
        if project_id:
            payload["project_id"] = project_id
        if due_string:
            payload["due_string"] = due_string
        if due_date:
            payload["due_date"] = due_date
        if description:
            payload["description"] = description
        if labels:
            payload["labels"] = labels
        result = _todoist_request("POST", "/tasks", payload)
        return {
            "created": True,
            "task_id": str(result.get("id", "")),
            "content": result.get("content", ""),
            "due": result.get("due"),
            "project_id": str(result.get("project_id", "")),
        }
    except Exception as e:
        logger.error(f"create_todoist_task error: {e}")
        return {"error": str(e)}


def close_todoist_task(task_id: str):
    """
    Mark a Todoist task as complete (close/check off).
    For recurring tasks this advances to the next occurrence.
    For one-time tasks this removes it from active tasks.
    """
    try:
        _todoist_request("POST", f"/tasks/{task_id}/close")
        return {"closed": True, "task_id": task_id}
    except Exception as e:
        logger.error(f"close_todoist_task error: {e}")
        return {"error": str(e)}


def delete_todoist_task(task_id: str):
    """
    Permanently delete a Todoist task. Use with caution — cannot be undone.
    Prefer close_todoist_task for completing tasks.
    Only use delete for removing duplicate or stale tasks.
    """
    try:
        _todoist_request("DELETE", f"/tasks/{task_id}")
        return {"deleted": True, "task_id": task_id}
    except Exception as e:
        logger.error(f"delete_todoist_task error: {e}")
        return {"error": str(e)}
