"""
garmin_lambda.py — Daily Garmin ingestion Lambda (v1.5.0)

Fetches one day of biometric + activity data from Garmin Connect using OAuth tokens
stored in Secrets Manager and writes a single DynamoDB record + S3 backup.

v1.5.0 changes (Phase 1 API gap closure):
  - Expanded extract_sleep: 2 fields → 18 fields (stages, timing, SpO2,
    respiration, restless moments, sub-scores)
  - Expanded extract_activities: added avg_hr, max_hr, calories, avg/max speed
  - Garmin is now a complete second sleep source alongside Eight Sleep

v1.3.0 changes:
  - Fixed auth flow: properly calls api.login() to resolve display_name
  - Added display_name fallback via profile API endpoints
  - Saves refreshed OAuth tokens after each successful invocation
  - Better error handling for expired/invalid tokens

Data pulled:
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
  vertical_oscillation_cm, vertical_ratio_pct

DynamoDB item:
  pk = USER#matthew#SOURCE#garmin
  sk = DATE#YYYY-MM-DD

Auth pattern:
  First-auth runs interactively via setup_garmin_auth.py on local machine.
  OAuth tokens stored in Secrets Manager life-platform/garmin as JSON.
  Lambda loads stored garth tokens, calls login() to resolve display_name,
  and saves refreshed tokens back to keep them alive between daily runs.

IAM role: lambda-garmin-ingestion-role
Schedule: 9:30 AM PT daily (17:30 UTC)
"""

import json
import os
import logging
import boto3
from datetime import datetime, timezone, timedelta
from decimal import Decimal

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger
    logger = get_logger("garmin")
except ImportError:
    logger = logging.getLogger("garmin")
    logger.setLevel(logging.INFO)

# ── Constants ──────────────────────────────────────────────────────────────────
SECRET_NAME    = "life-platform/garmin"
# ── Config (env vars with backwards-compatible defaults) ──
REGION         = os.environ.get("AWS_REGION", "us-west-2")
S3_BUCKET      = os.environ["S3_BUCKET"]
DYNAMODB_TABLE = os.environ.get("TABLE_NAME", "life-platform")
USER_ID        = os.environ["USER_ID"]
LOOKBACK_DAYS  = int(os.environ.get("LOOKBACK_DAYS", "7"))

# ── AWS clients ────────────────────────────────────────────────────────────────
secrets_client = boto3.client("secretsmanager", region_name=REGION)
s3_client      = boto3.client("s3",             region_name=REGION)
dynamodb       = boto3.resource("dynamodb",      region_name=REGION)
table          = dynamodb.Table(DYNAMODB_TABLE)


# ── Serialisation ──────────────────────────────────────────────────────────────
def floats_to_decimal(obj):
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [floats_to_decimal(v) for v in obj]
    return obj


def safe_float(val):
    try:
        return round(float(val), 2) if val is not None else None
    except (TypeError, ValueError):
        return None


# ── Secrets ────────────────────────────────────────────────────────────────────
def get_secret():
    resp = secrets_client.get_secret_value(SecretId=SECRET_NAME)
    return json.loads(resp["SecretString"])


def save_secret(secret: dict):
    secrets_client.update_secret(
        SecretId=SECRET_NAME,
        SecretString=json.dumps(secret),
    )


