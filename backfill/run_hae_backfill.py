#!/usr/bin/env python3
"""
backfill/run_hae_backfill.py — Process a Health Auto Export JSON file locally

Bypasses Lambda auth and runs the payload through the exact same processing
pipeline as the webhook. Idempotent — safe to run multiple times.

Usage:
    python3 backfill/run_hae_backfill.py <path-to-json>

Example:
    python3 backfill/run_hae_backfill.py ingest/HealthAutoExport-2025-12-07-2026-03-07.json
"""

import json
import sys
import os

# Add lambdas/ to path so we can import the webhook module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

# Set env vars before importing (module reads these at import time)
os.environ.setdefault("TABLE_NAME",  "life-platform")
os.environ.setdefault("S3_BUCKET",   "matthew-life-platform")
os.environ.setdefault("SECRET_NAME", "life-platform/api-keys")
os.environ.setdefault("USER_ID",     "matthew")

# Import the module — all AWS clients initialise here using your local ~/.aws credentials
import health_auto_export_lambda as hae

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 backfill/run_hae_backfill.py <path-to-json>")
        sys.exit(1)

    path = sys.argv[1]
    print(f"Loading {path}...")
    with open(path) as f:
        payload = json.load(f)

    data     = payload.get("data", payload)
    metrics  = data.get("metrics",  []) if isinstance(data, dict) else []
    workouts = data.get("workouts", []) if isinstance(data, dict) else []
    print(f"Payload: {len(metrics)} metrics, {len(workouts)} workouts\n")

    # ── State of Mind ──
    som_daily_entries, som_daily_agg = hae.process_state_of_mind(payload)
    if som_daily_entries:
        total = sum(len(v) for v in som_daily_entries.values())
        print(f"State of Mind: {total} entries across {len(som_daily_entries)} days")
        som_new = 0
        for date_str, entries in som_daily_entries.items():
            som_new += hae.save_state_of_mind_to_s3(date_str, entries)
        for date_str, agg in som_daily_agg.items():
            hae.merge_day_to_dynamo(date_str, agg)
        print(f"  → {som_new} new entries saved")
    else:
        print("State of Mind: no data")

    # ── Archive raw payload ──
    s3_key = hae.save_raw_payload(payload)
    print(f"Raw payload archived: s3://{hae.S3_BUCKET}/{s3_key}")

    # ── Blood glucose (CGM) ──
    glucose_metric = next(
        (m for m in metrics if m.get("name") in ("Blood Glucose", "blood_glucose")), None
    )
    if glucose_metric:
        glucose_data  = glucose_metric.get("data", [])
        glucose_units = glucose_metric.get("units", "mg/dL")
        print(f"\nBlood Glucose: {len(glucose_data)} readings, units={glucose_units}")
        daily_agg, daily_readings = hae.process_blood_glucose(glucose_data, glucose_units)
        for date_str, agg in daily_agg.items():
            hae.merge_day_to_dynamo(date_str, agg)
        readings_new = sum(hae.save_cgm_readings_to_s3(d, r) for d, r in daily_readings.items())
        print(f"  → {len(daily_agg)} days updated, {readings_new} new readings saved")
    else:
        print("\nBlood Glucose: no data in payload")

    # ── Other metrics ──
    other_daily = hae.process_generic_metrics(metrics)
    if other_daily:
        fields_written = set()
        for date_str, fields in other_daily.items():
            hae.merge_day_to_dynamo(date_str, fields)
            fields_written.update(fields.keys())
        print(f"\nOther metrics: {len(other_daily)} days updated")
        print(f"  → Fields: {sorted(fields_written)}")
    else:
        print("\nOther metrics: no data")

    # ── Workouts ──
    if workouts:
        daily_workouts, daily_agg = hae.process_workouts(workouts)
        workout_new = 0
        for date_str, wkts in daily_workouts.items():
            workout_new += hae.save_workouts_to_s3(date_str, wkts)
        for date_str, agg in daily_agg.items():
            hae.merge_day_to_dynamo(date_str, agg)
        print(f"\nWorkouts: {workout_new} new saved across {len(daily_workouts)} days, {len(daily_agg)} recovery days written to DDB")
    else:
        print("\nWorkouts: no data")

    print("\n✅ Backfill complete")

if __name__ == "__main__":
    main()
