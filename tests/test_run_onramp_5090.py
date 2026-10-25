"""tests/test_run_onramp_5090.py — the run gate, the lower-leg prep and Stage 4, the run/walk on-ramp (#5090).

Every expected number is read from the training charter (`charter_value`), never pinned, so an owner
re-version moves the expectation with it. No clock is read anywhere in `training.run_onramp`.
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from training import (  # noqa: E402
    cardio_menu,
    run_onramp,
    training_charter as tc,  # noqa: E402
)
from training.training_charter import charter_value  # noqa: E402


@pytest.fixture(autouse=True)
def _public_charter_only(monkeypatch):
    """The bundled public charter only: no owner twin from the laptop env, no live S3 probe."""
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    yield
    tc.reset_cache()


GATE = float(charter_value("gated_movements.running.gate_lb"))
PREP = float(charter_value("gated_movements.lower_leg_prep.from_lb"))
WEEKS = int(charter_value("gated_movements.running.walking_weeks"))
HOURS = float(charter_value("gated_movements.running.walking_hours_per_wk"))
SEQ = list(charter_value("split.sequence"))
HEAVY_LOWER = next(s for s in SEQ if s.lower().startswith("lower") and "heavy" in s.lower())
CAP = int(charter_value("gated_movements.running.onramp.max_runs_per_wk"))
EASY_TOP = charter_value("cardio_menu.blocks.easy.rpe")[1]
LEVELS = charter_value("gated_movements.running.onramp.levels")
NEED = charter_value("gated_movements.running.onramp.advance_rule.sessions_at_level")


def _weeks(n=WEEKS, hours=HOURS + 1, pain=False):
    return [{"week_start": f"2027-02-{1 + 7 * i:02d}", "hours": hours, "pain_flag": pain} for i in range(n)]


# ── the gate: closed / prep / held / open / unknown ─────────────────────────────────────
def test_the_gate_is_closed_above_the_prep_weight_with_both_distances():
    g = run_onramp.gate_state(PREP + 41.8, _weeks(), [])
    assert g["state"] == run_onramp.CLOSED
    assert g["lb_to_prep"] == 41.8 and g["lb_to_gate"] == round(PREP + 41.8 - GATE, 1)
    assert "to the lower-leg prep" in g["reason"] and g["running_unlocked"] is False


def test_prep_opens_at_the_prep_weight_and_the_onramp_waits_for_the_gate_and_the_walking_weeks():
    g = run_onramp.gate_state(PREP, _weeks(), [])
    assert g["state"] == run_onramp.PREP and f"{PREP - GATE:g} lb to go" in g["reason"]
    under = run_onramp.gate_state(GATE - 1, _weeks(WEEKS - 1), [])
    assert under["state"] == run_onramp.PREP and f"walking weeks {WEEKS - 1}/{WEEKS}" in under["reason"]


def test_the_gate_opens_at_the_gate_weight_with_the_walking_weeks_and_no_hold():
    g = run_onramp.gate_state(GATE, _weeks(), [])
    assert g["state"] == run_onramp.OPEN and g["onramp_open"] and not g["running_unlocked"]
    done = run_onramp.gate_state(GATE, _weeks(), [], stage4_done=True)
    assert done["running_unlocked"] and "continuous running is unlocked" in done["reason"]


def test_a_lower_leg_strain_flag_holds_the_gate_and_only_hold_causes_count():
    ramp = {"held_by": ["strain_flag:calf", "deload_record:2027-02-01", "no_baseline"]}
    g = run_onramp.gate_state(GATE - 5, _weeks(), ramp)
    assert g["state"] == run_onramp.HELD and g["holds"] == ["strain_flag:calf"] and g["onramp_open"]
    # a deload or a missing baseline is not a lower-leg hold
    assert run_onramp.gate_state(GATE - 5, _weeks(), {"held_by": ["deload_record:x"]})["state"] == run_onramp.OPEN


def test_an_unread_hold_or_weight_never_reads_open_or_closed():
    assert run_onramp.gate_state(GATE - 5, _weeks(), None)["state"] == run_onramp.PREP  # unread flags: never open
    assert run_onramp.gate_state(None, _weeks(), [])["state"] == run_onramp.UNKNOWN


def test_walking_weeks_count_the_newest_consecutive_met_weeks_and_an_unread_week_breaks_the_run():
    rows = _weeks(WEEKS + 1)
    rows[-2]["pain_flag"] = None  # the second-newest week's pain flags were not read
    s = run_onramp.walking_weeks_status(rows)
    assert s["met"] == 1 and s["broken_by"] == "pain_not_read" and not s["satisfied"]
    assert s["weeks_meeting_hours"] == WEEKS + 1  # the hours are still shown, the week is just not counted
    low = run_onramp.walking_weeks_status(_weeks(hours=HOURS - 0.1))
    assert low["met"] == 0 and low["broken_by"] == "below_hours"
    assert run_onramp.walking_weeks_status(_weeks(pain=True))["broken_by"] == "pain_flag"


# ── the spacing rule and the weekly cap ─────────────────────────────────────────────────
def _open_gate():
    return run_onramp.gate_state(GATE - 1, _weeks(), [])


def test_no_run_within_24_h_of_a_heavy_lower_session_against_the_sequence():
    i = SEQ.index(HEAVY_LOWER)
    before, after = SEQ[(i - 1) % len(SEQ)], SEQ[(i + 1) % len(SEQ)]
    for name in (HEAVY_LOWER, before, after):
        v = run_onramp.run_day_verdict(name, gate=_open_gate())
        assert v["eligible"] is False and ("heavy lower" in v["why"]), (name, v)
    free = [s for s in SEQ if s not in (HEAVY_LOWER, before, after)]
    assert free and all(run_onramp.run_day_verdict(s, gate=_open_gate())["eligible"] for s in free)
    # the role key is the same session as its sequence name; a generic archetype cannot be spaced
    assert run_onramp.run_day_verdict(HEAVY_LOWER.lower().replace("-", "_"), gate=_open_gate())["eligible"] is False
    assert run_onramp.run_day_verdict("lower", gate=_open_gate())["eligible"] is False


def test_max_two_runs_a_week():
    free = next(s for s in SEQ if run_onramp.run_day_verdict(s, gate=_open_gate())["eligible"])
    assert run_onramp.run_day_verdict(free, gate=_open_gate(), runs_this_week=CAP - 1)["eligible"] is True
    v = run_onramp.run_day_verdict(free, gate=_open_gate(), runs_this_week=CAP)
    assert v["eligible"] is False and f"{CAP} runs" in v["why"]


def test_no_run_when_the_gate_is_not_open_and_a_strain_flag_pauses_the_run_like_the_pogo_hops():
    """HELD pauses ALL impact: no day of the sequence carries a run/walk, the same rule that pauses the pogo hops
    (`prep_exposures`), and the week placement places none; the level is kept by `stage_progress`."""
    free = next(s for s in SEQ if run_onramp.run_day_verdict(s, gate=_open_gate())["eligible"])
    assert not run_onramp.run_day_verdict(free, gate=run_onramp.gate_state(PREP + 1, _weeks(), []))["eligible"]
    held = run_onramp.gate_state(GATE - 1, _weeks(), ["strain_flag:shin"])
    assert held["state"] == run_onramp.HELD and held["onramp_open"]
    for name in SEQ:
        v = run_onramp.run_day_verdict(name, gate=held, level=3)
        assert v["eligible"] is False and "pauses the run/walk" in v["why"]
    days = [{"date": f"2027-03-0{d + 1}", "archetype": SEQ[d]} for d in range(len(SEQ))]
    assert not any(p and p["kind"] == "run_walk" for p in cardio_menu.place_week(days, run_gate=held, run_level=3))
    assert "run/walk" in charter_value("gated_movements.running.onramp.held_by")


def test_the_week_placement_puts_runs_on_easy_slots_only_within_the_cap_and_the_spacing():
    days = [{"date": f"2027-03-0{d + 1}", "archetype": SEQ[d]} for d in range(len(SEQ))] + [
        {"date": "2027-03-06", "archetype": None},
        {"date": "2027-03-07", "archetype": None},
    ]
    picks = cardio_menu.place_week(days, run_gate=_open_gate(), run_level=1)
    runs = [days[i]["archetype"] for i, p in enumerate(picks) if p and p["kind"] == "run_walk"]
    assert 0 < len(runs) <= CAP
    for name in runs:
        assert run_onramp.run_day_verdict(name, gate=_open_gate())["eligible"]
    assert all(p["kind"] not in cardio_menu.HARD for p in picks if p and p["kind"] == "run_walk")
    # the conditioning still lands: a run never takes a hard slot
    assert sum(1 for p in picks if p and p["kind"] in cardio_menu.HARD) == cardio_menu.conditioning_per_wk()
    closed = cardio_menu.place_week(days, run_gate=run_onramp.gate_state(PREP + 1, _weeks(), []))
    assert not any(p and p["kind"] == "run_walk" for p in closed)


def test_choose_kind_never_turns_a_conditioning_slot_or_a_red_day_into_a_run():
    verdict = {"eligible": True, "why": "run 1 of 2 this week", "block": run_onramp.run_walk_block(1)}
    hard = cardio_menu.choose_kind(target_date="2027-03-01", archetype=SEQ[0], week_kinds=[], run_walk=verdict)
    assert hard["kind"] in cardio_menu.HARD  # the week's first conditioning slot stays conditioning
    easy = cardio_menu.choose_kind(target_date="2027-03-05", archetype=SEQ[0], week_kinds=["tempo", "intervals"], run_walk=verdict)
    assert easy["kind"] == "run_walk" and easy["machine"] == cardio_menu.TREADMILL and easy["block"]["level"] == 1
    red = cardio_menu.choose_kind(
        target_date="2027-03-05", archetype=SEQ[0], week_kinds=["tempo", "intervals"], recovery_band="red", run_walk=verdict
    )
    assert red["kind"] != "run_walk"


# ── Stage 4: advance, hold, done ────────────────────────────────────────────────────────
def _s(level, rpe=EASY_TOP, pain=False, date="2027-03-01"):
    return {"date": date, "level": level, "rpe": rpe, "pain_flag": pain}


def test_two_sessions_at_or_under_the_easy_rpe_with_no_pain_advance_one_level():
    p = run_onramp.stage_progress([_s(1)] * NEED)
    assert p["level"] == LEVELS[1]["level"] and p["sessions_at_level"] == 0 and not p["stage4_done"]
    assert run_onramp.stage_progress([_s(1)] * (NEED - 1))["level"] == LEVELS[0]["level"]


def test_a_hard_an_unlogged_or_a_painful_session_does_not_advance():
    assert run_onramp.stage_progress([_s(1, rpe=EASY_TOP + 1)] * NEED)["level"] == 1
    assert run_onramp.stage_progress([_s(1, rpe=None)] * NEED)["level"] == 1
    reset = run_onramp.stage_progress([_s(1)] * (NEED - 1) + [_s(1, pain=True)] + [_s(1)] * (NEED - 1))
    assert reset["level"] == 1 and reset["sessions_at_level"] == NEED - 1


def test_a_strain_hold_holds_the_onramp_at_its_level():
    runs = [_s(1, date="2027-03-01")] * (NEED - 1) + [_s(1, date="2027-03-08")]
    held = run_onramp.stage_progress(runs, holds=["strain_flag:calf"], held_since="2027-03-05")
    assert held["level"] == 1 and held["held"] and "held at level 1" in held["reason"]
    assert run_onramp.stage_progress(runs)["level"] == 2  # the same record unheld advances


def test_an_undated_hold_never_advances_the_level():
    """The review's reproduction: a hold with no `held_since` used to count every session (level 2 under a 'held'
    reason). An undated hold now covers the whole record — the reason and the level agree."""
    p = run_onramp.stage_progress([_s(1)] * NEED, holds=["strain_flag:x"])
    assert p["level"] == LEVELS[0]["level"] and p["held"] and "no advance" in p["reason"]


def test_stage4_is_done_when_the_last_level_is_completed_twice():
    runs = [_s(lv["level"]) for lv in LEVELS for _ in range(NEED)]
    assert run_onramp.stage_progress(runs[:-1])["stage4_done"] is False
    done = run_onramp.stage_progress(runs)
    assert done["stage4_done"] is True and done["level"] == LEVELS[-1]["level"]


def test_his_logged_notes_are_read_for_level_rpe_and_a_lower_leg_pain_word():
    sessions = [
        {"date": "2027-03-03", "note": "run/walk L2 RPE 5 felt easy"},
        {"date": "2027-03-01", "note": "Run/walk level 1, RPE 4"},
        {"date": "2027-03-05", "note": "run/walk L2 RPE 5, sharp pain in my left shin"},
        {"date": "2027-03-02", "note": "incline walk 10% at 2.8 mph"},
    ]
    got = run_onramp.performed_from_notes(sessions)
    assert [(r["date"], r["level"], r["rpe"], r["pain_flag"]) for r in got] == [
        ("2027-03-01", 1, 4.0, False),
        ("2027-03-03", 2, 5.0, False),
        ("2027-03-05", 2, 5.0, True),
    ]


# ── the block, its note, its minutes ────────────────────────────────────────────────────
def test_every_level_renders_a_short_reasoned_block_whose_minutes_count_toward_movement():
    from training.routine_ir import ExerciseBlock, Set

    from mcp.tools_plan import HEVY_NOTE_OBSERVED_VISIBLE_CHARS

    for lv in run_onramp.levels():
        b = run_onramp.run_walk_block(lv["level"])
        line1, line2 = b["note"].split("\n")
        assert len(line1) <= HEVY_NOTE_OBSERVED_VISIBLE_CHARS and f"RPE <= {EASY_TOP}" in line1 and line2.startswith("Why: ")
        assert b["total_min"] == (lv["run_min"] + lv["walk_min"]) * lv["rounds"] == b["movement_minutes"]
        block = ExerciseBlock(movement_key="treadmill", sets=[Set(type="normal", duration_seconds=b["total_min"] * 60)], rest_seconds=0)
        assert cardio_menu.movement_minutes([block]) == b["total_min"]
    assert run_onramp.run_walk_block(len(LEVELS) + 1) is None


def test_the_onramp_runs_toward_twenty_to_thirty_minutes_continuous():
    last = run_onramp.levels()[-1]
    assert last["walk_min"] == 0 and 20 <= last["run_min"] * last["rounds"] <= 30
    assert run_onramp.levels()[0]["run_min"] < run_onramp.levels()[0]["walk_min"]  # starts walk-heavy


# ── the carve-out: limited to its list ──────────────────────────────────────────────────
def test_the_carve_out_is_limited_to_the_charter_list_and_a_box_jump_stays_excluded():
    from training.movement_catalog import carve_out_keys, generator_eligible, is_plyometric
    from training.routine_generator import _load_json

    movements = _load_json("movement_catalog.json")["movements"]
    carve = carve_out_keys()
    assert carve == set(charter_value("gated_movements.lower_leg_prep.carve_out_catalog_keys"))
    for key in carve:
        assert is_plyometric(movements[key], key)
        assert not generator_eligible(movements[key], 3, key=key)  # closed prep: excluded like every jump
        assert generator_eligible(movements[key], 3, key=key, prep_open=True)
    plyo = [k for k, v in movements.items() if is_plyometric(v, k) and k not in carve]
    assert "box_jump" in plyo and "high_pogos" in plyo
    leaked = [k for k in plyo if generator_eligible(movements[k], 3, key=k, prep_open=True)]
    assert not leaked, f"plyometric entries outside the carve-out are eligible: {leaked}"
    calf = movements["seated_calf_raise"]
    assert not is_plyometric(calf, "seated_calf_raise") and generator_eligible(calf, 3, key="seated_calf_raise")


def test_the_muscle_selector_never_picks_a_plyometric_entry():
    import random

    from training.movement_catalog import is_plyometric
    from training.routine_generator import _load_json, _select_movements_for_muscle

    catalog = _load_json("movement_catalog.json")
    muscles = {v.get("primary_muscle") for v in catalog["movements"].values() if is_plyometric(v)}
    picked = [
        k
        for m in muscles
        for k, _d in _select_movements_for_muscle(m, 12, catalog, 3, {}, random.Random(0), [])
        if is_plyometric(catalog["movements"][k], k)
    ]
    assert not picked, picked


# ── the prep on the served session ──────────────────────────────────────────────────────
def _catalog():
    from training.routine_generator import _load_json

    return _load_json("movement_catalog.json")["movements"]


def test_the_prep_rides_lower_days_from_the_prep_weight_and_a_hold_pauses_only_the_pogo_hops():
    items = [i["item"] for i in charter_value("gated_movements.lower_leg_prep.prescription")]
    pogo = next(i for i in items if "pogo" in i)
    on = run_onramp.prep_exposures(run_onramp.gate_state(PREP, None, []), "lower", _catalog())
    assert on["placed"] and [e["item"] for e in on["exposures"]] == items
    assert next(e for e in on["exposures"] if e["item"] == pogo)["movement_key"] in set(
        charter_value("gated_movements.lower_leg_prep.carve_out_catalog_keys")
    )
    assert all("Why: lower-leg prep" in e["note"] and "RPE" in e["cue"] for e in on["exposures"])
    held = run_onramp.prep_exposures(run_onramp.gate_state(PREP, None, ["strain_flag:calf"]), "lower", _catalog())
    assert pogo not in [e["item"] for e in held["exposures"]] and len(held["exposures"]) == len(items) - 1
    assert not run_onramp.prep_exposures(run_onramp.gate_state(PREP, None, []), "upper", _catalog())["placed"]
    assert not run_onramp.prep_exposures(run_onramp.gate_state(PREP + 1, None, []), "lower", _catalog())["placed"]
    # a calf key already in the session is not prescribed twice
    first_calf = on["exposures"][0]["movement_key"]
    again = run_onramp.prep_exposures(run_onramp.gate_state(PREP, None, []), "lower", _catalog(), taken={first_calf})
    assert again["exposures"][0]["movement_key"] not in (None, first_calf)


def test_the_served_session_carries_the_prep_on_a_lower_day():
    session = {"archetype": "lower", "prescription": {"exposures": [{"movement_key": "leg_press"}]}}
    run_onramp.attach_prep(session, "2027-01-20", PREP - 1, [], _catalog())
    assert session["lower_leg_prep"]["placed"] and session["lower_leg_prep"]["gate_state"] == run_onramp.PREP
    closed = {"archetype": "lower", "prescription": {"exposures": []}}
    run_onramp.attach_prep(closed, "2026-10-20", PREP + 40, [], _catalog())
    assert closed["lower_leg_prep"]["placed"] is False and closed["lower_leg_prep"]["gate_state"] == run_onramp.CLOSED


# ── the readers: the May tracker and the coach context ──────────────────────────────────
def test_the_may_tracker_reads_the_gate_from_this_module():
    from training import may_tracker as mt

    r = mt.running_gate_section(GATE - 1, _weeks(), [])
    assert r["gate_state"] == run_onramp.OPEN and r["walking"]["met"] == WEEKS and r["line"].startswith("Run gate: open")
    c = mt.running_gate_section(PREP + 10, None, None)
    assert c["gate_state"] == run_onramp.CLOSED and c["lb_to_prep"] == 10.0 and c["value"] == round(PREP + 10 - GATE, 1)


def test_the_coach_context_carries_the_gate_line_on_the_owner_channel_only():
    from training import coach_context

    row = {"running_gate": {"gate_state": "closed", "line": "Run gate: closed — 41.8 lb to the lower-leg prep."}}
    ctx = coach_context.assemble("2026-10-20", packet=None, constraint_block=None, tracker={"state": "measured", "row": row})
    assert ctx["run_gate"]["state"] == "measured" and "RUN GATE (owner-only)" in ctx["text"] and "41.8 lb" in ctx["text"]
    bare = coach_context.assemble("2026-10-20", packet=None, constraint_block=None)
    assert bare["run_gate"]["state"] == "not_supplied" and "no measured reading supplied" in bare["run_gate"]["line"]
    pub = coach_context.assemble("2026-10-20", packet=None, constraint_block=None, published=True)
    assert pub["run_gate"] is None and "RUN GATE" not in pub["text"]


# ── the must-agree pair: the owner's redline record and the charter's numbers ───────────
def test_the_redline_record_and_the_charter_state_the_same_gate():
    from training.owner_redlines import REDLINES

    rec = REDLINES["run_gate_lb"]
    onramp = charter_value("gated_movements.running.onramp")
    assert rec["value"] == GATE
    assert rec["tissue_clause"]["weeks"] == WEEKS and rec["tissue_clause"]["weight_bearing_hr_wk"] == HOURS
    assert rec["tissue_clause"]["stage_completed"] == onramp["stage"]
    assert rec["non_impact_intensity"]["not_within_h_before_heavy_lower"] == onramp["not_within_h_of_heavy_lower"]
    assert f"max {onramp['max_runs_per_wk']} runs/wk" in rec["gate"]


def test_the_run_walk_block_on_the_published_menu_names_no_gate_weight():
    view = tc.public_view()
    blk = view["cardio_menu"]["blocks"]["run_walk"]
    assert not any(k.endswith("_lb") for k in blk) and str(int(GATE)) not in str(blk)
    assert "gated_movements" not in view


def test_the_tracker_reads_each_walking_week_and_its_lower_leg_pain_from_the_rows_it_already_holds():
    """`tools_may_tracker.running_inputs` over row-shaped fixtures (the Strava day item, the Hevy per-workout row):
    hours are the walking modality only (a ride is not weight-bearing), a lower-leg pain note flags its week, and an
    unread source is None — never a pain-free or zero-hour week."""
    from mcp import tools_may_tracker as tmt

    sunday = "2027-02-28"
    strava, hevy = [], []
    for k in range(WEEKS):
        day = tmt.mt.shift(sunday, -7 * k - 2)
        walk = {"type": "Walk", "sport_type": "Walk", "moving_time_seconds": (HOURS + 1) * 3600}
        ride = {"type": "Ride", "sport_type": "Ride", "moving_time_seconds": 5 * 3600}
        strava.append({"date": day, "activities": [walk, ride]})
    pain_day = tmt.mt.shift(sunday, -7 * (WEEKS - 1) - 1)  # the oldest week
    hevy.append({"date": pain_day, "exercises": [{"name": "Calf Raise", "notes": "sharp pain in my left calf", "sets": []}]})
    got = tmt.running_inputs(sunday, strava, hevy)
    weeks = got["walking_weeks"]
    assert len(weeks) == WEEKS and all(w["hours"] == HOURS + 1 for w in weeks)
    assert [w["pain_flag"] for w in weeks] == [False] * (WEEKS - 1) + [True]
    assert got["holds"] == []  # the pain note is older than the hold's 14 days
    status = run_onramp.walking_weeks_status(weeks)
    assert status["met"] == WEEKS - 1 and status["broken_by"] == "pain_flag"
    unread = tmt.running_inputs(sunday, None, None)
    assert all(w["hours"] is None and w["pain_flag"] is None for w in unread["walking_weeks"]) and unread["holds"] is None
    assert unread["onramp"] is None and unread["stage4_done"] is False


def test_the_tracker_reads_stage_4_from_his_logged_run_walk_notes():
    from mcp import tools_may_tracker as tmt

    sunday = "2027-03-14"
    note = f"run/walk L1 RPE {EASY_TOP}"
    hevy = [
        {"date": f"2027-03-{d:02d}", "exercises": [{"name": "Treadmill", "notes": note, "sets": [{"duration_sec": 1260}]}]}
        for d in range(1, NEED + 1)
    ] + [
        {"date": "2027-03-10", "exercises": [{"name": "Leg Press", "notes": note, "sets": []}]}
    ]  # not a run block
    got = tmt.running_inputs(sunday, [], hevy)
    assert got["onramp"]["level"] == LEVELS[1]["level"] and got["stage4_done"] is False
    from training import may_tracker as mt

    sec = mt.running_gate_section(GATE - 1, got["walking_weeks"], got["holds"], got["stage4_done"], got["onramp"])
    assert sec["onramp"]["level"] == LEVELS[1]["level"]


# ── the tracker's hold is the plan's hold; Stage 4 survives the rolling window (review round, PR #5179) ──
def _run_row(day, level, rpe=EASY_TOP, extra=""):
    return {"date": day, "exercises": [{"name": "Treadmill", "notes": f"run/walk L{level} RPE {rpe}{extra}", "sets": []}]}


def test_a_lower_leg_strain_flag_holds_the_onramp_through_the_tracker():
    """`running_inputs` passes the hold's start, so the strain flag holds the on-ramp on the wired path: the two
    sessions before the shin note advance the level, the two after it do not."""
    from mcp import tools_may_tracker as tmt

    sunday = "2027-03-14"
    hevy = [_run_row("2027-03-01", 1), _run_row("2027-03-03", 1)]
    hevy.append({"date": "2027-03-06", "exercises": [{"name": "Calf Raise", "notes": "sharp pain in my left shin", "sets": []}]})
    hevy += [_run_row("2027-03-08", 2), _run_row("2027-03-10", 2)]
    got = tmt.running_inputs(sunday, [], hevy)
    assert got["holds"] and all(h.startswith("strain_flag:") for h in got["holds"]) and got["held_since"] == "2027-03-06"
    assert got["onramp"]["level"] == LEVELS[1]["level"] and got["onramp"]["held"] and "no advance" in got["onramp"]["reason"]
    unheld = tmt.running_inputs(sunday, [], [r for r in hevy if r["date"] != "2027-03-06"])
    assert unheld["holds"] == [] and unheld["onramp"]["level"] == LEVELS[2]["level"]


def test_the_tracker_hold_and_the_plan_hold_agree_on_dismissals_and_standing_constraints(monkeypatch):
    """The must-agree pair: the tracker resolves its hold through `steps_ramp.lower_leg_holds` — the plan path's
    (`attach_prep`) function — so an owner dismissal releases it and an active standing lower-leg constraint holds it."""
    from training import steps_ramp, training_context_registry as tcr

    from mcp import tools_may_tracker as tmt

    sunday = "2027-03-14"
    hevy = [{"date": "2027-03-10", "exercises": [{"name": "Calf Raise", "notes": "sharp pain in my left shin", "sets": []}]}]
    inst = tmt.pain_instances(hevy)
    assert tmt.running_inputs(sunday, [], hevy)["holds"] == steps_ramp.lower_leg_holds(sunday, inst) != []
    dismissal = tcr.build_dismissal_record(
        site="left shin", dismissed_on="2027-03-12", words="the shin is fine", movements=["Calf Raise"],
        flag_note_date="2027-03-10", recorded_at="2027-03-12T08:00:00Z",
    )  # fmt: skip
    assert steps_ramp.lower_leg_holds(sunday, inst, [dismissal]) == []  # the plan path releases it on his word
    assert tmt.running_inputs(sunday, [], hevy, [dismissal])["holds"] == []  # and so does the tracker
    standing = {"id": "test_ankle", "kind": "injury", "detail": "ankle", "dated": "2027-02-20", "confirmed": True, "status": "active"}
    monkeypatch.setattr(tcr, "RECORDED_CONSTRAINTS", [*tcr.RECORDED_CONSTRAINTS, standing])
    got = tmt.running_inputs(sunday, [], [])
    assert got["holds"] == steps_ramp.lower_leg_holds(sunday, []) == ["standing_constraint:test_ankle"]
    assert got["held_since"] == "2027-02-20"
    assert run_onramp.gate_state(GATE - 1, _weeks(), got["holds"])["state"] == run_onramp.HELD


def test_stage_4_survives_its_early_levels_leaving_the_anchor_window(monkeypatch):
    """The early levels sit before the tracker's anchor lookback; the one Hevy read reaches back to the charter's
    `onramp.history_from`, so the level and `stage4_done` never fall back as the record ages."""
    from training import rate_band

    from mcp import core, tools_may_tracker as tmt

    start = run_onramp.history_from()
    assert start and start <= "2026-10-20"
    days = [tmt.mt.shift("2026-10-20", 7 * i + d) for i in range(len(LEVELS)) for d in (0, 2)]
    hevy = [_run_row(day, LEVELS[i // NEED]["level"]) for i, day in enumerate(days)]
    reads = []

    def read_hevy(s, e):
        reads.append(s)
        return [r for r in hevy if s <= r["date"] <= e], []

    monday = "2027-03-01"
    monkeypatch.setattr(core, "query_source", lambda *a, **k: [])
    monkeypatch.setattr(core, "query_source_range", lambda *a, **k: [])
    monkeypatch.setattr(rate_band, "guidance_cap_for", lambda table, user_id="matthew": None)
    monkeypatch.setattr("mcp.tools_strength._read_hevy_all_phases", read_hevy)
    monkeypatch.setattr(tmt, "_anchor_series", lambda items: {})
    monkeypatch.setattr(tmt, "pacific_today", lambda: "2027-03-09")
    assert days[0] < tmt.mt.shift(monday, -7 - tmt.ANCHOR_LOOKBACK_DAYS)  # L1 is outside the anchor window
    row = tmt.compute_weeks(monday, weeks=1)[-1]
    from training.session_sequence import block_start

    assert reads == [min(start, block_start())]  # still ONE Hevy read; #5078's battery position reaches the block start through it
    gate = row["running_gate"]
    assert gate["onramp"]["level"] == LEVELS[-1]["level"] and gate["onramp"]["stage4_done"] is True


def test_the_gate_line_names_its_weight_and_date_and_agrees_with_the_plan_gate_5314():
    """#5314: the packet reads a stored tracker week, the plan the latest weigh-in; one function, so the same weight
    gives the same distance, and the packet line names which weight and day it was measured from."""
    from training import coach_context, may_tracker as mt

    series = {"2026-10-18": 302.2, "2026-10-24": 298.3}
    d, w = max(series.items())
    plan_gate = run_onramp.gate_state(w, None, [])
    packet = mt.running_gate_section(w, None, [], weight_date=d)
    assert (packet["lb_to_prep"], packet["value"]) == (plan_gate["lb_to_prep"], plan_gate["lb_to_gate"])
    assert packet["weight_date"] == d and f"{w:g} lb on {d}" in packet["line"]
    old = mt.running_gate_section(302.2, None, [], weight_date="2026-10-18")
    assert "302.2 lb on 2026-10-18" in old["line"]
    ctx = coach_context.assemble(
        "2026-10-24", packet=None, constraint_block=None, tracker={"state": "measured", "row": {"running_gate": old}}
    )
    assert "on 2026-10-18" in ctx["text"]
    assert "weigh-in undated" in run_onramp.gate_line(run_onramp.gate_state(w, None, []))
