#!/usr/bin/env python3
"""
Quick test: verify Habitify API key, show areas/habits/moods.
Run: python3 test_habitify_api.py YOUR_API_KEY

Prints your full habit structure so we can verify the mapping before building the Lambda.
"""

import json
import sys
from datetime import datetime, timedelta
import urllib.request
import urllib.parse

BASE_URL = "https://api.habitify.me"


def api_get(endpoint, api_key, params=None):
    """Simple GET request to Habitify API."""
    url = f"{BASE_URL}{endpoint}"
    if params:
        qs = urllib.parse.urlencode(params)
        url = f"{url}?{qs}"
    req = urllib.request.Request(url, headers={"Authorization": api_key, "User-Agent": "LifePlatform/1.0"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 test_habitify_api.py YOUR_API_KEY")
        sys.exit(1)

    api_key = sys.argv[1].strip()
    today = datetime.now().strftime("%Y-%m-%dT00:00:00+00:00")

    # ── 1. Areas (P40 groups) ────────────────────────────────────────────────
    print("=" * 60)
    print("AREAS (P40 Groups)")
    print("=" * 60)
    areas_resp = api_get("/areas", api_key)
    areas = areas_resp.get("data", [])
    area_map = {}  # id → name
    for area in areas:
        area_map[area["id"]] = area["name"]
        print(f"  {area['name']:20s}  id={area['id']}")
    print(f"\n  Total areas: {len(areas)}\n")

    # ── 2. Habits ────────────────────────────────────────────────────────────
    print("=" * 60)
    print("HABITS (by area)")
    print("=" * 60)
    habits_resp = api_get("/habits", api_key)
    habits = habits_resp.get("data", [])

    # Group habits by area
    by_area = {}
    no_area = []
    for h in habits:
        area = h.get("area")
        if area and area.get("id") in area_map:
            group_name = area_map[area["id"]]
            by_area.setdefault(group_name, []).append(h)
        else:
            no_area.append(h)

    total_habits = 0
    for group_name in sorted(by_area.keys()):
        group_habits = by_area[group_name]
        print(f"\n  [{group_name}] ({len(group_habits)} habits)")
        for h in sorted(group_habits, key=lambda x: x["name"]):
            goal_info = ""
            if h.get("goal"):
                g = h["goal"]
                goal_info = f"  (goal: {g.get('value', '?')} {g.get('unit_type', '')} {g.get('periodicity', '')})"
            archived = " [ARCHIVED]" if h.get("is_archived") else ""
            print(f"    • {h['name']}{goal_info}{archived}")
            total_habits += 1

    if no_area:
        print(f"\n  [NO AREA] ({len(no_area)} habits)")
        for h in no_area:
            print(f"    • {h['name']}")
            total_habits += 1

    print(f"\n  Total habits: {total_habits}")
    print(f"  Active (non-archived): {sum(1 for h in habits if not h.get('is_archived'))}")

    # ── 3. Journal (today's status) ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"JOURNAL (today: {datetime.now().strftime('%Y-%m-%d')})")
    print("=" * 60)
    journal_resp = api_get("/journal", api_key, {"target_date": today})
    journal = journal_resp.get("data", [])
    status_counts = {"completed": 0, "in_progress": 0, "skipped": 0, "failed": 0, "none": 0}
    for j in journal:
        status = j.get("status", "none")
        if isinstance(status, dict):
            status = status.get("status", "none")
        status_counts[status] = status_counts.get(status, 0) + 1
    print(f"  Habits in journal: {len(journal)}")
    for s, c in sorted(status_counts.items()):
        if c > 0:
            print(f"    {s}: {c}")

    # Show completed habits
    completed = [j for j in journal if j.get("status") == "completed" or
                 (isinstance(j.get("status"), dict) and j["status"].get("status") == "completed")]
    if completed:
        print(f"\n  Completed today ({len(completed)}):")
        for j in completed:
            print(f"    ✓ {j['name']}")

    # ── 4. Moods ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("MOODS")
    print("=" * 60)
    mood_labels = {1: "Terrible", 2: "Bad", 3: "Okay", 4: "Good", 5: "Excellent"}
    try:
        moods_resp = api_get("/moods", api_key, {"target_date": today})
        moods = moods_resp.get("data", [])
        if moods:
            for m in moods:
                val = m.get("value", "?")
                label = mood_labels.get(val, "Unknown")
                print(f"  {m.get('created_at', '?')}: {val} ({label})")
        else:
            print("  No mood entries for today")
    except Exception as e:
        print(f"  Moods API error: {e}")

    # ── 5. Habit ID mapping (for Lambda reference) ───────────────────────────
    print("\n" + "=" * 60)
    print("HABIT → AREA MAPPING (for Lambda)")
    print("=" * 60)
    print("\n  habit_id → (name, area)")
    for h in sorted(habits, key=lambda x: x["name"]):
        area_name = area_map.get(h.get("area", {}).get("id", ""), "NO_AREA") if h.get("area") else "NO_AREA"
        archived = " [ARCHIVED]" if h.get("is_archived") else ""
        print(f"  {h['id']:40s} → {h['name']:35s} [{area_name}]{archived}")


if __name__ == "__main__":
    main()
