"""tests/test_muscle_volume_completeness.py — B2a (2026-06-21).

get_muscle_volume read off a high-water mark that hadn't caught the latest session,
so it undercounted (calves 'lagging' when optimal) and poisoned night-before
authoring. assess_volume_completeness surfaces whether the aggregation actually
folded in the newest in-window ingested session. Pure function — no AWS.

Key guard: rest days at the tail of the window, and sessions ingested *beyond*
end_date, must NOT read as stale (only an in-window session we failed to aggregate).
"""

import os

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")

from mcp.strength_helpers import assess_volume_completeness  # noqa: E402


def test_includes_latest_when_aggregation_reaches_high_water():
    r = assess_volume_completeness(["2026-06-16", "2026-06-18", "2026-06-20"], "2026-06-20", "2026-06-20")
    assert r["includes_latest"] is True
    assert r["stale"] is False
    assert r["data_current_through"] == "2026-06-20"


def test_stale_when_newer_in_window_session_missed():
    # Partition has a 6-20 session but the analysis only reached 6-19 → the bug.
    r = assess_volume_completeness(["2026-06-16", "2026-06-19"], "2026-06-20", "2026-06-20")
    assert r["stale"] is True
    assert r["includes_latest"] is False
    assert "undercount" in r["note"]


def test_session_beyond_window_is_not_stale():
    # High-water mark is past end_date → out of scope, not a gap.
    r = assess_volume_completeness(["2026-06-14"], "2026-07-01", "2026-06-20")
    assert r["stale"] is False
    assert r["includes_latest"] is True


def test_rest_days_at_tail_are_not_stale():
    # Latest in-window session is 6-16; nothing newer is ingested → complete.
    r = assess_volume_completeness(["2026-06-14", "2026-06-16"], "2026-06-16", "2026-06-20")
    assert r["stale"] is False
    assert r["data_current_through"] == "2026-06-16"


def test_no_hevy_data_at_all():
    r = assess_volume_completeness([], None, "2026-06-20")
    assert r["latest_ingested"] is None
    assert r["stale"] is False
    assert r["includes_latest"] is True
