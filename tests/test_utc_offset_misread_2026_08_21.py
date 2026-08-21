"""The model's own UTC→Pacific arithmetic is wrong — pinned at the checker layer.

THE PRODUCTION FINDING (2026-08-21, confirmed on a second pass, rated `high` — the
severity that FAILs a blocking gate):

    sleep_trend row dated 2026-08-21 reports sleep_start at 2026-08-21T07:02:51.150Z
    (7:02 AM UTC = ~11:02 PM prior Pacific evening, but this is bedtime on the morning
    of Day 5, not the night before)

`07:02Z` in August is **00:02 PDT (UTC-7)**, not 23:02. The model applied **PST
(UTC-8)**. That single hour is load-bearing: it moves the instant back across midnight
onto the previous calendar day, which is the entire substance of the "contradiction"
it then reported. The underlying row is correct — a 12:02 AM bedtime with a same-day
wake, exactly what the wake-date convention describes.

NOT A NEW CLASS FOR THIS REPO. `deploy/backfill_eightsleep_hours.py` exists because
ingestion once "converted UTC timestamps to local hours with a FIXED standard-time
offset (-8)", corrupting every PDT-season night. Same arithmetic, same off-by-one-hour;
there it was our code, here it is the model.

WHY A SUPPRESSOR AND NOT A BETTER PROMPT. #2741 measured what prose achieves here: a
clause the model was told to honour was ignored in 25 of 60 runs, severity flipping
run-to-run on byte-identical input. The payload ALREADY ships
`figure_scope.trend_sleep_start_note` spelling out the UTC-vs-Pacific split — the model
quoted that very note and still miscomputed. Per ADR-105, deterministic computation
precedes the LLM verdict.

Pins, in the #2613/#2780 retirement style:
  1. the verbatim production finding is dropped;
  2. the drop is SCOPED — a CORRECT conversion that still objects survives, as does
     another surface, another category, a note with no instant, and a note with no
     clock time at all;
  3. the conversion is DST-exact (zoneinfo at the instant's own date), so the same
     clock time is judged differently in January and August — the bug, inverted.

NB this suite does not sweep the source tree — unit suite over one module, so it needs
no `tests/conftest.py` registration.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from operational import reader_truth_qa as rt  # noqa: E402

SLEEP = "/api/sleep_detail"

# Verbatim shape of the 2026-08-21 production finding.
PROD_NOTE = (
    "sleep_trend row dated 2026-08-21 reports sleep_start at 2026-08-21T07:02:51.150Z "
    "(7:02 AM UTC = ~11:02 PM prior Pacific evening, but this is bedtime on the morning "
    "of Day 5, not the night before)."
)


def _finding(note, page=SLEEP, category="temporal_contradiction"):
    return {"page": page, "category": category, "severity": "high", "note": note}


# ── 1. the production finding is dropped ─────────────────────────────────────


def test_the_verbatim_production_finding_is_dropped():
    assert rt.is_utc_offset_misread(_finding(PROD_NOTE)) is True


def test_the_correct_pacific_rendering_is_what_the_note_lacks():
    """States the arithmetic explicitly so the pin cannot be satisfied by accident:
    07:02Z on 2026-08-21 is 00:02 PDT, i.e. '12:02 AM' — a string the note never
    contains, while it does contain the PST answer '11:02 PM'."""
    correct = rt._pacific_renderings("2026-08-21", 7, 2)
    assert "12:02 AM" in correct
    assert not any(c in PROD_NOTE for c in correct), "the note already states the correct time — re-check the fixture"
    assert "11:02 PM" in PROD_NOTE


# ── 2. the drop is SCOPED ────────────────────────────────────────────────────


def test_a_correct_conversion_that_still_objects_SURVIVES():
    """THE most important negative. This guard must never become a way to discard
    temporal findings on sleep_detail — only ones resting on bad arithmetic."""
    note = "sleep_start 2026-08-21T07:02:51.150Z is 12:02 AM Pacific on 2026-08-21, yet the summary claims a 9:30 PM bedtime."
    assert rt.is_utc_offset_misread(_finding(note)) is False


def test_another_surface_survives():
    assert rt.is_utc_offset_misread(_finding(PROD_NOTE, page="/api/coaches")) is False


def test_another_category_survives():
    assert rt.is_utc_offset_misread(_finding(PROD_NOTE, category="duplicated_narrative")) is False


def test_a_note_with_no_utc_instant_survives():
    assert rt.is_utc_offset_misread(_finding("the page claims seven days of data on Day 5.")) is False


def test_a_note_quoting_an_instant_but_no_clock_time_survives():
    """No stated conversion means no arithmetic to falsify — the finding stands on
    whatever else it says."""
    note = "sleep_trend row dated 2026-08-21 reports sleep_start at 2026-08-21T07:02:51.150Z, which disagrees with night_of."
    assert rt.is_utc_offset_misread(_finding(note)) is False


# ── 3. the conversion is DST-exact, which is the whole point ─────────────────


def test_the_same_clock_time_converts_differently_in_winter():
    """The bug was a FIXED offset. In August 07:02Z is 00:02 PDT; in January the same
    07:02Z is 23:02 PST the previous day. A guard using one fixed offset would get one
    of these wrong — which is exactly the defect it exists to catch."""
    august = rt._pacific_renderings("2026-08-21", 7, 2)
    january = rt._pacific_renderings("2026-01-21", 7, 2)
    assert "12:02 AM" in august
    assert "11:02 PM" in january
    assert august != january


def test_the_pst_answer_is_correct_in_winter_and_therefore_survives():
    """Inverting the production case: the very wording that is wrong in August is RIGHT
    in January, and must not be suppressed there. A guard that fired on the phrasing
    rather than the arithmetic would fail this."""
    winter_note = (
        "sleep_trend row dated 2026-01-21 reports sleep_start at 2026-01-21T07:02:51.150Z "
        "(7:02 AM UTC = ~11:02 PM prior Pacific evening), which contradicts the wake date."
    )
    assert rt.is_utc_offset_misread(_finding(winter_note)) is False


# ── 4. the drop is wired into the pipeline, not just defined ────────────────


def test_the_suppressor_is_actually_called_by_assess_prose():
    """A checker nobody calls is the dark-gate shape this platform keeps re-learning.
    Pins the wiring by source inspection — cheaper and more direct than driving a
    Bedrock round-trip, and it fails the day someone deletes the call site."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "lambdas", "operational", "reader_truth_qa.py")).read()
    body = src.split("def assess_prose")[1]
    assert "is_utc_offset_misread(f)" in body, "assess_prose never calls the suppressor — it is defined and dark"


def test_the_drop_is_printed_not_silently_swallowed():
    """Every sibling retirement (#2613, #2780, #2741) prints its drop. A silent drop
    would make a suppressed finding indistinguishable from one that never fired."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "lambdas", "operational", "reader_truth_qa.py")).read()
    body = src.split("if is_utc_offset_misread(f):")[1][:400]
    assert "print(" in body, "the drop is silent — it must be printed like every sibling retirement"
