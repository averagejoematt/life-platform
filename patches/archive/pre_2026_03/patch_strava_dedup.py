#!/usr/bin/env python3
"""
patch_strava_dedup.py — Add dedup logic to Strava ingestion Lambda

Fixes known issue: when multiple devices (WHOOP, Garmin, Apple Watch) record
the same workout, Strava stores each as a separate activity. Previously dedup
only ran in the daily brief (read-time); this fix deduplicates at write-time
in the ingestion Lambda so all downstream MCP tools benefit.

Overlap detection: same sport_type AND start times within 15 minutes.
Keep strategy: prefer GPS data > route > cadence > longer duration.

Usage:
  python3 patches/patch_strava_dedup.py
  (patches lambdas/strava_lambda.py in place)
"""

LAMBDA_FILE = "lambdas/strava_lambda.py"

def read_file(path):
    with open(path, "r") as f:
        return f.read()

def write_file(path, content):
    with open(path, "w") as f:
        f.write(content)

# ─────────────────────────────────────────────
# Patch 1: Add dedup_activities function before save_to_s3
# ─────────────────────────────────────────────

DEDUP_FN = '''

def dedup_activities(activities):
    """Remove duplicate activities from multi-device Strava sync at ingestion time.

    When multiple devices (WHOOP, Garmin, Apple Watch) record the same workout,
    Strava stores each as a separate activity. This detects overlaps and keeps
    the richer record.

    Overlap = same sport_type AND start times within 15 minutes.
    Keep = prefer has-distance over no-distance, then longer duration.
    """
    if len(activities) <= 1:
        return activities

    def parse_start(a):
        s = a.get("start_date_local") or a.get("start_date") or ""
        try:
            return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    def richness(a):
        """Score how much data an activity has. Higher = keep."""
        score = 0
        dist = float(a.get("distance_meters") or a.get("distance") or 0)
        if dist > 0:
            score += 1000  # GPS data is strong signal
        score += float(a.get("moving_time_seconds") or a.get("moving_time") or 0)
        polyline = a.get("summary_polyline") or (a.get("map") or {}).get("summary_polyline", "")
        if polyline:
            score += 500  # has route
        if a.get("average_cadence") is not None:
            score += 100  # has cadence
        return score

    # Sort by start time
    indexed = [(i, a, parse_start(a)) for i, a in enumerate(activities)]
    indexed_valid = [(i, a, t) for i, a, t in indexed if t is not None]
    indexed_valid.sort(key=lambda x: x[2])

    remove = set()
    for j in range(len(indexed_valid)):
        if j in remove:
            continue
        i_j, a_j, t_j = indexed_valid[j]
        sport_j = (a_j.get("sport_type") or a_j.get("type") or "").lower()
        for k in range(j + 1, len(indexed_valid)):
            if k in remove:
                continue
            i_k, a_k, t_k = indexed_valid[k]
            sport_k = (a_k.get("sport_type") or a_k.get("type") or "").lower()

            if sport_j != sport_k:
                continue

            gap_min = abs((t_k - t_j).total_seconds()) / 60
            if gap_min > 15:
                break  # sorted by time, no more overlaps

            # Overlap detected — remove the less rich one
            if richness(a_j) >= richness(a_k):
                remove.add(k)
                dev_drop = a_k.get("device_name", "?")
                dev_keep = a_j.get("device_name", "?")
            else:
                remove.add(j)
                dev_drop = a_j.get("device_name", "?")
                dev_keep = a_k.get("device_name", "?")
            print(f"  [DEDUP] {sport_j} overlap — kept {dev_keep}, dropped {dev_drop}")

    kept = [a for idx, (i, a, t) in enumerate(indexed_valid) if idx not in remove]
    # Also include any activities with no parseable start time
    no_time = [a for a in activities if parse_start(a) is None]
    result = kept + no_time
    if len(result) < len(activities):
        print(f"  [DEDUP] {len(activities)} → {len(result)} activities (removed {len(activities) - len(result)} duplicates)")
    return result


'''

# ─────────────────────────────────────────────
# Patch 2: Call dedup in lambda_handler before grouping by date
# ─────────────────────────────────────────────

OLD_HANDLER_SECTION = '''    by_date = {}
    for activity in activities:
        local_date = activity["start_date_local"][:10]
        if local_date not in by_date:
            by_date[local_date] = []
        by_date[local_date].append(activity)'''

NEW_HANDLER_SECTION = '''    # Deduplicate multi-device recordings at ingestion time (v2.34.0)
    orig_count = len(activities)
    activities = dedup_activities(activities)
    if len(activities) < orig_count:
        print(f"[DEDUP] Global dedup: {orig_count} → {len(activities)} activities")

    by_date = {}
    for activity in activities:
        local_date = activity["start_date_local"][:10]
        if local_date not in by_date:
            by_date[local_date] = []
        by_date[local_date].append(activity)'''


def main():
    content = read_file(LAMBDA_FILE)

    # Check if already patched
    if "dedup_activities" in content:
        print("⏭️  strava_lambda.py already has dedup logic — skipping")
        return

    # Insert dedup function before save_to_s3
    anchor = "def save_to_s3("
    if anchor not in content:
        raise ValueError(f"Could not find anchor '{anchor}' in {LAMBDA_FILE}")
    content = content.replace(anchor, DEDUP_FN + anchor)

    # Patch lambda_handler to call dedup
    if OLD_HANDLER_SECTION not in content:
        raise ValueError("Could not find handler section to patch")
    content = content.replace(OLD_HANDLER_SECTION, NEW_HANDLER_SECTION)

    write_file(LAMBDA_FILE, content)
    print("✅ strava_lambda.py patched with ingestion-level dedup")


if __name__ == "__main__":
    main()
