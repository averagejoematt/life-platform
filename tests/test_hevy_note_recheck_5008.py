"""#5008 re-check (2026-10-23) — C1-C4 driven through the real renderers, on the shapes stored live.

The unit pins for the #5032 fixes live in tests/test_hevy_note_fixes_5008.py. This file drives each item
through the path that actually reaches Matthew, on record shapes copied from DynamoDB on 2026-10-23
(read-only):

C1 `tools_plan._place_block_on_first_exercise` — the function that writes the critics' block onto the Hevy
   exercise-0 note — on the 10-24 draft's critics record (two `change` verdicts, both `applied: false`).
C2 `recent_aerobic.build` -> `critics_aerobic.aerobic_flags` on a stored `cardio_hr` join: the 10-23 block
   (joined, 116.5 bpm) reaches `last_cardio_block_avg_hr`; the 10-16 block (no wearable overlapped) is unknown.
C3 `routine_generator._enforce_load_floors` — the floor line and the progression line land in the order the
   two rules ran, and a floor line whose load a progression then replaced says so (live 10-22: "db_curl:
   floor_raise -> 27.5 lb" was followed by "db_curl: floor applied -> 25 lb").
C4 `calculate_adherence` -> `self_added_volume.weekly_excess` on the 10-23 lower session: the leg press was
   programmed 1 warm-up + 2 working and performed 3 working — one added working set, which the
   warm-up-inclusive count (3 vs 3) hid.

Nothing here reads the clock or AWS.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from coach import critics, critics_aerobic  # noqa: E402
from health.adherence_calc import calculate_adherence  # noqa: E402
from training import recent_aerobic, routine_generator as rg, self_added_volume, training_charter as tc  # noqa: E402
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402

from mcp import tools_plan as tp  # noqa: E402

LB = 0.45359237


# ── C1 ────────────────────────────────────────────────────────────────────────────────
def _live_10_24_critics(applied: bool) -> dict:
    """The 74beb045 draft's stored record (2026-10-24 upper), reasons shortened."""
    return {
        "engine": critics.CRITICS_VERSION,
        "ran_at": "2026-10-24T03:00:00+00:00",
        "verdicts": [
            {"critic": "muscle_defense", "verdict": "change", "metric": "protein_days_missed_7d", "value": "7", "reason": "7 of 7 below"},
            {"critic": "joints_tendons", "verdict": "approve", "reason": "nothing in this packet crosses a stated threshold"},
            {"critic": "rate_advocate", "verdict": "change", "metric": "rate_ceiling", "value": "tripped", "reason": "4.4 lb/wk"},
            {"critic": "blueprint_historian", "verdict": "approve", "reason": "nothing in this packet crosses a stated threshold"},
        ],
        "changes": [
            {"critic": "muscle_defense", "field": "session.total_sets", "to": "hold", "applied": applied, "why": "hold: nothing to trim"},
            {"critic": "rate_advocate", "field": None, "applied": False, "why": "change carried no mechanical field"},
        ],
    }


def _ir(critics_rec: dict) -> RoutineSpec:
    ir = RoutineSpec(
        routine_id="r-5008-c1",
        target_date="2026-10-24",
        archetype="upper",
        exercises=[ExerciseBlock(movement_key="db_shoulder_press", sets=[Set(reps=8)], notes="GATE: ECG + feel.")],
    )
    ir.inputs_snapshot = {"critics": critics_rec}
    return ir


# #5428: the verdict block is the stored record's preview (`critics.notes_block`, shown by stage 2 and the chat);
# it no longer rides a Hevy note, so C1's verdict word is checked on the preview and the note is left as it was.
def test_c1_the_hevy_note_prints_flag_for_every_change_that_applied_nothing():
    from coach import critics

    ir = _ir(_live_10_24_critics(applied=False))
    before = ir.exercises[0].notes
    tp._place_block_on_first_exercise(ir)
    assert ir.exercises[0].notes == before and "RED TEAM" not in ir.exercises[0].notes
    preview = critics.notes_block(ir)
    assert "- muscle-defense FLAG:" in preview and "- rate-advocate FLAG:" in preview
    assert "CHANGE" not in preview


def test_c1_mutation_control_an_applied_change_still_prints_change_on_the_note():
    from coach import critics

    ir = _ir(_live_10_24_critics(applied=True))
    tp._place_block_on_first_exercise(ir)
    preview = critics.notes_block(ir)
    assert "- muscle-defense CHANGE:" in preview and "- rate-advocate FLAG:" in preview
    assert "RED TEAM" not in ir.exercises[0].notes


# ── C2 ────────────────────────────────────────────────────────────────────────────────
def _hevy_row(day: str, start: str, end: str, block: dict) -> dict:
    """A stored Hevy row: one cycling block at exercise index 1, with its `cardio_hr` join as DynamoDB holds it."""
    return {
        "date": day,
        "sk": f"DATE#{day}#WORKOUT#x",
        "start_time": start,
        "end_time": end,
        "exercises": [
            {"name": "Squat (Barbell)", "sets": [{"weight_kg": 97.5, "reps": 5}]},
            {"name": "Cycling", "sets": [{"duration_sec": int(block["duration_s"])}]},
        ],
        "cardio_hr": {"blocks": [{**block, "exercise_index": "1"}]},
    }


