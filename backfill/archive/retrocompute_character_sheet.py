#!/usr/bin/env python3
"""
Character Sheet Retrocompute — v2.58.0
Backfills character sheet data from baseline date (2026-02-22) forward.

CRITICAL: Must run sequentially because levels depend on prior day's state.
Each day's computation uses the previous day's character_sheet record for
streak tracking, level changes, and XP accumulation.

Strategy:
  1. Load character_sheet config from local file (or S3)
  2. Batch-query all source data for the full date range (efficient)
  3. Process dates sequentially, maintaining rolling state
  4. For each date, assemble data dict with rolling windows
  5. Call character_engine.compute_character_sheet()
  6. Write to DynamoDB (SOURCE=character_sheet)

Usage:
  python3 retrocompute_character_sheet.py                     # Dry run (preview)
  python3 retrocompute_character_sheet.py --write             # Write to DynamoDB
  python3 retrocompute_character_sheet.py --write --force     # Overwrite existing
  python3 retrocompute_character_sheet.py --start 2026-02-22  # Custom start date
  python3 retrocompute_character_sheet.py --stats             # Data coverage only

Requires:
  - character_engine.py in same directory or PYTHONPATH
  - AWS credentials configured (same as other backfill scripts)
  - config/character_sheet.json (local) or S3 config
"""

import json
import sys
import os
import time
import argparse
import boto3
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from collections import defaultdict

# Add parent dir so we can import character_engine
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
from character_engine import (
    compute_character_sheet, store_character_sheet, fetch_character_sheet,
    _to_decimal, _from_decimal, ENGINE_VERSION
)

# ── AWS clients ──
dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
s3 = boto3.client("s3", region_name="us-west-2")
table = dynamodb.Table("life-platform")

# ── Config ──
BUCKET = "matthew-life-platform"
CONFIG_KEY = "config/character_sheet.json"
DEFAULT_START = "2026-04-01"  # Journey start / Character Sheet baseline
USER_PREFIX = "USER#matthew#SOURCE#"
THROTTLE_DELAY = 0.05  # seconds between writes
PILLAR_ORDER = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]


# ==============================================================================
# DATA LOADING — batch query entire date ranges per source
# ==============================================================================

def d2f(obj):
    """Convert DynamoDB Decimal to float recursively."""
    if isinstance(obj, list):    return [d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


def query_all_dates(source, start_date, end_date):
    """Query all records for a source in a date range. Returns dict keyed by date."""
    pk = USER_PREFIX + source
    records = {}
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
        "ExpressionAttributeValues": {
            ":pk": pk, ":s": "DATE#" + start_date, ":e": "DATE#" + end_date,
        },
    }
    while True:
        resp = table.query(**kwargs)
        for item in resp.get("Items", []):
            date_str = item.get("date") or item["sk"].replace("DATE#", "")
            records[date_str] = d2f(item)
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return records


def query_journal_entries(start_date, end_date):
    """Query journal entries. Returns dict of date -> list of entries."""
    pk = USER_PREFIX.replace("SOURCE#", "") + "SOURCE#notion"
    # Correct: pk should be USER#matthew#SOURCE#notion
    pk = "USER#matthew#SOURCE#notion"
    entries_by_date = defaultdict(list)
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
        "ExpressionAttributeValues": {
            ":pk": pk,
            ":s": "DATE#" + start_date + "#journal#",
            ":e": "DATE#" + end_date + "#journal#zzz",
        },
    }
    while True:
        resp = table.query(**kwargs)
        for item in resp.get("Items", []):
            sk = item["sk"]
            date_str = sk.split("#")[1]
            entries_by_date[date_str].append(d2f(item))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return dict(entries_by_date)


