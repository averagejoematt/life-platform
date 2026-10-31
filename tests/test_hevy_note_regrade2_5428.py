"""tests/test_hevy_note_regrade2_5428.py — #5428's blind four-voice re-grade #2 (2026-10-31, ~05:45Z): the nightly
pre-draft 40f2c0b5 v3 (Shoulders + arms, 7 exercises) graded C+/B−, not A, while `hevy_note_lint` read it CLEAN. Six
defect classes, several written into `docs/coaching/HEVY_NOTE_STANDARD.md` itself:

  1. §3.2 said a capped exposure is OD1's ">90 days, on any lift" — against the owner's 2026-10-30 ruling (no blanket
     layoff cap). The text now names what caps a lift; a long layoff nothing capped keeps the normal band.
  2. `New: replaces Lateral Raise (Dumbbell).` over a PREVIOUS of 65 lb × 10 (2024-02-09), its 35-lb rows with no why,
     and "find the load" over a fixed row. New is only for a lift with NO PREVIOUS; a stale PREVIOUS far off says
     `Lighter: first time in 2 years.`; the feeler line tests the rows' load.
  3. The load rule: RPE 8.5 in neither branch, "pins" on a dumbbell, "on later sets" over a one-set lift.
  4. The reverse fly and the rope pushdown held at a PREVIOUS that hit the top of the range at RPE 8.5, with no reason.
  5. Intervals: the talk check at min 8 (the hard/easy boundary), a two-level escape, no warm-up or cool-down level,
     "between" at L10 under his steady L11, and the low-energy line promising easy cardio the session did not have.
  6. The carry: rows rendered "60 m" under "Steps go in the yards box." The row IS the step count (#5373; his logged
     carries read back as whole numbers), so the linter renders it as steps and fails a metre word or a converted row.

The proof: the stored draft (tests/fixtures/hevy_notes_2026_10/draft_40f2c0b5_regrade2.json, public-safe: notes, set
rows, PREVIOUS, the swaps) FAILS lint under the new rules with every class above that lives on the wire, and the same
draft re-composed by the producers (`lift_note.compose_blocks`, `cardio_note.compose`, `session_block.place_on_first`)
and compiled (`hevy_compiler.to_create_body`) reads the new notes and lints clean. Offline: no Hevy, no AWS, no AI.
"""

from __future__ import annotations

import copy
import json
import pathlib
from typing import Any

from training import cardio_note, hevy_compiler, hevy_note_grammar as g, hevy_note_lint as lint, lift_note, session_block
from training.exercise_history import CARRY_INDEX_PREFIX
from training.routine_ir import ExerciseBlock, RoutineSpec, Set

ROOT = pathlib.Path(__file__).resolve().parents[1]
DRAFT = json.loads((ROOT / "tests" / "fixtures" / "hevy_notes_2026_10" / "draft_40f2c0b5_regrade2.json").read_text(encoding="utf-8"))
_REPO_CATALOG: dict[str, Any] = json.loads((ROOT / "config" / "movement_catalog.json").read_text(encoding="utf-8"))["movements"]


def _catalog() -> dict[str, Any]:
    """The repo's catalog entries for the draft's movements, each carrying the Hevy template the generator resolved for
    it (the PREVIOUS record's `template_id`: an in-block performed record, #4409, where the catalog names none)."""
    cat = {k: dict(_REPO_CATALOG[k]) for k in (e["movement_key"] for e in DRAFT["exercises"])}
    for key, prev in DRAFT["previous_loads"].items():
        cat[key]["hevy_template_id_hint"] = prev["template_id"]
    return cat


CATALOG = _catalog()


def _sets(rows: list[dict[str, Any]], *, drop_feeler: bool) -> list[Set]:
    fields = ("type", "weight_kg", "reps", "rep_range_start", "rep_range_end", "distance_meters", "duration_seconds")
    return [Set(**{k: r[k] for k in fields if k in r}) for r in rows if not (drop_feeler and r.get("feeler"))]


