#!/usr/bin/env python3
"""
backfill_garmin.py — Backfill Garmin data from a start date to today.

Runs locally using stored garth tokens from Secrets Manager.
Writes directly to DynamoDB and S3 (same format as the Lambda).

v2.0.0 — Synced with garmin_lambda.py v1.5.0 extraction logic:
  - Sleep: 2 fields → 18 fields (stages, timing, SpO2, respiration, restless, sub-scores)
  - Training status: uses mostRecentTrainingStatus path with ACWR
  - Training readiness: handles list + dict, extracts level, hrv_weekly_avg, recovery_time
  - Activities: adds avg_hr, max_hr, calories, avg_speed, max_speed
  - Uses modular extract_* functions matching Lambda structure

Features:
  - Skips dates already in DynamoDB (safe to re-run)
  - Rate limiting: 2s between requests to avoid Garmin throttling
  - Progress saved to /tmp/garmin_backfill_progress.json — resume after interruption
  - Prints a running summary every 50 days
  - Skips empty days silently (no data = not worn)

Usage:
  source /tmp/garmin-venv/bin/activate
  python3 backfill_garmin.py                        # 2004-01-01 to today
  python3 backfill_garmin.py --start 2025-11-26     # 90-day backfill
  python3 backfill_garmin.py --start 2025-11-26 --end 2026-02-24
  python3 backfill_garmin.py --force                 # re-ingest even if already in DynamoDB
"""

import argparse
import json
import time
import boto3
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal

# ── Config ─────────────────────────────────────────────────────────────────────
SECRET_NAME    = "life-platform/garmin"
S3_BUCKET      = "matthew-life-platform"
DYNAMODB_TABLE = "life-platform"
REGION         = "us-west-2"
RATE_LIMIT_SEC = 2.0   # seconds between Garmin API calls
PROGRESS_FILE  = "/tmp/garmin_backfill_progress.json"

# ── AWS clients ────────────────────────────────────────────────────────────────
secrets_client = boto3.client("secretsmanager", region_name=REGION)
s3_client      = boto3.client("s3",             region_name=REGION)
dynamodb       = boto3.resource("dynamodb",      region_name=REGION)
table          = dynamodb.Table(DYNAMODB_TABLE)


# ── Serialisation helpers ──────────────────────────────────────────────────────
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


def save_secret(secret):
    secrets_client.update_secret(
        SecretId=SECRET_NAME,
        SecretString=json.dumps(secret),
    )


# ── Garmin auth ────────────────────────────────────────────────────────────────
def get_garmin_client(secret):
    import garth
    from garminconnect import Garmin

    email    = secret["email"]
    password = secret["password"]

    if not secret.get("garth_tokens"):
        raise RuntimeError("No garth tokens. Run setup_garmin_auth.py first.")

    garth.client.loads(secret["garth_tokens"])
    print("Loaded stored garth OAuth tokens.")

    api = Garmin(email=email, password=password)
    api.garth = garth.client

    # Resolve display_name from profile API
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
                print(f"Resolved display_name: {name}")
                break
        except Exception as e:
            print(f"Profile path {profile_path} failed: {e}")

    if not api.display_name:
        raise RuntimeError("Could not resolve display_name. Re-run setup_garmin_auth.py.")

    # Save refreshed tokens
    try:
        new_tokens = garth.client.dumps()
        if new_tokens and new_tokens != secret.get("garth_tokens"):
            secret["garth_tokens"] = new_tokens
            save_secret(secret)
            print("Refreshed tokens saved.")
    except Exception as e:
        print(f"Warning: could not save tokens ({e})")

    return api


# ── Extraction functions (synced with garmin_lambda.py v1.5.0) ─────────────────

def extract_user_summary(api, date_str):
    result = {}
    try:
        data = api.get_user_summary(date_str)
        if data:
            rhr   = data.get("restingHeartRate")
            steps = data.get("totalSteps")
            if rhr is not None and rhr > 0:
                result["resting_heart_rate"] = safe_float(rhr)
            if steps is not None and steps >= 0:
                result["steps"] = int(steps)
    except Exception as e:
        print(f"    Warning: user summary failed: {e}")
    return result


