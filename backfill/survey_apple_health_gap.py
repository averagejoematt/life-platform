#!/usr/bin/env python3
"""
survey_apple_health_gap.py — READ-ONLY inventory of HK record types in a date window.

Streams export.xml and counts records in (default) 2026-04-02 → 2026-05-01 for the
specific HK types that the v1.0 backfill script does NOT handle but the live HAE
Lambda v1.6 does. Used to decide whether to run as-is or upgrade the script first.

Writes nothing. Touches no AWS resources. Pure parse + count.

Usage:
    python3 survey_apple_health_gap.py [PATH_TO_EXPORT_XML]

Default path: ~/Documents/Claude/life-platform/datadrops/apple_health_drop/apple_health_export_may2/export.xml
"""

import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict, Counter

DEFAULT_PATH = os.path.expanduser(
    "~/Documents/Claude/life-platform/datadrops/apple_health_drop/"
    "apple_health_export_may2/export.xml"
)
GAP_START = "2026-04-02"
GAP_END   = "2026-05-01"  # inclusive

# Types the v1.0 backfill script silently drops as "unmapped" but v1.6 Lambda processes:
TARGET_TYPES = {
    # Blood pressure (v1.4)
    "HKQuantityTypeIdentifierBloodPressureSystolic":  "BP Systolic",
    "HKQuantityTypeIdentifierBloodPressureDiastolic": "BP Diastolic",
    # Water (v1.3 — currently in SKIP_TYPES of backfill, should be ingested)
    "HKQuantityTypeIdentifierDietaryWater":           "Water intake",
    # Caffeine (Tier 1 in v1.6)
    "HKQuantityTypeIdentifierDietaryCaffeine":        "Caffeine intake",
    # Mindful sessions (Tier 1 in v1.6, breath/meditation)
    "HKCategoryTypeIdentifierMindfulSession":         "Mindful sessions",
}

# State of Mind: separate top-level element type
SOM_TAG = "StateOfMind"

# Workout: separate top-level element with workoutActivityType attribute
WORKOUT_TAG = "Workout"

# Recovery workout types (the categories v1.6 aggregates to DDB)
RECOVERY_WORKOUT_KEYWORDS = {
    "Flexibility", "Yoga", "Pilates", "Cooldown", "TaiChi",
    "MindAndBody", "Breathing",
}


