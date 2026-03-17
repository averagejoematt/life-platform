"""
Daily Insight Compute Lambda — IC-2 v1.3.0
Scheduled at 9:42 AM PT (17:42 UTC via EventBridge).

Transforms raw pre-computed metrics into curated coaching intelligence
for the Daily Brief's AI calls. Bridges the gap between data and insight:
the Brief's AI calls stop getting raw numbers and start getting context.

Reads from (already computed by 9:40 AM):
  - SOURCE#computed_metrics    — day grade, component scores, readiness (7-day history)
  - SOURCE#habit_scores        — tier-level completion rates (7-day history)
  - SOURCE#day_grade           — 14-day grade history for momentum trend
  - SOURCE#platform_memory     — coaching_calibration, what_worked, failure_pattern

Writes to:
  - SOURCE#computed_insights   — structured intelligence record
  - SOURCE#platform_memory     — MEMORY#intention_tracking#<date> (IC-8)

Output consumed by:
  - ai_calls.py: all 4 AI calls inject `ai_context_block` as platform intelligence

Schedule:
  9:40 AM PT  daily-metrics-compute  (writes computed_metrics + habit_scores)
  9:42 AM PT  daily-insight-compute  ← this Lambda
  10:00 AM PT daily-brief            (reads computed_insights via data["computed_insights"])

v1.4.0 — 2026-03-13 (TB7-22: equalize slow drift windows)
  - _compute_slow_drift(): windows changed from 7d recent/8-28d baseline
    to 14d recent/15-28d baseline (equal 14d windows, same SE of mean)
v1.3.0 — 2026-03-11 (IC-19: Slow Drift + Experiment Context)
  - _compute_slow_drift(): non-overlapping 7d vs 8-28d windows, min N=14 (Henning)
  - Weight plateau: regression slope on >=8 measurements, not endpoint (Attia)
  - Weight plateau: MacroFactor TDEE preferred over Apple Watch (Webb/Norton)
  - Recomposition caveat + >=11 complete log day gate (Okafor/Henning)
  - Circadian consistency note when HRV/recovery drift fires (Huberman)
  - slow_drift_metrics stored on computed_insights with baseline_n (Omar)
  - _build_experiment_context(): descriptive active experiment injection (Anika/Raj)
  - _build_prioritized_context_block(): priority queue + 700-token budget (Priya)
  - Social quality flag when multiple drift + sparse journal (Murthy)
v1.2.0 — 2026-03-09 (IC-5: Early Warning Detection — multi-marker proactive alert)
v1.1.0 — 2026-03-08 (IC-8: Intent vs Execution Gap)
"""

import json
import math
import os
import statistics
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import urllib.request
import urllib.error

import boto3

# OBS-1: Structured logger — JSON output for CloudWatch Logs Insights
try:
    from platform_logger import get_logger
    logger = get_logger("daily-insight-compute")
except ImportError:
    logger = logging.getLogger("daily-insight-compute")
    logger.setLevel(logging.INFO)

_REGION     = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME  = os.environ.get("TABLE_NAME", "life-platform")
USER_ID     = os.environ["USER_ID"]

USER_PREFIX = f"USER#{USER_ID}#SOURCE#"
PROFILE_PK  = f"USER#{USER_ID}"

ANTHROPIC_API  = "https://api.anthropic.com/v1/messages"
_api_key_cache = None

dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table    = dynamodb.Table(TABLE_NAME)

# AI model constant — read from env so model can be updated without redeployment
AI_MODEL_HAIKU = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")

# BS-MP3: Decision Fatigue Detector — proactive alert threshold
DECISION_FATIGUE_THRESHOLD = int(os.environ.get("DECISION_FATIGUE_THRESHOLD", "15"))
DECISION_FATIGUE_HABIT_THRESHOLD = float(os.environ.get("DECISION_FATIGUE_HABIT_THRESHOLD", "0.60"))


# ==============================================================================
# HELPERS
# ==============================================================================

def d2f(obj):
    if isinstance(obj, list):    return [d2f(i) for i in obj]
    if isinstance(obj, dict):    return {k: d2f(v) for k, v in obj.items()}
    if isinstance(obj, Decimal): return float(obj)
    return obj


def safe_float(rec, field, default=None):
    if rec and field in rec:
        try:   return float(rec[field])
        except Exception: return default
    return default


def fetch_date(source, date_str):
    try:
        r = table.get_item(Key={"pk": USER_PREFIX + source, "sk": "DATE#" + date_str})
        return d2f(r.get("Item"))
    except Exception as e:
        logger.warning(f"fetch_date({source}, {date_str}): {e}")
        return None


def fetch_range(source, start, end):
    try:
        records = []
        kwargs = {
            "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
            "ExpressionAttributeValues": {":pk": USER_PREFIX + source,
                                          ":s": "DATE#" + start, ":e": "DATE#" + end},
        }
        while True:
            r = table.query(**kwargs)
            records.extend(d2f(i) for i in r.get("Items", []))
            if "LastEvaluatedKey" not in r:
                break
            kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]
        return records
    except Exception as e:
        logger.warning(f"fetch_range({source}): {e}")
        return []


def fetch_profile():
    try:
        r = table.get_item(Key={"pk": PROFILE_PK, "sk": "PROFILE#v1"})
        return d2f(r.get("Item", {}))
    except Exception as e:
        logger.error(f"fetch_profile: {e}")
        return {}


def fetch_memory_records(category, days=30):
    """Load platform_memory records for a given category."""
    today = datetime.now(timezone.utc).date()
    start = (today - timedelta(days=days)).isoformat()
    pk = USER_PREFIX + "platform_memory"
    start_sk = f"MEMORY#{category}#{start}"
    end_sk   = f"MEMORY#{category}#~"
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={":pk": pk, ":s": start_sk, ":e": end_sk},
            ScanIndexForward=False,
            Limit=5,
        )
        return [d2f(i) for i in resp.get("Items", [])]
    except Exception as e:
        logger.warning(f"fetch_memory({category}): {e}")
        return []


# ==============================================================================
# MOMENTUM COMPUTATION
# ==============================================================================

def compute_momentum(grade_records_14d, yesterday_str):
    """Compare this week vs last week average grade.

    Returns: (signal, this_week_avg, prev_week_avg, trend_pct)
    """
    week_boundary = (
        datetime.strptime(yesterday_str, "%Y-%m-%d") - timedelta(days=7)
    ).strftime("%Y-%m-%d")

    this_week, prev_week = [], []
    for rec in grade_records_14d:
        date_str = rec.get("date", "") or rec.get("sk", "").replace("DATE#", "")
        score = safe_float(rec, "day_grade_score") or safe_float(rec, "total_score")
        if score is None:
            continue
        if date_str > week_boundary:
            this_week.append(score)
        else:
            prev_week.append(score)

    this_avg = round(sum(this_week) / len(this_week), 1) if this_week else None
    prev_avg = round(sum(prev_week) / len(prev_week), 1) if prev_week else None

    if this_avg is None:
        return "unknown", None, None, None
    if prev_avg is None:
        return "stable", this_avg, None, None

    trend_pct = round((this_avg - prev_avg) / max(prev_avg, 1) * 100, 1)
    if trend_pct > 5:
        signal = "improving"
    elif trend_pct < -5:
        signal = "declining"
    else:
        signal = "stable"

    return signal, this_avg, prev_avg, trend_pct


# ==============================================================================
# METRIC TREND DETECTION
# ==============================================================================

