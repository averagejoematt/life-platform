"""#5428 Lane B — the generator's lift notes, loads and warm-ups to the Hevy note standard.

What this holds (each with a mutation control that reds it):

  * a generated lift note is the standard's shape: line 1 the effort (`RPE 8–9[, last set RPE 9–10]`), then at most one
    reason and one cue — three lines at most, nothing the set rows show (no kg, no `Last:`, no set count, no load-model or
    gate vocabulary). Run over REAL generator renders (the 10-18 upper re-draft, the first v0.4 lower-heavy) and over the
    10-26 upper-volume shapes the review graded.
  * loads round to the implement (`rep_scheme.round_to_implement`): 192.9 -> 195, 210.5 -> 210, 89.3 -> 90.
  * the achieved-load floor: a week after 245 x 5 @ RPE 8 the squat is never prescribed 215, even across a bodyweight band.
  * a stale anchor (> 28 days, or none) is the pick-load form: a no-load W row of 8 and `W set: up to 8 easy reps, find the
    load.` — never an old kg history line.
  * Hevy's PREVIOUS is written to `inputs_snapshot["previous_loads"]` for the note linter (Lane D).

Fixtures are synthetic or the routine's own published loads (loads are ruled public). No bodyweight in a fixture is his:
the band tests use round synthetic numbers either side of a band line.
"""

from __future__ import annotations

import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO / "tests"))

from training import lift_note, load_ramp, movement_cues, rep_scheme, routine_generator  # noqa: E402
from training.routine_ir import ExerciseBlock, Set  # noqa: E402

LB = 0.45359237

# ── the rules a lift note must keep (standard §3.2, §5; the brief's owner rulings) ──────────────────────────────────
LINE1 = re.compile(r"^RPE \d+(?:\.5)?(?:–\d+(?:\.5)?)?(?:, last set RPE \d+(?:\.5)?(?:–\d+(?:\.5)?)?)?(?: · pick the load per hand)?$")
BANNED = re.compile(
    r"\bkg\b|\d\s*kg|Last:|\bsets? of\b|\bWeek \d|band anchor|\banchor\b|\bfloor\b|\bramp\b|never up|Down on the day|\bhold\b|"
    r"charter|standing-constraint|subtract-only|ECG|[Ss]inus|cardiology|Optional if|§|#\d|\bRIR\b|in the tank|e1RM|\bv0\.\d|"
    r"\(platform|you carried it|his own|…",
)


def note_problems(note: str) -> list[str]:
    """Every way one lift note breaks the standard (empty = clean)."""
    out: list[str] = []
    lines = note.split("\n")
    if not LINE1.match(lines[0]):
        out.append(f"line 1 is not the effort line: {lines[0]!r}")
    # standard §3.2/§7: effort, one reason, one cue — plus the pick-load W line when a rotated accessory (#5083) is also new
    # to him; the budget is 4 lines
    if len(lines) > 4:
        out.append(f"{len(lines)} lines (max 4: effort, one reason, the W line, one cue)")
    hit = BANNED.search(note)
    if hit:
        out.append(f"banned token {hit.group(0)!r}")
    return out


def _lift_blocks(ir):
    return [b for b in ir.exercises if not str(b.rationale_tag or "").startswith("cardio") and not any(s.duration_seconds for s in b.sets)]


# ── 1. real generator renders ──────────────────────────────────────────────────────────────────────────────────────
def test_every_lift_note_of_the_redrafted_10_18_upper_meets_the_standard():
    from test_warmup_sets_5049 import _redraft

    ideal = _redraft()
    bad = {b.movement_key: note_problems(b.notes) for b in _lift_blocks(ideal)}
    assert {k: v for k, v in bad.items() if v} == {}
    # the replaced text is kept on the record, not lost
    details = ideal.inputs_snapshot["lift_notes"]
    assert set(details) == {b.movement_key for b in _lift_blocks(ideal)}
    assert any("Last:" in d["detail"] for d in details.values())


