"""tests/test_wrist_clock_cardio_5374.py — cardio prescriptions for the wrist clock, and his own shapes read back (#5374).

The owner rides with an iPad over the console and the watch gives no alert, so a block is ONE rule line he follows by
glancing at the watch clock: change points on a 2/5/10-minute grid, at most three numbers to remember (owner amendment
2026-10-26), never "the hill program". His own 10-25 note is the parse-back fixture (verbatim, from the issue body).
All other values are synthetic. No clock is read: every date is passed in.
"""

from __future__ import annotations

import os
import pathlib
import re
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO))

from health.adherence_calc import calculate_adherence  # noqa: E402
from training import (
    cardio_menu as cm,  # noqa: E402
    cardio_note as cn,  # noqa: E402
    cardio_progression as cp,  # noqa: E402
    routine_generator as rg,  # noqa: E402
    training_charter as tc,  # noqa: E402
    wrist_clock as wc,  # noqa: E402
)
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402
from training.training_notes import performed_shape  # noqa: E402

# his 10-25 Hevy cycling note, verbatim (issue #5374)
OWNER_NOTE = "8/12 for 2 mins for 20 mins / 8/14 for 2 mins for 20 mins / 8 level up every 2 mins from 40 to 60 to level 18"
MACHINES = ("cycling", "elliptical", "rowing_machine", "treadmill", "air_bike")
DAY = "2026-10-26"  # after the no-push gate's retirement (2026-10-18), so every kind renders as itself
CYCLING_TID = "D8F7F851"  # config/movement_catalog.json -> movements.cycling


def _compose(kind, machine, minutes, facts=None, **kw):
    return cn.compose(movement_key=machine, minutes=minutes, target_date=DAY, kind=kind, facts=facts, **kw)


def _cases():
    """Every KIND x machine pair, with and without a level on record, over the menu's minutes and off-grid totals."""
    for kind in cm.KINDS:
        for machine in MACHINES:
            for facts in ({"last_level": 10}, {}):
                for minutes in sorted({20, 25, 30, 45, 60, cm.block_minutes(kind)}):
                    yield kind, machine, facts, minutes


# ── box 1: one rule line per KIND x machine pair, under the grammar ────────────────────
def test_every_kind_machine_pair_renders_one_clock_rule_line_on_the_grid_with_at_most_three_numbers():
    offenders = []
    for kind, machine, facts, minutes in _cases():
        note, audit = _compose(kind, machine, minutes, facts)
        line1 = note.split("\n")[0]
        m = cn.LINE1_RE.match(line1)
        clock = m.group("clock") if m else None
        shape = wc.parse_rule(clock)
        why = f"{kind}/{machine}/{minutes}/{facts}: {line1!r}"
        if shape is None:
            offenders.append(f"no clock rule under RULE_RE — {why}")
            continue
        if wc.off_grid(shape):
            offenders.append(f"change points off the 2/5/10 grid {wc.off_grid(shape)} — {why}")
        if any(int(p) != p for p in shape["change_points"]):
            offenders.append(f"a change point is not a whole minute — {why}")
        if len(wc.numbers_to_remember(shape)) > wc.MAX_NUMBERS:
            offenders.append(f"{wc.numbers_to_remember(shape)} to remember — {why}")
        if shape["total_min"] != minutes or int(m.group("minutes")) != minutes:
            offenders.append(f"the clock adds up to {shape['total_min']}, not {minutes} — {why}")
        if audit["clock_rule"] != clock or audit["clock_off_grid"] != []:
            offenders.append(f"the audit does not carry the rule — {why}")
    assert offenders == [], "\n".join(offenders)


def test_the_grammar_is_the_module_docstrings_and_its_own_examples_parse():
    """The grammar is defined in `wrist_clock`'s docstring; each clause line's quoted example parses under `RULE_RE`."""
    doc = wc.__doc__ or ""
    for clause in ("HOLD", "ALT", "RAMP", "SPRINT", "TIME", "VALUE", "DELTA"):
        assert re.search(rf"^\s+{clause}\s+:=", doc, re.M), clause
    lines = re.findall(r"^\s+(?:HOLD|ALT|RAMP|SPRINT)\s+:=(.*)$", doc, re.M)
    examples = [re.findall(r'"([^"]+)"', line)[-1] for line in lines]
    assert len(examples) == 4, examples
    for ex in examples:
        assert wc.RULE_RE.match(ex), ex
    # the issue's own example shape parses too
    assert wc.parse_rule("8/12 every 2 min for 20 · then +1 level every 2 min from 40 to 60") is not None


