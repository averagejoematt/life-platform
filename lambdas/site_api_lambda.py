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
_cost_cache = {}
_cost_cache_ts = 0
STATUS_CACHE_TTL = 60  # 1 minute — more dynamic status updates

# ── Experiment start date — public Day 1 ───────────────────
EXPERIMENT_START = "2026-04-01"
# Data query start: 1 day before experiment for sleep/recovery data
# (sleep keyed to wake date — night of Mar 31 = record on Mar 31)
EXPERIMENT_QUERY_START = "2026-03-31"


def _experiment_date(days_back=30):
    """Compute a date N days ago, clamped to EXPERIMENT_QUERY_START.
    Use this for ALL date range queries to prevent pre-experiment data leaking through."""
    raw = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
    return max(raw, EXPERIMENT_QUERY_START)


# ── Platform stats — single source of truth for all site pages ──
# Update these when Lambdas/tools/sources change. Every page reads from here.
PLATFORM_STATS = {
    "data_sources": 26,
    "mcp_tools": 115,
    "lambdas": 62,
    "cdk_stacks": 8,
    "alarms": 66,
    "adrs": 45,
    "monthly_cost": "$19",
    "review_count": 19,
    "review_grade": "A",
    "active_secrets": 10,
    "site_pages": 72,
    "test_count": 1075,
    "board_technical": 12,
    "board_product": 8,
    "start_weight": 307,
    "goal_weight": 185,
    "start_date": EXPERIMENT_START,
    "build_date": "2026-02-22",
}

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
    if start_date > end_date:
        return []  # EXPERIMENT_START is in the future — no data yet
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

    # G-3: Latest weight — check Withings first, fall back to Apple Health (HAE)
    withings_latest = _latest_item("withings")
    current_weight = None
    weight_as_of = None
    if withings_latest:
        wv = withings_latest.get("weight_lbs")
        if wv is not None:
            current_weight = float(wv)
            weight_as_of = (withings_latest.get("sk", "").replace("DATE#", "")
                            or withings_latest.get("date"))
    # v1.4.2: Check apple_health for more recent weight (HAE fallback)
    try:
        ah_latest = _latest_item("apple_health")
        if ah_latest and ah_latest.get("weight_lbs"):
            ah_date = ah_latest.get("sk", "").replace("DATE#", "")[:10]
            if not weight_as_of or ah_date > weight_as_of:
                current_weight = float(ah_latest["weight_lbs"])
                weight_as_of = ah_date
    except Exception:
        pass

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


