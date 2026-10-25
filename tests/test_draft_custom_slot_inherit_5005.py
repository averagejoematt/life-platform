"""tests/test_draft_custom_slot_inherit_5005.py — a custom draft is gated on its program slot's floors (#5005).

THE DEFECT (owner's live MCP session, 2026-10-18; reproduced read-only from the stored drafts):
the engine draft 2167c0e6… for the week-4 upper-volume session tagged every block with its slot
(`anchor:bench:volume`) and its bench floor read 83.91 kg (RPE-9 rep cap 81.65 kg, then the #4408
hold of the 2026-10-15 83.91 kg x 10 @ 9). A `draft_custom` of the SAME movements and sets
(014e1142…) tagged every block `custom`; the commit gate reads the slot off that tag
(`load_ramp.slot_of`), found no intensity, fell back to the lowest program ceiling (RPE 8,
"unknown intensity", #4149), skipped the hold, and floored the bench at 79.38 kg.

What these tests hold, all on the wire (`tests/fixtures/draft_custom_slot_5005`, read-only captures):

  1. THE STORED DRAFTS — the fixture's two 10-18 drafts carry the floors the issue quotes.
  2. THE ENGINE DRAFT, regenerated from the wire, tags the bench `anchor:bench:volume` at 83.91 kg.
  3. THE CUSTOM DRAFT, stamped, carries the engine's tag on every prescribed movement and the slot's
     `session_role`; the commit gate's audit gives it the engine draft's floor for EVERY program
     movement (bench 83.91 kg, RPE ceiling 9, ceiling_basis "slot").
  4. OFF-PROGRAM movements (cycling, a stretching template, a lift the slot does not prescribe)
     stay `custom`.
  5. MUTATION CONTROL — without the stamp the gate skips the hold (the live 79.38 kg at RPE 8; 81.65 kg at the #5058 RPE 9).
  6. FAIL-SOFT — an unreadable record or a non-program date leaves every block custom and says so.
  7. WIRING — `manage_hevy_routine draft_custom` runs the stamp and persists it.

Clock: every path is driven by the fixed `target_date` 2026-10-18 and the captured rows; no
asserted number is computed through a live clock (#4848).
"""

# premerge-gate: #5005 reads config/movement_catalog.json + config week grid through the generator's _load_json
from __future__ import annotations

import json
import os
import pathlib
import sys
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import load_ramp, routine_generator  # noqa: E402
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402

from mcp import draft_custom_session  # noqa: E402


@pytest.fixture(autouse=True)
def _pre_rotation_record():
    """#5075: the wire fixture is the 2026-10-18 record, drafted before accessory slots rotated — the rotation is held off
    (no program position) so the engine and the custom draft compare against the template that record was drafted from."""
    with patch("training.variant_rotation.position", return_value=None):
        yield


DAY = "2026-10-18"
WIRE = json.loads((REPO / "tests" / "fixtures" / "draft_custom_slot_5005" / "wire_2026_10_18.json").read_text())
ROWS = WIRE["hevy_rows"]
WEIGHTS = {k: float(v) for k, v in WIRE["bodyweights_lb"].items()}
MOVEMENTS = json.loads((REPO / "config" / "movement_catalog.json").read_text())["movements"]
BENCH = "barbell_bench_press"
BENCH_ENGINE_KG = 83.91458845000001  # 185 lb — the engine draft's stored floor
BENCH_CUSTOM_LIVE_KG = 79.37866475  # 175 lb — the custom draft's stored floor (the defect)
PROGRAM_KEYS = (
    "barbell_bench_press",
    "one_arm_db_row",
    "db_shoulder_press",
    "lat_pulldown",
    "cable_chest_fly",
    "cable_tricep_pushdown",
    "db_curl",
)


@pytest.fixture(autouse=True)
def _upper_volume_as_served_2026_10_18():
    """The wire is the 2026-10-18 upper-volume session, served WITH the overhead press; #5162 (owner ruling 2026-10-23)
    moved the press's sets to a face pull. What this file holds is the custom-draft slot stamp (#5005), not the week's
    design, so the replay runs against upper-volume's template as it was served that day (`served_templates_5162`)."""
    from served_templates_5162 import pre_5162_upper_days

    with pre_5162_upper_days():
        yield


def _history():
    """The real `load_history_indexes` over the captured rows (the generator's and the gate's index)."""
    import datetime

    from training import exercise_history

    class _Table:
        def query(self, **_kw):
            return {"Items": ROWS}

    with patch.object(exercise_history, "_table", return_value=_Table()):
        return exercise_history.load_history_indexes(lookback_days=30, today=datetime.date(2026, 10, 18))[0]


