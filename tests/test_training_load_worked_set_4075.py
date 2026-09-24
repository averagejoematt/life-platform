"""#4075 (owner ruling 2026-09-24, decision 4A): the Hevy term of training load is
charged on WORKED-SET time, not whole-session duration.

The contract pinned here:
  - rest is excluded: a longer session with the SAME set log carries the SAME load
    (mutation control — charging session duration fails it);
  - warm-ups are excluded by Hevy set type (mutation control — counting them fails it);
  - a working rep set is reps × SECONDS_PER_REP (a labelled, population-derived
    constant: Hevy stores no per-set time on rep sets), a timed hold is its MEASURED
    duration, mobility is 0;
  - a Hevy-logged cardio block takes the no-HR duration proxy ONLY for the minutes no
    HR-bearing Strava activity already scored (no double counting); a WHOOP
    weight-training copy of the lift stays skipped (worked-set time governs lifting);
  - every path that computes a TSB reads this ONE model (derivation guard).

The Hevy fixtures are the WIRE: the exact per-set keys the Hevy ingestion writes to
DynamoDB (`set_index`, `type`, `weight_kg`, `reps`, `rpe`, `distance_m`,
`duration_sec` — `duration_sec: None` on every rep set), with synthetic values.
"""

import ast
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lambdas"))

from training import training_load as tl  # noqa: E402

ROOT = Path(__file__).parent.parent
TODAY = date(2026, 9, 23)
DAY = (TODAY - timedelta(days=1)).isoformat()


def _set(i, *, type_="normal", reps=None, weight_kg=None, duration_sec=None, distance_m=None, rpe=None):
    # The stored Hevy set row, key for key (read-only DDB read of SOURCE#hevy 2026-09-23).
    return {
        "set_index": i,
        "type": type_,
        "weight_kg": weight_kg,
        "reps": reps,
        "rpe": rpe,
        "distance_m": distance_m,
        "duration_sec": duration_sec,
    }


def _workout(exercises, *, minutes=150, start="2026-09-22T12:00:00+00:00", end=None, day=DAY):
    return {
        "pk": "USER#matthew#SOURCE#hevy",
        "sk": f"DATE#{day}#WORKOUT#00000000-0000-0000-0000-000000000001",
        "date": day,
        "source": "hevy",
        "title": "Foundation - Push - 9 - 99",
        "start_time": start,
        "end_time": end or "2026-09-22T14:30:00+00:00",
        "duration_sec": minutes * 60,
        "exercises": exercises,
    }


def _lift(name, n_sets, reps, *, warmups=0):
    sets = [_set(i, type_="warmup", reps=reps, weight_kg=20.0) for i in range(warmups)]
    sets += [_set(warmups + i, reps=reps, weight_kg=60.0, rpe=8.0) for i in range(n_sets)]
    return {"name": name, "notes": "", "template_id": "ABCDEF01", "sets": sets}


def _timed(name, secs, distance_m=None):
    return {"name": name, "notes": "", "template_id": "ABCDEF02", "sets": [_set(0, duration_sec=secs, distance_m=distance_m)]}


def _points_per_rep_set(reps):
    return reps * tl.SECONDS_PER_REP / 3600.0 * tl.LIFT_TSS_PER_HOUR


# ── the per-set rules ─────────────────────────────────────────────────────────


def test_working_rep_sets_are_charged_reps_times_the_stated_tempo():
    w = _workout([_lift("Bench Press (Barbell)", 4, 10), _lift("Lat Pulldown (Cable)", 3, 12)])
    s = tl.hevy_session_load(w)
    assert s["basis"] == "worked_set"
    assert s["working_rep_sets"] == 7
    assert s["rep_seconds_assumed"] == (4 * 10 + 3 * 12) * tl.SECONDS_PER_REP == 228.0
    assert abs(s["points"] - (4 * _points_per_rep_set(10) + 3 * _points_per_rep_set(12))) < 1e-9
    # 7 working sets ≈ 3.2 points; the whole 150-min session at the old rate was 125.
    assert s["points"] < 5 < 150 / 60 * tl.LIFT_TSS_PER_HOUR


def test_rest_is_excluded_mutation_control():
    """The SAME set log in a 60-min and a 210-min session carries the SAME load. A model
    that charged session duration (the pre-4A term) fails this."""
    lifts = [_lift("Squat (Barbell)", 5, 5), _lift("Leg Press", 3, 12)]
    short = tl.hevy_session_load(_workout(lifts, minutes=60))["points"]
    long_ = tl.hevy_session_load(_workout(lifts, minutes=210))["points"]
    assert short == long_ > 0


