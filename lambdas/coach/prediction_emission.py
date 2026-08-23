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

import re
from datetime import datetime, timezone

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


def emission_status(eval_spec):
    """(status, gradeable_by) for a newly-emitted PREDICTION# — THE contract.

    A spec the evaluator can grade → ("pending", "deterministic"). A qualitative
    spec → ("observation", "none"): on the record, never pending-forever."""
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
