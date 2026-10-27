"""tests/test_hevy_notes_followups_5428.py — the Hevy note standard on every path, and the rotation shown (#5428, #5083).

What lanes A-C deferred, each held here with a mutation control that reds it:

  1. ROTATION IN THE NOTE (#5083 box 1/3, #5075). The engine's accessory rotation (`rotated: Face Pull → DB Rear Delt
     Rows, week 4 of block 1 …` in the rationale) reaches the swapped-in exercise's Hevy note as ONE reason line,
     `New: replaces Face Pull.` — no slot id, no week arithmetic, no issue number. Driven through the REAL generator on
     the 10-26 UPPER-VOLUME position (block 1, week 5: the four rotations that day's routine carried), and the render
     check finds it (`rotation_note` lands) or reports it `missing` when the wire loses it (the fallback test).
  2. THE COMPOSER ON EVERY PATH. The chat path (`draft_custom`) runs `lift_note.compose_blocks` (the 10-25
     SHOULDERS + ARMS chat routine's own exercises and notes; the 10-26 lat-pulldown rep step); the minimum / travel
     routine carries the three-line session block and standard lift notes; stage 2 re-stamps the cardio `After:` line on
     the final order.
  3. NO INTERNAL IDS ON THE WIRE from the fitness-test, minimum-session and reverted-plan producers.
  4. The note extractor's form keywords match whole words: his "4.0 / 3 from 20" is not a form note.

Fixtures: the routines' own exercises, published loads (ruled public) and the coach's own note text. No bodyweight,
nutrition or clinical value. No clock is read: every date is passed in.
"""

from __future__ import annotations

import ast
import os
import pathlib
import re
import sys
from contextlib import ExitStack
from unittest.mock import patch

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from training import (  # noqa: E402
    disruption,
    fitness_tests,
    hevy_render,
    session_block,
    training_notes,
    variant_rotation as vr,  # noqa: E402
)
from training.hevy_compiler import to_create_body  # noqa: E402
from training.routine_generator import _load_json  # noqa: E402
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402
from training.routine_title import format_why_note  # noqa: E402

LB = 0.45359237
CATALOG = _load_json("movement_catalog.json")

# HEVY_NOTE_STANDARD §5 (linter L1) — what no path may put on the wire: issue numbers, version ids, engine and
# load-model words, restated rows, kg, non-RPE effort, tier / verdict / medical / bookkeeping text, slot ids.
BANNED = re.compile(
    r"#\d|\bv\d+\.\d|§|critic|red team|charter|\bengine\b|platform|tripwire|\bfloor \d|\bfloor:|load floor|\bramp\b|e1RM|\banchor\b|\bband\b(?! pull-aparts)|"
    r"\bkg\b|\dkg|Last:|\bsets? of\b|\bRIR\b|in the tank|never up|subtract-only|ECG|[Ss]inus|cardiolog|metoprolol|Optional if|"
    r"protein|🟢|🟡|🔴|\bGREEN\b|\bRED\b|APPROVE|applied:|\w+\.\w+_\w+|\bweek \d+ of block|computed\]|…",
)


def banned_hits(notes: list[str]) -> list[str]:
    return [m.group(0) for n in notes for m in [BANNED.search(n or "")] if m]


def _wire_notes(ir: RoutineSpec) -> list[str]:
    why = session_block.why_note_for(ir, format_why_note(ir))
    return [e["notes"] for e in to_create_body(ir, lambda k: "T-" + k, why_note=why)["routine"]["exercises"]]


def test_the_banned_scan_fails_the_archived_originals():
    """Mutation control for the scan itself: the producers' pre-#5428 copy, verbatim, all fail it."""
    originals = [
        "Minimum: top set 4-6 @ RPE 8-9, then one back-off at -10% — keeps the habit on a short day (#5088).",
        "RPE 8–9 Today: 2 working set(s) only, the tests are the session (#5078).",
        "v0.4 revert: 72 % of e1RM (v0.4 ramp week 3); heavy 4-6 reps.",
        "rotated: Face Pull → DB Rear Delt Rows, week 4 of block 1 (serves weeks 4–6; this is week 5) [upper_volume.face_pull, computed]",
        "3 sets of 8-15 @ RPE 8-9; last set RPE 9-10. Last: 15 lb x 15/15/15 (4 Oct).",
    ]
    assert all(banned_hits([o]) for o in originals), [o for o in originals if not banned_hits([o])]