def test_warmups_are_excluded_by_set_type_mutation_control():
    """Two warm-up sets add nothing; the same two sets typed "normal" add exactly their
    worked time. Counting warm-ups (as health.tdee's energy term deliberately does) fails."""
    with_wu = tl.hevy_session_load(_workout([_lift("Bench Press (Barbell)", 3, 8, warmups=2)]))
    no_wu = tl.hevy_session_load(_workout([_lift("Bench Press (Barbell)", 3, 8)]))
    assert with_wu["points"] == no_wu["points"]
    assert with_wu["warmup_sets"] == 2 and with_wu["working_rep_sets"] == 3
    as_working = tl.hevy_session_load(_workout([_lift("Bench Press (Barbell)", 5, 8)]))
    assert abs(as_working["points"] - with_wu["points"] - 2 * _points_per_rep_set(8)) < 1e-9


def test_a_timed_hold_is_its_measured_duration_and_mobility_is_zero():
    w = _workout([_timed("Plank", 90), _timed("Stretching", 900)])
    s = tl.hevy_session_load(w)
    assert s["measured_hold_seconds"] == 90 and s["mobility_seconds"] == 900
    assert abs(s["points"] - 90 / 3600 * tl.LIFT_TSS_PER_HOUR) < 1e-9


def test_a_logged_cardio_block_takes_the_no_hr_rate_for_its_modality():
    # 60 min treadmill at 4.8 km/h = 1.33 m/s → walking pace → the walk rate.
    walk = tl.hevy_session_load(_workout([_timed("Treadmill", 3600, distance_m=4800)]))
    assert abs(walk["points"] - tl.WALK_TSS_PER_HOUR) < 1e-9 and walk["cardio_seconds"] == 3600
    # 45 min stationary cycling → the default no-HR cardio rate.
    ride = tl.hevy_session_load(_workout([_timed("Cycling", 2700, distance_m=15000)]))
    assert abs(ride["points"] - 0.75 * tl.DEFAULT_CARDIO_TSS_PER_HOUR) < 1e-9
    # A treadmill RUN (10 km/h) is not walking pace.
    run = tl.hevy_session_load(_workout([_timed("Treadmill", 1800, distance_m=5000)]))
    assert abs(run["points"] - 0.5 * tl.DEFAULT_CARDIO_TSS_PER_HOUR) < 1e-9


def test_a_workout_with_no_set_log_takes_the_stated_work_fraction():
    """The fraction is health.tdee's ONE constant (read from there, not restated); the
    tdee value is read by AST so this file drives no module with a clock (#2376)."""
    tdee_src = (ROOT / "lambdas/health/tdee.py").read_text(encoding="utf-8")
    fraction = next(
        ast.literal_eval(n.value)
        for n in ast.walk(ast.parse(tdee_src))
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "LIFTING_WORK_FRACTION_FALLBACK" for t in n.targets)
    )
    assert "from health.tdee import LIFTING_WORK_FRACTION_FALLBACK" in (ROOT / "lambdas/training/training_load.py").read_text(
        encoding="utf-8"
    )
    s = tl.hevy_session_load({"date": DAY, "duration_sec": 120 * 60})
    assert s["basis"] == "no_set_log_work_fraction"
    assert abs(s["points"] - 2.0 * fraction * tl.LIFT_TSS_PER_HOUR) < 1e-9


def test_the_hevy_api_wire_name_for_duration_is_read_too():
    ex = {"name": "Plank", "sets": [{"type": "normal", "duration_seconds": 60, "reps": None}]}
    assert tl.hevy_session_load(_workout([ex]))["measured_hold_seconds"] == 60


# ── HR vs worked-set time: which governs ─────────────────────────────────────


def _whoop(sport, start_utc, minutes, avg_hr):
    return {
        "sport_type": sport,
        "type": sport,
        "device_name": "WHOOP",
        "start_date": start_utc,
        "elapsed_time_seconds": minutes * 60,
        "moving_time_seconds": minutes * 60,
        "average_heartrate": avg_hr,
    }


