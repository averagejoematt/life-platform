#!/usr/bin/env python3
"""
restart_rollback.py — Unwind the ADR-058 restart back to a previous genesis.

This is insurance. It does NOT delete data — it just removes the tombstone
flags and re-tags phase based on a different genesis date. Original content
was preserved by interpretation-B; this script just makes it visible again.

Use when:
  - The Monday auto-pivot misfired
  - You decide the new genesis is wrong and want to revert
  - You want to look at pre-genesis state during an investigation

Usage:
    # Roll back to a previous genesis date:
    python3 deploy/restart_rollback.py --to-genesis 2026-05-18 --dry-run
    python3 deploy/restart_rollback.py --to-genesis 2026-05-18 --apply

    # Full unwind: untombstone everything, drop all phase tags:
    python3 deploy/restart_rollback.py --full-unwind --dry-run
    python3 deploy/restart_rollback.py --full-unwind --apply

What it does:
  1. Removes `tombstone`, `tombstoned_at`, `tombstoned_reason`, `hidden` from
     items whose `tombstoned_reason` matches the CURRENT genesis (i.e., the
     records that THIS restart pipeline tombstoned).
  2. If --to-genesis is supplied: updates config + constants + DDB profile
     to that date, then re-runs phase-tag relative to it.
  3. If --full-unwind: removes ALL phase attributes too (every record becomes
     untagged, no filtering applied anywhere).

Run this BEFORE re-running restart_pipeline.py with a corrected genesis.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from lambdas.constants import EXPERIMENT_START_DATE

REGION = "us-west-2"
TABLE = "life-platform"
USER = "matthew"
TOMBSTONE_REASON_CURRENT = f"experiment_restart_{EXPERIMENT_START_DATE}"


def untombstone_matching(table, apply: bool, full: bool) -> int:
    """Remove tombstone flags from items.

    If full=True: untombstone all items regardless of tombstoned_reason.
    Else: only items whose tombstoned_reason == current TOMBSTONE_REASON_CURRENT.
    Returns count of items un-tombstoned.
    """
    count = 0
    scan_kwargs = {
        "FilterExpression": "attribute_exists(tombstone) AND tombstone = :t",
        "ExpressionAttributeValues": {":t": True},
    }
    if not full:
        scan_kwargs["FilterExpression"] += " AND tombstoned_reason = :r"
        scan_kwargs["ExpressionAttributeValues"][":r"] = TOMBSTONE_REASON_CURRENT
    while True:
        resp = table.scan(**scan_kwargs)
        for item in resp.get("Items", []):
            count += 1
            if apply:
                try:
                    table.update_item(
                        Key={"pk": item["pk"], "sk": item["sk"]},
                        UpdateExpression="REMOVE tombstone, tombstoned_at, tombstoned_reason, hidden",
                    )
                except ClientError as e:
                    print(f"  ERROR untombstoning {item['pk']}/{item['sk']}: {e}")
        if "LastEvaluatedKey" not in resp:
            break
        scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return count


def remove_all_phase_tags(table, apply: bool) -> int:
    """Strip the `phase` attribute from every item that has one."""
    count = 0
    scan_kwargs = {
        "FilterExpression": "attribute_exists(#p)",
        "ExpressionAttributeNames": {"#p": "phase"},
    }
    while True:
        resp = table.scan(**scan_kwargs)
        for item in resp.get("Items", []):
            count += 1
            if apply:
                try:
                    table.update_item(
                        Key={"pk": item["pk"], "sk": item["sk"]},
                        UpdateExpression="REMOVE #p",
                        ExpressionAttributeNames={"#p": "phase"},
                    )
                except ClientError as e:
                    print(f"  ERROR untagging {item['pk']}/{item['sk']}: {e}")
        if "LastEvaluatedKey" not in resp:
            break
        scan_kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to-genesis", help="Roll back to this date (re-runs the pipeline against it after un-tombstoning)")
    parser.add_argument("--full-unwind", action="store_true",
                        help="Remove ALL phase tags + tombstones (whether from this restart or not). Total reset.")
    parser.add_argument("--apply", action="store_true", help="Commit writes (default: dry-run)")
    args = parser.parse_args()

    if not args.to_genesis and not args.full_unwind:
        parser.error("Must pass either --to-genesis YYYY-MM-DD or --full-unwind")

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] rollback. current_genesis={EXPERIMENT_START_DATE}")
    print(f"  current tombstoned_reason='{TOMBSTONE_REASON_CURRENT}'")
    if args.full_unwind:
        print(f"  Mode: FULL UNWIND — removes ALL phase tags + ALL tombstones")
    else:
        print(f"  Mode: ROLL BACK to genesis={args.to_genesis}")

    ddb = boto3.resource("dynamodb", region_name=REGION)
    table = ddb.Table(TABLE)

    # ── 1. Untombstone ──
    print(f"\n[1] {'Untombstoning everything' if args.full_unwind else f'Untombstoning records from {TOMBSTONE_REASON_CURRENT}'}")
    untomb = untombstone_matching(table, args.apply, args.full_unwind)
    print(f"  {untomb} items {'untombstoned' if args.apply else 'would be untombstoned'}")

    # ── 2. Strip phase tags (only on full unwind) ──
    if args.full_unwind:
        print(f"\n[2] Removing ALL phase attributes")
        phases = remove_all_phase_tags(table, args.apply)
        print(f"  {phases} items {'untagged' if args.apply else 'would be untagged'}")
    else:
        print(f"\n[2] Skipping phase strip (rolling back to a different genesis, not full unwind)")

    # ── 3. If rolling back to a specific genesis, kick off the pipeline ──
    if args.to_genesis and args.apply:
        print(f"\n[3] Re-running pipeline against new genesis {args.to_genesis}")
        proc = subprocess.run(
            ["python3", "deploy/restart_pipeline.py",
             "--genesis", args.to_genesis, "--apply",
             "--override-weight-lbs", "297.24"],  # caller can re-run pipeline manually for the correct weight
            cwd=REPO_ROOT,
        )
        print(f"  pipeline exit={proc.returncode}")
        print(f"  NOTE: weight defaulted to 297.24 placeholder; re-run restart_pipeline with --override or wait for genesis-day Withings.")

    # Report
    report = REPO_ROOT / "docs" / "restart" / "_rollback_report.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        f"rollback report — mode={mode} — current_genesis={EXPERIMENT_START_DATE}\n"
        f"generated={datetime.now(timezone.utc).isoformat()}\n\n"
        f"to_genesis={args.to_genesis}\n"
        f"full_unwind={args.full_unwind}\n"
        f"untombstoned={untomb}\n"
    )
    print(f"\nReport: {report.relative_to(REPO_ROOT)}")
    if not args.apply:
        print(f"\n(dry-run) — pass --apply to commit.")


if __name__ == "__main__":
    main()