def detect_metric_trends(computed_records_7d):
    """Detect 3+ consecutive day runs in key metrics (leading indicators).

    Uses pre-computed records so this is cheap — no raw DDB reads needed.
    Returns: (declining_list, improving_list), each item:
      {metric, consecutive_days, current, baseline_7d_avg, delta_pct}
    """
    TOP_METRICS  = ["day_grade_score", "readiness_score"]
    COMP_METRICS = ["sleep_quality", "recovery", "nutrition", "movement", "habits_mvp"]

    series = {m: [] for m in TOP_METRICS + COMP_METRICS}
    for rec in sorted(computed_records_7d, key=lambda x: x.get("date", "")):
        date_str    = rec.get("date") or rec.get("sk", "").replace("DATE#", "")
        comp_scores = rec.get("component_scores", {})
        for m in TOP_METRICS:
            val = safe_float(rec, m)
            if val is not None:
                series[m].append((date_str, val))
        for m in COMP_METRICS:
            val = safe_float(comp_scores, m)
            if val is not None:
                series[m].append((date_str, val))

    declining, improving = [], []
    for metric, pts in series.items():
        if len(pts) < 3:
            continue
        recent      = pts[-3:]
        baseline_7d = round(sum(v for _, v in pts) / len(pts), 1)

        if all(recent[i][1] < recent[i - 1][1] for i in range(1, len(recent))):
            delta_pct = round((recent[-1][1] - recent[0][1]) / max(recent[0][1], 1) * 100, 1)
            declining.append({
                "metric": metric, "consecutive_days": 3,
                "current": round(recent[-1][1]), "baseline_7d_avg": baseline_7d,
                "delta_pct": delta_pct,
            })

        elif all(recent[i][1] > recent[i - 1][1] for i in range(1, len(recent))):
            delta_pct = round((recent[-1][1] - recent[0][1]) / max(recent[0][1], 1) * 100, 1)
            improving.append({
                "metric": metric, "consecutive_days": 3,
                "current": round(recent[-1][1]), "baseline_7d_avg": baseline_7d,
                "delta_pct": delta_pct,
            })

    return declining, improving


# ==============================================================================
# HABIT PATTERN ANALYSIS
# ==============================================================================

def compute_habit_patterns(habit_score_records_7d, profile):
    """Compute 7-day habit miss rates from pre-computed habit_scores records.

    Returns: (miss_rates, strongest_habits, weakest_habits, synergy_health)
    """
    registry = profile.get("habit_registry", {})
    if not registry or not habit_score_records_7d:
        return {}, [], [], {}

    t0_miss_counts = {}
    t0_total_days  = 0
    for rec in habit_score_records_7d:
        missed = rec.get("missed_tier0") or []
        t0_total_days += 1
        for h in missed:
            t0_miss_counts[h] = t0_miss_counts.get(h, 0) + 1

    miss_rates = {}
    if t0_total_days > 0:
        for h, count in t0_miss_counts.items():
            miss_rates[h] = round(count / t0_total_days, 2)

    synergy_avg = {}
    for rec in habit_score_records_7d:
        sg = rec.get("synergy_groups") or {}
        for group, pct in sg.items():
            synergy_avg.setdefault(group, []).append(float(pct))
    synergy_health = {g: round(sum(v) / len(v), 2) for g, v in synergy_avg.items()}

    t0_completion_rates = {}
    for name, meta in registry.items():
        if meta.get("status") != "active" or meta.get("tier", 2) != 0:
            continue
        days_missed    = t0_miss_counts.get(name, 0)
        days_available = t0_total_days
        if days_available > 0:
            t0_completion_rates[name] = round(1 - days_missed / days_available, 2)

    strongest = [h for h, r in sorted(t0_completion_rates.items(), key=lambda x: -x[1])
                 if r >= 0.8][:5]
    weakest   = [h for h, r in sorted(t0_completion_rates.items(), key=lambda x: x[1])
                 if r <= 0.4][:5]

    return miss_rates, strongest, weakest, synergy_health


# ==============================================================================
# PLATFORM MEMORY CONTEXT BUILDER
# ==============================================================================

def build_memory_context():
    """Load relevant platform memory records and format as coaching context string.

    Prioritizes: coaching_calibration > what_worked > failure_pattern.
    Returns empty string if no records exist yet.
    """
    lines = []

    calibration = fetch_memory_records("coaching_calibration", days=90)
    if calibration:
        latest = calibration[0]
        note = latest.get("note") or latest.get("content") or ""
        if isinstance(note, dict):
            note = json.dumps(note)
        if note:
            lines.append(f"COACHING CALIBRATION: {str(note)[:200]}")

    what_worked = fetch_memory_records("what_worked", days=60)
    if what_worked:
        lines.append("WHAT HAS WORKED (recent episodes):")
        for rec in what_worked[:2]:
            conditions = rec.get("conditions", "")
            behaviors  = rec.get("behaviors", "")
            outcomes   = rec.get("outcomes", "")
            if conditions or behaviors:
                lines.append(f"  When {conditions}: {behaviors} → {outcomes}"[:150])

    failure_patterns = fetch_memory_records("failure_pattern", days=60)
    if failure_patterns:
        lines.append("KNOWN FAILURE PATTERNS:")
        for rec in failure_patterns[:2]:
            pattern = rec.get("pattern") or rec.get("note") or ""
            if isinstance(pattern, dict):
                pattern = json.dumps(pattern)
            if pattern:
                lines.append(f"  {str(pattern)[:120]}")

    return "\n".join(lines)


# ==============================================================================
# IC-8: INTENT VS EXECUTION GAP
# Compares stated journal intentions against next-day actual metrics.
# Accumulates recurring gap patterns in platform_memory.
# One Haiku call per day (~$0.001). Non-fatal throughout.
#
# Data flow:
#   Morning journal todays_intention  ─┐
#   Prev-evening tomorrow_focus       ─┼─→ Haiku evaluation → platform_memory
#   Actual metrics (nutrition/sleep/  ─┘         ↓
#   exercise/habits)                        ai_context_block injection
# ==============================================================================

def _get_api_key():
    """Lazy-load Anthropic API key from Secrets Manager."""
    global _api_key_cache
    if _api_key_cache:
        return _api_key_cache
    secrets_client = boto3.client("secretsmanager", region_name=_REGION)
    secret_name = os.environ.get("ANTHROPIC_SECRET", "life-platform/ai-keys")
    resp = secrets_client.get_secret_value(SecretId=secret_name)
    _api_key_cache = json.loads(resp["SecretString"])["anthropic_api_key"]
    return _api_key_cache


def _fetch_journal_for_date(date_str):
    """Fetch all notion journal entries for a given date."""
    pk = USER_PREFIX + "notion"
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={
                ":pk": pk,
                ":s": f"DATE#{date_str}#journal",
                ":e": f"DATE#{date_str}#journal#~",
            },
        )
        return [d2f(i) for i in resp.get("Items", [])]
    except Exception as e:
        logger.warning(f"_fetch_journal_for_date({date_str}): {e}")
        return []


def _extract_intention_texts(journal_entries):
    """Pull intention texts from journal entries.

    Returns dict: {"today": str|None, "tomorrow": str|None}
      "today"    -- morning check-in todays_intention
      "tomorrow" -- evening reflection tomorrow_focus
    """
    result = {"today": None, "tomorrow": None}
    for entry in journal_entries:
        ti = (entry.get("todays_intention") or "").strip()
        if ti and len(ti) > 5 and not result["today"]:
            result["today"] = ti

        tf = (entry.get("tomorrow_focus") or "").strip()
        if tf and len(tf) > 5 and not result["tomorrow"]:
            result["tomorrow"] = tf

    return result


def _fetch_execution_metrics(date_str, profile):
    """Fetch execution metrics for a date to check intention follow-through.

    Returns a compact dict with enough context for Haiku evaluation.
    """
    metrics     = {}
    cal_target  = profile.get("calorie_target", 1800)
    prot_target = profile.get("protein_target_g", 190)

    # Nutrition (MacroFactor)
    mf = fetch_date("macrofactor", date_str)
    if mf:
        cal   = safe_float(mf, "total_calories_kcal")
        prot  = safe_float(mf, "total_protein_g")
        items = len(mf.get("food_log", []))
        if cal is not None:
            metrics["calories_logged"]   = int(cal)
            metrics["calorie_target"]    = cal_target
            metrics["food_items_logged"] = items
            if cal < cal_target * 0.65:
                metrics["nutrition_note"] = (
                    f"Likely incomplete log -- only {int(cal)} cal logged vs {cal_target} target"
                )
        if prot is not None:
            metrics["protein_g"]        = int(prot)
            metrics["protein_target_g"] = prot_target

    # Activity (Strava)
    strava = fetch_date("strava", date_str)
    if strava:
        act_count  = int(strava.get("activity_count") or 0)
        activities = strava.get("activities", [])
        metrics["exercise_sessions"] = act_count
        if activities:
            metrics["exercise_types"] = [a.get("sport_type", "?") for a in activities[:3]]
    else:
        metrics["exercise_sessions"] = 0

    # Sleep (Whoop -- for bed-time intention checking)
    whoop = fetch_date("whoop", date_str)
    if whoop:
        sleep_start = whoop.get("sleep_start", "")
        if sleep_start and "T" in sleep_start:
            metrics["sleep_start_time"] = sleep_start.split("T")[1][:5]
        rec = safe_float(whoop, "recovery_score")
        if rec is not None:
            metrics["recovery_score"] = int(rec)

    # Habits (habit_scores partition)
    hs = fetch_date("habit_scores", date_str)
    if hs:
        t0_done  = int(hs.get("tier0_done") or 0)
        t0_total = int(hs.get("tier0_total") or 0)
        if t0_total > 0:
            metrics["habit_tier0_pct"]    = round(t0_done / t0_total * 100)
            metrics["habit_tier0_detail"] = f"{t0_done}/{t0_total} T0 habits completed"
        missed = hs.get("missed_tier0") or []
        if missed:
            metrics["missed_tier0_habits"] = missed[:5]

    return metrics


