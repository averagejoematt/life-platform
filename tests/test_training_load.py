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

from training import training_load as tl  # noqa: E402


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


def test_hr_backed_cardio_is_normalised_to_100_per_hour_at_threshold():
    # 1 h at threshold HR ≈ 100 points — the hrTSS normalisation every TSB band assumes.
    pts, basis = tl.activity_load({"type": "Run", "moving_time_seconds": 3600, "average_heartrate": tl.THRESHOLD_HR})
    assert abs(pts - 100.0) < 0.01
    assert basis == "hr"
    # #4075: the old IF ≥ 0.4 clamp floored ANY HR-bearing hour at 16 points; an HR at or
    # below the Zone-1 ceiling now scores exactly 0.
    easy, basis = tl.activity_load({"type": "Run", "moving_time_seconds": 3600, "average_heartrate": 40})
    assert easy == 0.0 and basis == "hr"


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


# ── #4075: HR-based load; Zone-1 walking is not training stress ──────────────


def _hr_walk(minutes, avg_hr):
    return {"type": "Walk", "sport_type": "Walk", "moving_time_seconds": minutes * 60, "average_heartrate": avg_hr}


def test_z1_ceiling_is_derived_from_the_platforms_one_zone_table():
    """The Z1 ceiling is not a new number: it is the platform's zone-1 upper bound
    (mcp/helpers.HR_ZONE_BOUNDS, mirrored by site_api_autonomic._ZONE_BOUNDS) × the
    owner's measured max HR. Pin all three tables together so none can move alone.
    Both tables are read from SOURCE by AST — importing a handler module here would
    drive its clock from this file's dated fixtures (#2376)."""
    import ast

    root = Path(__file__).parent.parent

    def _bounds(rel, name):
        tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                return ast.literal_eval(node.value)
        raise AssertionError(f"{name} not found in {rel}")

    helpers = _bounds("mcp/helpers.py", "HR_ZONE_BOUNDS")
    autonomic = _bounds("lambdas/web/site_api_autonomic.py", "_ZONE_BOUNDS")
    assert helpers[0][0] == "zone_1" and autonomic[0][0] == "zone_1"
    assert tl.Z1_CEILING_FRACTION_OF_MAX == helpers[0][3] == autonomic[0][3]
    assert tl.Z1_CEILING_HR == round(tl.MAX_HR * tl.Z1_CEILING_FRACTION_OF_MAX, 1) == 109.8


def test_a_redline_compliant_walk_scores_exactly_zero():
    """The programme's walking cap (owner_redlines, 105 bpm) sits under the Z1 ceiling,
    so every walk the plan prescribes contributes nothing to ATL/CTL."""
    from training.owner_redlines import REDLINES

    cap = REDLINES["walking_floor_hr_wk"]["hr_ceiling_bpm"]
    assert cap <= tl.Z1_CEILING_HR
    pts, basis = tl.activity_load(_hr_walk(75, cap))
    assert pts == 0.0 and basis == "hr"


def test_z1_walk_with_hr_is_near_zero_while_the_same_walk_without_hr_is_proxied():
    """The specimen: a 58-min walk at 113.4 bpm (2026-09-14, WHOOP). Scored by HR it is
    ~1-2 points; the duration proxy (no HR) would have charged it 25 points/h."""
    pts, basis = tl.activity_load(_hr_walk(58, 113.4))
    assert basis == "hr"
    assert 0 < pts < 2.0, pts
    proxy, pbasis = tl.activity_load({"type": "Walk", "moving_time_seconds": 58 * 60})
    assert pbasis == "duration" and abs(proxy - 58 / 60 * tl.WALK_TSS_PER_HOUR) < 0.01


def test_hr_load_is_monotone_in_intensity_and_linear_in_time():
    hrs = [100, 109, 115, 125, 140, 165, 180]
    pts = [tl.hr_load(1.0, h) for h in hrs]
    assert pts == sorted(pts) and pts[0] == pts[1] == 0.0 and pts[-1] > 100
    assert abs(tl.hr_load(2.0, 140) - 2 * tl.hr_load(1.0, 140)) < 1e-9


