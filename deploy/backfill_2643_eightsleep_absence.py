#!/usr/bin/env python3
"""
backfill_2643_eightsleep_absence.py — record the ADR-104 absence marker for
Eight Sleep's 2026-08-09 interior gap (#2643).

Why: `freshness-interior-gap` red on `{'Eight Sleep': ['2026-08-09']}` — a
single date missing from the middle of the series (2026-08-08 and 2026-08-10
both present). Investigated by measurement, not assumption:

  * DDB: USER#matthew#SOURCE#eightsleep has no DATE#2026-08-09 item, but every
    other date 2026-08-01..2026-08-18 is present.
  * S3 raw/matthew/eightsleep/2026/08/ has no 2026-08-09.json either.
  * CloudWatch Logs (/aws/lambda/eightsleep-data-ingestion) show the Lambda ran
    HOURLY through the entire Pacific day 2026-08-09 (00:15Z 08-09 through
    05:15Z 08-10), every run logging `[GAP-FILL] Found 1 missing dates:
    ['2026-08-09']` followed by `2026-08-09: no records after transform` — the
    vendor call succeeded every time, it simply never returned a "day" entry
    matching 2026-08-09.
  * A live direct probe of the Eight Sleep trends API on 2026-08-18 (9 days
    later, this script's companion investigation) for the window
    2026-08-05..2026-08-12 returned every day EXCEPT 2026-08-09 — confirmed
    stable over 9+ days, not a delayed-processing artifact.

Conclusion: Branch 2 of the issue's three named branches — the vendor
genuinely has no sleep session for that date (Matthew's morning-of-08-08 wake
was ~08:14 PT; the next bed presence wasn't until evening of 08-09, landing as
the 08-10 night — consistent with one night not spent in the pod). This is
real data about a real night, not a pipeline miss. Per ADR-104 (behavioral-
absence semantics), it is recorded explicitly rather than left as a hole that
reads as "not yet fetched".

This is the SAME marker shape `ingestion_framework._record_absence_marker`
(added by this issue's PR) now writes automatically the next time Eight
Sleep's own gap-fill window ages a date out unfulfilled — this script exists
only because 2026-08-09 already aged out of the 7-day lookback window before
that mechanism could apply to it retroactively.

Read-only by default (prints the item and validates it against the platform's
own eightsleep schema). Apply with --apply.

  python3 deploy/backfill_2643_eightsleep_absence.py            # dry-run report
  python3 deploy/backfill_2643_eightsleep_absence.py --apply    # write the marker
"""

import argparse
import json
import sys
from datetime import datetime, timezone

import boto3

sys.path.insert(0, "lambdas")

TABLE = "life-platform"
REGION = "us-west-2"
USER_ID = "matthew"
SOURCE = "eightsleep"
DATE_STR = "2026-08-09"
LOOKBACK_DAYS = 7  # matches eightsleep_lambda's IngestionConfig.lookback_days


def build_item() -> dict:
    from ingestion.ingestion_framework import phase_for_date  # same helper the framework stamps with

    return {
        "pk": f"USER#{USER_ID}#SOURCE#{SOURCE}",
        "sk": f"DATE#{DATE_STR}",
        "source": SOURCE,
        "schema_version": 1,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "date": DATE_STR,
        "phase": phase_for_date(DATE_STR),
        "absent": True,
        "absence_reason": (
            f"No data returned by the source across the full {LOOKBACK_DAYS}-day gap-fill retry window "
            "(#2643) — recorded as a measured absence, not a pipeline miss. Confirmed by a direct live "
            "probe of the vendor trends API on 2026-08-18 over the window 2026-08-05..2026-08-12, which "
            "returned every day except this one."
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the absence marker (default: dry-run)")
    args = ap.parse_args()

    item = build_item()

    from ingestion.ingestion_validator import validate_item

    result = validate_item(SOURCE, item, DATE_STR)
    print("Item to write:")
    print(json.dumps(item, indent=2, default=str))
    print(f"\nValidator: errors={result.errors} warnings={result.warnings}")
    if result.errors:
        print("CRITICAL validation errors — refusing to write.")
        return 1

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    existing = table.get_item(Key={"pk": item["pk"], "sk": item["sk"]}).get("Item")
    if existing:
        print(f"\nREFUSING: an item already exists at this key — this script only fills a confirmed hole.\n{existing}")
        return 1

    if not args.apply:
        print("\nDry-run only — no write performed. Re-run with --apply to write.")
        return 0

    table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)")
    print(f"\nWrote absence marker for {SOURCE}/{DATE_STR}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
