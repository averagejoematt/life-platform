"""tests/test_reader_truth_uncited_objection_3379.py — the uncited-objection ruling.

#3379 (2026-08-31): qa-smoke FAILed on a home-page high whose note cites no
temporal value at all — an editorial labeling preference in a temporal_contradiction
costume. The ruling adjudicates the ABSENCE structurally (no date, day number, or
elapsed span in the judge's own sentences; quoted page copy excluded; a payload
date field refuses it). WIRE notes are recorded judge output pulled from
`/aws/lambda/life-platform-qa-smoke`'s `[QA] DETAIL … full note (N chars)` lines
(2026-08-31) and the fixtures already replayed in
tests/test_reader_truth_structural_rulings_3337.py; PARAPHRASE notes are the
mutation, never evidence a class exists.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambdas"))

from common.constants import EXPERIMENT_START_DATE  # noqa: E402
from operational import reader_truth_rulings as R  # noqa: E402

_START = EXPERIMENT_START_DATE
_TODAY = (date.fromisoformat(_START) + timedelta(days=14)).isoformat()  # Day 15, the wire frame


def _f(note, category="temporal_contradiction", page="/", severity="high"):
    return {"page": page, "category": category, "severity": severity, "note": note}


# WIRE — qa-smoke 2026-08-31, finding 539c6d (high, "confirmed on a second pass"),
# the note that held qa-smoke-failures in ALARM. Zero temporal citations.
# NOTE (2026-08-31, the September 1st launch re-anchor, Session O Phase D1): the home copy
# this note quotes ("every climb before this one ended the same way…") was retired from
# site/index.html for launch framing — an editorial decision, NOT a concession to the
# finding. The fixture stays VERBATIM: it is recorded judge output, the evidence that this
# class exists, and the ruling it proves is structural (an absence of temporal citations in
# the judge's own sentences), so it neither reads nor depends on the live page.
WIRE_539C6D = (
    "Home page states 'Every climb before this one ended the same way' and references "
    "'a drawer of devices measured everything and changed nothing.' The phrasing 'before "
    "this one' and the comparative framing treat prior cycles as historical record. "
    "However, the phrase 'every climb before this one ended the same way' asserts a "
    "pattern across multiple prior attempts. While prior cycles (1–13) are legitimate "
    "historical record and may be referenced, this sentence is written as present-tense "
    "narrative analysis of Matthew's past attempts, not as a labeled archive or separate "
    "historical section. It appears on the public home page as current editorial voice, "
    "not segregated as cycle history. The phrasing ambiguously blurs whether this is "
    "authored analysis of Cycle 14 or a historical reflection; if it is current-cycle "
    "prose (which the position on the home page suggests), it violates the principle "
    "that only explicitly labeled prior-cycle content may narrate those cycles. The "
    "sentence should either be moved to a labeled 'previous attempts' archive or "
    "reframed as 'In prior cycles, every climb ended…' to make its historical scope "
    "explicit on the current surface."
)

# WIRE — /api/vitals d1c6a0 (2026-08-31 sweep): names payload date fields, cites
# dates. A data claim; must never be adjudicated by this ruling.
WIRE_D1C6A0 = (
    "API payload timestamp generated_at is 2026-08-31T06:23:12Z, which is 2026-08-31 "
    "— one day AFTER the ground-truth today (2026-08-30, Day 14). The experiment "
    "phase ends at 2026-08-30; no data from 2026-08-31 can legitimately exist."
)


def test_the_wire_note_is_adjudicated():
    assert R.is_uncited_temporal_objection(_f(WIRE_539C6D))


def test_it_fires_through_the_ledger_table():
    ids = [rid for rid, _l, fires, _r in R.advisory_rulings(_START, _TODAY) if fires(_f(WIRE_539C6D))]
    assert "uncited_temporal_objection" in ids


def test_wording_independent():
    """PARAPHRASE — same objection, none of the vagueness adjectives, no shared phrasing.
    A structural ruling must not care."""
    para = (
        "The sentence frames earlier efforts as though they belong to the current "
        "narrative; a reader cannot tell from the surrounding copy that this reflects "
        "history rather than the present attempt. It reads as editorial voice."
    )
    assert R.is_uncited_temporal_objection(_f(para))


def test_spares_a_payload_dating_finding():
    assert not R.is_uncited_temporal_objection(_f(WIRE_D1C6A0, page="/api/vitals"))


def test_spares_a_genuine_impossibility_citing_a_span():
    note = "The page states a 57-day history of this cycle. A 57-day history is impossible."
    assert not R.is_uncited_temporal_objection(_f(note))


def test_spares_a_note_citing_a_day_number():
    note = "The banner reads as though written on Day 40, which has not occurred."
    assert not R.is_uncited_temporal_objection(_f(note))


def test_spares_a_note_citing_a_date():
    note = "The intro narrates events of 2026-07-02 as though they are current."
    assert not R.is_uncited_temporal_objection(_f(note))


def test_a_quoted_temporal_value_does_not_shield_the_judge():
    """A span the JUDGE states counts against demotion even when the note also
    quotes page copy; a span appearing only inside quotes does not."""
    quoting_only = "The claim 'a 90-day hold' is narrated as present history without a label."
    assert R.is_uncited_temporal_objection(_f(quoting_only))
    judge_states = "The claim 'a 90-day hold' is impossible: a 90-day span exceeds the young cycle."
    assert not R.is_uncited_temporal_objection(_f(judge_states))


def test_fails_closed_on_an_empty_note():
    assert not R.is_uncited_temporal_objection(_f(""))
    assert not R.is_uncited_temporal_objection(_f(None))


def test_scoped_to_its_category():
    assert not R.is_uncited_temporal_objection(_f(WIRE_539C6D, category="stale_data"))


def test_demotes_never_drops():
    """The ruling lives in the ADVISORY table (visible, recorded), not the DROP set."""
    ids = {rid for rid, _l, _f2, _r in R.advisory_rulings(_START, _TODAY)}
    assert "uncited_temporal_objection" in ids
