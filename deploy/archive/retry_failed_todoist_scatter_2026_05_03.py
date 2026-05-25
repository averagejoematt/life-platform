#!/usr/bin/env python3
"""
retry_failed_todoist_scatter_2026_05_03.py
==========================================

Retries the 4 tasks that hit transient 503 errors during the original
scatter run. Each gets pushed to its originally-assigned spot in the
14-day spread, with exponential backoff on 503/429.

Usage:
    python3 deploy/retry_failed_todoist_scatter_2026_05_03.py            # dry-run
    python3 deploy/retry_failed_todoist_scatter_2026_05_03.py --apply
"""
import argparse
import json
import sys
import time
import urllib.request
import urllib.error

import boto3

REGION       = "us-west-2"
SECRET_NAME  = "life-platform/todoist"
TODOIST_BASE = "https://api.todoist.com/api/v1"

# 4 task IDs that failed during the original scatter, with the dates they
# should have landed on per the priority-ordered spread (extracted from the
# original run's plan preview).
RETRIES = [
    # task_id,                          target_date,   label
    ("67VJGrGR3G7WhM88",  "2026-05-13", "Bookmarks Review"),
    ("67VJHgJCGjPvMfv8",  "2026-05-13", "ProtonDrive Sync"),
    ("6XXQVRggfW46rp5r",  "2026-05-13", "Write down all memories"),
    ("6cR5XGPhCqfF6rRg",  "2026-05-14", "amazon recall"),
]


def get_token():
    client = boto3.client("secretsmanager", region_name=REGION)
    resp = client.get_secret_value(SecretId=SECRET_NAME)
    secret = json.loads(resp["SecretString"])
    return secret.get("todoist_api_token") or secret.get("todoist")


def update_task_with_retry(token, task_id, new_date, max_retries=4):
    """POST with exp backoff on 503/429."""
    url = f"{TODOIST_BASE}/tasks/{task_id}"
    payload = json.dumps({"due_date": new_date}).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    delay = 1.0
    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req) as resp:
                resp.read()
                return True, None
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:200]
            if e.code in (503, 429, 502, 504) and attempt < max_retries:
                print(f"    attempt {attempt} → {e.code}, retrying in {delay:.1f}s...")
                time.sleep(delay)
                delay *= 2
                continue
            return False, f"{e.code}: {body}"
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"
    return False, "max retries exhausted"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n=== Retry Failed Scatter — {mode} ===")
    print(f"  retrying {len(RETRIES)} tasks with exp backoff\n")

    if not args.apply:
        for tid, date, label in RETRIES:
            print(f"  WOULD update {tid}  → {date}  | {label}")
        print(f"\nDRY-RUN. Re-run with --apply to commit.")
        return 0

    token = get_token()
    success, failed = 0, []
    for tid, date, label in RETRIES:
        print(f"  Updating {tid} ({label}) → {date}")
        ok, err = update_task_with_retry(token, tid, date)
        if ok:
            success += 1
            print(f"    ✓")
        else:
            failed.append((tid, label, err))
            print(f"    ✗ {err}")
        time.sleep(0.3)  # polite pacing

    print()
    print("=" * 50)
    print(f"✅ {success}/{len(RETRIES)} succeeded")
    if failed:
        print(f"❌ {len(failed)} still failing:")
        for tid, label, err in failed:
            print(f"   {tid} ({label}): {err}")
        print("\nIf still failing: open Todoist app and reschedule manually.")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
