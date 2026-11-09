"""tests/test_hinge_programming_5694.py — the hinge days prescribe the lifts he does, loaded from each lift's OWN history.

#5694 (owner ruling 2026-11-08, attended, delegated): Lower-heavy's hinge is the conventional deadlift (Deadlift (Barbell),
C6272009) as the heavy pull; Lower-volume's is the Romanian deadlift (barbell, 2B4B7310) for 8–10 reps; the
conventional-deadlift trap-bar gate is retired. The defect it closes: the 11-06 predraft printed `W set: up to 8 easy reps,
find the load.` over unloaded RDL rows, because the owner had relabelled 19 RDL sessions to Deadlift (Barbell) on 11-01 and
the RDL template was left with no history (re-grade #6 on #5428).

THE WIRE (`tests/fixtures/hinge_programming_5694/wire_2026_11_08.json`, read-only from DynamoDB 2026-11-08, its
`_provenance` says how): the generator's own history index for the three lower barbell templates, his bodyweight index
around those days, and the block's Hevy rows. Measured there:
  * Deadlift (Barbell) C6272009 — 10 sessions 09-09 → 10-30 this cycle, 225 lb x 5–6 at RPE 8–8.5 for the last four;
  * Romanian Deadlift (Barbell) 2B4B7310 — one session, 11-06, 185 lb x 8 x 3 at RPE 8.

Offline: the history read is patched at the generator's one seam (`routine_generator._load_note_indexes`); no Hevy, no AI.
"""

from __future__ import annotations

import json
import pathlib
from unittest.mock import patch

import pytest
from training import exercise_history, hevy_compiler, hevy_note_lint, program_structure, routine_generator, session_block, session_sequence
from training.full_body_session import full_body_routines
from training.routine_title import format_why_note

REPO = pathlib.Path(__file__).resolve().parent.parent
WIRE = json.loads((REPO / "tests" / "fixtures" / "hinge_programming_5694" / "wire_2026_11_08.json").read_text())
CATALOG = json.loads((REPO / "config" / "movement_catalog.json").read_text())
TARGET = "2026-11-09"
LB = 2.20462
DEADLIFT, RDL = "C6272009", "2B4B7310"


@pytest.fixture(autouse=True)
def _frozen_clock():
    """#4848: the history cues read `pacific_today()` when no `today` is passed; pin it to the capture day so nothing here
    moves with the wall clock (patched on the importing module — the name is bound there at import)."""
    with patch.object(exercise_history, "pacific_today", return_value="2026-11-08"):
        yield


def _draft(role: str, history: dict | None = None):
    """The ideal routine the generator drafts for `role` on TARGET, over the wire (week/block from the real sequence)."""
    week_cfg = routine_generator.resolve_week_grid(routine_generator._load_json)
    entry = session_sequence.next_session(TARGET, WIRE["block_workouts"], [])
    assert entry and entry.get("source") == "session_sequence", entry
    entry = {**entry, "session_role": role, "archetype": "lower", "deload": False}
    inputs = routine_generator.GeneratorInputs(
        target_date=TARGET, z2_minutes_7d=None, deload_records=[], disruption_records=[], rotation_rows=[], days_since_last_workout=2
    )
    indexes = (WIRE["history"] if history is None else history, WIRE["weights"], {}, {})
    with patch.object(routine_generator, "_load_note_indexes", return_value=indexes):
        routines = full_body_routines(inputs, entry, week_cfg.week, {}, CATALOG, week_cfg, [], block_workouts=WIRE["block_workouts"])
    return next(r for r in routines if r.variant == "ideal")


def _working(block) -> list:
    return [s for s in block.sets if s.type == "normal"]


def _lb(kg) -> float | None:
    return None if kg is None else round(kg * LB)


def _wire_body(ideal) -> dict:
    session_block.place_on_first(ideal)
    resolver = lambda k: CATALOG["movements"][k]["hevy_template_id_hint"]  # noqa: E731 — pure: the catalog hint, no cache write
    return hevy_compiler.to_create_body(ideal, resolver, why_note=session_block.why_note_for(ideal, format_why_note(ideal)))


def test_the_wire_is_the_history_the_issue_measured():
    dl = WIRE["history"][DEADLIFT]
    this_cycle = [r for r in dl if r["date"] >= "2026-09-06"]
    assert len(this_cycle) == 10 and this_cycle[-1]["date"] == "2026-09-09" and this_cycle[0]["date"] == "2026-10-30"
    last = [(_lb(s["weight_kg"]), s["reps"], s["rpe"]) for s in this_cycle[0]["sets"] if s["rpe"] is not None]
    assert last == [(225, 6, 8.0), (225, 6, 8.5), (225, 6, 8.5)]
    (rdl,) = WIRE["history"][RDL]
    assert rdl["date"] == "2026-11-06"
    assert [(_lb(s["weight_kg"]), s["reps"], s["rpe"]) for s in rdl["sets"] if s["rpe"] is not None] == [(185, 8, 8.0)] * 3