def test_MUTATION_CONTROL_the_grammar_and_the_limits_can_fail():
    assert wc.parse_rule("the hill program, RPE 5–7") is None
    assert wc.parse_rule("level 10 for 30 · RPE 4–5") is None  # effort words are not part of the rule
    assert wc.off_grid({"change_points": [3, 6, 10, 15]}) == [3]
    # his own ride carries four numbers: read in full, never trimmed (the limit binds what we prescribe)
    assert wc.numbers_to_remember(performed_shape(OWNER_NOTE)) == ["8", "12", "14", "1"]
    # a note composed before the clock rule still reads as composed (re-drafts never stack)
    old = "Recumbent bike · 30 min · level 10 at 12.3 mph hill · the hill program, RPE 5–7, short phrases on the climbs"
    assert cn.is_composed(old) and cn.composed_kind(old) == "hills" and cn.clock_of(old) is None


# ── box 2: the shapes, dosed from the charter; never "program" / "preset" ──────────────
def test_no_note_says_program_or_preset():
    offenders = []
    for kind, machine, facts, minutes in _cases():
        for band in (None, "green", "yellow"):
            note, _ = _compose(kind, machine, minutes, facts, recovery_band=band)
            if re.search(r"\bprogram|\bpreset", note, re.I):
                offenders.append(f"{kind}/{machine}/{band}: {note!r}")
    assert offenders == [], "\n".join(offenders)


def _shape(kind, machine="cycling", minutes=30, facts=None):
    note, audit = _compose(kind, machine, minutes, {"last_level": 10} if facts is None else facts)
    return cn.clock_of(note), note.split("\n")[0], audit


def test_easy_and_the_incline_walk_hold_one_level_with_a_check_in():
    for kind, machine in (("easy", "cycling"), ("incline_treadmill_walk", "treadmill")):
        shape, line1, _ = _shape(kind, machine)
        assert [c["type"] for c in shape["clauses"]] == ["hold"] and len(shape["levels"]) == 1, line1
        assert shape["check_in_every"] == cn.EASY_CHECK_IN_MINUTES and shape["change_points"] == []


def test_tempo_holds_the_menus_tempo_level_with_its_talk_test():
    shape, line1, audit = _shape("tempo")
    assert [c["type"] for c in shape["clauses"]] == ["hold"]
    assert shape["levels"] == [10 + cm.TEMPO_LEVEL_STEP] == [audit["level"]]
    lo, hi = tc.charter_value("cardio_menu.blocks.tempo.rpe")
    assert f"RPE {lo}–{hi}, {tc.charter_value('cardio_menu.blocks.tempo.talk_test')}" in line1


def test_hills_climb_and_descend_on_the_step_minutes_and_the_treadmill_climbs_the_menus_band():
    shape, line1, _ = _shape("hills")
    assert [c["type"] for c in shape["clauses"]] == ["hold", "ramp", "ramp", "hold"], line1
    up, down = shape["clauses"][1], shape["clauses"][2]
    assert up["step"] == cn.HILL_LEVEL_STEP and down["step"] == -cn.HILL_LEVEL_STEP
    assert up["every"] == down["every"] == cm.HILL_STEP_MINUTES
    assert shape["top_level"] == 10 + cn.HILL_CLIMB_STEPS * cn.HILL_LEVEL_STEP and shape["base_level"] == 10
    assert "the hill program" not in line1
    # the treadmill: from the walk's dose to the top of the menu's starting band, one charter step at a time
    t_shape, t_line, audit = _shape("hills", "treadmill", facts={})
    band_top = tc.charter_value("cardio_menu.blocks.incline_treadmill_walk.starting_dose.incline_pct")[1]
    step = tc.charter_value("cardio_menu.blocks.incline_treadmill_walk.step.incline_pct")
    assert t_shape["unit"] == "%" and t_shape["top_level"] == band_top and t_shape["base_level"] == audit["incline_pct"]
    assert t_shape["clauses"][1]["step"] == step
    assert f"–{band_top:g}% at" in t_line  # the dose words name the band the rule climbs


def test_intervals_are_the_menus_set_sprinted_on_the_clock():
    efforts, work, easy = (
        tc.charter_value("cardio_menu.blocks.intervals.efforts"),
        *tc.charter_value("cardio_menu.blocks.intervals.work_easy_minutes"),
    )
    shape, line1, _ = _shape("intervals")
    sprint = next(c for c in shape["clauses"] if c["type"] == "sprint")
    assert sprint["work"] == work and sprint["every"] == work + easy
    assert sprint["value"] == 10 + cn.INTERVAL_LEVEL_STEP
    hard = [b for b in shape["blocks"] if b[2] == 10 + cn.INTERVAL_LEVEL_STEP]
    assert len(hard) == efforts and all(b[1] - b[0] == work for b in hard), line1
    assert f"RPE {tc.charter_value('cardio_menu.blocks.intervals.rpe_hard_minutes')} on the hard minutes" in line1


