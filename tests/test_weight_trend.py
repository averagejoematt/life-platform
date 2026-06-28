"""Tests for weight_trend — the shared regression rate + projection (kills -13.75 vs -7.33)."""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

import weight_trend as wt  # noqa: E402

REF = datetime(2026, 6, 27, tzinfo=timezone.utc)


def _series(start_day, days, start_w, per_day):
    from datetime import timedelta

    base = datetime(2026, 6, start_day, tzinfo=timezone.utc)
    return [((base + timedelta(days=i)).strftime("%Y-%m-%d"), start_w + per_day * i) for i in range(days)]


def test_regression_rate_not_total():
    # 14 days losing ~1 lb/day → ~ -6.9 lb/wk regression, NOT the -13.75 total.
    series = _series(14, 14, 314.0, -1.0)
    r = wt.weight_trajectory(series, current_weight=300.0, goal_weight=185.0, ref_dt=REF)
    assert -7.5 < r["weekly_rate_lbs"] < -6.5  # ~-7 lb/wk, not -13.x
    assert r["rate_provisional"] is True  # 13-day span < 21


def test_projection_suppressed_while_provisional():
    series = _series(14, 14, 314.0, -1.0)
    r = wt.weight_trajectory(series, current_weight=300.0, goal_weight=185.0, ref_dt=REF)
    assert r["projected_goal_date"] is None  # no impossible finish line on thin data
    assert r["days_to_goal"] is None


def test_projection_appears_once_span_is_enough():
    # 30 days of data, steady 0.5 lb/day loss → span >= 21, projection allowed.
    series = _series(1, 30, 314.0, -0.5)
    r = wt.weight_trajectory(series, current_weight=299.0, goal_weight=185.0, ref_dt=datetime(2026, 7, 1, tzinfo=timezone.utc))
    assert r["rate_provisional"] is False
    assert r["projected_goal_date"] is not None
    assert r["weekly_rate_lbs"] < 0


def test_too_few_points_is_zero():
    r = wt.weight_trajectory([("2026-06-26", 300.0)], current_weight=300.0, goal_weight=185.0, ref_dt=REF)
    assert r["weekly_rate_lbs"] == 0.0
    assert r["projected_goal_date"] is None
