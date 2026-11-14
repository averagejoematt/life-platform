"""#5861 FIX6 — THE OWNER'S RULINGS OF 2026-11-13 on the decision register, as LIVE-only behaviour (the library stays
`proposed`; tests/test_no_live_change_5861_l6.py holds the proposed drafts byte-identical and poisons every entry point here).

One section per ruling: the ruled default, the outcome on the drafted week, and a must-fail control in the same test (mutate the
rule or flip the setting -> the assertion goes red). Synthetic profiles only (tests/fixtures/sample_week_profiles_5861.json).

Fix round 9 (consolidation): the OUTCOMES of every ruling are re-pinned against the consolidated rules — one settings table
(`live_settings`), one volume plan + one time fit (`live_volume`), one load model (`live_load`). The mechanisms the earlier rounds
pinned here (ALLOCATION, ARMS_FLOOR, PRIORITY_ADD, the KB slot and its template setting, the symptom presets) are gone; the
outcomes are not.
"""

from __future__ import annotations

import copy
import json
import pathlib
import re
import sys
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
for _p in (REPO, REPO / "lambdas", REPO / "scripts", REPO / "deploy"):
    sys.path.insert(0, str(_p))

import sample_weeks_5861 as sw  # noqa: E402
from health import rate_policy  # noqa: E402
from training import (  # noqa: E402
    cardio_model as cm,
    live_program as lp,
    live_rulings as lr,
    live_sequence,
    live_settings,
    live_volume,
    quality_rubric as qr,
    routine_generator as rg,
    selection_engine as se,
    selection_live,
)

LIB0 = json.loads((REPO / "config" / "exercise_library.json").read_text())
PROFILES = sw.load_profiles()
LANDMARKS = rg._load_json("training_landmarks.json")


def _week(name: str, patches: dict | None = None, settings: dict | None = None, profile: dict | None = None) -> dict:
    prof = profile or PROFILES[name]
    with patch.dict(sw.SETTINGS, settings or {}):
        world = sw.build_world(prof, "approved")
        ps_ = [patch.object(m, a, v) for (m, a), v in (patches or {}).items()]
        for p in ps_:
            p.start()
        try:
            week = sw.generate_week(prof, "approved", world)
        finally:
            for p in ps_:
                p.stop()
    return {"week": week, "world": world, "m": sw.measure(week, world["lib"], world["catalog"]["movements"], LANDMARKS)}


@pytest.fixture(scope="module")
def weeks() -> dict:
    return {n: _week(n) for n in PROFILES}


def _lifts(week: dict, role: str | None = None) -> list[dict]:
    return [x for s in week["sessions"] if role in (None, s["role"]) for x in s["lifts"]]


# ── the settings: ruled, library-carried, one table ──────────────────────────────────────────────────────────────────────
def test_every_ruled_setting_is_library_carried_and_equal_to_its_code_default():
    have = LIB0["programming_settings"]
    assert have == live_settings.defaults()  # the ONE table, written by the builder (no per-round dicts, no stale disk value)
    assert LIB0["status"] == "proposed"  # configuration, never activation
    stale = {"behind_schedule_week", "adherence_response", "cardio_purpose_only", "kb_slot_role", "symptom_line", "rate_band_mode"}
    assert not stale & set(have)  # the dead alternatives the owner ruled out are gone from the data
    assert live_settings.settings({"programming_settings": {"press_sets": 2}})["press_sets"] == 2  # control: a value on disk wins


# ── ruling 1: the shared cap; the whole morning fits, strength is never cut for cardio ─────────────────────────────────────
def test_ruling_1_the_whole_morning_fits_and_no_needed_set_is_cut_for_cardio(weeks):
    for name, w in weeks.items():
        assert all(p["morning_minutes"] <= 75.05 for p in w["m"]["per_session"]), name
        assert not any(ln.startswith("cardio room") for s in w["week"]["sessions"] for ln in s["live_fit"] or []), name
    off = _week("e_short_week", {(live_volume, "time_fit"): lambda *a, **k: []})  # control: no time fit -> over the cap
    assert any(p["lifting_minutes"] > 75.05 for p in off["m"]["per_session"])


