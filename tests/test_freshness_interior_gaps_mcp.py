"""tests/test_freshness_interior_gaps_mcp.py — B3 (2026-06-21).

DI-2 added interior-gap detection to the freshness_checker LAMBDA, but the
get_freshness_status MCP tool stayed high-water-mark only — it would still report a
mid-window hole as green. This locks the MCP-side find_interior_gaps (TD-14 parity
with emails/freshness_checker_lambda.find_interior_gaps) and the daily-source set.
Pure function — no AWS (env vars set only so mcp.config imports cleanly).
"""

import os

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")

from mcp.tools_labs import DAILY_SOURCES_INTERIOR, find_interior_gaps  # noqa: E402

WIN_START = "2026-06-01"
WIN_END = "2026-06-14"


def test_single_interior_gap_flagged():
    present = ["2026-06-01", "2026-06-02", "2026-06-04", "2026-06-05"]  # 06-03 missing
    assert find_interior_gaps(present, WIN_START, WIN_END) == ["2026-06-03"]


def test_contiguous_has_no_gap():
    present = ["2026-06-05", "2026-06-06", "2026-06-07"]
    assert find_interior_gaps(present, WIN_START, WIN_END) == []


def test_trailing_absence_is_recency_not_gap():
    # Newest present is 06-05; the empty tail to 06-14 is recency, not interior.
    present = ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"]
    assert find_interior_gaps(present, WIN_START, WIN_END) == []


def test_leading_absence_is_not_gap():
    present = ["2026-06-10", "2026-06-11", "2026-06-12"]
    assert find_interior_gaps(present, WIN_START, WIN_END) == []


def test_multi_day_interior_gap():
    present = ["2026-06-01", "2026-06-05"]  # 02,03,04 missing inside the span
    assert find_interior_gaps(present, WIN_START, WIN_END) == ["2026-06-02", "2026-06-03", "2026-06-04"]


def test_single_present_date_no_interior():
    assert find_interior_gaps(["2026-06-07"], WIN_START, WIN_END) == []


def test_daily_sources_set_matches_lambda():
    # Parity guard: the MCP daily-source set must mirror the lambda's DAILY_SOURCES.
    assert DAILY_SOURCES_INTERIOR == {"whoop", "apple_health", "eightsleep", "habitify"}
