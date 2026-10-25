"""tests/test_warmup_sets_5049.py — the routine climbs to the working load (#5049).

THE DEFECT (owner, 2026-10-18; reproduced read-only from DynamoDB): both 10-18 upper routines —
the engine draft 2167c0e6… and the committed custom draft 014e1142… — open the bench press on
its first 185 lb (83.91 kg) working set. He added the warm-ups by hand in Hevy and re-ordered them.

What these tests hold (the wire is `tests/fixtures/draft_custom_slot_5005`, #5005's read-only
capture of that day, and `tests/fixtures/hevy_openapi_5010`, the 10-18 Hevy spec + the 10-15/16 rows):

  1. RE-DRAFTING 10-18's UPPER — the bench opens with three `warmup` sets at 50/70/85 % x 8/5/3
     of 185 lb (95/130/155 lb on the 5 lb step), then the SAME three working sets; the note names
     band pull-aparts; the exercise order and every working set are unchanged; the sub-floor
     dumbbell lifts and the vertical pull get none. Mutation control: with the warm-up pass
     removed the bench opens on its 185 lb working set — the live defect.
  2. THE WIRE — the compiled Hevy body carries `type: "warmup"` on exactly those sets, a value of
     the 10-18 spec's set-type enum.
  3. THE COMMIT GATE reads them as warm-ups: the re-drafted session is clean; retyped `normal` the
     same sets are below-floor refusals (mutation control).
  4. ADHERENCE + SELF-ADDED VOLUME — the #5008 working-set pair is unchanged by programmed
     warm-ups (10-18 bench: programmed working 3), and doing the programmed climb adds no volume;
     the 10-16 squat, hand-drafted WITH four warm-ups, is never stacked or rewritten.
  5. THE RULE TABLE — later compounds get one 70 % x 5 set; the 95 lb floor is inclusive; the
     table is owner-ruled 2026-10-23 (ADR-105).
  6. THE CEILINGS AND THE CUT count working sets: the green-block check and stage 2's total-sets
     trim never count or pop a warm-up.
  7. THE CHAT PATH — draft_custom's bench gets the same climb; `warmups=false` opts out.

Clock: every path runs on the fixed 2026-10-18 target date and captured rows (#4848).
"""

# premerge-gate: #5049 reads config/movement_catalog.json + the config week grid through the generator's _load_json
from __future__ import annotations

import copy
import json
import os
import pathlib
import sys
from datetime import date
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import hevy_compiler, routine_generator, self_added_volume, warmup_sets  # noqa: E402
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402


@pytest.fixture(autouse=True)
def _pre_rotation_record():
    """#5075: the wire is the 2026-10-18 record, drafted before accessory slots rotated — the rotation is held off (no
    program position) so the re-draft serves the template that record was drafted from."""
    with patch("training.variant_rotation.position", return_value=None):
        yield


DAY = "2026-10-18"
WIRE = json.loads((REPO / "tests" / "fixtures" / "draft_custom_slot_5005" / "wire_2026_10_18.json").read_text())
ROWS = WIRE["hevy_rows"]
WEIGHTS = {k: float(v) for k, v in WIRE["bodyweights_lb"].items()}
SPEC = json.loads((REPO / "tests" / "fixtures" / "hevy_openapi_5010" / "hevy_openapi_2026-10-18.json").read_text())
ROWS_1015_16 = json.loads((REPO / "tests" / "fixtures" / "hevy_openapi_5010" / "hevy_rows_2026-10-15_16.json").read_text())
MOVEMENTS = json.loads((REPO / "config" / "movement_catalog.json").read_text())["movements"]
LB = 0.45359237
BENCH = "barbell_bench_press"
BENCH_KG = 83.91458845000001  # 185 lb, the 10-18 bench working load
SQUAT_TID = "D04AC939"


def _lb(kg):
    return round(kg / LB, 1)


def _history():
    import datetime

    from training import exercise_history

    class _Table:
        def query(self, **_kw):
            return {"Items": ROWS}

    with patch.object(exercise_history, "_table", return_value=_Table()):
        return exercise_history.load_history_indexes(lookback_days=30, today=datetime.date(2026, 10, 18))[0]


