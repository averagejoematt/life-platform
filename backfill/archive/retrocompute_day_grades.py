#!/usr/bin/env python3
"""
Day Grade Retrocompute — v2.23.0
Backfills historical day grades using algo v1.1 for every day with data.

Strategy:
  1. Batch-query each data source for the full date range (efficient — ~7 queries vs ~6K gets)
  2. Index all records by date in memory
  3. For each date, assemble data, run 8 component scorers, compute weighted grade
  4. Write to DynamoDB (SOURCE=day_grade), skip dates that already have a grade

Usage:
  python3 retrocompute_day_grades.py                     # Dry run (preview)
  python3 retrocompute_day_grades.py --write             # Write to DynamoDB
  python3 retrocompute_day_grades.py --write --force      # Overwrite existing grades
  python3 retrocompute_day_grades.py --start 2025-01-01   # Custom start date
  python3 retrocompute_day_grades.py --stats              # Just show stats, no processing

Scoring algorithm matches daily_brief_lambda.py v2.2.3 (algo v1.1):
  - Journal returns None when no entries (not 0)
  - Hydration treats <118ml as not tracked
  - Strava activity deduplication applied
"""

import json
import sys
import time
import argparse
import boto3
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from collections import defaultdict

# -- AWS clients ---------------------------------------------------------------
dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
table    = dynamodb.Table("life-platform")

# -- Config --------------------------------------------------------------------
ALGO_VERSION = "1.1"
DEFAULT_START = "2023-07-23"  # Eight Sleep start (first sleep data)
BATCH_WRITE_SIZE = 25         # DynamoDB batch limit
THROTTLE_DELAY = 0.1          # seconds between batch writes


# ==============================================================================
# SCORING FUNCTIONS (exact copy from daily_brief_lambda.py v2.2.3)
# ==============================================================================

def safe_float(rec, field, default=None):
    if rec and field in rec:
        try: return float(rec[field])
        except Exception: return default
    return default

def clamp(val, lo=0, hi=100):
    return max(lo, min(hi, val))

def score_sleep(data, profile):
    sleep = data.get("sleep")
    if not sleep:
        return None, {}
    sleep_score = safe_float(sleep, "sleep_score")
    efficiency = safe_float(sleep, "sleep_efficiency_pct")
    duration_hrs = safe_float(sleep, "sleep_duration_hours")
    deep_pct = safe_float(sleep, "deep_pct")
    rem_pct = safe_float(sleep, "rem_pct")
    target_hrs = profile.get("sleep_target_hours_ideal", 7.5)
    details = {"sleep_score": sleep_score, "efficiency": efficiency,
               "duration_hrs": duration_hrs, "target_hrs": target_hrs,
               "deep_pct": deep_pct, "rem_pct": rem_pct}
    parts, weights = [], []
    if sleep_score is not None:
        parts.append(sleep_score * 0.40); weights.append(0.40)
    if efficiency is not None:
        parts.append(efficiency * 0.30); weights.append(0.30)
    if duration_hrs is not None:
        dur_score = clamp(100 - (abs(duration_hrs - target_hrs) / 2.0) * 100)
        parts.append(dur_score * 0.30); weights.append(0.30)
    if not weights:
        return None, details
    return clamp(round(sum(parts) / sum(weights))), details

def score_recovery(data, profile):
    recovery = safe_float(data.get("whoop"), "recovery_score")
    if recovery is None:
        return None, {}
    return clamp(round(recovery)), {"recovery_score": recovery}