# ── Garmin auth ────────────────────────────────────────────────────────────────
def get_garmin_client(secret: dict):
    """
    Initialise garminconnect.Garmin using stored garth OAuth tokens.

    Auth flow:
      1. Load stored garth tokens from Secrets Manager
      2. Wire garth client into garminconnect Garmin object
      3. Resolve display_name via profile API (required for URL paths)
      4. Save refreshed tokens back to Secrets Manager

    NOTE: Lambda cannot do interactive garth.login() (no stdin for MFA).
    If tokens are expired, re-run setup_garmin_auth.py locally.

    The display_name is critical: garminconnect uses it in URL paths like
    /usersummary/daily/{display_name}. If None, those calls return 403.
    """
    import garth
    from garminconnect import Garmin

    email    = secret["email"]
    password = secret["password"]

    # Step 1: Load stored garth tokens
    if not secret.get("garth_tokens"):
        raise RuntimeError(
            "No garth tokens in Secrets Manager. "
            "Run setup_garmin_auth.py locally to authenticate."
        )

    try:
        garth.client.loads(secret["garth_tokens"])
        print("Loaded stored garth OAuth tokens.")
    except Exception as e:
        raise RuntimeError(
            f"Stored garth tokens invalid ({e}). "
            "Run setup_garmin_auth.py locally to re-authenticate."
        ) from e

    # Step 2: Wire garth into garminconnect
    api = Garmin(email=email, password=password)
    api.garth = garth.client

    # Step 3: Resolve display_name from profile API
    for profile_path in [
        "/userprofile-service/socialProfile",
        "/userprofile-service/userdisplayname",
    ]:
        try:
            profile = garth.client.connectapi(profile_path)
            name = None
            if isinstance(profile, dict):
                name = (profile.get("displayName")
                        or profile.get("userName")
                        or profile.get("fullName"))
            elif isinstance(profile, str):
                name = profile.strip()
            if name:
                api.display_name = name
                print(f"Resolved display_name: {name} (from {profile_path})")
                break
        except Exception as e:
            print(f"Profile path {profile_path} failed: {e}")

    if not api.display_name:
        raise RuntimeError(
            "Could not resolve Garmin display_name — tokens may be expired. "
            "Run setup_garmin_auth.py locally to re-authenticate."
        )

    # Step 4: Save refreshed tokens to Secrets Manager
    try:
        new_tokens = garth.client.dumps()
        if new_tokens and new_tokens != secret.get("garth_tokens"):
            secret["garth_tokens"] = new_tokens
            save_secret(secret)
            print("Refreshed OAuth tokens saved to Secrets Manager.")
    except Exception as e:
        print(f"Warning: could not save refreshed tokens ({e})")

    return api


# ── Data extraction ────────────────────────────────────────────────────────────
def extract_body_battery(api, date_str: str) -> dict:
    result = {}
    try:
        data = api.get_body_battery(date_str, date_str)
        if not data:
            return result
        values = []
        for entry in data:
            arr = entry.get("bodyBatteryValuesArray") or []
            for row in arr:
                if len(row) >= 2 and row[1] is not None:
                    values.append(int(row[1]))
        if values:
            result["body_battery_high"] = max(values)
            result["body_battery_low"]  = min(values)
            result["body_battery_end"]  = values[-1]
            print(f"Body Battery: high={result['body_battery_high']}, low={result['body_battery_low']}, end={result['body_battery_end']}")
    except Exception as e:
        print(f"Warning: body battery extraction failed: {e}")
    return result


def extract_hrv(api, date_str: str) -> dict:
    result = {}
    try:
        data = api.get_hrv_data(date_str)
        if not data:
            return result
        summary    = data.get("hrvSummary") or {}
        last_night = summary.get("lastNight")
        status     = summary.get("status")
        high       = summary.get("lastNight5MinHigh")
        if last_night is not None:
            result["hrv_last_night"] = safe_float(last_night)
        if status and status not in ("NONE", "UNQUALIFIED", ""):
            result["hrv_status"] = status
        if high is not None:
            result["hrv_5min_high"] = safe_float(high)
        if result:
            print(f"HRV: last_night={result.get('hrv_last_night')}ms status={result.get('hrv_status')}")
    except Exception as e:
        print(f"Warning: HRV extraction failed: {e}")
    return result


def extract_stress(api, date_str: str) -> dict:
    result = {}
    try:
        data = api.get_stress_data(date_str)
        if not data:
            return result
        avg_stress = data.get("avgStressLevel")
        max_stress = data.get("maxStressLevel")
        qualifier  = data.get("stressQualifier")
        if avg_stress is not None and avg_stress >= 0:
            result["avg_stress"] = safe_float(avg_stress)
        if max_stress is not None and max_stress >= 0:
            result["max_stress"] = safe_float(max_stress)
        if qualifier:
            result["stress_qualifier"] = qualifier
        if result:
            print(f"Stress: avg={result.get('avg_stress')} max={result.get('max_stress')} qualifier={result.get('stress_qualifier')}")
    except Exception as e:
        print(f"Warning: stress extraction failed: {e}")
    return result


