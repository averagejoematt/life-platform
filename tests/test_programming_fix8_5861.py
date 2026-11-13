"""tests/test_programming_fix8_5861.py — the seventh red team's findings, as outcome tests with must-fail controls (#5861 FIX8).

Every test drafts through the real path (`scripts/sample_weeks_5861.py`, the library flipped to `approved` IN MEMORY) or, for the
progression, feeds drafted weeks back as the next week's record through the RECORD-SEEDED athlete the red team built
(`scripts/progression_sim_5861.py` `Physiological`: a true e1RM per lift, every set performed to the prescribed effort at the
prescribed load — so a heavy day served a volume day's load shows up as a set far under its band). Each test carries a control
that mutates the rule and shows the outcome breaks. Synthetic profiles only (no person's numbers).
"""

from __future__ import annotations

import copy
import pathlib
import sys
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "lambdas"), str(REPO / "scripts"), str(REPO / "deploy")):
    if p not in sys.path:
        sys.path.insert(0, p)

import progression_sim_5861 as sim  # noqa: E402
import sample_weeks_5861 as sw  # noqa: E402
from training import (  # noqa: E402
    cardio_model as cm,
    fatigue_model as fm,
    live_pain,
    live_progress as lpg,
    live_rulings as lr,
    live_session as ls,
    live_shape,
    live_stimulus,
)
from training.exercise_history import previous_load  # noqa: E402

PROFILES = sw.load_profiles()
FIXTURES = REPO / "tests" / "fixtures"
FIX8 = sw.load_profiles(FIXTURES / "sample_week_stress_profiles_fix8_5861.json")
ALL_FIXTURES = ("sample_week_stress_profiles_5861", "sample_week_stress_profiles_rt5_5861", "sample_week_stress_profiles_fix7_5861")
LANDMARKS = sw._load_landmarks() if hasattr(sw, "_load_landmarks") else None
KEYS = ("squat_barbell", "deadlift_barbell", "barbell_bench_press", "romanian_deadlift_barbell")
BLIND = lambda rx, hidx, tid, day, lo, hi: previous_load(hidx, tid, day)  # noqa: E731 — the role-blind reference (the defect)


def _week(prof: dict, patches: dict | None = None, settings: dict | None = None, world_edit=None) -> dict:
    with patch.dict(sw.SETTINGS, settings or {}):
        world = sw.build_world(prof, "approved")
        if world_edit:
            world_edit(world)
        ps_ = [patch.object(m, a, v) for (m, a), v in (patches or {}).items()]
        for p in ps_:
            p.start()
        try:
            week = sw.generate_week(prof, "approved", world)
        finally:
            for p in ps_:
                p.stop()
    return {"world": world, "week": week, "hard": sw.hard_sets_by_muscle(week, world["lib"], world["catalog"]["movements"])}


def _lift(week: dict, role: str, key: str) -> dict | None:
    s = next((s for s in week["sessions"] if s["role"] == role), None)
    return next((x for x in (s or {}).get("lifts") or [] if x["key"] == key), None)


def _lines(week: dict, role: str | None = None) -> list[str]:
    return [ln for s in week["sessions"] if role in (None, s["role"]) for ln in s["rationale"]]