def load_config():
    """Load character_sheet config — try local file first, fall back to S3."""
    local_path = os.path.join(os.path.dirname(__file__), "..", "config", "character_sheet.json")
    if os.path.exists(local_path):
        with open(local_path) as f:
            config = json.load(f)
        print(f"  Config loaded from: {local_path}")
        return config

    try:
        resp = s3.get_object(Bucket=BUCKET, Key=CONFIG_KEY)
        config = json.loads(resp["Body"].read().decode("utf-8"))
        print(f"  Config loaded from: s3://{BUCKET}/{CONFIG_KEY}")
        return config
    except Exception as e:
        print(f"  ERROR: Could not load config from local or S3: {e}")
        sys.exit(1)


def load_latest_weight(withings_data, date_str):
    """Find the most recent weight on or before date_str from withings data."""
    best_date = None
    best_weight = None
    for d, rec in withings_data.items():
        if d <= date_str:
            w = None
            for field in ("weight_kg", "weight_lbs", "weight"):
                v = rec.get(field)
                if v is not None:
                    try:
                        w = float(v)
                    except (ValueError, TypeError):
                        continue
                    break
            if w is not None:
                # Convert kg to lbs if needed
                if w < 200:  # likely kg
                    w = w * 2.20462
                if best_date is None or d > best_date:
                    best_date = d
                    best_weight = w
    return best_weight


def load_latest_labs(labs_data, date_str):
    """Find the most recent lab results on or before date_str."""
    best_date = None
    best_rec = None
    for d, rec in labs_data.items():
        if d <= date_str:
            if best_date is None or d > best_date:
                best_date = d
                best_rec = rec
    return best_rec


# ==============================================================================
# DATA ASSEMBLY — build the data dict that character_engine expects
# ==============================================================================

def assemble_data_for_date(date_str, sources, journal_entries, all_dates_idx):
    """Build the data dict that character_engine.compute_character_sheet() expects."""
    data = {"date": date_str}

    # ── Primary source records (today) ──
    data["sleep"] = sources["whoop"].get(date_str)
    data["whoop"] = sources["whoop"].get(date_str)
    data["macrofactor"] = sources["macrofactor"].get(date_str)
    data["apple"] = sources["apple_health"].get(date_str)
    data["journal"] = sources.get("notion_daily", {}).get(date_str)
    data["journal_entries"] = journal_entries.get(date_str, [])

    # ── Habit scores (from DDB partition) ──
    data["habit_scores"] = sources["habit_scores"].get(date_str)

    # ── State of Mind ──
    data["state_of_mind"] = sources.get("state_of_mind", {}).get(date_str)

    # ── Rolling windows ──
    dt = datetime.strptime(date_str, "%Y-%m-%d")

    # Sleep 14d (for onset consistency)
    sleep_14d = []
    for i in range(14):
        d = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
        rec = sources["whoop"].get(d)
        if rec:
            sleep_14d.append(rec)
    data["sleep_14d"] = sleep_14d

    # Strava 7d (for training frequency, zone2, diversity)
    strava_7d = []
    for i in range(7):
        d = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
        rec = sources["strava"].get(d)
        if rec:
            strava_7d.append(rec)
    data["strava_7d"] = strava_7d

    # Strava 42d (for progressive overload / CTL trend)
    strava_42d = []
    for i in range(42):
        d = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
        rec = sources["strava"].get(d)
        if rec:
            strava_42d.append(rec)
    data["strava_42d"] = strava_42d

    # MacroFactor 14d (for nutrition consistency)
    mf_14d = []
    for i in range(14):
        d = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
        rec = sources["macrofactor"].get(d)
        if rec:
            mf_14d.append(rec)
    data["macrofactor_14d"] = mf_14d

    # Withings 30d (for body fat trajectory)
    withings_30d = []
    for i in range(30):
        d = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
        rec = sources["withings"].get(d)
        if rec:
            withings_30d.append(rec)
    data["withings_30d"] = withings_30d

    # Latest weight (search backwards)
    data["latest_weight"] = load_latest_weight(sources["withings"], date_str)

    # Latest labs (search backwards)
    data["labs_latest"] = load_latest_labs(sources.get("labs", {}), date_str)

    # BP data
    data["bp_data"] = sources.get("bp", {}).get(date_str)

    # Journal 14d count
    j14d_count = 0
    for i in range(14):
        d = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
        if d in journal_entries and journal_entries[d]:
            j14d_count += 1
    data["journal_14d_count"] = j14d_count

    # Data completeness
    expected = ["whoop", "macrofactor", "apple_health", "strava", "habitify"]
    present = 0
    for src in expected:
        if sources.get(src, {}).get(date_str):
            present += 1
    data["data_completeness_pct"] = round((present / len(expected)) * 100, 1)

    return data


