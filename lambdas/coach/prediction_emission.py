"""lambdas/coach/prediction_emission.py — the PREDICTION# emission contract (#3046).

Closed #715's acceptance included "zero predictions ungradeable-by-construction";
DIL-007 (diligence review 2026-08-23) found 28 of 50 pending predictions carrying
`eval_type: "qualitative"` — records the deterministic evaluator structurally
skips, so they could only pend forever. The defect was at EMISSION: a claim with
no grading path was still written with status "pending", which is a promise the
evaluator will grade it.

The contract, enforced here and regression-gated by
tests/test_prediction_gradeability_3046.py:

  * Every emitted PREDICTION# carries ``gradeable_by`` — "deterministic" (the
    daily evaluator grades it) or "none" (nothing can).
  * ``gradeable_by: "none"`` claims are emitted with status "observation",
    NEVER "pending"/"confirming": they stay on the record (labeled as
    observational on the public surfaces) but never enter the pending-grading
    corpus. No newly-emitted prediction is ungradeable-by-construction.

Legacy pending-qualitative rows are retired by the evaluator at window end
(coach_prediction_evaluator._retire_ungradeable) — they drain, this stops refill.

Extracted from coach_state_updater's inline loop (#3046; the module sat at its
module-size ratchet cap). Pure record construction — no AWS clients.
"""

import math
import re
from datetime import datetime, timedelta, timezone

from experiment.measurable_metrics import base_metric as base_metric_key  # #3551: aggregate keys grade their base metric's unit

GRADEABLE_BY_DETERMINISTIC = "deterministic"
GRADEABLE_BY_NONE = "none"

# The status a claim without a grading path is emitted under. Deliberately NOT in
# the evaluator's EVALUABLE_STATUSES and never counted as "pending" on a surface.
OBSERVATION_STATUS = "observation"


def build_prediction_eval_spec(metric_hint, direction, window_days):
    """Build the PREDICTION# `evaluation` block, choosing the gradable type.

    metric + direction → directional (EWMA trend, no threshold needed) — this is
    the path that lets the daily evaluator actually confirm/refute. Without a
    resolvable direction (or metric) we stay qualitative rather than writing a
    machine spec with threshold=None that can only ever go inconclusive.
    (Moved verbatim from coach_state_updater — semantics unchanged.)
    """
    if metric_hint and direction in ("up", "down"):
        return {
            "type": "directional",
            "metric": metric_hint,
            "condition": direction,  # the directional evaluator reads 'up'/'down'
            "threshold": None,
            "evaluation_window_days": window_days,
            "null_hypothesis": None,
            "beats_null_if": None,
        }
    return {
        "type": "qualitative",
        "metric": metric_hint or None,
        "condition": None,
        "threshold": None,
        "evaluation_window_days": window_days,
        "null_hypothesis": None,
        "beats_null_if": None,
    }


# ── #3551: a numeric LEVEL claim is a point spec, never a directional one ───────
#
# THE LIVE DEFECT (2026-09-05, /review full QS-4): 'Recovery score will be
# approximately 53.5%' was stored as {type: directional, condition: up, window 14}
# and 'Recovery score tomorrow will be around 50%' (2026-08-17) was CONFIRMED as a
# 14-day up-trend — a one-day level forecast scored as a two-week slope sign, now
# in the lifetime 8/37. Two feeders into one missing type: (1) 'recover' in
# DIR_UP_WORDS substring-matched the metric name (fixed in
# measurable_metrics.infer_direction), and (2) build_prediction_eval_spec only knew
# directional | qualitative, so any resolvable direction — including the LLM
# extractor's — turned a point estimate into a slope bet. This classifier runs
# BEFORE direction inference: a claim carrying a numeric level becomes a `point`
# spec (graded by numeric tolerance) or, when no tolerance can be derived, an
# observation — never `directional`.

POINT_TYPE = "point"

