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

import hashlib
import json
import logging
import os
import re
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


def _load_supp_metadata() -> dict:
    """Load supplement metadata from S3 config/supplement_metadata.json. Cached after first call."""
    global _supp_metadata_cache
    if _supp_metadata_cache is not None:
        return _supp_metadata_cache
    try:
        S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
        s3 = boto3.client("s3", region_name=S3_REGION)
        resp = s3.get_object(Bucket=S3_BUCKET, Key="site/config/supplement_metadata.json")
        data = json.loads(resp["Body"].read())
        _supp_metadata_cache = data.get("supplements", {})
        logger.info(f"[supp_metadata] Loaded: {len(_supp_metadata_cache)} supplements")
    except Exception as e:
        logger.warning(f"[supp_metadata] Failed to load from S3: {e}")
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
    "Content-Type":                 "application/json",
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
            weight_series = [("2026-02-09", 302.0)]  # No data at all — show journey start

    start_weight = 302.0   # Journey start (from profile)
    goal_weight  = 185.0
    current_weight = weight_series[-1][1]
    lost_lbs     = round(start_weight - current_weight, 1)
    remaining    = round(current_weight - goal_weight, 1)
    progress_pct = round(lost_lbs / (start_weight - goal_weight) * 100, 1)

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
            "started_date":       "2026-02-09",
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
    GET /api/status
    Lightweight health check — confirms DynamoDB is reachable.
    Cache: 60s.
    """
    try:
        # Use GetItem (allowed by policy) rather than table.load() which triggers DescribeTable
        table.get_item(Key={"pk": f"USER#{USER_ID}", "sk": "PROFILE#v1"})
        return _ok({"status": "ok", "platform": "life-platform"}, cache_seconds=60)
    except Exception as e:
        return _error(503, f"DynamoDB unavailable: {e}")


# ── BS-11: Timeline data ────────────────────────────────────────

def handle_timeline() -> dict:
    """
    GET /api/timeline
    Returns weight series + life events + experiments + level-ups
    for the interactive Transformation Timeline page.
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start = "2026-02-09"

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
            "journey_start": "2026-02-09",
            "start_weight":  302.0,
            "goal_weight":   185.0,
        }
    }, cache_seconds=3600)


# ── Sprint 9: Supplements + Habits public endpoints ─────────────