# ── ruling 2: the 4-session week after missed sessions ───────────────────────────────────────────────────────────────────────
def test_ruling_2_a_dip_is_answered_by_a_four_session_week_without_make_up_sets(weeks):
    d = weeks["d_stalled_anchor_adherence_dip"]["week"]
    assert len(d["sessions"]) == 4 and "shoulders_arms" not in {s["role"] for s in d["sessions"]}
    total = sum(x["working_sets"] for x in _lifts(d))
    full = sum(x["working_sets"] for x in _lifts(weeks["a_large_deficit_experienced"]["week"]))
    assert total < full  # no make-up: the missed sets are not re-served
    nodip = _week("d_stalled_anchor_adherence_dip", {(live_sequence, "_dip"): lambda workouts, monday: False})["week"]  # control
    assert len(nodip["sessions"]) == 5


# ── ruling 3: the 4-day week holds shoulders and arms at MEV, counted ───────────────────────────────────────────────────────
def test_ruling_3_the_four_day_week_keeps_shoulders_and_arms_at_mev(weeks):
    e = weeks["e_short_week"]
    assert "shoulders_arms" not in {s["role"] for s in e["week"]["sessions"]} and len(e["week"]["sessions"]) == 4
    hard = e["m"]["hard_sets"]
    under = [mu for mu in live_volume.FOUR_DAY_MEV if hard.get(mu, 0) < LANDMARKS["muscles"][mu]["MEV"]]
    assert under == [], (under, hard)
    with patch.object(live_volume, "FOUR_DAY_MEV", ()):  # control: the counted floor off -> an arm or the delts under MEV
        off = _week("e_short_week")
    assert any(off["m"]["hard_sets"].get(mu, 0) < LANDMARKS["muscles"][mu]["MEV"] for mu in ("shoulders", "biceps", "triceps"))


# ── ruling 4: purposeful cardio only ─────────────────────────────────────────────────────────────────────────────────────────
def test_ruling_4_no_cardio_block_without_a_named_purpose(weeks):
    for name, w in weeks.items():
        for s in w["week"]["sessions"]:
            if s["cardio"].get("key"):
                assert any(ln.startswith("cardio (live):") and "purpose:" in ln for ln in s["rationale"]), (name, s["role"])
            assert "easy cardio" not in (s["lifts"][0]["hevy_note"] if s["lifts"] else "") or s["cardio"].get("key"), (name, s["role"])
    gap = {(lp, "aerobic"): lambda inputs: {"volume_covered": False, "walking_min_per_wk": 0, "line": "x"}}
    nopurpose = gap | {(lr, "purposeful_cardio"): lambda kind, live, hard: (True, [])}  # control: no purpose named -> caught
    old = _week("a_large_deficit_experienced", nopurpose, settings={"session_cap_includes_cardio": False})
    assert any(
        s["cardio"].get("key") and not any("purpose:" in ln for ln in s["rationale"] if ln.startswith("cardio (live):"))
        for s in old["week"]["sessions"]
    )


# ── ruling 5: top set + one back-off; one lead lift on the heavy lower day ─────────────────────────────────────────────────
def _effort_top(note: str | None) -> float | None:
    return sw.lift_effort(note)


