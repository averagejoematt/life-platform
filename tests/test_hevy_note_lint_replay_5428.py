"""tests/test_hevy_note_lint_replay_5428.py — #5428's live proof failed: the deployed linter's own words on the first
nightly drafts after the wave-11 deploy, classified and fixed.

THE WIRE (CloudWatch, warn mode, `hevy_compiler._lint_notes` -> `check_compiled`), verbatim below as WIRE_LOWER and
WIRE_UPPER. Four problem classes, each decided against `docs/coaching/HEVY_NOTE_STANDARD.md`:

  * L4 "the W text says 8 reps, the W rows hold ['8.0']" (5 of the 8 lines) — LINTER false positive. The stored IR holds
    reps as a float (8.0); the linter compared the string '8.0' to the text's '8'. Now compared as numbers.
  * L4 "working row 2 is 205 lb against PREVIOUS 225 lb with no reason line" (bench, an Upper-heavy top set + back-offs)
    — LINTER false positive. `inputs_snapshot["previous_loads"]` carries ONE load, the TOP working load of his last
    session (`exercise_history.previous_load`); the linter held every row to it, so the -10 % back-offs (standard §3.1:
    "on a top-set day, the back-offs move and the top set stays") read as unexplained drops. One PREVIOUS load is now
    judged against the top row only — the producer's rule (`lift_note._engine_reason` judges `_top_lb`); a per-row list
    still judges every row.
  * L7 "lift note 5 phone lines > 4" (seated calf raise) — COMPOSER defect. The composer wrote 4 lines (effort, the
    rotation's `New: replaces …`, the pick-load W line, the calf cue); the joints critic's applied set-count change then
    INSERTED `3 sets today: first time in 19 weeks.` as a second reason. One reason per lift (§3.2, whose reason list
    includes the critic clause) and the clause is a safety change that is never dropped (§6.3), so the clause now takes
    the reason slot (`session_block.add_reason`); `No jumps` and an earlier critic clause keep theirs.
  * L5 "dumbbell load 44 lb is not on a 2.5 lb step" (side bend) — COMPOSER defect. He logged 44 lb (19.958 kg, his
    2026-09-26 sets); the progression's floor_raise put that number on the rows unrounded. §5 'Row rounding' states the
    dumbbell step (2.5 lb under 50, nearest, ties down): `load_progression.round_to_implement` -> 45 lb.

Offline: no Hevy, no AWS, no AI; catalog entries are stubs carrying the catalog's own titles / equipment / anchors.
"""

from __future__ import annotations

import copy
from typing import Any

from coach import critics_apply
from training import hevy_compiler, hevy_note_grammar as g, hevy_note_lint as lint, lift_note, load_progression as lp, session_block
from training.rep_scheme import LB_IN_KG
from training.routine_ir import ExerciseBlock, RoutineSpec, Set

# ── the wire, verbatim ─────────────────────────────────────────────────────────────────────────────────────────────

WIRE_LOWER = (
    "hevy note lint (warn): 4 problem(s) on 'Foundation - Lower - 10 - 40': L7 [3] Seated Calf Raise: lift note 5 phone "
    "lines > 4; L4 [3] Seated Calf Raise: the W text says 8 reps, the W rows hold ['8.0']; L5 [4] Side Bend (Dumbbell): "
    "dumbbell load 44 lb is not on a 2.5 lb step; L4 [4] Side Bend (Dumbbell): the W text says 8 reps, the W rows hold ['8.0']"
)  # 2026-10-29T00:22:49Z, /aws/lambda/life-platform-mcp-warmer
WIRE_UPPER = (
    "hevy note lint (warn): 4 problem(s) on 'Foundation - Upper - 13 - 41': L4 [1] Bench Press (Barbell): working row 2 is "
    "205 lb against PREVIOUS 225 lb with no reason line; L4 [4] Lateral Raise (Machine): the W text says 8 reps, the W "
    "rows hold ['8.0']; L4 [5] Triceps Extension (Cable): the W text says 8 reps, the W rows hold ['8.0']; L4 [6] Hammer "
    "Curl (Dumbbell): the W text says 8 reps, the W rows hold ['8.0']"
)  # 2026-10-29T04:31:03Z, /aws/lambda/life-platform-mcp


def _problems(wire: str) -> list[str]:
    """The problem list of one wire line, in the linter's own `Problem.__str__` form."""
    return wire.split("': ", 1)[1].split("; ")


