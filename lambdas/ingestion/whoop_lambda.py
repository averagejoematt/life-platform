"""
whoop_lambda.py — Whoop ingestion via SIMP-2 framework (P4.1, 2026-05-17).

7th of 8 ingestion Lambdas to migrate. Most complex pre-Garmin: multi-endpoint
(recovery + sleep + cycle + workout), per-workout sub-records via the
framework's sk_suffix mechanism, cross-day sleep-consistency query.

Source-specific concerns preserved:
  - OAuth refresh with refresh_token rotation (enable_secret_writeback=True)
  - Per-workout DDB items at DATE#{date}#WORKOUT#{id} (framework sk_suffix)
  - Sleep onset 7-day rolling consistency (cross-day query)
  - Nap aggregation (separate from main sleep)
  - Field-presence validation logging (F2.5)
  - Auth-failure circuit breaker (now framework-native via enable_gap_detection)

DDB shape unchanged from pre-migration.

Note: ADR-036 race risk — Whoop runs every hour. Reserved concurrency=1 must
remain set on this function until proven safe under concurrent invocations.
"""

import json
import logging
import os
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import boto3
from boto3.dynamodb.conditions import Key

try:
    from common.platform_logger import get_logger

    logger = get_logger("whoop")
except ImportError:
    logger = logging.getLogger("whoop")
    logger.setLevel(logging.INFO)

try:
    from common.http_retry import urlopen_with_retry
except ImportError:  # pragma: no cover — layer-module fallback (local tooling)
    if not TYPE_CHECKING:  # mypy sees ONE signature (the import); runtime unchanged (#1656)

        def urlopen_with_retry(req, timeout=30, max_attempts=None):
            # The fallback must accept max_attempts — the token POST passes it (#2196).
            return urllib.request.urlopen(req, timeout=timeout)


try:
    from common.auth_breaker import check_breaker, looks_like_auth_failure, mark_as_auth_failure, mark_failure
except ImportError:  # pragma: no cover — layer-module fallback (local tooling)
    if not TYPE_CHECKING:  # mypy sees ONE signature (the import); runtime unchanged (#1656)

        def mark_as_auth_failure(exc):
            return exc

        def check_breaker(table, source_name, user_id, logger):
            return None

        def mark_failure(table, source_name, user_id, error_msg, logger):
            return None

        def looks_like_auth_failure(exc):
            return False


from common.pacific_time import parse_iso_utc  # #1964: THE ISO parser (naive input == UTC, never runner-local)

from ingestion.ingestion_framework import IngestionConfig, run_ingestion

REGION = os.environ.get("AWS_REGION", "us-west-2")
USER_ID = os.environ.get("USER_ID", "matthew")
SECRET_NAME = os.environ.get("WHOOP_SECRET_NAME", "life-platform/whoop")
DYNAMODB_TABLE = os.environ.get("TABLE_NAME", "life-platform")

WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
WHOOP_API_BASE = "https://api.prod.whoop.com/developer/v2"

# ── Rotation-budget knobs (#2196) ─────────────────────────────────────────────
# Whoop's refresh_token is SINGLE-USE: every exchange mints a new one and voids
# the old one server-side at the moment of issue. So each exchange is a chance
# to lose the credential in transit (measured: ~1% of token POSTs 5xx; the
# 2026-08-03 and 2026-08-04 losses were both a 5xx AFTER the server had already
# consumed the token). Exchanges are therefore a budget to spend, not a free
# per-invocation ritual — see `authenticate`.
#
# _ACCESS_TOKEN_SKEW_SECONDS: refresh only when the stored access token has
# less than this much life left (clock skew + the run's own duration).
_ACCESS_TOKEN_SKEW_SECONDS = int(os.environ.get("WHOOP_TOKEN_SKEW_SECONDS", "300"))
# Where the expiry lives IN the existing secret JSON (no new storage): an epoch
# seconds int alongside access_token/refresh_token.
_EXPIRES_AT_FIELD = "access_token_expires_at"  # noqa: S105 — a JSON field name, not a secret

# The token POST's transport codes: the ones where the request MIGHT not have
# been processed. A 400 immediately after one of these, in the same invocation,
# is the "lost rotation" fingerprint (see _refresh_access_token).
_TOKEN_TRANSPORT_CODES = frozenset({429, 500, 502, 503, 504})
_TOKEN_PROBE_DELAY_SECONDS = 2

# A data-endpoint 401 within this window of a SUCCESSFUL rotation in the same
# invocation is treated as transient (2026-08-01: a 401 8s after a healthy
# refresh latched the 24h breaker on a credential that was never dead).
_ROTATION_GRACE_SECONDS = int(os.environ.get("WHOOP_ROTATION_GRACE_SECONDS", "600"))
# Durable one-shot: the grace applies once, then recurrence latches (see
# _fetch_all_endpoints). TTL'd like the auth-failure marker.
_GLITCH_SK = "AUTH_GLITCH"
_GLITCH_TTL_SECONDS = 2 * 3600
WHOOP_SCOPES = "offline read:recovery read:cycles read:workout read:sleep " "read:profile read:body_measurement"

WHOOP_SPORT_NAMES = {
    -1: "Activity",
    0: "Running",
    1: "Cycling",
    16: "Basketball",
    17: "Baseball",
    18: "Football",
    19: "Soccer",
    25: "Swimming",
    27: "Tennis",
    44: "Weightlifting",
    45: "Cross Training",
    46: "Functional Fitness",
    48: "Yoga",
    49: "Pilates",
    50: "HIIT",
    51: "Spin",
    57: "Rowing",
    63: "Hiking",
    71: "Triathlon",
    72: "Golf",
    73: "Skiing / Snowboarding",
    74: "Skateboarding",
    85: "Lacrosse",
    91: "Walking",
}
_ZONE_WORD = ["zero", "one", "two", "three", "four", "five"]

# Module-level DDB resource — needed by transform() for sleep-consistency
# cross-day query (framework doesn't pass its table to callbacks).
_dynamodb = boto3.resource("dynamodb", region_name=REGION)
_table = _dynamodb.Table(DYNAMODB_TABLE)

