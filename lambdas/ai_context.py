"""
lambdas/ai_context.py — pure prompt-context + scoring builders.

Extracted from ai_calls.py (god-module split, slice 2 of N, 2026-06-08). Like
ai_summaries, these are pure: they turn data/profile/character_sheet dicts into
prompt-context strings/dicts and call nothing in the AI layer (no call_anthropic,
no module state). ai_calls.py re-exports them for backward compatibility.
"""

from datetime import date as _date_cls

from ai_summaries import _avg, _safe_float  # noqa: F401
from constants import EXPERIMENT_BASELINE_WEIGHT_LBS, EXPERIMENT_START_DATE  # noqa: F401


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
    start_str = profile.get("journey_start_date", EXPERIMENT_START_DATE)
    try:
        start = _date_cls.fromisoformat(start_str)
        today = _date_cls.fromisoformat(current_date_str) if current_date_str else _date_cls.today()
        days_in = max(1, (today - start).days + 1)
        week_num = max(1, (days_in + 6) // 7)
    except Exception:
        days_in = 1
        week_num = 1

    start_weight = profile.get("journey_start_weight_lbs", EXPERIMENT_BASELINE_WEIGHT_LBS)
    goal_weight = profile.get("goal_weight_lbs", 185)

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
        lines.append(
            "⚠ VERY LOW INTAKE: >25% below target — may be a logging gap or aggressive restriction. Check for logging completeness before coaching deficit."
        )
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

    tier0_names = [n for n, m in registry.items() if m.get("tier") == 0 and m.get("status") == "active"]
    tier1_names = [n for n, m in registry.items() if m.get("tier") == 1 and m.get("status") == "active"]

    # 7-day completion trend
    trend_lines = []
    for day_rec in habitify_7d[-7:]:
        date_str = day_rec.get("sk", "").replace("DATE#", "")
        habits_map = day_rec.get("habits", {}) if isinstance(day_rec, dict) else {}
        t0_done = sum(1 for h in tier0_names if habits_map.get(h) is not None and float(habits_map.get(h, 0)) >= 1)
        t1_done = sum(1 for h in tier1_names if habits_map.get(h) is not None and float(habits_map.get(h, 0)) >= 1)
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
    lines.append(
        "INSTRUCTION: When a T0/T1 habit was missed, NAME THE LIKELY CORRELATIVE PATTERN. "
        "Don't just list 'missed X' — connect it to the metric it's designed to support. "
        "Frame as correlation, not proven causation: e.g. 'Wind-down missed → sleep efficiency 71% (vs your ~82% baseline — consistent pattern but not proven causal).'"
    )

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
    _safe_float(mf, "total_protein_g")
    food_log = mf.get("food_log", [])
    cal_target = profile.get("calorie_target", 1800)

    if cal is None or cal == 0:
        signals.append("\u274c Nutrition (MacroFactor): NO DATA logged")
        scores["nutrition"] = 0.0
    else:
        # Check against 7-day average for consistency
        data.get("apple_7d") or []
        # Use simple heuristic: if calories < 50% of target, likely incomplete
        if cal < cal_target * 0.50:
            signals.append(
                f"\u26a0\ufe0f Nutrition: {int(cal)} cal logged \u2014 likely INCOMPLETE (target {cal_target}). Treat with skepticism."
            )
            scores["nutrition"] = 0.3
        elif cal < cal_target * 0.75:
            signals.append(
                f"\u26a0\ufe0f Nutrition: {int(cal)} cal \u2014 possibly incomplete or aggressive restriction. Verify before coaching."
            )
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
    strava.get("activity_count", 0)
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
        "nutrition": 0.25,
        "sleep": 0.25,
        "apple_health": 0.20,
        "habits": 0.15,
        "activity": 0.10,
        "journal": 0.05,
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
        "sleep": [
            "wind_down_routine",
            "no_screens_before_bed",
            "no_screens_1hr_before_bed",
            "consistent_bedtime",
            "caffeine_cutoff",
            "caffeine_cutoff_2pm",
        ],
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
            completed = sum(1 for h in active_habits if habits_map.get(h) is not None and float(habits_map.get(h, 0)) >= 1)
            effort_pct = round(completed / len(active_habits) * 100) if active_habits else 0
        else:
            effort_pct = None  # No habits mapped to this pillar

        pillar_analysis.append(
            {
                "pillar": pillar_name,
                "score": raw_score,
                "level": level,
                "effort_pct": effort_pct,
            }
        )

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
    saturated = [p for p in scored if p["effort_pct"] is not None and p["effort_pct"] >= 80 and p["score"] >= 70]

    # Detect underinvested: low score + low effort (or no habits)
    underinvested = [p for p in scored if p["score"] < 50 and (p["effort_pct"] is None or p["effort_pct"] < 50)]

    lines = []

    if saturated and lowest["score"] < highest["score"] - 20:
        sat_names = ", ".join((p.get("pillar") or "").capitalize() for p in saturated)
        lines.append("LEVERAGE ANALYSIS:")
        lines.append(f"  \u26a0\ufe0f Diminishing returns on: {sat_names} (high effort, score already {saturated[0]['score']:.0f}+)")
        lines.append(
            f"  \u2b06\ufe0f Highest leverage: {(lowest.get('pillar') or '').capitalize()} (score {lowest['score']:.0f}, most room for improvement)"
        )
        if underinvested:
            ui_names = ", ".join((p.get("pillar") or "").capitalize() for p in underinvested)
            lines.append(f"  \ud83c\udfaf Underinvested: {ui_names} (low score + low effort = high ROI)")
        lines.append("INSTRUCTION: Redirect coaching effort toward highest-leverage pillars. Don't over-optimize what's already strong.")
    elif underinvested:
        ui_names = ", ".join((p.get("pillar") or "").capitalize() for p in underinvested)
        lines.append("LEVERAGE ANALYSIS:")
        lines.append(
            f"  \ud83c\udfaf Underinvested pillars: {ui_names} (low score + low effort \u2014 small changes here have outsized impact)"
        )
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
    sleep_score = component_scores.get("sleep")
    movement_score = component_scores.get("movement")
    nutrition_score = component_scores.get("nutrition")
    mind_score = component_scores.get("mind")  # noqa: F841
    metabolic_score = component_scores.get("metabolic_health")
    consistency_score = component_scores.get("consistency")

    mf = data.get("macrofactor") or {}
    whoop = data.get("whoop") or {}
    journal = data.get("journal") or {}

    cal = _safe_float(mf, "total_calories_kcal")
    tsb = data.get("tsb")
    sleep_debt = data.get("sleep_debt_7d_hrs")
    stress = _safe_float(journal, "stress_avg")
    recovery = _safe_float(whoop, "recovery_score")
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
        strong_pillars = [k for k, v in component_scores.items() if v is not None and v > 65 and k not in ("consistency", "relationships")]
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