# ── 1. the rotation, through the real generator at the 10-26 position ─────────────────────────────────────────────
def _generate_10_26(rows=None):
    """The real generator on 2026-10-26 with 26 performed program sessions: block 1, week 5, UPPER-VOLUME — the session
    whose four accessory slots rotated that day (the rationale lines the published routine carried)."""
    from test_variant_rotation_5075 import _done, _generate

    return _generate("2026-10-26", _done(26), rotation_rows=[] if rows is None else rows)[0]


ROTATED_10_26 = {
    "db_rear_delt_rows": "Face Pull",
    "chest_fly_machine": "Cable Fly Crossovers",
    "lying_db_tricep_extension": "Triceps Pushdown",
    "preacher_curl_machine": "Bicep Curl (Dumbbell)",
}


def test_each_rotated_accessory_names_the_exercise_it_replaces():
    ideal = _generate_10_26()
    cal = ideal.inputs_snapshot["calendar"]
    assert (cal["session_role"], cal["week"], cal["block"]) == ("upper_volume", 5, 1)
    # the engine's own record of the four swaps is the source (rationale), and it keeps its slot ids there
    assert sum(1 for ln in ideal.rationale if ln.startswith("rotated:") and "[upper_volume." in ln) == 4
    notes = {b.movement_key: b.notes for b in ideal.exercises}
    for key, replaced in ROTATED_10_26.items():
        lines = notes[key].split("\n")
        assert lines[0].startswith("RPE ") and lines[1] == f"New: replaces {replaced}.", (key, notes[key])
        assert sum(1 for ln in lines if ln.startswith("New: ")) == 1
    # the anchors are fixed per block: no rotation line on them
    assert not [k for k, n in notes.items() if k not in ROTATED_10_26 and "New: replaces" in n]
    assert banned_hits(list(notes.values())) == []
    rec = ideal.inputs_snapshot["lift_notes"]["chest_fly_machine"]
    assert rec["reason"] == "rotation" and rec["reason_line"] == "New: replaces Cable Fly Crossovers."


def test_before_and_after_the_10_26_chest_fly():
    """The published 10-26 Chest Fly (Machine) note (bodyweights scrubbed) against today's render of the same slot."""
    before = (
        "hold: 100 lb on 11-30 has a set with no RPE logged — not evidence it sat under the ceiling. Last: 45.5kg 10/10/10/10 "
        "(Nov 2024) ACCESSORY: 2 sets of 8–15 @ RPE 8–9; last set RPE 9–10 (charter ceilings). Week 5 load 60 lb — 80% of "
        "your band anchor after the 10% detraining discount (v0.3 §3). Down on the day if you must, never up.\n"
        "Optional if the ECG is not sinus."
    )
    fly = next(b for b in _generate_10_26().exercises if b.movement_key == "chest_fly_machine")
    assert fly.notes == "RPE 8–9, last set RPE 9–10\nNew: replaces Cable Fly Crossovers.\nW set: up to 8 easy reps, find the load."
    assert banned_hits([before]) and not banned_hits([fly.notes])


def test_no_rotation_line_when_the_slot_did_not_rotate():
    """Mutation controls: block 1's first phase serves the template (step 0), a REFUSED rotation serves the template,
    and a held variant (the ledger holds what the previous phase served) is no swap — none of them writes the line."""
    from test_variant_rotation_5075 import _done, _generate

    first_phase = _generate("2026-10-13", _done(10), rotation_rows=[])[0]
    assert vr.position(first_phase.inputs_snapshot["calendar"])["step"] == 0
    assert not [b.notes for b in first_phase.exercises if "New: replaces" in (b.notes or "")]
    rot = _generate_10_26().inputs_snapshot["rotation"]
    assert set(vr.swaps(rot, CATALOG["movements"])) == set(ROTATED_10_26)
    assert vr.swaps({**rot, "variants": {}}, CATALOG["movements"]) == {}  # refused: the template serves
    held = {**rot, "slots": [{**s, "previous": s["variant"]} for s in rot["slots"]]}
    assert vr.swaps(held, CATALOG["movements"]) == {}
    pinned = {**rot, "slots": [{**s, "source": "pinned"} for s in rot["slots"]]}
    assert vr.swaps(pinned, CATALOG["movements"]) == {}


