"""tests/test_hevy_session_block_5428.py — exercise 1 opens with the three-line session block; the critics stay stored (#5428, Lane A).

Owner rulings 2026-10-27 (latest wins over HEVY_NOTE_STANDARD §3.1): the block is exactly the session line, the
low-energy line and the load rule. No safety or medical line, no daily gate, no Whoop-band header, no bookkeeping,
no provenance, no RED TEAM block, no `applied:` line. The critics' record stays on `inputs_snapshot["critics"]`.

Fixtures are synthetic: the 10-26 UPPER-VOLUME and 10-27 LOWER-VOLUME shapes with public loads only (loads are
ruled public) — no body, nutrition or clinical value. No clock is read: every date is passed in.
"""

from __future__ import annotations

import os
import pathlib
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO))

from coach import critics  # noqa: E402
from training import cardio_note, session_block, standing_constraints as sc  # noqa: E402
from training.hevy_compiler import to_create_body  # noqa: E402
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402
from training.routine_title import format_why_note  # noqa: E402

from mcp import (
    draft_standing_constraint as dcg,  # noqa: E402
    tools_hevy_routine as thr,  # noqa: E402
    tools_plan as tp,  # noqa: E402
)
from mcp.recovery_authoring import derive_training_context  # noqa: E402

LB = 0.45359237
MEMORY_TEXT = "STANDING: (1) one. (2) two. (3) three. (4) PLACEHOLDER-STOP-LIST. (5) five."
# #5428 re-grade #2 (2026-10-31): RPE 7.5–8.5 is the one-step branch; no pins; per hand; "sets left", never "later sets"
LOAD_RULE = "Top reps at RPE 7 or less → +10 lb on sets left; 7.5–8.5 → +5. Under 40 lb: +5 max. Dumbbells per hand. Once per lift."
UPPER_BLOCK = "Upper volume · RPE 8–9 on big lifts\nLow energy → first 2 lifts + easy cardio.\n" + LOAD_RULE
LOWER_BLOCK = "Lower volume · RPE 8–9 on big lifts\nLow energy → first 2 lifts + easy cardio.\n" + LOAD_RULE

# What Lane A must keep off every Hevy note (HEVY_NOTE_STANDARD §5 L1, owner rulings 2026-10-27).
BANNED = (
    "ECG",
    "Sinus",
    "sinus",
    "cardiolog",
    "metoprolol",
    "beta-blocker",
    "Whoop",
    "GATE",
    "Chest pain",
    "911",
    "RED TEAM",
    "APPROVE",
    "applied:",
    "inputs_current_through",
    "Loaded lifting",
    "protein",
    "lb/wk",
    "🟢",
    "🟡",
    "🔴",
    "Optional if",
    "subtract-only",
    "never up",
    "critic",
    "joints_tendons",
    "bpm",
    "#",
)

# 10-26's recorded verdict shapes (reasons replaced by placeholders; the metric is a training gap, not a health value)
VERDICTS_10_26 = [
    {
        "critic": "muscle_defense",
        "verdict": "change",
        "field": "session.total_sets",
        "to": "hold",
        "metric": "m",
        "value": 1,
        "reason": "x",
    },
    {
        "critic": "joints_tendons",
        "verdict": "change",
        "field": "exercises[0].set_count",
        "to": "2.0",
        "metric": "days_since_movement[0]",
        "value": 37,
        "reason": "exposure 1 back after 37 days — 3 -> 2 working sets",
    },
    {"critic": "rate_advocate", "verdict": "change", "field": None, "metric": "rate_ceiling", "value": "tripped", "reason": "x"},
]


def _lift(key: str, note: str, work_lb: float, n: int, warm_lb: float | None = None, tier: int = 2) -> ExerciseBlock:
    warm = [Set(type="warmup", weight_kg=warm_lb * LB, reps=8)] if warm_lb else []
    work = [Set(weight_kg=work_lb * LB, rep_range_start=8, rep_range_end=12) for _ in range(n)]
    return ExerciseBlock(movement_key=key, sets=warm + work, notes=note, skill_tier=tier, rationale_tag=f"anchor:{key}")