def extract_hrv(api, date_str):
    result = {}
    try:
        data = api.get_hrv_data(date_str)
        if data:
            summary = data.get("hrvSummary") or {}
            ln = summary.get("lastNight")
            st = summary.get("status")
            hi = summary.get("lastNight5MinHigh")
            if ln is not None:
                result["hrv_last_night"] = safe_float(ln)
            if st and st not in ("NONE", "UNQUALIFIED", ""):
                result["hrv_status"] = st
            if hi is not None:
                result["hrv_5min_high"] = safe_float(hi)
    except Exception as e:
        print(f"    Warning: HRV failed: {e}")
    return result


def extract_stress(api, date_str):
    result = {}
    try:
        data = api.get_stress_data(date_str)
        if data:
            avg = data.get("avgStressLevel")
            mx  = data.get("maxStressLevel")
            q   = data.get("stressQualifier")
            if avg is not None and avg >= 0:
                result["avg_stress"] = safe_float(avg)
            if mx is not None and mx >= 0:
                result["max_stress"] = safe_float(mx)
            if q:
                result["stress_qualifier"] = q
    except Exception as e:
        print(f"    Warning: stress failed: {e}")
    return result


def extract_body_battery(api, date_str):
    result = {}
    try:
        data = api.get_body_battery(date_str, date_str)
        if data:
            values = []
            for entry in data:
                for row in (entry.get("bodyBatteryValuesArray") or []):
                    if len(row) >= 2 and row[1] is not None:
                        values.append(int(row[1]))
            if values:
                result["body_battery_high"] = max(values)
                result["body_battery_low"]  = min(values)
                result["body_battery_end"]  = values[-1]
    except Exception as e:
        print(f"    Warning: body battery failed: {e}")
    return result


def extract_respiration(api, date_str):
    result = {}
    try:
        data = api.get_respiration_data(date_str)
        if data:
            wk = data.get("avgWakingRespirationValue")
            sl = data.get("avgSleepRespirationValue")
            if wk and wk > 0:
                result["avg_respiration"] = safe_float(wk)
            if sl and sl > 0:
                result["sleep_respiration"] = safe_float(sl)
    except Exception as e:
        print(f"    Warning: respiration failed: {e}")
    return result


def extract_spo2(api, date_str):
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
    except Exception as e:
        print(f"    Warning: SpO2 failed: {e}")
    return result


def extract_max_metrics(api, date_str):
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
    except Exception as e:
        print(f"    Warning: max metrics failed: {e}")
    return result


def extract_training_status(api, date_str):
    """Training status + acute/chronic load + readiness (v1.5.0 logic)."""
    result = {}

    # Training status + load from mostRecentTrainingStatus path
    try:
        data = api.get_training_status(date_str)
        if data:
            mrt = data.get("mostRecentTrainingStatus") or {}
            latest_map = mrt.get("latestTrainingStatusData") or {}
            for device_id, device_data in latest_map.items():
                if not device_data.get("primaryTrainingDevice"):
                    continue
                feedback = device_data.get("trainingStatusFeedbackPhrase")
                if feedback:
                    result["training_status"] = feedback

                atl = device_data.get("acuteTrainingLoadDTO") or {}
                acute   = safe_float(atl.get("dailyTrainingLoadAcute"))
                chronic = safe_float(atl.get("dailyTrainingLoadChronic"))
                acwr    = safe_float(atl.get("dailyAcuteChronicWorkloadRatio"))
                if acute is not None:
                    result["garmin_acute_load"] = acute
                if chronic is not None:
                    result["garmin_chronic_load"] = chronic
                if acwr is not None:
                    result["garmin_acwr"] = acwr
                break

            # Fallback for older API response format
            if "training_status" not in result:
                status = data.get("trainingStatusFeedback") or data.get("trainingStatus")
                load   = data.get("trainingLoad")
                if status:
                    result["training_status"] = str(status)
                if load and load > 0:
                    result["training_load"] = safe_float(load)
    except Exception as e:
        print(f"    Warning: training status failed: {e}")

    # Training readiness (handles both list and dict responses)
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
        elif data and isinstance(data, dict):
            score = data.get("score") or data.get("trainingReadinessScore")
            if score and score > 0:
                result["training_readiness"] = safe_float(score)
    except Exception as e:
        print(f"    Warning: training readiness failed: {e}")

    return result


