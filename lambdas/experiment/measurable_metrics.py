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

import re

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

# Aggregate suffixes the evaluator computes on the fly over a base metric.
AGG_SUFFIXES = ("_7day_avg", "_14day_avg", "_30day_avg")

# Metric → the subdomain name used for window enforcement. Every value here MUST be a key
# of `coach_prediction_evaluator.SUBDOMAIN_TO_DOMAIN`, or the prediction silently falls to
# the conservative "training" default and its window is clamped to 21 days (#813). Lives
# HERE, next to METRIC_SOURCES, for the same reason METRIC_SOURCES does: it is derived
# from the metric identity, and a second copy is a drift bug waiting to happen.
# `dispute_docket._METRIC_SUBDOMAIN` is still a separate copy pending its own collapse
# onto this one — tests/test_diary_claims_1841.py pins the two identical meanwhile.
METRIC_SUBDOMAIN = {
    "weight_lbs": "weight",
    "body_fat_pct": "body_fat",
    "sleep_duration_hours": "sleep",
    "sleep_score": "sleep",
    "deep_pct": "sleep",
    "rem_pct": "sleep",
    "hrv": "hrv",
    "recovery_score": "recovery",
    "resting_heart_rate": "recovery",
    "blood_glucose_avg": "glucose",
    "blood_glucose_std_dev": "glucose",
    "total_calories_kcal": "calories",
    "total_protein_g": "protein",
    "steps": "training",
}


def base_metric(metric_key):
    """Strip a supported aggregate suffix down to the base metric key."""
    for suffix in AGG_SUFFIXES:
        if str(metric_key).endswith(suffix):
            return str(metric_key)[: -len(suffix)]
    return str(metric_key)


def metric_is_resolvable(metric_key):
    """True only when the evaluator's own metric machinery can resolve this key."""
    if not metric_key or not isinstance(metric_key, str):
        return False
    return base_metric(metric_key) in METRIC_SOURCES


def metric_subdomain(metric_key):
    """The window-enforcement subdomain for a metric ('general' when unmapped)."""
    return METRIC_SUBDOMAIN.get(base_metric(metric_key), "general")


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


def _phrase_pattern(phrase):
    """A word-boundary regex for one direction phrase that tolerates ordinary English
    inflection — `improve` matches improve/improves/improved/improving and `drop`
    matches drop/drops/dropped/dropping — but NEVER a different word that merely
    starts with it: `recover` no longer matches `recovery` (#3551).

    Each word: strip a trailing 'e', allow an optional doubled final consonant,
    then an optional inflection suffix, then a word boundary."""
    parts = []
    for word in phrase.split():
        stem = word[:-1] if word.endswith("e") else word
        doubled = re.escape(stem[-1]) + "?" if stem and stem[-1].isalpha() and stem[-1] not in "aeiou" else ""
        parts.append(rf"{re.escape(stem)}{doubled}(?:e|es|s|ed|d|ing)?")
    return re.compile(r"\b" + r"\s+".join(parts) + r"\b")


_DIR_UP_PATTERNS = tuple(_phrase_pattern(w) for w in DIR_UP_WORDS)
_DIR_DOWN_PATTERNS = tuple(_phrase_pattern(w) for w in DIR_DOWN_WORDS)


def _strip_metric_name(claim, metric_hint):
    """Blank out the metric's own name from the claim so a direction word can never
    be read off it: for `recovery_score` the tokens `recovery` / `score` and every
    prose needle that normalizes to it (`recovery score`, `recovery`) are removed
    at word boundaries. THE #3551 FEEDER: 'recover' in DIR_UP_WORDS substring-
    matched the metric name 'recovery', so every recovery_score claim without a
    down-word was emitted condition='up' regardless of its content."""
    if not metric_hint:
        return claim
    names = {tok for tok in str(metric_hint).lower().split("_") if len(tok) >= 3}
    names |= {needle for needle, target in _METRIC_HINT_NORMALIZERS if target == metric_hint}
    out = claim
    for name in sorted(names, key=len, reverse=True):
        out = re.sub(r"\b" + re.escape(name) + r"\b", " ", out)
    return out


def infer_direction(extractor_direction, claim_natural, metric_hint=None):
    """Resolve a prediction's expected direction → 'up' | 'down' | None.

    Prefers the extractor's explicit `direction`; falls back to deterministic
    keyword inference from the claim text. Ambiguous (both directions present)
    or directionless claims return None — the caller keeps them qualitative
    rather than guessing (ADR-105: deterministic computation only).

    #3551: keyword matching is word-boundary + inflection aware (never a bare
    substring), and the metric's own name is excluded from the text first, so
    'Recovery score will be approximately 53.5%' cannot receive 'up' from the
    word 'recovery'. A numeric LEVEL claim is not a directional claim at all —
    prediction_emission.classify_claim_shape routes those to a `point` spec
    before this function is consulted.
    """
    d = (extractor_direction or "").strip().lower()
    if d in ("up", "rise", "increase", "higher"):
        return "up"
    if d in ("down", "fall", "decrease", "lower"):
        return "down"
    c = _strip_metric_name((claim_natural or "").lower(), metric_hint)
    up = any(p.search(c) for p in _DIR_UP_PATTERNS)
    down = any(p.search(c) for p in _DIR_DOWN_PATTERNS)
    if up and not down:
        return "up"
    if down and not up:
        return "down"
    return None  # ambiguous or none → caller keeps it qualitative
