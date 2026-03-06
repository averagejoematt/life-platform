"""
patch_garmin_phase1.py — Enhance Garmin ingestion Lambda (v1.4.0 → v1.5.0)

Phase 1 of API gap closure:
  1. Expand extract_sleep: stage durations, start/end times, SpO2, respiration,
     restless moments, sleep sub-scores (quality, duration, deep, rem, light, awakenings)
  2. Expand extract_activities: avg_hr, max_hr, calories per activity
  3. Docstring update to reflect new fields

Run locally — generates garmin_lambda.py ready for deploy.
"""

INPUT  = "garmin_lambda.py"
OUTPUT = "garmin_lambda.py"  # overwrite in place


def patch():
    with open(INPUT, "r") as f:
        code = f.read()

    # ── 1. Update version in docstring ────────────────────────────────────
    code = code.replace(
        'garmin_lambda.py — Daily Garmin ingestion Lambda (v1.4.0)',
        'garmin_lambda.py — Daily Garmin ingestion Lambda (v1.5.0)'
    )

    # ── 2. Replace extract_sleep with expanded version ────────────────────
    old_sleep = '''def extract_sleep(api, date_str: str) -> dict:
    result = {}
    try:
        data = api.get_sleep_data(date_str)
        if data:
            daily    = data.get("dailySleepDTO") or {}
            duration = daily.get("sleepTimeSeconds")
            score    = daily.get("sleepScore")
            if duration and duration > 0:
                result["sleep_duration_seconds"] = int(duration)
            if score and score > 0:
                result["sleep_score"] = safe_float(score)
        if result:
            print(f"Sleep: {result.get('sleep_duration_seconds')}s score={result.get('sleep_score')}")
    except Exception as e:
        print(f"Warning: sleep extraction failed: {e}")
    return result'''

    new_sleep = '''def extract_sleep(api, date_str: str) -> dict:
    """
    Extract comprehensive sleep data from Garmin get_sleep_data API.

    Fields extracted (v1.5.0 expansion):
      Core:       sleep_duration_seconds, sleep_score
      Stages:     deep_sleep_seconds, light_sleep_seconds, rem_sleep_seconds,
                  awake_sleep_seconds, unmeasurable_sleep_seconds
      Timing:     sleep_start_local, sleep_end_local
      Biometrics: sleep_spo2_avg, sleep_spo2_low, sleep_avg_respiration,
                  sleep_lowest_respiration
      Quality:    restless_moments_count
      Sub-scores: sleep_score_quality, sleep_score_duration, sleep_score_deep,
                  sleep_score_rem, sleep_score_light, sleep_score_awakenings

    This makes Garmin a second complete sleep source alongside Eight Sleep,
    enabling cross-device validation via the existing get_device_agreement tool.
    """
    result = {}
    try:
        data = api.get_sleep_data(date_str)
        if not data:
            return result

        daily = data.get("dailySleepDTO") or {}

        # ── Core (existing) ──
        duration = daily.get("sleepTimeSeconds")
        score = daily.get("sleepScore")
        if duration and duration > 0:
            result["sleep_duration_seconds"] = int(duration)
        if score and score > 0:
            result["sleep_score"] = safe_float(score)

        # ── Sleep stages ──
        for field, key in [
            ("deep_sleep_seconds",          "deepSleepSeconds"),
            ("light_sleep_seconds",         "lightSleepSeconds"),
            ("rem_sleep_seconds",           "remSleepSeconds"),
            ("awake_sleep_seconds",         "awakeSleepSeconds"),
            ("unmeasurable_sleep_seconds",  "unmeasurableSleepSeconds"),
        ]:
            val = daily.get(key)
            if val is not None and val >= 0:
                result[field] = int(val)

        # ── Sleep timing ──
        # Prefer local timestamps for circadian analysis
        sleep_start = daily.get("sleepStartTimestampLocal")
        sleep_end = daily.get("sleepEndTimestampLocal")
        if sleep_start:
            # Convert epoch millis to ISO string
            try:
                ts = sleep_start / 1000 if sleep_start > 1e12 else sleep_start
                result["sleep_start_local"] = datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")
            except (OSError, ValueError):
                pass
        if sleep_end:
            try:
                ts = sleep_end / 1000 if sleep_end > 1e12 else sleep_end
                result["sleep_end_local"] = datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")
            except (OSError, ValueError):
                pass

        # ── Sleep biometrics (SpO2 + respiration during sleep) ──
        spo2_avg = daily.get("averageSpO2Value")
        spo2_low = daily.get("lowestSpO2Value")
        resp_avg = daily.get("averageRespirationValue")
        resp_low = daily.get("lowestRespirationValue")
        if spo2_avg and spo2_avg > 0:
            result["sleep_spo2_avg"] = safe_float(spo2_avg)
        if spo2_low and spo2_low > 0:
            result["sleep_spo2_low"] = safe_float(spo2_low)
        if resp_avg and resp_avg > 0:
            result["sleep_avg_respiration"] = safe_float(resp_avg)
        if resp_low and resp_low > 0:
            result["sleep_lowest_respiration"] = safe_float(resp_low)

        # ── Restless moments ──
        restless = daily.get("restlessMomentsCount")
        if restless is not None and restless >= 0:
            result["restless_moments_count"] = int(restless)

        # ── Sleep sub-scores (breakdown of overall sleep_score) ──
        sleep_scores = daily.get("sleepScores") or {}
        for field, key in [
            ("sleep_score_quality",     "qualityScore"),
            ("sleep_score_duration",    "durationScore"),
            ("sleep_score_deep",        "deepScore"),
            ("sleep_score_rem",         "remScore"),
            ("sleep_score_light",       "lightScore"),
            ("sleep_score_awakenings",  "awakeningsScore"),
        ]:
            val = sleep_scores.get(key)
            if val is not None and val > 0:
                result[field] = safe_float(val)

        if result:
            stages = []
            if "deep_sleep_seconds" in result:
                stages.append(f"deep={result['deep_sleep_seconds']//60}m")
            if "light_sleep_seconds" in result:
                stages.append(f"light={result['light_sleep_seconds']//60}m")
            if "rem_sleep_seconds" in result:
                stages.append(f"rem={result['rem_sleep_seconds']//60}m")
            if "awake_sleep_seconds" in result:
                stages.append(f"awake={result['awake_sleep_seconds']//60}m")
            stage_str = " ".join(stages)
            print(f"Sleep: {result.get('sleep_duration_seconds')}s score={result.get('sleep_score')} "
                  f"{stage_str} spo2={result.get('sleep_spo2_avg')} restless={result.get('restless_moments_count')}")

    except Exception as e:
        print(f"Warning: sleep extraction failed: {e}")
    return result'''

    if old_sleep not in code:
        raise RuntimeError("Could not find extract_sleep to replace — has the function changed?")
    code = code.replace(old_sleep, new_sleep)

    # ── 3. Expand extract_activities to include avg/max HR and calories ───
    old_activities_start = '''            ga["start_time"]     = act.get("startTimeLocal")
            ga["duration_secs"]  = safe_float(act.get("duration"))
            ga["distance_meters"] = safe_float(act.get("distance"))'''

    new_activities_start = '''            ga["start_time"]     = act.get("startTimeLocal")
            ga["duration_secs"]  = safe_float(act.get("duration"))
            ga["distance_meters"] = safe_float(act.get("distance"))

            # Core activity metrics (v1.5.0 — previously missing)
            avg_hr = safe_float(act.get("averageHR"))
            max_hr = safe_float(act.get("maxHR"))
            calories = safe_float(act.get("calories"))
            avg_speed = safe_float(act.get("averageSpeed"))
            max_speed = safe_float(act.get("maxSpeed"))
            if avg_hr is not None and avg_hr > 0:
                ga["avg_hr"] = avg_hr
            if max_hr is not None and max_hr > 0:
                ga["max_hr"] = max_hr
            if calories is not None and calories > 0:
                ga["calories"] = calories
            if avg_speed is not None and avg_speed > 0:
                ga["avg_speed_mps"] = avg_speed
            if max_speed is not None and max_speed > 0:
                ga["max_speed_mps"] = max_speed'''

    if old_activities_start not in code:
        raise RuntimeError("Could not find extract_activities insertion point — has the function changed?")
    code = code.replace(old_activities_start, new_activities_start)

    # ── 4. Update docstring to document new fields ────────────────────────
    old_data_pulled = '''Data pulled:
  BIOMETRICS (cross-device validation):
  resting_heart_rate, hrv_last_night, hrv_status, hrv_5min_high,
  avg_stress, max_stress, stress_qualifier,
  body_battery_high/low/end, avg_respiration, sleep_respiration, steps

  GARMIN-EXCLUSIVE BIOMETRICS:
  spo2_avg/low, vo2_max, fitness_age, training_status, training_load,
  training_readiness, sleep_duration_seconds, sleep_score,
  hr_zone_0..4_seconds, zone2_minutes, intensity_minutes_*,
  floors_climbed, active_calories, bmr_calories, total_calories_burned,
  garmin_acute_load, garmin_chronic_load

  GARMIN ACTIVITIES (proprietary fields not in Strava):
  garmin_activities[] — aerobic/anaerobic_training_effect, performance_condition,
  lactate_threshold_hr/speed, activity_training_load, body_battery_change,
  normalized_power_watts, training_stress_score, training_effect_label,
  avg_cadence, stride_length_m, ground_contact_time_ms,
  vertical_oscillation_cm, vertical_ratio_pct'''

    new_data_pulled = '''Data pulled:
  BIOMETRICS (cross-device validation):
  resting_heart_rate, hrv_last_night, hrv_status, hrv_5min_high,
  avg_stress, max_stress, stress_qualifier,
  body_battery_high/low/end, avg_respiration, sleep_respiration, steps

  GARMIN-EXCLUSIVE BIOMETRICS:
  spo2_avg/low, vo2_max, fitness_age, training_status, training_load,
  training_readiness,
  hr_zone_0..4_seconds, zone2_minutes, intensity_minutes_*,
  floors_climbed, active_calories, bmr_calories, total_calories_burned,
  garmin_acute_load, garmin_chronic_load

  SLEEP (v1.5.0 expansion — was 2 fields, now 18):
  sleep_duration_seconds, sleep_score,
  deep_sleep_seconds, light_sleep_seconds, rem_sleep_seconds,
  awake_sleep_seconds, unmeasurable_sleep_seconds,
  sleep_start_local, sleep_end_local,
  sleep_spo2_avg, sleep_spo2_low,
  sleep_avg_respiration, sleep_lowest_respiration,
  restless_moments_count,
  sleep_score_quality, sleep_score_duration, sleep_score_deep,
  sleep_score_rem, sleep_score_light, sleep_score_awakenings

  GARMIN ACTIVITIES (proprietary + core metrics):
  garmin_activities[] — avg_hr, max_hr, calories, avg_speed_mps, max_speed_mps,
  aerobic/anaerobic_training_effect, performance_condition,
  lactate_threshold_hr/speed, activity_training_load, body_battery_change,
  normalized_power_watts, training_stress_score, training_effect_label,
  avg_cadence, stride_length_m, ground_contact_time_ms,
  vertical_oscillation_cm, vertical_ratio_pct'''

    if old_data_pulled not in code:
        raise RuntimeError("Could not find Data pulled docstring to replace")
    code = code.replace(old_data_pulled, new_data_pulled)

    # ── 5. Update version change notes in docstring ───────────────────────
    old_version_notes = '''v1.3.0 changes:
  - Fixed auth flow: properly calls api.login() to resolve display_name
  - Added display_name fallback via profile API endpoints
  - Saves refreshed OAuth tokens after each successful invocation
  - Better error handling for expired/invalid tokens'''

    new_version_notes = '''v1.5.0 changes (Phase 1 API gap closure):
  - Expanded extract_sleep: 2 fields → 18 fields (stages, timing, SpO2,
    respiration, restless moments, sub-scores)
  - Expanded extract_activities: added avg_hr, max_hr, calories, avg/max speed
  - Garmin is now a complete second sleep source alongside Eight Sleep

v1.3.0 changes:
  - Fixed auth flow: properly calls api.login() to resolve display_name
  - Added display_name fallback via profile API endpoints
  - Saves refreshed OAuth tokens after each successful invocation
  - Better error handling for expired/invalid tokens'''

    if old_version_notes not in code:
        raise RuntimeError("Could not find version notes to replace")
    code = code.replace(old_version_notes, new_version_notes)

    with open(OUTPUT, "w") as f:
        f.write(code)

    print(f"✅ Patched {OUTPUT}")
    print("   - extract_sleep: 2 → 18 fields")
    print("   - extract_activities: +5 fields (avg_hr, max_hr, calories, avg/max speed)")
    print("   - Docstring updated to v1.5.0")
    print(f"\nNext: run deploy_garmin_v150.sh to push to Lambda")


if __name__ == "__main__":
    patch()