def test_hr_governs_a_cardio_block_it_overlaps_and_the_lift_stays_on_worked_set_time():
    """A WHOOP walk covering the Hevy treadmill block: the block is NOT charged again
    (the walk is scored by HR), and the WHOOP weight-training copy of the lift is skipped
    as an echo — worked-set time governs lifting. No minute is counted twice."""
    w = _workout([_lift("Bench Press (Barbell)", 4, 10), _timed("Treadmill", 3600, distance_m=4800)])
    whoop_walk = _whoop("Walk", "2026-09-22T13:20:00Z", 60, 113.0)
    whoop_lift = _whoop("WeightTraining", "2026-09-22T12:05:00Z", 60, 121.0)
    load, basis = tl.daily_training_load([{"date": DAY, "activities": [whoop_lift, whoop_walk]}], [w], TODAY)
    expected = 4 * _points_per_rep_set(10) + tl.hr_load(1.0, 113.0)
    assert abs(load[DAY] - round(expected, 1)) < 0.06, (load, expected)
    assert basis["worked_set"]["cardio_hr_covered_seconds"] == 3600
    # Mutation control: move the walk outside the session and the block IS charged.
    away = dict(whoop_walk, start_date="2026-09-22T18:00:00Z")
    load2, _ = tl.daily_training_load([{"date": DAY, "activities": [whoop_lift, away]}], [w], TODAY)
    assert abs(load2[DAY] - load[DAY] - tl.WALK_TSS_PER_HOUR) < 0.1


def test_partial_hr_cover_charges_only_the_uncovered_share():
    w = _workout([_timed("Cycling", 3600, distance_m=20000)])
    half = _whoop("Walk", "2026-09-22T12:00:00Z", 30, 112.0)
    s = tl.hevy_session_load(w, tl.hr_intervals([half]))
    assert s["cardio_hr_covered_seconds"] == 1800
    assert abs(s["cardio_points"] - 0.5 * tl.DEFAULT_CARDIO_TSS_PER_HOUR) < 1e-9


def test_an_hr_less_or_echo_activity_never_counts_as_hr_cover():
    no_hr = dict(_whoop("Walk", "2026-09-22T12:00:00Z", 60, None))
    echo = _whoop("WeightTraining", "2026-09-22T12:00:00Z", 60, 125.0)
    assert tl.hr_intervals([no_hr, echo]) == []


# ── the Strava-only paths (digests, brief fallback) ──────────────────────────


def test_strava_weight_training_without_hr_or_set_log_is_charged_the_work_fraction():
    """The weekly/monthly digests read Strava only. A Hevy-pushed WeightTraining copy
    with no HR must not be charged as a whole session of work there either."""
    pts, basis = tl.activity_load({"sport_type": "WeightTraining", "device_name": "Hevy", "moving_time_seconds": 150 * 60})
    assert basis == "duration" and abs(pts - 2.5 * 0.25 * tl.LIFT_TSS_PER_HOUR) < 1e-9


def test_a_tombstoned_legacy_aggregate_is_not_counted():
    w = _workout([_lift("Bench Press (Barbell)", 4, 10)])
    legacy = {"date": DAY, "sk": f"DATE#{DAY}", "duration_sec": 7200, "tombstone": True}
    load, _ = tl.daily_training_load([], [w, legacy], TODAY)
    assert abs(load[DAY] - round(4 * _points_per_rep_set(10), 1)) < 0.06


# ── the labelled basis (ADR-105) ─────────────────────────────────────────────


def test_basis_names_the_model_and_the_provenance_of_the_per_set_time():
    w = _workout([_lift("Bench Press (Barbell)", 3, 10, warmups=1), _timed("Plank", 60), _timed("Stretching", 600)])
    _load, basis = tl.daily_training_load([], [w], TODAY)
    assert basis["model"] == tl.LOAD_MODEL == "trimp_above_z1_plus_hevy_worked_set_v2"
    assert basis["lift_model"] == tl.LIFT_MODEL and basis["hr_model"] == tl.HR_MODEL
    ws = basis["worked_set"]
    assert ws["seconds_per_rep"] == tl.SECONDS_PER_REP == 3.0
    assert "acsm_2009" in ws["seconds_per_rep_source"]
    assert ws["assumed_seconds"] == 90.0 and ws["measured_seconds"] == 60.0 and ws["worked_seconds"] == 150.0
    assert ws["warmup_sets_excluded"] == 1 and ws["mobility_seconds_excluded"] == 600.0
    assert basis["confidence"] == "worked_set" and basis["worked_set_share"] == 1.0 and basis["proxy_share"] == 0.0
    assert not tl.is_duration_proxy(basis)


def test_the_per_rep_constant_carries_a_citation_in_source():
    src = (ROOT / "lambdas/training/training_load.py").read_text(encoding="utf-8")
    assert "Ratamess et al. 2009" in src and "41(3):687" in src