def extract_user_summary(api, date_str: str) -> dict:
    result = {}
    try:
        data = api.get_user_summary(date_str)
        if not data:
            return result
        rhr   = data.get("restingHeartRate")
        steps = data.get("totalSteps")
        if rhr is not None and rhr > 0:
            result["resting_heart_rate"] = safe_float(rhr)
        if steps is not None and steps >= 0:
            result["steps"] = int(steps)
        if result:
            print(f"Summary: RHR={result.get('resting_heart_rate')}bpm steps={result.get('steps')}")
    except Exception as e:
        print(f"Warning: user summary extraction failed: {e}")
    return result


def extract_respiration(api, date_str: str) -> dict:
    result = {}
    try:
        data = api.get_respiration_data(date_str)
        if not data:
            return result
        avg_waking = data.get("avgWakingRespirationValue")
        avg_sleep  = data.get("avgSleepRespirationValue")
        if avg_waking is not None and avg_waking > 0:
            result["avg_respiration"] = safe_float(avg_waking)
        if avg_sleep is not None and avg_sleep > 0:
            result["sleep_respiration"] = safe_float(avg_sleep)
        if result:
            print(f"Respiration: waking={result.get('avg_respiration')} sleep={result.get('sleep_respiration')} brpm")
    except Exception as e:
        print(f"Warning: respiration extraction failed: {e}")
    return result


def extract_spo2(api, date_str: str) -> dict:
    result = {}
    try:
        data = api.get_spo2_data(date_str)
        if data:
            avg = data.get("averageSpO2")
            low = data.get("lowestSpO2")
            if avg and avg > 0:
                result["spo2_avg"] = safe_float(avg)
            if low and low > 0:
                result["spo2_low"] = safe_float(low)
        if result:
            print(f"SpO2: avg={result.get('spo2_avg')}% low={result.get('spo2_low')}%")
    except Exception as e:
        print(f"Warning: SpO2 extraction failed: {e}")
    return result


def extract_max_metrics(api, date_str: str) -> dict:
    result = {}
    try:
        data = api.get_max_metrics(date_str)
        if data and isinstance(data, list) and data:
            entry   = data[0] if isinstance(data[0], dict) else {}
            generic = entry.get("generic") or {}
            vo2     = generic.get("vo2MaxPreciseValue") or generic.get("vo2MaxValue")
            fit_age = generic.get("fitnessAge")
            if vo2 and vo2 > 0:
                result["vo2_max"] = safe_float(vo2)
            if fit_age and fit_age > 0:
                result["fitness_age"] = int(fit_age)
        if result:
            print(f"MaxMetrics: VO2max={result.get('vo2_max')} fitness_age={result.get('fitness_age')}")
    except Exception as e:
        print(f"Warning: max metrics extraction failed: {e}")
    return result


def extract_training_status(api, date_str: str) -> dict:
    result = {}
    try:
        data = api.get_training_status(date_str)
        if data:
            # Training status label
            mrt = data.get("mostRecentTrainingStatus") or {}
            latest_map = mrt.get("latestTrainingStatusData") or {}
            for device_id, device_data in latest_map.items():
                if not device_data.get("primaryTrainingDevice"):
                    continue
                feedback = device_data.get("trainingStatusFeedbackPhrase")
                if feedback:
                    result["training_status"] = feedback

                # Acute/chronic training load (replaces removed get_training_load)
                atl = device_data.get("acuteTrainingLoadDTO") or {}
                acute = safe_float(atl.get("dailyTrainingLoadAcute"))
                chronic = safe_float(atl.get("dailyTrainingLoadChronic"))
                acwr = safe_float(atl.get("dailyAcuteChronicWorkloadRatio"))
                if acute is not None:
                    result["garmin_acute_load"] = acute
                if chronic is not None:
                    result["garmin_chronic_load"] = chronic
                if acwr is not None:
                    result["garmin_acwr"] = acwr
                break

        if result:
            print(f"Training status: {result.get('training_status')} acute={result.get('garmin_acute_load')} chronic={result.get('garmin_chronic_load')} ACWR={result.get('garmin_acwr')}")
    except Exception as e:
        print(f"Warning: training status extraction failed: {e}")

    try:
        data = api.get_training_readiness(date_str)
        if data and isinstance(data, list) and data:
            entry = data[0]
            score = entry.get("score")
            if score and score > 0:
                result["training_readiness"] = safe_float(score)
            level = entry.get("level")
            if level:
                result["training_readiness_level"] = level
            hrv_weekly = entry.get("hrvWeeklyAverage")
            if hrv_weekly and hrv_weekly > 0:
                result["hrv_weekly_average"] = safe_float(hrv_weekly)
            recovery_time = entry.get("recoveryTime")
            if recovery_time is not None:
                result["recovery_time_hours"] = int(recovery_time)
            if result.get("training_readiness"):
                print(f"Training readiness: {result['training_readiness']} ({result.get('training_readiness_level')}) HRV_weekly={result.get('hrv_weekly_average')}ms recovery={result.get('recovery_time_hours')}h")
        elif data and isinstance(data, dict):
            # Fallback for dict response (older API versions)
            score = data.get("score") or data.get("trainingReadinessScore")
            if score and score > 0:
                result["training_readiness"] = safe_float(score)
                print(f"Training readiness: {score}")
    except Exception as e:
        print(f"Warning: training readiness extraction failed: {e}")
    return result


