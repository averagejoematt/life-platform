"""tests/test_hevy_note_lint_5428.py — #5428: the Hevy routine-note linter (standard §8, rules L1–L13).

Three fixtures, all offline (no Hevy, no AWS, no AI):

  * `a_grade.json` — the review's A-grade corpus (the newest 10 routines rewritten to the standard), with the owner's
    2026-10-27 ~04:50Z session block (no safety line; the low-energy line back). The linter must return [] on every one.
  * `originals.json` — the same 10 routines AS PUSHED (2026-10-11 .. 10-26), scrubbed for the public repo (clinical,
    bodyweight, nutrition and rate lines replaced; loads and reps kept, ruled public). Every one must fail, and the
    named drift classes the review found must each be among the problems.
  * MUTATION CONTROLS — a one-line break of the golden corpus per rule; each must fire its rule. One test iterates every
    control and reports every one that stays silent (a parametrized test would count as one gate per control).

The compiler hook (warn mode: log, never block, never rewrite) and the wire adapter are proved here too.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
from typing import Any, Callable

from training import hevy_compiler, hevy_note_grammar as g, hevy_note_lint as lint
from training.routine_ir import ExerciseBlock, RoutineSpec, Set

_FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "hevy_notes_2026_10")


def _load(name: str) -> list[dict[str, Any]]:
    with open(os.path.join(_FIX, name), encoding="utf-8") as fh:
        return json.load(fh)["routines"]


GOLDEN = _load("a_grade.json")
ORIGINALS = _load("originals.json")


def _by_date(routines: list[dict[str, Any]], date: str) -> dict[str, Any]:
    return copy.deepcopy(next(r for r in routines if r["date"] == date))


def routine_from_dict(d: dict[str, Any]) -> lint.LintRoutine:
    """The fixture shape (tests/fixtures/hevy_notes_2026_10/*.json): {"exercises": [{"name", "kind", "rows":
    [[type, lb, reps]], "note", "compound", "family", "anchor_family", "previous_lb"}], "previous_supplied"}."""
    exs = [
        lint.LintExercise(
            name=str(e["name"]),
            kind=str(e["kind"]),
            rows=[(str(r[0]), None if r[1] is None else float(r[1]), None if r[2] is None else str(r[2])) for r in e.get("rows") or []],
            note=str(e.get("note") or ""),
            compound=bool(e.get("compound")),
            family=e.get("family"),
            anchor_family=e.get("anchor_family"),
            previous_lb=e.get("previous_lb"),
            previous_reps=e.get("previous_reps"),
            previous_rpe=e.get("previous_rpe"),
        )
        for e in d.get("exercises") or []
    ]
    return lint.LintRoutine(exercises=exs, previous_supplied=bool(d.get("previous_supplied")), title=str(d.get("title") or ""))


def _lint(rt: dict[str, Any]) -> lint.LintResult:
    return lint.lint_routine(routine_from_dict(rt))


# ── the golden corpus passes; the originals fail ───────────────────────────────────────────────────────────────────


def test_the_a_grade_corpus_lints_clean():
    assert len(GOLDEN) == 10
    offenders = {r["date"]: _lint(r).lines() for r in GOLDEN if _lint(r).problems}
    assert offenders == {}, offenders


def test_every_archived_original_fails_with_the_named_classes():
    assert len(ORIGINALS) == 10 and [r["date"] for r in ORIGINALS] == [r["date"] for r in GOLDEN]
    results = {r["date"]: _lint(r) for r in ORIGINALS}
    clean = [d for d, res in results.items() if not res.problems]
    assert clean == [], f"an original lints clean: {clean}"
    assert min(len(res.problems) for res in results.values()) >= 10, {d: len(r.problems) for d, r in results.items()}
    every = {d: res.lines() for d, res in results.items()}
    # the critics' RED TEAM block rode exercise 1 on every one of them
    assert all(any("banned (red team)" in p for p in ps) for ps in every.values()), every
    # none opens with the session block (10-25, the chat path, had no session block of any kind)
    assert all(any(p.startswith("L12 [1]") for p in ps) for ps in every.values())
    expected = {
        "2026-10-26": ["banned (kg): '36.5kg'", "text says 3 sets, the rows hold 2 working sets"],  # VOLUME: 3 sets over 2 rows
        "2026-10-23": ["barbell load 192.9 lb is not on a 5 lb step", "text says 2 sets, the rows hold 4 working sets"],
        "2026-10-16": ["barbell load 210.5 lb is not on a 5 lb step"],
        "2026-10-15": ["dumbbell load 89.3 lb is not on a 5 lb step"],
    }
    missing = {d: [m for m in ms if not any(m in p for p in every[d])] for d, ms in expected.items()}
    assert all(not v for v in missing.values()), missing


def test_the_originals_fixture_carries_no_private_text():
    """Public repo: the scrub left no clinical, bodyweight or nutrition text in the archived originals."""
    import re

    text = json.dumps(ORIGINALS, ensure_ascii=False)
    hits = re.findall(r"metoprolol|\bECG\b|[Ss]inus|\bAF\b|cardiolog|protein|lb/wk|weigh-in|\d{3}\.\d lb, |at \d{3}(?:\.\d)? lb\)", text)
    assert hits == [], hits


# ── the owner's rulings, structurally ──────────────────────────────────────────────────────────────────────────────


def test_the_session_block_is_three_lines_with_no_safety_line():
    """Owner 2026-10-27 ~04:50Z: no chest-pain / dizziness / 911 line; the low-energy option is back."""
    block = g.session_block("Upper volume", (8, 9))
    assert block.split("\n") == ["Upper volume · RPE 8–9 on big lifts", g.LOW_ENERGY_LINE, *g.LOAD_RULE_LINES]
    # re-grade #3: a one-set exercise 1 has no later set to step, so its block carries no load rule
    assert g.session_block("Shoulders + arms", (8, 9), ex1_working_sets=1, others_multi=False).split("\n") == [
        "Shoulders + arms · RPE 8–9 on big lifts",
        g.LOW_ENERGY_LINE,
    ]
    # re-grade #4: the session's multi-set lifts still get it, addressed to them (dropping it left them with no rule)
    assert g.session_block("Shoulders + arms", (8, 9), ex1_working_sets=1).split("\n")[2:] == list(g.OTHER_LIFTS_RULE_LINES)
    assert g.OTHER_LIFTS_RULE_LINES[0].startswith("Other lifts: top reps at RPE 7 or less → +10 lb on later sets")
    assert g.phone_lines(block) <= g.SESSION_BLOCK_MAX_LINES
    for word in ("Chest pain", "dizziness", "faint", "911", "heartbeat"):
        assert word not in block
        assert all(word not in e["note"] for r in GOLDEN for e in r["exercises"]), word
    # R3's safeguard as §5's step (re-grade #5: "+5 lb max" was two steps on a 30-lb dumbbell), a stack's plate at any load
    assert "Under 40 lb: one step. Stack: next plate at any load." in g.LOAD_RULE_LINE
    # re-grade #2: RPE 7.5 and 8.5 each sit in a branch; no pins. Re-grade #3: two if/then lines, a unit on every step,
    # no "per hand" (a dumbbell row is already per hand), a stack's step is its next plate
    assert "7.5–8.5 → +5 lb" in g.LOAD_RULE_LINE and "Stack: next plate" in g.LOAD_RULE_LINE and "per hand" not in g.LOAD_RULE_LINE
    assert "pin" not in g.LOAD_RULE_LINE and len(g.LOAD_RULE_LINES) == 2
    assert all(g.phone_lines(ln) <= 2 for ln in g.LOAD_RULE_LINES) and not re.search(r"\+\d+(?:\.\d)?(?![\d.]| lb)", g.LOAD_RULE_LINE)
    for r in GOLDEN:
        # a session whose only cardio is a hard kind (10-23 tempo, 10-25 intervals) promises no easy cardio; the 10-25
        # Shoulders + arms opens on a one-set press, so no load rule
        low = g.LOW_ENERGY_HARD_CARDIO_LINE if r["date"] in ("2026-10-23", "2026-10-25") else g.LOW_ENERGY_LINE
        rule = list(g.OTHER_LIFTS_RULE_LINES) if r["date"] == "2026-10-25" else list(g.LOAD_RULE_LINES)
        assert r["exercises"][0]["note"].split("\n\n", 1)[0].split("\n")[1:] == [low, *rule], r["date"]


def test_the_warm_up_text_is_one_prep_cue_per_family():
    """Owner 2026-10-27 ~04:50Z: at most the #5049 prep movement per compound family; no warm-up block."""
    from training.warmup_sets import WARMUP_MOVEMENT_CUES

    assert set(g.PREP_CUES) == set(WARMUP_MOVEMENT_CUES)
    rt = _by_date(GOLDEN, "2026-10-18")  # bench first: its prep cue is a movement, not the load model's "band"
    rt["exercises"][0]["note"] = rt["exercises"][0]["note"].replace("\n\n", "\n\n" + g.PREP_CUES["bench"] + "\n", 1)
    assert g.PREP_CUES["bench"] in rt["exercises"][0]["note"] and _lint(rt).problems == [], _lint(rt).lines()
    rt = _by_date(GOLDEN, "2026-10-23")
    rt["exercises"][1]["note"] += "\nWarm up: hip hinges, then the ramp sets."
    assert "L1" in _lint(rt).rules()


def test_the_grammar_builders():
    assert g.effort_line((8, 9)) == "RPE 8–9"
    assert g.effort_line((8, 9), (9, 10)) == "RPE 8–9, last set RPE 9–10"
    assert g.cardio_line1("Recumbent", "L11", (4, 5)) == "Recumbent · L11 · RPE 4–5 (full sentences)"
    assert g.cardio_line1("Recumbent", "L11/L12", 8, hard=True) == "Recumbent · L11/L12 · hard RPE 8 (a few words)"
    assert g.carry_line1((8, 9)) == "RPE 8–9 · pick the load per hand"
    assert g.carry_line1((8, 9), 60) == "RPE 8–9 · 60 lb per hand to start" and g.CARRY_LINE1_RE.match(g.carry_line1((8, 9), 60))
    assert g.carry_adjust_line(5) == "Set 1 at RPE 7 or less: +10 lb per hand." and g.CARRY_ADJUST_RE.match(g.carry_adjust_line(5))
    # re-grade #4: the feeler's result rule; #5: its step is the lift's one step today ("no more")
    assert g.pick_load_line() == "W at RPE 5 or less → one step, no more."
    assert (
        g.pick_load_line(step_text="+5 lb per hand") == "W at RPE 5 or less → one step, no more."
        and g.phone_lines(g.pick_load_line(step_text="+5 lb per hand")) == 1
    )
    assert g.pick_load_line(rows_loaded=False) == "W set: up to 8 easy reps, find the load."
    # re-grade #3: the held-top reason IS the load rule on this lift's set 1 (one timeline), in its implement's step
    held = {
        "stack": g.held_top_line(15, stack=True),
        "small": g.held_top_line(15, row_lb=30, per_hand=True, step_lb=5),
        "fixed": g.held_top_line(10, row_lb=95, step_lb=5),
        "one set": g.held_top_line(10, working_sets=1, next_step_lb=5),
    }
    assert held == {
        # re-grade #4: in the load rule's own timeline words ("on later sets" today; "next session" on a one-set lift)
        "stack": "Set 1: 15 reps at RPE 8.5 or less → next plate on later sets.",
        "small": "Set 1: 15 reps at RPE 8.5 or less → +5 lb per hand on later sets.",
        "fixed": "Set 1: 10 reps at RPE 7 or less → +10 lb on later sets; 7.5–8.5 → +5 lb.",
        "one set": "Same load: 10 reps again → +5 lb next session.",
    }
    assert all(g.REASON_RE.match(x) and g.HELD_TOP_RE.match(x) for x in held.values()) and not any(
        g.HELD_TOP_RE.match(x)
        for x in ("Same load: hit 15 again to move it up.", "Same load to start: 15 reps on set 1 at RPE 8.5 or less → next plate.")
    )
    assert g.one_set_line(10, 9, 5, True) == "One set: 10 reps at RPE 9 or less two sessions running → +5 lb per hand."
    assert g.stale_reason_line(g.LIGHTER, "2 years") == "Lighter: first time in 2 years." and g.REASON_RE.match(
        "Lighter: first time in 2 years."
    )
    # re-grade #4: the standard's talk words; too hard shortens the reps at the hard level, never drops to the recovery level
    assert g.interval_escape_line(13, 12) == "As rep 1 ends: full sentences → L13; can't talk → 1 min at L12."
    assert g.phone_lines(g.interval_escape_line(13, 12)) == 2
    assert g.sets_today_clause(2, "first incline in 5 weeks") == "2 sets today: first incline in 5 weeks."
    assert g.reason_line(g.HEAVIER, "15 reps was RPE 7") == "Heavier: 15 reps was RPE 7."
    assert g.delta_word(90, 80, 5) == g.HEAVIER and g.delta_word(80, 90, 5) == g.LIGHTER and g.delta_word(85, 80, 5) is None
    assert g.implement_step_lb("dumbbell", 45) == 2.5 and g.implement_step_lb("dumbbell", 50) == 5.0
    assert g.implement_step_lb("cable", 57.5) is None
    assert g.talk_words_for((6, 7)) == "short phrases" and g.talk_words_for(8) == "a few words"
    for builder, line in (
        (g.EFFORT_RE, g.effort_line((8, 9), (9, 10))),
        (g.CARRY_LINE1_RE, g.carry_line1((8, 9))),
        (g.CARDIO_LINE1_RE, g.cardio_line1("Treadmill", "today 3.0 mph, 6% → 10%", (4, 5))),
        (g.SESSION_LINE_RE, g.session_line("Shoulders + arms", (8, 9))),
        (g.SESSION_LINE_RE, g.fitness_test_line("5-min bike, max level")),
    ):
        assert builder.match(line), line


# ── mutation controls: every rule can fail ─────────────────────────────────────────────────────────────────────────

Mut = Callable[[dict[str, Any]], None]


def _note(i: int, fn: Callable[[str], str]) -> Mut:
    def m(rt: dict[str, Any]) -> None:
        rt["exercises"][i]["note"] = fn(rt["exercises"][i]["note"])

    return m


def _append(i: int, line: str) -> Mut:
    return _note(i, lambda n: n + "\n" + line)


def _rows(i: int, fn: Callable[[list[list[Any]]], list[list[Any]]]) -> Mut:
    def m(rt: dict[str, Any]) -> None:
        rt["exercises"][i]["rows"] = fn(rt["exercises"][i]["rows"])

    return m


def _previous(i: int, lb: float, note_fn: Callable[[str], str] | None = None) -> Mut:
    def m(rt: dict[str, Any]) -> None:
        rt["previous_supplied"] = True
        rt["exercises"][i]["previous_lb"] = lb
        if note_fn:
            rt["exercises"][i]["note"] = note_fn(rt["exercises"][i]["note"])

    return m


def _drop_last_exercise(rt: dict[str, Any]) -> None:
    rt["exercises"].pop()


SAFETY_LINE_RETIRED = "Chest pain, dizziness, faintness or an odd heartbeat → end the session, sit. Fainted, or not gone in 5 min → 911."

# (label, golden date, mutation, the rule that must fire)
MUTATIONS: list[tuple[str, str, Mut, str]] = [
    # L1 — banned vocabulary
    ("kg", "2026-10-26", _append(1, "Last time 40kg."), "L1"),
    ("an issue number", "2026-10-26", _append(2, "See #4503."), "L1"),
    ("ECG text back on the wire", "2026-10-26", _append(1, "Take an ECG first."), "L1"),
    ("cardiology text", "2026-10-26", _append(2, "Tell cardiology today."), "L1"),
    ("@ before RPE", "2026-10-26", _append(1, "Stop @ RPE 9."), "L1"),
    ("a bookkeeping emoji", "2026-10-26", _append(2, "No 🟢 this week."), "L1"),
    ("the RED TEAM block", "2026-10-26", _append(2, "RED TEAM (4 voices): all approve"), "L1"),
    ("load-model jargon (a band)", "2026-10-26", _append(2, "Top of your band."), "L1"),
    # L2 — restated rows
    ("restated rows", "2026-10-26", _append(1, "3 × 8–12 @ 90 lb per hand"), "L2"),
    ("a Last: line", "2026-10-26", _append(2, "Last: 160 lb × 8/8 (Oct 21)."), "L2"),
    ("minutes on cardio line 1", "2026-10-26", _note(7, lambda n: n.replace("Recumbent · L11", "Recumbent · 30 min · L11")), "L2"),
    # L3 — line-1 grammar
    ("a lift line 1 that is not the effort", "2026-10-26", _note(2, lambda n: n.replace("RPE 8–9", "Go hard today", 1)), "L3"),
    (
        "a cardio line 1 off the grammar",
        "2026-10-26",
        _note(7, lambda n: n.replace("Recumbent · L11 · RPE 4–5 (full sentences)", "Bike, easy")),
        "L3",
    ),
    (
        "the retired safety line back in the session block",
        "2026-10-26",
        _note(0, lambda n: n.replace(g.LOAD_RULE_LINE, g.LOAD_RULE_LINE + "\n" + SAFETY_LINE_RETIRED)),
        "L3",
    ),
    # L4 — text agrees with the rows
    ("a set count that is not the rows", "2026-10-26", _rows(0, lambda r: r + [["N", 80, "8–12"]]), "L4"),
    (
        "W text that is not the W rows",
        "2026-10-26",
        lambda rt: (
            _rows(3, lambda r: [["W", None, "5"]] + [[x[0], None, x[2]] for x in r[1:]])(rt),
            _note(3, lambda n: n.replace(n.split("\n")[-1], "W set: up to 8 easy reps, find the load."))(rt),
        ),
        "L4",
    ),
    ("a row two steps off PREVIOUS with no reason", "2026-10-25", _previous(1, 25.0), "L4"),
    (
        "a reason pointing the wrong way",
        "2026-10-26",
        _previous(1, 80.0, lambda n: n.replace("Volume day: chase 12.", "Lighter: chase 12.")),
        "L4",
    ),
    # L5 — loadable steps
    ("an unloadable 192.9 back-off", "2026-10-23", _rows(0, lambda r: r[:4] + [["N", 192.9, "4–6"], ["N", 192.9, "4–6"]]), "L5"),
    ("W rows that do not climb", "2026-10-23", _rows(0, lambda r: [r[1], r[0]] + r[2:]), "L5"),
    # L6 — one effort expression
    ("two efforts on line 1", "2026-10-26", _note(2, lambda n: n.replace("RPE 8–9", "RPE 8–9 RPE 9", 1)), "L6"),
    # L7 — budgets
    ("exercise 1 off the first screen", "2026-10-26", _append(0, "Slow on the way down.\nPause at the chest."), "L7"),
    (
        "a lift note over 4 phone lines",
        "2026-10-26",
        _append(1, "Squeeze at the top of every rep and hold it for one full count, then lower slowly."),
        "L7",
    ),
    # L8 — safety facts
    (
        "HR as the lead cardio target",
        "2026-10-26",
        _note(7, lambda n: n.replace("Recumbent · L11 · RPE 4–5 (full sentences)", "Recumbent · HR avg ≤ 120 bpm")),
        "L8",
    ),
    ("the first press without its cue", "2026-10-26", _note(0, lambda n: n.replace("\nBreathe out on the press.", "")), "L8"),
    (
        "a cue from the wrong family",
        "2026-10-26",
        _note(1, lambda n: n.replace("Breathe out on the pull.", "Breathe out on the press.")),
        "L8",
    ),
    ("a prep cue on the wrong lift", "2026-10-23", _note(1, lambda n: n.replace("Hip hinges first.", "Band pull-aparts first.")), "L8"),
    # L9 — clock lines
    ("a clock number with no min", "2026-10-23", _note(5, lambda n: n.replace("at min 5 and 15", "at 5 and 15")), "L9"),
    ("four levels on one ride", "2026-10-25", _note(6, lambda n: n.replace("else L11", "else L10")), "L9"),
    (
        "a tempo ride with no clock line",
        "2026-10-23",
        _note(5, lambda n: "\n".join(ln for ln in n.split("\n") if not ln.startswith(g.CLOCK_PREFIX))),
        "L9",
    ),
    ("intervals with no start minutes", "2026-10-25", _note(6, lambda n: n.replace("at min 6, 10, 14, 18, 22", "every 4 min")), "L9"),
    # L10 — the watch step
    ("a missing After line", "2026-10-26", _note(7, lambda n: n.replace("\n" + g.AFTER_LINE, "")), "L10"),
    ("an After line with nothing after", "2026-10-26", _drop_last_exercise, "L10"),
    # L11 — units
    ("a DB load without per hand", "2026-10-26", _append(1, "Set 1 over RPE 9 → sets 2–3 at 85 lb."), "L11"),
    ("per hand on a barbell", "2026-10-23", _append(0, "Set 1 over RPE 9 → sets 2–3 at 190 lb per hand."), "L11"),
    ("mph on a bike", "2026-10-26", _note(7, lambda n: n.replace("Recumbent · L11 ·", "Recumbent · L11 at 13.8 mph ·")), "L11"),
    # L12 — the session block heads exercise 1; nothing truncated
    ("exercise 1 without the session block", "2026-10-26", _note(0, lambda n: n.split("\n\n", 1)[1]), "L12"),
    ("a truncated note", "2026-10-26", _append(2, "Chase 12 reps…"), "L12"),
    # L13 — the dumbbell warm-up row (R4)
    ("the first DB compound with no W row", "2026-10-26", _rows(0, lambda r: [x for x in r if x[0] != "W"]), "L13"),
]

OLD_LOAD_RULE = "Top reps at RPE 7 or less → +10 lb (2 pins) on later sets; at RPE 8 → +5 lb (1 pin). Under 40 lb: +5 max. Once per lift."


def _previous_full(i: int, lb: float, reps: float, rpe: float, note_fn: Callable[[str], str] | None = None) -> Mut:
    def m(rt: dict[str, Any]) -> None:
        _previous(i, lb, note_fn)(rt)
        rt["exercises"][i].update(previous_reps=reps, previous_rpe=rpe)

    return m


# #5428 blind re-grade #2 (2026-10-31, draft 40f2c0b5): six defect classes the linter read clean on. Each is a one-line
# break of a clean golden routine, and each must fire its OWN message (label, date, mutation, rule, message fragment).
REGRADE_2_MUTATIONS: list[tuple[str, str, Mut, str, str]] = [
    (
        "New: replaces … over a PREVIOUS",
        "2026-10-26",
        _previous(3, 30.0, lambda n: n.replace("RPE 9–10\n", "RPE 9–10\nNew: replaces Face Pull.\n", 1)),
        "L4",
        "'New: replaces …' over a PREVIOUS",
    ),
    (
        "a drop past one step with only the W line for a reason",
        "2026-10-26",
        _previous(3, 65.0),
        "L4",
        "against PREVIOUS 65 lb with no reason line",
    ),
    (
        "find the load over a loaded row",
        "2026-10-26",
        _note(4, lambda n: n.replace(n.split("\n")[-1], "W set: up to 8 easy reps, find the load.")),
        "L4",
        "find the load",
    ),
    (
        "a held load after a top-of-range PREVIOUS at RPE 8.5, no reason",
        "2026-10-25",
        _previous_full(3, 20.0, 15, 8.5),
        "L4",
        "held at PREVIOUS",
    ),
    (
        "pins on a dumbbell lift",
        "2026-10-26",
        _note(0, lambda n: n.replace("+10 lb on later sets", "+10 lb (2 pins) on later sets")),
        "L11",
        "'pins'",
    ),
    (
        "later sets on a one-set lift",
        "2026-10-25",
        _note(0, lambda n: n.replace(g.LOW_ENERGY_HARD_CARDIO_LINE, g.LOW_ENERGY_HARD_CARDIO_LINE + "\n" + g.LOAD_RULE_LINE)),
        "L11",
        "'later sets'",
    ),
    (
        "the load rule on a one-set exercise 1",
        "2026-10-25",
        _note(0, lambda n: n.replace(g.LOW_ENERGY_HARD_CARDIO_LINE, g.LOW_ENERGY_HARD_CARDIO_LINE + "\n" + g.LOAD_RULE_LINE)),
        "L3",
        "heads a one-set exercise 1",
    ),
    ("exercise 1's effort twice", "2026-10-26", _note(0, lambda n: n.replace("\n\n", "\n\nRPE 8–9\n", 1)), "L6", "repeats the session"),
    (
        "a hold reason against the load rule",
        "2026-10-25",
        _previous_full(3, 20.0, 15, 8.5, lambda n: n + "\nSame load: hit 15 again to move it up."),
        "L4",
        "contradicts the load rule",
    ),
    ("a carry with no adjust rule", "2026-10-25", _note(5, lambda n: n.replace(g.carry_adjust_line(5) + "\n", "")), "L4", "no adjust rule"),
    ("a carry with a last load and no start", "2026-10-25", _previous(5, 60.0), "L4", "names no start"),
    (
        "easy interval minutes with no talk words",
        "2026-10-25",
        _note(6, lambda n: n.replace("else L11 (full sentences)", "else L11")),
        "L9",
        "no talk words",
    ),
    (
        "an escape that steps down to the recovery level",
        "2026-10-25",
        _note(6, lambda n: n.replace("; can't talk → 1 min at L12.", "; none → L11.")),
        "L9",
        "shorter reps at the hard level",
    ),
    (
        "an escape with no too-hard branch",
        "2026-10-25",
        _note(6, lambda n: n.replace("; can't talk → 1 min at L12.", ".")),
        "L9",
        "can't talk",
    ),
    (
        "the old load rule's RPE 8.5 gap",
        "2026-10-26",
        _note(0, lambda n: n.replace(g.LOAD_RULE_LINE, OLD_LOAD_RULE)),
        "L3",
        "session block",
    ),
    ("metres on a carry", "2026-10-25", _append(5, "Walk 60 m."), "L11", "names metres"),
    (
        "a carry row that is not whole steps",
        "2026-10-25",
        _rows(5, lambda r: [["N", None, "45.72 steps"] for _ in r]),
        "L11",
        "whole step count",
    ),
    (
        "easy cardio promised over an intervals-only session",
        "2026-10-25",
        _note(0, lambda n: n.replace(g.LOW_ENERGY_HARD_CARDIO_LINE, g.LOW_ENERGY_LINE)),
        "L3",
        "low-energy line for this session's cardio",
    ),
    (
        "between below his steady level",
        "2026-10-25",
        _note(6, lambda n: n.replace("L11/L12", "L10/L12")),
        "L9",
        "between is his steady level",
    ),
    (
        "no warm-up or cool-down level",
        "2026-10-25",
        _note(6, lambda n: n.replace("else L11 (full sentences)", "L11 between")),
        "L9",
        "before and after",
    ),
    (
        "a talk check at a bare minute",
        "2026-10-25",
        _note(
            6,
            lambda n: n.replace(
                "sentences).\nAs rep 1 ends: full sentences → L13; can't talk → 1 min at L12.",
                "sentences). Full sentences at min 8 → L13 from min 10.",
            ),
        ),
        "L9",
        "bare minute",
    ),
    # re-grade #4 (lint 1.3.0)
    (
        "no load rule for a one-set exercise 1's other lifts",
        "2026-10-25",
        _note(0, lambda n: n.replace("\n" + "\n".join(g.OTHER_LIFTS_RULE_LINES), "")),
        "L3",
        "no load rule for the session's multi-set lifts",
    ),
    (
        "a feeler W line with no result rule",
        "2026-10-26",
        _note(4, lambda n: n.replace(n.split("\n")[-1], "W set: up to 8 easy reps, test the load.")),
        "L4",
        "no result rule",
    ),
    (
        "a carry's start load only in the note",
        "2026-10-25",
        _note(5, lambda n: n.replace("pick the load per hand", "60 lb per hand to start")),
        "L4",
        "not on its rows",
    ),
    ("a two-level escape", "2026-10-25", _note(6, lambda n: n.replace("→ L13;", "→ L14;")), "L9", "more than one level"),
]


def test_every_regrade_2_class_has_a_mutation_control_that_fires_its_own_message():
    silent = []
    for label, date, mutate, rule, fragment in REGRADE_2_MUTATIONS:
        rt = _by_date(GOLDEN, date)
        assert not _lint(rt).problems, (label, "its golden routine must start clean")
        mutate(rt)
        res = _lint(rt)
        if not any(p.rule == rule and fragment in str(p) for p in res.problems):
            silent.append((label, rule, fragment, res.lines()))
    assert silent == [], silent


def test_every_rule_has_a_mutation_control_that_fires():
    assert {rule for *_, rule in MUTATIONS} == set(lint.RULES), "a rule without a mutation control"
    silent = []
    for label, date, mutate, rule in MUTATIONS:
        rt = _by_date(GOLDEN, date)
        assert not _lint(rt).problems, (label, "its golden routine must start clean")
        mutate(rt)
        res = _lint(rt)
        if rule not in res.rules():
            silent.append((label, rule, res.lines()))
    assert silent == [], silent


def test_previous_is_reported_not_checked_when_absent_and_passes_with_a_reason():
    rt = _by_date(GOLDEN, "2026-10-26")
    res = _lint(rt)
    assert any(n.startswith("L4 PREVIOUS") for n in res.not_checked)
    rt["previous_supplied"] = True
    rt["exercises"][1]["previous_lb"] = 80.0  # 90 lb rows, two steps up: "Volume day: chase 12." is the reason
    rt["exercises"][2]["previous_lb"] = [100.0, 100.0]  # a cable stack has no fixed step: never judged (lift_note's rule too)
    res = _lint(rt)
    assert res.problems == [] and not any(n.startswith("L4 PREVIOUS") for n in res.not_checked), res.lines()


# ── the wire: compile a golden routine through the real compiler and lint the body ─────────────────────────────────

LB = 0.45359237
_EQUIPMENT = {"barbell": "barbell", "dumbbell": "dumbbell", "machine": "machine", "cable": "cable"}


def _ir_from_golden(rt: dict[str, Any]) -> tuple[RoutineSpec, str, dict[str, Any], dict[str, str | None]]:
    """(the IR, the session block the compiler is handed, a catalog, each key's cue family) for one golden routine."""
    catalog: dict[str, Any] = {}
    families: dict[str, str | None] = {}
    blocks = []
    session = rt["exercises"][0]["note"].split("\n\n", 1)[0]
    for i, e in enumerate(rt["exercises"]):
        key = "cycling" if e["kind"] == "cardio" else f"k{i}"
        catalog[key] = {"title": e["name"], "equipment": _EQUIPMENT.get(e["kind"], "other"), "anchor_family": e["anchor_family"]}
        if e["kind"] == "carry":
            catalog[key]["hevy_type"] = "short_distance_weight"
        families[key] = e["family"]
        sets = []
        for t, lb, reps in e["rows"]:
            s = Set(type="warmup" if t == "W" else "normal", weight_kg=None if lb is None else lb * LB)
            if reps.endswith(" min"):
                s.duration_seconds = int(reps.split()[0]) * 60
            elif reps.endswith(" steps"):
                # the step count goes on the wire as written (`session_cues.CARRY_EXPOSURE`: `carry_steps` IS the
                # `distance_meters` value; his yards box shows it unconverted, #5373) — never a yards-to-metres conversion
                s.distance_meters = int(reps.split()[0])
            elif "–" in reps:
                lo, hi = reps.split("–")
                s.rep_range_start, s.rep_range_end = int(lo), int(hi)
            else:
                s.reps = int(reps)
            sets.append(s)
        own = e["note"].split("\n\n", 1)[1] if i == 0 else e["note"]
        blocks.append(ExerciseBlock(movement_key=key, sets=sets, notes=own))
    ir = RoutineSpec(routine_id=f"golden-{rt['date']}", target_date=rt["date"], archetype="upper", title=rt["title"], exercises=blocks)
    return ir, session, catalog, families


def test_a_golden_routine_compiled_through_the_wire_lints_clean():
    offenders = {}
    for date in ("2026-10-25", "2026-10-26"):
        ir, session, catalog, families = _ir_from_golden(_by_date(GOLDEN, date))
        body = hevy_compiler.to_create_body(ir, lambda k: f"T-{k}", why_note=session)
        assert body["routine"]["exercises"][0]["notes"].startswith(session + "\n\n")
        res = lint.lint_wire(body, ir, catalog=catalog, family_fn=lambda key, entry: families.get(key))
        if res.problems:
            offenders[date] = res.lines()
        assert any(n.startswith("L4 PREVIOUS") for n in res.not_checked)
    assert offenders == {}, offenders


def test_the_wire_adapter_reads_previous_loads_and_kinds():
    rt = _by_date(GOLDEN, "2026-10-26")
    ir, session, catalog, families = _ir_from_golden(rt)
    ir.inputs_snapshot = {lint.PREVIOUS_LOADS_KEY: {"k1": 80, "k2": {"loads_lb": [140, 140]}}}
    body = hevy_compiler.to_create_body(ir, lambda k: f"T-{k}", why_note=session)
    routine = lint.from_wire(body, ir, catalog=catalog, family_fn=lambda key, entry: families.get(key))
    assert [e.kind for e in routine.exercises][:3] == ["dumbbell", "dumbbell", "cable"]
    assert routine.exercises[0].rows[0] == ("W", 50.0, "8") and routine.exercises[7].kind == "cardio"
    assert routine.previous_supplied and routine.exercises[1].previous_lb == 80.0
    res = lint.lint_routine(routine)
    # the pulldown is two steps over PREVIOUS (140 -> 160) and carries its "Now aiming" reason; the row's "Volume day"
    assert res.problems == [], res.lines()


def test_kind_of_reads_the_catalog():
    assert lint.kind_of("cycling", {"equipment": "machine"}) == "cardio"
    assert lint.kind_of("farmers_walk", {"title": "Farmers Walk", "equipment": "other", "hevy_type": "short_distance_weight"}) == "carry"
    assert lint.kind_of("stretching", {"title": "Stretching", "equipment": "none"}) == "mobility"
    assert lint.kind_of("incline_db_press", {"title": "Incline Bench Press (Dumbbell)", "equipment": "dumbbell"}) == "dumbbell"
    assert lint.kind_of("db_curl", None) == "dumbbell"
    assert lint.family_of("leg_press", {"title": "Leg Press (Machine)", "anchor_family": "squat"}) == "leg_press"
    assert lint.family_of("lat_pulldown", {"title": "Lat Pulldown (Cable)", "anchor_family": "vertical_pull"}) == "pull"
    cat = {"x": {"title": "Squat (Barbell)", "hevy_template_id_hint": "D04AC939"}}
    assert lint.entry_for("tmpl:d04ac939", cat) == cat["x"]


# ── the compiler hook: warn logs, never blocks, never rewrites ─────────────────────────────────────────────────────


def _bad_ir() -> RoutineSpec:
    return RoutineSpec(
        routine_id="r-bad",
        target_date="2026-10-28",
        archetype="upper",
        exercises=[
            ExerciseBlock(movement_key="incline_db_press", sets=[Set(type="normal", weight_kg=36.0, reps=8)], notes="Last: 36kg 8/8/8")
        ],
    )


def test_the_compiler_warns_and_never_changes_the_body(monkeypatch, caplog):
    monkeypatch.setenv(lint.MODE_ENV, "off")
    off = hevy_compiler.to_create_body(_bad_ir(), lambda k: "T1")
    monkeypatch.setenv(lint.MODE_ENV, "warn")
    with caplog.at_level(logging.WARNING, logger="training.hevy_note_lint"):
        warn = hevy_compiler.to_update_body(_bad_ir(), lambda k: "T1")
    assert warn["routine"]["exercises"] == off["routine"]["exercises"]
    msgs = [r.getMessage() for r in caplog.records if r.name == "training.hevy_note_lint"]
    assert len(msgs) == 1 and "hevy note lint (warn)" in msgs[0] and "L12" in msgs[0], msgs


def test_enforce_mode_still_only_logs_at_the_compiler(monkeypatch, caplog):
    monkeypatch.setenv(lint.MODE_ENV, "enforce")
    with caplog.at_level(logging.WARNING, logger="training.hevy_note_lint"):
        body = hevy_compiler.to_create_body(_bad_ir(), lambda k: "T1")
    assert body["routine"]["exercises"][0]["notes"] == "Last: 36kg 8/8/8"
    assert any("hevy note lint (enforce)" in r.getMessage() for r in caplog.records)
    res = lint.lint_wire(body, _bad_ir())
    assert {"L1", "L12"} <= res.rules()  # rules D2's commit gate will refuse on; the compiler only logged them


def test_a_linter_crash_never_blocks_a_write(monkeypatch, caplog):
    def boom(*a: Any, **kw: Any) -> None:
        raise RuntimeError("lint bug")

    monkeypatch.setenv(lint.MODE_ENV, "warn")
    monkeypatch.setattr(lint, "lint_wire", boom)
    with caplog.at_level(logging.WARNING, logger="training.hevy_note_lint"):
        body = hevy_compiler.to_create_body(_bad_ir(), lambda k: "T1")
    assert body["routine"]["exercises"][0]["notes"] == "Last: 36kg 8/8/8"
    assert any("not run (RuntimeError: lint bug)" in r.getMessage() for r in caplog.records)


def test_an_unknown_mode_reads_as_warn(monkeypatch):
    monkeypatch.setenv(lint.MODE_ENV, "bogus")
    assert lint.lint_mode() == "warn"
    monkeypatch.delenv(lint.MODE_ENV, raising=False)
    assert lint.lint_mode() == lint.DEFAULT_MODE == "warn"
