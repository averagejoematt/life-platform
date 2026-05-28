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
import time
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
SECRET_NAME = "life-platform/garmin"
# ── Config (env vars with backwards-compatible defaults) ──
REGION = os.environ.get("AWS_REGION", "us-west-2")
S3_BUCKET = os.environ["S3_BUCKET"]
DYNAMODB_TABLE = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "7"))

# ── AWS clients ────────────────────────────────────────────────────────────────
secrets_client = boto3.client("secretsmanager", region_name=REGION)
s3_client = boto3.client("s3",             region_name=REGION)
dynamodb = boto3.resource("dynamodb",      region_name=REGION)
table = dynamodb.Table(DYNAMODB_TABLE)


# ── Serialisation ──────────────────────────────────────────────────────────────
# Phase 4.2 (2026-05-16): canonical impl in lambdas/numeric.py.
try:
    from numeric import floats_to_decimal  # noqa: F401
except ImportError:
    def floats_to_decimal(obj):
        if isinstance(obj, bool): return obj
        if isinstance(obj, float): return Decimal(str(obj))
        if isinstance(obj, dict): return {k: floats_to_decimal(v) for k, v in obj.items()}
        if isinstance(obj, list): return [floats_to_decimal(v) for v in obj]
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
    """Persist refreshed garth tokens. Writeback failures emit a metric but do
    NOT raise — the next scheduled run will retry refresh from the previous
    saved tokens. Raising would cascade a transient SM hiccup into a 401 loop.
    """
    try:
        secrets_client.update_secret(
            SecretId=SECRET_NAME,
            SecretString=json.dumps(secret),
        )
    except Exception as e:
        logger.warning(f"Garmin token writeback failed: {e}")
        try:
            cw = boto3.client("cloudwatch", region_name=REGION)
            cw.put_metric_data(
                Namespace="LifePlatform/OAuth",
                MetricData=[{"MetricName": "TokenWritebackFailure",
                             "Dimensions": [{"Name": "Source", "Value": "garmin"}],
                             "Value": 1.0}],
            )
        except Exception:
            pass


# ── Refresh-429 circuit breaker ──────────────────────────────────────────────
# Garmin aggressively 429-rate-limits the OAuth2 refresh-exchange endpoint for
# non-browser clients (their March-2026 crackdown). The OAuth1 refresh token
# stays valid ~1 year, so a refresh SHOULD succeed whenever we're not throttled.
# Once we hit a 429 we record a marker and skip *all* refresh attempts for a
# cooldown window — re-hitting the endpoint only prolongs the throttle and is
# what historically stranded us until a manual browser re-auth. Distinct from
# the generic 401/403 auth_breaker (different trigger, recovery, and TTL).
_REFRESH_BREAKER_SK = "REFRESH_RATELIMIT"
_REFRESH_BREAKER_TTL = 3 * 3600  # 3h — typical window for Garmin's throttle to clear


class GarminRefreshRateLimited(RuntimeError):
    """OAuth2 refresh was 429-throttled (or is in cooldown). Caught in
    lambda_handler and converted to a clean skip so the async invocation does
    NOT error — erroring triggers EventBridge retries that re-hammer the
    throttled endpoint and keep us stuck."""


def _breaker_key() -> dict:
    return {"pk": f"USER#{USER_ID}#SOURCE#garmin", "sk": _REFRESH_BREAKER_SK}


def refresh_breaker_cooldown() -> int:
    """Seconds remaining in the refresh-429 cooldown, or 0 if none/expired."""
    try:
        item = table.get_item(Key=_breaker_key()).get("Item")
    except Exception:
        return 0
    if not item:
        return 0
    try:
        remaining = _REFRESH_BREAKER_TTL - (time.time() - float(item.get("marked_at", 0)))
    except (TypeError, ValueError):
        return 0
    return int(remaining) if remaining > 0 else 0


def mark_refresh_breaker(err) -> None:
    now = time.time()
    try:
        table.put_item(Item={
            **_breaker_key(),
            "marked_at": Decimal(str(int(now))),
            "error": str(err)[:300],
            "ttl": int(now) + _REFRESH_BREAKER_TTL,
        })
        logger.warning(f"Garmin refresh-429 breaker tripped — cooling down {_REFRESH_BREAKER_TTL // 3600}h")
    except Exception as e:
        logger.warning(f"refresh breaker mark failed: {e}")


def clear_refresh_breaker() -> None:
    try:
        table.delete_item(Key=_breaker_key())
    except Exception:
        pass


