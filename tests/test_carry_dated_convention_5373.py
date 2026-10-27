"""tests/test_carry_dated_convention_5373.py - the dated carry convention (#5373, owner ruling 2026-10-27).

One logging rule from 2026-10-27: he logs ONE hand (the dumbbell he picks up) on every dumbbell movement, two-dumbbell carries
included. Two Farmers Walk sessions (2026-06-20, 2026-10-25) were logged as the TOTAL carried and are NOT edited in Hevy, so the
platform reads them through `load_convention_history` in `config/movement_catalog.json`:
`[{"until": "2026-10-26", "convention": "total_carried"}]` with `load_convention: per_hand` as the current convention.

What this file holds:
  * the resolver: the four two-dumbbell carries read `total_carried` on or before 2026-10-26 and `per_hand` from 2026-10-27;
    a sandbag and a suitcase carry (one object / one dumbbell) read `total_carried` on both sides;
  * a reader called with no date: `day` is a REQUIRED keyword (TypeError), and an entry with a history given an empty or
    malformed date RAISES `MissingSessionDate` - it never silently reads as current;
  * the readers: tonnage (a 2026-10-25 set of total T counts T; a 2026-10-27 set of per-hand P counts 2P), the progression
    history (a historical total reads as T/2 per hand), the PR / best weight, the stall readback, the carry line, the routine
    note (prescribes per hand);
  * a mutation control: strip the history and the 2026-10-25 tonnage doubles - the assertions above would red.

Every number is SYNTHETIC (the public repo carries no real loads).
"""

from __future__ import annotations

import copy
import json
import os
import pathlib
import sys
from datetime import date
from unittest.mock import patch

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

from fakes import FakeDdbTable  # noqa: E402
from training import (  # noqa: E402
    carry_line as cl,  # noqa: E402
    exercise_history as eh,  # noqa: E402
    load_progression,
    logging_conventions as lc,  # noqa: E402
    session_cues,
)
from training.muscle_volume import normalize_hevy_items, session_tonnage_lbs, working_sets_by_muscle  # noqa: E402

from mcp import hevy_readback_report, strength_helpers  # noqa: E402

CATALOG = json.loads((REPO / "config" / "movement_catalog.json").read_text())["movements"]
KG_TO_LB = 2.20462

OLD_DAY = "2026-10-25"  # logged as the TOTAL carried
LAST_OLD_DAY = "2026-10-26"
FIRST_NEW_DAY = "2026-10-27"  # the one-hand rule starts here
NEW_DAY = "2026-10-29"

TWO_DUMBBELL_CARRIES = ("farmers_walk", "farmers_walk_8d414b80", "db_gun_carries", "db_overhead_farmers_carry")
OVERHEAD = CATALOG["db_overhead_farmers_carry"]["hevy_template_id_hint"]  # a weight_reps carry (Core by the taxonomy)
WALK_8D = CATALOG["farmers_walk_8d414b80"]["hevy_template_id_hint"]
WALK_DISTANCE = CATALOG["farmers_walk"]["hevy_template_id_hint"]  # the distance-typed template (steps, no reps)
SUITCASE = CATALOG["suitcase_carry"]["hevy_template_id_hint"]
SANDBAG = CATALOG["sandbag_carry"]["hevy_template_id_hint"]


@pytest.fixture(autouse=True)
def _real_catalog():
    lc.set_catalog(CATALOG)
    eh._reset_for_tests()
    yield
    lc.set_catalog(None)
    eh._reset_for_tests()


def _workout(day: str, name: str, tid: str, weight_kg: float, reps: int = 10, n: int = 3) -> dict:
    return {
        "sk": f"DATE#{day}#WORKOUT#w-{day}-{tid[:6]}",
        "date": day,
        "source_workout_id": f"w-{day}-{tid[:6]}",
        "title": "synthetic",
        "exercises": [{"name": name, "template_id": tid, "sets": [{"type": "normal", "weight_kg": weight_kg, "reps": reps}] * n}],
    }


# -- the data: the catalog says it, no reader hard-codes the date ----------------------------------------------------------
def test_the_four_two_dumbbell_carries_are_per_hand_with_a_dated_total_history():
    for key in TWO_DUMBBELL_CARRIES:
        e = CATALOG[key]
        assert e[lc.LOAD_CONVENTION_FIELD] == lc.PER_HAND, key
        assert e[lc.LOAD_HISTORY_FIELD] == [{"until": "2026-10-26", "convention": lc.TOTAL_CARRIED}], key