def test_every_lift_note_of_the_first_v04_lower_heavy_meets_the_standard():
    from test_program_session_4064_4147 import _generate

    ideal = _generate("2026-09-25")[0]
    bad = {b.movement_key: note_problems(b.notes) for b in _lift_blocks(ideal)}
    assert {k: v for k, v in bad.items() if v} == {}


def test_the_rule_checker_fails_the_archived_10_26_originals():
    """Mutation control for the checker itself: the notes the platform pushed on 10-26 (bodyweights scrubbed) fail it."""
    originals = {
        "one_arm_db_row": (
            "hold 90 lb: 0 of 2 top sets at the top of 8-12 at or under the ceiling. Last: 50kg 5 (21 Oct) VOLUME: 3 sets of 8–12 @ "
            "RPE 8–9 (charter compound ceiling). Week 5 load 90 lb — held from what you already moved: 90 lb x 10 @ RPE 9 on "
            "2026-10-18, this band, no layoff. Down on the day if you must, never up."
        ),
        "chest_fly_machine": (
            "hold: 100 lb on 11-30 has a set with no RPE logged — not evidence it sat under the ceiling. Last: 45.5kg 10/10/10/10 "
            "(Nov 2024) ACCESSORY: 2 sets of 8–15 @ RPE 8–9; last set RPE 9–10 (charter ceilings). Week 5 load 60 lb — 80% of "
            "your band anchor after the 10% detraining discount (v0.3 §3). Down on the day if you must, never up.\n"
            "Optional if the ECG is not sinus."
        ),
        "squat_barbell": "HEAVY: 1 top set of 4–6 @ RPE 8–9, then 2 back-offs at −10 % of the top set (charter ceilings).",
    }
    for key, note in originals.items():
        assert note_problems(note), key


# ── 2. the 10-26 upper-volume shapes, through the composer ─────────────────────────────────────────────────────────
TARGET = "2026-10-26"
CATALOG = {
    "incline_db_press": {"equipment": "dumbbell", "anchor_family": "bench", "hevy_template_id_hint": "T-INC"},
    "one_arm_db_row": {"equipment": "dumbbell", "anchor_family": "row", "hevy_template_id_hint": "T-ROW"},
    "lat_pulldown": {"equipment": "cable", "anchor_family": "vertical_pull", "hevy_template_id_hint": "T-LAT"},
    "chest_fly_machine": {"equipment": "machine", "anchor_family": None, "hevy_template_id_hint": "T-FLY"},
    "lying_db_tricep_extension": {"equipment": "dumbbell", "anchor_family": None, "hevy_template_id_hint": "T-EXT"},
}


def _sess(date, lb, reps, rpe=None, n=1):
    return {"date": date, "top_weight_kg": lb * LB, "sets": [{"weight_kg": lb * LB, "reps": reps, "rpe": rpe}] * n}


HISTORY = {
    "T-INC": [_sess("2026-09-19", 80, 8, n=3)],  # 37 days before 10-26: stale, but the incline is warmed (its W row)
    "T-ROW": [_sess("2026-10-21", 110, 5, 8)],  # PREVIOUS 110 x 5 — the 90-lb volume row is two steps lighter
    "T-LAT": [_sess("2026-10-21", 160, 8, 8, n=2), _sess("2026-10-18", 160, 8, 8, n=2), _sess("2026-10-11", 160, 8, 8, n=2)],
    "T-FLY": [_sess("2022-01-17", 85, 10, n=4)],  # the 2022 anchor the review named
    "T-EXT": [_sess("2025-09-15", 25, 10, n=4)],
}


def _block(key, lb, n, lo, hi, tag, warm=()):
    sets = [Set(type="warmup", weight_kg=w * LB, reps=r) for w, r in warm]
    sets += [Set(weight_kg=lb * LB if lb else None, rep_range_start=lo, rep_range_end=hi) for _ in range(n)]
    return ExerciseBlock(movement_key=key, sets=sets, notes="Last: 36.5kg 8/8/8 (19 Sep) VOLUME: 3 sets of 8–12", rationale_tag=tag)