# A level cue: the verb/approximation that ties a number to the metric as ITS value.
_LEVEL_CUE = (
    r"(?:(?:will|should|to)\s+(?:be|read|register|hit|reach|average|come\s+in\s+at|sit\s+at|land\s+(?:at|on)|"
    r"settle\s+(?:at|around|near)|hover\s+(?:at|around|near)|stay\s+(?:at|around|near)|end\s+(?:at|around|near))"
    r"|sits?\s+at|averag(?:e|es|ing)(?:\s+of)?|approximately|approx\.?|around|about|roughly|near|nearly|close\s+to|~)"
)
_LEVEL_APPROX = r"(?:approximately|approx\.?|around|about|roughly|near|nearly|close\s+to|at|~)?"
_NUM = r"(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
# metric name → [filler: no digits, no clause break] → cue → [approx] → number
_LEVEL_AFTER_METRIC_RE = re.compile(
    r"^(?P<filler>[^\d.;!?]{0,60}?)(?<![a-z])(?P<cue>" + _LEVEL_CUE + r")\s*" + _LEVEL_APPROX + r"\s*" + _NUM,
    re.IGNORECASE,
)
# The number is a THRESHOLD, a CHANGE or a DURATION — not a level of the metric.
_THRESHOLD_OR_CHANGE_RE = re.compile(
    r"\b(?:at\s+least|at\s+most|exceed(?:s|ing)?|above|below|under|over|more\s+than|less\s+than|fewer\s+than|"
    r"minimum|maximum|no\s+more|no\s+less|beyond|past|by|in|within|after|for|next|last|per|each|every)\b|\bor\s+(?:more|higher|lower|better|worse)\b",
    re.IGNORECASE,
)
_NOT_A_LEVEL_AFTER_RE = re.compile(
    r"^\s*(?:%|percent)?\s*(?:-|to|or)?\s*(?:confidence|confident|probability|likelihood|chance|certainty|"
    r"or\s+(?:more|higher|lower|better|worse|above|below)|days?|weeks?|months?|sessions?|workouts?|times|x\b|reps?|sets?|"
    r"meals?|nights?|mornings?|miles?|mi\b|km\b|minutes?|mins?\b|points?\s+(?:up|down|higher|lower)|(?:lbs?|kg|%)\s+(?:up|down|lower|higher|lighter|heavier))",
    re.IGNORECASE,
)
_UNIT_RE = re.compile(
    r"^\s*(%|percent|lbs?|pounds?|kg|kgs|hours?|hrs?|h\b|ms|bpm|kcal|cal|calories|g\b|grams?|steps?|mg/dl)", re.IGNORECASE
)
# A unit that belongs to a DIFFERENT quantity than the metric rejects the match —
# "~16 hours" is a fasting window, not a glucose level. Unitless numbers pass.
_METRIC_UNITS = {
    "recovery_score": {"%", "percent"},
    "hrv": {"ms"},
    "resting_heart_rate": {"bpm"},
    "sleep_duration_hours": {"hours", "hour", "hrs", "hr", "h"},
    "sleep_score": {"%", "percent"},
    "deep_pct": {"%", "percent"},
    "rem_pct": {"%", "percent"},
    "body_fat_pct": {"%", "percent"},
    "weight_lbs": {"lbs", "lb", "pounds", "pound", "kg", "kgs"},
    "total_calories_kcal": {"kcal", "cal", "calories"},
    "total_protein_g": {"g", "grams", "gram"},
    "steps": {"steps", "step"},
    "blood_glucose_avg": {"mg/dl"},
    "blood_glucose_std_dev": {"mg/dl"},
}
_TOMORROW_RE = re.compile(r"\b(tomorrow|tonight|today)\b", re.IGNORECASE)
_DATE_RE = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")


def _metric_names(metric_hint):
    """Every way the claim text can name this metric: the key, its base key (for a
    `_7day_avg` aggregate), the key's own tokens, and every prose needle that
    normalizes to it ('recovery score', 'resting hr', 'step count', ...)."""
    from experiment.measurable_metrics import _METRIC_HINT_NORMALIZERS  # local: the normalizer table is private to that module

    keys = {str(metric_hint).lower()}
    base = base_metric_key(metric_hint)
    if base:
        keys.add(str(base).lower())
    names = set(keys)
    for k in keys:
        names |= {tok for tok in k.split("_") if len(tok) >= 3 and not tok.endswith("day") and tok not in ("avg", "std", "dev", "pct")}
        names |= {needle for needle, target in _METRIC_HINT_NORMALIZERS if target == k}
    return sorted(names, key=len, reverse=True)