def _redraft(no_warmups: bool = False):
    """Re-draft the 2026-10-18 upper session from the wire (the engine path), on upper-volume's template as it was served
    that day — with the press, before #5162 traded it (`served_templates_5162`)."""
    from served_templates_5162 import pre_5162_upper_days

    with pre_5162_upper_days(), patch.object(routine_generator, "_load_note_indexes", return_value=(_history(), WEIGHTS, {}, {})):
        if no_warmups:
            with patch.object(warmup_sets, "attach_warmups", side_effect=lambda b, c: {"warmup_sets": 0, "movements": []}):
                return routine_generator.generate_routines(routine_generator.GeneratorInputs(target_date=DAY, block_workouts=ROWS))[0]
        return routine_generator.generate_routines(routine_generator.GeneratorInputs(target_date=DAY, block_workouts=ROWS))[0]


def _block(ir, key):
    return next(b for b in ir.exercises if b.movement_key == key)


def _working(sets):
    return [s for s in sets if s.type != "warmup"]


# ── 1. re-drafting 10-18's upper ─────────────────────────────────────────────
def test_the_redrafted_10_18_bench_climbs_50_70_85_then_its_unchanged_working_sets():
    ideal = _redraft()
    bench = _block(ideal, BENCH)
    warm = bench.sets[:3]
    assert [s.type for s in warm] == ["warmup"] * 3
    assert [(_lb(s.weight_kg), s.reps) for s in warm] == [(95.0, 8), (130.0, 5), (155.0, 3)]
    assert [s.type for s in bench.sets[3:]] == ["normal"] * 3
    assert all(s.weight_kg == pytest.approx(BENCH_KG) for s in bench.sets[3:])
    assert "band pull-aparts" in bench.notes and bench.notes.count(warmup_sets.CUE_MARKER) == 1
    row = next(r for r in ideal.inputs_snapshot["warmups"]["movements"] if r["movement_key"] == BENCH)
    assert row["status"] == "warmed" and row["position"] == "first"


def test_working_sets_loads_and_the_exercise_order_are_byte_identical_to_the_pass_removed():
    """Mutation control included: without the warm-up pass the bench OPENS on 185 lb — the live defect."""
    with_w, without = _redraft(), _redraft(no_warmups=True)
    assert [b.movement_key for b in with_w.exercises] == [b.movement_key for b in without.exercises]
    for a, b in zip(with_w.exercises, without.exercises):
        assert _working(a.sets) == b.sets, a.movement_key
    first = _block(without, BENCH).sets[0]
    assert first.type == "normal" and first.weight_kg == pytest.approx(BENCH_KG)


def test_sub_floor_dumbbell_lifts_and_the_vertical_pull_get_no_warmups():
    ideal = _redraft()
    rows = {r["movement_key"]: r for r in ideal.inputs_snapshot["warmups"]["movements"]}
    assert rows["one_arm_db_row"]["status"] == "below_floor"  # 85 lb dumbbell
    assert rows["db_shoulder_press"]["status"] == "below_floor"  # 70 lb dumbbell
    assert "lat_pulldown" not in rows  # vertical pull is not in the compound families
    for key in ("one_arm_db_row", "db_shoulder_press", "lat_pulldown", "cable_chest_fly"):
        assert not any(s.type == "warmup" for s in _block(ideal, key).sets)
        assert warmup_sets.CUE_MARKER not in (_block(ideal, key).notes or "")
    assert ideal.inputs_snapshot["warmups"]["warmup_sets"] == 3


# ── 2. the wire ──────────────────────────────────────────────────────────────
def test_the_compiled_hevy_body_types_the_climb_warmup_from_the_specs_enum():
    ideal = _redraft()
    body = hevy_compiler.to_create_body(ideal, template_resolver=lambda k: "T-" + k)
    wire_bench = next(e for e in body["routine"]["exercises"] if e["exercise_" "template_id"] == "T-" + BENCH)
    assert [s["type"] for s in wire_bench["sets"]] == ["warmup"] * 3 + ["normal"] * 3
    assert [s["reps"] for s in wire_bench["sets"][:3]] == [8, 5, 3]
    enum = SPEC["components"]["schemas"]["PostRoutinesRequestSet"]["properties"]["type"]["enum"]
    assert "warmup" in enum


# ── 3. the commit gate ───────────────────────────────────────────────────────
def test_the_commit_gate_reads_programmed_warmups_as_warmups():
    from mcp.hevy_prescription_gate import prescription_gate

    ideal = _redraft()
    assert prescription_gate(ideal)["verdict"] == "clean"  # the generator's own load_floors audit is reused
    retyped = copy.deepcopy(ideal)
    for s in _block(retyped, BENCH).sets:
        s.type = "normal"  # mutation control: the same loads typed as working sets are under the floor
    gate = prescription_gate(retyped)
    assert gate["verdict"] == "refuse"
    hits = [v for v in gate["audit"]["violations"] if v["kind"] == "below_floor"]
    assert {v["where"] for v in hits} == {BENCH} and {v["set"] for v in hits} == {1, 2, 3}