def _should_refresh(token, fraction: float = 0.25) -> bool:
    """True if the OAuth2 token is already expired OR within `fraction` of the
    end of its lifetime. Refreshing proactively (before hard expiry) means the
    stored token never goes fully stale between scheduled runs, so a single
    throttled refresh can't strand us — the still-valid token serves data calls
    until the next run refreshes it."""
    if token is None:
        return False
    if getattr(token, "expired", False):
        return True
    expires_at = getattr(token, "expires_at", None)
    expires_in = getattr(token, "expires_in", None)
    if not expires_at or not expires_in:
        return False
    return (expires_at - time.time()) < fraction * expires_in


# ── Garmin auth ────────────────────────────────────────────────────────────────
def get_garmin_client(secret: dict):
    """
    Initialise garminconnect.Garmin using stored OAuth tokens from Secrets Manager.

    Supports two token formats:
      1. Browser-auth (2026+): garth_tokens contains JSON with oauth1/oauth2 objects.
         Written by setup_garmin_browser_auth.py. Loaded via garth.resume() from /tmp.
      2. Legacy: garth_tokens contains garth.client.dumps() blob.
         Written by old setup_garmin_auth.py. Loaded via garth.client.loads().

    NOTE: Lambda cannot do interactive garth.login() (no stdin for MFA,
    and Garmin blocks programmatic SSO since March 2026).
    If tokens are expired, re-run setup_garmin_browser_auth.py locally.
    """
    import garth
    from garminconnect import Garmin

    if not secret.get("garth_tokens"):
        raise RuntimeError(
            "No garth tokens in Secrets Manager. "
            "Run setup_garmin_browser_auth.py locally to authenticate."
        )

    # ── Detect token format and load accordingly ──
    token_data = secret["garth_tokens"]
    loaded = False

    # Format 1: Browser-auth JSON (has oauth1/oauth2 keys)
    try:
        parsed = json.loads(token_data) if isinstance(token_data, str) else token_data
        if isinstance(parsed, dict) and "oauth1" in parsed and "oauth2" in parsed:
            import os, tempfile
            garth_dir = os.path.join(tempfile.gettempdir(), ".garth_tokens")
            os.makedirs(garth_dir, exist_ok=True)
            with open(os.path.join(garth_dir, "oauth1_token.json"), "w") as f:
                json.dump(parsed["oauth1"], f)
            with open(os.path.join(garth_dir, "oauth2_token.json"), "w") as f:
                json.dump(parsed["oauth2"], f)
            garth.resume(garth_dir)
            logger.info("Loaded OAuth tokens (browser-auth format) via garth.resume()")
            loaded = True
    except (json.JSONDecodeError, TypeError, KeyError):
        pass
    except Exception as e:
        logger.info(f"Browser-auth token load failed: {e}, trying legacy format...")

    # Format 2: Legacy garth.client.dumps() blob
    if not loaded:
        try:
            garth.client.loads(token_data)
            logger.info("Loaded stored garth OAuth tokens (legacy format).")
            loaded = True
        except Exception as e:
            raise RuntimeError(
                f"Could not load garth tokens in any format ({e}). "
                "Run setup_garmin_browser_auth.py locally to re-authenticate."
            ) from e

    # ── Log token expiry for observability ──
    try:
        oauth2 = garth.client.oauth2_token
        if oauth2 and hasattr(oauth2, "expires_at"):
            logger.info(f"OAuth2 token expires at: {oauth2.expires_at}")
        if oauth2 and hasattr(oauth2, "expired"):
            logger.info(f"OAuth2 token expired: {oauth2.expired}")
    except Exception:
        pass

    # ── Token refresh (proactive, breaker-gated, 429-safe) ──
    # Refresh proactively when the token is near the end of its life (not only
    # after hard expiry), but skip entirely while the refresh-429 breaker is in
    # cooldown so we don't re-hammer a throttled endpoint. Retry transient 5xx
    # with 2s/8s backoff; a 429 trips the breaker and aborts cleanly.
    token = garth.client.oauth2_token
    need_refresh = _should_refresh(token)
    cooldown = refresh_breaker_cooldown() if need_refresh else 0

    if need_refresh and cooldown:
        if token is None or getattr(token, "expired", False):
            # Token unusable AND we're throttled — skip this run cleanly so the
            # cooldown can clear. The OAuth1 token is still valid; a later run
            # will refresh successfully once Garmin lifts the throttle.
            raise GarminRefreshRateLimited(
                f"OAuth2 expired but refresh in 429 cooldown ({cooldown}s left)."
            )
        # Only near-expiry (still valid) — serve data with the current token and
        # defer the refresh rather than poking the throttled endpoint.
        logger.info(f"Deferring proactive refresh — in 429 cooldown ({cooldown}s left), token still valid.")
        need_refresh = False

    if need_refresh:
        refresh_backoff = [2, 8]
        refresh_attempts = 3
        for refresh_attempt in range(refresh_attempts):
            try:
                logger.info(f"Refreshing OAuth2 token — attempt {refresh_attempt + 1}/{refresh_attempts}...")
                garth.client.refresh_oauth2()
                logger.info("OAuth2 token refreshed successfully.")
                clear_refresh_breaker()
                break
            except Exception as e:
                err_str = str(e)
                if "429" in err_str or "Too Many Requests" in err_str:
                    mark_refresh_breaker(e)
                    logger.error("Garmin OAuth refresh rate-limited (429) — tripping breaker, will retry after cooldown.")
                    raise GarminRefreshRateLimited("Garmin OAuth refresh rate-limited (429).") from e
                # Retry transient 5xx; everything else (4xx auth, malformed token) raises.
                is_transient = any(c in err_str for c in ("500", "502", "503", "504", "timeout", "timed out"))
                if is_transient and refresh_attempt < refresh_attempts - 1:
                    logger.info(f"OAuth refresh transient error: {e} — retry in {refresh_backoff[refresh_attempt]}s")
                    time.sleep(refresh_backoff[refresh_attempt])
                    continue
                raise RuntimeError(
                    f"Garmin OAuth refresh failed ({e}). "
                    "Run setup_garmin_browser_auth.py locally to re-authenticate."
                ) from e

    # ── Save refreshed tokens eagerly (before any data calls) ──
    def _save_tokens():
        try:
            new_tokens = garth.client.dumps()
            if new_tokens and new_tokens != secret.get("garth_tokens"):
                secret["garth_tokens"] = new_tokens
                save_secret(secret)
                logger.info("Refreshed OAuth tokens saved to Secrets Manager.")
        except Exception as e:
            logger.info(f"Warning: could not save refreshed tokens ({e})")

    _save_tokens()

    # ── Wire garth into garminconnect ──
    api = Garmin()
    api.garth = garth.client

    # ── Resolve display_name ──
    # Prefer pre-stored display_name from browser auth
    if secret.get("display_name"):
        api.display_name = secret["display_name"]
        logger.info(f"display_name from secret: {api.display_name}")
    else:
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
                    logger.info(f"Resolved display_name: {name} (from {profile_path})")
                    break
            except Exception as e:
                logger.info(f"Profile path {profile_path} failed: {e}")

    if not api.display_name:
        raise RuntimeError(
            "Could not resolve Garmin display_name — tokens may be expired. "
            "Run setup_garmin_browser_auth.py locally to re-authenticate."
        )

    # Save again after profile resolution (profile calls may have triggered a refresh)
    _save_tokens()

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
            result["body_battery_low"] = min(values)
            result["body_battery_end"] = values[-1]
            logger.info(f"Body Battery: high={result['body_battery_high']}, low={result['body_battery_low']}, end={result['body_battery_end']}")
    except Exception as e:
        logger.info(f"Warning: body battery extraction failed: {e}")
    return result