def test_a_one_object_carry_has_no_history_and_stays_total_carried():
    for key in ("sandbag_carry", "suitcase_carry"):
        assert CATALOG[key][lc.LOAD_CONVENTION_FIELD] == lc.TOTAL_CARRIED, key
        assert lc.LOAD_HISTORY_FIELD not in CATALOG[key], key


# -- the resolver ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("key", TWO_DUMBBELL_CARRIES)
def test_each_two_dumbbell_carry_flips_on_the_cutover_day(key):
    e = CATALOG[key]
    assert lc.load_convention_of(e, day="2026-06-20") == lc.TOTAL_CARRIED
    assert lc.load_convention_of(e, day=OLD_DAY) == lc.TOTAL_CARRIED
    assert lc.load_convention_of(e, day=LAST_OLD_DAY) == lc.TOTAL_CARRIED  # `until` is inclusive
    assert lc.load_convention_of(e, day=FIRST_NEW_DAY) == lc.PER_HAND
    assert lc.load_convention_of(e, day=NEW_DAY) == lc.PER_HAND
    assert lc.load_convention_of(e, day=f"{NEW_DAY}T04:00:00") == lc.PER_HAND  # an instant's date part reads the same


@pytest.mark.parametrize("key", ("sandbag_carry", "suitcase_carry"))
def test_one_object_carries_are_total_carried_on_both_sides(key):
    for day in (OLD_DAY, LAST_OLD_DAY, FIRST_NEW_DAY, NEW_DAY):
        assert lc.load_convention_of(CATALOG[key], day=day) == lc.TOTAL_CARRIED
    assert lc.in_current_unit(40.0, lc.TOTAL_CARRIED, lc.current_load_convention_of(CATALOG[key])) == 40.0  # nothing to halve


def test_a_reader_called_without_a_date_fails_loudly():
    """STATED: no `day` is a TypeError (a required keyword); a history entry given an empty/malformed day raises
    MissingSessionDate. It never defaults to current - that reads a 2026-10-25 total as a per-hand load."""
    walk = CATALOG["farmers_walk"]
    with pytest.raises(TypeError):
        lc.load_convention_of(walk)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        lc.load_convention_for("Farmers Walk", WALK_DISTANCE)  # type: ignore[call-arg]
    for bad in (None, "", "yesterday", "2026-10"):
        with pytest.raises(lc.MissingSessionDate):
            lc.load_convention_of(walk, day=bad)
    with pytest.raises(lc.MissingSessionDate):
        lc.load_convention_for("Farmers Walk", WALK_DISTANCE, day=None)
    with pytest.raises(lc.MissingSessionDate):
        cl.carry_line("Farmers Walk", [{"type": "normal", "weight_kg": 30.0, "distance_m": 40}], template_id=WALK_DISTANCE, day=None)
    # an entry with no history needs no date
    assert lc.load_convention_of(CATALOG["db_bench_press_flat"], day=None) == lc.PER_HAND
    assert lc.load_convention_of(CATALOG["suitcase_carry"], day=None) == lc.TOTAL_CARRIED


def test_a_prescription_uses_the_current_convention_without_a_date():
    for key in TWO_DUMBBELL_CARRIES:
        assert lc.current_load_convention_of(CATALOG[key]) == lc.PER_HAND
    assert lc.current_load_convention_for("Farmers Walk", WALK_DISTANCE) == lc.PER_HAND
    assert lc.current_load_convention_for("Sandbag Carry", SANDBAG) == lc.TOTAL_CARRIED


def test_an_uncatalogued_farmers_walk_gets_the_dated_convention_from_its_title():
    lc.set_catalog({})
    assert lc.load_convention_for("Farmers Carry (synthetic)", "ZZZZ5373", day=OLD_DAY) == lc.TOTAL_CARRIED
    assert lc.load_convention_for("Farmers Carry (synthetic)", "ZZZZ5373", day=NEW_DAY) == lc.PER_HAND
    assert lc.load_convention_for("Suitcase Carry (synthetic)", "ZZZZ5374", day=NEW_DAY) == lc.TOTAL_CARRIED