def _upper_volume(day: str) -> RoutineSpec:
    """The 10-26 UPPER-VOLUME shape: incline DB press (W 50 + 3 working at 80 per hand), row, pulldown, cardio."""
    return RoutineSpec(
        routine_id=f"fixture-5428-{day}",
        target_date=day,
        archetype="upper",
        source_action="draft",
        inputs_snapshot={"calendar": {"session_role": "upper_volume"}},
        exercises=[
            _lift("incline_db_press", "RPE 8–9\nBreathe out on the press.", 80, 3, warm_lb=50),
            _lift("db_row", "RPE 8–9\nVolume day: chase 12.\nBreathe out on the pull.", 90, 3),
            _lift("lat_pulldown", "RPE 8–9", 160, 2, tier=1),
            ExerciseBlock(movement_key="cycling", sets=[Set(duration_seconds=1800)], notes="Recumbent · L11 · RPE 4–5 (full sentences)"),
        ],
    )


def _lower_volume(day: str) -> RoutineSpec:
    """The 10-27 LOWER-VOLUME shape: trap-bar deadlift with barbell warm-ups, leg press, calf press."""
    return RoutineSpec(
        routine_id=f"fixture-5428-{day}",
        target_date=day,
        archetype="lower",
        source_action="draft",
        inputs_snapshot={"calendar": {"session_role": "lower_volume"}},
        exercises=[
            _lift("trap_bar_deadlift", "RPE 8–9\nBrace; breathe out on the way up.", 215, 3, warm_lb=110),
            _lift("leg_press", "RPE 8–9\nAs deep as your hips stay on the pad.", 270, 3),
            _lift("calf_press", "RPE 8–9, last set RPE 9–10", 180, 2, tier=1),
        ],
    )


def _draft(ir: RoutineSpec) -> dict:
    """The draft path's own step (`_action_draft` → `gate_draft` → `_apply_recovery_adaptation`), every read injected."""
    constraint = dcg.read_standing_constraint(ir.target_date, memory_reader=lambda sk: MEMORY_TEXT)
    ctx = derive_training_context(2, "moderate", ir.target_date)
    return thr._apply_recovery_adaptation(ir, ctx, "2026-10-26", constraint, "protein floor missed 6 of 7")


def _stage_2(ir: RoutineSpec, verdicts: list[dict]) -> list[dict]:
    """`_run_stage_2`'s apply + placement steps, with the recorded verdicts (the model and the evidence reads are not the unit)."""
    changes = critics.apply_changes(ir, verdicts)
    ir.inputs_snapshot = {**ir.inputs_snapshot, "critics": {"engine": critics.CRITICS_VERSION, "verdicts": verdicts, "changes": changes}}
    tp._place_block_on_first_exercise(ir)
    return changes


def _wire(ir: RoutineSpec) -> list[dict]:
    why = session_block.why_note_for(ir, format_why_note(ir))
    return to_create_body(ir, lambda k: "T-" + k, why_note=why)["routine"]["exercises"]


# ── the block itself ─────────────────────────────────────────────────────────────
def test_the_block_is_exactly_three_lines_from_the_charter():
    assert session_block.render("Upper volume", [8, 9], 5) == UPPER_BLOCK
    ir = _upper_volume("2026-10-28")
    assert session_block.render_for(ir) == UPPER_BLOCK, "the charter's compounds band and plate step give the ruled text"
    assert session_block.day_label("shoulders_arms", "upper") == "Shoulders + arms"
    assert session_block.day_label(None, "custom") == "Session"
    # an unreadable charter names no number it cannot read (absence is absence)
    assert session_block.render("Lower heavy", None, None).split("\n")[0] == "Lower heavy"


def test_a_cardio_only_session_gets_no_block():
    ir = RoutineSpec(routine_id="c", target_date="2026-10-28", archetype="custom", exercises=[_upper_volume("2026-10-28").exercises[-1]])
    assert session_block.place_on_first(ir) is None and not session_block.split(ir.exercises[0].notes)[0]


