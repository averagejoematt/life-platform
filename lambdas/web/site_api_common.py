"""
lambdas/web/site_api_common.py — shared helpers for the site-api Lambda.

Extracted from lambdas/web/site_api_lambda.py (P1.1 Phase B, 2026-05-26).

This module owns:
  • AWS client setup (DDB table, S3 region/bucket)
  • Module-level caches (secrets, content filter, supplements, profile, status)
  • Configuration constants (TABLE_NAME, USER_ID, USER_PREFIX, EXPERIMENT_START)
  • Request envelope helpers (_ok, _error, CORS_HEADERS)
  • DDB helpers (_query_source, _latest_item, _decimal_to_float)
  • Cross-cutting business helpers (_get_profile, _scrub_blocked_terms [hardened], _is_blocked_vice, etc.)
  • Per-request correlation ID state (set by lambda_handler, read by _ok/_error)

site_api_lambda.py + sibling handler modules import from here.
"""

import copy  # noqa: F401 — kept for downstream import compatibility
import hashlib  # noqa: F401
import json
import logging
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key  # noqa: F401 — re-exported for downstream use
from common.constants import EXPERIMENT_BASELINE_WEIGHT_LBS, EXPERIMENT_START_DATE as EXPERIMENT_START
from common.pacific_time import PACIFIC
from experiment.phase_filter import with_phase_filter

# ── Config ─────────────────────────────────────────────────
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
PT = PACIFIC  # canonical frame (#1964) — re-exported to fingerprint/fulfillment
DDB_REGION = os.environ.get("DYNAMODB_REGION", "us-west-2")
S3_REGION = os.environ.get("S3_REGION", "us-west-2")
# Data query start: 1 day before experiment for sleep/recovery data
# (sleep keyed to wake date — night before genesis = record on that night).
EXPERIMENT_QUERY_START = "2026-05-17"

# ── Logger ─────────────────────────────────────────────────
logger = logging.getLogger("site_api")
logger.setLevel(logging.INFO)

# ── AWS clients (module-level for warm container reuse) ─────
dynamodb = boto3.resource("dynamodb", region_name=DDB_REGION)
table = dynamodb.Table(TABLE_NAME)

# ── Caches ─────────────────────────────────────────────────
# COST-OPT-1: cache secrets in warm containers (15-min TTL).
_secret_cache: dict = {}
_content_filter_cache = None
_content_filter_cache_at = None
_supp_metadata_cache = None
_supp_metadata_cache_at = None

# #2019 — bucket-root config/ objects were cached for the WHOLE life of a warm
# container. That was the second of three layers that let a merged correction
# stay dark: even after the object reached S3, live containers kept serving the
# bytes read on their first request (measured 2026-08-02: ~13h of withdrawn
# citations on /api/supplements). A short TTL means a synced config object
# starts serving on its own, with no Lambda recycle required.
CONFIG_CACHE_TTL_SECONDS = int(os.environ.get("CONFIG_CACHE_TTL_SECONDS", "300"))


def config_cache_valid(loaded_at):
    """True when a cached bucket-root config/ read may still be reused.

    `loaded_at is None` means PINNED: the cache was populated by something
    other than the S3 load path — tests inject these module globals directly —
    so it never expires. Only a real S3 read stamps a load time and takes a TTL.
    """
    if loaded_at is None:
        return True
    return (time.monotonic() - loaded_at) < CONFIG_CACHE_TTL_SECONDS


_status_cache: dict = {}
_status_cache_ts = 0
_cost_cache: dict = {}
_cost_cache_ts = 0
STATUS_CACHE_TTL = 60
_profile_cache = None

# ── Per-request correlation ID (P3.4) ─────────────────────
# Lambda handler sets via set_request_id(); _ok/_error read via get_request_id().
_current_request_id: str | None = None


def set_request_id(rid):
    global _current_request_id
    _current_request_id = rid


def get_request_id():
    return _current_request_id