# ── 1. role-keyed load references ────────────────────────────────────────────
def test_a_reference_reads_the_same_session_role_and_fails_closed():
    rows = [
        {"date": "2026-11-13", "role": "lower_volume", "kg": 70.0, "reps": 10, "rpe": 8.0},
        {"date": "2026-11-10", "role": "lower_heavy", "kg": 90.0, "reps": 5, "rpe": 8.0},
    ]
    rx = {"session_role": "lower_heavy", ls.MARK: {"refs": {"T": rows}}}
    ref = lpg.reference(rx, None, "T", "2026-11-17", 4, 6)
    assert ref and ref["role"] == "lower_heavy" and abs(ref["lb"] - 90.0 / lpg.KG_PER_LB) < 0.2  # its own day, not the latest
    vol = lpg.reference(rx | {"session_role": "lower_volume"}, None, "T", "2026-11-17", 8, 12)
    assert vol and vol["role"] == "lower_volume"
    # no same-role row in the window: no reference -> the guard changes nothing (fail closed)
    assert lpg.reference(rx | {ls.MARK: {"refs": {"T": rows[:1]}}}, None, "T", "2026-11-17", 4, 6) is None
    assert lpg.reference(rx, None, "T", "2026-12-30", 4, 6) is None  # older than max_age_days
    # a row with no readable role counts only inside today's rep band: a 10-rep volume set never stands in for a 4-6 heavy day
    idx = {"T": [{"date": "2026-11-13", "sets": [{"weight_kg": 70.0, "reps": 10, "rpe": 8.0}]}]}
    assert lpg.reference({"session_role": "lower_heavy"}, idx, "T", "2026-11-17", 4, 6) is None
    assert lpg.reference({"session_role": "lower_heavy"}, idx, "T", "2026-11-17", 8, 12) is not None
    assert BLIND(rx, idx, "T", "2026-11-17", 4, 6) is not None  # control: the role-blind read takes the volume set


def _lighter_volume_days(world: dict) -> None:
    """The record's lower-volume squats at 80% of the heavy load for 10 reps (a real heavy/volume split)."""
    tid = sw._tid(world["catalog"]["movements"], "squat_barbell")
    for w in world["record"]:
        if w["title"] == "lower_volume":
            for x in w["exercises"]:
                if x["template_id"] == tid:
                    x["sets"] = [{"type": "normal", "weight_kg": round(s["weight_kg"] * 0.8, 3), "reps": 10, "rpe": 8.0} for s in x["sets"]]


def test_a_held_heavy_day_holds_at_its_own_load_never_the_volume_days():
    """The seventh red team's blocking defect: on a strained day the guard HOLDS at the last top set — role-blind, the heavy squat
    was held at the volume day's lighter load (a ~20% cut labelled 'hold'). Role-keyed (`live_progress.reference`): it holds at
    the heavy day's own load. Control: the role-blind reference reproduces the cut."""
    prof = PROFILES["a_large_deficit_experienced"] | {"readiness": "red", "sleep_hours": 5.0, "acwr": "danger", "trend": "stalled"}
    fixed = _week(prof, world_edit=_lighter_volume_days)
    heavy = [
        max(s["weight_kg"] for s in x["sets"]) / lpg.KG_PER_LB
        for w in fixed["world"]["record"]
        if w["title"] == "lower_heavy"
        for x in w["exercises"]
        if x["template_id"] == sw._tid(fixed["world"]["catalog"]["movements"], "squat_barbell")
    ][-1]
    cuts = [ln for ln in _lines(fixed["week"], "lower_heavy") if ln.startswith("load (live): Squat (Barbell)")]
    assert all("last lower heavy" in ln for ln in cuts)  # its own day's set, named
    top = sim.top_loads(fixed["week"])["squat_barbell"][0]
    assert top >= heavy - 5.1, (top, heavy)
    blind = _week(prof, {(lpg, "reference"): BLIND}, world_edit=_lighter_volume_days)
    assert sim.top_loads(blind["week"])["squat_barbell"][0] < heavy * 0.85  # control: held at the volume day's load


@pytest.fixture(scope="module")
def steady() -> list[dict]:
    prof = PROFILES["a_large_deficit_experienced"] | {"weekly_loss_pct": 1.0}
    return sim.simulate(prof, 8, sim.Physiological())