# -- tonnage ---------------------------------------------------------------------------------------------------------------
def test_tonnage_a_total_logged_set_counts_T_and_a_per_hand_set_counts_2P():
    total_kg, per_hand_kg, reps, sets = 60.0, 30.0, 10, 3
    old = normalize_hevy_items([_workout(OLD_DAY, "DB Overhead Farmers Carry", OVERHEAD, total_kg, reps, sets)])
    new = normalize_hevy_items([_workout(FIRST_NEW_DAY, "DB Overhead Farmers Carry", OVERHEAD, per_hand_kg, reps, sets)])
    assert old[0]["exercises"][0]["load_convention"] == lc.TOTAL_CARRIED
    assert new[0]["exercises"][0]["load_convention"] == lc.PER_HAND
    t = total_kg * KG_TO_LB * reps * sets
    assert session_tonnage_lbs(old[0]) == pytest.approx(t, abs=1)  # T, as logged
    assert session_tonnage_lbs(new[0]) == pytest.approx(2 * per_hand_kg * KG_TO_LB * reps * sets, abs=1)  # 2P
    # the per-muscle volume goes through the same dated convention
    assert working_sets_by_muscle(old)["muscles"]["Core"]["volume_lbs"] == pytest.approx(t, abs=1)
    assert working_sets_by_muscle(new)["muscles"]["Core"]["volume_lbs"] == pytest.approx(t, abs=1)
    assert working_sets_by_muscle(old + new)["muscles"]["Core"]["volume_lbs"] == pytest.approx(2 * t, abs=2)  # one window, two eras


def test_tonnage_suitcase_and_sandbag_are_unchanged_across_the_cutover():
    for tid, name in ((SANDBAG, "Sandbag Carry"), (SUITCASE, "Suitcase Carry")):
        for day in (OLD_DAY, NEW_DAY):
            norm = normalize_hevy_items([_workout(day, name, tid, 40.0, 10, 2)])
            assert norm[0]["exercises"][0]["load_convention"] == lc.TOTAL_CARRIED
            assert session_tonnage_lbs(norm[0]) == pytest.approx(40.0 * KG_TO_LB * 10 * 2, abs=1)  # logged = the whole load, both eras


def test_mutation_control_without_the_history_the_old_session_doubles():
    """The assertion above discriminates: strip the history and a 2026-10-25 total is counted as a per-hand load (2T)."""
    mutated = copy.deepcopy(CATALOG)
    mutated["db_overhead_farmers_carry"][lc.LOAD_HISTORY_FIELD] = []  # a stated empty history wins over the title derivation
    lc.set_catalog(mutated)
    old = normalize_hevy_items([_workout(OLD_DAY, "DB Overhead Farmers Carry", OVERHEAD, 60.0, 10, 3)])
    t = 60.0 * KG_TO_LB * 10 * 3
    assert old[0]["exercises"][0]["load_convention"] == lc.PER_HAND
    assert session_tonnage_lbs(old[0]) == pytest.approx(2 * t, abs=1)  # the wrong answer the real catalog prevents
    assert session_tonnage_lbs(old[0]) != pytest.approx(t, abs=1)


def test_mutation_control_a_cutover_a_day_late_flips_the_first_new_session():
    mutated = copy.deepcopy(CATALOG)
    mutated["db_overhead_farmers_carry"][lc.LOAD_HISTORY_FIELD] = [{"until": "2026-10-27", "convention": lc.TOTAL_CARRIED}]
    lc.set_catalog(mutated)
    assert lc.load_convention_for("DB Overhead Farmers Carry", OVERHEAD, day=FIRST_NEW_DAY) == lc.TOTAL_CARRIED  # wrong: the data decides


# -- the progression history ------------------------------------------------------------------------------------------------
def _history(items: list[dict]) -> dict:
    with patch.object(eh, "_table", return_value=FakeDdbTable(rows=items)):
        return eh.load_recent_history(lookback_days=90, today=date(2026, 11, 2))


