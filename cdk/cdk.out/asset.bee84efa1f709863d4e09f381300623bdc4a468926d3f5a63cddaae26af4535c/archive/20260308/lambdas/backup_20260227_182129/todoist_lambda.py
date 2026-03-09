import json
import boto3
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from decimal import Decimal

SECRET_NAME = "life-platform/todoist"
S3_BUCKET = "matthew-life-platform"
DYNAMODB_TABLE = "life-platform"
REGION = "us-west-2"

secrets_client = boto3.client("secretsmanager", region_name=REGION)
s3_client = boto3.client("s3", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(DYNAMODB_TABLE)

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
    response = secrets_client.get_secret_value(SecretId=SECRET_NAME)
    return json.loads(response["SecretString"])


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
    api_token = secret["api_token"]

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

    s3_payload = {
        "date": date_str,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "completed_count": len(normalized),
        "active_count": active_count,
        "completed_tasks": normalized,
        "completions_by_project": by_project,
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
        "pk": "USER#matthew#SOURCE#todoist",
        "sk": f"DATE#{date_str}",
        "date": date_str,
        "source": "todoist",
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "completed_count": len(normalized),
        "active_count": active_count,
        "completed_tasks": normalized,
        "completions_by_project": by_project,
    }
    table.put_item(Item=floats_to_decimal(db_item))
    print(f"Saved to DynamoDB for {date_str}")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "completed_tasks": len(normalized),
            "active_tasks": active_count,
            "projects": len(project_map),
        })
    }
