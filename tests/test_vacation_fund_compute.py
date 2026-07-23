"""tests/test_vacation_fund_compute.py — deterministic miles->USD math for the
vacation-fund tracker (lambdas/vacation_fund.py).

This module is the SINGLE source of the miles->dollars computation imported by
three surfaces (MCP tool, /api/vacation_fund, daily brief), so its unit
conversions (meters/yards -> miles), sport-type filtering, source-overlap
warning, and the 1-year projection are a public contract. Per ADR-105 the number
is computed deterministically before anything narrates it — these tests pin that
determinism.

All DDB access is stubbed by monkeypatching `_query_range` (the one function that
touches boto3); every test drives real records -> asserted miles/USD.
"""

from decimal import Decimal

import pytest
import vacation_fund as vf


@pytest.fixture
def stub_ranges(monkeypatch):
    """Route _query_range(partition, ...) to a per-partition fixture list."""
    store = {}

    def fake_query_range(partition, start_date, end_date):
        return list(store.get(partition, []))

    monkeypatch.setattr(vf, "_query_range", fake_query_range)
    return store


# ── _f: Decimal / None / garbage-safe float ─────────────────────────────────


def test_f_handles_none_decimal_str_and_garbage():
    assert vf._f(None) == 0.0
    assert vf._f(Decimal("3.5")) == 3.5
    assert vf._f("2.25") == 2.25
    assert vf._f(object()) == 0.0  # unconvertible → 0, never raises


# ── _strava_miles: total vs sport-type filter ───────────────────────────────


def test_strava_miles_no_filter_uses_daily_total_and_per_sport(stub_ranges):
    stub_ranges["strava"] = [
        {
            "total_distance_miles": Decimal("10.0"),
            "activities": [
                {"sport_type": "Run", "distance_miles": Decimal("6.0")},
                {"sport_type": "Ride", "distance_miles": Decimal("4.0")},
            ],
        }
    ]
    total, per_sport = vf._strava_miles("2026-07-22", "2026-07-29", "all")
    assert total == 10.0
    assert per_sport == {"Run": 6.0, "Ride": 4.0}


def test_strava_miles_filter_counts_only_matching_sport_types(stub_ranges):
    stub_ranges["strava"] = [
        {
            "total_distance_miles": Decimal("10.0"),  # ignored when a filter is active
            "activities": [
                {"sport_type": "Run", "distance_miles": Decimal("6.0")},
                {"sport_type": "Ride", "distance_miles": Decimal("4.0")},
            ],
        }
    ]
    total, per_sport = vf._strava_miles("2026-07-22", "2026-07-29", ["run"])
    assert total == 6.0  # only Run counts, from the activity list not the daily total
    assert per_sport == {"Run": 6.0}  # Ride excluded from the breakdown too


# ── _hevy_miles / _macrofactor_miles: unit conversions ──────────────────────


def test_hevy_miles_converts_meters(stub_ranges):
    stub_ranges["hevy"] = [{"exercises": [{"sets": [{"distance_m": 1609.34}, {"distance_m": 3218.68}]}]}]
    # 1609.34m + 3218.68m = 4828.02m = 3.0 miles
    assert vf._hevy_miles("2026-07-22", "2026-07-29") == 3.0


def test_macrofactor_miles_prefers_miles_then_yards_then_meters(stub_ranges):
    stub_ranges["macrofactor_workouts"] = [
        {
            "workouts": [
                {
                    "exercises": [
                        {
                            "sets": [
                                {"distance_miles": 2.0},  # taken as-is
                                {"distance_yards": 1760},  # = 1.0 mile
                                {"distance_m": 1609.34},  # = 1.0 mile
                            ]
                        }
                    ]
                }
            ]
        }
    ]
    assert vf._macrofactor_miles("2026-07-22", "2026-07-29") == 4.0


# ── compute_vacation_fund: end-to-end math + warnings ───────────────────────


@pytest.fixture
def default_config(monkeypatch):
    """Pin a known config so compute_* is deterministic regardless of repo config."""
    cfg = {
        "rate_per_mile": 2.0,
        "start_date": "2026-07-01",
        "included_sport_types": "all",
        "extra_sources": ["hevy", "macrofactor_export"],
        "manual_adjustment_usd": 5.0,
    }
    monkeypatch.setattr(vf, "load_config", lambda: dict(cfg))
    return cfg


