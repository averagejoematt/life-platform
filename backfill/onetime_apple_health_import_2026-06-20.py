#!/usr/bin/env python3
"""
ONE-TIME Apple Health native-export import (2026-06-20).

Why this exists (not the S3-trigger Lambda): the native Health.app `export.xml`
is ~1.2 GB. The `apple-health-ingestion` Lambda is memory_mb=512 / timeout=300s
and reads the whole file into RAM — it would OOM instantly. So we run the SAME
parse/validate/write code locally, streaming from disk.

It reuses the production functions verbatim (zero drift):
  - apple_health_lambda.process_xml      (field maps, UTC parse_date, SUM/AVG aggregation)
  - apple_health_lambda.build_day_record (per-day assembly)
  - apple_health_lambda.save_day         (raw/matthew/apple_health/... S3 + DATA-2 validate + DDB put)

What this wrapper adds:
  - Streams `export.xml` from disk into iterparse (no 1.2 GB RAM load).
  - Windows to [--start, today] (default = genesis 2026-06-14) so we only re-write
    the days that are broken/incomplete and never un-hide pilot history as "current".
  - Derives `phase` from genesis (date < genesis -> "pilot", else "experiment").
  - Prints a before/after report for the additive movement metrics.
  - DRY-RUN by default. Writes to prod S3+DynamoDB only with --apply.

Usage:
  python3 backfill/onetime_apple_health_import_2026-06-20.py            # dry-run, window = genesis..today
  python3 backfill/onetime_apple_health_import_2026-06-20.py --apply    # write
  python3 backfill/onetime_apple_health_import_2026-06-20.py --start 2026-06-05 --apply
"""

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, datetime, timezone

os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("DYNAMODB_TABLE", "life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("USER_ID", "matthew")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))
sys.path.insert(0, os.path.join(_ROOT, "lambdas", "ingestion"))

import apple_health_lambda as ah  # noqa: E402

GENESIS = "2026-06-14"  # lambdas/constants.py EXPERIMENT_START_DATE (cycle 4)
DEFAULT_EXPORT = os.path.join(_ROOT, "datadrops", "apple_health_export_4", "apple_health_export", "export.xml")

# Additive activity metrics that must use the max-sum-across-sources rule (P0 fix
# 9e98e093 / health_auto_export_lambda._ACTIVITY_MAX_FIELDS). The raw native export
# contains separate per-sample records from BOTH iPhone ("Matt 17") and Garmin
# ("Connect"); naively summing every source double-counts (e.g. 6/19 steps 11645+9869
# = 21514). The rule: per day, sum each source independently, then keep ONLY the
# single source with the largest daily sum.
ACTIVITY_MAX_FIELDS = {"steps", "distance_walk_run_miles", "active_calories", "basal_calories", "flights_climbed"}

# Reported in the before/after table (same 5 fields).
REPORT_FIELDS = ["steps", "active_calories", "basal_calories", "distance_walk_run_miles", "flights_climbed"]


def parse_maxsum(path, cutoff_date):
    """Stream-parse export.xml mirroring apple_health_lambda.process_xml, EXCEPT additive
    activity fields are accumulated per-source so we can apply the max-sum rule (no
    cross-device double-count). Returns the same 5-tuple process_xml does, plus a
    per-day source_audit dict {date: {field: {chosen, rejected}}}.
    """
    day_sums = defaultdict(lambda: defaultdict(float))  # non-activity SUM fields
    activity_src = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))  # [date][field][source] = sum
    day_avg_acc = defaultdict(lambda: defaultdict(lambda: [0.0, 0]))
    bg_readings = defaultdict(list)
    day_workouts = defaultdict(list)
    day_sleep = defaultdict(list)

    for _ev, elem in ET.iterparse(path, events=("start",)):
        tag = elem.tag
        if tag == "Record":
            rtype = elem.get("type", "")
            start_date = ah.parse_date(elem.get("startDate", ""))
            if not start_date or start_date < cutoff_date:
                elem.clear()
                continue
            if rtype in ah.QUANTITY_RECORDS:
                field = ah.QUANTITY_RECORDS[rtype]
                try:
                    value = float(elem.get("value", "0") or "0")
                except (ValueError, TypeError):
                    elem.clear()
                    continue
                if field == "blood_glucose_mgdl":
                    bg_readings[start_date].append(value)
                elif field in ACTIVITY_MAX_FIELDS:
                    src = elem.get("sourceName", "") or "_unknown"
                    activity_src[start_date][field][src] += value
                elif field in ah.SUM_TYPES:
                    day_sums[start_date][field] += value
                elif field in ah.AVG_TYPES:
                    day_avg_acc[start_date][field][0] += value
                    day_avg_acc[start_date][field][1] += 1
            elif rtype == "HKCategoryTypeIdentifierSleepAnalysis":
                day_sleep[start_date].append(
                    {
                        "source": elem.get("sourceName", ""),
                        "start": elem.get("startDate", ""),
                        "end": elem.get("endDate", ""),
                        "value": elem.get("value", ""),
                    }
                )
            elem.clear()
        elif tag == "Workout":
            start_date = ah.parse_date(elem.get("startDate", ""))
            if not start_date or start_date < cutoff_date:
                elem.clear()
                continue

            def _f(attr):
                try:
                    return float(elem.get(attr) or 0)
                except (ValueError, TypeError):
                    return 0.0

            day_workouts[start_date].append(
                {
                    "type": elem.get("workoutActivityType", "").replace("HKWorkoutActivityType", ""),
                    "source": elem.get("sourceName", ""),
                    "duration_min": round(_f("duration"), 1),
                    "calories": round(_f("totalEnergyBurned"), 1),
                    "distance": round(_f("totalDistance"), 2),
                    "distance_unit": elem.get("totalDistanceUnit", ""),
                    "start": elem.get("startDate", ""),
                    "end": elem.get("endDate", ""),
                }
            )
            elem.clear()
        elif tag in ("ActivitySummary", "ClinicalRecord", "Audiogram"):
            elem.clear()

    # Resolve activity fields with the max-sum rule and fold into day_sums.
    source_audit = defaultdict(dict)
    for d, fields in activity_src.items():
        for field, src_sums in fields.items():
            chosen = max(src_sums, key=lambda s: src_sums[s])
            day_sums[d][field] = src_sums[chosen]
            rejected = {s: round(v, 2) for s, v in src_sums.items() if s != chosen}
            if rejected:
                source_audit[d][field] = {"chosen": chosen, "chosen_sum": round(src_sums[chosen], 2), "rejected": rejected}

    return day_sums, day_avg_acc, bg_readings, day_workouts, day_sleep, source_audit


