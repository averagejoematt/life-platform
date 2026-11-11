"""tests/test_step_gap_walk_5758.py — the walk that closes a day's projected gap to the steps floor (#5758).

What this holds (the three acceptance boxes of #5758):
  1. the plan names a walk sized to close the day's projected gap — a LIFTING day projects from lifting days, so the
     off-day walking volume never hides the lifting-day shortfall the block-1 retro (#5496) graded F; the goal is the
     steps ramp's `today_target` (the charter floor once reached, never a number of this module's own); the sizing is
     the evening nudge's one `walk_minutes`; stage 1 carries it on `constraint_block.steps_ramp.walk_to_close_gap` and
     stage 2 stores it on the drafted routine's record (`inputs_snapshot.critics.steps_walk`);
  2. the May tracker's steps trigger names each day it fired on with the walk offered (read back from the stored
     routines) and the walking minutes performed;
  3. the retro's Walking row input (`days_at_floor` / `days_measured`) is unchanged by the new fields.

Every asserted number is derived from fixtures and the charter; no clock is read (#4848): dates are fixed day keys and
the module is pure.
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
sys.path.insert(0, str(ROOT))

from common.pacific_time import shift_day_key  # noqa: E402
from training import (
    block_retro as br,  # noqa: E402
    may_tracker as mt,  # noqa: E402
    step_gap_walk as sgw,  # noqa: E402
    steps_nudge,  # noqa: E402
)
from training.training_charter import charter_value  # noqa: E402

DATE = "2026-11-12"  # a Thursday
FLOOR = int(charter_value("steps.floor"))
LIFTING_SESSION = {"source": "session_sequence", "prescription": {"anchors": ["squat"]}}
OFF_SESSION = {"source": "session_sequence", "prescription": None}


def _lift(day):
    return {"date": day, "exercises": [{"title": "Squat (Barbell)", "sets": [{"weight_kg": 80, "reps": 8, "type": "normal"}]}]}


def _window(counts, end=DATE):
    """The 14 days before `end`, oldest first, each with its resolved count."""
    n = len(counts)
    return {"days": [{"date": shift_day_key(end, -(n - i)), "steps": c, "degraded": None} for i, c in enumerate(counts)]}


# The shape of block 1 (#5496), exaggerated: lifting days far under the floor, off days far over it — the all-days
# mean clears the floor while every lifting day misses it (live 10-27..11-09: lifting ~6.9k, off ~18.4k).
LOW_LIFT, HIGH_OFF = FLOOR // 2, 2 * FLOOR + FLOOR // 2
PATTERN = ["lift", "lift", "off", "lift", "lift", "off", "lift", "lift", "off", "lift", "lift", "off", "lift", "lift"]
COUNTS = [LOW_LIFT if k == "lift" else HIGH_OFF for k in PATTERN]
WINDOW = _window(COUNTS)
HEVY = [_lift(d["date"]) for d, k in zip(WINDOW["days"], PATTERN) if k == "lift"]
RAMP_AT_FLOOR = {"state": "at_floor", "today_target": FLOOR, "floor": FLOOR, "date": DATE}


def _plan(**kw):
    args = dict(ramp=RAMP_AT_FLOOR, window=WINDOW, session=LIFTING_SESSION, hevy_rows=HEVY, hevy_covered_from=None)
    args.update(kw)
    return sgw.plan(DATE, **args)


# ── box 1: the walk is sized to the day's projected gap ─────────────────────────


def test_a_lifting_day_projects_from_lifting_days_and_gets_a_walk_sized_by_the_one_rule():
    out = _plan()
    assert out["state"] == sgw.WALK and out["day_kind"] == sgw.LIFTING and out["basis"] == "lifting_days"
    assert out["projected_steps"] == LOW_LIFT and out["days_used"] == PATTERN.count("lift")
    assert out["goal"] == FLOOR and out["gap"] == FLOOR - LOW_LIFT
    assert out["walk_minutes"] == steps_nudge.walk_minutes(FLOOR - LOW_LIFT)  # the evening nudge's one sizing
    assert out["line"].startswith(f"Walk {out['walk_minutes']} min on Thu, outside the session")


def test_must_fail_control_the_all_days_mean_would_have_hidden_the_lifting_day_gap():
    """The retro's defect class: the all-days mean clears the floor while every lifting day misses it."""
    all_days_mean = round(sum(COUNTS) / len(COUNTS))
    assert all_days_mean >= FLOOR  # the fixture IS the trap: a whole-window projection offers no walk
    assert sgw.projection(WINDOW["days"], sgw.UNKNOWN_KIND, None)["projected_steps"] == all_days_mean
    assert _plan(session=None)["state"] == sgw.ON_TRACK  # kind unknown -> all days -> the gap disappears
    assert _plan()["state"] == sgw.WALK  # typed by the Hevy record, the lifting day gets its walk