def test_compute_applies_rate_manual_adjustment_and_flags_overlap(stub_ranges, default_config):
    stub_ranges["strava"] = [
        {"total_distance_miles": Decimal("10.0"), "activities": [{"sport_type": "Run", "distance_miles": Decimal("10.0")}]}
    ]
    stub_ranges["hevy"] = [{"exercises": [{"sets": [{"distance_m": 1609.34}]}]}]  # 1.0 mi
    out = vf.compute_vacation_fund(end_date="2026-07-08")
    # total miles = 10 (strava) + 1 (hevy) + 0 (macrofactor) = 11
    assert out["total_miles"] == 11.0
    assert out["per_source"]["strava"] == 10.0
    assert out["per_source"]["hevy"] == 1.0
    assert out["rate_per_mile"] == 2.0
    assert out["miles_usd"] == 22.0  # 11 * 2
    assert out["total_usd"] == 27.0  # 22 + 5 manual adj
    # Overlap warning present because extra sources were added on top of strava.
    assert any("counted twice" in w for w in out["warnings"])


def test_compute_type_filter_skips_extras_with_warning(stub_ranges, monkeypatch):
    cfg = {
        "rate_per_mile": 1.0,
        "start_date": "2026-07-01",
        "included_sport_types": ["Run"],
        "extra_sources": ["hevy"],
        "manual_adjustment_usd": 0.0,
    }
    monkeypatch.setattr(vf, "load_config", lambda: dict(cfg))
    stub_ranges["strava"] = [{"activities": [{"sport_type": "Run", "distance_miles": 5.0}]}]
    stub_ranges["hevy"] = [{"exercises": [{"sets": [{"distance_m": 1609.34}]}]}]
    out = vf.compute_vacation_fund(end_date="2026-07-08")
    assert out["total_miles"] == 5.0  # hevy NOT added under an active sport filter
    assert "hevy" not in out["per_source"]
    assert out["extra_sources_enabled"] == []
    assert any("filter is active" in w for w in out["warnings"])


def test_compute_zero_miles_warns_and_projects_zero(stub_ranges, default_config):
    # No records for any partition → all zeros.
    out = vf.compute_vacation_fund(end_date="2026-07-08")
    assert out["total_miles"] == 0.0
    assert out["miles_usd"] == 0.0
    assert out["pace"]["miles_per_week"] == 0.0
    assert out["pace"]["projected_usd_1yr"] == 5.0  # only the manual adjustment carries
    assert any("No workout miles recorded yet" in w for w in out["warnings"])


def test_compute_projection_scales_weekly_pace_to_year(stub_ranges, monkeypatch):
    cfg = {
        "rate_per_mile": 1.0,
        "start_date": "2026-07-01",
        "included_sport_types": "all",
        "extra_sources": [],
        "manual_adjustment_usd": 0.0,
    }
    monkeypatch.setattr(vf, "load_config", lambda: dict(cfg))
    # 7 miles over exactly one week (7 days inclusive) → 7 mi/week → 364 mi/yr.
    stub_ranges["strava"] = [{"total_distance_miles": 7.0, "activities": []}]
    out = vf.compute_vacation_fund(start_date="2026-07-01", end_date="2026-07-07")
    assert out["day_count"] == 7
    assert out["pace"]["miles_per_week"] == 7.0
    assert out["pace"]["projected_usd_1yr"] == 364.0  # 7 * 52 * $1


# ── load_config: defaults + local-file merge ────────────────────────────────


def test_load_config_falls_back_to_defaults_when_no_file(monkeypatch, tmp_path):
    # Point at an empty config dir so no local file exists; S3 fetch fails under
    # the test's fake creds → merged over defaults.
    monkeypatch.setattr(vf, "CONFIG_DIR", str(tmp_path))
    cfg = vf.load_config()
    assert cfg["rate_per_mile"] == 1.0
    assert cfg["extra_sources"] == ["hevy", "macrofactor_export"]


def test_load_config_merges_local_file_over_defaults(monkeypatch, tmp_path):
    (tmp_path / "vacation_fund.json").write_text('{"rate_per_mile": 3.5, "manual_adjustment_usd": 12.0}')
    monkeypatch.setattr(vf, "CONFIG_DIR", str(tmp_path))
    cfg = vf.load_config()
    assert cfg["rate_per_mile"] == 3.5  # overridden
    assert cfg["manual_adjustment_usd"] == 12.0  # overridden
    assert cfg["included_sport_types"] == "all"  # default preserved