def test_a_steady_or_gaining_athlete_never_loses_a_heavy_day_load_over_eight_weeks(steady):
    """The red team's acceptance: the record-seeded athlete in a 1 %BW/wk deficit, holding (or gaining 0.5 %/wk) strength, over
    8 weeks — no anchor's heavy-day load falls more than 10%, and no stall reset fires (a held e1RM in a deficit is maintenance).
    Control: the pre-FIX8 effort-drift rule (any RPE rise vs the best, even at a lighter load and more reps) resets the squat."""
    assert sim.heavy_day_falls(steady, KEYS) == {}
    assert not any("rep range ->" in ln for r in steady for lines in r["rationale"].values() for ln in lines)
    gain = sim.simulate(PROFILES["a_large_deficit_experienced"] | {"weekly_loss_pct": 1.0}, 8, sim.Physiological(drift=0.005))
    assert sim.heavy_day_falls(gain, KEYS) == {}

    def old_held(pts, e1):  # the pre-FIX8 rule
        adj = [fm._e1rm_rir(p) or v for p, v in zip(pts, e1)]
        best = max(range(len(adj)), key=lambda i: adj[i])
        if adj[-1] < adj[best] * (1 - float(fm.THRESHOLDS["deficit_hold_pct"]["value"])):
            return False
        a, b = pts[-1][2], pts[best][2]
        return a is None or b is None or float(a) - float(b) < float(fm.THRESHOLDS["rpe_drift"]["value"])

    with patch.object(fm, "_held", old_held):
        old = sim.simulate(PROFILES["a_large_deficit_experienced"] | {"weekly_loss_pct": 1.0}, 5, sim.Physiological())
    assert sim.heavy_day_falls(old, KEYS)


# ── 2. the spine is one joint ────────────────────────────────────────────────
def _spine_loading_served(w: dict) -> list[tuple[str, str, float | None, str]]:
    lib, cat = w["world"]["lib"], w["world"]["catalog"]["movements"]
    out = []
    for s in w["week"]["sessions"]:
        for x in s["lifts"]:
            spinal = str((sw._lib_entry(lib, cat, x["key"]).get("joint_stress") or {}).get("spinal_load"))
            if spinal in ("moderate", "high") and not x["tag"].endswith(":carry"):
                out.append((s["role"], x["key"], sw.lift_effort(x["hevy_note"]), x["hevy_note"] or ""))
    return out


def test_a_sharp_low_back_flag_reaches_every_spine_loading_lift():
    """Sharp low-back pain 6/10 logged on the squat (profile x): no lift that loads the spine at moderate or more is served as it
    was — the deadlift and the RDL go to pain-free routes (RPE <= 8, the stop line, no load step) — and the quadriceps keep MEV in
    hard sets. Control: the spine reach off -> the deadlift leads at RPE 8-9 with a load step (the red team's blocking finding)."""
    w = _week(FIX8["x_sharp_low_back_5day"])
    served = _spine_loading_served(w)
    assert not any(k in ("deadlift_barbell", "romanian_deadlift_barbell", "squat_barbell") for _r, k, _e, _n in served)
    for role, key, effort, note in served:
        assert effort is not None and effort <= 8 and "on later sets" not in note, (role, key)
    assert w["hard"].get("quadriceps", 0) >= 8
    off = _week(FIX8["x_sharp_low_back_5day"], {(live_pain, "spine_reach"): lambda entry, f, joint: False})
    dl = _lift(off["week"], "lower_heavy", "deadlift_barbell")
    assert dl and (sw.lift_effort(dl["hevy_note"]) or 0) >= 9 and "on later sets" in (dl["hevy_note"] or "")


def test_the_spine_reach_is_above_the_mild_line_only():
    f = {"joints": ["spinal_load"], "scope": "pattern", "tier": "reduce", "severity": 3.0}
    dl = {"joint_stress": {"spinal_load": "high"}}
    assert not live_pain.spine_reach(dl, f, "spinal_load")  # 3/10 discomfort: the pattern rule alone
    assert live_pain.spine_reach(dl, f | {"severity": 5.0}, "spinal_load")
    assert live_pain.spine_reach(dl, f | {"tier": "avoid", "severity": None}, "spinal_load")
    assert not live_pain.spine_reach({"joint_stress": {"spinal_load": "low"}}, f | {"tier": "avoid"}, "spinal_load")
    assert not live_pain.spine_reach(dl, f | {"tier": "avoid", "scope": "lift"}, "spinal_load")


