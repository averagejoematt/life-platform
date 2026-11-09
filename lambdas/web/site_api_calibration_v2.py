"""lambdas/web/site_api_calibration_v2.py — ``assessment_v2`` on /api/calibration (owner requirement 2026-11-09).

DARK and ADDITIVE: the calibration-v2 assessment (``experiment.calibration_v2``, ``docs/methods/CALIBRATION_V2.md``)
per coach and per platform stratum, this season, served beside the v1 fields. No v1 field reads it, and no page renders
it until the owner adopts the method. It reads the SAME publication-eligible decided rows as the record and the
comparison beside it, so private calls never reach it (``tests/test_calibration_v2_privacy.py``).
"""

from __future__ import annotations

from coach import coach_baseline, coach_record
from experiment import calibration_core, calibration_v2

from web.site_api_common import logger


def baseline_paired(decided) -> dict:
    """calibration-v2's skill input (``calibration_v2.skill_vs_baseline``): per record, (coach right, nothing-changes
    right) over the SAME decided rows ``coach_baseline.comparison_block`` tallies, with the same unscorable /
    not-yet-scored split — so v2's question 3 is asked of exactly the calls the served comparison counts."""
    out: dict = {}
    for row in decided or []:
        status = coach_record.graded_status(row)
        key = coach_baseline.record_of(row) if status else None
        if key is None:
            continue
        rec = out.setdefault(key, {"pairs": [], "unscorable": 0, "not_yet_scored": 0})
        bl = row.get("baseline")
        if not isinstance(bl, dict) or bl.get("rule") != coach_baseline.RULE_ID:
            rec["not_yet_scored"] += 1
        elif bl.get("right") is None:
            rec["unscorable"] += 1
        else:
            rec["pairs"].append((status == "confirmed", bool(bl["right"])))
    return out


def _assess_rows(rows) -> dict:
    return calibration_v2.assess(calibration_core.pairs_from_prediction_records(rows), baseline_paired(rows))


def assessment_v2(coach_decided: dict, strata: dict) -> dict | None:
    """``{constants…, status, scope, coaches: {cid: assessment}, strata: {name: assessment}}``. ``coach_decided`` maps a
    coach to its season decided rows; ``strata`` maps the other platform strata to their (confidence, outcome) pairs
    (no baseline: their skill answer is "no baseline"). The strata are never pooled. Fails soft to None so it can never
    take the v1 payload down."""
    try:
        season_rows = [r for rows in coach_decided.values() for r in rows]
        return {
            **calibration_v2.constants(),
            "status": "proposed, not adopted; the v1 labels beside it are what the site shows",
            "scope": "season",
            "coaches": {cid: _assess_rows(rows) for cid, rows in coach_decided.items()},
            "strata": {"coaches": _assess_rows(season_rows), **{name: calibration_v2.assess(pairs) for name, pairs in strata.items()}},
        }
    except Exception as e:  # noqa: BLE001 — additive block: never take the v1 scoreboard down
        logger.error(f"[calibration] assessment_v2: {e}")
        return None