def _evaluate_intentions_haiku(intentions_dict, execution_metrics, api_key):
    """Haiku call: evaluate which stated intentions were actually executed.

    Returns list of dicts: [{type, text, executed, evidence, confidence}, ...]
    Returns [] on failure (non-fatal).
    """
    parts = []
    if intentions_dict.get("today"):
        parts.append(f"[Morning intention] {intentions_dict['today']}")
    if intentions_dict.get("tomorrow"):
        parts.append(f"[Previous-evening plan] {intentions_dict['tomorrow']}")

    if not parts:
        return []

    intentions_str = "\n".join(parts)
    metrics_str    = json.dumps(execution_metrics, indent=2)

    prompt = f"""Evaluate which stated intentions were executed based on actual metrics.

STATED INTENTIONS:
{intentions_str}

ACTUAL METRICS:
{metrics_str}

For each distinct intention evaluate:
1. type -- one of: sleep_timing / food_logging / protein_goal / exercise / walk /
          meal_prep / stress_management / habit_completion / hydration / generic
2. executed -- true if clearly followed through, false otherwise
3. evidence -- specific metric reference (keep to 15 words or less)
4. confidence -- high/medium/low (low = insufficient data to judge)

Rules:
- Skip intentions with no corresponding metric to check.
- Partial execution (e.g. some food logged but far below target) = false.
- Any exercise session counts for a generic "exercise" intention.
- If a log looks incomplete (nutrition_note present), treat food-logging as false.
- Be conservative -- if evidence is unclear, lean toward executed=false with confidence=low.

Return ONLY a JSON array, no preamble:
[{{"type": "sleep_timing", "text": "get to bed by 10", "executed": false, "evidence": "sleep start 23:30 -- 90 min late", "confidence": "high"}}]"""

    payload = json.dumps({
        "model": AI_MODEL_HAIKU,
        "max_tokens": 600,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(
        ANTHROPIC_API, data=payload,
        headers={"Content-Type": "application/json", "x-api-key": api_key,
                 "anthropic-version": "2023-06-01"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = json.loads(r.read())["content"][0]["text"].strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            return json.loads(raw.strip())
    except Exception as e:
        logger.warning(f"IC-8 Haiku evaluation failed: {e}")
        return []


def _load_intention_history(yesterday_str):
    """Load last 14 days of intention_tracking records from platform_memory."""
    start = (
        datetime.strptime(yesterday_str, "%Y-%m-%d") - timedelta(days=14)
    ).strftime("%Y-%m-%d")
    pk = USER_PREFIX + "platform_memory"
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={
                ":pk": pk,
                ":s": f"MEMORY#intention_tracking#{start}",
                ":e": f"MEMORY#intention_tracking#{yesterday_str}",
            },
            ScanIndexForward=False,
            Limit=14,
        )
        records = []
        for item in resp.get("Items", []):
            rec       = d2f(item)
            evals_raw = rec.get("evaluations", "[]")
            if isinstance(evals_raw, str):
                try:
                    rec["evaluations"] = json.loads(evals_raw)
                except Exception:
                    rec["evaluations"] = []
            records.append(rec)
        return records
    except Exception as e:
        logger.warning(f"_load_intention_history: {e}")
        return []


def _compute_intention_patterns(history_records):
    """Compute recurring gap patterns from historical intention tracking records.

    Returns dict:
      gap_types_ranked:       [{type, stated, missed, miss_rate}] by miss_rate desc
      follow_through_rate_7d: float 0-1 or None
    """
    if not history_records:
        return {}

    type_stated = {}
    type_missed = {}
    day_rates   = []

    for rec in history_records:
        evals = rec.get("evaluations", [])
        if not evals:
            continue
        day_total = len(evals)
        day_exec  = sum(
            1 for e in evals if e.get("executed") and e.get("confidence") != "low"
        )
        day_rates.append(day_exec / day_total if day_total else 0)

        for ev in evals:
            itype = ev.get("type", "generic")
            type_stated[itype] = type_stated.get(itype, 0) + 1
            if not ev.get("executed"):
                type_missed[itype] = type_missed.get(itype, 0) + 1

    # Flag types stated >= 2 times with >50% miss rate
    gap_types = []
    for itype, count in type_stated.items():
        if count < 2:
            continue
        miss_count = type_missed.get(itype, 0)
        miss_rate  = miss_count / count
        if miss_rate >= 0.50:
            gap_types.append({
                "type":      itype,
                "stated":    count,
                "missed":    miss_count,
                "miss_rate": round(miss_rate, 2),
            })
    gap_types.sort(key=lambda x: -x["miss_rate"])

    recent  = day_rates[-7:] if len(day_rates) >= 7 else day_rates
    overall = round(sum(recent) / len(recent), 2) if recent else None

    return {
        "gap_types_ranked":       gap_types[:4],
        "follow_through_rate_7d": overall,
    }


def analyze_intention_execution_gap(yesterday_str, profile):
    """IC-8 orchestrator: compare yesterday's stated intentions against actual execution.

    Fetches journal + metrics, calls Haiku, stores to platform_memory,
    returns a prompt block string for inclusion in ai_context_block.
    Non-fatal throughout -- returns "" on any failure.
    """
    try:
        api_key = _get_api_key()
    except Exception as e:
        logger.warning(f"IC-8: Could not load API key: {e}")
        return ""

    # Intentions to check for yesterday:
    #   (a) Yesterday's morning check-in: todays_intention
    #   (b) Day-before's evening reflection: tomorrow_focus (refers to yesterday)
    yesterday_entries  = _fetch_journal_for_date(yesterday_str)
    day_before_str     = (
        datetime.strptime(yesterday_str, "%Y-%m-%d") - timedelta(days=1)
    ).strftime("%Y-%m-%d")
    day_before_entries = _fetch_journal_for_date(day_before_str)

    yesterday_intents  = _extract_intention_texts(yesterday_entries)
    day_before_intents = _extract_intention_texts(day_before_entries)

    combined = {
        "today":    yesterday_intents.get("today"),
        "tomorrow": day_before_intents.get("tomorrow"),
    }

    if not any(combined.values()):
        logger.info(f"IC-8: No intention data for {yesterday_str} -- skipping")
        return ""

    # Execution metrics for yesterday
    execution_metrics = _fetch_execution_metrics(yesterday_str, profile)

    # Haiku evaluation
    evaluations = _evaluate_intentions_haiku(combined, execution_metrics, api_key)
    if not evaluations:
        logger.info(f"IC-8: No evaluations produced for {yesterday_str}")
        return ""

    total          = len(evaluations)
    executed_count = sum(
        1 for e in evaluations if e.get("executed") and e.get("confidence") != "low"
    )
    follow_through_rate = round(executed_count / total, 2) if total else None

    # Store to platform_memory
    try:
        mem_item = {
            "pk":                  USER_PREFIX + "platform_memory",
            "sk":                  f"MEMORY#intention_tracking#{yesterday_str}",
            "category":            "intention_tracking",
            "date":                yesterday_str,
            "evaluations":         json.dumps(evaluations),
            "total_intentions":    total,
            "intentions_executed": executed_count,
            "stored_at":           datetime.now(timezone.utc).isoformat(),
            "ttl":                 int((datetime.now(timezone.utc) + timedelta(days=90)).timestamp()),
        }
        if follow_through_rate is not None:
            mem_item["follow_through_rate"] = Decimal(str(follow_through_rate))
        table.put_item(Item=mem_item)
        logger.info(f"IC-8: Stored intention tracking {yesterday_str} (rate={follow_through_rate or 0:.2f}, {executed_count}/{total})")
    except Exception as e:
        logger.warning(f"IC-8: Failed to store to platform_memory: {e}")

    # Recurring patterns from history
    history  = _load_intention_history(yesterday_str)
    patterns = _compute_intention_patterns(history)

    # Build prompt block
    lines = ["INTENT VS EXECUTION GAP (IC-8):"]

    gaps = [e for e in evaluations if not e.get("executed") and e.get("confidence") != "low"]
    hits = [e for e in evaluations if e.get("executed")]

    if hits:
        hit_types = ", ".join(e.get("type", "?").replace("_", " ") for e in hits[:3])
        lines.append(f"  \u2705 Followed through: {hit_types}")

    for gap in gaps[:3]:
        text     = (gap.get("text") or "")[:80]
        evidence = (gap.get("evidence") or "")[:100]
        itype    = (gap.get("type") or "generic").replace("_", " ")
        lines.append(f"  \u274c Intent: '{text}' ({itype}) -- {evidence}")

    if not gaps and total > 0:
        lines.append(f"  \u2705 All stated intentions executed ({executed_count}/{total})")

    gap_types = patterns.get("gap_types_ranked", [])
    if gap_types:
        lines.append("  RECURRING GAPS (last 14 days):")
        for gt in gap_types[:2]:
            times = f"{gt['missed']}/{gt['stated']} times"
            pct   = int(gt["miss_rate"] * 100)
            lines.append(
                f"    \u2192 {gt['type'].replace('_', ' ')}: missed {times} ({pct}% miss rate)"
            )

    overall = patterns.get("follow_through_rate_7d")
    if overall is not None:
        lines.append(f"  7-day follow-through rate: {int(overall * 100)}%")

    lines.append(
        "INSTRUCTION: If recurring gaps exist, name the pattern directly and probe the friction. "
        "'You've stated X four times and executed once -- what's the actual barrier?' "
        "Don't just note the gap -- connect it to why it keeps happening "
        "(schedule, energy, vagueness of intention). "
        "The knowing-doing gap is specific."
    )

    return "\n".join(lines)


# ==============================================================================
# AI CONTEXT BLOCK ASSEMBLY
# ==============================================================================

# ==============================================================================
# IC-5: EARLY WARNING DETECTION
# ==============================================================================

def detect_early_warning(computed_records_7d, habit_7d, declining):
    """IC-5: Detect early warning state from simultaneous multi-marker deterioration.

    Fires when 2+ of the following markers are active at once:
      1. journal_sparse   — journal component < 50 for 2 of last 3 days
      2. nutrition_gap    — nutrition component < 40 for 2 of last 3 days
      3. habit_declining  — T0 completion dropped >=15pp (last-3d avg vs prior-4d avg)
      4. recovery_sliding — recovery or readiness_score already in declining list

    Returns: (warning_active: bool, markers: list[str], warning_block: str)
    """
    markers = []

    sorted_recs = sorted(computed_records_7d, key=lambda x: x.get("date", ""))
    recent_3 = sorted_recs[-3:] if len(sorted_recs) >= 3 else sorted_recs

    # Marker 1: journal sparse
    journal_low = 0
    for rec in recent_3:
        comp = rec.get("component_scores", {})
        score = safe_float(comp, "journal")
        if score is not None and score < 50:
            journal_low += 1
    if journal_low >= 2:
        markers.append("journal_sparse")

    # Marker 2: nutrition gap
    nutrition_low = 0
    for rec in recent_3:
        comp = rec.get("component_scores", {})
        score = safe_float(comp, "nutrition")
        if score is not None and score < 40:
            nutrition_low += 1
    if nutrition_low >= 2:
        markers.append("nutrition_gap")

    # Marker 3: habit completion dropping
    sorted_habits = sorted(habit_7d, key=lambda x: x.get("date", ""))
    if len(sorted_habits) >= 4:
        recent_h = sorted_habits[-3:]
        prior_h  = sorted_habits[-7:-3] if len(sorted_habits) >= 7 else sorted_habits[:-3]
        def avg_completion(records):
            vals = [safe_float(r, "t0_completion_rate") for r in records]
            vals = [v for v in vals if v is not None]
            return sum(vals) / len(vals) if vals else None
        recent_comp = avg_completion(recent_h)
        prior_comp  = avg_completion(prior_h)
        if recent_comp is not None and prior_comp is not None:
            drop_pp = prior_comp - recent_comp  # positive = drop
            if drop_pp >= 0.15:  # 15 percentage point drop
                markers.append("habit_declining")

    # Marker 4: recovery / readiness sliding (reuse declining list from detect_metric_trends)
    declining_metrics = {d["metric"] for d in declining}
    if "recovery" in declining_metrics or "readiness_score" in declining_metrics:
        markers.append("recovery_sliding")

    warning_active = len(markers) >= 2

    warning_block = ""
    if warning_active:
        marker_labels = {
            "journal_sparse":   "journal tracking dropped off (2+ of last 3 days)",
            "nutrition_gap":    "nutrition score critically low (2+ of last 3 days)",
            "habit_declining":  "T0 habit completion dropped 15%+ this week",
            "recovery_sliding": "recovery/readiness declining 3 consecutive days",
        }
        active_desc = [marker_labels[m] for m in markers if m in marker_labels]
        warning_block = (
            "\u26a0\ufe0f EARLY WARNING: Multiple deterioration markers active simultaneously:\n"
            + "\n".join(f"  \u2022 {d}" for d in active_desc)
            + "\nThis pattern often precedes broader health score decline. Address proactively."
        )
        logger.warning(f"IC-5 EARLY WARNING active: markers={markers}")
    else:
        logger.info(f"IC-5: No early warning (active markers: {markers})")

    return warning_active, markers, warning_block


# ==============================================================================
# PRIORITY QUEUE CONTEXT ASSEMBLER  (IC-19 v1.3.0 — Priya/Anika/Elena)
# ==============================================================================

def _build_prioritized_context_block(signals, token_budget=700):
    """Assemble AI context block from priority-ranked signals, filling to token budget.

    Args:
        signals: list of dicts with keys:
            priority      (int, lower = higher urgency; 1 always included)
            content       (str, the line or block to append)
            token_estimate (int, approximate tokens for budget tracking)
        token_budget: maximum tokens to spend on signal content.
            NOTE: 700 is an initial estimate — revisit once coaching quality
            feedback is available to calibrate against actual Daily Brief quality.

    Pure function — no AWS/DynamoDB dependencies. (Elena)
    """
    header = "PLATFORM INTELLIGENCE (7-day context, pre-computed):"
    footer = ("INSTRUCTION: Reference this intelligence in coaching. Name the specific patterns, "
              "causal chains, and leading indicators above \u2014 don't just list them, connect them.")

    lines = [header]
    used  = len(header.split())  # rough word count as token proxy

    for sig in sorted(signals, key=lambda s: s["priority"]):
        est = sig.get("token_estimate", 20)
        if sig["priority"] > 1 and used + est > token_budget:
            break  # priority-1 signals always included regardless of budget
        lines.append(sig["content"])
        used += est

    lines.append("")
    lines.append(footer)
    return "\n".join(lines)


# ==============================================================================
# SLOW DRIFT DETECTION  (IC-19 Deliverable 1 — Henning/Attia/Webb/Okafor/Huberman)
# ==============================================================================

def _linreg_slope(y_vals):
    """Compute linear regression slope for equally-spaced observations.
    Returns slope per step (e.g. lbs/day), or None if fewer than 2 points."""
    n = len(y_vals)
    if n < 2:
        return None
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(y_vals) / n
    num = sum((xs[i] - x_mean) * (y_vals[i] - y_mean) for i in range(n))
    den = sum((xs[i] - x_mean) ** 2 for i in range(n))
    return num / den if den != 0 else 0.0


def _check_circadian_consistency(yesterday_str, window_days=21):
    """Return SD of bedtime (sleep start hour) over the window, or None.

    Huberman: if HRV/recovery drift fires AND bedtime consistency has degraded,
    surface it as a potential upstream cause.
    """
    try:
        today = datetime.now(timezone.utc).date()
        start = (today - timedelta(days=window_days + 1)).isoformat()
        recs  = fetch_range("eightsleep", start, yesterday_str)
        bedtimes = []
        for r in recs:
            bt = r.get("bedtime_start") or r.get("sleep_start")
            if not bt:
                continue
            try:
                dt = datetime.fromisoformat(str(bt).replace("Z", "+00:00"))
                # Convert to decimal hours (e.g. 23.5 = 11:30 PM)
                bedtimes.append(dt.hour + dt.minute / 60.0)
            except Exception:
                pass
        if len(bedtimes) < 7:
            return None
        return round(statistics.stdev(bedtimes), 2)
    except Exception:
        return None


def _compute_slow_drift(yesterday_str, profile):
    """Detect gradual metric drift using non-overlapping baseline windows.

    Windows (TB7-22, 2026-03-13 — equalized per Henning recommendation):
      Recent window:   days 1-14 before yesterday  (14 days)
      Baseline window: days 15-28 before yesterday (14 days, zero overlap)

    Rationale: original 7d recent / 21d baseline was asymmetric. The shorter recent
    window was more volatile and the asymmetric comparison inflated apparent drift
    severity. Equal 14d/14d windows are more statistically comparable (same N, same
    SE of mean). Min N=14 gate now applies identically to both windows.

    Severity tiers:
      mild:        0.5-1.0 SD drift  — stored but NOT injected into context block
      significant: 1.0-1.5 SD        — injected into context block at priority 4
      severe:      >1.5 SD           — injected at priority 2 (displaces lower signals)

    Minimum data (Henning): N>=14 non-null points in baseline window, else insufficient_data.

    Weight plateau uses separate regression logic (Attia):
      - Requires >=8 weight measurements in 14-day window
      - Requires >=11 complete nutrition log days (Henning)
      - Uses regression slope, not endpoint comparison
      - MacroFactor TDEE preferred over Apple Watch (Webb/Norton)
      - Includes recomposition caveat in output (Okafor)

    Returns list of drift dicts with keys:
      metric, source, recent_mean, baseline_mean, drift_sd, severity,
      baseline_n, note (optional context string)
    """
    today       = datetime.now(timezone.utc).date()
    yest        = datetime.strptime(yesterday_str, "%Y-%m-%d").date()

    # Recent window: days 1-14 before yesterday (inclusive) — TB7-22
    recent_end   = (yest - timedelta(days=1)).isoformat()
    recent_start = (yest - timedelta(days=14)).isoformat()

    # Baseline window: days 15-28 before yesterday (non-overlapping) — TB7-22
    baseline_end   = (yest - timedelta(days=15)).isoformat()
    baseline_start = (yest - timedelta(days=28)).isoformat()

    drift_results = []

    # ── Biometric drift metrics (HRV, RHR, sleep efficiency, recovery score) ──
    DRIFT_METRICS = [
        ("whoop",  "hrv",                         "HRV",              True),
        ("whoop",  "resting_heart_rate",           "Resting HR",       False),
        ("whoop",  "sleep_efficiency_percentage",  "Sleep Efficiency", True),
        ("whoop",  "recovery_score",              "Recovery Score",   True),
    ]

    circadian_sd = None  # computed once if HRV or recovery drift detected

    for source, field, label, higher_is_better in DRIFT_METRICS:
        recent_recs   = fetch_range(source, recent_start, recent_end)
        baseline_recs = fetch_range(source, baseline_start, baseline_end)

        recent_vals   = [safe_float(r, field) for r in recent_recs
                         if safe_float(r, field) is not None]
        baseline_vals = [safe_float(r, field) for r in baseline_recs
                         if safe_float(r, field) is not None]

        # Henning: minimum N=14 in baseline window
        if len(baseline_vals) < 14:
            drift_results.append({
                "metric":    label,
                "source":    source,
                "severity":  "insufficient_data",
                "baseline_n": len(baseline_vals),
            })
            continue

        if len(recent_vals) == 0:
            continue

        baseline_mean = sum(baseline_vals) / len(baseline_vals)
        baseline_sd   = statistics.stdev(baseline_vals) if len(baseline_vals) > 1 else 0
        recent_mean   = sum(recent_vals) / len(recent_vals)

        if baseline_sd == 0:
            continue

        # Drift = recent_mean - baseline_mean, expressed in baseline SDs
        # Henning: recent and baseline windows are non-overlapping
        drift_sd_val = (recent_mean - baseline_mean) / baseline_sd

        # Determine severity direction (worse or better?)
        if higher_is_better:
            is_worsening = drift_sd_val < 0
            abs_drift    = abs(drift_sd_val)
        else:
            is_worsening = drift_sd_val > 0
            abs_drift    = abs(drift_sd_val)

        if abs_drift < 0.5:
            continue  # noise, skip entirely
        elif abs_drift < 1.0:
            severity = "mild"
        elif abs_drift < 1.5:
            severity = "significant"
        else:
            severity = "severe"

        note = None
        # Huberman: circadian consistency note for HRV/recovery drift
        if field in ("hrv", "recovery_score") and severity in ("significant", "severe") and is_worsening:
            if circadian_sd is None:
                circadian_sd = _check_circadian_consistency(yesterday_str)
            if circadian_sd is not None and circadian_sd > 1.0:
                note = (f"Note: bedtime consistency has also varied (SD {circadian_sd}h over the "
                        f"window). Circadian timing may be an upstream contributor to this drift.")

        drift_results.append({
            "metric":        label,
            "field":         field,
            "source":        source,
            "recent_mean":   round(recent_mean, 2),
            "baseline_mean": round(baseline_mean, 2),
            "drift_sd":      round(drift_sd_val, 2),
            "severity":      severity,
            "worsening":     is_worsening,
            "baseline_n":    len(baseline_vals),   # Omar: include for downstream confidence
            "note":          note,
        })

    # ── Weight plateau detection (Attia/Henning/Webb/Okafor) ──
    try:
        wt_recs = fetch_range("withings",
                              (yest - timedelta(days=14)).isoformat(),
                              yesterday_str)
        wt_vals = [(r.get("date") or r.get("sk", "").replace("DATE#", ""),
                    safe_float(r, "weight_lbs"))
                   for r in wt_recs if safe_float(r, "weight_lbs") is not None]
        wt_vals.sort(key=lambda x: x[0])  # chronological

        if len(wt_vals) >= 8:  # Attia: need >=8 measurements for regression
            # Check complete nutrition log days (Henning: >=11 of last 14 days)
            cal_target  = profile.get("calorie_target", 1800)
            mf_recs     = fetch_range("macrofactor",
                                      (yest - timedelta(days=14)).isoformat(),
                                      yesterday_str)
            complete_days = sum(
                1 for r in mf_recs
                if safe_float(r, "total_calories_kcal", 0) >= cal_target * 0.65
            )

            if complete_days >= 11:
                weights_only = [v for _, v in wt_vals]
                slope_per_day = _linreg_slope(weights_only)   # lbs/day
                slope_per_week = slope_per_day * 7 if slope_per_day is not None else None

                # Attia: plateau = slope > -0.2 lbs/week (insufficient loss)
                if slope_per_week is not None and slope_per_week > -0.2:
                    # MacroFactor TDEE preferred; fallback to Apple Watch (Webb/Norton)
                    mf_tdee = None
                    aw_tdee = None
                    for r in mf_recs:
                        v = safe_float(r, "tdee_kcal") or safe_float(r, "maintenance_calories")
                        if v:
                            mf_tdee = v; break
                    aw_recs = fetch_range("apple_health",
                                         (yest - timedelta(days=14)).isoformat(),
                                         yesterday_str)
                    aw_cals = [safe_float(r, "active_energy_burned") for r in aw_recs
                               if safe_float(r, "active_energy_burned") is not None]
                    if aw_cals:
                        aw_tdee = sum(aw_cals) / len(aw_cals)

                    tdee_used = mf_tdee or aw_tdee
                    tdee_source = "MacroFactor" if mf_tdee else ("Apple Watch" if aw_tdee else "unknown")

                    # Okafor: always include recomposition caveat
                    recomp_note = (
                        "Note: a flat scale weight doesn't necessarily mean a stall — "
                        "recomposition (muscle gain while losing fat) can produce a flat "
                        "trend even during a genuine deficit. Interpret alongside body "
                        "composition data, not scale weight alone."
                    )

                    drift_results.append({
                        "metric":          "Weight Plateau",
                        "source":          "withings",
                        "slope_lbs_week":  round(slope_per_week, 2),
                        "measurements_n":  len(wt_vals),
                        "complete_log_days": complete_days,
                        "tdee_source":     tdee_source,
                        "severity":        "significant",
                        "worsening":       True,
                        "baseline_n":      len(wt_vals),
                        "note":            recomp_note,
                    })
    except Exception as e:
        logger.warning(f"Slow drift weight plateau check failed (non-fatal): {e}")

    return [r for r in drift_results if r.get("severity") not in ("insufficient_data", None)
            and r.get("severity") != "mild"]


# ==============================================================================
# EXPERIMENT CONTEXT INJECTION  (IC-19 Deliverable 3A — Anika/Raj/Patrick/Conti)
# ==============================================================================

def _build_experiment_context(yesterday_str, profile):
    """Build a purely descriptive active-experiment block for the AI context.

    Rules (Board v2 spec):
    - Early return if no active experiments (Raj/Viktor: no DDB latency on empty days)
    - Purely descriptive: raw numbers only, no trajectory verdict (Anika)
    - For supplement-type experiments: include dose adherence from supplement log (Patrick)
    - Negative psychological variable hypotheses framed as opportunities, not baselines (Conti)
    - Active experiment context is priority 7 in the queue (below sustained anomaly,
      above declining metrics) since it is informational, not urgent
    """
    try:
        exp_pk = USER_PREFIX + "experiments"
        resp   = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            FilterExpression="#st = :active",
            ExpressionAttributeNames={"#st": "status"},
            ExpressionAttributeValues={
                ":pk":     exp_pk,
                ":prefix": "EXP#",
                ":active": "active",
            },
        )
        active_exps = [d2f(i) for i in resp.get("Items", [])]
    except Exception as e:
        logger.warning(f"_build_experiment_context: query failed (non-fatal): {e}")
        return ""

    # Raj/Viktor: early return — zero DDB fetch cost on non-experiment days
    if not active_exps:
        return ""

    today_dt   = datetime.now(timezone.utc).date()
    yest_dt    = datetime.strptime(yesterday_str, "%Y-%m-%d").date()
    lines      = ["ACTIVE EXPERIMENTS (descriptive only — evaluate with get_experiment_results):"]

    # Negative psychological variable keywords (Conti: use intervention framing)
    _NEG_PSYCH_KEYWORDS = {
        "stress", "anxiety", "mood", "loneliness", "isolation",
        "depression", "grief", "fatigue", "avoidance", "rumination"
    }

    for exp in active_exps:
        name        = exp.get("name", exp.get("experiment_id", "Unknown"))
        start_str   = exp.get("start_date", "")
        hypothesis  = exp.get("hypothesis", "")
        category    = (exp.get("category") or "").lower()
        metrics     = exp.get("primary_metrics") or []

        # Compute day count
        try:
            start_dt = datetime.strptime(start_str, "%Y-%m-%d").date()
            days_in  = (yest_dt - start_dt).days + 1
        except Exception:
            days_in  = "?"

        lines.append(f"  {name} (Day {days_in}, started {start_str}):")

        # Per-metric descriptive snapshot: baseline vs recent — NO verdict
        for metric_def in metrics[:4]:  # cap at 4 metrics per experiment
            source = metric_def.get("source", "")
            field  = metric_def.get("field", "")
            label  = metric_def.get("label", field)
            if not source or not field:
                continue
            try:
                # Baseline: same window before experiment started
                if isinstance(days_in, int) and days_in >= 1:
                    bl_start = (start_dt - timedelta(days=days_in)).isoformat()
                    bl_end   = (start_dt - timedelta(days=1)).isoformat()
                    bl_recs  = fetch_range(source, bl_start, bl_end)
                    bl_vals  = [safe_float(r, field) for r in bl_recs
                                if safe_float(r, field) is not None]
                    # Recent 7d during experiment
                    dur_start = max(start_str,
                                    (yest_dt - timedelta(days=6)).isoformat())
                    dur_recs  = fetch_range(source, dur_start, yesterday_str)
                    dur_vals  = [safe_float(r, field) for r in dur_recs
                                 if safe_float(r, field) is not None]
                    if bl_vals and dur_vals:
                        bl_mean   = round(sum(bl_vals) / len(bl_vals), 1)
                        dur_mean  = round(sum(dur_vals) / len(dur_vals), 1)
                        delta     = round(dur_mean - bl_mean, 1)
                        delta_str = f"+{delta}" if delta > 0 else str(delta)
                        lines.append(f"    {label}: baseline {bl_mean} | 7d avg {dur_mean} | delta {delta_str}")
            except Exception:
                pass

        # Patrick: supplement adherence for supplement-type experiments
        if "supplement" in category or "supplement" in name.lower():
            try:
                supp_name = exp.get("supplement_name") or name
                supp_pk   = USER_PREFIX + "supplements"
                if isinstance(days_in, int):
                    supp_recs = fetch_range("supplements",
                                            start_str, yesterday_str)
                    doses_taken = sum(
                        1 for r in supp_recs
                        if supp_name.lower() in (r.get("supplement_name") or "").lower()
                    )
                    lines.append(f"    Adherence: {doses_taken}/{days_in} doses logged")
            except Exception:
                pass

        # Conti: intervention framing for negative psychological variable hypotheses
        if hypothesis:
            hyp_lower = hypothesis.lower()
            is_neg_psych = any(kw in hyp_lower for kw in _NEG_PSYCH_KEYWORDS)
            if is_neg_psych:
                lines.append(f"    Context: This experiment tests a potential intervention "
                              f"opportunity — data is early; treat as exploratory, not diagnostic.")

    return "\n".join(lines) if len(lines) > 1 else ""


# ==============================================================================
# BS-MP3: DECISION FATIGUE DETECTOR (proactive)
# ==============================================================================

def _compute_decision_fatigue_alert(yesterday_str, habit_7d):
    """BS-MP3: Proactive decision fatigue alert.

    Fires when BOTH conditions are true simultaneously:
      1. Active + overdue Todoist tasks > DECISION_FATIGUE_THRESHOLD (default 15)
      2. T0 habit completion < DECISION_FATIGUE_HABIT_THRESHOLD (default 60%) this week

    Reads the most recent Todoist DDB record for task load.
    Returns a (fired: bool, alert_block: str) tuple. Non-fatal.
    """
    try:
        # ── 1. Todoist task load from DDB ──────────────────────────────────────
        pk = USER_PREFIX + "todoist"
        resp = table.query(
            KeyConditionExpression="pk = :pk",
            ExpressionAttributeValues={":pk": pk},
            ScanIndexForward=False,
            Limit=3,
        )
        todoist_items = [d2f(i) for i in resp.get("Items", [])]

        active_count  = None
        overdue_count = None
        for item in todoist_items:
            # Try various field names written by different ingestion versions
            ac = item.get("active_task_count") or item.get("active_count") or item.get("total_active")
            oc = item.get("overdue_count") or item.get("overdue_task_count") or item.get("overdue")
            if ac is not None:
                active_count  = int(ac)
                overdue_count = int(oc or 0)
                break

        if active_count is None:
            logger.info("BS-MP3: No Todoist task count found in DDB — skipping decision fatigue check")
            return False, ""

        total_load = active_count + overdue_count

        # ── 2. T0 habit completion rate this week ─────────────────────────────
        if not habit_7d:
            return False, ""

        t0_rates = [
            safe_float(r, "tier0_pct") or safe_float(r, "t0_completion_rate")
            for r in habit_7d
        ]
        t0_rates = [v for v in t0_rates if v is not None]
        t0_avg_7d = sum(t0_rates) / len(t0_rates) if t0_rates else None

        if t0_avg_7d is None:
            return False, ""

        # ── 3. Evaluate thresholds ────────────────────────────────────────────
        load_breached  = total_load > DECISION_FATIGUE_THRESHOLD
        habits_breached = t0_avg_7d < DECISION_FATIGUE_HABIT_THRESHOLD
        fired = load_breached and habits_breached

        logger.info(
            "BS-MP3: total_load=%d (threshold=%d), t0_avg_7d=%.2f (threshold=%.2f) → fired=%s",
            total_load, DECISION_FATIGUE_THRESHOLD, t0_avg_7d, DECISION_FATIGUE_HABIT_THRESHOLD, fired,
        )

        if not fired:
            return False, ""

        # ── 4. Build alert block ──────────────────────────────────────────────
        t0_pct_str    = f"{int(t0_avg_7d * 100)}%"
        overdue_note  = f" ({overdue_count} overdue)" if overdue_count > 0 else ""
        alert = (
            f"\U0001f9e0 DECISION FATIGUE DETECTED (BS-MP3):\n"
            f"  Task load: {total_load} active+overdue tasks{overdue_note} "
            f"(threshold: >{DECISION_FATIGUE_THRESHOLD})\n"
            f"  T0 habit completion: {t0_pct_str} this week "
            f"(threshold: <{int(DECISION_FATIGUE_HABIT_THRESHOLD * 100)}%)\n"
            f"INSTRUCTION: Decision load is elevated and it is correlating with habit slippage. "
            f"Name this pattern directly. Suggest 1-2 specific tasks Matthew could cancel, delegate, "
            f"or defer today to protect evening habit completion. Be specific, not vague."
        )
        return True, alert

    except Exception as e:
        logger.warning("BS-MP3 decision fatigue check failed (non-fatal): %s", e)
        return False, ""


# ==============================================================================
# AI CONTEXT BLOCK ASSEMBLER  (priority queue version — IC-19 v1.3.0)
# ==============================================================================

def build_ai_context_block(momentum_signal, this_week_avg, prev_week_avg, trend_pct,
                            declining, improving, miss_rates, strongest, weakest,
                            synergy_health, memory_ctx, intention_gap_ctx="",
                            early_warning_block="",
                            slow_drift_metrics=None,
                            experiment_ctx="",
                            social_flag="",
                            decision_fatigue_block=""):
    """Assemble the compact text block injected into all Daily Brief AI prompts.

    Delegates to _build_prioritized_context_block() with priority-ranked signals.
    Priority 1 signals always included; lower priorities filled to 700-token budget.
    """
    # Build signals list (Priya priority queue)
    # Priority 1 = always included regardless of budget
    # Higher number = lower priority, first to be dropped if budget exceeded
    signals = []

    # P1: IC-5 Early Warning (always surfaces)
    if early_warning_block:
        signals.append({"priority": 1, "content": early_warning_block, "token_estimate": 60})

    # P2: Severe slow drift (displaces lower signals — Attia/Henning)
    if slow_drift_metrics:
        severe = [d for d in slow_drift_metrics if d.get("severity") == "severe" and d.get("worsening")]
        for d in severe:
            line = (f"\U0001F6A8 SLOW DRIFT — SEVERE: {d['metric']} has drifted "
                    f"{abs(d.get('drift_sd', 0)):.1f} SD below baseline over 3 weeks "
                    f"(recent avg: {d.get('recent_mean')} vs baseline: {d.get('baseline_mean')}, "
                    f"N={d.get('baseline_n')} days).")
            if d.get("note"):
                line += f" {d['note']}"
            signals.append({"priority": 2, "content": line, "token_estimate": 40})

    # P3: Decision Fatigue (BS-MP3) — fires when task load AND habit completion both breach thresholds
    if decision_fatigue_block:
        signals.append({"priority": 3, "content": decision_fatigue_block, "token_estimate": 50})

    # P3b: Sustained anomaly context (informational only — full alert sent separately)
    # (No content here — the anomaly detector sends its own email; we just note it)

    # P4: Significant slow drift
    if slow_drift_metrics:
        significant = [d for d in slow_drift_metrics if d.get("severity") == "significant" and d.get("worsening")]
        for d in significant:
            line = (f"\u26a0\ufe0f SLOW DRIFT: {d['metric']} trending down "
                    f"({abs(d.get('drift_sd', 0)):.1f} SD below 3-week baseline; "
                    f"recent avg {d.get('recent_mean')} vs {d.get('baseline_mean')}, "
                    f"N={d.get('baseline_n')}).")
            if d.get("note"):
                line += f" {d['note']}"
            signals.append({"priority": 4, "content": line, "token_estimate": 35})
        # Weight plateau
        wt = next((d for d in slow_drift_metrics if d.get("metric") == "Weight Plateau"), None)
        if wt:
            line = (f"\U0001F6A8 WEIGHT PLATEAU: scale trend is flat "
                    f"({wt.get('slope_lbs_week', 0):+.2f} lbs/wk over "
                    f"{wt.get('measurements_n')} weigh-ins, {wt.get('complete_log_days')} complete log days, "
                    f"TDEE from {wt.get('tdee_source', 'unknown')}). {wt.get('note', '')}")
            signals.append({"priority": 4, "content": line, "token_estimate": 45})

    # P5: IC-8 Intent vs Execution Gap
    if intention_gap_ctx:
        signals.append({"priority": 5, "content": intention_gap_ctx, "token_estimate": 50})

    # P6: Declining metrics (3-day consecutive)
    for d in declining[:2]:
        m = d["metric"].replace("_", " ")
        line = (f"\u26a0\ufe0f LEADING INDICATOR: {m} declining {d['consecutive_days']} days "
                f"(now {d['current']} vs {d['baseline_7d_avg']} avg, {d['delta_pct']}%)")
        signals.append({"priority": 6, "content": line, "token_estimate": 25})

    # P7: Momentum signal
    if this_week_avg is not None:
        if momentum_signal == "improving" and trend_pct is not None:
            mom = f"\U0001f4c8 Momentum: IMPROVING ({prev_week_avg}\u2192{this_week_avg} avg grade, +{trend_pct}% WoW)"
        elif momentum_signal == "declining" and trend_pct is not None:
            mom = f"\U0001f4c9 Momentum: DECLINING ({prev_week_avg}\u2192{this_week_avg} avg grade, {trend_pct}% WoW)"
        else:
            mom = f"\u27a1\ufe0f Momentum: STABLE (avg grade: {this_week_avg})"
        signals.append({"priority": 7, "content": mom, "token_estimate": 20})

    # P7: Active experiments (descriptive)
    if experiment_ctx:
        signals.append({"priority": 7, "content": experiment_ctx, "token_estimate": 60})

    # P8: Improving metrics
    for imp in improving[:2]:
        m = imp["metric"].replace("_", " ")
        line = (f"\u2705 POSITIVE SIGNAL: {m} improving {imp['consecutive_days']} days "
                f"(now {imp['current']} vs {imp['baseline_7d_avg']} avg, +{imp['delta_pct']}%)")
        signals.append({"priority": 8, "content": line, "token_estimate": 25})

    # P9: Habit patterns
    if weakest:
        habit_detail = []
        for h in weakest[:3]:
            miss_rate   = miss_rates.get(h)
            days_missed = round(miss_rate * 7) if miss_rate else "?"
            habit_detail.append(f"{h} (missed {days_missed}/7 days)")
        signals.append({"priority": 9,
                         "content": f"\U0001f534 Weakest T0 habits: {', '.join(habit_detail)}",
                         "token_estimate": 20})
    if strongest:
        signals.append({"priority": 9,
                         "content": f"\U0001f4aa Strongest habits: {', '.join(strongest[:3])}",
                         "token_estimate": 15})

    # P9: Synergy group issues
    broken_synergies = [g for g, h in synergy_health.items() if h < 0.5]
    if broken_synergies:
        signals.append({"priority": 9,
                         "content": f"\u26a1 Broken synergy stacks: {', '.join(broken_synergies)}",
                         "token_estimate": 15})

    # P10: Platform memory (coaching calibration)
    if memory_ctx:
        signals.append({"priority": 10, "content": memory_ctx, "token_estimate": 40})

    # P11: Murthy — social quality flag when multiple drift signals + sparse journal
    if social_flag:
        signals.append({"priority": 11, "content": social_flag, "token_estimate": 25})

    return _build_prioritized_context_block(signals)


# ==============================================================================
# STORE
# ==============================================================================

def _to_dec(val):
    if val is None: return None
    return Decimal(str(round(float(val), 4)))


def store_computed_insights(yesterday_str, payload):
    """Write computed_insights record to DynamoDB."""
    item = {
        "pk":          USER_PREFIX + "computed_insights",
        "sk":          "DATE#" + yesterday_str,
        "date":        yesterday_str,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }

    for key in ("momentum_signal", "ai_context_block", "memory_context"):
        if payload.get(key) is not None:
            item[key] = payload[key]

    for key in ("week_grade_avg", "prev_week_grade_avg", "grade_trend_pct"):
        if payload.get(key) is not None:
            item[key] = _to_dec(payload[key])

    for key in ("declining_metrics", "improving_metrics"):
        if payload.get(key):
            item[key] = json.dumps(payload[key])

    if payload.get("miss_rates"):
        item["habit_miss_rates_7d"] = json.dumps(payload["miss_rates"])
    if payload.get("strongest"):
        item["strongest_habits"] = payload["strongest"]
    if payload.get("weakest"):
        item["weakest_habits"] = payload["weakest"]
    if payload.get("synergy_health"):
        item["synergy_health"] = json.dumps(payload["synergy_health"])
    if payload.get("slow_drift_metrics"):
        item["slow_drift_metrics"] = json.dumps(payload["slow_drift_metrics"])

    item = {k: v for k, v in item.items() if v is not None}
    # DATA-2: validate_item for computed_insights (Item 3, R12)
    try:
        from ingestion_validator import validate_item as _vi
        _vr = _vi("computed_insights", item, yesterday_str)
        if _vr.should_skip_ddb:
            logger.error("[DATA-2] Skipping computed_insights write for %s: %s", yesterday_str, _vr.errors)
            return
        if _vr.warnings:
            logger.warning("[DATA-2] computed_insights warnings for %s: %s", yesterday_str, _vr.warnings)
    except ImportError:
        pass
    except Exception as ve:
        logger.warning("[DATA-2] computed_insights validate_item failed (proceeding): %s", ve)
    table.put_item(Item=item)
    logger.info(f"Stored computed_insights for {yesterday_str} (momentum={payload.get('momentum_signal')}, declining={len(payload.get('declining_metrics', []))}, improving={len(payload.get('improving_metrics', []))})")


# ==============================================================================
# HANDLER
# ==============================================================================

def lambda_handler(event, context):
    logger.info("Daily Insight Compute v1.2.0 starting...")

    today         = datetime.now(timezone.utc).date()
    yesterday_str = event.get("date") or (today - timedelta(days=1)).isoformat()

    # Idempotency check (skip unless force=True)
    if not event.get("force"):
        existing = fetch_date("computed_insights", yesterday_str)
        if existing:
            logger.info(f"Already computed insights for {yesterday_str} — skipping (use force=true to override)")
            return {"statusCode": 200, "body": f"Already computed for {yesterday_str}", "skipped": True}

    profile = fetch_profile()

    # ── 1. Load pre-computed records ──
    computed_7d = fetch_range("computed_metrics",
                              (today - timedelta(days=7)).isoformat(),
                              yesterday_str)
    habit_7d    = fetch_range("habit_scores",
                              (today - timedelta(days=7)).isoformat(),
                              yesterday_str)
    grade_14d   = fetch_range("day_grade",
                              (today - timedelta(days=14)).isoformat(),
                              yesterday_str)

    logger.info(f"Loaded: {len(computed_7d)} computed_metrics, {len(habit_7d)} habit_scores, {len(grade_14d)} day_grade records")

    # ── 2. Momentum ──
    momentum_signal, this_week_avg, prev_week_avg, trend_pct = compute_momentum(
        grade_14d, yesterday_str)
    logger.info(f"Momentum: {momentum_signal} (this_week={this_week_avg or 0:.1f}, prev_week={prev_week_avg}, trend={trend_pct}%)")

    # ── 3. Metric trends ──
    declining, improving = detect_metric_trends(computed_7d)
    logger.info(f"Declining metrics: {[d['metric'] for d in declining]} | Improving: {[i['metric'] for i in improving]}")

    # ── 4. Habit patterns ──
    miss_rates, strongest, weakest, synergy_health = compute_habit_patterns(
        habit_7d, profile)
    logger.info(f"Weakest T0 habits: {weakest[:3]} | Strongest: {strongest[:3]}")

    # ── 5. Platform memory context ──
    memory_ctx = build_memory_context()

    # ── 5b. IC-8: Intent vs Execution Gap ──
    intention_gap_ctx = ""
    try:
        intention_gap_ctx = analyze_intention_execution_gap(yesterday_str, profile)
        logger.info(f"IC-8: Intention gap context: {len(intention_gap_ctx)} chars")
    except Exception as e:
        logger.warning(f"IC-8 failed (non-fatal): {e}")

    # ── 5c. IC-5: Early Warning Detection ──
    ic5_warning, ic5_markers, early_warning_block = False, [], ""
    try:
        ic5_warning, ic5_markers, early_warning_block = detect_early_warning(
            computed_7d, habit_7d, declining)
    except Exception as e:
        logger.warning(f"IC-5 failed (non-fatal): {e}")

    # ── 5d. IC-19: Slow Drift Detection (non-fatal) ──
    slow_drift_metrics = []
    try:
        slow_drift_metrics = _compute_slow_drift(yesterday_str, profile)
        logger.info(f"IC-19 slow drift: {len(slow_drift_metrics)} signals detected")
    except Exception as e:
        logger.warning(f"IC-19 slow drift failed (non-fatal): {e}")

    # ── 5e. IC-19: Active Experiment Context (non-fatal) ──
    experiment_ctx = ""
    try:
        experiment_ctx = _build_experiment_context(yesterday_str, profile)
        if experiment_ctx:
            logger.info(f"IC-19 experiment context: {len(experiment_ctx)} chars")
    except Exception as e:
        logger.warning(f"IC-19 experiment context failed (non-fatal): {e}")

    # ── 5f. Murthy: social quality flag when multiple drift signals + sparse journal ──
    social_flag = ""
    try:
        if len(slow_drift_metrics) >= 2 and ic5_markers and "journal_sparse" in ic5_markers:
            social_flag = (
                "\U0001f91d SOCIAL NOTE: Multiple drift signals are active alongside sparse "
                "journalling this week. Research (Murthy) associates withdrawal from "
                "self-reflection with reduced social connection. Consider reaching out "
                "to someone in your network today."
            )
    except Exception:
        pass

    # ── 5g. BS-MP3: Decision Fatigue Detector (proactive) ───────────────────────────
    df_fired, decision_fatigue_block = False, ""
    try:
        df_fired, decision_fatigue_block = _compute_decision_fatigue_alert(yesterday_str, habit_7d)
        if df_fired:
            logger.info("BS-MP3: Decision fatigue alert fired for %s", yesterday_str)
    except Exception as e:
        logger.warning("BS-MP3 failed (non-fatal): %s", e)

    # ── 6. Assemble AI context block ──
    ai_block = build_ai_context_block(
        momentum_signal, this_week_avg, prev_week_avg, trend_pct,
        declining, improving, miss_rates, strongest, weakest,
        synergy_health, memory_ctx, intention_gap_ctx, early_warning_block,
        slow_drift_metrics=slow_drift_metrics,
        experiment_ctx=experiment_ctx,
        social_flag=social_flag,
        decision_fatigue_block=decision_fatigue_block)
    logger.info(f"AI context block: {len(ai_block)} chars")

    # ── 7. Store ──
    payload = {
        "momentum_signal":     momentum_signal,
        "week_grade_avg":      this_week_avg,
        "prev_week_grade_avg": prev_week_avg,
        "grade_trend_pct":     trend_pct,
        "declining_metrics":   declining,
        "improving_metrics":   improving,
        "miss_rates":          miss_rates,
        "strongest":           strongest,
        "weakest":             weakest,
        "synergy_health":      synergy_health,
        "memory_context":      memory_ctx,
        "ai_context_block":    ai_block,
        "slow_drift_metrics":  slow_drift_metrics,
    }
    store_computed_insights(yesterday_str, payload)

    return {
        "statusCode":      200,
        "body":            f"Insights computed for {yesterday_str}",
        "momentum":        momentum_signal,
        "declining_count": len(declining),
        "improving_count": len(improving),
        "weakest_habits":  weakest[:3],
        "ic8_active":            bool(intention_gap_ctx),
        "ic5_warning":           ic5_warning,
        "ic5_markers":           ic5_markers,
        "decision_fatigue_fired": df_fired,
    }
