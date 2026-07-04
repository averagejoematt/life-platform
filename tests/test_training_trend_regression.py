"""tests/test_training_trend_regression.py — #511.

`_linear_regression(points)` takes one list of (x, y) tuples, but two call
sites in tools_training passed `(list(range(n)), ce_vals)` — a TypeError the
moment eligible sessions exist (the same latent bug fixed in tools_journal by
PR #510). These tests run both tools over enough mocked Strava sessions to
reach the regression and pin that a real slope/trend comes back.
"""

import os

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")

import mcp.tools_training as tt  # noqa: E402


def _strava_days():
    """Five Zone 2 runs with steadily improving pace-at-HR."""
    days = []
    for i in range(5):
        days.append(
            {
                "date": f"2026-06-{10 + i:02d}",
                "activities": [
                    {
                        "sport_type": "Run",
                        "average_heartrate": 125,
                        "moving_time_seconds": 2400,
                        "distance_miles": 3.0 + i * 0.2,
                    }
                ],
            }
        )
    return days


def test_lactate_threshold_regression_runs(monkeypatch):
    monkeypatch.setattr(tt, "query_source", lambda *a, **k: _strava_days())
    out = tt.tool_get_lactate_threshold_estimate({"start_date": "2026-06-01", "end_date": "2026-06-30"})
    assert "error" not in out
    assert out["trend"]["direction"] == "improving"
    assert out["trend"]["slope"] is not None


def test_exercise_efficiency_trend_regression_runs(monkeypatch):
    monkeypatch.setattr(tt, "query_source", lambda *a, **k: _strava_days())
    out = tt.tool_get_exercise_efficiency_trend({"start_date": "2026-06-01", "end_date": "2026-06-30"})
    assert "error" not in out
    (sport_result,) = out["by_sport"].values()
    assert sport_result["sessions"] == 5
    assert sport_result["trend"] == "improving"