# Module-level CloudWatch client for the reconciliation metric (mirrors strava).
_cw = boto3.client("cloudwatch", region_name=REGION)


# ── Whoop API ─────────────────────────────────────────────────────────────────


class WhoopRotationLost(RuntimeError):
    """The single-use refresh_token was consumed by Whoop but never reached us.

    Raised ONLY on the measured fingerprint (#2196): a token POST that returned
    a transport 5xx, followed — in the SAME invocation, with the SAME token — by
    a 400. The 400 proves the server had already rotated (and therefore voided)
    the token before its 5xx response was lost in transit. The credential is
    unrecoverable without a browser re-auth, and every later run will 400.

    Distinct from the generic auth latch on purpose: this class of death is
    *not* "the credential expired / the user revoked us", it is "our stored
    token is provably stale through no fault of the operator", and the only fix
    is an immediate manual re-auth.
    """


def _token_post(payload: bytes) -> dict:
    """One token exchange. NO retry (#2196, acceptance box 2).

    `http_retry`'s documented non-idempotent escape hatch (max_attempts=1,
    module docstring "a POST/PUT whose 5xx might mean 'the write actually
    landed'") is exactly this request: Whoop consumes the single-use
    refresh_token server-side BEFORE responding, so a blind retry re-sends a
    token that may already be spent. #2069 added retry here on the assumption
    that a 5xx meant "never processed"; the 2026-08-04 trace refutes it — the
    retry re-sent the spent token ~10s later and got a 400. Retry policy for
    this POST now lives in `_refresh_access_token`, which classifies what it
    sees instead of retrying blindly.
    """
    req = urllib.request.Request(
        WHOOP_TOKEN_URL,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "WhoopIngestion/1.0"},
    )
    with urlopen_with_retry(req, timeout=30, max_attempts=1) as resp:
        data: dict = json.loads(resp.read())
    return data


def _refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> tuple[str, str, int]:
    """Exchange the refresh_token. Returns (access_token, refresh_token, expires_in).

    On a transport 5xx we make exactly ONE further attempt with the same token
    — deliberate and classified, not a blind retry (#2196):

      * it succeeds  → the 5xx really was "never processed", the rotation is
        intact, and the run recovers inside the invocation (the #2069 benefit,
        kept);
      * it returns 400 → the first POST DID rotate before failing to answer.
        The stored token is provably spent: raise `WhoopRotationLost`, which
        `authenticate` surfaces as its own urgent signal instead of letting it
        masquerade as a generic auth latch discovered days later.

    Any other outcome propagates unchanged.
    """
    payload = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": WHOOP_SCOPES,
        }
    ).encode()
    try:
        data = _token_post(payload)
    except urllib.error.HTTPError as e:
        if e.code not in _TOKEN_TRANSPORT_CODES:
            raise
        logger.warning("Whoop token POST returned %d — one classified probe with the same refresh_token", e.code)
        time.sleep(_TOKEN_PROBE_DELAY_SECONDS)
        try:
            data = _token_post(payload)
        except urllib.error.HTTPError as probe_exc:
            if probe_exc.code == 400:
                raise WhoopRotationLost(
                    f"WHOOP_ROTATION_LOST — the token endpoint returned {e.code} and then rejected the same "
                    "refresh_token, so Whoop consumed the rotation and the new token was lost in transit. "
                    "The stored credential is dead; re-auth required NOW: python3 setup/setup_whoop_auth.py"
                ) from probe_exc
            raise
    return data["access_token"], data["refresh_token"], int(data.get("expires_in") or 0)


def _invalidate_secret_cache() -> None:
    """Drop the warm-container copy of the Whoop secret after a rotation write.

    #2196, acceptance box 4: `common.secret_cache.invalidate` shipped with ZERO
    callers, so a warm container held the PRE-rotation secret for up to its 15
    minute TTL. Every "a concurrent invocation already rotated the token;
    adopting it" WARNING in the logs is that: a second invocation reading a
    cached, already-spent refresh_token and burning an exchange to discover it.
    Best-effort — a cache miss is never worse than a stale hit.
    """
    try:
        from common.secret_cache import invalidate
    except ImportError:  # pragma: no cover — layer-module fallback (local tooling)
        return
    try:
        invalidate(SECRET_NAME)
    except Exception as e:  # pragma: no cover — cache hygiene must never fail a run
        logger.warning("Whoop secret-cache invalidate failed (non-fatal): %s", e)


def _emit_rotation_lost_metric() -> None:
    """The distinct urgent signal for a lost rotation (#2196, box 3).

    Rides the EXISTING OAuth observability channel rather than inventing one:
    the same `LifePlatform/OAuth` namespace and `Source` dimension the
    auth_breaker's IngestAuthHealthy uses, on the PutMetricData grant the
    ingestion role already holds (role_policies._ingestion_base) — so this
    needs no IAM change and no new topic. The generic latch still happens
    (mark_as_auth_failure → the framework marks the breaker → IngestAuthHealthy
    0 → `ingest-auth-unhealthy-whoop`, urgent-topic-routed, which is what pages
    and reaches the remediation triage). What this metric adds is the CAUSE,
    separable from "the credential expired": a nonzero OAuthRotationLost{whoop}
    means re-auth NOW, not "look into it". The marker text carries the same
    classification into the operator-visible error string.
    """
    try:
        _cw.put_metric_data(
            Namespace="LifePlatform/OAuth",
            MetricData=[
                {
                    "MetricName": "OAuthRotationLost",
                    "Dimensions": [{"Name": "Source", "Value": "whoop"}],
                    "Value": 1.0,
                    "Unit": "Count",
                }
            ],
        )
    except Exception as e:  # metric emission must never fail the run
        logger.warning("Whoop rotation-lost metric emit failed (non-fatal): %s", e)