def score_nutrition(data, profile):
    mf = data.get("macrofactor")
    if not mf:
        return None, {}
    cal = safe_float(mf, "total_calories_kcal")
    protein = safe_float(mf, "total_protein_g")
    fat = safe_float(mf, "total_fat_g")
    carbs = safe_float(mf, "total_carbs_g")
    cal_target = profile.get("calorie_target", 1800)
    protein_target = profile.get("protein_target_g", 190)
    protein_floor = profile.get("protein_floor_g", 170)
    cal_tolerance = profile.get("calorie_tolerance_pct", 10) / 100
    cal_penalty = profile.get("calorie_penalty_threshold_pct", 25) / 100
    details = {"calories": cal, "protein_g": protein, "fat_g": fat, "carbs_g": carbs}
    parts, weights = [], []
    if cal is not None and cal_target:
        pct_off = abs(cal - cal_target) / cal_target
        if pct_off <= cal_tolerance: cal_score = 100
        elif pct_off >= cal_penalty: cal_score = 0
        else: cal_score = 100 * (1 - (pct_off - cal_tolerance) / (cal_penalty - cal_tolerance))
        if cal > cal_target * (1 + cal_tolerance):
            cal_score = max(0, cal_score - 15)
        cal_score = clamp(round(cal_score))
        parts.append(cal_score * 0.40); weights.append(0.40)
    if protein is not None:
        if protein >= protein_target: prot_score = 100
        elif protein >= protein_floor:
            prot_score = 80 + 20 * (protein - protein_floor) / (protein_target - protein_floor)
        else: prot_score = max(0, 80 * protein / protein_floor)
        prot_score = clamp(round(prot_score))
        parts.append(prot_score * 0.40); weights.append(0.40)
    fat_target = profile.get("fat_target_g", 60)
    carb_target = profile.get("carb_target_g", 125)
    if fat is not None and carbs is not None:
        fat_diff = abs(fat - fat_target) / fat_target if fat_target else 0
        carb_diff = abs(carbs - carb_target) / carb_target if carb_target else 0
        macro_score = clamp(round(100 - (fat_diff + carb_diff) * 50))
        parts.append(macro_score * 0.20); weights.append(0.20)
    if not weights:
        return None, details
    return clamp(round(sum(parts) / sum(weights))), details

def score_movement(data, profile):
    step_target = profile.get("step_target", 7000)
    details = {}
    parts, weights = [], []
    strava = data.get("strava")
    if strava:
        act_count = safe_float(strava, "activity_count") or 0
        total_time = safe_float(strava, "total_moving_time_seconds") or 0
        if act_count > 0:
            exercise_score = min(100, 70 + (total_time / 60) * 0.5)
        else:
            exercise_score = 0
    else:
        exercise_score = 0
    exercise_score = clamp(round(exercise_score))
    parts.append(exercise_score * 0.50); weights.append(0.50)
    details["exercise_score"] = exercise_score
    apple = data.get("apple")
    steps = safe_float(apple, "steps") if apple else None
    if steps is not None:
        step_score = clamp(round(min(100, steps / step_target * 100)))
        parts.append(step_score * 0.50); weights.append(0.50)
        details["step_score"] = step_score
        details["steps"] = round(steps)
    if not weights:
        return None, details
    return clamp(round(sum(parts) / sum(weights))), details

def score_habits_mvp(data, profile):
    habitify = data.get("habitify")
    if not habitify:
        # Also check chronicling for pre-Habitify era
        chronicling = data.get("chronicling")
        if not chronicling:
            return None, {}
        # Chronicling has different schema — use completion_pct if available
        completion = safe_float(chronicling, "completion_pct")
        if completion is not None:
            score = clamp(round(completion * 100))
            return score, {"chronicling": True, "completion_pct": completion}
        return None, {}
    habits_map = habitify.get("habits", {})
    mvp_list = profile.get("mvp_habits", [])
    if not mvp_list:
        return None, {}
    completed = 0
    for habit_name in mvp_list:
        done = habits_map.get(habit_name, 0)
        if done is not None and float(done) >= 1:
            completed += 1
    score = clamp(round(completed / len(mvp_list) * 100))
    return score, {"completed": completed, "total": len(mvp_list)}

def score_hydration(data, profile):
    apple = data.get("apple")
    water_ml = safe_float(apple, "water_intake_ml") if apple else None
    target_ml = profile.get("water_target_ml", 2957)
    # v1.1: Minimum 118ml (4oz) to count as tracked
    if water_ml is None or water_ml < 118:
        return None, {}
    score = clamp(round(min(100, water_ml / target_ml * 100)))
    return score, {"water_ml": round(water_ml)}

