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
from datetime import date as _date_cls
from typing import Any, Optional, Union

import boto3

# God-module split slices 2+3: pure context/scoring + domain-data builders moved
# to ai_context.py. Re-exported so callers + the coach functions keep working.
from ai_context import (  # noqa: F401
    _build_acwr_coaching_context,
    _build_cross_pillar_tradeoffs,
    _build_explorer_data,
    _build_glucose_data,
    _build_habit_outcome_context,
    _build_journey_context,
    _build_labs_data,
    _build_milestone_context,
    _build_mind_data,
    _build_nutrition_data,
    _build_physical_data,
    _build_recent_training_summary,
    _build_sleep_data,
    _build_surprise_context,
    _build_tdee_context,
    _build_training_data,
    _build_weight_context,
    _compute_data_quality,
    _compute_diminishing_returns,
    _compute_surprise_scores,
    _format_analysis,
    _format_journey_context,
    _load_insights_context,
)

# God-module split (2026-06-08): pure data-summary builders + numeric leaf utils
# moved to ai_summaries.py. Re-exported here so callers (daily_brief_lambda via
# `import ai_calls`) keep working unchanged, and so the ~90 in-module _safe_float
# references resolve.
from ai_summaries import (  # noqa: F401
    _avg,
    _safe_float,
    build_activity_summary,
    build_data_summary,
    build_food_summary,
    build_workout_summary,
)
from constants import EXPERIMENT_BASELINE_WEIGHT_LBS, EXPERIMENT_START_DATE  # ADR-058

# AI-3 middleware: lazy import of output validator (transparent fail-safe)
try:
    from ai_output_validator import AIOutputType, validate_ai_output as _validate_ai_output

    _AI_VALIDATOR_AVAILABLE = True
except ImportError:
    _validate_ai_output = None
    AIOutputType = None  # type: ignore[misc]
    _AI_VALIDATOR_AVAILABLE = False

# AI model constants — read from env so model can be updated without redeployment
AI_MODEL = os.environ.get("AI_MODEL", "claude-sonnet-4-6")
AI_MODEL_HAIKU = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")

# CloudWatch client for token usage + failure metrics (P1.8/P1.9)
_cw = boto3.client("cloudwatch", region_name=os.environ.get("AWS_REGION", "us-west-2"))
_LAMBDA_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "unknown")
_CW_NAMESPACE = "LifePlatform/AI"

# Exponential backoff delays (seconds) between retry attempts
_BACKOFF_DELAYS = [5, 15, 45]  # attempts 1→2, 2→3, 3→4


def _emit_failure_metric():
    """Emit API failure metric to CloudWatch (P1.8)."""
    try:
        _cw.put_metric_data(
            Namespace=_CW_NAMESPACE,
            MetricData=[
                {
                    "MetricName": "AnthropicAPIFailure",
                    "Dimensions": [{"Name": "LambdaFunction", "Value": _LAMBDA_NAME}],
                    "Value": 1,
                    "Unit": "Count",
                }
            ],
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


def init(s3_client: Any, bucket: str, has_board_loader: bool, board_loader_module: Any = None) -> None:
    """Inject shared dependencies. Call once at Lambda startup."""
    global _s3, _S3_BUCKET, _HAS_BOARD_LOADER, _board_loader
    _s3 = s3_client
    _S3_BUCKET = bucket
    _HAS_BOARD_LOADER = has_board_loader
    _board_loader = board_loader_module


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
    comp_str = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in component_scores.items() if v is not None)

    prompt = f"""You are analyzing Matthew's health data. Output ONLY a JSON object, no preamble.

COMPONENT SCORES (0-100): {comp_str}
{insights_ctx or ''}
{habit_miss_context}

Identify the most important patterns. Then play devil's advocate on your own analysis.

Output this exact JSON structure:
{{"key_patterns": ["specific data observation 1", "specific data observation 2"], "likely_connection": "habit/metric X correlates with metric Y result — note this is a pattern, not proven causation", "challenge": "One reason this analysis might be wrong or misleading — e.g. confounding factor, insufficient data, correlation ≠ causation, or the obvious insight hiding a subtler one", "priority": "single most important coaching focus for today", "tone": "celebrate|challenge|support"}}"""

    try:
        # 2026-05-03: bumped 200 → 600. IC-3 JSON has 5 fields (key_patterns
        # array + likely_connection + challenge + priority + tone). 200 was
        # truncating mid-string ("Unterminated string starting at... char 670"
        # in daily-brief logs). 600 gives ample headroom.
        raw = call_anthropic(prompt, api_key, max_tokens=600, model=AI_MODEL_HAIKU)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        return json.loads(raw.strip())
    except Exception as e:
        print("[WARN] IC-3 analysis pass failed: " + str(e))
        return None


# ==============================================================================
# DATA SUMMARY BUILDERS (used by AI prompt construction)
# ==============================================================================


# ==============================================================================
# ANTHROPIC API
# ==============================================================================


