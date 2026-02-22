#!/usr/bin/env python3
"""
backfill_whoop.py — Ingest historical Whoop data from 2020-03-01 to yesterday.

Writes the same 20 daily fields as the production Lambda, plus one DynamoDB
record per workout.  All writes go to the same S3 bucket and DynamoDB table
used by the Lambda.

Daily DynamoDB item  pk=USER#matthew#SOURCE#whoop  sk=DATE#YYYY-MM-DD
  Recovery : recovery_score, hrv, resting_heart_rate, spo2_percentage,
             skin_temp_celsius
  Sleep    : sleep_duration_hours, rem_sleep_hours, slow_wave_sleep_hours,
             light_sleep_hours, time_awake_hours, disturbance_count,
             respiratory_rate, sleep_efficiency_percentage,
             sleep_consistency_percentage, sleep_performance_percentage,
             sleep_quality_score
  Cycle    : strain, kilojoule, average_heart_rate, max_heart_rate

Workout DynamoDB item  pk=USER#matthew#SOURCE#whoop
                       sk=DATE#YYYY-MM-DD#WORKOUT#<workout_id>
  sport_id, sport_name, start_time, end_time,
  strain, average_heart_rate, max_heart_rate, kilojoule, distance_meter,
  zone_0_minutes … zone_5_minutes

Usage:
    python backfill_whoop.py                          # start from 2020-03-01
    python backfill_whoop.py --from 2021-04-06        # resume from a date

Rate-limit behaviour:
    0.3 s between each of the 4 API calls per day (call_delay).
    0.5 s between days (day_delay).
    On HTTP 429: exponential backoff — waits 30 s, 60 s, 120 s before giving up.

AWS credentials are read from ~/.aws/credentials or environment variables.
"""

import argparse
import json
import sys
import time
import urllib.error
from datetime import date, timedelta

import boto3

from lambda_function import (
    DYNAMODB_TABLE,
    REGION,
    S3_BUCKET,
    SECRET_NAME,
    ingest_day,
    refresh_access_token,
)

BACKFILL_START = date(2020, 3, 1)
TOKEN_TTL_SECONDS = 45 * 60   # refresh token proactively every 45 minutes
CALL_DELAY = 0.3               # seconds between the 4 API calls per day
DAY_DELAY = 0.5                # seconds between days
RETRY_WAITS = [30, 60, 120]   # seconds to wait on successive 429 retries


# ── Token management ──────────────────────────────────────────────────────────

def _do_refresh(secretsmanager, credentials):
    """Refresh token, persist to Secrets Manager, return new access_token."""
    access_token, new_refresh = refresh_access_token(
        credentials["client_id"],
        credentials["client_secret"],
        credentials["refresh_token"],
    )
    credentials["access_token"] = access_token
    credentials["refresh_token"] = new_refresh
    secretsmanager.update_secret(
        SecretId=SECRET_NAME,
        SecretString=json.dumps(credentials),
    )
    return access_token


def load_credentials(secretsmanager):
    """Read Whoop secret and return a fresh (access_token, credentials_dict)."""
    credentials = json.loads(
        secretsmanager.get_secret_value(SecretId=SECRET_NAME)["SecretString"]
    )
    print("Refreshing access token...", flush=True)
    access_token = _do_refresh(secretsmanager, credentials)
    print("Token refreshed.\n", flush=True)
    return access_token, credentials


# ── 429-aware day ingestion ───────────────────────────────────────────────────

def ingest_day_with_retry(date_str, access_token, credentials, secretsmanager,
                          s3, table, prefix):
    """
    Call ingest_day; on 429 wait and retry (up to len(RETRY_WAITS) times).
    On 401 refresh the token once and retry.
    Returns (summary_dict, new_access_token).
    """
    attempt = 0
    while True:
        try:
            summary = ingest_day(
                date_str, access_token, s3, table,
                verbose=False, call_delay=CALL_DELAY,
            )
            return summary, access_token

        except urllib.error.HTTPError as e:
            if e.code == 429:
                if attempt < len(RETRY_WAITS):
                    wait = RETRY_WAITS[attempt]
                    attempt += 1
                    print(
                        f"\r{prefix}  [429 → waiting {wait}s, attempt {attempt}/{len(RETRY_WAITS)}]",
                        end="", flush=True,
                    )
                    time.sleep(wait)
                    continue  # retry same day
                else:
                    raise  # give up after all retries exhausted

            elif e.code == 401:
                print(f"\r{prefix}  [401 → refreshing token]", end="", flush=True)
                access_token = _do_refresh(secretsmanager, credentials)
                attempt = 0
                continue  # retry with fresh token

            else:
                raise


# ── Progress formatting ───────────────────────────────────────────────────────

