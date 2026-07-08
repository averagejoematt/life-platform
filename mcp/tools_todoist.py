"""
Todoist tools: task completion trends, load analysis, project activity, decision fatigue signal.
Write tools: create_todoist_task, update_todoist_task, close_todoist_task, get_todoist_projects.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import boto3

from mcp.config import logger
from mcp.core import query_source

# ── Todoist API client ────────────────────────────────────────────────────────

_TODOIST_BASE = "https://api.todoist.com/api/v1"
_SECRET_NAME = os.environ.get("SECRET_NAME", "life-platform/todoist")
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


# ── Helpers ──────────────────────────────────────────────────────────────────


def _get_todoist_range(days=30):
    """Fetch todoist records for the last N days. Returns list of day items."""
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days - 1)
    return query_source("todoist", str(start), str(end))


def _rolling_avg(series, window=7):
    """Compute rolling average for a list of (date, value) tuples."""
    result = []
    values = [v for _, v in series]
    for i, (date, val) in enumerate(series):
        window_vals = values[max(0, i - window + 1) : i + 1]
        result.append((date, round(sum(window_vals) / len(window_vals), 1)))
    return result


# ── Tools ─────────────────────────────────────────────────────────────────────


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


def get_todoist_day(date: str = None):
    """
    Full Todoist snapshot for a specific date (default: yesterday).
    Returns completed tasks list with project names, overdue/active counts,
    priority breakdown, and completions by project.
    """
    try:
        if not date:
            date = (datetime.now(timezone.utc).date() - timedelta(days=1)).strftime("%Y-%m-%d")

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


def update_todoist_task(
    task_id: str,
    due_string: str = None,
    due_date: str = None,
    content: str = None,
    description: str = None,
    priority: int = None,
    project_id: str = None,
):
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


def create_todoist_task(
    content: str,
    project_id: str = None,
    due_string: str = None,
    due_date: str = None,
    priority: int = 4,
    description: str = None,
    labels: list = None,
):
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


def tool_get_todoist_snapshot(args):
    """Unified Todoist snapshot dispatcher.
    Adapts args dict to underlying positional-arg signatures.
    """
    VALID_VIEWS = {
        "today": lambda a: get_todoist_day(a.get("date")),
        "load": lambda a: get_task_load_summary(int(a.get("days", 7))),
    }
    view = (args.get("view") or "load").lower().strip()
    if view not in VALID_VIEWS:
        return {
            "error": f"Unknown view '{view}'.",
            "valid_views": list(VALID_VIEWS.keys()),
            "hint": "'load' for current task load snapshot + cognitive load signal, 'today' for full Todoist day summary.",
        }
    return VALID_VIEWS[view](args)
