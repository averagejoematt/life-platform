"""tests/test_hevy_note_regrade_5428.py — #5428's second live proof (2026-10-30): a blind four-voice re-grade of three
drafted routines (81fe18c0, be80e308, dde23e6b) graded the notes C+, not A. Seven code defects, each fixed against
`docs/coaching/HEVY_NOTE_STANDARD.md` and held here on the graded wire (the notes as the graders saw them, verbatim in
the GRADED_* strings) with a mutation control that brings the defect back:

  1. The predraft never compiled a body, so the linter never ran on it, and a clean lint logged nothing: "no problem
     line" proved nothing. `nightly_predraft._note_lint` compiles the drafted routine (compile only, offline resolver);
     `check_compiled` logs one `clean` line; the verdict rides in NIGHTLY_PREDRAFT_SUMMARY.
  2. Pick-load staleness was 28 days against §3.3's 180: a hammer curl logged 40 days before read "find the load".
  3. `New: replaces …` was written on a lift PREVIOUS shows he did weeks ago (a face pull 8 days back).
  4. A bike hill climbed five levels (`L11 → L15`) against §3.7's ≤ 3, and L9 counted only the two levels named.
  5. The talk words came from the band's top: `RPE 5–7 (short phrases)`, where RPE 5 is full sentences. And the
     treadmill's clock line said "ride clock".
  6. A layoff set cap whose days-since value was None wrote a bare `3 sets today.` (§6.3 requires the reason).
  7. A layoff set cap kept `last set RPE 9–10` under the +10 lb rule; only the ramp's exposure cap got `RPE 7` +
     `No jumps`.
Plus the addendum's prep-cue item: the #5049 prep clause now rides beside a reason line when the note still fits.

Offline: no Hevy, no AWS writes, no AI. The catalog is the repo's own `config/movement_catalog.json`.
"""

from __future__ import annotations

import ast
import json
import logging
import pathlib
import re
from typing import Any
from unittest.mock import patch

from coach import critics_apply
from training import (
    cardio_menu,
    cardio_note,
    hevy_compiler,
    hevy_note_grammar as g,
    hevy_note_lint as lint,
    lift_note,
    session_block,
)
from training.exercise_history import STALE_AFTER_DAYS as HISTORY_STALE_AFTER_DAYS
from training.rep_scheme import LB_IN_KG
from training.routine_ir import ExerciseBlock, RoutineSpec, Set, deserialize, serialize

ROOT = pathlib.Path(__file__).resolve().parents[1]
CATALOG: dict[str, Any] = json.loads((ROOT / "config" / "movement_catalog.json").read_text())["movements"]
STANDARD = (ROOT / "docs" / "coaching" / "HEVY_NOTE_STANDARD.md").read_text()

# ── the graded wire, verbatim (p5428/grader_routines.md) ─────────────────────────────────────────────────────────────
GRADED_HAMMER_CURL = "RPE 8–9, last set RPE 9–10\nNew: replaces Bicep Curl (Dumbbell).\nW set: up to 8 easy reps, find the load."
GRADED_FACE_PULL = "RPE 8–9, last set RPE 9–10\nNew: replaces Rear Delt Reverse Fly (Machine)."
GRADED_LEG_CURL = "RPE 8–9, last set RPE 9–10\nNew: replaces Seated Leg Curl (Machine).\nW set: up to 8 easy reps, find the load."
GRADED_STANDING_CALF = (
    "RPE 8–9, last set RPE 9–10\n3 sets today.\nW set: up to 8 easy reps, find the load.\nFull stretch at the bottom; knees soft."
)
GRADED_SEATED_CALF = (
    "RPE 8–9, last set RPE 9–10\n3 sets today: first time in 19 weeks.\nW set: up to 8 easy reps, find the load.\n"
    "Full stretch at the bottom; knees soft."
)
GRADED_BIKE_HILL = (
    "Recumbent · L11 → L15 · RPE 5–7 (short phrases)\n"
    "⌚ ride clock: L11 to min 6 · up a level every 2 min to min 14 · down the same to min 22 · L11 to the end"
)
GRADED_TREADMILL_HILL = (
    "Treadmill · today 2.8 mph, 6% → 10% · RPE 5–7 (short phrases)\n"
    "⌚ ride clock: 6% to min 6 · +1% every 2 min to min 14 · down the same to min 22 · 6% to the end"
)
SESSION = (  # the load rule as re-grade #3 (2026-10-31) left it: two lines, a unit on every step
    "Lower heavy · RPE 8–9 on big lifts\nLow energy → first 2 lifts + easy cardio.\n"
    "Top reps at RPE 7 or less → +10 lb on later sets; 7.5–8.5 → +5 lb.\nUnder 40 lb: one step. Stack: next plate at any load. Once per lift."
)
TARGET = "2026-10-30"  # routine 81fe18c0's day; be80e308 / dde23e6b were 10-29