def extract_hrv(api, date_str: str) -> dict:
    result = {}
    try:
        data = api.get_hrv_data(date_str)
        if not data:
            return result
        summary = data.get("hrvSummary") or {}
        last_night = summary.get("lastNight")
        status = summary.get("status")
        high = summary.get("lastNight5MinHigh")
        if last_night is not None:
            result["hrv_last_night"] = safe_float(last_night)
        if status and status not in ("NONE", "UNQUALIFIED", ""):
            result["hrv_status"] = status
        if high is not None:
            result["hrv_5min_high"] = safe_float(high)
        if result:
            logger.info(f"HRV: last_night={result.get('hrv_last_night')}ms status={result.get('hrv_status')}")
    except Exception as e:
        logger.info(f"Warning: HRV extraction failed: {e}")
    return result


def extract_stress(api, date_str: str) -> dict:
    result = {}
    try:
        data = api.get_stress_data(date_str)
        if not data:
            return result
        avg_stress = data.get("avgStressLevel")
        max_stress = data.get("maxStressLevel")
        qualifier = data.get("stressQualifier")
        if avg_stress is not None and avg_stress >= 0:
            result["avg_stress"] = safe_float(avg_stress)
        if max_stress is not None and max_stress >= 0:
            result["max_stress"] = safe_float(max_stress)
        if qualifier:
            result["stress_qualifier"] = qualifier
        if result:
            logger.info(f"Stress: avg={result.get('avg_stress')} max={result.get('max_stress')} qualifier={result.get('stress_qualifier')}")
    except Exception as e:
        logger.info(f"Warning: stress extraction failed: {e}")
    return result