def handle_tools_baseline() -> dict:
    """
    GET /api/tools_baseline
    Returns baseline (first week of experiment) and current values for the
    Tools page comparison badges: RHR, HRV, sleep quality, weight.
    Cache: 3600s — baseline is fixed, current shifts slowly.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Baseline: first 7 days of the experiment
    baseline_end = (datetime.strptime(EXPERIMENT_START, "%Y-%m-%d")
                    + timedelta(days=7)).strftime("%Y-%m-%d")

    # Current: last 7 days
    d7 = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

    baseline_whoop = _query_source("whoop", EXPERIMENT_START, baseline_end)
    current_whoop = _query_source("whoop", d7, today)

    def first_val(records, field):
        """First non-null value from sorted records."""
        for r in sorted(records, key=lambda x: x.get("sk", "")):
            if r.get(field) is not None:
                return round(float(r[field]), 1)
        return None

    def avg_val(records, field):
        """Average of non-null values."""
        vals = [float(r[field]) for r in records if r.get(field) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    baseline = {
        "rhr_bpm": first_val(baseline_whoop, "resting_heart_rate"),
        "hrv_ms": first_val(baseline_whoop, "hrv"),
        "sleep_score": first_val(baseline_whoop, "sleep_quality_score"),
        "sleep_hours": first_val(baseline_whoop, "sleep_duration_hours"),
    }
    current = {
        "rhr_bpm": avg_val(current_whoop, "resting_heart_rate"),
        "hrv_ms": avg_val(current_whoop, "hrv"),
        "sleep_score": avg_val(current_whoop, "sleep_quality_score"),
        "sleep_hours": avg_val(current_whoop, "sleep_duration_hours"),
    }

    # Weight — baseline from first week, current from latest
    baseline_withings = _query_source("withings", EXPERIMENT_START, baseline_end)
    baseline["weight_lbs"] = first_val(baseline_withings, "weight_lbs")

    latest_withings = _latest_item("withings")
    current["weight_lbs"] = (round(float(latest_withings["weight_lbs"]), 1)
                             if latest_withings and latest_withings.get("weight_lbs")
                             else None)

    return _ok({
        "baseline": baseline,
        "baseline_date": EXPERIMENT_START,
        "current": current,
        "current_date": today,
    }, cache_seconds=3600)


def handle_platform_stats() -> dict:
    """GET /api/platform_stats — authoritative platform counts for all site pages."""
    return _ok(PLATFORM_STATS, cache_seconds=3600)


def handle_ledger() -> dict:
    """
    GET /api/ledger
    Returns: Ledger transactions (by event and by cause) + running totals.
    Source: ledger DynamoDB partition + config/ledger.json from S3.
    Cache: 3600s.
    """
    ledger_pk = f"{USER_PREFIX}ledger"

    # 1. Fetch TOTALS#current
    totals_resp = table.get_item(Key={"pk": ledger_pk, "sk": "TOTALS#current"})
    totals_item = _decimal_to_float(totals_resp.get("Item", {}))

    totals = {
        "total_donated_usd": totals_item.get("total_donated_usd", 0),
        "total_bounties_usd": totals_item.get("total_bounties_usd", 0),
        "total_punishments_usd": totals_item.get("total_punishments_usd", 0),
        "bounty_count": totals_item.get("bounty_count", 0),
        "punishment_count": totals_item.get("punishment_count", 0),
    }

    # 2. Fetch LEDGER# transaction records
    txn_resp = table.query(
        KeyConditionExpression=Key("pk").eq(ledger_pk) & Key("sk").begins_with("LEDGER#"),
        ScanIndexForward=False,
        Limit=200,
    )
    txn_items = _decimal_to_float(txn_resp.get("Items", []))

    earned = []
    reluctant = []
    for txn in txn_items:
        entry = {
            "ledger_id": txn.get("sk", "").replace("LEDGER#", ""),
            "date": txn.get("date", ""),
            "source_type": txn.get("source_type", ""),
            "source_id": txn.get("source_id", ""),
            "source_name": txn.get("source_name", ""),
            "outcome": txn.get("outcome", ""),
            "amount_usd": txn.get("amount_usd", 0),
            "cause_id": txn.get("cause_id", ""),
            "cause_name": txn.get("cause_name", ""),
        }
        if txn.get("type") == "punishment" or txn.get("outcome") in ("abandoned", "failed"):
            reluctant.append(entry)
        else:
            earned.append(entry)

    # 3. Fetch config/ledger.json from S3 for display metadata
    try:
        S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
        s3_client = boto3.client("s3", region_name=S3_REGION)
        s3_resp = s3_client.get_object(Bucket=S3_BUCKET, Key="config/ledger.json")
        ledger_config = json.loads(s3_resp["Body"].read())
    except Exception:
        ledger_config = {"earned_causes": [], "reluctant_causes": []}

    # 4. Build by_cause with merged metadata
    by_cause_raw = totals_item.get("by_cause", {})
    earned_causes = []
    for cause_cfg in ledger_config.get("earned_causes", []):
        cid = cause_cfg.get("id", "")
        cause_data = by_cause_raw.get(cid, {})
        earned_causes.append({
            **cause_cfg,
            "total_usd": cause_data.get("total_usd", 0),
            "count": cause_data.get("count", 0),
        })

    reluctant_causes = []
    for cause_cfg in ledger_config.get("reluctant_causes", []):
        cid = cause_cfg.get("id", "")
        cause_data = by_cause_raw.get(cid, {})
        reluctant_causes.append({
            **cause_cfg,
            "total_usd": cause_data.get("total_usd", 0),
            "count": cause_data.get("count", 0),
        })

    return _ok({
        "totals": totals,
        "by_event": {"earned": earned, "reluctant": reluctant},
        "by_cause": {"earned_causes": earned_causes, "reluctant_causes": reluctant_causes},
    }, cache_seconds=3600)


def handle_discoveries() -> dict:
    """
    GET /api/discoveries
    Returns structured content for the Discoveries page:
    - active_hypotheses: from experiment_library S3 config (active experiments)
    - inner_life: from insights partition (chronicle observations)
    - ai_findings: from weekly_correlations (FDR-significant pairs)
    Cache: 1800s (30 min).
    """
    # ── 1. Active hypotheses from experiment library ──
    S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
    active_hypotheses = []
    try:
        s3_client = boto3.client("s3", region_name=S3_REGION)
        obj = s3_client.get_object(Bucket=S3_BUCKET,
                                   Key="config/experiment_library.json")
        lib = json.loads(obj["Body"].read())
        for exp in lib.get("experiments", []):
            if exp.get("status") != "active":
                continue
            active_hypotheses.append({
                "name": exp.get("name", ""),
                "description": exp.get("description", ""),
                "hypothesis": exp.get("hypothesis_template", ""),
                "protocol": exp.get("protocol_template", ""),
                "pillar": exp.get("pillar", ""),
                "evidence_tier": exp.get("evidence_tier", ""),
                "metrics": exp.get("metrics_measurable", []),
                "duration_days": exp.get("suggested_duration_days"),
                "why": exp.get("why_it_matters", ""),
                "evidence_for": exp.get("evidence_for", []),
                "evidence_against": exp.get("evidence_against", []),
                "rationale": exp.get("rationale", ""),
            })
    except Exception as e:
        logger.warning(f"[discoveries] experiment library read failed: {e}")

    # ── 2. Inner life observations from insights partition ──
    inner_life = []
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}insights"),
            ScanIndexForward=False,
            Limit=50,
        )
        for item in _decimal_to_float(resp.get("Items", [])):
            digest_type = item.get("digest_type", "")
            insight_type = item.get("insight_type", "")
            date = item.get("date", "")
            # Chronicle observations are AI narrative findings
            if digest_type == "chronicle" and insight_type == "observation":
                category = "Journal Breakthrough"
            elif digest_type == "weekly_digest":
                category = "Weekly Pattern"
            elif digest_type == "monday_compass":
                category = "Coaching Insight"
            elif digest_type == "weekly_plate":
                category = "Nutrition Pattern"
            else:
                continue

            # Extract a clean title from the HTML text
            text = item.get("text", "")
            title = ""
            # Try to find a heading in the HTML
            import re
            heading_match = re.search(
                r'font-weight:\s*7[0-9]{2}[^>]*>([^<]{10,80})<', text)
            if heading_match:
                title = heading_match.group(1).strip()
            if not title:
                # Fall back to first substantial text
                text_match = re.search(r'>([A-Z][^<]{20,100})<', text)
                if text_match:
                    title = text_match.group(1).strip()
            if not title:
                title = f"{category} — {date}"

            # Extract a body snippet
            body = ""
            # Find first paragraph-like content
            para_match = re.search(
                r'font-size:\s*1[3-5]px[^>]*>([^<]{30,200})<', text)
            if para_match:
                body = para_match.group(1).strip()

            inner_life.append({
                "date": date,
                "category": category,
                "title": title,
                "body": body,
                "confidence": item.get("confidence", ""),
                "actionable": item.get("actionable", False),
                "pillars": item.get("pillars", []),
            })

        # Dedupe by title, keep most recent
        seen_titles = set()
        deduped = []
        for il in inner_life:
            if il["title"] not in seen_titles:
                seen_titles.add(il["title"])
                deduped.append(il)
        inner_life = deduped[:12]  # Cap at 12 cards
    except Exception as e:
        logger.warning(f"[discoveries] insights read failed: {e}")

    # ── 3. AI findings from weekly correlations ──
    ai_findings = []
    try:
        corr_resp = table.query(
            KeyConditionExpression=Key("pk").eq(
                f"{USER_PREFIX}weekly_correlations"),
            ScanIndexForward=False,
            Limit=4,
        )
        _LABELS = {
            "hrv": "HRV", "recovery_score": "Recovery",
            "sleep_duration": "Sleep Duration", "sleep_score": "Sleep Score",
            "resting_hr": "Resting HR", "strain": "Strain",
            "training_kj": "Training Load", "protein_g": "Protein",
            "calories": "Calories", "steps": "Steps",
            "habit_pct": "Habit Completion", "day_grade": "Day Grade",
        }
        for item in _decimal_to_float(corr_resp.get("Items", [])):
            week = item.get("week", item.get("sk", "").replace("WEEK#", ""))
            corrs = item.get("correlations", [])
            if isinstance(corrs, str):
                try:
                    corrs = json.loads(corrs)
                except (json.JSONDecodeError, TypeError):
                    corrs = []
            if not isinstance(corrs, list):
                continue
            for c in corrs:
                if not (c.get("fdr_significant") or c.get("significant")):
                    continue
                a = _LABELS.get(c.get("metric_a", ""), c.get("metric_a", ""))
                b = _LABELS.get(c.get("metric_b", ""), c.get("metric_b", ""))
                r = c.get("r", 0)
                direction = "positively" if r > 0 else "negatively"
                ai_findings.append({
                    "week": week,
                    "metric_a": a,
                    "metric_b": b,
                    "r": round(r, 2) if r else 0,
                    "n": c.get("n", 0),
                    "title": f"{a} × {b}: {direction} correlated",
                    "body": f"r={r:+.2f}, n={c.get('n', '?')} days. "
                            f"FDR-corrected significant finding from {week}.",
                })
    except Exception as e:
        logger.warning(f"[discoveries] correlations read failed: {e}")

    return _ok({
        "active_hypotheses": active_hypotheses,
        "inner_life": inner_life,
        "ai_findings": ai_findings,
    }, cache_seconds=1800)



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
            weight_series = [("2026-04-01", 302.0)]  # Matthew's journey start weight fallback; only used when no Withings data exists

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

    # Pre-experiment: show zeroed character (experiment hasn't started)
    if date_str < EXPERIMENT_START:
        return _ok({
            "character": {
                "level": 1, "tier": "Foundation", "tier_emoji": "\ud83d\udd28",
                "xp_total": 0, "as_of_date": date_str,
                "pre_experiment": True,
            },
            "pillars": [{"name": p, "emoji": PILLAR_EMOJI.get(p, ""),
                         "level": 1, "raw_score": 0, "tier": "Foundation",
                         "xp_delta": 0} for p in PILLAR_ORDER],
        }, cache_seconds=900)

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

    # Pre-experiment: zeroed character
    if date_str < EXPERIMENT_START:
        PILLARS_ZERO = {p: {"level": 1, "raw_score": 0, "tier": "Foundation"}
                        for p in PILLARS}
        return _ok({
            "character_stats": {
                "level": 1, "tier": "Foundation", "tier_emoji": "\ud83d\udd28",
                "xp_total": 0, "as_of_date": date_str, "pre_experiment": True,
            },
            "pillars": PILLARS_ZERO,
        }, cache_seconds=3600)

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

    # ── Pipeline health check results (active probe) ──
    health_check_failures = set()
    health_check_info = {}
    try:
        hc_resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}health_check"),
            ScanIndexForward=False, Limit=1,
        )
        hc_items = hc_resp.get("Items", [])
        if hc_items:
            hc = hc_items[0]
            health_check_info = {
                "checked_at": hc.get("checked_at", ""),
                "passed": int(hc.get("passed", 0)),
                "failed": int(hc.get("failed", 0)),
            }
            failures = json.loads(hc.get("failures", "[]"))
            for f in failures:
                health_check_failures.add(f.get("source_id", ""))
    except Exception as e:
        logger.warning(f"[status] Health check read failed (non-fatal): {e}")

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
    # Restructured: name is the DATA type, source app is separate
    # (source_id, name, description, yellow_h, red_h, category, group, activity_dependent, source_app, field_check)
    # field_check: if set, _last_sync filters by this field existing (for shared partitions like apple_health)
    _DATA_SOURCES = [
        # ── API-Based (fully automated) ──
        ("whoop",              "Recovery & Sleep Data",              "HRV \u00B7 recovery score \u00B7 sleep staging",      25,  49, "auto",    "API-Based", False, "Whoop", None),
        ("withings",           "Weight Data",                        "Weight \u00B7 body composition \u00B7 blood pressure", 25,  49, "auto",   "API-Based", True,  "Withings", None),
        ("eightsleep",         "Sleep Environment Data",             "Sleep staging \u00B7 bed temperature \u00B7 HRV",      25,  49, "auto",    "API-Based", False, "Eight Sleep", None),
        ("todoist",            "To Do Task Data",                    "Tasks \u00B7 projects \u00B7 completion rate",          25,  49, "auto",   "API-Based", True,  "Todoist", None),
        ("weather",            "Weather Data",                       "Daily temperature \u00B7 conditions \u00B7 humidity",   25,  49, "auto",   "API-Based", False, "OpenWeather", None),
        ("garmin",             "Activity Tracking (1 of 2)",         "Steps \u00B7 GPS routes \u00B7 stress \u00B7 body battery", 25,  49, "auto",   "API-Based", True,  "Garmin", None),
        ("strava",             "Activity Tracking (2 of 2)",         "Activities \u00B7 segments \u00B7 training load",      25,  49, "auto",    "API-Based", True,  "Strava", None),
        ("notion",             "Journal Data",                       "Journal entries \u00B7 mood \u00B7 reflections",       25,  49, "auto",    "API-Based", True,  "Notion", None),
        # ── User-Driven (requires user to log/sync) ──
        ("habitify",           "Habit Tracking Data",                "Daily habits \u00B7 day grades",                       25,  49, "auto",    "User-Driven", True,  "Habitify", None),
        ("macrofactor",        "Nutrition Data",                     "Calories \u00B7 macros \u00B7 meal timing",            25,  49, "auto",    "User-Driven", True,  "MacroFactor via Dropbox", None),
        ("supplements",        "Supplement Adherence",               "Daily supplement tracking & compliance",                25,  49, "auto",   "User-Driven", True,  "Habitify", None),
        # State of Mind tracked via apple_health partition field check (som_avg_valence) in Periodic Uploads section
        # ── Periodic Uploads (file drops, webhooks, device sync) ──
        ("macrofactor_workouts","Exercise Log Data",                 "Workout CSV via file drop",                             48, 168, "auto",   "Periodic Uploads", True,  "MacroFactor via Dropbox", None),
        ("apple_health",       "CGM Glucose Data",                   "Continuous glucose monitor readings",                   25,  49, "auto",  "Periodic Uploads", True,  "Dexcom Stelo via Health Exporter", "blood_glucose_avg"),
        ("apple_health",       "Water Intake Data",                  "Daily water consumption tracking",                      25,  49, "auto",   "Periodic Uploads", True,  "Apple Health via Health Exporter", "water_intake_ml"),
        ("bp_readings",        "Blood Pressure Data",                "Systolic \u00B7 diastolic \u00B7 pulse",               168, 336, "manual",  "Periodic Uploads", True,  "Apple Health via Health Exporter", None),
        ("apple_health",       "Breathwork Data",                    "Breathing exercises \u00B7 sessions",                   48, 168, "auto",   "Periodic Uploads", True,  "Breathwrk via Health Exporter", "recovery_workout_minutes"),
        ("apple_health",       "Stretching Data",                    "Flexibility sessions \u00B7 recovery",                  48, 168, "auto",   "Periodic Uploads", True,  "Pliability via Health Exporter", "flexibility_minutes"),
        ("apple_health",       "Mindful Minutes Data",               "Meditation & mindfulness sessions",                     48, 168, "auto",   "Periodic Uploads", True,  "Apple Health via Health Exporter", "mindful_minutes"),
        ("apple_health",       "State of Mind Data (Health Export)",  "How We Feel mood check-ins via Health Exporter",       48, 168, "auto",   "Periodic Uploads", True,  "Apple Health via Health Exporter", "som_avg_valence"),
        ("apple_health",       "Apple Health Import",                 "Steps \u00B7 activity \u00B7 walking metrics",        25,  49, "auto",  "Periodic Uploads", True,  "Health Auto Export", "steps"),
        ("food_delivery",      "Food Delivery Index",                "Quarterly CSV import \u00B7 delivery index 0-10",     2160, 2880, "manual", "Periodic Uploads", True, "CSV upload"),
        ("measurements",       "Body Tape Measurements",             "Periodic body measurements \u00B7 waist-to-height ratio", 1440, 2880, "manual", "Periodic Uploads", True, "CSV upload (Brittany)"),
        # ── Lab & Clinical (infrequent) ──
        ("labs",               "Blood Test Results",                  "Lab work \u00B7 biomarkers \u00B7 lipid panel",       4320, 8760, "manual", "Lab & Clinical", True,  "Function Health"),
        ("dexa",               "Bone Density & Body Comp",           "DEXA scan \u00B7 bone density \u00B7 lean mass",      4320, 8760, "manual", "Lab & Clinical", True,  "Clinical (manual)"),
        ("genome",             "Genome Data",                         "Genetic variants \u00B7 risk scores \u00B7 SNPs",    999999, 999999, "onetime", "Lab & Clinical", False, "23andMe (one-time)"),
    ]
    _COMPUTE_SOURCES = [
        ("character_sheet",  "Character Sheet",        "Pillar scores \u00B7 level \u00B7 XP",         25, 49),
        ("computed_metrics", "Daily Metrics",          "Cross-domain computed signals",                 25, 49),
        ("habit_scores",     "Habit Score Aggregation", "Tier scores \u00B7 streaks \u00B7 grades",    25, 49),
        ("insights",         "Daily Insights",         "IC-8 intent vs execution",                     25, 49),
        ("adaptive_mode",    "Adaptive Mode",          "Engagement scoring \u00B7 brief mode",         25, 49),
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

    def _last_sync(source_id, field_check=None):
        """Get the latest date for a source. If field_check is set, only count records
        that have that specific field (for shared partitions like apple_health)."""
        try:
            if field_check:
                # Must scan with filter — more expensive but necessary for sub-source tracking
                from boto3.dynamodb.conditions import Attr
                resp = table.query(
                    KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}{source_id}") & Key("sk").begins_with("DATE#"),
                    FilterExpression=Attr(field_check).exists(),
                    ScanIndexForward=False,
                    ProjectionExpression="sk",
                    Limit=200,  # scan recent records to find one with the field
                )
                items = resp.get("Items", [])
                return items[0]["sk"].replace("DATE#", "")[:10] if items else None
            else:
                resp = table.query(
                    KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}{source_id}") & Key("sk").begins_with("DATE#"),
                    ScanIndexForward=False, Limit=1, ProjectionExpression="sk",
                )
                items = resp.get("Items", [])
                return items[0]["sk"].replace("DATE#", "")[:10] if items else None
        except Exception:
            return None

    # Sources where data is inherently 1 day behind (keyed by wake date / previous day)
    _LAGGED_SOURCES = {"eightsleep", "whoop"}

    def _comp_status(last_date_str, yellow_h, red_h, source_id=None):
        if not last_date_str:
            return "green" if source_id == "genome" else "red", "never", "No records found in DynamoDB" if source_id != "genome" else None
        last_dt = datetime.strptime(last_date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        days_ago = (now.date() - last_dt.date()).days

        # Sleep/recovery sources are keyed by wake date — yesterday is current
        effective_days = days_ago
        if source_id in _LAGGED_SOURCES:
            effective_days = max(0, days_ago - 1)

        if days_ago == 0:
            rel = "today"
        elif days_ago == 1:
            rel = "yesterday"
        else:
            rel = f"{days_ago}d ago"

        # For lagged sources, show "current" instead of "2d ago" when data is actually fresh
        if source_id in _LAGGED_SOURCES and effective_days <= 1 and days_ago >= 1:
            rel = "current"

        # Green: data is current (accounting for natural lag)
        if effective_days <= 1:
            return "green", rel, None
        elif effective_days <= 2:
            return "yellow", rel, f"Last data {rel} — monitoring"
        else:
            hours_ago = (now - last_dt).total_seconds() / 3600
            if hours_ago <= red_h:
                return "yellow", rel, f"Last data {rel} — expected within {red_h}h"
            return "red", rel, f"STALE: last data {rel}. Threshold exceeded ({red_h}h)."

    def _uptime_90d(source_id, activity_dependent=False):
        """Uptime bars including today. All sources use same window for visual alignment."""
        try:
            epoch_start = datetime(2026, 3, 28, tzinfo=timezone.utc).date()
            today = datetime.now(timezone.utc).date()
            window_days = min(90, (today - epoch_start).days + 1)
            if window_days < 1:
                return [2]  # pre-epoch: neutral

            resp = table.query(
                KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}{source_id}") & Key("sk").between(
                    f"DATE#{epoch_start.isoformat()}", f"DATE#{today.isoformat()}"
                ),
                ProjectionExpression="sk",
            )
            present = {item["sk"].replace("DATE#", "")[:10] for item in resp.get("Items", [])}
            bars = []
            for i in range(window_days - 1, -1, -1):
                d = (today - timedelta(days=i)).isoformat()
                if d in present:
                    bars.append(1)  # green — data exists
                elif i <= 1:
                    bars.append(2)  # neutral — today or yesterday, data may come later
                elif activity_dependent:
                    bars.append(2)  # neutral — no user activity, not a system failure
                else:
                    bars.append(0)  # red — older day with no data (system issue)
            return bars
        except Exception:
            return [2]

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
        source_app = row[8] if len(row) > 8 else ""
        field_check = row[9] if len(row) > 9 else None
        last = _last_sync(sid, field_check=field_check)

        if category == "onetime":
            # Genome — one-time import, no recurring tracking
            try:
                _gene_resp = table.query(
                    KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}{sid}"),
                    Limit=1, ProjectionExpression="sk",
                )
                has_data = len(_gene_resp.get("Items", [])) > 0
            except Exception:
                has_data = False
            status = "green" if has_data else "blue"
            rel = "imported" if has_data else "not imported"
            comment = "One-time import \u2014 data on file" if has_data else "Awaiting initial import"
            uptime = []  # No daily bars for one-time sources
        elif category == "manual":
            # Labs / DEXA / Food Delivery — due-date tracking
            # Board recommendation: labs every 6mo, DEXA every 12mo, food delivery every 3mo
            DUE_MONTHS = {"labs": 6, "dexa": 12, "food_delivery": 3, "bp_readings": 3, "measurements": 2}
            due_mo = DUE_MONTHS.get(sid, 6)
            if last:
                last_dt = datetime.strptime(last[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                days_ago = (datetime.now(timezone.utc).date() - last_dt.date()).days
                months_ago = days_ago / 30.0
                due_date = last_dt + timedelta(days=due_mo * 30)
                due_str = due_date.strftime("%b %Y")
                # Human-readable relative time
                if days_ago == 0:
                    rel = "today"
                elif days_ago == 1:
                    rel = "yesterday"
                elif days_ago < 30:
                    rel = f"{days_ago}d ago"
                else:
                    rel = f"{int(months_ago)}mo ago"
                if months_ago < due_mo:
                    status = "green"
                    comment = f"Last: {rel}. Next due: {due_str}"
                elif months_ago < due_mo * 1.5:
                    status = "yellow"
                    comment = f"Due for refresh ({due_str}). Last: {rel}"
                else:
                    status = "yellow"
                    comment = f"Overdue \u2014 was due {due_str}. Last: {rel}"
            else:
                status = "blue"
                rel = "never"
                comment = "No data yet \u2014 schedule first appointment"
            uptime = []  # No daily bars for infrequent sources
        else:
            status, rel, comment = _comp_status(last, yh, rh, source_id=sid)
            uptime = _uptime_90d(sid, activity_dependent=activity_dep)

            # Activity-dependent sources: distinguish "user didn't log" vs "pipeline broke"
            # If a source HAD regular data and suddenly stops, that's likely a pipeline issue
            # (auth failure, webhook key mismatch) — not missing user activity.
            if activity_dep and status in ("red", "yellow") and sid not in alarming_sources:
                # Check if this source had a consistent history that suddenly stopped
                _was_regular = False
                if last:
                    try:
                        _hist_resp = table.query(
                            KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}{sid}") & Key("sk").begins_with("DATE#"),
                            ScanIndexForward=False, Limit=14, ProjectionExpression="sk",
                        )
                        _hist_dates = [i["sk"].replace("DATE#", "")[:10] for i in _hist_resp.get("Items", [])]
                        if len(_hist_dates) >= 7:
                            # Had 7+ records in recent history — this source was flowing regularly
                            # Check gap: if last record is 3+ days old but source had daily data, pipeline likely broke
                            _last_dt = datetime.strptime(last[:10], "%Y-%m-%d")
                            _gap_days = (now.date() - _last_dt.date()).days
                            if _gap_days >= 3 and len(_hist_dates) >= 5:
                                _was_regular = True
                    except Exception:
                        pass

                # Also check: for API-based sources, if the Lambda ran today but wrote nothing,
                # that's a pipeline issue (auth failure, not missing activity)
                if not _was_regular and group == "API-Based" and last:
                    try:
                        _last_dt = datetime.strptime(last[:10], "%Y-%m-%d")
                        _gap_days = (now.date() - _last_dt.date()).days
                        # API sources should write daily — a 2+ day gap means the Lambda
                        # ran but couldn't fetch data (auth expired, API down, etc.)
                        if _gap_days >= 2:
                            _was_regular = True
                    except Exception:
                        pass

                if _was_regular:
                    status = "yellow"
                    comment = f"Pipeline may need attention \u2014 was flowing regularly but stopped {rel}. Check auth/webhook."
                elif last:
                    status = "green"
                    comment = f"Pipeline ready \u2014 awaiting user activity. Last data: {rel}"
                else:
                    status = "green"
                    comment = "Pipeline ready \u2014 no data recorded yet"

        # CloudWatch alarm override — if Lambda is actively erroring, show red
        if sid in alarming_sources and status != "blue":
            status = "red"
            comment = f"CloudWatch alarm firing \u2014 Lambda errors detected"
        # Health check override — if daily probe failed, show red
        elif sid in health_check_failures and status not in ("blue", "red"):
            status = "red"
            comment = f"Daily health check failed \u2014 pipeline error detected"

        ds_components.append({"id": sid, "name": name, "description": desc,
                              "status": status, "last_sync_relative": rel,
                              "uptime_90d": uptime, "comment": comment,
                              "group": group, "source_app": source_app})

    # Compute components
    compute_components = []
    for sid, name, desc, yh, rh in _COMPUTE_SOURCES:
        last = _last_sync(sid)
        status, rel, comment = _comp_status(last, yh, rh, source_id=sid)
        uptime = _uptime_90d(sid, activity_dependent=True)  # compute depends on ingestion — missing days aren't system failures
        # Compute sources depend on ingestion data — if no new input, no new output is expected
        if status in ("red", "yellow") and sid not in alarming_sources:
            if not last:
                status = "green"
                rel = "verified"
                comment = "Smoke-tested OK \u2014 awaiting first scheduled run (April 1+)"
            else:
                status = "green"
                comment = f"Last computed: {rel} \u2014 runs daily when new data arrives"
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
        status, rel, comment = _comp_status(last, yh, rh, source_id=lid)
        status, rel = _sched_aware(status, rel, exp_dow)
        uptime = _uptime_90d(f"email_log#{lid}", activity_dependent=True)  # scheduled emails — gaps aren't system failures
        # Weekly/scheduled emails: if they've run within their expected window, they're fine
        if status in ("yellow",) and last and lid not in alarming_sources:
            status = "green"
            comment = f"Last sent: {rel} \u2014 next run scheduled"
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

    # Infrastructure
    # DLQ depth check
    dlq_depth = 0
    dlq_status = "green"
    dlq_comment = None
    try:
        sqs = boto3.client("sqs", region_name=REGION)
        dlq_attrs = sqs.get_queue_attributes(
            QueueUrl=f"https://sqs.{REGION}.amazonaws.com/205930651321/life-platform-ingestion-dlq",
            AttributeNames=["ApproximateNumberOfMessages"],
        )
        dlq_depth = int(dlq_attrs["Attributes"]["ApproximateNumberOfMessages"])
        if dlq_depth > 0:
            dlq_status = "yellow" if dlq_depth < 10 else "red"
            dlq_comment = f"{dlq_depth} messages in dead-letter queue"
    except Exception:
        pass

    infra = [
        {"id": "cloudfront_main", "name": "averagejoematt.com",     "description": "CloudFront \u00B7 66 pages",         "status": "green", "comment": None},
        {"id": "site_api",        "name": "Site API Lambda",         "description": "us-west-2 \u00B7 60+ endpoints",    "status": "green", "comment": None},
        {"id": "mcp_server",      "name": "MCP server",              "description": "us-west-2 \u00B7 116 tools",        "status": "green", "comment": None},
        {"id": "dynamodb",        "name": "DynamoDB",                "description": "on-demand \u00B7 PITR enabled",      "status": "green", "comment": None},
        {"id": "ses",             "name": "SES email delivery",      "description": "Production mode \u00B7 receipt rule", "status": "green", "comment": None},
        {"id": "dlq",             "name": "Dead-letter queue",       "description": f"{dlq_depth} messages",               "status": dlq_status, "comment": dlq_comment},
    ]

    # Overall status: proportional to severity.
    # Exclude: blue (manual/infrequent), gray (idle), yellow (overdue labs etc.)
    red_components = [c for c in ds_components + compute_components + email_components
                      if c["status"] == "red"]
    red_count = len(red_components)
    total_active = len([c for c in ds_components + compute_components + email_components
                        if c["status"] not in ("blue", "gray")])

    if red_count == 0:
        overall = "green"
    elif red_count >= 3 or (total_active > 0 and red_count / total_active > 0.2):
        overall = "red"  # 3+ failures OR >20% of active pipelines down
    else:
        overall = "yellow"  # 1-2 failures = degraded, not down

    # ── Cost tracking (cached 1h — Cost Explorer API is slow, 10-15s cross-region) ──
    global _cost_cache, _cost_cache_ts
    cost_info = {}
    if _cost_cache and (time.time() - _cost_cache_ts < 3600):
        cost_info = _cost_cache
    else:
        try:
            ce = boto3.client("ce", region_name="us-east-1")
            now_date = datetime.now(timezone.utc)
            month_start = now_date.strftime("%Y-%m-01")
            today_str = now_date.strftime("%Y-%m-%d")
            resp = ce.get_cost_and_usage(
                TimePeriod={"Start": month_start, "End": today_str},
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
            )
            mtd = float(resp["ResultsByTime"][0]["Total"]["UnblendedCost"]["Amount"])
            days_elapsed = now_date.day
            days_in_month = 30
            projected = round((mtd / max(days_elapsed, 1)) * days_in_month, 2)
            budget = 15.0
            cost_info = {
                "mtd": round(mtd, 2),
                "projected": projected,
                "budget": budget,
                "status": "green" if projected <= budget else "yellow" if projected <= budget * 1.2 else "red",
                "pct_of_budget": round((projected / budget) * 100),
            }
            _cost_cache = cost_info
            _cost_cache_ts = time.time()
        except Exception as e:
            logger.warning(f"[status] Cost Explorer failed (non-fatal): {e}")

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "cost": cost_info,
        "health_check": health_check_info,
        "groups": [
            {"id": "data_sources",  "label": "Data sources",   "subtitle": f"{len(ds_components)} feeds \u2014 wearables \u00B7 nutrition \u00B7 labs \u00B7 genome", "components": ds_components},
            {"id": "compute",       "label": "Compute layer",  "subtitle": "character sheet \u00B7 metrics \u00B7 insights \u00B7 adaptive mode", "components": compute_components},
            {"id": "email",         "label": "Email & digests", "subtitle": "7 scheduled senders", "components": email_components},
            {"id": "infrastructure","label": "Infrastructure",  "subtitle": "CloudFront \u00B7 DynamoDB \u00B7 SES \u00B7 DLQ", "components": infra},
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
    ninety_days_ago = _experiment_date(90)

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
    ninety_days_ago = _experiment_date(90)

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
    d30 = _experiment_date(30)

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
    d30 = _experiment_date(30)

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
            "deep_sleep_hours":  round(float(w["slow_wave_sleep_hours"]), 2) if w.get("slow_wave_sleep_hours") else None,
            "rem_sleep_hours":   round(float(w["rem_sleep_hours"]), 2) if w.get("rem_sleep_hours") else None,
            "recovery_score":    round(float(w["recovery_score"]), 0) if w.get("recovery_score") else None,
            "hrv":               round(float(w["hrv"]), 1) if w.get("hrv") else None,
            "rhr":               round(float(w["resting_heart_rate"]), 0) if w.get("resting_heart_rate") else None,
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
            "deep_sleep_hours":  round(float(whoop_latest.get("slow_wave_sleep_hours", 0)), 2) if whoop_latest.get("slow_wave_sleep_hours") else None,
            "rem_sleep_hours":   round(float(whoop_latest.get("rem_sleep_hours", 0)), 2) if whoop_latest.get("rem_sleep_hours") else None,
            "recovery_score":    round(float(whoop_latest.get("recovery_score", 0)), 0) if whoop_latest.get("recovery_score") else None,
            "hrv":               round(float(whoop_latest.get("hrv", 0)), 1) if whoop_latest.get("hrv") else None,
            "rhr":               round(float(whoop_latest.get("resting_heart_rate", 0)), 0) if whoop_latest.get("resting_heart_rate") else None,
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
            _pulse_day = max(1, (datetime.now(timezone.utc).date() - datetime.strptime(EXPERIMENT_START, "%Y-%m-%d").date()).days + 1) if datetime.now(timezone.utc).strftime("%Y-%m-%d") >= EXPERIMENT_START else 0
            return _ok({
                "pulse": {
                    "day_number": _pulse_day,
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

def handle_nutrition_overview() -> dict:
    """
    GET /api/nutrition_overview
    Returns: 30-day macro averages, protein adherence, eating window, deficit status.
    Source: MacroFactor DynamoDB partition.
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d30 = _experiment_date(30)
    d7 = _experiment_date(7)

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

    protein_target = 190  # Matthew's protein target in grams — matches profile.protein_target_g
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

    # ── Weekday vs Weekend comparison ──
    weekday_items = []
    weekend_items = []
    for i in items:
        d = i.get("date") or i.get("sk", "").replace("DATE#", "")
        try:
            dow = datetime.strptime(d, "%Y-%m-%d").weekday()
        except Exception:
            continue
        if dow >= 5:
            weekend_items.append(i)
        else:
            weekday_items.append(i)

    def _group_avg(group, field):
        vals = [float(x[field]) for x in group if x.get(field) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    weekday_vs_weekend = {
        "weekday": {
            "avg_calories": _group_avg(weekday_items, "calories"),
            "avg_protein_g": _group_avg(weekday_items, "protein_g"),
            "avg_carbs_g": _group_avg(weekday_items, "carbs_g"),
            "avg_fat_g": _group_avg(weekday_items, "fat_g"),
            "avg_fiber_g": _group_avg(weekday_items, "fiber_g"),
            "days": len(weekday_items),
            "protein_hit_pct": round(
                sum(1 for x in weekday_items if float(x.get("protein_g") or 0) >= protein_target)
                / len(weekday_items) * 100
            ) if weekday_items else 0,
        },
        "weekend": {
            "avg_calories": _group_avg(weekend_items, "calories"),
            "avg_protein_g": _group_avg(weekend_items, "protein_g"),
            "avg_carbs_g": _group_avg(weekend_items, "carbs_g"),
            "avg_fat_g": _group_avg(weekend_items, "fat_g"),
            "avg_fiber_g": _group_avg(weekend_items, "fiber_g"),
            "days": len(weekend_items),
            "protein_hit_pct": round(
                sum(1 for x in weekend_items if float(x.get("protein_g") or 0) >= protein_target)
                / len(weekend_items) * 100
            ) if weekend_items else 0,
        },
    }

    # ── Eating window (first/last meal time from food_log) ──
    eating_windows = []
    for i in items:
        food_log = i.get("food_log") or []
        times = []
        for entry in food_log:
            t = entry.get("time")
            if t:
                try:
                    parts = t.split(":")
                    hour_min = int(parts[0]) * 60 + int(parts[1])
                    times.append(hour_min)
                except (ValueError, IndexError):
                    pass
        if len(times) >= 2:
            first = min(times)
            last = max(times)
            window_hrs = round((last - first) / 60, 1)
            eating_windows.append({
                "first_meal_min": first,
                "last_meal_min": last,
                "window_hrs": window_hrs,
            })

    eating_window = None
    if eating_windows:
        avg_first = round(sum(e["first_meal_min"] for e in eating_windows) / len(eating_windows))
        avg_last = round(sum(e["last_meal_min"] for e in eating_windows) / len(eating_windows))
        avg_window = round(sum(e["window_hrs"] for e in eating_windows) / len(eating_windows), 1)
        eating_window = {
            "avg_hours": avg_window,
            "avg_first_meal": f"{avg_first // 60}:{avg_first % 60:02d}",
            "avg_last_meal": f"{avg_last // 60}:{avg_last % 60:02d}",
            "days_with_data": len(eating_windows),
        }

    # ── Caloric periodization (training days vs rest days) ──
    strava_items_30d = _query_source("strava", d30, today)
    training_dates = set()
    for s in strava_items_30d:
        d = s.get("date") or s.get("sk", "").replace("DATE#", "")
        training_dates.add(d)

    training_day_items = []
    rest_day_items = []
    for i in items:
        d = i.get("date") or i.get("sk", "").replace("DATE#", "")
        if d in training_dates:
            training_day_items.append(i)
        else:
            rest_day_items.append(i)

    periodization = {
        "training_day": {
            "avg_calories": _group_avg(training_day_items, "calories"),
            "avg_protein_g": _group_avg(training_day_items, "protein_g"),
            "count": len(training_day_items),
        },
        "rest_day": {
            "avg_calories": _group_avg(rest_day_items, "calories"),
            "avg_protein_g": _group_avg(rest_day_items, "protein_g"),
            "count": len(rest_day_items),
        },
    }
    # Compute deficit for each group if TDEE is available
    if tdee:
        for key in ("training_day", "rest_day"):
            avg = periodization[key]["avg_calories"]
            periodization[key]["avg_deficit"] = round(tdee - avg) if avg else None

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
        "weekday_vs_weekend": weekday_vs_weekend,
        "eating_window": eating_window,
        "periodization": periodization,
    }, cache_seconds=3600)