def _kg(lb: float) -> float:
    return lb * LB_IN_KG


def _n(lb: float | None, lo: int, hi: int) -> Set:
    return Set(type="normal", weight_kg=None if lb is None else _kg(lb), rep_range_start=lo, rep_range_end=hi)


def _history(key: str, *sessions: tuple[str, float, int, float | None]) -> dict[str, list]:
    """The generator's history index for one movement: newest first, as `exercise_history` builds it."""
    tid = CATALOG[key]["hevy_template_id_hint"]
    rows = [{"date": d, "sets": [{"weight_kg": _kg(lb), "reps": reps, "rpe": rpe}] * 2} for d, lb, reps, rpe in sessions]
    return {tid: sorted(rows, key=lambda r: r["date"], reverse=True)}


def _accessory(key: str, lb: float, n: int = 2, lo: int = 8, hi: int = 15) -> ExerciseBlock:
    return ExerciseBlock(movement_key=key, sets=[_n(lb, lo, hi) for _ in range(n)], rationale_tag=f"accessory:{key}:accessory")


def _compose(blocks: list[ExerciseBlock], history: dict[str, list], rotations: dict[str, str] | None = None, target: str = TARGET):
    return lift_note.compose_blocks(blocks, CATALOG, load_floors={}, history_index=history, target_date=target, rotations=rotations)


def _lint(ir: RoutineSpec) -> lint.LintResult:
    body = hevy_compiler.to_create_body(ir, lambda k: f"T-{k}", why_note=session_block.why_note_for(ir, ""))
    return lint.lint_wire(body, ir, catalog=CATALOG)


# ── 1. the predraft compiles and lints what it drafted; a clean lint says so ─────────────────────────────────────────


def _clean_ir(rid: str = "r-5428") -> RoutineSpec:
    """A drafted Lower-heavy routine as the predraft leaves it after stage 2: the session block on exercise 1."""
    squat = ExerciseBlock(
        movement_key="squat_barbell",
        sets=[Set(type="warmup", reps=5, weight_kg=_kg(135))] + [_n(225, 4, 6) for _ in range(3)],
        notes=SESSION + "\n\nAnkles + hips first. Brace each rep, breathe between reps.",  # its RPE 8–9 is the session line's
    )
    return RoutineSpec(
        routine_id=rid,
        target_date=TARGET,
        archetype="lower",
        title="Foundation - Lower - 11 - 42",
        exercises=[squat],
        inputs_snapshot={lint.PREVIOUS_LOADS_KEY: {"squat_barbell": {"date": "2026-10-27", "lb": 225.0, "reps": 5, "rpe": 8}}},
    )


class _Repo:
    """The routine repository, every read through the real serializer (the shape DynamoDB stores)."""

    def __init__(self, *routines: RoutineSpec) -> None:
        self.items = {r.routine_id: serialize(r) for r in routines}

    def list_by_date_range(self, start: str, end: str, limit: int = 100) -> list[RoutineSpec]:
        return [deserialize(json.loads(json.dumps(it, default=str))) for it in self.items.values() if start <= it["target_date"] <= end]


def _note_lint(ir: RoutineSpec, caplog) -> dict[str, Any]:
    from mcp import nightly_predraft as npd

    repo = _Repo(ir)
    caplog.set_level(logging.INFO, logger="training.hevy_note_lint")
    with (
        patch("training.routine_repo.list_by_date_range", side_effect=repo.list_by_date_range),
        patch("mcp.tools_hevy_routine._resolve_title_inputs", return_value=(None, "")),
        patch("training.hevy_template_cache.resolve_movement", side_effect=AssertionError("a lint compile resolves nothing")),
        patch("training.hevy_write_client.list_templates", side_effect=AssertionError("a lint compile calls no Hevy")),
    ):
        return npd._note_lint(TARGET, ir.routine_id)


