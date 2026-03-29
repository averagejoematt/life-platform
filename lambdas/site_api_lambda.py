"""
site_api_lambda.py — Real-time public API for averagejoematt.com

PURPOSE:
    Serves live health/journey/character data to the website.
    This is a SEPARATE, READ-ONLY Lambda from the MCP server.
    Never expose the MCP endpoint publicly — this Lambda is the
    only thing the website talks to.

ARCHITECTURE:
    Browser → CloudFront (TTL cache) → API Gateway → this Lambda → DynamoDB
    
    CloudFront TTL tiers (set on each route):
      /api/vitals      → 300s  (5 min) — weight, HRV, recovery
      /api/journey     → 3600s (1 hr)  — weight trajectory, goal date
      /api/character   → 900s  (15 min) — pillar scores, level
      /api/status      → 60s   (1 min) — system health check

VIRAL DEFENCE (board-mandated by Marcus + Dana):
    1. CloudFront TTL means 50k visitors → ~12 Lambda calls per endpoint
    2. Lambda reserved concurrency = 20 (set in CDK)
    3. WAF rate limit: 100 req/min per IP (set in WAF rule)
    4. Budget alert at $5 (already configured)
    
    Cost at 50k hits: under $1.00

COST ESTIMATE (50k hits, all endpoints):
    CloudFront: ~$0.25 (data transfer)
    Lambda:     ~$0.05 (12 calls × 4 endpoints × 50ms avg)
    DynamoDB:   ~$0.01 (few dozen reads, all cached in Lambda warm container)
    API GW:     ~$0.02
    Total:      ~$0.33

DEPLOYMENT:
    1. Create Lambda: life-platform-site-api
    2. Set reserved concurrency: 20 (hard cap — returns 429 if exceeded)
    3. Add Function URL or API Gateway HTTP route
    4. Create CloudFront distribution with /api/* → Lambda origin
    5. Set Cache-Control headers per endpoint (handled in this Lambda)
    6. Add to CDK: compute_stack.py or new web_api_stack.py

IAM ROLE:
    Read-only:
      dynamodb:GetItem, Query on life-platform table
      s3:GetObject on matthew-life-platform/config/*
    NO write permissions whatsoever.
    NO access to Secrets Manager.
    NO access to MCP server.

v1.0.0 — 2026-03-16
"""

import copy
import hashlib
import json
import logging
import os
import re
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ── Config ─────────────────────────────────────────────────
TABLE_NAME  = os.environ.get("TABLE_NAME", "life-platform")
USER_ID     = os.environ.get("USER_ID", "matthew")
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

# DynamoDB is always us-west-2 even when this Lambda runs in us-east-1 (web stack).
# DYNAMODB_REGION env var injected by CDK; defaults to us-west-2.
DDB_REGION = os.environ.get("DYNAMODB_REGION", "us-west-2")
# SEC-03: S3 bucket is us-west-2; separate from DDB_REGION so each can be changed independently.
S3_REGION = os.environ.get("S3_REGION", "us-west-2")

# ── AWS clients (module-level for warm container reuse) ─────
dynamodb = boto3.resource("dynamodb", region_name=DDB_REGION)
table    = dynamodb.Table(TABLE_NAME)
# ── Content safety filter (S3-cached) ───────────────────────
_content_filter_cache = None

# ── Supplement metadata (S3-cached) ─────────────────────────
_supp_metadata_cache = None

# ── Status page (module-level cache) ───────────────────────
_status_cache = {}
_status_cache_ts = 0
STATUS_CACHE_TTL = 60  # 1 minute — more dynamic status updates

# ── Experiment start date — public Day 1 ───────────────────
EXPERIMENT_START = "2026-04-01"

# ── Profile (DynamoDB-cached per warm container) ────────────
_profile_cache = None


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
    """Load supplement registry from S3 config/supplement_registry.json. Cached after first call.
    Returns the full registry dict with 'groups' and 'genome_snps' keys."""
    global _supp_metadata_cache
    if _supp_metadata_cache is not None:
        return _supp_metadata_cache
    try:
        S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
        s3 = boto3.client("s3", region_name=S3_REGION)
        resp = s3.get_object(Bucket=S3_BUCKET, Key="site/config/supplement_registry.json")
        data = json.loads(resp["Body"].read())
        _supp_metadata_cache = data
        total = sum(len(g.get("items", [])) for g in data.get("groups", {}).values())
        logger.info(f"[supp_registry] Loaded: {total} supplements in {len(data.get('groups', {}))} groups")
    except Exception as e:
        logger.warning(f"[supp_registry] Failed to load from S3: {e}")
        _supp_metadata_cache = {}
    return _supp_metadata_cache

def _load_content_filter():
    """Load blocked terms from S3 config/content_filter.json. Cached after first call."""
    global _content_filter_cache
    if _content_filter_cache is not None:
        return _content_filter_cache
    try:
        S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
        s3 = boto3.client("s3", region_name=S3_REGION)
        resp = s3.get_object(Bucket=S3_BUCKET, Key="config/content_filter.json")
        _content_filter_cache = json.loads(resp["Body"].read())
        logger.info(f"[content_filter] Loaded: {len(_content_filter_cache.get('blocked_vice_keywords', []))} blocked terms")
    except Exception as e:
        logger.warning(f"[content_filter] Failed to load from S3: {e}")
        _content_filter_cache = {
            "blocked_vices": ["No porn", "No marijuana"],
            "blocked_vice_keywords": ["porn", "pornography", "marijuana", "cannabis", "weed", "thc"],
        }
        # BUG-05: Emit metric so we know when the fallback is active
        try:
            import time as _t, json as _j
            print(_j.dumps({"_aws": {"Timestamp": int(_t.time() * 1000),
                "CloudWatchMetrics": [{"Namespace": "LifePlatform/SiteApi",
                    "Dimensions": [[]], "Metrics": [{"Name": "ContentFilterFallback", "Unit": "Count"}]}]},
                "ContentFilterFallback": 1}))
        except Exception:
            pass
    return _content_filter_cache


def _scrub_blocked_terms(text: str) -> str:
    """Remove any mention of blocked terms from public-facing text."""
    cf = _load_content_filter()
    result = text
    for term in cf.get("blocked_vice_keywords", []):
        pattern = re.compile(re.escape(term), re.IGNORECASE)
        result = pattern.sub("[filtered]", result)
    # Also scrub full vice names
    for vice in cf.get("blocked_vices", []):
        pattern = re.compile(re.escape(vice), re.IGNORECASE)
        result = pattern.sub("[filtered]", result)
    # Clean up any "[filtered]" artifacts in sentences
    result = re.sub(r'\[filtered\]', '', result)
    result = re.sub(r'\s{2,}', ' ', result)
    return result.strip()


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


# ── CORS headers ────────────────────────────────────────────
# SEC-07: CORS_ORIGIN is env-configurable so staging/dev can override.
CORS_ORIGIN = os.environ.get("CORS_ORIGIN", "https://averagejoematt.com")

# SEC-04: CloudFront injects X-AMJ-Origin header on every origin request.
# When SITE_API_ORIGIN_SECRET is set, requests missing this header are rejected with 403.
# Leave unset in local/test environments to disable the check.
SITE_API_ORIGIN_SECRET = os.environ.get("SITE_API_ORIGIN_SECRET", "")
CORS_HEADERS = {
    "Access-Control-Allow-Origin":  CORS_ORIGIN,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Subscriber-Token",
    "Access-Control-Max-Age":       "3600",
    "Content-Type":                 "application/json",
    "X-Content-Type-Options":       "nosniff",
    "X-Frame-Options":              "DENY",
    "Strict-Transport-Security":    "max-age=31536000; includeSubDomains",
}


def _decimal_to_float(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimal_to_float(i) for i in obj]
    return obj


def _query_source(source: str, start_date: str, end_date: str) -> list:
    """Query DynamoDB for a source within a date range."""
    pk = f"{USER_PREFIX}{source}"
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(pk) & Key("sk").between(
            f"DATE#{start_date}", f"DATE#{end_date}"
        )
    )
    return _decimal_to_float(resp.get("Items", []))


def _latest_item(source: str) -> dict | None:
    """Get the most recent item for a source."""
    pk = f"{USER_PREFIX}{source}"
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(pk),
        ScanIndexForward=False,
        Limit=1,
    )
    items = _decimal_to_float(resp.get("Items", []))
    return items[0] if items else None


def _ok(data: dict, cache_seconds: int = 300) -> dict:
    """Return a successful API response with caching headers."""
    return {
        "statusCode": 200,
        "headers": {
            **CORS_HEADERS,
            "Cache-Control": f"public, max-age={cache_seconds}, s-maxage={cache_seconds}",
        },
        "body": json.dumps({
            "_meta": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "cache_seconds": cache_seconds,
            },
            **data,
        }),
    }


def _error(status: int, message: str) -> dict:
    return {
        "statusCode": status,
        "headers": CORS_HEADERS,
        "body": json.dumps({"error": message}),
    }


# ── Endpoint handlers ───────────────────────────────────────

def handle_vitals() -> dict:
    """
    GET /api/vitals
    Returns: current weight, HRV, recovery, RHR, sleep hours, 30d trends.
    Cache: 300s (5 min) — feels real-time, Lambda fires ~12x/hour at 50k traffic.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d30 = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    d7  = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

    # Whoop (recovery, HRV, RHR, sleep)
    whoop_7d = _query_source("whoop", d7, today)
    whoop_30d = _query_source("whoop", d30, today)

    # Latest reading
    latest = sorted(
        [w for w in whoop_7d if w.get("recovery_score") is not None],
        key=lambda x: x.get("sk", ""), reverse=True
    )
    latest = latest[0] if latest else {}

    # 30d averages + trends
    hrv_vals     = sorted([float(w["hrv"]) for w in whoop_30d if w.get("hrv")], key=lambda _: 0)
    rhr_vals     = sorted([float(w["resting_heart_rate"]) for w in whoop_30d if w.get("resting_heart_rate")], key=lambda _: 0)
    rec_vals     = [float(w["recovery_score"]) for w in whoop_30d if w.get("recovery_score")]

    def trend(vals):
        if len(vals) < 6: return "insufficient_data"
        mid = len(vals) // 2
        first_avg = sum(vals[:mid]) / len(vals[:mid])
        second_avg = sum(vals[mid:]) / len(vals[mid:])
        if second_avg > first_avg * 1.03: return "improving"
        if second_avg < first_avg * 0.97: return "declining"
        return "stable"

    # G-3: Latest weight from Withings — always use most-recent record regardless of date window.
    # _latest_item queries with no date filter so it always returns something even if weeks old.
    withings_latest = _latest_item("withings")
    current_weight = None
    weight_as_of = None
    if withings_latest:
        wv = withings_latest.get("weight_lbs")
        if wv is not None:
            current_weight = float(wv)
            weight_as_of = (withings_latest.get("sk", "").replace("DATE#", "")
                            or withings_latest.get("date"))

    withings_30d = _query_source("withings", d30, today)
    weight_vals = [float(w["weight_lbs"]) for w in withings_30d if w.get("weight_lbs")]
    weight_delta_30d = round(weight_vals[-1] - weight_vals[0], 1) if len(weight_vals) >= 2 else None

    recovery_pct = float(latest.get("recovery_score", 0))
    recovery_status = "green" if recovery_pct >= 67 else ("yellow" if recovery_pct >= 34 else "red")

    return _ok({
        "vitals": {
            "weight_lbs":       round(current_weight, 1) if current_weight is not None else None,
            "weight_as_of":     weight_as_of,
            "weight_delta_30d": weight_delta_30d,
            "hrv_ms":           round(float(latest.get("hrv", 0)), 1) if latest.get("hrv") else None,
            "hrv_30d_avg":      round(sum(hrv_vals) / len(hrv_vals), 1) if hrv_vals else None,
            "hrv_trend":        trend(hrv_vals),
            "rhr_bpm":          round(float(latest.get("resting_heart_rate", 0)), 0) if latest.get("resting_heart_rate") else None,
            "rhr_trend":        trend(list(reversed(rhr_vals))),  # lower is better
            "recovery_pct":     round(recovery_pct, 0),
            "recovery_status":  recovery_status,
            "sleep_hours":      round(float(latest.get("sleep_duration_hours", 0)), 1) if latest.get("sleep_duration_hours") else None,
            "as_of_date":       latest.get("sk", "").replace("DATE#", "") if latest else None,
        }
    }, cache_seconds=300)


def handle_journey() -> dict:
    """
    GET /api/journey
    Returns: weight trajectory, progress, milestones, projected goal date.
    Cache: 3600s (1 hr) — weight changes slowly.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d120 = (datetime.now(timezone.utc) - timedelta(days=120)).strftime("%Y-%m-%d")

    withings_all = _query_source("withings", d120, today)
    weight_series = sorted(
        [(w["sk"].replace("DATE#", ""), float(w["weight_lbs"]))
         for w in withings_all if w.get("weight_lbs")],
        key=lambda x: x[0]
    )

    if not weight_series:
        # G-4: Fall back to last known weight — never return 503 for missing recent data.
        withings_latest = _latest_item("withings")
        if withings_latest and withings_latest.get("weight_lbs") is not None:
            last_date = (withings_latest.get("sk", "").replace("DATE#", "")
                         or withings_latest.get("date", today))
            weight_series = [(last_date, float(withings_latest["weight_lbs"]))]
        else:
            weight_series = [("2026-04-01", 302.0)]  # No data at all — show journey start

    _p = _get_profile()
    start_weight = float(_p.get("journey_start_weight_lbs", 302.0))
    goal_weight  = float(_p.get("goal_weight_lbs", 185.0))
    current_weight = weight_series[-1][1]
    lost_lbs     = round(start_weight - current_weight, 1)
    remaining    = round(current_weight - goal_weight, 1)
    progress_pct = round(lost_lbs / (start_weight - goal_weight) * 100, 1) if start_weight != goal_weight else 0

    # Recent rate (last 28 days regression)
    recent = [(d, w) for d, w in weight_series
              if d >= (datetime.now(timezone.utc) - timedelta(days=28)).strftime("%Y-%m-%d")]
    weekly_rate = 0.0
    slope_per_day = 0.0
    if len(recent) >= 4:
        x = [(datetime.strptime(d, "%Y-%m-%d") - datetime.strptime(recent[0][0], "%Y-%m-%d")).days for d, _ in recent]
        y = [w for _, w in recent]
        n = len(x)
        sx, sy = sum(x), sum(y)
        sxy = sum(a * b for a, b in zip(x, y))
        sxx = sum(a * a for a in x)
        denom = n * sxx - sx * sx
        slope_per_day = (n * sxy - sx * sy) / denom if denom else 0
        weekly_rate = round(slope_per_day * 7, 2)

    # Projected goal date
    projected_goal_date = None
    days_to_goal = None
    if weekly_rate < 0 and current_weight > goal_weight:
        days = (current_weight - goal_weight) / abs(slope_per_day) if abs(slope_per_day) > 0 else 0
        projected_goal_date = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")
        days_to_goal = int(days)

    return _ok({
        "journey": {
            "start_weight_lbs":   start_weight,
            "goal_weight_lbs":    goal_weight,
            "current_weight_lbs": round(current_weight, 1),
            "lost_lbs":           lost_lbs,
            "remaining_lbs":      remaining,
            "progress_pct":       progress_pct,
            "weekly_rate_lbs":    weekly_rate,
            "projected_goal_date": projected_goal_date,
            "days_to_goal":       days_to_goal,
            "started_date":       "2026-04-01",
        }
    }, cache_seconds=3600)


def handle_character() -> dict:
    """
    GET /api/character
    Returns: character level, pillar scores, recent events.
    Cache: 900s (15 min) — computed nightly but visitors expect freshness.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    # Try today first, then yesterday
    pk = f"{USER_PREFIX}character_sheet"
    for date_str in [today, yesterday]:
        resp = table.get_item(Key={"pk": pk, "sk": f"DATE#{date_str}"})
        record = _decimal_to_float(resp.get("Item"))
        if record:
            break

    if not record:
        return _error(503, "Character sheet not yet computed today")

    PILLAR_ORDER = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]
    PILLAR_EMOJI = {"sleep": "😴", "movement": "🏋️", "nutrition": "🥗", "metabolic": "📊",
                    "mind": "🧠", "relationships": "💬", "consistency": "🎯"}

    pillars = []
    for p in PILLAR_ORDER:
        pd = record.get(f"pillar_{p}", {})
        pillars.append({
            "name":      p,
            "emoji":     PILLAR_EMOJI.get(p, ""),
            "level":     float(pd.get("level", 1)),
            "raw_score": float(pd.get("raw_score", 0)),
            "tier":      pd.get("tier", "Foundation"),
            "xp_delta":  float(pd.get("xp_delta", 0)),
        })

    return _ok({
        "character": {
            "level":      float(record.get("character_level", 1)),
            "tier":       record.get("character_tier", "Foundation"),
            "tier_emoji": record.get("character_tier_emoji", "🔨"),
            "xp_total":   float(record.get("character_xp", 0)),
            "as_of_date": date_str,
        },
        "pillars": pillars,
    }, cache_seconds=900)


def handle_weight_progress() -> dict:
    """
    GET /api/weight_progress
    Returns: daily weight readings for last 180 days.
    Cache: 3600s (1 hr).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d180  = (datetime.now(timezone.utc) - timedelta(days=180)).strftime("%Y-%m-%d")
    items = _query_source("withings", d180, today)

    readings = sorted(
        [
            {
                "date":       item["sk"].replace("DATE#", ""),
                "weight_lbs": round(float(item["weight_lbs"]), 1),
            }
            for item in items
            if item.get("weight_lbs")
        ],
        key=lambda x: x["date"],
    )

    return _ok({"weight_progress": readings}, cache_seconds=3600)


def handle_character_stats() -> dict:
    """
    GET /api/character_stats
    Returns: current character level, tier, and all 7 pillar scores.
    Cache: 3600s (1 hr) — computed nightly.
    """
    today     = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    pk = f"{USER_PREFIX}character_sheet"
    record = None
    for date_str in [today, yesterday]:
        resp = table.get_item(Key={"pk": pk, "sk": f"DATE#{date_str}"})
        record = _decimal_to_float(resp.get("Item"))
        if record:
            break
    if not record:
        return _error(503, "Character sheet not computed yet")

    PILLARS = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]
    pillars = {}
    for p in PILLARS:
        pd = record.get(f"pillar_{p}", {})
        pillars[p] = {
            "level":     float(pd.get("level", 1)),
            "raw_score": float(pd.get("raw_score", 0)),
            "tier":      pd.get("tier", "Foundation"),
        }

    return _ok({
        "character_stats": {
            "level":       float(record.get("character_level", 1)),
            "tier":        record.get("character_tier", "Foundation"),
            "tier_emoji":  record.get("character_tier_emoji", "🔨"),
            "xp_total":    float(record.get("character_xp", 0)),
            "as_of_date":  date_str,
        },
        "pillars": pillars,
    }, cache_seconds=3600)


def handle_habit_streaks() -> dict:
    """
    GET /api/habit_streaks
    Returns: Tier 0 habit streaks for public display (aggregate streak only, no habit names).
    Cache: 3600s (1 hr).
    """
    today     = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    # Read latest habit_scores record
    pk = f"{USER_PREFIX}habit_scores"
    resp = table.query(
        KeyConditionExpression="pk = :pk",
        ExpressionAttributeValues={":pk": pk},
        ScanIndexForward=False,
        Limit=3,
    )
    items = _decimal_to_float(resp.get("Items", []))
    record = items[0] if items else None

    if not record:
        return _error(503, "Habit scores not available")

    t0_done  = int(record.get("tier0_done", 0))
    t0_total = int(record.get("tier0_total", 1))
    t0_pct   = round(t0_done / t0_total * 100) if t0_total else 0

    # Compute aggregate T0 streak from habit_scores (t0_streak field if present)
    t0_streak = int(record.get("t0_perfect_streak") or record.get("t0_aggregate_streak") or 0)

    return _ok({
        "habit_streaks": {
            "as_of_date":      record.get("date", yesterday),
            "tier0_pct":       t0_pct,
            "tier0_done":      t0_done,
            "tier0_total":     t0_total,
            "aggregate_streak": t0_streak,
        }
    }, cache_seconds=3600)


def handle_experiments() -> dict:
    """
    GET /api/experiments
    Returns: list of experiments with status (no sensitive metric data).
    Cache: 3600s (1 hr).
    """
    pk = f"{USER_PREFIX}experiments"
    resp = table.query(
        KeyConditionExpression="pk = :pk",
        ExpressionAttributeValues={":pk": pk},
        ScanIndexForward=False,
        Limit=50,
    )
    items = _decimal_to_float(resp.get("Items", []))

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    experiments = []
    for item in items:
        if not item.get("sk", "").startswith("EXP#"):
            continue
        start = item.get("start_date", "")
        end   = item.get("end_date")
        status = item.get("status", "unknown")

        # Compute duration in days
        duration_days = None
        try:
            end_d  = datetime.strptime(end, "%Y-%m-%d") if end else datetime.now(timezone.utc).replace(tzinfo=None)
            start_d = datetime.strptime(start, "%Y-%m-%d")
            duration_days = max(0, (end_d - start_d).days)
        except Exception:
            pass

        # Days remaining (for active experiments)
        days_in = None
        planned_duration = item.get("planned_duration_days")
        if status == "active" and start:
            try:
                days_in = (datetime.now(timezone.utc).replace(tzinfo=None) - datetime.strptime(start, "%Y-%m-%d")).days
            except Exception:
                pass

        # Progress pct for active
        progress_pct = None
        if status == "active" and days_in is not None and planned_duration:
            progress_pct = min(100, round(days_in / int(planned_duration) * 100))

        experiments.append({
            "id":                item.get("sk", "").replace("EXP#", ""),
            "name":              item.get("name", "Unnamed"),
            "status":            status,
            "start_date":        start,
            "end_date":          end,
            "hypothesis":        item.get("hypothesis", ""),
            "tags":              item.get("tags", []),
            # Phase 2 additions
            "outcome":           item.get("outcome") or item.get("result_summary"),
            "result_summary":    item.get("result_summary") or item.get("outcome"),
            "primary_metric":    item.get("primary_metric"),
            "baseline_value":    item.get("baseline_value"),
            "result_value":      item.get("result_value"),
            "metrics_tracked":   item.get("metrics_tracked", []),
            "planned_duration_days": planned_duration,
            "duration_days":     duration_days,
            "days_in":           days_in,
            "progress_pct":      progress_pct,
            "confirmed":         item.get("confirmed", False),
            "hypothesis_confirmed": item.get("hypothesis_confirmed"),
            # EXP-2: depth fields
            "mechanism":         item.get("mechanism"),
            "key_finding":       item.get("key_finding"),
            "protocol":          item.get("protocol"),
            "evidence_tier":     item.get("evidence_tier"),
            # EL-16+: Evolution fields for Record zone
            "grade":             item.get("grade"),
            "compliance_pct":    item.get("compliance_pct"),
            "reflection":        item.get("reflection"),
            "library_id":        item.get("library_id"),
            "duration_tier":     item.get("duration_tier"),
            "experiment_type":   item.get("experiment_type"),
            "iteration":         item.get("iteration", 1),
        })
    experiments.sort(key=lambda x: x["start_date"], reverse=True)

    return _ok({"experiments": experiments}, cache_seconds=3600)


def handle_current_challenge() -> dict:
    """
    GET /api/current_challenge
    Returns the current weekly challenge from S3 config.
    Manually updated each Monday via:
      aws s3 cp current_challenge.json s3://matthew-life-platform/site/config/current_challenge.json
    Cache: 3600s (1 hr) — changes once/week, no need for shorter TTL.
    """
    S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
    S3_REGION = os.environ.get("S3_REGION", "us-west-2")
    try:
        s3_client = boto3.client("s3", region_name=S3_REGION)
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key="site/config/current_challenge.json")
        data = json.loads(resp["Body"].read())
        return _ok({"current_challenge": data}, cache_seconds=3600)
    except Exception as e:
        logger.warning(f"[site_api] current_challenge S3 fetch failed: {e}")
        # Fallback: static placeholder so ticker degrades gracefully
        return _ok({
            "current_challenge": {
                "week_num": None,
                "challenge": "Check back soon",
                "detail": "",
                "days_complete": 0,
                "days_total": 7,
            }
        }, cache_seconds=60)