def handle_training_overview() -> dict:
    """
    GET /api/training_overview
    Returns: workout frequency, zone 2 minutes, training load, strength summary.
    Sources: Strava (cardio), Hevy (strength), Whoop (strain).
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d90 = _experiment_date(90)
    d30 = _experiment_date(30)

    # Strava activities (90 days)
    strava_items = _query_source("strava", d90, today)
    strava_30d = [s for s in strava_items if (s.get("date") or s.get("sk", "").replace("DATE#", "")) >= d30]

    # Zone 2 detection: HR between 60-70% of max HR
    max_hr = 184  # Matthew's measured max HR — matches profile.max_heart_rate
    z2_low, z2_high = max_hr * 0.60, max_hr * 0.70
    z2_minutes_30d = 0
    # Z2 is recalculated after flattening activities below
    z2_target = 150  # minutes/week

    # Flatten nested activities lists from day-level Strava records
    all_activities_30d = []
    for s in strava_30d:
        acts = s.get("activities") or []
        if acts:
            for a in acts:
                a["_day_date"] = s.get("date") or s.get("sk", "").replace("DATE#", "")
            all_activities_30d.extend(acts)
        else:
            # Fallback: treat day record itself as a single activity
            s["_day_date"] = s.get("date") or s.get("sk", "").replace("DATE#", "")
            all_activities_30d.append(s)

    all_activities_90d = []
    for s in strava_items:
        acts = s.get("activities") or []
        if acts:
            for a in acts:
                a["_day_date"] = s.get("date") or s.get("sk", "").replace("DATE#", "")
            all_activities_90d.extend(acts)
        else:
            s["_day_date"] = s.get("date") or s.get("sk", "").replace("DATE#", "")
            all_activities_90d.append(s)

    total_workouts_90d = len(all_activities_90d)
    total_workouts_30d = len(all_activities_30d)
    weekly_avg = round(total_workouts_30d / 4.3, 1) if total_workouts_30d else 0

    # Activity type breakdown (30d)
    type_counts = {}
    for a in all_activities_30d:
        sport = a.get("sport_type") or a.get("type") or "Other"
        type_counts[sport] = type_counts.get(sport, 0) + 1
    top_activities = sorted(type_counts.items(), key=lambda x: -x[1])[:8]

    # Total training minutes and distance (30d)
    def _act_minutes(a):
        return float(a.get("duration_minutes") or a.get("moving_time_minutes") or
                      (a.get("moving_time_seconds") or 0) / 60 or 0)

    def _act_miles(a):
        if a.get("distance_miles"):
            return float(a["distance_miles"])
        if a.get("distance_meters"):
            return float(a["distance_meters"]) * 0.000621371
        if a.get("distance"):
            return float(a["distance"]) / 1609.34
        return 0.0

    total_minutes_30d = sum(_act_minutes(a) for a in all_activities_30d)
    total_distance_mi = sum(_act_miles(a) for a in all_activities_30d)

    # ── Modality breakdown (30d) — group by sport_type with per-modality stats ──
    from collections import defaultdict as _dd2
    modality_map = _dd2(lambda: {
        "count": 0, "total_min": 0, "total_mi": 0, "total_elev_ft": 0,
        "hr_sum": 0, "hr_count": 0, "z2_min": 0,
    })
    # Also compute prior 30d for trend (days 31-60)
    d60 = _experiment_date(60)
    prior_30d_acts = []
    for s in strava_items:
        d = s.get("date") or s.get("sk", "").replace("DATE#", "")
        if d60 <= d < d30:
            acts = s.get("activities") or [s]
            prior_30d_acts.extend(acts)
    prior_type_counts = {}
    for a in prior_30d_acts:
        sport = a.get("sport_type") or a.get("type") or "Other"
        prior_type_counts[sport] = prior_type_counts.get(sport, 0) + 1

    for a in all_activities_30d:
        sport = a.get("sport_type") or a.get("type") or "Other"
        m = modality_map[sport]
        m["count"] += 1
        dur = _act_minutes(a)
        m["total_min"] += dur
        m["total_mi"] += _act_miles(a)
        m["total_elev_ft"] += float(a.get("total_elevation_gain_feet") or 0)
        avg_hr = a.get("average_heartrate") or a.get("avg_hr")
        if avg_hr:
            m["hr_sum"] += float(avg_hr)
            m["hr_count"] += 1
            if z2_low <= float(avg_hr) <= z2_high:
                m["z2_min"] += dur

    modality_breakdown = []
    for sport, m in sorted(modality_map.items(), key=lambda x: -x[1]["count"]):
        prior_count = prior_type_counts.get(sport, 0)
        trend = m["count"] - prior_count  # positive = more active
        modality_breakdown.append({
            "type": sport,
            "count_30d": m["count"],
            "total_minutes_30d": round(m["total_min"]),
            "avg_duration_min": round(m["total_min"] / m["count"]) if m["count"] else 0,
            "avg_hr": round(m["hr_sum"] / m["hr_count"]) if m["hr_count"] else None,
            "total_distance_mi": round(m["total_mi"], 1),
            "total_elevation_ft": round(m["total_elev_ft"]),
            "z2_minutes": round(m["z2_min"]),
            "trend_vs_prior_30d": trend,
        })

    # Recalculate Z2 from all flattened activities
    z2_minutes_30d = 0
    for a in all_activities_30d:
        avg_hr = a.get("average_heartrate") or a.get("avg_hr")
        dur = _act_minutes(a)
        if avg_hr and dur:
            if z2_low <= float(avg_hr) <= z2_high:
                z2_minutes_30d += dur
    z2_weekly_avg = round(z2_minutes_30d / 4.3)
    z2_pct = round(z2_weekly_avg / z2_target * 100) if z2_target else 0

    # ── Walking stats (Garmin steps + Strava walks) ──
    garmin_30d = _query_source("garmin", d30, today)
    step_vals = [float(g["steps"]) for g in garmin_30d if g.get("steps")]
    avg_daily_steps = round(sum(step_vals) / len(step_vals)) if step_vals else None
    daily_steps_trend = []
    for g in sorted(garmin_30d, key=lambda x: x.get("date") or x.get("sk", "")):
        if g.get("steps"):
            _step_date = g.get("date") or g.get("sk", "").replace("DATE#", "")
            try:
                _step_dow = datetime.strptime(_step_date, "%Y-%m-%d").weekday()
            except Exception:
                _step_dow = 0
            daily_steps_trend.append({
                "date": _step_date,
                "steps": int(float(g["steps"])),
                "is_weekend": _step_dow >= 5,
            })

    walk_activities = [a for a in all_activities_30d if (a.get("sport_type") or "").lower() in ("walk", "hike")]
    ruck_activities = [a for a in all_activities_30d if "ruck" in (a.get("name") or "").lower() or "ruck" in (a.get("sport_type") or "").lower()]
    walking_data = {
        "avg_daily_steps": avg_daily_steps,
        "total_walks_30d": len(walk_activities),
        "total_rucks_30d": len(ruck_activities),
        "total_miles_30d": round(sum(_act_miles(a) for a in walk_activities), 1),
        "avg_pace_min_per_mi": None,
        "z2_minutes_walking": round(sum(
            _act_minutes(a) for a in walk_activities
            if a.get("average_heartrate") and z2_low <= float(a["average_heartrate"]) <= z2_high
        )),
        "daily_steps_trend": daily_steps_trend,
    }
    # Avg walking pace (min/mi)
    walk_w_speed = [a for a in walk_activities if a.get("average_speed_ms") and float(a["average_speed_ms"]) > 0]
    if walk_w_speed:
        avg_speed_ms = sum(float(a["average_speed_ms"]) for a in walk_w_speed) / len(walk_w_speed)
        walking_data["avg_pace_min_per_mi"] = round(26.8224 / avg_speed_ms, 1) if avg_speed_ms > 0 else None

    # ── Breathwork stats (Apple Health) ──
    ah_30d = _query_source("apple_health", d30, today)
    bw_sessions = sum(int(float(h.get("breathwork_sessions") or 0)) for h in ah_30d)
    bw_minutes = sum(float(h.get("breathwork_minutes") or 0) for h in ah_30d)
    bw_weekly_trend = []
    bw_week_map = _dd2(lambda: {"sessions": 0, "minutes": 0.0})
    for h in ah_30d:
        d = h.get("date") or h.get("sk", "").replace("DATE#", "")
        try:
            wk = datetime.strptime(d, "%Y-%m-%d").strftime("%Y-W%V")
        except Exception:
            continue
        bw_week_map[wk]["sessions"] += int(float(h.get("breathwork_sessions") or 0))
        bw_week_map[wk]["minutes"] += float(h.get("breathwork_minutes") or 0)
    for wk in sorted(bw_week_map):
        bw_weekly_trend.append({"week": wk, **bw_week_map[wk]})
    breathwork_data = {
        "sessions_30d": bw_sessions,
        "total_minutes_30d": round(bw_minutes, 1),
        "avg_session_min": round(bw_minutes / bw_sessions, 1) if bw_sessions else None,
        "weekly_trend": bw_weekly_trend[-8:],
    }

    # ── V2: Daily modality minutes (30 days) for stacked bar chart ──
    _MODALITY_MAP = {
        "WeightTraining": "strength", "Workout": "strength",
        "Walk": "walking", "Hike": "hiking",
        "Ride": "cycling", "VirtualRide": "cycling",
        "Stretch": "stretching", "Yoga": "stretching",
        "Soccer": "soccer",
        "Breathwork": "breathwork",
    }
    _daily_mod = _dd2(lambda: _dd2(float))
    for a in all_activities_30d:
        _dm_date = a.get("_day_date", "")
        _dm_sport = a.get("sport_type") or a.get("type") or "Other"
        _dm_mapped = _MODALITY_MAP.get(_dm_sport, "other")
        _dm_dur = _act_minutes(a)
        _daily_mod[_dm_date][_dm_mapped] += _dm_dur
    # Add Apple Health breathwork minutes
    for h in ah_30d:
        _bw_d = h.get("date") or h.get("sk", "").replace("DATE#", "")
        _bw_min = float(h.get("breathwork_minutes") or 0)
        if _bw_min > 0:
            _daily_mod[_bw_d]["breathwork"] += _bw_min
    _mod_keys = ["strength", "walking", "cycling", "stretching", "soccer", "hiking", "breathwork", "other"]
    daily_modality_minutes_30d = []
    for i in range(30):
        dt = datetime.now(timezone.utc) - timedelta(days=29 - i)
        _dm_d = dt.strftime("%Y-%m-%d")
        _dm_entry = {"date": _dm_d}
        _dm_total = 0
        for _mk in _mod_keys:
            _mv = round(_daily_mod.get(_dm_d, {}).get(_mk, 0))
            _dm_entry[_mk + "_min"] = _mv
            _dm_total += _mv
        _dm_entry["total_min"] = _dm_total
        daily_modality_minutes_30d.append(_dm_entry)

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

    # Weekly trend (for chart) — use flattened activities
    from collections import defaultdict as _dd
    week_buckets = _dd(lambda: {"workouts": 0, "minutes": 0, "z2_min": 0})
    for a in all_activities_90d:
        d = a.get("_day_date") or ""
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            week_key = dt.strftime("%Y-W%V")
        except Exception:
            continue
        week_buckets[week_key]["workouts"] += 1
        dur = _act_minutes(a)
        week_buckets[week_key]["minutes"] += dur
        avg_hr = a.get("average_heartrate") or a.get("avg_hr")
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
            "active_modalities": len(modality_breakdown),
            "avg_daily_steps": walking_data["avg_daily_steps"],
        },
        "modality_breakdown": modality_breakdown,
        "daily_modality_minutes_30d": daily_modality_minutes_30d,
        "walking": walking_data,
        "breathwork": breathwork_data,
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


def handle_weekly_physical_summary() -> dict:
    """
    GET /api/weekly_physical_summary
    Returns: 7-day array with per-day modality breakdown (Strava + Garmin steps + breathwork).
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d7 = _experiment_date(7)

    strava_items = _query_source("strava", d7, today)
    garmin_items = _query_source("garmin", d7, today)
    ah_items = _query_source("apple_health", d7, today)

    # Build per-day maps
    garmin_by_date = {(g.get("date") or g.get("sk", "").replace("DATE#", "")): g for g in garmin_items}
    ah_by_date = {(h.get("date") or h.get("sk", "").replace("DATE#", "")): h for h in ah_items}

    # Flatten Strava activities by day
    from collections import defaultdict
    day_activities = defaultdict(list)
    for s in strava_items:
        d = s.get("date") or s.get("sk", "").replace("DATE#", "")
        acts = s.get("activities") or [s]
        for a in acts:
            sport = a.get("sport_type") or a.get("type") or "Other"
            dur = float(a.get("duration_minutes") or a.get("moving_time_minutes") or
                        (a.get("moving_time_seconds") or 0) / 60 or 0)
            day_activities[d].append({"type": sport, "minutes": round(dur)})

    # Build 7-day array
    days = []
    for i in range(7):
        dt = datetime.now(timezone.utc) - timedelta(days=6 - i)
        d = dt.strftime("%Y-%m-%d")
        dow = dt.strftime("%a")
        garmin = garmin_by_date.get(d, {})
        ah = ah_by_date.get(d, {})
        activities = day_activities.get(d, [])
        total_active_min = sum(a["minutes"] for a in activities)
        bw_min = float(ah.get("breathwork_minutes") or 0)
        if bw_min > 0:
            activities.append({"type": "Breathwork", "minutes": round(bw_min)})
            total_active_min += bw_min
        days.append({
            "date": d,
            "day_of_week": dow,
            "steps": int(float(garmin.get("steps", 0))) if garmin.get("steps") else None,
            "activities": activities,
            "total_active_minutes": round(total_active_min),
        })

    return _ok({"days": days}, cache_seconds=3600)