def daily_brief_shared_system(
    data: dict[str, Any],
    profile: dict[str, Any],
    day_grade: Optional[int] = None,
    grade: Optional[str] = None,
) -> str:
    """Phase 3.8 (2026-05-16): build a stable system block reused across the 4
    daily-brief AI calls (BoD, training+nutrition, journal, TL;DR).

    NOTE (D-01, 2026-06-05): prompt caching is intentionally DISABLED on the 4
    daily-brief calls (cache_system=False). Bedrock cross-region inference routes
    each call to a region-local cache, so a once/day brief never gets a cache HIT
    — measured 0 reads / 10K writes per 14d, i.e. pure write-premium waste. Do NOT
    re-enable caching here without re-measuring CacheRead>0. (The high-frequency
    coach-narrative-orchestrator path DOES hit, and keeps caching on.) This shared
    block is still built once and reused across the 4 calls for consistency.
    """
    jctx = _build_journey_context(profile, (data or {}).get("date") if data else None)
    journey_block = _format_journey_context(jctx)
    parts = [
        "You are coaching Matthew, a real person on a multi-year health transformation journey.",
        "",
        "## Profile snapshot (stable across this brief)",
        f"- Journey: {journey_block}",
        f"- Calorie target: {profile.get('calorie_target', '?')} kcal",
        f"- Protein target: {profile.get('protein_target_g', '?')} g",
        f"- Goals: {', '.join(profile.get('active_goals', [])) or 'unspecified'}",
    ]
    if day_grade is not None and grade is not None:
        parts.append(f"- Today's day-grade: {grade} (score {day_grade:.0f}/100)")
    # #506: one-line journal-signals block — the subjective layer every coach sees.
    # Built only from enriched aggregates already computed (extract_journal_signals);
    # honest-when-sparse: no entries → no line, never a padded placeholder.
    js = (data or {}).get("journal_signals") or {}
    js_bits = []
    if js.get("mood_avg") is not None:
        js_bits.append(f"mood {js['mood_avg']}/10")
    if js.get("energy_avg") is not None:
        js_bits.append(f"energy {js['energy_avg']}/10")
    if js.get("stress_avg") is not None:
        js_bits.append(f"stress {js['stress_avg']}/10")
    if js.get("themes"):
        js_bits.append("themes: " + ", ".join(str(t) for t in js["themes"][:3]))
    if js_bits:
        parts.append(f"- Journal signals (recent entries): {'; '.join(js_bits)}")
    parts.extend(
        [
            "",
            "## Voice + rules common to all coaching",
            "- Reference real data shown in user message. Don't invent numbers.",
            "- Concrete > abstract. Action > theory.",
            "- If a metric is missing from the user message, say so — don't extrapolate.",
            "- Coaching is direct and warm; never preachy.",
            "- Stage-appropriate: Matthew is mid-journey, not a beginner.",
            "- **Opening-line rule (do not violate)**: Never begin your response"
            " with the name 'Matthew' or any greeting/salutation. Open with the"
            " *substance* — a number, an observation, a verdict."
            " The ai_output_validator flags 'Output starts with Matthew' as a"
            " quality warning; the training coach has been violating this"
            " consistently. Correct openings start with data: 'HRV at 47ms tells"
            " me…', 'Sleep dropped to 5.8 hours…', 'Two missed sessions this"
            " week…'. Incorrect: 'Matthew, your HRV…', 'Matthew — sleep dropped…'."
            " Treat this as a hard constraint, not a stylistic preference.",
            "",
            "Coach-specific instructions follow in each user message.",
        ]
    )
    return "\n".join(parts)


def _build_system_block(system, cache_system):
    """Convert system prompt to cached content block format if caching enabled."""
    if not system:
        return None
    if isinstance(system, list):
        return system  # already structured
    if cache_system:
        return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    return system


