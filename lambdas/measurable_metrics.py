"""
measurable_metrics.py — the ONE registry of machine-gradable coach-prediction metrics.

A coach prediction is only auto-gradable if its metric (a) is on an allowlist the
extractor recognises and (b) maps to a DynamoDB source the evaluator can read. Those
two facts used to live as SEPARATE copies — `MEASURABLE_METRICS` in
coach_state_updater.py and `METRIC_SOURCES` in coach_prediction_evaluator.py — and
when they drifted, predictions silently fell to `qualitative` and never graded (the
v7.15.0 audit: 504 predictions, 100% inconclusive). The Coherence Sentinel's
prediction_health invariant exists precisely because this failure is invisible.

This is the single source. `MEASURABLE_METRICS` is DERIVED from `METRIC_SOURCES`, so
the allowlist and the source-map cannot drift by construction. Both coach lambdas
import from here. Pure (no boto3) — bundled with the lambdas/ asset, not the layer.
"""

from __future__ import annotations

# Metric key → the DynamoDB source partition the evaluator reads it from.
# Keep additions here; the allowlist + the suffix-aggregate logic follow automatically.
# INVARIANT (#813): the key must be the EXACT attribute name on that source's DATE#
# records — the evaluator reads record[metric_key] verbatim. The #813 triage found
# sleep_score/deep_pct/rem_pct mapped to whoop, whose records carry none of those
# fields (whoop has sleep_quality_score + *_sleep_hours); the fields live on
# eightsleep records, so every sleep-architecture prediction resolved to "no data"
# forever. Verify against a live record before adding a mapping.
METRIC_SOURCES = {
    "hrv": "whoop",
    "hrv_7day_avg": "whoop",
    "recovery_score": "whoop",
    "resting_heart_rate": "whoop",
    "sleep_duration_hours": "whoop",
    "sleep_score": "eightsleep",  # #813: field exists on eightsleep records, NOT whoop
    "deep_pct": "eightsleep",  # #813: same
    "rem_pct": "eightsleep",  # #813: same
    "weight_lbs": "withings",
    "total_calories_kcal": "macrofactor",
    "total_protein_g": "macrofactor",
    "steps": "apple_health",
    "blood_glucose_avg": "apple_health",
    "blood_glucose_std_dev": "apple_health",
    "body_fat_pct": "dexa",
}

# DERIVED — every measurable metric is, by definition, one the evaluator can source.
# Aggregate-suffixed forms (_7day_avg/_14day_avg/_30day_avg) the evaluator computes
# on the fly are valid extensions of any base key.
MEASURABLE_METRICS = frozenset(METRIC_SOURCES)

# Substring → measurable-metric mapping for normalizing prose-y metric hints. Checked
# in declared order — first match wins, so multi-word/specific patterns come BEFORE
# single-word ones (e.g. "hours of sleep needed for recovery" must hit sleep before
# recovery). Tuned from the LEARNING# audit (v7.15.0).
_METRIC_HINT_NORMALIZERS = (
    ("heart rate variability", "hrv"),
    ("resting heart rate", "resting_heart_rate"),
    ("resting hr", "resting_heart_rate"),
    ("hours of sleep", "sleep_duration_hours"),
    ("sleep duration", "sleep_duration_hours"),
    ("sleep score", "sleep_score"),
    ("sleep quality", "sleep_score"),
    ("sleep efficiency", "sleep_score"),
    ("deep sleep", "deep_pct"),
    ("rem sleep", "rem_pct"),
    ("rem percentage", "rem_pct"),
    ("blood glucose", "blood_glucose_avg"),
    ("glucose variability", "blood_glucose_std_dev"),
    ("glucose excursion", "blood_glucose_avg"),
    ("postprandial glucose", "blood_glucose_avg"),
    ("post-meal glucose", "blood_glucose_avg"),
    ("body fat", "body_fat_pct"),
    ("step count", "steps"),
    ("daily steps", "steps"),
    ("recovery score", "recovery_score"),
    ("recovery", "recovery_score"),
    # Single-word fallbacks (checked last)
    ("hrv", "hrv"),
    ("weight", "weight_lbs"),
    ("calorie", "total_calories_kcal"),
    ("kcal", "total_calories_kcal"),
    ("protein", "total_protein_g"),
    ("glucose", "blood_glucose_avg"),
    ("steps", "steps"),
)


def normalize_metric_hint(hint):
    """Map an LLM-produced metric_hint to a measurable key, or None.

    If the hint already names an allowlisted key, returns it as-is (covers the
    aggregate-suffixed `hrv_7day_avg`). Otherwise walks the substring map. Returns
    None when nothing matches — the caller marks the prediction qualitative so the
    evaluator skips it (rather than churning daily 'inconclusive: no data')."""
    if not hint:
        return None
    h = hint.strip().lower()
    if h in MEASURABLE_METRICS:
        return h
    h_spaced = h.replace("_", " ")
    for needle, target in _METRIC_HINT_NORMALIZERS:
        if needle in h or needle in h_spaced:
            return target
    return None


# ── Direction inference (#813 — shared by the writer AND the evaluator) ─────────
# The writer (coach_state_updater) uses this to route metric+direction claims to
# the gradable `directional` evaluator at emission. The evaluator uses the SAME
# inference to deterministically rescue the legacy machine-type backlog (specs
# written before C-3 with threshold=None + condition='gt' regardless of the claim
# — 'gt' was a constant, not a signal, so the claim text is the only honest
# direction source). One list, one function — the two sides cannot drift.
DIR_UP_WORDS = (
    "improve",
    "increase",
    "rise",
    "rising",
    "higher",
    "climb",
    "go up",
    "goes up",
    "recover",
    "rebound",
    "gain",
    "grow",
    "strengthen",
    "trend up",
    "trending up",
    "upward",
    "bounce back",
)
DIR_DOWN_WORDS = (
    "drop",
    "decrease",
    "decline",
    "fall",
    "lower",
    "reduce",
    "shrink",
    "lose",
    "loss",
    "go down",
    "goes down",
    "come down",
    "dip",
    "trend down",
    "trending down",
    "downward",
    "ease",
)


def infer_direction(extractor_direction, claim_natural):
    """Resolve a prediction's expected direction → 'up' | 'down' | None.

    Prefers the extractor's explicit `direction`; falls back to deterministic
    keyword inference from the claim text. Ambiguous (both directions present)
    or directionless claims return None — the caller keeps them qualitative
    rather than guessing (ADR-105: deterministic computation only).
    """
    d = (extractor_direction or "").strip().lower()
    if d in ("up", "rise", "increase", "higher"):
        return "up"
    if d in ("down", "fall", "decrease", "lower"):
        return "down"
    c = (claim_natural or "").lower()
    up = any(w in c for w in DIR_UP_WORDS)
    down = any(w in c for w in DIR_DOWN_WORDS)
    if up and not down:
        return "up"
    if down and not up:
        return "down"
    return None  # ambiguous or none → caller keeps it qualitative