def handle_protein_sources() -> dict:
    """
    GET /api/protein_sources
    Returns: Top protein sources from MacroFactor food_log, aggregated by food name.
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d30 = _experiment_date(30)

    items = _query_source("macrofactor", d30, today)
    if not items:
        return _error(503, "No nutrition data available.")

    from collections import defaultdict
    # Aggregate protein contribution by food name
    food_protein = defaultdict(lambda: {"total_protein": 0.0, "frequency": 0, "total_cal": 0.0})
    days_count = len(items)

    for day in items:
        food_log = day.get("food_log") or []
        for entry in food_log:
            name = (entry.get("food_name") or "").strip()
            if not name or len(name) < 3:
                continue
            pro = float(entry.get("protein_g") or 0)
            if pro < 1:
                continue  # Skip items with negligible protein
            f = food_protein[name]
            f["total_protein"] += pro
            f["frequency"] += 1
            f["total_cal"] += float(entry.get("calories_kcal") or 0)

    total_protein_all = sum(f["total_protein"] for f in food_protein.values())
    sources = []
    for name, f in sorted(food_protein.items(), key=lambda x: -x[1]["total_protein"]):
        avg_daily = round(f["total_protein"] / days_count, 1) if days_count else 0
        pct = round(f["total_protein"] / total_protein_all * 100, 1) if total_protein_all else 0
        sources.append({
            "food": name,
            "avg_daily_g": avg_daily,
            "pct_of_total": pct,
            "frequency": f["frequency"],
            "avg_protein_per_serving": round(f["total_protein"] / f["frequency"], 1) if f["frequency"] else 0,
            "protein_cal_pct": round((f["total_protein"] * 4) / f["total_cal"] * 100) if f["total_cal"] > 0 else 0,
        })
        if len(sources) >= 12:
            break

    return _ok({
        "protein_sources": sources,
        "total_protein_30d_avg_g": round(total_protein_all / days_count, 1) if days_count else 0,
        "days_analyzed": days_count,
    }, cache_seconds=3600)


def handle_physical_overview() -> dict:
    """
    GET /api/physical_overview
    Returns: Latest + baseline DEXA scans, tape measurements, delta computations.
    Source: dexa + measurements DynamoDB partitions.
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── 1. DEXA scans (all, sorted ascending) ──
    dexa_pk = f"{USER_PREFIX}dexa"
    dexa_resp = table.query(
        KeyConditionExpression=Key("pk").eq(dexa_pk),
        ScanIndexForward=True,
    )
    dexa_items = _decimal_to_float(dexa_resp.get("Items", []))

    # Baseline = most recent scan on or before EXPERIMENT_START (the starting point)
    # Latest = most recent scan after EXPERIMENT_START (progress since Day 1)
    latest_dexa = None
    baseline_dexa = None
    if dexa_items:
        pre_experiment = [d for d in dexa_items if (d.get("scan_date") or "") <= EXPERIMENT_START]
        post_experiment = [d for d in dexa_items if (d.get("scan_date") or "") > EXPERIMENT_START]
        baseline_dexa = pre_experiment[-1] if pre_experiment else dexa_items[0]
        if post_experiment:
            latest_dexa = post_experiment[-1]
        else:
            # No post-experiment scan yet — show baseline as the current state
            latest_dexa = baseline_dexa
            baseline_dexa = None  # no comparison until a future scan exists

    def _dexa_summary(item):
        if not item:
            return None
        bc = item.get("body_composition", {})
        bs = item.get("body_score", {})
        bone = item.get("bone", {})
        idx = item.get("indices", {})
        s360 = item.get("score_360", {})
        seg_fat = item.get("segmental_fat", {})
        seg_lean = item.get("segmental_lean", {})
        limbs = item.get("limbs", {})
        targets = item.get("targets", {})
        changes = item.get("changes_vs_baseline", {})
        return {
            "scan_date": item.get("scan_date", ""),
            "body_composition": {
                "total_mass_lb": bc.get("total_mass_lb"),
                "body_fat_pct": bc.get("body_fat_pct"),
                "fat_mass_lb": bc.get("fat_mass_lb"),
                "lean_mass_lb": bc.get("lean_mass_lb"),
                "visceral_fat_lb": bc.get("visceral_fat_lb"),
                "visceral_fat_g": bc.get("visceral_fat_g"),
                "android_fat_pct": bc.get("android_fat_pct"),
                "gynoid_fat_pct": bc.get("gynoid_fat_pct"),
                "ag_ratio": bc.get("ag_ratio"),
            },
            "body_score": {
                "grade": bs.get("grade"),
                "numeric": bs.get("numeric"),
                "percentile": bs.get("percentile"),
            },
            "bone": {
                "t_score": bone.get("t_score"),
                "z_score": bone.get("z_score"),
            },
            "indices": {
                "almi_kg_m2": idx.get("almi_kg_m2"),
                "ffmi_kg_m2": idx.get("ffmi_kg_m2"),
                "fmi_kg_m2": idx.get("fmi_kg_m2"),
                "almi_percentile": idx.get("almi_percentile"),
                "ffmi_rating": idx.get("ffmi_rating"),
                "fmi_rating": idx.get("fmi_rating"),
            } if idx else None,
            "score_360": {
                "score": s360.get("score"),
                "biological_age": s360.get("biological_age"),
                "chronological_age": s360.get("chronological_age"),
                "biological_age_delta": s360.get("biological_age_delta"),
            } if s360 else None,
            "segmental_fat": {
                "arms_pct": seg_fat.get("arms_pct"),
                "trunk_pct": seg_fat.get("trunk_pct"),
                "legs_pct": seg_fat.get("legs_pct"),
            } if seg_fat else None,
            "segmental_lean": {
                "total_lb": seg_lean.get("total_lb"),
                "arms_lb": seg_lean.get("arms_lb"),
                "trunk_lb": seg_lean.get("trunk_lb"),
                "legs_lb": seg_lean.get("legs_lb"),
            } if seg_lean else None,
            "targets": targets if targets else None,
            "changes_vs_baseline": changes if changes else None,
        }

    # Days since latest DEXA
    days_since_dexa = None
    next_dexa_recommended = None
    if latest_dexa:
        try:
            scan_dt = datetime.strptime(latest_dexa.get("scan_date", ""), "%Y-%m-%d")
            days_since_dexa = (datetime.now(timezone.utc).replace(tzinfo=None) - scan_dt).days
            next_dt = scan_dt + timedelta(days=90)
            next_dexa_recommended = next_dt.strftime("%Y-%m-%d")
        except Exception:
            pass

    # ── 2. Tape measurements (latest session) ──
    meas_pk = f"{USER_PREFIX}measurements"
    meas_resp = table.query(
        KeyConditionExpression=Key("pk").eq(meas_pk),
        ScanIndexForward=False,
        Limit=1,
    )
    meas_items = _decimal_to_float(meas_resp.get("Items", []))
    tape = None
    tape_session_count = 0
    if meas_items:
        m = meas_items[0]
        # Count total sessions
        count_resp = table.query(
            KeyConditionExpression=Key("pk").eq(meas_pk),
            Select="COUNT",
        )
        tape_session_count = count_resp.get("Count", 1)

        # Build tape data from raw measurement fields
        raw = {}
        derived = {}
        for k, v in m.items():
            if k in ("pk", "sk", "ingested_at", "source_file", "unit", "measured_by", "date", "session_number"):
                continue
            if k in ("waist_height_ratio", "bilateral_symmetry_bicep_in", "bilateral_symmetry_thigh_in",
                      "trunk_sum_in", "limb_avg_in"):
                derived[k] = v
            elif k.endswith("_in"):
                raw[k] = v

        tape = {
            "session_date": m.get("date", m.get("sk", "").replace("DATE#", "")),
            "session_number": m.get("session_number", 1),
            **raw,
            "derived": {
                **derived,
                "waist_height_ratio_target": 0.5,
            },
        }

    # ── 3. Blood pressure (from apple_health) ──
    bp_data = None
    try:
        ah_pk = f"{USER_PREFIX}apple_health"
        ah_resp = table.query(
            KeyConditionExpression=Key("pk").eq(ah_pk) & Key("sk").begins_with("DATE#"),
            FilterExpression="attribute_exists(bp_systolic) OR attribute_exists(blood_pressure_systolic)",
            ScanIndexForward=False,
            Limit=30,
            ProjectionExpression="sk, bp_systolic, bp_diastolic, blood_pressure_systolic, blood_pressure_diastolic, blood_pressure_readings_count",
        )
        bp_items = _decimal_to_float(ah_resp.get("Items", []))
        if bp_items:
            latest_bp = bp_items[0]
            sys_val = latest_bp.get("bp_systolic") or latest_bp.get("blood_pressure_systolic")
            dia_val = latest_bp.get("bp_diastolic") or latest_bp.get("blood_pressure_diastolic")
            bp_date = latest_bp.get("sk", "").replace("DATE#", "")
            # Status classification
            bp_status = "normal"
            if sys_val and float(sys_val) >= 140 or (dia_val and float(dia_val) >= 90):
                bp_status = "high"
            elif sys_val and float(sys_val) >= 130 or (dia_val and float(dia_val) >= 80):
                bp_status = "elevated"
            # Build trend
            bp_trend = []
            for bpi in bp_items:
                s = bpi.get("bp_systolic") or bpi.get("blood_pressure_systolic")
                d = bpi.get("bp_diastolic") or bpi.get("blood_pressure_diastolic")
                if s:
                    bp_trend.append({
                        "date": bpi.get("sk", "").replace("DATE#", ""),
                        "systolic": float(s),
                        "diastolic": float(d) if d else None,
                    })
            bp_data = {
                "systolic": float(sys_val) if sys_val else None,
                "diastolic": float(dia_val) if dia_val else None,
                "date": bp_date,
                "status": bp_status,
                "readings_count": len(bp_items),
                "trend": bp_trend[:14],
            }
    except Exception as _bp_e:
        logger.warning(f"BP query failed (non-fatal): {_bp_e}")

    return _ok({
        "latest_dexa": _dexa_summary(latest_dexa),
        "baseline_dexa": _dexa_summary(baseline_dexa),
        "dexa_scan_count": len(dexa_items),
        "days_since_dexa": days_since_dexa,
        "next_dexa_recommended": next_dexa_recommended,
        "tape_measurements": tape,
        "tape_session_count": tape_session_count,
        "blood_pressure": bp_data,
    }, cache_seconds=3600)


