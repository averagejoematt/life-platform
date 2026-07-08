"""
tests/test_health_window_guards.py — regression net for the 2026-06-13 date-window
bugs in get_weight_loss_progress (F3). (get_body_composition_trend pruned by #395.)

Root cause (both): the effective query window was clamped to journey_start in a
way that (a) ignored an explicit start_date and (b) when journey_start sat AHEAD
of end_date — a freshly re-anchored genesis dated tomorrow — passed start > end
to DynamoDB's BETWEEN, raising a ValidationException.

These tests mock get_profile + query_source so they assert the WINDOW LOGIC
without touching AWS:
  (a) no dates + a future genesis → graceful pre_genesis return, query_source
      NEVER called with start > end;
  (b) explicit dates → honored verbatim (query_source called with the passed
      start), not overridden by journey_start.
"""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# tools_health reads these at import.
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("DYNAMODB_TABLE", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")

import mcp.tools_health as th  # noqa: E402

FUTURE_GENESIS = "2999-01-01"  # always ahead of "today" → exercises the guard


@pytest.fixture
def patched(monkeypatch):
    """Profile with a future genesis; query_source records its args and never
    returns data (so handlers reach their no-data path, not real DDB)."""
    calls = []
    monkeypatch.setattr(
        th,
        "get_profile",
        lambda: {
            "journey_start_date": FUTURE_GENESIS,
            "journey_start_weight_lbs": 300.0,
            "goal_weight_lbs": 185,
            "height_inches": 70,
        },
    )

    def fake_query(source, start, end, *a, **k):
        calls.append((source, start, end))
        assert start <= end, f"query_source got start>end: {start} > {end} (the F3/F4 ValidationException bug)"
        return []

    monkeypatch.setattr(th, "query_source", fake_query)
    return calls


@pytest.mark.parametrize("fn", ["tool_get_weight_loss_progress"])
def test_future_genesis_no_validation_exception(patched, fn):
    """No dates + future genesis → pre_genesis return, no start>end query."""
    result = getattr(th, fn)({})
    assert result.get("pre_genesis") is True, f"{fn}: expected graceful pre_genesis, got {result}"
    assert patched == [], f"{fn}: should short-circuit before querying when genesis is in the future"


@pytest.mark.parametrize("fn", ["tool_get_weight_loss_progress"])
def test_explicit_dates_honored(patched, fn):
    """Explicit start_date must reach query_source verbatim, not be overridden
    by journey_start (the param-override half of the bug)."""
    getattr(th, fn)({"start_date": "2026-04-01", "end_date": "2026-06-11"})
    assert patched, f"{fn}: query_source was never called for an explicit valid range"
    _src, start, end = patched[-1]
    assert start == "2026-04-01", f"{fn}: explicit start_date overridden → queried {start}"
    assert end == "2026-06-11"