# ── the two shapes, end to end through the draft + stage 2 + compiler ──────────────
def test_the_10_26_upper_volume_shape_exercise_1_is_the_block_plus_its_own_note():
    ir = _upper_volume("2026-10-28")
    structured = _draft(ir)
    changes = _stage_2(ir, VERDICTS_10_26)
    wire = _wire(ir)
    assert wire[0]["notes"] == UPPER_BLOCK + "\n\nRPE 8–9\n2 sets today: first time in 5 weeks.\nBreathe out on the press."
    # the set count in the clause equals the working rows, and the warm-up row survived the cut
    assert [s["type"] for s in wire[0]["sets"]] == ["warmup", "normal", "normal"]
    assert [c["clauses"] for c in changes if c.get("applied")] == [
        [{"movement_key": "incline_db_press", "clause": "2 sets today: first time in 5 weeks."}]
    ]
    # nothing else moved: the other lifts keep their own notes byte for byte
    assert wire[1]["notes"] == "RPE 8–9\nVolume day: chase 12.\nBreathe out on the pull."
    # what left the wire is STORED on the routine
    snap = ir.inputs_snapshot
    assert snap["critics"]["verdicts"] == VERDICTS_10_26 and "RED TEAM (" in critics.notes_block(ir)
    assert snap["inputs_current_through"] == "2026-10-26"
    assert snap["recovery_branches"]["green_withheld"] == "protein floor missed 6 of 7"
    assert snap["recovery_branches"]["session"]["loaded_lifting_streak"] == 2
    assert set(structured["exercises"]) == {"incline_db_press", "db_row"}, "the top-set branches stay stored for adherence"


def test_the_10_27_lower_volume_shape_exercise_1_is_the_block_plus_its_own_note():
    ir = _lower_volume("2026-10-27")
    _draft(ir)
    _stage_2(ir, [v for v in VERDICTS_10_26 if v["critic"] != "joints_tendons"])
    wire = _wire(ir)
    assert wire[0]["notes"] == LOWER_BLOCK + "\n\nRPE 8–9\nBrace; breathe out on the way up."
    assert [n["notes"] for n in wire[1:]] == ["RPE 8–9\nAs deep as your hips stay on the pad.", "RPE 8–9, last set RPE 9–10"]


def test_no_banned_token_reaches_any_note_and_the_scan_can_fail():
    for ir in (_upper_volume("2026-10-28"), _lower_volume("2026-10-27"), _upper_volume("2026-11-02")):
        _draft(ir)
        _stage_2(ir, VERDICTS_10_26)
        notes = "\n".join(e["notes"] or "" for e in _wire(ir))
        assert not [t for t in BANNED if t in notes], (ir.target_date, [t for t in BANNED if t in notes])
        assert notes.count("Low energy →") == 1 and notes.count("on big lifts") == 1, "one session line, never a second WHY line"
    # mutation control: a draft dated before the gate's retirement still writes the gate, and the scan sees it
    old = _upper_volume("2026-10-26")
    _draft(old)
    old_notes = "\n".join(e["notes"] or "" for e in _wire(old))
    assert "ECG" in old_notes and "inputs_current_through" in old_notes


# ── the constraint: the daily gate retired by date, the record and its HR half kept ──
def test_the_daily_gate_is_retired_by_its_date_and_the_record_is_history():
    c = sc.active_constraint("2026-10-28")
    assert c is not None and c["id"] == "hr_regime_change_2026_10_10", "the record is kept"
    assert c["hr_prescriptions_allowed"] is False, "its HR half still keeps an HR target off the cardio note"
    assert sc.daily_gate_active(c, "2026-10-26") is True and sc.daily_gate_active(c, "2026-10-27") is False
    assert sc.daily_gate_active(c, None) is True, "a caller naming no day keeps the pre-#5428 output"
    assert c["provenance"]["daily_gate_retired_from"].startswith("owner")


# ── bug 1: the set-count cut counts and pops WORKING sets only ─────────────────────
def _old_pop(ex: ExerciseBlock, n: int) -> None:
    while len(ex.sets) > n:
        ex.sets.pop()


def test_a_set_count_cut_keeps_every_warm_up_row():
    ir = RoutineSpec(routine_id="w", target_date="2026-10-28", archetype="upper", exercises=[_lift("bench", "RPE 8–9", 185, 4, warm_lb=95)])
    ir.exercises[0].sets[1:1] = [Set(type="warmup", weight_kg=135 * LB, reps=5), Set(type="warmup", weight_kg=165 * LB, reps=3)]
    assert [s.type for s in ir.exercises[0].sets] == ["warmup"] * 3 + ["normal"] * 4
    [rec] = critics.apply_changes(ir, [{"critic": "joints_tendons", "verdict": "change", "field": "exercises[0].set_count", "to": 2}])
    assert rec["applied"] is True
    assert [s.type for s in ir.exercises[0].sets] == ["warmup"] * 3 + ["normal"] * 2
    assert rec["clauses"][0]["clause"] == "2 sets today: a lighter day for the joints."
    # mutation control: the pre-#5428 pop (`len(ex.sets)`) on the same block leaves 2 W rows and no working set
    again = _lift("bench", "", 185, 4, warm_lb=95)
    again.sets[1:1] = [Set(type="warmup", weight_kg=135 * LB, reps=5), Set(type="warmup", weight_kg=165 * LB, reps=3)]
    _old_pop(again, 2)
    assert [s.type for s in again.sets] == ["warmup", "warmup"], "the fixture discriminates: the old pop leaves no working set"