def call_anthropic(
    prompt: str,
    api_key: str = "",  # ADR-062: ignored — Bedrock uses IAM auth. Kept default for compat.
    max_tokens: int = 200,
    system: Union[str, list[dict[str, Any]], None] = None,
    output_type: Any = None,
    health_context: Optional[dict[str, Any]] = None,
    model: Optional[str] = None,
    cache_system: bool = True,
) -> str:
    """Call Anthropic API with exponential backoff (4 attempts: 5s/15s/45s delays).

    P1.8: Exponential backoff replaces fixed 2-attempt/5s retry.
    P1.9: Token usage emitted to CloudWatch LifePlatform/AI namespace.
    COST-OPT: Prompt caching — 90% discount on cached system message tokens.
    AI-3 middleware: validates output when output_type is specified (transparent fail-safe).
    R17-16: Graceful degradation — returns "[AI_UNAVAILABLE]" after all retries exhausted
            instead of raising. Callers should check for AI_UNAVAILABLE.

    Args:
        model:          Model ID override — defaults to AI_MODEL env var.
        cache_system:   Enable prompt caching on system message (default True).
        output_type:    AIOutputType enum value — enables AI-3 output validation.
                        Pass None (default) to skip — used for JSON callers and IC passes.
        health_context: Dict of health metrics for context-aware validation checks
                        (e.g. {"recovery_score": 45, "tsb": -12}).
    Returns text string, or "[AI_UNAVAILABLE]" if Anthropic is unavailable after all retries.
    """
    body = {
        "model": model or AI_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    sys_block = _build_system_block(system, cache_system)
    if sys_block:
        body["system"] = sys_block

    # ADR-062 (2026-05-27): migrated from direct Anthropic API (urllib POST to
    # api.anthropic.com) to AWS Bedrock invoke_model. Auth is IAM (api_key
    # param now ignored — kept for signature compatibility). Prompt caching
    # preserved via cache_control blocks in sys_block. Response shape is
    # identical to the direct API, so parsing/validation below is unchanged.
    import botocore.exceptions as _bce
    from bedrock_client import invoke as _bedrock_invoke

    max_attempts = len(_BACKOFF_DELAYS) + 1  # 4
    for attempt in range(1, max_attempts + 1):
        try:
            resp = _bedrock_invoke(body, model_name=body["model"])
            # Token usage + estimated spend are now metered centrally at the
            # bedrock_client.invoke() chokepoint (G1) — no per-caller emit here.
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
        except _bce.ClientError as e:
            code = e.response.get("Error", {}).get("Code", "Unknown")
            # Retryable Bedrock errors: throttling + transient service issues.
            retryable = code in (
                "ThrottlingException",
                "ModelTimeoutException",
                "ServiceUnavailableException",
                "InternalServerException",
                "ModelNotReadyException",
            )
            print(f"[WARN] Bedrock {code} attempt {attempt}/{max_attempts}")
            if retryable and attempt < max_attempts:
                delay = _BACKOFF_DELAYS[attempt - 1]
                print(f"[INFO] Retrying in {delay}s...")
                time.sleep(delay)
            else:
                _emit_failure_metric()
                # R17-16: graceful degradation — return sentinel so callers know AI
                # failed (not just empty output). Callers check for AI_UNAVAILABLE.
                print(f"[ERROR] Bedrock unavailable after {max_attempts} attempts ({code}).")
                return "[AI_UNAVAILABLE]"
        except Exception as e:
            print(f"[WARN] Bedrock error attempt {attempt}/{max_attempts}: {e}")
            if attempt < max_attempts:
                delay = _BACKOFF_DELAYS[attempt - 1]
                print(f"[INFO] Retrying in {delay}s...")
                time.sleep(delay)
            else:
                _emit_failure_metric()
                print(f"[ERROR] Bedrock unreachable after {max_attempts} attempts: {e}.")
                return "[AI_UNAVAILABLE]"


# ==============================================================================
# AI PROMPT HELPERS
# ==============================================================================


# ==============================================================================
# IC-28: ACWR TRAINING LOAD COACHING CONTEXT
# Reads ACWR fields from computed_metrics (already written by acwr-compute before
# the Daily Brief runs). Provides prescriptive training guidance to the coach prompt.
# ==============================================================================


# ==============================================================================
# AI CALLS
# ==============================================================================


def call_training_nutrition_coach(
    data: dict[str, Any], profile: dict[str, Any], api_key: str = "", shared_system: Optional[str] = None
) -> str:
    """AI call: Training coach + Nutritionist combined. (P2+P3+P5 aware)
    Phase 3.8: optional shared_system reused across 4 daily-brief calls (cached)."""
    data_summary = build_data_summary(data, profile)
    food_summary = build_food_summary(data)
    activity_summary = build_activity_summary(data)
    workout_summary = build_workout_summary(data)
    _build_weight_context(data, profile)
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
- Nutrition is logged at END OF DAY (a manual upload), so "yesterday" IS the latest complete day and the live nutrition state. NEVER frame an absent current-day log as a failure, a missed day, or "hasn't logged today" — that's the pipeline being a day behind by design, not the person.
- Reference TDEE context above to reason about deficit size.
- If intake is >25% below target, flag possible logging gap before assuming great adherence.
- Comment on macro adherence AND meal timing/distribution. When was protein consumed? Any long gaps?
- Be specific about what to adjust TODAY. Reference actual food items from the log.

Respond in EXACTLY this JSON format, no other text:
{{"training": "2-4 sentences from sports scientist. Per-activity analysis. Walks evaluated as primary sessions at Week {jctx['week_num']}. Reference specific metrics.", "nutrition": "2-3 sentences from nutritionist about macro adherence + meal timing + deficit context. Reference specific foods and timestamps. What to adjust today."}}"""

    try:
        raw = call_anthropic(prompt, api_key, max_tokens=500, system=shared_system, cache_system=False)
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


def call_journal_coach(data: dict[str, Any], profile: dict[str, Any], api_key: str = "", shared_system: Optional[str] = None) -> str:
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

    # Phase 2A: Journal enrichment context
    j_signals = data.get("journal_signals") or {}
    _defense_ctx = ""
    if j_signals.get("defense_patterns"):
        _defense_ctx = f"\nDEFENSE PATTERNS DETECTED: {', '.join(j_signals['defense_patterns'])}. Challenge one gently."
    if j_signals.get("growth_signals"):
        _defense_ctx += f"\nGROWTH SIGNALS: {', '.join(j_signals['growth_signals'])}. Acknowledge these."
    if j_signals.get("avoidance_flags"):
        _defense_ctx += f"\nAVOIDANCE FLAGS: {', '.join(j_signals['avoidance_flags'])}. Name what's being avoided."
    if j_signals.get("stress_sources"):
        _defense_ctx += f"\nSTRESS SOURCES: {', '.join(j_signals['stress_sources'])}."

    prompt = f"""You are a wise, warm-but-direct inner coach reading Matthew's journal from yesterday.
He's 36, {jctx['stage_label']} of transformation ({weight_ctx}), battling: {obstacles_str}.
His coaching tone: Jocko's discipline meets Attia's precision meets Brene Brown's vulnerability.
{_defense_ctx}

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
        return call_anthropic(
            prompt,
            api_key,
            max_tokens=250,
            system=shared_system,
            cache_system=False,
            output_type=AIOutputType.JOURNAL_COACH if _AI_VALIDATOR_AVAILABLE else None,
        )
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

    weight_ctx = _build_weight_context(data, profile) if data and profile else f"{int(round(EXPERIMENT_BASELINE_WEIGHT_LBS))}->185 lbs"
    intro = f"""You are the Board of Directors for Project40 — {panel_desc} — unified.
Speaking to Matthew, 36yo, weight loss journey ({weight_ctx}). Phase 1 Ignition: 3 lbs/week, 1500 kcal deficit, 1800 cal daily.
Tone: direct, empathetic, no-BS.{protocol_note}"""

    print("[INFO] Using config-driven daily BoD prompt")
    return intro


def call_board_of_directors(
    data, profile, day_grade, grade, component_scores, api_key="", character_sheet=None, brief_mode="standard", shared_system=None
):
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
            character_ctx += (
                "\n  "
                + (pn or "").capitalize()
                + ": Level "
                + str(pd.get("level", "?"))
                + " ("
                + str(pd.get("tier", "?"))
                + ") raw="
                + str(pd.get("raw_score", "?"))
            )
        if cs_events:
            character_ctx += "\nLEVEL EVENTS TODAY:"
            for ev in cs_events:
                ev_type = ev.get("type", "")
                if "tier" in ev_type:
                    character_ctx += (
                        "\n  "
                        + (ev.get("pillar") or "").capitalize()
                        + ": "
                        + str(ev.get("old_tier", ""))
                        + " → "
                        + str(ev.get("new_tier", ""))
                    )
                elif "character" in ev_type:
                    character_ctx += "\n  Character Level " + str(ev.get("old_level", "")) + " → " + str(ev.get("new_level", ""))
                else:
                    arrow = "↑" if "up" in ev_type else "↓"
                    character_ctx += (
                        "\n  "
                        + arrow
                        + " "
                        + (ev.get("pillar") or "").capitalize()
                        + " Level "
                        + str(ev.get("old_level", ""))
                        + " → "
                        + str(ev.get("new_level", ""))
                    )
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
        bod_intro = (
            "You are the Board of Directors for Project40 — sports scientist + nutritionist + sleep specialist + behavioral coach unified.\n"
            f"Speaking to Matthew, 36yo, weight loss journey ({weight_ctx}). Phase 1 Ignition: 3 lbs/week, 1500 kcal deficit, 1800 cal daily.\n"
            "Tone: direct, empathetic, no-BS."
        )

    prompt = (
        bod_intro
        + f"""

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
    )

    if brief_mode == "flourishing":
        prompt += "\n\nTONE: He is FLOURISHING — engagement is high, habits strong, trajectory improving. Lead with reinforcement. Be energising. Name what's working specifically. One brief forward-looking note."
    elif brief_mode == "struggling":
        prompt += "\n\nTONE: He is in a ROUGH PATCH — engagement is low, habits slipping. Be warm, not clinical. Acknowledge the difficulty without piling on. Focus on the smallest possible next right action. No guilt."

    _hctx = {
        "recovery_score": _safe_float(data.get("whoop"), "recovery_score") if data else None,
        "tsb": data.get("tsb") if data else None,
        "sleep_score": _safe_float((data.get("sleep") or {}), "sleep_score") if data else None,
    }
    return call_anthropic(
        prompt,
        api_key,
        max_tokens=200,
        system=shared_system,
        cache_system=False,
        output_type=AIOutputType.BOD_COACHING if _AI_VALIDATOR_AVAILABLE else None,
        health_context=_hctx,
    )


def call_tldr_and_guidance(
    data, profile, day_grade, grade, component_scores, component_details, readiness_score, readiness_colour, api_key, shared_system=None
):
    """v2.3: Combined TL;DR + Smart Guidance — one AI call that returns both. (P2+P4+P5 aware)
    Phase 3.8: shared_system passed for cross-call prompt caching."""
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

    _build_weight_context(data, profile)

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
        component_scores, ("MISSED HABITS: " + ", ".join(missed_mvp)) if missed_mvp else "", insights_ctx, api_key
    )
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

    # Phase 2B: Character sheet tone adaptation
    _cs = data.get("character_sheet") or {}
    _tone_ctx = ""
    if _cs:
        _consc = _cs.get("conscientiousness_score")
        _resil = _cs.get("resilience_score")
        _growth = _cs.get("growth_mindset_score")
        if any(v is not None for v in [_consc, _resil, _growth]):
            _tone_parts = []
            if _consc and float(_consc) > 80:
                _tone_parts.append("User responds well to structured, specific guidance")
            if _resil and float(_resil) < 50:
                _tone_parts.append("Resilience is low — use supportive tone, avoid shame-framing")
            if _growth and float(_growth) > 70:
                _tone_parts.append("Growth mindset is strong — frame challenges as opportunities")
            if _tone_parts:
                _tone_ctx = "\nTONE ADAPTATION: " + ". ".join(_tone_parts) + "."

    # Phase 2C: Adaptive mode → email tone
    _adaptive = data.get("adaptive_mode") or {}
    _mode = _adaptive.get("brief_mode") or _adaptive.get("engagement_mode") or ""
    _mode_ctx = ""
    if _mode == "flourishing":
        _mode_ctx = "\nENGAGEMENT MODE: Flourishing — push harder, suggest experiments, confident tone."
    elif _mode == "struggling":
        _mode_ctx = "\nENGAGEMENT MODE: Struggling — warm tone, max 2 guidance items, lead with validation not correction."

    # Phase 2D: State of Mind emotional context
    _som_ctx = ""
    _som = data.get("state_of_mind") or {}
    if _som:
        _valence = _som.get("som_avg_valence") or _som.get("avg_valence")
        if _valence is not None and float(_valence) < -0.3:
            _som_ctx = "\nEMOTIONAL STATE: Low mood detected. Prioritize nervous system reset over performance push."
        _assoc = _som.get("som_top_associations")
        if _assoc and isinstance(_assoc, list):
            _som_ctx += f"\nPrimary stressor context: {', '.join(_assoc[:2])}."

    # Phase 2E: Supplements context
    _supp_ctx = ""
    _supps = data.get("supplements_recent") or []
    if _supps:
        _supp_names = list(set(s.get("name", "") for s in _supps if s.get("name")))[:6]
        if _supp_names:
            _supp_ctx = f"\nACTIVE SUPPLEMENTS: {', '.join(_supp_names)}. Account for these in nutrient adequacy."

    # Phase 2F: Weather context
    _weather_ctx = ""
    _wx = data.get("weather") or {}
    if _wx:
        _dl = _wx.get("daylight_hours")
        _press = _wx.get("pressure_hpa")
        _temp = _wx.get("temp_high_f")
        if _dl and float(_dl) < 10:
            _weather_ctx += f"\nWEATHER: Short daylight ({_dl}h) — consider morning light exposure."
        if _press and float(_press) < 1005:
            _weather_ctx += f"\nWEATHER: Low barometric pressure ({_press} hPa) — expect lower energy."
        if _temp and float(_temp) > 85:
            _weather_ctx += f"\nWEATHER: High heat ({_temp}°F) — increase hydration, modify outdoor intensity."

    # Phase 4: Labs + genome context
    _labs_ctx = data.get("labs_coaching_ctx", "")
    _genome_ctx = data.get("genome_coaching_ctx", "")

    prompt = f"""You are the intelligence engine behind Matthew's Life Platform daily brief.
Your job: synthesize ALL of yesterday's data into (1) one TL;DR sentence and (2) 3-4 smart, personalized guidance items for TODAY.
{_tone_ctx}{_mode_ctx}{_som_ctx}{_supp_ctx}{_weather_ctx}
{_labs_ctx}
{_genome_ctx}

{journey_block}

{tdee_ctx}

YESTERDAY'S SIGNALS:
- Day grade: {day_grade}/100 ({grade})
- Components: {", ".join(comp_lines)}
- Recovery/readiness: {readiness_score} ({readiness_colour})
- HRV: {data_summary.get("hrv_yesterday")}ms yesterday, 7d avg {data_summary.get("hrv_7d_avg")}ms, 30d avg {data_summary.get("hrv_30d_avg")}ms
- TSB (training stress balance): {data_summary.get("tsb")}{data_summary.get("tsb_basis_note") or ""}
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
        "tsb": data_summary.get("tsb"),
        "sleep_score": data_summary.get("sleep_score"),
    }
    try:
        raw = call_anthropic(
            prompt,
            api_key,
            max_tokens=450,
            system=shared_system,
            cache_system=False,
            output_type=AIOutputType.GUIDANCE if _AI_VALIDATOR_AVAILABLE else None,
            health_context=_hctx,
        )
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


# ==============================================================================
# COACH INTELLIGENCE PIPELINE — Generic + Per-Coach (Phase 2C / Phase 3)
# Runs computation engine → narrative orchestrator → voice-spec-driven generation
# → state updater. Falls back to legacy generation on failure.
# ==============================================================================

# Cache computation results within a single daily brief run to avoid
# invoking the computation engine Lambda multiple times.
_comp_results_cache = None

# N-06 (#390): bounded retry cap for the quality-gate regenerate-or-hold loop.
# One corrective rewrite, then hold — mirrors the established regen_once
# ("one corrective rewrite, kept only if strictly better") convention used by
# the grounding gate (ADR-104) elsewhere in this same pipeline.
_QUALITY_GATE_MAX_REGENERATIONS = 1


def _invoke_quality_gate_sync(lambda_client, coach_id, output_text, generation_brief):
    """Synchronous (RequestResponse) call to coach-quality-gate.

    N-06 (#390): promoted from the prior fire-and-forget `InvocationType="Event"`
    call (whose report was discarded — nothing ever acted on it) so the pipeline
    can actually enforce the verdict. Fails OPEN on any infra error (invoke
    exception, timeout, malformed payload) — an unreachable gate must never
    block a draft; it only blocks on an actual sub-threshold verdict from a
    gate that responded. This mirrors coach_quality_gate.py's own internal
    fail-open contract (`_build_fallback_report`) for LLM-side failures.
    """
    try:
        resp = lambda_client.invoke(
            FunctionName="coach-quality-gate",
            InvocationType="RequestResponse",
            Payload=json.dumps(
                {
                    "coach_id": coach_id,
                    "output_text": output_text,
                    "generation_brief": generation_brief if isinstance(generation_brief, dict) else None,
                    "generation_date": _date_cls.today().isoformat(),
                }
            ).encode(),
        )
        payload = json.loads(resp["Payload"].read())
        if not isinstance(payload, dict):
            raise ValueError(f"non-dict quality gate payload: {type(payload)}")
        payload.setdefault("passed", True)
        return payload
    except Exception as e:
        print(f"[COACH-QUALITY-GATE:{coach_id}] sync invoke failed (fail-open, not blocking): {e}")
        return {"passed": True, "score": None, "suggestions": [], "_fail_open": True}


def _quality_gate_correction_note(report):
    """Build a corrective-rewrite note from a failing quality gate report.

    Pure function (no I/O) so the regenerate-or-hold loop is unit-testable
    without a live Bedrock/Lambda call. Mirrors the directness of
    grounded_generation.correction_prompt.
    """
    lines = ["QUALITY GATE FEEDBACK — your previous draft failed review. Fix these specific issues:"]
    for v in report.get("anti_pattern_violations") or []:
        phrase = v.get("phrase") if isinstance(v, dict) else v
        if phrase:
            lines.append(f'  - Remove/avoid the forbidden phrase: "{phrase}"')
    for v in report.get("decision_class_violations") or []:
        if isinstance(v, dict):
            lines.append(
                f"  - You exceeded the evidence ceiling (expected max: {v.get('expected_max', 'observational')}); "
                f"offending text: \"{v.get('excerpt', '')}\""
            )
    for flag in report.get("cross_coach_similarity_flags") or []:
        if isinstance(flag, dict):
            lines.append(f"  - Too similar to {flag.get('similar_to', 'another coach')}: {flag.get('reason', '')}")
    for s in report.get("suggestions") or []:
        if s:
            lines.append(f"  - {s}")
    if len(lines) == 1:
        lines.append("  - Write a more distinctive, on-voice draft that matches your persona.")
    lines.append("Rewrite the full response addressing all of the above. Do not mention this feedback in the output.")
    return "\n".join(lines)


def _enforce_quality_gate(
    lambda_client, coach_id, output_text, generation_brief, regenerate_fn, max_regenerations=_QUALITY_GATE_MAX_REGENERATIONS
):
    """N-06 (#390): the coach quality gate, promoted from advisory to blocking.

    Regenerate-or-hold: a sub-threshold draft is retried through `regenerate_fn`
    (the caller's own generation call, given a corrective note) up to
    `max_regenerations` times. Only a passing draft is returned. If the cap is
    hit with no passing draft, returns (None, report) — the caller's existing
    "None = hold, don't publish this cycle" contract (see
    `_run_coach_v2_pipeline`'s early-return failure paths) keeps a
    known-failing narrative off the site/brief instead of auto-publishing it
    with a note.

    Never fails open on an actual sub-threshold verdict from a gate that
    responded — only on gate infra errors (see `_invoke_quality_gate_sync`).
    """
    report = _invoke_quality_gate_sync(lambda_client, coach_id, output_text, generation_brief)
    attempts = 0
    while not report.get("passed", True) and attempts < max_regenerations:
        attempts += 1
        note = _quality_gate_correction_note(report)
        try:
            regenerated = regenerate_fn(note)
        except Exception as e:
            print(f"[COACH-QUALITY-GATE:{coach_id}] regeneration attempt {attempts} failed: {e}")
            break
        if not (regenerated or "").strip():
            print(f"[COACH-QUALITY-GATE:{coach_id}] regeneration attempt {attempts} returned empty — keeping prior draft")
            break
        output_text = regenerated
        report = _invoke_quality_gate_sync(lambda_client, coach_id, output_text, generation_brief)

    if not report.get("passed", True):
        print(
            f"[COACH-QUALITY-GATE:{coach_id}] HELD after {attempts} regeneration attempt(s) — "
            f"score={report.get('score')}, not publishing this cycle (N-06)"
        )
        try:
            _cw.put_metric_data(
                Namespace=_CW_NAMESPACE,
                MetricData=[
                    {
                        "MetricName": "CoachQualityGateHeld",
                        "Dimensions": [{"Name": "CoachID", "Value": coach_id}],
                        "Value": 1,
                        "Unit": "Count",
                    }
                ],
            )
        except Exception as e:
            print(f"[COACH-QUALITY-GATE:{coach_id}] CloudWatch held-metric emit failed (non-fatal): {e}")
        return None, report

    return output_text, report


def _run_coach_v2_pipeline(coach_id, domain_data, domain_label, data, api_key):
    """
    Generic Coach Intelligence pipeline for any coach.

    Returns generated text on success, None on failure (caller falls back to legacy).
    """
    global _comp_results_cache

    try:
        lambda_client = boto3.client("lambda", region_name="us-west-2")
        s3 = boto3.client("s3", region_name="us-west-2")

        # Step 1: Computation engine (cached per daily brief cycle)
        if _comp_results_cache is None:
            print(f"[COACH-V2:{coach_id}] Step 1: Invoking computation engine...")
            try:
                comp_resp = lambda_client.invoke(
                    FunctionName="coach-computation-engine",
                    InvocationType="RequestResponse",
                    Payload=json.dumps({"source": "daily_brief"}).encode(),
                )
                comp_payload = json.loads(comp_resp["Payload"].read())
                comp_body = comp_payload.get("body")
                _comp_results_cache = json.loads(comp_body) if isinstance(comp_body, str) else (comp_body or comp_payload)
                print(f"[COACH-V2:{coach_id}] Computation engine returned {len(str(_comp_results_cache))} chars")
            except Exception as e:
                print(f"[COACH-V2:{coach_id}] Computation engine failed: {e} — using empty results")
                _comp_results_cache = {}
        comp_results = _comp_results_cache

        # Step 2: Narrative orchestrator
        print(f"[COACH-V2:{coach_id}] Step 2: Invoking narrative orchestrator...")
        try:
            orch_resp = lambda_client.invoke(
                FunctionName="coach-narrative-orchestrator",
                InvocationType="RequestResponse",
                Payload=json.dumps(
                    {
                        "coach_id": coach_id,
                        "computation_results": comp_results,
                    }
                ).encode(),
            )
            orch_payload = json.loads(orch_resp["Payload"].read())
            orch_body = orch_payload.get("body")
            generation_brief = json.loads(orch_body) if isinstance(orch_body, str) else (orch_body or orch_payload)
            print(f"[COACH-V2:{coach_id}] Orchestrator returned brief: {len(str(generation_brief))} chars")
        except Exception as e:
            print(f"[COACH-V2:{coach_id}] Orchestrator failed: {e} — falling back to legacy")
            return None

        # Step 3: Load voice spec from S3
        try:
            vs_resp = s3.get_object(Bucket="matthew-life-platform", Key=f"config/coaches/{coach_id}.json")
            voice_spec = json.loads(vs_resp["Body"].read())
        except Exception as e:
            print(f"[COACH-V2:{coach_id}] Voice spec load failed: {e} — falling back to legacy")
            return None

        # Step 4: Build prompt
        few_shots = voice_spec.get("few_shot_examples", [])
        few_shot_block = ""
        if few_shots:
            few_shot_block = "\n\nVOICE CALIBRATION EXAMPLES (write in this style):\n"
            for i, ex in enumerate(few_shots, 1):
                few_shot_block += f"\nExample {i}:\n{ex}\n"

        voice_rules = voice_spec.get("structural_voice_rules", {})
        decision_style = voice_spec.get("decision_style", {})
        anti_patterns = voice_spec.get("anti_pattern_detection", {})
        brief = generation_brief.get("generation_brief", generation_brief)
        voice_guidance = brief.get("voice_guidance", {})

        # ADR-104: canonical facts — this render previously injected only the
        # hard-coded goals, so coaches had no authoritative vitals to cite and
        # nothing gated what they invented. Fail-soft: without the helpers the
        # render works exactly as before (no facts block, no gate).
        _gg_mod = None
        _canon_facts = {}
        _facts_block = ""
        try:
            import grounded_generation as _gg_mod  # bundled + layer (ADR-104)
            from boto3.dynamodb.conditions import Key as _Key
            from canonical_facts import build_canonical_facts as _bcf

            _tbl = boto3.resource("dynamodb", region_name="us-west-2").Table(os.environ.get("TABLE_NAME", "life-platform"))
            _cm = _tbl.query(
                KeyConditionExpression=_Key("pk").eq("USER#matthew#SOURCE#computed_metrics"),
                ScanIndexForward=False,
                Limit=1,
            ).get("Items", [])
            if _cm:
                _canon_facts = {k: v for k, v in _bcf(_cm[0]).items() if k != "as_of"}
                _facts_block = _gg_mod.authoritative_facts_block(_canon_facts)

            # #541: today's model expectations ride the same authoritative block, so
            # the numbers land in the prompt → automatically in the ADR-104 allow-list.
            # Fail-soft: no forecast summary, no block.
            _fx = _tbl.query(
                KeyConditionExpression=_Key("pk").eq("USER#matthew#SOURCE#forecast") & _Key("sk").begins_with("DATE#"),
                ScanIndexForward=False,
                Limit=1,
            ).get("Items", [])
            _fx_lines = []
            if _fx:
                from decimal import Decimal as _Dec

                def _fnum(v):
                    return float(v) if isinstance(v, (_Dec, int, float)) else None

                for _f in _fx[0].get("forecasts", []):
                    _p, _lo, _hi = _fnum(_f.get("point")), _fnum(_f.get("lo")), _fnum(_f.get("hi"))
                    if _p is None or _lo is None or _hi is None:
                        continue
                    _fx_lines.append(
                        f"  - {_f.get('metric', '?')} {_f.get('frame', '')}: the model expects {_p:g}{_f.get('unit', '')} "
                        f"(80% interval {_lo:g}-{_hi:g})"
                    )
                _cov = _fx[0].get("coverage") or {}
                if _cov.get("n_resolved") and _fnum(_cov.get("coverage_pct")) is not None:
                    _fx_lines.append(
                        f"  - Track record: the 80% interval covered {_fnum(_cov.get('coverage_pct')):g}% of "
                        f"{int(_cov['n_resolved'])} graded forecasts so far"
                    )
            if _fx_lines:
                _facts_block += (
                    "\nMODEL EXPECTATIONS (deterministic forecast from Matthew's own recent data — "
                    "an expectation from observed patterns, NEVER a causal claim or a promise; frame as "
                    "'the model expects'):\n" + "\n".join(_fx_lines)
                )
        except Exception as _gf_e:
            print(f"[COACH-V2:{coach_id}] canonical facts unavailable (non-blocking): {_gf_e}")

        system_prompt = f"""You are {voice_spec['display_name']}, {voice_spec.get('domain', '')} specialist.

VOICE RULES:
- Sentence rhythm: {voice_rules.get('sentence_rhythm', '')}
- Uncertainty style: {voice_rules.get('uncertainty_style', '')}
- Analogy domain: {voice_rules.get('analogy_domain', '')}
- Paragraph structure: {voice_rules.get('paragraph_structure', '')}
- Humor style: {voice_rules.get('humor_style', '')}
- Relationship to other coaches: {voice_rules.get('relationship_to_others', '')}

DECISION STYLE:
- Evidence threshold: {decision_style.get('default_evidence_threshold', 'moderate')}
- Bold claims: {decision_style.get('comfort_with_bold_claims', 'low')}
- Revision style: {decision_style.get('revision_style', 'transparent')}

FORBIDDEN PHRASES: {json.dumps(anti_patterns.get('phrase_blacklist', []))}
FORBIDDEN STRUCTURES: {json.dumps(anti_patterns.get('structural_blacklist', []))}

OPENING GUIDANCE: {voice_guidance.get('suggested_opening', 'vary your opening')}
AVOID OPENINGS: {json.dumps(voice_guidance.get('avoid_openings', []))}
{voice_guidance.get('structural_note', '')}

DECISION CLASS CEILING: {brief.get('decision_class_ceiling', 'observational')}
EVIDENCE NOTE: {brief.get('evidence_note', 'Early data — use preliminary framing.')}

VOICE: Write in FIRST PERSON. You ARE {voice_spec['display_name']}. Say "I" not "Dr. [Name]". Address Matthew directly as "you". Never refer to yourself in third person.

MATTHEW'S GOALS (standing targets — the fixed backdrop, not your read):
- Target weight: 185 lbs (starting {int(round(EXPERIMENT_BASELINE_WEIGHT_LBS))})
- Body composition: reduce body fat, preserve lean mass
- Training philosophy: building from walking + Zone 2 base; structured strength training planned but not yet started
- Timeline: 12-month experiment, genesis {EXPERIMENT_START_DATE}
- Key priorities: sleep quality, protein adherence (190g/day target), consistent movement (8,000+ steps/day)

{_facts_block}

YOUR CURRENT STANCE: If the generation brief includes `current_stance`, that is YOUR own evolving, evidence-derived read of Matthew — let it LEAD your framing (what you're focused on now, what you've set aside, how your read has changed). The goals above are the standing targets; the stance is where you actually are with him today. If no stance is present (early cycles), frame against the goals.

ACTIVE PROTOCOLS: If the generation brief includes `site_protocols`, those are the challenges/experiments Matthew has actually committed to in your domain. Acknowledge the relevant ones BY NAME and give your honest read on how each is going. NEVER invent a progress, streak, day-count, or adherence number — ground any progress claim in the DATA below, or say plainly you can't see that data yet. The same N=1 and decision-class ceilings apply: an active commitment is not yet evidence it's working.

ENGAGEMENT / PRESENCE: If the generation brief includes `engagement_signal`, Matthew's own logging has gone quiet — a real gap in the data, not a data problem. A good coach NOTICES this. Acknowledge it in YOUR OWN VOICE and character — you may be concerned, curious, blunt, or gently checking in, whatever fits who you are; don't all sound the same. Rules that keep you honest:
- Ground the day-count in the real `gap_days` / `last_food_log_date` provided — e.g. "it's been four days since you logged a meal". Cite the real number, never round it up for drama.
- You do NOT know WHY he went quiet — you can't see that he was travelling, or eating out, or stressed. Do NOT invent a reason or narrate events you can't see. Name the SILENCE and, if `passive_still_flowing` is true, what the wearables DID catch (cite only the real `passive_read` values given — rough sleep, elevated RHR) — then INVITE the story ("what happened this week?"), don't assume it.
- If `planned_pause` is true, this looks like a deliberate break (`planned_pause_reason`) — frame it as a planned pause, not falling off.
- If `returned` is true, he's BACK after `resumed_after_days` days. Acknowledge the return warmly, note any real `weight_delta_over_gap_lbs` plainly (regain is data, not a verdict), and be SUPPORTIVE about re-engaging — never punitive. The point is to help him restart, not to shame the lapse.
- An absent SAME-DAY log is by-design lag (manual sources arrive end-of-day), never a gap — the signal already accounts for this, so trust `gap_days`.

DATA INTERPRETATION RULES:
- If an activity count or log is ZERO, that means Matthew hasn't done that activity — say "no training logged this week" NOT "provide your training data"
- If a data source exists but values are null for today, it means today's sync hasn't completed — use the most recent available data
- NEVER tell Matthew to "obtain" or "get" a scan/test if the data already exists in the payload below
- Garmin is the step count source of truth (wearable). Ignore Apple Health step counts if Garmin is available.
{few_shot_block}

Write 2-4 paragraphs of {domain_label} coaching for Matthew. Be specific, reference numbers, and stay within your evidence ceiling. Write in your distinctive voice — not a generic AI coach voice."""

        # Build data inventory — tell the coach what data sources are available
        _inventory_parts = []
        for _src_name, _src_val in [
            ("DEXA body composition", data.get("dexa")),
            ("Lab bloodwork", data.get("labs")),
            ("Body measurements", data.get("measurements")),
            ("MacroFactor nutrition", data.get("macrofactor")),
            ("Whoop recovery/sleep", data.get("whoop")),
            ("Garmin steps", data.get("garmin")),
            ("Strava activities", data.get("strava_7d")),
            ("Eight Sleep bed temp", data.get("eightsleep")),
            ("CGM glucose", data.get("apple_health") or data.get("apple")),
        ]:
            if _src_val and (not isinstance(_src_val, list) or len(_src_val) > 0):
                _inventory_parts.append(f"  - {_src_name}: AVAILABLE")
            else:
                _inventory_parts.append(f"  - {_src_name}: not available")
        _data_inventory = "\n".join(_inventory_parts)

        user_message = f"""GENERATION BRIEF:
{json.dumps(brief, indent=2, default=str)}

DATA SOURCES AVAILABLE:
{_data_inventory}

{domain_label.upper()} DATA:
{json.dumps(domain_data, indent=2, default=str)}

COMPUTATION OUTPUTS:
{json.dumps(comp_results.get('trends', {}), indent=2, default=str)[:2000]}

Write your {domain_label} coaching section now."""

        # Step 5: Generate with Sonnet
        print(f"[COACH-V2:{coach_id}] Generating output...")
        output = call_anthropic(system_prompt + "\n\n" + user_message, api_key, max_tokens=600)
        print(f"[COACH-V2:{coach_id}] Output: {len(output)} chars")

        # Step 5.5 (ADR-104): deterministic grounding gate — the highest-traffic
        # coach surface previously shipped with NO numeric check. Findings = hard
        # canonical contradictions (RHR/recovery/HRV) + the allow-list gate (every
        # number in the output must appear in the prompt/data/facts — kills invented
        # trend endpoints). One corrective rewrite, kept only if strictly better.
        if _gg_mod is not None and output:
            try:
                _allowed = _gg_mod.allowed_numbers(system_prompt, user_message)

                def _findings_fn(_t):
                    return _gg_mod.grounding_findings(_t, facts=_canon_facts or None, allowed=_allowed)

                _pre = _findings_fn(output)
                if _pre:
                    print(f"[COACH-V2:{coach_id}] grounding finding(s): {[f['detail'] for f in _pre][:5]}")
                output, _left, _corrected = _gg_mod.regen_once(
                    output,
                    _findings_fn,
                    lambda _corr: call_anthropic(system_prompt + "\n\n" + user_message + "\n\n" + _corr, api_key, max_tokens=600),
                )
                if _corrected:
                    print(f"[COACH-V2:{coach_id}] grounding self-corrected: {len(_pre)}→{len(_left)} finding(s)")
            except Exception as _gg_e:
                print(f"[COACH-V2:{coach_id}] grounding gate failed (non-blocking): {_gg_e}")

        # Step 6 (N-06, #390): quality gate — promoted from advisory to blocking.
        # Was fire-and-forget (InvocationType=Event, report discarded — nothing
        # ever acted on a fail). The 2026-06-05→07-04 CloudWatch re-eval (30d,
        # 206 real logged verdicts) found the score threshold (60) never fires on
        # its own (observed min score 62) but the gate's own `passed` verdict
        # (anti-pattern / decision-class / voice-distinctiveness / cross-coach
        # findings) fired on 10.2% of outputs — that's the real signal. Blocking
        # is keyed off `passed`, not a re-tuned score cutoff. See ADR-107.
        # Runs BEFORE the state updater so a regenerated draft (not a discarded
        # one) is what gets recorded and published.
        output, _quality_report = _enforce_quality_gate(
            lambda_client,
            coach_id,
            output,
            generation_brief,
            regenerate_fn=lambda _note: call_anthropic(system_prompt + "\n\n" + user_message + "\n\n" + _note, api_key, max_tokens=600),
        )
        if output is None:
            print(f"[COACH-V2:{coach_id}] Held by quality gate (N-06) — no output published this cycle")
            return None

        # Step 7: Invoke state updater (async) — records the final, gate-passed text.
        try:
            lambda_client.invoke(
                FunctionName="coach-state-updater",
                InvocationType="Event",
                Payload=json.dumps(
                    {
                        "coach_id": coach_id,
                        "output_text": output,
                        "output_type": f"daily_brief_{domain_label.lower().replace(' ', '_')}",
                        "generation_date": _date_cls.today().isoformat(),
                    }
                ).encode(),
            )
        except Exception as e:
            print(f"[COACH-V2:{coach_id}] State updater invoke failed (non-blocking): {e}")

        return output

    except Exception as e:
        print(f"[COACH-V2:{coach_id}] Pipeline failed: {e} — returning None for legacy fallback")
        return None


def call_sleep_coach_v2(data: dict[str, Any], profile: dict[str, Any], api_key: str = "") -> str:
    """Run Coach Intelligence pipeline for sleep coach. Returns text or None."""
    return _run_coach_v2_pipeline("sleep_coach", _build_sleep_data(data), "sleep", data, api_key)


def call_nutrition_coach_v2(data: dict[str, Any], profile: dict[str, Any], api_key: str = "") -> str:
    """Run Coach Intelligence pipeline for nutrition coach. Returns text or None."""
    return _run_coach_v2_pipeline("nutrition_coach", _build_nutrition_data(data), "nutrition", data, api_key)


def call_training_coach_v2(data: dict[str, Any], profile: dict[str, Any], api_key: str = "") -> str:
    """Run Coach Intelligence pipeline for training coach. Returns text or None."""
    return _run_coach_v2_pipeline("training_coach", _build_training_data(data), "training", data, api_key)


def call_mind_coach_v2(data: dict[str, Any], profile: dict[str, Any], api_key: str = "") -> str:
    """Run Coach Intelligence pipeline for mind coach. Returns text or None."""
    return _run_coach_v2_pipeline("mind_coach", _build_mind_data(data), "mind", data, api_key)


def call_physical_coach_v2(data: dict[str, Any], profile: dict[str, Any], api_key: str = "") -> str:
    """Run Coach Intelligence pipeline for physical coach. Returns text or None."""
    return _run_coach_v2_pipeline("physical_coach", _build_physical_data(data), "physical", data, api_key)


def call_glucose_coach_v2(data: dict[str, Any], profile: dict[str, Any], api_key: str = "") -> str:
    """Run Coach Intelligence pipeline for glucose coach. Returns text or None."""
    return _run_coach_v2_pipeline("glucose_coach", _build_glucose_data(data), "glucose", data, api_key)


def call_labs_coach_v2(data: dict[str, Any], profile: dict[str, Any], api_key: str = "") -> str:
    """Run Coach Intelligence pipeline for labs coach. Returns text or None."""
    return _run_coach_v2_pipeline("labs_coach", _build_labs_data(data), "labs", data, api_key)


def call_explorer_coach_v2(data: dict[str, Any], profile: dict[str, Any], api_key: str = "") -> str:
    """Run Coach Intelligence pipeline for explorer coach. Returns text or None."""
    return _run_coach_v2_pipeline("explorer_coach", _build_explorer_data(data), "cross-domain exploration", data, api_key)