def test_ruling_5_the_squat_leads_and_the_deadlift_runs_a_notch_lower_every_week(weeks):
    """Fix round 11 (the tenth red team's simpler rule): the squat always leads at the session's effort; the deadlift is a top set
    + one back-off at RPE <= deadlift_rpe (8) — every week, no ISO-week alternation. Control: the rule off -> both at RPE 9."""
    a = weeks["a_large_deficit_experienced"]["week"]
    lh = {x["key"]: x for x in _lifts(a, "lower_heavy")}
    squat, dl = _effort_top(lh["squat_barbell"]["hevy_note"]), _effort_top(lh["deadlift_barbell"]["hevy_note"])
    assert squat == 9 and dl == live_settings.value("deadlift_rpe") == 8
    assert lh["deadlift_barbell"]["working_sets"] == 2  # top set + one back-off
    prof = PROFILES["a_large_deficit_experienced"]
    nxt = _week("a", profile=prof | {"days": [sw._day(d, 7) for d in prof["days"]]} | {"as_of": sw._day(prof["as_of"], 7)})
    lh2 = {x["key"]: x for x in _lifts(nxt["week"], "lower_heavy")}
    assert _effort_top(lh2["squat_barbell"]["hevy_note"]) == 9 and _effort_top(lh2["deadlift_barbell"]["hevy_note"]) == 8  # no swap
    both = _week("a_large_deficit_experienced", {(lr, "lead_lift"): lambda rx, ctx: []})["week"]  # control
    lh = {x["key"]: x for x in _lifts(both, "lower_heavy")}
    assert _effort_top(lh["squat_barbell"]["hevy_note"]) == _effort_top(lh["deadlift_barbell"]["hevy_note"]) == 9


def test_ruling_5_a_swapped_out_deadlift_is_not_a_second_maximal_lift(weeks):
    f = weeks["f_high_fatigue_poor_sleep"]["week"]  # discomfort swaps the deadlift for a hip thrust
    lines = [ln for s in f["sessions"] if s["role"] == "lower_heavy" for ln in s["live_fit"] or []]
    assert "deadlift_barbell" not in {x["key"] for x in _lifts(f, "lower_heavy")}
    assert not any(ln.startswith("heavy lower (live)") for ln in lines)


# ── ruling 6: overhead press 3 sets, from the lateral raises ────────────────────────────────────────────────────────────────
def test_ruling_6_the_press_takes_three_sets_from_the_lateral_raises(weeks):
    sa = {x["key"]: x for x in _lifts(weeks["a_large_deficit_experienced"]["week"], "shoulders_arms")}
    press = next(x for k, x in sa.items() if "press" in k)
    assert press["working_sets"] == 3 and press["reps"] == "6-10"
    cat = sw.build_world(PROFILES["a_large_deficit_experienced"])["catalog"]["movements"]
    plan = live_volume.week_plan(cat, LIB0, 5)
    assert any("from the lateral raises" in ln for ln in plan["lines"])  # the ruling: the laterals pay first
    alt = live_volume.press_trade_alternative(cat, LIB0)  # the owner's alternative (the rear-delt surplus pays), reported
    assert all(v["side_delts"] >= live_settings.value("delt_heads")["side_delts"] and v["shoulders"] <= 16 for v in alt.values())
    one = _week("a_large_deficit_experienced", settings={"press_sets": 1})["week"]  # control: the charter's one set
    assert next(x for x in _lifts(one, "shoulders_arms") if "press" in x["key"])["working_sets"] == 1


# ── ruling 7 (and #2/#6 of fix round 8): no KB hinge slot; the swing never fills a hinge slot ─────────────────────────────────
def test_ruling_7_no_kb_hinge_slot_and_no_make_up(weeks):
    for name, w in weeks.items():
        keys = {x["key"] for x in _lifts(w["week"])}
        assert not keys & {"kettlebell_deadlift", "kettlebell_swing"}, name
    cat = weeks["a_large_deficit_experienced"]["world"]["catalog"]["movements"]
    assert not any(r["slot"] == "kettlebell_swing" for r in live_volume.week_plan(cat, LIB0, 5)["rows"])
    with patch.object(live_volume, "_kb_slot", lambda e: False):  # control: the slot kept in the plan
        assert any(r["slot"] == "kettlebell_swing" for r in live_volume.week_plan(cat, LIB0, 5)["rows"])


