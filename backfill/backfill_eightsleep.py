#!/usr/bin/env python3
"""
backfill_eightsleep.py — Ingest historical Eight Sleep data from a start date to yesterday.

Writes one DynamoDB record per wake date (morning of the night being tracked),
matching the schema of the production eightsleep_lambda.py.

Usage:
    python backfill_eightsleep.py                       # from 2023-01-01 by default
    python backfill_eightsleep.py --from 2024-03-01     # resume from a specific date
    python backfill_eightsleep.py --from 2024-03-01 --to 2024-03-31  # specific window

Auth:
    Reads credentials from Secrets Manager (life-platform/eightsleep).
    If access_token is missing, does a full login and saves the tokens.
    Refreshes the token every 45 minutes proactively.

Rate limits:
    Eight Sleep's undocumented API enforces rate limits — aggressive polling
    causes 429s, especially on login.  This script:
      - Uses a 1s delay between days (generous, avoids any throttling)
      - Refreshes token proactively rather than waiting for 401
      - Backs off on 429: waits 30s, 60s, 120s before giving up on that day
"""

import argparse
import json
import sys
import time
import urllib.error
from datetime import date, datetime, timedelta

import boto3

from eightsleep_lambda import (
    KNOWN_CLIENT_ID,
    KNOWN_CLIENT_SECRET,
    REGION,
    SECRET_NAME,
    ensure_user_id,
    get_secret,
    ingest_day,
    login,
    refresh_token,
    save_secret,
)

# ── Config ────────────────────────────────────────────────────────────────────
BACKFILL_START  = date(2023, 1, 1)   # adjust to your actual Eight Sleep purchase date
DAY_DELAY       = 1.0                 # seconds between days
TOKEN_TTL_SECS  = 45 * 60            # proactive refresh interval
RETRY_WAITS     = [30, 60, 120]       # seconds to wait on successive 429s


# ── Token management ──────────────────────────────────────────────────────────
def ensure_tokens(secret: dict) -> dict:
    """Make sure we have a valid access_token, logging in fresh if needed."""
    if not secret.get("access_token"):
        print("No access token found — performing full login...")
        token_data = login(
            email         = secret["email"],
            password      = secret["password"],
            client_id     = secret.get("client_id",     DEFAULT_CLIENT_ID),
            client_secret = secret.get("client_secret", DEFAULT_CLIENT_SECRET),
        )
        secret.update(token_data)
        secret = ensure_user_id(secret)
        save_secret(secret)
        print(f"Logged in. user_id={secret['user_id']}")
    return secret


def do_refresh(secret: dict) -> dict:
    """Refresh token and persist."""
    secret = refresh_token(secret)
    save_secret(secret)
    return secret


# ── Day ingestion with retry ───────────────────────────────────────────────────
def ingest_with_retry(wake_date: str, secret: dict) -> dict:
    """
    Call ingest_day with exponential backoff on 429, token refresh on 401.
    Returns the parsed record (may be empty dict if no data).
    """
    attempt = 0
    while True:
        try:
            return ingest_day(wake_date, secret)

        except urllib.error.HTTPError as e:
            if e.code == 429:
                if attempt < len(RETRY_WAITS):
                    wait = RETRY_WAITS[attempt]
                    attempt += 1
                    print(f"  [429 — sleeping {wait}s, attempt {attempt}/{len(RETRY_WAITS)}]",
                          flush=True)
                    time.sleep(wait)
                else:
                    raise  # give up

            elif e.code == 401:
                print("  [401 — refreshing token]", flush=True)
                secret = do_refresh(secret)
                attempt = 0

            else:
                raise


# ── Progress display ───────────────────────────────────────────────────────────
def fmt_result(parsed: dict) -> str:
    if not parsed:
        return "(no data)"
    parts = []
    if parsed.get("sleep_score")         is not None: parts.append(f"score={parsed['sleep_score']:.0f}")
    if parsed.get("sleep_duration_hours") is not None: parts.append(f"sleep={parsed['sleep_duration_hours']:.1f}h")
    if parsed.get("deep_hours")          is not None: parts.append(f"deep={parsed['deep_hours']:.1f}h")
    if parsed.get("rem_hours")           is not None: parts.append(f"rem={parsed['rem_hours']:.1f}h")
    if parsed.get("hrv_avg")             is not None: parts.append(f"hrv={parsed['hrv_avg']:.0f}")
    if parsed.get("hr_avg")              is not None: parts.append(f"hr={parsed['hr_avg']:.0f}")
    if parsed.get("respiratory_rate")    is not None: parts.append(f"rr={parsed['respiratory_rate']:.1f}")
    return "  ".join(parts) if parts else "(minimal data)"


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Backfill historical Eight Sleep data.")
    parser.add_argument("--from", dest="start_from", metavar="YYYY-MM-DD",
                        help=f"Start date (inclusive). Defaults to {BACKFILL_START}.")
    parser.add_argument("--to", dest="end_at", metavar="YYYY-MM-DD",
                        help="End date (inclusive). Defaults to yesterday.")
    args = parser.parse_args()

    start_date = BACKFILL_START
    if args.start_from:
        try:
            start_date = date.fromisoformat(args.start_from)
        except ValueError:
            print(f"[ERROR] Invalid date: {args.start_from}", file=sys.stderr)
            sys.exit(1)

    end_date = date.today() - timedelta(days=1)
    if args.end_at:
        try:
            end_date = date.fromisoformat(args.end_at)
        except ValueError:
            print(f"[ERROR] Invalid date: {args.end_at}", file=sys.stderr)
            sys.exit(1)

    all_dates = []
    cursor = start_date
    while cursor <= end_date:
        all_dates.append(cursor)
        cursor += timedelta(days=1)
    total = len(all_dates)

    print(f"Eight Sleep backfill  {start_date} → {end_date}  ({total} days)")
    print(f"Table : life-platform  (region {REGION})")
    print(f"Pacing: {DAY_DELAY}s between days, proactive token refresh every {TOKEN_TTL_SECS//60}min")
    print("=" * 80, flush=True)

    secret = get_secret()
    secret = ensure_tokens(secret)
    token_refreshed_at = time.monotonic()

    success = 0
    no_data = 0
    errors  = 0

    for i, dt in enumerate(all_dates, 1):
        wake_date = dt.strftime("%Y-%m-%d")
        prefix    = f"[{i:5d}/{total}] {wake_date}"

        # Proactive token refresh
        if time.monotonic() - token_refreshed_at > TOKEN_TTL_SECS:
            print(f"\n  ↻ proactive token refresh...", end="", flush=True)
            try:
                secret = do_refresh(secret)
                token_refreshed_at = time.monotonic()
                print(" ok", flush=True)
            except Exception as ex:
                print(f"\n[FATAL] Token refresh failed: {ex}", file=sys.stderr)
                break

        print(f"{prefix} ...", end="", flush=True)

        try:
            parsed = ingest_with_retry(wake_date, secret)
            token_refreshed_at = time.monotonic()  # API call implies token is still valid

            result_str = fmt_result(parsed)
            print(f"\r{prefix}  {result_str}")

            if parsed:
                success += 1
            else:
                no_data += 1

        except urllib.error.HTTPError as ex:
            print(f"\r{prefix}  ✗ HTTP {ex.code}: {ex.reason}")
            errors += 1
        except Exception as ex:
            print(f"\r{prefix}  ✗ {type(ex).__name__}: {ex}")
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
        print(f"\nTo retry errors, re-run with: --from {start_date}")


if __name__ == "__main__":
    main()
