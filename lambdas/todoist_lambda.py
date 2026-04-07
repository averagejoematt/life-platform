import json
import os
import logging
import boto3
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from decimal import Decimal

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger
    logger = get_logger("todoist")
except ImportError:
    logger = logging.getLogger("todoist")
    logger.setLevel(logging.INFO)

SECRET_NAME = os.environ.get("SECRET_NAME", "life-platform/ingestion-keys")
# ── Config (env vars with backwards-compatible defaults) ──
REGION         = os.environ.get("AWS_REGION", "us-west-2")
S3_BUCKET      = os.environ["S3_BUCKET"]
DYNAMODB_TABLE = os.environ.get("TABLE_NAME", "life-platform")
USER_ID        = os.environ.get("USER_ID", "matthew")

secrets_client = boto3.client("secretsmanager", region_name=REGION)
s3_client = boto3.client("s3", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(DYNAMODB_TABLE)

# COST-OPT-1: Cache secrets in warm Lambda containers (15-min TTL)
_secret_cache = {}


def _cached_secret(client, secret_id):
    import time as _t
    entry = _secret_cache.get(secret_id)
    if entry and _t.time() - entry[1] < 900:
        return entry[0]
    val = client.get_secret_value(SecretId=secret_id)["SecretString"]
    _secret_cache[secret_id] = (val, _t.time())
    return val

BASE_URL = "https://api.todoist.com/api/v1"


def floats_to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    elif isinstance(obj, dict):
        return {k: floats_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [floats_to_decimal(v) for v in obj]
    return obj


def get_secret():
    return json.loads(_cached_secret(secrets_client, SECRET_NAME))


def api_get(path, api_token, params=None):
    url = BASE_URL + path
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_token}"}
    )
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())


def get_projects(api_token):
    """Get all projects, return id->name map."""
    result = api_get("/projects", api_token)
    projects = result.get("items", result.get("results", result)) if isinstance(result, dict) else result
    return {p["id"]: p["name"] for p in projects}


def get_completed_tasks(api_token, since, until):
    """
    Fetch completed tasks using the new v1 endpoint.
    GET /api/v1/tasks/completed/by_completion_date
    Params: since (ISO datetime), until (ISO datetime), limit, cursor
    """
    all_tasks = []
    cursor = None

    while True:
        params = {
            "since": since,
            "until": until,
            "limit": 200,
        }
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
    """Snapshot of current active tasks count."""
    result = api_get("/tasks", api_token, {"limit": 200})
    return result.get("items", result.get("results", result)) if isinstance(result, dict) else result


def get_filtered_tasks(api_token, filter_str):
    """Fetch tasks matching a Todoist filter string (e.g. 'overdue', 'today')."""
    try:
        all_tasks = []
        cursor = None
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
        print(f"Warning: filter query '{filter_str}' failed: {e}")
        return []


def normalize_completed_task(task, project_map):
    """Normalize a completed task from the v1 API."""
    return {
        "task_id": str(task.get("id", "")),
        "task_name": task.get("content", ""),
        "project_id": str(task.get("project_id", "")),
        "project_name": project_map.get(str(task.get("project_id", "")), "Unknown"),
        "completed_at": task.get("completed_at", ""),
        "labels": task.get("labels", []),
        "priority": task.get("priority", 1),
    }