def _ir(blocks: list[ExerciseBlock]) -> RoutineSpec:
    return RoutineSpec(
        routine_id=DRAFT["routine_id"],
        target_date=DRAFT["target_date"],
        archetype=DRAFT["archetype"],
        title=DRAFT["title"],
        exercises=blocks,
        inputs_snapshot={
            "calendar": {"session_role": DRAFT["session_role"]},
            lint.PREVIOUS_LOADS_KEY: copy.deepcopy(DRAFT["previous_loads"]),
        },
    )


def stored_ir() -> RoutineSpec:
    """The draft exactly as stored: its notes and its rows (the pick-load feeler W row included)."""
    blocks = [
        ExerciseBlock(
            movement_key=e["movement_key"],
            sets=_sets(e["sets"], drop_feeler=False),
            notes=e["stored_note"],
            rest_seconds=e["rest_seconds"],
            rationale_tag=e["rationale_tag"],
        )
        for e in DRAFT["exercises"]
    ]
    return _ir(blocks)


def _history() -> dict[str, list[dict[str, Any]]]:
    """The generator's history index, reduced to what Hevy's PREVIOUS column shows (one top set per template)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for prev in DRAFT["previous_loads"].values():
        top = {"weight_kg": prev["lb"] * 0.45359237, "reps": prev["reps"], "rpe": prev["rpe"]}
        out[prev["template_id"]] = [{"date": prev["date"], "sets": [top]}]
    # a loaded carry lives under its own key (`exercise_history.CARRY_INDEX_PREFIX`), in the current per-hand unit
    for c in DRAFT["carry_history"].values():
        kg = c["top_lb_per_hand"] * 0.45359237
        out[CARRY_INDEX_PREFIX + c["template_id"]] = [{"date": c["date"], "sets": [{"weight_kg": kg, "reps": 0}], "top_weight_kg": kg}]
    return out


def recomposed_ir() -> RoutineSpec:
    """The same draft through today's producers, in the generator's order: the lift notes over the rows the load passes
    left (the feeler W row is the composer's, so it is re-added, not carried), the cardio note from the dose's steady
    level, then the session block on exercise 1 (its low-energy line reads the cardio)."""
    blocks = [
        ExerciseBlock(
            movement_key=e["movement_key"],
            sets=_sets(e["sets"], drop_feeler=True),
            notes="",
            rest_seconds=e["rest_seconds"],
            rationale_tag=e["rationale_tag"],
        )
        for e in DRAFT["exercises"]
    ]
    floors = {"movements": {k: {"progression": v} for k, v in DRAFT["progression"].items()}}
    record = lift_note.compose_blocks(
        blocks, CATALOG, load_floors=floors, history_index=_history(), target_date=DRAFT["target_date"], rotations=DRAFT["rotations"]
    )
    c = DRAFT["cardio"]
    facts = {"series": [{"date": f"2026-10-{d:02d}", "level": c["steady_level"]} for d in range(20, 25)]}
    cardio = next(b for b in blocks if b.movement_key == c["movement_key"])
    cardio.notes, _audit = cardio_note.compose(
        movement_key=c["movement_key"], minutes=c["minutes"], target_date=DRAFT["target_date"], kind=c["kind"], facts=facts
    )
    cardio_note.apply_after_lines(blocks)
    ir = _ir(blocks)
    ir.inputs_snapshot[lint.PREVIOUS_LOADS_KEY] = record["previous_loads"]  # what the generator stores: the carry's last load too
    session_block.place_on_first(ir)
    return ir


def _lint(ir: RoutineSpec) -> lint.LintResult:
    """What `check_compiled` sees: the compiled create body + the IR."""
    body = hevy_compiler.to_create_body(ir, lambda k: f"T-{k}", why_note=session_block.why_note_for(ir, ""))
    return lint.lint_wire(body, ir, catalog=CATALOG)


# ── the stored draft fails, by class ─────────────────────────────────────────────────────────────────────────────────

OLD_DRAFT_PROBLEMS = [
    "L3 session block: the low-energy line for this session's cardio is 'Low energy → first 2 lifts + cardio, no hard efforts.'",
    "L3 session block: the load rule heads a one-set exercise 1 (no later set to step)",
    "L6 [1] Shoulder Press (Dumbbell): exercise 1 repeats the session line's effort ('RPE 8–9')",
    "L11 [1] Shoulder Press (Dumbbell): 'pins' on a dumbbell lift (a step is lb per hand)",
    "L11 [1] Shoulder Press (Dumbbell): 'later sets' on a lift with one working set",
    "L4 [2] Lateral Raise (Machine): the W line says 'find the load.' but the working rows carry a load",
    "L4 [2] Lateral Raise (Machine): the W line gives its test no result rule: 'W set: up to 8 easy reps, find the load.'",
    "L4 [2] Lateral Raise (Machine): 'New: replaces …' over a PREVIOUS (Hevy shows it beside the row): New is only for a lift never logged",
    "L4 [3] Rear Delt Reverse Fly (Machine): held at PREVIOUS 60 lb, which reached the top of 15 reps at RPE 8.5, with no reason "
    "(what moves it?)",
    "L4 [5] Triceps Rope Pushdown: held at PREVIOUS 50 lb, which reached the top of 15 reps at RPE 8.5, with no reason (what moves it?)",
    "L4 [6] Farmers Walk: a carry with no adjust rule after set 1",
    "L9 [7] Cycling: interval levels L10/L12: between is his steady level, one under the hard level",
    "L9 [7] Cycling: interval clock names no level before and after the reps (warm-up, cool-down)",
    "L9 [7] Cycling: interval talk check at a bare minute; it lands as a hard rep ends",
    "L9 [7] Cycling: interval clock gives the easy minutes no talk words",
    "L9 [7] Cycling: interval escape L12 → L14 is more than one level",
    "L9 [7] Cycling: interval escape is not full sentences → one level up, can't talk → shorter reps at the hard level",
]


def test_the_stored_40f2c0b5_draft_fails_lint_with_every_regrade_2_class(monkeypatch):
    """The draft the deployed linter logged `clean` at 02:00:51Z, under lint 1.1.0: every wire class of re-grade #2."""
    monkeypatch.setenv(lint.MODE_ENV, "off")
    res = _lint(stored_ir())
    assert not res.ok and res.lines() == OLD_DRAFT_PROBLEMS, res.lines()
    assert res.not_checked == [], res.not_checked


def test_MUTATION_the_10_lint_rules_read_the_stored_draft_clean(monkeypatch):
    """Control: the 1.0.0 rule set's view — the same draft with the 1.1.0 checks taken out reads clean, which is what the
    deployed run logged. The new rules are what fail it, not a fixture artefact."""
    monkeypatch.setenv(lint.MODE_ENV, "off")
    monkeypatch.setattr(lint, "_lint_set_words", lambda *a, **k: None)
    monkeypatch.setattr(lint, "_lint_intervals", lambda *a, **k: None)
    monkeypatch.setattr(lint, "_lint_carry", lambda *a, **k: None)
    monkeypatch.setattr(lint, "cardio_kinds", lambda rt: [])
    monkeypatch.setattr(lint, "_session_effort", lambda session: None)
    monkeypatch.setattr(g, "rule_mode", lambda *a: "ex1")
    monkeypatch.setattr(g, "rule_lines", lambda mode: [DRAFT["exercises"][0]["stored_note"].split("\n")[2]])
    monkeypatch.setattr(g, "PICK_LOAD_RESULT_RE", __import__("re").compile("W set"))
    ir = stored_ir()
    for key in ir.inputs_snapshot[lint.PREVIOUS_LOADS_KEY].values():
        key.pop("rpe")  # the held-top rule reads PREVIOUS's RPE; 1.0.0 read the load only
    ir.exercises[1].notes = ir.exercises[1].notes.replace("New: replaces Lateral Raise (Dumbbell).\n", "Lighter: x.\n")
    ir.exercises[1].notes = ir.exercises[1].notes.replace(g.PICK_LOAD_OPEN_TAIL, g.PICK_LOAD_FIXED_TAIL)
    assert _lint(ir).ok, _lint(ir).lines()


# ── the same draft, re-composed: the new notes, clean ────────────────────────────────────────────────────────────────

# re-grade #2's rendering (round 1 of this PR), graded B− by blind re-grade #3 — it must fail the round-3 rules too
ROUND_1_NOTES = {
    "db_shoulder_press": (
        "Shoulders + arms · RPE 8–9 on big lifts\nLow energy → first 2 lifts + cardio, no hard efforts.\n"
        "Top reps at RPE 7 or less → +10 lb on sets left; 7.5–8.5 → +5. Under 40 lb: +5 max. Dumbbells per hand. Once per lift.\n\n"
        "RPE 8–9\nBreathe out on the press."
    ),
    "lateral_raise_machine": "RPE 8–9, last set RPE 9–10\nLighter: first time in 2 years.\nW set: up to 8 easy reps, test the load.",
    "reverse_pec_deck": "RPE 8–9, last set RPE 9–10\nSame load: hit 15 again to move it up.",
    "seated_incline_curl_dumbbell": "RPE 8–9, last set RPE 9–10",
    "triceps_rope_pushdown": "RPE 8–9, last set RPE 9–10\nSame load: hit 15 again to move it up.",
    "farmers_walk": "RPE 8–9 · pick the load per hand\nTall, ribs down, bells off your legs.\nSteps go in the yards box.",
    "cycling": (
        "Recumbent · L11/L12 · hard RPE 8 (a few words)\n"
        "⌚ ride clock: L12 2 min at min 6, 10, 14, 18, 22; L11 before, between, after.\n"
        "Full sentences as rep 1 ends → L13 reps."
    ),
}
ROUND_1_PROBLEMS = [
    "L3 session block: the load rule heads a one-set exercise 1 (no later set to step)",
    "L6 [1] Shoulder Press (Dumbbell): exercise 1 repeats the session line's effort ('RPE 8–9')",
    "L4 [2] Lateral Raise (Machine): the W line gives its test no result rule: 'W set: up to 8 easy reps, test the load.'",
    "L4 [3] Rear Delt Reverse Fly (Machine): the reason contradicts the load rule or leaves its timeline open: 'Same load: hit 15 "
    "again to move it up.' (PREVIOUS's top reps at RPE <= 8.5 earn the step: say it as set 1 → the step on later sets)",
    "L4 [5] Triceps Rope Pushdown: the reason contradicts the load rule or leaves its timeline open: 'Same load: hit 15 again to "
    "move it up.' (PREVIOUS's top reps at RPE <= 8.5 earn the step: say it as set 1 → the step on later sets)",
    "L4 [6] Farmers Walk: a carry with no adjust rule after set 1",
    "L4 [6] Farmers Walk: a carry with his last load on file (60 lb per hand) names no start",
    "L9 [7] Cycling: interval clock gives the easy minutes no talk words",
    "L9 [7] Cycling: interval escape is not full sentences → one level up, can't talk → shorter reps at the hard level",
]


def _as_rendered(notes: dict[str, str]) -> RoutineSpec:
    """The recomposed rows with an earlier round's notes, and that round's rows: the feeler W row without a load and the
    carry rows without one (both were added in round 4)."""
    ir = recomposed_ir()
    for b in ir.exercises:
        b.notes = notes[b.movement_key]
        if b.movement_key in ("lateral_raise_machine", "farmers_walk"):
            for st in b.sets:
                if st.type == "warmup" or b.movement_key == "farmers_walk":
                    st.weight_kg = None
    return ir


def test_the_round_1_rendering_fails_the_round_3_rules(monkeypatch):
    """Blind re-grade #3's five defects, on the rendering it graded: the load rule on a one-set exercise 1, RPE 8–9
    twice, the hold reason against the load rule, a carry with no start and no adjust rule, and intervals whose easy
    minutes have no talk words and whose escape only steps up."""
    monkeypatch.setenv(lint.MODE_ENV, "off")
    res = _lint(_as_rendered(ROUND_1_NOTES))
    assert res.lines() == ROUND_1_PROBLEMS, res.lines()


# round 3 (re-grade #3's fixes), graded B/B+ by blind re-grade #4 — it must fail the round-4 rules
ROUND_2_NOTES = {
    "db_shoulder_press": (
        "Shoulders + arms · RPE 8–9 on big lifts\nLow energy → first 2 lifts + cardio, no hard efforts.\n\n"
        "One set: 10 reps at RPE 9 or less two sessions running → +5 lb per hand.\nBreathe out on the press."
    ),
    "lateral_raise_machine": "RPE 8–9, last set RPE 9–10\nLighter: first time in 2 years.\nW set: up to 8 easy reps, test the load.",
    "reverse_pec_deck": "RPE 8–9, last set RPE 9–10\nSame load to start: 15 reps on set 1 at RPE 8.5 or less → next plate.",
    "seated_incline_curl_dumbbell": "RPE 8–9, last set RPE 9–10",
    "triceps_rope_pushdown": "RPE 8–9, last set RPE 9–10\nSame load to start: 15 reps on set 1 at RPE 8.5 or less → next plate.",
    "farmers_walk": (
        "RPE 8–9 · 60 lb per hand to start\nTall, ribs down, bells off your legs.\nSet 1 at RPE 7 or less: +10 lb per hand.\n"
        "Steps go in the yards box."
    ),
    "cycling": (
        "Recumbent · L11/L12 · hard RPE 8 (a few words)\n"
        "⌚ ride clock: L12 2 min at min 6, 10, 14, 18, 22; else L11 (full sentences).\n"
        "Rep 1: full sentences → L13; none → L11."
    ),
}
ROUND_2_PROBLEMS = [
    "L3 session block: no load rule for the session's multi-set lifts ('Other lifts: …')",
    "L4 [2] Lateral Raise (Machine): the W line gives its test no result rule: 'W set: up to 8 easy reps, test the load.'",
    "L4 [3] Rear Delt Reverse Fly (Machine): the reason contradicts the load rule or leaves its timeline open: 'Same load to start: "
    "15 reps on set 1 at RPE 8.5 or less → next plate.' (PREVIOUS's top reps at RPE <= 8.5 earn the step: say it as set 1 → the "
    "step on later sets)",
    "L4 [5] Triceps Rope Pushdown: the reason contradicts the load rule or leaves its timeline open: 'Same load to start: 15 reps on "
    "set 1 at RPE 8.5 or less → next plate.' (PREVIOUS's top reps at RPE <= 8.5 earn the step: say it as set 1 → the step on "
    "later sets)",
    "L4 [6] Farmers Walk: the carry's start load is in the note but not on its rows",
    "L9 [7] Cycling: interval escape is not full sentences → one level up, can't talk → shorter reps at the hard level",
]


def test_the_round_3_rendering_fails_the_round_4_rules(monkeypatch):
    """Blind re-grade #4's four defects, on the rendering it graded: no in-session load rule left for the multi-set lifts
    (it was dropped with the one-set exercise 1), a feeler W line with no result, the carry's load only in the note, and
    an escape whose "none" is not a talk word and whose step down cancels the intervals."""
    monkeypatch.setenv(lint.MODE_ENV, "off")
    res = _lint(_as_rendered(ROUND_2_NOTES))
    assert res.lines() == ROUND_2_PROBLEMS, res.lines()


SESSION = (
    "Shoulders + arms · RPE 8–9 on big lifts\nLow energy → first 2 lifts + cardio, no hard efforts.\n"
    # re-grade #4: the press has one set, but the session's multi-set lifts still get the in-session rule, addressed to them
    "Other lifts: top reps at RPE 7 or less → +10 lb on later sets; 7.5–8.5 → +5 lb.\n"
    "Under 40 lb: +5 lb max. Stack: next plate. Once per lift."
)
NEW_NOTES = {
    "db_shoulder_press": SESSION
    + "\n\nOne set: 10 reps at RPE 9 or less two sessions running → +5 lb per hand.\nBreathe out on the press.",
    # the feeler W row is AT the 35-lb start load now, and the line says what its answer does
    "lateral_raise_machine": "RPE 8–9, last set RPE 9–10\nLighter: first time in 2 years.\nW set at RPE 5 or less → next plate.",
    # the load rule's own step on this lift, in the rule's own timeline words
    "reverse_pec_deck": "RPE 8–9, last set RPE 9–10\nSet 1: 15 reps at RPE 8.5 or less → next plate on later sets.",
    "seated_incline_curl_dumbbell": "RPE 8–9, last set RPE 9–10",
    "triceps_rope_pushdown": "RPE 8–9, last set RPE 9–10\nSet 1: 15 reps at RPE 8.5 or less → next plate on later sets.",
    "farmers_walk": (
        "RPE 8–9 · 60 lb per hand to start\nTall, ribs down, bells off your legs.\nSet 1 at RPE 7 or less: +10 lb per hand.\n"
        "Steps go in the yards box."
    ),
    "cycling": (
        "Recumbent · L11/L12 · hard RPE 8 (a few words)\n"
        "⌚ ride clock: L12 2 min at min 6, 10, 14, 18, 22; else L11 (full sentences).\n"
        "As rep 1 ends: full sentences → L13; can't talk → 1 min at L12."
    ),
}


def test_the_recomposed_draft_reads_the_new_notes_and_lints_clean(monkeypatch):
    monkeypatch.setenv(lint.MODE_ENV, "off")
    ir = recomposed_ir()
    assert {b.movement_key: b.notes for b in ir.exercises} == NEW_NOTES
    res = _lint(ir)
    assert res.ok and res.not_checked == [], res.lines()
    # the working rows the engine chose are untouched; two rows gained a load (round 4): the feeler W row is AT the
    # 35-lb start load it tests, and the carry rows carry his last carry, 60 lb per hand (the current convention)
    stored = stored_ir()
    for new, old in zip(ir.exercises, stored.exercises):
        got = [(s.type, s.weight_kg, s.reps, s.rep_range_end, s.distance_meters) for s in new.sets]
        want = [(s.type, s.weight_kg, s.reps, s.rep_range_end, s.distance_meters) for s in old.sets]
        if new.movement_key == "lateral_raise_machine":
            want[0] = ("warmup", new.sets[1].weight_kg, 8, None, None)
        if new.movement_key == "farmers_walk":
            want = [(t, round(60 * 0.45359237, 6), r, e, d) for t, _w, r, e, d in want]
        assert got == want, new.movement_key


def test_the_carry_row_is_a_whole_step_count_and_reads_as_steps():
    """The 60 on the wire is 60 in his yards box (#5373): a whole number, rendered `60 steps`, never `60 m`."""
    ir = recomposed_ir()
    body = hevy_compiler.to_create_body(ir, lambda k: f"T-{k}", why_note="")
    carry = body["routine"]["exercises"][5]  # the farmer's walk, by position (the compiler emits the IR order)
    assert [s["distance_meters"] for s in carry["sets"]] == [60, 60]
    rt = lint.from_wire(body, ir, catalog=CATALOG)
    assert [r[2] for r in rt.exercises[5].rows] == ["60 steps", "60 steps"] and rt.exercises[5].kind == "carry"


def test_each_fixed_note_fits_its_budget():
    ir = recomposed_ir()
    block, own = session_block.split(ir.exercises[0].notes)
    assert g.phone_lines(block) <= g.SESSION_BLOCK_MAX_LINES and g.phone_lines(ir.exercises[0].notes) <= g.EX1_MAX_LINES
    for b in ir.exercises[1:6]:
        assert g.phone_lines(b.notes) <= g.LIFT_MAX_LINES, b.movement_key
    cardio = ir.exercises[6].notes
    # an interval ride's budget is 7 with its two-line escape (re-grade #4); room for an After line
    assert g.phone_lines(cardio) <= g.CARDIO_INTERVAL_MAX_LINES - 1 and len(cardio) + 1 + len(g.AFTER_LINE) <= g.CARDIO_NOTE_MAX_CHARS
    assert all(len(ln) <= g.LINE_MAX_CHARS for b in ir.exercises for ln in b.notes.split("\n"))


def test_a_critic_change_to_the_cardio_resyncs_the_low_energy_line():
    """Stage 2 (`tools_plan`) re-reads line 2 after the critics' swaps and drops (`session_block.sync_low_energy`): drop
    the intervals and the session has no hard cardio left, so the ruled `+ easy cardio` line comes back; idempotent."""
    ir = recomposed_ir()
    assert ir.exercises[0].notes.split("\n")[1] == g.LOW_ENERGY_HARD_CARDIO_LINE
    assert session_block.sync_low_energy(ir) is False  # already right
    ir.exercises.pop()  # a critic dropped the ride
    assert session_block.sync_low_energy(ir) is True and ir.exercises[0].notes.split("\n")[1] == g.LOW_ENERGY_LINE
    assert ir.exercises[0].notes.endswith("\n\n" + NEW_NOTES["db_shoulder_press"].split("\n\n", 1)[1])
    assert session_block.sync_low_energy(ir) is False
    src = (ROOT / "mcp" / "tools_plan.py").read_text(encoding="utf-8")
    assert "session_block.sync_low_energy(ir)" in src


def test_a_loaded_carry_is_indexed_under_its_own_key_and_starts_the_note():
    """His 10-25 Farmers Walk (120 lb logged as the total, distances 50/60/60): the weighted index's reps filter drops
    it, so `exercise_history` keeps it under `carry:<template>`, in the current per-hand unit, and the carry note starts
    from it. Control: a reps-bearing block is never a carry entry."""
    from training import exercise_history

    index: dict[str, list] = {}
    sets = [{"weight_kg": 54.43114913227677, "distance_m": d, "reps": None, "type": "normal"} for d in (50, 60, 60)]
    exercise_history._index_carry(index, "50C613D0", {"name": "Farmers Walk"}, sets, 0.5, "2026-10-25")
    assert list(index) == [CARRY_INDEX_PREFIX + "50C613D0"] and round(index["carry:50C613D0"][0]["top_weight_kg"] / 0.45359237) == 60
    start = lift_note._last_carry(index, "50C613D0", "2026-10-31")
    assert start == {"date": "2026-10-25", "template_id": "50C613D0", "lb": 60.0, "reps": 0, "rpe": None, "carry": True}
    assert lift_note.carry_note(start).split("\n")[0] == "RPE 8–9 · 60 lb per hand to start"
    assert lift_note.carry_note(None).split("\n")[0] == "RPE 8–9 · pick the load per hand"
    exercise_history._index_carry(index, "T-CURL", {"name": "Curl"}, [{"weight_kg": 13.6, "reps": 10}], 1.0, "2026-10-25")
    assert "carry:T-CURL" not in index