FALSE_POSITIVE_WIRE = ("the W text says 8 reps, the W rows hold ['8.0']", "against PREVIOUS 225 lb with no reason line")
COMPOSER_WIRE = ("lift note 5 phone lines > 4", "dumbbell load 44 lb is not on a 2.5 lb step")
# the 2026-10-30 re-grade's cardio defects, which the linter now sees on the same stored ride (L3 talk words, L9 levels
# counted through the ladder; tests/test_hevy_note_regrade_5428.py) — not on the 10-29 wire, which predates both checks
REGRADE_CARDIO = ("Cycling: RPE 5–7 is not the talk table's row for 'short phrases'", "Cycling: 5 levels > 3")
# the 2026-10-31 blind re-grade #2's classes, which the linter now also sees on these stored drafts (lint 1.1.0;
# tests/test_hevy_note_regrade2_5428.py): the old load rule, "+ easy cardio" over a hill-only session, "find the load" over rows that carry a load, `New: replaces …`
# over a PREVIOUS, and a held load whose PREVIOUS reached the top of its range at RPE <= 8.5 with no reason
REGRADE_2 = (
    "the low-energy line, the load rule",
    # re-grade #3 (lint 1.2.0): exercise 1's effort printed twice; a hold reason against the load rule
    "repeats the session line's effort",
    "the reason contradicts the load rule",
    "the low-energy line for this session's cardio",
    "the W line says 'find the load.' but the working rows carry a load",
    "'New: replaces …' over a PREVIOUS",
    "with no reason (what moves it?)",
)

# ── the two stored drafts, as the compiler saw them (loads in kg off the stored IR; reps as floats, as stored) ────────

SESSION_LOWER = (
    "Lower volume · RPE 8–9 on big lifts\nLow energy → first 2 lifts + easy cardio.\n"
    "Top reps at RPE 7 or less → +10 lb (2 pins) on later sets; at RPE 8 → +5 lb (1 pin). Under 40 lb: +5 max. Once per lift."
)
SESSION_UPPER = SESSION_LOWER.replace("Lower volume", "Upper heavy")
CARDIO_NOTE = (
    "Recumbent · L11 → L15 · RPE 5–7 (short phrases)\n"
    "⌚ ride clock: L11 to min 6 · up a level every 2 min to min 14 · down the same to min 22 · L11 to the end"
)
CATALOG: dict[str, dict[str, Any]] = {
    "deadlift_trap_bar": {
        "title": "Deadlift (Trap bar)",
        "equipment": "barbell",
        "anchor_family": "hinge",
        "hevy_template_id_hint": "B923B230",
    },
    "squat_barbell": {"title": "Squat (Barbell)", "equipment": "barbell", "anchor_family": "squat", "hevy_template_id_hint": "D04AC939"},
    "seated_calf_raise": {
        "title": "Seated Calf Raise",
        "equipment": "machine",
        "hevy_template_id_hint": "062AB91A",
        "hevy_type": "weight_reps",
    },
    "side_bend_dumbbell": {
        "title": "Side Bend (Dumbbell)",
        "equipment": "dumbbell",
        "hevy_template_id_hint": "026FD047",
        "hevy_type": "weight_reps",
    },
    "cycling": {"title": "Cycling", "equipment": "machine", "primary_muscle": "cardio", "hevy_template_id_hint": "D8F7F851"},
    "barbell_bench_press": {
        "title": "Bench Press (Barbell)",
        "equipment": "barbell",
        "anchor_family": "bench",
        "hevy_template_id_hint": "79D0BB3A",
    },
    "one_arm_db_row": {"title": "Dumbbell Row", "equipment": "dumbbell", "anchor_family": "row", "hevy_template_id_hint": "F1E57334"},
    "lat_pulldown": {
        "title": "Lat Pulldown (Cable)",
        "equipment": "cable",
        "anchor_family": "vertical_pull",
        "hevy_template_id_hint": "6A6C31A5",
    },
    "lateral_raise_machine": {"title": "Lateral Raise (Machine)", "equipment": "machine", "hevy_template_id_hint": "D5D0354D"},
    "triceps_extension_cable": {"title": "Triceps Extension (Cable)", "equipment": "cable", "hevy_template_id_hint": "21310F5F"},
    "hammer_curl_dumbbell": {"title": "Hammer Curl (Dumbbell)", "equipment": "dumbbell", "hevy_template_id_hint": "7E3BC8B6"},
    "face_pull": {"title": "Face Pull", "equipment": "machine", "hevy_template_id_hint": "BE640BA0"},
}
PICK = "RPE 8–9, last set RPE 9–10\n{lead}W set: up to 8 easy reps, find the load."