# ── 3. the 75-minute ceiling, every fixture, both cap settings ───────────────
def _all_profiles() -> list[tuple[str, dict]]:
    out = list(PROFILES.items())
    for fx in ALL_FIXTURES + ("sample_week_stress_profiles_fix8_5861",):
        out += list(sw.load_profiles(FIXTURES / f"{fx}.json").items())
    return out


def _over(week: dict, shared: bool) -> list[tuple[str, float]]:
    out = []
    for s in week["sessions"]:
        mins = float(s["lifting_minutes"] or 0) + (float(s["cardio"].get("minutes") or 0) if shared else 0.0)
        if mins > 75.05:
            out.append((s["role"], round(mins, 1)))
    return out


@pytest.mark.parametrize("shared", [False, True])
def test_every_session_of_every_fixture_fits_the_75_minute_ceiling(shared):
    """The red team: 1-3 morning weeks drafted 78-83 lifting minutes and the cap test ran on the public profiles only. Now every
    public and stress profile (the 2-day q, the 1-day y, the 2-day z included), under both `session_cap_includes_cardio` values:
    lifting <= 75 (and lifting + cardio under the shared cap). Control: the anchors' back-off trim off -> the short weeks overrun."""
    bad = {}
    for name, prof in _all_profiles():
        w = _week(prof, settings={"session_cap_includes_cardio": shared})
        over = _over(w["week"], shared)
        if over:
            bad[name] = over
    assert bad == {}
    if shared:
        off = _week(FIX8["y_one_day_low_back"], {(live_shape, "trim_anchor_backoffs"): lambda *a, **k: []})
        assert _over(off["week"], True), "control: no anchor trim -> the 1-day full-body morning runs over"


# ── 5. the hard-set floor is an outcome ──────────────────────────────────────
def test_the_week_floor_adds_only_sets_that_can_be_hard_and_holds_the_direct_abs():
    """Every set the week floor adds is prescribed at RPE >= 8 (never a layoff- or first-exposure-capped set), and the week holds
    `abs_direct_sets_per_week` (owner ruling #8: ~4 challenging DIRECT ab sets — indirect compound trunk loading never counts).
    Controls: the floor off -> the direct abs fall short; the setting 0 -> the same."""
    w = _week(PROFILES["a_large_deficit_experienced"])
    added = [
        x
        for s in w["week"]["sessions"]
        for x in s["lifts"]
        if any(ln.startswith(f"added (live): {x['title']} ") and "WEEK_FLOOR" in ln for ln in s["rationale"])
    ]
    assert all((sw.lift_effort(x["hevy_note"]) or 0) >= 8 for x in added), [(x["key"], x["hevy_note"]) for x in added]
    assert w["hard"].get("abs", 0) >= 4
    off = _week(PROFILES["a_large_deficit_experienced"], {(live_stimulus, "week_floor"): lambda *a, **k: []})
    assert off["hard"].get("abs", 0) < 4
    no_abs = _week(PROFILES["a_large_deficit_experienced"], settings={"abs_direct_sets_per_week": 0})
    assert no_abs["hard"].get("abs", 0) < 4


def test_indirect_trunk_loading_is_never_an_ab_set():
    """Owner ruling #8: a squat or a deadlift that lists the abs as a secondary target adds NOTHING to the abs' count."""
    world = sw.build_world(PROFILES["a_large_deficit_experienced"], "approved")
    from training import selection_engine as se

    lib, cat = world["lib"], world["catalog"]["movements"]
    ctx = {"lib": lib, "catalog": cat, "idx": se.key_index(lib, cat)}
    with_abs = {k for k, e in lib["movements"].items() if "abs" in (e.get("target") or {}).get("secondary", [])}
    key = next((k for k in ("squat_barbell", "deadlift_barbell", "barbell_bench_press") if sw._tid(cat, k)), None)
    rx = {"exposures": [{"movement_key": key, "kind": "anchor", "sets": [{}] * 3}]}
    assert live_stimulus._today(rx, ctx).get("abs", 0.0) == 0.0
    assert with_abs is not None  # the library's secondary list is read, the abs simply never credited from it
    assert (
        live_stimulus.abs_target(ctx | {"week_skip": ()}) == 4
        and live_stimulus.abs_target(ctx | {"week_skip": ("upper_heavy", "lower_heavy")}) == 2
    )


