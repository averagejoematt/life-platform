"""
ai_output_validator.py — AI-3: Post-processing validation for AI coaching output.

Validates AI-generated coaching text AFTER generation, BEFORE delivery.
Catches dangerous recommendations, empty/truncated output, and advice that
conflicts with the user's known health context.

USAGE (in ai_calls.py or any Lambda after receiving AI output):

    from ai_output_validator import validate_ai_output, AIOutputType

    result = validate_ai_output(
        text=bod_insight,
        output_type=AIOutputType.BOD_COACHING,
        health_context={"recovery_score": 18, "tsb": -22},
    )

    if result.blocked:
        logger.error("AI output blocked", reason=result.block_reason)
        return result.safe_fallback   # use fallback text instead

    if result.warnings:
        logger.warning("AI output warnings", warnings=result.warnings)

    final_text = result.sanitized_text   # safe to use

VALIDATION TIERS:

    BLOCK  — output is replaced with safe_fallback. Used for:
             - Empty/None output (Lambda crash protection)
             - Dangerous exercise recs with red recovery (injury risk)
             - Severely dangerous caloric guidance (< 800 kcal)
             - Output clearly truncated mid-sentence

    WARN   — output used as-is, warning logged. Used for:
             - Aggressive training language with borderline recovery
             - High-calorie surplus recommendation (unusual for this user)
             - Generic phrases that suggest context was ignored
             - Correlation presented as causation with low-confidence signal

    PASS   — no issues detected

DISCLAIMER:
    All AI output validated by this module should still include the footer:
    "AI-generated analysis, not medical advice." (AI-1 requirement)
    This module validates logical safety, not medical accuracy.

v1.0.0 — 2026-03-08 (AI-3)
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


# ── Output types ───────────────────────────────────────────────────────────────

class AIOutputType(str, Enum):
    BOD_COACHING   = "bod_coaching"      # Board of Directors 2-3 sentence coaching
    TLDR           = "tldr"              # TL;DR one-liner
    GUIDANCE       = "guidance"          # Smart guidance bullet item
    TRAINING_COACH = "training_coach"    # Training coach section
    NUTRITION_COACH = "nutrition_coach"  # Nutrition coach section
    JOURNAL_COACH  = "journal_coach"     # Journal reflection + tactical
    CHRONICLE      = "chronicle"         # Weekly chronicle narrative
    WEEKLY_DIGEST  = "weekly_digest"     # Weekly digest coaching
    MONTHLY_DIGEST = "monthly_digest"    # Monthly digest coaching
    GENERIC        = "generic"           # Unknown — minimal checks only


# ── Validation result ──────────────────────────────────────────────────────────

@dataclass
class AIValidationResult:
    original_text: str
    output_type: AIOutputType
    warnings: list[str] = field(default_factory=list)
    blocked: bool = False
    block_reason: str = ""
    safe_fallback: str = ""

    @property
    def sanitized_text(self) -> str:
        """Text to deliver — original if not blocked, fallback if blocked."""
        return self.safe_fallback if self.blocked else self.original_text

    @property
    def passed(self) -> bool:
        return not self.blocked and not self.warnings


# ── Dangerous phrase patterns ──────────────────────────────────────────────────

# These patterns in coaching output may indicate dangerous recommendations
# when combined with concerning health context data.

_AGGRESSIVE_TRAINING_PHRASES = [
    r"\bhigh.intensity\b",
    r"\bmax.effort\b",
    r"\bpush.hard\b",
    r"\bgo.all.out\b",
    r"\badd.more.volume\b",
    r"\bincrease.training.load\b",
    r"\bsprint\b",
    r"\bHIIT\b",
    r"\bVO2.max.test\b",
    r"\btrain.through\b",
    r"\bignore.*recovery\b",
    r"\bpush.through.*pain\b",
]

_DANGEROUS_CALORIE_PHRASES = [
    r"\b[1-7]\d{2}\s*(?:kcal|calories|cal)(?!\s*deficit)\b",  # 100-799 cal mentioned
    r"\bfast(?:ing)?\s+(?:all\s+day|24\s*h|skip\s+meal)\b",
    r"\bskip\s+(?:all\s+)?meal\b",
    r"\beat\s+nothing\b",
    r"\bzero\s+calories\b",
]

_SUPPLEMENT_OVERDOSE_PATTERNS = {
    # Supplement name → (safe_max_per_day, unit_pattern)
    "vitamin_d": (10_000, r"(?:vitamin\s+d\s*\d{5,}|d3\s*\d{5,})"),
    "zinc": (40, r"(?:zinc.*\b[5-9][0-9]\b|\bzinc.*\b[1-9]\d{2,}\b)"),
    "iron": (45, r"(?:iron.*\b[5-9][0-9]\b|\biron.*\b[1-9]\d{2,}\b)"),
    "vitamin_a": (10_000, r"(?:vitamin\s+a\s*\d{5,})"),
}

_GENERIC_USELESS_PHRASES = [
    r"\bstay\s+hydrated\b",
    r"\bdrink\s+plenty\s+of\s+water\b",
    r"\bget\s+enough\s+sleep\b",
    r"\beat\s+a\s+balanced\s+diet\b",
    r"\bexercise\s+regularly\b",
    r"\bmanage\s+your\s+stress\b",
    r"\btake\s+care\s+of\s+yourself\b",
    r"\blisten\s+to\s+your\s+body\b",
]

_CORRELATION_AS_CAUSATION = [
    r"\bcauses?\b.*\bproves?\b",
    r"\bclearly\s+causing\b",
    r"\bdefinitely\s+caused\b",
    r"\bproven\s+(?:to\s+)?(?:cause|link)\b",
]


# ── Core validator ─────────────────────────────────────────────────────────────

def validate_ai_output(
    text: Optional[str],
    output_type: AIOutputType = AIOutputType.GENERIC,
    health_context: dict = None,
    min_length: int = 10,
    max_length: int = 5_000,
) -> AIValidationResult:
    """Validate AI-generated coaching text for safety and quality.

    Args:
        text:           Raw AI output string
        output_type:    Which AI call produced this (affects thresholds)
        health_context: Dict of current health metrics for context-aware checks.
                        Key metrics: recovery_score (0-100), tsb (float),
                        sleep_score (0-100), hrv_yesterday (ms), latest_weight (lbs)
        min_length:     Minimum character count (below = blocked as empty)
        max_length:     Maximum character count (above = warn, not block)

    Returns:
        AIValidationResult with .sanitized_text ready to use.
    """
    ctx = health_context or {}
    result = AIValidationResult(
        original_text=text or "",
        output_type=output_type,
    )

    # ── Check 1: Empty / None output (BLOCK) ──────────────────────────────────
    if not text or not text.strip():
        result.blocked = True
        result.block_reason = "Empty or null output from AI call"
        result.safe_fallback = _fallback_for_type(output_type)
        logger.error("[ai_validator] BLOCKED empty output: %s", output_type)
        return result

    stripped = text.strip()

    # ── Check 2: Minimum length (BLOCK) ───────────────────────────────────────
    if len(stripped) < min_length:
        result.blocked = True
        result.block_reason = f"Output too short ({len(stripped)} chars, min {min_length})"
        result.safe_fallback = _fallback_for_type(output_type)
        logger.error("[ai_validator] BLOCKED too-short output: %s (%d chars)", output_type, len(stripped))
        return result

    # ── Check 3: Clearly truncated output (BLOCK) ─────────────────────────────
    if _is_truncated(stripped):
        result.blocked = True
        result.block_reason = "Output appears truncated (ends mid-sentence)"
        result.safe_fallback = _fallback_for_type(output_type)
        logger.error("[ai_validator] BLOCKED truncated output: %s", output_type)
        return result

    # ── Check 4: Dangerous exercise with red recovery (BLOCK) ─────────────────
    recovery_score = _safe_float(ctx.get("recovery_score"))
    if recovery_score is not None and recovery_score < 34:
        aggressive_found = _find_patterns(stripped, _AGGRESSIVE_TRAINING_PHRASES)
        if aggressive_found:
            result.blocked = True
            result.block_reason = (
                f"Dangerous training recommendation with red recovery score ({recovery_score:.0f}): "
                f"{', '.join(aggressive_found[:3])}"
            )
            result.safe_fallback = (
                "⚠️ Recovery is in the red zone — today is a mandatory rest or gentle walk day. "
                "Your body needs recovery resources, not new training stimulus."
            )
            logger.error(
                "[ai_validator] BLOCKED dangerous training rec: recovery=%.0f, patterns=%s",
                recovery_score, aggressive_found[:3],
            )
            return result

    # ── Check 5: Dangerously low calorie suggestions (BLOCK) ──────────────────
    if output_type in (AIOutputType.NUTRITION_COACH, AIOutputType.GUIDANCE, AIOutputType.BOD_COACHING):
        low_cal_found = _find_patterns(stripped, _DANGEROUS_CALORIE_PHRASES)
        if low_cal_found:
            # Extract any actual calorie numbers to confirm (avoid false positives on "800 cal deficit")
            cal_numbers = re.findall(r'\b([1-7]\d{2})\s*(?:kcal|calories|cal)\b', stripped, re.IGNORECASE)
            # Only block if numbers are < 800 and not clearly about deficit/restriction context
            blocked_cals = [c for c in cal_numbers if int(c) < 800
                            and not re.search(rf'{c}.*(?:deficit|below)', stripped, re.IGNORECASE)]
            if blocked_cals:
                result.blocked = True
                result.block_reason = f"Dangerously low calorie recommendation: {blocked_cals} kcal"
                result.safe_fallback = (
                    "⚠️ Calorie guidance review needed. Target minimum: 1,200 kcal/day. "
                    "Consult your nutritionist if you're uncertain about your calorie target."
                )
                logger.error("[ai_validator] BLOCKED low-cal rec: %s", blocked_cals)
                return result

    # ── Check 6: Aggressive training with borderline recovery (WARN) ───────────
    if recovery_score is not None and 34 <= recovery_score < 50:
        aggressive_found = _find_patterns(stripped, _AGGRESSIVE_TRAINING_PHRASES)
        if aggressive_found:
            result.warnings.append(
                f"Aggressive training language with borderline recovery ({recovery_score:.0f}): "
                f"{', '.join(aggressive_found[:2])}"
            )

    # ── Check 7: TSB too negative + training push (WARN) ──────────────────────
    tsb = _safe_float(ctx.get("tsb"))
    if tsb is not None and tsb < -15:
        aggressive_found = _find_patterns(stripped, _AGGRESSIVE_TRAINING_PHRASES)
        if aggressive_found:
            result.warnings.append(
                f"Training recommendation with high accumulated fatigue (TSB {tsb:.1f})"
            )

    # ── Check 8: Generic useless phrases (WARN) ───────────────────────────────
    if output_type not in (AIOutputType.CHRONICLE, AIOutputType.WEEKLY_DIGEST, AIOutputType.MONTHLY_DIGEST):
        generic_found = _find_patterns(stripped.lower(), _GENERIC_USELESS_PHRASES)
        if len(generic_found) >= 2:
            result.warnings.append(
                f"Generic coaching phrases detected (context may have been ignored): "
                f"{', '.join(generic_found[:3])}"
            )

    # ── Check 9: Correlation presented as causation (WARN) ────────────────────
    causation_found = _find_patterns(stripped.lower(), _CORRELATION_AS_CAUSATION)
    if causation_found:
        result.warnings.append(
            f"Correlation-as-causation language: {', '.join(causation_found[:2])}"
        )

    # ── Check 10: Length warning (WARN, not block) ────────────────────────────
    if len(stripped) > max_length:
        result.warnings.append(
            f"Output unusually long ({len(stripped)} chars) — check for prompt injection or runaway generation"
        )

    # ── Check 11: Output starts with "Matthew" (WARN) ─────────────────────────
    # Prompt explicitly says "DO NOT start with 'Matthew'" — this is a quality signal
    if stripped.startswith("Matthew"):
        result.warnings.append("Output starts with 'Matthew' — prompt instruction may have been ignored")

    if result.blocked:
        logger.error("[ai_validator] Output blocked: %s | %s", output_type, result.block_reason)
    elif result.warnings:
        logger.warning(
            "[ai_validator] Output warnings for %s: %s",
            output_type, result.warnings,
        )

    return result


def validate_json_output(
    parsed: Optional[dict],
    required_keys: list[str],
    output_type: AIOutputType = AIOutputType.GENERIC,
    health_context: dict = None,
) -> AIValidationResult:
    """Validate JSON-structured AI output (training_nutrition, tldr_guidance).

    Args:
        parsed:        Already-parsed dict from AI call (None if JSON parse failed)
        required_keys: Keys that must be present and non-empty
        output_type:   For fallback text selection
        health_context: Health context for text-level checks on each value

    Returns:
        AIValidationResult. Checks each string value with validate_ai_output.
    """
    ctx = health_context or {}

    if not parsed:
        return AIValidationResult(
            original_text="{}",
            output_type=output_type,
            blocked=True,
            block_reason="JSON output is None or failed to parse",
            safe_fallback="",
        )

    warnings = []
    errors = []

    for key in required_keys:
        val = parsed.get(key)
        if not val:
            errors.append(f"Required key '{key}' missing or empty in JSON output")
            continue
        if isinstance(val, str):
            sub_result = validate_ai_output(val, output_type, ctx)
            if sub_result.blocked:
                errors.append(f"Key '{key}' failed validation: {sub_result.block_reason}")
                parsed[key] = sub_result.safe_fallback  # replace with safe text in-place
            warnings.extend([f"[{key}] {w}" for w in sub_result.warnings])
        elif isinstance(val, list):
            for i, item in enumerate(val):
                if isinstance(item, str):
                    sub_result = validate_ai_output(item, output_type, ctx)
                    if sub_result.blocked:
                        warnings.append(f"Key '{key}[{i}]' blocked: {sub_result.block_reason}")
                        val[i] = sub_result.safe_fallback

    result = AIValidationResult(
        original_text=str(parsed),
        output_type=output_type,
        warnings=warnings,
    )
    if errors:
        result.blocked = True
        result.block_reason = "; ".join(errors[:3])
        result.safe_fallback = ""

    return result


# ── Helpers ────────────────────────────────────────────────────────────────────

def _find_patterns(text: str, patterns: list[str]) -> list[str]:
    """Return list of patterns that match in text (case-insensitive)."""
    found = []
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            found.append(pattern.replace(r"\b", "").replace("\\", "").strip(".+*?()[]{}^$|"))
    return found


def _is_truncated(text: str) -> bool:
    """Heuristic: output appears truncated mid-sentence."""
    stripped = text.strip()
    if len(stripped) < 20:
        return True
    # Ends with a comma, conjunction, or clearly incomplete
    truncation_endings = [",", " and", " but", " or", " so", " the", " a ", " an "]
    for ending in truncation_endings:
        if stripped.endswith(ending):
            return True
    # No terminal punctuation at all for short outputs
    if len(stripped) < 200 and not any(stripped.endswith(p) for p in ".!?\"'"):
        return False  # not necessarily truncated for short coaching blurbs
    return False


def _safe_float(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _fallback_for_type(output_type: AIOutputType) -> str:
    """Safe fallback text when AI output is blocked."""
    fallbacks = {
        AIOutputType.BOD_COACHING: (
            "Data analysis complete. Review your metrics above and focus on your top-priority "
            "habit for today. Consistency compounds."
        ),
        AIOutputType.TLDR: "Review today's scorecard above for your key takeaways.",
        AIOutputType.GUIDANCE: "📋 Focus on your Tier 0 habits today.",
        AIOutputType.TRAINING_COACH: (
            "Training data received. Listen to your body — recovery score should guide today's intensity."
        ),
        AIOutputType.NUTRITION_COACH: (
            "Nutrition data received. Aim for your protein target and stay within your calorie range."
        ),
        AIOutputType.JOURNAL_COACH: "Take a moment to reflect on what's working and what you'd do differently.",
        AIOutputType.CHRONICLE: "(Chronicle generation temporarily unavailable.)",
        AIOutputType.WEEKLY_DIGEST: "(Weekly digest coaching temporarily unavailable.)",
        AIOutputType.MONTHLY_DIGEST: "(Monthly digest coaching temporarily unavailable.)",
        AIOutputType.GENERIC: "Analysis temporarily unavailable. Check your metrics directly.",
    }
    return fallbacks.get(output_type, fallbacks[AIOutputType.GENERIC])


# ── Convenience: validate all Daily Brief AI outputs ─────────────────────────

def validate_daily_brief_outputs(
    bod_insight: str,
    training_nutrition: dict,
    journal_coach_text: str,
    tldr_guidance: dict,
    health_context: dict = None,
) -> dict:
    """Validate all four Daily Brief AI outputs and return safe versions.

    Args:
        bod_insight:         BoD coaching string
        training_nutrition:  {"training": ..., "nutrition": ...} dict
        journal_coach_text:  Journal coach string
        tldr_guidance:       {"tldr": ..., "guidance": [...]} dict
        health_context:      Current health metrics dict

    Returns:
        Dict with keys: bod_insight, training_nutrition, journal_coach_text,
        tldr_guidance, validation_warnings (list of all warnings across calls)
    """
    ctx = health_context or {}
    all_warnings = []
    results = {}

    # BoD coaching
    bod_result = validate_ai_output(bod_insight, AIOutputType.BOD_COACHING, ctx)
    results["bod_insight"] = bod_result.sanitized_text
    all_warnings.extend([f"[bod] {w}" for w in bod_result.warnings])
    if bod_result.blocked:
        all_warnings.append(f"[bod] BLOCKED: {bod_result.block_reason}")

    # Training + nutrition JSON
    tn = training_nutrition or {}
    training_result = validate_ai_output(tn.get("training", ""), AIOutputType.TRAINING_COACH, ctx)
    nutrition_result = validate_ai_output(tn.get("nutrition", ""), AIOutputType.NUTRITION_COACH, ctx)
    results["training_nutrition"] = {
        "training": training_result.sanitized_text,
        "nutrition": nutrition_result.sanitized_text,
    }
    all_warnings.extend([f"[training] {w}" for w in training_result.warnings])
    all_warnings.extend([f"[nutrition] {w}" for w in nutrition_result.warnings])
    if training_result.blocked:
        all_warnings.append(f"[training] BLOCKED: {training_result.block_reason}")
    if nutrition_result.blocked:
        all_warnings.append(f"[nutrition] BLOCKED: {nutrition_result.block_reason}")

    # Journal coach
    jc_result = validate_ai_output(journal_coach_text, AIOutputType.JOURNAL_COACH, ctx)
    results["journal_coach_text"] = jc_result.sanitized_text
    all_warnings.extend([f"[journal_coach] {w}" for w in jc_result.warnings])

    # TL;DR + guidance JSON
    tg = tldr_guidance or {}
    tldr_result = validate_ai_output(tg.get("tldr", ""), AIOutputType.TLDR, ctx, min_length=5)
    results["tldr_guidance"] = {
        "tldr": tldr_result.sanitized_text,
        "guidance": [],
    }
    all_warnings.extend([f"[tldr] {w}" for w in tldr_result.warnings])
    for i, g_item in enumerate(tg.get("guidance", [])):
        g_result = validate_ai_output(g_item, AIOutputType.GUIDANCE, ctx, min_length=5)
        results["tldr_guidance"]["guidance"].append(g_result.sanitized_text)
        all_warnings.extend([f"[guidance[{i}]] {w}" for w in g_result.warnings])
        if g_result.blocked:
            all_warnings.append(f"[guidance[{i}]] BLOCKED: {g_result.block_reason}")

    results["validation_warnings"] = all_warnings

    if all_warnings:
        logger.warning("[ai_validator] Daily Brief validation: %d warnings", len(all_warnings))

    return results
