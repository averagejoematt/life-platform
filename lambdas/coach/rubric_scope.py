"""rubric_scope.py — which arms of the N-06 judge rubric apply to which surface (#4343, #4188).

The coach quality gate grades a draft on persona arms (anti-patterns from the coach's voice
spec, cross-coach similarity, voice distinctiveness) and on honesty arms (the decision-class
ceiling, number grounding, and the deterministic reader and served-fact checks folded in by
`ai_calls`). Every surface was graded on all of them.

The head coach's DAILY lead read (`coach/lead_daily_read.py`) is not a persona narrative. It
is <= 90 words about Matthew for friends and family, built so that every figure is copied
from a cited block. The persona arms graded it against a brief it was never given: on
2026-09-28 (score 18) and 2026-09-29 (score 15) the judge held it for "Narrating the
dashboard (listing metrics without interpreting them)", for sounding like the domain coaches
("Both outputs open with metric recitation"), and for a voice score of 5. Neither draft had
an honesty finding: every number was cited, and the reader and served-fact checks were
clean. The door has served the 09-27 read ever since, and its "4.4 pounds per week" is now
outside the served rate's CI.

This is a RUBRIC SCOPING, not a threshold drop. `PASS_SCORE_THRESHOLD` and
`VOICE_DISTINCTIVENESS_MINIMUM` are unchanged, and every other surface is graded exactly as
before. For a scoped surface the out-of-scope arms are moved aside, not deleted: they stay
on the report under `out_of_rubric` so they can still be read. The verdict then rests on
the in-scope arms. When no in-scope finding remains, the judge's composite score (which
counted the out-of-scope arms) is recorded as `rubric_scope.prior_score`, and `score` is
set to the pass threshold, the same move `judge_hit_filter` makes for a phantom hit. Number
grounding is applied after this and can still fail the report on its own, as can the
reader, served-fact and exact-cited checks downstream.
"""

from __future__ import annotations

import json
from typing import Any

# surface -> the report arms that are NOT part of that surface's rubric.
OUT_OF_RUBRIC = {
    "lead_daily": ("anti_pattern_violations", "cross_coach_similarity_flags", "voice_distinctiveness_score"),
}
LOG_TAG = "RUBRIC_SCOPED"
_VOICE_SUGGESTION = "Voice distinctiveness below minimum threshold"


def surface_of(generation_brief: Any) -> str:
    return str((generation_brief or {}).get("surface") or "") if isinstance(generation_brief, dict) else ""


def skips_cross_coach(generation_brief: Any) -> bool:
    """A surface whose rubric has no cross-coach arm needs no peer outputs fetched or sent."""
    return "cross_coach_similarity_flags" in OUT_OF_RUBRIC.get(surface_of(generation_brief), ())


def apply(result: dict, generation_brief: Any, *, pass_threshold: int, coach_id: str = "", logger=None) -> dict:
    """Scope `result` (the judge's report) to the surface's rubric. Mutates and returns it."""
    surface = surface_of(generation_brief)
    arms = OUT_OF_RUBRIC.get(surface)
    if not arms:
        return result
    aside = {arm: result.pop(arm) for arm in arms if arm in result}
    result["out_of_rubric"] = aside
    result["suggestions"] = [s for s in result.get("suggestions") or [] if s != _VOICE_SUGGESTION]
    in_scope = result.get("decision_class_violations") or result.get("number_grounding_violations")
    record = {"surface": surface, "prior_score": result.get("score"), "prior_passed": result.get("passed")}
    if not in_scope:
        result["passed"] = True
        if not isinstance(record["prior_score"], (int, float)) or record["prior_score"] < pass_threshold:
            result["score"] = pass_threshold
        record["verdict"] = "restored" if record["prior_passed"] is False or result["score"] != record["prior_score"] else "pass"
    else:
        record["verdict"] = "unchanged"
    result["rubric_scope"] = record
    line = f"{LOG_TAG} " + json.dumps({"coach_id": coach_id, **record, "out_of_rubric": sorted(aside)}, default=str, sort_keys=True)
    (logger.info if logger is not None else print)(line)
    return result