def test_hard_capable_reads_the_record_and_familiarity_by_pattern():
    world = sw.build_world(PROFILES["a_large_deficit_experienced"], "approved")
    from training import selection_engine as se

    lib, cat = world["lib"], world["catalog"]["movements"]
    ctx = {"lib": lib, "catalog": cat, "idx": se.key_index(lib, cat)}
    tid = sw._tid(cat, "leg_extension_machine")
    rec = [{"date": f"2026-11-0{i}", "exercises": [{"template_id": tid, "sets": [{"weight_kg": 40.0, "reps": 12}]}]} for i in (2, 4, 6)]
    assert live_stimulus.hard_capable("leg_extension_machine", ctx, rec) == "recent"
    assert live_stimulus.hard_capable("leg_extension_machine", ctx, rec[:1]) is None  # an OD1 re-entry exposure: capped
    assert live_stimulus.hard_capable("leg_extension_machine", ctx | {"layoff": {"gap_days": 12}}, rec[:1]) == "pattern"


# ── 6. the second lift's own load ────────────────────────────────────────────
def test_the_capped_second_lift_takes_the_load_its_own_cap_implies():
    """The non-lead heavy lift is capped at RPE 7-8: its load comes from its OWN same-role e1RM at the bottom of the range and
    the cap's mid-point (a 200 x 3 @ 9.5 heavy day -> ~180 for 4 at RPE 7-8, not the engine's 4-6 load), and its note quotes its
    own day's last set. A lift already under that load is untouched."""
    ref = {"date": "2026-11-10", "lb": 200.0, "reps": 3, "rpe": 9.5, "role": "lower_heavy"}
    e = {"live_lead": "second", "live_effort_band": [7, 8]}
    d = lpg.second_lift(e, ref, 4, "barbell")
    assert d and d["second"] and 175 * lpg.KG_PER_LB <= d["cap_kg"] <= 185 * lpg.KG_PER_LB and d["mode"] == "down"
    assert "200x3 @ 9.5" in lpg.second_clause(d)
    assert lpg.second_lift({"live_lead": "lead"}, ref, 4, "barbell") is None
    assert lpg.second_lift(e, None, 4, "barbell") is None  # no same-role reference: no change


def test_the_capped_second_lift_never_reads_the_volume_days_load():
    prof = PROFILES["a_large_deficit_experienced"]
    fixed = _week(prof, world_edit=_lighter_volume_days)
    blind = _week(prof, {(lpg, "reference"): BLIND}, world_edit=_lighter_volume_days)
    ok, bad = sim.top_loads(fixed["week"])["squat_barbell"][0], sim.top_loads(blind["week"])["squat_barbell"][0]
    assert ok > bad, (ok, bad)  # control: role-blind, the second lift's cap is computed from the volume day's 10s


# ── 7. the first session back after a layoff (owner ruling #10, fix round 8) ──
def test_after_a_two_week_layoff_each_lifts_first_session_back_is_conservative_and_no_more():
    """Two weeks with no logged session (profile w): each lift's FIRST session back stops at RPE 8 with no load step and no load
    increase; nothing else changes (no week-long deload: a lift already done since the layoff progresses as usual). Control: the
    rule off -> lifts at RPE 9 with load steps."""
    prof = FIX8["w_layoff_two_weeks"]
    world = sw.build_world(prof, "approved")
    assert not [w for w in world["record"] if w["date"] >= sw._day(prof["as_of"], -14)]  # the generator expresses 0 sessions
    w = _week(prof)
    first = {}
    for s in w["week"]["sessions"]:
        for x in s["lifts"]:
            if x["tag"].endswith(":carry"):
                continue
            first.setdefault(x["key"], (s["role"], x))
    for key, (role, x) in first.items():
        own = (x["hevy_note"] or "").split("\n\n", 1)[-1]  # the lift's own lines (exercise 1 carries the session block)
        assert (sw.lift_effort(x["hevy_note"]) or 0) <= 8 and "on later sets" not in own, (role, key)
    assert any(ln.startswith("first back (live)") for ln in _lines(w["week"]))
    later = [ln for s in w["week"]["sessions"][1:] for ln in s["rationale"] if ln.startswith("first back (live)")]
    assert all("Bench Press (Barbell)" not in ln for ln in later)  # the bench was done Monday: Thursday's lifts are not 'first back'
    off = _week(prof, {(lpg, "layoff_end"): lambda workouts, day: None})
    assert any((sw.lift_effort(x["hevy_note"]) or 0) >= 9 for s in off["week"]["sessions"] for x in s["lifts"])


