"""tests/test_layoff_return_and_warmup_climb_5428.py — owner ruling 2026-11-10 ("go", a delegated training call).

THE DRAFT (the real nightly draft for 2026-11-11, routine be7aca7a…, read read-only through `routine_repo.get_current`):

  * Torso Rotation, rotated in for the side bend, last logged 2023-04-14:
        RPE 8–9, last set RPE 9–10
        Lighter: first time in 2 years.
        W at RPE 5 or less → one step, no more.
    rows W 100 x 8, then 100 lb x 8–15 four times — a hard band after a two-year gap, and a "warm-up" AT the work.
  * Squat (Barbell), the second compound of a Lower-volume day at 225 x 8–12: ONE W row, 160 x 5. The Romanian deadlift
    ahead of it took the session's first climb (95/130/155), and every later compound got the single 70 % row.

THE RULING. (A) a movement's first session back after a long layoff is easy: its working sets at the charter's
`effort_ceilings.layoff_return_rpe` (6–7, charter 1.41.0) with no last-set target, one load all sets, behind a W row
LIGHTER than the work. "Long layoff" is the OD1 exposure-cap line already in the code, `layoff_tiers.REENTRY_MAX_GAP_DAYS`
(no new threshold). (B) a barbell compound prescribed at 10+ reps climbs at least two W rows.

Mutation controls: each producer change reverted in place (monkeypatch) brings the 11-11 shape back, and each new lint
rule (L14, L15) fires on the live draft's own text and stays quiet on the corrected render.

Clock: pure — a fixed target date and a fixed history; nothing reads the clock (#4848).
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from training import (
    effort_ceilings,
    hevy_compiler,
    hevy_note_grammar as g,
    hevy_note_lint as lint,
    layoff_tiers,
    lift_note,
    session_block,
    warmup_sets,
)
from training.rep_scheme import LB_IN_KG
from training.routine_ir import ExerciseBlock, RoutineSpec, Set

ROOT = pathlib.Path(__file__).resolve().parents[1]
CATALOG: dict[str, Any] = json.loads((ROOT / "config" / "movement_catalog.json").read_text())["movements"]
TARGET = "2026-11-11"
TORSO = "torso_rotation"
SQUAT = "squat_barbell"
RDL = "romanian_deadlift_barbell"


def _kg(lb: float) -> float:
    return lb * LB_IN_KG


def _lb(kg: float | None) -> float | None:
    return None if kg is None else round(kg / LB_IN_KG, 1)


def _n(lb: float, lo: int, hi: int) -> Set:
    return Set(type="normal", weight_kg=_kg(lb), rep_range_start=lo, rep_range_end=hi)


def _blocks() -> list[ExerciseBlock]:
    """The 11-11 Lower-volume draft as the load passes left it (before the warm-up pass and the note composer)."""
    return [
        ExerciseBlock(movement_key=RDL, sets=[_n(185, 8, 10) for _ in range(3)], rationale_tag="anchor:hinge:volume"),
        ExerciseBlock(movement_key=SQUAT, sets=[_n(225, 8, 12) for _ in range(3)], rationale_tag="anchor:squat:volume"),
        ExerciseBlock(movement_key=TORSO, sets=[_n(100, 8, 15) for _ in range(4)], rationale_tag=f"accessory:{TORSO}:accessory"),
    ]


def _history() -> dict[str, list]:
    """Newest first, as `exercise_history` builds it: the RDL and squat this cycle, the torso rotation in 2023 only."""

    def rows(key: str, *sessions: tuple[str, float, int, float]) -> tuple[str, list]:
        tid = CATALOG[key]["hevy_template_id_hint"]
        out = [{"date": d, "sets": [{"weight_kg": _kg(lb), "reps": r, "rpe": rpe}] * 3} for d, lb, r, rpe in sessions]
        return tid, sorted(out, key=lambda s: s["date"], reverse=True)

    return dict(
        [
            rows(RDL, ("2026-11-06", 185, 10, 8)),
            rows(SQUAT, ("2026-10-30", 215, 10, 8)),
            rows(TORSO, ("2023-04-14", 120, 12, None), ("2023-03-30", 120, 10, None)),
        ]
    )


def _draft() -> list[ExerciseBlock]:
    """The two passes the nightly runs, in its order: the warm-up climb, then the note composer (the ramp set no
    exposure cap on the torso rotation: a nearest-band fallback, as on the live draft)."""
    blocks = _blocks()
    warmup_sets.attach_warmups(blocks, CATALOG)
    lift_note.compose_blocks(blocks, CATALOG, load_floors={}, history_index=_history(), target_date=TARGET)
    return blocks


def _by_key(blocks: list[ExerciseBlock], key: str) -> ExerciseBlock:
    return next(b for b in blocks if b.movement_key == key)


def _w(block: ExerciseBlock) -> list[float]:
    return [_lb(s.weight_kg) for s in block.sets if s.type == "warmup"]


def _work_top(block: ExerciseBlock) -> float:
    return max(_lb(s.weight_kg) for s in block.sets if s.type != "warmup")


def _lint(blocks: list[ExerciseBlock]) -> lint.LintResult:
    ir = RoutineSpec(routine_id="r-1111", target_date=TARGET, archetype="lower", title="LOWER-VOLUME", exercises=blocks)
    session_block.place_on_first(ir)
    body = hevy_compiler.to_create_body(ir, lambda k: f"T-{k}", why_note=session_block.why_note_for(ir, ""))
    return lint.lint_wire(body, ir, catalog=CATALOG)


# ── the charter and the threshold ──────────────────────────────────────────────────────────────────────────────────


def test_the_layoff_band_is_the_charters_and_the_long_layoff_line_is_the_od1_one():
    from training import training_charter as tc

    assert effort_ceilings.layoff_return_band() == [6, 7]
    # the 1.41.0 entry, wherever later bumps (#5797's 1.42.0, ...) put the head of the log
    assert tuple(int(x) for x in tc.charter_version().split(".")) >= (1, 41, 0)
    log = next(e for e in tc.charter_value("change_log") if e["version"] == "1.41.0")
    assert "2026-11-10" in log["by"] and "layoff_return_rpe" in log["what"]
    # no new number: the long-layoff line IS the exposure-cap gap
    assert layoff_tiers.REENTRY_MAX_GAP_DAYS == 90
    prev = {"date": "2026-08-12"}  # 91 days before the target
    assert lift_note.is_layoff_return(None, prev, TARGET) is True
    assert lift_note.is_layoff_return(None, {"date": "2026-08-13"}, TARGET) is False  # exactly 90: the hold/re-entry side
    assert lift_note.is_layoff_return(None, None, TARGET) is False  # a lift never logged is new, not a return
    assert lift_note.is_layoff_return({"exposure": 1}, None, TARGET) is True
    assert lift_note.is_layoff_return({"exposure": 2}, prev, TARGET) is False  # exposures 2–3 keep the OD1 cap


# ── (A) the torso rotation ─────────────────────────────────────────────────────────────────────────────────────────


def test_the_torso_rotation_renders_easy_with_a_w_row_below_the_work():
    torso = _by_key(_draft(), TORSO)
    lines = torso.notes.split("\n")
    assert lines[0] == "RPE 6–7", torso.notes
    assert "last set" not in torso.notes and "9–10" not in torso.notes
    assert lines[1] == "Same load all sets: first time in 3 years.", torso.notes  # one load: the load rule's step is off
    assert not any(g.PICK_LOAD_RESULT_RE.match(ln) for ln in lines), "the feeler's step line would undo the easy band"
    assert _w(torso) == [50.0] and _work_top(torso) == 100.0, [(s.type, _lb(s.weight_kg)) for s in torso.sets]
    assert [s.reps for s in torso.sets if s.type == "warmup"] == [8]
    assert sum(1 for s in torso.sets if s.type != "warmup") == 4  # the working sets are untouched


def test_MUTATION_without_the_layoff_treatment_the_torso_rotation_is_the_11_11_draft(monkeypatch):
    monkeypatch.setattr(lift_note, "is_layoff_return", lambda *a, **k: False)
    torso = _by_key(_draft(), TORSO)
    assert torso.notes.split("\n")[0] == "RPE 8–9, last set RPE 9–10"
    assert _w(torso) == [100.0] == [_work_top(torso)]  # the W row AT the work: the live defect


def test_a_capped_first_exposure_reads_the_layoff_band_and_gets_its_light_row():
    blocks = [ExerciseBlock(movement_key=TORSO, sets=[_n(100, 8, 8) for _ in range(3)], rationale_tag=f"accessory:{TORSO}:accessory")]
    caps = layoff_tiers.exposure_caps(CATALOG[TORSO]["hevy_template_id_hint"], _history(), TARGET)
    assert caps and caps["exposure"] == 1
    floors = {"movements": {TORSO: {"ramp": {"exposure_caps": caps}}}}
    lift_note.compose_blocks(blocks, CATALOG, load_floors=floors, history_index=_history(), target_date=TARGET)
    assert blocks[0].notes.split("\n")[:2] == ["RPE 6–7", "Same load all sets: first time in 3 years."]
    assert _w(blocks[0]) == [50.0]
    # exposure 2 keeps OD1's RPE 7 and gets no extra row
    blocks = [ExerciseBlock(movement_key=TORSO, sets=[_n(100, 8, 8) for _ in range(3)], rationale_tag=f"accessory:{TORSO}:accessory")]
    floors = {"movements": {TORSO: {"ramp": {"exposure_caps": {**caps, "exposure": 2}}}}}
    lift_note.compose_blocks(blocks, CATALOG, load_floors=floors, history_index=_history(), target_date=TARGET)
    assert blocks[0].notes.split("\n")[0] == "RPE 7" and _w(blocks[0]) == []


def test_a_critic_layoff_cap_keeps_the_easy_band_and_eases_a_first_return():
    eased = "RPE 6–7\nSame load all sets: first time in 3 years."
    assert session_block.add_capped_reason(eased, "Same load all sets: first time in 3 years.", 7).split("\n")[0] == "RPE 6–7"
    hard = "RPE 8–9, last set RPE 9–10\nFull stretch at the bottom; knees soft."
    first = session_block.add_capped_reason(hard, "Same load all sets: first time in 18 months.", 7)
    assert first.split("\n")[:2] == ["RPE 6–7", "Same load all sets: first time in 18 months."]
    later = session_block.add_capped_reason(hard, "Same load all sets: 2nd session back after 18 months off.", 7)
    assert later.split("\n")[0] == "RPE 7"


# ── (B) the squat ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_volume_squat_climbs_two_w_rows_to_its_work():
    blocks = _draft()
    squat, rdl = _by_key(blocks, SQUAT), _by_key(blocks, RDL)
    assert _w(rdl) == [95.0, 130.0, 155.0]  # the first warmed lift: the 10-23 climb, unchanged
    assert _w(squat) == [115.0, 160.0] and _work_top(squat) == 225.0, [(s.type, _lb(s.weight_kg), s.reps) for s in squat.sets]
    assert [s.reps for s in squat.sets if s.type == "warmup"] == [8, 5]


def test_MUTATION_without_the_high_rep_rung_the_squat_is_the_11_11_draft(monkeypatch):
    monkeypatch.setitem(warmup_sets.WARMUP_PRESCRIPTION, "later_compound_high_rep", warmup_sets.WARMUP_PRESCRIPTION["later_compound"])
    assert _w(_by_key(_draft(), SQUAT)) == [160.0]


def test_a_later_compound_under_10_reps_keeps_its_one_row():
    blocks = _blocks()
    blocks[1].sets = [_n(225, 4, 6) for _ in range(3)]
    warmup_sets.attach_warmups(blocks, CATALOG)
    assert _w(blocks[1]) == [160.0]


# ── the linter: L14 and L15 fire on the live draft's text, and the corrected render is clean of both ──────────────


def test_the_corrected_draft_lints_clean_of_l14_and_l15():
    res = _lint(_draft())
    assert not ({"L14", "L15"} & res.rules()), res.lines()


def test_MUTATION_the_live_11_11_shapes_fail_l14_and_l15():
    blocks = _draft()
    torso, squat = _by_key(blocks, TORSO), _by_key(blocks, SQUAT)
    torso.notes = "RPE 8–9, last set RPE 9–10\nLighter: first time in 2 years.\nW at RPE 5 or less → one step, no more."
    torso.sets = [Set(type="warmup", reps=8, weight_kg=_kg(100))] + [s for s in torso.sets if s.type != "warmup"]
    squat.sets = [Set(type="warmup", reps=5, weight_kg=_kg(160))] + [s for s in squat.sets if s.type != "warmup"]
    lines = _lint(blocks).lines()
    assert any(ln.startswith("L14") and "over the layoff band" in ln for ln in lines), lines
    assert any(ln.startswith("L14") and "not lighter than the work" in ln for ln in lines), lines
    assert any(ln.startswith("L15") and "Squat" in ln for ln in lines), lines
    # and a first session back with NO W row at all is named too
    torso.sets = [s for s in torso.sets if s.type != "warmup"]
    torso.notes = "RPE 6–7\nSame load all sets: first time in 2 years."
    assert any(ln.startswith("L14") and "no W row" in ln for ln in _lint(blocks).lines())