def extract_sleep(api, date_str):
    """
    Comprehensive sleep extraction — 18 fields (v1.5.0).
    Stages, timing, SpO2, respiration, restless moments, sub-scores.
    """
    result = {}
    try:
        data = api.get_sleep_data(date_str)
        if not data:
            return result

        daily = data.get("dailySleepDTO") or {}

        # Core
        duration = daily.get("sleepTimeSeconds")
        score    = daily.get("sleepScore")
        if duration and duration > 0:
            result["sleep_duration_seconds"] = int(duration)
        if score and score > 0:
            result["sleep_score"] = safe_float(score)

        # Sleep stages
        for field, key in [
            ("deep_sleep_seconds",         "deepSleepSeconds"),
            ("light_sleep_seconds",        "lightSleepSeconds"),
            ("rem_sleep_seconds",          "remSleepSeconds"),
            ("awake_sleep_seconds",        "awakeSleepSeconds"),
            ("unmeasurable_sleep_seconds", "unmeasurableSleepSeconds"),
        ]:
            val = daily.get(key)
            if val is not None and val >= 0:
                result[field] = int(val)

        # Sleep timing (local timestamps for circadian analysis)
        sleep_start = daily.get("sleepStartTimestampLocal")
        sleep_end   = daily.get("sleepEndTimestampLocal")
        if sleep_start:
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

        # Sleep biometrics
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

        # Restless moments
        restless = daily.get("restlessMomentsCount")
        if restless is not None and restless >= 0:
            result["restless_moments_count"] = int(restless)

        # Sleep sub-scores
        sleep_scores = daily.get("sleepScores") or {}
        for field, key in [
            ("sleep_score_quality",    "qualityScore"),
            ("sleep_score_duration",   "durationScore"),
            ("sleep_score_deep",       "deepScore"),
            ("sleep_score_rem",        "remScore"),
            ("sleep_score_light",      "lightScore"),
            ("sleep_score_awakenings", "awakeningsScore"),
        ]:
            val = sleep_scores.get(key)
            if val is not None and val > 0:
                result[field] = safe_float(val)

    except Exception as e:
        print(f"    Warning: sleep failed: {e}")
    return result


def extract_hr_zones(api, date_str):
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
    except Exception as e:
        print(f"    Warning: HR zones failed: {e}")
    return result


def extract_intensity_minutes(api, date_str):
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
    except Exception as e:
        print(f"    Warning: intensity minutes failed: {e}")
    return result


def extract_stats(api, date_str):
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
    except Exception as e:
        print(f"    Warning: stats failed: {e}")
    return result


def extract_activities(api, date_str):
    """Garmin-proprietary per-activity fields (v1.5.0 — includes HR/calories/speed)."""
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
            ga["activity_name"]   = act.get("activityName")
            ga["activity_type"]   = (act.get("activityType") or {}).get("typeKey")
            ga["start_time"]      = act.get("startTimeLocal")
            ga["duration_secs"]   = safe_float(act.get("duration"))
            ga["distance_meters"] = safe_float(act.get("distance"))

            # Core activity metrics (v1.5.0 additions)
            avg_hr    = safe_float(act.get("averageHR"))
            max_hr    = safe_float(act.get("maxHR"))
            calories  = safe_float(act.get("calories"))
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

            # Garmin-proprietary training analytics
            for key, field in [
                ("aerobic_training_effect",    "aerobicTrainingEffect"),
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
                ("avg_cadence",              "averageRunningCadenceInStepsPerMinute"),
                ("stride_length_m",          "strideLength"),
                ("ground_contact_time_ms",   "groundContactTime"),
                ("vertical_oscillation_cm",  "verticalOscillation"),
                ("vertical_ratio_pct",       "verticalRatio"),
            ]:
                v = safe_float(act.get(field))
                if v is not None:
                    ga[key] = v

            # Biking cadence fallback
            if "avg_cadence" not in ga:
                bike_cadence = safe_float(act.get("averageBikingCadenceInRevPerMinute"))
                if bike_cadence is not None:
                    ga["avg_cadence"] = bike_cadence

            ga = {k: v for k, v in ga.items() if v is not None}
            if ga:
                garmin_activities.append(ga)

        if garmin_activities:
            result["garmin_activities"]    = garmin_activities
            result["garmin_activity_count"] = len(garmin_activities)
    except Exception as e:
        print(f"    Warning: activities failed: {e}")
    return result