def _persist_refreshed_secret(secret: dict) -> bool:
    """Write the rotated credentials to Secrets Manager IMMEDIATELY — inside
    `authenticate()`, before it returns, before any fetch/transform work, and
    before control even returns to `ingestion_framework.run_ingestion` (which
    also writes back on `enable_secret_writeback`, redundantly-but-safely,
    since it re-writes the identical already-persisted dict).

    Why here specifically (#2069): Whoop invalidates the OLD refresh_token
    server-side the instant it issues the token response — the single-use
    rotation is consumed at that moment, not when WE finish processing it. So
    the durability window is bounded below by network latency (irreducible)
    and bounded above by how much of OUR OWN code runs between "we have the
    new token" and "it's durably stored." Persisting here, in the same
    function that just received the token, collapses that upper bound to
    (approximately) the write itself — no fetch_day, no transform, not even a
    second function's worth of unrelated logic, can get between rotation and
    persistence.

    Retries once (mirrors ingestion_framework's own writeback shape, #481/A-9)
    A second failure is logged at ERROR ('re-auth likely needed') but does
    NOT raise — an otherwise-successful token exchange must not fail the run
    over a transient Secrets Manager hiccup; the framework's own writeback
    step gets a second chance right after `authenticate` returns. Returns
    True iff the write landed here.
    """
    secrets_client = boto3.client("secretsmanager", region_name=REGION)
    for attempt in (1, 2):
        try:
            secrets_client.update_secret(SecretId=SECRET_NAME, SecretString=json.dumps(secret))
            _invalidate_secret_cache()
            logger.info("Whoop rotated refresh_token persisted immediately post-refresh")
            return True
        except Exception as e:
            if attempt == 1:
                logger.warning(f"Whoop immediate secret writeback failed (attempt 1/2, retrying): {e}")
                time.sleep(1)
            else:
                logger.error(
                    f"Whoop immediate secret writeback FAILED twice — rotated refresh_token may be stranded; " f"re-auth likely needed: {e}"
                )
    return False


def _fetch_endpoint(access_token: str, endpoint: str, start_dt: str, end_dt: str) -> dict:
    """GET on the shared retry policy (#501/X-11 — converged onto http_retry;
    3-attempt 2s/8s backoff on 429/5xx and network errors). Auth failures
    (401/403) still bubble immediately — the auth_breaker pattern handles those."""
    params = urllib.parse.urlencode({"start": start_dt, "end": end_dt, "limit": 25})
    url = f"{WHOOP_API_BASE}/{endpoint}?{params}"
    req = urllib.request.Request(
        url,
        method="GET",
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json", "User-Agent": "WhoopIngestion/1.0"},
    )
    with urlopen_with_retry(req, timeout=30) as resp:
        return json.loads(resp.read())


def _fetch_all_records(access_token: str, endpoint: str, start_dt: str, end_dt: str, max_pages: int = 60) -> list:
    """Page through EVERY record in [start_dt, end_dt] by following Whoop's
    ``next_token`` cursor. ``_fetch_endpoint`` above takes only the first page
    (limit=25) — fine for a single-day ingest, but the reconciler's trailing
    window can hold more than a page of workouts/sleeps, so a silent drop past
    page 1 would masquerade as a gap. ``max_pages`` is a runaway guard."""
    records: list = []
    next_token = None
    for _ in range(max_pages):
        params = {"start": start_dt, "end": end_dt, "limit": 25}
        if next_token:
            params["nextToken"] = next_token
        url = f"{WHOOP_API_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(
            url,
            method="GET",
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json", "User-Agent": "WhoopIngestion/1.0"},
        )
        with urlopen_with_retry(req, timeout=30) as resp:
            data = json.loads(resp.read())
        records.extend(data.get("records", []) or [])
        next_token = data.get("next_token")
        if not next_token:
            break
    return records


# ── Field extractors (DDB-shape preserved from pre-migration) ────────────────


def _set_dec(fields: dict, name: str, value) -> None:
    if value is None:
        return
    fields[name] = Decimal(str(value))


def _round(value, decimals):
    return round(value, decimals) if value is not None else None


def _extract_recovery(recovery: dict) -> dict:
    fields: dict[str, Any] = {}
    records = recovery.get("records", [])
    if not records:
        return fields
    record = records[0]
    if record.get("score_state") != "SCORED":
        return fields
    score = record.get("score") or {}
    _set_dec(fields, "recovery_score", score.get("recovery_score"))
    _set_dec(fields, "resting_heart_rate", score.get("resting_heart_rate"))
    hrv = score.get("hrv_rmssd_milli")
    if hrv is not None:
        _set_dec(fields, "hrv", round(hrv, 2))
    _set_dec(fields, "spo2_percentage", _round(score.get("spo2_percentage"), 2))
    _set_dec(fields, "skin_temp_celsius", _round(score.get("skin_temp_celsius"), 2))
    return fields


def _extract_sleep(sleep: dict) -> dict:
    fields: dict[str, Any] = {}
    records = sleep.get("records", [])
    main = next((r for r in records if not r.get("nap", False)), None)
    if not main or main.get("score_state") != "SCORED":
        return fields
    score = main.get("score") or {}
    stage = score.get("stage_summary", {}) or {}

    def ms_to_h(ms):
        return round((ms or 0) / 3_600_000, 2)

    in_bed_ms = stage.get("total_in_bed_time_milli", 0)
    awake_ms = stage.get("total_awake_time_milli", 0)
    rem_ms = stage.get("total_rem_sleep_time_milli", 0)
    sws_ms = stage.get("total_slow_wave_sleep_time_milli", 0)
    light_ms = stage.get("total_light_sleep_time_milli", 0)
    sleep_ms = in_bed_ms - awake_ms

    if sleep_ms > 0:
        _set_dec(fields, "sleep_duration_hours", ms_to_h(sleep_ms))
    if rem_ms > 0:
        _set_dec(fields, "rem_sleep_hours", ms_to_h(rem_ms))
    if sws_ms > 0:
        _set_dec(fields, "slow_wave_sleep_hours", ms_to_h(sws_ms))
    if light_ms > 0:
        _set_dec(fields, "light_sleep_hours", ms_to_h(light_ms))
    if awake_ms > 0:
        _set_dec(fields, "time_awake_hours", ms_to_h(awake_ms))

    if stage.get("disturbance_count") is not None:
        fields["disturbance_count"] = int(stage["disturbance_count"])

    _set_dec(fields, "respiratory_rate", _round(score.get("respiratory_rate"), 2))
    _set_dec(fields, "sleep_efficiency_percentage", _round(score.get("sleep_efficiency_percentage"), 2))
    _set_dec(fields, "sleep_consistency_percentage", _round(score.get("sleep_consistency_percentage"), 2))

    perf = score.get("sleep_performance_percentage")
    if perf is not None:
        _set_dec(fields, "sleep_performance_percentage", perf)
        _set_dec(fields, "sleep_quality_score", perf)  # backward-compat alias

    if main.get("start"):
        fields["sleep_start"] = main["start"]
    if main.get("end"):
        fields["sleep_end"] = main["end"]

    naps = [r for r in records if r.get("nap", False)]
    if naps:
        fields["nap_count"] = len(naps)
        total_nap_ms = 0
        for nap in naps:
            ns = (nap.get("score") or {}).get("stage_summary") or {}
            total_nap_ms += ns.get("total_in_bed_time_milli", 0) - ns.get("total_awake_time_milli", 0)
        if total_nap_ms > 0:
            _set_dec(fields, "nap_duration_hours", round(total_nap_ms / 3_600_000, 2))
    return fields


