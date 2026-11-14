"""tests/test_session_time_supersets_5799.py — #5799: measured lifting minutes, the re-derived set time, antagonist supersets.

Hevy's payload carries the workout's start and end only (no per-set timestamps), so a session's lifting minutes are its
length less the logged durations of its timed (cardio, stretching) blocks (`training.session_time.measure`). The per-set time
model is the median of his matched sessions once the charter's minimum is met, and the 45 s platform constant is retired.
Over the ceiling, the generator pairs the charter's antagonist accessories as one Hevy superset BEFORE the time trim cuts any
accessory (`session_shape.pair_supersets`); drop sets exist only as the owner-selected short-on-time variant. Offline.
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

from training import hevy_note_lint, hevy_render, program_structure, routine_title, session_block, session_shape, session_time
from training.hevy_compiler import to_create_body
from training.routine_ir import ExerciseBlock, RoutineSpec, Set
from training.training_charter import charter_value

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(_REPO, "config", "movement_catalog.json"), encoding="utf-8") as _f:
    MOVEMENTS = json.load(_f)["movements"]


def _workout(minutes: int, blocks: list[dict]) -> dict:
    return {
        "start_time": "2026-11-10T15:00:00Z",
        "end_time": f"2026-11-10T{15 + minutes // 60:02d}:{minutes % 60:02d}:00Z",
        "exercises": blocks,
    }


def _lift(n: int, kg: float = 40.0) -> dict:
    return {"title": "T", "sets": [{"weight_kg": kg, "reps": 8} for _ in range(n)]}


def _timed(minutes: int) -> dict:
    return {"title": "C", "sets": [{"duration_seconds": minutes * 60}]}


# ── the measurement ────────────────────────────────────────────────────────────────────────────────────────────────


def test_lifting_minutes_are_the_workout_less_its_timed_blocks_and_a_carry_stays_lifting():
    carry = {"title": "F", "sets": [{"weight_kg": 30.0, "duration_seconds": 60}]}
    m = session_time.measure(_workout(130, [_lift(10), _lift(10), carry, _timed(30), _timed(15)]))
    assert m["workout_minutes"] == 130.0 and m["timed_block_minutes"] == 45.0
    assert m["lifting_minutes"] == 85.0 and m["lifting_sets"] == 21
    assert m["ceiling_minutes"] == charter_value("split.session_minutes.lifting_ceiling") and m["over_ceiling"] is True
    assert "no per-set timestamps" in m["basis"]
    assert "estimate_minutes" not in m  # no routine known: no estimate is invented


def test_a_normalized_record_measures_the_same_and_a_lengthless_one_is_none():
    norm = {"duration_sec": 130 * 60, "exercises": [{"sets": [{"weight_kg": 40.0, "reps": 8}] * 20}, {"sets": [{"duration_sec": 2700}]}]}
    assert session_time.measure(norm)["lifting_minutes"] == 85.0
    assert session_time.measure({"exercises": [_lift(3)]}) is None


def test_a_matched_session_carries_the_estimate_its_role_and_its_set_time_sample():
    ir = RoutineSpec(
        routine_id="r",
        target_date="2026-11-10",
        archetype="lower",
        exercises=[ExerciseBlock("squat_barbell", sets=[Set(reps=5)] * 10, rest_seconds=120)],
        inputs_snapshot={"calendar": {"session_role": "lower_volume"}},
    )
    m = session_time.measure(_workout(70, [_lift(20)]), ir, MOVEMENTS)
    assert m["session_role"] == "lower_volume"
    assert m["estimate_minutes"] == session_shape.routine_minutes(ir.exercises, MOVEMENTS)["lifting_minutes"]
    assert m["implied_set_seconds"] == 70 * 60 / 20 - 120  # measured seconds per set less the routine's rest per set


def test_the_role_median_reads_only_that_roles_measured_sessions():
    def rec(role, minutes, sets=20):
        return {"adherence": {"session_time": {"session_role": role, "lifting_minutes": minutes, "lifting_sets": sets}}}

    recs = [rec("upper_volume", 80), rec("upper_volume", 90), rec("lower_volume", 60), rec("upper_volume", 0, sets=0), {}]
    assert session_time.role_median_minutes(recs, "upper_volume")["median_minutes"] == 85.0
    assert session_time.role_median_minutes(recs, "upper_volume")["n"] == 2
    assert session_time.role_median_minutes(recs, "shoulders_arms") is None


# ── the re-derived model ───────────────────────────────────────────────────────────────────────────────────────────


def test_the_set_time_is_re_derived_only_at_the_charter_minimum():
    need = int(charter_value("split.session_minutes.measured_min_sessions"))
    few = [(f"2026-10-{i + 1:02d}", 90.0) for i in range(need - 1)]
    assert session_time.derive_set_seconds(few)["status"] == "insufficient"
    rec = session_time.derive_set_seconds(few + [("2026-11-10", 120.0)])
    assert rec["set_seconds"] == 90 and rec["n"] == need and rec["as_of"] == "2026-11-10"


def test_the_model_is_the_measured_record_and_the_platform_constant_is_retired():
    rec = session_time.MEASURED_SET_SECONDS
    assert rec["n"] >= int(charter_value("split.session_minutes.measured_min_sessions"))
    assert rec["as_of"] and rec["source"] == "scripts/derive_session_time_model.py"
    model = session_shape.SESSION_TIME_MODEL
    assert model["provenance"] == "measured" and model["set_seconds"] == rec["set_seconds"]
    assert model["retired"]["set_seconds"] == 45 and model["set_seconds"] != 45
    assert "platform-proposed" not in json.dumps({k: v for k, v in model.items() if k != "retired"})


# ── supersets ─────────────────────────────────────────────────────────────────────────────────────────────────────


def _rx(role: str, **kw) -> dict:
    return program_structure.session_prescription_for_role(role, catalog_movements=MOVEMENTS, **kw)


def _pairs(rx: dict) -> list[tuple[str, str]]:
    ex = rx["exposures"]
    return [
        (a["movement_key"], b["movement_key"])
        for a, b in zip(ex, ex[1:])
        if a.get("superset_id") and a.get("superset_id") == b.get("superset_id")
    ]


def test_over_the_ceiling_the_accessories_are_paired_before_any_is_cut():
    rx = _rx("upper_heavy")
    assert rx["supersets"]["trigger"] == "estimate" and rx["supersets"]["estimate_before_min"] > rx["supersets"]["cap_minutes"]
    assert _pairs(rx) == [("db_lateral_raise", "reverse_pec_deck"), ("db_curl", "cable_tricep_pushdown")]
    assert not [e for e in rx["exposures"] if e["kind"] == "anchor" and e.get("superset_id") is not None]
    first = [e for e in rx["exposures"] if e.get("superset_id")][0::2]
    assert {e["rest_seconds"] for e in first} == {0}  # the pair rests once, after its second member
    assert rx["time_trim"] is None and rx["session_minutes"]["within_cap"]  # pairing alone fit it: nothing was cut


def test_without_the_pairs_the_same_session_loses_an_accessory():
    """The control: the charter's pairs removed, the same draft is cut by the trim."""
    real = charter_value

    def no_pairs(path, default=None):
        return [] if path == "split.supersets.pairs" else real(path, default)

    with patch.object(session_shape, "charter_value", no_pairs):
        rx = _rx("upper_heavy")
    assert rx["supersets"] is None and rx["time_trim"]["dropped_accessories"]


