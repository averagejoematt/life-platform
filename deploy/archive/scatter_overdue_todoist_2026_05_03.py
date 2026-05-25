#!/usr/bin/env python3
"""
scatter_overdue_todoist_2026_05_03.py
=====================================

Spreads the 278 overdue Todoist tasks evenly across the next 14 days, so
they reappear gradually instead of hammering Monday morning's "today" view.

PER MATTHEW (2026-05-03):
   "I like having them there as a reminder, but for me it is not adding
    to stress. ... I think we can either push, scatter."

STRATEGY
--------
- One-time tasks with due dates in the past → spread evenly across days
  +1 through +14 from today, ordered by current priority (P1s land on
  the earliest days, P4s on the latest).
- RECURRING TASKS ARE SKIPPED. Todoist's recurrence engine will self-heal
  on the next natural cycle; rescheduling them by hand can break the
  cadence (e.g. "every Monday" tasks shouldn't be moved to a Wednesday).
- Tasks with no due date are also skipped — they're not "overdue."

USAGE
-----
    # 1. Dry-run first:
    python3 deploy/scatter_overdue_todoist_2026_05_03.py

    # 2. Apply for real:
    python3 deploy/scatter_overdue_todoist_2026_05_03.py --apply

REQUIREMENTS
------------
- AWS credentials (reads life-platform/todoist secret for API token)
- Region us-west-2
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone

import boto3

REGION       = "us-west-2"
SECRET_NAME  = "life-platform/todoist"
TODOIST_BASE = "https://api.todoist.com/api/v1"
SPREAD_DAYS  = 14
RATE_DELAY_S = 0.15  # ~6 req/sec — Todoist allows 450/min

PRIORITY_ORDER = [4, 3, 2, 1]  # Todoist priority: 4=P1 (urgent) ... 1=P4 (normal)
# Note: priority=4 in API = "Priority 1" (highest) in UI. Stay with API numbering.


def get_todoist_token():
    client = boto3.client("secretsmanager", region_name=REGION)
    resp = client.get_secret_value(SecretId=SECRET_NAME)
    secret = json.loads(resp["SecretString"])
    return secret.get("todoist_api_token") or secret.get("todoist")


def todoist_request(token, method, path, payload=None):
    url = TODOIST_BASE + path
    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Todoist API {method} {path} → {e.code}: {body}")


def list_all_overdue(token):
    """Pull all overdue tasks (Todoist filter 'overdue')."""
    all_tasks = []
    cursor = None
    while True:
        params = {"limit": 200, "filter": "overdue"}
        if cursor:
            params["cursor"] = cursor
        path = "/tasks?" + urllib.parse.urlencode(params)
        result = todoist_request(token, "GET", path)
        items = result.get("items") or result.get("results") or result
        if not isinstance(items, list):
            break
        all_tasks.extend(items)
        cursor = result.get("next_cursor") if isinstance(result, dict) else None
        if not cursor or not items:
            break
    return all_tasks


def is_recurring(task):
    due = task.get("due") or {}
    return bool(due.get("is_recurring"))


def has_due_date(task):
    due = task.get("due") or {}
    return bool(due.get("date") or due.get("string"))


def task_priority(task):
    """Returns 1-4 (1=normal, 4=urgent). Fallback to 1 if missing."""
    return int(task.get("priority", 1))


def update_task_due(token, task_id, new_date):
    """Set due_date on a task. Format: YYYY-MM-DD."""
    payload = {"due_date": new_date}
    return todoist_request(token, "POST", f"/tasks/{task_id}", payload)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="Actually update tasks (default is dry-run)")
    parser.add_argument("--spread-days", type=int, default=SPREAD_DAYS,
                        help=f"Days to spread tasks across (default {SPREAD_DAYS})")
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    today = datetime.now(timezone.utc).date()
    print(f"\n=== Todoist Overdue Scatter — {mode} ===")
    print(f"  today:        {today}")
    print(f"  spread_days:  {args.spread_days}")
    print()

    print("Fetching token from Secrets Manager...")
    token = get_todoist_token()
    if not token:
        print("ERROR: no Todoist token found in secret.")
        return 1

    print("Listing overdue tasks (paginated)...")
    overdue = list_all_overdue(token)
    print(f"  → {len(overdue)} overdue tasks total")
    print()

    # Bucket
    recurring = [t for t in overdue if is_recurring(t)]
    no_due    = [t for t in overdue if not has_due_date(t)]
    rescheduable = [t for t in overdue
                    if not is_recurring(t) and has_due_date(t)]

    print(f"  Skipping: {len(recurring)} recurring  + {len(no_due)} no-due")
    print(f"  Will reschedule: {len(rescheduable)} one-time tasks")
    print()

    if not rescheduable:
        print("Nothing to scatter. Done.")
        return 0

    # Sort by priority desc (urgent first), then by current due date asc.
    rescheduable.sort(
        key=lambda t: (
            -task_priority(t),
            (t.get("due") or {}).get("date", "9999-12-31"),
        )
    )

    # Assign each task to a target day evenly: tasks_per_day = ceil(N / spread)
    n = len(rescheduable)
    spread = args.spread_days
    per_day = (n + spread - 1) // spread

    print(f"  → ~{per_day} tasks per day across {spread} days "
          f"(highest priority lands on day +1)")
    print()

    # Build assignment plan
    plan = []
    for idx, task in enumerate(rescheduable):
        day_offset = (idx // per_day) + 1   # +1 to +spread
        new_date = (today + timedelta(days=day_offset)).strftime("%Y-%m-%d")
        plan.append((task, new_date))

    # Print first 5 + last 5 of plan as sanity check
    print("  Plan preview (first 5):")
    for task, new_date in plan[:5]:
        cur_due = (task.get("due") or {}).get("date") or "?"
        print(f"    P{task_priority(task)}  {task['id']}  {cur_due} → {new_date}  | "
              f"{task.get('content','')[:60]}")
    if len(plan) > 10:
        print(f"    ... ({len(plan) - 10} skipped)")
        print("  Plan preview (last 5):")
        for task, new_date in plan[-5:]:
            cur_due = (task.get("due") or {}).get("date") or "?"
            print(f"    P{task_priority(task)}  {task['id']}  {cur_due} → {new_date}  | "
                  f"{task.get('content','')[:60]}")
    print()

    if not args.apply:
        print(f"DRY-RUN: would update {len(plan)} tasks. Re-run with --apply to commit.")
        return 0

    # Apply
    success = 0
    failed = []
    print(f"Applying {len(plan)} updates (≈{int(len(plan)*RATE_DELAY_S/60)+1} minutes)...")
    for i, (task, new_date) in enumerate(plan, 1):
        try:
            update_task_due(token, task["id"], new_date)
            success += 1
            if i % 25 == 0:
                print(f"  ...{i}/{len(plan)}")
            time.sleep(RATE_DELAY_S)
        except Exception as e:
            failed.append((task["id"], task.get("content", "")[:60], str(e)))
            time.sleep(RATE_DELAY_S * 2)  # back off on error

    print()
    print("=" * 60)
    print(f"✅ Updated {success}/{len(plan)} tasks.")
    if failed:
        print(f"❌ {len(failed)} failed:")
        for tid, content, err in failed[:10]:
            print(f"   {tid} ({content})  {err[:80]}")
        if len(failed) > 10:
            print(f"   ... +{len(failed)-10} more")
    print()
    print(f"Skipped intentionally:")
    print(f"   • {len(recurring)} recurring (Todoist will heal naturally)")
    print(f"   • {len(no_due)} no-due (not overdue per definition)")
    print()


if __name__ == "__main__":
    sys.exit(main() or 0)
