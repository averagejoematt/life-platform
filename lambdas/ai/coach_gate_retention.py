"""coach_gate_retention.py — the coach quality gate's eval-retention translator (#744, #3202).

One job: turn a fired `coach-quality-gate` report into the `eval_retention.retain()`
call for the `coach_brief` surface. Extracted from `ai_calls` by #3202, which needed to
retain the grounding findings + allow-list + facts and could not spend the lines: the
#1665 size ratchet asks for exactly this — "a cohesive helper module beside it" — rather
than a baseline raise. `ai_calls._retain_coach_brief_flag` re-exports the function, so no
caller's or test's import path changes.

Everything here is fail-soft by contract: retention is eval data, never a reader-facing
surface, and it must never raise into the coach pipeline.
"""

from typing import Any, Optional

from ai.quality_gate_contract import grounding_from_brief


def retain_coach_brief_flag(
    coach_id: str, verdict: str, draft: Any, final: Any, report: dict, generation_brief: Optional[dict] = None
) -> None:
    """#744: persist a fired coach-quality-gate verdict (draft + findings + disposition)
    as eval data via the SAME `eval_retention.py` mechanism #812 wired for the other 5
    surfaces. `ai_calls._enforce_quality_gate` is the ORIGINAL surface #744 named — the
    highest-fire-rate ADR-104-adjacent gate in the platform (10.2% of 206 logged verdicts
    over 30 days, ADR-108) — and #812 did not reach it (it wired the 5 newer
    golden_surface_eval surfaces only). Fail-soft: never affects the coach pipeline.
    """
    try:
        from experiment import eval_retention

        findings = []
        for v in report.get("anti_pattern_violations") or []:
            phrase = v.get("phrase") if isinstance(v, dict) else v
            if phrase:
                findings.append({"type": "anti_pattern", "detail": phrase})
        for v in report.get("decision_class_violations") or []:
            if isinstance(v, dict):
                findings.append({"type": "decision_class", "detail": v.get("excerpt", "")})
        for flag in report.get("cross_coach_similarity_flags") or []:
            if isinstance(flag, dict):
                findings.append({"type": "cross_coach_similarity", "detail": flag.get("reason", "")})
        for v in report.get("cycle_boundary_violations") or []:  # #1973
            if isinstance(v, dict):
                findings.append({"type": "cycle_boundary", "detail": v.get("reason", "")})
        # #3202: the ONE class that held two reader-facing coaches dark every cycle was the
        # one this retention dropped — the record carried the draft text and not the reason,
        # so root-causing the 2026-08-26 holds meant rebuilding the drafts out of DDB and
        # re-running the grounder offline. With the findings, the allow-list and the facts
        # retained, the next diagnosis of a hold is a query.
        _raw_gr = report.get("number_grounding")
        _gr: dict = _raw_gr if isinstance(_raw_gr, dict) else {}
        findings += [{"type": f.get("type"), "detail": f.get("detail", "")} for f in (_gr.get("findings") or []) if isinstance(f, dict)]
        allowed, facts = grounding_from_brief(generation_brief)
        eval_retention.retain(
            "coach_brief",
            verdict,
            draft=draft or "",
            final=final or "",
            findings=findings,
            allowed=allowed,
            facts=facts,
            # `extra` stays exactly the two keys #744 defined — the grounding verdict is
            # recoverable from the retained findings, and tests/test_coach_quality_gate_390.py
            # pins this dict by equality on purpose.
            extra={"coach_id": coach_id, "score": report.get("score")},
        )
    except Exception:  # noqa: BLE001 — retention is never load-bearing
        pass