_JOINED_10_23 = {
    "state": "joined",
    "avg_hr": "116.5",
    "max_hr": "127",
    "hr_coverage": "0.828",
    "hr_source": "WHOOP",
    "duration_s": "2700",
    "modality": "cycling",
    "window": {"start_utc": "2026-10-24T00:30:02+00:00", "end_utc": "2026-10-24T01:15:02+00:00", "timing": "inferred_tail"},
}
_UNKNOWN_10_16 = {
    "state": "unknown",
    "avg_hr": None,
    "hr_coverage": "0",
    "duration_s": "2730",
    "modality": "cycling",
    "reason": "no HR-bearing wearable activity overlaps the block",
    "window": {"start_utc": "2026-10-16T23:59:59+00:00", "end_utc": "2026-10-17T00:45:29+00:00", "timing": "inferred_tail"},
}
_DRAFT = {"archetype": "upper", "exercises": [{"idx": 0, "label": "Bench Press", "movement_key": "barbell_bench_press"}]}


def _numbers(rows: list[dict], target: str) -> tuple[dict, list]:
    block = recent_aerobic.build(target_date=target, today=target, strava_items=[], hevy_workouts=rows)
    numbers: dict = {}
    unknown: list = []
    critics_aerobic.aerobic_flags(_DRAFT, block, numbers, [], unknown)
    return numbers, unknown


def test_c2_a_stored_joined_block_reaches_the_critics_number():
    numbers, unknown = _numbers(
        [_hevy_row("2026-10-23", "2026-10-23T23:04:27+00:00", "2026-10-24T01:30:02+00:00", _JOINED_10_23)], "2026-10-24"
    )
    assert numbers["last_cardio_block_avg_hr"] == pytest.approx(116.5)
    assert "last_cardio_block_avg_hr" not in unknown


def test_c2_a_block_no_wearable_covered_is_unknown_never_zero():
    row = _hevy_row("2026-10-16", "2026-10-16T22:22:35+00:00", "2026-10-17T01:00:29+00:00", _UNKNOWN_10_16)
    numbers, unknown = _numbers([row], "2026-10-17")
    assert numbers["last_cardio_block_avg_hr"] is None
    assert "last_cardio_block_avg_hr" in unknown


# ── C3 ────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def _fresh_charter():
    tc.reset_cache()
    yield
    tc.reset_cache()


def _lat_pulldown_case(hold_reason: str | None) -> tuple[list[str], ExerciseBlock]:
    """No load prescribed; 160 lb carried at RPE 7.5 twice — the floor sets 160, the double progression steps to 165."""
    catalog = rg._load_json("movement_catalog.json")
    tid = catalog["movements"]["lat_pulldown"]["hevy_template_id_hint"]
    history = {
        tid: [
            {"date": d, "top_weight_kg": 160 * LB, "sets": [{"weight_kg": 160 * LB, "reps": 12, "rpe": 7.5}]}
            for d in ("2026-10-16", "2026-10-14")
        ]
    }
    weights = {"2026-10-14": 300.0, "2026-10-16": 300.0, "2026-10-18": 300.0}
    block = ExerciseBlock(movement_key="lat_pulldown", sets=[Set(type="normal", rep_range_start=8, rep_range_end=12) for _ in range(2)])
    rationale: list[str] = []
    rg._enforce_load_floors([block], catalog, history, weights, "2026-10-19", 1, 7, rationale, hold_reason=hold_reason)
    return rationale, block


def test_c3_the_floor_line_precedes_the_progression_and_says_it_was_superseded(_fresh_charter):
    rationale, block = _lat_pulldown_case(None)
    floor_i = next(i for i, line in enumerate(rationale) if line.startswith("lat_pulldown: floor applied"))
    step_i = next(i for i, line in enumerate(rationale) if line.startswith("lat_pulldown: step"))
    assert floor_i < step_i  # the order the two rules ran in
    assert rationale[floor_i].startswith("lat_pulldown: floor applied, then superseded by step (next line) — ")
    assert all(s.weight_kg == pytest.approx(165 * LB) for s in block.sets)  # the load is the step's, as the lines now say


def test_c3_mutation_control_a_floor_nothing_replaced_carries_no_superseded_mark(_fresh_charter):
    rationale, block = _lat_pulldown_case("a deload the owner applied")
    (line,) = [x for x in rationale if x.startswith("lat_pulldown:")]
    assert line.startswith("lat_pulldown: floor applied — ") and "superseded" not in line
    assert all(s.weight_kg == pytest.approx(160 * LB) for s in block.sets)


# ── C4 ────────────────────────────────────────────────────────────────────────────────
def test_c4_the_10_23_leg_press_reports_one_added_working_set_the_inclusive_count_hid(monkeypatch):
    from health import adherence_calc

    monkeypatch.setattr(adherence_calc, "_load_template_cache", lambda: {})  # the catalog hint resolves leg_press; no S3
    catalog = rg._load_json("movement_catalog.json")
    tid = catalog["movements"]["leg_press"]["hevy_template_id_hint"]
    ir = RoutineSpec(
        routine_id="r-5008-c4",
        target_date="2026-10-23",
        archetype="lower",
        exercises=[ExerciseBlock("leg_press", sets=[Set(type="warmup"), Set(), Set()])],
    )
    performed = {"exercises": [{"exercise_" "template_id": tid, "sets": [{"type": "normal"}] * 3}]}
    adherence = calculate_adherence(ir, performed)
    (m,) = adherence["movements"]
    assert (m["programmed_sets"], m["performed_sets"]) == (3, 3)  # inclusive: no surplus visible
    # ingest stamps the routine match (`adherence_calc` match_routine, "matched") beside the counts
    row = {
        "date": "2026-10-23",
        "sk": "DATE#2026-10-23#WORKOUT#x",
        "title": "Foundation - Lower - 9 - 37",
        "adherence": {**adherence, "status": "matched"},
    }
    wk = self_added_volume.weekly_excess([row], "2026-10-23")[-1]
    assert (wk["programmed_sets"], wk["performed_sets"], wk["added_sets"]) == (2, 3, 1)
    assert wk["added"][0]["movement"] == catalog["movements"]["leg_press"]["title"]  # a title, not the key