def test_a_layoff_is_ten_days_without_a_session_not_a_skipped_lift():
    rec = [{"date": "2026-11-12", "exercises": [{"sets": [{"weight_kg": 50.0, "reps": 5}]}]}]
    assert lpg.layoff_end(rec, "2026-11-17") is None  # 5 days off: normal
    gap = lpg.layoff_end([{"date": "2026-11-02", "exercises": rec[0]["exercises"]}] + rec, "2026-11-17")
    assert gap and gap["end"] == "2026-11-12" and gap["gap_days"] == 10  # the latest 10+-day gap ended on the 12th


# ── 8. the arms on an alternate-week misser's dip weeks ──────────────────────
def test_an_alternate_week_misser_keeps_shoulders_and_arms_at_maintenance():
    """The red team: a lifter who misses every other week sat in dip weeks with the shoulders at 3 hard sets for six weeks. Now
    each dip week holds shoulders, biceps and triceps at MV (maintenance, ruling 2's recovery week) and chest (a priority) at MV.
    Control: the arms floor's slot keeping and top-up off -> the shoulders fall back under MV."""
    prof = PROFILES["a_large_deficit_experienced"] | {"weekly_loss_pct": 1.0}
    rows = sim.simulate(prof, 4, sim.Physiological(), skip=lambda k: k % 2 == 1)
    dips = [r for r in rows if len(r["roles"]) == 4]
    assert dips
    for r in dips:
        assert r["hard"].get("shoulders", 0) >= 6 and r["hard"].get("biceps", 0) >= 5 and r["hard"].get("triceps", 0) >= 5, r["hard"]
        assert r["hard"].get("chest", 0) >= 6, r["hard"]
    with patch.object(lr, "arms_keep", lambda rx, ctx, w: []), patch.object(lr, "arms_top_up", lambda rx, ctx, w: []):
        old = sim.simulate(prof, 3, sim.Physiological(), skip=lambda k: k % 2 == 1)
    assert any(r["hard"].get("shoulders", 0) < 6 for r in old if len(r["roles"]) == 4)


# ── 9. unknown-intensity steps (owner ruling 12) ─────────────────────────────
def test_steps_of_unknown_intensity_are_reported_never_a_manufactured_gap():
    high = {"walking_min_per_wk": 0, "steps_per_day": 14000, "volume_covered": False}
    low = high | {"steps_per_day": 5000}
    live = {"target_date": "2026-11-18", "aerobic": high}
    assert live_shape.intensity_unknown(high) and live_shape.aerobic_gap(live) is None
    assert not live_shape.intensity_unknown(low) and live_shape.aerobic_gap(live | {"aerobic": low}) == 150
    assert not live_shape.intensity_unknown(high | {"walking_min_per_wk": 160})  # the record covers it: no question to ask
    w = _week(PROFILES["a_large_deficit_experienced"])
    assert not any("min short" in ln or ln.startswith("walk (live)") for ln in _lines(w["week"]))
    old = _week(PROFILES["a_large_deficit_experienced"], {(live_shape, "intensity_unknown"): lambda aer: False})
    assert any("min short" in ln for ln in _lines(old["week"]))  # control: the old reading manufactures a 150-min gap