def _extract_cycle(cycle: dict) -> dict:
    fields: dict[str, Any] = {}
    records = cycle.get("records", [])
    if not records or records[0].get("score_state") != "SCORED":
        return fields
    score = records[0].get("score") or {}
    _set_dec(fields, "strain", _round(score.get("strain"), 2))
    _set_dec(fields, "kilojoule", _round(score.get("kilojoule"), 2))
    _set_dec(fields, "average_heart_rate", score.get("average_heart_rate"))
    _set_dec(fields, "max_heart_rate", score.get("max_heart_rate"))
    return fields


def _extract_workout(workout: dict) -> dict:
    fields = {}
    sport_id = workout.get("sport_id")
    if sport_id is not None:
        fields["sport_id"] = int(sport_id)
        fields["sport_name"] = WHOOP_SPORT_NAMES.get(sport_id, f"Sport_{sport_id}")
    for key in ("start", "end"):
        if workout.get(key):
            fields[f"{key}_time"] = workout[key]
    if workout.get("score_state") != "SCORED":
        return fields
    score = workout.get("score") or {}
    _set_dec(fields, "strain", _round(score.get("strain"), 2))
    _set_dec(fields, "average_heart_rate", score.get("average_heart_rate"))
    _set_dec(fields, "max_heart_rate", score.get("max_heart_rate"))
    _set_dec(fields, "kilojoule", _round(score.get("kilojoule"), 2))
    _set_dec(fields, "distance_meter", _round(score.get("distance_meter"), 1))
    zone_dur = score.get("zone_duration", {}) or {}
    for i, word in enumerate(_ZONE_WORD):
        ms = zone_dur.get(f"zone_{word}_milli") or 0
        fields[f"zone_{i}_minutes"] = Decimal(str(round(ms / 60_000, 2)))
    return fields


# ── Sleep-onset consistency (cross-day) ───────────────────────────────────────


def _sleep_onset_minutes(iso_ts: str | None) -> int | None:
    dt = parse_iso_utc(iso_ts)  # #1964: the one parser
    return dt.hour * 60 + dt.minute if dt else None


def _compute_sleep_consistency(date_str: str, current_onset: int) -> float | None:
    """Query the prior 6 nights; compute 7-day StdDev of onset times (midnight-aware).

    The whoop partition interleaves DATE#{d}#WORKOUT#{id} sub-records with the
    date-only night records, so a bare Limit=6 descending page can be mostly
    workouts on training-heavy weeks (#488/A-6). Bound the key range to the
    actual 7-day window and skip the workout sub-records.
    """
    window_start = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=6)).strftime("%Y-%m-%d")
    resp = _table.query(
        KeyConditionExpression=Key("pk").eq(f"USER#{USER_ID}#SOURCE#whoop") & Key("sk").between(f"DATE#{window_start}", f"DATE#{date_str}"),
        ProjectionExpression="sk, sleep_onset_minutes",
        ScanIndexForward=False,
    )
    onsets = [current_onset]
    for item in resp.get("Items", []):
        sk = item.get("sk", "")
        if "#WORKOUT#" in sk or sk == f"DATE#{date_str}":
            continue
        val = item.get("sleep_onset_minutes")
        if val is not None:
            onsets.append(int(val))
    if len(onsets) < 3:
        return None
    if max(onsets) - min(onsets) > 720:
        onsets = [v + 1440 if v < 720 else v for v in onsets]
    return round(statistics.stdev(onsets), 1)


# ── SIMP-2 callbacks ──────────────────────────────────────────────────────────

_secret_cache: dict[str, Any] = {"access_token": None}
# Per-invocation rotation state (#2196). Reserved concurrency is 1, so a module
# global is a per-invocation scratchpad; `authenticate` resets it every run.
_rotation_state: dict[str, Any] = {"rotated_at": None}


class WhoopTransientAuthGlitch(RuntimeError):
    """A data-endpoint auth rejection seconds after a *successful* rotation.

    Deliberately NOT an HTTPError and deliberately worded without any of
    `auth_breaker`'s classifier substrings ("401", "unauthorized", "auth
    failed", …): the framework must record this as an ordinary per-date error
    (the run reports 207, the ingest-health streak grows, the
    consecutive-failures alarm still covers recurrence) WITHOUT latching the
    24h breaker on a credential that just proved itself working.
    """


def _seconds_until_expiry(secret: dict) -> float | None:
    """Life left on the stored access token, or None if we can't tell.

    None (no stored expiry — e.g. the first run after a re-auth, or a secret
    written before #2196) means "assume expired" at every call site: the
    conservative direction, since a wrong reuse costs a whole run's data while
    a wrong refresh costs one exchange.
    """
    raw = secret.get(_EXPIRES_AT_FIELD)
    if raw is None:
        return None
    try:
        return float(raw) - time.time()
    except (TypeError, ValueError):
        return None