def in_window(date_str):
    """Inclusive window check."""
    return GAP_START <= date_str <= GAP_END


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH

    if not os.path.exists(path):
        print(f"ERROR: not found: {path}", file=sys.stderr)
        sys.exit(1)

    size_mb = os.path.getsize(path) / (1024 * 1024)
    print(f"Surveying: {path}")
    print(f"Size:      {size_mb:.0f} MB")
    print(f"Window:    {GAP_START} → {GAP_END} (inclusive)")
    print()

    # Counters
    record_counts   = Counter()                   # HK type → count
    record_dates    = defaultdict(set)            # HK type → set of dates with data
    workout_counts  = Counter()                   # workoutActivityType → count
    workout_dates   = defaultdict(set)
    workout_by_source = defaultdict(Counter)      # workoutActivityType → {sourceName: count}
    som_count       = 0
    som_dates       = set()
    som_kinds       = Counter()
    som_sources     = Counter()
    total_scanned   = 0

    print("Streaming...")
    for _, elem in ET.iterparse(path, events=("end",)):
        tag = elem.tag

        if tag == "Record":
            total_scanned += 1
            if total_scanned % 1_000_000 == 0:
                print(f"  ... {total_scanned:,} records scanned")

            rtype = elem.get("type", "")
            if rtype in TARGET_TYPES:
                start_date = elem.get("startDate", "")[:10]
                if start_date and in_window(start_date):
                    record_counts[rtype] += 1
                    record_dates[rtype].add(start_date)

        elif tag == WORKOUT_TAG:
            start_date = elem.get("startDate", "")[:10]
            if start_date and in_window(start_date):
                wtype_raw = elem.get("workoutActivityType", "")
                # strip "HKWorkoutActivityType" prefix
                wtype = wtype_raw.replace("HKWorkoutActivityType", "")
                src = elem.get("sourceName", "")
                workout_counts[wtype] += 1
                workout_dates[wtype].add(start_date)
                workout_by_source[wtype][src] += 1

        elif tag == SOM_TAG or tag.endswith("StateOfMind"):
            # Try common date attributes
            d = (elem.get("startDate") or elem.get("creationDate")
                 or elem.get("date") or "")[:10]
            if d and in_window(d):
                som_count += 1
                som_dates.add(d)
                som_kinds[elem.get("kind", "unknown")] += 1
                som_sources[elem.get("sourceName", "")] += 1

        elem.clear()

    # ── Report ──
    print()
    print("=" * 60)
    print(f"Total <Record> elements scanned: {total_scanned:,}")
    print("=" * 60)
    print()
    print(f"GAP WINDOW: {GAP_START} → {GAP_END}")
    print()

    print("──────────── Record types of interest ────────────")
    if not record_counts:
        print("  (none — no BP / water / caffeine / mindful records in window)")
    else:
        for rtype, label in TARGET_TYPES.items():
            n = record_counts.get(rtype, 0)
            d = len(record_dates.get(rtype, set()))
            if n:
                print(f"  {label:25s}  {n:>6,} records across {d:>3} days  ({rtype})")
            else:
                print(f"  {label:25s}  (none)")
    print()

    print("──────────── State of Mind ────────────")
    if som_count == 0:
        print("  (none — no SoM check-ins in window)")
    else:
        print(f"  {som_count} check-ins across {len(som_dates)} days")
        print(f"  Kinds:   {dict(som_kinds)}")
        print(f"  Sources: {dict(som_sources)}")
    print()

    print("──────────── Workouts ────────────")
    if not workout_counts:
        print("  (none — no workouts in window)")
    else:
        print(f"  {sum(workout_counts.values())} total workouts across {len(set().union(*workout_dates.values()))} days")
        print()
        # Highlight recovery types
        print("  Recovery types (v1.6 would aggregate to DynamoDB):")
        any_recovery = False
        for wtype, n in workout_counts.most_common():
            is_recovery = any(kw.lower() in wtype.lower() for kw in RECOVERY_WORKOUT_KEYWORDS)
            if is_recovery:
                any_recovery = True
                d = len(workout_dates[wtype])
                src_str = ", ".join(f"{s}({c})" for s, c in workout_by_source[wtype].most_common(3))
                print(f"    {wtype:30s}  {n:>4} sessions / {d:>3} days  [{src_str}]")
        if not any_recovery:
            print("    (no recovery-type workouts — Pliability / Breathwrk / Yoga etc.)")
        print()
        print("  Other workout types (v1.6 stores to S3 only, not DDB):")
        any_other = False
        for wtype, n in workout_counts.most_common():
            is_recovery = any(kw.lower() in wtype.lower() for kw in RECOVERY_WORKOUT_KEYWORDS)
            if not is_recovery:
                any_other = True
                d = len(workout_dates[wtype])
                src_str = ", ".join(f"{s}({c})" for s, c in workout_by_source[wtype].most_common(2))
                print(f"    {wtype:30s}  {n:>4} sessions / {d:>3} days  [{src_str}]")
        if not any_other:
            print("    (none)")
    print()

    print("=" * 60)
    print("VERDICT")
    print("=" * 60)
    has_records = bool(record_counts)
    has_som     = som_count > 0
    has_recovery_workouts = any(
        any(kw.lower() in wtype.lower() for kw in RECOVERY_WORKOUT_KEYWORDS)
        for wtype in workout_counts
    )
    if not (has_records or has_som or has_recovery_workouts):
        print("  Nothing in the gap window for the metrics the v1.0 script skips.")
        print("  → Safe to run backfill_apple_health_export.py as-is. Nothing lost.")
    else:
        print("  The gap window contains data the v1.0 script would silently drop:")
        if has_records:
            print(f"    • {sum(record_counts.values())} records of skipped types (BP/water/caffeine/mindful)")
        if has_som:
            print(f"    • {som_count} State of Mind check-ins")
        if has_recovery_workouts:
            print(f"    • Recovery-type workouts (would be silently dropped — script doesn't process <Workout> elements at all)")
        print()
        print("  → Recommend upgrading backfill script to v1.6 parity before running.")
        print("    Or run as-is and accept the listed gap; can re-run upgraded later (merge-safe).")
    print()


if __name__ == "__main__":
    main()
