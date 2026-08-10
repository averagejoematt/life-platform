#!/usr/bin/env python3
"""reconcile_strava_measured_zero.py — re-derive stored distance/elevation under the #2331 rule.

The writer fix (``ingestion/strava_population``) only governs rows Strava re-fetches, and
the ingestion Lambda re-fetches the trailing 3 days plus today. Every older activity keeps
whatever the falsy-check wrote — so a flat 2021 run stays "unmeasured" forever unless the
stored rows are re-derived. This script does that re-derivation, from data already in the
row: ``distance_meters`` and ``total_elevation_gain_meters`` are the raw API values and were
never collapsed, so no API call and no re-ingest is needed.

It is a DRY RUN by default and prints the exact per-activity plan. ``--apply`` is an
owner/morning step run from main against prod DynamoDB — nothing in CI or in a worktree
should ever pass it.

    python3 scripts/reconcile_strava_measured_zero.py                 # plan only
    python3 scripts/reconcile_strava_measured_zero.py --verbose       # plan, every row
    python3 scripts/reconcile_strava_measured_zero.py --apply         # owner, from main

Safety properties:
  * Only the two derived fields ``distance_miles`` / ``total_elevation_gain_feet`` are
    written, and only on activities whose re-derived value DIFFERS from what is stored.
  * The day record is written back with ``update_item`` on the ``activities`` attribute
    only — the rest of the row (aggregates, enrichment carry-forward fields) is untouched.
  * Floats are cast to ``Decimal`` before any write (boto3 rejects float).
  * ``--apply`` re-reads and re-plans each day immediately before writing it, so a
    concurrent ingest of the same day cannot be clobbered by a stale plan.

Blast radius, measured by this script's own dry run on 2026-08-10 (1,207 day records /
2,769 activities): 6 day records, 2 `distance_miles` and 6 `total_elevation_gain_feet`
values, all on pre-2024 outdoor GPS activities (the newest is 2021-07-18). The 650
indoor-trainer, manually-entered and 1,237 gym rows are correctly left absent by the rule,
so they are no-ops — which is exactly why the rule had to be decided before the coercion.
"""

import argparse
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from ingestion import strava_population  # noqa: E402

USER_ID = os.environ.get("USER_ID", "matthew")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
REGION = os.environ.get("AWS_REGION", "us-west-2")
PARTITION = f"USER#{USER_ID}#SOURCE#strava"


def _as_float(value):
    return None if value is None else float(value)


def plan_activity(activity: dict) -> dict:
    """Return {field: (old, new)} for the fields whose stored value disagrees with the rule."""
    changes = {}
    new_dist = strava_population.distance_miles(activity, activity.get("distance_meters"))
    new_elev = strava_population.elevation_gain_feet(activity, activity.get("total_elevation_gain_meters"))
    for field, new in (("distance_miles", new_dist), ("total_elevation_gain_feet", new_elev)):
        old = _as_float(activity.get(field))
        if old != new:
            changes[field] = (old, new)
    return changes


def plan_day(item: dict) -> list[tuple[int, dict, dict]]:
    """Return [(index, activity, changes)] for one stored day record."""
    out = []
    for idx, act in enumerate(item.get("activities") or []):
        changes = plan_activity(act)
        if changes:
            out.append((idx, act, changes))
    return out


def _apply_changes(activities: list, planned: list) -> list:
    """Return a copy of `activities` with the planned values written as Decimal/None."""
    updated = [dict(a) for a in activities]
    for idx, _act, changes in planned:
        for field, (_old, new) in changes.items():
            updated[idx][field] = None if new is None else Decimal(str(new))
    return updated


def _iter_days(table):
    from boto3.dynamodb.conditions import Key

    kwargs = {"KeyConditionExpression": Key("pk").eq(PARTITION)}
    while True:
        page = table.query(**kwargs)
        for item in page["Items"]:
            yield item
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="WRITE the re-derived values (owner step, from main)")
    ap.add_argument("--verbose", action="store_true", help="print every changed activity, not just a sample")
    args = ap.parse_args()

    import boto3

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)

    days_scanned = 0
    days_changed = 0
    field_counts = {"distance_miles": 0, "total_elevation_gain_feet": 0}
    printed = 0

    for item in _iter_days(table):
        days_scanned += 1
        planned = plan_day(item)
        if not planned:
            continue
        days_changed += 1
        sk = item.get("sk", "?")
        for _idx, act, changes in planned:
            for field, (old, new) in changes.items():
                field_counts[field] += 1
            if args.verbose or printed < 25:
                printed += 1
                desc = ", ".join(f"{f}: {o!r} -> {n!r}" for f, (o, n) in sorted(changes.items()))
                print(f"  {sk}  {strava_population.activity_type(act) or '?':<16} {str(act.get('name'))[:28]:<28} {desc}")

        if args.apply:
            # Re-read the row so a concurrent ingest of this day is not clobbered by a stale plan.
            fresh = table.get_item(Key={"pk": item["pk"], "sk": item["sk"]}).get("Item")
            if not fresh:
                print(f"  !! {sk} vanished between plan and apply — skipped")
                continue
            fresh_plan = plan_day(fresh)
            if not fresh_plan:
                print(f"  .. {sk} already reconciled by a concurrent write — skipped")
                continue
            table.update_item(
                Key={"pk": fresh["pk"], "sk": fresh["sk"]},
                UpdateExpression="SET activities = :a",
                ExpressionAttributeValues={":a": _apply_changes(fresh.get("activities") or [], fresh_plan)},
            )

    verb = "WROTE" if args.apply else "would change"
    print()
    print(f"scanned {days_scanned} day records")
    print(
        f"{verb} {days_changed} day records: "
        f"{field_counts['distance_miles']} distance_miles, {field_counts['total_elevation_gain_feet']} total_elevation_gain_feet"
    )
    if not args.apply:
        print("DRY RUN — nothing was written. Re-run with --apply from main to reconcile.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
