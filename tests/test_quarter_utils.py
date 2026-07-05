"""tests/test_quarter_utils.py — calendar-quarter boundary math (#553).

Pure date arithmetic, no AWS. The coach-memoir batch's entire "fires once per
quarter" guarantee rests on previous_quarter_key() picking the right quarter
on the 1st of a new one, so the year-rollover (Q1 -> prior year's Q4) gets
its own case.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import quarter_utils  # noqa: E402


def test_quarter_key_maps_month_to_quarter():
    assert quarter_utils.quarter_key("2026-01-15") == "2026-Q1"
    assert quarter_utils.quarter_key("2026-03-31") == "2026-Q1"
    assert quarter_utils.quarter_key("2026-04-01") == "2026-Q2"
    assert quarter_utils.quarter_key("2026-07-04") == "2026-Q3"
    assert quarter_utils.quarter_key("2026-09-30") == "2026-Q3"
    assert quarter_utils.quarter_key("2026-10-01") == "2026-Q4"
    assert quarter_utils.quarter_key("2026-12-31") == "2026-Q4"


def test_previous_quarter_key_within_year():
    assert quarter_utils.previous_quarter_key("2026-10-01") == "2026-Q3"
    assert quarter_utils.previous_quarter_key("2026-07-01") == "2026-Q2"
    assert quarter_utils.previous_quarter_key("2026-04-01") == "2026-Q1"


def test_previous_quarter_key_year_rollover():
    # Running the batch on Jan 1st must retrospect on the PRIOR year's Q4,
    # not "Q0" or the current year's Q1.
    assert quarter_utils.previous_quarter_key("2027-01-01") == "2026-Q4"
    assert quarter_utils.previous_quarter_key("2027-01-31") == "2026-Q4"


def test_quarter_bounds_round_trip():
    for q in ("2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"):
        start, end = quarter_utils.quarter_bounds(q)
        assert quarter_utils.quarter_key(start) == q
        # end is exclusive — it belongs to the NEXT quarter.
        assert quarter_utils.quarter_key(end) != q


def test_quarter_bounds_exact_dates():
    assert quarter_utils.quarter_bounds("2026-Q3") == ("2026-07-01", "2026-10-01")
    assert quarter_utils.quarter_bounds("2026-Q4") == ("2026-10-01", "2027-01-01")
    assert quarter_utils.quarter_bounds("2026-Q1") == ("2026-01-01", "2026-04-01")
