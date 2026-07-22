#!/usr/bin/env python3
"""
backfill_training_notes.py — one-time resumable backfill of the derived note-signal layer
over existing Hevy workouts that carry non-empty notes.

Trivial at current scale (~1 session) but written resumable for growth. Mirrors the
meal-layer backfill. Reads raw Hevy workouts, runs the SAME extractor + projection writer
the on-ingest hook uses, and elevates pain. Dry-run by default.

Usage:
  python3 deploy/backfill_training_notes.py                 # dry-run, all dates
  python3 deploy/backfill_training_notes.py --apply         # write
  python3 deploy/backfill_training_notes.py --since 2026-06-01 --apply
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import boto3  # noqa: E402
import training_notes as tn  # noqa: E402
from boto3.dynamodb.conditions import Key  # noqa: E402
from training_notes_llm import make_llm_fn  # noqa: E402

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE = os.environ.get("TABLE_NAME", "life-platform")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2000-01-01")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    llm_fn = make_llm_fn(table) if args.apply else None  # dry-run: deterministic-only, no model spend

    resp = table.query(
        KeyConditionExpression=Key("pk").eq("USER#matthew#SOURCE#hevy") & Key("sk").between(f"DATE#{args.since}", "DATE#9999~"),
    )
    workouts = [it for it in resp.get("Items", []) if "#WORKOUT#" in it.get("sk", "")]
    total_records = total_pain = total_workouts = 0
    for w in workouts:
        exs = w.get("exercises", []) or []
        if not any((e.get("notes") or "").strip() for e in exs):
            continue
        total_workouts += 1
        res = tn.write_workout_notes(table, w["date"], w.get("workout_uid", ""), exs, dry_run=not args.apply, llm_fn=llm_fn)
        total_records += res["records"]
        if args.apply:
            for it in res.get("items", []):
                if it.get("pain_flag"):
                    tn.elevate_pain(table, it)
                    total_pain += 1
        print(f"  {w['date']} {w.get('workout_uid', '')}: {res['records']} records" + (" [dry-run]" if not args.apply else ""))

    print(
        f"\n{'APPLIED' if args.apply else 'DRY-RUN'}: {total_workouts} noted workouts → {total_records} records, {total_pain} pain elevated"
    )


if __name__ == "__main__":
    main()