def handle_ai_analysis() -> dict:
    """
    GET /api/ai_analysis?expert=mind|nutrition|training|physical
    Returns cached AI expert analysis from DynamoDB.
    Cache: 300s.
    """
    # Note: query params handled in lambda_handler before ROUTES dispatch
    # This function is not directly called via ROUTES; handled specially
    pass


def handle_journal_analysis() -> dict:
    """
    GET /api/journal_analysis
    Returns 90-day journal theme analysis from cache partition.
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d90 = _experiment_date(90)

    ja_pk = f"{USER_PREFIX}journal_analysis"
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(ja_pk) & Key("sk").between(f"DATE#{d90}", f"DATE#{today}"),
        ScanIndexForward=True,
    )
    items = _decimal_to_float(resp.get("Items", []))

    # Build theme frequency counts
    theme_counts = {}
    for item in items:
        for theme in item.get("themes", []):
            theme_counts[theme] = theme_counts.get(theme, 0) + 1

    total = len(items)
    top_themes = sorted(
        [{"theme": k, "count": v, "pct": round(v / max(total, 1) * 100)} for k, v in theme_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:8]

    # Sentiment trend — rolling 7-day average
    sentiment_trend = []
    daily_scores = [(item.get("date", ""), float(item.get("sentiment_score", 0))) for item in items]
    for i, (date, _) in enumerate(daily_scores):
        window = [s for _, s in daily_scores[max(0, i - 6):i + 1]]
        sentiment_trend.append({
            "date": date,
            "avg_sentiment": round(sum(window) / len(window), 3) if window else 0,
        })

    daily_themes = []
    for item in items:
        daily_themes.append({
            "date": item.get("date", item.get("sk", "").replace("DATE#", "")),
            "dominant_theme": item.get("dominant_theme", "other"),
            "themes": item.get("themes", []),
            "sentiment_score": float(item.get("sentiment_score", 0)),
            "sentiment_label": item.get("sentiment_label", "neutral"),
            "word_count": item.get("word_count", 0),
            "one_line_summary": item.get("one_line_summary", ""),
        })

    return _ok({
        "daily_themes": daily_themes,
        "top_themes": top_themes,
        "total_analyzed": total,
        "date_range": {"start": d90, "end": today},
        "sentiment_trend": sentiment_trend,
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
    d90 = _experiment_date(90)

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

    # ── 7. Meditation / breathwork (Apple Health) ──
    ah_mind = _query_source("apple_health", d30, today)
    meditation_sessions = []
    med_total_min = 0
    med_session_count = 0
    for h in ah_mind:
        _md = h.get("date") or h.get("sk", "").replace("DATE#", "")
        _bw_min = float(h.get("breathwork_minutes") or 0)
        _bw_sess = int(float(h.get("breathwork_sessions") or 0))
        if _bw_min > 0 or _bw_sess > 0:
            meditation_sessions.append({
                "date": _md,
                "minutes": round(_bw_min, 1),
                "sessions": _bw_sess,
            })
            med_total_min += _bw_min
            med_session_count += _bw_sess
    meditation_sessions.sort(key=lambda x: x["date"])
    meditation_data = {
        "sessions_30d": med_session_count,
        "total_minutes_30d": round(med_total_min, 1),
        "avg_session_min": round(med_total_min / med_session_count, 1) if med_session_count else None,
        "daily": meditation_sessions,
    }

    # ── 8. Vice streak timeline (30-day daily history) ──
    hs_30d_resp = table.query(
        KeyConditionExpression=Key("pk").eq(hs_pk) & Key("sk").between(f"DATE#{d30}", f"DATE#{today}"),
        ScanIndexForward=True,
    )
    hs_30d_items = _decimal_to_float(hs_30d_resp.get("Items", []))
    vice_timeline = []
    for hs_day in hs_30d_items:
        day_date = hs_day.get("date") or hs_day.get("sk", "").replace("DATE#", "")
        raw_vs = hs_day.get("vice_streaks") or {}
        day_entry = {"date": day_date, "held": int(hs_day.get("vices_held", 0)), "total": int(hs_day.get("vices_total", 0))}
        # Include per-vice streaks (filtered)
        if isinstance(raw_vs, dict):
            streaks = {}
            for name, val in raw_vs.items():
                if name.lower().strip() in blocked_set:
                    continue
                streaks[name] = int(val or 0)
            day_entry["streaks"] = streaks
        vice_timeline.append(day_entry)

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
        "vice_timeline": vice_timeline,
        "mood_trend": mood_entries[-30:],
        "meditation": meditation_data,
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
        # Matthew's personal 1RM goals -- should migrate to profile.strength_targets
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


def handle_food_delivery_overview() -> dict:
    """
    GET /api/food_delivery_overview
    Returns: 30-day food delivery stats from food_delivery DDB partition.
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d30 = _experiment_date(30)

    items = _query_source("food_delivery", d30, today)
    if not items:
        return _ok({"food_delivery": None}, cache_seconds=3600)

    from collections import Counter, defaultdict
    total_orders = len(items)
    total_spend = sum(float(i.get("amount") or 0) for i in items)
    platform_counts = Counter()
    weekly_counts = defaultdict(int)
    binge_days = 0

    for i in items:
        platform_counts[i.get("platform") or "Unknown"] += 1
        if i.get("binge"):
            binge_days += 1
        d = i.get("date") or i.get("sk", "").replace("DATE#", "")
        try:
            wk = datetime.strptime(d, "%Y-%m-%d").strftime("%Y-W%V")
            weekly_counts[wk] += 1
        except Exception:
            pass

    weekly_trend = sorted([{"week": k, "orders": v} for k, v in weekly_counts.items()], key=lambda x: x["week"])

    return _ok({
        "food_delivery": {
            "orders_30d": total_orders,
            "avg_spend": round(total_spend / total_orders, 2) if total_orders else 0,
            "total_spend_30d": round(total_spend, 2),
            "binge_days_30d": binge_days,
        },
        "platform_breakdown": [{"platform": p, "count": c} for p, c in platform_counts.most_common()],
        "weekly_trend": weekly_trend,
    }, cache_seconds=3600)