# ── ruling #8 (fix round 8): ~4 direct ab sets, spread ─────────────────────────────────────────────────────────────────────
def test_ruling_8_four_direct_ab_sets_spread_over_the_week(weeks):
    a = weeks["a_large_deficit_experienced"]
    assert a["m"]["hard_sets"].get("abs", 0) >= 4
    days = [
        s["role"]
        for s in a["week"]["sessions"]
        if any(live_volume.landmark_muscle(x["key"], a["world"]["catalog"]["movements"], a["world"]["lib"]) == "abs" for x in s["lifts"])
    ]
    assert len(days) >= 2, days  # spread, not one slot of four
    none = _week("a_large_deficit_experienced", settings={"abs_direct_sets_per_week": 0})  # control: the ruling's dose off
    assert none["m"]["hard_sets"].get("abs", 0) < 4


# ── ruling 9 (+ #9 of fix round 8): priority muscles at MEV+, delt heads assessed apart ─────────────────────────────────────
def test_ruling_9_priority_muscles_at_or_over_mev_and_each_delt_head_has_its_aim(weeks):
    a = weeks["a_large_deficit_experienced"]
    assert live_settings.settings(LIB0)["priority_muscles"] == ["chest", "quadriceps"]
    for mu in ("chest", "quadriceps"):
        assert a["m"]["hard_sets"].get(mu, 0) >= LANDMARKS["muscles"][mu]["MEV"], mu
    heads = a["m"]["delt_heads"]
    assert heads["side_delts"] >= live_settings.value("delt_heads")["side_delts"] and heads["rear_delts"] >= 4, heads
    assert "shoulders" not in live_settings.settings(LIB0)["priority_muscles"]
    # fix round 10 (the ninth red team: chest 9 under biceps 11, and naming back + glutes changed nothing): the plan holds each
    # priority muscle at or over the arms and calves, and the setting moves the week
    cat, lib = a["world"]["catalog"]["movements"], a["world"]["lib"]
    for n in (5, 4):  # the plan, within its one-set tolerance (the served weeks: tests/test_fix10_5861.py)
        c = live_volume.week_plan(cat, lib, n)["counts"]
        tol = live_volume.PARITY_TOLERANCE + (1.0 if n == 4 else 0.0)  # 4 mornings: ruling 3 holds the arms a set over MEV
        assert all(c.get(p, 0) + tol >= c.get(r, 0) for p in ("chest", "quadriceps") for r in live_volume.PARITY_RIVALS), (n, c)
    other = lib | {"programming_settings": {**(lib.get("programming_settings") or {}), "priority_muscles": ["back", "glutes"]}}
    assert live_volume.week_plan(cat, other, 5)["counts"] != live_volume.week_plan(cat, lib, 5)["counts"]
    with patch.object(live_volume, "_priority_parity", lambda *a: []):  # control: no parity -> a rival over a priority muscle
        c = live_volume.week_plan(cat, lib, 5)["counts"]
    assert any(c.get(r, 0) > c.get(p, 0) for p in ("chest", "quadriceps") for r in live_volume.PARITY_RIVALS), c


# ── ruling #10 (fix round 8): a familiar swap works at target; the first session back after 10+ days is conservative ───────
def _later(name: str, weeks_later: int) -> dict:
    """The profile's week drafted `weeks_later` weeks on, over the SAME record (no session logged in between: a layoff)."""
    prof = PROFILES[name]
    world = sw.build_world(prof, "approved")
    later = prof | {"days": [sw._day(d, 7 * weeks_later) for d in prof["days"]], "as_of": sw._day(prof["as_of"], 7 * weeks_later)}
    world["profile"] = world["profile"] | {"days": later["days"], "as_of": later["as_of"]}
    return sw.generate_week(later, "approved", world)