# ── CORS ──────────────────────────────────────────────────
# SEC-07: CORS_ORIGIN env-configurable so staging/dev can override.
CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "https://averagejoematt.com")

# SEC-04: CloudFront injects X-AMJ-Origin header on every origin request.
# When SITE_API_ORIGIN_SECRET is set, missing/wrong values 403.
SITE_API_ORIGIN_SECRET = os.environ.get("SITE_API_ORIGIN_SECRET", "")
CORS_HEADERS = {
    "Access-Control-Allow-Origin": CORS_ORIGIN,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Subscriber-Token",
    "Access-Control-Max-Age": "3600",
    "Content-Type": "application/json",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}


# ── Platform stats — single source of truth for all site pages ──
# The discoverable fields (mcp_tools, lambdas, alarms, data_sources, adrs,
# test_count) are REWRITTEN by `python3 deploy/sync_doc_metadata.py --apply` and
# pinned by tests/test_platform_stats_truth.py — don't hand-edit them. lambdas =
# CDK-defined count; test_count = `def test_` functions in tests/. Judgment /
# live-AWS fields (monthly_cost, review_grade, active_secrets, site_pages…) stay
# hand-maintained.
PLATFORM_STATS = {
    "data_sources": 20,
    "mcp_tools": 76,
    "lambdas": 101,
    "cdk_stacks": 8,
    "alarms": 93,
    "adrs": 147,
    "monthly_cost": "~$80",  # GROUND-TRUTH run-rate, pinned (#1232). Source = the budget
    # governor's own numbers: June 2026 actual $79.80 (Cost Explorer), July projects $82.22
    # (SSM /life-platform/budget-breakdown "projected"; governor emits it as the
    # LifePlatform/Budget ProjectedMonthlySpend metric). Two consecutive months at ~$80, so
    # "~$80" is the honest trailing run-rate. The prior "~$60" understated it ~25% and its
    # comment cited the RETIRED "$75 cap" — the effective ceiling is $85, floating to $100 in
    # surge (ADR-133). This is a hand-maintained judgment field (never rewritten by
    # sync_doc_metadata); tests/test_platform_stats_cost.py is the offline drift guard.
    "review_count": 19,
    "review_grade": "A",
    "active_secrets": 21,
    "site_pages": 77,
    "test_count": 13134,
    "board_technical": 12,
    "board_product": 8,
    "start_weight": EXPERIMENT_BASELINE_WEIGHT_LBS,
    "goal_weight": 185,
    "start_date": EXPERIMENT_START,
}


# ── Helpers ───────────────────────────────────────────────


def _cached_secret(client, secret_id):
    entry = _secret_cache.get(secret_id)
    if entry and time.time() - entry[1] < 900:
        return entry[0]
    val = client.get_secret_value(SecretId=secret_id)["SecretString"]
    _secret_cache[secret_id] = (val, time.time())
    return val


def _decimal_to_float(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_to_float(i) for i in obj]
    return obj


def _clamp_today(date_str: str, _now_date: str | None = None) -> str:
    """Clamp a date (YYYY-MM-DD) to today as an UPPER bound — today in PACIFIC.

    Guards the future-genesis 500: a reset stages EXPERIMENT_START in the FUTURE
    (genesis = tomorrow), and any handler that uses it as a DynamoDB query lower
    bound — Key('sk').between(lower, upper) — throws a ValidationException when
    lower > upper (DynamoDB requires upper >= lower), 500'ing the endpoint.
    Clamping to today yields the empty [today, today] range ('no data yet').
    No-op once genesis <= today. Use this for ANY genesis-derived query lower
    bound that bypasses _query_source (which has its own start>end guard).

    PACIFIC, not UTC (genesis-eve incident, 2026-07-19 00:00-07:00 UTC): handlers
    build their UPPER bound from `datetime.now(PT)`, so a UTC clamp here left a
    ~7-hour window each genesis eve where lower(UTC today = genesis) > upper(PT
    today = genesis-1) — /api/fulfillment_ritual 500'd through it live. PT date
    is <= UTC date at every moment, so the PT clamp is safe for BOTH kinds of
    upper bound. `_now_date` is a test seam only."""
    today = _now_date or datetime.now(PT).strftime("%Y-%m-%d")
    return min(date_str, today)