def classify_claim_shape(claim, metric_hint=None):
    """Deterministic claim-shape classifier: {'shape': 'level' | 'other', 'target',
    'unit', 'window_hint', 'target_date'}.

    A LEVEL claim states a numeric value OF THE METRIC — the metric is named, and a
    level cue ('will be', 'will read', 'sits at', 'around', '~', ...) ties a number
    to it inside the same clause: 'Recovery score will be approximately 53.5%',
    'resting heart rate ~62 bpm', 'steps will be around 8000 tomorrow'. Everything
    else is 'other' and takes the directional path untouched — a threshold ('meet
    or exceed roughly 6,000 steps', 'under 320'), a change ('drop by 2 lbs', '5
    points higher'), a duration ('in about 3 days'), an event count ('3 sessions'),
    or a number that describes a protocol input rather than the metric ('daily
    ~3-mile walks will lift HRV', '~16 hours of fasting lowers glucose'). The live
    corpus is mostly the latter (2026-09-06 dry run: 5 of 6 loose matches were
    protocol inputs), which is why the number must be anchored to the metric name.
    """
    text = str(claim or "")
    none = {"shape": "other", "target": None, "unit": None, "window_hint": None, "target_date": None}
    if not text.strip() or not metric_hint:
        return none
    lowered = text.lower()
    for name in _metric_names(metric_hint):
        for m in re.finditer(r"\b" + re.escape(name) + r"s?\b", lowered):
            tail = text[m.end() :]
            lm = _LEVEL_AFTER_METRIC_RE.match(tail)
            if not lm:
                continue
            region = tail[: lm.start("num")]
            if _THRESHOLD_OR_CHANGE_RE.search(region):
                continue
            after = tail[lm.end("num") :]
            if _NOT_A_LEVEL_AFTER_RE.match(after):
                continue
            unit_m = _UNIT_RE.match(after)
            unit = unit_m.group(1).lower() if unit_m else None
            allowed = _METRIC_UNITS.get(str(base_metric_key(metric_hint) or metric_hint).lower())
            if unit and allowed is not None and unit not in allowed:
                continue
            try:
                target = float(lm.group("num").replace(",", ""))
            except (TypeError, ValueError):
                continue
            date_m = _DATE_RE.search(text)
            when = _TOMORROW_RE.search(text)
            return {
                "shape": "level",
                "target": target,
                "unit": unit,
                "window_hint": when.group(1).lower() if when else None,
                "target_date": date_m.group(1) if date_m else None,
            }
    return none


# The floor below which no personal SD is derived — matches the writer's liveness
# minimum (_LIVENESS_MIN_POINTS) so a metric alive enough to grade is alive enough
# to price a tolerance from.
POINT_TOLERANCE_MIN_POINTS = 5


def point_tolerance_from_series(values, lookback_days=30):
    """The tolerance for a point spec, derived from the subject's own trailing
    series (ADR-105 rule 4: thresholds from personal variance, or say why not).

    tolerance = 1 sample SD of the trailing values (n-1 denominator). Returns
    (tolerance, rule_string, n) or None when fewer than POINT_TOLERANCE_MIN_POINTS
    readings exist or the series is constant (an SD of 0 would make the spec an
    exact-match lottery, which is not a forecast anyone made). The rule string is
    frozen INTO the spec so the served grade is reproducible from it."""
    clean = []
    for v in values or []:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if not math.isnan(f):
            clean.append(f)
    n = len(clean)
    if n < POINT_TOLERANCE_MIN_POINTS:
        return None
    mean = sum(clean) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in clean) / (n - 1))
    if sd <= 0:
        return None
    tol = round(sd, 4)
    rule = f"±1 SD of the trailing {lookback_days}-day personal series (n={n} readings, SD={tol})"
    return tol, rule, n


def build_point_eval_spec(metric_hint, target, tolerance, tolerance_rule, window_days, generation_date):
    """The `point` evaluation block: the metric's reading on `target_date`
    (generation + window) must land within ±tolerance of `target`. Frozen at
    emission (pre-registration): the target, the tolerance and the rule that
    produced it are all on the record before the window opens."""
    try:
        target_date = (datetime.strptime(generation_date, "%Y-%m-%d") + timedelta(days=int(window_days))).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        target_date = None
    return {
        "type": POINT_TYPE,
        "metric": metric_hint,
        "condition": "within",
        "threshold": float(target),
        "tolerance": float(tolerance),
        "tolerance_rule": tolerance_rule,
        "target_date": target_date,
        "evaluation_window_days": window_days,
        "null_hypothesis": None,
        "beats_null_if": None,
    }