def test_under_the_ceiling_nothing_is_paired_unless_the_measured_median_is_over():
    assert _rx("shoulders_arms")["supersets"] is None
    measured = {"median_minutes": 83.0, "n": 3, "role": "shoulders_arms"}
    rx = _rx("shoulders_arms", measured_minutes=measured)
    assert rx["supersets"]["trigger"] == "measured_median"
    assert _pairs(rx) == [("db_lateral_raise", "face_pull"), ("db_curl", "cable_tricep_pushdown")]


def test_a_trim_that_cuts_one_member_leaves_its_partner_alone_with_its_rest_back():
    ex = [
        {"kind": "accessory", "movement_key": "db_curl", "sets": [{"reps": [10, 12]}] * 20, "rest_seconds": 90},
        {"kind": "accessory", "movement_key": "cable_tricep_pushdown", "sets": [{"reps": [10, 12]}] * 20, "rest_seconds": 90},
    ]
    session_shape.pair_supersets(ex)
    assert ex[0]["rest_seconds"] == 0 and ex[0]["superset_id"] == ex[1]["superset_id"]
    session_shape.trim_to_time(ex)
    assert [e["movement_key"] for e in ex] == ["db_curl"] and "superset_id" not in ex[0] and ex[0]["rest_seconds"] == 90


# ── drop sets: the owner's variant, never a default ──────────────────────────────────────────────────────────────