def _custom_ir(extra: list[ExerciseBlock] | None = None) -> RoutineSpec:
    """The 2026-10-18 custom draft as stored: the same movements and sets, every block `custom`."""
    blocks = []
    for ex in WIRE["drafts_2026_10_18"]["custom"]["exercises"]:
        sets = [Set(**s) for s in ex["sets"]]
        blocks.append(ExerciseBlock(movement_key=ex["movement_key"], sets=sets, rationale_tag=ex["rationale_tag"]))
    return RoutineSpec(
        routine_id="r5005",
        target_date=DAY,
        archetype="custom",
        variant="ideal",
        title="t",
        notes="",
        version=1,
        created_at="2026-10-18T17:00:00+00:00",
        created_by="chat",
        source_action="draft_custom",
        status="draft",
        exercises=blocks + list(extra or []),
        inputs_snapshot={"authored": "custom"},
        rationale=[],
    )


def _gate_floors(ir) -> dict:
    from mcp.hevy_prescription_gate import derive_load_floors

    with patch("mcp.plan_hevy_windows._block_workouts", return_value=ROWS):
        return derive_load_floors(ir, movements=MOVEMENTS, history_index=_history(), weight_index=WEIGHTS)["movements"]


def _rep_cap(row: dict) -> dict:
    return (row.get("ramp") or {}).get("rep_cap") or {}


def _engine_ideal():
    with patch.object(routine_generator, "_load_note_indexes", return_value=(_history(), WEIGHTS, {}, {})):
        return routine_generator.generate_routines(routine_generator.GeneratorInputs(target_date=DAY, block_workouts=ROWS))[0]


# ── 1. the stored drafts are the issue's numbers ─────────────────────────────
def test_the_stored_10_18_drafts_carry_the_two_floors_the_issue_quotes():
    eng, cus = WIRE["drafts_2026_10_18"]["engine"], WIRE["drafts_2026_10_18"]["custom"]
    assert eng["source_action"] == "cron_generated" and eng["calendar_session_role"] == "upper_volume"
    assert cus["source_action"] == "draft_custom" and cus["calendar_session_role"] is None
    assert {e["rationale_tag"] for e in cus["exercises"] if e["movement_key"] in PROGRAM_KEYS} == {"custom"}
    assert eng["stored_floors"][BENCH] == {"floor_kg": BENCH_ENGINE_KG, "rpe_ceiling": 9, "ceiling_basis": "slot"}
    assert cus["stored_floors"][BENCH]["floor_kg"] == BENCH_CUSTOM_LIVE_KG and cus["stored_floors"][BENCH]["rpe_ceiling"] == 8
    assert cus["stored_floors"][BENCH]["ceiling_basis"].startswith("unknown intensity")


# ── 2. the engine draft, regenerated from the wire ───────────────────────────
def test_the_engine_draft_regenerated_from_the_wire_is_the_upper_volume_slot_at_83_91():
    ideal = _engine_ideal()
    assert ideal.inputs_snapshot["calendar"]["session_role"] == "upper_volume"
    bench = next(b for b in ideal.exercises if b.movement_key == BENCH)
    first_working = next(s for s in bench.sets if s.type != "warmup")  # #5049: the climb precedes it
    assert bench.rationale_tag == "anchor:bench:volume" and first_working.weight_kg == pytest.approx(BENCH_ENGINE_KG)


# ── 3 + 4. the stamped custom draft is gated on the engine's floors; off-program stays custom ──
def test_a_custom_draft_of_the_same_movements_inherits_the_slot_and_gets_the_engine_floors():
    ideal = _engine_ideal()
    off = [
        ExerciseBlock(movement_key="leg_press", sets=[Set(weight_kg=100.0, rep_range_start=8, rep_range_end=12)], rationale_tag="custom")
    ]
    ir = _custom_ir(extra=off)
    slot = draft_custom_session.stamp_program_slot(ir, block_workouts_reader=lambda _d: ROWS)

    assert slot["status"] == "inherited" and ir.inputs_snapshot["calendar"]["session_role"] == "upper_volume"
    engine_tags = {b.movement_key: b.rationale_tag for b in ideal.exercises}
    got_tags = {b.movement_key: b.rationale_tag for b in ir.exercises}
    assert {k: got_tags[k] for k in PROGRAM_KEYS} == {k: engine_tags[k] for k in PROGRAM_KEYS}
    # only movements the prescription lacks stay custom (the stretching template keeps its title tag)
    assert got_tags["cycling"] == "custom" and got_tags["leg_press"] == "custom" and got_tags["tmpl:527DA061"] == "Stretching"
    assert {m["movement_key"] for m in slot["movements"] if not m["inherited"]} == {"cycling", "tmpl:527DA061", "leg_press"}

    custom_floors, engine_floors = _gate_floors(ir), _gate_floors(ideal)
    for k in PROGRAM_KEYS:  # the SAME floors, back-off floors and rep caps as the engine draft, every program movement
        c, e = custom_floors[k], engine_floors[k]
        assert (c["floor_kg"], c.get("back_off_floor_kg"), _rep_cap(c).get("rpe_ceiling")) == (
            e["floor_kg"],
            e.get("back_off_floor_kg"),
            _rep_cap(e).get("rpe_ceiling"),
        ), k
    bench = custom_floors[BENCH]
    assert bench["floor_kg"] == pytest.approx(BENCH_ENGINE_KG)
    assert _rep_cap(bench)["rpe_ceiling"] == 9 and _rep_cap(bench)["ceiling_basis"] == "slot"
    # the off-program lift is still judged as custom: the lowest program ceiling, never loosened
    assert _rep_cap(custom_floors["leg_press"]).get("ceiling_basis", "").startswith("unknown intensity")