def _kg(lb: float) -> float:
    return lb * LB_IN_KG


def _w(reps: float, lb: float | None = None) -> Set:
    return Set(type="warmup", reps=reps, weight_kg=None if lb is None else _kg(lb))


def _n(lb: float, lo: float, hi: float) -> Set:
    return Set(type="normal", weight_kg=_kg(lb), rep_range_start=lo, rep_range_end=hi)


def _ex(key: str, sets: list[Set], notes: str) -> ExerciseBlock:
    return ExerciseBlock(movement_key=key, sets=sets, notes=notes)


def _lower() -> RoutineSpec:
    """Routine dde23e6b (target 2026-10-29, cron 02:00Z), its stored exercises."""
    return RoutineSpec(
        routine_id="dde23e6b",
        target_date="2026-10-29",
        archetype="lower",
        exercises=[
            _ex(
                "deadlift_trap_bar",
                [_w(8.0, 120), _w(5.0, 165), _w(3.0, 200)] + [_n(235, 8.0, 12.0)] * 3,
                SESSION_LOWER + "\n\nRPE 8–9\nHip hinges first. Brace; breathe out on the way up.",
            ),
            _ex(
                "squat_barbell",
                [_w(5.0, 150)] + [_n(215, 8.0, 12.0)] * 3,
                "RPE 8–9\nVolume day: chase 12.\nBrace each rep, breathe between reps.",
            ),
            _ex(
                "seated_calf_raise",
                [_w(8.0)] + [_n(90, 8.0, 15.0)] * 3,
                "RPE 8–9, last set RPE 9–10\n3 sets today: first time in 19 weeks.\nNew: replaces Calf Press (Machine).\n"
                "W set: up to 8 easy reps, find the load.\nFull stretch at the bottom; knees soft.",
            ),
            _ex("side_bend_dumbbell", [_w(8.0)] + [_n(44, 8.0, 15.0)] * 4, PICK.format(lead="New: replaces Crunch (Machine).\n")),
            _ex("cycling", [Set(type="normal", duration_seconds=1800)], CARDIO_NOTE),
        ],
        inputs_snapshot={
            lint.PREVIOUS_LOADS_KEY: {
                "deadlift_trap_bar": {"date": "2026-10-19", "lb": 235.0, "reps": 8.0, "rpe": 8.5},
                "seated_calf_raise": {"date": "2026-06-20", "lb": 90.0, "reps": 15.0, "rpe": 9.0},
                "side_bend_dumbbell": {"date": "2026-09-26", "lb": 44.0, "reps": 15.0, "rpe": 7.0},
                "squat_barbell": {"date": "2026-10-23", "lb": 265.0, "reps": 4.0, "rpe": 9.0},
            }
        },
    )


