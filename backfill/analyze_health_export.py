#!/usr/bin/env python3
"""
Analyze Apple Health export.xml to understand what data types and sources exist.
Run: python3 analyze_health_export.py
"""

import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime
import sys

EXPORT_PATH = "/Users/matthewwalker/Documents/Claude/apple_health_export/export.xml"

print("Parsing Apple Health export (streaming)...")
print("This may take 30-60 seconds for a large file...\n")

record_types = defaultdict(lambda: {"count": 0, "sources": set(), "earliest": None, "latest": None, "unit": ""})
workout_types = defaultdict(lambda: {"count": 0, "sources": set()})
total_records = 0
total_workouts = 0
me_info = {}
export_date = ""

context = ET.iterparse(EXPORT_PATH, events=("start",))

for event, elem in context:
    tag = elem.tag

    if tag == "ExportDate":
        export_date = elem.get("value", "")

    elif tag == "Me":
        me_info = {
            "dob": elem.get("HKCharacteristicTypeIdentifierDateOfBirth", ""),
            "sex": elem.get("HKCharacteristicTypeIdentifierBiologicalSex", ""),
        }

    elif tag == "Record":
        total_records += 1
        rtype = elem.get("type", "").replace("HKQuantityTypeIdentifier", "").replace("HKCategoryTypeIdentifier", "CAT:").replace("HKDataType", "")
        source = elem.get("sourceName", "")
        unit = elem.get("unit", "")
        start = elem.get("startDate", "")[:10]

        r = record_types[rtype]
        r["count"] += 1
        r["sources"].add(source)
        r["unit"] = unit
        if start:
            if r["earliest"] is None or start < r["earliest"]:
                r["earliest"] = start
            if r["latest"] is None or start > r["latest"]:
                r["latest"] = start

        elem.clear()

    elif tag == "Workout":
        total_workouts += 1
        wtype = elem.get("workoutActivityType", "").replace("HKWorkoutActivityType", "")
        source = elem.get("sourceName", "")
        workout_types[wtype]["count"] += 1
        workout_types[wtype]["sources"].add(source)
        elem.clear()

    elif tag == "ActivitySummary":
        elem.clear()

print(f"Export date: {export_date}")
print(f"Total records: {total_records:,}")
print(f"Total workouts: {total_workouts:,}")
print()

print("=" * 70)
print("RECORD TYPES (sorted by count)")
print("=" * 70)
for rtype, info in sorted(record_types.items(), key=lambda x: -x[1]["count"]):
    sources = ", ".join(sorted(info["sources"]))
    print(f"\n{rtype}")
    print(f"  Count: {info['count']:,}  |  Unit: {info['unit']}")
    print(f"  Range: {info['earliest']} → {info['latest']}")
    print(f"  Sources: {sources}")

print()
print("=" * 70)
print("WORKOUT TYPES")
print("=" * 70)
for wtype, info in sorted(workout_types.items(), key=lambda x: -x[1]["count"]):
    sources = ", ".join(sorted(info["sources"]))
    print(f"  {wtype}: {info['count']:,} workouts | Sources: {sources}")