def test_ruling_10_familiar_patterns_have_no_reentry_cap_and_the_first_session_back_runs_rpe_8(weeks):
    a = weeks["a_large_deficit_experienced"]["week"]
    notes = [x["hevy_note"] or "" for x in _lifts(a)]
    assert not any("session back after" in n or "first time in" in n for n in notes)  # he trains these patterns weekly
    back = _later("a_large_deficit_experienced", 2)  # 14+ days with no session
    seen: set = set()  # each lift's FIRST exposure after the gap (later ones are its second session back)
    first = [x for x in _lifts(back) if x["key"] in ("barbell_bench_press", "machine_row", "squat_barbell", "deadlift_barbell")]
    first = [x for x in first if not (x["key"] in seen or seen.add(x["key"]))]
    assert first and all((_effort_top(x["hevy_note"]) or 0) <= 8 for x in first), [(x["key"], _effort_top(x["hevy_note"])) for x in first]
    assert not any("Heavier" in (x["hevy_note"] or "") for x in first)  # no automatic increase on the first session back
    with patch.dict(live_settings.HEURISTICS["layoff_days"], {"value": 99}):  # control: the layoff rule off -> full effort
        full = _later("a_large_deficit_experienced", 2)
    assert any((_effort_top(x["hevy_note"]) or 0) > 8 for x in _lifts(full) if x["key"] in ("barbell_bench_press", "machine_row"))


def test_ruling_10_no_symptom_warning_on_any_session(weeks):
    words = ("Stop, log it", "dizzy", "heart racing", "medical help")
    for name, w in weeks.items():
        notes = [x["hevy_note"] or "" for x in _lifts(w["week"])] + [s["cardio"].get("note") or "" for s in w["week"]["sessions"]]
        assert not any(t in n for n in notes for t in words), name
    assert "symptom_line" not in live_settings.SETTINGS and not hasattr(__import__("training.live_safety").live_safety, "SYMPTOM_PRESETS")


# ── ruling 11: the advisory loss-rate ceiling ───────────────────────────────────────────────────────────────────────────────
def _line(days: int, start: float, per_day: float, jump: float = 0.0) -> dict:
    w = {f"2026-10-{d:02d}": round(start - per_day * (d - 1), 2) for d in range(1, days + 1)}
    if jump:
        last = sorted(w)[-3:]
        for k in last:
            w[k] = round(w[k] - jump, 2)
    return w


def test_ruling_11_the_ceiling_tapers_with_weight_and_one_fast_week_is_not_muscle_loss():
    hi, lo = rate_policy.advisory_ceiling(_line(31, 300, 0.3)), rate_policy.advisory_ceiling(_line(31, 200, 0.2))
    assert hi["ceiling_lb_per_wk"] > lo["ceiling_lb_per_wk"] and hi["ceiling_pct_bw"] == lo["ceiling_pct_bw"] == 1.0  # tapers
    fast = rate_policy.advisory_ceiling(_line(31, 300, 0.3, jump=4), strength_regressing=True)
    assert fast["weeks_over"] == 1 and not fast["muscle_loss_risk"] and "one fast week" in fast["verdict"]
    sustained = rate_policy.advisory_ceiling(_line(31, 300, 0.55), strength_regressing=True)
    assert sustained["muscle_loss_risk"]  # over the reference 3+ of 4 weeks AND strength sliding
    held = rate_policy.advisory_ceiling(_line(31, 300, 0.55), strength_regressing=False)
    assert not held["muscle_loss_risk"] and "watch" in held["verdict"]  # sustained, strength holding: a watch
    slow = rate_policy.advisory_ceiling(_line(31, 300, 0.3), fatigue_level="high", recovery_low=True)
    assert slow["ceiling_pct_bw"] == 1.0 - 2 * rate_policy.SIGNAL_STEP_PCT and slow["applied"] is False  # modulated, advisory
    with patch.object(rate_policy, "SUSTAINED_WEEKS", 1):  # control: the guard removed -> one fast week reads as risk
        assert rate_policy.advisory_ceiling(_line(31, 300, 0.3, jump=4), strength_regressing=True)["muscle_loss_risk"]