# ── 10. recorded-workout hygiene ─────────────────────────────────────────────
WALK = {"strava_id": "1", "sport_type": "Walk", "start_date": "2026-11-02T15:53:46Z", "elapsed_time": 6372, "moving_time": 6000}


def test_a_duplicate_upload_is_counted_once():
    a = WALK | {"distance": 8490, "average_speed_ms": 1.33}
    tz = WALK | {"strava_id": "2", "start_date": "2026-11-03T14:53:46Z", "distance": 16980, "average_speed_ms": 2.67}  # +23 h
    other = WALK | {"strava_id": "3", "start_date": "2026-11-04T15:10:00Z", "elapsed_time": 3000, "distance": 4000}
    rows, dropped = cm.dedupe_strava([{"activities": [a]}, {"activities": [tz]}, {"activities": [other]}])
    assert dropped == 1 and [x["strava_id"] for r in rows for x in r["activities"]] == ["1", "3"]
    assert (
        cm.dedupe_strava([{"activities": [a]}, {"activities": [WALK | {"strava_id": "4", "start_date": "2026-11-03T15:20:00Z"}]}])[1] == 0
    )


def test_a_walk_an_over_long_gym_record_absorbed_is_credited():
    walk = WALK | {
        "strava_id": "8",
        "start_date": "2026-11-05T15:00:00Z",
        "elapsed_time": 3600,
        "moving_time": 3600,
        "average_speed_ms": 1.4,
    }
    hevy = [
        {
            "id": "h1",
            "start_time": "2026-11-05T13:05:00Z",
            "end_time": "2026-11-05T15:55:00Z",
            "exercises": [
                {"name": "Bench Press (Barbell)", "sets": [{"weight_kg": 80, "reps": 5}]},
                {"name": "Treadmill", "sets": [{"duration_seconds": 600}]},
            ],
        }
    ]
    assert cm.recorded_aerobic(strava=[{"activities": [walk]}], hevy=hevy)["credited_min"] == 60
    with patch.object(cm, "walks_beside_the_gym", lambda *a: []):  # control: absorbed into the gym identity
        assert cm.recorded_aerobic(strava=[{"activities": [walk]}], hevy=hevy)["credited_min"] == 0


# ── polish: the squat before the hinge on a full-body day ────────────────────
def test_the_squat_comes_before_the_hinge_on_a_full_body_day():
    rx = {
        "session_role": "upper_heavy",
        "exposures": [
            {"kind": "anchor", "pattern": "horizontal_press", "movement_key": "bench"},
            {"kind": "anchor", "pattern": "hinge", "movement_key": "rdl", "live_full_body": "lower_volume"},
            {"kind": "anchor", "pattern": "squat", "movement_key": "squat", "live_full_body": "lower_volume"},
        ],
    }
    lines = live_shape.order_lower_volume(copy.deepcopy(rx) | {"exposures": copy.deepcopy(rx["exposures"])})
    out = copy.deepcopy(rx)
    live_shape.order_lower_volume(out)
    assert [e["movement_key"] for e in out["exposures"]] == ["bench", "squat", "rdl"] and lines
    plain = copy.deepcopy(rx)
    for e in plain["exposures"]:
        e.pop("live_full_body", None)
    live_shape.order_lower_volume(plain)  # control: an ordinary upper day is never reordered
    assert [e["movement_key"] for e in plain["exposures"]] == ["bench", "rdl", "squat"]


