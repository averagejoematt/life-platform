"""
todoist_lambda.py — Todoist ingestion via SIMP-2 framework (P4.1, 2026-05-17).

Migrated from the standalone pattern to lambdas/ingestion_framework.py. The
shape of the DDB record + S3 archive is unchanged — daily-brief and other
consumers see no difference.

Framework provides (for free):
  - Auth-failure circuit breaker (24h marker on 401/403; auto-clears on success)
  - Gap-aware backfill (env LOOKBACK_DAYS=7 default)
  - Date-override event payload ({"date_override": "YYYY-MM-DD"} or "today")
  - DATA-2 validation + DDB write
  - S3 raw archival
  - Decimal conversion
  - Structured logging via platform_logger

Source-specific logic stays here:
  - api_get retry helper
  - get_projects / get_completed_tasks / get_active_tasks / get_filtered_tasks
  - normalize_completed_task

P4.1 proof-of-concept Lambda. If this works for 1-2 weeks without issues, the
other 12 ingestion Lambdas can follow the same pattern.
"""

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# OBS-1 logger
try:
    from platform_logger import get_logger
    logger = get_logger("todoist")
except ImportError:
    logger = logging.getLogger("todoist")
    logger.setLevel(logging.INFO)

# Framework (shipped in the shared layer)
from ingestion_framework import IngestionConfig, run_ingestion

SECRET_NAME = os.environ.get("SECRET_NAME", "life-platform/ingestion-keys")
USER_ID     = os.environ.get("USER_ID", "matthew")
BASE_URL    = "https://api.todoist.com/api/v1"


# ── Todoist API helpers (unchanged from pre-migration) ─────────────────────────

def api_get(path, api_token, params=None):
    """GET with retry on transient Todoist outages (429/500/502/503/504).
    3 attempts with 2s/8s backoff.
    """
    url = BASE_URL + path
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_token}"})
    backoff = [2, 8]
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                logger.warning("Todoist HTTP %d on %s — retry %d/2 in %ds",
                               e.code, path, attempt + 1, backoff[attempt])
                time.sleep(backoff[attempt])
                continue
            raise


def get_projects(api_token):
    """Get all projects, return id→name map."""
    result = api_get("/projects", api_token)
    projects = result.get("items", result.get("results", result)) if isinstance(result, dict) else result
    return {p["id"]: p["name"] for p in projects}