def test_a_set_count_above_the_working_sets_is_refused_by_name():
    ir = RoutineSpec(routine_id="w", target_date="2026-10-28", archetype="upper", exercises=[_lift("bench", "RPE 8–9", 185, 2, warm_lb=95)])
    [rec] = critics.apply_changes(ir, [{"critic": "joints_tendons", "verdict": "change", "field": "exercises[0].set_count", "to": 3}])
    assert rec["applied"] is False and "no critic adds sets (set_count 2 -> 3" in rec["why"]
    assert ir.exercises[0].notes == "RPE 8–9", "an unapplied change writes no clause"


# ── bug 2: the cardio swap goes through the composer, never an HR target ─────────────
def test_the_cardio_swap_is_the_composers_note_with_no_hr_target():
    ir = _upper_volume("2026-10-28")
    ir.exercises[-1] = ExerciseBlock(movement_key="treadmill", sets=[Set(duration_seconds=1800)], notes="Treadmill · 30 min")
    [rec] = critics.apply_changes(
        ir, [{"critic": "joints_tendons", "verdict": "change", "field": "exercises[3].movement_key", "to": "cycling"}]
    )
    assert rec["applied"] is True
    swapped = ir.exercises[3]
    want, _ = cardio_note.compose(
        movement_key="cycling",
        minutes=30,
        target_date="2026-10-28",
        archetype="upper",
        constraint=sc.active_constraint("2026-10-28"),
    )
    assert swapped.movement_key == "cycling" and swapped.notes == want
    assert cardio_note.LINE1_RE.match(swapped.notes.split("\n")[0])
    assert not [t for t in ("bpm", "#", "joints", "swapped", "critic") if t in swapped.notes]
    # mutation control: the pre-#5428 literal carried exactly what this scan refuses
    old = "Cycling (recumbent), same duration, HR avg ≤ 120 bpm (target 105) — swapped from treadmill by joints_tendons (#4387)"
    assert [t for t in ("bpm", "#", "joints", "swapped") if t in old] == ["bpm", "#", "joints", "swapped"]


def test_a_critic_load_lands_on_a_plate_step_with_its_clause():
    ir = _upper_volume("2026-10-28")
    [rec] = critics.apply_changes(
        ir, [{"critic": "blueprint_historian", "verdict": "change", "field": "exercises[2].weight_lbs", "to": 148.6}]
    )
    assert rec["applied"] is True
    assert {round(s.weight_kg / LB, 1) for s in ir.exercises[2].sets} == {150.0}
    assert ir.exercises[2].notes == "RPE 8–9\nLighter today."


# ── the clause grammar ────────────────────────────────────────────────────────────
def test_the_clause_is_plain_short_and_written_once():
    assert (
        session_block.applied_clause("set_count", working_sets=1, reason="first time in 10 days") == "1 set today: first time in 10 days."
    )
    assert session_block.applied_clause("total_sets", working_sets=3, reason="a lighter day for the joints") == (
        "3 sets today: a lighter day for the joints."
    )
    assert session_block.applied_clause("drop") is None and session_block.applied_clause("movement_key") is None
    for clause in (
        session_block.applied_clause(k, working_sets=2, reason=session_block.change_reason(v))
        for k in ("set_count", "weight_lbs", "reps")
        for v in VERDICTS_10_26
    ):
        assert clause and len(clause) <= session_block.CLAUSE_MAX_CHARS and "#" not in clause
    note = UPPER_BLOCK + "\n\nRPE 8–9\nBreathe out on the press."
    once = session_block.add_reason(note, "2 sets today.")
    assert once == UPPER_BLOCK + "\n\nRPE 8–9\n2 sets today.\nBreathe out on the press."
    assert session_block.add_reason(once, "2 sets today.") == once


def test_the_block_is_idempotent_and_replaces_never_stacks():
    ir = _lower_volume("2026-10-27")
    session_block.place_on_first(ir)
    first = ir.exercises[0].notes
    session_block.place_on_first(ir)
    assert ir.exercises[0].notes == first and first.count("Low energy") == 1