def test_the_predraft_lints_its_drafted_routine_and_a_clean_lint_logs_one_line(monkeypatch, caplog):
    monkeypatch.setenv(lint.MODE_ENV, "warn")
    out = _note_lint(_clean_ir(), caplog)
    assert out["state"] == "clean" and out["problems"] == 0, out
    msgs = [r.getMessage() for r in caplog.records if "hevy note lint" in r.getMessage()]
    assert msgs == ["hevy note lint (warn): clean ('Foundation - Lower - 11 - 42', 1 exercises)"], msgs
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING and "hevy note lint" in r.getMessage()]


def test_MUTATION_a_defective_draft_logs_its_warning_and_no_clean_line(monkeypatch, caplog):
    """Control: the graded bike hill appended to the draft — the WARNING line names it, the clean line does not appear,
    and the summary carries `problems` with the rule ids."""
    from mcp import predraft_summary

    monkeypatch.setenv(lint.MODE_ENV, "warn")
    ir = _clean_ir()
    ir.exercises.append(ExerciseBlock(movement_key="cycling", sets=[Set(type="normal", duration_seconds=1800)], notes=GRADED_BIKE_HILL))
    out = _note_lint(ir, caplog)
    assert out["state"] == "problems" and {"L3", "L9"} <= set(out["rules"]), out
    msgs = [r.getMessage() for r in caplog.records if "hevy note lint" in r.getMessage()]
    # three since re-grade #2: the hill's talk band (L3) and levels (L9), and the session's "+ easy cardio" over a
    # session whose only cardio is now a hill (L3)
    assert len(msgs) == 1 and msgs[0].startswith("hevy note lint (warn): 3 problem(s)") and "clean" not in msgs[0], msgs
    line = predraft_summary.summary_line({"job": "nightly_predraft", "outcome": "drafted", "note_lint": out})
    assert '"note_lint":{"state":"problems","problems":3,"rules":["L3","L9"]}' in line, line
    clean = predraft_summary.summary_line({"note_lint": {"state": "clean", "problems": 0}})
    assert '"note_lint":{"state":"clean"}' in clean and '"note_lint":{"state":"absent"}' in predraft_summary.summary_line({})


def test_the_drafted_outcome_carries_the_lint_and_a_lint_failure_is_named_never_raised(monkeypatch, caplog):
    """The run's DRAFTED outcome is built with `note_lint=_note_lint(...)` (read off the source: a run needs the program,
    the draft and stage 2), and an unreadable routine or a compile failure is a named `not_run`, never the outcome."""
    from mcp import nightly_predraft as npd

    src = pathlib.Path(npd.__file__).read_text()
    run = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "run")
    drafted = [
        c
        for c in ast.walk(run)
        if isinstance(c, ast.Call) and any(k.arg == "outcome" and ast.unparse(k.value) == "DRAFTED" for k in c.keywords)
    ]
    assert len(drafted) == 1 and "note_lint=_note_lint(target, routine_id)" in ast.unparse(drafted[0])
    monkeypatch.setenv(lint.MODE_ENV, "warn")
    with patch("training.routine_repo.list_by_date_range", return_value=[]):
        assert npd._note_lint(TARGET, "nope") == {"state": "not_run", "reason": "the drafted routine is not readable back"}
    with (
        patch("training.routine_repo.list_by_date_range", return_value=[_clean_ir()]),
        patch("mcp.tools_hevy_routine._resolve_title_inputs", return_value=(None, "")),
        patch.object(hevy_compiler, "to_create_body", side_effect=RuntimeError("boom")),
    ):
        assert npd._note_lint(TARGET, "r-5428") == {"state": "not_run", "error": "RuntimeError: boom"}
    monkeypatch.setenv(lint.MODE_ENV, "off")
    with patch("training.routine_repo.list_by_date_range", return_value=[_clean_ir()]):
        assert npd._note_lint(TARGET, "r-5428") == {"state": "off"}


# ── 2 + 3. staleness is 180 days; "New" only on a lift genuinely new to him ──────────────────────────────────────────


