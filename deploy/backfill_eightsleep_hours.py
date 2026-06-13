#!/usr/bin/env python3
"""
backfill_eightsleep_hours.py — re-derive stored Eight Sleep circadian hours (2026-06-12).

Why: eightsleep ingestion converted UTC timestamps to local hours with a FIXED
standard-time offset (America/Los_Angeles → -8), so every stored
sleep_onset_hour / wake_hour / sleep_midpoint_hour for a PDT-season night
(March–November, all years) is one hour earlier than reality. The ingestion
bug is fixed (zoneinfo); this corrects the archive.

What it does: for every USER#matthew#SOURCE#eightsleep DATE# item that has
sleep_start/sleep_end ISO-UTC timestamps, recompute the three hour fields with
zoneinfo at the timestamp's OWN date (exact historical DST handling — strictly
better than ingest-time offsets) and update the item where values differ.

Read-only by default. Apply with --apply.

  python3 deploy/backfill_eightsleep_hours.py            # dry-run report
  python3 deploy/backfill_eightsleep_hours.py --apply    # write corrections
"""

import argparse
import sys
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import boto3
from boto3.dynamodb.conditions import Key

TABLE = "life-platform"
REGION = "us-west-2"
PK = "USER#matthew#SOURCE#eightsleep"
LA = ZoneInfo("America/Los_Angeles")
UTC = ZoneInfo("UTC")
FIELDS = ("sleep_onset_hour", "wake_hour", "sleep_midpoint_hour")


def local_hour(iso_ts: str) -> float | None:
    """Fractional Pacific hour for an ISO UTC timestamp, DST-correct per date."""
    if not iso_ts:
        return None
    try:
        clean = str(iso_ts).split(".")[0].replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        loc = dt.astimezone(LA)
        return round(loc.hour + loc.minute / 60.0 + loc.second / 3600.0, 2)
    except Exception:
        return None


def midpoint(onset: float, wake: float) -> float:
    """Same cross-midnight formula as the ingestion lambda."""
    if wake < onset:
        return round(((onset + wake + 24) / 2) % 24, 2)
    return round((onset + wake) / 2, 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write corrections (default: dry-run)")
    args = ap.parse_args()

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    items, kwargs = [], {"KeyConditionExpression": Key("pk").eq(PK)}
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    scanned = changed = skipped = 0
    for it in items:
        sk = it.get("sk", "")
        if not sk.startswith("DATE#"):
            continue
        scanned += 1
        onset = local_hour(it.get("sleep_start"))
        wake = local_hour(it.get("sleep_end"))
        if onset is None or wake is None:
            skipped += 1
            continue
        correct = {"sleep_onset_hour": onset, "wake_hour": wake, "sleep_midpoint_hour": midpoint(onset, wake)}
        stored = {f: (float(it[f]) if it.get(f) is not None else None) for f in FIELDS}
        diffs = {f: (stored[f], correct[f]) for f in FIELDS if stored[f] is None or abs(stored[f] - correct[f]) > 0.011}
        if not diffs:
            continue
        changed += 1
        delta = ", ".join(f"{f}: {a} → {b}" for f, (a, b) in diffs.items())
        print(f"  {sk[5:]}  {delta}")
        if args.apply:
            table.update_item(
                Key={"pk": PK, "sk": sk},
                UpdateExpression="SET " + ", ".join(f"#f{i} = :v{i}" for i in range(len(FIELDS))),
                ExpressionAttributeNames={f"#f{i}": f for i, f in enumerate(FIELDS)},
                ExpressionAttributeValues={f":v{i}": Decimal(str(correct[f])) for i, f in enumerate(FIELDS)},
            )

    mode = "APPLIED" if args.apply else "DRY-RUN (no writes)"
    print(f"\n{mode}: {scanned} nights scanned, {changed} corrected, {skipped} skipped (no timestamps)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