def _upper_volume():
    blocks = [
        _block("incline_db_press", 80, 2, 8, 12, "anchor:bench:volume", warm=((50, 8),)),
        _block("one_arm_db_row", 90, 3, 8, 12, "anchor:row:volume"),
        _block("lat_pulldown", 160, 2, 10, 12, "anchor:vertical_pull:volume"),
        _block("chest_fly_machine", 60, 2, 8, 15, "accessory:chest_fly_machine:accessory"),
        _block("lying_db_tricep_extension", 20, 2, 8, 15, "accessory:lying_db_tricep_extension:accessory"),
    ]
    floors = {
        "movements": {
            "lat_pulldown": {
                "progression": {
                    "basis": "step",
                    "step_kind": "reps",
                    "next_reps": 10,
                    "from_reps": 8,
                    "dates": ["2026-10-11", "2026-10-18", "2026-10-21"],
                }
            }
        }
    }
    return blocks, floors


def test_the_10_26_upper_volume_renders_to_the_a_grade_corpus():
    blocks, floors = _upper_volume()
    record = lift_note.compose_blocks(blocks, CATALOG, load_floors=floors, history_index=HISTORY, target_date=TARGET)
    notes = {b.movement_key: b.notes for b in blocks}
    assert notes == {
        "incline_db_press": "RPE 8–9\nBand pull-aparts first. Breathe out on the press.",
        "one_arm_db_row": "RPE 8–9\nVolume day: chase 12.\nBreathe out on the pull.",
        "lat_pulldown": "RPE 8–9\nNow aiming 10–12: 8s were RPE 8 three times.",
        # #5428 re-grade #2 (2026-10-31): a stale PREVIOUS still shows in Hevy's PREVIOUS column, so a row more than one
        # step under it says why; the feeler W line tests the rows' start load ("find the load" read as "ignore the rows")
        "chest_fly_machine": "RPE 8–9, last set RPE 9–10\nLighter: first time in 4 years.\nW set: up to 8 easy reps, test the load.",
        "lying_db_tricep_extension": (
            "RPE 8–9, last set RPE 9–10\nLighter: first time in 13 months.\nW set: up to 8 easy reps, test the load.\nElbows still."
        ),
    }
    assert all(not note_problems(n) for n in notes.values())
    # Hevy's PREVIOUS, for the note linter: the last performed top load per movement (lb), with its date
    assert record["previous_loads"]["one_arm_db_row"] == {"date": "2026-10-21", "template_id": "T-ROW", "lb": 110.0, "reps": 5, "rpe": 8.0}
    assert record["lift_notes"]["one_arm_db_row"]["detail"].startswith("Last: 36.5kg")


def test_a_stale_anchor_is_the_pick_load_form_with_a_feeler_row():
    """The 10-26 chest fly (a 2022 anchor): a no-load W row of 8 ahead of the engine's start load, and the pick line."""
    blocks, floors = _upper_volume()
    lift_note.compose_blocks(blocks, CATALOG, load_floors=floors, history_index=HISTORY, target_date=TARGET)
    fly = next(b for b in blocks if b.movement_key == "chest_fly_machine")
    assert (fly.sets[0].type, fly.sets[0].weight_kg, fly.sets[0].reps) == ("warmup", None, 8)
    assert [s.weight_kg for s in fly.sets[1:]] == [60 * LB, 60 * LB]  # the engine's start load stays on the working rows
    assert "80% of your band anchor" not in fly.notes and "Last:" not in fly.notes


def test_mutation_control_a_recent_anchor_is_not_the_pick_form():
    blocks, floors = _upper_volume()
    recent = dict(HISTORY, **{"T-FLY": [_sess("2026-10-19", 60, 12, 8)]})
    lift_note.compose_blocks(blocks, CATALOG, load_floors=floors, history_index=recent, target_date=TARGET)
    fly = next(b for b in blocks if b.movement_key == "chest_fly_machine")
    assert not any(s.type == "warmup" for s in fly.sets) and lift_note.PICK_LOAD_LINE not in fly.notes
    assert fly.notes == "RPE 8–9, last set RPE 9–10"