def score_journal(data, profile):
    entries = data.get("journal_entries", [])
    # v1.1: Return None when no entries (not 0)
    if not entries:
        return None, {"entries": 0}
    templates = set()
    for e in entries:
        t = (e.get("template") or "").lower()
        if t:
            templates.add(t)
    has_morning = "morning" in templates
    has_evening = "evening" in templates
    if has_morning and has_evening: score = 100
    elif has_morning or has_evening: score = 60
    else: score = 40
    return score, {"entries": len(entries), "templates": list(templates)}

def score_glucose(data, profile):
    apple = data.get("apple")
    if not apple:
        return None, {}
    tir = safe_float(apple, "blood_glucose_time_in_range_pct")
    avg_glucose = safe_float(apple, "blood_glucose_avg")
    std_dev = safe_float(apple, "blood_glucose_std_dev")
    if tir is None and avg_glucose is None:
        return None, {}
    details = {"tir_pct": tir, "avg_glucose": avg_glucose, "std_dev": std_dev}
    parts, weights = [], []
    if tir is not None:
        if tir >= 95: tir_score = 100
        elif tir >= 90: tir_score = 80 + (tir - 90) * 4
        elif tir >= 70: tir_score = max(0, 80 * (tir - 70) / 20)
        else: tir_score = 0
        parts.append(tir_score * 0.50); weights.append(0.50)
    if avg_glucose is not None:
        if avg_glucose < 95: glu_score = 100
        elif avg_glucose < 100: glu_score = 80 + (100 - avg_glucose) * 4
        elif avg_glucose < 140: glu_score = max(0, 80 * (140 - avg_glucose) / 40)
        else: glu_score = 0
        parts.append(glu_score * 0.30); weights.append(0.30)
    if std_dev is not None:
        if std_dev < 15: var_score = 100
        elif std_dev < 20: var_score = 80 + (20 - std_dev) * 4
        elif std_dev < 40: var_score = max(0, 80 * (40 - std_dev) / 20)
        else: var_score = 0
        parts.append(var_score * 0.20); weights.append(0.20)
    if not weights:
        return None, details
    return clamp(round(sum(parts) / sum(weights))), details


COMPONENT_SCORERS = {
    "sleep_quality": score_sleep, "recovery": score_recovery,
    "nutrition": score_nutrition, "movement": score_movement,
    "habits_mvp": score_habits_mvp, "hydration": score_hydration,
    "journal": score_journal, "glucose": score_glucose,
}


def letter_grade(score):
    if score >= 95: return "A+"
    if score >= 90: return "A"
    if score >= 85: return "A-"
    if score >= 80: return "B+"
    if score >= 75: return "B"
    if score >= 70: return "B-"
    if score >= 65: return "C+"
    if score >= 60: return "C"
    if score >= 55: return "C-"
    if score >= 45: return "D"
    return "F"


def compute_day_grade(data, profile):
    weights = profile.get("day_grade_weights", {})
    component_scores = {}
    component_details = {}
    active_components = []
    for comp_name, scorer_fn in COMPONENT_SCORERS.items():
        score, details = scorer_fn(data, profile)
        component_scores[comp_name] = score
        component_details[comp_name] = details
        weight = weights.get(comp_name, 0)
        if score is not None and weight > 0:
            active_components.append((comp_name, score, weight))
    if not active_components:
        return None, "—", component_scores, component_details
    total_weight = sum(w for _, _, w in active_components)
    total_score = clamp(round(sum(s * w for _, s, w in active_components) / total_weight))
    return total_score, letter_grade(total_score), component_scores, component_details


# ==============================================================================
# STRAVA DEDUP (from daily_brief_lambda.py v2.2.3)
# ==============================================================================

