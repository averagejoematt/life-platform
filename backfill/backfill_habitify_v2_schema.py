"""TD-11 Phase 2: backfill habit_statuses + pending-aware completion_pct.

After the ingestion Lambda (v2 schema) deploys, today's record gets the new
fields automatically via the next hourly run (refresh_today=True), and the
ingestion framework's gap-detection re-fetches the last 7 days. Anything
older needs an explicit one-off re-ingest.

The Habitify API supports historical state queries
(/journal?target_date=YYYY-MM-DDT00:00:00+00:00) — see audit
docs/audits/TD-11_HABITIFY_API_AUDIT.md. We re-invoke the live Lambda with
{"date_override": "<date>"} for each backfill day, which is idempotent: the
Lambda overwrites the DDB record with the v2-schema record.

Usage (dry run first):
    python3 backfill/backfill_habitify_v2_schema.py --days 60 --dry-run
    python3 backfill/backfill_habitify_v2_schema.py --days 60 --apply

Defaults to a 60-day window. Picks a polite 1 req/sec pacing so we don't
trip Habitify's rate limit on a large backfill.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone, timedelta

import boto3

LAMBDA_NAME = "habitify-data-ingestion"
REGION = "us-west-2"


def main():
    p = argparse.ArgumentParser(description="TD-11 Phase 2 backfill")
    p.add_argument("--days", type=int, default=60,
                   help="Days back from today to re-ingest (default: 60)")
    p.add_argument("--apply", action="store_true",
                   help="Actually invoke the Lambda. Without --apply, prints planned dates only.")
    p.add_argument("--start-date", default=None,
                   help="Optional explicit start date (YYYY-MM-DD). Overrides --days.")
    p.add_argument("--pace-seconds", type=float, default=1.0,
                   help="Sleep between invocations (default: 1s)")
    args = p.parse_args()

    today = datetime.now(timezone.utc).date()
    if args.start_date:
        start = datetime.strptime(args.start_date, "%Y-%m-%d").date()
    else:
        start = today - timedelta(days=args.days)

    dates = []
    d = start
    while d <= today:
        dates.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)

    print(f"Plan: {len(dates)} dates from {dates[0]} to {dates[-1]}")
    print(f"Pacing: {args.pace_seconds}s between invocations")
    print(f"Total expected runtime: ~{len(dates) * args.pace_seconds:.0f}s")
    print()
    if not args.apply:
        print("DRY RUN — re-run with --apply to execute. Sample dates:")
        for date in dates[:5]:
            print(f"  would invoke lambda with date_override={date}")
        if len(dates) > 5:
            print(f"  ... and {len(dates) - 5} more")
        return 0

    lam = boto3.client("lambda", region_name=REGION)
    ok = 0
    failed = 0
    for date in dates:
        payload = json.dumps({"date_override": date}).encode()
        try:
            resp = lam.invoke(
                FunctionName=LAMBDA_NAME,
                InvocationType="RequestResponse",
                Payload=payload,
            )
            status = resp["StatusCode"]
            if status == 200:
                # The function may itself have errored — check FunctionError.
                err = resp.get("FunctionError")
                if err:
                    body = resp["Payload"].read().decode()[:200]
                    print(f"  FAIL  {date}  function-error: {body}")
                    failed += 1
                else:
                    print(f"  OK    {date}")
                    ok += 1
            else:
                print(f"  FAIL  {date}  HTTP {status}")
                failed += 1
        except Exception as e:
            print(f"  FAIL  {date}  exception: {e}")
            failed += 1
        time.sleep(args.pace_seconds)

    print()
    print(f"Done: {ok} succeeded, {failed} failed of {len(dates)} dates.")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