def extract_sleep(api, date_str: str) -> dict:
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
        print(f"Sleep API response type={type(data).__name__} truthy={bool(data)}")
        if data:
            print(f"Sleep API top keys: {list(data.keys()) if isinstance(data, dict) else 'not a dict'}")
        if not data:
            print("Sleep: no data returned from get_sleep_data")
            return result

        daily = data.get("dailySleepDTO") or {}
        print(f"dailySleepDTO keys: {list(daily.keys())[:10] if daily else 'empty'}")

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
    return result


def extract_hr_zones(api, date_str: str) -> dict:
    result = {}
    try:
        data = api.get_heart_rates(date_str)
        if data:
            zones = data.get("heartRateZones") or []
            for i, z in enumerate(zones):
                secs = z.get("secsInZone") or z.get("secondsInZone")
                if secs is not None:
                    result[f"hr_zone_{i}_seconds"] = int(secs)
            z2 = result.get("hr_zone_1_seconds")
            if z2:
                result["zone2_minutes"] = round(z2 / 60, 1)
        if result:
            print(f"HR zones: zone2={result.get('zone2_minutes')}min total_zones={len([k for k in result if 'zone' in k])}")
    except Exception as e:
        print(f"Warning: HR zones extraction failed: {e}")
    return result


def extract_intensity_minutes(api, date_str: str) -> dict:
    result = {}
    try:
        data = api.get_intensity_minutes_data(date_str)
        if data:
            mod = data.get("moderateIntensityMinutes")
            vig = data.get("vigorousIntensityMinutes")
            if mod is not None:
                result["intensity_minutes_moderate"] = int(mod)
            if vig is not None:
                result["intensity_minutes_vigorous"] = int(vig)
            if mod is not None and vig is not None:
                result["intensity_minutes_total"] = int(mod) + int(vig) * 2
        if result:
            print(f"Intensity minutes: mod={result.get('intensity_minutes_moderate')} vig={result.get('intensity_minutes_vigorous')}")
    except Exception as e:
        print(f"Warning: intensity minutes extraction failed: {e}")
    return result


def extract_stats(api, date_str: str) -> dict:
    result = {}
    try:
        data = api.get_stats(date_str)
        if data:
            floors = data.get("floorsAscended")
            active = data.get("activeKilocalories")
            bmr    = data.get("bmrKilocalories")
            total  = data.get("totalKilocalories")
            if floors is not None:
                result["floors_climbed"] = int(floors)
            if active and active > 0:
                result["active_calories"] = int(active)
            if bmr and bmr > 0:
                result["bmr_calories"] = int(bmr)
            if total and total > 0:
                result["total_calories_burned"] = int(total)
        if result:
            print(f"Stats: floors={result.get('floors_climbed')} active_cal={result.get('active_calories')} bmr={result.get('bmr_calories')}")
    except Exception as e:
        print(f"Warning: stats extraction failed: {e}")
    return result