def test_ruling_11_the_draft_reports_the_ceiling_once_a_week_and_nothing_applies_it(weeks):
    a = weeks["a_large_deficit_experienced"]["week"]
    lines = {s["role"]: [ln for ln in s["rationale"] if ln.startswith("loss rate (advisory")] for s in a["sessions"]}
    assert lines["upper_heavy"] and all(not v for r, v in lines.items() if r != "upper_heavy")
    assert "not applied" in lines["upper_heavy"][0]
    src = (REPO / "lambdas/health/calorie_target.py").read_text()
    assert "advisory_ceiling" not in src and "rate_policy" not in src  # the live kcal path never reads it


# ── ruling 12: aerobic credit from recorded sessions with intensity; steps reported ────────────────────────────────────────
def _apple(wid: str, start: str, minutes: int, mets: float | None = None, cadence: float | None = None, name: str = "Outdoor Walk"):
    w = {"id": wid, "name": name, "start": start, "duration": minutes * 60}
    if mets is not None:
        w["intensity"] = {"qty": mets, "units": "kcal/hr·kg"}
    if cadence is not None:
        w["stepCadence"] = {"qty": cadence, "units": "spm"}
    return {"apple_workouts": {wid: w}}


def _strava(sid: str, start: str, minutes: int, speed: float | None = None):
    a = {
        "strava_id": sid,
        "sport_type": "Walk",
        "start_date": start,
        "moving_time_seconds": minutes * 60,
        "elapsed_time_seconds": minutes * 60,
    }
    return {"activities": [a | ({"average_speed_ms": speed} if speed is not None else {})]}


def test_ruling_12_recorded_minutes_with_intensity_count_once_and_steps_never_count():
    apple = [
        _apple("A1", "2026-11-10T15:00:00+00:00", 40, mets=3.6),  # moderate by METs
        _apple("A2", "2026-11-11T15:00:00+00:00", 30, cadence=108),  # moderate by cadence (population heuristic)
        _apple("A3", "2026-11-12T15:00:00+00:00", 25, mets=2.2),  # light
    ]
    strava = [
        _strava("S1", "2026-11-10T15:01:00+00:00", 39),  # A1's copy: one identity
        _strava("S2", "2026-11-13T15:00:00+00:00", 45),  # no speed, no Apple copy: intensity unknown
        _strava("S3", "2026-11-14T15:00:00+00:00", 30, speed=1.40),  # a brisk walk by its speed (walking equation, a floor)
        _strava("S4", "2026-11-15T15:00:00+00:00", 20, speed=2.70),  # outside the walking equation's range: unknown
    ]
    out = cm.recorded_aerobic(apple=apple, strava=strava, hevy=[])
    # A1 + its Strava copy S1 are ONE identity, timed by Strava's moving time (39, the resolver's precedence): 39 + 30 credited
    assert out["credited_min"] == 99 and out["light_min"] == 25 and out["unknown_min"] == 65  # S2, S4: reported, not credited
    assert out["hr_used"] is False and "intensity unknown" in out["line"]
    hevy = [{"workout_id": "H1", "start_time": "2026-11-10T14:55:00+00:00", "end_time": "2026-11-10T15:45:00+00:00",
             "exercises": [{"name": "Treadmill", "sets": [{"duration_sec": 2400, "rpe": 6}]}]}]  # fmt: skip
    gym = cm.recorded_aerobic(apple=apple, strava=strava, hevy=hevy)
    assert gym["credited_min"] == 60  # A1/S1 sit inside the gym block: the gym's, never counted twice
    dose = cm._walking_dose({d: 15000 for d in ("2026-11-10", "2026-11-11")})
    assert dose["moderate_min_per_wk"] == 0 and dose["steps_per_day"] == 15000  # steps reported, not credited
    with patch.object(cm, "MODERATE_METS", 10.0), patch.object(cm, "CADENCE_MODERATE_SPM", 200):  # control: the thresholds bite
        assert cm.recorded_aerobic(apple=apple, strava=strava, hevy=[])["credited_min"] == 0