def test_a_rotated_lift_he_logged_weeks_ago_is_not_new_and_not_find_the_load():
    """Be80e308's hammer curl (PREVIOUS 22.5 lb × 12 @ RPE 8, 2026-09-20) and face pull (65 lb × 15 @ RPE 9, 10-21): the
    rows carry his own load, so neither is "New" and neither is the pick-load form."""
    curl, face = _accessory("hammer_curl_dumbbell", 22.5), _accessory("face_pull", 65)
    history = {**_history("hammer_curl_dumbbell", ("2026-09-20", 22.5, 12, 8.0)), **_history("face_pull", ("2026-10-21", 65, 15, 9.0))}
    rotations = {"hammer_curl_dumbbell": "Bicep Curl (Dumbbell)", "face_pull": "Rear Delt Reverse Fly (Machine)"}
    rec = _compose([curl, face], history, rotations, target="2026-10-29")
    assert curl.notes == face.notes == "RPE 8–9, last set RPE 9–10", (curl.notes, face.notes)
    assert len(curl.sets) == 2 and not any(s.type == "warmup" for s in curl.sets)  # no feeler W row on his logged load
    assert rec["lift_notes"]["hammer_curl_dumbbell"]["rotation_of"] == "Bicep Curl (Dumbbell)"  # the swap stays stored
    assert rec["lift_notes"]["face_pull"]["reason"] is None and rec["lift_notes"]["face_pull"]["pick_load"] is False


def test_MUTATION_the_28_day_line_brings_back_the_graded_wire(monkeypatch):
    """Control: put the old 28-day line back and the same inputs fall back into the pick-load form. Re-grade #2
    (2026-10-31) closed the second door too: `New: replaces …` needs NO PREVIOUS at all, so even at 28 days the hammer
    curl (PREVIOUS 39 days old, same load) is not "New" — the graded wire minus its New line, W line reworded."""
    monkeypatch.setattr(lift_note, "STALE_AFTER_DAYS", 28)
    curl, face = _accessory("hammer_curl_dumbbell", 22.5), _accessory("face_pull", 65)
    history = {**_history("hammer_curl_dumbbell", ("2026-09-20", 22.5, 12, 8.0)), **_history("face_pull", ("2026-10-21", 65, 15, 9.0))}
    _compose([curl, face], history, {"hammer_curl_dumbbell": "Bicep Curl (Dumbbell)"}, target="2026-10-29")
    assert curl.notes == "RPE 8–9, last set RPE 9–10\nW at RPE 5 or less → one step, no more.", curl.notes
    assert curl.sets[0].type == "warmup" and "New: replaces" in GRADED_HAMMER_CURL
    # the face pull's "New" came from the rotation alone (its PREVIOUS was 8 days old): not stale even at 28 days
    face2 = _accessory("face_pull", 65)
    monkeypatch.setattr(lift_note, "STALE_AFTER_DAYS", 180)
    _compose([face2], _history("face_pull", ("2026-10-21", 65, 15, 9.0)), {"face_pull": "Rear Delt Reverse Fly (Machine)"}, "2026-10-29")
    assert "New: replaces" not in face2.notes and GRADED_FACE_PULL.split("\n")[0] == face2.notes


def test_a_stale_previous_far_off_is_lighter_not_new_and_a_lift_never_logged_keeps_new():
    """81fe18c0's lying leg curl (PREVIOUS 40 lb × 8, 2024-11-29 — 23 months, row 30 lb): stale, so the feeler W row
    leads (§3.3) and the band stays (owner ruling 2026-10-30: no blanket layoff cap). Re-grade #2 (2026-10-31): Hevy
    still shows that PREVIOUS beside the 30-lb row, so the reason slot carries `Lighter: first time in 23 months.`, not
    `New: replaces …` — New is only for a lift with NO PREVIOUS (the 40f2c0b5 machine lateral raise read "New" over 65 lb
    × 10 from 2024 and dropped to 35 lb with no why)."""
    leg = _accessory("lying_leg_curl_machine", 30)
    _compose(
        [leg], _history("lying_leg_curl_machine", ("2024-11-29", 40, 8, None)), {"lying_leg_curl_machine": "Seated Leg Curl (Machine)"}
    )
    assert leg.notes == "RPE 8–9, last set RPE 9–10\nLighter: first time in 23 months.\nW at RPE 5 or less → one step, no more."
    assert leg.sets[0].type == "warmup" and leg.sets[0].reps == g.PICK_LOAD_W_REPS and leg.notes != GRADED_LEG_CURL
    # never logged: New stands, with the feeler line over the engine's start load
    fresh = _accessory("lying_leg_curl_machine", 30)
    _compose([fresh], {}, {"lying_leg_curl_machine": "Seated Leg Curl (Machine)"})
    assert fresh.notes == "RPE 8–9, last set RPE 9–10\nNew: replaces Seated Leg Curl (Machine).\nW at RPE 5 or less → one step, no more."


