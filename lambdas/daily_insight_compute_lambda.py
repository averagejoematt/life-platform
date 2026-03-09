"""
Daily Insight Compute Lambda — IC-2 v1.0.0
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

v1.1.0 — 2026-03-08 (IC-8: Intent vs Execution Gap)
"""

import json
import os
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import urllib.request
import urllib.error

import boto3

logger = logging.getLogger()
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
        logger.warning("fetch_date(%s, %s): %s", source, date_str, e)
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
        logger.warning("fetch_range(%s): %s", source, e)
        return []


def fetch_profile():
    try:
        r = table.get_item(Key={"pk": PROFILE_PK, "sk": "PROFILE#v1"})
        return d2f(r.get("Item", {}))
    except Exception as e:
        logger.error("fetch_profile: %s", e)
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
        logger.warning("fetch_memory(%s): %s", category, e)
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
    secret_name = os.environ.get("ANTHROPIC_SECRET", "life-platform/api-keys")
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
        logger.warning("_fetch_journal_for_date(%s): %s", date_str, e)
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
        logger.warning("IC-8 Haiku evaluation failed: %s", e)
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
        logger.warning("_load_intention_history: %s", e)
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
        logger.warning("IC-8: Could not load API key: %s", e)
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
        logger.info("IC-8: No intention data for %s -- skipping", yesterday_str)
        return ""

    # Execution metrics for yesterday
    execution_metrics = _fetch_execution_metrics(yesterday_str, profile)

    # Haiku evaluation
    evaluations = _evaluate_intentions_haiku(combined, execution_metrics, api_key)
    if not evaluations:
        logger.info("IC-8: No evaluations produced for %s", yesterday_str)
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
        }
        if follow_through_rate is not None:
            mem_item["follow_through_rate"] = Decimal(str(follow_through_rate))
        table.put_item(Item=mem_item)
        logger.info(
            "IC-8: Stored intention tracking %s (rate=%.2f, %d/%d)",
            yesterday_str, follow_through_rate or 0, executed_count, total,
        )
    except Exception as e:
        logger.warning("IC-8: Failed to store to platform_memory: %s", e)

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

def build_ai_context_block(momentum_signal, this_week_avg, prev_week_avg, trend_pct,
                            declining, improving, miss_rates, strongest, weakest,
                            synergy_health, memory_ctx, intention_gap_ctx=""):
    """Assemble the compact text block injected into all Daily Brief AI prompts."""
    lines = ["PLATFORM INTELLIGENCE (7-day context, pre-computed):"]

    # Momentum
    if this_week_avg is not None:
        if momentum_signal == "improving" and trend_pct is not None:
            lines.append(f"\U0001f4c8 Momentum: IMPROVING ({prev_week_avg}\u2192{this_week_avg} avg grade, +{trend_pct}% week-over-week)")
        elif momentum_signal == "declining" and trend_pct is not None:
            lines.append(f"\U0001f4c9 Momentum: DECLINING ({prev_week_avg}\u2192{this_week_avg} avg grade, {trend_pct}% week-over-week)")
        else:
            lines.append(f"\u27a1\ufe0f Momentum: STABLE (avg grade: {this_week_avg})")

    # Leading indicators — declining first (more urgent)
    for d in declining[:2]:
        m = d["metric"].replace("_", " ")
        lines.append(f"\u26a0\ufe0f LEADING INDICATOR: {m} declining {d['consecutive_days']} days straight (now {d['current']} vs {d['baseline_7d_avg']} avg, {d['delta_pct']}%)")

    for imp in improving[:2]:
        m = imp["metric"].replace("_", " ")
        lines.append(f"\u2705 POSITIVE SIGNAL: {m} improving {imp['consecutive_days']} days straight (now {imp['current']} vs {imp['baseline_7d_avg']} avg, +{imp['delta_pct']}%)")

    # Habit patterns
    if weakest:
        habit_detail = []
        for h in weakest[:3]:
            miss_rate   = miss_rates.get(h)
            days_missed = round(miss_rate * 7) if miss_rate else "?"
            habit_detail.append(f"{h} (missed {days_missed}/7 days)")
        lines.append(f"\U0001f534 Weakest T0 habits: {', '.join(habit_detail)}")

    if strongest:
        lines.append(f"\U0001f4aa Strongest habits: {', '.join(strongest[:3])}")

    # Synergy group issues
    broken_synergies = [g for g, h in synergy_health.items() if h < 0.5]
    if broken_synergies:
        lines.append(f"\u26a1 Broken synergy stacks: {', '.join(broken_synergies)}")

    # Platform memory (coaching calibration, what worked)
    if memory_ctx:
        lines.append("")
        lines.append(memory_ctx)

    # IC-8: Intent vs Execution Gap
    if intention_gap_ctx:
        lines.append("")
        lines.append(intention_gap_ctx)

    lines.append("INSTRUCTION: Reference this intelligence in coaching. Name the specific patterns, "
                 "causal chains, and leading indicators above \u2014 don't just list them, connect them.")

    return "\n".join(lines)


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

    item = {k: v for k, v in item.items() if v is not None}
    table.put_item(Item=item)
    logger.info("Stored computed_insights for %s (momentum=%s, declining=%d, improving=%d)",
                yesterday_str, payload.get("momentum_signal"),
                len(payload.get("declining_metrics", [])),
                len(payload.get("improving_metrics", [])))