def test_with_no_level_on_record_the_rule_rides_his_own_base():
    shape, line1, _ = _shape("intervals", facts={})
    assert line1.split(" · ")[3].startswith("base for ") and "base+2 for" in line1
    assert shape["levels"] == []  # no level is invented


# ── box 3: the rule line first, then the why; the coach skill says so ──────────────────
def test_the_rule_line_comes_first_and_the_why_second():
    for kind in ("easy", "tempo", "hills", "intervals"):
        note, _ = _compose(kind, "cycling", 30, {"last_level": 10})
        lines = note.split("\n")
        assert len(lines) == 2 and cn.LINE1_RE.match(lines[0]).group("clock"), note
        assert cn.LINE1_RE.match(lines[1]) is None and not wc.RULE_RE.search(lines[1]), note


def test_the_coach_session_skill_says_a_cardio_prescription_is_a_clock_rule():
    skill = (REPO / ".claude" / "skills" / "coach-session" / "SKILL.md").read_text(encoding="utf-8")
    assert "A cardio prescription is a clock rule, not a machine program." in skill
    assert "the watch does not alert" in skill


# ── box 4: his own shape grammar, read back ────────────────────────────────────────────
def test_his_10_25_note_parses_into_a_structured_shape():
    shape = performed_shape(OWNER_NOTE)
    assert shape["status"] == "shaped" and shape["unparsed"] == []
    got = [(c["type"], c["start"], c["end"], c.get("every")) for c in shape["clauses"]]
    assert got == [("alternate", 0, 20, 2), ("alternate", 20, 40, 2), ("ramp", 40, 60, 2)]
    assert shape["clauses"][0]["values"] == [8, 12] and shape["clauses"][1]["values"] == [8, 14]
    ramp = shape["clauses"][2]
    assert ramp["from_resolved"] == 8 and ramp["step"] == 1 and ramp["to_resolved"] == ramp["to_stated"] == 18
    assert shape["total_min"] == 60 and sum(shape["level_minutes"].values()) == 60
    assert shape["level_minutes"]["8"] == 20 and shape["level_minutes"]["18"] == 2
    assert (shape["base_level"], shape["top_level"], shape["family"]) == (8, 18, "intervals")


def test_the_rest_of_his_grammar_reads_too():
    ramp = performed_shape("+2 levels every 2 mins from 10 to 20", total_min=30)
    assert ramp["clauses"][0]["step"] == 2 and ramp["family"] == "hills"
    sprint = performed_shape("level 9 for 10 then sprint at level 13 for 2 mins every 10 mins", total_min=30)
    assert [c["type"] for c in sprint["clauses"]] == ["hold", "sprint"] and sprint["total_min"] == 30
    assert sprint["level_minutes"] == {"9": 10 + 8 + 8, "13": 2 + 2}
    bare = performed_shape("sprint 2 every 10", total_min=30)
    assert bare["status"] == "shaped" and bare["clauses"][0]["end"] == 30
    assert performed_shape("Level 9 - 5.6 miles")["status"] == "none"


def test_a_shaped_ride_is_no_longer_read_as_its_top_level():
    """MUTATION CONTROL, executed: the single-level reader alone takes "to level 18" — the ramp's END — as the ride."""
    singles = [int(m.group(1)) for m in cp.LEVEL_RE.finditer(OWNER_NOTE)]
    assert singles == [18]  # the one "level N" reference the pre-#5374 reader saw
    lvl = cp.structured_level(OWNER_NOTE)
    assert lvl["status"] == "shaped_session" and lvl["level"] is None
    assert (lvl["base_level"], lvl["top_level"], lvl["levels"][:3]) == (8, 18, [8, 9, 10])
    assert cp.structured_level("Level 9 for 20 and then level 6 for 10")["status"] == "multi_level_session"  # unchanged


def _index():
    return {
        CYCLING_TID: [
            {"date": "2026-10-25", "note": OWNER_NOTE, "duration_sec": 3600, "distance_m": 30000},
            *[{"date": f"2026-10-{d:02d}", "note": "Level 8 flat", "duration_sec": 1800, "distance_m": 9000 + d} for d in range(10, 20)],
        ]
    }


