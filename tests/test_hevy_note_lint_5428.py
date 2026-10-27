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


def _lint(rt: dict[str, Any]) -> lint.LintResult:
    return lint.lint_routine(lint.routine_from_dict(rt))


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
    assert block.split("\n") == ["Upper volume · RPE 8–9 on big lifts", g.LOW_ENERGY_LINE, g.LOAD_RULE_LINE]
    assert g.phone_lines(block) <= g.SESSION_BLOCK_MAX_LINES
    for word in ("Chest pain", "dizziness", "faint", "911", "heartbeat"):
        assert word not in block
        assert all(word not in e["note"] for r in GOLDEN for e in r["exercises"]), word
    assert "Under 40 lb: +5 max" in g.LOAD_RULE_LINE  # R3's safeguard
    for r in GOLDEN:
        assert r["exercises"][0]["note"].split("\n\n", 1)[0].split("\n")[1:] == [g.LOW_ENERGY_LINE, g.LOAD_RULE_LINE], r["date"]


def test_the_warm_up_text_is_one_prep_cue_per_family():
    """Owner 2026-10-27 ~04:50Z: at most the #5049 prep movement per compound family; no warm-up block."""
    from training.warmup_sets import WARMUP_MOVEMENT_CUES

    assert set(g.PREP_CUES) == set(WARMUP_MOVEMENT_CUES)
    rt = _by_date(GOLDEN, "2026-10-23")
    rt["exercises"][1]["note"] += "\nWarm up: hip hinges, then the ramp sets."
    assert "L1" in _lint(rt).rules()


def test_the_grammar_builders():
    assert g.effort_line((8, 9)) == "RPE 8–9"
    assert g.effort_line((8, 9), (9, 10)) == "RPE 8–9, last set RPE 9–10"
    assert g.cardio_line1("Recumbent", "L11", (4, 5)) == "Recumbent · L11 · RPE 4–5 (full sentences)"
    assert g.cardio_line1("Recumbent", "L10/L12", 8, hard=True) == "Recumbent · L10/L12 · hard RPE 8 (a few words)"
    assert g.carry_line1((8, 9)) == "RPE 8–9 · pick the load per hand"
    assert g.pick_load_line() == "W set: up to 8 easy reps, find the load."
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
    ("W text that is not the W rows", "2026-10-26", _rows(3, lambda r: [["W", None, "5"]] + r[1:]), "L4"),
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
    ("four levels on one ride", "2026-10-25", _note(6, lambda n: n.replace("L10 between", "L9 between")), "L9"),
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
    rt["exercises"][2]["previous_lb"] = [160.0, 160.0]  # per-row PREVIOUS, no move
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
                s.distance_meters = round(int(reps.split()[0]) * 0.9144, 2)
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
    assert lint.refusing(res) and {p.rule for p in lint.refusing(res)} <= set(lint.ENFORCE_RULES)


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