def test_a_row_more_than_one_step_from_previous_carries_a_reason_and_one_within_a_step_does_not():
    blocks, floors = _upper_volume()
    near = dict(HISTORY, **{"T-ROW": [_sess("2026-10-21", 95, 10, 8)]})  # 90 vs 95: one 5-lb step -> no reason
    lift_note.compose_blocks(blocks, CATALOG, load_floors=floors, history_index=near, target_date=TARGET)
    assert next(b for b in blocks if b.movement_key == "one_arm_db_row").notes == "RPE 8–9\nBreathe out on the pull."
    blocks, floors = _upper_volume()
    heavier = dict(HISTORY, **{"T-ROW": [_sess("2026-10-21", 75, 12, 7)]})  # 90 vs 75: three steps up
    lift_note.compose_blocks(blocks, CATALOG, load_floors=floors, history_index=heavier, target_date=TARGET)
    row = next(b for b in blocks if b.movement_key == "one_arm_db_row")
    assert row.notes.split("\n")[1] == "Heavier: 12 reps was RPE 7."


def test_the_same_load_as_a_previous_that_ran_to_rpe_10_carries_the_one_more_rep_reason():
    """Owner ruling 2026-10-30 (#5428): a bare same-load row after a grind reads as a copy of the grind, so the band's
    lower effort is said out loud. Within one step but a different load, or a PREVIOUS under RPE 10, stays silent."""
    blocks, floors = _upper_volume()
    grind = dict(HISTORY, **{"T-ROW": [_sess("2026-10-21", 90, 12, 10)]})  # 90 vs 90 at RPE 10
    lift_note.compose_blocks(blocks, CATALOG, load_floors=floors, history_index=grind, target_date=TARGET)
    row = next(b for b in blocks if b.movement_key == "one_arm_db_row")
    assert row.notes == "RPE 8–9\nSame load: aim to leave one more rep.\nBreathe out on the pull."
    assert lift_note.hevy_note_grammar.REASON_RE.match(row.notes.split("\n")[1])  # the linter reads it as a reason
    for prev in (_sess("2026-10-21", 90, 12, 9), _sess("2026-10-21", 95, 12, 10), _sess("2026-10-21", 90, 12)):
        blocks, floors = _upper_volume()
        lift_note.compose_blocks(blocks, CATALOG, load_floors=floors, history_index=dict(HISTORY, **{"T-ROW": [prev]}), target_date=TARGET)
        assert next(b for b in blocks if b.movement_key == "one_arm_db_row").notes == "RPE 8–9\nBreathe out on the pull."


def test_one_cue_per_family_and_no_press_cue_on_a_squat_day():
    blocks = [
        ExerciseBlock(
            movement_key="squat_barbell",
            sets=[Set(weight_kg=245 * LB, rep_range_start=4, rep_range_end=6)],
            rationale_tag="anchor:squat:heavy",
        ),
        ExerciseBlock(
            movement_key="front_squat",
            sets=[Set(weight_kg=135 * LB, rep_range_start=6, rep_range_end=10)],
            rationale_tag="anchor:squat:moderate",
        ),
    ]
    cat = {
        "squat_barbell": {"equipment": "barbell", "anchor_family": "squat", "hevy_template_id_hint": "S1"},
        "front_squat": {"equipment": "barbell", "anchor_family": "squat", "hevy_template_id_hint": "S2"},
    }
    hist = {"S1": [_sess("2026-10-16", 245, 5, 8)], "S2": [_sess("2026-10-16", 135, 8, 8)]}
    lift_note.compose_blocks(blocks, cat, load_floors={}, history_index=hist, target_date="2026-10-23")
    assert blocks[0].notes == "RPE 8–9\nAnkles + hips first. Brace each rep, breathe between reps."
    assert blocks[1].notes == "RPE 8–9"  # the second squat-family lift: no second cue
    assert "press" not in blocks[0].notes.lower()
    assert movement_cues.family_of("leg_press", {"anchor_family": "squat"}) == "leg_press"  # a leg press is not a squat cue