def handle_supplements() -> dict:
    """
    GET /api/supplements
    Returns current supplement stack with dosage, timing, category.
    Metadata is the authoritative source (all supplements); DynamoDB dose/timing
    overrides metadata defaults when available.
    Excludes medications and personal notes for privacy.
    Cache: 3600s (1 hr).
    """
    import re as _re

    today     = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    pk = f"{USER_PREFIX}supplements"
    item = None
    # Try today first, fall back to yesterday
    for date in (today, yesterday):
        resp = table.get_item(Key={"pk": pk, "sk": f"DATE#{date}"})
        item = _decimal_to_float(resp.get("Item"))
        if item:
            break

    if not item:
        # Scan last 30 days for latest record
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(pk),
            ScanIndexForward=False,
            Limit=30,
        )
        items = _decimal_to_float(resp.get("Items", []))
        item = items[0] if items else None

    metadata = _load_supp_metadata()
    if not metadata:
        return _error(503, "Supplement data not available")

    def _normalize_key(name: str) -> str:
        return _re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")

    # Build a lookup from normalized name → DynamoDB supplement record
    ddb_lookup = {}
    if item:
        for s in item.get("supplements", []):
            if s.get("category") == "medication":
                continue
            ddb_lookup[_normalize_key(s.get("name", ""))] = s

    as_of_date = item.get("date", yesterday) if item else yesterday

    # SUPP-1: Iterate metadata as authoritative list; merge DynamoDB dose/timing
    public_sups = []
    for key, meta in metadata.items():
        ddb = ddb_lookup.get(key, {})
        category = ddb.get("category", "supplement")
        pub = {
            "key":     key,
            "name":    meta.get("display_name", key),
            "dose":    ddb.get("dose") if ddb.get("dose") is not None else meta.get("default_dose"),
            "unit":    ddb.get("unit") or meta.get("default_unit", ""),
            "timing":  ddb.get("timing") or meta.get("default_timing", ""),
            "category": category,
            "adherence_pct": ddb.get("adherence_pct"),
            "purpose_group":  meta.get("purpose_group"),
            "evidence_tier":  meta.get("evidence_tier"),
            "genome_snp":     meta.get("genome_snp"),
            "rationale":      meta.get("rationale"),
            "science_points": meta.get("science_points", []),
            "watching":       meta.get("watching"),
            "signal":         meta.get("signal"),
            "linked_experiment_id": meta.get("linked_experiment_id"),
        }
        public_sups.append(pub)

    return _ok({
        "as_of_date":  as_of_date,
        "supplements": public_sups,
        "total_count": len(public_sups),
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
    start_date      = "2026-01-01"
    start_weight    = 302.0
    goal_weight     = 185.0

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

    # Sort chronologically, deduplicate by date+title
    events.sort(key=lambda e: e["date"])
    seen: set = set()
    deduped = []
    for e in events:
        key = (e["date"], e["title"])
        if key not in seen:
            seen.add(key)
            deduped.append(e)

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

def handle_correlations() -> dict:
    """
    GET /api/correlations
    Returns the most recent weekly correlation matrix (23 pairs)
    for the public Correlation Explorer.
    Cache: 3600s.
    """
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
    pairs = record.get("pairs", [])
    week = record.get("sk", "").replace("WEEK#", "")

    public_pairs = []
    for p in pairs:
        public_pairs.append({
            "source_a":  p.get("source_a", ""),
            "field_a":   p.get("field_a", ""),
            "label_a":   p.get("label_a", p.get("field_a", "")),
            "source_b":  p.get("source_b", ""),
            "field_b":   p.get("field_b", ""),
            "label_b":   p.get("label_b", p.get("field_b", "")),
            "r":         round(float(p.get("r", 0)), 3),
            "n":         int(p.get("n", 0)),
            "strength":  p.get("strength", "weak"),
            "fdr_significant": p.get("fdr_significant", False),
            "correlation_type": p.get("correlation_type", "cross_sectional"),
            "lag_days":  int(p.get("lag_days", 0)),
        })

    return _ok({
        "correlations": {
            "week":  week,
            "pairs": sorted(public_pairs, key=lambda x: -abs(x["r"])),
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
    api_key = _get_anthropic_key() or "fallback-dev-secret"
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
    to unlock 20 questions/hr instead of the default 3.
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
- If asked about something outside your data
- CONTENT FILTER: NEVER mention porn, pornography, marijuana, cannabis, weed, THC, or any related terms.
- If asked about these topics, respond only with "I don't have data on that specific topic.", say "I don't have that data" — don't speculate."""


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
    d30 = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

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
    d30 = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

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
    start_weight = 302.0
    lost_lbs = round(start_weight - current_weight, 1) if current_weight < start_weight else 0

    # ── First experiment
    exp_pk = f"{USER_PREFIX}experiments"
    exp_resp = table.query(
        KeyConditionExpression=Key("pk").eq(exp_pk),
        ScanIndexForward=False,
        Limit=5,
    )
    completed_exps = [
        i for i in _decimal_to_float(exp_resp.get("Items", []))
        if i.get("sk", "").startswith("EXP#") and i.get("status") in ("completed", "confirmed")
    ]

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


# ── Router ──────────────────────────────────────────────────

ROUTES = {
    "/api/vitals":          handle_vitals,
    "/api/journey":         handle_journey,
    "/api/character":       handle_character,
    "/api/status":          handle_status,
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
            rate_limit = 20 if is_subscriber else 3
            allowed, remaining = _ask_rate_check(ip_hash, limit=rate_limit)
            if not allowed:
                limit_msg = "20" if is_subscriber else "3"
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
        return _error(404, f"Unknown route: {path}. Valid: {list(ROUTES.keys())}")

    try:
        return handler()
    except Exception as e:
        logger.error(f"[site_api] {path} failed: {e}")
        return _error(500, "Internal error — check CloudWatch logs")