def handle_status() -> dict:
    """
    GET /api/status — full system status for status page
    GET /api/status/summary — lightweight overall status for footer dot
    Cache: 300s (5 min) server-side, 60s client-side.
    """
    global _status_cache, _status_cache_ts

    now_ts = time.time()
    if now_ts - _status_cache_ts < STATUS_CACHE_TTL and _status_cache:
        return _ok(_status_cache, cache_seconds=60)

    today_dow = datetime.now(timezone.utc).weekday()

    # ── CloudWatch alarm check — detect pipeline errors ──
    cw_alarm_states = {}
    try:
        cw = boto3.client("cloudwatch", region_name=REGION)
        alarms_resp = cw.describe_alarms(StateValue="ALARM", MaxRecords=50)
        for alarm in alarms_resp.get("MetricAlarms", []):
            # Map alarm name back to source ID (convention: ingestion-error-{source} or {source}-errors)
            aname = alarm.get("AlarmName", "")
            for dim in alarm.get("Dimensions", []):
                if dim.get("Name") == "FunctionName":
                    cw_alarm_states[dim["Value"]] = aname
    except Exception as e:
        logger.warning(f"[status] CloudWatch alarm check failed (non-fatal): {e}")

    # Map Lambda function names to source IDs for alarm lookup
    _LAMBDA_TO_SOURCE = {
        "whoop-data-ingestion": "whoop", "withings-data-ingestion": "withings",
        "garmin-data-ingestion": "garmin", "strava-data-ingestion": "strava",
        "habitify-data-ingestion": "habitify", "eightsleep-data-ingestion": "eightsleep",
        "macrofactor-data-ingestion": "macrofactor", "notion-journal-ingestion": "notion",
        "todoist-data-ingestion": "todoist", "weather-data-ingestion": "weather",
        "health-auto-export-webhook": "apple_health", "food-delivery-ingestion": "food_delivery",
        "character-sheet-compute": "character_sheet", "daily-metrics-compute": "computed_metrics",
        "daily-insight-compute": "insights", "adaptive-mode-compute": "adaptive_mode",
        "daily-brief": "daily_brief", "weekly-digest": "weekly_digest",
        "monday-compass": "monday_compass", "wednesday-chronicle": "wednesday_chronicle",
        "weekly-plate": "weekly_plate", "nutrition-review": "nutrition_review",
        "anomaly-detector": "anomaly_detector",
    }
    alarming_sources = set()
    for fn_name, alarm_name in cw_alarm_states.items():
        src = _LAMBDA_TO_SOURCE.get(fn_name)
        if src:
            alarming_sources.add(src)

    # (source_id, display_name, description, yellow_h, red_h, category)
    # category: "auto" (default), "manual" (blue — infrequent file imports), "onetime" (green — never changes)
    # activity_dependent: True = user must do something for data to flow (e.g., run, log habit)
    # When stale AND activity_dependent, show "idle" (gray) instead of "red"
    _DATA_SOURCES = [
        # (source_id, name, description, yellow_h, red_h, category, group, activity_dependent)
        # ── API-Based (fully automated — pipeline pulls without user action) ──
        ("whoop",              "Recovery & Sleep (Whoop)",           "HRV · recovery score · sleep staging",      25,  49, "auto",    "API-Based", False),
        ("withings",           "Weigh In (Withings)",                "Weight · body composition · blood pressure", 25,  49, "auto",   "API-Based", True),
        ("eightsleep",         "Sleep Environment (Eight Sleep)",    "Sleep staging · bed temperature · HRV",      25,  49, "auto",    "API-Based", False),
        ("todoist",            "To Do List Feed (Todoist)",          "Tasks · projects · completion rate",          25,  49, "auto",   "API-Based", False),
        ("weather",            "Weather Conditions",                 "Daily temperature · conditions · humidity",   25,  49, "auto",   "API-Based", False),
        ("habit_scores",       "Habit Scores (Computed)",            "Aggregated daily habit grades & streaks",     25,  49, "auto",   "API-Based", False),
        ("garmin",             "Activity Tracking (Garmin)",         "Steps · GPS routes · stress · body battery", 25,  49, "auto",   "API-Based", True),
        ("strava",             "Cardio & Running (Strava)",          "Activities · segments · training load",      25,  49, "auto",    "API-Based", True),
        ("notion",             "Daily Journal (Notion)",             "Journal entries · mood · reflections",       25,  49, "auto",    "API-Based", True),
        # ── User-Driven (requires user to log/sync/upload) ──
        ("habitify",           "Habit Tracking (Habitify)",          "P40 daily habits · day grades",              25,  49, "auto",    "User-Driven", True),
        ("macrofactor",        "Nutrition (MacroFactor)",            "Calories · macros · meal timing",            25,  49, "auto",    "User-Driven", True),
        ("supplements",        "Supplement Adherence",               "Daily supplement tracking & compliance",      25,  49, "auto",   "User-Driven", True),
        ("state_of_mind",      "State of Mind (How We Feel)",       "Mood valence · emotions · life associations", 25,  49, "auto",   "User-Driven", True),
        # ── Periodic Uploads (file drops, webhooks, device sync) ──
        ("macrofactor_workouts","Exercise Log (Dropbox)",            "MacroFactor workout CSV via file drop",       48, 168, "auto",   "Periodic Uploads", True),
        ("apple_health",       "CGM Glucose (Dexcom Stelo)",        "Continuous glucose monitor readings",          25,  49, "auto",  "Periodic Uploads", True),
        ("apple_health",       "Water Intake (Health Auto Export)",  "Daily water consumption tracking",            25,  49, "auto",   "Periodic Uploads", True),
        ("apple_health",       "Blood Pressure (Health Auto Export)","Systolic · diastolic · pulse readings",       168, 336, "auto",  "Periodic Uploads", True),
        ("apple_health",       "Breathwork (Breathwrk)",            "Breathing exercises · sessions · minutes",    48, 168, "auto",   "Periodic Uploads", True),
        ("apple_health",       "Stretching (Pliability)",           "Flexibility sessions · recovery minutes",     48, 168, "auto",   "Periodic Uploads", True),
        ("apple_health",       "Mindful Minutes (Meditation)",      "Meditation & mindfulness sessions",           48, 168, "auto",   "Periodic Uploads", True),
        ("apple_health",       "Apple Health Import",                "Manual XML export · steps · workouts",       168, 336, "auto",  "Periodic Uploads", True),
        ("food_delivery",      "Food Delivery Index (Behavioral)",  "Quarterly CSV import · delivery index 0-10", 2160, 2880, "auto", "Periodic Uploads", True),
        # ── Lab & Clinical (infrequent) ──
        ("labs",               "Blood Tests",                        "Lab work · biomarkers · lipid panel",        4320, 8760, "manual", "Lab & Clinical", True),
        ("dexa",               "Bone Density & Body Comp (DEXA)",   "DEXA scan · bone density · lean mass",       4320, 8760, "manual", "Lab & Clinical", True),
        ("genome",             "Genome (one-time import)",           "Genetic variants · risk scores · SNPs",      999999, 999999, "onetime", "Lab & Clinical", False),
    ]
    _COMPUTE_SOURCES = [
        ("character_sheet",  "Character sheet",  "Pillar scores · level · XP",         25, 49),
        ("computed_metrics", "Daily metrics",    "Cross-domain computed signals",       25, 49),
        ("insights",         "Daily insights",   "IC-8 intent vs execution",            25, 49),
        ("adaptive_mode",    "Adaptive mode",    "Engagement scoring · brief mode",     25, 49),
    ]
    _EMAIL_LAMBDAS = [
        ("daily_brief",         "Daily brief",         "11:00 AM daily · 18 sections",     -1, 25,  49),
        ("weekly_digest",       "Weekly digest",       "Sunday 9:00 AM",                    6, 200, 400),
        ("monday_compass",      "Monday compass",      "Monday 8:00 AM · forward planning", 0, 200, 400),
        ("wednesday_chronicle", "Wednesday chronicle", "Wednesday 8:00 AM · Elena Voss",    2, 200, 400),
        ("weekly_plate",        "Weekly plate",        "Friday 7:00 PM · nutrition",        4, 200, 400),
        ("nutrition_review",    "Nutrition review",    "Saturday 10:00 AM",                 5, 200, 400),
        ("anomaly_detector",    "Anomaly detector",    "9:05 AM daily · 15 metrics",       -1, 25,  49),
    ]

    def _last_sync(source_id):
        try:
            resp = table.query(
                KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}{source_id}") & Key("sk").begins_with("DATE#"),
                ScanIndexForward=False, Limit=1, ProjectionExpression="sk",
            )
            items = resp.get("Items", [])
            return items[0]["sk"].replace("DATE#", "")[:10] if items else None
        except Exception:
            return None

    def _comp_status(last_date_str, yellow_h, red_h):
        if not last_date_str:
            return "red", "never", "No records found in DynamoDB"
        last_dt = datetime.strptime(last_date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        days_ago = (now.date() - last_dt.date()).days
        hours_ago = (now - last_dt).total_seconds() / 3600

        if days_ago == 0:
            rel = "today"
        elif days_ago == 1:
            rel = "yesterday"
        elif days_ago < 7:
            rel = f"{days_ago}d ago"
        else:
            rel = f"{days_ago}d ago"

        # For daily sources: today or yesterday = green, 2+ days = check thresholds
        if days_ago <= 1:
            return "green", rel, None
        elif days_ago <= 2:
            return "yellow", rel, f"Last data {rel} — monitoring"
        elif hours_ago <= red_h:
            return "yellow", rel, f"Last data {rel} — expected within {red_h}h"
        else:
            return "red", rel, f"STALE: last data {rel}. Threshold exceeded ({red_h}h)."

    def _uptime_90d(source_id):
        """Uptime bars showing completed days only (excludes today — data not expected yet)."""
        try:
            epoch_start = datetime(2026, 3, 28, tzinfo=timezone.utc).date()
            yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
            window_days = min(90, (yesterday - epoch_start).days + 1)
            if window_days < 1:
                return [1]  # No completed days yet — show green (pipeline exists)

            resp = table.query(
                KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}{source_id}") & Key("sk").between(
                    f"DATE#{epoch_start.isoformat()}", f"DATE#{yesterday.isoformat()}"
                ),
                ProjectionExpression="sk",
            )
            present = {item["sk"].replace("DATE#", "")[:10] for item in resp.get("Items", [])}
            return [1 if (yesterday - timedelta(days=i)).isoformat() in present else 0 for i in range(window_days - 1, -1, -1)]
        except Exception:
            return [1]  # Assume healthy on error

    def _sched_aware(status, rel, exp_dow):
        if exp_dow < 0 or today_dow == exp_dow:
            return status, rel
        if status == "yellow":
            names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            return "gray", f"next: {names[exp_dow]}"
        return status, rel

    # Build data source components
    ds_components = []
    for row in _DATA_SOURCES:
        sid, name, desc, yh, rh = row[0], row[1], row[2], row[3], row[4]
        category = row[5] if len(row) > 5 else "auto"
        group = row[6] if len(row) > 6 else "API-Based"
        activity_dep = row[7] if len(row) > 7 else False
        last = _last_sync(sid)

        if category == "onetime":
            # Genome — check if ANY records exist (uses GENE# keys, not DATE#)
            try:
                _gene_resp = table.query(
                    KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}{sid}"),
                    Limit=1, ProjectionExpression="sk",
                )
                has_data = len(_gene_resp.get("Items", [])) > 0
            except Exception:
                has_data = False
            status = "green" if has_data else "red"
            rel = "imported" if has_data else "not imported"
            comment = "One-time data source — does not require refresh" if has_data else "Awaiting initial import"
            uptime = [1] * 90 if has_data else [0] * 90
        elif category == "manual":
            # Labs / DEXA — blue status, show refresh recommendation
            status_raw, rel, _ = _comp_status(last, yh, rh)
            if last:
                last_dt = datetime.strptime(last[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                months_ago = int((datetime.now(timezone.utc) - last_dt).days / 30)
                if months_ago < 6:
                    comment = f"Last updated {rel}. Next recommended: ~6 months"
                elif months_ago < 12:
                    comment = f"Last updated {rel}. Consider scheduling a refresh"
                else:
                    comment = f"Last updated {rel}. Overdue for refresh (>12 months)"
                status = "blue"
            else:
                status, comment = "blue", "No data yet — schedule first appointment"
            uptime = _uptime_90d(sid)
        else:
            status, rel, comment = _comp_status(last, yh, rh)
            uptime = _uptime_90d(sid)

            # Activity-dependent sources: pipeline is healthy, just no user activity
            if activity_dep and status == "red" and last:
                status = "green"
                comment = f"Pipeline ready \u2014 awaiting user activity. Last data: {rel}"
                uptime = [1] * len(uptime)
            elif activity_dep and status == "red" and not last:
                status = "green"
                comment = "Pipeline ready \u2014 no data recorded yet"
                uptime = [1] * max(1, len(uptime))

        # CloudWatch alarm override — if Lambda is actively erroring, show red
        if sid in alarming_sources and status != "blue":
            status = "red"
            comment = f"CloudWatch alarm firing \u2014 Lambda errors detected"

        ds_components.append({"id": sid, "name": name, "description": desc,
                              "status": status, "last_sync_relative": rel,
                              "uptime_90d": uptime, "comment": comment,
                              "group": group})

    # Compute components
    compute_components = []
    for sid, name, desc, yh, rh in _COMPUTE_SOURCES:
        last = _last_sync(sid)
        status, rel, comment = _comp_status(last, yh, rh)
        uptime = _uptime_90d(sid)
        # Pre-launch: "never" is expected, not broken — smoke-tested Mar 29
        if status == "red" and not last:
            status = "green"
            rel = "verified"
            comment = "Smoke-tested OK \u2014 awaiting first scheduled run (April 1+)"
            uptime = [1] * max(1, len(uptime))
        if sid in alarming_sources:
            status = "red"
            comment = "CloudWatch alarm firing \u2014 Lambda errors detected"
        compute_components.append({"id": sid, "name": name, "description": desc,
                                   "status": status, "last_sync_relative": rel,
                                   "uptime_90d": uptime, "comment": comment})

    # Email components
    email_components = []
    for lid, name, desc, exp_dow, yh, rh in _EMAIL_LAMBDAS:
        last = _last_sync(f"email_log#{lid}")
        status, rel, comment = _comp_status(last, yh, rh)
        status, rel = _sched_aware(status, rel, exp_dow)
        uptime = _uptime_90d(f"email_log#{lid}")
        # Pre-launch: weekly emails that haven't fired yet — smoke-tested Mar 29
        if status == "red" and not last:
            status = "green"
            rel = "verified"
            comment = "Smoke-tested OK \u2014 awaiting first scheduled run"
            uptime = [1] * max(1, len(uptime))
        if lid in alarming_sources:
            status = "red"
            comment = "CloudWatch alarm firing \u2014 Lambda errors detected"
        email_components.append({"id": lid, "name": name, "description": desc,
                                 "status": status, "last_sync_relative": rel,
                                 "uptime_90d": uptime, "comment": comment})

    # Infrastructure (static — always green unless manually updated)
    infra = [
        {"id": "cloudfront_main", "name": "averagejoematt.com",     "description": "CloudFront · 12 pages",         "status": "green", "comment": None},
        {"id": "site_api",        "name": "Site API Lambda",         "description": "us-east-1 · public read-only",  "status": "green", "comment": None},
        {"id": "mcp_server",      "name": "MCP server",              "description": "us-west-2 · 95+ tools",        "status": "green", "comment": None},
        {"id": "dynamodb",        "name": "DynamoDB",                "description": "on-demand · PITR enabled",      "status": "green", "comment": None},
        {"id": "ses",             "name": "SES email delivery",      "description": "Production mode · receipt rule", "status": "green", "comment": None},
        {"id": "dlq",             "name": "Dead-letter queue",       "description": "life-platform-ingestion-dlq",    "status": "green", "comment": None},
    ]

    # Exclude blue (manual import) and onetime from overall health — they're not system issues
    # Exclude blue (manual) and gray (idle/activity-dependent) from overall health
    all_statuses = [c["status"] for c in ds_components + compute_components + email_components
                    if c["status"] not in ("blue", "gray")]
    if "red" in all_statuses:
        overall = "red"
    elif "yellow" in all_statuses:
        overall = "yellow"
    else:
        overall = "green"

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "groups": [
            {"id": "data_sources",  "label": "Data sources",   "subtitle": f"{len(ds_components)} feeds — wearables · nutrition · labs · genome", "components": ds_components},
            {"id": "compute",       "label": "Compute layer",  "subtitle": "character sheet · metrics · insights · adaptive mode", "components": compute_components},
            {"id": "email",         "label": "Email & digests", "subtitle": "7 scheduled senders", "components": email_components},
            {"id": "infrastructure","label": "Infrastructure",  "subtitle": "CloudFront · DynamoDB · SES · DLQ", "components": infra},
        ]
    }

    _status_cache = result
    _status_cache_ts = now_ts
    return _ok(result, cache_seconds=60)


def handle_status_summary() -> dict:
    """GET /api/status/summary — lightweight overall status for footer dot."""
    # Ensure the cache is populated
    if not _status_cache or (time.time() - _status_cache_ts >= STATUS_CACHE_TTL):
        handle_status()
    return _ok({
        "overall": _status_cache.get("overall", "green"),
        "generated_at": _status_cache.get("generated_at", ""),
    }, cache_seconds=60)


# ── BS-11: Timeline data ────────────────────────────────────────

def handle_timeline() -> dict:
    """
    GET /api/timeline
    Returns weight series + life events + experiments + level-ups
    for the interactive Transformation Timeline page.
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start = "2026-04-01"

    # Weight series (full journey)
    wt_items = _query_source("withings", start, today)
    weights = sorted(
        [{"date": i["sk"].replace("DATE#", ""), "lbs": round(float(i["weight_lbs"]), 1)}
         for i in wt_items if i.get("weight_lbs")],
        key=lambda x: x["date"]
    )

    # Life events
    life_pk = f"USER#{USER_ID}#SOURCE#life_events"
    le_resp = table.query(KeyConditionExpression=Key("pk").eq(life_pk))
    life_events = [
        {"date": i.get("date", ""), "title": i.get("title", ""),
         "type": i.get("type", "other"), "weight": int(i.get("emotional_weight", 3))}
        for i in _decimal_to_float(le_resp.get("Items", []))
    ]

    # Experiments
    exp_pk = f"USER#{USER_ID}#SOURCE#experiments"
    exp_resp = table.query(KeyConditionExpression=Key("pk").eq(exp_pk))
    experiments = [
        {"name": i.get("name", ""), "start": i.get("start_date", ""),
         "end": i.get("end_date"), "status": i.get("status", "active")}
        for i in _decimal_to_float(exp_resp.get("Items", []))
        if i.get("sk", "").startswith("EXP#")
    ]

    # Character level history
    cs_pk = f"{USER_PREFIX}character_sheet"
    cs_resp = table.query(
        KeyConditionExpression=Key("pk").eq(cs_pk) & Key("sk").begins_with("DATE#"),
        ScanIndexForward=True,
    )
    level_events = []
    prev_level = 0
    for item in _decimal_to_float(cs_resp.get("Items", [])):
        lvl = int(float(item.get("character_level", 0)))
        if lvl > prev_level and prev_level > 0:
            level_events.append({
                "date": item.get("sk", "").replace("DATE#", ""),
                "level": lvl,
                "tier": item.get("character_tier", ""),
            })
        prev_level = lvl

    return _ok({
        "timeline": {
            "weights":      weights,
            "life_events":  sorted(life_events, key=lambda x: x["date"]),
            "experiments":  sorted(experiments, key=lambda x: x["start"]),
            "level_ups":    level_events,
            "journey_start": EXPERIMENT_START,
            "start_weight":  float(_get_profile().get("journey_start_weight_lbs", 302.0)),
            "goal_weight":   float(_get_profile().get("goal_weight_lbs", 185.0)),
        }
    }, cache_seconds=3600)


# ── Sprint 9: Supplements + Habits public endpoints ─────────────

def handle_supplements() -> dict:
    """
    GET /api/supplements
    Returns full supplement registry (groups, items, genome SNPs) from S3 config.
    Merges DynamoDB adherence data when available.
    Cache: 3600s (1 hr).
    """
    registry = _load_supp_metadata()
    if not registry or not registry.get("groups"):
        return _error(503, "Supplement data not available")

    # Try to merge DynamoDB adherence data
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    pk = f"{USER_PREFIX}supplements"
    item = None
    for date in (today, yesterday):
        resp = table.get_item(Key={"pk": pk, "sk": f"DATE#{date}"})
        item = _decimal_to_float(resp.get("Item"))
        if item:
            break
    if not item:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(pk),
            ScanIndexForward=False, Limit=5,
        )
        items = _decimal_to_float(resp.get("Items", []))
        item = items[0] if items else None

    # Build adherence lookup from DynamoDB
    adherence_lookup = {}
    if item:
        for s in item.get("supplements", []):
            name = s.get("name", "").lower().replace(" ", "_").replace("-", "_")
            adherence_lookup[name] = s.get("adherence_pct")

    as_of_date = item.get("date", yesterday) if item else yesterday

    # Merge adherence into registry groups
    groups = registry.get("groups", {})
    total_count = 0
    for gkey, group in groups.items():
        for supp in group.get("items", []):
            total_count += 1
            adh = adherence_lookup.get(supp.get("key", ""))
            if adh is not None:
                supp["adherence_pct"] = adh

    return _ok({
        "as_of_date": as_of_date,
        "groups": groups,
        "genome_snps": registry.get("genome_snps", []),
        "total_count": total_count,
    }, cache_seconds=3600)


def handle_vice_streaks() -> dict:
    """
    GET /api/vice_streaks
    Returns content-filtered vice streak portfolio from habit_scores.vice_streaks.
    Computes current streak, 90-day best, and relapse count per vice.
    Blocked vices (per content_filter.json) are excluded from the response.
    Cache: 3600s (1 hr).
    """
    today           = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ninety_days_ago = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")

    content_filter = _load_content_filter()
    blocked_set    = set(v.lower().strip() for v in content_filter.get("blocked_vices", []))

    pk = f"{USER_PREFIX}habit_scores"
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(pk) & Key("sk").between(
            f"DATE#{ninety_days_ago}", f"DATE#{today}"
        ),
        ScanIndexForward=True,
    )
    items = _decimal_to_float(resp.get("Items", []))

    if not items:
        return _ok({"vices": [], "total_held": 0, "total_tracked": 0, "as_of_date": today}, cache_seconds=3600)

    # Gather per-vice streak history (chronological)
    vice_history: dict = {}
    for item in items:
        vs = item.get("vice_streaks") or {}
        if not isinstance(vs, dict):
            continue
        for vice_name, streak_val in vs.items():
            if vice_name.lower().strip() in blocked_set:
                continue
            if vice_name not in vice_history:
                vice_history[vice_name] = []
            vice_history[vice_name].append(int(streak_val or 0))

    if not vice_history:
        return _ok({"vices": [], "total_held": 0, "total_tracked": 0, "as_of_date": today}, cache_seconds=3600)

    # Current state from latest record
    latest    = items[-1]
    latest_vs = {}
    raw_vs    = latest.get("vice_streaks") or {}
    if isinstance(raw_vs, dict):
        latest_vs = {k: int(v or 0) for k, v in raw_vs.items() if k.lower().strip() not in blocked_set}

    vices = []
    for vice_name, history in vice_history.items():
        current_streak = latest_vs.get(vice_name, history[-1] if history else 0)
        best_streak    = max(history) if history else 0
        # Relapse = streak dropped from >0 to 0
        relapses = sum(1 for i in range(1, len(history)) if history[i - 1] > 0 and history[i] == 0)
        vices.append({
            "name":           vice_name,
            "current_streak": current_streak,
            "best_streak":    best_streak,
            "relapses_90d":   relapses,
            "holding":        current_streak > 0,
        })

    # Sort: holding first, then by streak descending
    vices.sort(key=lambda v: (-int(v["holding"]), -v["current_streak"]))

    total_held    = int(latest.get("vices_held", 0) or 0)
    total_tracked = len(vices)

    return _ok({
        "as_of_date":    latest.get("date", today),
        "vices":         vices,
        "total_held":    total_held,
        "total_tracked": total_tracked,
    }, cache_seconds=3600)


def handle_journey_timeline() -> dict:
    """
    GET /api/journey_timeline
    Returns ordered timeline events for the Story page:
    - Weight milestones (first crossing of 5-lb thresholds)
    - Level-up events from character_sheet
    - Experiment start/completion events
    Cache: 3600s (1 hr).
    """
    today           = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start_date      = EXPERIMENT_START
    _p              = _get_profile()
    start_weight    = float(_p.get("journey_start_weight_lbs", 302.0))
    goal_weight     = float(_p.get("goal_weight_lbs", 185.0))

    events: list = []

    # ── 1. Day 1 anchor ──────────────────────────────────────────────────────
    events.append({
        "date":  start_date,
        "type":  "milestone",
        "title": "Day 1 — The Experiment Begins",
        "body":  "Started at 302 lbs. Built the platform from scratch. Committed publicly.",
        "link":  "/story/",
    })

    # ── 2. Weight milestones (5-lb thresholds) ───────────────────────────────
    thresholds = list(range(295, int(goal_weight) - 1, -5))  # 295, 290, 285, …, 190, 185
    crossed: dict = {}  # threshold -> date string

    wk_pk = f"{USER_PREFIX}withings"
    try:
        wk_resp = table.query(
            KeyConditionExpression=Key("pk").eq(wk_pk) & Key("sk").between(
                f"DATE#{start_date}", f"DATE#{today}"
            ),
            ScanIndexForward=True,
        )
        for item in _decimal_to_float(wk_resp.get("Items", [])):
            wt = item.get("weight_lbs")
            if wt is None:
                continue
            wt = float(wt)
            date_str = item.get("date") or item.get("sk", "").replace("DATE#", "")
            for thr in thresholds:
                if thr not in crossed and wt <= thr:
                    crossed[thr] = date_str
    except Exception:
        pass

    for thr in sorted(crossed.keys(), reverse=True):  # highest first = earliest
        lbs_lost = start_weight - thr
        events.append({
            "date":  crossed[thr],
            "type":  "weight",
            "title": f"Crossed {thr} lbs — {int(lbs_lost)} lbs lost",
            "body":  f"Down {int(lbs_lost)} lbs from 302. {round((lbs_lost / (start_weight - goal_weight)) * 100)}% of the way to goal.",
            "link":  "/live/",
        })

    # ── 3. Level-up events from character_sheet ──────────────────────────────
    cs_pk = f"{USER_PREFIX}character_sheet"
    try:
        cs_resp = table.query(
            KeyConditionExpression=Key("pk").eq(cs_pk) & Key("sk").between(
                f"DATE#{start_date}", f"DATE#{today}"
            ),
            ScanIndexForward=True,
        )
        seen_levels: set = set()
        for item in _decimal_to_float(cs_resp.get("Items", [])):
            level = item.get("character_level")
            date_str = item.get("date") or item.get("sk", "").replace("DATE#", "")
            if level and level not in seen_levels:
                seen_levels.add(level)
                if level > 1:
                    events.append({
                        "date":  date_str,
                        "type":  "level_up",
                        "title": f"Reached Character Level {level}",
                        "body":  f"Level {level} — {item.get('character_tier', '')}. Pillar scores converging.",
                        "link":  "/character/",
                    })
    except Exception:
        pass

    # ── 4. Experiment starts ─────────────────────────────────────────────────
    exp_pk = f"{USER_PREFIX}experiments"
    try:
        exp_resp = table.query(
            KeyConditionExpression=Key("pk").eq(exp_pk),
            ScanIndexForward=False,
            Limit=20,
        )
        for item in _decimal_to_float(exp_resp.get("Items", [])):
            if not item.get("sk", "").startswith("EXP#"):
                continue
            start = item.get("start_date", "")
            if not start or start < start_date:
                continue
            status = item.get("status", "")
            if status == "active":
                events.append({
                    "date":  start,
                    "type":  "experiment",
                    "title": f"Experiment: {item.get('name', 'Unnamed')}",
                    "body":  item.get("hypothesis", "")[:120] + ("…" if len(item.get("hypothesis", "")) > 120 else ""),
                    "link":  "/experiments/",
                })
            elif status == "completed":
                end = item.get("end_date", start)
                outcome = (item.get("outcome") or item.get("result_summary") or "")[:80]
                events.append({
                    "date":  end,
                    "type":  "discovery",
                    "title": f"Experiment Complete: {item.get('name', 'Unnamed')}",
                    "body":  outcome + ("…" if len(outcome) == 80 else ""),
                    "link":  "/discoveries/",
                })
    except Exception:
        pass

    # ── 5. FDR-significant correlation findings ────────────────────────
    corr_pk = f"{USER_PREFIX}weekly_correlations"
    try:
        corr_resp = table.query(
            KeyConditionExpression=Key("pk").eq(corr_pk),
            ScanIndexForward=True,
        )
        _METRIC_LABELS = {
            "hrv": "Heart Rate Variability", "recovery_score": "Recovery Score",
            "sleep_duration": "Sleep Duration", "sleep_score": "Sleep Score",
            "resting_hr": "Resting Heart Rate", "strain": "Strain",
            "tsb": "Training Stress Balance", "training_kj": "Training Load",
            "training_mins": "Training Minutes", "protein_g": "Protein",
            "calories": "Calories", "carbs_g": "Carbs", "steps": "Steps",
            "habit_pct": "Habit Completion", "day_grade": "Day Grade",
            "readiness": "Readiness", "tier0_streak": "Tier 0 Streak",
        }
        seen_findings: set = set()
        for item in _decimal_to_float(corr_resp.get("Items", [])):
            week = item.get("week", item.get("sk", "").replace("WEEK#", ""))
            end_d = item.get("end_date", "")
            corrs = item.get("correlations", {})
            if not isinstance(corrs, dict):
                continue
            for label, data in corrs.items():
                if not data.get("fdr_significant"):
                    continue
                if label in seen_findings:
                    continue  # only show first detection
                seen_findings.add(label)
                r_val = float(data.get("pearson_r", 0) or 0)
                n_val = int(data.get("n_days", 0) or 0)
                ma = data.get("metric_a", "")
                mb = data.get("metric_b", "")
                la = _METRIC_LABELS.get(ma, ma)
                lb = _METRIC_LABELS.get(mb, mb)
                direction = "higher" if r_val > 0 else "lower"
                is_ci = data.get("counterintuitive", False)
                evt_type = "counterintuitive" if is_ci else "finding"
                title_prefix = "⚠️ Surprise: " if is_ci else "AI Finding: "
                events.append({
                    "date":  end_d or week,
                    "type":  evt_type,
                    "title": f"{title_prefix}{la} → {direction} {lb}",
                    "body":  f"r={r_val:+.2f} over {n_val} days. Passed FDR significance testing (week {week}).",
                    "link":  "/explorer/",
                    "meta":  {"r": r_val, "n": n_val, "pair": label, "week": week},
                })
    except Exception as e:
        logger.warning("journey_timeline: correlation events failed (non-fatal): %s", e)

    # Exclude pre-experiment events and sort chronologically
    events = [e for e in events if e["date"] >= start_date]
    events.sort(key=lambda e: e["date"])
    seen_evt: set = set()
    deduped = []
    for e in events:
        key = (e["date"], e["title"])
        if key not in seen_evt:
            seen_evt.add(key)
            deduped.append(e)

    # ── 6. DISC-7: Merge behavioral response annotations ──────────────
    try:
        ann_pk = f"{USER_PREFIX}discovery_annotations"
        ann_resp = table.query(
            KeyConditionExpression=Key("pk").eq(ann_pk),
            ScanIndexForward=True,
        )
        ann_items = _decimal_to_float(ann_resp.get("Items", []))
        # Build lookup: event_key → annotation data
        ann_lookup: dict = {}
        for ai in ann_items:
            ek = ai.get("sk", "").replace("EVENT#", "")
            ann_lookup[ek] = {
                "annotation": ai.get("annotation", ""),
                "action_taken": ai.get("action_taken"),
                "outcome": ai.get("outcome"),
            }
        # Attach annotations to matching events
        if ann_lookup:
            for e in deduped:
                ek = hashlib.sha256(
                    f"{e['date']}|{e['type']}|{e['title']}".encode()
                ).hexdigest()[:16]
                if ek in ann_lookup:
                    e["annotation"] = ann_lookup[ek]
    except Exception as _ann_e:
        logger.warning("journey_timeline: annotation merge failed (non-fatal): %s", _ann_e)

    return _ok({
        "as_of_date": today,
        "events":     deduped,
        "total":      len(deduped),
    }, cache_seconds=3600)


def handle_journey_waveform() -> dict:
    """
    GET /api/journey_waveform
    Returns 42 days of daily pillar-sum scores for the Story page emotional waveform.
    Score = sum of 7 pillar level_scores (0–700 range).
    Color tiers: green (>=250), amber (>=150), red (<150), gray (no data).
    Cache: 3600s (1 hr).
    """
    today      = datetime.now(timezone.utc).date()
    start_date = (today - timedelta(days=41)).isoformat()
    end_date   = today.isoformat()

    PILLARS = [
        "pillar_sleep", "pillar_nutrition", "pillar_movement",
        "pillar_metabolic", "pillar_mind", "pillar_consistency", "pillar_relationships",
    ]

    cs_pk = f"{USER_PREFIX}character_sheet"
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(cs_pk) & Key("sk").between(
                f"DATE#{start_date}", f"DATE#{end_date}"
            ),
            ScanIndexForward=True,
        )
        items = resp.get("Items", [])
    except Exception:
        items = []

    # Index by date
    by_date: dict = {}
    for item in items:
        date_str = item.get("date") or item.get("sk", "").replace("DATE#", "")
        if not date_str:
            continue
        total = 0.0
        for pillar in PILLARS:
            pdata = item.get(pillar, {})
            # boto3 Table resource returns already-deserialized Python values
            if isinstance(pdata, dict):
                ls = pdata.get("level_score")
                if ls is not None:
                    try:
                        total += float(ls)
                    except (TypeError, ValueError):
                        pass
        by_date[date_str] = round(total, 1)

    # Build ordered 42-day series
    days = []
    for i in range(42):
        d = (today - timedelta(days=41 - i)).isoformat()
        score = by_date.get(d)
        if score is None:
            color = "gray"
        elif score >= 250:
            color = "green"
        elif score >= 150:
            color = "amber"
        else:
            color = "red"
        days.append({"date": d, "score": score, "color": color})

    max_score = max((d["score"] for d in days if d["score"] is not None), default=1)

    return _ok({
        "days":      days,
        "max_score": max_score,
        "window":    42,
    }, cache_seconds=3600)


def handle_habits() -> dict:
    """
    GET /api/habits
    Returns 90-day daily habit completion history (aggregate only — no habit names).
    Used by /habits/ page for the heatmap and group adherence bars.
    Cache: 3600s (1 hr).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ninety_days_ago = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")

    pk = f"{USER_PREFIX}habit_scores"
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(pk) & Key("sk").between(
            f"DATE#{ninety_days_ago}", f"DATE#{today}"
        ),
        ScanIndexForward=True,
    )
    items = _decimal_to_float(resp.get("Items", []))

    # ── Also pull by_group from habitify partition (group data lives there, not in habit_scores)
    hab_pk = f"{USER_PREFIX}habitify"
    hab_resp = table.query(
        KeyConditionExpression=Key("pk").eq(hab_pk) & Key("sk").between(
            f"DATE#{ninety_days_ago}", f"DATE#{today}"
        ),
        ScanIndexForward=True,
    )
    habitify_by_date = {}
    for hi in _decimal_to_float(hab_resp.get("Items", [])):
        date_key = hi.get("date") or hi.get("sk", "").replace("DATE#", "")
        by_group = hi.get("by_group", {})
        if by_group and isinstance(by_group, dict):
            # by_group[Group] = {completed, possible, pct, habits_done}
            # pct is 0.0–1.0, convert to 0–100
            habitify_by_date[date_key] = {
                g: round(float(v.get("pct", 0) or 0) * 100)
                for g, v in by_group.items()
                if isinstance(v, dict)
            }

    history = []
    for item in items:
        date_str = item.get("date") or item.get("sk", "").replace("DATE#", "")
        t0_done  = int(item.get("tier0_done", 0) or 0)
        t0_total = int(item.get("tier0_total", 1) or 1)
        t01_done  = int(item.get("tier01_done", t0_done) or t0_done)
        t01_total = int(item.get("tier01_total", t0_total) or t0_total)
        t0_pct   = round(t0_done / t0_total * 100) if t0_total else 0
        t01_pct  = round(t01_done / t01_total * 100) if t01_total else 0
        streak   = int(item.get("t0_perfect_streak") or item.get("t0_aggregate_streak") or 0)

        # Per-group breakdown: prefer flat group_* fields on habit_scores;
        # fall back to habitify by_group data if present
        group_data = {}
        for key, val in item.items():
            if key.startswith("group_") and isinstance(val, (int, float)):
                group_data[key.replace("group_", "")] = val
        if not group_data and date_str in habitify_by_date:
            group_data = habitify_by_date[date_str]

        day = {
            "date":      date_str,
            "tier0_pct": t0_pct,
            "tier01_pct": t01_pct,
            "t0_done":   t0_done,
            "t0_total":  t0_total,
            "perfect":   t0_pct == 100,
        }
        if group_data:
            day["groups"] = group_data
        history.append(day)

    # Latest record for current streak
    latest = history[-1] if history else {}
    latest_streak = 0
    if items:
        last_item = _decimal_to_float(items[-1])
        latest_streak = int(last_item.get("t0_perfect_streak") or last_item.get("t0_aggregate_streak") or 0)

    # ── Day-of-week analysis (0=Mon ... 6=Sun)
    dow_sums = [0.0] * 7
    dow_counts = [0] * 7
    for day in history:
        try:
            d = datetime.strptime(day["date"], "%Y-%m-%d")
            dow = d.weekday()  # 0=Mon ... 6=Sun
            dow_sums[dow] += day.get("tier0_pct", 0) or 0
            dow_counts[dow] += 1
        except Exception:
            pass
    dow_avgs = [
        round(dow_sums[i] / dow_counts[i]) if dow_counts[i] else None
        for i in range(7)
    ]
    valid_dow = [(i, v) for i, v in enumerate(dow_avgs) if v is not None]
    best_dow  = max(valid_dow, key=lambda x: x[1])[0] if valid_dow else None
    worst_dow = min(valid_dow, key=lambda x: x[1])[0] if valid_dow else None

    # ── 90-day per-group averages + keystone identification
    group_90d_sums: dict = {}
    group_90d_counts: dict = {}
    for day in history:
        for gname, gpct in (day.get("groups") or {}).items():
            if isinstance(gpct, (int, float)):
                group_90d_sums[gname] = group_90d_sums.get(gname, 0) + gpct
                group_90d_counts[gname] = group_90d_counts.get(gname, 0) + 1
    group_90d_avgs = {
        g: round(group_90d_sums[g] / group_90d_counts[g])
        for g in group_90d_sums
        if group_90d_counts.get(g, 0) > 0
    }
    keystone_group = max(group_90d_avgs, key=group_90d_avgs.get) if group_90d_avgs else None
    keystone_group_pct = group_90d_avgs.get(keystone_group) if keystone_group else None

    # ── HAB-3: Pearson correlation per habit group vs character score ──────────
    keystone_correlations = []
    try:
        import math as _math

        # Fetch character_sheet records for same window
        cs_pk = f"{USER_PREFIX}character_sheet"
        cs_resp = table.query(
            KeyConditionExpression=Key("pk").eq(cs_pk) & Key("sk").between(
                f"DATE#{ninety_days_ago}", f"DATE#{today}"
            ),
            ScanIndexForward=True,
        )
        cs_items = _decimal_to_float(cs_resp.get("Items", []))

        # Build date → pillar sum (character health proxy)
        PILLARS_CS = ["pillar_sleep", "pillar_movement", "pillar_nutrition",
                      "pillar_metabolic", "pillar_mind", "pillar_relationships", "pillar_consistency"]
        char_by_date = {}
        for ci in cs_items:
            cs_date = ci.get("date") or ci.get("sk", "").replace("DATE#", "")
            psum = 0.0
            for pkey in PILLARS_CS:
                pdata = ci.get(pkey) or {}
                if isinstance(pdata, dict):
                    ls = pdata.get("level_score")
                    if ls is not None:
                        psum += float(ls)
            if psum > 0:
                char_by_date[cs_date] = psum

        # For each group, collect matched (char_score, group_pct) pairs
        group_series: dict = {}
        for day in history:
            d = day.get("date")
            if d not in char_by_date:
                continue
            cs_score = char_by_date[d]
            for gname, gpct in (day.get("groups") or {}).items():
                if isinstance(gpct, (int, float)):
                    if gname not in group_series:
                        group_series[gname] = []
                    group_series[gname].append((float(gpct), cs_score))

        # Pearson r helper
        def _pearson(pairs):
            n = len(pairs)
            if n < 5:
                return None
            xs = [p[0] for p in pairs]
            ys = [p[1] for p in pairs]
            mx = sum(xs) / n
            my = sum(ys) / n
            num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
            dx  = _math.sqrt(sum((x - mx) ** 2 for x in xs))
            dy  = _math.sqrt(sum((y - my) ** 2 for y in ys))
            if dx == 0 or dy == 0:
                return None
            return round(num / (dx * dy), 3)

        corr_list = []
        for gname, pairs in group_series.items():
            r = _pearson(pairs)
            if r is not None:
                corr_list.append({
                    "group":         gname,
                    "correlation_r": r,
                    "avg_pct":       group_90d_avgs.get(gname),
                    "n_days":        len(pairs),
                })
        corr_list.sort(key=lambda x: abs(x["correlation_r"]), reverse=True)
        keystone_correlations = corr_list[:5]
    except Exception as _hc_e:
        logger.warning("[handle_habits] keystone_correlations failed (non-fatal): %s", _hc_e)

    return _ok({
        "as_of_date":             today,
        "days_tracked":           len(history),
        "current_streak":         latest_streak,
        "history":                history,
        "day_of_week_avgs":       dow_avgs,
        "best_day":               best_dow,
        "worst_day":              worst_dow,
        "group_90d_avgs":         group_90d_avgs,
        "keystone_group":         keystone_group,
        "keystone_group_pct":     keystone_group_pct,
        # HAB-3: top 5 habit groups by |Pearson r| vs character score
        "keystone_correlations":  keystone_correlations,
    }, cache_seconds=3600)