# ==============================================================================
# MAIN RETROCOMPUTE
# ==============================================================================

def run_retrocompute(start_date, end_date, config, write=False, force=False, stats_only=False):
    print(f"{'=' * 60}")
    print(f"Character Sheet Retrocompute — engine v{ENGINE_VERSION}")
    print(f"Range: {start_date} → {end_date}")
    print(f"Mode:  {'WRITE' if write else 'DRY RUN'}{' (force overwrite)' if force else ''}")
    print(f"{'=' * 60}\n")

    # ── Extended start for rolling windows ──
    # Need 42 days before start for Strava CTL trend
    dt_start = datetime.strptime(start_date, "%Y-%m-%d")
    extended_start = (dt_start - timedelta(days=42)).strftime("%Y-%m-%d")

    # ── Batch query all sources ──
    print("[1/3] Batch-querying data sources...")
    t0 = time.time()

    sources = {}
    source_queries = [
        ("whoop", "whoop"),
        ("strava", "strava"),
        ("macrofactor", "macrofactor"),
        ("apple_health", "apple_health"),
        ("withings", "withings"),
        ("habitify", "habitify"),
        ("habit_scores", "habit_scores"),
        ("garmin", "garmin"),
        ("state_of_mind", "state_of_mind"),
        ("labs", "labs"),
        ("bp", "blood_pressure"),
    ]

    for name, ddb_source in source_queries:
        sources[name] = query_all_dates(ddb_source, extended_start, end_date)
        print(f"  {name}: {len(sources[name]):,} records")

    # Notion daily summaries
    sources["notion_daily"] = query_all_dates("notion", extended_start, end_date)
    print(f"  notion_daily: {len(sources['notion_daily']):,} records")

    journal_entries = query_journal_entries(extended_start, end_date)
    print(f"  journal_entries: {len(journal_entries):,} days with entries")

    # Check existing character_sheet records
    existing = query_all_dates("character_sheet", start_date, end_date)
    print(f"  existing character_sheet: {len(existing):,} records")

    t_query = time.time() - t0
    print(f"\n  Query time: {t_query:.1f}s\n")

    # ── Generate date range ──
    dt_end = datetime.strptime(end_date, "%Y-%m-%d")
    all_dates = []
    d = dt_start
    while d <= dt_end:
        all_dates.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)

    if stats_only:
        print_coverage_stats(all_dates, sources, journal_entries)
        return

    # ── Sequential computation ──
    print(f"[2/3] Computing character sheets for {len(all_dates):,} dates (sequential)...\n")

    previous_state = None
    raw_score_histories = {p: [] for p in PILLAR_ORDER}
    results = []
    skipped_existing = 0
    computed = 0
    events_total = 0
    level_history = []

    for i, date_str in enumerate(all_dates):
        # Skip existing unless --force
        if not force and date_str in existing:
            # Still need to load state for continuity
            prev = existing[date_str]
            previous_state = prev
            # Rebuild raw_score histories from existing data
            for p in PILLAR_ORDER:
                pdata = prev.get(f"pillar_{p}", {})
                raw = pdata.get("raw_score")
                if raw is not None:
                    raw_score_histories[p].append(float(raw))
                else:
                    raw_score_histories[p].append(40.0)
            skipped_existing += 1
            continue

        # Assemble data for this date
        data = assemble_data_for_date(date_str, sources, journal_entries, i)

        # Compute character sheet
        try:
            record = compute_character_sheet(data, previous_state, raw_score_histories, config)
        except Exception as e:
            print(f"  ERROR computing {date_str}: {e}")
            # Use neutral scores to maintain continuity
            for p in PILLAR_ORDER:
                raw_score_histories[p].append(40.0)
            continue

        # Update histories
        for p in PILLAR_ORDER:
            pdata = record.get(f"pillar_{p}", {})
            raw = pdata.get("raw_score")
            raw_score_histories[p].append(float(raw) if raw is not None else 40.0)

        # Track events
        events = record.get("level_events", [])
        events_total += len(events)
        if events:
            for ev in events:
                level_history.append({"date": date_str, **ev})

        results.append(record)
        previous_state = record
        computed += 1

        # Progress update
        if (i + 1) % 5 == 0 or i == len(all_dates) - 1:
            char_lv = record.get("character_level", 1)
            char_tier = record.get("character_tier", "Foundation")
            pillars_str = " | ".join(
                f"{p[:3]}:{record.get(f'pillar_{p}', {}).get('level', 1)}"
                for p in PILLAR_ORDER[:4]
            )
            print(f"  {date_str}: Level {char_lv} ({char_tier}) [{pillars_str}]"
                  f"{' +' + str(len(events)) + ' events' if events else ''}")

    # ── Summary ──
    print(f"\n{'=' * 60}")
    print(f"RESULTS SUMMARY")
    print(f"{'=' * 60}")
    print(f"  Total dates in range:    {len(all_dates):,}")
    print(f"  Skipped (existing):      {skipped_existing:,}")
    print(f"  Computed:                {computed:,}")
    print(f"  Level events:            {events_total:,}")

    if results:
        latest = results[-1]
        print(f"\n  Latest ({latest['date']}):")
        print(f"    Character Level: {latest.get('character_level', 1)} "
              f"({latest.get('character_tier_emoji', '🔨')} {latest.get('character_tier', 'Foundation')})")
        print(f"    Total XP: {latest.get('character_xp', 0)}")
        print()
        for p in PILLAR_ORDER:
            pdata = latest.get(f"pillar_{p}", {})
            print(f"    {p:>15}: Level {pdata.get('level', 1):3d} "
                  f"({pdata.get('tier_emoji', '🔨')} {pdata.get('tier', 'Foundation'):12s}) "
                  f"raw={pdata.get('raw_score', '?'):>5}  xp_total={pdata.get('xp_total', 0)}")

        if level_history:
            print(f"\n  Level Events ({len(level_history)}):")
            for ev in level_history[-20:]:
                etype = ev.get("type", "")
                pillar = ev.get("pillar", "overall").capitalize()
                if "tier" in etype:
                    print(f"    {ev['date']}: {pillar} {ev.get('old_tier')} → {ev.get('new_tier')}")
                elif "character" in etype:
                    print(f"    {ev['date']}: Character Level {ev.get('old_level')} → {ev.get('new_level')}")
                else:
                    arrow = "↑" if "up" in etype else "↓"
                    print(f"    {ev['date']}: {arrow} {pillar} Level {ev.get('old_level')} → {ev.get('new_level')}")
            if len(level_history) > 20:
                print(f"    ... and {len(level_history) - 20} more")

        active = latest.get("active_effects", [])
        if active:
            print(f"\n  Active Effects:")
            for eff in active:
                print(f"    {eff.get('emoji', '')} {eff['name']}")

    # ── Write ──
    if write and results:
        print(f"\n[3/3] Writing {len(results):,} records to DynamoDB...")
        write_results(results)
        print("Done!")
    elif not write and results:
        print(f"\nDRY RUN — no writes performed. Use --write to persist.\n")


