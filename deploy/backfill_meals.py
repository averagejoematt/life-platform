#!/usr/bin/env python3
"""Backfill the `macrofactor_meals` projection over full MacroFactor history.

DRY-RUN BY DEFAULT — prints the grouped days and writes nothing. Pass --apply to
write. Resumable (skips days already projected unless --force). Conservation is
reconciled on EVERY day: `group_day` asserts `sum(rollups) == raw totals` to the
cent and raises on any mismatch — this script HALTS the whole job on the first
failure rather than writing a partial, non-reconciling projection.

Reads the raw partition DIRECTLY (not via the MCP phase filter) so it sees the
full cross-phase history, including pre-genesis days.

Usage:
    python3 deploy/backfill_meals.py                      # dry-run (default), prints grouped days
    python3 deploy/backfill_meals.py --limit 14           # dry-run, first 14 days only (eyeball a week or two)
    python3 deploy/backfill_meals.py --apply              # WRITE the projection (skips already-done days)
    python3 deploy/backfill_meals.py --apply --since 2026-06-01
    python3 deploy/backfill_meals.py --apply --force      # re-project every day (ignore resume)

Verify after: CloudWatch + `manage_meals get_day` spot-checks.
"""

import argparse
import os
import sys

import boto3
from boto3.dynamodb.conditions import Key

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import meal_projection as mp  # noqa: E402  (imports meal_grouper transitively)

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE = os.environ.get("TABLE_NAME", "life-platform")
USER = os.environ.get("USER_ID", "matthew")
RAW_PK = f"USER#{USER}#SOURCE#macrofactor"


def _decimal_to_float(obj):
    from decimal import Decimal

    if isinstance(obj, list):
        return [_decimal_to_float(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


def fetch_raw_days(table):
    items, kwargs = [], {"KeyConditionExpression": Key("pk").eq(RAW_PK) & Key("sk").begins_with("DATE#")}
    while True:
        r = table.query(**kwargs)
        items += r["Items"]
        if "LastEvaluatedKey" not in r:
            break
        kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    return _decimal_to_float(items)


def fetch_projected_dates(table):
    pk = mp.meals_pk(USER)
    dates, kwargs = set(), {
        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with("DATE#"),
        "ProjectionExpression": "#d",
        "ExpressionAttributeNames": {"#d": "date"},
    }
    while True:
        r = table.query(**kwargs)
        dates |= {it["date"] for it in r.get("Items", []) if it.get("date")}
        if "LastEvaluatedKey" not in r:
            break
        kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    return dates


def main():
    ap = argparse.ArgumentParser(description="Backfill macrofactor_meals projection")
    ap.add_argument("--apply", action="store_true", help="WRITE (default is dry-run)")
    ap.add_argument("--since", help="Only process dates >= YYYY-MM-DD")
    ap.add_argument("--limit", type=int, help="Process at most N days (eyeball a sample)")
    ap.add_argument("--force", action="store_true", help="Re-project days already done")
    args = ap.parse_args()
    dry_run = not args.apply

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    raw_days = sorted(
        (it for it in fetch_raw_days(table) if it.get("food_log")),
        key=lambda it: it["date"],
    )
    if args.since:
        raw_days = [it for it in raw_days if it["date"] >= args.since]
    projected = set() if (dry_run or args.force) else fetch_projected_dates(table)
    if args.limit:
        raw_days = raw_days[: args.limit]

    mode = "DRY-RUN (no writes)" if dry_run else "APPLY (writing)"
    print(f"=== Meal backfill — {mode} ===")
    print(f"Raw diary days with food_log: {len(raw_days)}  |  already projected: {len(projected)}\n")

    total_meals = total_skipped = total_written = 0
    for it in raw_days:
        date = it["date"]
        if date in projected:
            total_skipped += 1
            continue
        try:
            # group_day asserts conservation internally — raises on any reconcile failure
            res = mp.project_day(table, date, it["food_log"], user=USER, dry_run=dry_run)
        except ValueError as e:
            print(f"\n❌ HALT — conservation failed on {date}: {e}")
            print("   No partial projection written for this day. Fix the grouper/vocab and re-run.")
            sys.exit(1)
        except Exception as e:  # noqa: BLE001
            print(f"\n❌ HALT — unexpected error on {date}: {e}")
            sys.exit(1)

        groups = res["groups"]
        meals = [g for g in groups if g["kind"] == "meal"]
        snacks = [g for g in groups if g["kind"] == "snack"]
        uncat = [g for g in groups if g["kind"] == "uncategorized"]
        total_meals += len(meals)
        total_written += res["wrote"]
        names = ", ".join(g["meal_name"] for g in sorted(meals, key=lambda g: g["time_window"]["start"] or ""))
        flag = "" if dry_run else f"  (wrote {res['wrote']}, pruned {res['stale_pruned']})"
        print(f"  {date}  meals={len(meals)} snacks={len(snacks)} uncat={len(uncat)}{flag}")
        print(f"           {names or '(no named meals)'}")
        if uncat:
            print(f"           ⚠️ uncategorized: {[g['signature'].split('#')[0] for g in uncat]}")

    print(
        f"\n=== Done. days={len(raw_days)} processed, {total_skipped} skipped (resume), "
        f"{total_meals} meals grouped, {total_written} items written ==="
    )
    if dry_run:
        print("DRY-RUN only — re-run with --apply to write. Eyeball the days above first.")


if __name__ == "__main__":
    main()