# ── 5. mutation control: without the stamp the gate reproduces the live defect ──
def test_mutation_control_without_the_stamp_the_gate_reads_the_live_79_38_at_rpe_8():
    """#5058 moved the lowest program ceiling from RPE 8 to the charter compounds ceiling (RPE 9), so the unstamped
    gate no longer reproduces the live 79.38 kg exactly: it reads the RPE-9 rep cap (81.65 kg, 180 lb) and still
    skips the hold — still under the engine's 83.91 kg, so the stamp is still what moves the floor."""
    bench = _gate_floors(_custom_ir())[BENCH]
    lowest = load_ramp.lowest_program_rpe_ceiling()
    assert lowest == 9 and _rep_cap(bench)["rpe_ceiling"] == lowest and _rep_cap(bench)["ceiling_basis"].startswith("unknown intensity")
    assert bench["floor_kg"] == pytest.approx(180 * 0.45359237) and BENCH_CUSTOM_LIVE_KG < bench["floor_kg"] < BENCH_ENGINE_KG


# ── 6. fail-soft ─────────────────────────────────────────────────────────────
def test_an_unreadable_record_or_a_non_program_date_leaves_every_block_custom_and_says_so():
    def boom(_d):
        raise RuntimeError("ddb down")

    ir = _custom_ir()
    slot = draft_custom_session.stamp_program_slot(ir, block_workouts_reader=boom)
    assert slot["status"] == "read_failed" and "RuntimeError" in slot["error"] and "calendar" not in ir.inputs_snapshot
    assert {b.rationale_tag for b in ir.exercises if b.movement_key in PROGRAM_KEYS} == {"custom"}
    assert any("read_failed" in line for line in ir.rationale)

    pre = _custom_ir()
    pre.target_date = "2026-09-01"  # before the block start: no program session
    assert draft_custom_session.stamp_program_slot(pre, block_workouts_reader=lambda _d: [])["status"] == "not_a_program_session"
    assert {b.rationale_tag for b in pre.exercises if b.movement_key in PROGRAM_KEYS} == {"custom"}


# ── 7. wiring: the draft_custom action runs the stamp and persists it ─────────
def test_the_draft_custom_action_persists_the_inherited_slot():
    from mcp import tools_hevy_routine

    persisted = {}
    exercises = [
        {"movement_key": e["movement_key"], "sets": e["sets"]}
        for e in WIRE["drafts_2026_10_18"]["custom"]["exercises"]
        if e["movement_key"] in PROGRAM_KEYS
    ]
    with (
        patch("training.routine_repo.draft_versioned", side_effect=lambda ir: persisted.setdefault("ir", ir)),
        patch("mcp.plan_hevy_windows._block_workouts", return_value=ROWS),
        patch("mcp.plan_cardio_pick.draft_cardio_warnings", return_value=[]),
        patch("training.routine_generator.attach_cardio_cues", return_value=0),
    ):
        resp = tools_hevy_routine._action_draft_custom(
            {"departure_reason": "test: deliberate departure from the engine draft", "exercises": exercises, "target_date": DAY}
        )
    assert resp["status"] == "drafted_custom" and resp["program_slot"]["status"] == "inherited"
    ir = persisted["ir"]
    assert ir.inputs_snapshot["calendar"]["session_role"] == "upper_volume"
    assert next(b for b in ir.exercises if b.movement_key == BENCH).rationale_tag == "anchor:bench:volume"