def test_the_stale_line_is_the_standards_180_days_at_its_boundary():
    """§3.3: "over 180 days old". 180 days is a load to quote; 181 is the pick-load form. One number with the history's
    own `STALE_AFTER_DAYS`, and the standard's sentence carries it."""
    assert lift_note.STALE_AFTER_DAYS == HISTORY_STALE_AFTER_DAYS == 180
    assert "the newest one is over 180 days old" in STANDARD
    assert not lift_note.is_stale({"date": "2026-05-03"}, TARGET)  # 180 days
    assert lift_note.is_stale({"date": "2026-05-02"}, TARGET)  # 181 days
    assert lift_note.is_stale(None, TARGET)


# ── 4 + 5. the hill: ≤ 3 levels, counted through the ladder; the talk words' band; the walk's clock ──────────────────


def _cardio_ir(note: str, key: str = "cycling") -> RoutineSpec:
    squat = _clean_ir().exercises[0]
    # re-grade #2: a session whose only cardio is a hard kind (a hill) promises no easy cardio
    squat.notes = squat.notes.replace(g.LOW_ENERGY_LINE, g.low_energy_line([cardio_note.composed_kind(note) or "easy"]), 1)
    return RoutineSpec(
        routine_id="r-c",
        target_date=TARGET,
        archetype="lower",
        exercises=[squat, ExerciseBlock(movement_key=key, sets=[Set(type="normal", duration_seconds=1800)], notes=note)],
        inputs_snapshot=_clean_ir().inputs_snapshot,
    )


def test_the_graded_hill_fails_lint_on_levels_and_talk_words_and_the_composed_hill_is_clean(monkeypatch):
    monkeypatch.setenv(lint.MODE_ENV, "off")
    assert _lint(_cardio_ir(GRADED_BIKE_HILL)).lines() == [
        "L3 [2] Cycling: RPE 5–7 is not the talk table's row for 'short phrases'",
        "L9 [2] Cycling: 5 levels > 3",
    ]
    facts = {"last_level": 11}
    note, audit = cardio_note.compose(movement_key="cycling", minutes=30, target_date=TARGET, kind="hills", facts=facts)
    assert note == (
        "Recumbent · L11 → L13 · RPE 6–7 (short phrases)\n"
        "⌚ ride clock: L11 to min 10 · up a level every 2 min to min 14 · down the same to min 18 · L11 to the end"
    ), note
    assert audit["rpe"] == [5, 7] and audit["rpe_on_wire"] == [6, 7]  # the menu's band stays on the record
    assert _lint(_cardio_ir(note)).ok, _lint(_cardio_ir(note)).lines()


def test_MUTATION_the_old_level_count_saw_two_levels_on_a_five_level_ladder():
    """Control: the pre-fix L9 counted the L-numbers named on the two lines — 2 — so the graded hill passed it."""
    line1, clock = GRADED_BIKE_HILL.split("\n")
    assert len(set(re.findall(r"L(\d+)", clock)) | set(re.findall(r"L(\d+)", line1))) == 2
    assert lint._levels(line1, clock) == {11, 12, 13, 14, 15}
    assert lint._levels("Recumbent · L11 · RPE 4–5 (full sentences)", "at min 5 and 15, full sentences → one level up") == {11}
    intervals = "L12 2 min at min 6, 10, 14, 18, 22; L10 between. Full sentences at min 8 → L14 from min 10."
    assert lint._levels("Recumbent · L10/L12 · hard RPE 8 (a few words)", intervals) == {10, 12, 14}