def lambda_handler(event, context):
    if event.get("healthcheck"):
        return {"statusCode": 200, "body": "ok"}
    if hasattr(logger, "set_date"): logger.set_date(datetime.now(timezone.utc).strftime("%Y-%m-%d"))  # OBS-1
    # Date range handling
    if "start_date" in event and "end_date" in event:
        start_date = datetime.strptime(event["start_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_date = datetime.strptime(event["end_date"], "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
    elif "date" in event:
        target = datetime.strptime(event["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        start_date = target
        end_date = target + timedelta(days=1)
    else:
        yesterday = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        start_date = yesterday
        end_date = yesterday + timedelta(days=1)

    date_str = start_date.strftime("%Y-%m-%d")
    print(f"Fetching Todoist data for {date_str}")

    secret = get_secret()
    api_token = secret.get("todoist_api_token") or secret.get("api_token")

    project_map = get_projects(api_token)
    print(f"Found {len(project_map)} projects")

    since = start_date.strftime("%Y-%m-%dT%H:%M:%SZ")
    until = end_date.strftime("%Y-%m-%dT%H:%M:%SZ")
    completed_raw = get_completed_tasks(api_token, since, until)
    print(f"Found {len(completed_raw)} completed tasks")

    active_tasks = get_active_tasks(api_token)
    active_count = len(active_tasks)
    print(f"Active tasks: {active_count}")

    normalized = [normalize_completed_task(t, project_map) for t in completed_raw]

    by_project = {}
    for task in normalized:
        proj = task["project_name"]
        by_project[proj] = by_project.get(proj, 0) + 1

    # Priority breakdown of active tasks
    priority_map = {1: "p1_urgent", 2: "p2_high", 3: "p3_medium", 4: "p4_normal"}
    priority_breakdown = {"p1_urgent": 0, "p2_high": 0, "p3_medium": 0, "p4_normal": 0}
    for t in active_tasks:
        p = t.get("priority", 4)
        key = priority_map.get(p, "p4_normal")
        priority_breakdown[key] += 1

    # Overdue and due-today counts via filter API
    overdue_tasks = get_filtered_tasks(api_token, "overdue")
    due_today_tasks = get_filtered_tasks(api_token, "today")
    overdue_count = len(overdue_tasks)
    due_today_count = len(due_today_tasks)
    print(f"Overdue: {overdue_count}, Due today: {due_today_count}")

    # Lightweight due-today task list for Daily Brief context
    tasks_due_today = [
        {
            "task_id": str(t.get("id", "")),
            "task_name": t.get("content", ""),
            "project_id": str(t.get("project_id", "")),
            "project_name": project_map.get(str(t.get("project_id", "")), "Unknown"),
            "priority": t.get("priority", 4),
        }
        for t in due_today_tasks[:50]  # cap at 50
    ]

    s3_payload = {
        "date": date_str,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "completed_count": len(normalized),
        "active_count": active_count,
        "overdue_count": overdue_count,
        "due_today_count": due_today_count,
        "priority_breakdown": priority_breakdown,
        "completed_tasks": normalized,
        "completions_by_project": by_project,
        "tasks_due_today": tasks_due_today,
    }

    key = f"raw/todoist/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=json.dumps(s3_payload, default=str),
        ContentType="application/json"
    )
    print(f"Saved to S3: {key}")

    db_item = {
        "pk": f"USER#{USER_ID}#SOURCE#todoist",
        "sk": f"DATE#{date_str}",
        "date": date_str,
        "source": "todoist",
        "schema_version": 1,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "completed_count": len(normalized),
        "active_count": active_count,
        "overdue_count": overdue_count,
        "due_today_count": due_today_count,
        "priority_breakdown": priority_breakdown,
        "completed_tasks": normalized,
        "completions_by_project": by_project,
        "tasks_due_today": tasks_due_today,
    }
    # DATA-2: Validate before write
    try:
        from ingestion_validator import validate_item as _validate_item
        _vr = _validate_item("todoist", floats_to_decimal(db_item), date_str)
        if _vr.should_skip_ddb:
            logger.error(f"[DATA-2] CRITICAL: Skipping todoist DDB write for {date_str}: {_vr.errors}")
            _vr.archive_to_s3(s3_client, bucket=S3_BUCKET, item=db_item)
        else:
            if _vr.warnings:
                logger.warning(f"[DATA-2] Validation warnings for todoist/{date_str}: {_vr.warnings}")
            table.put_item(Item=floats_to_decimal(db_item))
            print(f"Saved to DynamoDB for {date_str}")
    except ImportError:
        table.put_item(Item=floats_to_decimal(db_item))
        print(f"Saved to DynamoDB for {date_str}")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "completed_tasks": len(normalized),
            "active_tasks": active_count,
            "overdue_tasks": overdue_count,
            "due_today": due_today_count,
            "projects": len(project_map),
        })
    }
