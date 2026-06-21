"""
tests/test_freshness_interior_gaps.py — unit tests for the DI-2b interior-gap
detector in freshness_checker_lambda.

The staleness check only sees the latest date per source (the high-water mark),
so a hole BEHIND it — a daily source going dead mid-window then resuming — is
invisible. `find_interior_gaps` closes that blind spot: it flags missing dates
strictly inside the [first, last] present span, while leaving trailing/leading
absence to the recency check. These are pure-function tests — no AWS, no network.
"""

import os
import sys

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from emails.freshness_checker_lambda import find_interior_gaps  # noqa: E402

WIN_START = "2026-06-01"
WIN_END = "2026-06-14"


def test_single_interior_gap_is_flagged():
    present = {"2026-06-10", "2026-06-12", "2026-06-13"}
    assert find_interior_gaps(present, WIN_START, WIN_END) == ["2026-06-11"]


def test_consecutive_interior_gap_run():
    present = {"2026-06-08", "2026-06-12"}  # 09, 10, 11 all missing inside the span
    assert find_interior_gaps(present, WIN_START, WIN_END) == ["2026-06-09", "2026-06-10", "2026-06-11"]


def test_contiguous_span_has_no_gaps():
    present = {"2026-06-10", "2026-06-11", "2026-06-12", "2026-06-13"}
    assert find_interior_gaps(present, WIN_START, WIN_END) == []


def test_trailing_absence_is_not_an_interior_gap():
    # Source went quiet AFTER 06-11 — that's recency (staleness check), not a hole.
    present = {"2026-06-09", "2026-06-10", "2026-06-11"}
    assert find_interior_gaps(present, WIN_START, WIN_END) == []


def test_leading_absence_is_not_an_interior_gap():
    # No records early in the window, then a contiguous run — nothing interior missing.
    present = {"2026-06-12", "2026-06-13", "2026-06-14"}
    assert find_interior_gaps(present, WIN_START, WIN_END) == []


def test_fewer_than_two_present_dates_yields_no_interior():
    assert find_interior_gaps({"2026-06-10"}, WIN_START, WIN_END) == []
    assert find_interior_gaps(set(), WIN_START, WIN_END) == []


def test_dates_outside_window_are_ignored():
    # An out-of-window straggler must not widen the judged span.
    present = {"2026-05-01", "2026-06-12", "2026-06-13"}
    assert find_interior_gaps(present, WIN_START, WIN_END) == []