def test_the_rotation_note_lands_in_the_render_check_and_is_missing_when_the_wire_drops_it():
    """#5083 box 3: the rotation has no Hevy field, so it rides the note (the documented fallback) — `render_check`
    finds it there, and an IR that records the swap but a wire that lost it reads `missing`, never `absent`."""
    ideal = _generate_10_26()
    why = session_block.why_note_for(ideal, format_why_note(ideal))
    body = to_create_body(ideal, lambda k: "T-" + k, why_note=why)
    rc = hevy_render.render_check(body, session_note=why, ir=ideal)
    status = {r["field"]: r["status"] for r in rc["fields"]}
    assert status["rotation_note"] == "lands", rc["fields"]
    assert {e["movement_key"] for e in rc["expected_reasons"] if e["field"] == "rotation_note"} == set(ROTATED_10_26)
    assert not [p for p in rc["problems"] if p.startswith("rotation_note")]
    row = next(r for r in hevy_render.RENDER_TABLE if r["field"] == "rotation_note")
    assert row["home"] == hevy_render.NOTE and "deferred" not in row["producer"]
    # mutation: strip the line from one wire note
    for ex in body["routine"]["exercises"]:
        ex["notes"] = "\n".join(ln for ln in ex["notes"].split("\n") if not ln.startswith("New: replaces Face Pull"))
    rc = hevy_render.render_check(body, session_note=why, ir=ideal)
    assert {r["field"]: r["status"] for r in rc["fields"]}["rotation_note"] == "missing"
    assert any(p.startswith("rotation_note: expected on the wire for db_rear_delt_rows") for p in rc["problems"]), rc["problems"]


# ── 2a. the chat path runs the composer (the 10-25 SHOULDERS + ARMS chat routine) ─────────────────────────────────
CHAT_10_25 = [
    {
        "movement_key": "db_shoulder_press",
        "sets": [{"weight_lbs": 75, "rep_range_start": 6, "rep_range_end": 10}],
        "notes": "Option B: DB laterals x3 for delt priority; press at 75 lb chasing 8.\n\n"
        "1 set of 6-10 @ RPE 8-9. 75 lb, aim for 8. Exhale through the press.",
    },
    {
        "movement_key": "db_lateral_raise",
        "sets": [{"weight_lbs": 15, "rep_range_start": 8, "rep_range_end": 15, "count": 3}],
        "notes": "3 sets of 8-15 @ RPE 8-9; last set RPE 9-10. Last: 15 lb x 15/15/15 (4 Oct).",
    },
    {
        "movement_key": "reverse_pec_deck",
        "sets": [{"rep_range_start": 8, "rep_range_end": 15, "count": 3}],
        "notes": "3 sets of 8-15 @ RPE 8-9; last set RPE 9-10. No load on file: pick it, log it.",
    },
    {
        "movement_key": "seated_incline_curl_dumbbell",
        "sets": [{"weight_lbs": 20, "rep_range_start": 8, "rep_range_end": 15, "count": 2}],
        "notes": "2 sets of 8-15 @ RPE 8-9; last set RPE 9-10.",
    },
    {
        "movement_key": "triceps_rope_pushdown",
        "sets": [{"weight_lbs": 40, "rep_range_start": 8, "rep_range_end": 15, "count": 2}],
        "notes": "2 sets of 8-15 @ RPE 8-9; last set RPE 9-10.",
    },
]