def _fmt_progress(s):
    """
    All 20 daily fields in a compact multi-block line.

    Example:
      rec=68 hrv=38.8 rhr=59 spo2=95.6 skin=33.7 |
      sleep=9.0h rem=2.8h sws=1.8h lt=4.1h wake=0.3h dist=5 rr=16.1 eff=97 cons=66 q=77 |
      strain=4.0 kJ=2100 avghr=68 maxhr=141 | 0 workouts
    """
    def f(key, label, spec):
        val = s.get(key)
        return f"{label}={val:{spec}}" if val is not None else ""

    def fh(key, label):
        val = s.get(key)
        return f"{label}={val:.1f}h" if val is not None else ""

    rec = _join([
        f("recovery_score",    "rec",   ".0f"),
        f("hrv",               "hrv",   ".1f"),
        f("resting_heart_rate","rhr",   ".0f"),
        f("spo2_percentage",   "spo2",  ".1f"),
        f("skin_temp_celsius", "skin",  ".1f"),
    ])
    slp = _join([
        fh("sleep_duration_hours",  "sleep"),
        fh("rem_sleep_hours",       "rem"),
        fh("slow_wave_sleep_hours", "sws"),
        fh("light_sleep_hours",     "lt"),
        fh("time_awake_hours",      "wake"),
        f("disturbance_count",          "dist", "d"),
        f("respiratory_rate",           "rr",   ".1f"),
        f("sleep_efficiency_percentage","eff",  ".0f"),
        f("sleep_consistency_percentage","cons",".0f"),
        f("sleep_quality_score",        "q",    ".0f"),
    ])
    cyc = _join([
        f("strain",             "strain", ".1f"),
        f("kilojoule",          "kJ",     ".0f"),
        f("average_heart_rate", "avghr",  ".0f"),
        f("max_heart_rate",     "maxhr",  ".0f"),
    ])
    wc = s.get("workout_count", 0)
    wrkt = f"{wc} workout{'s' if wc != 1 else ''}"

    blocks = [b for b in [rec, slp, cyc, wrkt] if b]
    return " | ".join(blocks) if blocks else "(no data)"


def _join(parts):
    return " ".join(p for p in parts if p)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Backfill historical Whoop data.")
    parser.add_argument(
        "--from", dest="start_from", metavar="YYYY-MM-DD", default=None,
        help="Resume from this date (inclusive). Defaults to 2020-03-01.",
    )
    args = parser.parse_args()

    start_date = BACKFILL_START
    if args.start_from:
        try:
            start_date = date.fromisoformat(args.start_from)
        except ValueError:
            print(f"[ERROR] Invalid date: {args.start_from}", file=sys.stderr)
            sys.exit(1)

    end_date = date.today() - timedelta(days=1)

    all_dates = []
    cursor = start_date
    while cursor <= end_date:
        all_dates.append(cursor)
        cursor += timedelta(days=1)
    total = len(all_dates)

    print(f"Whoop backfill  {start_date} → {end_date}  ({total} days)")
    print(f"Bucket : s3://{S3_BUCKET}/raw/whoop/")
    print(f"Table  : {DYNAMODB_TABLE}  (region {REGION})")
    print(f"Pacing : {CALL_DELAY}s between API calls, {DAY_DELAY}s between days")
    print("=" * 80, flush=True)

    secretsmanager = boto3.client("secretsmanager", region_name=REGION)
    s3 = boto3.client("s3", region_name=REGION)
    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    table = dynamodb.Table(DYNAMODB_TABLE)

    access_token, credentials = load_credentials(secretsmanager)
    token_refreshed_at = time.monotonic()

    success = 0
    no_data = 0
    errors = 0

    for i, dt in enumerate(all_dates, 1):
        date_str = dt.strftime("%Y-%m-%d")
        prefix = f"[{i:5d}/{total}] {date_str}"

        # Proactive token refresh every 45 minutes
        if time.monotonic() - token_refreshed_at > TOKEN_TTL_SECONDS:
            print(f"\n  ↻ proactive token refresh...", end="", flush=True)
            try:
                access_token = _do_refresh(secretsmanager, credentials)
                token_refreshed_at = time.monotonic()
                print(" ok", flush=True)
            except Exception as e:
                print(f"\n[FATAL] Token refresh failed: {e}", file=sys.stderr)
                break

        print(f"{prefix} ...", end="", flush=True)

        try:
            summary, access_token = ingest_day_with_retry(
                date_str, access_token, credentials, secretsmanager, s3, table, prefix,
            )
            # Track token refresh time if it was refreshed inside the retry loop
            token_refreshed_at = time.monotonic()

            line = _fmt_progress(summary)
            print(f"\r{prefix}  {line}")

            has_data = any(
                summary.get(k) is not None
                for k in ("recovery_score", "sleep_duration_hours", "strain")
            )
            if has_data:
                success += 1
            else:
                no_data += 1

        except urllib.error.HTTPError as e:
            print(f"\r{prefix}  ✗ HTTP {e.code} (gave up after retries): {e.reason}")
            errors += 1

        except Exception as e:
            print(f"\r{prefix}  ✗ {type(e).__name__}: {e}")
            errors += 1

        time.sleep(DAY_DELAY)

    print("=" * 80)
    print(
        f"Done.  ✓ {success} with data   "
        f"~ {no_data} no data   "
        f"✗ {errors} errors   "
        f"({total} days total)"
    )
    if errors:
        print(f"\nTo retry failed days, re-run with: --from {start_date}")


if __name__ == "__main__":
    main()
