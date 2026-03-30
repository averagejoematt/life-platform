"""
ai_calls.py — Anthropic API call functions for the Daily Brief.

Extracted from daily_brief_lambda.py (Phase 2 monolith extraction).
Handles all four AI calls plus data-summary builders consumed by those calls.

Exports:
  init(s3_client, bucket, has_board_loader)  — must call before using module
  call_anthropic(prompt, api_key, max_tokens, system) — raw Anthropic API call with exponential backoff + token metrics
  call_training_nutrition_coach(data, profile, api_key)
  call_journal_coach(data, profile, api_key)
  call_board_of_directors(data, profile, day_grade, grade, component_scores, api_key, ...)
  call_tldr_and_guidance(data, profile, day_grade, grade, ...)
  build_data_summary(data, profile)           — shared data dict for AI prompts
  build_food_summary(data)
  build_activity_summary(data)
  build_workout_summary(data)
"""

import json
import os
import time
import urllib.error
import urllib.request
from datetime import date as _date_cls

import boto3

# AI-3 middleware: lazy import of output validator (transparent fail-safe)
try:
    from ai_output_validator import validate_ai_output as _validate_ai_output, AIOutputType
    _AI_VALIDATOR_AVAILABLE = True
except ImportError:
    _validate_ai_output = None
    AIOutputType = None
    _AI_VALIDATOR_AVAILABLE = False

# AI model constants — read from env so model can be updated without redeployment
AI_MODEL       = os.environ.get("AI_MODEL",       "claude-sonnet-4-6")
AI_MODEL_HAIKU = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")

# CloudWatch client for token usage + failure metrics (P1.8/P1.9)
_cw = boto3.client("cloudwatch", region_name=os.environ.get("AWS_REGION", "us-west-2"))
_LAMBDA_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "unknown")
_CW_NAMESPACE = "LifePlatform/AI"

# Exponential backoff delays (seconds) between retry attempts
_BACKOFF_DELAYS = [5, 15, 45]  # attempts 1→2, 2→3, 3→4


def _emit_token_metrics(input_tokens, output_tokens):
    """Emit per-Lambda Anthropic token usage to CloudWatch (P1.9)."""
    try:
        _cw.put_metric_data(
            Namespace=_CW_NAMESPACE,
            MetricData=[
                {
                    "MetricName": "AnthropicInputTokens",
                    "Dimensions": [{"Name": "LambdaFunction", "Value": _LAMBDA_NAME}],
                    "Value": input_tokens,
                    "Unit": "Count",
                },
                {
                    "MetricName": "AnthropicOutputTokens",
                    "Dimensions": [{"Name": "LambdaFunction", "Value": _LAMBDA_NAME}],
                    "Value": output_tokens,
                    "Unit": "Count",
                },
            ],
        )
    except Exception as e:
        print(f"[WARN] CloudWatch token metric emit failed (non-fatal): {e}")


def _emit_failure_metric():
    """Emit API failure metric to CloudWatch (P1.8)."""
    try:
        _cw.put_metric_data(
            Namespace=_CW_NAMESPACE,
            MetricData=[{
                "MetricName": "AnthropicAPIFailure",
                "Dimensions": [{"Name": "LambdaFunction", "Value": _LAMBDA_NAME}],
                "Value": 1,
                "Unit": "Count",
            }],
        )
    except Exception as e:
        print(f"[WARN] CloudWatch failure metric emit failed (non-fatal): {e}")

# ==============================================================================
# MODULE STATE (set by init())
# ==============================================================================

_s3 = None
_S3_BUCKET = None
_HAS_BOARD_LOADER = False
_board_loader = None


def init(s3_client, bucket, has_board_loader, board_loader_module=None):
    """Inject shared dependencies. Call once at Lambda startup."""
    global _s3, _S3_BUCKET, _HAS_BOARD_LOADER, _board_loader
    _s3 = s3_client
    _S3_BUCKET = bucket
    _HAS_BOARD_LOADER = has_board_loader
    _board_loader = board_loader_module


# ==============================================================================
# INLINE UTILITIES
# ==============================================================================

def _safe_float(rec, field, default=None):
    if rec and field in rec:
        try: return float(rec[field])
        except Exception: return default
    return default

def _avg(vals):
    v = [x for x in vals if x is not None]
    return round(sum(v)/len(v), 1) if v else None


# ==============================================================================
# IC-2: COMPUTED INSIGHTS READER
# Reads the pre-computed platform intelligence block from daily-insight-compute Lambda.
# ==============================================================================

# TB7-20: Hard cap on insights context injected into prompts.
# The upstream _build_prioritized_context_block() already applies a 700-token budget,
# but as the corpus grows this is a safety valve for the ai_calls layer.
# 1500 chars ≈ ~375 tokens. Truncates at a signal boundary with a note.
_MAX_INSIGHTS_CONTEXT_CHARS = 1500


def _load_insights_context(data):
    """Extract the AI context block from the computed_insights record.

    Returns a compact string block for prompt injection, or empty string
    if the insights Lambda hasn't run yet (graceful degradation).

    TB7-20: Applies a 1500-char hard cap as a second safety valve beyond the
    700-token budget enforced upstream in _build_prioritized_context_block().
    Truncates at a newline boundary and appends a truncation note.
    """
    insights = data.get("computed_insights")
    if not insights:
        return ""
    block = insights.get("ai_context_block", "")
    if not block:
        return ""
    if len(block) <= _MAX_INSIGHTS_CONTEXT_CHARS:
        return block
    # Truncate at the last newline before the cap so we don't cut mid-sentence
    cutoff = block.rfind("\n", 0, _MAX_INSIGHTS_CONTEXT_CHARS)
    if cutoff < 0:
        cutoff = _MAX_INSIGHTS_CONTEXT_CHARS
    return block[:cutoff] + "\n[...context truncated at 1500-char limit]"


# ==============================================================================
# IC-6: WEIGHT MILESTONE ARCHITECTURE
# Biological waypoints with significance — injected when within 10 lbs.
# ==============================================================================

_WEIGHT_MILESTONES = [
    {
        "weight_lbs": 285,
        "name": "Sleep Threshold",
        "significance": "Sleep apnea risk drops substantially (genome flag). First major metabolic milestone on this journey.",
        "domains": ["sleep", "metabolic"],
    },
    {
        "weight_lbs": 270,
        "name": "Walking Speed Unlock",
        "significance": "Walking pace naturally improves ~0.3 mph from reduced load. Zone 2 walks feel meaningfully easier.",
        "domains": ["movement", "metabolic"],
    },
    {
        "weight_lbs": 250,
        "name": "Athletic Zone 2",
        "significance": "Zone 2 achievable at a pace that feels like a real workout — not just a stroll.",
        "domains": ["movement", "cardiovascular"],
    },
    {
        "weight_lbs": 225,
        "name": "Athletic FFMI Range",
        "significance": "FFMI crosses athletic range if muscle is preserved. Body composition makes the turn.",
        "domains": ["body", "strength"],
    },
    {
        "weight_lbs": 200,
        "name": "Onederland",
        "significance": "Under 200 lbs. Cardiovascular age improves dramatically. A threshold few expected.",
        "domains": ["metabolic", "cardiovascular"],
    },
    {
        "weight_lbs": 185,
        "name": "Goal Weight — Transformation Complete",
        "significance": "117 lbs lost from start. Athletic BMI. The person Matthew set out to become.",
        "domains": ["all"],
    },
]


def _build_milestone_context(profile, current_weight):
    """Return milestone alert string if within 10 lbs of upcoming or just passed a milestone.

    Empty string if no milestone is near — zero prompt bloat on normal days.
    """
    if current_weight is None:
        return ""

    milestones = profile.get("weight_milestones", _WEIGHT_MILESTONES)
    lines = []

    # Upcoming milestone (below current weight, approaching)
    upcoming = [m for m in milestones if m["weight_lbs"] < current_weight]
    if upcoming:
        next_m = max(upcoming, key=lambda x: x["weight_lbs"])
        lbs_away = round(current_weight - next_m["weight_lbs"], 1)
        if lbs_away <= 10:
            lines.append(f"🎯 MILESTONE APPROACHING: '{next_m['name']}' at {next_m['weight_lbs']} lbs ({lbs_away} lbs away)")
            lines.append(f"   Biological significance: {next_m['significance']}")

    # Most recently achieved milestone (current weight just passed it)
    achieved = [m for m in milestones if m["weight_lbs"] >= current_weight]
    if achieved:
        recent_m = min(achieved, key=lambda x: x["weight_lbs"])
        lbs_past = round(recent_m["weight_lbs"] - current_weight, 1)
        if lbs_past <= 5:
            lines.append(f"🏆 MILESTONE JUST ACHIEVED: '{recent_m['name']}' at {recent_m['weight_lbs']} lbs ({lbs_past} lbs below threshold)")
            lines.append(f"   Significance: {recent_m['significance']}")
            lines.append("   → Acknowledge this in your coaching. This is a real biological event, not just a number.")

    return "\n".join(lines)


# ==============================================================================
# IC-3: CHAIN-OF-THOUGHT ANALYSIS PASS
# Pass 1: structured pattern identification (100-150 tokens)
# Pass 2: coaching output using Pass 1 analysis
# Applied to BoD and TL;DR+Guidance calls.
# ==============================================================================

def _run_analysis_pass(component_scores, habit_miss_context, insights_ctx, api_key):
    """IC-3 Pass 1: Identify patterns and causal chains BEFORE writing coaching.

    Forces the model to reason about what's happening before it writes.
    Returns analysis dict, or None if the call fails (graceful degradation).
    """
    comp_str = ", ".join(
        f"{k.replace('_', ' ')}: {v}" for k, v in component_scores.items() if v is not None
    )

    prompt = f"""You are analyzing Matthew's health data. Output ONLY a JSON object, no preamble.

COMPONENT SCORES (0-100): {comp_str}
{insights_ctx or ''}
{habit_miss_context}

Identify the most important patterns. Then play devil's advocate on your own analysis.

Output this exact JSON structure:
{{"key_patterns": ["specific data observation 1", "specific data observation 2"], "likely_connection": "habit/metric X correlates with metric Y result — note this is a pattern, not proven causation", "challenge": "One reason this analysis might be wrong or misleading — e.g. confounding factor, insufficient data, correlation ≠ causation, or the obvious insight hiding a subtler one", "priority": "single most important coaching focus for today", "tone": "celebrate|challenge|support"}}"""

    try:
        raw = call_anthropic(prompt, api_key, max_tokens=200)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        return json.loads(raw.strip())
    except Exception as e:
        print("[WARN] IC-3 analysis pass failed: " + str(e))
        return None