def test_level_verdict_reads_the_levels_he_rode_and_keeps_them_out_of_the_speed_comparison():
    facts = cp.cardio_facts(CYCLING_TID, _index())
    assert facts["last_level"] is None and facts["last_level_status"] == "shaped_session"
    assert facts["last_shape"]["base_level"] == 8 and facts["excluded"] == {"shaped_session": 1}
    at8 = cp.level_verdict(facts["series"], 8, facts["shaped"])
    assert at8["shaped_arm"] == {
        "status": "read",
        "n_rides": 1,
        "minutes_at_level": 20,
        "top_level_ridden": 18,
        "dates": ["2026-10-25"],
        "in_speed_comparison": False,
    }
    without = cp.level_verdict(facts["series"], 8)
    assert {k: v for k, v in at8.items() if k != "shaped_arm"} == {k: v for k, v in without.items() if k != "shaped_arm"}
    last = cp.level_verdict(facts["series"], facts["last_level"], facts["shaped"])
    assert last["verdict"] == "no_level" and "levels 8–18" in last["basis"]
    assert "levels 8–18" in cp.render_cardio_cue(facts, last)


def test_a_shaped_last_ride_no_longer_prescribes_its_top_level():
    facts = cp.cardio_facts(CYCLING_TID, {CYCLING_TID: _index()[CYCLING_TID][:1]})
    assert cn.prescribed_level(facts, None, constrained=False) == (8, 8)  # its base, never 18
    _, audit = _compose("easy", "cycling", 30, facts)
    assert audit["level"] == 8 and "clock-shaped" in audit["level_basis"]


def test_his_shape_counts_as_the_kind_it_was_for_the_weeks_placement():
    assert cm.kind_of_performed("cycling", OWNER_NOTE) == "intervals"
    assert cm.kind_of_performed("cycling", "level 9 for 10 then +1 level every 2 mins from 10 to 30") == "hills"
    assert cm.kind_of_performed("cycling", "Level 9 for 30") == "easy"


def test_adherence_grades_the_performed_shape_against_the_prescribed_one():
    note, _ = _compose("intervals", "cycling", 60, {"last_level": 8})
    ir = RoutineSpec(
        routine_id="r-5374",
        target_date=DAY,
        archetype="upper",
        exercises=[ExerciseBlock(movement_key="cycling", sets=[Set(duration_seconds=3600)], notes=note)],
    )
    ride = {"exercise_template_id": CYCLING_TID, "notes": OWNER_NOTE, "sets": [{"type": "normal", "duration_seconds": 3600}]}
    out = calculate_adherence(ir, {"exercises": [ride]})
    grade = out["as_prescribed_by_kind"]["cardio"]["shape"]["cycling"]
    assert grade["status"] == "same_shape" and grade["minutes_delta"] == 0
    assert grade["performed"]["top_level"] == 18 and grade["prescribed"]["top_level"] == 8 + cn.INTERVAL_LEVEL_STEP
    assert grade["top_level_delta"] == 18 - (8 + cn.INTERVAL_LEVEL_STEP)
    assert out["as_prescribed_by_kind"]["cardio"]["verdict"] == "unknown"  # the RPE half is still unread: never folded in
    # absences are named
    blank = calculate_adherence(ir, {"exercises": [{**ride, "notes": ""}]})
    assert blank["as_prescribed_by_kind"]["cardio"]["shape"]["cycling"]["status"] == "performed_unread"
    prose = RoutineSpec(
        routine_id="r-5374b",
        target_date=DAY,
        archetype="upper",
        exercises=[ExerciseBlock(movement_key="cycling", sets=[Set(duration_seconds=3600)], notes="Easy ride, RPE 6 max.")],
    )
    assert (
        calculate_adherence(prose, {"exercises": [ride]})["as_prescribed_by_kind"]["cardio"]["shape"]["cycling"]["status"]
        == "prescribed_unread"
    )


# ── box 5: the grid never changes the minutes ──────────────────────────────────────────
def test_the_clock_leaves_the_blocks_minutes_and_movement_minutes_unchanged():
    for kind, machine in (("easy", "cycling"), ("hills", "cycling"), ("intervals", "rowing_machine"), ("hills", "treadmill")):
        for minutes in (20, 25, cm.block_minutes(kind), 45):
            block = ExerciseBlock(
                movement_key=machine, sets=[Set(duration_seconds=minutes * 60)], rationale_tag=f"cardio:{machine}:menu:{kind}"
            )
            spec = RoutineSpec(routine_id="r-5374-min", target_date=DAY, archetype="upper", exercises=[block])
            before = cm.movement_minutes(spec.exercises)
            assert rg.attach_cardio_cues(spec, cardio_index={}, whoop_index={}, aerobic_block=None) == 1
            after = cm.movement_minutes(spec.exercises)
            shape = cn.clock_of(spec.exercises[0].notes)
            assert before == after == minutes == shape["total_min"] == spec.inputs_snapshot["cardio_plan"]["movement_minutes"], (
                kind,
                machine,
            )
            assert [s.duration_seconds for s in spec.exercises[0].sets] == [minutes * 60]