# ── 4. adherence + self-added volume ─────────────────────────────────────────
def _performed_from(day, tid):
    row = next(r for r in ROWS_1015_16 if r["date"] == day)
    ex = next(e for e in row["exercises"] if (e.get("exercise_" "template_id") or e.get("template_id")) == tid)
    return {"exercises": [{"exercise_" "template_id": tid, "sets": [{"type": s["type"]} for s in ex["sets"]]}]}


def test_adherence_keeps_programmed_working_sets_at_3_for_the_warmed_10_18_bench():
    from health.adherence_calc import calculate_adherence

    ideal = _redraft()
    bench_only = RoutineSpec(routine_id="r5049", target_date=DAY, archetype="upper", exercises=[_block(ideal, BENCH)])
    performed = {"exercises": [{"exercise_" "template_id": "79D0BB3A", "sets": [{"type": "warmup"}] * 3 + [{"type": "normal"}] * 3}]}
    (m,) = calculate_adherence(bench_only, performed)["movements"]
    assert (m["programmed_working_sets"], m["performed_working_sets"]) == (3, 3)
    bucket = {"programmed_sets": 0, "performed_sets": 0, "added_sets": 0, "added": []}
    self_added_volume._movement_adds({"movements": [m]}, {}, date(2026, 10, 18), bucket)
    assert bucket["added_sets"] == 0  # doing the programmed climb is not added volume
    # mutation control: the same climb typed `normal` would read as 6 programmed working sets
    retyped = copy.deepcopy(bench_only)
    for s in retyped.exercises[0].sets:
        s.type = "normal"
    (m2,) = calculate_adherence(retyped, performed)["movements"]
    assert m2["programmed_working_sets"] == 6


def _squat_1016():
    """The 10-16 squat as stored (1b98159c…, hand-drafted): 45/135/185/215 warm-ups, then 235 / 210.5 / 210.5."""
    kg = [20.41168, 61.23504, 83.91469, 97.52236]
    sets = [Set(type="warmup", weight_kg=w, reps=r) for w, r in zip(kg, (10, 5, 3, 2))]
    sets += [Set(weight_kg=w, rep_range_start=4, rep_range_end=6) for w in (106.59420695, 95.5, 95.5)]
    return ExerciseBlock(movement_key=f"tmpl:{SQUAT_TID}", sets=sets)


def test_the_10_16_squat_with_authored_warmups_is_never_stacked_and_its_pair_stays_3():
    from health.adherence_calc import calculate_adherence

    block = _squat_1016()
    before = copy.deepcopy(block.sets)
    audit = warmup_sets.attach_warmups([block], MOVEMENTS)
    assert block.sets == before and audit["movements"][0]["status"] == "authored"
    assert warmup_sets.compound_family(f"tmpl:{SQUAT_TID}", MOVEMENTS) == "squat"
    ir = RoutineSpec(routine_id="r5049s", target_date="2026-10-16", archetype="lower", exercises=[block])
    (m,) = calculate_adherence(ir, _performed_from("2026-10-16", SQUAT_TID))["movements"]
    assert (m["programmed_working_sets"], m["performed_working_sets"]) == (3, 5)  # #5008's pair, unchanged


# ── 5. the rule table ────────────────────────────────────────────────────────
def _loaded(key, lb, n=3):
    return ExerciseBlock(movement_key=key, sets=[Set(weight_kg=lb * LB, rep_range_start=5, rep_range_end=8) for _ in range(n)])


def test_a_later_compound_gets_one_set_at_70_percent_x_5():
    bench, squat = _loaded(BENCH, 185), _loaded("squat_barbell", 225)
    warmup_sets.attach_warmups([bench, squat], MOVEMENTS)
    assert len([s for s in bench.sets if s.type == "warmup"]) == 3
    warm = [s for s in squat.sets if s.type == "warmup"]
    assert [(_lb(s.weight_kg), s.reps) for s in warm] == [(160.0, 5)]  # 157.5 -> nearest 5 lb, half up
    assert "ankle/hip mobility" in squat.notes


def test_the_floor_is_inclusive_at_95_lb_and_a_block_below_it_gets_nothing():
    at, under = _loaded(BENCH, 95), _loaded(BENCH, 90)
    warmup_sets.attach_warmups([under], MOVEMENTS)
    assert not any(s.type == "warmup" for s in under.sets) and not under.notes
    warmup_sets.attach_warmups([at], MOVEMENTS)
    assert [s.type for s in at.sets[:2]] == ["warmup", "warmup"]  # 50 % and 70 %; 85 % of 95 rounds onto 80 — kept
    assert all(s.weight_kg < 95 * LB for s in at.sets if s.type == "warmup")