def test_talk_words_follow_the_table_not_the_bands_top():
    """§3.7: full sentences 4–5, short phrases 6–7, a few words 8. The old rule took the band's top, so 4–6 read
    "short phrases"; a straddling band now takes the row it overlaps most, and line 1 prints the band clipped to it."""
    assert g.talk_words_for((4, 6)) == "full sentences" and g.talk_words_for((5, 7)) == "short phrases"
    assert g.talk_words_for(8) == "a few words" and g.talk_words_for((4, 5)) == "full sentences"
    assert g.talk_band((5, 7), "short phrases") == (6, 7) and g.talk_band((4, 6), "full sentences") == (4, 5)
    assert g.talk_band((3, 4), "full sentences") == (3, 4)  # the table's ends are open: under 4 is still full sentences
    assert g.talk_agrees((6, 7), "short phrases") and not g.talk_agrees((5, 7), "short phrases")
    for kind in ("easy", "tempo", "hills", "intervals", "incline_treadmill_walk"):
        band, words = cardio_note.wire_band(kind), cardio_note.talk_words(kind)
        assert g.talk_agrees(band, words), (kind, band, words)
    # the stage-1 pick reads the same band as the note (#5201: one prescription)
    assert cardio_menu.effort_words("incline_treadmill_walk") == "RPE 4–5, full sentences"
    assert cardio_menu.effort_words("hills").startswith("RPE 6–7, ")


def test_a_treadmill_hill_reads_the_walk_clock_and_a_bike_the_ride_clock(monkeypatch):
    monkeypatch.setenv(lint.MODE_ENV, "off")
    sessions = [{"date": "2026-10-20", "note": "2.8 / 6"}]
    note, _ = cardio_note.compose(movement_key="treadmill", minutes=30, target_date=TARGET, kind="hills", treadmill_sessions=sessions)
    line1, clock = note.split("\n")
    assert line1.endswith("6% → 10% · RPE 6–7 (short phrases)") and clock.startswith("⌚ walk clock: 6% to min 6"), note
    assert cardio_note.clock_of(note, 30) is not None  # the adherence reader reads the walk clock back
    assert _lint(_cardio_ir(note, "treadmill")).ok, _lint(_cardio_ir(note, "treadmill")).lines()
    assert g.clock_line("x", "Recumbent") == "⌚ ride clock: x" and g.clock_line("x", "Treadmill") == "⌚ walk clock: x"
    # control: the walk clock line removed, a hill ride has no clock line — L9 still sees that on a treadmill
    assert "L9 [2] Treadmill: a tempo, hill or interval ride without a ⌚ clock line" in _lint(_cardio_ir(line1, "treadmill")).lines()
    graded = _lint(_cardio_ir(GRADED_TREADMILL_HILL, "treadmill")).lines()
    assert graded == ["L3 [2] Treadmill: RPE 5–7 is not the talk table's row for 'short phrases'"], graded


# ── 6 + 7. a critic's layoff cap: never a bare cap, and the capped exposure's effort ─────────────────────────────────


def _calf_ir(key: str, prev_date: str | None, notes: str, n: int = 4) -> RoutineSpec:
    block = ExerciseBlock(movement_key=key, sets=[Set(type="warmup", reps=8)] + [_n(120, 8, 15) for _ in range(n)], notes=notes)
    prev = {key: {"date": prev_date, "lb": 330.0, "reps": 21, "rpe": None}} if prev_date else {}
    squat = _clean_ir().exercises[0]
    return RoutineSpec(
        routine_id="r-cap",
        target_date=TARGET,
        archetype="lower",
        exercises=[squat, block],
        inputs_snapshot={lint.PREVIOUS_LOADS_KEY: {**_clean_ir().inputs_snapshot[lint.PREVIOUS_LOADS_KEY], **prev}},
    )


def _cap(ir: RoutineSpec, value: Any, to: int = 3) -> list[dict[str, Any]]:
    """The joints critic's governed stale-lift change, as `critics.deterministic_verdict` emits it (`to`: WORKING sets)."""
    verdict = {"critic": "joints_tendons", "verdict": "change", "metric": "days_since_movement[1]", "value": value}
    return critics_apply.apply_changes(ir, [{**verdict, "field": "exercises[1].set_count", "to": to}])