def test_drop_sets_appear_only_when_the_owner_selects_short_on_time():
    for role in program_structure.SESSION_TEMPLATES:
        rx = _rx(role)
        assert rx["short_on_time"] is None
        assert not [s for e in rx["exposures"] for s in e["sets"] if s.get("kind") == "drop"], role
    rx = _rx("upper_volume", short_on_time_variant=True)
    acc = [e for e in rx["exposures"] if e["kind"] == "accessory"]
    assert rx["short_on_time"] and all([s["kind"] for s in e["sets"]] == ["working", "drop"] for e in acc)
    assert all(e["sets"][0]["kind"] != "drop" for e in rx["exposures"] if e["kind"] == "anchor")


# ── the render proof (#5083 pattern): the superset reaches the Hevy wire, grouped, and the notes stay lint-clean ─


def _upper_heavy_ir() -> RoutineSpec:
    from test_program_session_4064_4147 import _done, _generate

    ir = next(
        r
        for r in (_generate("2026-10-10", block_workouts=_done(n))[0] for n in range(4))
        if r.inputs_snapshot["calendar"]["session_role"] == "upper_heavy"
    )
    return ir


def test_the_generated_superset_is_grouped_on_the_hevy_wire_and_lints_clean():
    ir = _upper_heavy_ir()
    session_block.place_on_first(ir)
    why = session_block.why_note_for(ir, routine_title.format_why_note(ir))
    body = to_create_body(ir, lambda k: "T-" + k, why_note=why)
    wire = body["routine"]["exercises"]
    ids = [ex["superset_id"] for ex in wire]
    grouped = {sid: [i for i, x in enumerate(ids) if x == sid] for sid in set(ids) - {None}}
    assert sorted(len(v) for v in grouped.values()) == [2, 2]
    assert all(v[1] == v[0] + 1 for v in grouped.values())  # each pair is adjacent: Hevy shows it as one group
    row = next(r for r in hevy_render.render_check(body, why, ir)["fields"] if r["field"] == "superset_id")
    assert row["status"] == "lands" and len(row["found"]) == 4, row  # four exercises, two supersets
    res = hevy_note_lint.lint_wire(body, ir)
    # offline (no history) a barbell/machine compound asks for a load (L4) — the 4064 golden's known class; nothing else
    assert [p for p in res.problems if p.rule != "L4"] == [], res.lines()


def test_the_warmup_rows_survive_the_pairing():
    """#5754's warm-up rules (the climb on a barbell compound) are untouched: only accessories are paired."""
    ir = _upper_heavy_ir()
    bench = ir.exercises[0]
    assert bench.superset_id is None and any(s.type == "warmup" for s in bench.sets)


# ── stored with the adherence record ────────────────────────────────────────────────────────────────────────────────


def test_the_adherence_record_stores_the_measured_minutes_beside_the_estimate(monkeypatch):
    from health import adherence_calc

    ir = RoutineSpec(
        routine_id="r1",
        target_date="2026-11-10",
        archetype="upper",
        exercises=[ExerciseBlock("db_curl", sets=[Set(reps=10)] * 3, rest_seconds=90)],
        inputs_snapshot={"calendar": {"session_role": "upper_volume"}},
    )
    monkeypatch.setattr(adherence_calc, "resolve_routine_for_workout", lambda performed: (ir, "hevy_routine_id", []))
    monkeypatch.setattr(adherence_calc, "_load_catalog", lambda: {"movements": MOVEMENTS})
    monkeypatch.setattr(adherence_calc, "calculate_adherence", lambda ir, performed: {"overall_pct": 100.0})
    st = adherence_calc.derive_adherence(_workout(100, [_lift(18), _timed(20)]))["session_time"]
    assert st["lifting_minutes"] == 80.0 and st["over_ceiling"] is True and st["session_role"] == "upper_volume"
    assert st["estimate_minutes"] == session_shape.routine_minutes(ir.exercises, MOVEMENTS)["lifting_minutes"]
    monkeypatch.setattr(adherence_calc, "resolve_routine_for_workout", lambda performed: (None, None, []))
    ad_hoc = adherence_calc.derive_adherence(_workout(50, [_lift(10)]))
    assert ad_hoc["status"] == "ad_hoc" and ad_hoc["session_time"]["lifting_minutes"] == 50.0
    assert "estimate_minutes" not in ad_hoc["session_time"]


def test_an_anchor_is_never_paired_even_on_a_pair_slot():
    sets = [{"reps": [10, 12]}] * 20
    ex = [
        {"kind": "anchor", "movement_key": "db_curl", "sets": sets, "rest_seconds": 90},
        {"kind": "accessory", "movement_key": "cable_tricep_pushdown", "sets": sets, "rest_seconds": 90},
    ]
    assert session_shape.pair_supersets(ex) is None and not [e for e in ex if "superset_id" in e]