def authenticate(secret_data: dict) -> dict:
    """Return usable credentials, exchanging the refresh_token ONLY when needed.

    #2196 (acceptance box 1) — the treadmill this ends: `authenticate` ran on
    every invocation, before gap detection, and unconditionally spent one
    single-use refresh_token rotation. At ~22 invocations/day against a
    measured ~1% token-endpoint 5xx rate, the expected time to a lost rotation
    was 4-5 days — which matches the observed 08-01 / 08-03 / 08-04 cadence
    exactly. An access token is reusable until it expires, so the exchange is
    now gated on the expiry Whoop itself reports (`expires_in`, stored as
    `access_token_expires_at` IN the existing secret JSON — no new storage),
    minus a skew margin. The rotation rate becomes at most one per access-token
    lifetime instead of one per invocation: the 09:30 recovery-refresh run, the
    daily reconcile invocation, EventBridge at-least-once duplicates and warm
    re-entries all stop costing a rotation.
    """
    secret = dict(secret_data)
    _rotation_state["rotated_at"] = None

    stored_token = secret.get("access_token")
    remaining = _seconds_until_expiry(secret)
    if stored_token and remaining is not None and remaining > _ACCESS_TOKEN_SKEW_SECONDS:
        _secret_cache["access_token"] = stored_token
        logger.info("whoop_token_reused remaining_s=%d — no refresh_token rotation this run", int(remaining))
        return secret

    logger.info("whoop_token_exchange reason=%s", "no_stored_expiry" if remaining is None else f"expires_in_{int(remaining)}s")
    return _rotate(secret)


def _rotate(secret: dict) -> dict:
    """Spend one refresh_token rotation and persist the result.

    Concurrency-safe (2026-06-08): EventBridge at-least-once delivery occasionally
    fires two invocations seconds apart. The first rotates the single-use refresh
    token; the second then gets HTTP 400. On a 400 we re-read the secret fresh
    (briefly retrying to cover the winner's secret-writeback window) — if a
    concurrent invocation already rotated it, we adopt the winner's tokens rather
    than fail (a raise here DLQs a benign race + false-fires the error alarm).
    A 400 with an *unchanged* refresh_token is a genuine auth failure and raises
    — marked via `mark_as_auth_failure` (#2069) so the breaker's classifier
    (which only recognizes 401/403 + keywords, deliberately NOT a bare '400'
    — a data-fetch 400 is not auth) can latch on THIS specific, call-site-
    confirmed case without over-broadening what counts as "auth" globally.

    `WhoopRotationLost` (#2196) is the third outcome: not a race, not an expired
    credential — a rotation Whoop consumed and we never received. It gets its
    own urgent signal before it re-raises into the same latch.
    """
    try:
        access_token, new_refresh, expires_in = _refresh_access_token(
            secret["client_id"],
            secret["client_secret"],
            secret["refresh_token"],
        )
    except WhoopRotationLost as lost:
        logger.error("%s", lost)
        _emit_rotation_lost_metric()
        mark_as_auth_failure(lost)
        raise
    except urllib.error.HTTPError as e:
        if e.code != 400:
            raise
        for _ in range(2):
            time.sleep(1.5)  # let a concurrent invocation persist its rotated token
            _invalidate_secret_cache()  # never decide the race from a warm-container copy
            fresh = json.loads(boto3.client("secretsmanager").get_secret_value(SecretId=SECRET_NAME)["SecretString"])
            if fresh.get("refresh_token") and fresh["refresh_token"] != secret["refresh_token"]:
                logger.warning("Whoop refresh 400 — a concurrent invocation already rotated the token; adopting it.")
                secret["access_token"] = fresh["access_token"]
                secret["refresh_token"] = fresh["refresh_token"]
                if fresh.get(_EXPIRES_AT_FIELD) is not None:
                    secret[_EXPIRES_AT_FIELD] = fresh[_EXPIRES_AT_FIELD]
                _secret_cache["access_token"] = fresh["access_token"]
                # The winner minted this token seconds ago — same grace footing
                # as if we had rotated it ourselves (see _fetch_all_endpoints).
                _rotation_state["rotated_at"] = time.time()
                return secret
        logger.error("Whoop refresh 400 with unchanged refresh_token — genuine auth failure.")
        mark_as_auth_failure(e)
        raise
    secret["access_token"] = access_token
    secret["refresh_token"] = new_refresh
    if expires_in > 0:
        secret[_EXPIRES_AT_FIELD] = int(time.time()) + expires_in
    else:  # the provider didn't say — don't invent a lifetime, just re-exchange next run
        secret.pop(_EXPIRES_AT_FIELD, None)
    _secret_cache["access_token"] = access_token
    _rotation_state["rotated_at"] = time.time()
    # #2069: persist BEFORE returning — see _persist_refreshed_secret's docstring
    # for why this closes the crash window instead of relying solely on the
    # framework's post-authenticate() writeback.
    _persist_refreshed_secret(secret)
    return secret


# ── Data-endpoint 401 handling (#2196, acceptance box 6) ──────────────────────


def _glitch_marker_is_fresh() -> bool:
    """True if a previous run already used the one-shot transient-401 grace.

    Same marker shape as the auth breaker (DDB item on the whoop partition with
    a TTL), read age-first so an expired-but-not-yet-reaped row can't latch a
    healthy run. Read failures return False — the grace stays available, which
    is the fail-open direction that matches the framework's own breaker lookup.
    """
    try:
        resp = _table.get_item(Key={"pk": f"USER#{USER_ID}#SOURCE#whoop", "sk": _GLITCH_SK})
    except Exception as e:
        logger.warning("whoop glitch-marker lookup failed (non-fatal): %s", e)
        return False
    item = resp.get("Item")
    if not item:
        return False
    try:
        marked_at = float(item.get("marked_at_epoch", 0))
    except (TypeError, ValueError):
        return False
    return (time.time() - marked_at) < _GLITCH_TTL_SECONDS