STANDING_CALF_COMPOSED = "RPE 8–9, last set RPE 9–10\nW at RPE 5 or less → one step, no more.\nFull stretch at the bottom; knees soft."


def test_a_layoff_cap_with_no_days_since_value_reads_its_gap_off_previous(monkeypatch):
    """81fe18c0's standing calf raise: days-since None (nothing in the critic's 180-day read), PREVIOUS 2025-05-14 —
    18 months. The graded wire was the bare `3 sets today.`; the cap is over 90 days, so it is the capped exposure."""
    monkeypatch.setenv(lint.MODE_ENV, "off")
    ir = _calf_ir("standing_calf_raise_machine", "2025-05-14", STANDING_CALF_COMPOSED)
    recs = _cap(ir, None)
    assert recs[0]["applied"] and recs[0]["clauses"] == [
        {"movement_key": "standing_calf_raise_machine", "clause": "No jumps: 3 sets today, 18 months off.", "effort_capped": True}
    ]
    assert ir.exercises[1].notes == (
        "RPE 7\nNo jumps: 3 sets today, 18 months off.\nW at RPE 5 or less → one step, no more.\nFull stretch at the bottom; knees soft."
    )
    assert ir.exercises[1].notes != GRADED_STANDING_CALF and _lint(ir).ok, _lint(ir).lines()


def test_MUTATION_no_layoff_clause_is_ever_bare():
    """Control: `applied_clause` with no reason IS the graded bare cap — so the guard is that a layoff reason is never
    None: the verdict's value, else PREVIOUS's gap, else `back after a break`; and a gap nobody can read is capped."""
    assert session_block.applied_clause("set_count", working_sets=3, reason=None) == "3 sets today."
    v = {"critic": "joints_tendons", "metric": "days_since_movement[1]", "value": None}
    assert session_block.change_reason(v) == session_block.BREAK_WORDS
    assert session_block.change_reason(v, 40) == "first time in 6 weeks"
    assert session_block.change_reason({**v, "value": 3}) == session_block.BREAK_WORDS  # exposure 2 after a break
    assert session_block.layoff_gap(v, "2025-05-14", TARGET) == 534 and session_block.layoff_gap(v, None, TARGET) is None
    assert session_block.capped_clause(3, None) == "No jumps: 3 sets today, new to the log."
    for clause in ("No jumps: 3 sets today, 18 months off.", "No jumps: 1 set today, new to the log."):
        assert g.phone_lines(clause) == 1 and g.REASON_RE.match(clause) and g.SET_COUNT_RE.search(clause), clause
    # an uncapped layoff (a 40-day gap) keeps the plain clause, reason and all
    ir = _calf_ir("standing_calf_raise_machine", "2026-09-20", STANDING_CALF_COMPOSED)
    recs = _cap(ir, None)
    assert recs[0]["clauses"][0]["clause"] == "3 sets today: first time in 6 weeks." and ir.exercises[1].notes.startswith("RPE 8–9, last")


def test_a_layoff_set_cap_over_90_days_takes_the_capped_exposures_effort(monkeypatch):
    """Dde23e6b's seated calf raise: PREVIOUS 90 lb × 15 @ RPE 9 on 2026-06-20 (133 days), capped 4 → 3 by the joints
    critic. The graded wire kept `last set RPE 9–10` under the +10 lb rule; now `RPE 7` and the `No jumps` reason."""
    monkeypatch.setenv(lint.MODE_ENV, "off")
    calf = _accessory("seated_calf_raise", 90, n=4)
    _compose(
        [calf], _history("seated_calf_raise", ("2026-06-20", 90, 15, 9.0)), {"seated_calf_raise": "Calf Press (Machine)"}, "2026-10-31"
    )
    assert calf.notes == "RPE 8–9, last set RPE 9–10\nFull stretch at the bottom; knees soft."  # 133 days: fresh, not New
    ir = _calf_ir("seated_calf_raise", "2026-06-20", calf.notes)
    ir.exercises[1] = calf
    _cap(ir, 133, to=3)
    assert calf.notes == "RPE 7\nNo jumps: 3 sets today, 19 weeks off.\nFull stretch at the bottom; knees soft.", calf.notes
    assert calf.notes != GRADED_SEATED_CALF and _lint(ir).ok, _lint(ir).lines()