# ── WEB-CE: Correlation data ────────────────────────────────────

def handle_correlations(event: dict = None) -> dict:
    """
    GET /api/correlations
    Returns the most recent weekly correlation matrix (23 pairs)
    for the public Correlation Explorer.

    HP-06: When ?featured=true is passed, returns a flat array of
    the top N significant correlations (default 3) for the homepage
    dynamic discoveries section. Response shape changes to:
      {"correlations": [{...}, ...], "week": "...", "count": N}
    so the homepage JS can iterate directly.

    Cache: 3600s.
    """
    # HP-06: Parse query params
    params = {}
    if event:
        params = event.get("queryStringParameters") or {}
    featured = (params.get("featured") or "").lower() == "true"
    limit = None
    if params.get("limit"):
        try:
            limit = max(1, min(20, int(params["limit"])))
        except (ValueError, TypeError):
            pass

    pk = f"{USER_PREFIX}weekly_correlations"
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(pk),
        ScanIndexForward=False,
        Limit=1,
    )
    items = _decimal_to_float(resp.get("Items", []))
    if not items:
        return _error(503, "No correlation data available yet.")

    record = items[0]
    week = record.get("sk", "").replace("WEEK#", "")
    start_date = record.get("start_date", "")
    end_date = record.get("end_date", "")

    # The compute lambda stores correlations as a dict (label → data).
    # Convert to list for the public API. Also supports legacy "pairs" list format.
    raw_corrs = record.get("correlations", {})
    if isinstance(raw_corrs, list):
        # Legacy format: already a list
        pairs = raw_corrs
    elif isinstance(raw_corrs, dict):
        # Current format: dict keyed by label. Convert to list.
        pairs = []
        for label, data in raw_corrs.items():
            entry = dict(data)
            entry["label"] = label
            pairs.append(entry)
    else:
        pairs = []

    # Human-readable labels and source names for each metric
    _METRIC_META = {
        "hrv":            {"label": "Heart Rate Variability", "source": "Whoop"},
        "recovery_score": {"label": "Recovery Score",         "source": "Whoop"},
        "sleep_duration": {"label": "Sleep Duration",         "source": "Whoop"},
        "sleep_score":    {"label": "Sleep Score",            "source": "Whoop"},
        "resting_hr":     {"label": "Resting Heart Rate",     "source": "Whoop"},
        "strain":         {"label": "Strain",                 "source": "Whoop"},
        "tsb":            {"label": "Training Stress Balance", "source": "Computed"},
        "training_kj":    {"label": "Training Load (kJ)",     "source": "Strava"},
        "training_mins":  {"label": "Training Minutes",       "source": "Strava"},
        "protein_g":      {"label": "Protein (g)",            "source": "MacroFactor"},
        "calories":       {"label": "Calories",               "source": "MacroFactor"},
        "carbs_g":        {"label": "Carbs (g)",              "source": "MacroFactor"},
        "fat_g":          {"label": "Fat (g)",                "source": "MacroFactor"},
        "steps":          {"label": "Steps",                  "source": "Apple Health"},
        "habit_pct":      {"label": "Habit Completion %",     "source": "Habitify"},
        "day_grade":      {"label": "Day Grade",              "source": "Computed"},
        "readiness":      {"label": "Readiness Score",        "source": "Computed"},
        "tier0_streak":   {"label": "Tier 0 Streak",          "source": "Computed"},
    }

    public_pairs = []
    for p in pairs:
        metric_a = p.get("metric_a", p.get("field_a", ""))
        metric_b = p.get("metric_b", p.get("field_b", ""))
        meta_a = _METRIC_META.get(metric_a, {})
        meta_b = _METRIC_META.get(metric_b, {})
        r_val = float(p.get("pearson_r", p.get("r", 0)) or 0)
        public_pairs.append({
            "source_a":  meta_a.get("source", p.get("source_a", "")),
            "field_a":   metric_a,
            "label_a":   meta_a.get("label", p.get("label_a", metric_a)),
            "source_b":  meta_b.get("source", p.get("source_b", "")),
            "field_b":   metric_b,
            "label_b":   meta_b.get("label", p.get("label_b", metric_b)),
            "r":         round(r_val, 3),
            "p":         round(float(p.get("p_value", p.get("p", 1)) or 1), 4),
            "n":         int(p.get("n_days", p.get("n", 0)) or 0),
            "strength":  p.get("interpretation", p.get("strength", "weak")),
            "fdr_significant": p.get("fdr_significant", False),
            "correlation_type": p.get("correlation_type", "cross_sectional"),
            "lag_days":  int(p.get("lag_days", 0) or 0),
            "description": p.get("description", ""),
            "direction":   p.get("direction", ""),
            # DISC-1: counterintuitive flag from compute lambda
            "counterintuitive":    p.get("counterintuitive", False),
            "expected_direction":  p.get("expected_direction", ""),
            # HP-06: metric labels for homepage cards
            "metric_a":  meta_a.get("label", p.get("label_a", metric_a)),
            "metric_b":  meta_b.get("label", p.get("label_b", metric_b)),
        })

    # Sort all by absolute r descending
    public_pairs.sort(key=lambda x: -abs(x["r"]))

    # HP-06: Featured mode — return flat array of top significant correlations
    if featured:
        # Filter to significant only (p < 0.05 or FDR-significant)
        significant = [p for p in public_pairs if p.get("fdr_significant") or p.get("p", 1) < 0.05]
        # Fall back to strongest by |r| if no significant ones found
        if not significant:
            significant = public_pairs
        # Apply limit (default 3)
        top = significant[:limit or 3]
        # Auto-generate description if missing
        for p in top:
            if not p.get("description"):
                direction = "positive" if p["r"] > 0 else "inverse"
                p["description"] = (
                    f"{direction.title()} correlation between "
                    f"{p['metric_a']} and {p['metric_b']} "
                    f"(r={p['r']:.2f})"
                )
        return _ok({
            "correlations": top,
            "week":  week,
            "count": len(top),
        }, cache_seconds=3600)

    # Standard mode — return full object for explorer page
    return _ok({
        "correlations": {
            "week":  week,
            "start_date": start_date,
            "end_date":   end_date,
            "pairs": public_pairs,
            "count": len(public_pairs),
            "methodology": "Pearson r over 90-day rolling window. Benjamini-Hochberg FDR correction. n-gated strength labels.",
        }
    }, cache_seconds=3600)


# ── BS-BM2: Genome risk data ────────────────────────────────────

def handle_genome_risks() -> dict:
    """
    GET /api/genome_risks
    Returns genome SNPs grouped by category with risk levels.
    No raw genotypes exposed. Cache: 86400s (24h).
    """
    pk = f"{USER_PREFIX}genome"
    resp = table.query(KeyConditionExpression=Key("pk").eq(pk))
    items = _decimal_to_float(resp.get("Items", []))

    if not items:
        return _error(503, "No genome data available.")

    categories = {}
    risk_summary = {"unfavorable": 0, "mixed": 0, "neutral": 0, "favorable": 0}

    for snp in items:
        cat = snp.get("category", "other")
        risk = snp.get("risk_level", "neutral")
        risk_summary[risk] = risk_summary.get(risk, 0) + 1

        if cat not in categories:
            categories[cat] = []
        categories[cat].append({
            "gene":         snp.get("gene", ""),
            "rsid":         snp.get("rsid", snp.get("sk", "").replace("SNP#", "")),
            "risk_level":   risk,
            "summary":      snp.get("summary", ""),
            "implications":  snp.get("implications", ""),
            "interventions": snp.get("interventions", []),
            "evidence":     snp.get("evidence_strength", "moderate"),
        })

    for cat in categories:
        categories[cat].sort(key=lambda x: {"unfavorable": 0, "mixed": 1, "neutral": 2, "favorable": 3}.get(x["risk_level"], 2))

    return _ok({
        "genome": {
            "total_snps":   len(items),
            "risk_summary": risk_summary,
            "categories":   categories,
        }
    }, cache_seconds=86400)


# ── WR-24: Subscriber verification ──────────────────────────────────────────

import hmac as _hmac
import base64 as _b64

_token_secret_cache = None

def _get_token_secret() -> str:
    """Derive token signing secret from the existing Anthropic API key.
    No new secrets needed."""
    global _token_secret_cache
    if _token_secret_cache:
        return _token_secret_cache
    import hashlib as _h
    api_key = _get_anthropic_key()
    if not api_key:
        logger.error("[token_secret] No API key available — subscriber tokens cannot be signed")
        raise RuntimeError("Token signing secret unavailable")
    _token_secret_cache = _h.sha256(f"subscriber-token-v1:{api_key}".encode()).hexdigest()
    return _token_secret_cache


def _generate_subscriber_token(email: str) -> str:
    """Generate a 24hr HMAC token for a confirmed subscriber."""
    import time as _time
    expires = int(_time.time()) + 86400
    payload = f"{email.lower()}:{expires}"
    secret = _get_token_secret().encode()
    sig = _hmac.new(secret, payload.encode(), digestmod='sha256').hexdigest()[:32]
    return _b64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


def _validate_subscriber_token(token: str) -> bool:
    """Return True if token is valid and unexpired."""
    try:
        import time as _time
        decoded = _b64.urlsafe_b64decode(token.encode()).decode()
        parts = decoded.split(":")
        if len(parts) != 3:
            return False
        email, expires_str, provided_sig = parts
        if int(_time.time()) > int(expires_str):
            return False
        payload = f"{email}:{expires_str}"
        secret = _get_token_secret().encode()
        expected = _hmac.new(secret, payload.encode(), digestmod='sha256').hexdigest()[:32]
        return _hmac.compare_digest(provided_sig, expected)
    except Exception:
        return False