def _mark_glitch() -> None:
    now = time.time()
    try:
        _table.put_item(
            Item={
                "pk": f"USER#{USER_ID}#SOURCE#whoop",
                "sk": _GLITCH_SK,
                "marked_at_epoch": Decimal(str(int(now))),
                "marked_at": datetime.now(timezone.utc).isoformat(),
                "ttl": int(now) + _GLITCH_TTL_SECONDS,
            }
        )
    except Exception as e:
        logger.warning("whoop glitch-marker write failed (non-fatal): %s", e)


def _fetch_all_endpoints(token: str, start_dt: str, end_dt: str) -> dict:
    return {
        "recovery": _fetch_endpoint(token, "recovery", start_dt, end_dt),
        "sleep": _fetch_endpoint(token, "activity/sleep", start_dt, end_dt),
        "cycle": _fetch_endpoint(token, "cycle", start_dt, end_dt),
        "workouts": _fetch_endpoint(token, "activity/workout", start_dt, end_dt),
    }


def fetch_day(credentials: dict, date_str: str) -> dict | None:
    """Fetch all 4 Whoop endpoints for one calendar day (UTC).

    A 401 here is normally a genuine dead credential and MUST keep latching the
    breaker. Two narrow exceptions (#2196), in order:

      1. The access token was REUSED this run (no rotation — the box-1 path).
         A rejection then may simply mean the stored token died early, which
         before this change could not happen because every run refreshed. So:
         spend one rotation and retry once. If the exchange itself fails as
         auth, that propagates and latches, unchanged.
      2. The token was minted seconds ago (proactively, or by the retry above,
         or adopted from a concurrent winner) and the data endpoint still 401s.
         That is the 2026-08-01 shape: a healthy refresh at 12:00:20, a 401 at
         12:00:28, and a 24h breaker latched on a credential that was never
         dead. Grace it ONCE — durably, via the AUTH_GLITCH marker — so a
         recurrence on the next run latches normally.
    """
    token = _secret_cache["access_token"] or credentials["access_token"]
    next_day = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    start_dt = f"{date_str}T00:00:00.000Z"
    end_dt = f"{next_day}T00:00:00.000Z"

    try:
        return _fetch_all_endpoints(token, start_dt, end_dt)
    except urllib.error.HTTPError as e:
        if e.code != 401:
            raise
        if _rotation_state["rotated_at"] is None:
            logger.warning("Whoop data endpoint rejected the reused access token — spending one rotation and retrying.")
            refreshed = _rotate(dict(credentials))
            credentials.update(refreshed)  # later dates in this run reuse the new token
            try:
                return _fetch_all_endpoints(refreshed["access_token"], start_dt, end_dt)
            except urllib.error.HTTPError as retry_exc:
                if retry_exc.code != 401:
                    raise
                e = retry_exc
        age = time.time() - float(_rotation_state["rotated_at"] or 0)
        if age > _ROTATION_GRACE_SECONDS:
            raise  # not "seconds after a rotation" any more — treat as genuine
        if _glitch_marker_is_fresh():
            logger.error("Whoop data-endpoint auth rejection recurred after a fresh rotation — latching the breaker.")
            raise
        _mark_glitch()
        logger.warning(
            "Whoop data endpoint rejected a token minted %.0fs ago — transient, not latching; retries next run (#2196).",
            age,
        )
        # NB: the message is rendered in MINUTES on purpose — `auth_breaker`
        # classifies on substrings, and a seconds figure could literally print
        # "401" (age 401s is inside the grace window) and self-latch.
        raise WhoopTransientAuthGlitch(
            f"whoop data endpoint rejected a token minted {age / 60:.1f} minutes ago in this same run — "
            "classified transient (one-shot grace); the next run latches if it recurs"
        ) from e


def transform(raw: dict, date_str: str) -> list[dict]:
    """Build the daily aggregate item + one item per workout."""
    if not raw:
        return []
    normalized = {}
    normalized.update(_extract_recovery(raw["recovery"]))
    normalized.update(_extract_sleep(raw["sleep"]))
    normalized.update(_extract_cycle(raw["cycle"]))

    # Field-presence validation logging (F2.5)
    critical = ["recovery_score", "hrv", "resting_heart_rate", "sleep_duration_hours", "strain"]
    missing = [f for f in critical if f not in normalized]
    if missing:
        logger.warning("[VALIDATION] whoop/%s missing CRITICAL fields: %s", date_str, missing)

    # Sleep onset + 7-day consistency
    onset_min = _sleep_onset_minutes(normalized.get("sleep_start"))
    if onset_min is not None:
        normalized["sleep_onset_minutes"] = onset_min
        consistency = _compute_sleep_consistency(date_str, onset_min)
        if consistency is not None:
            normalized["sleep_onset_consistency_7d"] = Decimal(str(consistency))

    items = []
    if normalized:
        items.append({"source": "whoop", "date": date_str, **normalized})

    for workout in raw["workouts"].get("records", []):
        wid = workout["id"]
        items.append(
            {
                "source": "whoop",
                "date": date_str,
                "workout_id": wid,
                "sk_suffix": f"#WORKOUT#{wid}",
                **_extract_workout(workout),
            }
        )
    return items


# ── Framework config ──────────────────────────────────────────────────────────

_config = IngestionConfig(
    source_name="whoop",
    secret_id=SECRET_NAME,
    s3_archive_prefix=f"raw/{USER_ID}/whoop",
    schema_version=1,
    enable_gap_detection=True,
    lookback_days=int(os.environ.get("LOOKBACK_DAYS", "7")),
    enable_secret_writeback=True,
    enable_item_size_guard=True,
    refresh_today=True,  # Whoop recovery score finalizes mid-morning
    # Late-arriving workouts (2026-06-24): Whoop stores per-workout sub-records at
    # DATE#{date}#WORKOUT#{id}, but gap detection keys off the DATE#{date} recovery
    # record — so a workout that syncs from the band AFTER that day's recovery was
    # stored lands on an already-"present" date and is silently dropped, exactly the
    # Strava afternoon-walk class. Whoop runs hourly and has no rate-limit breaker, so
    # re-fetching a short trailing window is safe and cheap; it re-emits the per-workout
    # sub-records (keyed by id, idempotent) and picks up the late arrival. 2 days covers
    # the band's continuous-sync latency with buffer.
    refresh_trailing_days=2,
)