def test_ruling_12_the_cron_reads_the_record_only_when_live(monkeypatch):
    sys.path.insert(0, str(REPO / "lambdas" / "operational"))
    import hevy_routine_cron_lambda as cron

    monkeypatch.setattr(se, "load_library_failsoft", lambda: LIB0)
    assert cron._live_inputs("2026-11-16", read=lambda *a: pytest.fail("no read while proposed")) == {}
    live = copy.deepcopy(LIB0) | {"status": "approved", "approved_on": "2026-01-02"}
    monkeypatch.setattr(se, "load_library_failsoft", lambda: live)
    rows = {
        "apple_health": [_apple("A1", "2026-11-10T15:00:00+00:00", 40, mets=3.6)],
        "strava": [],
        "withings": [{"date": "2026-11-10", "weight_lbs": 250}],
    }
    out = cron._live_inputs("2026-11-16", read=lambda source, start, end: rows.get(source, []))
    assert out["aerobic_record"]["credited_min"] == 40 and out["weights_by_day"] == {"2026-11-10": 250.0}


# ── ruling 13: unconfirmed equipment is never served ────────────────────────────────────────────────────────────────────────
def _unknown_served(w: dict) -> list[str]:
    lib, cat = w["world"]["lib"], w["world"]["catalog"]["movements"]
    out = []
    for s in w["week"]["sessions"]:
        for x in s["lifts"]:
            e = sw._lib_entry(lib, cat, x["key"])
            if not e or se.availability(e, lib, None):
                out.append(f"{s['role']}: {x['key']}")
        ck = s["cardio"].get("key")
        if ck and se.availability((lib["movements"].get(ck) or sw._lib_entry(lib, cat, ck)), lib, None):
            out.append(f"{s['role']}: cardio {ck}")
    return out


def test_ruling_13_unknown_availability_is_never_served(weeks):
    items = LIB0["gym_inventory"]["items"]
    ruled = (
        "hip_abduction_machine",
        "hip_adduction_machine",
        "stair_climber",
        "belt_squat_machine",
        "pendulum_squat_machine",
        "incline_press_machine",
    )
    assert all(items[i]["home_gym"]["state"] == "unknown" for i in ruled)
    for k, e in LIB0["movements"].items():
        if set(e.get("equipment") or []) & set(ruled):
            assert se.availability(e, LIB0, None), k  # unknown equipment reads unavailable
    for name, w in weeks.items():
        assert _unknown_served(w) == [], name
    for cap in (False,):
        assert _unknown_served(_week("c_equipment_limited", settings={"session_cap_includes_cardio": cap})) == []
    bad = copy.deepcopy(weeks["a_large_deficit_experienced"])  # control: an unknown-equipment movement planted -> caught
    bad["week"]["sessions"][0]["lifts"].append({"key": "hip_adduction_machine", "working_sets": 2})
    bad["world"] = {**bad["world"], "lib": LIB0}
    assert _unknown_served(bad)


# ── ruling 16: evidence and completeness visible; provisional never proves suitability ─────────────────────────────────────
def test_ruling_16_every_served_movement_shows_tier_evidence_and_completeness(weeks):
    for name, w in weeks.items():
        for s in w["week"]["sessions"]:
            ev = [ln for ln in s["rationale"] if ln.startswith("evidence (live): ")]
            assert len(ev) == 1, (name, s["role"])
            assert all(re.search(r"(none_reviewed|consensus|rct_\w+), data \d+/\d+", part) for part in ev[0].split("; ")), ev
    e = copy.deepcopy(LIB0["movements"]["squat_barbell"])
    assert qr.objective_ratings(e)["strength"]["tier"] == "S"
    e["objective_inputs"]["reviewed"] = False  # control: the same row, provisional -> never S
    assert qr.objective_ratings(e)["strength"]["tier"] == "A"
    c = {"tier": "A", "discomfort": False, "n1": {"score": 0}, "fatigue_cost": 0, "novel": False, "exposures": 0, "movement_id": "x"}
    inside = selection_live.rank_key(c | {"provisional": False}, set(), {}, ("S", "A"))
    outside = selection_live.rank_key(c | {"provisional": True}, set(), {}, ("S", "A"))
    assert inside[0] == 0 and outside[0] == 1  # a provisional A is not inside the suitable pool