def resolve_eval_spec(claim, metric_hint, extractor_direction, timeframe_hint, generation_date, tolerance_for, infer_direction):
    """THE emission-time routing for one coach claim — pure, dependency-injected.

    Order matters (#3551): the claim SHAPE is classified first. A level claim
    becomes a `point` spec when `tolerance_for(metric)` can derive one from the
    subject's own trailing variance, else a qualitative (observation) spec — it is
    NEVER handed to direction inference, whatever the extractor said. Everything
    else takes the directional path exactly as before.

    Returns (eval_spec, window_days, shape).
    """
    shape = classify_claim_shape(claim, metric_hint) if metric_hint else {"shape": "other", "window_hint": None, "target_date": None}
    window_days = prediction_window_days(timeframe_hint or shape.get("window_hint") or "")
    if shape.get("target_date") and generation_date:
        # An ISO date in the claim IS the window — "will sit at 318 by 2026-09-20".
        try:
            delta = (datetime.strptime(shape["target_date"], "%Y-%m-%d") - datetime.strptime(generation_date, "%Y-%m-%d")).days
            if delta >= 1:
                window_days = delta
        except (TypeError, ValueError):
            pass
    if shape.get("shape") == "level":
        tol = tolerance_for(metric_hint)
        if tol:
            tolerance, rule, _n = tol
            return build_point_eval_spec(metric_hint, shape["target"], tolerance, rule, window_days, generation_date), window_days, "level"
        return build_prediction_eval_spec(metric_hint, None, window_days), window_days, "level"
    direction = infer_direction(extractor_direction, claim, metric_hint) if metric_hint else None
    return build_prediction_eval_spec(metric_hint, direction, window_days), window_days, "other"


def emission_status(eval_spec):
    """(status, gradeable_by) for a newly-emitted PREDICTION# — THE contract.

    A spec the evaluator can grade (directional, point #3551, machine-with-threshold)
    → ("pending", "deterministic"). A qualitative spec → ("observation", "none"): on
    the record, never pending-forever."""
    if (eval_spec or {}).get("type") == "qualitative":
        return OBSERVATION_STATUS, GRADEABLE_BY_NONE
    return "pending", GRADEABLE_BY_DETERMINISTIC


def prediction_window_days(timeframe_hint, default=14):
    """Map a free-text timeframe hint to evaluation window days (prediction
    default 14 — distinct from commitments' 7). Moved verbatim from the
    coach_state_updater prediction loop."""
    if not timeframe_hint:
        return default
    tf = timeframe_hint.lower()
    # #3551: a one-day call is a one-day window — 'tomorrow' used to fall through to
    # the 14-day default, which is how a next-morning level forecast got graded as a
    # two-week trend.
    if "tomorrow" in tf or "tonight" in tf or "today" in tf:
        return 1
    if "week" in tf:
        try:
            return int(re.search(r"(\d+)", tf).group(1)) * 7
        except (AttributeError, ValueError):
            return default
    if "month" in tf:
        return 30
    if "day" in tf:
        try:
            return int(re.search(r"(\d+)", tf).group(1))
        except (AttributeError, ValueError):
            return default
    return default


def infer_subdomain(metric_hint):
    """Subdomain from the metric hint's keyword vocabulary (#813 — this emitted
    set MUST stay covered by prediction_windows.SUBDOMAIN_TO_DOMAIN)."""
    if metric_hint:
        mh = metric_hint.lower()
        for sd_key in ["sleep", "hrv", "recovery", "weight", "calories", "protein", "glucose", "training", "mood", "stress"]:
            if sd_key in mh:
                return sd_key
    return "general"


def build_prediction_record(coach_id, generation_date, claim, eval_spec, confidence, decision_class):
    """The canonical PREDICTION# item for a coach claim — the ONE place emission
    status/gradeable_by are decided (emission_status above). Callers pass the
    already-built eval_spec so the gradable-vs-qualitative routing they metered
    stays exactly what gets written."""
    slug = re.sub(r"[^a-z0-9]+", "_", claim.lower()[:40]).strip("_")
    pred_id = f"pred_{generation_date.replace('-', '')}_{slug}"
    status, gradeable_by = emission_status(eval_spec)
    return {
        "pk": f"COACH#{coach_id}",
        "sk": f"PREDICTION#{pred_id}",
        "prediction_id": pred_id,
        "coach_id": coach_id,
        "created_date": generation_date,
        "claim_natural": claim,
        "evaluation": eval_spec,
        "confidence": confidence,
        "subdomain": infer_subdomain(eval_spec.get("metric")),
        "confounders_noted": [],
        "status": status,
        "gradeable_by": gradeable_by,
        "outcome": None,
        "outcome_date": None,
        "outcome_notes": None,
        "decision_class": decision_class,
        "surfaced_to_subject": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