def dedup_activities(activities):
    if not activities or len(activities) <= 1:
        return activities
    def parse_start(a):
        s = a.get("start_date_local") or a.get("start_date") or ""
        try:
            return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    def richness(a):
        score = 0
        dist = float(a.get("distance_meters") or 0)
        if dist > 0: score += 1000
        score += float(a.get("moving_time_seconds") or 0)
        if a.get("summary_polyline"): score += 500
        if a.get("average_cadence") is not None: score += 100
        return score
    indexed = [(i, a, parse_start(a)) for i, a in enumerate(activities)]
    indexed = [(i, a, t) for i, a, t in indexed if t is not None]
    indexed.sort(key=lambda x: x[2])
    remove = set()
    for j in range(len(indexed)):
        if j in remove: continue
        i_j, a_j, t_j = indexed[j]
        sport_j = (a_j.get("sport_type") or a_j.get("type") or "").lower()
        for k in range(j + 1, len(indexed)):
            if k in remove: continue
            i_k, a_k, t_k = indexed[k]
            sport_k = (a_k.get("sport_type") or a_k.get("type") or "").lower()
            if sport_j != sport_k: continue
            gap_min = abs((t_k - t_j).total_seconds()) / 60
            if gap_min > 15: break
            if richness(a_j) >= richness(a_k): remove.add(k)
            else: remove.add(j)
    kept = [a for i, (_, a, _) in enumerate(indexed) if i not in remove]
    no_time = [a for a in activities if parse_start(a) is None]
    return kept + no_time


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
    """Query all records for a source in a date range. Returns dict keyed by date string."""
    pk = "USER#matthew#SOURCE#" + source
    records = {}
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
        "ExpressionAttributeValues": {
            ":pk": pk,
            ":s": "DATE#" + start_date,
            ":e": "DATE#" + end_date,
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
    """Query all journal entries. Returns dict of date -> list of entries."""
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
            # SK format: DATE#2026-02-24#journal#morning_abc123
            sk = item["sk"]
            date_str = sk.split("#")[1]
            entries_by_date[date_str].append(d2f(item))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return dict(entries_by_date)


def query_existing_grades(start_date, end_date):
    """Query existing day_grade records to support skip-existing mode."""
    return query_all_dates("day_grade", start_date, end_date)


def load_profile():
    """Load profile from DynamoDB."""
    resp = table.get_item(Key={"pk": "USER#matthew", "sk": "PROFILE#v1"})
    return d2f(resp.get("Item", {}))


# ==============================================================================
# MAIN RETROCOMPUTE
# ==============================================================================

def run_retrocompute(start_date, end_date, write=False, force=False, stats_only=False):
    print(f"{'='*60}")
    print(f"Day Grade Retrocompute — algo v{ALGO_VERSION}")
    print(f"Range: {start_date} → {end_date}")
    print(f"Mode:  {'WRITE' if write else 'DRY RUN'}{' (force overwrite)' if force else ''}")
    print(f"{'='*60}\n")

    # Load profile
    print("[1/3] Loading profile...")
    profile = load_profile()
    weights = profile.get("day_grade_weights", {})
    print(f"  Weights: {json.dumps(weights, default=str)}")
    print(f"  MVP habits: {len(profile.get('mvp_habits', []))} configured")
    print()

    # Batch-query all sources
    print("[2/3] Batch-querying data sources...")
    t0 = time.time()

    sources = {}
    source_names = ["whoop", "eightsleep", "macrofactor", "strava", "apple_health",
                    "habitify", "chronicling", "garmin"]
    for src in source_names:
        sources[src] = query_all_dates(src, start_date, end_date)
        print(f"  {src}: {len(sources[src]):,} records")

    journal_entries = query_journal_entries(start_date, end_date)
    print(f"  notion (journal): {len(journal_entries):,} days with entries")

    existing_grades = query_existing_grades(start_date, end_date)
    print(f"  existing day_grade: {len(existing_grades):,} records")

    t_query = time.time() - t0
    print(f"\n  Query time: {t_query:.1f}s\n")

    # Generate date range
    dt_start = datetime.strptime(start_date, "%Y-%m-%d")
    dt_end = datetime.strptime(end_date, "%Y-%m-%d")
    all_dates = []
    d = dt_start
    while d <= dt_end:
        all_dates.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)

    if stats_only:
        print_source_coverage_stats(all_dates, sources, journal_entries)
        return

    # Process each date
    print(f"[3/3] Computing grades for {len(all_dates):,} dates...\n")

    results = []
    skipped_existing = 0
    skipped_no_data = 0
    computed = 0
    grade_dist = defaultdict(int)
    component_coverage = defaultdict(int)  # how often each component had data
    score_sum = 0

    for date_str in all_dates:
        # Skip existing grades unless --force
        if not force and date_str in existing_grades:
            skipped_existing += 1
            continue

        # Assemble data dict matching daily brief format
        data = {
            "date": date_str,
            "whoop": sources["whoop"].get(date_str),
            "sleep": sources["eightsleep"].get(date_str),
            "macrofactor": sources["macrofactor"].get(date_str),
            "strava": sources["strava"].get(date_str),
            "apple": sources["apple_health"].get(date_str),
            "habitify": sources["habitify"].get(date_str),
            "chronicling": sources["chronicling"].get(date_str),
            "garmin": sources["garmin"].get(date_str),
            "journal_entries": journal_entries.get(date_str, []),
        }

        # Apply Strava dedup
        strava = data.get("strava")
        if strava and strava.get("activities"):
            orig_count = len(strava["activities"])
            strava["activities"] = dedup_activities(strava["activities"])
            deduped_count = len(strava["activities"])
            if deduped_count < orig_count:
                strava["activity_count"] = deduped_count
                strava["total_moving_time_seconds"] = sum(
                    float(a.get("moving_time_seconds") or 0) for a in strava["activities"])

        # Compute grade
        total_score, grade, component_scores, component_details = compute_day_grade(data, profile)

        if total_score is None:
            skipped_no_data += 1
            continue

        computed += 1
        score_sum += total_score
        grade_dist[grade] += 1

        # Track which components had data
        for comp, score in component_scores.items():
            if score is not None:
                component_coverage[comp] += 1

        # Active components for this day
        active = [c for c, s in component_scores.items() if s is not None and weights.get(c, 0) > 0]

        results.append({
            "date": date_str,
            "total_score": total_score,
            "grade": grade,
            "component_scores": component_scores,
            "active_components": len(active),
        })

    # Print summary
    print(f"\n{'='*60}")
    print(f"RESULTS SUMMARY")
    print(f"{'='*60}")
    print(f"  Total dates in range:    {len(all_dates):,}")
    print(f"  Skipped (existing):      {skipped_existing:,}")
    print(f"  Skipped (no data):       {skipped_no_data:,}")
    print(f"  Computed:                {computed:,}")
    if computed > 0:
        print(f"  Average score:           {score_sum / computed:.1f}")
        print(f"  Average grade:           {letter_grade(round(score_sum / computed))}")
    print()

    # Grade distribution
    if grade_dist:
        print("  Grade Distribution:")
        grade_order = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "F"]
        for g in grade_order:
            if g in grade_dist:
                pct = grade_dist[g] / computed * 100
                bar = "█" * round(pct / 2)
                print(f"    {g:>3}: {grade_dist[g]:>4} ({pct:5.1f}%) {bar}")
        print()

    # Component coverage
    if component_coverage:
        print("  Component Coverage (days with data):")
        for comp in ["sleep_quality", "recovery", "nutrition", "movement",
                      "habits_mvp", "hydration", "journal", "glucose"]:
            count = component_coverage.get(comp, 0)
            pct = count / computed * 100 if computed > 0 else 0
            print(f"    {comp:>15}: {count:>4} / {computed} ({pct:5.1f}%)")
        print()

    # Sample output
    if results:
        print("  Sample grades (first 10):")
        for r in results[:10]:
            comps = ", ".join(f"{c}={s}" for c, s in r["component_scores"].items() if s is not None)
            print(f"    {r['date']}: {r['total_score']} ({r['grade']}) [{r['active_components']} components] — {comps}")
        if len(results) > 10:
            print(f"    ... and {len(results) - 10} more")
        print()

    # Write to DynamoDB
    if write and results:
        print(f"Writing {len(results):,} grades to DynamoDB...")
        write_grades(results, weights)
        print("Done!")
    elif not write and results:
        print("DRY RUN — no writes performed. Use --write to persist.\n")


