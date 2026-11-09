"""lambdas/web/site_api_calibration_v2.py — ``assessment_v2`` on /api/calibration (owner requirement 2026-11-09).

ADOPTED (owner ruling 2026-11-09): the calibration-v2 assessment (``experiment.calibration_v2``,
``docs/methods/CALIBRATION_V2.md``) per coach and per platform stratum, this season, is the authority for every
calibration verdict the site shows or serves. The v1 labels (``calibration`` / ``label`` / ``score`` from
``calibration_core``) stay in the payloads for API compatibility only, listed as deprecated in ``calibration_method``;
no reader surface renders them. It reads the SAME publication-eligible decided rows as the record and the comparison
beside it, so private calls never reach it (``tests/test_calibration_v2_privacy.py``).
"""

from __future__ import annotations

from coach import coach_baseline, coach_record
from experiment import calibration_core, calibration_v2

from web.site_api_common import logger

#: The date the owner adopted calibration-v2 (ruling of 2026-11-09).
ADOPTED = "2026-11-09"
STATUS = "adopted"

#: The v1 verdict fields kept in the payloads ONLY for API compatibility. No reader surface renders them.
DEPRECATED_V1_FIELDS = ("calibration", "label", "score")

#: The calibration method's version history, oldest first. A new version is a new entry, never an edit.
METHOD_HISTORY = (
    {
        "version": "calibration-v1",
        "until": ADOPTED,
        "note": "One label per forecaster from a fixed ±0.15 mean-gap trip and a Brier-skill gate; retired because it "
        "answered three different questions with one threshold.",
    },
    {
        "version": calibration_v2.METHOD_VERSION,
        "effective": ADOPTED,
        "note": "Three separate questions — estimability across confidence levels, over/under-confidence at an "
        "observed level (exact test, Holm-corrected), and skill against the same-call baseline — each with its "
        "own interval; adopted by the owner on 2026-11-09.",
    },
)


def method_block() -> dict:
    """``calibration_method`` on /api/calibration: which method is the authority, since when, and which v1 fields are
    deprecated — the API keeps them for compatibility, the site no longer shows them."""
    return {
        "version": calibration_v2.METHOD_VERSION,
        "status": STATUS,
        "adopted": ADOPTED,
        "authority": "assessment_v2",
        "deprecated_fields": {
            "fields": list(DEPRECATED_V1_FIELDS),
            "where": "coaches[], platform, platform.strata.*, hypotheses, interval_forecasts and each lifetime block",
            "note": "calibration-v1 labels, kept for API compatibility only and no longer shown on any page. Read "
            "assessment_v2 for the calibration verdict.",
        },
        "history": [dict(h) for h in METHOD_HISTORY],
        "methods_note": "docs/methods/CALIBRATION_V2.md",
    }


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


def answers(assessment: dict | None) -> dict | None:
    """The three answers of one assessment in words — ``{question: {result, short, wording}}`` — for a surface that
    carries the verdict beside other content (the huddle, the MCP track record). None when there is no assessment."""
    if not isinstance(assessment, dict):
        return None
    out: dict = {"method_version": assessment.get("method_version"), "n": assessment.get("n")}
    for q in ("estimability", "confidence_direction", "skill"):
        a = assessment.get(q) or {}
        out[q] = {"result": a.get("result"), "short": a.get("short"), "wording": a.get("wording")}
    return out


def coach_answers(decided_rows) -> dict | None:
    """One coach's three answers over its season decided rows — the same rows and the same assessment
    ``assessment_v2.coaches`` serves. Fails soft to None."""
    try:
        return answers(_assess_rows(decided_rows))
    except Exception as e:  # noqa: BLE001 — a companion block: never take its host payload down
        logger.error(f"[calibration] coach_answers: {e}")
        return None


def assessment_v2(coach_decided: dict, strata: dict) -> dict | None:
    """``{constants…, status, adopted, method_history, scope, coaches: {cid: assessment}, strata: {name: assessment}}``.
    ``coach_decided`` maps a coach to its season decided rows; ``strata`` maps the other platform strata to their
    (confidence, outcome) pairs (no baseline: their skill answer is "no baseline"). The strata are never pooled. Fails
    soft to None so it can never take the rest of the payload down."""
    try:
        season_rows = [r for rows in coach_decided.values() for r in rows]
        return {
            **calibration_v2.constants(),
            "status": STATUS,
            "adopted": ADOPTED,
            "method_history": [dict(h) for h in METHOD_HISTORY],
            "scope": "season",
            "coaches": {cid: _assess_rows(rows) for cid, rows in coach_decided.items()},
            "strata": {"coaches": _assess_rows(season_rows), **{name: calibration_v2.assess(pairs) for name, pairs in strata.items()}},
        }
    except Exception as e:  # noqa: BLE001 — never take the scoreboard down
        logger.error(f"[calibration] assessment_v2: {e}")
        return None