# ── Reconciliation (DI-2, TR-07 #415) ─────────────────────────────────────────
# Every other Whoop freshness check reads only DynamoDB, so it sees only the
# high-water mark — blind to a *silent drop* where the Whoop API holds a record
# (a scored night, or a workout that synced from the band AFTER its day's
# recovery was already stored) that never landed in the store. That is the same
# class as the Jun-2026 evening-walk bug the Strava DI-2 reconciler catches.
# `refresh_trailing_days=2` HEALS the late-workout variant, but healing is blind
# to whether it actually worked; reconciliation is the independent audit that
# compares against the source of truth.
#
# This mirrors the shipped Strava pattern (strava_lambda._reconcile): the SAME
# lambda is invoked with {"reconcile": true}, pulls a trailing window from the
# Whoop API, and diffs it against the store. Two record classes are checked:
#   • daily biometric  — each SCORED main sleep (nap=false) anchors a UTC day
#     that MUST have a stored DATE#{day} record.
#   • workout          — each workout id W on day D must have a stored
#     DATE#{D}#WORKOUT#{W} sub-record.
# Emitted as LifePlatform/IngestReconciliation::MissingActivityCount{Source=whoop}
# (same metric as strava, distinguished by the Source dimension) and alarmed in
# monitoring_stack — READ-ONLY: it reports gaps, it never heals (that stays the
# ingestion job's role).
#
# OPT-IN: wired only because whoop carries the `provider_reconcile` facet in
# source_registry (garmin explicitly does NOT — ADR-123). The schedule lives in
# ingestion_stack; this handler branch is inert unless invoked with reconcile.

RECONCILE_WINDOW_DAYS = int(os.environ.get("WHOOP_RECONCILE_WINDOW_DAYS", "14"))


def _utc_day(s) -> str | None:
    """The UTC calendar date (YYYY-MM-DD) a Whoop record is keyed under — the
    ingestion per-date loop fetches by [day T00:00Z, nextday T00:00Z), so a
    record's DDB day is the UTC day of its ``start``.

    #1964: parses via the canonical ``parse_iso_utc``. The private ``_parse_iso``
    this replaces left a tz-less stamp NAIVE, so ``.astimezone(timezone.utc)``
    below would have interpreted it in the *runner's* local zone — correct only
    by the coincidence that the Lambda runtime is UTC, and wrong under a local
    pytest run or a laptop backfill. The canonical parser stamps naive input UTC,
    which is what this function's own docstring already assumed.
    """
    t = parse_iso_utc(s)
    return t.astimezone(timezone.utc).strftime("%Y-%m-%d") if t else None


def _dedup_workouts(workouts: list, tolerance_seconds: int = 120) -> list:
    """Collapse near-simultaneous workout twins (a GPS-drop / double-log pair the
    band can surface as two ids for one session) so a legitimately single stored
    record is not reported as a gap for the twin. Mirrors strava._dedup: keep one
    representative per overlap window."""
    parsed = [(w, parse_iso_utc(w.get("start"))) for w in workouts]
    kept: list = []
    kept_times: list = []
    for w, t in sorted(parsed, key=lambda p: (p[1] is None, p[1] or datetime.min.replace(tzinfo=timezone.utc))):
        if t is not None and any(abs((t - kt).total_seconds()) <= tolerance_seconds for kt in kept_times):
            continue  # twin of an already-kept workout
        kept.append(w)
        if t is not None:
            kept_times.append(t)
    return kept


def _records_missing_from_store(
    sleeps: list, workouts: list, stored_sks: set, stored_workout_starts: list, tolerance_seconds: int = 120
) -> list:
    """Return the Whoop API records with no counterpart in the store.

    Dedup-aware on both axes: multiple sleep/recovery records for one UTC day
    collapse to a single expected DATE#{day} (inherent), and near-simultaneous
    workout twins collapse via ``_dedup_workouts`` + a time-tolerance match
    against stored workout starts — so a known twin never raises a false gap.
    """
    missing: list = []

    # Daily biometric: a SCORED main sleep means the day exists at the provider.
    expected_days = set()
    for s in sleeps:
        if s.get("nap", False) or s.get("score_state") != "SCORED":
            continue
        d = _utc_day(s.get("start"))
        if d:
            expected_days.add(d)
    for d in sorted(expected_days):
        if f"DATE#{d}" not in stored_sks:
            missing.append({"kind": "daily", "date": d, "sk": f"DATE#{d}"})

    # Workouts: id-keyed sub-records, dedup-aware.
    for w in _dedup_workouts(workouts, tolerance_seconds):
        wid = str(w.get("id", ""))
        d = _utc_day(w.get("start"))
        if wid and d and f"DATE#{d}#WORKOUT#{wid}" in stored_sks:
            continue
        t = parse_iso_utc(w.get("start"))
        if t is not None and any(abs((t - ts).total_seconds()) <= tolerance_seconds for ts in stored_workout_starts):
            continue  # near-duplicate of a stored workout (e.g. a deduped twin)
        missing.append({"kind": "workout", "id": wid, "date": d})

    return missing


def _fetch_stored_records(table, start_date: str, end_date: str) -> tuple:
    """Return (stored_sks, stored_workout_starts) for the whoop partition across
    [start_date, end_date] inclusive. The SK upper bound appends U+FFFF so the
    range also captures DATE#{end_date}#WORKOUT#... sub-records (which sort AFTER
    the bare DATE#{end_date})."""
    from boto3.dynamodb.conditions import Key

    pk = f"USER#{USER_ID}#SOURCE#whoop"
    sks: set = set()
    workout_starts: list = []
    kwargs = {
        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(f"DATE#{start_date}", f"DATE#{end_date}\uffff"),
        "ProjectionExpression": "sk, start_time",
    }
    while True:
        resp = table.query(**kwargs)
        for item in resp.get("Items", []):
            sk = item.get("sk", "")
            if not sk:
                continue
            sks.add(sk)
            if "#WORKOUT#" in sk:
                t = parse_iso_utc(item.get("start_time"))
                if t is not None:
                    workout_starts.append(t)
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    return sks, workout_starts