def test_lower_heavy_pulls_the_conventional_deadlift_loaded_from_its_own_history():
    ideal = _draft("lower_heavy")
    keys = [b.movement_key for b in ideal.exercises]
    assert keys[:2] == ["squat_barbell", "deadlift_barbell"] and "romanian_deadlift_barbell" not in keys and "deadlift_trap_bar" not in keys
    dl = next(b for b in ideal.exercises if b.movement_key == "deadlift_barbell")
    work = _working(dl)
    # the heavy scheme: a top set and two back-offs at 4–6, every row loaded
    assert len(work) == 3 and all((s.rep_range_start, s.rep_range_end) == (4, 6) for s in work)
    assert all(s.weight_kg for s in work)
    floor = ideal.inputs_snapshot["load_floors"]["movements"]["deadlift_barbell"]
    assert floor["template_id"] == DEADLIFT  # its OWN template — never the trap bar's B923B230 or the RDL's
    # the top row moves off his last pull (225 x 6 at RPE 8 on 10-30): one 5-lb step, the back-offs −10 % on the bar's step
    assert _lb(work[0].weight_kg) == 230 and [_lb(s.weight_kg) for s in work[1:]] == [205, 205]
    assert "find the load" not in (dl.notes or "")


def test_lower_volume_pulls_the_rdl_for_8_to_10_loaded_from_its_one_session():
    ideal = _draft("lower_volume")
    assert ideal.exercises[0].movement_key == "romanian_deadlift_barbell"
    assert "deadlift_trap_bar" not in [b.movement_key for b in ideal.exercises]
    rdl = ideal.exercises[0]
    work = _working(rdl)
    assert len(work) == 3 and all((s.rep_range_start, s.rep_range_end) == (8, 10) for s in work)
    assert [_lb(s.weight_kg) for s in work] == [185, 185, 185]  # 11-06: 185 x 8 x 3 at RPE 8, held at the range floor
    assert ideal.inputs_snapshot["load_floors"]["movements"]["romanian_deadlift_barbell"]["template_id"] == RDL
    assert "find the load" not in (rdl.notes or "")


def test_mutation_control_without_its_own_history_the_rdl_has_no_load():
    """The 11-06 defect's shape: with no RDL history the rows carry no load — so the loads above are the RDL's own."""
    ideal = _draft("lower_volume", history={k: v for k, v in WIRE["history"].items() if k != RDL})
    rdl = ideal.exercises[0]
    assert rdl.movement_key == "romanian_deadlift_barbell" and not any(s.weight_kg for s in _working(rdl))


def test_both_hinge_days_lint_clean_on_the_wire_body():
    """Both drafts, compiled to the Hevy body the commit would send, every offender reported at once."""
    # the wire carries history for the three barbell lifts only, so an accessory with no history here opens on the
    # pick-load W line (a 5th phone line on the calf raise); the anchors — the session block, the squat and the hinge —
    # are what this file holds. The full-history dry run in the PR lints the whole routine clean.
    anchors = ("squat_barbell", "deadlift_barbell", "romanian_deadlift_barbell")
    offenders = []
    for role, hinge in (("lower_heavy", "deadlift_barbell"), ("lower_volume", "romanian_deadlift_barbell")):
        ideal = _draft(role)
        body = _wire_body(ideal)
        result = hevy_note_lint.lint_wire(body, ideal, catalog=CATALOG)
        offenders += [f"{role}: {p}" for p in result.problems if any(k in p.where for k in anchors)]
        # the compiler emits one wire exercise per IR block, in order (`hevy_compiler._primary_exercises`)
        ex = next(w for b, w in zip(hevy_compiler._primary_exercises(ideal), body["routine"]["exercises"]) if b.movement_key == hinge)
        if not all(s.get("weight_kg") for s in ex["sets"] if s.get("type") == "normal"):
            offenders.append(f"{role}: a working {hinge} row carries no load")
    assert not offenders, offenders


def test_the_pins_hold_on_the_real_block_record():
    """The block's own record: Lower-volume pulled the trap bar (10-13 … 11-03) and curled on 10-13 / 10-19; Lower-heavy
    pulled the RDL on 11-06. Neither in-block performance takes a pinned hinge slot (#4409 rule 1 reads pinned members only)."""
    movements = CATALOG["movements"]
    perf = program_structure.in_block_variant.performed_in_block(WIRE["block_workouts"], movements, TARGET)
    lv_keys = {p["movement_key"] for p in perf if p["role"] == "lower_volume"}
    assert {"deadlift_trap_bar", "leg_curl"} <= lv_keys
    for role, want in (("lower_heavy", "deadlift_barbell"), ("lower_volume", "romanian_deadlift_barbell")):
        rx = program_structure.session_prescription_for_role(role, catalog_movements=movements, in_block=perf)
        hinge = next(e for e in rx["exposures"] if e["pattern"] == "hinge")
        assert hinge["movement_key"] == want, (role, hinge)
