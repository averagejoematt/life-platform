#!/usr/bin/env python3
"""
tombstone_legacy_hevy_aggregates.py — One-shot WS-3 cleanup.

The 2026-02-22 one-off Hevy ingestion wrote daily-aggregate records under
USER#matthew#SOURCE#hevy with SK=DATE#yyyy-mm-dd (no #WORKOUT# suffix). The
2026-05-25 events-feed backfill subsequently wrote canonical per-workout
records (SK=DATE#yyyy-mm-dd#WORKOUT#<hevy_id>) for the same workouts.

The two record sets contain the SAME underlying workouts; the old aggregates
are now redundant. The phase=pilot tag hides them from default reads anyway,
but they:
  - confuse anyone doing a raw partition scan
  - inflate the partition by ~282 stale items
  - make the dedupe story harder to reason about

Action: tombstone each old aggregate (mark tombstone=true, write a
tombstoned_reason). Do NOT delete — keep the audit trail.

Usage:
  python3 deploy/tombstone_legacy_hevy_aggregates.py             # dry-run
  python3 deploy/tombstone_legacy_hevy_aggregates.py --apply     # commit
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

REGION = "us-west-2"
TABLE = "life-platform"
PK = "USER#matthew#SOURCE#hevy"
TOMBSTONE_REASON = "legacy_daily_aggregate_superseded_by_per_workout"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Commit the tombstones. Default = dry-run.")
    args = ap.parse_args()
    dry = not args.apply

    ddb = boto3.resource("dynamodb", region_name=REGION)
    table = ddb.Table(TABLE)

    legacy_keys: list[dict] = []
    last_eval = None
    scanned = 0
    while True:
        kwargs = {
            "KeyConditionExpression": Key("pk").eq(PK) & Key("sk").begins_with("DATE#"),
            # Match aggregates: SK is exactly "DATE#yyyy-mm-dd" with no further suffix.
            # The per-workout records have "DATE#yyyy-mm-dd#WORKOUT#..." which contains "#WORKOUT#".
            "FilterExpression": "attribute_not_exists(source_workout_id) "
                                "AND attribute_not_exists(tombstone)",
            "ProjectionExpression": "pk, sk, #d, workouts_count, total_sets",
            "ExpressionAttributeNames": {"#d": "date"},
        }
        if last_eval:
            kwargs["ExclusiveStartKey"] = last_eval
        resp = table.query(**kwargs)
        items = resp.get("Items") or []
        for it in items:
            sk = it["sk"]
            # Sanity guard: be paranoid — only match legacy aggregate sks.
            if "#WORKOUT#" in sk:
                continue
            legacy_keys.append({
                "pk": it["pk"], "sk": sk,
                "date": it.get("date"), "workouts_count": it.get("workouts_count"),
                "total_sets": it.get("total_sets"),
            })
        scanned += len(items)
        last_eval = resp.get("LastEvaluatedKey")
        if not last_eval:
            break

    print(f"scanned partition: {scanned} items reviewed, {len(legacy_keys)} legacy aggregates targeted")
    if not legacy_keys:
        print("nothing to do")
        return 0

    if dry:
        for k in legacy_keys[:10]:
            print(f"  [DRY] would tombstone sk={k['sk']} date={k['date']} "
                  f"workouts_count={k['workouts_count']} total_sets={k['total_sets']}")
        if len(legacy_keys) > 10:
            print(f"  ... + {len(legacy_keys) - 10} more")
        print(f"(dry-run) would update {len(legacy_keys)} items. Pass --apply to commit.")
        return 0

    now_iso = datetime.now(timezone.utc).isoformat()
    updated = 0
    for k in legacy_keys:
        table.update_item(
            Key={"pk": k["pk"], "sk": k["sk"]},
            UpdateExpression=(
                "SET tombstone = :t, tombstoned_at = :now, "
                "tombstoned_reason = :r"
            ),
            ExpressionAttributeValues={
                ":t":   True,
                ":now": now_iso,
                ":r":   TOMBSTONE_REASON,
            },
        )
        updated += 1
        if updated % 50 == 0:
            print(f"  … {updated}/{len(legacy_keys)} tombstoned")
    print(f"✅ tombstoned {updated} legacy Hevy daily-aggregate records.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