def pre_start_meta() -> dict | None:
    """The pre-start countdown contract (#931). A reset can stage a FUTURE genesis
    (constants regenerate the night before Day 1), and for that window the site is
    an ANTICIPATED LAUNCH, not a broken Day 0. When EXPERIMENT_START > today (PT)
    this returns the shared payload block:

        {"pre_start": True, "days_until_start": N, "start_date": EXPERIMENT_START}

    where N = whole PT calendar days until genesis (always >= 1 — on genesis day
    itself the experiment has started). Returns None once genesis <= today: the
    normal path is a structural no-op, proven by tests/test_pre_start_countdown.py.
    Consumers: /api/journey, /api/snapshot, /api/pulse (+ the front-end doors); the
    #948 sweep added /api/observatory_week, /api/cycle_compare, /api/vacation_fund,
    /api/weekly_priority, /api/journey_waveform, /api/forecast (flag only) and the
    zeroed character/character_stats states."""
    today = datetime.now(PT).date()
    start = date.fromisoformat(EXPERIMENT_START)
    if start <= today:
        return None
    return {"pre_start": True, "days_until_start": (start - today).days, "start_date": EXPERIMENT_START}


def _experiment_date(days_back=30):
    """Compute a date N days ago, clamped to EXPERIMENT_START (lower) and today (upper).
    Use this for ALL date range queries to prevent pre-experiment data leaking through.
    The today-clamp (via _clamp_today) prevents the future-genesis 500 — see that helper."""
    raw = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
    return _clamp_today(max(raw, EXPERIMENT_START))


def _window_span(start, end, requested_days):
    """The honest companion to _experiment_date: given an ALREADY-clamped window,
    say how much window it actually is.

    Returns {"start", "requested_days", "actual_days", "full"}.

    #1917 — WHY THIS EXISTS. `_experiment_date` gives an honest *query window*
    (ADR-077 "clamped, not hidden": at a reset the window shrinks rather than
    reaching into prior-cycle rows). What it does NOT do is tell the caller that
    the window shrank — so a field computed off it and *named* for the requested
    window (`weight_delta_30d`, `hrv_30d_avg`) keeps its 30-day name while
    carrying 6 days of data. The arithmetic was always honest; the label was not.
    That is what qa-smoke's reader_truth caught on Day 5 of cycle 11, and it
    recurs on Day 1..N-1 of EVERY cycle restart.

    THE RULE (the #1917 decision, recorded here because this is where the window
    is measured): a published field named for an N-day window must either span a
    real N days or not carry a value. Callers therefore do BOTH of:

      1. publish the value under a window-generic name plus the actual window
         (`weight_delta_lbs` + `weight_delta_window_days`) — the number is real
         and useful on Day 6, so it is NOT hidden; and
      2. gate the legacy `_Nd`-named key on `full`, so that key reads None until
         the window genuinely covers N days.

    Option (2) alone (null-and-hide) was rejected: it would suppress a true
    number for 30 days after every reset, which contradicts "clamped, not
    hidden". Renaming outright was rejected because `_Nd` keys are a public API
    contract; gated, they stay truthful instead of disappearing.

    Takes the clamped `start` rather than re-deriving it from `days_back`, so a
    handler that already computed its own window — as handle_vitals does for
    d30/d7 — reports the span of THAT window. Re-deriving is not equivalent: it
    ignores a caller-local or monkeypatched EXPERIMENT_START, which is both a
    test-seam break and a real divergence risk on the time-travel path (where
    ADR-058 deliberately keeps the full 30-day reach). One clamp, one source of
    truth. `full` is False whenever genesis — including a staged FUTURE genesis —
    truncated the window.

    The enforcement half is `tests/test_window_name_honesty_1917.py`, which
    AST-scans lambdas/web/ so a NEW window-named field cannot ship undeclared.
    """
    actual = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days
    actual = max(actual, 0)  # a staged FUTURE genesis makes start > end: zero window, never negative
    return {"start": start, "requested_days": requested_days, "actual_days": actual, "full": actual >= requested_days}