# ── Core fetch (uses modular extractors) ───────────────────────────────────────
def fetch_day(api, date_str):
    """Fetch all Garmin metrics for a single date using v1.5.0 extractors."""
    record = {}
    record.update(extract_user_summary(api, date_str))
    record.update(extract_hrv(api, date_str))
    record.update(extract_stress(api, date_str))
    record.update(extract_body_battery(api, date_str))
    record.update(extract_respiration(api, date_str))
    record.update(extract_spo2(api, date_str))
    record.update(extract_max_metrics(api, date_str))
    record.update(extract_training_status(api, date_str))
    record.update(extract_sleep(api, date_str))
    record.update(extract_hr_zones(api, date_str))
    record.update(extract_intensity_minutes(api, date_str))
    record.update(extract_stats(api, date_str))
    record.update(extract_activities(api, date_str))
    return record


# ── DynamoDB / S3 write ────────────────────────────────────────────────────────
def already_ingested(date_str):
    resp = table.get_item(Key={
        "pk": "USER#matthew#SOURCE#garmin",
        "sk": f"DATE#{date_str}",
    })
    return "Item" in resp


def write_day(date_str, record):
    s3_key = f"raw/garmin/{date_str[:4]}/{date_str[5:7]}/{date_str[8:10]}.json"
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=json.dumps({
            "date":        date_str,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "parsed":      record,
            "source":      "backfill_v2",
        }, default=str),
        ContentType="application/json",
    )

    db_item = {
        "pk":          "USER#matthew#SOURCE#garmin",
        "sk":          f"DATE#{date_str}",
        "date":        date_str,
        "source":      "garmin",
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        **record,
    }
    table.put_item(Item=floats_to_decimal(db_item))


# ── Progress tracking ──────────────────────────────────────────────────────────
def load_progress():
    try:
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f)


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Backfill Garmin data to DynamoDB (v2.0)")
    parser.add_argument("--start", default="2004-01-01", help="Start date YYYY-MM-DD")
    parser.add_argument("--end",   default=datetime.now(timezone.utc).strftime("%Y-%m-%d"), help="End date YYYY-MM-DD")
    parser.add_argument("--force", action="store_true", help="Re-ingest even if already in DynamoDB")
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end   = datetime.strptime(args.end,   "%Y-%m-%d").date()
    total_days = (end - start).days + 1

    print(f"Garmin backfill v2.0 (synced with Lambda v1.5.0)")
    print(f"Range: {args.start} → {args.end} ({total_days} days)")
    print(f"Rate limit: {RATE_LIMIT_SEC}s between requests")
    print(f"Force re-ingest: {args.force}")
    print()

    secret = get_secret()
    api    = get_garmin_client(secret)

    progress = load_progress()
    ingested = 0
    skipped  = 0
    empty    = 0
    errors   = 0

    current = start
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")

        # Skip if already done (unless --force)
        if not args.force and already_ingested(date_str):
            skipped += 1
            current += timedelta(days=1)
            continue

        try:
            record = fetch_day(api, date_str)

            if record:
                write_day(date_str, record)
                ingested += 1
                # Show key fields for quick verification
                sleep_fields = sum(1 for k in record if k.startswith("sleep_") or k.endswith("_sleep_seconds"))
                print(f"  ✓ {date_str} — {len(record)} fields (sleep:{sleep_fields})")
            else:
                empty += 1
                print(f"  · {date_str} — no data", end="\r")

            progress["last_completed"] = date_str
            progress["ingested"]       = ingested
            progress["empty"]          = empty
            save_progress(progress)

        except Exception as e:
            errors += 1
            print(f"  ✗ {date_str} — error: {e}")
            if "rate" in str(e).lower() or "429" in str(e) or "too many" in str(e).lower():
                print("    Rate limited — waiting 30s...")
                time.sleep(30)

        # Progress summary every 50 days
        days_done = (current - start).days + 1
        if days_done % 50 == 0:
            pct = days_done / total_days * 100
            print(f"\n  [{pct:.0f}%] {days_done}/{total_days} days — "
                  f"ingested={ingested} empty={empty} skipped={skipped} errors={errors}\n")

        current += timedelta(days=1)
        time.sleep(RATE_LIMIT_SEC)

    print()
    print("=" * 60)
    print("Backfill complete!")
    print(f"  Ingested : {ingested} days with data")
    print(f"  Empty    : {empty} days (no watch data)")
    print(f"  Skipped  : {skipped} days (already in DynamoDB)")
    print(f"  Errors   : {errors}")
    print("=" * 60)


if __name__ == "__main__":
    main()