def test_an_off_day_projects_from_off_days():
    out = _plan(session=OFF_SESSION)
    assert out["day_kind"] == sgw.OFF and out["basis"] == "off_days" and out["projected_steps"] == HIGH_OFF
    assert out["state"] == sgw.ON_TRACK and out["walk_minutes"] == 0 and out["line"] is None


def test_the_goal_is_the_ramps_target_never_a_number_of_its_own():
    ramping = {"state": "ramping", "today_target": FLOOR - 1000, "floor": FLOOR}
    out = _plan(ramp=ramping)
    assert out["goal"] == FLOOR - 1000 and out["gap"] == FLOOR - 1000 - LOW_LIFT
    assert f"toward the {FLOOR:,} floor" in out["line"]
    unknown = _plan(ramp={"state": "unknown", "reason": "steps_window read failed"})
    assert unknown["state"] == sgw.UNKNOWN and unknown["reason"] == "steps_window read failed" and unknown["line"] is None
    assert "goal" not in unknown  # no walk sized against an invented floor


def test_an_unread_hevy_record_or_too_few_days_of_the_kind_falls_back_to_all_days_and_says_why():
    unread = _plan(hevy_rows=None)
    assert unread["basis"] == "all_days" and unread["basis_note"] == "the Hevy record was not read"
    two_lifts = HEVY[:2]
    sparse = _plan(hevy_rows=two_lifts)
    assert sparse["basis"] == "all_days" and "fewer than" in sparse["basis_note"]


def test_days_before_the_hevy_coverage_leave_the_same_kind_mean_and_partial_days_are_excluded():
    covered = WINDOW["days"][7]["date"]
    out = _plan(hevy_covered_from=covered)
    assert out["days_used"] == PATTERN[7:].count("lift")
    days = [dict(d) for d in WINDOW["days"]]
    days[-1] = {**days[-1], "steps": 1, "degraded": "partial_day"}
    assert sgw.projection(days, sgw.LIFTING, sgw.lifting_dates(HEVY))["projected_steps"] == LOW_LIFT


def test_no_measured_day_is_unknown_never_zero_steps():
    out = _plan(window=_window([None] * 14))
    assert out["state"] == sgw.UNKNOWN and out["projected_steps"] is None


def test_attach_puts_the_walk_on_the_blocks_steps_ramp():
    block = {"date": DATE, "steps_ramp": dict(RAMP_AT_FLOOR), "session": LIFTING_SESSION}
    sgw.attach(block, WINDOW, HEVY)
    walk = block["steps_ramp"]["walk_to_close_gap"]
    assert walk["state"] == sgw.WALK and walk["goal"] == FLOOR
    no_ramp = {"date": DATE, "session": LIFTING_SESSION}
    sgw.attach(no_ramp, WINDOW, HEVY)
    assert "steps_ramp" not in no_ramp