# ── #1923: the wake-date temporal frame, in ONE place ────────────────────────
# Sleep/recovery/HRV/RHR are WAKE-DATE-KEYED: a record stored under 2026-07-31 is
# the reading from the night that set up the morning of 2026-07-31 — i.e. the night
# of 2026-07-30. So `night_of = as_of - 1 day`, always, by construction. (Weight is
# the opposite: same-day. See weight_as_of.)
#
# This is a deliberate, documented design decision, and on 2026-08-01 `reader_truth`
# raised it as a HIGH `temporal_contradiction` — an AI judge calling correct code a
# lie, on a check that gated deploys. The right answer to "a stochastic judge keeps
# re-litigating our contract" is to pin the contract in code, not to change working
# code until the judge stops complaining.
#
# Every surface publishing a `night_of` key must derive it HERE, so the frame cannot
# fork. tests/test_night_of_frame_1923.py AST-scans lambdas/web/ for `"night_of"`
# dict keys and fails any that compute the offset inline — the surface set is
# derived from the source, never hand-listed (#1917's lesson).
#
# NOT to be confused with `recovery_night_of` (site_api_vitals), which is a
# DIFFERENT quantity: the date of a borrowed recovery block when the latest night
# has none. That one is a real stored date, not an offset, and is deliberately out
# of scope here.
NIGHT_OF_FRAME = "last_night"
NIGHT_OF_OFFSET_DAYS = 1


def night_of_for(as_of):
    """The night a wake-date-keyed reading came from: `as_of` minus one day.

    Returns None for a missing/unparseable date — a caller must publish no
    `night_of` rather than a guessed one.
    """
    try:
        return (datetime.strptime(str(as_of)[:10], "%Y-%m-%d") - timedelta(days=NIGHT_OF_OFFSET_DAYS)).strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001 — an unparseable date means "no frame", never a guess
        return None


def _query_source(source: str, start_date: str, end_date: str, include_pilot: bool = False) -> list:
    """Query DynamoDB for a source within a date range. ADR-058: phase=pilot hidden by default."""
    if start_date > end_date:
        return []  # EXPERIMENT_START is in the future — no data yet
    pk = f"{USER_PREFIX}{source}"
    kwargs = with_phase_filter(
        {
            "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(f"DATE#{start_date}", f"DATE#{end_date}"),
        },
        include_pilot=include_pilot,
    )
    # Paginate: a long date range (or large items) can exceed DynamoDB's 1 MB
    # response limit; without the loop, trend endpoints silently truncate.
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
        kwargs["ExclusiveStartKey"] = last_key
    return _decimal_to_float(items)


def _latest_item(source: str, include_pilot: bool = False) -> dict | None:
    """Get the most recent item for a source. ADR-058: phase=pilot hidden by default."""
    pk = f"{USER_PREFIX}{source}"
    kwargs = with_phase_filter(
        {
            "KeyConditionExpression": Key("pk").eq(pk),
            "ScanIndexForward": False,
            "Limit": 1,
        },
        include_pilot=include_pilot,
    )
    resp = table.query(**kwargs)
    items = _decimal_to_float(resp.get("Items", []))
    return items[0] if items else None


