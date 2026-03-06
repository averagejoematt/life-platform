#!/usr/bin/env python3
"""
Backfill habit_scores partition from raw Habitify data + habit_registry.

Applies the same tier-weighted scoring logic as daily_brief_lambda.py v2.47.0:
  - Tier 0 (non-negotiable): 3x weight, binary
  - Tier 1 (high priority): 1x weight, binary
  - Tier 2 (aspirational): 0.5x weight, 7-day rolling frequency
  - Vices: streak tracking
  - Synergy groups: per-group completion %
  - applicable_days awareness (weekday-only, post_training)

Usage:
  python3 backfill_habit_scores.py                     # backfill all available habitify dates
  python3 backfill_habit_scores.py --dry-run            # preview without writing
  python3 backfill_habit_scores.py --start 2026-02-23   # backfill from specific date
  python3 backfill_habit_scores.py --force               # overwrite existing records

Requires: boto3 (pip install boto3)
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3

# --- Config ---
REGION = "us-west-2"
TABLE_NAME = "life-platform"
USER_ID = "matthew"
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
PROFILE_PK = f"USER#{USER_ID}"

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)


def fetch_profile():
    resp = table.get_item(Key={"pk": PROFILE_PK, "sk": "PROFILE#v1"})
    item = resp.get("Item")
    if item:
        return json.loads(json.dumps(item, default=str))
    return None


def fetch_date(source, date_str):
    resp = table.get_item(Key={"pk": USER_PREFIX + source, "sk": "DATE#" + date_str})
    item = resp.get("Item")
    if item:
        return json.loads(json.dumps(item, default=str))
    return None


def fetch_all_habitify_dates():
    """Get all dates with habitify data."""
    resp = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={
            ":pk": USER_PREFIX + "habitify",
            ":prefix": "DATE#",
        },
        ProjectionExpression="sk",
    )
    dates = []
    for item in resp.get("Items", []):
        sk = item.get("sk", "")
        if sk.startswith("DATE#"):
            dates.append(sk.replace("DATE#", ""))
    return sorted(dates)


def fetch_existing_habit_scores():
    """Get dates that already have habit_scores records."""
    resp = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={
            ":pk": USER_PREFIX + "habit_scores",
            ":prefix": "DATE#",
        },
        ProjectionExpression="sk",
    )
    return {item["sk"].replace("DATE#", "") for item in resp.get("Items", [])}


def fetch_habitify_range(start_date, end_date):
    """Fetch habitify records in a date range for 7-day lookback."""
    resp = table.query(
        KeyConditionExpression="pk = :pk AND sk BETWEEN :start AND :end",
        ExpressionAttributeValues={
            ":pk": USER_PREFIX + "habitify",
            ":start": f"DATE#{start_date}",
            ":end": f"DATE#{end_date}",
        },
    )
    items = resp.get("Items", [])
    return [json.loads(json.dumps(item, default=str)) for item in items]


def score_habits_registry(habitify_rec, habitify_7d, strava_rec, registry, date_str):
    """
    Tier-weighted habit scoring — mirrors daily_brief_lambda.py score_habits_registry().

    Returns (composite_score, details_dict) or (None, {}) if no data.
    """
    habits_map = habitify_rec.get("habits", {})
    if not registry or not habits_map:
        return None, {}

    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        is_weekday = dt.weekday() < 5
    except Exception:
        is_weekday = True

    tier_scores = {0: [], 1: [], 2: []}
    tier_status = {0: {}, 1: {}, 2: {}}
    vice_status = {}
    tier_weights = {0: 3.0, 1: 1.0, 2: 0.5}

    for habit_name, meta in registry.items():
        if meta.get("status") != "active":
            continue

        tier = int(meta.get("tier", 2))
        applicable = meta.get("applicable_days", "daily")
        is_vice = meta.get("vice", False)
        sw = float(meta.get("scoring_weight", 1.0))

        # Skip if not applicable today
        if applicable == "weekdays" and not is_weekday:
            continue
        if applicable == "post_training":
            has_activities = strava_rec and strava_rec.get("activities")
            if not has_activities:
                continue

        done = habits_map.get(habit_name, 0)
        is_done = float(done) >= 1 if done is not None else False

        if is_vice:
            vice_status[habit_name] = is_done

        if tier in (0, 1):
            habit_score = 100.0 if is_done else 0.0
            tier_scores[tier].append(habit_score * sw)
            tier_status[tier][habit_name] = is_done
        else:
            target_freq = int(meta.get("target_frequency", 7))
            week_count = 1 if is_done else 0
            for day_rec in (habitify_7d or [])[-6:]:
                day_habits = day_rec.get("habits", {}) if isinstance(day_rec, dict) else {}
                d = day_habits.get(habit_name, 0)
                if d is not None and float(d) >= 1:
                    week_count += 1
            freq_score = min(100.0, round(week_count / max(target_freq, 1) * 100))
            tier_scores[2].append(freq_score * sw)
            tier_status[2][habit_name] = is_done

    # Weighted composite
    weighted_sum = 0.0
    total_weight = 0.0
    for tier_num, scores in tier_scores.items():
        if scores:
            tier_avg = sum(scores) / len(scores)
            w = tier_weights[tier_num]
            weighted_sum += tier_avg * w
            total_weight += w

    if total_weight == 0:
        return None, {}

    composite = max(0, min(100, round(weighted_sum / total_weight)))

    t0_done = sum(1 for v in tier_status[0].values() if v)
    t0_total = len(tier_status[0])
    t1_done = sum(1 for v in tier_status[1].values() if v)
    t1_total = len(tier_status[1])
    vices_held = sum(1 for v in vice_status.values() if v)
    vices_total = len(vice_status)

    details = {
        "tier_status": tier_status,
        "vice_status": vice_status,
        "tier0": {"done": t0_done, "total": t0_total},
        "tier1": {"done": t1_done, "total": t1_total},
        "vices": {"held": vices_held, "total": vices_total},
        "composite_method": "tier_weighted",
    }
    return composite, details


def compute_vice_streaks(registry, date_str):
    """Compute per-vice streaks by walking backwards from date_str."""
    vice_habits = [
        name for name, meta in registry.items()
        if meta.get("status") == "active" and meta.get("vice", False)
    ]
    if not vice_habits:
        return {}

    streaks = {v: 0 for v in vice_habits}
    broken = {v: False for v in vice_habits}

    for i in range(0, 90):
        dt = datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=i)
        d = dt.strftime("%Y-%m-%d")
        is_weekday = dt.weekday() < 5

        rec = fetch_date("habitify", d)
        if not rec:
            rec = fetch_date("chronicling", d)
        if not rec:
            break

        habits_map = rec.get("habits", {})
        for v in vice_habits:
            if broken[v]:
                continue
            meta = registry.get(v, {})
            applicable = meta.get("applicable_days", "daily")
            if applicable == "weekdays" and not is_weekday:
                continue
            done = habits_map.get(v, 0)
            if done is not None and float(done) >= 1:
                streaks[v] += 1
            else:
                broken[v] = True

    return streaks


def build_habit_score_item(date_str, composite, details, vice_streaks, registry):
    """Build DynamoDB item matching the habit_scores schema."""
    t0 = details.get("tier0", {})
    t1 = details.get("tier1", {})
    vices = details.get("vices", {})
    tier_status = details.get("tier_status", {})

    missed_t0 = [name for name, done in tier_status.get(0, {}).items() if not done]

    # Synergy groups
    all_status = {}
    for tier_habits in tier_status.values():
        all_status.update(tier_habits)

    synergy_groups = {}
    for h_name, meta in registry.items():
        sg = meta.get("synergy_group")
        if not sg or meta.get("status") != "active":
            continue
        synergy_groups.setdefault(sg, {"done": 0, "total": 0})
        synergy_groups[sg]["total"] += 1
        if all_status.get(h_name, False):
            synergy_groups[sg]["done"] += 1

    sg_pcts = {}
    for sg, counts in synergy_groups.items():
        if counts["total"] > 0:
            sg_pcts[sg] = round(counts["done"] / counts["total"], 3)

    item = {
        "pk": USER_PREFIX + "habit_scores",
        "sk": "DATE#" + date_str,
        "date": date_str,
        "scoring_method": "tier_weighted_v1",
        "composite_score": Decimal(str(composite)),
        "tier0_done": t0.get("done", 0),
        "tier0_total": t0.get("total", 0),
        "tier0_pct": Decimal(str(round(t0["done"] / t0["total"], 3))) if t0.get("total") else None,
        "tier1_done": t1.get("done", 0),
        "tier1_total": t1.get("total", 0),
        "tier1_pct": Decimal(str(round(t1["done"] / t1["total"], 3))) if t1.get("total") else None,
        "vices_held": vices.get("held", 0),
        "vices_total": vices.get("total", 0),
        "missed_tier0": missed_t0 if missed_t0 else None,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "source": "backfill",
    }

    if vice_streaks:
        item["vice_streaks"] = json.loads(json.dumps(vice_streaks), parse_float=Decimal)
    if sg_pcts:
        item["synergy_groups"] = json.loads(json.dumps(sg_pcts), parse_float=Decimal)

    # Remove None values
    return {k: v for k, v in item.items() if v is not None}


def main():
    parser = argparse.ArgumentParser(description="Backfill habit_scores from Habitify data")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--force", action="store_true", help="Overwrite existing records")
    parser.add_argument("--start", type=str, help="Start date YYYY-MM-DD (default: earliest habitify)")
    parser.add_argument("--end", type=str, help="End date YYYY-MM-DD (default: latest habitify)")
    args = parser.parse_args()

    print("=" * 60)
    print("Habit Scores Backfill — v2.47.1")
    print("=" * 60)

    # 1. Load profile + registry
    profile = fetch_profile()
    if not profile:
        print("ERROR: No profile found")
        sys.exit(1)

    registry = profile.get("habit_registry", {})
    if not registry:
        print("ERROR: No habit_registry in profile")
        sys.exit(1)

    active_count = sum(1 for m in registry.values() if m.get("status") == "active")
    vice_count = sum(1 for m in registry.values() if m.get("vice", False))
    print(f"Registry: {active_count} active habits, {vice_count} vices")

    # 2. Find dates to process
    all_dates = fetch_all_habitify_dates()
    if not all_dates:
        print("No habitify data found. Nothing to backfill.")
        sys.exit(0)

    print(f"Habitify data: {len(all_dates)} days ({all_dates[0]} → {all_dates[-1]})")

    if args.start:
        all_dates = [d for d in all_dates if d >= args.start]
    if args.end:
        all_dates = [d for d in all_dates if d <= args.end]

    if not all_dates:
        print("No dates in specified range.")
        sys.exit(0)

    # 3. Check existing records
    existing = fetch_existing_habit_scores()
    if existing:
        print(f"Existing habit_scores: {len(existing)} records")

    if not args.force:
        dates_to_process = [d for d in all_dates if d not in existing]
        skipped = len(all_dates) - len(dates_to_process)
        if skipped:
            print(f"Skipping {skipped} dates (already have scores, use --force to overwrite)")
    else:
        dates_to_process = all_dates

    if not dates_to_process:
        print("All dates already have habit_scores. Use --force to overwrite.")
        sys.exit(0)

    print(f"\nProcessing {len(dates_to_process)} dates: {dates_to_process[0]} → {dates_to_process[-1]}")
    if args.dry_run:
        print("[DRY RUN — no writes]")
    print()

    # 4. Process each date
    written = 0
    errors = 0

    for date_str in dates_to_process:
        try:
            # Fetch habitify record
            habitify_rec = fetch_date("habitify", date_str)
            if not habitify_rec:
                print(f"  {date_str}: SKIP (no habitify data)")
                continue

            # Fetch 7-day lookback for Tier 2 frequency scoring
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            lookback_start = (dt - timedelta(days=6)).strftime("%Y-%m-%d")
            habitify_7d = fetch_habitify_range(lookback_start, date_str)
            # Remove current day from lookback (it's added separately in scoring)
            habitify_7d = [r for r in habitify_7d if r.get("sk", "").replace("DATE#", "") != date_str]

            # Fetch strava for post_training awareness
            strava_rec = fetch_date("strava", date_str)

            # Score
            composite, details = score_habits_registry(
                habitify_rec, habitify_7d, strava_rec, registry, date_str
            )

            if composite is None:
                print(f"  {date_str}: SKIP (scoring returned None)")
                continue

            # Vice streaks
            vice_streaks = compute_vice_streaks(registry, date_str)

            # Build item
            item = build_habit_score_item(date_str, composite, details, vice_streaks, registry)

            t0 = details.get("tier0", {})
            t1 = details.get("tier1", {})
            vices = details.get("vices", {})

            status = "WRITE" if not args.dry_run else "DRY"
            print(
                f"  {date_str}: [{status}] score={composite} "
                f"T0={t0.get('done',0)}/{t0.get('total',0)} "
                f"T1={t1.get('done',0)}/{t1.get('total',0)} "
                f"vices={vices.get('held',0)}/{vices.get('total',0)}"
            )

            if not args.dry_run:
                table.put_item(Item=item)
                written += 1

        except Exception as e:
            print(f"  {date_str}: ERROR — {e}")
            errors += 1

    # 5. Summary
    print()
    print("=" * 60)
    print(f"Done. Written: {written} | Skipped: {len(dates_to_process) - written - errors} | Errors: {errors}")
    if args.dry_run:
        print("(Dry run — re-run without --dry-run to write)")
    print("=" * 60)


if __name__ == "__main__":
    main()
