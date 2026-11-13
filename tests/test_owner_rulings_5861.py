"""#5861 FIX6 — THE OWNER'S RULINGS OF 2026-11-13 on the decision register, as LIVE-only behaviour (the library stays
`proposed`; tests/test_no_live_change_5861_l6.py holds the proposed drafts byte-identical and poisons every entry point here).

One section per ruling: the ruled default, the outcome on the drafted week, and a must-fail control in the same test (mutate the
rule or flip the setting -> the assertion goes red). Synthetic profiles only (tests/fixtures/sample_week_profiles_5861.json).
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

import build_exercise_library as builder  # noqa: E402
import sample_weeks_5861 as sw  # noqa: E402
from health import rate_policy  # noqa: E402
from training import (  # noqa: E402
    cardio_model as cm,
    live_balance as lb,
    live_program as lp,
    live_rules as lrules,
    live_rulings as lr,
    live_week as lw,
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


# ── the settings: ruled, library-carried, one value in code and data ────────────────────────────────────────────────────────
def test_every_ruled_setting_is_library_carried_and_equal_to_its_code_default():
    have = LIB0["programming_settings"]
    code = lp.settings({})  # every code default, no library
    off = {k: (have.get(k), code.get(k), v) for k, v in builder.OWNER_RULED_SETTINGS.items() if not (have.get(k) == code.get(k) == v)}
    assert off == {}
    assert LIB0["status"] == "proposed"  # configuration, never activation
    bad = copy.deepcopy(LIB0)  # control: a stale on-disk value is overwritten by the ruling on the next build
    bad["programming_settings"]["session_cap_includes_cardio"] = False
    assert (builder.PROGRAMMING_SETTINGS_DEFAULTS | bad["programming_settings"] | builder.OWNER_RULED_SETTINGS)[
        "session_cap_includes_cardio"
    ] is True
    assert {k: v for k, v in (builder.PROGRAMMING_SETTINGS_DEFAULTS | bad["programming_settings"]).items()}[
        "session_cap_includes_cardio"
    ] is False  # without the ruling dict the stale value would stand


# ── ruling 1: the shared cap; strength work a muscle needs is never cut for cardio ──────────────────────────────────────────
def _room_cuts(week: dict) -> list[str]:
    return [
        ln for s in week["sessions"] for ln in s["rationale"] if ln.startswith("cardio room (live)") and ("dropped" in ln or "off (" in ln)
    ]


def test_ruling_1_the_whole_morning_fits_and_no_needed_set_is_cut_for_cardio(weeks):
    for name, w in weeks.items():
        assert all(p["morning_minutes"] <= 75.05 for p in w["m"]["per_session"]), name
        cuts = [ln for ln in _room_cuts(w["week"]) if "over MAV" not in ln or "dropped" in ln]
        assert cuts == [], name
    # control: the fifth round's room-making cuts sets (#5861 FIX8: on a LOW-steps week — a high-steps week of unknown
    # intensity has no aerobic gap to make room for, ruling 12; and the arms floor's kept slots unprotected, `arms_keep`)
    old = _week(
        "e_short_week",
        {(lr, "arms_keep"): lambda rx, ctx, workouts: []},
        settings={"cardio_room_takes": "as_fix5"},
        profile=PROFILES["e_short_week"] | {"steps_per_day": 4000},
    )
    assert _room_cuts(old["week"])


# ── ruling 2: the 4-session week after missed sessions ───────────────────────────────────────────────────────────────────────
def test_ruling_2_a_dip_is_answered_by_a_four_session_week_without_make_up_sets(weeks):
    d = weeks["d_stalled_anchor_adherence_dip"]["week"]
    assert lp.settings(LIB0)["adherence_response"] == "short_week"
    assert len(d["sessions"]) == 4 and "shoulders_arms" not in {s["role"] for s in d["sessions"]}
    total = sum(x["working_sets"] for x in _lifts(d))
    full = sum(x["working_sets"] for x in _lifts(weeks["a_large_deficit_experienced"]["week"]))
    assert total < full  # no make-up: the missed sets are not re-served
    trim = _week("d_stalled_anchor_adherence_dip", settings={"adherence_response": "trim_sets"})["week"]  # control
    assert len(trim["sessions"]) == 5


# ── ruling 3: the 4-day week holds shoulders and arms at MEV, counted ───────────────────────────────────────────────────────
def _arms_under_mev(m: dict) -> list[str]:
    return [mu for mu in lr.ARMS_FLOOR["muscles"]["value"] if m["landmarks"][mu]["sets"] < m["landmarks"][mu]["MEV"]]


def test_ruling_3_the_four_day_week_keeps_shoulders_and_arms_at_mev(weeks):
    e = weeks["e_short_week"]
    assert "shoulders_arms" not in {s["role"] for s in e["week"]["sessions"]} and len(e["week"]["sessions"]) == 4
    assert _arms_under_mev(e["m"]) == []
    plan = lb.allocation_plan(e["world"]["catalog"]["movements"], e["world"]["lib"], ("shoulders_arms",))
    assert any("ARMS_FLOOR" in ln for ln in plan["lines"])  # the counted check acted (triceps 7 -> 8 on the synthetic week)
    from training import live_stimulus

    off = _week(  # control: neither the plan floor, the record top-up nor the FIX7 week floor -> an arm under MEV
        "e_short_week",
        {
            (lr, "short_week_floor"): lambda env, adds: [],
            (lr, "arms_top_up"): lambda rx, ctx, workouts: [],
            (live_stimulus, "week_floor"): lambda rx, ctx, workouts, cap: [],
        },
    )
    assert _arms_under_mev(off["m"])


# ── ruling 4: purposeful cardio only ─────────────────────────────────────────────────────────────────────────────────────────
def test_ruling_4_no_cardio_block_without_a_named_purpose(weeks):
    # #5861 FIX7: every served block names its purpose — the conditioning dose, or the RECORD's aerobic gap (an easy block where
    # the recorded, credited minutes leave the week short); none fills a slot
    for name, w in weeks.items():
        for s in w["week"]["sessions"]:
            if s["cardio"].get("key"):
                assert any(ln.startswith("cardio (live):") and "purpose:" in ln for ln in s["rationale"]), (name, s["role"])
    covered = {(lp, "aerobic"): lambda inputs: {"volume_covered": False, "walking_min_per_wk": 150, "line": "x"}}  # the record covers it
    full = _week("a", covered, profile=PROFILES["a_large_deficit_experienced"])
    kinds = [s["cardio"].get("kind") for s in full["week"]["sessions"] if s["cardio"].get("key")]
    assert all(k in lp.HARD_KINDS for k in kinds), kinds  # a covered week: the conditioning dose only
    walker = PROFILES["a_large_deficit_experienced"] | {"steps_per_day": 6000}
    old = _week("a", settings={"cardio_purpose_only": False, "session_cap_includes_cardio": False}, profile=walker)  # control
    assert any(s["cardio"].get("kind") and s["cardio"]["kind"] not in lp.HARD_KINDS for s in old["week"]["sessions"])


# ── ruling 5: top set + one back-off; one lead lift on the heavy lower day ─────────────────────────────────────────────────
def _effort_top(note: str | None) -> float | None:
    return sw.lift_effort(note)


def test_ruling_5_squat_and_deadlift_are_never_both_maximal_and_the_lead_alternates(weeks):
    assert lr.lead_of("2026-11-16") == "hinge" and lr.lead_of("2026-11-23") == "squat"  # ISO weeks 47 / 48
    a = weeks["a_large_deficit_experienced"]["week"]
    lh = {x["key"]: x for x in _lifts(a, "lower_heavy")}
    squat, dl = _effort_top(lh["squat_barbell"]["hevy_note"]), _effort_top(lh["deadlift_barbell"]["hevy_note"])
    assert dl == 9 and squat == lr.LEAD_LIFT["second_band"]["value"][1]  # the deadlift leads this (odd) week
    assert lh["deadlift_barbell"]["working_sets"] == 2  # top set + one back-off (heavy_day_deadlift_shape)
    nxt = _week(
        "a",
        profile=PROFILES["a_large_deficit_experienced"]  # the record moves with the week (#5861 FIX8: else a 10-day gap is a
        | {"days": [sw._day(d, 7) for d in PROFILES["a_large_deficit_experienced"]["days"]]}  # return week, every lift at 7-8)
        | {"as_of": sw._day(PROFILES["a_large_deficit_experienced"]["as_of"], 7)},
    )
    lh2 = {x["key"]: x for x in _lifts(nxt["week"], "lower_heavy")}
    assert _effort_top(lh2["squat_barbell"]["hevy_note"]) == 9 and _effort_top(lh2["deadlift_barbell"]["hevy_note"]) == 8  # alternates
    both = _week("a_large_deficit_experienced", settings={"lead_lift_rule": "off"})["week"]  # control: both at the top
    lh = {x["key"]: x for x in _lifts(both, "lower_heavy")}
    assert _effort_top(lh["squat_barbell"]["hevy_note"]) == _effort_top(lh["deadlift_barbell"]["hevy_note"]) == 9
    with patch.dict(lr.LEAD_LIFT, {"second_band": {"value": [8, 9], "label": "heuristic", "basis": "mutation"}}):  # consequence
        lh = {x["key"]: x for x in _lifts(_week("a_large_deficit_experienced")["week"], "lower_heavy")}
        assert _effort_top(lh["squat_barbell"]["hevy_note"]) == 9


def test_ruling_5_a_swapped_out_deadlift_is_not_a_second_maximal_lift(weeks):
    f = weeks["f_high_fatigue_poor_sleep"]["week"]  # discomfort swaps the deadlift for a hip thrust
    lines = [ln for s in f["sessions"] if s["role"] == "lower_heavy" for ln in s["rationale"]]
    assert "deadlift_barbell" not in {x["key"] for x in _lifts(f, "lower_heavy")}
    assert not any(ln.startswith("lead lift (live)") for ln in lines)


# ── ruling 6: overhead press 3 sets, from the lateral raises, recoverable ──────────────────────────────────────────────────
def test_ruling_6_the_press_takes_three_sets_and_drops_on_a_strained_week(weeks):
    sa = {x["key"]: x for x in _lifts(weeks["a_large_deficit_experienced"]["week"], "shoulders_arms")}
    press = next(x for k, x in sa.items() if "press" in k)
    assert press["working_sets"] == 3 and press["reps"] == "6-10"  # double progression in 6-10 (the load step on the note)
    assert "Top reps at RPE 7 or less" in press["hevy_note"]
    f = {x["key"]: x for x in _lifts(weeks["f_high_fatigue_poor_sleep"]["week"], "shoulders_arms")}
    assert next(x for k, x in f.items() if "press" in k)["working_sets"] <= 2  # a deload week takes a set off: recoverable
    with patch.object(lr, "press_trade", lambda rows, lib: {}):  # control: no trade -> the rear delts give the sets instead
        plan = lb.allocation_plan(sw.build_world(PROFILES["a_large_deficit_experienced"])["catalog"]["movements"], lp_lib())
    keep = lb.allocation_plan(sw.build_world(PROFILES["a_large_deficit_experienced"])["catalog"]["movements"], lp_lib())
    rear = lambda p: sum(d for (r, s), d in p["deltas"].items() if s in ("face_pull", "reverse_pec_deck"))  # noqa: E731
    assert rear(keep) > rear(plan)  # with the trade the rear delts give fewer sets: the laterals paid for the press


def lp_lib() -> dict:
    lib = copy.deepcopy(LIB0)
    lib["status"] = "approved"
    return lib


# ── ruling 7: no KB hinge on a strained week, no make-up ─────────────────────────────────────────────────────────────────────
NODL = {(lrules, "deadlifts"): lambda workouts, ctx: False}


def test_ruling_7_the_kb_hinge_drops_under_strain_with_no_make_up():
    home = NODL | {(lb, "_template_spine"): lambda role, catalog, lib: 0, (lp, "avoid_stacking"): lambda rx, ctx, rot, pinned: []}
    drop = _week("f_high_fatigue_poor_sleep", home)
    kept = _week("f_high_fatigue_poor_sleep", home, {"kb_slot_under_strain": "as_today"})  # control: the slot stays
    assert "kettlebell_deadlift" not in {x["key"] for x in _lifts(drop["week"])}
    kb = next(x for x in _lifts(kept["week"]) if x["key"] == "kettlebell_deadlift")
    total = lambda w: sum(x["working_sets"] for x in _lifts(w))  # noqa: E731
    assert total(drop["week"]) == total(kept["week"]) - kb["working_sets"]  # exactly the slot's sets gone: no make-up
    assert drop["m"]["sets_by_muscle"].get("glutes", 0) <= kept["m"]["sets_by_muscle"].get("glutes", 0)


# ── ruling 9: priority by stimulus and performance ──────────────────────────────────────────────────────────────────────────
def test_ruling_9_a_progressing_priority_muscle_at_mev_takes_no_extra_volume(weeks):
    a = weeks["a_large_deficit_experienced"]
    assert lp.settings(LIB0)["priority_muscles"] == ["chest", "quadriceps"]
    assert "leg_extension_machine" not in {x["key"] for x in _lifts(a["week"])}
    for mu in ("chest", "quadriceps"):
        assert a["m"]["landmarks"][mu]["sets"] >= a["m"]["landmarks"][mu]["MEV"], mu  # held AT MEV+, never under
    held = lambda w, mu: any(ln.startswith(f"priority (live): {mu} held") for s in w["sessions"] for ln in s["rationale"])  # noqa: E731
    assert held(a["week"], "chest") and not held(a["week"], "quadriceps")  # ISO week 47: the squat is the SECOND lift (RPE 7-8)
    prof = PROFILES["a_large_deficit_experienced"]
    nxt = _week("a", profile=prof | {"as_of": sw._day(prof["as_of"], 7), "days": [sw._day(d, 7) for d in prof["days"]]})["week"]
    assert held(nxt, "quadriceps")  # week 48: the squat leads, progressing at MEV -> held
    f = weeks["f_high_fatigue_poor_sleep"]  # regressing: the stimulus is not working -> the allocation stands
    assert not any(ln.startswith("priority (live)") and "held" in ln for s in f["week"]["sessions"] for ln in s["rationale"])
    with patch.dict(lr.PRIORITY_ADD, {"progressing": {"value": "never", "label": "heuristic", "basis": "mutation"}}):  # control
        more = _week("a_large_deficit_experienced")
    assert more["m"]["landmarks"]["chest"]["sets"] > a["m"]["landmarks"]["chest"]["sets"]


# ── ruling 10: no symptom warning line ──────────────────────────────────────────────────────────────────────────────────────
def test_ruling_10_no_symptom_warning_on_any_session(weeks):
    words = ("Stop, log it", "dizzy", "heart racing", "medical help")
    for name, w in weeks.items():
        notes = [x["hevy_note"] or "" for x in _lifts(w["week"])] + [s["cardio"].get("note") or "" for s in w["week"]["sessions"]]
        assert not any(t in n for n in notes for t in words), name
    on = _week("a_large_deficit_experienced", settings={"symptom_line": "extended"})["week"]  # control: the preset, set
    assert any("heart racing" in (s["cardio"].get("note") or "") for s in on["sessions"])


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
    live = copy.deepcopy(LIB0) | {"status": "approved"}
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


def test_ruling_18_fix6_heuristics_have_consequences():
    """Each FIX6 heuristic changes an outcome when mutated (its consequence test; the others' live in their rounds' files)."""
    assert lr.LEAD_LIFT and lr.ARMS_FLOOR and lr.PRIORITY_ADD  # exercised above: second_band, the floor off, progressing
    env = {"rows": [{"role": "upper_heavy", "slot": "tri", "kind": "accessory", "intensity": None, "key": "t", "sets": 1, "muscle": "triceps", "secondary": []}],
           "deltas": {}, "marks": {"triceps": {"MEV": 8}}}  # fmt: skip
    lr.short_week_floor(env, [])
    assert env["deltas"] == {("upper_heavy", "tri"): 2}  # 1 + 2 = 3, the slot maximum (#5861 FIX7, live_balance.SLOT_MAX)
    env["deltas"] = {}
    with patch.dict(lr.ARMS_FLOOR, {"add_per_slot": {"value": 1, "label": "heuristic", "basis": "mutation"}}):
        lr.short_week_floor(env, [])
    assert env["deltas"] == {("upper_heavy", "tri"): 1}


# ── Hevy templates: the KB deadlift id is ready, read as logged ────────────────────────────────────────────────────────────
def test_ruling_8_a_custom_kb_template_id_reads_its_history_as_logged():
    from types import SimpleNamespace

    custom = "2c03345f-0000-4000-8000-000000000001"  # a custom Hevy template id is a lower-case UUID
    hidx = {custom: [{"date": "2026-11-10", "sets": [{"weight_kg": 24.0, "reps": 8, "rpe": 7}]}]}
    blk = SimpleNamespace(movement_key="kettlebell_deadlift", sets=[SimpleNamespace(type="normal", weight_kg=None)] * 2)
    lib = copy.deepcopy(LIB0) | {"status": "approved"}
    lib["programming_settings"] = {**lib["programming_settings"], "kb_deadlift_template_id": custom}
    with patch.object(se, "load_library_failsoft", lambda: lib):
        lw.kb_seed(
            [blk],
            {"exposures": [{"movement_key": "kettlebell_deadlift", "live_kb": True}]},
            hidx,
            sw.build_world(PROFILES["a_large_deficit_experienced"])["catalog"]["movements"],
            "2026-11-20",
            [],
        )
        assert lb.template_resolver(lambda k: "D20D7BBE", lib)("kettlebell_deadlift") == custom  # written under his template
    assert all(abs(float(s.weight_kg) - 24.0) < 0.1 for s in blk.sets)  # the bell read off the lower-case id
    hidx_upper = {custom.upper(): hidx[custom]}  # control: an id the history does not hold -> no bell
    blk2 = SimpleNamespace(movement_key="kettlebell_deadlift", sets=[SimpleNamespace(type="normal", weight_kg=None)] * 2)
    other = copy.deepcopy(lib)
    other["programming_settings"]["kb_deadlift_template_id"] = "ffffffff-0000-4000-8000-000000000009"
    with patch.object(se, "load_library_failsoft", lambda: other):
        lw.kb_seed([blk2], {"exposures": [{"movement_key": "kettlebell_deadlift", "live_kb": True}]}, hidx_upper, {}, "2026-11-20", [])
    assert all(s.weight_kg is None for s in blk2.sets)


def test_ruling_3_the_last_upper_session_tops_up_an_arm_the_week_actually_left_under_mev():
    """The plan count reads the templates; `arms_top_up` reads the RECORD (what the week logged since Monday) — an earlier
    morning's time trim (the owner's 4-day week dropped a curl on upper heavy) is made up on upper volume."""
    world = sw.build_world(PROFILES["e_short_week"])
    lib, cat = world["lib"], world["catalog"]["movements"]
    ctx = {"lib": lib, "catalog": cat, "idx": se.key_index(lib, cat), "target_date": "2026-11-19", "week_skip": ("shoulders_arms",)}
    rx = {
        "session_role": "upper_volume",
        "exposures": [{"kind": "accessory", "movement_key": "db_curl", "sets": [{"kind": "working", "reps": [8, 15]}] * 2}],
    }
    tid = str(cat["db_curl"]["hevy_template_id_hint"]).upper()  # #5861 FIX8: a slot tops up only when its sets can be hard —
    rec = [  # logged 3 times before this week (past any re-entry cap), so the added set counts
        {"date": d, "title": "UPPER-VOLUME", "exercises": [{"template_id": tid, "sets": [{"weight_kg": 12.0, "reps": 10, "rpe": 8.0}]}]}
        for d in ("2026-10-29", "2026-11-05", "2026-11-12")
    ]
    lines = lr.arms_top_up(rx, ctx, rec)
    assert len(rx["exposures"][0]["sets"]) == 3 and lines and "biceps" in lines[0]  # 2 today < MEV 8 -> +1: SLOT_MAX 3 (FIX7)
    normal = copy.deepcopy(rx) | {"exposures": [{"kind": "accessory", "movement_key": "db_curl", "sets": [{"kind": "working"}] * 2}]}
    assert lr.arms_top_up(normal, ctx | {"week_skip": ()}, rec) == [] and len(normal["exposures"][0]["sets"]) == 2  # control
    capped = copy.deepcopy(rx) | {"exposures": [{"kind": "accessory", "movement_key": "db_curl", "sets": [{"kind": "working"}] * 2}]}
    lr.arms_top_up(capped, ctx, [])  # FIX8 control: never logged -> its sets could not be hard -> no top-up onto it
    assert len(capped["exposures"][0]["sets"]) == 2