def _upper() -> RoutineSpec:
    """Routine be80e308 (target 2026-10-29, cron 04:30Z), its stored exercises: an Upper-heavy bench top set + back-offs."""
    return RoutineSpec(
        routine_id="be80e308",
        target_date="2026-10-29",
        archetype="upper",
        exercises=[
            _ex(
                "barbell_bench_press",
                [_w(8.0, 115), _w(5.0, 160), _w(3.0, 190), _n(225, 4.0, 6.0), _n(205, 4.0, 6.0), _n(205, 4.0, 6.0)],
                SESSION_UPPER + "\n\nRPE 8–9\nBand pull-aparts first. Breathe out on the press.",
            ),
            _ex(
                "one_arm_db_row",
                [_w(5.0, 65), _n(110, 4.0, 6.0), _n(100, 4.0, 6.0), _n(100, 4.0, 6.0)],
                "RPE 8–9\nHeavier: 10 reps was RPE 8.\nBreathe out on the pull.",
            ),
            _ex("lat_pulldown", [_n(160, 6.0, 10.0)] * 2, "RPE 8–9"),
            _ex(
                "lateral_raise_machine", [_w(8.0)] + [_n(35, 8.0, 15.0)] * 3, PICK.format(lead="New: replaces Lateral Raise (Dumbbell).\n")
            ),
            _ex("triceps_extension_cable", [_w(8.0)] + [_n(40, 8.0, 15.0)] * 2, PICK.format(lead="New: replaces Triceps Pushdown.\n")),
            _ex("hammer_curl_dumbbell", [_w(8.0)] + [_n(22.5, 8.0, 15.0)] * 2, PICK.format(lead="New: replaces Bicep Curl (Dumbbell).\n")),
            _ex("face_pull", [_n(65, 8.0, 15.0)] * 2, "RPE 8–9, last set RPE 9–10\nNew: replaces Rear Delt Reverse Fly (Machine)."),
            _ex("cycling", [Set(type="normal", duration_seconds=1800)], CARDIO_NOTE),
        ],
        inputs_snapshot={
            lint.PREVIOUS_LOADS_KEY: {
                "barbell_bench_press": {"date": "2026-10-21", "lb": 225.0, "reps": 4.0, "rpe": 10.0},
                "face_pull": {"date": "2026-10-21", "lb": 65.0, "reps": 15.0, "rpe": 9.0},
                "hammer_curl_dumbbell": {"date": "2026-09-20", "lb": 22.5, "reps": 12.0, "rpe": 8.0},
                "lat_pulldown": {"date": "2026-10-26", "lb": 160.0, "reps": 10.0, "rpe": 8.5},
                "lateral_raise_machine": {"date": "2024-02-09", "lb": 65.0, "reps": 10.0, "rpe": None},
                "one_arm_db_row": {"date": "2026-10-26", "lb": 90.0, "reps": 10.0, "rpe": 8.0},
                "triceps_extension_cable": {"date": "2024-01-22", "lb": 52.5, "reps": 12.0, "rpe": None},
            }
        },
    )


def _lint(ir: RoutineSpec) -> lint.LintResult:
    """What `check_compiled` sees: the compiled create body + the IR (the session block is already on exercise 1, so the
    compiler's WHY note is empty — `session_block.why_note_for`)."""
    body = hevy_compiler.to_create_body(ir, lambda k: f"T-{k}", why_note=session_block.why_note_for(ir, ""))
    return lint.lint_wire(body, ir, catalog=CATALOG)


def test_the_stored_drafts_lint_to_exactly_the_wire_minus_the_false_positives(monkeypatch):
    """The replay. Every wire problem in a false-positive class is gone; every composer-class problem is still there,
    word for word — the linter was right about those, and the composer fixes below are what clear them."""
    monkeypatch.setenv(lint.MODE_ENV, "off")
    seen_2: set[str] = set()
    for wire, ir in ((WIRE_LOWER, _lower()), (WIRE_UPPER, _upper())):
        got = _lint(ir).lines()
        want = [p for p in _problems(wire) if any(c in p for c in COMPOSER_WIRE)]
        later = [p for p in got if p.endswith(REGRADE_CARDIO) or any(c in p for c in REGRADE_2)]
        assert [p for p in got if p not in later] == want, (wire[:60], got)
        assert [p.split(" ", 2)[2] for p in got if p.endswith(REGRADE_CARDIO)] == list(REGRADE_CARDIO), got
        seen_2 |= {c for c in REGRADE_2 for p in later if c in p}
    assert seen_2 == set(REGRADE_2), seen_2  # every re-grade #2 class fires on at least one of the two 10-29 drafts
    assert len(_problems(WIRE_LOWER)) == 4 and len(_problems(WIRE_UPPER)) == 4


def test_mutation_w_text_against_a_real_mismatch_is_still_flagged(monkeypatch):
    """Control for the numeric compare: W text 8 over a W row of 10.0 (and of '10') still fires L4."""
    monkeypatch.setenv(lint.MODE_ENV, "off")
    ir = _upper()
    ir.exercises[3].sets[0].reps = 10.0
    lines = _lint(ir).lines()
    assert "L4 [4] Lateral Raise (Machine): the W text says 8 reps, the W rows hold ['10']" in lines, lines
    rt = lint.LintRoutine(
        exercises=[lint.LintExercise(name="x", kind="machine", rows=[("W", None, "10"), ("N", 35.0, "8–15")], note=PICK.format(lead=""))]
    )
    assert any(p.rule == "L4" and "W text says 8" in p.message for p in lint.lint_routine(rt).problems)


