"""#2780 — the mid-cycle wake-date frame clause, pinned at the checker layer.

The confirm-before-FAIL path (#2741) twice confirmed a temporal_contradiction on
/api/sleep_detail: 'last_night' carrying night_of 2026-08-14 under as_of_date
2026-08-15. Measured against the live payload and the whoop partition, candidate 1
won: the payload honestly dates the night by the evening it began (#1923 wake-date
frame — night_of + 1 day = as_of IS last night), and the LLM class misread the frame.
#2583 ruled this at the genesis edge only; this clause is the same ruling mid-cycle.

Pins, in the #2613 retirement style:
  1. the verbatim production finding is dropped;
  2. the drop is SCOPED — a genuinely stale night (>1-day spread), a single-date
     note, a non-night note, another surface, another category all survive;
  3. dates are compared as dates, not strings.

NB this suite does not sweep the source tree — unit suite over one module, so it
needs no `tests/conftest.py` registration.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from operational import reader_truth_qa as rt  # noqa: E402

SLEEP = "/api/sleep_detail"

# Verbatim shape of the 2026-08-16 06:03Z production finding (#2780).
PROD_NOTE = (
    "sleep_detail payload reports 'total_sleep_hours': 9.5 for 'last_night' "
    "(night_of 2026-08-14, as_of_date 2026-08-15) — a day-old night served under a "
    "last-night label"
)


def _finding(note, page=SLEEP, category="temporal_contradiction"):
    return {"page": page, "category": category, "severity": "high", "note": note}


def test_production_finding_is_dropped():
    assert rt.is_wake_frame_correct(_finding(PROD_NOTE)) is True


def test_night_of_spelling_variants_are_dropped():
    for note in (
        "reports 8.1h for last night (night of 2026-08-15, as_of 2026-08-16)",
        "frame last_night: night_of 2026-08-15 but the page is dated 2026-08-16",
    ):
        assert rt.is_wake_frame_correct(_finding(note)) is True, note


def test_genuinely_stale_night_survives():
    # 2-day spread: a night served under 'last_night' after a fresher night exists.
    note = "reports 9.5 for 'last_night' (night_of 2026-08-13, as_of_date 2026-08-15)"
    assert rt.is_wake_frame_correct(_finding(note)) is False


def test_month_boundary_one_day_span_is_dropped():
    # Date math, not string math: 08-31 -> 09-01 is one day.
    note = "for 'last_night' (night_of 2026-08-31, as_of_date 2026-09-01)"
    assert rt.is_wake_frame_correct(_finding(note)) is True


def test_single_date_note_survives():
    assert rt.is_wake_frame_correct(_finding("night_of 2026-08-14 looks stale")) is False


def test_non_night_note_survives():
    # One-day spread but no night-frame language — not this class.
    note = "summary cites 2026-08-14 while the trend row says 2026-08-15"
    assert rt.is_wake_frame_correct(_finding(note)) is False


def test_other_surface_survives():
    assert rt.is_wake_frame_correct(_finding(PROD_NOTE, page="/api/coaches")) is False
    assert rt.is_wake_frame_correct(_finding(PROD_NOTE, page="/now/")) is False


def test_other_category_survives():
    for cat in ("duplicated_narrative", "audience_violation"):
        assert rt.is_wake_frame_correct(_finding(PROD_NOTE, category=cat)) is False
