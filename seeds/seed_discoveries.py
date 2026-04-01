#!/usr/bin/env python3
"""
seed_discoveries.py — Seed Day 1 timeline events with annotations for the Discoveries page.

Writes annotation records to the discovery_annotations DynamoDB partition.
These annotations attach to timeline events computed by /api/journey_timeline.

Usage:
  python3 seeds/seed_discoveries.py          # dry run
  python3 seeds/seed_discoveries.py --write  # write to DynamoDB
"""

import hashlib
import json
import sys
from datetime import datetime, timezone

import boto3

TABLE_NAME = "life-platform"
REGION = "us-west-2"
USER_ID = "matthew"
ANNOTATIONS_PK = f"USER#{USER_ID}#SOURCE#discovery_annotations"
NOW = datetime.now(timezone.utc).isoformat()


def _make_event_key(date, event_type, title):
    """Compute deterministic key — must match site_api_lambda.py and mcp/tools_social.py."""
    raw = f"{date}|{event_type}|{title}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# Note: event_type must match the `type` field in journey_timeline API output.
# The Day 1 anchor uses type="milestone", title="Day 1 — The Experiment Begins".
# Other seed events use types that the timeline API will generate as data accumulates.
SEED_EVENTS = [
    {
        "date": "2026-04-01",
        "event_type": "milestone",
        "title": "Day 1 \u2014 The Experiment Begins",  # matches site_api_lambda.py line 1748
        "annotation": "Made the decision to track everything publicly. No hiding, no selective disclosure.",
        "action_taken": "Launched platform",
        "outcome": None,
    },
    {
        "date": "2026-04-01",
        "event_type": "experiment",
        "title": "Hypothesis: Sleep onset before 11pm improves next-day recovery",
        "annotation": "Set 10:15pm phone alarm as wind-down trigger. Moved phone charger to kitchen.",
        "action_taken": "Evening routine change",
        "outcome": None,
    },
    {
        "date": "2026-04-01",
        "event_type": "experiment",
        "title": "Hypothesis: Zone 2 cardio 150min/week stabilizes glucose variability",
        "annotation": "Added 3x 50min rucking sessions to weekly schedule. Garmin HR zone targeting.",
        "action_taken": "Training protocol update",
        "outcome": None,
    },
    {
        "date": "2026-04-01",
        "event_type": "discovery",
        "title": "Baseline established: 14 biomarkers out of range",
        "annotation": "Scheduled follow-up labs for 90 days. Added vitamin D3+K2 5000IU and omega-3 protocol.",
        "action_taken": "Supplement protocol started",
        "outcome": None,
    },
]


def main():
    write_mode = "--write" in sys.argv

    print("=" * 60)
    print("Life Platform — Seed Day 1 Discovery Annotations")
    print("=" * 60)
    print(f"Mode:  {'WRITE' if write_mode else 'DRY RUN'}")
    print(f"Table: {TABLE_NAME} ({REGION})")
    print(f"PK:    {ANNOTATIONS_PK}")
    print()

    items = []
    for event in SEED_EVENTS:
        event_key = _make_event_key(event["date"], event["event_type"], event["title"])
        item = {
            "pk": ANNOTATIONS_PK,
            "sk": f"EVENT#{event_key}",
            "date": event["date"],
            "event_type": event["event_type"],
            "event_title": event["title"],
            "annotation": event["annotation"],
            "source": "discovery_annotations",
            "annotated_at": NOW,
        }
        if event.get("action_taken"):
            item["action_taken"] = event["action_taken"]
        if event.get("outcome"):
            item["outcome"] = event["outcome"]
        items.append(item)
        print(f"  [{event['event_type']:12s}] {event['title'][:50]}")
        print(f"               key={event_key}  annotation={event['annotation'][:60]}...")
        print()

    if not write_mode:
        print("DRY RUN — no data written. Run with --write to apply.")
        return

    ddb = boto3.resource("dynamodb", region_name=REGION)
    table = ddb.Table(TABLE_NAME)

    written = 0
    skipped = 0
    for item in items:
        # Idempotent: check if exists
        existing = table.get_item(Key={"pk": item["pk"], "sk": item["sk"]}).get("Item")
        if existing:
            print(f"  SKIP (exists): {item['sk']}")
            skipped += 1
            continue
        table.put_item(Item=item)
        print(f"  WROTE: {item['sk']}")
        written += 1

    print(f"\nDone: {written} written, {skipped} skipped (already exist).")


if __name__ == "__main__":
    main()