def test_mutation_previous_still_judges_the_top_row_and_every_row_of_a_list(monkeypatch):
    """Controls for the PREVIOUS fix: (1) one PREVIOUS load with the TOP row two steps off and no reason still fires;
    (2) a per-row PREVIOUS list still judges a back-off row against its own PREVIOUS."""
    monkeypatch.setenv(lint.MODE_ENV, "off")
    ir = _upper()
    ir.exercises[0].sets[3].weight_kg = _kg(245)
    assert "L4 [1] Bench Press (Barbell): working row 1 is 245 lb against PREVIOUS 225 lb with no reason line" in _lint(ir).lines()
    ir = _upper()
    ir.inputs_snapshot[lint.PREVIOUS_LOADS_KEY]["barbell_bench_press"] = {"loads_lb": [225.0, 225.0, 225.0]}
    assert "L4 [1] Bench Press (Barbell): working row 2 is 205 lb against PREVIOUS 225 lb with no reason line" in _lint(ir).lines()


# ── composer fix 1: a critic clause takes the one reason slot ────────────────────────────────────────────────────────

CALF_COMPOSED = (
    "RPE 8–9, last set RPE 9–10\nNew: replaces Calf Press (Machine).\nW set: up to 8 easy reps, find the load.\n"
    "Full stretch at the bottom; knees soft."
)  # the composer's own 4 lines on 2026-10-29 (inputs_snapshot.critics.draft_exercises)
CLAUSE = "3 sets today: first time in 19 weeks."
CALF_COMPOSED_2 = "RPE 8–9, last set RPE 9–10\nW set: up to 8 easy reps, test the load.\nFull stretch at the bottom; knees soft."


def test_the_critic_clause_displaces_the_rotation_reason_and_fits_the_budget():
    out = session_block.add_reason(CALF_COMPOSED, CLAUSE)
    assert out == (
        "RPE 8–9, last set RPE 9–10\n3 sets today: first time in 19 weeks.\nW set: up to 8 easy reps, find the load.\n"
        "Full stretch at the bottom; knees soft."
    )
    assert g.phone_lines(out) <= g.LIFT_MAX_LINES
    # mutation control: the pre-fix insert (clause after line 1, nothing displaced) is the wire's 5-line note
    lines = CALF_COMPOSED.split("\n")
    stacked = "\n".join(lines[:1] + [CLAUSE] + lines[1:])
    assert g.phone_lines(stacked) == 5 > g.LIFT_MAX_LINES
    # the displaced line under a session block too (exercise 1)
    head = session_block.add_reason(SESSION_LOWER + "\n\n" + CALF_COMPOSED, CLAUSE)
    assert head.startswith(SESSION_LOWER + "\n\nRPE 8–9, last set RPE 9–10\n" + CLAUSE + "\nW set:") and "New: replaces" not in head


def test_a_no_jumps_line_and_an_earlier_critic_clause_keep_their_lines():
    capped = "RPE 7\nNo jumps today: session 2 back after a break.\nBreathe out on the press."
    assert (
        session_block.add_reason(capped, "2 sets today.")
        == "RPE 7\n2 sets today.\nNo jumps today: session 2 back after a break.\nBreathe out on the press."
    )
    first = session_block.add_reason("RPE 8–9\nVolume day: chase 12.", "2 sets today: a lighter day for the joints.")
    assert first == "RPE 8–9\n2 sets today: a lighter day for the joints."
    both = session_block.add_reason(first, "Lighter today.")
    assert both == "RPE 8–9\nLighter today.\n2 sets today: a lighter day for the joints."
    assert session_block.add_reason(both, "Lighter today.") == both  # idempotent
    # the critic's load / rep clauses are reasons to the linter too (standard §3.2's list)
    assert all(g.REASON_RE.match(c) for c in ("Lighter today.", "Heavier today: x.", "Fewer reps today.", "1 set today.", CLAUSE))


