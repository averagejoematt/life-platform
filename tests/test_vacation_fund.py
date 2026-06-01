"""tests/test_vacation_fund.py — vacation fund compute (miles → USD).

Mocks the DDB range query + config so the math is tested without AWS.
"""
from __future__ import annotations

from unittest.mock import patch

import vacation_fund as vf


def _fake_query(mapping):
    """Return a _query_range side_effect that dispatches on partition name."""
    def _q(partition, start, end):
        return mapping.get(partition, [])
    return _q


def _cfg(**over):
    base = {
        "rate_per_mile": 1.0, "start_date": None, "included_sport_types": "all",
        "extra_sources": [], "manual_adjustment_usd": 0.0,
    }
    base.update(over)
    return base


def test_genesis_empty_returns_zero_with_warning():
    with patch.object(vf, "load_config", return_value=_cfg()), \
         patch.object(vf, "_query_range", side_effect=_fake_query({})):
        out = vf.compute_vacation_fund(start_date="2026-06-01", end_date="2026-06-01")
    assert out["total_miles"] == 0.0
    assert out["total_usd"] == 0.0
    assert any("No workout miles" in w for w in out["warnings"])


def test_strava_sum_and_per_sport_breakdown():
    strava = [
        {"total_distance_miles": 5.0,
         "activities": [{"sport_type": "Walk", "distance_miles": 3.0},
                        {"sport_type": "Run", "distance_miles": 2.0}]},
        {"total_distance_miles": 4.0,
         "activities": [{"sport_type": "VirtualRide", "distance_miles": 4.0}]},
    ]
    with patch.object(vf, "load_config", return_value=_cfg(rate_per_mile=1.0)), \
         patch.object(vf, "_query_range", side_effect=_fake_query({"strava": strava})):
        out = vf.compute_vacation_fund(start_date="2026-06-01", end_date="2026-06-08")
    assert out["total_miles"] == 9.0
    assert out["total_usd"] == 9.0
    assert out["per_sport_type"] == {"Walk": 3.0, "Run": 2.0, "VirtualRide": 4.0}
    assert out["per_source"] == {"strava": 9.0}


def test_additive_hevy_meters_to_miles():
    strava = [{"total_distance_miles": 2.0,
               "activities": [{"sport_type": "Walk", "distance_miles": 2.0}]}]
    hevy = [{"exercises": [{"sets": [{"distance_m": 1609.34}, {"distance_m": 3218.68}]}]}]
    with patch.object(vf, "load_config", return_value=_cfg(extra_sources=["hevy"])), \
         patch.object(vf, "_query_range",
                      side_effect=_fake_query({"strava": strava, "hevy": hevy})):
        out = vf.compute_vacation_fund(start_date="2026-06-01", end_date="2026-06-08")
    assert out["per_source"]["hevy"] == 3.0          # (1609.34 + 3218.68)/1609.34
    assert out["total_miles"] == 5.0
    assert any("overlap" in w.lower() for w in out["warnings"])


def test_additive_macrofactor_yards_to_miles():
    mf = [{"workouts": [{"exercises": [{"sets": [
        {"distance_yards": 1760},                 # → 1.0 mi
        {"distance_miles": 0.5},                   # native miles preferred
    ]}]}]}]
    with patch.object(vf, "load_config", return_value=_cfg(extra_sources=["macrofactor_export"])), \
         patch.object(vf, "_query_range",
                      side_effect=_fake_query({"macrofactor_workouts": mf})):
        out = vf.compute_vacation_fund(start_date="2026-06-01", end_date="2026-06-08")
    assert out["per_source"]["macrofactor_export"] == 1.5
    assert out["total_miles"] == 1.5


def test_rate_and_manual_adjustment_apply():
    strava = [{"total_distance_miles": 10.0, "activities": [{"sport_type": "Run", "distance_miles": 10.0}]}]
    with patch.object(vf, "load_config",
                      return_value=_cfg(rate_per_mile=2.0, manual_adjustment_usd=50.0)), \
         patch.object(vf, "_query_range", side_effect=_fake_query({"strava": strava})):
        out = vf.compute_vacation_fund(start_date="2026-06-01", end_date="2026-06-08")
    assert out["miles_usd"] == 20.0          # 10 mi * $2
    assert out["total_usd"] == 70.0          # + $50 manual


def test_sport_type_filter_restricts_and_skips_extras():
    strava = [{"total_distance_miles": 7.0,
               "activities": [{"sport_type": "Run", "distance_miles": 5.0},
                              {"sport_type": "Walk", "distance_miles": 2.0}]}]
    hevy = [{"exercises": [{"sets": [{"distance_m": 1609.34}]}]}]
    with patch.object(vf, "load_config",
                      return_value=_cfg(included_sport_types=["Run"], extra_sources=["hevy"])), \
         patch.object(vf, "_query_range",
                      side_effect=_fake_query({"strava": strava, "hevy": hevy})):
        out = vf.compute_vacation_fund(start_date="2026-06-01", end_date="2026-06-08")
    assert out["total_miles"] == 5.0                 # only Run counted
    assert "hevy" not in out["per_source"]           # extras skipped under a type filter
    assert any("skipped" in w.lower() for w in out["warnings"])


def test_start_end_override_beats_config_default():
    captured = {}

    def _q(partition, start, end):
        captured["range"] = (start, end)
        return []

    with patch.object(vf, "load_config", return_value=_cfg(start_date="2020-01-01")), \
         patch.object(vf, "_query_range", side_effect=_q):
        out = vf.compute_vacation_fund(start_date="2026-06-01", end_date="2026-06-30")
    assert out["start_date"] == "2026-06-01"
    assert out["end_date"] == "2026-06-30"
    assert captured["range"] == ("2026-06-01", "2026-06-30")