def get_completed_tasks(api_token, since, until):
    """Fetch completed tasks via GET /tasks/completed/by_completion_date with cursor pagination."""
    all_tasks, cursor = [], None
    while True:
        params = {"since": since, "until": until, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        result = api_get("/tasks/completed/by_completion_date", api_token, params)
        tasks = result.get("items", [])
        all_tasks.extend(tasks)
        next_cursor = result.get("next_cursor") or result.get("cursor")
        if not next_cursor or not tasks:
            break
        cursor = next_cursor
    return all_tasks


def get_active_tasks(api_token):
    """Snapshot of current active tasks."""
    result = api_get("/tasks", api_token, {"limit": 200})
    return result.get("items", result.get("results", result)) if isinstance(result, dict) else result


def get_filtered_tasks(api_token, filter_str):
    """Fetch tasks matching a Todoist filter string (e.g. 'overdue', 'today')."""
    try:
        all_tasks, cursor = [], None
        while True:
            params = {"filter": filter_str, "limit": 200}
            if cursor:
                params["cursor"] = cursor
            result = api_get("/tasks", api_token, params)
            items = result.get("items", result.get("results", result)) if isinstance(result, dict) else result
            if not isinstance(items, list):
                break
            all_tasks.extend(items)
            next_cursor = result.get("next_cursor") if isinstance(result, dict) else None
            if not next_cursor or not items:
                break
            cursor = next_cursor
        return all_tasks
    except Exception as e:
        logger.warning("filter query %r failed: %s", filter_str, e)
        return []


def normalize_completed_task(task, project_map):
    """Normalize a completed task from the v1 API."""
    return {
        "task_id":      str(task.get("id", "")),
        "task_name":    task.get("content", ""),
        "project_id":   str(task.get("project_id", "")),
        "project_name": project_map.get(str(task.get("project_id", "")), "Unknown"),
        "completed_at": task.get("completed_at", ""),
        "labels":       task.get("labels", []),
        "priority":     task.get("priority", 1),
    }


# ── SIMP-2 framework callbacks ─────────────────────────────────────────────────

def authenticate(secret_data: dict) -> dict:
    """Extract the API token from the secret bundle. SIMP-2 will pass this back
    to fetch_day as `credentials`. No OAuth refresh — Todoist uses a long-lived
    personal token; staleness alerts come from the freshness checker (P2.6)."""
    token = secret_data.get("todoist_api_token") or secret_data.get("api_token")
    if not token:
        raise RuntimeError("Todoist secret missing 'todoist_api_token' / 'api_token' field")
    return {"api_token": token}


def fetch_day(credentials: dict, date_str: str) -> dict | None:
    """Fetch one day of Todoist data. Returns raw aggregate dict that transform_fn
    will convert into a DDB record. Returns None on error (framework will retry next run)."""
    api_token = credentials["api_token"]

    # ISO datetime window for "this date in UTC" → API's date-aware completed query
    start_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_dt = start_dt.replace(hour=23, minute=59, second=59)
    since = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    until = end_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    project_map = get_projects(api_token)
    logger.info("Found %d projects", len(project_map))

    completed_raw = get_completed_tasks(api_token, since, until)
    active_tasks = get_active_tasks(api_token)
    overdue_tasks = get_filtered_tasks(api_token, "overdue")
    due_today_tasks = get_filtered_tasks(api_token, "today")
    logger.info("Day %s: completed=%d active=%d overdue=%d due_today=%d",
                date_str, len(completed_raw), len(active_tasks),
                len(overdue_tasks), len(due_today_tasks))

    return {
        "date":              date_str,
        "project_map":       project_map,
        "completed_raw":     completed_raw,
        "active_tasks":      active_tasks,
        "overdue_tasks":     overdue_tasks,
        "due_today_tasks":   due_today_tasks,
    }


def transform(raw: dict, date_str: str) -> list[dict]:
    """Convert raw Todoist response to a single DDB record dict.

    Returned dict must include a 'source' key (SIMP-2 builds the pk from it as
    USER#{user_id}#SOURCE#{source}). Optionally include 'sk_suffix' for
    sub-records — omitted here since Todoist writes one record per date.
    """
    if not raw:
        return []

    project_map = raw["project_map"]
    completed_raw = raw["completed_raw"]
    active_tasks = raw["active_tasks"]
    overdue_tasks = raw["overdue_tasks"]
    due_today_tasks = raw["due_today_tasks"]

    normalized = [normalize_completed_task(t, project_map) for t in completed_raw]

    by_project = {}
    for task in normalized:
        proj = task["project_name"]
        by_project[proj] = by_project.get(proj, 0) + 1

    priority_map = {1: "p1_urgent", 2: "p2_high", 3: "p3_medium", 4: "p4_normal"}
    priority_breakdown = {"p1_urgent": 0, "p2_high": 0, "p3_medium": 0, "p4_normal": 0}
    for t in active_tasks:
        key = priority_map.get(t.get("priority", 4), "p4_normal")
        priority_breakdown[key] += 1

    tasks_due_today = [
        {
            "task_id":     str(t.get("id", "")),
            "task_name":   t.get("content", ""),
            "project_id":  str(t.get("project_id", "")),
            "project_name": project_map.get(str(t.get("project_id", "")), "Unknown"),
            "priority":    t.get("priority", 4),
        }
        for t in due_today_tasks[:50]
    ]

    return [{
        "source":                "todoist",
        "date":                  date_str,
        "completed_count":       len(normalized),
        "active_count":          len(active_tasks),
        "overdue_count":         len(overdue_tasks),
        "due_today_count":       len(due_today_tasks),
        "priority_breakdown":    priority_breakdown,
        "completed_tasks":       normalized,
        "completions_by_project": by_project,
        "tasks_due_today":       tasks_due_today,
    }]


# ── Framework config (one place, declarative) ──────────────────────────────────

_config = IngestionConfig(
    source_name="todoist",
    secret_id=SECRET_NAME,
    s3_archive_prefix="raw/todoist",
    schema_version=1,
    enable_gap_detection=True,  # backfill yesterday + 7 day lookback
    lookback_days=7,
    enable_item_size_guard=True,
)


def lambda_handler(event: dict, context) -> dict:
    """SIMP-2 entry point. Accepts:
      {}                                 — gap-aware backfill (default cron behavior)
      {"date_override": "today"}         — force today's data only
      {"date_override": "2026-05-15"}    — single explicit date
      {"healthcheck": true}              — boot check, returns 200/"ok"
    """
    try:
        if event.get("healthcheck"):
            return {"statusCode": 200, "body": "ok"}
        return run_ingestion(_config, authenticate, fetch_day, transform, event, context)
    except Exception as e:
        logger.error("todoist ingestion failed: %s", e, exc_info=True)
        raise