def test_a_freshly_composed_rotated_pick_load_lift_with_a_critic_change_lints_clean(monkeypatch):
    """End to end over the producers: `lift_note.compose_blocks` (rotation + stale history -> the pick-load form), then
    the joints critic's applied set-count change (`critics_apply.apply_changes`), compiled and linted.

    #5428 re-grade (2026-10-30): stale is now §3.3's 180 days, so the history sits 8 months back (the 10-29 draft's
    06-20 session is fresh and is the re-grade test's case), and a set cap after more than 90 days takes the capped
    treatment — `RPE 7` and one `No jumps` line in the reason slot (tests/test_hevy_note_regrade_5428.py)."""
    monkeypatch.setenv(lint.MODE_ENV, "off")
    ir = _lower()
    calf = ExerciseBlock(
        movement_key="seated_calf_raise", sets=[_n(90, 8, 15) for _ in range(4)], rationale_tag="accessory:seated_calf_raise:accessory"
    )
    ir.exercises[2] = calf
    history = {"062AB91A": [{"date": "2026-02-28", "sets": [{"weight_kg": _kg(90), "reps": 15, "rpe": 9}] * 3}]}
    lift_note.compose_blocks(
        [calf],
        CATALOG,
        load_floors={},
        history_index=history,
        target_date="2026-10-29",
        rotations={"seated_calf_raise": "Calf Press (Machine)"},
    )
    # re-grade #2 (2026-10-31): PREVIOUS (90 lb, 8 months back) exists, so no `New: replaces …`; the row is its load,
    # so no reason; the feeler W line tests the start load
    assert calf.notes == CALF_COMPOSED_2, calf.notes
    verdict = {
        "critic": "joints_tendons",
        "verdict": "change",
        "field": "exercises[2].set_count",
        "to": 3,
        "metric": "days_since_last",
        "value": 243,
    }
    recs = critics_apply.apply_changes(ir, [verdict])
    assert recs[0]["applied"] and recs[0]["clauses"][0]["clause"] == "No jumps: 3 sets today, 8 months off.", recs
    assert ir.exercises[2].notes == (
        "RPE 7\nNo jumps: 3 sets today, 8 months off.\nW set: up to 8 easy reps, test the load.\nFull stretch at the bottom; knees soft."
    )
    res = _lint(ir)
    assert not [p for p in res.lines() if "[3]" in p], res.lines()
    assert g.phone_lines(ir.exercises[2].notes) == 4


# ── composer fix 2: a step / floor-raise load lands on the implement's step ──────────────────────────────────────────


def _floor_raise(lb: float) -> dict[str, Any]:
    return {"basis": lp.BASIS_FLOOR_RAISE, "next_load_kg": _kg(lb), "reason": f"floor {lb:g} lb"}


def test_a_floor_raise_to_a_logged_44_lb_dumbbell_is_45():
    prog = lp.round_to_implement(_floor_raise(44), "dumbbell")
    assert round(prog["next_load_kg"] / LB_IN_KG, 6) == 45.0 and round(prog["rounded_from_kg"] / LB_IN_KG, 6) == 44.0
    sets = [Set(type="warmup", reps=8)] + [Set(type="normal", weight_kg=_kg(40), rep_range_start=8, rep_range_end=15) for _ in range(4)]
    lp.apply_to_sets(sets, prog)
    assert [round(s.weight_kg / LB_IN_KG, 6) for s in sets[1:]] == [45.0] * 4 and sets[0].weight_kg is None
    # the same block through the linter: on the step, no L5
    ir = _lower()
    ir.exercises[3].sets = sets
    assert not [p for p in _lint(ir).lines() if p.startswith("L5")], _lint(ir).lines()


def test_mutation_rounding_only_moves_fixed_step_implements_and_load_steps():
    """Controls: the unrounded 44 on the wire still fires L5 (above); a cable / machine / kettlebell load, a hold, and a
    rep step keep their load; a barbell tie goes down (standard §5); an on-step load records no rounding."""
    for eq in ("cable", "machine", "kettlebell", None):
        assert lp.round_to_implement(_floor_raise(44), eq)["next_load_kg"] == _kg(44), eq
    hold = {"basis": lp.BASIS_HOLD, "next_load_kg": _kg(44)}
    assert lp.round_to_implement(copy.deepcopy(hold), "dumbbell") == hold
    reps = {"basis": lp.BASIS_STEP, "step_kind": lp.STEP_KIND_REPS, "next_load_kg": _kg(44), "next_reps": 12}
    assert lp.round_to_implement(copy.deepcopy(reps), "dumbbell") == reps
    assert round(lp.round_to_implement(_floor_raise(227.5), "barbell")["next_load_kg"] / LB_IN_KG, 6) == 225.0
    on = lp.round_to_implement(_floor_raise(22.5), "dumbbell")
    assert "rounded_from_kg" not in on and round(on["next_load_kg"] / LB_IN_KG, 6) == 22.5
    # raise only: a load rounded under the block's current one changes nothing
    sets = [Set(type="normal", weight_kg=_kg(45), reps=10)]
    assert lp.apply_to_sets(sets, lp.round_to_implement(_floor_raise(43.5), "dumbbell")) == [] and sets[0].weight_kg == _kg(45)