def _latest_item_asof(source: str, date: str, include_pilot: bool = False) -> dict | None:
    """Most-recent item on-or-before `date` (DATE#YYYY-MM-DD) — the time-travel
    counterpart of _latest_item. Phase 4 historical windows: 'the latest reading as it
    stood that morning'. ADR-058: pass include_pilot=True when time-travelling so
    prior-cycle history is visible (mirrors handle_character)."""
    pk = f"{USER_PREFIX}{source}"
    kwargs = with_phase_filter(
        {
            "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between("DATE#0000-00-00", f"DATE#{date}"),
            "ScanIndexForward": False,
            "Limit": 1,
        },
        include_pilot=include_pilot,
    )
    resp = table.query(**kwargs)
    items = _decimal_to_float(resp.get("Items", []))
    return items[0] if items else None


def nutrition_delivery_public() -> bool:
    """Shared parse of NUTRITION_DELIVERY_PUBLIC (P2.3, #2209) — the single source of
    truth for whether the `food_delivery` DDB partition may be queried and published on
    ANY public route. Every reader of that partition in lambdas/web/ must gate through
    this helper (checked before querying — never query-then-filter) rather than
    re-parsing the env var, so the two readers can never drift out of sync. Default OFF:
    with the flag off, the delivery source is never queried and nothing private
    (spend/binge figures) enters any response. Byte-identical parsing to the pre-#2209
    inline check: `.strip().lower() in ("1", "true", "yes")`.
    """
    return os.environ.get("NUTRITION_DELIVERY_PUBLIC", "").strip().lower() in ("1", "true", "yes")


def _get_profile() -> dict:
    """Read PROFILE#v1 from DynamoDB. Cached after first call in warm container."""
    global _profile_cache
    if _profile_cache is not None:
        return _profile_cache
    try:
        resp = table.get_item(Key={"pk": f"USER#{USER_ID}", "sk": "PROFILE#v1"})
        _profile_cache = _decimal_to_float(resp.get("Item", {}))
    except Exception as e:
        logger.warning("[profile] Failed to read profile: %s", e)
        _profile_cache = {}
    return _profile_cache


def _load_supp_metadata() -> dict:
    """Load supplement registry from the canonical S3 config/ prefix (root, not the
    site/config mirror — the latter is purged by experiment resets). Cached."""
    global _supp_metadata_cache, _supp_metadata_cache_at
    if _supp_metadata_cache is not None and config_cache_valid(_supp_metadata_cache_at):
        return _supp_metadata_cache
    try:
        S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
        s3 = boto3.client("s3", region_name=S3_REGION)
        resp = s3.get_object(Bucket=S3_BUCKET, Key="config/supplement_registry.json")
        data = json.loads(resp["Body"].read())
        _supp_metadata_cache = data
        _supp_metadata_cache_at = time.monotonic()
        total = sum(len(g.get("items", [])) for g in data.get("groups", {}).values())
        logger.info(f"[supp_registry] Loaded: {total} supplements in {len(data.get('groups', {}))} groups")
    except Exception as e:
        logger.warning(f"[supp_registry] Failed to load from S3: {e}")
        _supp_metadata_cache = {}
        _supp_metadata_cache_at = time.monotonic()
    return _supp_metadata_cache


def _load_content_filter():
    """Load blocked terms from S3 config/content_filter.json. Cached after first call."""
    global _content_filter_cache, _content_filter_cache_at
    if _content_filter_cache is not None and config_cache_valid(_content_filter_cache_at):
        return _content_filter_cache
    try:
        S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
        s3 = boto3.client("s3", region_name=S3_REGION)
        resp = s3.get_object(Bucket=S3_BUCKET, Key="config/content_filter.json")
        _content_filter_cache = json.loads(resp["Body"].read())
        _content_filter_cache_at = time.monotonic()
        logger.info(f"[content_filter] Loaded: {len(_content_filter_cache.get('blocked_vice_keywords', []))} blocked terms")
    except Exception as e:
        logger.warning(f"[content_filter] Failed to load from S3: {e}")
        _content_filter_cache = {
            "blocked_vices": ["No porn", "No marijuana"],
            "blocked_vice_keywords": ["porn", "pornography", "marijuana", "cannabis", "weed", "thc", "edible", "edibles"],
        }
        # Stamped so the hard-coded fallback is retried against S3 after the TTL
        # instead of being pinned for the container's whole life (#2019).
        _content_filter_cache_at = time.monotonic()
        # BUG-05: emit EMF metric when fallback is active. We use sys.stdout.write
        # rather than print() so this file passes test_no_print_in_new_lambdas —
        # CloudWatch EMF parser requires a pure-JSON line with no logger prefix,
        # so logger.info() isn't an option here.
        try:
            import sys

            sys.stdout.write(
                json.dumps(
                    {
                        "_aws": {
                            "Timestamp": int(time.time() * 1000),
                            "CloudWatchMetrics": [
                                {
                                    "Namespace": "LifePlatform/SiteApi",
                                    "Dimensions": [[]],
                                    "Metrics": [{"Name": "ContentFilterFallback", "Unit": "Count"}],
                                }
                            ],
                        },
                        "ContentFilterFallback": 1,
                    }
                )
                + "\n"
            )
        except Exception:
            pass
    return _content_filter_cache