def extract_user_summary(api, date_str: str) -> dict:
    result = {}
    try:
        data = api.get_user_summary(date_str)
        if not data:
            return result
        rhr = data.get("restingHeartRate")
        steps = data.get("totalSteps")
        if rhr is not None and rhr > 0:
            result["resting_heart_rate"] = safe_float(rhr)
        if steps is not None and steps >= 0:
            result["steps"] = int(steps)
        if result:
            logger.info(f"Summary: RHR={result.get('resting_heart_rate')}bpm steps={result.get('steps')}")
    except Exception as e:
        logger.info(f"Warning: user summary extraction failed: {e}")
    return result


def extract_respiration(api, date_str: str) -> dict:
    result = {}
    try:
        data = api.get_respiration_data(date_str)
        if not data:
            return result
        avg_waking = data.get("avgWakingRespirationValue")
        avg_sleep = data.get("avgSleepRespirationValue")
        if avg_waking is not None and avg_waking > 0:
            result["avg_respiration"] = safe_float(avg_waking)
        if avg_sleep is not None and avg_sleep > 0:
            result["sleep_respiration"] = safe_float(avg_sleep)
        if result:
            logger.info(f"Respiration: waking={result.get('avg_respiration')} sleep={result.get('sleep_respiration')} brpm")
    except Exception as e:
        logger.info(f"Warning: respiration extraction failed: {e}")
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
            logger.info(f"SpO2: avg={result.get('spo2_avg')}% low={result.get('spo2_low')}%")
    except Exception as e:
        logger.info(f"Warning: SpO2 extraction failed: {e}")
    return result


def extract_max_metrics(api, date_str: str) -> dict:
    result = {}
    try:
        data = api.get_max_metrics(date_str)
        if data and isinstance(data, list) and data:
            entry = data[0] if isinstance(data[0], dict) else {}
            generic = entry.get("generic") or {}
            vo2 = generic.get("vo2MaxPreciseValue") or generic.get("vo2MaxValue")
            fit_age = generic.get("fitnessAge")
            if vo2 and vo2 > 0:
                result["vo2_max"] = safe_float(vo2)
            if fit_age and fit_age > 0:
                result["fitness_age"] = int(fit_age)
        if result:
            logger.info(f"MaxMetrics: VO2max={result.get('vo2_max')} fitness_age={result.get('fitness_age')}")
    except Exception as e:
        logger.info(f"Warning: max metrics extraction failed: {e}")
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
            logger.info(f"Training status: {result.get('training_status')} acute={result.get('garmin_acute_load')} chronic={result.get('garmin_chronic_load')} ACWR={result.get('garmin_acwr')}")
    except Exception as e:
        logger.info(f"Warning: training status extraction failed: {e}")

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
                logger.info(f"Training readiness: {result['training_readiness']} ({result.get('training_readiness_level')}) HRV_weekly={result.get('hrv_weekly_average')}ms recovery={result.get('recovery_time_hours')}h")
        elif data and isinstance(data, dict):
            # Fallback for dict response (older API versions)
            score = data.get("score") or data.get("trainingReadinessScore")
            if score and score > 0:
                result["training_readiness"] = safe_float(score)
                logger.info(f"Training readiness: {score}")
    except Exception as e:
        logger.info(f"Warning: training readiness extraction failed: {e}")
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
        logger.info(f"Sleep API response type={type(data).__name__} truthy={bool(data)}")
        if data:
            logger.info(f"Sleep API top keys: {list(data.keys()) if isinstance(data, dict) else 'not a dict'}")
        if not data:
            logger.info("Sleep: no data returned from get_sleep_data")
            return result

        daily = data.get("dailySleepDTO") or {}
        logger.info(f"dailySleepDTO keys: {list(daily.keys())[:10] if daily else 'empty'}")

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
        logger.info(f"Warning: sleep extraction failed: {e}")
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
            # Garmin zones are 0-indexed; zone index 1 = "Zone 2" (aerobic) in Garmin Connect UI
            z2 = result.get("hr_zone_1_seconds")
            if z2:
                result["zone2_minutes"] = round(z2 / 60, 1)
        if result:
            logger.info(f"HR zones: zone2={result.get('zone2_minutes')}min total_zones={len([k for k in result if 'zone' in k])}")
    except Exception as e:
        logger.info(f"Warning: HR zones extraction failed: {e}")
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
                # WHO guidelines: 1 min vigorous = 2 min moderate for weekly activity targets
                result["intensity_minutes_total"] = int(mod) + int(vig) * 2
        if result:
            logger.info(f"Intensity minutes: mod={result.get('intensity_minutes_moderate')} vig={result.get('intensity_minutes_vigorous')}")
    except Exception as e:
        logger.info(f"Warning: intensity minutes extraction failed: {e}")
    return result


