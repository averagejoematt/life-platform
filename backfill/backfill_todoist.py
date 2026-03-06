#!/usr/bin/env python3
"""
Todoist historical backfill - Todoist API v1.
Fetches all completed tasks since account start in 30-day batches.
"""

import json
import boto3
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import time

SECRET_NAME = "life-platform/todoist"
S3_BUCKET = "matthew-life-platform"
DYNAMODB_TABLE = "life-platform"
REGION = "us-west-2"

# Adjust to whenever you first started using Todoist
START_DATE = datetime(2018, 1, 1, tzinfo=timezone.utc)
BATCH_DAYS = 30

BASE_URL = "https://api.todoist.com/api/v1"

secrets_client = boto3.client("secretsmanager", region_name=REGION)
s3_client = boto3.client("s3", region_name=REGION)
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(DYNAMODB_TABLE)


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
    result = api_get("/projects", api_token)
    projects = result.get("results", result) if isinstance(result, dict) else result
    return {p["id"]: p["name"] for p in projects}


def get_completed_tasks(api_token, since, until):
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
        time.sleep(0.2)

    return all_tasks


def normalize_completed_task(task, project_map):
    return {
        "task_id": str(task.get("id", "")),
        "task_name": task.get("content", ""),
        "project_id": str(task.get("project_id", "")),
        "project_name": project_map.get(str(task.get("project_id", "")), "Unknown"),
        "completed_at": task.get("completed_at", ""),
        "labels": task.get("labels", []),
        "priority": task.get("priority", 1),
    }


def save_day(date_str, normalized):
    by_project = {}
    for task in normalized:
        proj = task["project_name"]
        by_project[proj] = by_project.get(proj, 0) + 1

    key = f"raw/todoist/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"
    payload = {
        "date": date_str,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "completed_count": len(normalized),
        "completed_tasks": normalized,
        "completions_by_project": by_project,
    }
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=json.dumps(payload, default=str),
        ContentType="application/json"
    )

    item = {
        "pk": "USER#matthew#SOURCE#todoist",
        "sk": f"DATE#{date_str}",
        "date": date_str,
        "source": "todoist",
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "completed_count": len(normalized),
        "completed_tasks": normalized,
        "completions_by_project": by_project,
    }
    table.put_item(Item=floats_to_decimal(item))


def main():
    print(f"Starting Todoist backfill from {START_DATE.date()} to today")
    secret = get_secret()
    api_token = secret["api_token"]

    project_map = get_projects(api_token)
    print(f"Found {len(project_map)} projects: {list(project_map.values())}")

    current = START_DATE
    end = datetime.now(timezone.utc)
    total_tasks = 0
    total_days = 0
    batch_num = 0

    while current < end:
        batch_end = min(current + timedelta(days=BATCH_DAYS), end)
        batch_num += 1

        since = current.strftime("%Y-%m-%dT%H:%M:%SZ")
        until = batch_end.strftime("%Y-%m-%dT%H:%M:%SZ")

        print(f"Batch {batch_num}: {current.date()} → {batch_end.date()}", end="", flush=True)

        tasks = get_completed_tasks(api_token, since, until)

        if tasks:
            by_date = {}
            for task in tasks:
                completed_at = task.get("completed_at", "")[:10]
                if completed_at:
                    if completed_at not in by_date:
                        by_date[completed_at] = []
                    by_date[completed_at].append(task)

            for date_str, day_tasks in sorted(by_date.items()):
                normalized = [normalize_completed_task(t, project_map) for t in day_tasks]
                save_day(date_str, normalized)
                total_tasks += len(day_tasks)
                total_days += 1

            print(f" → {len(tasks)} tasks across {len(by_date)} days")
        else:
            print(f" → No completed tasks")

        current = batch_end
        time.sleep(0.5)

    print(f"\n=== Backfill complete ===")
    print(f"Total completed tasks: {total_tasks}")
    print(f"Total active days: {total_days}")
    print(f"Batches processed: {batch_num}")


if __name__ == "__main__":
    main()