def _sess(date, lb, reps, rpe=None, n=1):
    return {"date": date, "top_weight_kg": lb * LB, "sets": [{"weight_kg": lb * LB, "reps": reps, "rpe": rpe}] * n}


# his PREVIOUS on the templates the catalog names (the loads the 10-25 notes quote)
CHAT_HISTORY = {
    "422B08F1": [_sess("2026-10-04", 15, 15, n=3)],  # lateral raise, 15 x 15/15/15 on 10-04
    "8BAB2735": [_sess("2026-10-18", 20, 12, 8.5, n=2)],  # seated incline curl
    "94B7239B": [_sess("2026-10-18", 40, 12, 8.5, n=2)],  # rope pushdown
    "6A6C31A5": [_sess("2026-10-21", 160, 8, 8, n=2), _sess("2026-10-18", 160, 8, 8, n=2), _sess("2026-10-11", 160, 8, 8, n=2)],
}


def _slot(role):
    """The program slot the chat draft inherits (`draft_custom_session.inherit_program_session`), offline: the 10-25 chat
    routine was the shoulders + arms slot, the 10-26 one the upper-volume slot (their rationale lines)."""
    return {"status": "inherited", "calendar": {"session_role": role, "position_label": "fixture"}, "movements": [], "rule": "fixture"}


def _draft_custom(exercises, target_date="2026-10-25", archetype="upper", composer=None, role="shoulders_arms"):
    from mcp import tools_hevy_routine as t

    captured = {}
    with ExitStack() as st:
        st.enter_context(patch("training.routine_repo.draft_versioned", side_effect=lambda ir: captured.setdefault("ir", ir)))
        st.enter_context(patch("mcp.draft_custom_session._history_index", return_value=CHAT_HISTORY))
        st.enter_context(patch("mcp.draft_custom_session.inherit_program_session", return_value=_slot(role)))
        if composer is not None:
            st.enter_context(patch("mcp.draft_custom_session.compose_custom_notes", side_effect=composer))
        out = t.tool_manage_hevy_routine(
            {
                "action": "draft_custom",
                "target_date": target_date,
                "archetype": archetype,
                "departure_reason": "fixture: the routine as the chat drafted it",
                "exercises": exercises,
            }
        )
    assert out.get("status") == "drafted_custom", out
    return captured["ir"], out


def test_the_chat_draft_notes_are_composed_to_the_standard():
    ir, out = _draft_custom(CHAT_10_25)
    notes = {b.movement_key: b.notes for b in ir.exercises}
    lift = {k: n.split("\n\n")[-1] for k, n in notes.items()}  # exercise 1's own note, under the session block
    assert lift == {
        # no PREVIOUS on file for the press template: the author's load stands, his coach's own cue is kept as the cue
        "db_shoulder_press": "RPE 8–9\nExhale through the press.",
        # PREVIOUS 15 x 15 on 10-04 is within one step of the row: no reason, nothing the rows show
        "db_lateral_raise": "RPE 8–9, last set RPE 9–10",
        # no load authored, none on file: the pick-load form (one no-load W row of 8)
        "reverse_pec_deck": "RPE 8–9, last set RPE 9–10\nW set: up to 8 easy reps, find the load.",
        "seated_incline_curl_dumbbell": "RPE 8–9, last set RPE 9–10",
        "triceps_rope_pushdown": "RPE 8–9, last set RPE 9–10",
    }
    head = notes["db_shoulder_press"].split("\n")[:2]  # exercise 1 opens with the one session block (lane A)
    assert head == ["Shoulders + arms · RPE 8–9 on big lifts", session_block.LOW_ENERGY_LINE], head
    assert banned_hits(_wire_notes(ir)) == []
    # the authored text is not lost: it is on the stored record, and the response says each rewrite
    assert ir.inputs_snapshot["lift_notes"]["db_lateral_raise"]["detail"].startswith("3 sets of 8-15")
    assert {r["movement_key"] for r in ir.inputs_snapshot["lift_notes_replaced"]} == set(lift)
    assert sum(1 for w in out["warnings"] if w.startswith("Rewrote your ")) == len(lift)


