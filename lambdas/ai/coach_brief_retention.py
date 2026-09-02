r"""coach_brief_retention.py — the coach BRIEF's quality-gate eval-retention translator (#744, #3202).

One job: turn a fired `coach-quality-gate` report into the `eval_retention.retain()`
call for the `coach_brief` surface. Extracted from `ai_calls` by #3202, which needed to
retain the grounding findings + allow-list + facts and could not spend the lines: the
#1665 size ratchet asks for exactly this — "a cohesive helper module beside it" — rather
than a baseline raise. `ai_calls._retain_coach_brief_flag` re-exports the function, so no
caller's or test's import path changes.

Named for the coach BRIEF, not for the gate. The first cut was `coach_gate_retention.py`,
which (a) read as "retention belonging to the gate" — the one thing this explicitly is not,
since it enforces nothing and is fail-soft — and (b) matched `scripts/gate_census.py`'s
`_GUARD_NAME` filename pattern (`.*_gate[a-z0-9_]*\.py$`), landing a non-gate in the #3000
ratcheted gate inventory. Absorbing that into the ceiling would have taught the next author
to bump on noise and corrupted the denominator #2578 is measured against; the census's own
filename-only classification is filed separately.

Everything here is fail-soft by contract: retention is eval data, never a reader-facing
surface, and it must never raise into the coach pipeline.
"""

from typing import Any, Optional

from ai.quality_gate_contract import grounding_from_brief, report_findings


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

        # #3202: the ONE class that held two reader-facing coaches dark every cycle was the
        # one this retention dropped — the record carried the draft text and not the reason,
        # so root-causing the 2026-08-26 holds meant rebuilding the drafts out of DDB and
        # re-running the grounder offline. With the findings, the allow-list and the facts
        # retained, the next diagnosis of a hold is a query. The report -> findings mapping
        # itself moved to `quality_gate_contract.report_findings` (#3414) so the async
        # board channel retains the SAME record shape — one mapping, two surfaces.
        findings = report_findings(report)
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