def write_grades(results, weights):
    """Batch-write day grade records to DynamoDB."""
    written = 0
    errors = 0
    t0 = time.time()

    for i, r in enumerate(results):
        try:
            item = {
                "pk": "USER#matthew#SOURCE#day_grade",
                "sk": "DATE#" + r["date"],
                "date": r["date"],
                "total_score": Decimal(str(r["total_score"])),
                "letter_grade": r["grade"],
                "algorithm_version": ALGO_VERSION,
                "weights_snapshot": json.loads(json.dumps(weights), parse_float=Decimal),
                "computed_at": datetime.now(timezone.utc).isoformat(),
                "source": "retrocompute",
            }
            for comp, score in r["component_scores"].items():
                if score is not None:
                    item["component_" + comp] = Decimal(str(score))

            table.put_item(Item=item)
            written += 1

            # Progress every 100
            if (i + 1) % 100 == 0:
                elapsed = time.time() - t0
                rate = written / elapsed
                remaining = (len(results) - i - 1) / rate if rate > 0 else 0
                print(f"  {written:,} / {len(results):,} written ({rate:.0f}/s, ~{remaining:.0f}s remaining)")

            # Throttle to avoid provisioned throughput limits
            if (i + 1) % BATCH_WRITE_SIZE == 0:
                time.sleep(THROTTLE_DELAY)

        except Exception as e:
            errors += 1
            print(f"  ERROR writing {r['date']}: {e}")
            if errors > 10:
                print("  Too many errors, stopping.")
                break

    elapsed = time.time() - t0
    print(f"\n  Written: {written:,} in {elapsed:.1f}s ({written/elapsed:.0f}/s)")
    if errors:
        print(f"  Errors: {errors}")


