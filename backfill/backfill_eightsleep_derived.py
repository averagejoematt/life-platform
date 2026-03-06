#!/usr/bin/env python3
"""
backfill_eightsleep_derived.py
──────────────────────────────
Recomputes derived clinical fields for all existing Eight Sleep DynamoDB
records that are missing them (e.g. records ingested before derived fields
were added to the ingestor).

Fields added:
  time_in_bed_hours       sleep + awake
  sleep_efficiency_pct    sleep / TIB × 100
  waso_hours              awake − latency  (true Wake After Sleep Onset)
  rem_pct / deep_pct / light_pct   stage percentages
  sleep_onset_hour        local fractional hour of sleep onset
  wake_hour               local fractional hour of wake
  sleep_midpoint_hour     midpoint (circadian marker)

All logic lives in eightsleep_lambda.compute_derived_fields() — this script
just iterates DynamoDB records, calls that function, and patches records that
are missing any of the derived fields.

Usage:
  python3 backfill_eightsleep_derived.py [--dry-run] [--tz-offset N]

  --dry-run     Print what would change; don't write to DynamoDB.
  --tz-offset N Override the local timezone offset (default: -8 for PST).

Requirements:
  AWS credentials in environment (same profile used for normal ingestion).
  boto3 installed.
"""

import argparse
import json
import sys
from datetime import datetime
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

# Import helpers from the ingestor
sys.path.insert(0, ".")
from eightsleep_lambda import compute_derived_fields, _DEFAULT_TZ_OFFSET

# ── Config ─────────────────────────────────────────────────────────────────────
REGION         = "us-west-2"
DYNAMODB_TABLE = "life-platform"
PK             = "USER#matthew#SOURCE#eightsleep"

DERIVED_FIELDS = {
    "time_in_bed_hours",
    "sleep_efficiency_pct",
    "waso_hours",
    "rem_pct",
    "deep_pct",
    "light_pct",
    "sleep_onset_hour",
    "wake_hour",
    "sleep_midpoint_hour",
}

# ── Helpers ────────────────────────────────────────────────────────────────────
dynamodb = boto3.resource("dynamodb", region_name=REGION)
table    = dynamodb.Table(DYNAMODB_TABLE)


def floats_to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [floats_to_decimal(v) for v in obj]
    return obj


def fetch_all_records() -> list[dict]:
    """Paginate all Eight Sleep records from DynamoDB."""
    items, kwargs = [], {"KeyConditionExpression": Key("pk").eq(PK)}
    while True:
        resp = table.query(**kwargs)
        raw  = resp.get("Items", [])
        # Convert Decimal → float for easier arithmetic
        items.extend([
            {k: float(v) if isinstance(v, Decimal) else v for k, v in item.items()}
            for item in raw
        ])
        if not (lk := resp.get("LastEvaluatedKey")):
            break
        kwargs["ExclusiveStartKey"] = lk
    return items


def needs_update(record: dict) -> bool:
    """True if any computable derived field is missing from the record."""
    # Only check fields we can actually compute from stored data
    can_compute = set()
    if record.get("sleep_duration_hours") and record.get("awake_hours"):
        can_compute |= {"time_in_bed_hours", "sleep_efficiency_pct"}
    if record.get("awake_hours") and record.get("time_to_sleep_min"):
        can_compute.add("waso_hours")
    if record.get("sleep_duration_hours"):
        if record.get("rem_hours"):   can_compute.add("rem_pct")
        if record.get("deep_hours"):  can_compute.add("deep_pct")
        if record.get("light_hours"): can_compute.add("light_pct")
    if record.get("sleep_start"):
        can_compute |= {"sleep_onset_hour", "sleep_midpoint_hour"}
    if record.get("sleep_end"):
        can_compute.add("wake_hour")
        can_compute.add("sleep_midpoint_hour")

    missing = can_compute - set(record.keys())
    return len(missing) > 0


def patch_record(record: dict, tz_offset: int, dry_run: bool) -> dict:
    """Compute missing derived fields and update DynamoDB."""
    new_fields = compute_derived_fields(record, tz_offset)

    # Only write fields that are genuinely new or different
    to_write = {
        k: v for k, v in new_fields.items()
        if k not in record or abs(float(record.get(k, 0)) - float(v)) > 0.001
    }

    if not to_write:
        return {}

    if dry_run:
        return to_write

    # Build a targeted update expression (don't overwrite unrelated fields)
    expr_parts, names, values = [], {}, {}
    for i, (k, v) in enumerate(to_write.items()):
        placeholder = f"#f{i}"
        val_key     = f":v{i}"
        names[placeholder] = k
        values[val_key]    = floats_to_decimal(v)
        expr_parts.append(f"{placeholder} = {val_key}")

    table.update_item(
        Key={"pk": record["pk"], "sk": record["sk"]},
        UpdateExpression="SET " + ", ".join(expr_parts),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )
    return to_write


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Backfill Eight Sleep derived fields")
    parser.add_argument("--dry-run",   action="store_true", help="Print changes; don't write")
    parser.add_argument("--tz-offset", type=int, default=_DEFAULT_TZ_OFFSET,
                        help=f"Local timezone UTC offset (default: {_DEFAULT_TZ_OFFSET} = PST)")
    args = parser.parse_args()

    mode = "DRY RUN" if args.dry_run else "LIVE"
    print(f"\n{'='*60}")
    print(f" Eight Sleep derived-fields backfill  [{mode}]")
    print(f" tz_offset = {args.tz_offset:+d}h")
    print(f"{'='*60}\n")

    print("Fetching all Eight Sleep records from DynamoDB...")
    records = fetch_all_records()
    print(f"Found {len(records)} total records.\n")

    needs = [r for r in records if needs_update(r)]
    print(f"{len(needs)} records need updating ({len(records) - len(needs)} already complete).\n")

    if not needs:
        print("Nothing to do.")
        return

    updated = skipped = errors = 0
    for i, rec in enumerate(sorted(needs, key=lambda r: r.get("sk", "")), 1):
        date = rec.get("date", rec.get("sk", "?")[-10:])
        try:
            written = patch_record(rec, args.tz_offset, args.dry_run)
            if written:
                print(f"  [{i:4d}/{len(needs)}] {date}  +{list(written.keys())}")
                updated += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"  [{i:4d}/{len(needs)}] {date}  ERROR: {e}", file=sys.stderr)
            errors += 1

    print(f"\n{'='*60}")
    print(f" Done.  updated={updated}  skipped={skipped}  errors={errors}")
    if args.dry_run:
        print(" (DRY RUN — no writes performed)")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