def test_z1_walking_fortnight_leaves_tsb_near_zero_mutation_control():
    """Two walks a day for 14 days at Zone-1 HR → TSB ≈ 0. The mutation control: the
    SAME walks with no HR take the duration proxy and read fatigued. If the HR branch
    is removed or re-ordered behind the walk branch, the first assertion fails."""
    today = date(2026, 9, 23)
    days = [(today - timedelta(days=i)).isoformat() for i in range(1, 15)]
    with_hr = [{"date": d, "activities": [_hr_walk(60, 108), dict(_hr_walk(60, 112), start_date_local=f"{d}T18:00:00")]} for d in days]
    _c, _a, tsb = tl.compute_ctl_atl_tsb(with_hr, today)
    assert abs(tsb) < 1.0, tsb
    no_hr = [
        {"date": r["date"], "activities": [{k: v for k, v in a.items() if k != "average_heartrate"} for a in r["activities"]]}
        for r in with_hr
    ]
    _c, _a, tsb_proxy = tl.compute_ctl_atl_tsb(no_hr, today)
    assert tsb_proxy < -10, tsb_proxy


def test_duration_proxy_only_when_hr_absent_and_labelled():
    today = date(2026, 9, 23)
    d = (today - timedelta(days=1)).isoformat()
    _load, basis = tl.daily_training_load([{"date": d, "activities": [_hr_walk(60, 130)]}], [], today)
    assert basis["confidence"] == "hr" and basis["strava_hr_days"] == 1 and basis["strava_duration_days"] == 0
    assert basis["proxy_share"] == 0.0 and basis["hr_share"] == 1.0
    assert basis["model"] == tl.HR_MODEL and basis["z1_ceiling_bpm"] == tl.Z1_CEILING_HR
    assert not tl.is_duration_proxy(basis) and tl.basis_note(basis) == ""
    _load, basis = tl.daily_training_load([{"date": d, "activities": [{"type": "Walk", "moving_time_seconds": 3600}]}], [], today)
    assert basis["confidence"] == "duration_proxy" and tl.is_duration_proxy(basis)
    assert tl.basis_note(basis) == " (duration-proxy basis)"


def test_a_z1_walk_day_counts_as_an_hr_day_even_when_it_scores_zero():
    today = date(2026, 9, 23)
    d = (today - timedelta(days=1)).isoformat()
    load, basis = tl.daily_training_load([{"date": d, "activities": [_hr_walk(60, 100)]}], [], today)
    assert load == {} and basis["strava_hr_days"] == 1 and basis["confidence"] == "none"


def test_hevy_pushed_workout_echo_is_not_double_counted():
    """#4075 specimen: Hevy 'Engine' sessions reach Strava as sport_type Workout from
    device 'Hevy' with no HR, and were charged 50 points/h ON TOP of the Hevy term."""
    today = date(2026, 9, 23)
    d = (today - timedelta(days=1)).isoformat()
    echo = {"sport_type": "Workout", "device_name": "Hevy", "moving_time_seconds": 125 * 60}
    load, _ = tl.daily_training_load([{"date": d, "activities": [echo]}], [_hevy_day(d, 125)], today)
    assert abs(load[d] - 125 / 60 * tl.LIFT_TSS_PER_HOUR) < 0.1, load
    # Without a Hevy record that day the Strava copy is the only record and still counts.
    load, _ = tl.daily_training_load([{"date": d, "activities": [echo]}], [], today)
    assert abs(load[d] - 125 / 60 * tl.DEFAULT_CARDIO_TSS_PER_HOUR) < 0.1, load
    assert tl.is_hevy_echo(echo) and not tl.is_hevy_echo({"sport_type": "Walk", "device_name": "WHOOP"})


def test_hevy_sk_rows_resolve_to_their_day():
    rec = {"sk": "DATE#2026-09-14#WORKOUT#f2ee5131", "duration_sec": 3600}
    assert tl.day_key(rec) == "2026-09-14"


def test_no_second_trimp_implementation_in_the_training_or_compute_paths():
    """Derivation guard (#4075): the Banister TRIMP weighting lives in ONE place on the
    paths that write/serve the stored TSB. A second copy is how two TSBs disagree.
    `mcp/helpers.compute_daily_load_score` is the one known, named exception (the MCP
    get_training view=load model) — see #4075's PR for why it was not rewired here."""
    import re

    root = Path(__file__).parent.parent
    pat = re.compile(r"exp\(\s*1\.92")
    allowed = {"lambdas/training/training_load.py", "mcp/helpers.py"}
    hits = []
    for base in ("lambdas", "mcp"):
        for f in (root / base).rglob("*.py"):
            rel = f.relative_to(root).as_posix()
            if rel not in allowed and pat.search(f.read_text(encoding="utf-8")):
                hits.append(rel)
    assert hits == [], hits
    assert "TRIMP_B = 1.92" in (root / "lambdas/training/training_load.py").read_text(encoding="utf-8")