# ── a fortnight: the #4075 specimen shape ────────────────────────────────────


def test_a_fortnight_of_long_sessions_no_longer_reads_deeply_fatigued():
    """14 daily 150-min sessions of 20 working sets × 10 reps + a 60-min HR-covered Z1
    treadmill walk + 15 min stretching — the shape of 2026-09-08..22. Charged on session
    duration this read TSB ≈ −61 (#4113's replay); on worked-set time the load is the
    lifting actually done. Mutation control: the same fortnight with the pre-4A session
    charge (50/h × 150 min/day) reads fatigued by an order of magnitude more."""
    hevy, strava = [], []
    for i in range(1, 15):
        d = (TODAY - timedelta(days=i)).isoformat()
        start = f"{d}T12:00:00+00:00"
        hevy.append(
            dict(
                _workout(
                    [
                        _lift("Bench Press (Barbell)", 10, 10),
                        _lift("Row", 10, 10),
                        _timed("Treadmill", 3600, 4800),
                        _timed("Stretching", 900),
                    ],
                    start=start,
                    end=f"{d}T14:30:00+00:00",
                    day=d,
                ),
                sk=f"DATE#{d}#WORKOUT#{i}",
            )
        )
        strava.append({"date": d, "activities": [_whoop("Walk", f"{d}T13:30:00Z", 60, 108.0)]})
    _c, _a, tsb = tl.compute_ctl_atl_tsb(strava, TODAY, hevy)
    per_day = 20 * _points_per_rep_set(10)
    assert per_day < 10
    assert -10 < tsb < 0, tsb
    old = {(TODAY - timedelta(days=i)).isoformat(): 150 / 60 * tl.LIFT_TSS_PER_HOUR for i in range(1, 15)}
    _c, _a, tsb_old = tl.banister(old, TODAY)
    assert tsb_old < 10 * tsb < 0, (tsb_old, tsb)


# ── ONE load derivation (derivation guard) ───────────────────────────────────


def _py_files():
    for base in ("lambdas", "mcp"):
        for f in (ROOT / base).rglob("*.py"):
            yield f.relative_to(ROOT).as_posix(), f.read_text(encoding="utf-8")


def test_the_lift_rate_and_the_per_rep_tempo_live_in_one_module():
    """No second Hevy-duration × rate load model anywhere a TSB is computed or served."""
    pat = re.compile(r"\b(LIFT_TSS_PER_HOUR|SECONDS_PER_REP)\s*=")
    hits = [rel for rel, text in _py_files() if pat.search(text)]
    assert hits == ["lambdas/training/training_load.py"], hits
    assert not [rel for rel, text in _py_files() if "def compute_daily_load_score" in text]


def test_every_tsb_producer_reads_training_load():
    """Every module that PRODUCES a CTL/ATL/TSB reads it through training_load (the
    stored computed_metrics TSB → readiness, brief, AI context's deficit+fatigue rule;
    the dashboard; the digests; the brief's fallback; MCP view=load)."""
    producers = {
        "lambdas/compute/daily_metrics_compute_lambda.py": "training_load.compute_ctl_atl_tsb",
        "lambdas/compute/dashboard_refresh_lambda.py": "training_load.compute_ctl_atl_tsb",
        "lambdas/emails/daily_brief_signals.py": "training_load.compute_ctl_atl_tsb",
        "lambdas/common/digest_utils.py": "training_load.banister",
        "mcp/tools_training.py": "training_load.daily_training_load",
    }
    for rel, call in producers.items():
        assert call in (ROOT / rel).read_text(encoding="utf-8"), f"{rel} no longer calls {call}"


def test_the_energy_targets_load_input_is_the_stored_tsb_not_a_recompute():
    """The one place training load reaches the calorie side is ai_context's
    "aggressive deficit + TSB < −10" rule. It must read the STORED tsb (this model),
    never recompute one. health.tdee (the calorie target itself) reads no load at all."""
    ctx = (ROOT / "lambdas/ai/ai_context.py").read_text(encoding="utf-8")
    assert 'data.get("tsb")' in ctx
    assert "compute_ctl_atl_tsb" not in ctx and "banister(" not in ctx
    tdee_tree = ast.parse((ROOT / "lambdas/health/tdee.py").read_text(encoding="utf-8"))
    imported = {n.module for n in ast.walk(tdee_tree) if isinstance(n, ast.ImportFrom)}
    assert not any(m and "training" in m for m in imported)