# ── 3. implement rounding ──────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "lb, equipment, logged, expect",
    [
        (192.9, "barbell", None, 195.0),
        (210.5, "barbell", None, 210.0),
        (89.3, "dumbbell", None, 90.0),
        (27.5, "dumbbell", None, 27.5),
        (26.2, "dumbbell", None, 25.0),
        (57.5, "cable", None, 57.5),
        (58.0, "cable", [50.0, 57.5, 65.0], 57.5),
        (435.0, "machine", None, 435.0),
        (212.5, "barbell", None, 210.0),  # a tie goes down
    ],
)
def test_loads_round_to_the_implement(lb, equipment, logged, expect):
    assert rep_scheme.round_to_implement(lb, equipment, logged) == expect


def test_mutation_control_the_old_half_kilo_floor_is_unloadable():
    """The pre-#5428 back-off: 0.5 kg floors put 192.9 lb on a barbell row; the implement step puts 195."""
    old = routine_generator._floor_half_kg(97.52235955 * 0.9) / LB  # 10-23: 90 % of the 215-lb top set
    assert round(old, 1) == 192.9 and old % 5
    assert rep_scheme.round_to_implement(old, "barbell") == 195.0


# ── 4. the achieved-load floor (the 10-23 squat) ───────────────────────────────────────────────────────────────────
SQUAT = "D04AC939"
# synthetic bodyweights either side of a 10-lb band line (200-209 then 190-199): the band changed, the strength did not
SQUAT_WEIGHTS = {"2026-10-16": 202.0, "2026-10-23": 199.0}
SQUAT_HISTORY = {SQUAT: [{"date": "2026-10-16", "top_weight_kg": 245 * LB, "sets": [{"weight_kg": 245 * LB, "reps": 5, "rpe": 8.0}] * 2}]}
HEAVY_SLOT = {"intensity": "heavy", "min_reps": 4, "target_reps": 5, "rpe_ceiling": 9}


def _squat_floor():
    return load_ramp.v03_floor(SQUAT, SQUAT_HISTORY, SQUAT_WEIGHTS, 199.0, as_of="2026-10-23", week=4, slot=HEAVY_SLOT)


def test_a_week_after_245_x_5_at_rpe_8_the_squat_top_set_is_not_prescribed_215():
    floor = _squat_floor()
    assert floor["fallback"] == "nearest_band"  # the band line was crossed: the in-band hold does not apply
    assert floor["ramp"]["hold"]["applies"] is False
    assert floor["ramp"]["achieved_floor"]["applies"] is True
    assert round(floor["floor_kg"] / LB) == 245
    assert floor["ramp"]["achieved_floor"]["achieved"]["date"] == "2026-10-16"


def test_mutation_control_without_the_achieved_floor_215_returns(monkeypatch):
    monkeypatch.setattr(load_ramp, "_apply_achieved_floor", lambda *a, **k: None)
    assert round(_squat_floor()["floor_kg"] / LB) == 215  # the 10-23 defect: the week-4 ramp's 75 %


def test_the_achieved_floor_ignores_a_set_older_than_14_days_and_one_over_the_ceiling():
    old = {SQUAT: [dict(SQUAT_HISTORY[SQUAT][0], date="2026-10-05")]}
    weights = dict(SQUAT_WEIGHTS, **{"2026-10-05": 202.0})
    f = load_ramp.v03_floor(SQUAT, old, weights, 199.0, as_of="2026-10-23", week=4, slot=HEAVY_SLOT)
    assert f["ramp"]["achieved_floor"]["applies"] is False
    grinder = {SQUAT: [{"date": "2026-10-16", "top_weight_kg": 245 * LB, "sets": [{"weight_kg": 245 * LB, "reps": 4, "rpe": 10.0}]}]}
    g = load_ramp.v03_floor(SQUAT, grinder, SQUAT_WEIGHTS, 199.0, as_of="2026-10-23", week=4, slot=HEAVY_SLOT)
    # 245 x 4 @ RPE 10 is not a load inside the slot's RPE 9 ceiling: the floor is its RPE-adjusted hold, under 245
    assert g["floor_kg"] / LB < 245


def test_the_back_offs_off_the_held_squat_are_on_the_bar():
    top = _squat_floor()["floor_kg"]
    assert rep_scheme.round_to_implement_kg(top * 0.9, "barbell") / LB == pytest.approx(220.0)