def test_the_cue_table_names_one_movement_per_family_and_none_otherwise():
    assert warmup_sets.cue_clause("bench").endswith("band pull-aparts, then the ramp sets.")
    assert "hip hinges" in warmup_sets.cue_clause("hinge")
    assert "ankle/hip mobility" in warmup_sets.cue_clause("squat")
    assert warmup_sets.cue_clause("row") == "" and warmup_sets.cue_clause("overhead_press") == ""
    row = _loaded("machine_row", 200)
    warmup_sets.attach_warmups([row], MOVEMENTS)
    assert any(s.type == "warmup" for s in row.sets) and not row.notes


def test_the_numbers_are_owner_ruled_per_adr_105():
    assert warmup_sets.WARMUP_PRESCRIPTION["provenance"] == "owner-ruled"
    assert "#5049" in warmup_sets.WARMUP_PRESCRIPTION["provenance_detail"]
    assert warmup_sets.WARMUP_PRESCRIPTION["first_compound"] == ((0.50, 8), (0.70, 5), (0.85, 3))
    assert warmup_sets.WARMUP_PRESCRIPTION["later_compound"] == ((0.70, 5),) and warmup_sets.WARMUP_PRESCRIPTION["floor_lb"] == 95.0


def test_rerunning_the_pass_never_stacks():
    bench = _loaded(BENCH, 185)
    warmup_sets.attach_warmups([bench], MOVEMENTS)
    once = copy.deepcopy(bench)
    warmup_sets.attach_warmups([bench], MOVEMENTS)
    assert bench == once


# ── 6. ceilings and the stage-2 cut count working sets ───────────────────────
def test_the_green_block_ceiling_counts_working_sets_only():
    from training import green_block

    blocks = [_loaded(BENCH, 185, n=10), _loaded("squat_barbell", 225, n=10)]
    assert green_block.session_set_check(blocks, "upper") == []
    warmup_sets.attach_warmups(blocks, MOVEMENTS)  # +4 warm-up sets: 24 sets on the list, 20 hard
    assert green_block.session_set_check(blocks, "upper") == []
    blocks[0].sets.append(Set(weight_kg=185 * LB))  # control: one more WORKING set breaches 20
    assert green_block.session_set_check(blocks, "upper")


def test_the_stage_2_total_sets_cut_never_pops_a_warmup():
    from coach import critics, critics_apply

    ideal = _redraft()
    draft = critics.draft_summary(ideal)
    assert draft["total_sets"] == sum(len(_working(b.sets)) for b in ideal.exercises)
    target = draft["total_sets"] - 6
    ok, why = critics_apply._apply_one(ideal, critics_apply.CHANGE_FIELD_RE.match("session.total_sets"), target)
    assert ok, why
    bench = _block(ideal, BENCH)
    assert [s.type for s in bench.sets[:3]] == ["warmup"] * 3 and len(_working(bench.sets)) >= 1
    assert sum(len(_working(b.sets)) for b in ideal.exercises) == target


# ── 7. the chat path ─────────────────────────────────────────────────────────
def _custom_ir():
    blocks = [
        ExerciseBlock(movement_key=ex["movement_key"], sets=[Set(**s) for s in ex["sets"]], rationale_tag=ex["rationale_tag"])
        for ex in WIRE["drafts_2026_10_18"]["custom"]["exercises"]
    ]
    return RoutineSpec(routine_id="r5049c", target_date=DAY, archetype="upper", exercises=blocks, inputs_snapshot={}, rationale=[])


def test_draft_custom_gives_the_committed_10_18_bench_the_same_climb_and_opts_out_on_false():
    from mcp.draft_custom_session import attach_draft_warmups as _attach_draft_warmups

    ir = _custom_ir()
    audit = _attach_draft_warmups(ir, MOVEMENTS, {})
    bench = _block(ir, BENCH)
    assert [(_lb(s.weight_kg), s.reps, s.type) for s in bench.sets[:3]] == [(95.0, 8, "warmup"), (130.0, 5, "warmup"), (155.0, 3, "warmup")]
    assert audit["warmup_sets"] == 3 and ir.inputs_snapshot["warmups"] is audit
    off = _custom_ir()
    assert _attach_draft_warmups(off, MOVEMENTS, {"warmups": False}) is None
    assert not any(s.type == "warmup" for b in off.exercises for s in b.sets)
    assert off.inputs_snapshot["warmups"] == {"status": "opted_out"}