# ── ruling 17: the glute S standard ─────────────────────────────────────────────────────────────────────────────────────────
def test_ruling_17_glute_tiers_follow_the_same_standard_as_every_muscle():
    """#5861 FIX7 (rubric 3.5.0; the sixth red team on ruling 17): "the same evidence + personal-fit standard as other muscles" —
    glute length is scored like every muscle's (lengthened 5 / mid 3 / short 1), so no shortened glute lift earns a stretch credit
    and no glute S is manufactured; the barbell hip thrust reaches A through its direct trial's equivalence with the back squat
    (the rubric's +1 for a higher-tier comparator), and its untested machine form ties it, never above."""
    mv = LIB0["movements"]
    tiers = {k: next((r["tier"] for r in e.get("hypertrophy") or [] if r["target"] == "glutes"), None) for k, e in mv.items()}
    assert sorted(k for k, t in tiers.items() if t == "S") == []
    row = mv["hip_thrust_barbell"]["hypertrophy"][0]
    assert qr.capped_tier(mv["hip_thrust_barbell"], row) == "B" and row["evidence_adjustment"]["comparator"] == "squat_barbell"
    assert tiers["hip_thrust_barbell"] == "A" == tiers["hip_thrust_machine"] and tiers["cable_kickback"] == "B"
    with patch.dict(qr.STRETCH_CAPS, {"glutes": ("lengthened", "x", "the 3.4.0 override")}):  # control: the override -> S again
        assert qr.quality_tier(mv["hip_thrust_barbell"], row) == "S"


# ── ruling 18: every heuristic labelled, with its block-retro metric ────────────────────────────────────────────────────────
def _resolve(key: str):
    mod, *path = key.split(".")
    obj = sys.modules.get(f"training.{mod}") or sys.modules.get(f"health.{mod}")
    if obj is None:
        __import__(f"training.{mod}" if mod != "rate_policy" else "health.rate_policy")
        obj = sys.modules.get(f"training.{mod}") or sys.modules[f"health.{mod}"]
    for p in path:
        obj = obj[p] if isinstance(obj, dict) else getattr(obj, p)
    return obj, mod, path


def _labelled(obj, mod: str, name: str) -> bool:
    if isinstance(obj, dict) and (
        obj.get("label") == "heuristic" or (obj and all(isinstance(v, dict) and v.get("label") == "heuristic" for v in obj.values()))
    ):
        return True
    if isinstance(obj, dict) and all(isinstance(v, dict) for v in obj.values()) and obj:
        return False  # a table of rows: every row carries its own label
    src = (REPO / "lambdas" / ("health" if mod == "rate_policy" else "training") / f"{mod}.py").read_text()
    marker = next((m for m in (f"\n{name} = ", f"\n{name}: ") if m in src), None)
    if marker is None:
        return False
    before, after = src.split(marker, 1)
    return any(w in (before[-400:] + after[:600]) for w in ("HEURISTIC", "heuristic"))


def test_ruling_18_every_heuristic_names_its_block_retro_metric_and_is_documented():
    doc = (REPO / "docs/coaching/ENGINE_ARCHITECTURE.md").read_text()
    assert "## Block-retro hooks" in doc
    for key, metric in lr.HEURISTIC_HOOKS.items():
        obj, mod, path = _resolve(key)
        assert _labelled(obj, mod, path[-1]), key
        assert metric and f"`{key}`" in doc, key
    assert not _labelled({"value": 1}, "live_rulings", "X")  # control: an unlabelled table is caught