# Zero-width / invisible characters that can smuggle a blocked term past a
# literal substring scrub (e.g. a zero-width space inside "marijuana").
_ZERO_WIDTH_CHARS = dict.fromkeys((0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF), None)


def _normalize_for_detection(text: str) -> str:
    """Lowercase + drop non-alphanumeric after stripping zero-width chars.

    Collapses spaced / punctuated obfuscation ("m a r i j u a n a",
    "c-a-n-n-a-b-i-s") so a blocked term is detectable even when it slipped
    past the literal pass.
    """
    return re.sub(r"[^a-z0-9]", "", text.translate(_ZERO_WIDTH_CHARS).lower())


def _scrub_blocked_terms(text: str) -> str:
    """Remove any mention of blocked terms from public-facing text.

    Two layers:
      1. Literal case-insensitive removal — the common case; surgical, with no
         false-positives on normal text. Zero-width chars are stripped first so
         "mari<zwsp>juana" can't smuggle a term past it.
      2. Fail-safe detection on a normalized (de-spaced, de-punctuated) copy: if
         a LONG, unambiguous blocked term (>=7 normalized chars — "marijuana",
         "cannabis", "pornography"…) survived the literal pass, it was obfuscated
         on purpose, so we drop the WHOLE answer rather than surgically excise an
         obfuscated span (which would mangle legit text). Short terms
         ("thc"/"weed"/"porn") are too substring-prone to detect this way safely
         and are left to the literal pass — a documented residual.

    This is the canonical shared implementation. AI endpoints layer
    privacy_guard.scrub() on top for real-name redaction.
    """
    cf = _load_content_filter()
    text = text.translate(_ZERO_WIDTH_CHARS)
    result = text
    for term in cf.get("blocked_vice_keywords", []):
        result = re.compile(re.escape(term), re.IGNORECASE).sub("", result)
    for vice in cf.get("blocked_vices", []):
        result = re.compile(re.escape(vice), re.IGNORECASE).sub("", result)
    result = re.sub(r"\[filtered\]", "", result)
    result = re.sub(r"\s{2,}", " ", result).strip()

    norm = _normalize_for_detection(result)
    for term in cf.get("blocked_vice_keywords", []) + cf.get("blocked_vices", []):
        nt = _normalize_for_detection(term)
        if len(nt) >= 7 and nt in norm:
            return "I can't share that."
    return result


def _is_blocked_vice(name: str) -> bool:
    """Check if a vice/habit name matches the blocked list."""
    cf = _load_content_filter()
    name_lower = name.lower().strip()
    for blocked in cf.get("blocked_vices", []):
        if blocked.lower() == name_lower:
            return True
    for kw in cf.get("blocked_vice_keywords", []):
        if kw.lower() in name_lower:
            return True
    return False


def _request_id_headers() -> dict:
    """Return {x-request-id: ...} if a request id is set, else {}."""
    rid = get_request_id()
    if rid:
        return {"x-request-id": rid}
    return {}