def test_before_and_after_a_chat_path_note():
    """The 10-25 chat-drafted lateral raise: the note as published, and as the chat path writes it now."""
    ir, _ = _draft_custom(CHAT_10_25)
    raise_ = next(b for b in ir.exercises if b.movement_key == "db_lateral_raise")
    before = CHAT_10_25[1]["notes"]
    assert banned_hits([before]) == ["sets of"]
    assert raise_.notes == "RPE 8–9, last set RPE 9–10" and not banned_hits([raise_.notes])


def test_mutation_control_without_the_composer_the_chat_notes_fail_the_scan():
    ir, _ = _draft_custom(CHAT_10_25, composer=lambda *a, **k: {})
    assert banned_hits(_wire_notes(ir)), "the authored 10-25 notes restate the rows; the composer is what removes them"


def test_the_chat_path_step_is_the_standards_reason_and_the_render_check_finds_it():
    """The 10-26 lat pulldown, chat-drafted at 160 x 8-12: three sessions of 160 x 8 at RPE 8 make the stall rule's rep
    step due. Its note says so in the standard's grammar (no `160 lb x 8`, no `<=`, no dates), and the render check reads
    the step as landed — the IR records it, the wire carries it, nothing `missing`."""
    exercises = [{"movement_key": "lat_pulldown", "sets": [{"weight_lbs": 160, "rep_range_start": 8, "rep_range_end": 12, "count": 2}]}]
    ir, out = _draft_custom(exercises, target_date="2026-10-26", archetype="upper", role="upper_volume")
    note = ir.exercises[0].notes.split("\n\n")[-1]
    assert note == "RPE 8–9\nNow aiming 10–12: 8s were RPE 8 three times.\nBreathe out on the pull."
    [step] = out["step_due"]
    assert step["carried"] is False and step["wire_line"] == "Now aiming 10–12: 8s were RPE 8 three times."
    assert "160 lb x 8" in step["reason"]  # the engine's audit text stays on the stored record
    why = session_block.why_note_for(ir, format_why_note(ir))
    rc = hevy_render.render_check(to_create_body(ir, lambda k: "T-" + k, why_note=why), session_note=why, ir=ir)
    assert {r["field"]: r["status"] for r in rc["fields"]}["stall_step"] == "lands", rc["fields"]
    assert not [p for p in rc["problems"] if "expected on the wire" in p], rc["problems"]


# ── 2b. the minimum / travel routine: the session block and standard lift notes ───────────────────────────────────
def test_every_minimum_and_travel_routine_heads_with_the_session_block_and_carries_no_internal_id():
    bad: dict[str, list[str]] = {}
    for role in disruption.role_keys():
        for pool in disruption.POOL_NAMES:
            rx = disruption.session(role, pool, CATALOG["movements"])
            if not rx["exposures"]:
                continue
            ir = disruption.to_routine(rx, target_date="2026-12-22", variant="ideal", mode={"template": "travel"}, catalog=CATALOG)
            notes = _wire_notes(ir)
            head = notes[0].split("\n")
            want = "Minimum" if pool == "gym_minimum" else "Travel"
            if head[0] != f"{want} · RPE 8–9 on big lifts" or head[1] != session_block.LOW_ENERGY_LINE:
                bad.setdefault(f"{role}/{pool}", []).append(f"head {head[:2]}")
            if session_block.why_note_for(ir, format_why_note(ir)) != "":
                bad.setdefault(f"{role}/{pool}", []).append("a second WHY line")
            if hits := banned_hits(notes):
                bad.setdefault(f"{role}/{pool}", []).append(f"banned {hits}")
            if any(not n.split("\n\n")[-1].startswith("RPE ") for n in notes):
                bad.setdefault(f"{role}/{pool}", []).append("a lift note not led by its effort")
    assert bad == {}