def print_source_coverage_stats(all_dates, sources, journal_entries):
    """Print data coverage stats by source and time period."""
    print(f"\n{'='*60}")
    print(f"DATA COVERAGE ANALYSIS")
    print(f"{'='*60}\n")

    # Source coverage by year
    years = sorted(set(d[:4] for d in all_dates))
    print("  Records by source × year:")
    header = f"  {'Source':>15}" + "".join(f"{y:>8}" for y in years) + f"{'Total':>8}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    for src_name in ["whoop", "eightsleep", "strava", "apple_health",
                      "macrofactor", "habitify", "chronicling", "garmin"]:
        src_data = sources.get(src_name, {})
        counts = {}
        for d in src_data:
            y = d[:4]
            counts[y] = counts.get(y, 0) + 1
        row = f"  {src_name:>15}"
        for y in years:
            c = counts.get(y, 0)
            row += f"{c:>8}" if c > 0 else f"{'—':>8}"
        row += f"{len(src_data):>8}"
        print(row)

    # Journal
    j_counts = {}
    for d in journal_entries:
        y = d[:4]
        j_counts[y] = j_counts.get(y, 0) + 1
    row = f"  {'journal':>15}"
    for y in years:
        c = j_counts.get(y, 0)
        row += f"{c:>8}" if c > 0 else f"{'—':>8}"
    row += f"{len(journal_entries):>8}"
    print(row)
    print()

    # Days with N+ sources
    print("  Days by source count:")
    for threshold in [1, 2, 3, 4, 5]:
        count = 0
        for d in all_dates:
            src_count = sum(1 for src in sources.values() if d in src)
            if d in journal_entries:
                src_count += 1
            if src_count >= threshold:
                count += 1
        pct = count / len(all_dates) * 100
        print(f"    {threshold}+ sources: {count:>4} days ({pct:.1f}%)")
    print()


# ==============================================================================
# CLI
# ==============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Retrocompute day grades for historical dates")
    parser.add_argument("--write", action="store_true", help="Write grades to DynamoDB (default: dry run)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing grades")
    parser.add_argument("--start", default=DEFAULT_START, help=f"Start date YYYY-MM-DD (default: {DEFAULT_START})")
    parser.add_argument("--end", default=None, help="End date YYYY-MM-DD (default: yesterday)")
    parser.add_argument("--stats", action="store_true", help="Just show data coverage stats")
    args = parser.parse_args()

    end_date = args.end or (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()

    if args.stats:
        run_retrocompute(args.start, end_date, stats_only=True)
    else:
        run_retrocompute(args.start, end_date, write=args.write, force=args.force)
