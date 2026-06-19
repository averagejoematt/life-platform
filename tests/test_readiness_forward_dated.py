"""
tests/test_readiness_forward_dated.py — regression net for the readiness
date-integrity bug: tool_get_readiness_score future-stamped stale data.

Each component pulls a 7-day window and takes the newest available record, but
the result dict used to hardcode "date": end_date. Asking for a date whose
overnight hasn't happened yet returned yesterday's components stamped with the
requested date.

This test mocks query_source so it asserts the DATE LOGIC without touching AWS:
request a future date with only older Whoop data present, and assert the
top-level date reflects the actual newest component date, is_forward_dated is
true, and a staleness_warning is surfaced.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# tools_health reads these at import.
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("DYNAMODB_TABLE", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")

import mcp.tools_health as th  # noqa: E402

DATA_DATE = "2026-06-17"  # the newest record actually present
FUTURE_DATE = "2026-06-20"  # requested date whose overnight hasn't happened yet


def test_forward_dated_surfaces_real_data_date(monkeypatch):
    """Requesting a future date returns the latest available data, honestly dated."""

    def fake_query(source, start, end, *a, **k):
        if source == "whoop":
            return [
                {
                    "date": DATA_DATE,
                    "recovery_score": 68,
                    "hrv": 95,
                    "resting_heart_rate": 52,
                    "sleep_duration_hours": 7.2,
                    "sleep_quality_score": 80,
                }
            ]
        # computed_metrics, garmin, etc. → no data (forces live paths / skips)
        return []

    monkeypatch.setattr(th, "query_source", fake_query)

    result = th.tool_get_readiness_score({"date": FUTURE_DATE})

    assert result.get("is_forward_dated") is True, result
    assert result["date"] == DATA_DATE, f"top-level date should be the real data date, got {result['date']}"
    assert result["requested_date"] == FUTURE_DATE
    assert "staleness_warning" in result and FUTURE_DATE in result["staleness_warning"]
    # whoop_recovery carries the honest raw.date even before the fix
    assert result["components"]["whoop_recovery"]["raw"]["date"] == DATA_DATE