# ==============================================================================
# HANDLER
# ==============================================================================

def lambda_handler(event, context):
    logger.info("Daily Insight Compute v1.1.0 starting...")

    today         = datetime.now(timezone.utc).date()
    yesterday_str = event.get("date") or (today - timedelta(days=1)).isoformat()

    # Idempotency check (skip unless force=True)
    if not event.get("force"):
        existing = fetch_date("computed_insights", yesterday_str)
        if existing:
            logger.info("Already computed insights for %s — skipping (use force=true to override)", yesterday_str)
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

    logger.info("Loaded: %d computed_metrics, %d habit_scores, %d day_grade records",
                len(computed_7d), len(habit_7d), len(grade_14d))

    # ── 2. Momentum ──
    momentum_signal, this_week_avg, prev_week_avg, trend_pct = compute_momentum(
        grade_14d, yesterday_str)
    logger.info("Momentum: %s (this_week=%.1f, prev_week=%s, trend=%s%%)",
                momentum_signal, this_week_avg or 0, prev_week_avg, trend_pct)

    # ── 3. Metric trends ──
    declining, improving = detect_metric_trends(computed_7d)
    logger.info("Declining metrics: %s | Improving: %s",
                [d["metric"] for d in declining], [i["metric"] for i in improving])

    # ── 4. Habit patterns ──
    miss_rates, strongest, weakest, synergy_health = compute_habit_patterns(
        habit_7d, profile)
    logger.info("Weakest T0 habits: %s | Strongest: %s", weakest[:3], strongest[:3])

    # ── 5. Platform memory context ──
    memory_ctx = build_memory_context()

    # ── 5b. IC-8: Intent vs Execution Gap ──
    intention_gap_ctx = ""
    try:
        intention_gap_ctx = analyze_intention_execution_gap(yesterday_str, profile)
        logger.info("IC-8: Intention gap context: %d chars", len(intention_gap_ctx))
    except Exception as e:
        logger.warning("IC-8 failed (non-fatal): %s", e)

    # ── 6. Assemble AI context block ──
    ai_block = build_ai_context_block(
        momentum_signal, this_week_avg, prev_week_avg, trend_pct,
        declining, improving, miss_rates, strongest, weakest,
        synergy_health, memory_ctx, intention_gap_ctx)
    logger.info("AI context block: %d chars", len(ai_block))

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
    }
    store_computed_insights(yesterday_str, payload)

    return {
        "statusCode":      200,
        "body":            f"Insights computed for {yesterday_str}",
        "momentum":        momentum_signal,
        "declining_count": len(declining),
        "improving_count": len(improving),
        "weakest_habits":  weakest[:3],
        "ic8_active":      bool(intention_gap_ctx),
    }