def _source(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_stage_1_attaches_the_walk_and_stage_2_stores_it_on_the_drafted_routine():
    tree = ast.parse(_source("mcp/tools_plan.py"))
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    stage1 = ast.unparse(fns["tool_plan_next_session"])
    assert "step_gap_walk.attach(block, steps_window, prescription_rows)" in stage1
    stage2 = ast.unparse(fns["_run_stage_2"])
    assert "'steps_walk': (block.get('steps_ramp') or {}).get('walk_to_close_gap')" in stage2


# ── box 2: the tracker's trigger names each day, offered vs performed ───────────


def _routine(day, offer, ran_at="2026-11-01T02:00:00Z"):
    return SimpleNamespace(target_date=day, inputs_snapshot={"critics": {"ran_at": ran_at, "steps_walk": offer}})


MON = "2026-11-02"
WEEK_COUNTS = [FLOOR - 4000, FLOOR + 100, FLOOR - 3000, FLOOR - 500, FLOOR + 2000, FLOOR - 6000, FLOOR + 3000]
WEEK = [{"date": mt.shift(MON, i), "steps": c, "degraded": None} for i, c in enumerate(WEEK_COUNTS)]
BELOW = [d["date"] for d in WEEK if d["steps"] < FLOOR]


def test_offers_are_read_back_newest_stage_2_first():
    old = {"state": "walk", "walk_minutes": 20}
    new = {"state": "walk", "walk_minutes": 40}
    offers = sgw.offers_by_date([_routine(MON, old, "2026-11-01T01:00:00Z"), _routine(MON, new, "2026-11-01T03:00:00Z")])
    assert offers == {MON: new}
    assert sgw.offers_by_date(None) is None
    assert sgw.offers_by_date([SimpleNamespace(target_date=MON, inputs_snapshot={})]) == {}


def test_the_steps_trigger_names_every_day_with_the_walk_offered_and_performed():
    offers = {
        BELOW[0]: {"state": "walk", "walk_minutes": 40, "goal": FLOOR, "projected_steps": FLOOR - 4000, "basis": "lifting_days"},
        BELOW[1]: {"state": "walk", "walk_minutes": 30, "goal": FLOOR},
        BELOW[2]: {"state": "on_track", "walk_minutes": 0, "goal": FLOOR},
    }
    performed = {BELOW[0]: 15.0, BELOW[1]: 30.0, BELOW[2]: 0.0, BELOW[3]: None}
    steps = mt.steps_section(WEEK, None, {"offers": offers, "performed": performed})
    att = {a["date"]: a for a in steps["walk_attribution"]}
    assert list(att) == BELOW
    assert att[BELOW[0]]["verdict"] == sgw.WALK_SHORT and att[BELOW[0]]["offered"]["walk_minutes"] == 40
    assert att[BELOW[0]]["performed_walk_minutes"] == 15.0 and att[BELOW[0]]["steps"] == FLOOR - 4000
    assert att[BELOW[1]]["verdict"] == sgw.WALK_DONE
    assert att[BELOW[2]]["verdict"] == sgw.NO_GAP_PROJECTED
    assert att[BELOW[3]]["verdict"] == sgw.NOT_OFFERED and att[BELOW[3]]["offered"] == {"state": "none_on_record"}
    row = mt.build_week(
        MON,
        weight={},
        waist=mt.waist_section([], mt.shift(MON, 6)),
        steps=steps,
        anchors=mt.anchors_section({}, mt.shift(MON, 6)),
        volume=mt.volume_section({"muscles": {}}),
        fitness=mt.fitness_section(None),
    )
    trig = next(t for t in row["triggers"]["fired"] if t["id"] == "steps_floor_missed")
    assert [d["date"] for d in trig["days"]] == BELOW and trig["days"][0]["offered"]["walk_minutes"] == 40


def test_unread_offers_are_said_never_read_as_no_offer():
    steps = mt.steps_section(WEEK, None, {"offers": None, "performed": {}})
    assert {a["verdict"] for a in steps["walk_attribution"]} == {"offers_not_read"}
    assert {a["offered"]["state"] for a in steps["walk_attribution"]} == {"not_read"}


def test_without_the_builders_reads_the_trigger_still_names_its_days():
    steps = mt.steps_section(WEEK)
    assert "walk_attribution" not in steps
    row = mt.build_week(
        MON,
        weight={},
        waist=mt.waist_section([], mt.shift(MON, 6)),
        steps=steps,
        anchors=mt.anchors_section({}, mt.shift(MON, 6)),
        volume=mt.volume_section({"muscles": {}}),
        fitness=mt.fitness_section(None),
    )
    trig = next(t for t in row["triggers"]["fired"] if t["id"] == "steps_floor_missed")
    assert trig["days"] == [{"date": d} for d in BELOW] and trig["evidence"] == BELOW


def test_performed_minutes_are_the_walking_layers_and_unknown_when_a_source_is_unread():
    day = MON
    hevy = [{"date": day, "exercises": [{"name": "Treadmill", "sets": [{"duration_sec": 1800, "type": "normal"}]}]}]
    assert sgw.performed_minutes(day, [], hevy) == 30.0  # a 30-min Hevy treadmill block is 30 walking minutes
    other_day = [{**hevy[0], "date": shift_day_key(day, 1)}]
    assert sgw.performed_minutes(day, [], other_day) is None  # no record that day: unknown, never 0
    assert sgw.performed_minutes(day, None, hevy) is None and sgw.performed_minutes(day, [], None) is None


# ── box 3: the retro's Walking row reads the same input ─────────────────────────


def test_the_retro_walking_input_is_unchanged_by_the_attribution():
    plain = mt.steps_section(WEEK)
    with_walks = mt.steps_section(WEEK, None, {"offers": {}, "performed": {}})
    for k in ("days_measured", "days_at_floor", "days_at_target", "days_below_floor", "value"):
        assert plain[k] == with_walks[k]
    rows = [{"week_start": MON, "week_end": mt.shift(MON, 6), "steps": s} for s in (plain, with_walks)]
    assert br._steps_evidence(rows[:1])["days_at_floor"]["value"] == br._steps_evidence(rows[1:])["days_at_floor"]["value"]
    m = {"window": f"{MON}..{mt.shift(MON, 6)}", "threshold": 0.9}
    assert br._grade_steps_share(m, rows[:1], {}) == br._grade_steps_share(m, rows[1:], {})