def extract_activities(api, date_str: str) -> dict:
    """Garmin-proprietary per-activity fields not available via Strava."""
    result = {}
    try:
        activities = api.get_activities_by_date(date_str, date_str)
        if not activities:
            return result
        garmin_activities = []
        for act in activities:
            ga = {}
            aid = act.get("activityId")
            if aid:
                ga["garmin_activity_id"] = str(aid)
            ga["activity_name"]  = act.get("activityName")
            ga["activity_type"]  = (act.get("activityType") or {}).get("typeKey")
            ga["start_time"]     = act.get("startTimeLocal")
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
                ga["max_speed_mps"] = max_speed

            # Training analytics (Garmin proprietary)
            for key, field in [
                ("aerobic_training_effect",   "aerobicTrainingEffect"),
                ("anaerobic_training_effect",  "anaerobicTrainingEffect"),
                ("performance_condition",      "performanceCondition"),
                ("lactate_threshold_hr",       "lactateThresholdHeartRate"),
                ("lactate_threshold_speed_mps","lactateThresholdSpeed"),
                ("activity_training_load",     "activityTrainingLoad"),
                ("normalized_power_watts",     "normalizedPower"),
                ("training_stress_score",      "trainingStressScore"),
            ]:
                v = safe_float(act.get(field))
                if v is not None:
                    ga[key] = v

            te_msg = act.get("trainingEffectLabel") or act.get("aerobicTrainingEffectMessage")
            if te_msg:
                ga["training_effect_label"] = te_msg

            bb_ch = safe_float(act.get("bodyBatteryChange") or act.get("bodyBatteryDrained"))
            if bb_ch is not None:
                ga["body_battery_change"] = bb_ch

            # Running dynamics
            for key, field in [
                ("avg_cadence",             "averageRunningCadenceInStepsPerMinute"),
                ("stride_length_m",          "strideLength"),
                ("ground_contact_time_ms",   "groundContactTime"),
                ("vertical_oscillation_cm",  "verticalOscillation"),
                ("vertical_ratio_pct",       "verticalRatio"),
            ]:
                v = safe_float(act.get(field))
                if v is not None:
                    ga[key] = v

            ga = {k: v for k, v in ga.items() if v is not None}
            if ga:
                garmin_activities.append(ga)

        if garmin_activities:
            result["garmin_activities"]    = garmin_activities
            result["garmin_activity_count"] = len(garmin_activities)
            print(f"Activities: {len(garmin_activities)} Garmin activities with proprietary fields")
    except Exception as e:
        print(f"Warning: activities extraction failed: {e}")
    return result


# extract_training_load removed — get_training_load() no longer exists in garminconnect.
# Acute/chronic load now extracted from get_training_status() → acuteTrainingLoadDTO.
# See extract_training_status() above.


# ── Gap detection ──────────────────────────────────────────────────────────────
def find_missing_dates(lookback_days=LOOKBACK_DAYS):
    """Check DynamoDB for missing dates in the last N days. Returns sorted list of date strings."""
    from boto3.dynamodb.conditions import Key
    today = datetime.now(timezone.utc).date()
    expected_dates = set()
    for i in range(1, lookback_days + 1):
        expected_dates.add((today - timedelta(days=i)).strftime("%Y-%m-%d"))

    pk = f"USER#{USER_ID}#SOURCE#garmin"
    oldest = min(expected_dates)
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(pk) & Key("sk").between(f"DATE#{oldest}", f"DATE#{today.strftime('%Y-%m-%d')}"),
        ProjectionExpression="sk",
    )
    existing = {item["sk"][5:] for item in resp.get("Items", [])}
    missing = sorted(expected_dates - existing)
    if missing:
        print(f"[GAP-FILL] Found {len(missing)} missing dates in last {lookback_days} days: {missing}")
    else:
        print(f"[GAP-FILL] No gaps in last {lookback_days} days")
    return missing