# ── 2c. stage 2 re-stamps the After line on the final order ───────────────────────────────────────────────────────
def _cardio_then_stretch_ir():
    return RoutineSpec(
        routine_id="r-5428-after",
        target_date="2026-09-20",
        archetype="legs",
        version=1,
        source_action="draft_custom",
        notes="Legs.",
        exercises=[
            ExerciseBlock(movement_key="tmpl:1", rationale_tag="Squat (Barbell)", sets=[Set(weight_kg=80, reps=5)]),
            ExerciseBlock(
                movement_key="tmpl:2", rationale_tag="Leg Extension (Machine)", sets=[Set(weight_kg=40, reps=12) for _ in range(3)]
            ),
            # the composed ride, written before its position was final: no After line yet
            ExerciseBlock(movement_key="cycling", sets=[Set(duration_seconds=1800)], notes="Recumbent · L11 · RPE 4–5 (full sentences)"),
            ExerciseBlock(movement_key="tmpl:527DA061", rationale_tag="Stretching", sets=[Set(duration_seconds=900)]),
        ],
    )


def test_stage_2_stamps_the_after_line_on_the_final_order():
    import test_tools_plan_critics_3752 as base

    ir = _cardio_then_stretch_ir()
    out, stored, _ = base._run(ir, base._evidence())
    assert stored and "error" not in out, out
    assert stored[-1].exercises[2].notes.split("\n")[-1] == "After: end watch cardio, restart Hevy."


def test_mutation_control_without_the_stage_2_restamp_the_after_line_is_absent():
    import test_tools_plan_critics_3752 as base

    ir = _cardio_then_stretch_ir()
    with patch("training.cardio_note.apply_after_lines", side_effect=lambda exs: 0):
        out, stored, _ = base._run(ir, base._evidence())
    assert stored and "After:" not in stored[-1].exercises[2].notes