def _emit_reconciliation_metric(missing_count: int) -> None:
    try:
        _cw.put_metric_data(
            Namespace="LifePlatform/IngestReconciliation",
            MetricData=[
                {
                    "MetricName": "MissingActivityCount",
                    "Dimensions": [{"Name": "Source", "Value": "whoop"}],
                    "Value": float(missing_count),
                    "Unit": "Count",
                }
            ],
        )
    except Exception as e:  # metric emission must never fail the run
        logger.warning("reconcile metric emit failed (non-fatal): %s", e)


def _reconcile(event: dict, context) -> dict:
    """Diff the trailing-window Whoop API record set against the store (read-only).

    #2196 (acceptance box 5): this path used to bypass the ADR-052 auth breaker
    entirely — while the credential was dead from 08-03 to 08-07 the reconcile
    invocation still authenticated and hammered the token endpoint daily, one
    more exchange per day against a provider we already knew had locked us out
    (and one more chance to log a confusing failure on top of the real one).
    The breaker exists precisely so a known-dead credential stops being
    re-tried; honor it here the way run_ingestion does.
    """
    marker = check_breaker(_table, source_name="whoop", user_id=USER_ID, logger=logger)
    if marker:
        logger.info("[RECONCILE] skipped — auth breaker active (marked_at=%s)", marker.get("marked_at"))
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "mode": "reconcile",
                    "source": "whoop",
                    "skipped": "auth_failure_circuit_breaker",
                    "marked_at": str(marker.get("marked_at")),
                }
            ),
        }
    try:
        secrets_client = boto3.client("secretsmanager", region_name=REGION)
        try:
            from common.secret_cache import get_secret_json

            secret_data = get_secret_json(SECRET_NAME, secrets_client)
        except ImportError:
            secret_data = json.loads(secrets_client.get_secret_value(SecretId=SECRET_NAME)["SecretString"])

        # #2069: authenticate() now persists a rotated refresh_token itself
        # (_persist_refreshed_secret), immediately, before returning — this
        # reconcile invocation no longer needs its own separate writeback
        # step; it would only be a redundant re-write of the identical dict
        # authenticate() already wrote.
        secret = authenticate(secret_data)

        # #2976 considered clearing the breaker here (a successful authenticate()
        # is credential proof) and deliberately does NOT: the reconciler is
        # read-only on success by contract (test_reconcile_is_read_only), and the
        # main daily run now emits IngestAuthHealthy=1 on EVERY clean framework
        # run (errors == 0, even with zero new records), which is what feeds the
        # Source=whoop alarm's recovery path.

        token = secret["access_token"]
        # utc-exempt(#2811): bounds a UTC ISO window sent to the Whoop API
        # (`{start}T00:00:00.000Z` .. `{today+1}T00:00:00.000Z`), not a DATE# key —
        # Whoop's own collection boundaries are UTC, so the request frame must be too.
        today = datetime.now(timezone.utc).date()
        start = today - timedelta(days=RECONCILE_WINDOW_DAYS)
        start_dt = f"{start.isoformat()}T00:00:00.000Z"
        end_dt = f"{(today + timedelta(days=1)).isoformat()}T00:00:00.000Z"

        sleeps = _fetch_all_records(token, "activity/sleep", start_dt, end_dt)
        workouts = _fetch_all_records(token, "activity/workout", start_dt, end_dt)

        # DDB is keyed by the record's UTC day; the API window is UTC too, but a
        # workout that starts just before midnight UTC on the window edge can key
        # one day out — bracket the stored-side fetch by ±1 day (the strava-side
        # pattern). Extra stored rows only ADD match candidates; never a false gap.
        stored_sks, stored_workout_starts = _fetch_stored_records(
            _table,
            (start - timedelta(days=1)).isoformat(),
            (today + timedelta(days=1)).isoformat(),
        )
        missing = _records_missing_from_store(sleeps, workouts, stored_sks, stored_workout_starts)

        _emit_reconciliation_metric(len(missing))
        if missing:
            logger.warning(
                "[RECONCILE] %d Whoop records missing from store: %s",
                len(missing),
                [(m["kind"], m.get("id"), m.get("date")) for m in missing],
            )
        else:
            logger.info(
                "[RECONCILE] clean — %d sleeps + %d workouts all present in store (window=%dd)",
                len(sleeps),
                len(workouts),
                RECONCILE_WINDOW_DAYS,
            )
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "mode": "reconcile",
                    "source": "whoop",
                    "window_days": RECONCILE_WINDOW_DAYS,
                    "sleep_count": len(sleeps),
                    "workout_count": len(workouts),
                    "missing_count": len(missing),
                    "missing": missing,
                }
            ),
        }
    except Exception as e:
        # A reconcile failure (e.g. transient Whoop outage) must NOT raise — that
        # would trip the ingestion-error-whoop alarm on an unrelated cause. Skip
        # the metric for the day (the alarm treats missing data as not-breaching).
        #
        # #2196: an AUTH failure discovered here is different — swallowing it
        # kept the breaker un-latched, so the next reconcile went right back at
        # the dead endpoint. Mark it (same helper the framework uses), then
        # still return non-fatally.
        if looks_like_auth_failure(e):
            logger.error("[RECONCILE] auth failure — marking the breaker so the next run skips: %s", e)
            mark_failure(_table, source_name="whoop", user_id=USER_ID, error_msg=e, logger=logger)
        logger.error("[RECONCILE] failed (non-fatal): %s", e, exc_info=True)
        return {"statusCode": 200, "body": json.dumps({"mode": "reconcile", "source": "whoop", "error": str(e)})}


def lambda_handler(event: dict, context) -> dict:
    try:
        if event.get("healthcheck"):
            return {"statusCode": 200, "body": "ok"}
        if event.get("reconcile"):
            return _reconcile(event, context)
        return run_ingestion(_config, authenticate, fetch_day, transform, event, context)
    except Exception as e:
        logger.error("whoop ingestion failed: %s", e, exc_info=True)
        raise