# ── Core ingestion ─────────────────────────────────────────────────────────────
def ingest_day(target_date: str, secret: dict, api=None) -> dict:
    if api is None:
        api = get_garmin_client(secret)
    print(f"Fetching Garmin data for {target_date}...")

    record = {}
    record.update(extract_user_summary(api, target_date))
    record.update(extract_hrv(api, target_date))
    record.update(extract_stress(api, target_date))
    record.update(extract_body_battery(api, target_date))
    record.update(extract_respiration(api, target_date))
    record.update(extract_spo2(api, target_date))
    record.update(extract_max_metrics(api, target_date))
    record.update(extract_training_status(api, target_date))
    record.update(extract_sleep(api, target_date))
    record.update(extract_hr_zones(api, target_date))
    record.update(extract_intensity_minutes(api, target_date))
    record.update(extract_stats(api, target_date))
    record.update(extract_activities(api, target_date))

    if not record:
        print(f"No data returned from any Garmin endpoint for {target_date}.")
        return {}

    print(f"Total fields collected: {len(record)}")

    s3_key = f"raw/garmin/{target_date[:4]}/{target_date[5:7]}/{target_date[8:10]}.json"
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=json.dumps({
            "date":        target_date,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "parsed":      record,
        }, default=str),
        ContentType="application/json",
    )
    print(f"S3: s3://{S3_BUCKET}/{s3_key}")

    db_item = {
        "pk":             f"USER#{USER_ID}#SOURCE#garmin",
        "sk":             f"DATE#{target_date}",
        "date":           target_date,
        "source":         "garmin",
        "schema_version": 1,
        "ingested_at":    datetime.now(timezone.utc).isoformat(),
        **record,
    }
    # DATA-2: Validate before write
    try:
        from ingestion_validator import validate_item as _validate_item
        _vr = _validate_item("garmin", floats_to_decimal(db_item), target_date)
        if _vr.should_skip_ddb:
            logger.error(f"[DATA-2] CRITICAL: Skipping garmin DDB write for {target_date}: {_vr.errors}")
            _vr.archive_to_s3(s3_client, bucket=S3_BUCKET, item=db_item)
        else:
            if _vr.warnings:
                logger.warning(f"[DATA-2] Validation warnings for garmin/{target_date}: {_vr.warnings}")
            table.put_item(Item=floats_to_decimal(db_item))
            print(f"DynamoDB: DATE#{target_date} → {len(record)} fields written")
    except ImportError:
        table.put_item(Item=floats_to_decimal(db_item))
        print(f"DynamoDB: DATE#{target_date} → {len(record)} fields written")

    return record


# ── Lambda handler ─────────────────────────────────────────────────────────────
def lambda_handler(event, context):
    import time as _time
    logger.set_date(datetime.now(timezone.utc).strftime("%Y-%m-%d"))  # OBS-1

    secret = get_secret()

    # ── Mode 1: Explicit date override (manual invocation / backfill) ──
    if event.get("date"):
        target_date = event["date"]
        print(f"Garmin ingestion — explicit date={target_date}")
        result = ingest_day(target_date, secret)
        if not result:
            return {"statusCode": 204, "body": json.dumps({"message": f"No Garmin data for {target_date}"})}
        return {
            "statusCode": 200,
            "body": json.dumps({"date": target_date, "fields_written": len(result)}, default=str),
        }

    # ── Mode 2: Scheduled run — gap-aware lookback ──
    print(f"Garmin ingestion — gap-aware lookback ({LOOKBACK_DAYS} days)")
    missing_dates = find_missing_dates()

    if not missing_dates:
        return {"statusCode": 200, "body": json.dumps({"message": "No gaps to fill", "lookback_days": LOOKBACK_DAYS})}

    # Auth once, reuse across all gap days
    api = get_garmin_client(secret)
    results = {}
    for i, date_str in enumerate(missing_dates):
        print(f"[GAP-FILL] Ingesting {date_str} ({i+1}/{len(missing_dates)})")
        try:
            result = ingest_day(date_str, secret, api=api)
            results[date_str] = len(result) if result else 0
        except Exception as e:
            print(f"[GAP-FILL] ERROR on {date_str}: {e}")
            results[date_str] = f"error: {e}"
        if i < len(missing_dates) - 1:
            _time.sleep(1)  # Rate limit pacing

    filled = sum(1 for v in results.values() if isinstance(v, int) and v > 0)
    print(f"[GAP-FILL] Complete: {filled}/{len(missing_dates)} days filled")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "mode": "gap_fill",
            "lookback_days": LOOKBACK_DAYS,
            "gaps_found": len(missing_dates),
            "gaps_filled": filled,
            "details": results,
        }, default=str),
    }