def test_the_restamp_runs_after_the_critics_change_the_rows():
    """Order matters: a swap or drop moves what follows the cardio, so the restamp sits AFTER `apply_changes`."""
    src = (REPO / "mcp" / "tools_plan.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "_run_stage_2")
    calls = [(c.lineno, ast.unparse(c.func)) for c in ast.walk(fn) if isinstance(c, ast.Call)]
    apply_line = min(ln for ln, f in calls if f == "critics.apply_changes")
    assert any(f == "apply_after_lines" and ln > apply_line for ln, f in calls)


# ── 3. no internal ids from the fitness-test, minimum-cut and reverted-plan producers ─────────────────────────────
def test_fitness_test_notes_are_test_lines_with_no_issue_number():
    spec = fitness_tests.tests_spec(fitness_tests.protocol())
    notes = [fitness_tests.test_note(row) for row in spec.values()]
    assert all(n.startswith("Test · ") for n in notes) and banned_hits(notes) == []
    lifts = [
        ExerciseBlock(
            movement_key="squat_barbell",
            sets=[Set(type="warmup", weight_kg=60, reps=5)] + [Set(weight_kg=100, reps=5)] * 3,
            notes="RPE 8–9\nBrace each rep, breathe between reps.",
            rationale_tag="anchor:squat:heavy",
        ),
    ]
    [cut] = fitness_tests._minimum_blocks(lifts, 2, 4)
    assert cut.notes == "RPE 8–9\n2 sets today: the tests are the session.\nBrace each rep, breathe between reps."
    assert [s.type for s in cut.sets] == ["warmup", "normal", "normal"]


def test_the_reverted_plan_note_names_its_basis_without_a_version_id():
    from mcp.predraft_shadow import _v04_note

    note = _v04_note({"load_basis": "72 % of e1RM (v0.4 ramp week 3)", "intensity": "heavy", "sets": [{"reps": [4, 6]}]})
    assert note == "Reverted plan: 72 % of e1RM (ramp week 3); heavy 4-6 reps."
    assert not re.search(r"\bv\d+\.\d", note)
    # and through the chat path's composer it never reaches the wire: the effort leads, the basis is stored
    ir, _ = _draft_custom([{"movement_key": "db_lateral_raise", "sets": [{"weight_lbs": 15, "reps": 12, "count": 2}], "notes": note}])
    assert banned_hits(_wire_notes(ir)) == [] and "Reverted plan" not in "".join(_wire_notes(ir))
    assert ir.inputs_snapshot["lift_notes"]["db_lateral_raise"]["detail"] == note


def test_the_attach_step_due_wire_copy_carries_no_issue_number_or_version_id():
    """Item 3 audit: `attach_step_due`'s wire text never held an issue number or a version id (the `#5083` is a code
    comment); on the chat path it no longer writes the note at all — the composer does (`wire_line`)."""
    from mcp.draft_custom_session import attach_step_due

    ir = RoutineSpec(
        routine_id="r",
        target_date="2026-10-26",
        archetype="upper",
        source_action="draft_custom",
        exercises=[ExerciseBlock(movement_key="lat_pulldown", sets=[Set(weight_kg=160 * LB, rep_range_start=8, rep_range_end=12)] * 2)],
    )
    [row] = attach_step_due(ir, CATALOG["movements"], history_reader=lambda: CHAT_HISTORY)
    assert ir.exercises[0].notes.startswith("Step due: ") and not re.search(r"#\d|\bv\d+\.\d", ir.exercises[0].notes)
    ir.exercises[0].notes = ""
    attach_step_due(ir, CATALOG["movements"], write_notes=False, index=CHAT_HISTORY)
    assert ir.exercises[0].notes == "" and row["carried"] is False


# ── 4. the extractor's form keywords are whole words ─────────────────────────────────────────────────────────────
def _form(text: str) -> bool:
    return any(s.get("class") == "form_technique" for s in training_notes.deterministic_pass(text))


def test_from_is_not_a_form_note_and_rom_still_is():
    assert not _form("4.0 / 3 from 20")  # his treadmill change (#5374's grammar)
    assert not _form("came back from the weekend, room was packed")
    assert _form("ROM was short on the left")
    assert _form("full range of motion today")
    assert _form("form broke down on the last rep")


def test_mutation_control_the_substring_rule_fired_on_from():
    """The pre-fix rule, `any(k in t for k in _FORM_KW)`, reads his "from" as ROM — the bug this fixes."""
    t = "4.0 / 3 from 20"
    assert any(k in t for k in training_notes._FORM_KW) and not training_notes._FORM_RE.search(t)


# ── 5. the note linter (lane D's rules, L1-L13) over every path's compiled wire ────────────────────────────────────
def _lint(ir: RoutineSpec) -> list[str]:
    from training import hevy_note_lint

    why = session_block.why_note_for(ir, format_why_note(ir))
    return hevy_note_lint.lint_wire(to_create_body(ir, lambda k: "T-" + k, why_note=why), ir).to_dict()["problems"]


def test_every_path_lints_clean_and_the_lint_fires_on_the_old_copy():
    step = [{"movement_key": "lat_pulldown", "sets": [{"weight_lbs": 160, "rep_range_start": 8, "rep_range_end": 12, "count": 2}]}]
    paths = {
        "generator, 10-26 rotated": _generate_10_26(),
        "chat, 10-25": _draft_custom(CHAT_10_25)[0],
        "chat, 10-26 step": _draft_custom(step, target_date="2026-10-26", role="upper_volume")[0],
    }
    for pool in disruption.POOL_NAMES:
        rx = disruption.session("upper_heavy", pool, CATALOG["movements"])
        paths[f"disruption, {pool}"] = disruption.to_routine(
            rx, target_date="2026-12-22", variant="ideal", mode={"template": "travel"}, catalog=CATALOG
        )
    assert {k: v for k, v in ((k, _lint(ir)) for k, ir in paths.items()) if v} == {}
    # mutation control: the engine's own rotation line (its slot id and week arithmetic) on the wire reds the lint
    ir = _generate_10_26()
    fly = next(b for b in ir.exercises if b.movement_key == "chest_fly_machine")
    fly.notes = fly.notes.replace("New: replaces Cable Fly Crossovers.", next(ln for ln in ir.rationale if "Chest Fly" in ln))
    assert [p for p in _lint(ir) if p.startswith("L1 ")], "the rationale's rotation line must fail L1"
