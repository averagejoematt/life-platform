#!/usr/bin/env python3
"""migrate_hevy_local_date_keys.py — one-shot re-key of Hevy workout records
from UTC dates to Pacific-local dates (#475 / C-8).

Before schema v2, hevy_common keyed each workout by the UTC calendar day of its
start_time (`DATE#{utc_date}#WORKOUT#{id}`). Strava keys by start_date_local, so
a >=17:00-PT lift landed on the WRONG platform day and desynced from its
same-evening Strava echo. Schema v2 keys new writes by the Pacific-local day;
this script re-keys the existing records so history is neither orphaned (left on
the UTC day) nor double-counted (present on both days).

Per affected record (stored date != Pacific date of start_time):
  1. put a copy under the new sk (date/phase recomputed, migrated_from_sk +
     migrated_at stamped, schema_version=2)
  2. delete the old sk

Put-then-delete order means a mid-run crash can only leave BOTH copies — and a
re-run converges (the old copy still mismatches, so it is re-migrated and
removed). Records already keyed to their local date are untouched, so the
script is idempotent. The raw S3 archive is flat UUID-keyed (raw/hevy/{id}.json
— see the source_registry raw_layout facet), so no S3 object moves are needed
and raw_ref stays valid.

DELETE#WORKOUT# tombstone markers and the INGESTION_STATE record are not DATE#
keys and are never touched.

Usage:
    python3 scripts/migrate_hevy_local_date_keys.py            # dry-run (default)
    python3 scripts/migrate_hevy_local_date_keys.py --apply    # execute

Run AFTER deploying the #475 ingestion change (else the hourly poll can re-write
a just-migrated record back under its UTC date).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
HEVY_PK = f"USER#{USER_ID}#SOURCE#hevy"


def _local_date_of(start_iso: str) -> str | None:
    """Pacific calendar date of an ISO instant (naive = UTC), or None if unparseable."""
    from pacific_time import pacific_date_of

    return pacific_date_of(start_iso)


def _phase_for(date_str: str, fallback: str | None) -> str | None:
    """Recompute the ADR-058 phase for the record's NEW date (a date shift can
    cross the genesis boundary). Falls back to the record's existing phase if
    the framework module is unavailable."""
    try:
        from ingestion_framework import _phase_for_date

        return _phase_for_date(date_str)
    except Exception:  # noqa: BLE001 — keep the stored phase rather than guess
        return fallback


def scan_workout_records(table) -> list[dict]:
    """All DATE#…#WORKOUT#… records in the hevy partition (full items)."""
    from boto3.dynamodb.conditions import Key

    items: list[dict] = []
    kwargs: dict = {"KeyConditionExpression": Key("pk").eq(HEVY_PK) & Key("sk").begins_with("DATE#")}
    while True:
        resp = table.query(**kwargs)
        items.extend(it for it in resp.get("Items", []) if "#WORKOUT#" in str(it.get("sk", "")))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            return items
        kwargs["ExclusiveStartKey"] = lek


def plan_moves(items: list[dict]) -> tuple[list[dict], list[str]]:
    """(moves, skipped_reasons). A move = {old_sk, new_sk, workout_id, old_date, new_date}."""
    moves: list[dict] = []
    skipped: list[str] = []
    for it in items:
        sk = str(it.get("sk", ""))
        wid = str(it.get("source_workout_id") or sk.rsplit("#WORKOUT#", 1)[-1])
        start_iso = str(it.get("start_time") or "")
        if not start_iso:
            skipped.append(f"{sk}: no start_time — cannot derive local date; left as-is")
            continue
        local_date = _local_date_of(start_iso)
        if local_date is None:
            skipped.append(f"{sk}: unparseable start_time {start_iso!r}; left as-is")
            continue
        old_date = str(it.get("date") or sk.split("DATE#", 1)[-1].split("#", 1)[0])
        if old_date == local_date:
            continue  # already local-keyed — idempotency path
        moves.append(
            {
                "old_sk": sk,
                "new_sk": f"DATE#{local_date}#WORKOUT#{wid}",
                "workout_id": wid,
                "old_date": old_date,
                "new_date": local_date,
                "start_time": start_iso,
                "item": it,
            }
        )
    return moves, skipped


def apply_moves(table, moves: list[dict]) -> dict:
    """Execute put-new-then-delete-old for each move. Items read from DDB are
    already Decimal-typed, so the copy is Decimal-safe by construction (the only
    added values are strings)."""
    migrated = 0
    collisions = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    for mv in moves:
        item = dict(mv["item"])  # shallow copy; nested values reused as-is (Decimal-safe)
        existing = table.get_item(Key={"pk": HEVY_PK, "sk": mv["new_sk"]}).get("Item")
        if existing:
            # Target already exists (workout ingested under both keyings, e.g. a
            # post-deploy re-ingest raced the migration). The target IS the same
            # workout under the correct key — keep it, just remove the UTC copy.
            collisions += 1
            print(f"  COLLISION {mv['old_sk']} → {mv['new_sk']} already exists; deleting old copy only")
        else:
            item["sk"] = mv["new_sk"]
            item["date"] = mv["new_date"]
            phase = _phase_for(mv["new_date"], item.get("phase"))
            if phase:
                item["phase"] = phase
            item["schema_version"] = 2
            item["migrated_from_sk"] = mv["old_sk"]
            item["migrated_at"] = now_iso
            table.put_item(Item=item)
            print(f"  MOVED {mv['old_sk']} → {mv['new_sk']} (start_time {mv['start_time']})")
        table.delete_item(Key={"pk": HEVY_PK, "sk": mv["old_sk"]})
        migrated += 1
    return {"migrated": migrated, "collisions": collisions}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-key Hevy workout records to Pacific-local dates (#475). Dry-run by default.")
    parser.add_argument("--apply", action="store_true", help="Execute the migration (default: dry-run, print the plan only)")
    args = parser.parse_args(argv)

    import boto3

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)

    items = scan_workout_records(table)
    moves, skipped = plan_moves(items)

    print(f"Hevy partition: {len(items)} WORKOUT# records; {len(moves)} need re-keying; {len(skipped)} skipped")
    for s in skipped:
        print(f"  SKIP {s}")
    for mv in moves:
        print(f"  {'WILL MOVE' if args.apply else 'DRY-RUN'} {mv['old_sk']} → {mv['new_sk']} (start_time {mv['start_time']})")

    if not args.apply:
        print("\nDry-run only — re-run with --apply to execute.")
        return 0

    result = apply_moves(table, moves)
    print(json.dumps({"records_scanned": len(items), **result, "skipped": len(skipped)}, default=str))
    print("Done. Re-run without --apply to verify 0 remaining moves (idempotency check).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