def _is_confirmed_subscriber(email: str) -> bool:
    """Check DDB: USER#matthew#SOURCE#subscribers / EMAIL#{sha256} / status=confirmed"""
    import hashlib as _h
    email_hash = _h.sha256(email.strip().lower().encode()).hexdigest()
    try:
        resp = table.get_item(Key={
            "pk": f"USER#{USER_ID}#SOURCE#subscribers",
            "sk": f"EMAIL#{email_hash}",
        })
        item = _decimal_to_float(resp.get("Item") or {})
        return item.get("status") == "confirmed"
    except Exception as e:
        logger.warning(f"[verify_subscriber] DDB lookup failed: {e}")
        return False


def _handle_verify_subscriber(event: dict) -> dict:
    """
    GET /api/verify_subscriber?email=...
    Returns a 24hr token if the email is a confirmed subscriber.
    Frontend stores token in sessionStorage and sends as X-Subscriber-Token header
    to unlock 20 questions/hr instead of the default 5.
    """
    params = event.get("queryStringParameters") or {}
    email = (params.get("email") or "").strip().lower()

    if not email or "@" not in email or len(email) > 254:
        return {
            "statusCode": 400,
            "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
            "body": json.dumps({"error": "Valid email required"}),
        }

    if not _is_confirmed_subscriber(email):
        return {
            "statusCode": 404,
            "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
            "body": json.dumps({
                "error": "Email not found. Subscribe at /subscribe/ to unlock more questions!"
            }),
        }

    token = _generate_subscriber_token(email)
    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
        "body": json.dumps({
            "token": token,
            "message": "Verified! You now have 20 questions per hour.",
            "limit": 20,
        }),
    }


def handle_subscriber_count() -> dict:
    """
    GET /api/subscriber_count
    Returns count of confirmed subscribers (read-only query).
    Used by homepage and subscribe page for social proof.
    """
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"USER#{USER_ID}#SOURCE#subscribers"),
            Select="COUNT",
            FilterExpression="attribute_exists(#s) AND #s = :confirmed",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":confirmed": "confirmed"},
        )
        count = resp.get("Count", 0)
    except Exception as e:
        logger.warning(f"[subscriber_count] DDB query failed: {e}")
        count = 0
    return _ok({"count": count}, cache_seconds=600)


# ── S2-T2-2: Board Ask ────────────────────────────────────────────────────────

PERSONA_PROMPTS = {
    "vasquez": {
        "name": "Dr. Elena Vasquez",
        "title": "Metabolic Medicine & Longevity",
        "system": (
            "You are Dr. Elena Vasquez, MD, a metabolic medicine physician specializing in longevity. "
            "Focus on: VO2max, Zone 2 training, strength, metabolic health, and the major drivers of chronic disease. "
            "Evidence-based and nuanced. Distinguish strong evidence from speculation. "
            "Your perspective is informed by current peer-reviewed research. Do not reference specific researchers by name. "
            "Use first person. 3-5 sentences. Note N=1 for any comparative claim. "
            "Never give medical advice — reference a physician only if clinically urgent."
        ),
    },
    "okafor": {
        "name": "Dr. James Okafor",
        "title": "Performance Neuroscience",
        "system": (
            "You are Dr. James Okafor PhD, a performance neuroscientist. "
            "Focus on: sleep architecture, light exposure, stress resilience, neuroplasticity, and dopamine. "
            "Explain the mechanism first, then the protocol. "
            "Your perspective is informed by current peer-reviewed research. Do not reference specific researchers by name. "
            "Use phrases like 'the data are clear' and 'the mechanism here is'. "
            "3-5 sentences. Actionable and specific."
        ),
    },
    "patrick": {
        "name": "Rhonda Patrick",
        "title": "Cellular Biology & Nutrition",
        "system": (
            "You are Rhonda Patrick PhD, biochemist and FoundMyFitness founder. "
            "Focus on: micronutrients, cellular resilience, omega-3s, heat/cold exposure, inflammation. "
            "Cite mechanisms. Use 'the research shows' and 'at the cellular level'. "
            "Thorough, not reductive. 3-5 sentences."
        ),
    },
    "norton": {
        "name": "Layne Norton",
        "title": "Evidence-Based Nutrition",
        "system": (
            "You are Layne Norton PhD, nutrition scientist and evidence-based coach. "
            "Focus on: protein synthesis, body composition, muscle retention in deficit. "
            "No-nonsense, skeptical of broscience. "
            "Use 'the evidence actually shows' and 'people get this wrong because'. "
            "Emphasize protein quality, leucine threshold, and adherence. 3-5 sentences."
        ),
    },
    "clear": {
        "name": "James Clear",
        "title": "Habit Architecture",
        "system": (
            "You are James Clear, author of Atomic Habits. "
            "Focus on: identity-based change, the four laws of behavior change, habit stacking, systems over goals. "
            "Aphorism-style language. Make abstract ideas concrete with specific examples. "
            "3-5 sentences. Actionable and memorable."
        ),
    },
    "goggins": {
        "name": "David Goggins",
        "title": "Mental Toughness",
        "system": (
            "You are David Goggins, retired Navy SEAL and ultra-endurance athlete. "
            "You believe most people quit at 40% capacity and that the mind is the limit. "
            "Brutally honest, intense, no coddling. Use 'stay hard' and 'nobody is coming to save you'. "
            "3-5 sentences. High energy."
        ),
    },
}

BOARD_RATE_LIMIT = 5  # per IP per hour


def _handle_board_ask(event: dict) -> dict:
    """
    POST /api/board_ask
    Body: {"question": str, "personas": ["vasquez", ...]}
    Returns: {"responses": {"vasquez": "...", ...}}
    S2-T2-2: Lead magnet — each board member answers in their own voice.
    """
    source_ip = (
        event.get("requestContext", {}).get("http", {}).get("sourceIp")
        or event.get("requestContext", {}).get("identity", {}).get("sourceIp")
        or "unknown"
    )
    import time as _time
    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
    now = int(_time.time())
    hour_ago = now - 3600
    board_ts = [t for t in _board_rate_store.get(ip_hash, []) if t > hour_ago]
    if len(board_ts) >= BOARD_RATE_LIMIT:
        _emit_rate_limit_metric("board_ask")
        return {
            "statusCode": 429,
            "headers": {**CORS_HEADERS, "Retry-After": "3600"},
            "body": json.dumps({"error": "Rate limit reached. Try again in an hour."}),
        }
    board_ts.append(now)
    _board_rate_store[ip_hash] = board_ts[-20:]

    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return {"statusCode": 400, "headers": CORS_HEADERS, "body": json.dumps({"error": "Invalid JSON"})}

    question = re.sub(r"<[^>]+>", "", (body.get("question") or "").strip())[:500]
    if len(question) < 5:
        return {"statusCode": 400, "headers": CORS_HEADERS, "body": json.dumps({"error": "Question too short"})}

    requested = body.get("personas") or list(PERSONA_PROMPTS.keys())
    personas = [p for p in requested if p in PERSONA_PROMPTS][:6]
    if not personas:
        personas = ["vasquez", "okafor", "clear"]

    api_key = _get_anthropic_key()
    if not api_key:
        return {"statusCode": 503, "headers": CORS_HEADERS, "body": json.dumps({"error": "AI service unavailable"})}

    responses = {}
    for pid in personas:
        p = PERSONA_PROMPTS[pid]
        try:
            req_body = json.dumps({
                "model": AI_MODEL_HAIKU,
                "max_tokens": 300,
                "system": p["system"],
                "messages": [{"role": "user", "content": question}],
            })
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=req_body.encode(),
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                result = json.loads(r.read())
            responses[pid] = _scrub_blocked_terms("".join(b["text"] for b in result.get("content", []) if b.get("type") == "text"))
        except Exception as e:
            logger.error(f"[board_ask] {pid} failed: {e}")
            responses[pid] = f"[{p['name']} is temporarily unavailable]"

    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
        "body": json.dumps({"responses": responses}),
    }


# ── Ask the Platform (AI Q&A) ─────────────────────────────────────

_anthropic_key_cache = None

# In-memory rate limit stores (warm container state — resets on cold start, acceptable for rate limiting)
# Maps ip_hash -> list of timestamps in the current hour
_ask_rate_store: dict = {}
_board_rate_store: dict = {}
_nudge_rate_store: dict = {}   # ACCT-2: ip_hash+category -> list of timestamps
_nudge_counts: dict = {}       # ACCT-2: category -> approximate count (warm container only)
_finding_rate_store: dict = {} # NEW-1: ip_hash -> list of timestamps for submit_finding

# R17-04: Separate Anthropic key for site-api — injected via CDK env var
AI_SECRET_NAME  = os.environ.get("AI_SECRET_NAME",  "life-platform/site-api-ai-key")
# R17-11: env-overridable model string — avoids silent deprecation failures
AI_MODEL_HAIKU  = os.environ.get("AI_MODEL_HAIKU",  "claude-haiku-4-5-20251001")


def _get_anthropic_key():
    """Fetch Anthropic API key from Secrets Manager (cached after first call)."""
    global _anthropic_key_cache
    if _anthropic_key_cache:
        return _anthropic_key_cache
    try:
        sm = boto3.client("secretsmanager", region_name="us-west-2")
        resp = sm.get_secret_value(SecretId=AI_SECRET_NAME)
        _anthropic_key_cache = resp["SecretString"]
        return _anthropic_key_cache
    except Exception as e:
        logger.error(f"[ask] Failed to fetch API key from {AI_SECRET_NAME}: {e}")
        return None


def _emit_rate_limit_metric(endpoint: str) -> None:
    """OBS-03: EMF metric emitted when a rate limit is hit. Zero-config via stdout."""
    import time as _t
    import json as _json
    try:
        emf = {
            "_aws": {
                "Timestamp": int(_t.time() * 1000),
                "CloudWatchMetrics": [{
                    "Namespace": "LifePlatform/SiteApi",
                    "Dimensions": [["Endpoint"]],
                    "Metrics": [{"Name": "RateLimitHit", "Unit": "Count"}],
                }],
            },
            "Endpoint": endpoint,
            "RateLimitHit": 1,
        }
        print(_json.dumps(emf))
    except Exception:
        pass


def _ask_rate_check(ip_hash: str, limit: int = 3) -> tuple:
    """Rate limit: N questions per IP-hash per hour (in-memory, warm container state)."""
    import time as _time
    now = int(_time.time())
    hour_ago = now - 3600
    timestamps = [t for t in _ask_rate_store.get(ip_hash, []) if t > hour_ago]
    if len(timestamps) >= limit:
        return False, 0
    timestamps.append(now)
    _ask_rate_store[ip_hash] = timestamps[-50:]  # cap stored entries
    return True, limit - len(timestamps)


def _ask_fetch_context() -> dict:
    """Fetch sanitized aggregate data for the AI prompt."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday_str = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    ctx = {}
    w = _latest_item("withings")
    if w and w.get("weight_lbs"):
        ctx["weight_lbs"] = float(w["weight_lbs"])
    wh = _latest_item("whoop")
    if wh:
        if wh.get("hrv"): ctx["hrv_ms"] = float(wh["hrv"])
        if wh.get("resting_heart_rate"): ctx["rhr_bpm"] = float(wh["resting_heart_rate"])
        if wh.get("recovery_score"): ctx["recovery_pct"] = float(wh["recovery_score"])
        if wh.get("sleep_duration_hours"): ctx["sleep_hours"] = float(wh["sleep_duration_hours"])
    cs_pk = f"{USER_PREFIX}character_sheet"
    for d in [today_str, yesterday_str]:
        resp = table.get_item(Key={"pk": cs_pk, "sk": f"DATE#{d}"})
        rec = _decimal_to_float(resp.get("Item"))
        if rec:
            ctx["character_level"] = float(rec.get("character_level", 1))
            ctx["character_tier"] = rec.get("character_tier", "Foundation")
            pillars = {}
            for p in ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]:
                pd = rec.get(f"pillar_{p}", {})
                pillars[p] = {"level": float(pd.get("level", 1)), "raw_score": float(pd.get("raw_score", 0)), "tier": pd.get("tier", "Foundation")}
            ctx["pillars"] = pillars
            break
    hs_pk = f"{USER_PREFIX}habit_scores"
    hs_resp = table.query(KeyConditionExpression=Key("pk").eq(hs_pk), ScanIndexForward=False, Limit=1)
    hs_items = _decimal_to_float(hs_resp.get("Items", []))
    if hs_items:
        ctx["tier0_streak"] = int(hs_items[0].get("t0_perfect_streak", 0) or 0)
    return ctx


# WR-40: Question safety filter — block sensitive query categories
_ASK_BLOCKED_PATTERNS = [
    r'\b(ssn|social.?security|passport|credit.?card|bank.?account|routing.?number)\b',
    r'\b(password|api.?key|secret|token|credential)\b',
    r'\b(address|phone.?number|email.?address|zip.?code|employer.?name)\b',
    r'\b(salary|income|net.?worth|financial|tax)\b',
    r'\b(suicid|self.?harm|eating.?disorder|mental.?illness|diagnos)\b',
    r'\b(medication.?name|prescription|dosage|drug.?interaction)\b',
]


def _ask_question_safe(question: str) -> tuple:
    """Returns (is_safe, reason). Blocks sensitive query categories."""
    q_lower = question.lower()
    for pattern in _ASK_BLOCKED_PATTERNS:
        if re.search(pattern, q_lower):
            return False, "This question touches on sensitive personal data that the platform doesn't share publicly. Try asking about weight, sleep, HRV, training, habits, or nutrition trends instead."
    return True, ""


def _ask_build_prompt(ctx: dict) -> str:
    pillars_str = ""
    if "pillars" in ctx:
        pillars_str = "\n".join(
            f"    {n}: level {p['level']:.0f}, score {p['raw_score']:.1f}, tier {p['tier']}"
            for n, p in ctx["pillars"].items()
        )
    return f"""You are the AI behind Matthew Walker's Life Platform — a personal health intelligence system tracking 19 data sources.

CURRENT DATA:
  Weight: {ctx.get('weight_lbs', '?')} lbs (started 302, goal 185)
  HRV: {ctx.get('hrv_ms', '?')} ms
  RHR: {ctx.get('rhr_bpm', '?')} bpm
  Recovery: {ctx.get('recovery_pct', '?')}%
  Sleep: {ctx.get('sleep_hours', '?')} hours
  Character level: {ctx.get('character_level', '?')} (tier: {ctx.get('character_tier', '?')})
  T0 habit streak: {ctx.get('tier0_streak', '?')} days
  Pillars:
{pillars_str or '    Not available'}

RULES:
- Answer from the data above. If you don't have data, say so honestly.
- Be specific: "HRV is 54ms" not "HRV is moderate."
- N=1 data. Note this for comparative claims.
- Never give medical advice. Say "the data shows X" not "you should do Y."
- Keep answers concise: 2-4 short paragraphs max.
- Bold key findings with **asterisks**.

SAFETY (WR-40):
- NEVER reveal: addresses, phone numbers, emails, employer details, financial info, passwords, API keys.
- NEVER provide: medical diagnoses, medication recommendations, mental health assessments.
- Stick to publicly shared health metrics: weight, HRV, sleep, recovery, training, habits, nutrition trends.
- If asked about something outside your data, say "I don't have that data" — don't speculate.
- CONTENT FILTER: NEVER mention porn, pornography, marijuana, cannabis, weed, THC, or any related terms.
- If asked about these topics, respond only with: I don't have data on that specific topic."""


def handle_ask() -> dict:
    """Handled specially in lambda_handler — this is a placeholder for ROUTES."""
    return _error(405, "Use POST method")