def write_results(results):
    """Write character sheet records to DynamoDB."""
    written = 0
    errors = 0
    t0 = time.time()

    for i, record in enumerate(results):
        try:
            item = {
                "pk": "USER#matthew#SOURCE#character_sheet",
                "sk": "DATE#" + record["date"],
            }
            item.update(_to_decimal(record))
            table.put_item(Item=item)
            written += 1

            if (i + 1) % 10 == 0:
                elapsed = time.time() - t0
                rate = written / elapsed if elapsed > 0 else 0
                remaining = (len(results) - i - 1) / rate if rate > 0 else 0
                print(f"  {written:,} / {len(results):,} written "
                      f"({rate:.0f}/s, ~{remaining:.0f}s remaining)")

            time.sleep(THROTTLE_DELAY)

        except Exception as e:
            errors += 1
            print(f"  ERROR writing {record.get('date', '?')}: {e}")
            if errors > 10:
                print("  Too many errors, stopping.")
                break

    elapsed = time.time() - t0
    print(f"\n  Written: {written:,} in {elapsed:.1f}s "
          f"({written / elapsed:.0f}/s)" if elapsed > 0 else "")
    if errors:
        print(f"  Errors: {errors}")


def print_coverage_stats(all_dates, sources, journal_entries):
    """Print data coverage stats relevant to character sheet computation."""
    print(f"\n{'=' * 60}")
    print(f"DATA COVERAGE FOR CHARACTER SHEET")
    print(f"{'=' * 60}\n")

    # Source coverage
    print("  Records by source:")
    for name in ["whoop", "strava", "macrofactor", "apple_health", "withings",
                  "habitify", "habit_scores", "garmin", "state_of_mind", "labs", "bp"]:
        data = sources.get(name, {})
        in_range = sum(1 for d in all_dates if d in data)
        pct = in_range / len(all_dates) * 100 if all_dates else 0
        print(f"    {name:>20}: {in_range:>4} / {len(all_dates)} days ({pct:.0f}%)")

    j_count = sum(1 for d in all_dates if d in journal_entries)
    print(f"    {'journal':>20}: {j_count:>4} / {len(all_dates)} days "
          f"({j_count / len(all_dates) * 100:.0f}%)")
    print()

    # Pillar data availability
    print("  Pillar data availability (which pillars can score on which days):")
    pillar_sources = {
        "Sleep": ["whoop"],
        "Movement": ["strava", "apple_health"],
        "Nutrition": ["macrofactor", "withings"],
        "Metabolic": ["withings", "apple_health"],
        "Mind": ["habit_scores", "state_of_mind"],
        "Relationships": ["journal_entries"],
    }
    for pillar, srcs in pillar_sources.items():
        days_with_any = 0
        for d in all_dates:
            has_data = False
            for src in srcs:
                if src == "journal_entries":
                    has_data = d in journal_entries
                else:
                    has_data = d in sources.get(src, {})
                if has_data:
                    break
            if has_data:
                days_with_any += 1
        pct = days_with_any / len(all_dates) * 100 if all_dates else 0
        print(f"    {pillar:>15}: {days_with_any:>4} / {len(all_dates)} days ({pct:.0f}%)")
    print()


# ==============================================================================
# CLI
# ==============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Retrocompute character sheets from baseline forward")
    parser.add_argument("--write", action="store_true", help="Write to DynamoDB (default: dry run)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing records")
    parser.add_argument("--start", default=DEFAULT_START,
                       help=f"Start date YYYY-MM-DD (default: {DEFAULT_START})")
    parser.add_argument("--end", default=None,
                       help="End date YYYY-MM-DD (default: yesterday)")
    parser.add_argument("--stats", action="store_true", help="Just show data coverage stats")
    args = parser.parse_args()

    end_date = args.end or (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()

    print("[0/3] Loading config...")
    config = load_config()
    print(f"  Pillars: {list(config.get('pillars', {}).keys())}")
    print(f"  Baseline: {config.get('baseline', {}).get('start_date', '?')}")
    print()

    if args.stats:
        run_retrocompute(args.start, end_date, config, stats_only=True)
    else:
        run_retrocompute(args.start, end_date, config, write=args.write, force=args.force)