def test_a_historical_total_reads_as_half_per_hand_for_progression():
    total_kg = 60.0
    idx = _history(
        [_workout(OLD_DAY, "DB Overhead Farmers Carry", OVERHEAD, total_kg), _workout(NEW_DAY, "DB Overhead Farmers Carry", OVERHEAD, 32.0)]
    )
    by_day = {s["date"]: s for s in idx[OVERHEAD]}
    assert by_day[OLD_DAY]["top_weight_kg"] == pytest.approx(total_kg / 2)  # T/2 per hand
    assert by_day[OLD_DAY]["sets"][0]["weight_kg"] == pytest.approx(total_kg / 2)
    assert by_day[NEW_DAY]["top_weight_kg"] == pytest.approx(32.0)  # P, as logged
    facts = eh.history_facts(OVERHEAD, {OVERHEAD: [by_day[OLD_DAY]]})
    assert facts["last_top_weight_kg"] == pytest.approx(30.0)  # the "Last: 30kg" cue reads per hand


def test_the_progression_floor_is_never_a_total():
    """A 60-kg total on 2026-10-25 + a 30-kg per-hand set on 2026-10-29: the series is flat at 30, not a 60 -> 30 'drop'."""
    idx = _history(
        [_workout(OLD_DAY, "DB Overhead Farmers Carry", OVERHEAD, 60.0), _workout(NEW_DAY, "DB Overhead Farmers Carry", OVERHEAD, 30.0)]
    )
    series = [s["top_weight_kg"] for s in sorted(idx[OVERHEAD], key=lambda s: s["date"])]
    assert series == [pytest.approx(30.0), pytest.approx(30.0)]
    rule = {"kind": "double_progression", "consecutive_same_type_exposures": 2, "step_lb": 5, "step_pct": 2.5}
    limits = {
        "tolerance_rpe": 0.5,
        "compound": {"ceiling_rpe": 8.0, "limit_rpe": 8.5},
        "last_isolation_set": {"ceiling_rpe": 9.0, "limit_rpe": 9.5},
    }
    rx = load_progression.next_prescription(
        idx[OVERHEAD], current_kg=30.0, rep_range=(8, 12), cls="isolation", rule=rule, limits=limits, load_convention=lc.PER_HAND
    )
    assert rx["load_convention"] == lc.PER_HAND
    assert rx["next_load_kg"] >= 30.0  # never lowered by a phantom 60 -> 30 step
    assert "per hand" in rx["reason"] and "total" not in rx["reason"]


def test_a_cardio_style_distance_carry_with_no_reps_never_enters_the_progression_index():
    idx = _history([{**_workout(OLD_DAY, "Farmers Walk", WALK_DISTANCE, 40.0, reps=0), "source_workout_id": "x"}])
    assert WALK_DISTANCE not in idx  # reps == 0: structurally outside the weighted index (its steps line is the report)


# -- the PR / best weight ----------------------------------------------------------------------------------------------------
def test_best_weight_current_puts_the_old_total_in_the_per_hand_unit():
    items = [
        _workout(OLD_DAY, "DB Overhead Farmers Carry", OVERHEAD, 60.0),
        _workout(NEW_DAY, "DB Overhead Farmers Carry", OVERHEAD, 32.0),
    ]
    sessions = strength_helpers.extract_hevy_sessions(items, "", template_id=OVERHEAD)
    old, new = sessions
    assert old["load_convention"] == lc.TOTAL_CARRIED and old["current_load_convention"] == lc.PER_HAND
    assert old["best_weight"] == pytest.approx(60.0 * KG_TO_LB, abs=0.1)  # as logged
    assert old["best_weight_current"] == pytest.approx(30.0 * KG_TO_LB, abs=0.1)  # T/2 per hand
    assert new["best_weight_current"] == pytest.approx(new["best_weight"], abs=0.01)  # P as logged
    # volume is the total moved in both eras: T, and 2P
    assert old["volume_lbs"] == pytest.approx(60.0 * KG_TO_LB * 10 * 3, abs=1)
    assert new["volume_lbs"] == pytest.approx(2 * 32.0 * KG_TO_LB * 10 * 3, abs=1)