def _format_analysis(analysis):
    """Format Pass 1 analysis for injection into Pass 2 prompt."""
    if not analysis:
        return ""
    lines = ["PATTERN ANALYSIS (synthesize these into your coaching, don't just list them):"]
    patterns = analysis.get("key_patterns", [])
    if patterns:
        for p in patterns:
            lines.append(f"  • {p}")
    chain = analysis.get("likely_connection", "") or analysis.get("causal_chain", "")  # AI-2: causal_chain renamed to likely_connection
    if chain:
        lines.append(f"  Likely pattern (correlation): {chain}")
    priority = analysis.get("priority", "")
    if priority:
        lines.append(f"  Today's priority: {priority}")
    challenge = analysis.get("challenge", "")
    if challenge:
        lines.append(f"  ⚠️ Red Team challenge: {challenge}")
    tone = analysis.get("tone", "")
    if tone:
        lines.append(f"  Tone: {tone}")
    return "\n".join(lines)


# ==============================================================================
# P2: JOURNEY CONTEXT BLOCK
# Injected into every AI call — week number, stage, stage-appropriate coaching.
# ==============================================================================

def _build_journey_context(profile, current_date_str=None):
    """
    Compute week number into transformation journey and return stage-appropriate
    coaching context. Prevents AI from coaching a Week-2 beginner at 300+ lbs
    like an intermediate athlete.

    Returns a dict with:
      week_num, days_in, stage, stage_label, coaching_principles (list[str])
    """
    start_str = profile.get("journey_start_date", "2026-04-01")
    try:
        start = _date_cls.fromisoformat(start_str)
        today = _date_cls.fromisoformat(current_date_str) if current_date_str else _date_cls.today()
        days_in = max(1, (today - start).days + 1)
        week_num = max(1, (days_in + 6) // 7)
    except Exception:
        days_in = 1
        week_num = 1

    start_weight = profile.get("journey_start_weight_lbs", 302)
    goal_weight  = profile.get("goal_weight_lbs", 185)

    # Periodization: Foundation (1-4wk) habit formation, Momentum (5-12) progressive overload,
    # Building (13-26) base, Advanced (27+) optimization
    if week_num <= 4:
        stage = "Foundation"
        principles = [
            f"WEEK {week_num} of transformation — form and consistency beat intensity at this stage.",
            f"Starting weight: {start_weight} lbs. At this bodyweight, a 45-min walk burns ~300-400 kcal and carries significant cardiovascular load — treat it as a PRIMARY training session, not a footnote.",
            "Walking IS the workout right now. Acknowledge distance, duration, and pace improvements as meaningful athletic progress.",
            "The primary goal this phase is HABIT FORMATION. All movement is meaningful, even if it looks simple to someone at half this bodyweight.",
            "Protein target adherence and calorie consistency matter more than macro fine-tuning at this stage.",
        ]
    elif week_num <= 12:
        stage = "Momentum"
        principles = [
            f"WEEK {week_num} — {days_in} days in. Habit foundation established. Progressive overload now appropriate.",
            "Training intensity can begin scaling. Recovery metrics should guide session intensity day-to-day.",
            f"Bodyweight ({start_weight}+ lbs at start) means bodyweight-adjusted benchmarks apply — not absolute pace/power/load standards.",
            "Consistency over weeks is more predictive of outcome than any single session's intensity.",
        ]
    elif week_num <= 26:
        stage = "Building"
        principles = [
            f"WEEK {week_num} — {days_in} days in. Meaningful base established.",
            "Progressive overload, periodization, and recovery optimization are primary training levers.",
            "Performance metrics (pace, load, HR drift) now carry coaching signal.",
        ]
    else:
        stage = "Advanced"
        principles = [
            f"WEEK {week_num} — {days_in} days in. Sustained transformation in progress.",
            "Performance coaching fully applicable. Data-driven periodization and protocol refinement are the levers.",
        ]

    return {
        "week_num": week_num,
        "days_in": days_in,
        "stage": stage,
        "stage_label": f"Week {week_num} ({stage} Stage, Day {days_in})",
        "start_weight": start_weight,
        "goal_weight": goal_weight,
        "coaching_principles": principles,
    }


def _format_journey_context(jctx):
    """Format journey context as a compact string for prompt injection."""
    lines = [f"JOURNEY CONTEXT: {jctx['stage_label']} | {jctx['start_weight']}→{jctx['goal_weight']} lbs"]
    lines.append("Stage-appropriate coaching principles:")
    for p in jctx["coaching_principles"]:
        lines.append(f"  • {p}")
    return "\n".join(lines)


# ==============================================================================
# P5: TDEE / DEFICIT CONTEXT
# ==============================================================================

def _build_tdee_context(data, profile):
    """
    Build TDEE + deficit context for nutrition AI calls.
    MacroFactor computes estimated TDEE; if not available, derive from phase targets.
    """
    mf = data.get("macrofactor") or {}
    # MacroFactor may store estimated TDEE as tdee_kcal or estimated_tdee_kcal
    tdee = _safe_float(mf, "tdee_kcal") or _safe_float(mf, "estimated_tdee_kcal")

    cal_target = profile.get("calorie_target", 1800)

    # Derive from current phase if MacroFactor doesn't expose TDEE
    if tdee is None:
        # Check weight phases for deficit target
        phases = profile.get("weight_loss_phases", [])
        latest_weight = data.get("latest_weight")
        deficit_target = 1500  # Phase 1 default
        for p in phases:
            if latest_weight and latest_weight >= p.get("end_lbs", 0):
                deficit_target = p.get("calorie_deficit_target", 1500)
                break
        tdee = cal_target + deficit_target

    # Actual intake
    actual_cal = _safe_float(mf, "total_calories_kcal")
    if actual_cal is None:
        return f"Estimated TDEE: ~{int(tdee)} kcal | Target: {cal_target} kcal/day"

    actual_deficit = tdee - actual_cal
    deficit_pct = round(actual_deficit / tdee * 100, 1)

    lines = [f"Estimated TDEE: ~{int(tdee)} kcal"]
    lines.append(f"Calorie target: {cal_target} kcal (planned deficit: ~{int(tdee - cal_target)} kcal)")
    lines.append(f"Actual intake: {int(actual_cal)} kcal → actual deficit: ~{int(actual_deficit)} kcal ({deficit_pct}% of TDEE)")

    if actual_cal < cal_target * 0.75:
        lines.append("⚠ VERY LOW INTAKE: >25% below target — may be a logging gap or aggressive restriction. Check for logging completeness before coaching deficit.")
    elif actual_cal > cal_target * 1.10:
        lines.append("⚠ ABOVE TARGET: more than 10% over calorie goal.")

    return "\n".join(lines)


# ==============================================================================
# P4: HABIT → OUTCOME PATTERNS (simplified)
# Traces causal links between habit completion and downstream metrics.
# ==============================================================================

def _build_habit_outcome_context(data, profile):
    """
    Simplified habit→outcome pattern context.
    Shows 7-day T0/T1 completion trend alongside key metric outcomes,
    so the AI can identify and call out causal chains rather than listing
    habit gaps and metric scores independently.
    """
    habitify_7d = data.get("habitify_7d") or []
    registry = profile.get("habit_registry", {})
    if not registry or not habitify_7d:
        return ""

    # Build causal mapping: habit → outcome metric it supports
    HABIT_OUTCOME_MAP = {
        # Sleep habits → sleep quality
        "wind_down_routine": "sleep_score",
        "no_screens_1hr_before_bed": "sleep_score",
        "no_screens_before_bed": "sleep_score",
        "consistent_bedtime": "sleep_score",
        "caffeine_cutoff": "sleep_score",
        "caffeine_cutoff_2pm": "sleep_score",
        # Nutrition habits → calorie/protein adherence
        "track_macros": "nutrition",
        "log_food": "nutrition",
        "protein_first": "protein_g",
        "meal_prep": "nutrition",
        # Movement habits → steps/exercise
        "morning_walk": "steps",
        "steps_goal": "steps",
        "exercise": "movement",
    }

    tier0_names = [n for n, m in registry.items()
                   if m.get("tier") == 0 and m.get("status") == "active"]
    tier1_names = [n for n, m in registry.items()
                   if m.get("tier") == 1 and m.get("status") == "active"]

    # 7-day completion trend
    trend_lines = []
    for day_rec in habitify_7d[-7:]:
        date_str = day_rec.get("sk", "").replace("DATE#", "")
        habits_map = day_rec.get("habits", {}) if isinstance(day_rec, dict) else {}
        t0_done = sum(1 for h in tier0_names
                      if habits_map.get(h) is not None and float(habits_map.get(h, 0)) >= 1)
        t1_done = sum(1 for h in tier1_names
                      if habits_map.get(h) is not None and float(habits_map.get(h, 0)) >= 1)
        trend_lines.append(f"  {date_str}: T0 {t0_done}/{len(tier0_names)}, T1 {t1_done}/{len(tier1_names)}")

    # Known habit-outcome relationships to surface to the AI
    causal_pairs = []
    for h_name, meta in registry.items():
        if meta.get("status") != "active" or meta.get("tier", 2) > 1:
            continue
        outcome = HABIT_OUTCOME_MAP.get(h_name.lower().replace(" ", "_"))
        why = meta.get("why_matthew", "")
        if why and outcome:
            causal_pairs.append(f"  {h_name} → impacts {outcome}: {why[:80]}")

    lines = ["HABIT→OUTCOME CONTEXT:"]
    if trend_lines:
        lines.append("7-day T0/T1 completion trend:")
        lines.extend(trend_lines)
    if causal_pairs:
        lines.append("Known habit→metric correlations (name the likely connection if habit was missed):")
        lines.extend(causal_pairs[:8])  # cap at 8 to avoid prompt bloat
    lines.append("INSTRUCTION: When a T0/T1 habit was missed, NAME THE LIKELY CORRELATIVE PATTERN. "
                 "Don't just list 'missed X' — connect it to the metric it's designed to support. "
                 "Frame as correlation, not proven causation: e.g. 'Wind-down missed → sleep efficiency 71% (vs your ~82% baseline — consistent pattern but not proven causal).'")

    return "\n".join(lines)


# ==============================================================================
# IC-24: DATA QUALITY SCORING
# Per-source confidence scores injected into AI prompts so the model knows
# when data is incomplete or suspicious. Eliminates coaching on logging gaps.
# ==============================================================================

def _compute_data_quality(data, profile):
    """Compute per-source data quality / confidence for yesterday's data.

    Returns a compact prompt block and a dict of source -> confidence (0-1).
    AI calls use the block to calibrate advice confidence.
    """
    signals = []
    scores = {}

    # --- Nutrition (MacroFactor) ---
    mf = data.get("macrofactor") or {}
    cal = _safe_float(mf, "total_calories_kcal")
    protein = _safe_float(mf, "total_protein_g")
    food_log = mf.get("food_log", [])
    cal_target = profile.get("calorie_target", 1800)

    if cal is None or cal == 0:
        signals.append("\u274c Nutrition (MacroFactor): NO DATA logged")
        scores["nutrition"] = 0.0
    else:
        # Check against 7-day average for consistency
        apple_7d = data.get("apple_7d") or []
        # Use simple heuristic: if calories < 50% of target, likely incomplete
        if cal < cal_target * 0.50:
            signals.append(f"\u26a0\ufe0f Nutrition: {int(cal)} cal logged \u2014 likely INCOMPLETE (target {cal_target}). Treat with skepticism.")
            scores["nutrition"] = 0.3
        elif cal < cal_target * 0.75:
            signals.append(f"\u26a0\ufe0f Nutrition: {int(cal)} cal \u2014 possibly incomplete or aggressive restriction. Verify before coaching.")
            scores["nutrition"] = 0.6
        else:
            meal_count = len(food_log) if food_log else 0
            if meal_count < 2 and cal > 500:
                signals.append(f"\u26a0\ufe0f Nutrition: {int(cal)} cal but only {meal_count} meal(s) logged \u2014 may be partial logging")
                scores["nutrition"] = 0.7
            else:
                scores["nutrition"] = 1.0

    # --- Sleep (Whoop) ---
    sleep = data.get("sleep") or {}
    sleep_score = _safe_float(sleep, "sleep_score")
    sleep_dur = _safe_float(sleep, "sleep_duration_hours")

    if sleep_score is None and sleep_dur is None:
        signals.append("\u274c Sleep (Whoop): NO DATA \u2014 device may not have synced")
        scores["sleep"] = 0.0
    elif sleep_dur is not None and sleep_dur < 2.0:
        signals.append(f"\u26a0\ufe0f Sleep: {sleep_dur}h logged \u2014 suspiciously short, possible sync issue")
        scores["sleep"] = 0.4
    else:
        scores["sleep"] = 1.0

    # --- Activity (Strava) ---
    strava = data.get("strava") or {}
    activity_count = strava.get("activity_count", 0)
    # No activity isn't a quality issue \u2014 could be a rest day
    scores["activity"] = 1.0

    # --- Apple Health (steps, CGM, gait) ---
    apple = data.get("apple") or {}
    steps = _safe_float(apple, "steps")
    glucose_avg = _safe_float(apple, "blood_glucose_avg")

    if not apple or (steps is None and glucose_avg is None):
        signals.append("\u274c Apple Health: NO DATA \u2014 phone sync gap")
        scores["apple_health"] = 0.0
    else:
        missing = []
        if steps is None:
            missing.append("steps")
        if glucose_avg is None:
            missing.append("CGM")
        if _safe_float(apple, "water_intake_ml") is None:
            missing.append("water")
        if missing:
            signals.append(f"\u26a0\ufe0f Apple Health: partial \u2014 missing {', '.join(missing)}")
            scores["apple_health"] = 0.6
        else:
            scores["apple_health"] = 1.0

    # --- Habitify ---
    habitify = data.get("habitify") or {}
    if not habitify or habitify.get("total_possible", 0) == 0:
        signals.append("\u26a0\ufe0f Habits (Habitify): NO DATA")
        scores["habits"] = 0.0
    else:
        scores["habits"] = 1.0

    # --- Journal ---
    journal_entries = data.get("journal_entries", [])
    if not journal_entries:
        scores["journal"] = 0.0
        # Not a signal \u2014 missing journal is common and handled elsewhere
    else:
        scores["journal"] = 1.0

    # Build overall score
    weighted_sources = {
        "nutrition": 0.25, "sleep": 0.25, "apple_health": 0.20,
        "habits": 0.15, "activity": 0.10, "journal": 0.05,
    }
    overall = sum(scores.get(s, 0) * w for s, w in weighted_sources.items())

    # Build prompt block
    if not signals:
        block = f"DATA QUALITY: {int(overall * 100)}% \u2014 all sources complete and consistent."
    else:
        lines = [f"DATA QUALITY: {int(overall * 100)}%"]
        for s in signals:
            lines.append(f"  {s}")
        lines.append("INSTRUCTION: Adjust confidence of advice for flagged sources. Do NOT coach assertively on incomplete data.")
        block = "\n".join(lines)

    return block, scores


# ==============================================================================
# IC-23: ATTENTION-WEIGHTED PROMPT BUDGETING
# Computes "surprise scores" for metrics \u2014 how far they deviate from personal
# rolling baseline. High-surprise gets expanded context; low-surprise compresses.
# Information theory applied to prompt engineering.
# ==============================================================================

def _compute_surprise_scores(data):
    """Compute per-metric surprise scores (0-1) based on deviation from 7-day baselines.

    Returns a dict of domain -> {surprise: float, direction: up|down|normal, detail: str}.
    Prompt builders use this to allocate context dynamically.
    """
    surprises = {}

    # --- HRV ---
    hrv_data = data.get("hrv", {})
    hrv_yesterday = hrv_data.get("hrv_yesterday")
    hrv_7d = hrv_data.get("hrv_7d")
    if hrv_yesterday is not None and hrv_7d and hrv_7d > 0:
        dev = abs(hrv_yesterday - hrv_7d) / hrv_7d
        direction = "up" if hrv_yesterday > hrv_7d else "down"
        surprises["hrv"] = {
            # 2.5x: 40% HRV deviation = max surprise; HRV has high day-to-day variance
            "surprise": min(1.0, dev * 2.5),
            "direction": direction,
            "detail": f"{hrv_yesterday:.0f}ms vs 7d avg {hrv_7d:.0f}ms ({'+' if direction == 'up' else '-'}{dev*100:.0f}%)",
        }

    # --- Sleep ---
    sleep = data.get("sleep") or {}
    sleep_score = _safe_float(sleep, "sleep_score")
    sleep_7d = data.get("sleep_7d") or []
    if sleep_score is not None and sleep_7d:
        scores_7d = [_safe_float(s, "sleep_score") for s in sleep_7d if _safe_float(s, "sleep_score") is not None]
        if scores_7d:
            avg_score = sum(scores_7d) / len(scores_7d)
            if avg_score > 0:
                dev = abs(sleep_score - avg_score) / avg_score
                direction = "up" if sleep_score > avg_score else "down"
                surprises["sleep"] = {
                    # 3.0x: 33% deviation = max surprise; sleep scores are more stable than HRV
                    "surprise": min(1.0, dev * 3.0),
                    "direction": direction,
                    "detail": f"Score {sleep_score:.0f} vs 7d avg {avg_score:.0f} ({'+' if direction == 'up' else '-'}{dev*100:.0f}%)",
                }

    # --- Nutrition (calories) ---
    mf = data.get("macrofactor") or {}
    cal = _safe_float(mf, "total_calories_kcal")
    cal_target = 1800  # Will be overridden by profile in caller if needed
    if cal is not None and cal > 0:
        dev_from_target = abs(cal - cal_target) / cal_target
        direction = "up" if cal > cal_target else "down"
        surprises["nutrition"] = {
            # 2.0x: 50% off cal target = max surprise; generous due to MacroFactor logging gaps
            "surprise": min(1.0, dev_from_target * 2.0),
            "direction": direction,
            "detail": f"{int(cal)} cal vs {cal_target} target ({'+' if direction == 'up' else '-'}{dev_from_target*100:.0f}%)",
        }

    # --- Steps ---
    apple = data.get("apple") or {}
    steps = _safe_float(apple, "steps")
    apple_7d = data.get("apple_7d") or []
    if steps is not None and apple_7d:
        steps_7d = [_safe_float(d, "steps") for d in apple_7d if _safe_float(d, "steps") is not None]
        if steps_7d:
            avg_steps = sum(steps_7d) / len(steps_7d)
            if avg_steps > 0:
                dev = abs(steps - avg_steps) / avg_steps
                direction = "up" if steps > avg_steps else "down"
                surprises["steps"] = {
                    "surprise": min(1.0, dev * 2.0),
                    "direction": direction,
                    "detail": f"{int(steps)} vs 7d avg {int(avg_steps)} ({'+' if direction == 'up' else '-'}{dev*100:.0f}%)",
                }

    # --- Glucose ---
    glucose_avg = _safe_float(apple, "blood_glucose_avg")
    if glucose_avg is not None and apple_7d:
        gluc_7d = [_safe_float(d, "blood_glucose_avg") for d in apple_7d if _safe_float(d, "blood_glucose_avg") is not None]
        if gluc_7d:
            avg_gluc = sum(gluc_7d) / len(gluc_7d)
            if avg_gluc > 0:
                dev = abs(glucose_avg - avg_gluc) / avg_gluc
                direction = "up" if glucose_avg > avg_gluc else "down"
                surprises["glucose"] = {
                    # 5.0x: 20% deviation = max surprise; glucose is physiologically tight-regulated
                    "surprise": min(1.0, dev * 5.0),
                    "direction": direction,
                    "detail": f"{glucose_avg:.0f} mg/dL vs 7d avg {avg_gluc:.0f} ({'+' if direction == 'up' else '-'}{dev*100:.0f}%)",
                }

    # --- Recovery (Whoop) ---
    whoop = data.get("whoop") or {}
    recovery = _safe_float(whoop, "recovery_score")
    if recovery is not None:
        # Recovery has known range 0-100, simple threshold-based surprise
        if recovery < 33:
            surprises["recovery"] = {"surprise": 0.9, "direction": "down", "detail": f"Recovery {recovery:.0f}% (red zone)"}
        elif recovery > 85:
            surprises["recovery"] = {"surprise": 0.6, "direction": "up", "detail": f"Recovery {recovery:.0f}% (peak)"}
        else:
            surprises["recovery"] = {"surprise": 0.1, "direction": "normal", "detail": f"Recovery {recovery:.0f}%"}

    return surprises


def _build_surprise_context(surprises, threshold=0.4):
    """Build a compact context block highlighting surprising metrics.

    Only surfaces metrics above the surprise threshold.
    Returns empty string if nothing is surprising (zero prompt bloat on normal days).
    """
    high_surprise = {k: v for k, v in surprises.items() if v["surprise"] >= threshold}
    if not high_surprise:
        return ""

    sorted_items = sorted(high_surprise.items(), key=lambda x: x[1]["surprise"], reverse=True)
    lines = ["\u26a1 ATTENTION-WORTHY SIGNALS (unusual vs recent baseline):"]
    for domain, info in sorted_items:
        icon = "\u2b06\ufe0f" if info["direction"] == "up" else "\u2b07\ufe0f" if info["direction"] == "down" else "\u27a1\ufe0f"
        lines.append(f"  {icon} {domain.upper()}: {info['detail']} (surprise: {info['surprise']:.1f})")
    lines.append("INSTRUCTION: Prioritize coaching on high-surprise signals. Low-surprise metrics need less attention today.")
    return "\n".join(lines)


# ==============================================================================
# IC-25: DIMINISHING RETURNS DETECTOR
# Identifies pillars where effort is high but score trajectory is flat.
# Redirects coaching to highest-leverage opportunities.
# ==============================================================================

def _compute_diminishing_returns(character_sheet, data, profile):
    """Detect pillars with high effort + flat/declining trajectory.

    Returns a prompt block redirecting coaching to highest-leverage pillar.
    Empty string if no diminishing returns detected or character sheet unavailable.
    """
    if not character_sheet:
        return ""

    registry = profile.get("habit_registry", {})
    habitify = data.get("habitify") or {}
    habits_map = habitify.get("habits", {}) if isinstance(habitify, dict) else {}

    # Map habits to pillars
    HABIT_PILLAR_MAP = {
        "sleep": ["wind_down_routine", "no_screens_before_bed", "no_screens_1hr_before_bed",
                  "consistent_bedtime", "caffeine_cutoff", "caffeine_cutoff_2pm"],
        "movement": ["morning_walk", "steps_goal", "exercise"],
        "nutrition": ["track_macros", "log_food", "protein_first", "meal_prep"],
        "mind": ["journal", "meditation", "gratitude"],
        "consistency": [],  # Meta-pillar, derived from others
    }

    pillar_analysis = []

    for pillar_name in ["sleep", "movement", "nutrition", "mind", "metabolic", "relationships", "consistency"]:
        pd = character_sheet.get(f"pillar_{pillar_name}", {})
        raw_score = pd.get("raw_score")
        level = pd.get("level", 0)

        if raw_score is None:
            continue

        # Compute effort: how many active habits for this pillar are being completed?
        pillar_habits = HABIT_PILLAR_MAP.get(pillar_name, [])
        active_habits = [h for h in pillar_habits if registry.get(h, {}).get("status") == "active"]
        if active_habits:
            completed = sum(1 for h in active_habits
                          if habits_map.get(h) is not None and float(habits_map.get(h, 0)) >= 1)
            effort_pct = round(completed / len(active_habits) * 100) if active_habits else 0
        else:
            effort_pct = None  # No habits mapped to this pillar

        pillar_analysis.append({
            "pillar": pillar_name,
            "score": raw_score,
            "level": level,
            "effort_pct": effort_pct,
        })

    if not pillar_analysis:
        return ""

    # Find highest-leverage opportunity: lowest score with room to grow
    scored = [p for p in pillar_analysis if p["score"] is not None]
    if not scored:
        return ""

    # Sort by score ascending \u2014 lowest score = most room for improvement
    scored.sort(key=lambda x: x["score"])
    lowest = scored[0]
    highest = scored[-1]

    # Detect diminishing returns: high effort + high score (above 75)
    saturated = [p for p in scored if p["effort_pct"] is not None
                 and p["effort_pct"] >= 80 and p["score"] >= 70]

    # Detect underinvested: low score + low effort (or no habits)
    underinvested = [p for p in scored if p["score"] < 50
                     and (p["effort_pct"] is None or p["effort_pct"] < 50)]

    lines = []

    if saturated and lowest["score"] < highest["score"] - 20:
        sat_names = ", ".join(p["pillar"].capitalize() for p in saturated)
        lines.append(f"LEVERAGE ANALYSIS:")
        lines.append(f"  \u26a0\ufe0f Diminishing returns on: {sat_names} (high effort, score already {saturated[0]['score']:.0f}+)")
        lines.append(f"  \u2b06\ufe0f Highest leverage: {lowest['pillar'].capitalize()} (score {lowest['score']:.0f}, most room for improvement)")
        if underinvested:
            ui_names = ", ".join(p["pillar"].capitalize() for p in underinvested)
            lines.append(f"  \ud83c\udfaf Underinvested: {ui_names} (low score + low effort = high ROI)")
        lines.append("INSTRUCTION: Redirect coaching effort toward highest-leverage pillars. Don't over-optimize what's already strong.")
    elif underinvested:
        ui_names = ", ".join(p["pillar"].capitalize() for p in underinvested)
        lines.append(f"LEVERAGE ANALYSIS:")
        lines.append(f"  \ud83c\udfaf Underinvested pillars: {ui_names} (low score + low effort \u2014 small changes here have outsized impact)")
        lines.append("INSTRUCTION: Nudge coaching toward underinvested pillars where effort-to-outcome ratio is highest.")

    return "\n".join(lines)


# ==============================================================================
# IC-7: CROSS-PILLAR TRADE-OFF REASONING
# Identifies conflicting pillar signals and surfaces explicit trade-off reasoning.
# Instead of coaching each pillar in isolation, finds where pillars are in tension
# and identifies the limiting factor + optimization call.
# ==============================================================================

def _build_cross_pillar_tradeoffs(component_scores, data, profile):
    """IC-7: Cross-pillar trade-off analysis.

    Detects when pillars conflict and names the limiting factor + optimization call.
    Enables coaching like: 'Sleep is the bottleneck \u2014 adding training load will compound
    the deficit, not improve fitness' instead of independently coaching both pillars.

    Returns a compact prompt block. Empty string if no meaningful trade-offs detected.
    """
    sleep_score       = component_scores.get("sleep")
    movement_score    = component_scores.get("movement")
    nutrition_score   = component_scores.get("nutrition")
    mind_score        = component_scores.get("mind")  # noqa: F841
    metabolic_score   = component_scores.get("metabolic_health")
    consistency_score = component_scores.get("consistency")

    mf      = data.get("macrofactor") or {}
    whoop   = data.get("whoop") or {}
    journal = data.get("journal") or {}

    cal        = _safe_float(mf, "total_calories_kcal")
    tsb        = data.get("tsb")
    sleep_debt = data.get("sleep_debt_7d_hrs")
    stress     = _safe_float(journal, "stress_avg")
    recovery   = _safe_float(whoop, "recovery_score")
    cal_target = profile.get("calorie_target", 1800)

    tradeoffs = []

    # 1. Sleep vs Movement: sleep is the limiting factor
    if sleep_score is not None and movement_score is not None:
        if sleep_score < 50 and movement_score > 60:
            debt_str = f", 7d sleep debt: {sleep_debt:.1f}h" if sleep_debt else ""
            tradeoffs.append(
                f"  \U0001f6cc Sleep ({sleep_score}) \u2194 Movement ({movement_score}): "
                f"Sleep is the LIMITING FACTOR{debt_str}. "
                "Adding training load will compound sleep deficit, not build fitness. "
                "\u2192 Optimization call: protect sleep infrastructure today; hold or reduce intensity."
            )
        elif sleep_score > 75 and movement_score < 45:
            tradeoffs.append(
                f"  \u26a1 Sleep ({sleep_score}) \u2194 Movement ({movement_score}): "
                "Sleep is STRONG \u2014 physiological readiness is high but Movement is lagging. "
                "\u2192 Optimization call: high-ROI training day. Substrate is recovered; adaptation window is open."
            )

    # 2. Nutrition deficit vs Training load (TSB)
    if cal is not None and tsb is not None:
        if cal < cal_target * 0.80 and tsb < -10:
            tradeoffs.append(
                f"  \u26a0\ufe0f Nutrition ({int(cal)} cal vs {cal_target} target) \u2194 Training fatigue (TSB {tsb:.0f}): "
                "Aggressive deficit + accumulated fatigue = under-fueling risk. "
                "\u2192 Optimization call: protein preservation takes priority over hitting calorie floor exactly today."
            )

    # 3. Mind/stress compounding physiological load
    if stress is not None and recovery is not None:
        if stress > 3.0 and recovery < 50:
            tradeoffs.append(
                f"  \U0001f9e0 Mind (journal stress {stress:.1f}/5) \u2194 Recovery ({recovery:.0f}%): "
                "Psychological and physiological stress are COMPOUNDING. Both systems are taxed. "
                "\u2192 Optimization call: this is a maintenance day. Reduce decision load; protect T0 habits only."
            )
    if stress is not None and stress > 3.5 and sleep_score is not None and sleep_score < 55:
        if not any("COMPOUNDING" in t for t in tradeoffs):
            tradeoffs.append(
                f"  \U0001f9e0 Mind (stress {stress:.1f}/5) \u2194 Sleep ({sleep_score}): "
                "Stress is likely suppressing sleep quality \u2014 the causation runs both ways. "
                "\u2192 Optimization call: sleep protocol compliance tonight has double ROI."
            )

    # 4. Nutrition behaviour strong but metabolic adaptation lagging
    if nutrition_score is not None and metabolic_score is not None:
        if nutrition_score > 70 and metabolic_score < 50:
            tradeoffs.append(
                f"  \U0001f4c8 Nutrition behaviour ({nutrition_score}) \u2194 Metabolic health ({metabolic_score}): "
                "Behavioural score is strong but metabolic adaptation LAGS by 1\u20133 weeks. "
                "\u2192 Optimization call: trust the process. Consistency is the bridge."
            )

    # 5. Consistency lagging behind pillar strength
    if consistency_score is not None and consistency_score < 45:
        strong_pillars = [k for k, v in component_scores.items()
                          if v is not None and v > 65 and k not in ("consistency", "relationships")]
        if strong_pillars:
            strong_str = ", ".join(k.replace("_", " ").title() for k in strong_pillars[:3])
            tradeoffs.append(
                f"  \U0001f517 Consistency ({consistency_score}) \u2194 Strong pillars ({strong_str}): "
                "Pillar strength is real but consistency is the compounding mechanism \u2014 without it, gains don\u2019t accumulate. "
                "\u2192 Optimization call: name one T0 habit to protect today regardless of everything else."
            )

    if not tradeoffs:
        return ""

    lines = ["CROSS-PILLAR TRADE-OFF ANALYSIS:"]
    lines.extend(tradeoffs)
    lines.append("")
    lines.append("INSTRUCTION: Reason about these trade-offs explicitly in your coaching. Name the limiting factor.")
    lines.append("Don't give equal coaching weight to all pillars \u2014 the constraint determines the ceiling.")
    lines.append("When pillars conflict, state the optimization call: which pillar to PRIORITIZE vs which to hold.")
    return "\n".join(lines)


# ==============================================================================
# DATA SUMMARY BUILDERS (used by AI prompt construction)
# ==============================================================================

def build_data_summary(data, profile):
    journal = data.get("journal") or {}
    mf = data.get("macrofactor") or {}
    strava = data.get("strava") or {}
    habitify = data.get("habitify") or {}
    apple = data.get("apple") or {}
    sleep = data.get("sleep") or {}
    return {
        "date": data.get("date"),
        "recovery_score": _safe_float(data.get("whoop"), "recovery_score"),
        "strain": _safe_float(data.get("whoop"), "strain"),
        "sleep_score": _safe_float(sleep, "sleep_score"),
        "sleep_duration_hrs": _safe_float(sleep, "sleep_duration_hours"),
        "sleep_efficiency_pct": _safe_float(sleep, "sleep_efficiency_pct"),
        "deep_sleep_pct": _safe_float(sleep, "deep_pct"),
        "rem_sleep_pct": _safe_float(sleep, "rem_pct"),
        "hrv_yesterday": data["hrv"].get("hrv_yesterday"),
        "hrv_7d_avg": data["hrv"].get("hrv_7d"),
        "hrv_30d_avg": data["hrv"].get("hrv_30d"),
        "calories": _safe_float(mf, "total_calories_kcal"),
        "protein_g": _safe_float(mf, "total_protein_g"),
        "fat_g": _safe_float(mf, "total_fat_g"),
        "carbs_g": _safe_float(mf, "total_carbs_g"),
        "fiber_g": _safe_float(mf, "total_fiber_g"),
        "steps": _safe_float(apple, "steps"),
        "water_ml": _safe_float(apple, "water_intake_ml"),
        "glucose_avg": _safe_float(apple, "blood_glucose_avg"),
        "glucose_tir": _safe_float(apple, "blood_glucose_time_in_range_pct"),
        "glucose_std_dev": _safe_float(apple, "blood_glucose_std_dev"),
        "glucose_min": _safe_float(apple, "blood_glucose_min"),
        "walking_speed_mph": _safe_float(apple, "walking_speed_mph"),
        "walking_step_length_in": _safe_float(apple, "walking_step_length_in"),
        "walking_asymmetry_pct": _safe_float(apple, "walking_asymmetry_pct"),
        "habits_completed": _safe_float(habitify, "total_completed"),
        "habits_possible": _safe_float(habitify, "total_possible"),
        "exercise_count": _safe_float(strava, "activity_count"),
        "exercise_minutes": round((_safe_float(strava, "total_moving_time_seconds") or 0) / 60, 1),
        "journal_mood": journal.get("mood_avg"),
        "journal_energy": journal.get("energy_avg"),
        "journal_stress": journal.get("stress_avg"),
        "current_weight": data.get("latest_weight"),
        "week_ago_weight": data.get("week_ago_weight"),
        "tsb": data.get("tsb"),
        "sleep_debt_7d_hrs": data.get("sleep_debt_7d_hrs"),
    }


def build_food_summary(data):
    mf = data.get("macrofactor") or {}
    food_log = mf.get("food_log", [])
    if not food_log:
        return "No food log data."
    meals = []
    for item in food_log:
        name = item.get("food_name", "?")
        cal = item.get("calories_kcal", 0)
        prot = item.get("protein_g", 0)
        t = item.get("time", "?")
        meals.append(str(t) + " - " + str(name) + " (" + str(round(float(cal))) + " cal, " + str(round(float(prot))) + "g P)")
    return "\n".join(meals)


def build_activity_summary(data):
    """Extract activity details from Strava."""
    strava = data.get("strava") or {}
    activities = strava.get("activities", [])
    if not activities:
        return "No activities recorded."
    lines = []
    for a in activities:
        name = a.get("name", "Activity")
        sport = a.get("sport_type", "?")
        duration_min = round((a.get("moving_time_seconds") or 0) / 60)
        avg_hr = a.get("average_heartrate")
        max_hr_act = a.get("max_heartrate")
        start = a.get("start_date_local", "")
        time_part = start.split("T")[1][:5] if "T" in start else "?"
        line = time_part + " - " + name + " (" + sport + ", " + str(duration_min) + " min"
        if avg_hr:
            line += ", avg HR " + str(round(avg_hr))
        if max_hr_act:
            line += ", max HR " + str(round(max_hr_act))
        line += ")"
        lines.append(line)
    return "\n".join(lines)


def build_workout_summary(data):
    """v2.2: Extract exercise-level detail from MacroFactor workouts."""
    mf_workouts = data.get("mf_workouts")
    if not mf_workouts:
        return "No strength training data."
    workouts = mf_workouts.get("workouts", [])
    if not workouts:
        return "No strength training data."
    lines = []
    for w in workouts:
        w_name = w.get("workout_name", "Workout")
        lines.append("WORKOUT: " + w_name)
        exercises = w.get("exercises", [])
        for ex in exercises:
            ex_name = ex.get("exercise_name", "?")
            sets = ex.get("sets", [])
            set_strs = []
            for s in sets:
                reps = s.get("reps", 0)
                weight = s.get("weight_lbs", 0)
                rir = s.get("rir")
                st = str(reps)
                if weight:
                    st += "@" + str(round(float(weight))) + "lb"
                if rir is not None:
                    st += " (RIR " + str(rir) + ")"
                set_strs.append(st)
            lines.append("  " + ex_name + ": " + ", ".join(set_strs))
        total_vol = mf_workouts.get("total_volume_lbs")
        total_sets = mf_workouts.get("total_sets")
        if total_vol:
            lines.append("Total volume: " + str(round(float(total_vol))) + " lbs, " + str(round(float(total_sets or 0))) + " sets")
    return "\n".join(lines)


# ==============================================================================
# ANTHROPIC API
# ==============================================================================

def call_anthropic(prompt, api_key, max_tokens=200, system=None,
                   output_type=None, health_context=None):
    """Call Anthropic API with exponential backoff (4 attempts: 5s/15s/45s delays).

    P1.8: Exponential backoff replaces fixed 2-attempt/5s retry.
    P1.9: Token usage emitted to CloudWatch LifePlatform/AI namespace.
    AI-3 middleware: validates output when output_type is specified (transparent fail-safe).
    R17-16: Graceful degradation — returns "" (empty string) after all retries exhausted
            instead of raising. Callers should check: if not result: handle_ai_unavailable().

    Args:
        output_type:    AIOutputType enum value — enables AI-3 output validation.
                        Pass None (default) to skip — used for JSON callers and IC passes.
        health_context: Dict of health metrics for context-aware validation checks
                        (e.g. {"recovery_score": 45, "tsb": -12}).
    Returns text string, or "" if Anthropic is unavailable after all retries.
    """
    body = {
        "model": AI_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system

    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    max_attempts = len(_BACKOFF_DELAYS) + 1  # 4
    for attempt in range(1, max_attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=55) as r:
                resp = json.loads(r.read())
                # P1.9: emit token usage metrics
                usage = resp.get("usage", {})
                if usage:
                    _emit_token_metrics(
                        usage.get("input_tokens", 0),
                        usage.get("output_tokens", 0),
                    )
                text = resp["content"][0]["text"].strip()
                # AI-3 middleware: validate output when output_type is specified
                if output_type is not None and _AI_VALIDATOR_AVAILABLE:
                    try:
                        vr = _validate_ai_output(text, output_type, health_context or {})
                        if vr.blocked:
                            print(f"[AI-3] BLOCKED {output_type}: {vr.block_reason}")
                        elif vr.warnings:
                            print(f"[AI-3] WARN {output_type}: {vr.warnings}")
                        return vr.sanitized_text
                    except Exception as _ve:
                        print(f"[WARN] ai_output_validator non-fatal: {_ve}")
                return text
        except urllib.error.HTTPError as e:
            retryable = e.code in (429, 529, 500, 502, 503, 504)
            print(f"[WARN] Anthropic HTTP {e.code} attempt {attempt}/{max_attempts}")
            if retryable and attempt < max_attempts:
                delay = _BACKOFF_DELAYS[attempt - 1]
                print(f"[INFO] Retrying in {delay}s...")
                time.sleep(delay)
            else:
                _emit_failure_metric()
                # R17-16: graceful degradation — return sentinel so callers know AI failed
                # (not just empty output). Callers should check for AI_UNAVAILABLE.
                print(f"[ERROR] Anthropic unavailable after {max_attempts} attempts (HTTP {e.code}).")
                return "[AI_UNAVAILABLE]"
        except urllib.error.URLError as e:
            print(f"[WARN] Anthropic network error attempt {attempt}/{max_attempts}: {e}")
            if attempt < max_attempts:
                delay = _BACKOFF_DELAYS[attempt - 1]
                print(f"[INFO] Retrying in {delay}s...")
                time.sleep(delay)
            else:
                _emit_failure_metric()
                print(f"[ERROR] Anthropic network unreachable after {max_attempts} attempts: {e}.")
                return "[AI_UNAVAILABLE]"


# ==============================================================================
# AI PROMPT HELPERS
# ==============================================================================

def _build_weight_context(data, profile):
    """Dynamic weight context for AI prompts."""
    start_w = profile.get("journey_start_weight_lbs", 302)
    goal_w = profile.get("goal_weight_lbs", 185)
    current_w = data.get("latest_weight")
    if current_w:
        lost = round(start_w - current_w, 1)
        remaining = round(current_w - goal_w, 1)
        return (f"Started at {start_w} lbs, currently {round(current_w, 1)} lbs, "
                f"goal {goal_w} lbs ({lost} lost so far, {remaining} to go)")
    return f"{start_w}->{goal_w} lbs"


def _build_recent_training_summary(data):
    """Summarize last 7 days of training for AI context."""
    strava_7d = data.get("strava_7d") or []
    if not strava_7d:
        return "No activities in last 7 days."
    lines = []
    for day_rec in strava_7d:
        date_str = day_rec.get("sk", "").replace("DATE#", "")
        activities = day_rec.get("activities", [])
        for a in activities:
            name = a.get("name", "Activity")
            sport = a.get("sport_type", "?")
            dur = round((a.get("moving_time_seconds") or 0) / 60)
            lines.append(f"{date_str}: {name} ({sport}, {dur} min)")
    return "\n".join(lines) if lines else "No activities in last 7 days."


# ==============================================================================
# IC-28: ACWR TRAINING LOAD COACHING CONTEXT
# Reads ACWR fields from computed_metrics (already written by acwr-compute before
# the Daily Brief runs). Provides prescriptive training guidance to the coach prompt.
# ==============================================================================

def _build_acwr_coaching_context(data):
    """IC-28: Extract ACWR training load status for the training coach prompt.

    Reads acwr/acwr_zone/acwr_alert/acwr_alert_reason from the computed_metrics
    record available in `data`. Returns a compact string for prompt injection,
    or empty string if no ACWR data present.
    """
    computed = data.get("computed_metrics") or {}
    zone   = computed.get("acwr_zone", "")
    acwr   = _safe_float(computed, "acwr")
    alert  = bool(computed.get("acwr_alert"))
    reason = computed.get("acwr_alert_reason", "")
    acute  = _safe_float(computed, "acute_load_7d")
    chron  = _safe_float(computed, "chronic_load_28d")

    if not zone or zone == "unknown" or acwr is None:
        return ""

    acwr_str  = f"{acwr:.2f}"
    acute_str = f"{acute:.1f}" if acute is not None else "?"
    chron_str = f"{chron:.1f}" if chron is not None else "?"

    lines = [f"TRAINING LOAD — ACWR (IC-28): {acwr_str} zone={zone.upper()} | 7d acute={acute_str} | 28d chronic={chron_str}"]
    if reason:
        lines.append(f"  {reason}")

    if zone == "danger":
        lines.append(
            "  COACHING RULE: ACWR is in the DANGER zone (>1.5). You MUST prescribe specific volume "
            "reductions in the training section. E.g. 'Zone 2 walk only today', "
            "'reduce planned volume by 40-50%', 'no PRs, no new load today'. "
            "Do NOT coach this as a normal training day."
        )
    elif zone == "caution":
        lines.append(
            "  COACHING RULE: ACWR is elevated (1.3-1.5). Prescribe volume reduction: "
            "lower intensity, no PRs, prioritise recovery session over planned workout if applicable."
        )
    elif zone == "detraining":
        lines.append(
            "  COACHING RULE: ACWR is below 0.8 — chronic load exceeds recent load. "
            "Gently flag under-stimulation. If recovery metrics support it, suggest a "
            "training session today to bring acute load up. This is an opportunity, not an alarm."
        )
    else:  # safe
        lines.append("  COACHING NOTE: Training load is in the optimal zone (0.8-1.3). Validate current approach.")

    return "\n".join(lines)


# ==============================================================================
# AI CALLS
# ==============================================================================

def call_training_nutrition_coach(data, profile, api_key):
    """AI call: Training coach + Nutritionist combined. (P2+P3+P5 aware)"""
    data_summary = build_data_summary(data, profile)
    food_summary = build_food_summary(data)
    activity_summary = build_activity_summary(data)
    workout_summary = build_workout_summary(data)
    weight_ctx = _build_weight_context(data, profile)
    recent_training = _build_recent_training_summary(data)

    # P2: Journey context
    jctx = _build_journey_context(profile, data.get("date"))
    journey_block = _format_journey_context(jctx)

    # P5: TDEE context
    tdee_ctx = _build_tdee_context(data, profile)

    # IC-28: ACWR training load context
    acwr_ctx = _build_acwr_coaching_context(data)

    # IC-24: Data quality (critical for nutrition coaching)
    data_quality_block, _quality_scores = _compute_data_quality(data, profile)

    cal_target = profile.get("calorie_target", 1800)
    protein_target = profile.get("protein_target_g", 190)
    fat_target = profile.get("fat_target_g", 60)
    carb_target = profile.get("carb_target_g", 125)

    prompt = f"""You are two coaches speaking to Matthew ({journey_block}).

{data_quality_block}

{tdee_ctx}

{acwr_ctx}

LAST 7 DAYS TRAINING CONTEXT:
{recent_training}

STRAVA ACTIVITIES YESTERDAY:
{activity_summary}

STRENGTH TRAINING DETAIL (from MacroFactor):
{workout_summary}

FOOD LOG YESTERDAY (with timestamps):
{food_summary}

MACRO TOTALS: {json.dumps({k: data_summary[k] for k in ["calories", "protein_g", "fat_g", "carbs_g", "fiber_g"] if k in data_summary}, default=str)}
TARGETS: {cal_target} cal, P{protein_target}g, F{fat_target}g, C{carb_target}g

TRAINING COACHING RULES (READ CAREFULLY):
- You are coaching someone at Week {jctx['week_num']} of transformation, starting weight {jctx['start_weight']} lbs.
- WALKS ARE PRIMARY TRAINING at this stage. A 45-min walk at {jctx['start_weight']}+ lbs carries ~300-400 kcal load and real cardiovascular demand. DO NOT give them "a brief NEAT acknowledgment." Give them real coaching: comment on pace, duration, HR if available, and connect to the aerobic base being built.
- For strength sessions: comment on exercise selection, volume, intensity (RIR), and how it connects to goals.
- Consider the 7-day training context. If yesterday was an appropriate rest day after recent training, say so — don't panic about low load.
- Evaluate distance, pace, and duration improvements relative to bodyweight and stage — NOT relative to absolute athlete benchmarks.

NUTRITION COACHING RULES:
- Reference TDEE context above to reason about deficit size.
- If intake is >25% below target, flag possible logging gap before assuming great adherence.
- Comment on macro adherence AND meal timing/distribution. When was protein consumed? Any long gaps?
- Be specific about what to adjust TODAY. Reference actual food items from the log.

Respond in EXACTLY this JSON format, no other text:
{{"training": "2-4 sentences from sports scientist. Per-activity analysis. Walks evaluated as primary sessions at Week {jctx['week_num']}. Reference specific metrics.", "nutrition": "2-3 sentences from nutritionist about macro adherence + meal timing + deficit context. Reference specific foods and timestamps. What to adjust today."}}"""

    try:
        raw = call_anthropic(prompt, api_key, max_tokens=500)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        return json.loads(cleaned)
    except Exception as e:
        print("[WARN] Training/nutrition coach failed: " + str(e))
        return {}


def call_journal_coach(data, profile, api_key):
    journal_entries = data.get("journal_entries", [])
    if not journal_entries:
        return ""
    texts = []
    for e in journal_entries[:3]:
        raw = e.get("raw_text", "")
        if raw:
            texts.append(raw[:500])
    if not texts:
        return ""
    journal_text = "\n---\n".join(texts)
    obstacles = profile.get("primary_obstacles", [])
    obstacles_str = ", ".join(obstacles) if obstacles else "none specified"
    weight_ctx = _build_weight_context(data, profile)

    # P2: Journey context in journal coach too
    jctx = _build_journey_context(profile, data.get("date"))

    prompt = f"""You are a wise, warm-but-direct inner coach reading Matthew's journal from yesterday.
He's 36, {jctx['stage_label']} of transformation ({weight_ctx}), battling: {obstacles_str}.
His coaching tone: Jocko's discipline meets Attia's precision meets Brene Brown's vulnerability.

JOURNAL ENTRIES:
{journal_text}

Write EXACTLY two parts separated by " || ":
Part 1: A perspective/reflection on what he wrote. Not a summary — a mirror that shows him something he might not see. 2 sentences max.
Part 2: One specific tactical thing he can try JUST TODAY. Be concrete (e.g. "practice box breathing for 30 seconds before each meal" or "text one person you're grateful for before noon"). 1 sentence.

TONE RULES:
- Match the emotional truth of what he actually wrote — don't force motivation onto a flat day or add caveats to a genuinely good day.
- If the journal shows avoidance, deflection, or a recurring unfinished intention, name it directly and without softening. "You've written about X three times this week without acting on it" is more useful than "consider taking action."
- If the journal shows genuine progress or insight, celebrate it without qualification. Not every note needs a challenge.
- 'Profound' is not a goal — honest is.

Format: [reflection] || [tactical thing]
No labels, no formatting. Natural voice. Max 80 words total."""

    try:
        return call_anthropic(prompt, api_key, max_tokens=250,
                              output_type=AIOutputType.JOURNAL_COACH if _AI_VALIDATOR_AVAILABLE else None)
    except Exception as e:
        print("[WARN] Journal coach failed: " + str(e))
        return ""


# -- Board of Directors prompt builder -----------------------------------------

def _build_daily_bod_intro_from_config(data=None, profile=None):
    """Build the Board of Directors role intro from S3 config."""
    if not _HAS_BOARD_LOADER or not _board_loader:
        return None

    config = _board_loader.load_board(_s3, _S3_BUCKET)
    if not config:
        return None

    members = _board_loader.get_feature_members(config, "daily_brief")
    if not members:
        return None

    panel_parts = []
    for mid, member, feat_cfg in members:
        role = feat_cfg.get("role", "unified_panel")
        if role == "unified_panel":
            title = member.get("title", member["name"])
            contribution = feat_cfg.get("contribution", "")
            panel_parts.append(f"{title} ({contribution})" if contribution else title)

    panel_desc = " + ".join(panel_parts) if panel_parts else "sports scientist + nutritionist + sleep specialist + behavioral coach"

    protocol_note = ""
    for mid, member, feat_cfg in members:
        if feat_cfg.get("role") == "protocol_tips":
            protocol_note = f"\n{member['name']} provides: {feat_cfg.get('contribution', 'protocol recommendations')}"

    weight_ctx = _build_weight_context(data, profile) if data and profile else "302->185 lbs"
    intro = f"""You are the Board of Directors for Project40 — {panel_desc} — unified.
Speaking to Matthew, 36yo, weight loss journey ({weight_ctx}). Phase 1 Ignition: 3 lbs/week, 1500 kcal deficit, 1800 cal daily.
Tone: direct, empathetic, no-BS.{protocol_note}"""

    print("[INFO] Using config-driven daily BoD prompt")
    return intro


def call_board_of_directors(data, profile, day_grade, grade, component_scores, api_key,
                             character_sheet=None, brief_mode="standard"):
    data_summary = build_data_summary(data, profile)
    comp_lines = []
    for comp, score in component_scores.items():
        label = comp.replace("_", " ").title()
        val = str(score) + "/100" if score is not None else "no data"
        comp_lines.append("  " + label + ": " + val)
    component_summary = "\n".join(comp_lines)
    obstacles = profile.get("primary_obstacles", [])
    health_ctx = "Primary obstacles: " + ", ".join(obstacles) + "." if obstacles else ""
    journal_ctx = ""
    journal_entries = data.get("journal_entries", [])
    if journal_entries:
        texts = []
        for e in journal_entries[:3]:
            raw = e.get("raw_text", "")
            if raw:
                texts.append(raw[:300])
        if texts:
            journal_ctx = "JOURNAL ENTRIES:\n" + "\n---\n".join(texts)

    # Habit context from registry
    registry = profile.get("habit_registry", {})
    habitify = data.get("habitify") or {}
    h_map = habitify.get("habits", {})
    missed_t0 = []
    missed_t1 = []
    for h_name, meta in registry.items():
        if meta.get("status") != "active" or meta.get("tier", 2) > 1:
            continue
        done = h_map.get(h_name, 0)
        if not (done is not None and float(done) >= 1):
            why = meta.get("why_matthew", "")
            tier = meta.get("tier", 2)
            if tier == 0:
                missed_t0.append(h_name + (" — " + why[:80] if why else ""))
            elif tier == 1:
                missed_t1.append(h_name)
    habit_ctx = ""
    if missed_t0:
        habit_ctx += "\nMISSED TIER 0 (non-negotiable): " + "; ".join(missed_t0)
    if missed_t1:
        habit_ctx += "\nMISSED TIER 1 (high priority): " + ", ".join(missed_t1[:8])

    # Synergy group analysis
    synergy_misses = {}
    for h_name, meta in registry.items():
        if meta.get("status") != "active":
            continue
        sg = meta.get("synergy_group")
        if not sg:
            continue
        done = h_map.get(h_name, 0)
        if not (done is not None and float(done) >= 1):
            synergy_misses.setdefault(sg, []).append(h_name)
    for sg, misses in synergy_misses.items():
        total_in_group = sum(1 for _, m in registry.items() if m.get("synergy_group") == sg and m.get("status") == "active")
        if len(misses) >= total_in_group * 0.5 and total_in_group >= 3:
            habit_ctx += "\nSYNERGY ALERT: " + sg + " stack mostly missing (" + ", ".join(misses[:5]) + ")"

    # Character sheet context
    character_ctx = ""
    if character_sheet:
        cs_level = character_sheet.get("character_level", 1)
        cs_tier = character_sheet.get("character_tier", "Foundation")
        cs_events = character_sheet.get("level_events", [])
        cs_effects = character_sheet.get("active_effects", [])
        character_ctx = "\nCHARACTER SHEET: Level " + str(cs_level) + " (" + cs_tier + ")"
        for pn in ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]:
            pd = character_sheet.get("pillar_" + pn, {})
            character_ctx += "\n  " + pn.capitalize() + ": Level " + str(pd.get("level", "?")) + " (" + str(pd.get("tier", "?")) + ") raw=" + str(pd.get("raw_score", "?"))
        if cs_events:
            character_ctx += "\nLEVEL EVENTS TODAY:"
            for ev in cs_events:
                ev_type = ev.get("type", "")
                if "tier" in ev_type:
                    character_ctx += "\n  " + ev.get("pillar", "").capitalize() + ": " + str(ev.get("old_tier", "")) + " → " + str(ev.get("new_tier", ""))
                elif "character" in ev_type:
                    character_ctx += "\n  Character Level " + str(ev.get("old_level", "")) + " → " + str(ev.get("new_level", ""))
                else:
                    arrow = "↑" if "up" in ev_type else "↓"
                    character_ctx += "\n  " + arrow + " " + ev.get("pillar", "").capitalize() + " Level " + str(ev.get("old_level", "")) + " → " + str(ev.get("new_level", ""))
        if cs_effects:
            character_ctx += "\nACTIVE EFFECTS: " + ", ".join(e.get("name", "") for e in cs_effects)

    # P2: Journey context
    jctx = _build_journey_context(profile, data.get("date"))
    journey_block = _format_journey_context(jctx)

    # P4: Habit → outcome patterns
    habit_outcome_ctx = _build_habit_outcome_context(data, profile)

    # IC-2: Pre-computed platform intelligence
    insights_ctx = _load_insights_context(data)

    # IC-3: Chain-of-thought analysis pass (Pass 1 — patterns before coaching)
    analysis = _run_analysis_pass(component_scores, habit_ctx + habit_outcome_ctx, insights_ctx, api_key)
    analysis_block = _format_analysis(analysis)

    # IC-6: Milestone architecture
    milestone_ctx = _build_milestone_context(profile, data.get("latest_weight"))

    # IC-24: Data quality scoring
    data_quality_block, _quality_scores = _compute_data_quality(data, profile)

    # IC-23: Surprise scoring (attention-weighted prompt budgeting)
    surprises = _compute_surprise_scores(data)
    surprise_ctx = _build_surprise_context(surprises)

    # IC-25: Diminishing returns detector
    diminishing_ctx = _compute_diminishing_returns(character_sheet, data, profile)

    # IC-7: Cross-pillar trade-off reasoning
    tradeoff_ctx = _build_cross_pillar_tradeoffs(component_scores, data, profile)

    # Try config-driven intro, fall back to dynamic default
    bod_intro = _build_daily_bod_intro_from_config(data, profile)
    if not bod_intro:
        print("[INFO] Using fallback dynamic daily BoD prompt")
        weight_ctx = _build_weight_context(data, profile)
        bod_intro = ("You are the Board of Directors for Project40 — sports scientist + nutritionist + sleep specialist + behavioral coach unified.\n"
                     f"Speaking to Matthew, 36yo, weight loss journey ({weight_ctx}). Phase 1 Ignition: 3 lbs/week, 1500 kcal deficit, 1800 cal daily.\n"
                     "Tone: direct, empathetic, no-BS.")

    prompt = bod_intro + f"""

{journey_block}
{health_ctx}
{milestone_ctx}

YESTERDAY'S DATA:
{json.dumps(data_summary, indent=2, default=str)}

DAY GRADE: {str(day_grade if day_grade is not None else "N/A")}/100 ({grade})
{component_summary}
{habit_ctx}
{habit_outcome_ctx}
{character_ctx}
{journal_ctx}
{insights_ctx}
{analysis_block}
{data_quality_block}
{surprise_ctx}
{diminishing_ctx}
{tradeoff_ctx}

Write 2-3 sentences. Reference specific numbers (at least two). Connect yesterday to today.
Celebrate wins briefly, name gaps directly — if a Tier 0 habit was missed, NAME it.
If a synergy stack is broken, note it. If there are LEVEL EVENTS, mention them.
If there are ACTIVE EFFECTS like Sleep Drag, note the impact.
CRITICAL: If habit gaps connect to metric outcomes (e.g. missed wind-down → low sleep efficiency), NAME THE LIKELY CORRELATIVE PATTERN (correlation, not proven causal). Don't just list the gap — connect the dots, but frame as a pattern to investigate, not a certainty.
CROSS-PILLAR: If the trade-off analysis above identifies a limiting factor or optimization call, incorporate it — don't coach conflicting pillars independently.
RED TEAM CHECK: If the analysis pass flagged a challenge (⚠️ above), consider it. If the correlation might be misleading or there's a confounding factor, adjust your coaching accordingly — don't give confident advice based on shaky signal. Intellectual honesty > false certainty.
OPENING RULE: DO NOT open with a metric readout. The form 'Recovery was X%, HRV was Y, today do Z' is explicitly banned as an opener — it's a data dump, not coaching. Open instead with a pattern ("Three nights of short sleep are compounding..."), a direct challenge ("The T0 miss yesterday is the third this week..."), or a concrete observation that requires inference, not just reading. The metric data exists in the scorecard above — the BoD's job is to interpret it, not repeat it.
DO NOT start with "Matthew". Max 60 words."""

    if brief_mode == "flourishing":
        prompt += "\n\nTONE: He is FLOURISHING — engagement is high, habits strong, trajectory improving. Lead with reinforcement. Be energising. Name what's working specifically. One brief forward-looking note."
    elif brief_mode == "struggling":
        prompt += "\n\nTONE: He is in a ROUGH PATCH — engagement is low, habits slipping. Be warm, not clinical. Acknowledge the difficulty without piling on. Focus on the smallest possible next right action. No guilt."

    _hctx = {
        "recovery_score": _safe_float(data.get("whoop"), "recovery_score") if data else None,
        "tsb": data.get("tsb") if data else None,
        "sleep_score": _safe_float((data.get("sleep") or {}), "sleep_score") if data else None,
    }
    return call_anthropic(prompt, api_key, max_tokens=200,
                          output_type=AIOutputType.BOD_COACHING if _AI_VALIDATOR_AVAILABLE else None,
                          health_context=_hctx)


def call_tldr_and_guidance(data, profile, day_grade, grade, component_scores, component_details,
                            readiness_score, readiness_colour, api_key):
    """v2.3: Combined TL;DR + Smart Guidance — one AI call that returns both. (P2+P4+P5 aware)"""
    data_summary = build_data_summary(data, profile)

    # Missed habits context
    habitify = data.get("habitify") or {}
    habits_map = habitify.get("habits", {})
    registry = profile.get("habit_registry", {})
    missed_mvp = []
    missed_context = []
    if registry:
        for h_name, meta in registry.items():
            if meta.get("status") != "active" or meta.get("tier", 2) > 1:
                continue
            done = habits_map.get(h_name, 0)
            if not (done is not None and float(done) >= 1):
                missed_mvp.append(h_name)
                why = meta.get("why_matthew", "")
                if why:
                    missed_context.append(h_name + " (T" + str(meta.get("tier", "?")) + "): " + why[:60])
    else:
        mvp_list = profile.get("mvp_habits", [])
        for h in mvp_list:
            done = habits_map.get(h, 0)
            if not (done is not None and float(done) >= 1):
                missed_mvp.append(h)

    comp_lines = []
    for comp, score in component_scores.items():
        if score is not None:
            comp_lines.append(comp.replace("_", " ") + ": " + str(score))
        elif comp == "hydration":
            comp_lines.append("hydration: NO DATA (Apple Health sync gap — do not give hydration tips)")

    sleep = data.get("sleep") or {}
    sleep_arch = ""
    deep = _safe_float(sleep, "deep_pct")
    rem = _safe_float(sleep, "rem_pct")
    if deep is not None:
        sleep_arch = "Deep: " + str(round(deep)) + "%, REM: " + str(round(rem or 0)) + "%"

    weight_ctx = _build_weight_context(data, profile)

    # P2: Journey context
    jctx = _build_journey_context(profile, data.get("date"))
    journey_block = _format_journey_context(jctx)

    # P5: TDEE context
    tdee_ctx = _build_tdee_context(data, profile)

    # P4: Habit → outcome patterns
    habit_outcome_ctx = _build_habit_outcome_context(data, profile)

    # IC-2: Pre-computed intelligence
    insights_ctx = _load_insights_context(data)

    # IC-3: Analysis pass (Pass 1)
    analysis = _run_analysis_pass(
        component_scores,
        ("MISSED HABITS: " + ", ".join(missed_mvp)) if missed_mvp else "",
        insights_ctx, api_key)
    analysis_block = _format_analysis(analysis)

    # IC-6: Milestone
    milestone_ctx = _build_milestone_context(profile, data_summary.get("current_weight"))

    # IC-24: Data quality scoring
    data_quality_block, _quality_scores = _compute_data_quality(data, profile)

    # IC-23: Surprise scoring
    surprises = _compute_surprise_scores(data)
    surprise_ctx = _build_surprise_context(surprises)

    # IC-7: Cross-pillar trade-off reasoning
    tradeoff_ctx = _build_cross_pillar_tradeoffs(component_scores, data, profile)

    prompt = f"""You are the intelligence engine behind Matthew's Life Platform daily brief.
Your job: synthesize ALL of yesterday's data into (1) one TL;DR sentence and (2) 3-4 smart, personalized guidance items for TODAY.

{journey_block}

{tdee_ctx}

YESTERDAY'S SIGNALS:
- Day grade: {day_grade}/100 ({grade})
- Components: {", ".join(comp_lines)}
- Recovery/readiness: {readiness_score} ({readiness_colour})
- HRV: {data_summary.get("hrv_yesterday")}ms yesterday, 7d avg {data_summary.get("hrv_7d_avg")}ms, 30d avg {data_summary.get("hrv_30d_avg")}ms
- TSB (training stress balance): {data_summary.get("tsb")}
- Sleep: {data_summary.get("sleep_duration_hrs")}hrs, score {data_summary.get("sleep_score")}, efficiency {data_summary.get("sleep_efficiency_pct")}%. {sleep_arch}
- 7-day sleep debt: {data.get("sleep_debt_7d_hrs")}hrs
- Calories: {data_summary.get("calories")}/target, Protein: {data_summary.get("protein_g")}g/{profile.get("protein_target_g", 190)}g
- Glucose: avg {data_summary.get("glucose_avg")} mg/dL, TIR {data_summary.get("glucose_tir")}%, overnight low {data_summary.get("glucose_min")} mg/dL
- Gait: walking speed {data_summary.get("walking_speed_mph")} mph, step length {data_summary.get("walking_step_length_in")} in, asymmetry {data_summary.get("walking_asymmetry_pct")}%
- Steps: {data_summary.get("steps")}
- Weight: {data_summary.get("current_weight")} lbs (week ago: {data_summary.get("week_ago_weight")})
- Missed habits: {(", ".join(missed_mvp) if missed_mvp else "none — all completed")}
- Missed habit context: {("; ".join(missed_context[:5]) if missed_context else "n/a")}
- Journal mood: {data_summary.get("journal_mood")}/5, stress: {data_summary.get("journal_stress")}/5

{habit_outcome_ctx}
{insights_ctx}
{milestone_ctx}
{analysis_block}
{data_quality_block}
{surprise_ctx}
{tradeoff_ctx}

RULES:
- TL;DR: One sentence, max 20 words. Must reference at least ONE SPECIFIC NUMBER from yesterday's data. The single most important takeaway — something that could only apply to yesterday's specific combination, not a generic summary. WRONG: 'Strong day overall, maintain momentum.' RIGHT: '81% recovery + 34g protein short — Zone 2 walk today, protein shake first.'
- Guidance: 3-4 items, each with an emoji prefix and 1 sentence. SMART — derived from the data above, not static advice. Each item should be something that could ONLY apply to TODAY given this specific data combination.
- CROSS-PILLAR TRADE-OFFS: If the trade-off analysis above identifies a limiting factor or optimization call, let it shape guidance priority. When pillars conflict, guide toward the constraint, not all pillars simultaneously.
- TDEE-aware nutrition guidance: use the TDEE context to reason about whether today's intake target should be maintained, increased (recovery day), or whether yesterday's intake looks like a logging gap vs genuine restriction.
- Walk/movement coaching is STAGE-APPROPRIATE: at Week {jctx['week_num']}, if steps were high, that's a genuine training achievement — acknowledge it as such.
- If habit gaps connect to metric outcomes, name the likely correlative pattern (correlation, not proven causal) — e.g. "Wind-down missed again last night — sleep efficiency dropped to 71% (consistent pattern). One habit change tonight may move that number."
- Avoid repeating daily constants (IF window, supplements, bedtime) unless there is a data-driven reason to modify them today.
- NEVER suggest hydration tips if hydration shows NO DATA — the sync is broken, not the behaviour.
- RED TEAM CHECK: If the analysis pass flagged a challenge (⚠️ above), factor it into your guidance. Don't build today's plan on a correlation that might be misleading. If confidence in a pattern is low, say so — e.g. "sleep dipped but only 2 days of data — monitor rather than react."

Examples of SMART guidance: "HRV down 15% + high stress yesterday — do Zone 2 instead of planned HIIT", "Protein 40g short yesterday — front-load with 50g shake before first meal"
Examples of BAD guidance (too generic): "Stay hydrated", "Get 7.5 hours of sleep", "Caffeine cutoff at noon"

Respond in EXACTLY this JSON format, no other text:
{{"tldr": "One sentence TL;DR", "guidance": ["emoji + sentence 1", "emoji + sentence 2", "emoji + sentence 3"]}}"""

    # health_context passed so AI-3 validator can run hallucination detection
    # on the guidance items (checks claimed metric values against actual data).
    _hctx = {
        "recovery_score": data_summary.get("recovery_score"),
        "tsb":            data_summary.get("tsb"),
        "sleep_score":    data_summary.get("sleep_score"),
    }
    try:
        raw = call_anthropic(prompt, api_key, max_tokens=450,
                             output_type=AIOutputType.GUIDANCE if _AI_VALIDATOR_AVAILABLE else None,
                             health_context=_hctx)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        return json.loads(cleaned)
    except Exception as e:
        print("[WARN] TL;DR+Guidance failed: " + str(e))
        return {}