def test_MUTATION_a_cap_inside_90_days_keeps_the_band_as_the_a_grade_corpus_does():
    """Control: the A-grade incline press, `2 sets today: first incline in 5 weeks.` under RPE 8–9 — a 35-day cap is not
    OD1's capped exposure, so line 1 and the plain clause stand. And a ramp-capped lift's `No jumps` line merges."""
    ir = _calf_ir("standing_calf_raise_machine", "2026-09-25", "RPE 8–9, last set RPE 9–10\nFull stretch at the bottom; knees soft.")
    _cap(ir, 35)
    assert (
        ir.exercises[1].notes == "RPE 8–9, last set RPE 9–10\n3 sets today: first time in 5 weeks.\nFull stretch at the bottom; knees soft."
    )
    capped = "RPE 7\nNo jumps today: session 2 back after a break.\nFull stretch at the bottom; knees soft."
    ir = _calf_ir("standing_calf_raise_machine", "2026-10-27", capped)
    _cap(ir, 3)
    assert ir.exercises[1].notes == "RPE 7\nNo jumps: 3 sets today, session 2 back.\nFull stretch at the bottom; knees soft."
    assert session_block.add_capped_reason(ir.exercises[1].notes, "No jumps: 3 sets today, session 2 back.", 7) == ir.exercises[1].notes


def test_a_ramp_capped_first_exposure_names_its_gap():
    """81fe18c0's split squat (PREVIOUS 2025-04-08): the ramp's exposure cap, exposure 1 — the gap, not 'session 1'."""
    caps = {"exposure": 1, "rpe_max": 7, "reps_max": 8, "gap_days": 540}
    assert lift_note.no_jumps_line(caps) == "No jumps: first time in 18 months."
    assert lift_note.no_jumps_line({**caps, "exposure": 2}) == "No jumps today: session 2 back after a break."
    assert g.gap_text(10) == "10 days" and g.gap_text(35) == "5 weeks" and g.gap_text(133) == "19 weeks" and g.gap_text(800) == "2 years"


# ── the addendum: the prep cue rides beside a reason when the note still fits ────────────────────────────────────────


def test_the_squat_prep_cue_stays_beside_a_reason_line_when_it_fits():
    """Dde23e6b's squat (exercise 2): `Volume day: chase 12.` and the squat's prep + family cue — 4 phone lines. The
    graded note dropped `Ankles + hips first.` whenever any reason line was present."""
    hinge = ExerciseBlock(movement_key="deadlift_trap_bar", sets=[_n(235, 8, 12) for _ in range(3)], rationale_tag="anchor:hinge:volume")
    squat = ExerciseBlock(movement_key="squat_barbell", sets=[_n(215, 8, 12) for _ in range(3)], rationale_tag="anchor:squat:volume")
    history = {**_history("deadlift_trap_bar", ("2026-10-19", 235, 8, 8.5)), **_history("squat_barbell", ("2026-10-23", 265, 4, 9.0))}
    _compose([hinge, squat], history, target="2026-10-29")
    assert squat.notes == "RPE 8–9\nVolume day: chase 12.\nAnkles + hips first. Brace each rep, breathe between reps.", squat.notes
    assert g.phone_lines(squat.notes) == g.LIFT_MAX_LINES


def test_MUTATION_a_critic_clause_that_overflows_drops_the_prep_clause_not_the_family_cue():
    """Control: a critic clause inserted under a 4-line note with a prep clause would be 5 lines — the optional prep
    goes (R8: "if overkill skip"); the breathing cue (§6.1) stays."""
    note = "RPE 8–9\nW set: up to 8 easy reps, find the load.\nAnkles + hips first. Brace each rep, breathe between reps."
    out = session_block.add_reason(note, "2 sets today: first time in 5 weeks.")
    assert (
        out
        == "RPE 8–9\n2 sets today: first time in 5 weeks.\nW set: up to 8 easy reps, find the load.\nBrace each rep, breathe between reps."
    )
    assert g.phone_lines(out) == g.LIFT_MAX_LINES
    assert session_block.add_reason("RPE 8–9\nAnkles + hips first. Brace each rep, breathe between reps.", "2 sets today.").endswith(
        "Ankles + hips first. Brace each rep, breathe between reps."
    )  # it fits: the prep stays
