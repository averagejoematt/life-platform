#!/usr/bin/env python3
"""
restart_character_rebuild.py — ADR-058: Rebuild character sheets from
EXPERIMENT_START_DATE → today. Reads genesis from lambdas/constants.py.

Spec §6:
  1. Tombstone S3 compute_state cache files older than genesis (if any)
  2. Invoke character-sheet-compute Lambda with force=true for each day
     from genesis → yesterday (today's compute fires on its own schedule)
  3. Report a spot-check of get_habits / get_vice_streaks / get_rewards
     (caller should manually verify via MCP that streaks reset to 0)

Date-agnostic: re-runnable. Idempotent — the Lambda's `force=true` ensures
every day is recomputed with current code + constants.

Usage:
    python3 deploy/restart_character_rebuild.py            # dry-run
    python3 deploy/restart_character_rebuild.py --apply    # invoke Lambda
"""
import argparse
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lambdas.constants import EXPERIMENT_START_DATE

REGION = "us-west-2"
S3_BUCKET = "matthew-life-platform"
CHARACTER_LAMBDA = "character-sheet-compute"
COMPUTE_STATE_PREFIX = "compute_state/character_sheet/"


def list_stale_state_files(s3, genesis: str) -> list[str]:
    """List S3 compute_state files modified before genesis."""
    stale = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=COMPUTE_STATE_PREFIX):
        for obj in page.get("Contents", []):
            # Heuristic: key contains date OR LastModified < genesis
            key = obj["Key"]
            last_mod = obj["LastModified"].date().isoformat()
            if last_mod < genesis:
                stale.append(key)
    return stale


def invoke_rebuild_for_day(lam, day_str: str, dry_run: bool):
    if dry_run:
        return {"statusCode": 0, "body": "dry-run, not invoked"}
    payload = json.dumps({"date": day_str, "force": True}).encode()
    resp = lam.invoke(
        FunctionName=CHARACTER_LAMBDA,
        InvocationType="RequestResponse",
        Payload=payload,
    )
    body = resp["Payload"].read().decode()
    return {"statusCode": resp.get("StatusCode"), "body": body[:200]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Invoke the Lambda for each day (default: dry-run)")
    parser.add_argument("--end-date", help="Override end date (YYYY-MM-DD). Default: yesterday.")
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] character rebuild starting. genesis={EXPERIMENT_START_DATE}")

    s3 = boto3.client("s3", region_name=REGION)
    lam = boto3.client("lambda", region_name=REGION)

    # ── Step 1: list stale S3 compute_state files ──
    try:
        stale = list_stale_state_files(s3, EXPERIMENT_START_DATE)
    except ClientError as e:
        print(f"  [WARN] S3 list failed (prefix may not exist): {e}")
        stale = []
    print(f"\n[1/3] Stale S3 compute_state files: {len(stale)}")
    for key in stale[:5]:
        print(f"  - {key}")
    if stale and not args.apply:
        print("  (would tombstone-overwrite these files via S3 PutObject)")
    elif stale and args.apply:
        for key in stale:
            s3.put_object(
                Bucket=S3_BUCKET,
                Key=key,
                Body=json.dumps(
                    {
                        "tombstone": True,
                        "tombstoned_at": datetime.now(timezone.utc).isoformat(),
                        "tombstoned_reason": f"experiment_restart_{EXPERIMENT_START_DATE}",
                    }
                ).encode(),
                ContentType="application/json",
            )
        print(f"  [APPLIED] tombstoned {len(stale)} stale state file(s)")

    # ── Step 2: invoke character-sheet-compute for each day ──
    end_date = args.end_date or (date.today() - timedelta(days=1)).isoformat()
    start = date.fromisoformat(EXPERIMENT_START_DATE)
    end = date.fromisoformat(end_date)
    days = []
    cursor = start
    while cursor <= end:
        days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    print(f"\n[2/3] Days to recompute: {len(days)} ({EXPERIMENT_START_DATE} → {end_date})")

    results = []
    for d in days:
        r = invoke_rebuild_for_day(lam, d, dry_run=not args.apply)
        results.append((d, r))
        if args.apply:
            print(f"  {d} → status={r['statusCode']}")
            time.sleep(0.5)  # gentle pace, avoid Lambda concurrency spikes
    if not args.apply:
        print(f"  (would invoke {len(days)} times)")

    # ── Step 3: spot-check verification hints ──
    print(f"\n[3/3] Verification hints (run via MCP after apply):")
    print(f"  - get_habits()              → expect streak=0 for all habits")
    print(f"  - get_vice_streaks()        → expect streak_days=0 for every vice")
    print(f"  - get_rewards()             → expect every milestone in active state, 0% progress")
    print(f"  - get_character(view=sheet) → expect days_active matches day_n({end_date})")

    # ── Report ──
    report_path = REPO_ROOT / "docs" / "restart" / "_character_rebuild_report.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"character rebuild report — mode={mode} — genesis={EXPERIMENT_START_DATE}",
        f"end_date={end_date}  days_recomputed={len(days) if args.apply else 0}",
        f"stale_state_files_tombstoned={len(stale) if args.apply else 0}",
        "",
    ]
    if args.apply:
        for d, r in results:
            lines.append(f"  {d:12s} status={r['statusCode']!s:5s} body={r['body'][:80]}")
    report_path.write_text("\n".join(lines))
    print(f"\nReport written to: {report_path.relative_to(REPO_ROOT)}")

    if not args.apply:
        print(f"\n(dry-run) — would recompute {len(days)} day(s). Pass --apply to commit.")


if __name__ == "__main__":
    main()
