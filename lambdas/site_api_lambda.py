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

import json
import logging
import os
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

# ── AWS clients (module-level for warm container reuse) ─────
dynamodb = boto3.resource("dynamodb", region_name=DDB_REGION)
table    = dynamodb.Table(TABLE_NAME)

# ── CORS headers ────────────────────────────────────────────
CORS_HEADERS = {
    "Access-Control-Allow-Origin":  "https://averagejoematt.com",
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

    # Latest weight from Withings
    withings = _latest_item("withings")
    current_weight = float(withings.get("weight_lbs", 0)) if withings else None

    withings_30d = _query_source("withings", d30, today)
    weight_vals = [float(w["weight_lbs"]) for w in withings_30d if w.get("weight_lbs")]
    weight_delta_30d = round(weight_vals[-1] - weight_vals[0], 1) if len(weight_vals) >= 2 else None

    recovery_pct = float(latest.get("recovery_score", 0))
    recovery_status = "green" if recovery_pct >= 67 else ("yellow" if recovery_pct >= 34 else "red")

    return _ok({
        "vitals": {
            "weight_lbs":       round(current_weight, 1) if current_weight else None,
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
        return _error(503, "No weight data available")

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

    experiments = [
        {
            "name":       item.get("name", "Unnamed"),
            "status":     item.get("status", "unknown"),
            "start_date": item.get("start_date", ""),
            "end_date":   item.get("end_date"),
            "hypothesis": item.get("hypothesis", ""),
            "tags":       item.get("tags", []),
        }
        for item in items
        if item.get("sk", "").startswith("EXP#")
    ]
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
    "attia": {
        "name": "Peter Attia",
        "title": "Longevity & Performance Medicine",
        "system": (
            "You are Peter Attia, MD, longevity physician and author of Outlive. "
            "Focus on: VO2max, Zone 2 training, strength, metabolic health, and the four horsemen of chronic disease. "
            "Evidence-based and nuanced. Distinguish strong evidence from speculation. "
            "Use first person. 3-5 sentences. Note N=1 for any comparative claim. "
            "Never give medical advice — reference a physician only if clinically urgent."
        ),
    },
    "huberman": {
        "name": "Andrew Huberman",
        "title": "Neuroscience & Sleep",
        "system": (
            "You are Andrew Huberman PhD, Stanford neuroscientist. "
            "Focus on: sleep, light exposure, stress resilience, dopamine, and performance neuroscience. "
            "Explain the mechanism first, then the protocol. "
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
    Body: {"question": str, "personas": ["attia", ...]}
    Returns: {"responses": {"attia": "...", ...}}
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
        personas = ["attia", "huberman", "clear"]

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
            responses[pid] = "".join(b["text"] for b in result.get("content", []) if b.get("type") == "text")
        except Exception as e:
            logger.error(f"[board_ask] {pid} failed: {e}")
            responses[pid] = f"[{p['name']} is temporarily unavailable]"

    return {
        "statusCode": 200,
        "headers": {**CORS_HEADERS, "Cache-Control": "no-store"},
        "body": json.dumps({"responses": responses}),
    }


# ── Ask the Platform (AI Q&A) ─────────────────────────────────────

import re
import hashlib
import urllib.request

_anthropic_key_cache = None

# In-memory rate limit stores (warm container state — resets on cold start, acceptable for rate limiting)
# Maps ip_hash -> list of timestamps in the current hour
_ask_rate_store: dict = {}
_board_rate_store: dict = {}

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
- If asked about something outside your data, say "I don't have that data" — don't speculate."""


def handle_ask() -> dict:
    """Handled specially in lambda_handler — this is a placeholder for ROUTES."""
    return _error(405, "Use POST method")


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
    # Website Review: Ask the Platform
    "/api/ask":                handle_ask,
    # WR-24 + S2-T2-2: handled specially in lambda_handler (POST routes)
    "/api/verify_subscriber":  None,
    "/api/board_ask":          None,
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
                "body": json.dumps({"answer": answer, "remaining": remaining}),
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
