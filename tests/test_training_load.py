"""#490 (C-5/C-6/M-3): the shared TSS-like training-load scale.

The contract these tests pin down:
  - the unit is TSS-like (100 ≈ 1 h at threshold), so the downstream form bands
    (readiness clamp(60 + tsb*2), character _in_range_score(-10, 25), MCP
    70 + tsb*2.5) are finally on the scale they always assumed;
  - walks carry load via the moving-time fallback (C-6);
  - a normal training block followed by rest reads as FRESH (positive TSB), not
    maximal fatigue (the C-5 saturation bug);
  - the basis dict is honest about how much of the load is proxy-derived (M-3).
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lambdas"))

import training_load as tl  # noqa: E402


def _walk_day(d, minutes, avg_hr=None):
    act = {"type": "Walk", "sport_type": "Walk", "kilojoules": None, "moving_time_seconds": minutes * 60}
    if avg_hr:
        act["average_heartrate"] = avg_hr
    return {"date": d, "activities": [act]}


def _hevy_day(d, minutes):
    return {"date": d, "duration_sec": minutes * 60}


# ── per-activity model ────────────────────────────────────────────────────────


def test_kilojoules_convert_to_tss_points():
    pts, basis = tl.activity_load({"kilojoules": 720})
    assert abs(pts - 100.0) < 0.01  # 720 kJ ≈ 1 h at ~200 W threshold = 100 points
    assert basis == "kj"


def test_walk_scores_by_moving_time():
    pts, basis = tl.activity_load({"type": "Walk", "kilojoules": None, "moving_time_seconds": 3600})
    assert pts == tl.WALK_TSS_PER_HOUR
    assert basis == "duration"


def test_hr_backed_cardio_uses_intensity_squared():
    # 1 h at threshold HR ≈ 100 points
    pts, _ = tl.activity_load({"type": "Run", "moving_time_seconds": 3600, "average_heartrate": tl.THRESHOLD_HR})
    assert abs(pts - 100.0) < 0.01
    # easy HR is clamped at IF 0.4 → 16 points/h
    easy, _ = tl.activity_load({"type": "Run", "moving_time_seconds": 3600, "average_heartrate": 40})
    assert abs(easy - 16.0) < 0.01


def test_unknown_cardio_falls_back_to_default_rate():
    pts, _ = tl.activity_load({"type": "Elliptical", "moving_time_seconds": 1800})
    assert abs(pts - tl.DEFAULT_CARDIO_TSS_PER_HOUR / 2) < 0.01


def test_zero_duration_zero_load():
    assert tl.activity_load({"type": "Walk"})[0] == 0.0


# ── the C-5 fix: rest reads as rest ──────────────────────────────────────────


def test_rest_after_normal_block_reads_fresh_not_saturated():
    """5 lifts/week for 7 weeks, then 8 full rest days → TSB must be positive
    (fresh) and inside the band every consumer assumes (roughly -30..+30)."""
    today = date(2026, 7, 4)
    hevy = []
    for i in range(8, 57):  # training block ends 8 days ago
        d = today - timedelta(days=i)
        if d.weekday() < 5:  # 5 sessions/week
            hevy.append(_hevy_day(d.isoformat(), 60))
    ctl, atl, tsb = tl.compute_ctl_atl_tsb([], today, hevy)
    assert tsb > 0, f"8 rest days after a block must read fresh, got TSB {tsb}"
    assert -30 <= tsb <= 30, f"TSB must live on the band scale the consumers assume, got {tsb}"
    # the old kJ-scale bug put CTL/ATL in the hundreds; TSS-like keeps them sane
    assert ctl < 100 and atl < 100, (ctl, atl)


def test_heavy_recent_block_reads_fatigued_within_band():
    today = date(2026, 7, 4)
    hevy = [_hevy_day((today - timedelta(days=i)).isoformat(), 90) for i in range(1, 11)]
    _ctl, _atl, tsb = tl.compute_ctl_atl_tsb([], today, hevy)
    assert tsb < 0, f"10 consecutive hard days must read fatigued, got {tsb}"
    assert tsb > -60, f"even a heavy block must not saturate the scale, got {tsb}"


# ── the C-6 fix: walks carry load ────────────────────────────────────────────


def test_walk_only_days_carry_load():
    today = date(2026, 7, 4)
    strava = [_walk_day((today - timedelta(days=i)).isoformat(), 75) for i in range(1, 30)]
    load_by_day, basis = tl.daily_training_load(strava, [], today)
    assert len(load_by_day) == 29, "every walk day must carry load"
    assert all(v > 0 for v in load_by_day.values())
    assert basis["strava_duration_days"] == 29
    assert basis["confidence"] == "duration_proxy"
    _ctl, _atl, tsb = tl.compute_ctl_atl_tsb(strava, today)
    assert tsb != 0.0, "walk-only history must produce a nonzero TSB"


def test_walk_and_lift_same_day_are_additive():
    today = date(2026, 7, 4)
    d = (today - timedelta(days=1)).isoformat()
    strava = [_walk_day(d, 60)]
    hevy = [_hevy_day(d, 60)]
    load_by_day, _ = tl.daily_training_load(strava, hevy, today)
    assert abs(load_by_day[d] - (tl.WALK_TSS_PER_HOUR + tl.LIFT_TSS_PER_HOUR)) < 0.5


def test_multi_device_duplicate_walk_not_double_counted():
    """Duplicates were harmless at 0 kJ; under the duration proxy they must dedup."""
    today = date(2026, 7, 4)
    d = (today - timedelta(days=1)).isoformat()
    a1 = {
        "type": "Walk",
        "sport_type": "Walk",
        "moving_time_seconds": 3600,
        "start_date_local": f"{d}T07:00:00",
        "distance_meters": 5000,
    }
    a2 = dict(a1, distance_meters=None, start_date_local=f"{d}T07:05:00")
    load_by_day, _ = tl.daily_training_load([{"date": d, "activities": [a1, a2]}], [], today)
    assert abs(load_by_day[d] - tl.WALK_TSS_PER_HOUR) < 0.5, load_by_day


# ── M-3: honest basis ────────────────────────────────────────────────────────


def test_basis_note_flags_proxy_loads():
    assert tl.basis_note({"confidence": "duration_proxy", "proxy_share": 1.0}) == " (duration-proxy basis)"
    assert tl.basis_note({"confidence": "mixed", "proxy_share": 0.8}) == " (duration-proxy basis)"
    assert tl.basis_note({"confidence": "power", "proxy_share": 0.0}) == ""
    assert tl.basis_note({"confidence": "hevy_fallback"}) == " (duration-proxy basis)"  # pre-#490 stored records
    assert tl.basis_note(None) == ""
    assert tl.basis_note({}) == ""


def test_basis_counts_and_shares():
    today = date(2026, 7, 4)
    d1 = (today - timedelta(days=1)).isoformat()
    d2 = (today - timedelta(days=2)).isoformat()
    strava = [
        {"date": d1, "activities": [{"kilojoules": 720, "type": "Ride"}]},
        _walk_day(d2, 60),
    ]
    _load, basis = tl.daily_training_load(strava, [], today)
    assert basis["strava_kj_days"] == 1 and basis["strava_duration_days"] == 1
    assert basis["strava_days"] == 2  # back-compat aggregate
    assert basis["confidence"] == "mixed"
    assert abs(basis["proxy_share"] - 25.0 / 125.0) < 0.001


def test_day_key_falls_back_to_sk():
    today = date(2026, 7, 4)
    d = (today - timedelta(days=1)).isoformat()
    rec = {"sk": f"DATE#{d}", "activities": [{"type": "Walk", "moving_time_seconds": 3600}]}
    load_by_day, _ = tl.daily_training_load([rec], [], today)
    assert d in load_by_day


# ── downstream band sanity (the three C-5 consumers) ─────────────────────────


def test_rest_tsb_scores_well_on_all_three_bands():
    """The acceptance criterion: 8 rest days no longer read as maximal fatigue on
    ANY of the three band consumers."""
    today = date(2026, 7, 4)
    hevy = []
    for i in range(8, 57):
        d = today - timedelta(days=i)
        if d.weekday() < 5:
            hevy.append(_hevy_day(d.isoformat(), 60))
    _ctl, _atl, tsb = tl.compute_ctl_atl_tsb([], today, hevy)

    readiness_component = max(0, min(100, round(60 + tsb * 2)))  # daily_metrics_compute
    mcp_score = max(0.0, min(100.0, 70.0 + tsb * 2.5))  # tools_health
    assert readiness_component > 60, (tsb, readiness_component)
    assert mcp_score > 70, (tsb, mcp_score)
    # character _in_range_score(-10, 25): fresh TSB must sit in/near the ideal range
    assert -10 <= tsb <= 25 or 0 < tsb, tsb