def existing_item(date_str):
    """Read the current DDB record for a day (unfiltered — we want the raw stored row)."""
    try:
        resp = ah.table.get_item(Key={"pk": "USER#matthew#SOURCE#apple_health", "sk": f"DATE#{date_str}"})
        return resp.get("Item")
    except Exception as e:  # noqa: BLE001
        print(f"  (could not read existing {date_str}: {e})")
        return None


def fmt(v):
    if v is None:
        return "—"
    try:
        f = float(v)
        return str(int(f)) if f == int(f) else f"{f:.2f}"
    except (TypeError, ValueError):
        return str(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--export", default=DEFAULT_EXPORT, help="path to export.xml")
    ap.add_argument("--start", default=GENESIS, help="earliest day to import (YYYY-MM-DD)")
    ap.add_argument("--end", default=date.today().isoformat(), help="latest day to import (YYYY-MM-DD)")
    ap.add_argument("--apply", action="store_true", help="actually write to S3+DynamoDB (default: dry-run)")
    args = ap.parse_args()

    if not os.path.exists(args.export):
        sys.exit(f"export not found: {args.export}")

    mode = "APPLY (writes to prod)" if args.apply else "DRY-RUN (no writes)"
    sz = os.path.getsize(args.export) / 1e9
    print("=" * 78)
    print(f"One-time Apple Health import — {mode}")
    print(f"  export : {args.export}  ({sz:.2f} GB)")
    print(f"  window : {args.start} .. {args.end}  (genesis {GENESIS})")
    print("=" * 78)
    print("Streaming parse (skips records older than --start; ~minutes for full file)...\n")

    # Stream from disk into iterparse (no full-file RAM load), with max-sum dedup.
    day_sums, day_avg_acc, bg_readings, day_workouts, day_sleep, source_audit = parse_maxsum(args.export, args.start)

    all_dates = set()
    for d in (day_sums, day_avg_acc, bg_readings, day_workouts, day_sleep):
        all_dates.update(d.keys())
    dates = sorted(x for x in all_dates if args.start <= x <= args.end)

    if not dates:
        sys.exit("No in-window dates parsed — check --start/--end or the export contents.")

    print(f"In-window days parsed: {len(dates)} ({dates[0]} .. {dates[-1]})\n")
    print(f"{'DATE':<12} {'phase':<11} " + " ".join(f"{f.replace('_', ' ')[:14]:>14}" for f in REPORT_FIELDS))
    print("-" * 100)

    written = 0
    for d in dates:
        day = ah.build_day_record(d, day_sums, day_avg_acc, bg_readings, day_workouts, day_sleep)
        day["phase"] = "pilot" if d < GENESIS else "experiment"

        before = existing_item(d) or {}
        # before / after per reported field
        cells = []
        for f in REPORT_FIELDS:
            b = before.get(f)
            a = day.get(f)
            arrow = "→" if fmt(b) != fmt(a) else "="
            cells.append(f"{fmt(b)}{arrow}{fmt(a)}")
        print(f"{d:<12} {day['phase']:<11} " + " ".join(f"{c:>14}" for c in cells))

        if args.apply:
            ah.save_day(d, day)
            written += 1

    print("-" * 100)
    print("(before→after; '=' = unchanged)\n")

    # Show which source won each day's activity metrics (and what was discarded).
    print("Source resolution (max-sum rule — rejected sources discarded to avoid double-count):")
    for d in dates:
        if d in source_audit:
            for field, info in sorted(source_audit[d].items()):
                rej = ", ".join(f"{s}={v}" for s, v in info["rejected"].items())
                print(f"  {d} {field:<24} chose {info['chosen']}={info['chosen_sum']}  | discarded {rej}")
    print()

    if args.apply:
        print(f"✅ Wrote {written} days to S3 + DynamoDB at {datetime.now(timezone.utc).isoformat()}")
    else:
        print("DRY-RUN complete — nothing written. Re-run with --apply to commit.")


if __name__ == "__main__":
    main()
