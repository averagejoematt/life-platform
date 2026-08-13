"""#2575 — the Day-1 temporal ruling, made explicit so it cannot rot back into noise.

The 2026-08-11 nightly published:

    FAIL [content_truth] Reader Truth / reader_truth:verdict: 2 high truth finding(s) at Day 1:
      [temporal_contradiction] Home page states 'This attempt starts at the Day-1 weigh-in, aimed at 185 lbs held for 90 ...'
      [temporal_contradiction] /api/sleep_detail reports 'night_of': '2026-08-09' (the night before Day 1) with 'as_of_date': ...

THE RULING: **the surfaces are correct; the check was wrong.** Both findings are
genesis-week artefacts that are true by construction:

  * the Home string is durable design copy describing what the experiment DOES. The
    rubric's false-positive ledger has carried it since 2026-08-09, scoped to the
    pre-start countdown — and Day 1 is not pre-start, so it recurred one phase later.
  * `/api/sleep_detail` publishing `night_of: 2026-08-09` under `as_of_date:
    2026-08-10` is the #1923 wake-date frame: these metrics are keyed to the MORNING
    they were recorded against, so the night behind Day 1's morning is necessarily the
    night before Day 1. There is no cycle in which this does not happen on Day 1.

WHY NOT CORRECT THE SURFACE. The deterministic half already grades this payload and
already passes it: `phase_plausibility._night_label_findings` (R5, #1968) demands that
a night-scoped figure NAME its night, and the live payload names it three ways. ADR-105
puts deterministic computation ahead of the LLM verdict, so the LLM is the layer that
is wrong here. Verified against the live payload while writing this: `frame:
"last_night"`, `night_of: "2026-08-10"`, and a `figure_scope` block spelling the
convention out in prose.

These tests pin the clauses. Not "the prompt contains a phrase" for its own sake — the
ledger IS the rule in this module (it is how the 2026-08-09 ruling was recorded), so an
unpinned clause is a ruling one reword away from being lost, and #1966 noise is what
grows back in its place.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from operational import phase_plausibility as pp, reader_truth_qa as rt  # noqa: E402

# The live `/api/sleep_detail` body on 2026-08-11, trimmed to the fields under dispute.
SLEEP_DETAIL_DAY1 = {
    "total_sleep_hours": 8.2,
    "recovery_score": 54.0,
    "hrv": 41.1,
    "rhr": 56.0,
    "as_of_date": "2026-08-10",
    "frame": "last_night",
    "night_of": "2026-08-09",
}


DAY_1_PHASE = {"today": "2026-08-10", "start_date": "2026-08-10", "day_n": 1, "pre_start": False, "days_until_start": 0}


def _rubric():
    return rt.build_prompt([{"name": "Home", "path": "/", "prose": "x"}], DAY_1_PHASE)


def test_the_design_copy_clause_is_no_longer_pre_start_scoped():
    """(a) The recurrence cause: the clause read as pre-start-only, so Day 1 re-flagged it."""
    rubric = _rubric()
    assert "starts at the Day-1 weigh-in" in rubric, "the ledger must still carry the exact string"
    assert "EVERY phase — before Day 1, ON Day 1, and after" in rubric, (
        "the durable-design-copy clause must name Day 1 explicitly; 'including pre-start' is what "
        "let the identical string re-fail one phase later"
    )


def test_the_wake_date_frame_clause_survives_for_PAGE_PROSE():
    """(b) The clause, as #2613's retirement left it.

    The clause still exists, because HTML pages are still the LLM's: no deterministic
    rule reads a night narrated in page prose. What left it is the JSON half — on the
    four code-swept API payloads the whole pre-cycle-date question is now
    phase_plausibility's (R6/R7), so the rubric no longer names `night_of`, no longer
    argues about a surface's payload, and no longer carries the two residual promises.
    Those promises did not evaporate; they became code, asserted just below.
    """
    rubric = _rubric()
    assert "the day BEFORE the cycle start" in rubric
    assert "on a page dated on or after the cycle start" in rubric


def test_the_clauses_two_residual_promises_are_now_CODE():
    """#2613: "still flag a night that precedes the cycle start by MORE than one day"
    left the rubric and became R7 — which, unlike a prose clause, cannot be argued with.

    Day 1's own payload is the fixture: `night_of` one day before genesis passes (the
    #1923 frame), two days before reds.
    """
    genesis = DAY_1_PHASE["start_date"]
    assert pp.check_payload("/api/sleep_detail", SLEEP_DETAIL_DAY1, 1, strict=True, start_date=genesis) == []
    two_days_early = dict(SLEEP_DETAIL_DAY1, night_of="2026-08-08")
    bad = pp.check_payload("/api/sleep_detail", two_days_early, 1, strict=True, start_date=genesis)
    assert len(bad) == 1 and bad[0]["severity"] == "high" and "names a night before" in bad[0]["note"]


def test_the_deterministic_layer_already_passes_the_disputed_payload():
    """The ruling's load-bearing premise: R5 (#1968) grades this payload and finds nothing.

    If this ever fails, the ruling above is void — the payload really would be
    unlabelled, and the LLM finding would be right. The clause and the deterministic
    rule have to agree, or the exemption is hiding a real defect.
    """
    findings = pp._night_label_findings("/api/sleep_detail", SLEEP_DETAIL_DAY1)
    assert findings == [], f"R5 must accept the labelled payload the clause exempts: {findings}"


def test_an_unlabelled_night_scoped_payload_still_fails_r5():
    """Mutation proof for the premise: strip the night label and the deterministic rule reds."""
    stripped = {k: v for k, v in SLEEP_DETAIL_DAY1.items() if k not in ("night_of", "frame")}
    findings = pp._night_label_findings("/api/sleep_detail", stripped)
    assert len(findings) == 1 and findings[0]["category"] == "temporal_contradiction"
    assert "no night label" in findings[0]["note"]
