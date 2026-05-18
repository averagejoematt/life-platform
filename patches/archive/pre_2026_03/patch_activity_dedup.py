#!/usr/bin/env python3
"""
Patch: Strava Activity Deduplication (v2.2.2)

Problem: Multiple devices (WHOOP, Garmin) record the same activity and both sync
to Strava independently. The daily brief shows duplicates and scores inflate
(activity_count, total_moving_time_seconds both over-counted).

Example: Feb 24 "Afternoon Walk" recorded by WHOOP (19 min, no GPS) AND
Garmin (33 min, 1.7 mi, GPS). Both show in training report, and the
movement score counts 125 min of exercise instead of 106 min.

Fix: Add dedup_activities() that detects overlapping activities (same sport_type,
start times within 15 min) and keeps the richer record (prefers GPS/distance,
then longer duration). Runs right after gather_daily_data() so all downstream
consumers (display, scoring, AI prompts) get clean data.

Recomputes strava aggregate fields (activity_count, total_moving_time_seconds)
from the deduped list.
"""

LAMBDA_FILE = "daily_brief_lambda.py"

DEDUP_FUNCTION = '''

def dedup_activities(activities):
    """Remove duplicate activities from multi-device Strava sync.
    
    When multiple devices (WHOOP, Garmin, Apple Watch) record the same workout,
    Strava stores each as a separate activity. This detects overlaps and keeps
    the richer record.
    
    Overlap = same sport_type AND start times within 15 minutes.
    Keep = prefer has-distance over no-distance, then longer duration.
    """
    if len(activities) <= 1:
        return activities

    from datetime import datetime as _dt

    def parse_start(a):
        s = a.get("start_date_local") or a.get("start_date") or ""
        try:
            return _dt.fromisoformat(str(s).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    def richness(a):
        """Score how much data an activity has. Higher = keep."""
        score = 0
        dist = float(a.get("distance_meters") or 0)
        if dist > 0:
            score += 1000  # GPS data is strong signal
        score += float(a.get("moving_time_seconds") or 0)  # tiebreak: longer duration
        if a.get("summary_polyline"):
            score += 500  # has route
        if a.get("average_cadence") is not None:
            score += 100  # has cadence
        return score

    # Sort by start time
    indexed = [(i, a, parse_start(a)) for i, a in enumerate(activities)]
    indexed = [(i, a, t) for i, a, t in indexed if t is not None]
    indexed.sort(key=lambda x: x[2])

    remove = set()
    for j in range(len(indexed)):
        if j in remove:
            continue
        i_j, a_j, t_j = indexed[j]
        sport_j = (a_j.get("sport_type") or a_j.get("type") or "").lower()
        for k in range(j + 1, len(indexed)):
            if k in remove:
                continue
            i_k, a_k, t_k = indexed[k]
            sport_k = (a_k.get("sport_type") or a_k.get("type") or "").lower()

            # Must be same sport type
            if sport_j != sport_k:
                continue

            # Must start within 15 minutes of each other
            gap_min = abs((t_k - t_j).total_seconds()) / 60
            if gap_min > 15:
                break  # sorted by time, no more overlaps possible

            # Overlap detected — remove the less rich one
            if richness(a_j) >= richness(a_k):
                remove.add(k)
                dev_drop = a_k.get("device_name", "?")
                dev_keep = a_j.get("device_name", "?")
            else:
                remove.add(j)
                dev_drop = a_j.get("device_name", "?")
                dev_keep = a_k.get("device_name", "?")
            print("[INFO] Dedup: " + sport_j + " overlap — kept " + dev_keep + ", dropped " + dev_drop)

    kept = [a for i, (_, a, _) in enumerate(indexed) if i not in remove]
    # Also include any activities that had no parseable start time
    no_time = [a for a in activities if parse_start(a) is None]
    return kept + no_time

'''

DEDUP_CALL = '''
    # Deduplicate multi-device Strava activities (v2.2.2)
    strava = data.get("strava")
    if strava and strava.get("activities"):
        orig_count = len(strava["activities"])
        strava["activities"] = dedup_activities(strava["activities"])
        deduped_count = len(strava["activities"])
        if deduped_count < orig_count:
            # Recompute aggregates from deduped list
            strava["activity_count"] = deduped_count
            strava["total_moving_time_seconds"] = sum(
                float(a.get("moving_time_seconds") or 0) for a in strava["activities"])
            print("[INFO] Dedup: " + str(orig_count) + " → " + str(deduped_count) + " activities")

'''


def patch():
    with open(LAMBDA_FILE, "r") as f:
        code = f.read()

    # -------------------------------------------------------------------------
    # Fix 1: Insert dedup_activities function before dedup call site
    # Place it right before the DAY GRADE section
    # -------------------------------------------------------------------------
    marker = "# ==============================================================================\n# DAY GRADE"
    if marker not in code:
        print("[ERROR] Could not find DAY GRADE section marker")
        return False
    code = code.replace(marker, DEDUP_FUNCTION + "\n" + marker)
    print("[OK] Fix 1: dedup_activities() function added")

    # -------------------------------------------------------------------------
    # Fix 2: Call dedup right after gather_daily_data()
    # -------------------------------------------------------------------------
    old_call = '''    data = gather_daily_data(profile, yesterday)
    print("[INFO] Date: " + yesterday + " | sources: " +
          ", ".join(k for k in ["whoop", "sleep", "macrofactor", "habitify", "apple", "strava", "mf_workouts"] if data.get(k)))'''

    new_call = '''    data = gather_daily_data(profile, yesterday)
    print("[INFO] Date: " + yesterday + " | sources: " +
          ", ".join(k for k in ["whoop", "sleep", "macrofactor", "habitify", "apple", "strava", "mf_workouts"] if data.get(k)))
''' + DEDUP_CALL

    if old_call not in code:
        print("[ERROR] Could not find gather_daily_data call site")
        return False
    code = code.replace(old_call, new_call)
    print("[OK] Fix 2: dedup call inserted after gather_daily_data()")

    # -------------------------------------------------------------------------
    # Update version
    # -------------------------------------------------------------------------
    code = code.replace(
        "Daily Brief Lambda — v2.2.1 (Day Grade Zero-Score Fix)",
        "Daily Brief Lambda — v2.2.2 (Day Grade Fix + Activity Dedup)"
    )
    print("[OK] Version header updated to v2.2.2")

    with open(LAMBDA_FILE, "w") as f:
        f.write(code)

    print("\n[DONE] Patch applied. Run deploy_daily_brief_v222.sh to deploy.")
    return True


if __name__ == "__main__":
    patch()
