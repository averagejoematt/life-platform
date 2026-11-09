"""web/verification_fields.py — the additive verification fields of the public call routes (owner 2026-11-09).

WHAT IS SERVED (additive; no existing field or label changes):

  * per item on ``/api/ledger_export`` and ``/api/predictions`` — ``item_fields``:
      ``evaluator_version``  the row's stored ``evaluator_version`` stamp (null when the row has none);
      ``algo_version``       the version that WROTE the grade text (``outcome_notes.algo_version``, null when absent);
      ``verification``       ``{outcome, verified_at, ruleset_version, classification_validated}`` read off the row's
                             ``latest_verification`` pointer (``coach.verification_record``) — NULL when the call has
                             no verification record. Never inferred from a version number.
  * top level on both routes — ``verification_summary``: ``{reproduced, corrected, could_not_verify, none}`` counted
    over the SAME rows the route's own total counts (the ledger's served items; ``/api/predictions``' season rows).
  * ``/api/calibration`` — ``verified_block``: ``{n, confirmed, accuracy_pct, accuracy_ci95, baseline}`` over the
    decided calls whose verdict was REPRODUCED or CORRECTED, scored by the same ``calibration_core`` functions and the
    same "nothing changes" comparison (``coach_baseline.comparison_block``) as the unverified numbers, on exactly
    those calls. Null until a verification record exists in that set.

PRIVACY. Every number here is taken over rows the route already counts — and those reach a handler only through
``web.narrative_publication.PublicationTable``, which omits a private (journal / State of Mind / diary-derived) call
and every row naming one before any handler runs (``common.prediction_publication``, method v2). No new read, no new
denominator: ``tests/test_call_publication_privacy.py`` walks every route with and without private verified calls.
"""

from __future__ import annotations

from typing import Any, Iterable

from coach import coach_baseline, grade_corrections, verification_record
from experiment import calibration_core

SUMMARY_KEYS = verification_record.OUTCOMES + ("none",)


def item_fields(row: dict) -> dict:
    ver = (row or {}).get("evaluator_version")
    return {
        "evaluator_version": None if ver is None else str(ver),
        "algo_version": grade_corrections.grade_text_version(row or {}),
        "verification": verification_record.served(row or {}),
    }


def summary(verifications: Iterable[Any]) -> dict:
    """Counts by outcome over served ``verification`` objects (``None`` = no record)."""
    out = {k: 0 for k in SUMMARY_KEYS}
    for v in verifications:
        out[v["outcome"] if isinstance(v, dict) and v.get("outcome") in verification_record.OUTCOMES else "none"] += 1
    return out


def verified_block(decided: Iterable[dict]) -> dict | None:
    """The verified-only numbers over decided rows; None when no row in the set carries a verification record."""
    rows = [r for r in decided or [] if isinstance(r, dict)]
    if not any(verification_record.served(r) for r in rows):
        return None
    verified = [r for r in rows if verification_record.is_verified(r)]
    s = calibration_core.score_pairs(calibration_core.pairs_from_prediction_records(verified))
    return {
        "n": s["n"],
        "confirmed": s["confirmed"],
        "accuracy_pct": s["accuracy_pct"],
        "accuracy_ci95": s["accuracy_ci95"],
        "baseline": coach_baseline.comparison_block(verified),
    }


def attach_stratum_extras(platform: dict, strata_pairs: dict, coach_decided: list) -> None:
    """Owner 2026-11-09, additive — changes no existing field. Each season stratum gains:

    * ``accuracy_pct`` / ``accuracy_ci95`` (95% Wilson) — ``calibration_core.score_pairs`` over the stratum's OWN
      pairs, the same function ``score_strata`` scores each stratum with (``n`` is already served beside them);
    * ``verified`` — the coaches' verified-only numbers (``verified_block``, over exactly the
      decided rows the stratum is scored on), null for the hypothesis and forecast strata, which have no
      verification record.

    Computed here, not in ``experiment.calibration_core``, so the scorer, its OSS parity vectors and its methods
    fingerprint are untouched."""
    for name, stratum in (platform.get("strata") or {}).items():
        scored = calibration_core.score_pairs(strata_pairs.get(name) or [])
        stratum["accuracy_pct"] = scored["accuracy_pct"]
        stratum["accuracy_ci95"] = scored["accuracy_ci95"]
        stratum["verified"] = verified_block(coach_decided) if name == "coaches" else None