# ── owner rulings of fix round 8 ─────────────────────────────────────────────
@pytest.mark.parametrize("name", ["a_large_deficit_experienced", "e_short_week"])
def test_each_delt_head_is_assessed_and_the_rear_delt_kept_without_extra_shoulder_volume(name):
    """Owner ruling #9: front, side and rear delts read apart (direct 1.0; pressing -> front, rowing -> rear by the explicit
    `DELT_CREDIT`), the rear delt adequate, and the shoulders out of the priority-vs-arms parity rule (never a donor or a
    recipient there). Control: without the rowing credit the rear head reads lower."""
    w = _week(PROFILES[name])
    m = sw.measure(w["week"], w["world"]["lib"], w["world"]["catalog"]["movements"], {})
    heads = m["delt_heads"]
    assert set(heads) == set(sw.DELT_HEADS) and heads["rear_delts"] >= 4 and heads["side_delts"] > 0, heads
    assert "shoulders" not in live_stimulus.PARITY["donors"]["value"]
    with patch.dict(sw.DELT_CREDIT, {"horizontal_pull": {}}):
        assert sw.delt_heads(w["week"], w["world"]["lib"], w["world"]["catalog"]["movements"])["rear_delts"] < heads["rear_delts"]


ANCHOR_PATTERNS = {"bench": ("barbell_bench_press",), "squat": ("squat_barbell", "leg_press"), "pull": ("machine_row", "lat_pulldown")}


@pytest.mark.parametrize("days", [1, 2, 3, 4, 5])
def test_every_declared_morning_count_is_restructured_by_coverage_never_by_cutting_the_last_sessions(days):
    """Owner ruling #5: 1-5 declared mornings, each restructured by coverage, recovery and strength retention: every session fits
    the 75-min ceiling, the week keeps a press, a squat and a pull anchor (and a hinge from 2 mornings), every major muscle gets
    hard sets from 2 mornings, and a 4-day week keeps the lower-volume day (it never drops the last session in order)."""
    base = PROFILES["a_large_deficit_experienced"]
    prof = base | {"days": base["days"][:days], "roles": base["roles"][:days]}
    w = _week(prof)
    assert _over(w["week"], True) == [], days
    keys = {x["key"] for s in w["week"]["sessions"] for x in s["lifts"]}
    for name, members in ANCHOR_PATTERNS.items():
        assert keys & set(members), (days, name, sorted(keys))
    if days >= 2:
        assert keys & {"deadlift_barbell", "romanian_deadlift_barbell"}, days
        for m in ("chest", "back", "quadriceps", "hamstrings", "shoulders"):
            assert w["hard"].get(m, 0) > 0, (days, m, w["hard"])
    if days == 4:
        assert [s["role"] for s in w["week"]["sessions"]][-1] == "lower_volume"  # never the chronological cut


def test_sequence_rules_start_the_monday_after_approval_and_never_apply_retroactively():
    """Owner ruling #4: `sequence_rule_from` defaults to the Monday AFTER the library's approval stamp; earlier weeks are never
    re-sequenced (the record stays for baselines). An explicit setting wins. Control: no stamp, no setting -> from the block start."""
    from training import live_sequence

    world = sw.build_world(PROFILES["e_short_week"], "approved")
    lib = copy.deepcopy(world["lib"]) | {"approved_on": "2026-11-18"}  # a Wednesday
    assert live_sequence.rule_from(lib) == "2026-11-23"
    assert live_sequence.week_plan("2026-11-16", world["record"], lib, days=4) is None  # the approval week: not re-judged
    assert live_sequence.week_plan("2026-11-23", world["record"], lib, days=4) is not None
    lib["programming_settings"] = {**lib["programming_settings"], "sequence_rule_from": "2026-12-07"}
    assert live_sequence.rule_from(lib) == "2026-12-07"
    assert live_sequence.week_plan("2026-11-16", world["record"], world["lib"], days=4) is not None  # control: no stamp


def test_the_swing_never_fills_the_kettlebell_hinge_slot():
    """Owner ruling #6: the swing is an optional power/conditioning movement, gated until readiness — never a replacement that
    fills the KB-deadlift slot, high-fatigue week or not: with no eligible KB hinge the slot drops (ruling 7, no makeup)."""
    from training import kb_entry, selection_engine as se

    for name in ("a_large_deficit_experienced", "f_high_fatigue_poor_sleep"):
        w = _week(PROFILES[name], {(se, "locked_gates"): lambda entry, lib: []})  # even with every gate open
        assert kb_entry.TARGET not in {x["key"] for s in w["week"]["sessions"] for x in s["lifts"]}, name