def test_the_pr_is_the_per_hand_best_not_the_old_total():
    from mcp.tools_strength import _summarize_exercise_sessions

    items = [
        _workout(OLD_DAY, "DB Overhead Farmers Carry", OVERHEAD, 60.0),
        _workout(NEW_DAY, "DB Overhead Farmers Carry", OVERHEAD, 32.0),
    ]
    sessions = strength_helpers.extract_hevy_sessions(items, "", template_id=OVERHEAD)
    summary = _summarize_exercise_sessions(OVERHEAD, sessions)["summary"]
    assert summary["best_weight_lbs"] == pytest.approx(32.0 * KG_TO_LB, abs=0.1)  # not the 60-kg total (132 lb)


# -- the stall readback ------------------------------------------------------------------------------------------------------
def test_stall_check_reads_the_old_total_as_per_hand(monkeypatch):
    monkeypatch.setattr(hevy_readback_report, "_prescription_for", lambda w: (None, None))
    seen: list[tuple[str, float]] = []
    from training import stall_detector  # stall_check imports `session_point_from_diff` at call time: spy on the module

    orig = stall_detector.session_point_from_diff

    def _spy(when, row):
        seen.append((when, row["performed_load_kg"]))
        return orig(when, row)

    monkeypatch.setattr(stall_detector, "session_point_from_diff", _spy)

    def _get(page=1, page_size=10):
        if page > 1:
            return {"workouts": []}
        return {
            "workouts": [
                {
                    "start_time": f"{d}T17:30:00+00:00",
                    "exercises": [
                        {
                            "template_id": OVERHEAD,
                            "title": "DB Overhead Farmers Carry",
                            "sets": [{"type": "normal", "weight_kg": kg, "reps": 10}] * 3,
                        }
                    ],
                }
                for d, kg in ((NEW_DAY, 30.0), (OLD_DAY, 60.0))
            ]
        }

    out = hevy_readback_report.stall_check({"template_id": OVERHEAD, "sessions": 3}, get_workouts=_get)
    assert out["status"] == "ok"
    assert dict(seen) == {NEW_DAY: pytest.approx(30.0), OLD_DAY: pytest.approx(30.0)}  # 60 total -> 30 per hand


# -- the carry line and the note ----------------------------------------------------------------------------------------------
def test_the_carry_line_names_the_convention_of_its_session_date():
    sets = [{"type": "normal", "weight_kg": 30.0, "distance_m": 60}] * 2
    old = cl.carry_line("Farmers Walk", sets, template_id=WALK_DISTANCE, day=OLD_DAY)
    new = cl.carry_line("Farmers Walk", sets, template_id=WALK_DISTANCE, day=FIRST_NEW_DAY)
    assert old["load_convention"] == lc.TOTAL_CARRIED and "TOTAL carried" in old["steps_basis"]
    assert new["load_convention"] == lc.PER_HAND and "ONE dumbbell" in new["steps_basis"]
    assert old["steps"] == new["steps"] == [60, 60]  # the step count is unaffected
    assert cl.carry_line("Suitcase Carry", sets, template_id=SUITCASE, day=NEW_DAY)["load_convention"] == lc.TOTAL_CARRIED
    assert cl.carry_line("Sandbag Carry", sets, template_id=SANDBAG, day=NEW_DAY)["load_convention"] == lc.TOTAL_CARRIED


def test_the_routine_note_prescribes_a_carry_per_hand():
    sets = [{"kind": "working", "distance_meters": 60}] * 2
    cue = session_cues.exposure_cue("carry", sets)
    assert "per hand" in cue and "TOTAL" not in cue and "both hands" not in cue


def test_a_carry_prescription_label_reads_per_hand():
    """'Farmers Walk 70 lb per hand' - the dumbbell-press wording (`load_progression._lb`)."""
    assert load_progression._lb(70 / KG_TO_LB, lc.current_load_convention_for("Farmers Walk", WALK_DISTANCE)) == "70 lb per hand"
    assert load_progression._lb(70 / KG_TO_LB, lc.current_load_convention_for("Bench Press (Dumbbell)")) == "70 lb per hand"


def test_the_conventions_line_states_the_one_hand_rule_and_the_dated_read():
    line = lc.CONVENTIONS_LINE
    assert "ONE dumbbell (PER HAND)" in line and "2026-10-27" in line and "total carried" in line and "half per hand" in line


# premerge-gate: 5373: reads `config/movement_catalog.json`, which `deploy/build_movement_catalog.py` regenerates - a rebuilt catalog that drops a carry's `load_convention_history` (or moves its `until`) must red on itself.