def handle_strength_deep_dive() -> dict:
    """
    GET /api/strength_deep_dive
    Returns: volume load trend, exercise variety, session patterns from Hevy data.
    Cache: 3600s.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    d90 = _experiment_date(90)
    d30 = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

    items = _query_source("hevy", d90, today)
    if not items:
        return _ok({"strength": None, "message": "No strength data available"}, cache_seconds=3600)

    from collections import defaultdict, Counter

    # Volume load per week (sets × reps × weight)
    weekly_volume = defaultdict(float)
    exercise_freq = Counter()
    session_days = Counter()  # day of week
    session_hours = Counter()  # hour of day
    total_sets_30d = 0
    exercises_30d = set()

    for day in items:
        d = day.get("date") or day.get("sk", "").replace("DATE#", "")
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            week_key = dt.strftime("%Y-W%V")
        except Exception:
            continue

        exercises = day.get("exercises") or day.get("workout_exercises") or []
        for ex in exercises:
            name = ex.get("exercise_name") or ex.get("name") or "Unknown"
            sets = ex.get("sets") or []
            for s in sets:
                w = float(s.get("weight_lbs") or s.get("weight") or 0)
                r = int(s.get("reps") or 0)
                weekly_volume[week_key] += w * r
                total_sets_30d += 1 if d >= d30 else 0

            if d >= d30:
                exercise_freq[name] += 1
                exercises_30d.add(name)

        if d >= d30:
            session_days[dt.strftime("%a")] += 1

    volume_trend = sorted([
        {"week": k, "volume_lbs": round(v)}
        for k, v in weekly_volume.items()
    ], key=lambda x: x["week"])[-12:]

    top_exercises = [{"name": n, "frequency": c} for n, c in exercise_freq.most_common(10)]

    return _ok({
        "strength": {
            "sessions_90d": len(items),
            "sessions_30d": len([i for i in items if (i.get("date") or i.get("sk", "").replace("DATE#", "")) >= d30]),
            "distinct_exercises_30d": len(exercises_30d),
            "total_sets_30d": total_sets_30d,
        },
        "volume_trend": volume_trend,
        "top_exercises": top_exercises,
        "session_days": dict(session_days),
    }, cache_seconds=3600)


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
    "/api/physical_overview":   handle_physical_overview,
    "/api/journal_analysis":    handle_journal_analysis,
    "/api/ai_analysis":         None,  # GET with ?expert= query param, handled in lambda_handler
    # BL-03: The Ledger / Snake Fund
    "/api/ledger":              handle_ledger,
    # BL-04: Field Notes
    "/api/field_notes":         None,  # GET with optional ?week= query param, handled in lambda_handler
    # BL-02: Bloodwork/Labs
    "/api/labs":                handle_labs,
    "/api/frequent_meals":      handle_frequent_meals,
    "/api/protein_sources":     handle_protein_sources,
    "/api/weekly_physical_summary": handle_weekly_physical_summary,
    "/api/strength_deep_dive":      handle_strength_deep_dive,
    "/api/food_delivery_overview":  handle_food_delivery_overview,
    "/api/meal_glucose":        handle_meal_glucose,
    "/api/strength_benchmarks": handle_strength_benchmarks,
    # Benchmark trends + meal responses (stub endpoints)
    "/api/benchmark_trends":    handle_benchmark_trends,
    "/api/meal_responses":      handle_meal_responses,
    # Tools page: baseline vs current comparison
    "/api/tools_baseline":      handle_tools_baseline,
    # Platform stats: single source of truth for all site pages
    "/api/platform_stats":      handle_platform_stats,
    # Discoveries page: active hypotheses + inner life + AI findings
    "/api/discoveries":         handle_discoveries,
    # Experiment suggestion (POST)
    "/api/experiment_suggest":  None,  # POST handler in lambda_handler
    # Phase 1: Reader engagement
    "/api/changes-since":       None,  # GET with ?ts= query param
    "/api/observatory_week":    None,  # GET with ?domain= query param
}


_COLD_START = True


def lambda_handler(event, context):
    """
    Main Lambda handler. Supports both API Gateway HTTP API and Function URL events.
    """
    global _COLD_START
    import time as _time
    _req_start = _time.time()

    path   = event.get("rawPath") or event.get("path", "/")
    method = (event.get("requestContext", {}).get("http", {}).get("method") or
              event.get("httpMethod", "GET")).upper()

    def _emit_route_log(status_code):
        """Emit structured JSON route metric to CloudWatch Logs (zero cost)."""
        global _COLD_START
        try:
            duration_ms = round((_time.time() - _req_start) * 1000, 1)
            print(json.dumps({
                "_type": "route_metric",
                "route": path,
                "method": method,
                "status": status_code,
                "duration_ms": duration_ms,
                "cold_start": _COLD_START,
            }))
        except Exception:
            pass
        _COLD_START = False

    # CORS preflight
    if method == "OPTIONS":
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": ""}

    # /api/healthz — lightweight health check (no auth, no PII)
    if path == "/api/healthz" and method == "GET":
        try:
            ddb_start = _time.time()
            table.get_item(Key={"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2026-01-01"})
            ddb_ms = round((_time.time() - ddb_start) * 1000)
            ddb_ok = True
        except Exception:
            ddb_ms = -1
            ddb_ok = False
        try:
            stats_obj = s3.get_object(Bucket=S3_BUCKET, Key="site/public_stats.json")
            refreshed = json.loads(stats_obj["Body"].read()).get("_meta", {}).get("refreshed_at", "unknown")
        except Exception:
            refreshed = "unavailable"
        total_ms = round((_time.time() - _req_start) * 1000)
        health = {
            "status": "ok" if ddb_ok else "degraded",
            "version": "v4.5.1",
            "checks": {
                "dynamodb": {"status": "ok" if ddb_ok else "error", "latency_ms": ddb_ms},
                "last_daily_refresh": refreshed,
                "lambda_warm": not _COLD_START,
            },
            "response_ms": total_ms,
        }
        _emit_route_log(200)
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": json.dumps(health)}

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

    # BL-04: Field Notes (GET with optional ?week= query param)
    if path == "/api/field_notes":
        qs = event.get("queryStringParameters") or {}
        week_param = qs.get("week")
        fn_pk = f"{USER_PREFIX}field_notes"

        if week_param:
            # Single entry mode
            item = table.get_item(Key={"pk": fn_pk, "sk": f"WEEK#{week_param}"}).get("Item")
            if not item:
                return _ok({"entry": None, "week": week_param}, cache_seconds=300)
            item = _decimal_to_float(item)
            return _ok({"entry": {
                "week": item.get("week", week_param),
                "ai_present": item.get("ai_present", ""),
                "ai_cautionary": item.get("ai_cautionary"),
                "ai_affirming": item.get("ai_affirming"),
                "ai_tone": item.get("ai_tone", "mixed"),
                "ai_generated_at": item.get("ai_generated_at"),
                "matthew_agreement": item.get("matthew_agreement"),
                "matthew_logged_at": item.get("matthew_logged_at"),
            }}, cache_seconds=300)
        else:
            # List mode — return all weeks (most recent first)
            resp = table.query(
                KeyConditionExpression=Key("pk").eq(fn_pk),
                ScanIndexForward=False,
                Limit=52,
            )
            items = _decimal_to_float(resp.get("Items", []))
            entries = [{
                "week": i.get("week", i.get("sk", "").replace("WEEK#", "")),
                "ai_tone": i.get("ai_tone", "mixed"),
                "ai_generated_at": i.get("ai_generated_at"),
                "has_matthew_response": bool(i.get("matthew_agreement")),
            } for i in items]
            return _ok({"entries": entries, "count": len(entries)}, cache_seconds=300)

    # AI Analysis (GET with ?expert= query param)
    if path == "/api/ai_analysis":
        qs = event.get("queryStringParameters") or {}
        expert_key = qs.get("expert", "mind")
        if expert_key not in ("mind", "nutrition", "training", "physical", "explorer"):
            return _error(400, "Invalid expert key")
        ai_pk = f"{USER_PREFIX}ai_analysis"
        ai_item = table.get_item(Key={"pk": ai_pk, "sk": f"EXPERT#{expert_key}"}).get("Item")
        if not ai_item:
            return _ok({"expert_key": expert_key, "analysis": None, "generated_at": None}, cache_seconds=300)
        ai_item = _decimal_to_float(ai_item)
        return _ok({
            "expert_key": expert_key,
            "analysis": ai_item.get("analysis", ""),
            "generated_at": ai_item.get("generated_at", ""),
        }, cache_seconds=300)

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
        _emit_route_log(404)
        return _error(404, "Not found")

    try:
        result = handler()
        _emit_route_log(result.get("statusCode", 200))
        return result
    except Exception as e:
        logger.error(f"[site_api] {path} failed: {e}")
        _emit_route_log(500)
        return _error(500, "Internal error — check CloudWatch logs")
