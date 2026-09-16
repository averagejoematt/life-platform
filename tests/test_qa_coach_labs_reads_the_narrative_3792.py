"""tests/test_qa_coach_labs_reads_the_narrative_3792.py — #3792 box 3.

The issue says *"the nightly that ran red nine nights never watched this card."* That
turned out to be wrong in an instructive way: `check_coach_labs_truth` HAS scanned
`/api/coaching-dashboard` `coaches[].position_summary` since #1993. It was watching the
card. **It was reading 198 characters of it.**

MEASURED 2026-09-16T21:4xZ against the live surfaces, `/api/labs` serving
`total_draws: 8, latest_draw_date: 2026-04-03`:

    served position_summary (198 chars)            -> PASS
    stored COACH#labs_coach/OUTPUT#2026-09-16#...  -> FAIL
        "Three things need to move from future to present tense this week:
         schedule the April 3rd draw, lock the protocol, ..."

Same coach, same day, same defect, opposite verdicts. `position_summary` is
`audience_guard.public_blurb`'s truncation, so a claim two sentences into a 2,716-char
narrative is outside everything the module can see.

This is the THIRD time this check has gone quiet while the defect was live — #1993
(wording), #3728 (wording again), and now the scan WINDOW. The first two were fixed by
asserting the fact rather than the phrasing; this one is fixed by reading the whole text.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAMBDAS = ROOT / "lambdas"
if str(LAMBDAS) not in sys.path:
    sys.path.insert(0, str(LAMBDAS))

from operational.qa_check_coach_labs import assess_coach_labs_truth  # noqa: E402

# The live /api/labs payload, verbatim shape.
_LABS = {"total_draws": 8, "latest_draw_date": "2026-04-03"}

# The served blurb, character-for-character as /api/coaching-dashboard returned it.
_SERVED_BLURB = (
    "I'm watching three administrative preconditions that must lock in place this week: the April 3rd draw "
    "scheduled, the protocol finalized, and results entry confirmed. Before the draw, I've asked him…"
)

# The opening of the stored narrative the blurb was cut from.
_STORED_NARRATIVE = (
    "Three things need to move from future to present tense this week: schedule the April 3rd draw, lock the "
    "protocol, and confirm where results will be entered. These are not tasks in a queue — they are the "
    "preconditions for every interpretation I'll be doing for the next 169 days."
)

_COACHES = [{"coach_id": "labs", "position_summary": _SERVED_BLURB}]


def test_THE_GAP_the_served_blurb_alone_reports_a_PASS():
    """The measurement that makes the fix necessary — and the must-fail control for it.

    Drop `stored_narratives` from `check_coach_labs_truth` and the nightly returns to
    exactly this verdict over exactly this live defect.
    """
    ok, msg = assess_coach_labs_truth(_LABS, _COACHES)
    assert ok, "the 198-char blurb no longer passes — re-measure the gap rather than deleting this control"
    assert "no served coach text contradicts" in msg


def test_THE_FIX_the_stored_narrative_is_scanned_and_FAILS():
    ok, msg = assess_coach_labs_truth(_LABS, _COACHES, stored_narratives=[("labs:stored OUTPUT#2026-09-16", _STORED_NARRATIVE)])
    assert not ok, "the narrative behind the card still passes — the check is reading a window, not the text (#3792)"
    assert "ARRANGING a lab draw" in msg
    assert "labs:stored" in msg, "the finding must name WHICH text it came from, or a fix cannot be aimed"


def test_a_CLEAN_narrative_still_passes():
    """The control in the opposite direction. Widening the scan must not make the check
    unfalsifiable-in-reverse: correct prose about the completed panel stays green, and a
    coach naming the NEXT panel is still allowed to say so."""
    clean = (
        "Your April 3rd panel is 166 days old and its results are in front of me: total IgE at 339 kU/L. "
        "When we book the next draw I want a fasting morning slot, but nothing about April is outstanding."
    )
    ok, msg = assess_coach_labs_truth(
        _LABS, [{"coach_id": "labs", "position_summary": clean[:198]}], stored_narratives=[("labs:stored", clean)]
    )
    assert ok, f"honest prose about a completed panel was flagged: {msg}"


def test_an_UNAVAILABLE_narrative_does_not_silently_look_like_coverage():
    """A DDB read that fails must degrade LOUDLY. `stored_narratives=[]` is the same
    input shape as 'the read returned nothing', so the caller — not the assessor — owns
    saying so; this pins the assessor half: no stored text means no stored finding, and
    the verdict is identical to the pre-fix blurb-only scan."""
    ok_none, msg_none = assess_coach_labs_truth(_LABS, _COACHES, stored_narratives=[])
    ok_missing, _ = assess_coach_labs_truth(_LABS, _COACHES, stored_narratives=None)
    assert ok_none is ok_missing is True
    assert "DEGRADED" not in msg_none, "the assessor must not invent a degradation notice it cannot observe"


def test_the_CHECK_appends_a_degraded_notice_when_the_narrative_is_missing():
    """And the caller half: `check_coach_labs_truth` says DEGRADED rather than reporting a
    clean green over a scan that never happened."""
    src = (LAMBDAS / "operational" / "qa_check_coach_labs.py").read_text(encoding="utf-8")
    assert "DEGRADED: stored narrative unavailable" in src
    assert "stored_narratives=stored" in src, "the check does not actually pass the narratives it read"