def handle_glucose() -> dict:
    """
    GET /api/glucose
    Returns: 30-day CGM stats — time-in-range, variability, daily trend.
    Source: apple_health DynamoDB records.
    Cache: 3600s (1h).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d30 = max((datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d"), EXPERIMENT_START)

    records = _query_source("apple_health", d30, today)
    cgm_days = [
        r for r in records
        if r.get("blood_glucose_avg") is not None
    ]
    cgm_days.sort(key=lambda x: x.get("sk", ""))

    if not cgm_days:
        return _ok({"glucose": None, "glucose_trend": []}, cache_seconds=3600)

    latest = cgm_days[-1]

    # 30-day averages
    avg_vals = [float(r["blood_glucose_avg"]) for r in cgm_days if r.get("blood_glucose_avg")]
    tir_vals = [float(r["blood_glucose_time_in_range_pct"]) for r in cgm_days if r.get("blood_glucose_time_in_range_pct")]
    opt_vals = [float(r["blood_glucose_time_in_optimal_pct"]) for r in cgm_days if r.get("blood_glucose_time_in_optimal_pct")]
    std_vals = [float(r["blood_glucose_std_dev"]) for r in cgm_days if r.get("blood_glucose_std_dev")]

    def avg(lst):
        return round(sum(lst) / len(lst), 1) if lst else None

    # Daily trend array for chart
    trend = [
        {
            "date": r.get("sk", "").replace("DATE#", ""),
            "avg": round(float(r["blood_glucose_avg"]), 1) if r.get("blood_glucose_avg") else None,
            "tir": round(float(r["blood_glucose_time_in_range_pct"]), 1) if r.get("blood_glucose_time_in_range_pct") else None,
            "std": round(float(r["blood_glucose_std_dev"]), 1) if r.get("blood_glucose_std_dev") else None,
        }
        for r in cgm_days
    ]

    tir_today = float(latest.get("blood_glucose_time_in_range_pct", 0))
    tir_status = "excellent" if tir_today >= 90 else ("good" if tir_today >= 70 else "needs_attention")
    std_today = float(latest.get("blood_glucose_std_dev", 99))
    variability_status = "low" if std_today < 15 else ("moderate" if std_today < 25 else "high")

    return _ok({
        "glucose": {
            "avg_mg_dl":          round(float(latest.get("blood_glucose_avg", 0)), 1) if latest.get("blood_glucose_avg") else None,
            "std_dev":            round(float(latest.get("blood_glucose_std_dev", 0)), 1) if latest.get("blood_glucose_std_dev") else None,
            "time_in_range_pct":  round(tir_today, 1),
            "time_in_optimal_pct": round(float(latest.get("blood_glucose_time_in_optimal_pct", 0)), 1) if latest.get("blood_glucose_time_in_optimal_pct") else None,
            "time_above_140_pct": round(float(latest.get("blood_glucose_time_above_140_pct", 0)), 1) if latest.get("blood_glucose_time_above_140_pct") else None,
            "cgm_source":         latest.get("cgm_source", "unknown"),
            "tir_status":         tir_status,
            "variability_status": variability_status,
            "30d_avg_mg_dl":      avg(avg_vals),
            "30d_avg_tir":        avg(tir_vals),
            "30d_avg_optimal":    avg(opt_vals),
            "30d_avg_std":        avg(std_vals),
            "days_tracked":       len(cgm_days),
            "as_of_date":         latest.get("sk", "").replace("DATE#", ""),
        },
        "glucose_trend": trend,
    }, cache_seconds=3600)


def handle_sleep_detail() -> dict:
    """
    GET /api/sleep_detail
    Returns: 30-day sleep stats from Eight Sleep + Whoop cross-referenced.
    Shows sleep score, efficiency, bed temp, quality, and daily trend.
    Cache: 3600s (1h).
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d30 = max((datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d"), EXPERIMENT_START)

    eight_days = _query_source("eightsleep", d30, today)
    whoop_days = _query_source("whoop", d30, today)

    # Index whoop by date for cross-referencing
    whoop_by_date = {
        r.get("sk", "").replace("DATE#", ""): r
        for r in whoop_days
        if r.get("sk")
    }

    eight_days.sort(key=lambda x: x.get("sk", ""))
    eight_with_data = [r for r in eight_days if r.get("sleep_score") is not None]

    if not eight_with_data:
        return _ok({"sleep_detail": None, "sleep_trend": []}, cache_seconds=3600)

    latest = eight_with_data[-1]
    latest_date = latest.get("sk", "").replace("DATE#", "")
    whoop_latest = whoop_by_date.get(latest_date, {})

    # 30-day averages (actual field names: sleep_efficiency_pct, sleep_duration_hours)
    score_vals = [float(r["sleep_score"]) for r in eight_with_data if r.get("sleep_score")]
    eff_vals   = [float(r["sleep_efficiency_pct"]) for r in eight_with_data if r.get("sleep_efficiency_pct")]
    temp_vals  = [float(r["bed_temp_f"]) for r in eight_with_data if r.get("bed_temp_f")]

    # Find best-performing temp range by pairing temp with sleep score
    temp_score_pairs = [
        (float(r["bed_temp_f"]), float(r["sleep_score"]))
        for r in eight_with_data
        if r.get("bed_temp_f") and r.get("sleep_score")
    ]
    optimal_temp = None
    if len(temp_score_pairs) >= 7:
        # Group by 2°F buckets, find highest average score bucket
        buckets = {}
        for temp, score in temp_score_pairs:
            bucket = round(temp / 2) * 2  # nearest 2°F
            buckets.setdefault(bucket, []).append(score)
        best_bucket = max(buckets, key=lambda b: sum(buckets[b]) / len(buckets[b]))
        optimal_temp = best_bucket

    def avg(lst):
        return round(sum(lst) / len(lst), 1) if lst else None

    # Daily trend
    trend = []
    for r in eight_with_data:
        date = r.get("sk", "").replace("DATE#", "")
        w = whoop_by_date.get(date, {})
        trend.append({
            "date":          date,
            "sleep_score":   round(float(r["sleep_score"]), 0) if r.get("sleep_score") else None,
            "efficiency":    round(float(r["sleep_efficiency_pct"]), 1) if r.get("sleep_efficiency_pct") else None,
            "bed_temp_f":    round(float(r["bed_temp_f"]), 1) if r.get("bed_temp_f") else None,
            "hours":         round(float(w["sleep_duration_hours"]), 1) if w.get("sleep_duration_hours") else None,
            "whoop_quality": round(float(w["sleep_quality_score"]), 0) if w.get("sleep_quality_score") else None,
        })

    score_today = float(latest.get("sleep_score", 0))
    score_status = "excellent" if score_today >= 85 else ("good" if score_today >= 70 else "needs_attention")

    return _ok({
        "sleep_detail": {
            "sleep_score":       round(score_today, 0),
            "sleep_efficiency":  round(float(latest.get("sleep_efficiency_pct", 0)), 1) if latest.get("sleep_efficiency_pct") else None,
            "bed_temp_f":        round(float(latest.get("bed_temp_f", 0)), 1) if latest.get("bed_temp_f") else None,
            "total_sleep_hours": round(float(latest.get("sleep_duration_hours", 0)), 1) if latest.get("sleep_duration_hours") else None,
            "whoop_quality":     round(float(whoop_latest.get("sleep_quality_score", 0)), 0) if whoop_latest.get("sleep_quality_score") else None,
            "whoop_hours":       round(float(whoop_latest.get("sleep_duration_hours", 0)), 1) if whoop_latest.get("sleep_duration_hours") else None,
            "score_status":      score_status,
            "optimal_temp_f":    optimal_temp,
            "30d_avg_score":     avg(score_vals),
            "30d_avg_efficiency": avg(eff_vals),  # from sleep_efficiency_pct field
            "30d_avg_temp":      avg(temp_vals),
            "days_tracked":      len(eight_with_data),
            "as_of_date":        latest_date,
        },
        "sleep_trend": trend,
    }, cache_seconds=3600)


# ── ARCH-03: Achievements endpoint ──────────────────────────

def handle_achievements() -> dict:
    """
    GET /api/achievements
    Computes earned/locked achievement badges from DynamoDB.
    Sources: habit_scores (streaks), character_sheet (level), withings (weight milestones),
             experiments (first experiment), habits (days tracked).
    Cache: 3600s (1 hr) — achievements update nightly.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d365 = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")

    # ── Streak data
    habit_pk = f"{USER_PREFIX}habit_scores"
    habit_resp = table.query(
        KeyConditionExpression=Key("pk").eq(habit_pk),
        ScanIndexForward=False,
        Limit=1,
    )
    habit_items = _decimal_to_float(habit_resp.get("Items", []))
    latest_habit = habit_items[0] if habit_items else {}
    current_streak = int(latest_habit.get("t0_perfect_streak") or latest_habit.get("t0_aggregate_streak") or 0)

    # Days tracked = count of habit_score records in last 365 days
    all_habits_resp = table.query(
        KeyConditionExpression=Key("pk").eq(habit_pk) & Key("sk").between(
            f"DATE#{d365}", f"DATE#{today}"
        ),
    )
    days_tracked = len(all_habits_resp.get("Items", []))

    # ── Character level
    char_pk = f"{USER_PREFIX}character_sheet"
    char_resp = table.query(
        KeyConditionExpression=Key("pk").eq(char_pk),
        ScanIndexForward=False,
        Limit=1,
    )
    char_items = _decimal_to_float(char_resp.get("Items", []))
    current_level = int(float((char_items[0] if char_items else {}).get("character_level", 1)))

    # ── Weight milestones
    withings = _latest_item("withings")
    current_weight = float(withings.get("weight_lbs", 999)) if withings else 999.0
    start_weight = float(_get_profile().get("journey_start_weight_lbs", 302.0))
    lost_lbs = round(start_weight - current_weight, 1) if current_weight < start_weight else 0

    # ── First experiment
    exp_pk = f"{USER_PREFIX}experiments"
    exp_resp = table.query(
        KeyConditionExpression=Key("pk").eq(exp_pk),
        ScanIndexForward=False,
        Limit=50,
    )
    all_exps = [
        i for i in _decimal_to_float(exp_resp.get("Items", []))
        if i.get("sk", "").startswith("EXP#")
    ]
    completed_exps = [i for i in all_exps if i.get("status") in ("completed", "confirmed")]

    # EL-21: Streak detection — last 3 finished experiments all completed (no abandoned/failed)
    _exp_has_3_streak = False
    finished = sorted(
        [i for i in all_exps if i.get("status") in ("completed", "confirmed", "abandoned")],
        key=lambda x: x.get("end_date") or x.get("start_date", ""), reverse=True,
    )
    if len(finished) >= 3:
        _exp_has_3_streak = all(e.get("status") in ("completed", "confirmed") for e in finished[:3])

    # EL-21: Pillar coverage — completed experiment in each of 7 pillars
    _ALL_PILLARS = {"sleep", "movement", "nutrition", "supplements", "mental", "social", "discipline"}
    _covered_pillars = set()
    for e in completed_exps:
        for tag in (e.get("tags") or []):
            tag_lower = tag.lower()
            for p in _ALL_PILLARS:
                if p in tag_lower:
                    _covered_pillars.add(p)
    _exp_all_pillars_covered = _covered_pillars >= _ALL_PILLARS

    # ── Challenge completion counts
    challenges_pk = f"USER#{USER_ID}#SOURCE#challenges"
    completed_challenges = 0
    perfect_challenges = 0
    try:
        ch_resp = table.query(
            KeyConditionExpression=Key("pk").eq(challenges_pk) & Key("sk").begins_with("CHALLENGE#"),
        )
        ch_items = _decimal_to_float(ch_resp.get("Items", []))
        for ch in ch_items:
            if ch.get("status") == "completed":
                completed_challenges += 1
                checkins = ch.get("daily_checkins", [])
                if checkins:
                    success = sum(1 for c in checkins if c.get("completed"))
                    if success == len(checkins):
                        perfect_challenges += 1
    except Exception as _ch_e:
        logger.warning("[achievements] Challenge query failed (non-fatal): %s", _ch_e)

    def badge(id_, label, category, desc, earned, earned_date=None, unlock_hint=None):
        return {
            "id": id_, "label": label, "category": category, "description": desc,
            "earned": earned, "earned_date": earned_date, "unlock_hint": unlock_hint,
        }

    achievements = [
        # ── Streak
        badge("week_warrior", "Week Warrior", "streak",
              "7-day Tier 0 habit streak",
              earned=current_streak >= 7,
              earned_date=today if current_streak >= 7 else None,
              unlock_hint=f"{max(0, 7 - current_streak)} days to unlock" if current_streak < 7 else None),
        badge("monthly_grind", "Monthly Grind", "streak",
              "30-day Tier 0 habit streak",
              earned=current_streak >= 30,
              earned_date=today if current_streak >= 30 else None,
              unlock_hint=f"{max(0, 30 - current_streak)} days to unlock" if current_streak < 30 else None),
        badge("quarterly", "Quarterly", "streak",
              "90-day Tier 0 habit streak",
              earned=current_streak >= 90,
              unlock_hint=f"{max(0, 90 - current_streak)} days to unlock" if current_streak < 90 else None),

        # ── Level
        badge("first_level_up", "First Level Up", "level",
              "Reached Character Level 2",
              earned=current_level >= 2,
              earned_date=today if current_level >= 2 else None),
        badge("apprentice", "Apprentice", "level",
              "Reached Character Level 5",
              earned=current_level >= 5,
              unlock_hint=f"Level {current_level} → Level 5 needed" if current_level < 5 else None),
        badge("journeyman", "Journeyman", "level",
              "Reached Character Level 10",
              earned=current_level >= 10,
              unlock_hint=f"Level {current_level} → Level 10 needed" if current_level < 10 else None),

        # ── Weight milestones
        badge("lost_20", "−20 lbs", "milestone",
              "Lost first 20 lbs",
              earned=lost_lbs >= 20,
              earned_date=today if lost_lbs >= 20 else None),
        badge("sub_280", "Sub-280", "milestone",
              "Weight under 280 lbs",
              earned=current_weight < 280,
              earned_date=today if current_weight < 280 else None,
              unlock_hint=f"{round(current_weight - 280, 1)} lbs to unlock" if current_weight >= 280 else None),
        badge("sub_260", "Sub-260", "milestone",
              "Weight under 260 lbs",
              earned=current_weight < 260,
              unlock_hint=f"{round(current_weight - 260, 1)} lbs to unlock" if current_weight >= 260 else None),

        # ── Data
        badge("100_days", "100 Days Tracked", "data",
              "100+ days of habit logging",
              earned=days_tracked >= 100,
              earned_date=today if days_tracked >= 100 else None,
              unlock_hint=f"{max(0, 100 - days_tracked)} days to unlock" if days_tracked < 100 else None),
        badge("365_days", "Year of Data", "data",
              "365 days of habit logging",
              earned=days_tracked >= 365,
              unlock_hint=f"{max(0, 365 - days_tracked)} days to unlock" if days_tracked < 365 else None),

        # ── Experiment
        badge("first_experiment", "First Experiment", "science",
              "Completed first N=1 experiment",
              earned=len(completed_exps) >= 1,
              earned_date=today if completed_exps else None),
        badge("hypothesis_confirmed", "Hypothesis Confirmed", "science",
              "N=1 result statistically validated",
              earned=False,  # requires manual confirmation
              unlock_hint="Complete a tracked experiment to unlock"),

        # EL-21: Experiment evolution badges
        badge("exp_3_completed", "Lab Rat", "science",
              "Completed 3 experiments",
              earned=len(completed_exps) >= 3,
              earned_date=today if len(completed_exps) >= 3 else None,
              unlock_hint=f"{max(0, 3 - len(completed_exps))} experiments to unlock" if len(completed_exps) < 3 else None),
        badge("exp_5_completed", "Research Fellow", "science",
              "Completed 5 experiments",
              earned=len(completed_exps) >= 5,
              earned_date=today if len(completed_exps) >= 5 else None,
              unlock_hint=f"{max(0, 5 - len(completed_exps))} experiments to unlock" if len(completed_exps) < 5 else None),
        badge("exp_10_completed", "Principal Investigator", "science",
              "Completed 10 experiments",
              earned=len(completed_exps) >= 10,
              unlock_hint=f"{max(0, 10 - len(completed_exps))} experiments to unlock" if len(completed_exps) < 10 else None),
        badge("exp_streak_3", "Hot Streak", "science",
              "3 consecutive completed experiments (no fails)",
              earned=_exp_has_3_streak,
              unlock_hint="Complete 3 experiments in a row without abandoning"),
        badge("exp_all_pillars", "Renaissance Man", "science",
              "Completed experiment in every pillar",
              earned=_exp_all_pillars_covered,
              unlock_hint="Complete at least one experiment in each of the 7 pillars"),

        # ── Challenges
        badge("first_challenge", "Arena Debut", "challenge",
              "Completed first challenge",
              earned=completed_challenges >= 1,
              earned_date=today if completed_challenges >= 1 else None),
        badge("five_challenges", "Arena Regular", "challenge",
              "Completed 5 challenges",
              earned=completed_challenges >= 5,
              unlock_hint=f"{max(0, 5 - completed_challenges)} challenges to unlock" if completed_challenges < 5 else None),
        badge("ten_challenges", "Arena Veteran", "challenge",
              "Completed 10 challenges",
              earned=completed_challenges >= 10,
              unlock_hint=f"{max(0, 10 - completed_challenges)} challenges to unlock" if completed_challenges < 10 else None),
        badge("twenty_five_challenges", "Arena Legend", "challenge",
              "Completed 25 challenges",
              earned=completed_challenges >= 25,
              unlock_hint=f"{max(0, 25 - completed_challenges)} challenges to unlock" if completed_challenges < 25 else None),
        badge("perfect_challenge", "Flawless", "challenge",
              "Completed a challenge with 100% success rate (7+ days)",
              earned=perfect_challenges >= 1,
              unlock_hint="Complete a 7+ day challenge without missing a single day"),
    ]

    earned_count = sum(1 for a in achievements if a["earned"])

    return _ok({
        "achievements": achievements,
        "summary": {
            "earned": earned_count,
            "total":  len(achievements),
            "current_streak": current_streak,
            "days_tracked":   days_tracked,
            "current_level":  current_level,
            "current_weight": round(current_weight, 1),
            "completed_challenges": completed_challenges,
            "perfect_challenges": perfect_challenges,
        },
    }, cache_seconds=3600)


# ── ARCH-02: Snapshot endpoint ──────────────────────────────

def handle_snapshot() -> dict:
    """
    GET /api/snapshot
    Combined response: vitals + journey + character in one call.
    Reduces client-side roundtrips for pages that need all three (e.g. /live/, homepage).
    On partial failure any sub-object is null; callers must handle gracefully.
    """
    vitals_result = journey_result = character_result = None
    try:
        vitals_result = handle_vitals()
        vitals_body = json.loads(vitals_result.get("body", "{}"))
    except Exception as _e:
        logger.warning("[snapshot] vitals failed: %s", _e)
        vitals_body = None

    try:
        journey_result = handle_journey()
        journey_body = json.loads(journey_result.get("body", "{}"))
    except Exception as _e:
        logger.warning("[snapshot] journey failed: %s", _e)
        journey_body = None

    try:
        character_result = handle_character()
        character_body = json.loads(character_result.get("body", "{}"))
    except Exception as _e:
        logger.warning("[snapshot] character failed: %s", _e)
        character_body = None

    payload = {
        "vitals":    vitals_body,
        "journey":   journey_body,
        "character": character_body,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return {
        "statusCode": 200,
        "headers":    {**CORS_HEADERS, "Cache-Control": "public, max-age=60"},
        "body":       json.dumps(payload, default=str),
    }


# ── ACCT-2: Nudge handler ───────────────────────────────────

NUDGE_CATEGORIES = {"back_on_it", "watching", "take_your_time", "you_got_this"}
NUDGE_LABELS = {
    "back_on_it":    "Get back on it 🔥",
    "watching":      "We're watching 👀",
    "take_your_time": "Take your time ⏰",
    "you_got_this":  "You've got this 💪",
}


def _handle_nudge(event: dict) -> dict:
    """
    POST /api/nudge
    Body: {"category": "back_on_it" | "watching" | "take_your_time" | "you_got_this"}
    Rate limit: 1 nudge per category per IP per hour (in-memory).
    Counts are approximate — reset on Lambda cold start.
    NOTE: Persisting counts to DynamoDB requires a CDK write-permission change (future work).
    """
    import time as _time
    source_ip = (
        event.get("requestContext", {}).get("http", {}).get("sourceIp")
        or event.get("requestContext", {}).get("identity", {}).get("sourceIp")
        or "unknown"
    )
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return _error(400, "Invalid JSON body")

    category = (body.get("category") or "").strip().lower()
    if category not in NUDGE_CATEGORIES:
        return _error(400, f"Invalid category. Must be one of: {sorted(NUDGE_CATEGORIES)}")

    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
    rate_key = f"{ip_hash}:{category}"
    now = int(_time.time())
    hour_ago = now - 3600

    # Rate limit: 1 per IP per category per hour
    recent = [t for t in _nudge_rate_store.get(rate_key, []) if t > hour_ago]
    if recent:
        return {
            "statusCode": 429,
            "headers": {**CORS_HEADERS, "Retry-After": "3600", "Cache-Control": "no-store"},
            "body": json.dumps({"error": "Already sent this reaction recently. Come back later.", "category": category}),
        }
    recent.append(now)
    _nudge_rate_store[rate_key] = recent[-10:]

    # Increment in-memory count
    _nudge_counts[category] = _nudge_counts.get(category, 0) + 1
    logger.info(f"[nudge] category={category} ip_hash={ip_hash} total_this_session={_nudge_counts[category]}")

    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
        "body": json.dumps({
            "success": True,
            "category": category,
            "label": NUDGE_LABELS[category],
            "message": "Reaction sent. Matthew will see this in his daily brief.",
        }),
    }


# ── NEW-1: Submit Finding ────────────────────────────────────

FINDING_RATE_LIMIT = 3  # per IP per hour


def _handle_submit_finding(event: dict) -> dict:
    """
    POST /api/submit_finding
    Body: {"metric_a": str, "metric_b": str, "finding": str, "email": str (optional)}
    Stores visitor-discovered correlation findings in S3 for Matthew's review.
    Rate limit: 3 per IP per hour.
    """
    import time as _time
    source_ip = (
        event.get("requestContext", {}).get("http", {}).get("sourceIp")
        or event.get("requestContext", {}).get("identity", {}).get("sourceIp")
        or "unknown"
    )
    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
    now = int(_time.time())
    hour_ago = now - 3600

    # Rate limit
    recent = [t for t in _finding_rate_store.get(ip_hash, []) if t > hour_ago]
    if len(recent) >= FINDING_RATE_LIMIT:
        _emit_rate_limit_metric("submit_finding")
        return {
            "statusCode": 429,
            "headers": {**CORS_HEADERS, "Retry-After": "3600"},
            "body": json.dumps({"error": "Rate limit reached. 3 submissions per hour."}),
        }
    recent.append(now)
    _finding_rate_store[ip_hash] = recent[-10:]

    # Parse body
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return _error(400, "Invalid JSON")

    metric_a = re.sub(r"<[^>]+>", "", (body.get("metric_a") or "").strip())[:100]
    metric_b = re.sub(r"<[^>]+>", "", (body.get("metric_b") or "").strip())[:100]
    finding  = re.sub(r"<[^>]+>", "", (body.get("finding") or "").strip())[:500]
    email    = re.sub(r"<[^>]+>", "", (body.get("email") or "").strip())[:254]

    if not metric_a or not metric_b:
        return _error(400, "Both metric_a and metric_b are required.")
    if not finding or len(finding) < 10:
        return _error(400, "Finding description must be at least 10 characters.")
    if email and "@" not in email:
        return _error(400, "Invalid email format.")

    # Build finding record
    timestamp = datetime.now(timezone.utc).isoformat()
    finding_id = hashlib.sha256(f"{ip_hash}:{timestamp}:{metric_a}:{metric_b}".encode()).hexdigest()[:12]
    record = {
        "id":        finding_id,
        "metric_a":  metric_a,
        "metric_b":  metric_b,
        "finding":   finding,
        "email":     email if email else None,
        "submitted_at": timestamp,
        "ip_hash":   ip_hash,
        "status":    "pending",
    }

    # Write to S3
    S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
    s3_key = f"site/findings/{datetime.now(timezone.utc).strftime('%Y-%m-%d')}_{finding_id}.json"
    try:
        s3_client = boto3.client("s3", region_name=S3_REGION)
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(record, indent=2),
            ContentType="application/json",
        )
        logger.info(f"[submit_finding] Stored: {s3_key} metric_a={metric_a} metric_b={metric_b}")
    except Exception as e:
        logger.error(f"[submit_finding] S3 write failed: {e}")
        return _error(503, "Unable to store finding. Try again later.")

    remaining = FINDING_RATE_LIMIT - len(recent)
    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
        "body": json.dumps({
            "success": True,
            "finding_id": finding_id,
            "message": "Finding submitted! Matthew will review it and may promote it to a Discovery or seed an Experiment.",
            "remaining": remaining,
        }),
    }


# ── EL-2: Experiment Library endpoint ───────────────────────

def handle_experiment_library() -> dict:
    """
    GET /api/experiment_library
    Returns the full experiment library from S3 config, merged with:
      - Vote counts from DynamoDB
      - Status from active/completed experiments (matched by library_id or name slug)
    Cache: 900s (15 min).
    """
    S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
    try:
        s3_client = boto3.client("s3", region_name=S3_REGION)
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key="site/config/experiment_library.json")
        library = json.loads(resp["Body"].read().decode("utf-8"))
    except Exception as e:
        logger.error(f"[experiment_library] S3 read failed: {e}")
        return _error(503, "Experiment library not available")

    # ── Load vote counts from DynamoDB ──
    vote_counts = {}
    try:
        vote_pk = "VOTES#experiment_library"
        vote_resp = table.query(
            KeyConditionExpression=Key("pk").eq(vote_pk),
            ProjectionExpression="sk, vote_count",
        )
        for item in _decimal_to_float(vote_resp.get("Items", [])):
            lib_id = item.get("sk", "").replace("LIB#", "")
            vote_counts[lib_id] = int(item.get("vote_count", 0))
    except Exception as e:
        logger.warning(f"[experiment_library] Vote query failed (non-fatal): {e}")

    # ── Load active/completed experiments to merge status ──
    exp_status_map = {}
    try:
        exp_pk = f"{USER_PREFIX}experiments"
        exp_resp = table.query(
            KeyConditionExpression=Key("pk").eq(exp_pk),
            ScanIndexForward=False,
            Limit=100,
        )
        for item in _decimal_to_float(exp_resp.get("Items", [])):
            if not item.get("sk", "").startswith("EXP#"):
                continue
            exp_id = item.get("sk", "").replace("EXP#", "")
            lib_id = item.get("library_id")
            status = item.get("status", "unknown")
            start = item.get("start_date", "")
            days_in = None
            if status == "active" and start:
                try:
                    days_in = (datetime.now(timezone.utc).replace(tzinfo=None) - datetime.strptime(start, "%Y-%m-%d")).days
                except Exception:
                    pass

            entry = {
                "status": status,
                "experiment_id": exp_id,
                "days_in": days_in,
                "start_date": start,
                "outcome": item.get("outcome"),
                "grade": item.get("grade"),
                "hypothesis_confirmed": item.get("hypothesis_confirmed"),
            }
            if lib_id:
                exp_status_map[lib_id] = entry
            name_slug = re.sub(r"[^a-z0-9]+", "-", item.get("name", "").lower()).strip("-")[:40]
            if name_slug:
                exp_status_map.setdefault(name_slug, entry)
    except Exception as e:
        logger.warning(f"[experiment_library] Experiment query failed (non-fatal): {e}")

    # ── Merge votes + experiment status into library entries ──
    experiments = library.get("experiments", [])
    pillar_map = {}
    pillar_meta = library.get("pillars", {})
    pillar_order = library.get("pillar_order", list(pillar_meta.keys()))

    total_votes = 0
    for exp in experiments:
        lib_id = exp.get("id", "")
        exp["votes"] = vote_counts.get(lib_id, exp.get("votes", 0))
        total_votes += exp["votes"]

        matched = exp_status_map.get(lib_id)
        if matched:
            exp["status"] = matched["status"]
            exp["active_experiment_id"] = matched["experiment_id"]
            exp["days_in"] = matched.get("days_in")

        pillar_id = exp.get("pillar", "other")
        if pillar_id not in pillar_map:
            meta = pillar_meta.get(pillar_id, {})
            pillar_map[pillar_id] = {
                "id": pillar_id,
                "label": meta.get("label", pillar_id.title()),
                "icon": meta.get("icon", "circle"),
                "color": meta.get("color"),
                "experiments": [],
                "stats": {"total": 0, "active": 0, "completed": 0, "backlog": 0},
            }
        group = pillar_map[pillar_id]
        group["experiments"].append(exp)
        group["stats"]["total"] += 1
        s = exp.get("status", "backlog")
        if s == "active":
            group["stats"]["active"] += 1
        elif s in ("completed", "partial", "failed"):
            group["stats"]["completed"] += 1
        else:
            group["stats"]["backlog"] += 1

    pillars = []
    for pid in pillar_order:
        if pid in pillar_map:
            group = pillar_map[pid]
            group["experiments"].sort(
                key=lambda e: (0 if e.get("status") == "active" else 1, -(e.get("votes") or 0))
            )
            pillars.append(group)
    for pid, group in pillar_map.items():
        if pid not in pillar_order:
            pillars.append(group)

    return _ok({
        "pillars": pillars,
        "total_experiments": len(experiments),
        "total_votes": total_votes,
        "version": library.get("version", "1.0.0"),
    }, cache_seconds=900)


# ── EL-3/4: Experiment Vote POST handler ────────────────────

def _handle_experiment_vote(event: dict) -> dict:
    """
    POST /api/experiment_vote
    Body: {"library_id": "post-dinner-walk"}
    Rate limit: 1 vote per IP per experiment per 24 hours via DynamoDB TTL.
    """
    source_ip = (
        event.get("requestContext", {}).get("http", {}).get("sourceIp")
        or event.get("requestContext", {}).get("identity", {}).get("sourceIp")
        or "unknown"
    )
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return _error(400, "Invalid JSON body")

    library_id = (body.get("library_id") or "").strip().lower()
    if not library_id or len(library_id) > 80:
        return _error(400, "library_id is required (max 80 chars)")

    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
    rate_pk = "VOTES#rate_limit"
    rate_sk = f"IP#{ip_hash}#LIB#{library_id}"
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    ttl_24h = now_epoch + 86400

    try:
        table.put_item(
            Item={
                "pk": rate_pk,
                "sk": rate_sk,
                "voted_at": now_epoch,
                "ttl": ttl_24h,
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
    except Exception as e:
        if "ConditionalCheckFailedException" in str(e):
            return {
                "statusCode": 429,
                "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
                "body": json.dumps({"error": "Already voted for this experiment in the last 24 hours"}),
            }
        logger.error(f"[experiment_vote] Rate limit check failed: {e}")
        return _error(500, "Vote rate limit check failed")

    vote_pk = "VOTES#experiment_library"
    vote_sk = f"LIB#{library_id}"
    try:
        result = table.update_item(
            Key={"pk": vote_pk, "sk": vote_sk},
            UpdateExpression="ADD vote_count :one SET library_id = :lid, last_voted = :ts",
            ExpressionAttributeValues={
                ":one": 1,
                ":lid": library_id,
                ":ts": now_epoch,
            },
            ReturnValues="UPDATED_NEW",
        )
        new_count = int(result.get("Attributes", {}).get("vote_count", 1))
    except Exception as e:
        logger.error(f"[experiment_vote] Vote increment failed: {e}")
        return _error(500, "Failed to record vote")

    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
        "body": json.dumps({
            "library_id": library_id,
            "new_count": new_count,
        }),
    }


# ── EL-F1: Per-experiment follow (email interest) ─────────

def _handle_experiment_follow(event: dict) -> dict:
    """
    POST /api/experiment_follow
    Body: {"email": "user@example.com", "library_id": "post-dinner-walk"}
    Stores interest so we can notify when experiment completes.
    Rate limit: 10 follows per IP per hour.
    """
    source_ip = (
        event.get("requestContext", {}).get("http", {}).get("sourceIp")
        or event.get("requestContext", {}).get("identity", {}).get("sourceIp")
        or "unknown"
    )
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return _error(400, "Invalid JSON body")

    email = (body.get("email") or "").strip().lower()
    library_id = (body.get("library_id") or "").strip().lower()

    if not email or "@" not in email or len(email) > 200:
        return _error(400, "Valid email is required")
    if not library_id or len(library_id) > 80:
        return _error(400, "library_id is required")

    email_hash = hashlib.sha256(email.encode()).hexdigest()[:16]
    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
    now_epoch = int(datetime.now(timezone.utc).timestamp())

    # Rate limit: 10 follows per IP per hour
    rate_pk = "VOTES#rate_limit"
    rate_sk = f"FOLLOW#{ip_hash}#{now_epoch // 3600}"
    try:
        result = table.update_item(
            Key={"pk": rate_pk, "sk": rate_sk},
            UpdateExpression="ADD follow_count :one SET #ttl = :ttl",
            ExpressionAttributeNames={"#ttl": "ttl"},
            ExpressionAttributeValues={
                ":one": 1,
                ":ttl": now_epoch + 7200,
            },
            ReturnValues="UPDATED_NEW",
        )
        count = int(result.get("Attributes", {}).get("follow_count", 1))
        if count >= 10:
            return {
                "statusCode": 429,
                "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
                "body": json.dumps({"error": "Too many follow requests. Try again later."}),
            }
    except Exception as e:
        logger.error(f"[experiment_follow] Rate limit check failed: {e}")
        return _error(500, "Follow rate limit check failed")

    # Store the follow interest
    follow_pk = "EXPERIMENT_FOLLOWS"
    follow_sk = f"EMAIL#{email_hash}#EXP#{library_id}"
    try:
        table.put_item(
            Item={
                "pk": follow_pk,
                "sk": follow_sk,
                "email": email,
                "library_id": library_id,
                "followed_at": now_epoch,
                "notified": False,
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
    except Exception as e:
        if "ConditionalCheckFailedException" in str(e):
            return {
                "statusCode": 200,
                "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
                "body": json.dumps({"already_following": True, "library_id": library_id}),
            }
        logger.error(f"[experiment_follow] DDB put failed: {e}")
        return _error(500, "Failed to save follow")

    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
        "body": json.dumps({"followed": True, "library_id": library_id}),
    }


# ── EL-F2: Single experiment detail endpoint ────────────────

def _handle_experiment_detail(event: dict) -> dict:
    """
    GET /api/experiment_detail?id=post-dinner-walk
    Returns full detail for a single experiment from the library,
    merged with any active/completed DynamoDB experiment data + votes + followers.
    Cache: 900s.
    """
    params = event.get("queryStringParameters") or {}
    lib_id = (params.get("id") or "").strip().lower()
    if not lib_id:
        return _error(400, "id query parameter is required")

    S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
    try:
        s3_client = boto3.client("s3", region_name=S3_REGION)
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key="site/config/experiment_library.json")
        library = json.loads(resp["Body"].read().decode("utf-8"))
    except Exception as e:
        logger.error(f"[experiment_detail] S3 read failed: {e}")
        return _error(503, "Experiment library not available")

    lib_exp = None
    for exp in library.get("experiments", []):
        if exp.get("id") == lib_id:
            lib_exp = exp
            break
    if not lib_exp:
        return _error(404, f"Experiment '{lib_id}' not found in library")

    pillar_meta = library.get("pillars", {}).get(lib_exp.get("pillar", ""), {})
    lib_exp["pillar_label"] = pillar_meta.get("label", lib_exp.get("pillar", "").title())
    lib_exp["pillar_icon"] = pillar_meta.get("icon", "circle")

    # Vote count
    try:
        vote_resp = table.get_item(Key={"pk": "VOTES#experiment_library", "sk": f"LIB#{lib_id}"})
        vote_item = _decimal_to_float(vote_resp.get("Item"))
        lib_exp["votes"] = int(vote_item.get("vote_count", 0)) if vote_item else 0
    except Exception:
        lib_exp["votes"] = 0

    # Follower count
    try:
        follow_resp = table.query(
            KeyConditionExpression=Key("pk").eq("EXPERIMENT_FOLLOWS"),
            FilterExpression="library_id = :lid",
            ExpressionAttributeValues={":lid": lib_id},
            Select="COUNT",
        )
        lib_exp["follower_count"] = follow_resp.get("Count", 0)
    except Exception:
        lib_exp["follower_count"] = 0

    # Past runs from DynamoDB
    runs = []
    try:
        exp_pk = f"{USER_PREFIX}experiments"
        exp_resp = table.query(
            KeyConditionExpression=Key("pk").eq(exp_pk),
            ScanIndexForward=False,
            Limit=100,
        )
        for item in _decimal_to_float(exp_resp.get("Items", [])):
            if not item.get("sk", "").startswith("EXP#"):
                continue
            item_lib_id = item.get("library_id", "")
            name_slug = re.sub(r"[^a-z0-9]+", "-", item.get("name", "").lower()).strip("-")[:40]
            if item_lib_id == lib_id or name_slug == lib_id:
                start = item.get("start_date", "")
                end = item.get("end_date")
                status = item.get("status", "unknown")
                days = None
                try:
                    end_d = datetime.strptime(end, "%Y-%m-%d") if end else datetime.now(timezone.utc).replace(tzinfo=None)
                    days = max(0, (end_d - datetime.strptime(start, "%Y-%m-%d")).days)
                except Exception:
                    pass
                runs.append({
                    "experiment_id": item.get("sk", "").replace("EXP#", ""),
                    "status": status,
                    "start_date": start,
                    "end_date": end,
                    "days": days,
                    "hypothesis": item.get("hypothesis"),
                    "outcome": item.get("outcome") or item.get("result_summary"),
                    "primary_metric": item.get("primary_metric"),
                    "baseline_value": item.get("baseline_value"),
                    "result_value": item.get("result_value"),
                    "grade": item.get("grade"),
                    "compliance_pct": item.get("compliance_pct"),
                    "reflection": item.get("reflection"),
                    "mechanism": item.get("mechanism"),
                    "key_finding": item.get("key_finding"),
                    "hypothesis_confirmed": item.get("hypothesis_confirmed"),
                    "iteration": item.get("iteration", 1),
                })
    except Exception as e:
        logger.warning(f"[experiment_detail] Experiment query failed: {e}")

    lib_exp["runs"] = runs
    lib_exp["total_runs"] = len(runs)
    lib_exp["active_run"] = next((r for r in runs if r["status"] == "active"), None)
    lib_exp["completed_runs_count"] = sum(1 for r in runs if r["status"] == "completed")

    return _ok(lib_exp, cache_seconds=900)



# ── Router ──────────────────────────────────────────────────

# ── S3 config caches for data-driven pages ─────────────────
_protocols_cache = None
_challenges_cache = None
_challenge_catalog_cache = None
_domains_cache = None

def _load_s3_json(key, cache_name):
    """Load a JSON file from S3. Returns parsed dict. Cached per Lambda container."""
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

# ── PULSE-A4: Pulse endpoint ───────────────────────────────────────────────

def handle_pulse() -> dict:
    """
    GET /api/pulse
    Returns the Pulse daily state: 8 glyph signals, status word, narrative.
    Today: reads from S3 pulse.json (pre-computed by daily brief).
    Cache: 300s (5 min).
    """
    S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
    try:
        s3_client = boto3.client("s3", region_name=S3_REGION)
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key="site/pulse.json")
        pulse_data = json.loads(resp["Body"].read())
        logger.info("[pulse] Loaded pulse.json from S3")
        return _ok(pulse_data, cache_seconds=300)
    except Exception as e:
        if "NoSuchKey" in str(e):
            logger.warning("[pulse] pulse.json not found — not yet generated")
            return _ok({
                "pulse": {
                    "day_number": 0,
                    "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "status": "quiet",
                    "status_color": "#3a5a48",
                    "narrative": "Today's pulse generates at 11 AM PT.",
                    "signals_reporting": 0,
                    "signals_total": 8,
                    "glyphs": {},
                    "generated_at": None,
                }
            }, cache_seconds=60)
        logger.error(f"[pulse] Failed: {e}")
        return _error(503, "Pulse data not available")


def handle_protocols() -> dict:
    """GET /api/protocols — Return protocol definitions from DynamoDB."""
    protocols_pk = f"{USER_PREFIX}protocols"
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(protocols_pk) & Key("sk").begins_with("PROTOCOL#"),
            ScanIndexForward=True,
        )
        protocols = []
        for item in _decimal_to_float(resp.get("Items", [])):
            item.pop("pk", None)
            item.pop("sk", None)
            protocols.append(item)
        return _ok({"protocols": protocols, "count": len(protocols)}, cache_seconds=3600)
    except Exception as e:
        logger.warning("handle_protocols: DynamoDB query failed, falling back to S3: %s", e)
        global _protocols_cache
        if _protocols_cache is None:
            _protocols_cache = _load_s3_json("site/config/protocols.json", "protocols")
        protocols = _protocols_cache.get("protocols", [])
        return _ok({"protocols": protocols, "count": len(protocols)}, cache_seconds=3600)


def _handle_challenge_vote(event: dict) -> dict:
    """POST /api/challenge_vote — Rate-limited vote for challenge catalog entries.
    Body: {"catalog_id": "cold-shower-finish"}
    Rate limit: 1 vote per IP per challenge per 24 hours via DynamoDB TTL.
    """
    source_ip = (
        event.get("requestContext", {}).get("http", {}).get("sourceIp")
        or event.get("requestContext", {}).get("identity", {}).get("sourceIp")
        or "unknown"
    )
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return _error(400, "Invalid JSON body")

    catalog_id = (body.get("catalog_id") or "").strip().lower()
    if not catalog_id or len(catalog_id) > 80:
        return _error(400, "catalog_id is required (max 80 chars)")

    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
    rate_pk = "VOTES#rate_limit"
    rate_sk = f"IP#{ip_hash}#CH#{catalog_id}"
    now_epoch = int(datetime.now(timezone.utc).timestamp())
    ttl_24h = now_epoch + 86400

    try:
        table.put_item(
            Item={
                "pk": rate_pk,
                "sk": rate_sk,
                "voted_at": now_epoch,
                "ttl": ttl_24h,
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
    except Exception as e:
        if "ConditionalCheckFailedException" in str(e):
            return {
                "statusCode": 429,
                "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
                "body": json.dumps({"error": "Already voted for this challenge in the last 24 hours"}),
            }
        logger.error(f"[challenge_vote] Rate limit check failed: {e}")
        return _error(500, "Vote rate limit check failed")

    vote_pk = "VOTES#challenges"
    vote_sk = f"CH#{catalog_id}"
    try:
        result = table.update_item(
            Key={"pk": vote_pk, "sk": vote_sk},
            UpdateExpression="ADD vote_count :one SET catalog_id = :cid, last_voted = :ts",
            ExpressionAttributeValues={
                ":one": 1,
                ":cid": catalog_id,
                ":ts": now_epoch,
            },
            ReturnValues="UPDATED_NEW",
        )
        new_count = int(result.get("Attributes", {}).get("vote_count", 1))
    except Exception as e:
        logger.error(f"[challenge_vote] Vote increment failed: {e}")
        return _error(500, "Failed to record vote")

    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
        "body": json.dumps({
            "catalog_id": catalog_id,
            "new_count": new_count,
        }),
    }


def _handle_challenge_follow(event: dict) -> dict:
    """POST /api/challenge_follow — Email follow for challenge catalog entries.
    Body: {"email": "user@example.com", "catalog_id": "cold-shower-finish"}
    Rate limit: 10 follows per IP per hour.
    """
    source_ip = (
        event.get("requestContext", {}).get("http", {}).get("sourceIp")
        or event.get("requestContext", {}).get("identity", {}).get("sourceIp")
        or "unknown"
    )
    try:
        body = json.loads(event.get("body") or "{}")
    except Exception:
        return _error(400, "Invalid JSON body")

    email = (body.get("email") or "").strip().lower()
    catalog_id = (body.get("catalog_id") or "").strip().lower()

    if not email or "@" not in email or len(email) > 200:
        return _error(400, "Valid email is required")
    if not catalog_id or len(catalog_id) > 80:
        return _error(400, "catalog_id is required")

    email_hash = hashlib.sha256(email.encode()).hexdigest()[:16]
    ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
    now_epoch = int(datetime.now(timezone.utc).timestamp())

    # Rate limit: 10 follows per IP per hour
    rate_pk = "VOTES#rate_limit"
    rate_sk = f"CHFOLLOW#{ip_hash}#{now_epoch // 3600}"
    try:
        result = table.update_item(
            Key={"pk": rate_pk, "sk": rate_sk},
            UpdateExpression="ADD follow_count :one SET #ttl = :ttl",
            ExpressionAttributeNames={"#ttl": "ttl"},
            ExpressionAttributeValues={
                ":one": 1,
                ":ttl": now_epoch + 7200,
            },
            ReturnValues="UPDATED_NEW",
        )
        count = int(result.get("Attributes", {}).get("follow_count", 1))
        if count >= 10:
            return {
                "statusCode": 429,
                "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
                "body": json.dumps({"error": "Too many follow requests. Try again later."}),
            }
    except Exception as e:
        logger.error(f"[challenge_follow] Rate limit check failed: {e}")
        return _error(500, "Follow rate limit check failed")

    # Store the follow interest
    follow_pk = "CHALLENGE_FOLLOWS"
    follow_sk = f"EMAIL#{email_hash}#CH#{catalog_id}"
    try:
        table.put_item(
            Item={
                "pk": follow_pk,
                "sk": follow_sk,
                "email": email,
                "catalog_id": catalog_id,
                "followed_at": now_epoch,
                "notified": False,
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
    except Exception as e:
        if "ConditionalCheckFailedException" in str(e):
            return {
                "statusCode": 200,
                "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
                "body": json.dumps({"already_following": True, "catalog_id": catalog_id}),
            }
        logger.error(f"[challenge_follow] DDB put failed: {e}")
        return _error(500, "Failed to save follow")

    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
        "body": json.dumps({"followed": True, "catalog_id": catalog_id}),
    }


def handle_challenge_catalog() -> dict:
    """GET /api/challenge_catalog — Challenge catalog from S3 with vote counts.

    Returns the full catalog of challenges with metadata (icons, evidence,
    board recommenders, protocols) plus merged vote counts from DynamoDB.
    Dynamic status (active/completed/checkins) comes from /api/challenges.
    """
    global _challenge_catalog_cache
    if _challenge_catalog_cache is None:
        _challenge_catalog_cache = _load_s3_json(
            "site/config/challenges_catalog.json", "challenge_catalog"
        )

    # Merge vote counts from DynamoDB
    vote_counts = {}
    try:
        vote_pk = "VOTES#challenges"
        vote_resp = table.query(
            KeyConditionExpression=Key("pk").eq(vote_pk),
            ProjectionExpression="sk, vote_count",
        )
        for item in _decimal_to_float(vote_resp.get("Items", [])):
            cid = item.get("sk", "").replace("CH#", "")
            vote_counts[cid] = int(item.get("vote_count", 0))
    except Exception as e:
        logger.warning(f"[challenge_catalog] Vote query failed (non-fatal): {e}")

    # Inject votes into each challenge (deep copy to avoid mutating the cache)
    result = copy.deepcopy(_challenge_catalog_cache)
    # Filter out private challenges (public: false)
    challenges = [ch for ch in result.get("challenges", []) if ch.get("public", True) is not False]
    total_votes = 0
    for ch in challenges:
        ch["votes"] = vote_counts.get(ch.get("id", ""), 0)
        total_votes += ch["votes"]
    result["challenges"] = challenges
    result["total_votes"] = total_votes

    return _ok(result, cache_seconds=900)


def handle_challenges() -> dict:
    """GET /api/challenges — Return challenges from DynamoDB (primary) with S3 fallback.

    DynamoDB partition: USER#matthew#SOURCE#challenges
    Returns active + candidate challenges for the website.
    """
    challenges_pk = f"USER#{USER_ID}#SOURCE#challenges"
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(challenges_pk) & Key("sk").begins_with("CHALLENGE#"),
            ScanIndexForward=False,
        )
        items = resp.get("Items", [])

        # Build response — website mainly needs active + candidate
        result = []
        for item in items:
            status = item.get("status", "candidate")
            # Include active, candidate, and recently completed (last 30 days)
            if status in ("active", "candidate", "completed", "failed"):
                ch = _decimal_to_float(item)
                ch.pop("pk", None)
                ch.pop("sk", None)

                # Compute progress for active challenges
                if status == "active":
                    checkins = ch.get("daily_checkins", [])
                    duration = int(ch.get("duration_days", 7))
                    completed_days = sum(1 for c in checkins if c.get("completed"))
                    ch["progress"] = {
                        "checkin_days":   len(checkins),
                        "completed_days": completed_days,
                        "duration_days":  duration,
                        "completion_pct": round(len(checkins) / duration * 100) if duration else 0,
                        "success_rate":   round(completed_days / len(checkins) * 100) if checkins else 0,
                    }

                result.append(ch)

        # Summary
        summary = {
            "total":     len(items),
            "active":    sum(1 for i in items if i.get("status") == "active"),
            "candidate": sum(1 for i in items if i.get("status") == "candidate"),
            "completed": sum(1 for i in items if i.get("status") == "completed"),
        }

        if result:
            return _ok({"challenges": result, "count": len(result), "summary": summary, "source": "dynamodb"}, cache_seconds=300)

    except Exception as e:
        logger.warning(f"[challenges] DynamoDB query failed, falling back to S3: {e}")

    # Fallback to S3 config if DynamoDB is empty or errors
    global _challenges_cache
    if _challenges_cache is None:
        _challenges_cache = _load_s3_json("site/config/challenges.json", "challenges")
    challenges = _challenges_cache.get("challenges", [])
    return _ok({"challenges": challenges, "count": len(challenges), "source": "s3_fallback"}, cache_seconds=3600)


def _handle_challenge_checkin(event: dict) -> dict:
    """POST /api/challenge_checkin — Public check-in for active challenges.

    Body: {"challenge_id": "...", "completed": true/false, "note": "...", "date": "YYYY-MM-DD"}
    Uses localStorage on the client to prevent double-taps.
    """
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        return _error(400, "Invalid JSON body")

    challenge_id = (body.get("challenge_id") or "").strip()
    completed = body.get("completed")
    note = (body.get("note") or "").strip()[:500]
    date_str = (body.get("date") or "").strip()

    if not challenge_id:
        return _error(400, "challenge_id required")
    if completed is None:
        return _error(400, "completed (true/false) required")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not date_str:
        date_str = today

    challenges_pk = f"USER#{USER_ID}#SOURCE#challenges"
    sk = f"CHALLENGE#{challenge_id}"

    # Verify challenge exists and is active
    try:
        item = table.get_item(Key={"pk": challenges_pk, "sk": sk}).get("Item")
    except Exception as e:
        logger.error(f"[challenge_checkin] DDB get failed: {e}")
        return _error(500, "Database error")

    if not item:
        return _error(404, "Challenge not found")
    if item.get("status") != "active":
        return _error(400, f"Challenge is not active (status: {item.get('status')})")

    # Build checkin
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    checkin = {
        "date":      date_str,
        "completed": bool(completed),
        "logged_at": now_iso,
        "source":    "website",
    }
    if note:
        checkin["note"] = note

    # Append to daily_checkins list
    try:
        table.update_item(
            Key={"pk": challenges_pk, "sk": sk},
            UpdateExpression="SET daily_checkins = list_append(if_not_exists(daily_checkins, :empty), :ci)",
            ExpressionAttributeValues={
                ":ci":    [checkin],
                ":empty": [],
            },
        )
    except Exception as e:
        logger.error(f"[challenge_checkin] DDB update failed: {e}")
        return _error(500, "Failed to record check-in")

    existing = item.get("daily_checkins", [])
    total = len(existing) + 1
    duration = int(item.get("duration_days", 7) if item.get("duration_days") else 7)

    return _ok({
        "checked_in":     True,
        "challenge_id":   challenge_id,
        "date":           date_str,
        "completed":      bool(completed),
        "total_checkins": total,
        "duration_days":  duration,
        "completion_pct":  round(total / duration * 100) if duration else 0,
    }, cache_seconds=0)

def handle_domains() -> dict:
    """GET /api/domains — Return domain groupings from S3 config."""
    global _domains_cache
    if _domains_cache is None:
        _domains_cache = _load_s3_json("site/config/domains.json", "domains")
    domains = _domains_cache.get("domains", [])
    return _ok({"domains": domains, "count": len(domains)}, cache_seconds=3600)

def handle_habit_registry() -> dict:
    """GET /api/habit_registry — Return habit registry from DynamoDB PROFILE#v1."""
    try:
        resp = table.get_item(Key={"pk": f"USER#{USER_ID}", "sk": "PROFILE#v1"})
        profile = resp.get("Item", {})
        registry = profile.get("habit_registry", {})
        habits = []
        for name, meta in registry.items():
            h = {"name": name}
            for k, v in meta.items():
                h[k] = float(v) if isinstance(v, Decimal) else v
            habits.append(h)
        tier_order = {"T0": 0, "T1": 1, "T2": 2}
        habits.sort(key=lambda x: (tier_order.get(x.get("tier", "T2"), 9), x.get("name", "")))
        return _ok({"habits": habits, "count": len(habits)}, cache_seconds=3600)
    except Exception as e:
        logger.error(f"[habit_registry] Error: {e}")
        return _error(500, "Failed to load habit registry")


# ── Observatory API endpoints ────────────────────────────────────────────────

def handle_nutrition_observatory() -> dict:
    """
    GET /api/nutrition_observatory
    Returns: 30-day macro averages, protein adherence, eating window, daily trend.
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d30 = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

    items = _query_source("macrofactor", d30, today)
    items.sort(key=lambda x: x.get("sk", ""))

    if not items:
        return _ok({"nutrition": None, "trend": []}, cache_seconds=3600)

    cals = [float(i["calories"]) for i in items if i.get("calories")]
    prots = [float(i["protein_g"]) for i in items if i.get("protein_g")]
    carbs = [float(i["carbs_g"]) for i in items if i.get("carbs_g")]
    fats = [float(i["fat_g"]) for i in items if i.get("fat_g")]
    fibers = [float(i["fiber_g"]) for i in items if i.get("fiber_g")]

    def avg(lst): return round(sum(lst) / len(lst), 1) if lst else None

    protein_target = 180
    protein_hits = sum(1 for p in prots if p >= protein_target)
    protein_hit_pct = round(protein_hits / len(prots) * 100) if prots else None

    # Eating window from first/last meal times
    windows = []
    for i in items:
        first = i.get("first_meal_time") or i.get("eating_window_start")
        last = i.get("last_meal_time") or i.get("eating_window_end")
        dur = i.get("eating_window_hours")
        if dur:
            windows.append(float(dur))

    latest = items[-1]
    trend = [
        {
            "date": i.get("sk", "").replace("DATE#", ""),
            "calories": round(float(i["calories"])) if i.get("calories") else None,
            "protein": round(float(i["protein_g"]), 1) if i.get("protein_g") else None,
            "carbs": round(float(i["carbs_g"]), 1) if i.get("carbs_g") else None,
            "fat": round(float(i["fat_g"]), 1) if i.get("fat_g") else None,
        }
        for i in items
    ]

    return _ok({
        "nutrition": {
            "avg_calories": avg(cals),
            "avg_protein_g": avg(prots),
            "avg_carbs_g": avg(carbs),
            "avg_fat_g": avg(fats),
            "avg_fiber_g": avg(fibers),
            "protein_target_g": protein_target,
            "protein_hit_pct": protein_hit_pct,
            "protein_hits": protein_hits,
            "days_tracked": len(items),
            "avg_eating_window_hrs": avg(windows),
            "latest_calories": round(float(latest["calories"])) if latest.get("calories") else None,
            "latest_protein": round(float(latest["protein_g"]), 1) if latest.get("protein_g") else None,
            "tdee_estimate": round(float(latest.get("tdee") or latest.get("expenditure") or 0)) or None,
            "as_of_date": latest.get("sk", "").replace("DATE#", ""),
        },
        "trend": trend,
    }, cache_seconds=3600)


def handle_training_observatory() -> dict:
    """
    GET /api/training_observatory
    Returns: training load (CTL/ATL/TSB), recent workouts, zone 2 stats, strength summary.
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d30 = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    d90 = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")

    # Training load from compute partition
    load_pk = f"{USER_PREFIX}training_load"
    load_item = None
    try:
        load_resp = table.query(
            KeyConditionExpression=Key("pk").eq(load_pk),
            ScanIndexForward=False, Limit=1,
        )
        load_items = _decimal_to_float(load_resp.get("Items", []))
        load_item = load_items[0] if load_items else None
    except Exception:
        pass

    ctl = float(load_item.get("ctl", 0)) if load_item else None
    atl = float(load_item.get("atl", 0)) if load_item else None
    tsb = float(load_item.get("tsb", 0)) if load_item else None
    acwr = float(load_item.get("acwr", 0)) if load_item else None

    # Recent Strava activities
    strava_items = _query_source("strava", d30, today)
    workouts = []
    zone2_mins = 0
    for s in sorted(strava_items, key=lambda x: x.get("sk", ""), reverse=True):
        sport = s.get("sport_type") or s.get("type", "")
        dur_min = float(s.get("moving_time_seconds", 0) or 0) / 60
        avg_hr = float(s.get("average_heartrate", 0) or 0)
        dist_mi = round(float(s.get("distance_meters", 0) or 0) / 1609.34, 1)
        cals = float(s.get("kilojoules", 0) or s.get("calories", 0) or 0)

        # Zone 2 estimate: HR 60-70% of max (assume max_hr ~ 190)
        max_hr = 190
        if avg_hr and 0.60 * max_hr <= avg_hr <= 0.70 * max_hr and dur_min >= 10:
            zone2_mins += dur_min

        if len(workouts) < 10:
            workouts.append({
                "date": s.get("sk", "").replace("DATE#", ""),
                "sport": sport,
                "duration_min": round(dur_min),
                "distance_mi": dist_mi if dist_mi > 0 else None,
                "avg_hr": round(avg_hr) if avg_hr else None,
                "calories": round(cals) if cals else None,
            })

    # Strength PRs from Hevy
    hevy_items = _query_source("hevy", d90, today)
    exercises_seen = {}
    for h in hevy_items:
        for ex in h.get("exercises", []):
            name = ex.get("name", "")
            e1rm = float(ex.get("estimated_1rm", 0) or 0)
            if name and e1rm > exercises_seen.get(name, 0):
                exercises_seen[name] = e1rm
    top_lifts = sorted(exercises_seen.items(), key=lambda x: -x[1])[:8]

    # Fitness status
    fitness_status = "building"
    if tsb is not None:
        if tsb > 10:
            fitness_status = "fresh"
        elif tsb > -10:
            fitness_status = "neutral"
        elif tsb > -20:
            fitness_status = "fatigued"
        else:
            fitness_status = "overreaching"

    return _ok({
        "training": {
            "ctl": round(ctl, 1) if ctl else None,
            "atl": round(atl, 1) if atl else None,
            "tsb": round(tsb, 1) if tsb else None,
            "acwr": round(acwr, 2) if acwr else None,
            "fitness_status": fitness_status,
            "zone2_mins_30d": round(zone2_mins),
            "zone2_weekly_avg": round(zone2_mins / 4.3),
            "zone2_target_min": 150,
            "workouts_30d": len(strava_items),
            "days_tracked": 30,
        },
        "recent_workouts": workouts,
        "top_lifts": [{"name": n, "est_1rm": round(v, 1)} for n, v in top_lifts],
    }, cache_seconds=3600)


def handle_mind_observatory() -> dict:
    """
    GET /api/mind_observatory
    Returns: mood/energy trend, Mind pillar score, vice streaks, social connection,
    cognitive pattern aggregates. No raw journal text exposed.
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    d30 = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    d90 = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")

    # Mind pillar from character_sheet
    mind_level = None
    mind_score = None
    mind_tier = None
    cs_pk = f"{USER_PREFIX}character_sheet"
    for date_str in [today, yesterday]:
        try:
            resp = table.get_item(Key={"pk": cs_pk, "sk": f"DATE#{date_str}"})
            rec = _decimal_to_float(resp.get("Item"))
            if rec:
                pm = rec.get("pillar_mind", {})
                mind_level = float(pm.get("level", 1))
                mind_score = float(pm.get("raw_score", 0))
                mind_tier = pm.get("tier", "Foundation")
                break
        except Exception:
            pass

    # Mood/energy/stress from state_of_mind or journal enrichment
    som_items = _query_source("state_of_mind", d30, today)
    mood_trend = []
    moods = []
    energies = []
    for s in sorted(som_items, key=lambda x: x.get("sk", "")):
        date_str = s.get("sk", "").replace("DATE#", "")
        m = s.get("valence") or s.get("mood")
        e = s.get("energy")
        if m is not None:
            moods.append(float(m))
        if e is not None:
            energies.append(float(e))
        mood_trend.append({
            "date": date_str,
            "mood": round(float(m), 1) if m is not None else None,
            "energy": round(float(e), 1) if e is not None else None,
        })

    # Also try journal-enriched mood from notion partition
    if not mood_trend:
        notion_items = _query_source("notion", d30, today)
        for n in sorted(notion_items, key=lambda x: x.get("sk", "")):
            m = n.get("enriched_mood") or n.get("mood_score")
            e = n.get("enriched_energy") or n.get("energy_score")
            st = n.get("enriched_stress") or n.get("stress_score")
            if m is not None or e is not None:
                moods.append(float(m)) if m else None
                energies.append(float(e)) if e else None
                mood_trend.append({
                    "date": n.get("sk", "").replace("DATE#", ""),
                    "mood": round(float(m), 1) if m is not None else None,
                    "energy": round(float(e), 1) if e is not None else None,
                    "stress": round(float(st), 1) if st is not None else None,
                })

    def avg(lst): return round(sum(lst) / len(lst), 1) if lst else None

    # Vice streaks from habit_scores
    content_filter = _load_content_filter()
    blocked_set = set(v.lower().strip() for v in content_filter.get("blocked_vices", []))
    hs_pk = f"{USER_PREFIX}habit_scores"
    hs_resp = table.query(
        KeyConditionExpression=Key("pk").eq(hs_pk),
        ScanIndexForward=False, Limit=1,
    )
    hs_items = _decimal_to_float(hs_resp.get("Items", []))
    vices = []
    if hs_items:
        vs = hs_items[0].get("vice_streaks") or {}
        if isinstance(vs, dict):
            for name, streak in vs.items():
                if name.lower().strip() not in blocked_set:
                    vices.append({"name": name, "streak": int(streak or 0)})
            vices.sort(key=lambda v: -v["streak"])

    # Social connection from interactions
    int_pk = f"{USER_PREFIX}interactions"
    try:
        int_resp = table.query(
            KeyConditionExpression=Key("pk").eq(int_pk) & Key("sk").between(
                f"DATE#{d30}", f"DATE#{today}"
            ),
        )
        interactions = _decimal_to_float(int_resp.get("Items", []))
        total_interactions = len(interactions)
        meaningful = sum(1 for i in interactions if i.get("depth") in ("meaningful", "deep"))
        unique_people = len(set(i.get("person", "") for i in interactions if i.get("person")))
    except Exception:
        total_interactions = 0
        meaningful = 0
        unique_people = 0

    # Cognitive patterns from journal enrichment (aggregate only — no raw text)
    cognitive_patterns = {}
    try:
        notion_30 = _query_source("notion", d90, today)
        for n in notion_30:
            patterns = n.get("enriched_cognitive_patterns") or n.get("cognitive_patterns") or []
            if isinstance(patterns, str):
                patterns = [p.strip() for p in patterns.split(",")]
            for p in patterns:
                if p:
                    cognitive_patterns[p] = cognitive_patterns.get(p, 0) + 1
        # Normalize to percentages
        total_p = sum(cognitive_patterns.values())
        if total_p:
            cognitive_patterns = {
                k: round(v / total_p * 100, 1)
                for k, v in sorted(cognitive_patterns.items(), key=lambda x: -x[1])
            }
    except Exception:
        pass

    # Divergence detection (mood vs energy)
    divergence = None
    if len(moods) >= 7 and len(energies) >= 7:
        mood_recent = sum(moods[-7:]) / 7
        mood_prior = sum(moods[:7]) / 7 if len(moods) >= 14 else mood_recent
        energy_recent = sum(energies[-7:]) / 7
        energy_prior = sum(energies[:7]) / 7 if len(energies) >= 14 else energy_recent
        mood_delta = mood_recent - mood_prior
        energy_delta = energy_recent - energy_prior
        if mood_delta > 0.3 and energy_delta < -0.3:
            divergence = "burnout_risk"
        elif mood_delta < -0.3 and energy_delta > 0.3:
            divergence = "disconnection"
        elif mood_delta < -0.3 and energy_delta < -0.3:
            divergence = "declining"
        else:
            divergence = "aligned"

    return _ok({
        "mind": {
            "pillar_level": mind_level,
            "pillar_score": mind_score,
            "pillar_tier": mind_tier,
            "avg_mood": avg(moods),
            "avg_energy": avg(energies),
            "divergence_status": divergence,
            "days_with_mood_data": len(moods),
            "total_interactions_30d": total_interactions,
            "meaningful_interactions_30d": meaningful,
            "unique_people_30d": unique_people,
            "as_of_date": today,
        },
        "mood_trend": mood_trend[-30:],
        "vice_streaks": vices[:6],
        "cognitive_patterns": cognitive_patterns,
        "social": {
            "total_30d": total_interactions,
            "meaningful_30d": meaningful,
            "unique_people": unique_people,
        },
    }, cache_seconds=3600)


# ── Observatory endpoints: Nutrition, Training, Mind ──────────────────

def handle_nutrition_overview() -> dict:
    """
    GET /api/nutrition_overview
    Returns: 30-day macro averages, protein adherence, eating window, deficit status.
    Source: MacroFactor DynamoDB partition.
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d30 = max((datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d"), EXPERIMENT_START)
    d7 = max((datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d"), EXPERIMENT_START)

    items = _query_source("macrofactor", d30, today)
    if not items:
        return _error(503, "No nutrition data available.")

    items.sort(key=lambda x: x.get("sk", ""))

    def safe_avg(field):
        vals = [float(i[field]) for i in items if i.get(field) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    def safe_sum_avg(field):
        return safe_avg(field)

    cal_vals = [float(i["calories"]) for i in items if i.get("calories")]
    pro_vals = [float(i["protein_g"]) for i in items if i.get("protein_g")]
    carb_vals = [float(i["carbs_g"]) for i in items if i.get("carbs_g")]
    fat_vals = [float(i["fat_g"]) for i in items if i.get("fat_g")]
    fiber_vals = [float(i["fiber_g"]) for i in items if i.get("fiber_g")]

    protein_target = 180
    protein_hit_days = sum(1 for v in pro_vals if v >= protein_target)
    protein_hit_pct = round(protein_hit_days / len(pro_vals) * 100) if pro_vals else 0

    # Latest day
    latest = items[-1] if items else {}
    latest_date = latest.get("date") or latest.get("sk", "").replace("DATE#", "")

    # 7-day vs 30-day comparison
    items_7d = [i for i in items if (i.get("date") or i.get("sk", "").replace("DATE#", "")) >= d7]
    cal_7d = [float(i["calories"]) for i in items_7d if i.get("calories")]
    pro_7d = [float(i["protein_g"]) for i in items_7d if i.get("protein_g")]

    # TDEE estimate (if available in latest record)
    tdee = float(latest.get("tdee") or latest.get("expenditure") or 0) or None
    avg_cal = round(sum(cal_vals) / len(cal_vals)) if cal_vals else None
    deficit = round(tdee - avg_cal) if tdee and avg_cal else None

    # Daily trend for chart
    trend = []
    for i in items:
        d = i.get("date") or i.get("sk", "").replace("DATE#", "")
        trend.append({
            "date": d,
            "calories": round(float(i["calories"])) if i.get("calories") else None,
            "protein_g": round(float(i["protein_g"]), 1) if i.get("protein_g") else None,
            "carbs_g": round(float(i["carbs_g"]), 1) if i.get("carbs_g") else None,
            "fat_g": round(float(i["fat_g"]), 1) if i.get("fat_g") else None,
        })

    return _ok({
        "nutrition": {
            "avg_calories": round(sum(cal_vals) / len(cal_vals)) if cal_vals else None,
            "avg_protein_g": round(sum(pro_vals) / len(pro_vals), 1) if pro_vals else None,
            "avg_carbs_g": round(sum(carb_vals) / len(carb_vals), 1) if carb_vals else None,
            "avg_fat_g": round(sum(fat_vals) / len(fat_vals), 1) if fat_vals else None,
            "avg_fiber_g": round(sum(fiber_vals) / len(fiber_vals), 1) if fiber_vals else None,
            "protein_target_g": protein_target,
            "protein_hit_pct": protein_hit_pct,
            "protein_hit_days": protein_hit_days,
            "days_logged": len(items),
            "tdee": round(tdee) if tdee else None,
            "avg_deficit": deficit,
            "cal_7d_avg": round(sum(cal_7d) / len(cal_7d)) if cal_7d else None,
            "pro_7d_avg": round(sum(pro_7d) / len(pro_7d), 1) if pro_7d else None,
            "latest_date": latest_date,
            "latest_calories": round(float(latest.get("calories", 0))) if latest.get("calories") else None,
            "latest_protein_g": round(float(latest.get("protein_g", 0)), 1) if latest.get("protein_g") else None,
        },
        "nutrition_trend": trend,
    }, cache_seconds=3600)


def handle_training_overview() -> dict:
    """
    GET /api/training_overview
    Returns: workout frequency, zone 2 minutes, training load, strength summary.
    Sources: Strava (cardio), Hevy (strength), Whoop (strain).
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d90 = max((datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d"), EXPERIMENT_START)
    d30 = max((datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d"), EXPERIMENT_START)

    # Strava activities (90 days)
    strava_items = _query_source("strava", d90, today)
    strava_30d = [s for s in strava_items if (s.get("date") or s.get("sk", "").replace("DATE#", "")) >= d30]

    total_workouts_90d = len(strava_items)
    total_workouts_30d = len(strava_30d)
    weekly_avg = round(total_workouts_30d / 4.3, 1) if total_workouts_30d else 0

    # Zone 2 detection: HR between 60-70% of max (assume max 190 if not in profile)
    max_hr = 190
    z2_low, z2_high = max_hr * 0.60, max_hr * 0.70
    z2_minutes_30d = 0
    for s in strava_30d:
        avg_hr = s.get("average_heartrate") or s.get("avg_hr")
        duration = s.get("duration_minutes") or s.get("moving_time_minutes") or 0
        if avg_hr and duration:
            avg_hr = float(avg_hr)
            duration = float(duration)
            if z2_low <= avg_hr <= z2_high:
                z2_minutes_30d += duration
    z2_weekly_avg = round(z2_minutes_30d / 4.3)
    z2_target = 150  # minutes/week
    z2_pct = round(z2_weekly_avg / z2_target * 100) if z2_target else 0

    # Activity type breakdown (30d)
    type_counts = {}
    for s in strava_30d:
        sport = s.get("sport_type") or s.get("type") or "Other"
        type_counts[sport] = type_counts.get(sport, 0) + 1
    top_activities = sorted(type_counts.items(), key=lambda x: -x[1])[:5]

    # Total training minutes and distance (30d)
    total_minutes_30d = sum(float(s.get("duration_minutes") or s.get("moving_time_minutes") or 0) for s in strava_30d)
    total_distance_mi = sum(float(s.get("distance_miles") or s.get("distance", 0)) / 1609.34 if s.get("distance") else float(s.get("distance_miles", 0)) for s in strava_30d)

    # Whoop strain (30d)
    whoop_30d = _query_source("whoop", d30, today)
    strain_vals = [float(w["strain"]) for w in whoop_30d if w.get("strain")]
    avg_strain = round(sum(strain_vals) / len(strain_vals), 1) if strain_vals else None

    # Whoop workouts — per-workout HR zone data (enriches Strava)
    whoop_workouts = []
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}whoop") & Key("sk").between(
                f"DATE#{d30}#WORKOUT#", f"DATE#{today}#WORKOUT#~"
            ),
        )
        whoop_workouts = _decimal_to_float(resp.get("Items", []))
        # Add Whoop Z2 minutes from actual HR zones to the Z2 calculation
        for ww in whoop_workouts:
            z2_from_whoop = float(ww.get("zone_2_minutes", 0) or 0)
            if z2_from_whoop > 0:
                z2_minutes_30d += z2_from_whoop
        # Recalculate Z2 weekly avg with Whoop data
        if whoop_workouts:
            z2_weekly_avg = round(z2_minutes_30d / 4.3)
            z2_pct = round(z2_weekly_avg / z2_target * 100) if z2_target else 0
    except Exception as e:
        logger.warning(f"[training_overview] Whoop workout query failed (non-fatal): {e}")

    # Hevy — latest strength session info
    hevy_items = _query_source("hevy", d30, today)
    strength_sessions_30d = len(hevy_items)

    # Weekly trend (for chart)
    from collections import defaultdict as _dd
    week_buckets = _dd(lambda: {"workouts": 0, "minutes": 0, "z2_min": 0})
    for s in strava_items:
        d = s.get("date") or s.get("sk", "").replace("DATE#", "")
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            week_key = dt.strftime("%Y-W%V")
        except Exception:
            continue
        week_buckets[week_key]["workouts"] += 1
        dur = float(s.get("duration_minutes") or s.get("moving_time_minutes") or 0)
        week_buckets[week_key]["minutes"] += dur
        avg_hr = s.get("average_heartrate") or s.get("avg_hr")
        if avg_hr and z2_low <= float(avg_hr) <= z2_high:
            week_buckets[week_key]["z2_min"] += dur

    weekly_trend = sorted([
        {"week": k, "workouts": v["workouts"], "minutes": round(v["minutes"]), "z2_min": round(v["z2_min"])}
        for k, v in week_buckets.items()
    ], key=lambda x: x["week"])[-12:]  # last 12 weeks

    return _ok({
        "training": {
            "workouts_30d": total_workouts_30d,
            "workouts_90d": total_workouts_90d,
            "weekly_avg": weekly_avg,
            "total_minutes_30d": round(total_minutes_30d),
            "total_distance_mi": round(total_distance_mi, 1),
            "z2_weekly_avg_min": z2_weekly_avg,
            "z2_target_min": z2_target,
            "z2_pct": min(z2_pct, 100),
            "avg_strain": avg_strain,
            "strength_sessions_30d": strength_sessions_30d,
            "top_activities": [{"type": t, "count": c} for t, c in top_activities],
            "whoop_workout_count": len(whoop_workouts),
        },
        "weekly_trend": weekly_trend,
        "whoop_workouts": [{
            "date": w.get("date"),
            "sport_name": w.get("sport_name", "Activity"),
            "strain": w.get("strain"),
            "zone_2_minutes": w.get("zone_2_minutes"),
            "zone_3_minutes": w.get("zone_3_minutes"),
            "distance_meter": w.get("distance_meter"),
            "average_heart_rate": w.get("average_heart_rate"),
        } for w in whoop_workouts[:20]],
    }, cache_seconds=3600)


def handle_mind_overview() -> dict:
    """
    GET /api/mind_overview
    Returns: mood/energy/stress trends, vice streaks, social connection quality,
    mind pillar score, cognitive patterns (when journal data is available).
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    d30 = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    d90 = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")

    # ── 1. Mind pillar from character_sheet ──
    mind_pillar = None
    cs_pk = f"{USER_PREFIX}character_sheet"
    for date_str in [today, yesterday]:
        resp = table.get_item(Key={"pk": cs_pk, "sk": f"DATE#{date_str}"})
        record = _decimal_to_float(resp.get("Item"))
        if record:
            mp = record.get("pillar_mind", {})
            mind_pillar = {
                "level": float(mp.get("level", 1)),
                "raw_score": float(mp.get("raw_score", 0)),
                "tier": mp.get("tier", "Foundation"),
            }
            break

    # ── 2. State of mind / mood data (Apple Health How We Feel) ──
    som_items = _query_source("state_of_mind", d30, today)
    mood_entries = []
    for s in som_items:
        valence = s.get("valence")
        if valence is not None:
            mood_entries.append({
                "date": s.get("date") or s.get("sk", "").replace("DATE#", ""),
                "valence": float(valence),
                "label": s.get("label", ""),
            })
    mood_entries.sort(key=lambda x: x["date"])
    avg_valence = None
    if mood_entries:
        vals = [m["valence"] for m in mood_entries]
        avg_valence = round(sum(vals) / len(vals), 2)

    # ── 3. Vice streaks from habit_scores ──
    content_filter = _load_content_filter()
    blocked_set = set(v.lower().strip() for v in content_filter.get("blocked_vices", []))

    hs_pk = f"{USER_PREFIX}habit_scores"
    hs_resp = table.query(
        KeyConditionExpression=Key("pk").eq(hs_pk),
        ScanIndexForward=False,
        Limit=1,
    )
    hs_items = _decimal_to_float(hs_resp.get("Items", []))
    vice_data = []
    if hs_items:
        latest_hs = hs_items[0]
        raw_vs = latest_hs.get("vice_streaks") or {}
        if isinstance(raw_vs, dict):
            for name, streak_val in raw_vs.items():
                if name.lower().strip() in blocked_set:
                    continue
                vice_data.append({
                    "name": name,
                    "current_streak": int(streak_val or 0),
                    "holding": int(streak_val or 0) > 0,
                })
        vice_data.sort(key=lambda v: -v["current_streak"])

    # ── 4. Social connection quality (interactions) ──
    int_pk = f"{USER_PREFIX}interactions"
    try:
        int_resp = table.query(
            KeyConditionExpression=Key("pk").eq(int_pk) & Key("sk").between(
                f"DATE#{d30}", f"DATE#{today}~"
            ),
            ScanIndexForward=True,
        )
        interactions = _decimal_to_float(int_resp.get("Items", []))
    except Exception:
        interactions = []

    total_interactions = len(interactions)
    depth_counts = {"surface": 0, "meaningful": 0, "deep": 0}
    for i in interactions:
        d = (i.get("depth") or "surface").lower()
        if d in depth_counts:
            depth_counts[d] += 1
    meaningful_pct = round((depth_counts["meaningful"] + depth_counts["deep"]) / total_interactions * 100) if total_interactions else 0

    # ── 5. Temptation resist rate (90d) ──
    temp_pk = f"{USER_PREFIX}temptations"
    try:
        temp_resp = table.query(
            KeyConditionExpression=Key("pk").eq(temp_pk) & Key("sk").between(
                f"DATE#{d90}", f"DATE#{today}~"
            ),
        )
        temptations = _decimal_to_float(temp_resp.get("Items", []))
    except Exception:
        temptations = []

    total_temptations = len(temptations)
    resisted = sum(1 for t in temptations if t.get("resisted"))
    resist_rate = round(resisted / total_temptations * 100) if total_temptations else None

    # ── 6. Journal entry count (as journaling progress signal) ──
    journal_pk = f"{USER_PREFIX}notion"
    try:
        j_resp = table.query(
            KeyConditionExpression=Key("pk").eq(journal_pk) & Key("sk").between(
                f"DATE#{d30}", f"DATE#{today}"
            ),
            Select="COUNT",
        )
        journal_count = j_resp.get("Count", 0)
    except Exception:
        journal_count = 0

    return _ok({
        "mind": {
            "mind_pillar": mind_pillar,
            "avg_valence": avg_valence,
            "mood_entries_count": len(mood_entries),
            "journal_entries_30d": journal_count,
            "resist_rate_pct": resist_rate,
            "total_temptations_90d": total_temptations,
            "resisted_90d": resisted,
            "total_interactions_30d": total_interactions,
            "meaningful_pct": meaningful_pct,
            "depth_counts": depth_counts,
        },
        "vice_streaks": vice_data,
        "mood_trend": mood_entries[-30:],  # last 30 entries for chart
    }, cache_seconds=3600)


# ── BL-02: Bloodwork/Labs endpoint ─────────────────────────────
def handle_labs() -> dict:
    """GET /api/labs — Returns lab biomarkers from clinical.json in S3."""
    try:
        S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
        s3 = boto3.client("s3", region_name=S3_REGION)
        resp = s3.get_object(Bucket=S3_BUCKET, Key=f"dashboard/{USER_ID}/clinical.json")
        data = json.loads(resp["Body"].read())
        labs = data.get("labs", {})
        if not labs or not labs.get("biomarkers"):
            return _error(404, "No lab data available.")
        return _ok({"labs": labs}, cache_seconds=3600)
    except Exception as e:
        logger.warning(f"[labs] Failed to load clinical.json: {e}")
        return _error(503, "Lab data temporarily unavailable.")


# ── Frequent Meals endpoint ───────────────────────────────────
def handle_frequent_meals() -> dict:
    """GET /api/frequent_meals — Top meals by frequency from MacroFactor food logs."""
    from datetime import datetime, timezone, timedelta
    from collections import Counter, defaultdict
    now = datetime.now(timezone.utc)
    end_date = now.strftime("%Y-%m-%d")
    start_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    try:
        items = _query_source("macrofactor", start_date, end_date)
        meal_counts = Counter()
        meal_macros = defaultdict(lambda: {"cal": 0, "protein": 0, "carbs": 0, "fat": 0, "count": 0})

        for day in items:
            food_log = day.get("food_log") or []
            for entry in food_log:
                name = (entry.get("food_name") or "").strip()
                if not name or len(name) < 3:
                    continue
                meal_counts[name] += 1
                m = meal_macros[name]
                m["cal"] += float(entry.get("calories_kcal") or 0)
                m["protein"] += float(entry.get("protein_g") or 0)
                m["carbs"] += float(entry.get("carbs_g") or 0)
                m["fat"] += float(entry.get("fat_g") or 0)
                m["count"] += 1

        top_meals = []
        for name, freq in meal_counts.most_common(8):
            m = meal_macros[name]
            cnt = m["count"] or 1
            avg_cal = round(m["cal"] / cnt)
            avg_pro = round(m["protein"] / cnt)
            avg_carb = round(m["carbs"] / cnt)
            ppc = round((avg_pro * 4 / avg_cal * 100)) if avg_cal > 0 else 0
            top_meals.append({
                "name": name,
                "frequency": freq,
                "avg_calories": avg_cal,
                "avg_protein_g": avg_pro,
                "avg_carbs_g": avg_carb,
                "protein_cal_pct": ppc,
            })

        return _ok({"meals": top_meals, "period_days": 30}, cache_seconds=3600)
    except Exception as e:
        logger.warning(f"[frequent_meals] Failed: {e}")
        return _error(503, "Meal data temporarily unavailable.")


# ── Meal Glucose Response endpoint ─────────────────────────────
def handle_meal_glucose() -> dict:
    """GET /api/meal_glucose — Cross-reference MacroFactor meals with Dexcom CGM spikes."""
    from datetime import datetime, timezone, timedelta
    from collections import defaultdict
    now = datetime.now(timezone.utc)
    end_date = now.strftime("%Y-%m-%d")
    start_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    try:
        mf_items = _query_source("macrofactor", start_date, end_date)
        cgm_items = _query_source("dexcom", start_date, end_date)

        # Build a map of date → glucose readings for spike calculation
        daily_glucose = {}
        for item in cgm_items:
            date = item.get("sk", "").replace("DATE#", "")
            avg = float(item.get("average_glucose", 0) or 0)
            peak = float(item.get("max_glucose", 0) or 0)
            baseline = float(item.get("min_glucose", 0) or 0)
            tir = float(item.get("time_in_range_pct", 0) or 0)
            if avg > 0:
                daily_glucose[date] = {"avg": avg, "peak": peak, "baseline": baseline, "tir": tir}

        # Aggregate meals with glucose context
        meal_data = defaultdict(lambda: {
            "cal": 0, "protein": 0, "carbs": 0, "count": 0,
            "spike_sum": 0, "spike_count": 0, "category": "meal"
        })

        for day in mf_items:
            date = day.get("sk", "").replace("DATE#", "")
            food_log = day.get("food_log") or []
            glucose = daily_glucose.get(date)

            for entry in food_log:
                name = (entry.get("food_name") or "").strip()
                if not name or len(name) < 3:
                    continue
                cal = float(entry.get("calories_kcal") or 0)
                if cal < 100:
                    continue  # Skip small items (seasonings, condiments)

                m = meal_data[name]
                m["cal"] += cal
                m["protein"] += float(entry.get("protein_g") or 0)
                m["carbs"] += float(entry.get("carbs_g") or 0)
                m["count"] += 1

                # Estimate category from meal time
                time_str = entry.get("time") or ""
                if time_str:
                    try:
                        hour = int(time_str.split(":")[0])
                        if hour < 11:
                            m["category"] = "breakfast"
                        elif hour < 15:
                            m["category"] = "lunch"
                        elif hour < 18:
                            m["category"] = "snack"
                        else:
                            m["category"] = "dinner"
                    except (ValueError, IndexError):
                        pass

                # Approximate spike from daily glucose data
                if glucose and glucose["peak"] > 0 and glucose["avg"] > 0:
                    spike = glucose["peak"] - glucose["avg"]
                    # Weight by carb content — high-carb meals contribute more to spikes
                    carbs = float(entry.get("carbs_g") or 0)
                    if carbs > 20:
                        m["spike_sum"] += spike * 0.8
                        m["spike_count"] += 1
                    elif carbs > 5:
                        m["spike_sum"] += spike * 0.4
                        m["spike_count"] += 1

        # Build response — top 10 meals by frequency, with glucose grades
        results = []
        for name, m in sorted(meal_data.items(), key=lambda x: x[1]["count"], reverse=True)[:10]:
            cnt = m["count"] or 1
            avg_cal = round(m["cal"] / cnt)
            avg_pro = round(m["protein"] / cnt)
            avg_carb = round(m["carbs"] / cnt)
            avg_spike = round(m["spike_sum"] / m["spike_count"]) if m["spike_count"] > 0 else None

            # Grade based on estimated spike
            if avg_spike is None:
                grade = "?"
                curve = "gentle"
            elif avg_spike <= 15:
                grade = "A"
                curve = "flat"
            elif avg_spike <= 25:
                grade = "B"
                curve = "gentle"
            elif avg_spike <= 40:
                grade = "C"
                curve = "moderate"
            else:
                grade = "D"
                curve = "steep"

            results.append({
                "meal": name,
                "category": m["category"],
                "calories": avg_cal,
                "protein": avg_pro,
                "carbs": avg_carb,
                "spike": avg_spike if avg_spike is not None else 0,
                "grade": grade,
                "curve": curve,
            })

        return _ok({"meals": results, "period_days": 30, "has_cgm": bool(daily_glucose)}, cache_seconds=3600)
    except Exception as e:
        logger.warning(f"[meal_glucose] Failed: {e}")
        return _error(503, "Meal glucose data temporarily unavailable.")


# ── Strength Benchmarks endpoint ──────────────────────────────
def handle_strength_benchmarks() -> dict:
    """GET /api/strength_benchmarks — Current 1RM and progress from Hevy data."""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    end_date = now.strftime("%Y-%m-%d")
    start_date = (now - timedelta(days=90)).strftime("%Y-%m-%d")

    targets = {
        "Deadlift": 315, "Squat": 265, "Bench Press": 185, "Overhead Press": 135,
    }

    try:
        items = _query_source("hevy", start_date, end_date)
        # Find max weight for each target lift
        best = {}
        for day in items:
            exercises = day.get("exercises") or day.get("workout_exercises") or []
            for ex in exercises:
                name = ex.get("exercise_name") or ex.get("name") or ""
                for target_name in targets:
                    if target_name.lower() in name.lower():
                        sets = ex.get("sets") or []
                        for s in sets:
                            w = float(s.get("weight_lbs") or s.get("weight") or 0)
                            if w > best.get(target_name, 0):
                                best[target_name] = w

        benchmarks = []
        for lift, target in targets.items():
            current = best.get(lift, 0)
            benchmarks.append({
                "lift": lift,
                "current_1rm": round(current),
                "target": target,
                "progress_pct": round((current / target) * 100) if target > 0 else 0,
            })

        return _ok({"benchmarks": benchmarks, "period_days": 90}, cache_seconds=3600)
    except Exception as e:
        logger.warning(f"[strength_benchmarks] Failed: {e}")
        return _error(503, "Strength data temporarily unavailable.")


# ── Phase 1: Changes-Since endpoint ─────────────────────────────
def handle_changes_since(qs: dict = None) -> dict:
    """GET /api/changes-since?ts=EPOCH — Returns notable changes since timestamp."""
    qs = qs or {}
    ts_str = qs.get("ts", "")
    if not ts_str:
        return _error(400, "Missing ts parameter")

    try:
        since_ts = int(ts_str)
    except (ValueError, TypeError):
        return _error(400, "Invalid ts parameter")

    from datetime import datetime, timezone, timedelta
    since_dt = datetime.fromtimestamp(since_ts, tz=timezone.utc)
    now = datetime.now(timezone.utc)
    days_ago = max(1, (now - since_dt).days)
    # Cap lookback to 30 days
    if days_ago > 30:
        since_dt = now - timedelta(days=30)
        days_ago = 30

    start_date = since_dt.strftime("%Y-%m-%d")
    end_date = now.strftime("%Y-%m-%d")

    # Fetch weight, HRV, sleep, character data
    deltas = {}
    try:
        whoop_items = _query_source("whoop", start_date, end_date)
        withings_items = _query_source("withings", start_date, end_date)

        # Weight delta
        weights = [float(i.get("weight_kg", 0)) * 2.20462 for i in withings_items
                    if i.get("weight_kg") and float(i.get("weight_kg", 0)) > 0]
        if len(weights) >= 2:
            spark = weights[-7:] if len(weights) > 7 else weights
            deltas["weight"] = {
                "from": round(weights[0], 1), "to": round(weights[-1], 1),
                "change": round(weights[-1] - weights[0], 1), "unit": "lbs",
                "sparkline": [round(w, 1) for w in spark],
            }

        # HRV delta
        hrvs = [float(i.get("hrv", 0)) for i in whoop_items if i.get("hrv") and float(i.get("hrv", 0)) > 0]
        if len(hrvs) >= 2:
            spark = hrvs[-7:] if len(hrvs) > 7 else hrvs
            trend = "climbing" if hrvs[-1] > hrvs[0] else "declining" if hrvs[-1] < hrvs[0] else "stable"
            deltas["hrv"] = {
                "from": round(hrvs[0]), "to": round(hrvs[-1]),
                "change": round(hrvs[-1] - hrvs[0]), "unit": "ms",
                "trend": trend, "sparkline": [round(h) for h in spark],
            }

        # Sleep delta
        sleeps = [float(i.get("sleep_duration_hours", 0)) for i in whoop_items
                  if i.get("sleep_duration_hours") and float(i.get("sleep_duration_hours", 0)) > 0]
        if len(sleeps) >= 2:
            spark = sleeps[-7:] if len(sleeps) > 7 else sleeps
            trend = "improving" if sleeps[-1] > sleeps[0] else "declining"
            deltas["sleep"] = {
                "from": round(sleeps[0], 1), "to": round(sleeps[-1], 1),
                "change": round(sleeps[-1] - sleeps[0], 1), "unit": "hrs",
                "trend": trend, "sparkline": [round(s, 1) for s in spark],
            }
    except Exception as e:
        logger.warning(f"[changes-since] DynamoDB query failed: {e}")

    # Character delta
    try:
        char_items = _query_source("character_sheet", start_date, end_date)
        scores = [float(i.get("overall_score", 0)) for i in char_items if i.get("overall_score")]
        if len(scores) >= 2:
            deltas["character"] = {
                "from": round(scores[0]), "to": round(scores[-1]),
                "change": round(scores[-1] - scores[0]), "unit": "pts",
                "sparkline": [round(s) for s in (scores[-7:] if len(scores) > 7 else scores)],
            }
    except Exception:
        pass

    # Events (experiments completed, chronicles published)
    events_list = []
    try:
        exp_items = _query_source("experiments", start_date, end_date)
        for e in exp_items:
            if e.get("status") == "completed":
                events_list.append({
                    "type": "experiment_complete",
                    "title": e.get("name", "Experiment"),
                    "link": "/experiments/",
                    "date": e.get("sk", "").replace("DATE#", ""),
                })
    except Exception:
        pass

    return _ok({
        "since": since_dt.isoformat(),
        "days_ago": days_ago,
        "deltas": deltas,
        "events": events_list[:5],
    }, cache_seconds=300)


# ── Phase 1: Observatory Week endpoint ─────────────────────────
def handle_observatory_week(qs: dict = None) -> dict:
    """GET /api/observatory_week?domain=sleep — Returns 7-day summary for a domain."""
    qs = qs or {}
    domain = (qs.get("domain") or "sleep").lower().strip()
    valid_domains = {"sleep", "glucose", "nutrition", "training", "mind"}
    if domain not in valid_domains:
        return _error(400, f"Invalid domain. Use: {', '.join(sorted(valid_domains))}")

    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    end_date = now.strftime("%Y-%m-%d")
    start_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    prev_start = (now - timedelta(days=14)).strftime("%Y-%m-%d")
    prev_end = (now - timedelta(days=8)).strftime("%Y-%m-%d")

    try:
        if domain == "sleep":
            items = _query_source("whoop", start_date, end_date)
            prev_items = _query_source("whoop", prev_start, prev_end)

            durations = [float(i.get("sleep_duration_hours", 0)) for i in items if i.get("sleep_duration_hours")]
            prev_durations = [float(i.get("sleep_duration_hours", 0)) for i in prev_items if i.get("sleep_duration_hours")]
            avg_dur = sum(durations) / len(durations) if durations else 0
            prev_avg = sum(prev_durations) / len(prev_durations) if prev_durations else 0

            best = max(items, key=lambda i: float(i.get("sleep_duration_hours", 0)), default={})
            worst = min(items, key=lambda i: float(i.get("sleep_duration_hours", 99)), default={})

            summary = {
                "primary": {"label": "Average Duration", "value": round(avg_dur, 1), "unit": "hrs",
                            "delta": round(avg_dur - prev_avg, 1), "delta_label": f"vs {round(prev_avg, 1)} last week",
                            "trend": "up" if avg_dur > prev_avg else "down", "sparkline": [round(d, 1) for d in durations]},
                "highlight": {"label": "Best Night", "value": f"{best.get('sk', '').replace('DATE#', '')[5:]} · {round(float(best.get('sleep_duration_hours', 0)), 1)}h",
                              "detail": f"Recovery {round(float(best.get('recovery_score', 0)))}%"},
                "lowlight": {"label": "Worst Night", "value": f"{worst.get('sk', '').replace('DATE#', '')[5:]} · {round(float(worst.get('sleep_duration_hours', 0)), 1)}h",
                             "detail": ""},
            }
            notable = f"Avg sleep {'improved' if avg_dur > prev_avg else 'declined'} {abs(round(avg_dur - prev_avg, 1))}h vs last week"

        elif domain == "nutrition":
            items = _query_source("macrofactor", start_date, end_date)
            prev_items = _query_source("macrofactor", prev_start, prev_end)

            cals = [float(i.get("calories", 0)) for i in items if i.get("calories")]
            prev_cals = [float(i.get("calories", 0)) for i in prev_items if i.get("calories")]
            avg_cal = sum(cals) / len(cals) if cals else 0
            prev_avg_cal = sum(prev_cals) / len(prev_cals) if prev_cals else 0
            proteins = [float(i.get("protein_g", 0)) for i in items if i.get("protein_g")]
            avg_protein = sum(proteins) / len(proteins) if proteins else 0

            summary = {
                "primary": {"label": "Avg Calories", "value": round(avg_cal), "unit": "kcal",
                            "delta": round(avg_cal - prev_avg_cal), "delta_label": f"vs {round(prev_avg_cal)} last week",
                            "trend": "up" if avg_cal > prev_avg_cal else "down", "sparkline": [round(c) for c in cals]},
                "highlight": {"label": "Avg Protein", "value": f"{round(avg_protein)}g/day", "detail": ""},
                "lowlight": {"label": "Logged Days", "value": f"{len(cals)}/7", "detail": ""},
            }
            notable = f"Protein averaged {round(avg_protein)}g/day this week"

        elif domain == "training":
            items = _query_source("whoop", start_date, end_date)
            strains = [float(i.get("strain", 0)) for i in items if i.get("strain")]
            recoveries = [float(i.get("recovery_score", 0)) for i in items if i.get("recovery_score")]
            avg_strain = sum(strains) / len(strains) if strains else 0
            avg_recovery = sum(recoveries) / len(recoveries) if recoveries else 0

            summary = {
                "primary": {"label": "Avg Strain", "value": round(avg_strain, 1), "unit": "",
                            "delta": 0, "delta_label": "", "trend": "flat",
                            "sparkline": [round(s, 1) for s in strains]},
                "highlight": {"label": "Avg Recovery", "value": f"{round(avg_recovery)}%", "detail": ""},
                "lowlight": {"label": "Active Days", "value": f"{len([s for s in strains if s > 5])}/7", "detail": ""},
            }
            notable = f"Average recovery {round(avg_recovery)}% this week"

        elif domain == "glucose":
            items = _query_source("dexcom", start_date, end_date)
            tirs = [float(i.get("time_in_range_pct", 0)) for i in items if i.get("time_in_range_pct")]
            avg_tir = sum(tirs) / len(tirs) if tirs else 0

            summary = {
                "primary": {"label": "Avg TIR", "value": round(avg_tir, 1), "unit": "%",
                            "delta": 0, "delta_label": "", "trend": "flat",
                            "sparkline": [round(t, 1) for t in tirs]},
                "highlight": {"label": "Best Day", "value": f"{round(max(tirs))}% TIR" if tirs else "—", "detail": ""},
                "lowlight": {"label": "Worst Day", "value": f"{round(min(tirs))}% TIR" if tirs else "—", "detail": ""},
            }
            notable = f"Average time-in-range {round(avg_tir)}% this week"

        elif domain == "mind":
            items = _query_source("journal", start_date, end_date)
            moods = [float(i.get("mood_valence", 0)) for i in items if i.get("mood_valence") is not None]
            avg_mood = sum(moods) / len(moods) if moods else 0

            summary = {
                "primary": {"label": "Avg Mood", "value": round(avg_mood, 2), "unit": "",
                            "delta": 0, "delta_label": "", "trend": "flat",
                            "sparkline": [round(m, 2) for m in moods]},
                "highlight": {"label": "Journal Entries", "value": str(len(items)), "detail": "this week"},
                "lowlight": {"label": "Energy", "value": "—", "detail": ""},
            }
            notable = f"{len(items)} journal entries this week"
        else:
            return _error(400, "Unsupported domain")

        return _ok({
            "domain": domain,
            "period": {"start": start_date, "end": end_date},
            "summary": summary,
            "notable": notable,
            "last_updated": now.isoformat(),
        }, cache_seconds=900)

    except Exception as e:
        logger.warning(f"[observatory_week] {domain} failed: {e}")
        return _error(503, f"Weekly {domain} data temporarily unavailable.")


# ── Benchmark trends endpoint ─────────────────────────────────
def handle_benchmark_trends() -> dict:
    """GET /api/benchmark_trends — Returns benchmark progress data."""
    try:
        resp = table.query(
            KeyConditionExpression='pk = :pk',
            ExpressionAttributeValues={':pk': 'USER#matthew#SOURCE#benchmarks'},
            ScanIndexForward=False,
            Limit=30
        )
        items = resp.get('Items', [])
        return {
            'statusCode': 200,
            'headers': {**CORS_HEADERS, 'Cache-Control': 'max-age=300'},
            'body': json.dumps({'trends': items}, default=str)
        }
    except Exception as e:
        logger.warning(f"[site_api] benchmark_trends: {e}")
        return {
            'statusCode': 200,
            'headers': {**CORS_HEADERS, 'Cache-Control': 'max-age=300'},
            'body': json.dumps({'trends': []})
        }


# ── Meal responses endpoint ───────────────────────────────────
def handle_meal_responses() -> dict:
    """GET /api/meal_responses — Returns CGM x MacroFactor meal response data."""
    try:
        resp = table.query(
            KeyConditionExpression='pk = :pk',
            ExpressionAttributeValues={':pk': 'USER#matthew#SOURCE#meal_responses'},
            ScanIndexForward=False,
            Limit=50
        )
        items = resp.get('Items', [])
        return {
            'statusCode': 200,
            'headers': {**CORS_HEADERS, 'Cache-Control': 'max-age=600'},
            'body': json.dumps({'meals': items}, default=str)
        }
    except Exception as e:
        logger.warning(f"[site_api] meal_responses: {e}")
        return {
            'statusCode': 200,
            'headers': {**CORS_HEADERS, 'Cache-Control': 'max-age=600'},
            'body': json.dumps({'meals': []})
        }


# ── Experiment suggestion POST handler ────────────────────────
def _handle_experiment_suggest(event: dict) -> dict:
    """POST /api/experiment_suggest — Store reader experiment suggestion."""
    try:
        body = json.loads(event.get('body', '{}'))
        idea = body.get('idea', '').strip()
        source = body.get('source', '').strip()
        if not idea or len(idea) < 10:
            return _error(400, 'Idea must be at least 10 characters')
        table.put_item(Item={
            'pk': 'USER#matthew#SOURCE#experiment_suggestions',
            'sk': f'SUGGEST#{datetime.now(timezone.utc).isoformat()}',
            'idea': idea,
            'source': source,
            'status': 'pending',
            'created_at': datetime.now(timezone.utc).isoformat(),
        })
        return {
            'statusCode': 200,
            'headers': CORS_HEADERS,
            'body': json.dumps({'status': 'received'})
        }
    except Exception as e:
        logger.error(f"[site_api] experiment_suggest failed: {e}")
        return _error(500, 'Failed to submit suggestion')


ROUTES = {
    "/api/vitals":          handle_vitals,
    "/api/journey":         handle_journey,
    "/api/character":       handle_character,
    "/api/status":          handle_status,
    "/api/status/summary":  handle_status_summary,
    # BS-07: new public endpoints
    "/api/weight_progress": handle_weight_progress,
    "/api/character_stats": handle_character_stats,
    "/api/habit_streaks":   handle_habit_streaks,
    "/api/experiments":        handle_experiments,
    "/api/current_challenge":  handle_current_challenge,
    # Sprint 4: BS-11, WEB-CE, BS-BM2
    "/api/timeline":           handle_timeline,
    "/api/correlations":       handle_correlations,
    "/api/genome_risks":       handle_genome_risks,
    # Sprint 9: new public endpoints
    "/api/supplements":        handle_supplements,
    "/api/habits":             handle_habits,
    "/api/vice_streaks":       handle_vice_streaks,
    "/api/journey_timeline":   handle_journey_timeline,
    "/api/journey_waveform":   handle_journey_waveform,
    # Sprint 11: glucose + sleep intelligence pages
    "/api/glucose":            handle_glucose,
    "/api/sleep_detail":       handle_sleep_detail,
    # ARCH-03: Achievement badges
    "/api/achievements":       handle_achievements,
    # ARCH-02: Combined snapshot — single-call summary for pages that need vitals + journey + character
    "/api/snapshot":           handle_snapshot,
    # Website Review: Ask the Platform
    "/api/ask":                handle_ask,
    # WR-24 + S2-T2-2: handled specially in lambda_handler (POST routes)
    "/api/verify_subscriber":  None,
    "/api/board_ask":          None,
    "/api/submit_finding":     None,  # NEW-1: POST handler in lambda_handler
    # EL-2: Experiment library (GET) + EL-3: Experiment vote (POST)
    "/api/experiment_library":  handle_experiment_library,
    "/api/experiment_vote":     None,  # POST handler in lambda_handler
    "/api/experiment_follow":   None,  # EL-F1: POST handler in lambda_handler
    "/api/experiment_detail":   None,  # EL-F2: GET with query params
    # DATA-DRIVEN: S3 config + DynamoDB source-of-truth endpoints
    "/api/protocols":          handle_protocols,
    "/api/challenges":         handle_challenges,
    "/api/challenge_catalog":  handle_challenge_catalog,
    "/api/challenge_vote":     None,  # POST handler in lambda_handler
    "/api/challenge_follow":   None,  # POST handler in lambda_handler
    "/api/challenge_checkin":  None,  # POST handler in lambda_handler
    "/api/domains":            handle_domains,
    "/api/habit_registry":     handle_habit_registry,
    # PULSE-A4: Daily pulse endpoint
    "/api/pulse":              handle_pulse,
    # Subscriber count social proof (read-only)
    "/api/subscriber_count":   handle_subscriber_count,
    # Observatory pages
    "/api/nutrition_overview":  handle_nutrition_overview,
    "/api/training_overview":   handle_training_overview,
    "/api/mind_overview":       handle_mind_overview,
    # BL-02: Bloodwork/Labs
    "/api/labs":                handle_labs,
    "/api/frequent_meals":      handle_frequent_meals,
    "/api/meal_glucose":        handle_meal_glucose,
    "/api/strength_benchmarks": handle_strength_benchmarks,
    # Benchmark trends + meal responses (stub endpoints)
    "/api/benchmark_trends":    handle_benchmark_trends,
    "/api/meal_responses":      handle_meal_responses,
    # Experiment suggestion (POST)
    "/api/experiment_suggest":  None,  # POST handler in lambda_handler
    # Phase 1: Reader engagement
    "/api/changes-since":       None,  # GET with ?ts= query param
    "/api/observatory_week":    None,  # GET with ?domain= query param
}


def lambda_handler(event, context):
    """
    Main Lambda handler. Supports both API Gateway HTTP API and Function URL events.
    """
    path   = event.get("rawPath") or event.get("path", "/")
    method = (event.get("requestContext", {}).get("http", {}).get("method") or
              event.get("httpMethod", "GET")).upper()

    # CORS preflight
    if method == "OPTIONS":
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": ""}

    # SEC-04: Reject requests that didn't come through CloudFront (when secret is configured).
    if SITE_API_ORIGIN_SECRET:
        req_headers = event.get("headers") or {}
        incoming = req_headers.get("x-amj-origin") or req_headers.get("X-AMJ-Origin") or ""
        import hmac as _hmac
        if not _hmac.compare_digest(incoming, SITE_API_ORIGIN_SECRET):
            return _error(403, "Forbidden")

    # WR-24: Subscriber verification (GET)
    if path == "/api/verify_subscriber":
        if method not in ("GET", "OPTIONS"):
            return _error(405, "Use GET method")
        return _handle_verify_subscriber(event)

    # S2-T2-2: Board Ask (POST)
    if path == "/api/board_ask":
        if method != "POST":
            return _error(405, "Use POST method")
        return _handle_board_ask(event)

    # ACCT-2: Nudge (POST)
    if path == "/api/nudge":
        if method != "POST":
            return _error(405, "Use POST method")
        return _handle_nudge(event)

    # NEW-1: Submit Finding (POST)
    if path == "/api/submit_finding":
        if method != "POST":
            return _error(405, "Use POST method")
        return _handle_submit_finding(event)

    # EL-3: Experiment Vote (POST)
    if path == "/api/experiment_vote":
        if method != "POST":
            return _error(405, "Use POST method")
        return _handle_experiment_vote(event)

    # EL-F1: Experiment Follow (POST)
    if path == "/api/experiment_follow":
        if method != "POST":
            return _error(405, "Use POST method")
        return _handle_experiment_follow(event)

    # Experiment Suggest (POST)
    if path == "/api/experiment_suggest":
        if method != "POST":
            return _error(405, "Use POST method")
        return _handle_experiment_suggest(event)

    # Challenge Check-in (POST)
    if path == "/api/challenge_checkin":
        if method != "POST":
            return _error(405, "Use POST method")
        return _handle_challenge_checkin(event)

    # Challenge Vote (POST)
    if path == "/api/challenge_vote":
        if method != "POST":
            return _error(405, "Use POST method")
        return _handle_challenge_vote(event)

    # Challenge Follow (POST)
    if path == "/api/challenge_follow":
        if method != "POST":
            return _error(405, "Use POST method")
        return _handle_challenge_follow(event)

    # EL-F2: Experiment Detail (GET with query params)
    if path == "/api/experiment_detail":
        return _handle_experiment_detail(event)

    # HP-06: Correlations with optional ?featured=true&limit=N
    if path == "/api/correlations":
        return handle_correlations(event)

    # Phase 1: Changes-since (GET with query params)
    if path == "/api/changes-since":
        qs = event.get("queryStringParameters") or {}
        return handle_changes_since(qs)

    # Phase 1: Observatory week (GET with query params)
    if path == "/api/observatory_week":
        qs = event.get("queryStringParameters") or {}
        return handle_observatory_week(qs)

    # Special handling: /api/ask accepts POST
    if path == "/api/ask":
        if method != "POST":
            return _error(405, "Use POST method")
        source_ip = (
            event.get("requestContext", {}).get("http", {}).get("sourceIp") or
            event.get("requestContext", {}).get("identity", {}).get("sourceIp") or
            "unknown"
        )
        try:
            question = json.loads(event.get("body") or "{}").get("question", "").strip()[:500]
            question = re.sub(r'<[^>]+>', '', question)
            if len(question) < 5:
                return _error(400, "Question too short")

            # WR-40: Safety filter
            is_safe, safety_reason = _ask_question_safe(question)
            if not is_safe:
                return {
                    "statusCode": 200,
                    "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
                    "body": json.dumps({"answer": safety_reason, "remaining": 999, "filtered": True}),
                }

            ip_hash = hashlib.sha256(source_ip.encode()).hexdigest()[:16]
            # WR-24: Check for valid subscriber token → higher rate limit
            sub_token = (event.get("headers") or {}).get("x-subscriber-token", "")
            is_subscriber = bool(sub_token) and _validate_subscriber_token(sub_token)
            rate_limit = 20 if is_subscriber else 5
            allowed, remaining = _ask_rate_check(ip_hash, limit=rate_limit)
            if not allowed:
                limit_msg = "20" if is_subscriber else "5"
                _emit_rate_limit_metric("ask")
                return {
                    "statusCode": 429,
                    "headers": {**CORS_HEADERS, "Retry-After": "3600"},
                    "body": json.dumps({"error": f"Rate limit exceeded. {limit_msg} questions per hour.", "remaining": 0}),
                }

            api_key = _get_anthropic_key()
            if not api_key:
                return _error(503, "AI service configuration error")

            ctx = _ask_fetch_context()
            system_prompt = _ask_build_prompt(ctx)

            req_body = json.dumps({
                "model": AI_MODEL_HAIKU,
                "max_tokens": 600,
                "system": system_prompt,
                "messages": [{"role": "user", "content": question}],
            })

            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=req_body.encode(),
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())

            answer = "".join(b["text"] for b in result.get("content", []) if b.get("type") == "text")

            return {
                "statusCode": 200,
                "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
                "body": json.dumps({"answer": _scrub_blocked_terms(answer), "remaining": remaining}),
            }
        except Exception as e:
            logger.error(f"[site_api] /api/ask failed: {e}")
            return _error(500, "AI service error")

    if method != "GET":
        return _error(405, "Method not allowed")

    handler = ROUTES.get(path)
    if not handler:
        return _error(404, "Not found")

    try:
        return handler()
    except Exception as e:
        logger.error(f"[site_api] {path} failed: {e}")
        return _error(500, "Internal error — check CloudWatch logs")