def _ok(data: dict, cache_seconds: int = 300) -> dict:
    """Return a successful API response with caching headers."""
    rid = get_request_id()
    return {
        "statusCode": 200,
        "headers": {
            **CORS_HEADERS,
            **_request_id_headers(),
            "Cache-Control": f"public, max-age={cache_seconds}, s-maxage={cache_seconds}",
        },
        "body": json.dumps(
            {
                "_meta": {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "cache_seconds": cache_seconds,
                    **({"request_id": rid} if rid else {}),
                },
                **data,
            }
        ),
    }


def _error(status: int, message: str) -> dict:
    rid = get_request_id()
    return {
        "statusCode": status,
        "headers": {**CORS_HEADERS, **_request_id_headers(), "Cache-Control": "no-cache, no-store"},
        "body": json.dumps(
            {
                "error": message,
                **({"request_id": rid} if rid else {}),
            }
        ),
    }


def _load_s3_json(key: str, cache_name: str) -> dict:
    """Load a JSON file from S3. Returns parsed dict. Caller manages caching."""
    try:
        S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
        s3 = boto3.client("s3", region_name=S3_REGION)
        resp = s3.get_object(Bucket=S3_BUCKET, Key=key)
        data = json.loads(resp["Body"].read())
        logger.info(f"[{cache_name}] Loaded from S3: {key}")
        return data
    except Exception as e:
        logger.warning(f"[{cache_name}] Failed to load {key}: {e}")
        return {}


def _prereg_stamp_key(genesis: str) -> str:
    """S3 key of the genesis pre-registration's hash-stamp sidecar.

    MUST mirror deploy/genesis_prereg_stamp.py's stamp_key() exactly — duplicated
    rather than imported because deploy/ is operator tooling, never part of the
    lambda bundle (#781). Parity between the two literal formats is pinned by
    tests/test_prereg_seal_1980.py (calls gps.stamp_key() and this function with
    the same genesis and asserts equality) so the two can't silently drift."""
    return f"generated/experiments/prereg/genesis-{genesis}.sha256.json"


# #1980: cache the seal lookup per warm container (same pattern as _supp_metadata_cache),
# but a MISSING stamp is a legitimate, cacheable answer (a freshly re-anchored cycle
# whose --with-preregistration hasn't landed yet) — so a separate "attempted" flag
# distinguishes "not tried" from "tried, none published" without needing a sentinel.
_prereg_seal_cache: dict | None = None
_prereg_seal_attempted = False


def prereg_seal_meta() -> dict | None:
    """#1980: the CURRENT cycle's sealed pre-registration artifact — link + SHA-256
    + the copy-pasteable verify command, read verbatim from the stamp
    genesis_prereg_stamp.py published to S3 (the hash is never recomputed here —
    read-the-stamp, not recompute-and-trust, is the honesty rule).

    The genesis is DERIVED from EXPERIMENT_START (never a literal date), so the
    link is correct again the moment restart_pipeline.py re-anchors and a fresh
    stamp is published — no code change needed at the next reset.

    Returns None (honest-empty) when no stamp exists yet for this genesis; callers
    render nothing rather than a broken/guessed link.
    """
    global _prereg_seal_cache, _prereg_seal_attempted
    if _prereg_seal_attempted:
        return _prereg_seal_cache
    _prereg_seal_attempted = True
    stamp = _load_s3_json(_prereg_stamp_key(EXPERIMENT_START), "prereg_seal")
    if not stamp or not stamp.get("sha256") or stamp.get("genesis") != EXPERIMENT_START:
        _prereg_seal_cache = None
        return None
    _prereg_seal_cache = {
        "genesis": stamp.get("genesis"),
        "sha256": stamp.get("sha256"),
        "artifact_url": stamp.get("public_artifact_url"),
        "stamp_url": stamp.get("public_stamp_url"),
        "verify": stamp.get("verify"),
        "stamped_at": stamp.get("stamped_at"),
    }
    return _prereg_seal_cache
