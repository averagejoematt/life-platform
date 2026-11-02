"""tests/test_reader_truth_portrait_signals_5596.py — the portrait's Mind and Connection
tiles are two signals (#5596).

qa-smoke 2026-11-02 06:19Z held qa-smoke-failures on a home-page high (finding 539c6d,
confirmed on a second pass) that set the Start portrait's "Mind · journal" tile (journal
ENTRIES) against its "Connection · logged interactions" tile (logged SOCIAL INTERACTIONS)
as a temporal contradiction. Owner ruling 2026-11-02: both statements are factual and
describe different signals; fix the QA rule, not the copy, and keep real defects
flaggable. WIRE is the recorded judge output from `/aws/lambda/life-platform-qa-smoke`'s
`[QA] DETAIL … full note (837 chars)` line; PARAPHRASE/MUTATION notes are the guards.
Every test passes `today` explicitly — no clock read (#4848).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambdas"))

from operational import (
    reader_truth_qa as Q,  # noqa: E402
    reader_truth_rulings as R,  # noqa: E402
)

_START = "2026-09-06"
_TODAY = "2026-11-01"  # Day 57, the wire frame (06:19Z on 11-02 is 11-01 Pacific)

WIRE_539C6D = (
    "Surface 1 states 'Mind · journal 2 entries in 57 days, the last on 9 Sep.' Day 1 of the experiment is "
    "2026-09-06 (Saturday). September 9 is Day 4. The phrasing '2 entries in 57 days, the last on 9 Sep' "
    "asserts that the most recent journal entry occurred on Day 4, with no entries in the intervening 53 days "
    "(Days 5–57). However, Surface 1 also states 'Connection · logged interactions — None logged in the last "
    "thirty days. The journal went quiet; so did this.' This creates an internal contradiction: if the journal "
    "'went quiet' in the last 30 days, the last entry cannot be on Day 4 (57 days ago), because Day 4 is before "
    "the 30-day window. The two statements are mutually incompatible on a 57-day timeline. The '2 entries in 57 "
    "days, the last on 9 Sep' phrasing is impossible if interpreted as the final entry within the 57-day cycle."
)

# PARAPHRASE — the same objection with no tile prefixes and none of the wire's wording.
PARAPHRASE = (
    "The home page reports '2 entries in 57 days, the last on 9 Sep' yet the neighbouring tile reads "
    "'None logged in the last thirty days' and 'The journal went quiet; so did this'. Day 57 makes these "
    "two timelines irreconcilable."
)


def _f(note, page="/", category="temporal_contradiction", severity="high"):
    return {"page": page, "category": category, "severity": severity, "note": note}


def _fired(finding, today=_TODAY):
    return [rid for rid, _l, fires, _r in R.advisory_rulings(_START, today) if fires(finding)]


def test_the_wire_note_is_adjudicated_through_the_ledger():
    assert R.is_portrait_distinct_signals(_f(WIRE_539C6D), _TODAY)
    assert "portrait_distinct_signals" in _fired(_f(WIRE_539C6D))


def test_wording_independent():
    assert R.is_portrait_distinct_signals(_f(PARAPHRASE), _TODAY)


def test_a_zero_journal_count_is_consistent_too():
    note = "'Mind · journal 0 entries in 57 days.' beside 'Connection · logged interactions — None logged in the last thirty days.'"
    assert R.is_portrait_distinct_signals(_f(note), _TODAY)


# ── the residue that must keep gating ─────────────────────────────────────────


def test_one_signal_stated_two_incompatible_ways_still_gates():
    """The same tile (journal entries) with two different counts IS a contradiction."""
    note = (
        "Surface 1 states 'Mind · journal 2 entries in 57 days, the last on 9 Sep.' but also "
        "'Mind · journal 5 entries in 57 days, the last on 9 Sep.' beside 'Connection · logged interactions "
        "— None logged in the last thirty days.' Two journal counts for one cycle cannot both be true."
    )
    assert not R.is_portrait_distinct_signals(_f(note), _TODAY)
    assert "portrait_distinct_signals" not in _fired(_f(note))


def test_two_incompatible_last_dates_still_gate():
    note = (
        "'Mind · journal 2 entries in 57 days, the last on 9 Sep.' and '2 entries in 57 days, the last on 12 Sep' "
        "beside 'None logged in the last thirty days. The journal went quiet; so did this.'"
    )
    assert not R.is_portrait_distinct_signals(_f(note), _TODAY)


def test_a_journal_entry_inside_the_window_beside_went_quiet_still_gates():
    """'The journal went quiet' is false when the last entry is inside the thirty days."""
    note = WIRE_539C6D.replace("9 Sep", "28 Oct")
    assert not R.is_portrait_distinct_signals(_f(note), _TODAY)


def test_scoped_to_the_home_page_and_its_category():
    assert not R.is_portrait_distinct_signals(_f(WIRE_539C6D, page="/story/"), _TODAY)
    assert not R.is_portrait_distinct_signals(_f(WIRE_539C6D, category="audience_violation"), _TODAY)


def test_needs_both_tiles_quoted():
    note = "Surface 1 states 'Mind · journal 2 entries in 57 days, the last on 9 Sep.' but Day 57 is too long."
    assert not R.is_portrait_distinct_signals(_f(note), _TODAY)


def test_a_quoted_span_from_outside_the_portrait_refuses_it():
    note = WIRE_539C6D + " The chapter says 'The Monday afternoon walk covered 5.4 miles'."
    assert not R.is_portrait_distinct_signals(_f(note), _TODAY)


def test_fails_closed_without_a_clock():
    assert not R.is_portrait_distinct_signals(_f(WIRE_539C6D), None)
    assert not R.is_portrait_distinct_signals(_f(""), _TODAY)
    assert not R.is_portrait_distinct_signals(_f(None), _TODAY)


def test_demotes_never_drops():
    ids = {rid for rid, _l, _fires, _r in R.advisory_rulings(_START, _TODAY)}
    assert "portrait_distinct_signals" in ids


def test_the_rubric_states_the_distinction():
    """Owner ruling 2026-11-02: the rubric itself recognises journal entries vs logged
    social interactions as different signals — and keeps the real defect flaggable."""
    prompt = Q.build_prompt([{"name": "Home", "path": "/", "prose": "x"}], Q.phase_context(_TODAY))
    flat = " ".join(prompt.split())
    assert "counts JOURNAL ENTRIES" in flat
    assert "counts LOGGED SOCIAL INTERACTIONS" in flat
    assert "Still flag ONE tile stating its own signal two incompatible ways" in flat
    assert "a last entry INSIDE the window" in flat