def extract_stats(api, date_str: str) -> dict:
    result = {}
    try:
        data = api.get_stats(date_str)
        if data:
            floors = data.get("floorsAscended")
            active = data.get("activeKilocalories")
            bmr = data.get("bmrKilocalories")
            total = data.get("totalKilocalories")
            if floors is not None:
                result["floors_climbed"] = int(floors)
            if active and active > 0:
                result["active_calories"] = int(active)
            if bmr and bmr > 0:
                result["bmr_calories"] = int(bmr)
            if total and total > 0:
                result["total_calories_burned"] = int(total)
        if result:
            logger.info(f"Stats: floors={result.get('floors_climbed')} active_cal={result.get('active_calories')} bmr={result.get('bmr_calories')}")
    except Exception as e:
        logger.info(f"Warning: stats extraction failed: {e}")
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
            ga["activity_name"] = act.get("activityName")
            ga["activity_type"] = (act.get("activityType") or {}).get("typeKey")
            ga["start_time"] = act.get("startTimeLocal")
            ga["duration_secs"] = safe_float(act.get("duration"))
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
                ("lactate_threshold_speed_mps", "lactateThresholdSpeed"),
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
            result["garmin_activities"] = garmin_activities
            result["garmin_activity_count"] = len(garmin_activities)
            logger.info(f"Activities: {len(garmin_activities)} Garmin activities with proprietary fields")
    except Exception as e:
        logger.info(f"Warning: activities extraction failed: {e}")
    return result


# extract_training_load removed — get_training_load() no longer exists in garminconnect.
# Acute/chronic load now extracted from get_training_status() → acuteTrainingLoadDTO.
# See extract_training_status() above.


# ══════════════════════════════════════════════════════════════════════════════
# P4.1 SIMP-2 framework migration (2026-05-17)
# ══════════════════════════════════════════════════════════════════════════════

from ingestion_framework import IngestionConfig, run_ingestion

# Cache the garth-backed api client across the gap-fill loop within one
# invocation. Re-creating it per-day would hit the OAuth refresh endpoint
# 7+ times per cold invoke (and Garmin rate-limits refresh aggressively).
_client_cache = {"api": None, "secret": None}


def authenticate(secret_data: dict) -> dict:
    """Initialize the garth-backed Garmin client. get_garmin_client refreshes
    OAuth tokens in-place and writes them back to the secret dict, which the
    framework persists via enable_secret_writeback=True."""
    secret = dict(secret_data)
    api = get_garmin_client(secret)
    _client_cache["api"] = api
    _client_cache["secret"] = secret
    return secret


def fetch_day(credentials: dict, date_str: str) -> dict | None:
    """Pull all 13 Garmin endpoints for one day. Per-extractor errors are
    caught inside each extract_* — partial-record returns are normal."""
    api = _client_cache["api"]
    if api is None:
        # Defensive: framework caller mismatch — re-auth.
        api = get_garmin_client(dict(credentials))
        _client_cache["api"] = api
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
    return record if record else None


def transform(raw: dict, date_str: str) -> list[dict]:
    if not raw:
        return []
    return [{"source": "garmin", "date": date_str, **raw}]


_config = IngestionConfig(
    source_name="garmin",
    secret_id=SECRET_NAME,
    s3_archive_prefix=f"raw/{USER_ID}/garmin",
    schema_version=1,
    enable_gap_detection=True,
    lookback_days=LOOKBACK_DAYS,
    enable_secret_writeback=True,
    enable_item_size_guard=True,
    refresh_today=True,
)


def lambda_handler(event: dict, context) -> dict:
    try:
        if event.get("healthcheck"):
            return {"statusCode": 200, "body": "ok"}
        return run_ingestion(_config, authenticate, fetch_day, transform, event, context)
    except GarminRefreshRateLimited as e:
        # Clean skip — do NOT raise. Raising marks the async invocation failed,
        # triggering EventBridge retries that re-hit the throttled refresh
        # endpoint and keep us stuck. Returning 200 lets the cooldown clear so a
        # later scheduled run refreshes normally (no manual re-auth needed).
        logger.warning(f"garmin run skipped (refresh rate-limited): {e}")
        return {"statusCode": 200, "body": json.dumps({"skipped": "refresh_ratelimited", "detail": str(e)})}
    except Exception as e:
        logger.error("garmin ingestion failed: %s", e, exc_info=True)
        raise
