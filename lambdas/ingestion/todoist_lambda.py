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
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# OBS-1 logger
try:
    from common.platform_logger import get_logger

    logger = get_logger("todoist")
except ImportError:
    logger = logging.getLogger("todoist")
    logger.setLevel(logging.INFO)

try:
    from common.http_retry import urlopen_with_retry
except ImportError:  # pragma: no cover — layer-module fallback (local tooling)
    urlopen_with_retry = urllib.request.urlopen

# Framework (bundled in the lambdas/ tree)
from ingestion.ingestion_framework import IngestionConfig, run_ingestion

SECRET_NAME = os.environ.get("SECRET_NAME", "life-platform/ingestion-keys")
USER_ID = os.environ.get("USER_ID", "matthew")
BASE_URL = "https://api.todoist.com/api/v1"


# ── Todoist API helpers (unchanged from pre-migration) ─────────────────────────


def api_get(path, api_token, params=None):
    """GET on the shared retry policy (#501/X-11 — converged onto http_retry;
    3 attempts, 2s/8s backoff on 429/5xx and network errors; auth failures
    bubble immediately)."""
    url = BASE_URL + path
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {api_token}"})
    with urlopen_with_retry(req, timeout=30) as response:
        return json.loads(response.read())


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


def _paginate_tasks(api_token, path, base_params):
    """Fetch every page of a v1 tasks endpoint via cursor pagination.

    The v1 API caps a single page at 200; without following `next_cursor` you
    silently truncate at the first page (#478). Handles both the `results`
    (v1 task lists) and `items` (legacy) envelope shapes.
    """
    all_tasks, cursor = [], None
    while True:
        params = dict(base_params)
        params["limit"] = 200
        if cursor:
            params["cursor"] = cursor
        result = api_get(path, api_token, params)
        if isinstance(result, dict):
            items = result.get("results", result.get("items", []))
            next_cursor = result.get("next_cursor")
        else:
            items = result if isinstance(result, list) else []
            next_cursor = None
        if not isinstance(items, list):
            break
        all_tasks.extend(items)
        if not next_cursor or not items:
            break
        cursor = next_cursor
    return all_tasks


def get_active_tasks(api_token):
    """Snapshot of ALL current active tasks (paginated past the 200-page cap, #478)."""
    return _paginate_tasks(api_token, "/tasks", {})


def get_filtered_tasks(api_token, filter_str):
    """Fetch tasks matching a Todoist filter string (e.g. 'overdue', 'today').

    Uses the dedicated server-side filter endpoint GET /tasks/filter?query=...
    (#478). The plain /tasks endpoint on the v1 API silently IGNORES a `filter`
    param and returns the entire active list — which is why overdue/due-today
    counts were previously ≈ the whole task list.
    """
    try:
        return _paginate_tasks(api_token, "/tasks/filter", {"query": filter_str})
    except Exception as e:
        logger.warning("filter query %r failed: %s", filter_str, e)
        return []


# ── Priority (#4635) ───────────────────────────────────────────────────────────
# The Todoist API's priority runs 1 = normal … 4 = very urgent. The APP shows the
# reverse numbering: its "p1" (red flag) is API 4 and its "p4" (no flag) is API 1.
# Until #4635 this module labelled API 1 "p1_urgent" and API 4 "p4_normal", so every
# stored breakdown read as the reverse of the truth.
#
# Two fields now, with separate jobs:
#   priority_counts_vendor  the count per API integer, keyed by that integer exactly
#                           as the vendor sent it ("1".."4"). This is the stored fact.
#   priority_breakdown      DERIVED from it in the app's p1..p4 order, for readers
#                           that want the human labels. Never the other way round.
# A per-task `priority` is the vendor's integer, untouched. A task with no usable
# priority is counted under "unknown" and keeps no `priority` key — it is not
# defaulted to either end of the scale.
VENDOR_PRIORITIES = (1, 2, 3, 4)
PRIORITY_LABEL_BY_VENDOR = {4: "p1_urgent", 3: "p2_high", 2: "p3_medium", 1: "p4_normal"}


def vendor_priority(task):
    """The task's priority exactly as the API sent it, or None when it is not one of
    the four documented integers (`bool` is an `int` to Python — excluded)."""
    p = task.get("priority")
    if isinstance(p, bool) or p not in VENDOR_PRIORITIES:
        return None
    return int(p)


def priority_counts_vendor(tasks):
    """Count tasks per API priority integer. Keys are the vendor's integers as
    strings (DynamoDB map keys are strings); "unknown" appears only when non-zero."""
    counts = {str(p): 0 for p in VENDOR_PRIORITIES}
    unknown = 0
    for t in tasks:
        p = vendor_priority(t)
        if p is None:
            unknown += 1
        else:
            counts[str(p)] += 1
    if unknown:
        counts["unknown"] = unknown
    return counts


def priority_breakdown_from_vendor(counts):
    """The app-order p1..p4 view of a `priority_counts_vendor` map (API 4 → p1_urgent)."""
    return {label: int(counts.get(str(p), 0)) for p, label in PRIORITY_LABEL_BY_VENDOR.items()}


def _with_vendor_priority(record, task):
    p = vendor_priority(task)
    if p is not None:
        record["priority"] = p
    return record


def normalize_completed_task(task, project_map):
    """Normalize a completed task from the v1 API."""
    return _with_vendor_priority(
        {
            "task_id": str(task.get("id", "")),
            "task_name": task.get("content", ""),
            "project_id": str(task.get("project_id", "")),
            "project_name": project_map.get(str(task.get("project_id", "")), "Unknown"),
            "completed_at": task.get("completed_at", ""),
            "labels": task.get("labels", []),
        },
        task,
    )


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
    logger.info(
        "Day %s: completed=%d active=%d overdue=%d due_today=%d",
        date_str,
        len(completed_raw),
        len(active_tasks),
        len(overdue_tasks),
        len(due_today_tasks),
    )

    return {
        "date": date_str,
        "project_map": project_map,
        "completed_raw": completed_raw,
        "active_tasks": active_tasks,
        "overdue_tasks": overdue_tasks,
        "due_today_tasks": due_today_tasks,
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

    by_project: dict[str, int] = {}
    for task in normalized:
        proj = task["project_name"]
        by_project[proj] = by_project.get(proj, 0) + 1

    # #4635: the vendor's integers are the stored fact; the p1..p4 view derives from them.
    counts_vendor = priority_counts_vendor(active_tasks)
    priority_breakdown = priority_breakdown_from_vendor(counts_vendor)

    tasks_due_today = [
        _with_vendor_priority(
            {
                "task_id": str(t.get("id", "")),
                "task_name": t.get("content", ""),
                "project_id": str(t.get("project_id", "")),
                "project_name": project_map.get(str(t.get("project_id", "")), "Unknown"),
            },
            t,
        )
        for t in due_today_tasks[:50]
    ]

    return [
        {
            "source": "todoist",
            "date": date_str,
            "completed_count": len(normalized),
            "active_count": len(active_tasks),
            "overdue_count": len(overdue_tasks),
            "due_today_count": len(due_today_tasks),
            "priority_counts_vendor": counts_vendor,
            "priority_breakdown": priority_breakdown,
            "completed_tasks": normalized,
            "completions_by_project": by_project,
            "tasks_due_today": tasks_due_today,
        }
    ]


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
