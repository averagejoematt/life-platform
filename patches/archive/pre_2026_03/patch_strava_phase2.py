"""
patch_strava_phase2.py — Enhance Strava ingestion Lambda (Phase 2 API gap closure)

Adds per-activity HR zone distribution via GET /activities/{id}/zones.
This gives exact time-in-zone data for each activity, replacing the v2.13.0
approximation that classified entire activities by average HR.

For daily ingestion (1-3 activities), this adds 1-3 extra API calls.
Rate limit: 100 requests/15 min, 1000/day — no concern for daily use.

Changes:
  1. New function: fetch_activity_zones(strava_id, secret)
  2. normalize_activity gains: hr_zone_seconds (list), zone2_seconds, zone_sensor_based
  3. Day-level aggregation: total_zone2_seconds across all activities
  4. Only fetches zones for activities with has_heartrate=True
"""

INPUT  = "strava_lambda.py"
OUTPUT = "strava_lambda.py"


def patch():
    with open(INPUT, "r") as f:
        code = f.read()

    # ── 1. Add fetch_activity_zones function after strava_get ─────────────
    insert_after = '''    with urllib.request.urlopen(req) as response:
        return json.loads(response.read()), secret


def fetch_activities(secret, after_ts, before_ts=None):'''

    zones_function = '''    with urllib.request.urlopen(req) as response:
        return json.loads(response.read()), secret


def fetch_activity_zones(strava_id: str, secret: dict) -> tuple:
    """
    Fetch HR zone distribution for a single activity.

    GET /activities/{id}/zones returns time in each HR zone.
    Only called for activities with has_heartrate=True.

    Returns:
        (zone_data dict, updated secret)
        zone_data: {
            "hr_zone_seconds": [z1_secs, z2_secs, z3_secs, z4_secs, z5_secs],
            "zone2_seconds": int,
            "zone_sensor_based": bool,
            "zone_boundaries": [z1_max, z2_max, z3_max, z4_max]
        }
        Returns empty dict if zones not available.
    """
    try:
        url = f"https://www.strava.com/api/v3/activities/{strava_id}/zones"
        data, secret = strava_get(url, secret)

        if not data:
            return {}, secret

        # Find heartrate zone data
        hr_zones = None
        for zone_set in data:
            if zone_set.get("type") == "heartrate":
                hr_zones = zone_set
                break

        if not hr_zones:
            return {}, secret

        buckets = hr_zones.get("distribution_buckets") or []
        if len(buckets) < 2:
            return {}, secret

        zone_seconds = [int(b.get("time", 0)) for b in buckets]
        # Zone boundaries (max HR of each zone except last)
        boundaries = [int(b.get("max", 0)) for b in buckets[:-1]]

        result = {
            "hr_zone_seconds": zone_seconds,
            "zone_sensor_based": hr_zones.get("sensor_based", False),
        }

        # Zone boundaries for reference
        if boundaries:
            result["zone_boundaries"] = boundaries

        # Zone 2 is typically index 1 (0-indexed: Z1=recovery, Z2=aerobic, Z3=tempo, Z4=threshold, Z5=anaerobic)
        if len(zone_seconds) > 1:
            result["zone2_seconds"] = zone_seconds[1]

        print(f"  Zones for {strava_id}: {[f'Z{i+1}={s//60}m' for i, s in enumerate(zone_seconds)]}")
        return result, secret

    except Exception as e:
        print(f"  Warning: zones fetch failed for {strava_id}: {e}")
        return {}, secret


def fetch_activities(secret, after_ts, before_ts=None):'''

    if insert_after not in code:
        raise RuntimeError("Could not find insertion point for fetch_activity_zones")
    code = code.replace(insert_after, zones_function)

    # ── 2. Update normalize_activity to accept and merge zone data ────────
    old_normalize_sig = '''def normalize_activity(activity):
    """Extract the fields we care about from a Strava activity summary."""
    return {'''

    new_normalize_sig = '''def normalize_activity(activity, zone_data=None):
    """Extract the fields we care about from a Strava activity summary + zones."""
    result = {'''

    if old_normalize_sig not in code:
        raise RuntimeError("Could not find normalize_activity signature")
    code = code.replace(old_normalize_sig, new_normalize_sig)

    # Change the return at the end of normalize_activity to merge zone data
    old_normalize_end = '''        "location_city": activity.get("location_city"),
        "location_state": activity.get("location_state"),
        "location_country": activity.get("location_country"),
    }'''

    new_normalize_end = '''        "location_city": activity.get("location_city"),
        "location_state": activity.get("location_state"),
        "location_country": activity.get("location_country"),
    }

    # Merge HR zone data if available (Phase 2 enhancement)
    if zone_data:
        result.update(zone_data)

    return result'''

    if old_normalize_end not in code:
        raise RuntimeError("Could not find normalize_activity ending")
    code = code.replace(old_normalize_end, new_normalize_end)

    # ── 3. Update the processing loop to fetch zones and pass to normalize ──
    old_processing = '''    for date_str, day_activities in sorted(by_date.items()):
        normalized = [normalize_activity(a) for a in day_activities]
        save_to_s3(date_str, normalized, day_activities)
        save_to_dynamodb(date_str, normalized)'''

    new_processing = '''    for date_str, day_activities in sorted(by_date.items()):
        normalized = []
        for a in day_activities:
            # Fetch HR zones for activities with heart rate data (Phase 2)
            zone_data = {}
            if a.get("has_heartrate") and a.get("id"):
                zone_data, secret = fetch_activity_zones(str(a["id"]), secret)
            normalized.append(normalize_activity(a, zone_data))
        save_to_s3(date_str, normalized, day_activities)
        save_to_dynamodb(date_str, normalized)'''

    if old_processing not in code:
        raise RuntimeError("Could not find processing loop")
    code = code.replace(old_processing, new_processing)

    # ── 4. Add total_zone2_seconds to day-level aggregation ───────────────
    old_day_agg = '''        "sport_types": list(set(a.get("sport_type", "") for a in activities)),
    }'''

    new_day_agg = '''        "sport_types": list(set(a.get("sport_type", "") for a in activities)),
        # Phase 2: aggregate zone data across all activities for the day
        "total_zone2_seconds": sum(a.get("zone2_seconds") or 0 for a in activities),
    }'''

    if old_day_agg not in code:
        raise RuntimeError("Could not find day-level aggregation")
    code = code.replace(old_day_agg, new_day_agg)

    with open(OUTPUT, "w") as f:
        f.write(code)

    print(f"✅ Patched {OUTPUT}")
    print("   - Added fetch_activity_zones() for per-activity HR zone distribution")
    print("   - normalize_activity now merges zone data (hr_zone_seconds, zone2_seconds)")
    print("   - Day-level total_zone2_seconds aggregation added")
    print("   - Only fetches zones for activities with HR data")
    print(f"\nNext: run deploy_strava_phase2.sh to push to Lambda")


if __name__ == "__main__":
    patch()
