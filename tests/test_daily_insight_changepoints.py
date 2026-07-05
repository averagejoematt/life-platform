"""
tests/test_daily_insight_changepoints.py — IC-31 / #542 changepoint consumer.

Exercises _compute_changepoints (the real wiring of stats_core.detect_changepoints
into daily-insight-compute) and _format_changepoint_line, with fetch_range mocked
so no AWS is touched. The synthetic HRV series steps DOWN mid-window (a genuine
regime shift); the tests assert the shift is recovered with an approximate date,
magnitude, and confidence — and that flat/thin series stay silent.
"""

import os
import random
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "compute"))

import daily_insight_compute_lambda as di  # noqa: E402


def _records(start_day, values):
    """Build fake DDB records: one per day from start_day with `hrv` (and weight)."""
    out = []
    for i, v in enumerate(values):
        d = (start_day + timedelta(days=i)).isoformat()
        out.append({"date": d, "hrv": v, "resting_heart_rate": v, "weight_lbs": v})
    return out


class TestComputeChangepoints:
    def setup_method(self):
        self._orig_fetch = di.fetch_range

    def teardown_method(self):
        di.fetch_range = self._orig_fetch

    def _run_with_series(self, hrv_values, window_days=60):
        yesterday = date(2026, 7, 4)
        start = yesterday - timedelta(days=len(hrv_values) - 1)
        recs = _records(start, hrv_values)

        def fake_fetch(source, s, e):
            if source == "whoop":
                return recs
            return []  # only wire whoop for the test

        di.fetch_range = fake_fetch
        # Restrict to just the HRV series so the test is deterministic.
        series = [("whoop", "hrv", "HRV", "ms", True)]
        return di._compute_changepoints(yesterday.isoformat(), series_defs=series, window_days=window_days)

    def test_recent_regime_shift_detected(self):
        # HRV holds ~62 for 40 days then steps down to ~50 for the last 20 days —
        # a shift ~20 days before yesterday (inside the 28-day recency window).
        rng = random.Random(42)
        values = [62 + rng.gauss(0, 3) for _ in range(40)] + [50 + rng.gauss(0, 3) for _ in range(20)]
        result = self._run_with_series(values)
        assert len(result) >= 1
        cp = result[0]
        assert cp["metric"] == "HRV"
        assert cp["direction"] == "decrease"
        assert cp["worsening"] is True  # HRV down is adverse
        assert cp["magnitude"] < 0
        assert cp["confidence"] >= 0.99
        assert cp["unit"] == "ms"
        assert cp["n_before"] >= 7 and cp["n_after"] >= 7
        # The reported date is roughly 20 days before yesterday (2026-07-04).
        assert cp["date"] >= "2026-06-10" and cp["date"] <= "2026-06-25"

    def test_flat_series_no_shift(self):
        rng = random.Random(1)
        values = [60 + rng.gauss(0, 1) for _ in range(60)]
        assert self._run_with_series(values) == []

    def test_old_shift_not_surfaced_as_recent(self):
        # Shift happens in the FIRST week of a 60-day window (>28d ago) — real, but
        # not actionable news for today's brief, so it must be filtered out.
        rng = random.Random(5)
        values = [50 + rng.gauss(0, 2) for _ in range(8)] + [62 + rng.gauss(0, 2) for _ in range(52)]
        result = self._run_with_series(values)
        assert result == []

    def test_thin_series_silent(self):
        rng = random.Random(2)
        values = [60 + rng.gauss(0, 2) for _ in range(10)]  # < 14 points
        assert self._run_with_series(values) == []

    def test_format_line_shape(self):
        cp = {
            "metric": "HRV",
            "unit": "ms",
            "magnitude": -8.1,
            "before_mean": 62.0,
            "after_mean": 53.9,
            "effect_size": -1.4,
            "confidence": 0.997,
            "direction": "decrease",
            "worsening": True,
            "date": "2026-06-14",
            "n_before": 21,
            "n_after": 19,
            "window_days": 60,
        }
        line = di._format_changepoint_line(cp)
        assert "REGIME SHIFT" in line
        assert "HRV" in line
        assert "2026-06-14" in line
        assert "level change" in line
        assert "(adverse)" in line


if __name__ == "__main__":
    # Print a concrete example insight for the PR body.
    rng = random.Random(42)
    yesterday = date(2026, 7, 4)
    values = [62 + rng.gauss(0, 3) for _ in range(40)] + [50 + rng.gauss(0, 3) for _ in range(20)]
    start = yesterday - timedelta(days=len(values) - 1)
    recs = _records(start, values)
    di.fetch_range = lambda source, s, e: recs if source == "whoop" else []
    cps = di._compute_changepoints(yesterday.isoformat(), series_defs=[("whoop", "hrv", "HRV", "ms", True)])
    for cp in cps:
        print(di._format_changepoint_line(cp))
