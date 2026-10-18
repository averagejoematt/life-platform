"""tests/test_draft_constraint_gate_5000.py — the draft obeys the standing constraint and the 🟢 tripwire (#5000).

The 2026-10-18 draft (`2167c0e6…`, reproduced from DDB on 2026-10-18) carried the Whoop-band tier
cues, printed the 🟢 branch with `protein_floor_missed` tripped 6 of 7, and dropped the computed
`cardio_pick` (with HR fields) on the floor. The owner's hand-built routine for that day (`014e1142…`)
is the regression fixture: re-drafting 2026-10-18 must produce notes equivalent to it in every
semantic part (`tests/fixtures/routine_2026_10_18_constraint_gate_5000.json`).

Privacy: the stop list is read at draft time from the owner-only memory row; every test here feeds
a PLACEHOLDER string instead. No clock is read: every date is passed in.
"""

from __future__ import annotations

import json
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

from training import recent_aerobic, standing_constraints as sc  # noqa: E402
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402

from mcp import draft_constraint_gate as dcg  # noqa: E402
from mcp.recovery_authoring import derive_training_context, find_conditional_up  # noqa: E402

FIX = json.loads((REPO / "tests" / "fixtures" / "routine_2026_10_18_constraint_gate_5000.json").read_text(encoding="utf-8"))
DAY = FIX["target_date"]
DRAFT = FIX["draft_2167c0e68e25f311d46f1015cbefc047"]
HAND = FIX["hand_built_014e1142aaad30b3b3b1fb5e90046dc2"]
PLACEHOLDER_STOP = "PLACEHOLDER-STOP-LIST means stop"
MEMORY_TEXT = f"STANDING: (1) rule one. (2) rule two. (3) rule three. (4) {PLACEHOLDER_STOP}. (5) rule five."
BAND_MARKERS = ("67-100", "34-66", "1-33", "ADAPT BY WAKE RECOVERY", "band/feel")


def _draft_ir() -> RoutineSpec:
    exercises = [
        ExerciseBlock(
            movement_key=e["movement_key"],
            sets=[Set(weight_kg=20.0, rep_range_start=8, rep_range_end=12) for _ in range(e["sets"])],
            notes="VOLUME: program note.",
            skill_tier=e["skill_tier"],
            rationale_tag=e["rationale_tag"],
        )
        for e in DRAFT["exercises"]
    ]
    return RoutineSpec(routine_id="fixture-5000", target_date=DAY, archetype=FIX["archetype"], variant="ideal", exercises=exercises)


def _ctx() -> dict:
    c = DRAFT["training_context"]
    return derive_training_context(c["loaded_lifting_streak"], c["deficit_state"], DAY)


def _redraft(monkeypatch, *, day=DAY, protein_missed=DRAFT["protein_days_missed_7d"], memory=lambda sk: MEMORY_TEXT):
    """The draft path's own sequence (`tools_hevy_routine._action_draft`) on the fixture IR, every read injected."""
    from mcp import tools_hevy_routine as thr

    monkeypatch.setattr(recent_aerobic, "legs_loaded", lambda block: (True, "a long walk yesterday"))
    ir = _draft_ir()
    ir.target_date = day
    constraint = dcg.read_standing_constraint(day, memory_reader=memory)
    protein = dcg.protein_tripwire(day, reader=lambda d: (protein_missed, 7))
    withheld = dcg.green_withheld_reason(protein)
    structured = thr._apply_recovery_adaptation(ir, _ctx(), DRAFT["inputs_current_through"], constraint, withheld)
    cardio, pick = dcg.cardio_block(day, ir.archetype, constraint, layer={"state": "read"})
    if cardio is not None:
        ir.exercises.append(cardio)
    return ir, structured, pick, constraint


# ── the reader ─────────────────────────────────────────────────────────────────
def test_the_reader_finds_the_constraint_from_its_date_and_never_before():
    assert sc.active_constraint(DAY)["id"] == "hr_regime_change_2026_10_10"
    assert sc.active_constraint("2026-10-10") is not None
    assert sc.active_constraint("2026-10-09") is None  # mutation control: the boundary is the date it took effect
    c = dcg.read_standing_constraint(DAY, memory_reader=lambda sk: MEMORY_TEXT)
    assert c["memory_read"] == "ok" and c["stop_list"] == PLACEHOLDER_STOP + "."
    assert dcg.read_standing_constraint("2026-10-09", memory_reader=lambda sk: MEMORY_TEXT) is None


def test_an_unreadable_memory_row_is_named_in_the_gate_never_silently_dropped():
    def boom(sk):
        raise RuntimeError("ddb down")

    c = dcg.read_standing_constraint(DAY, memory_reader=boom)
    assert c["memory_read"] == "failed:RuntimeError" and c["stop_list"] is None
    lines = sc.gate_lines(c, c["stop_list"], None)
    assert any("could not be read" in ln for ln in lines)
    assert dcg.read_standing_constraint(DAY, memory_reader=lambda sk: None)["memory_read"] == "missing"


def test_every_gate_number_carries_its_provenance():
    """ADR-105: each threshold the gate acts on is labelled owner / owner-history / population."""
    for c in sc.STANDING_CONSTRAINTS:
        prov = c["provenance"]
        for key in ("invalidates_hr_tiers", "hr_prescriptions_allowed", "sinus_rpe_cap", "not_sinus_rpe_cap", "cardio_minutes"):
            assert prov[key].split(" ")[0] in ("owner", "owner-history", "population"), key


# ── box 1 + 2: the ECG + feel gate, no Whoop-band cues ──────────────────────────
def test_the_redraft_writes_the_ecg_and_feel_gate_and_no_band_cues(monkeypatch):
    ir, structured, _, _ = _redraft(monkeypatch)
    first = ir.exercises[0].notes
    gate = HAND["first_exercise_gate"]
    assert "Take an ECG before you leave." in first and "Whoop bands invalid since 2026-10-10" in first
    assert f"the plan as written, every set ≤ RPE {gate['sinus_rpe_cap']}" in first
    assert f"every set ≤ RPE {gate['not_sinus_rpe_cap']}; accessories and cardio optional" in first
    assert PLACEHOLDER_STOP in first
    assert "no breath-hold" in first and "Get up slowly" in first
    every_note = "\n".join(e.notes for e in ir.exercises)
    assert not [m for m in BAND_MARKERS if m in every_note], "a Whoop-band cue survived the constraint"
    # the stashed ceiling adherence grades against is the sinus cap, never the old GREEN bonus
    assert {b["green"]["rpe_cap"] for b in structured["exercises"].values()} == {gate["sinus_rpe_cap"]}


def test_mutation_control_without_the_constraint_the_band_block_is_written(monkeypatch):
    """Before 2026-10-10 nothing is active: the band block is exactly what the draft wrote before #5000."""
    ir, _, pick, constraint = _redraft(monkeypatch, day="2026-10-05", protein_missed=0)
    assert constraint is None
    assert "ADAPT BY WAKE RECOVERY" in ir.exercises[0].notes and "🟢 67-100" in ir.exercises[0].notes
    assert pick["hr_ceiling_bpm"] == recent_aerobic.HR_CEILING_BPM


# ── box 3: a tripped protein_floor_missed omits the 🟢 branch ────────────────────
def test_a_tripped_protein_tripwire_omits_the_green_branch_under_the_gate(monkeypatch):
    ir, structured, _, _ = _redraft(monkeypatch)
    first = ir.exercises[0].notes
    assert f"No 🟢 this week — protein floor missed {HAND['first_exercise_gate']['green_withheld_with_count']}." in first
    assert all(b["green"].get("withheld") for b in structured["exercises"].values())


def test_a_tripped_protein_tripwire_omits_the_green_branch_without_the_constraint(monkeypatch):
    """Mutation control for the tripwire alone: on a pre-constraint day the band block keeps 🟡/🔴 and
    loses 🟢; with the tripwire clear the 🟢 branch is back."""
    ir, structured, _, _ = _redraft(monkeypatch, day="2026-10-05", protein_missed=6)
    notes = "\n".join(e.notes for e in ir.exercises)
    assert "🟢 67-100" not in notes and "no 🟢 this week (protein floor missed 6 of 7)" in notes
    assert not [ln for ln in notes.splitlines() if ln.startswith("🟢")]
    assert all(b["green"]["rpe_cap"] == b["yellow"]["rpe_cap"] for b in structured["exercises"].values())
    clear, _, _, _ = _redraft(monkeypatch, day="2026-10-05", protein_missed=2)
    assert "🟢 67-100" in clear.exercises[0].notes


def test_an_unread_protein_window_is_unknown_never_clear_and_never_withholds():
    trip = dcg.protein_tripwire(DAY, reader=lambda d: (None, None))
    assert trip["state"] == "unknown" and dcg.green_withheld_reason(trip) is None

    def boom(d):
        raise RuntimeError("x")

    assert dcg.protein_tripwire(DAY, reader=boom)["state"] == "unknown"
    assert dcg.protein_tripwire(DAY, reader=lambda d: (3, 7))["state"] == "tripped"  # the owner's threshold, at the edge
    assert dcg.protein_tripwire(DAY, reader=lambda d: (2, 7))["state"] == "clear"


# ── box 4: the cardio_pick block, talk test, no HR fields ───────────────────────
def test_the_cardio_pick_is_appended_with_the_talk_test_and_no_hr_fields(monkeypatch):
    ir, _, pick, _ = _redraft(monkeypatch)
    cardio = ir.exercises[-1]
    want = HAND["cardio"]
    assert cardio.movement_key == want["movement_key"] and [s.duration_seconds for s in cardio.sets] == [want["minutes"] * 60]
    assert "Recumbent" in cardio.notes and "talk test" in cardio.notes and "No HR target." in cardio.notes
    assert "bpm" not in cardio.notes
    assert not set(sc.HR_PICK_FIELDS) & set(pick) and pick["hr_fields_dropped_by"] == "hr_regime_change_2026_10_10"
    # the served stage-1 pick is the same constrained pick
    assert not set(sc.HR_PICK_FIELDS) & set(recent_aerobic.cardio_pick({"state": "read"}, "upper", DAY))
    assert set(sc.HR_PICK_FIELDS) <= set(recent_aerobic.cardio_pick({"state": "read"}, "upper"))  # undated: unchanged


# ── box 5: the hand-built routine is the fixture ───────────────────────────────
def test_redrafting_2026_10_18_is_equivalent_to_the_hand_built_routine(monkeypatch):
    """Semantic, not byte-for-byte: the same lifts in the same order with the same set counts (v0.4 is
    untouched), the cardio block appended, the gate's every part present, and every exercise the owner
    marked optional-when-not-sinus optional in the re-draft (which marks only accessories and cardio)."""
    ir, _, _, _ = _redraft(monkeypatch)
    lifted = [e for e in HAND["exercises"] if not e.get("_note")]
    assert [(e.movement_key, len(e.sets)) for e in ir.exercises] == [(e["movement_key"], e["sets"]) for e in lifted]
    optional = {e.movement_key for e in ir.exercises if "Optional if the ECG is not sinus." in e.notes}
    assert {e["movement_key"] for e in lifted if e.get("optional_if_not_sinus")} <= optional
    allowed = {e["movement_key"] for e in DRAFT["exercises"] if e["rationale_tag"].startswith("accessory:")} | {"cycling"}
    assert optional <= allowed
    # the gate prose writes no conditional up-branch (the subtract-only auditor reads these notes at commit)
    assert not [hit for e in ir.exercises for hit in find_conditional_up(e.notes)]


def test_the_observed_defects_were_on_the_stored_draft():
    """The reproduction, as read: all three defects were on the stored draft before this fix."""
    assert DRAFT["observed_defects"] == {
        "whoop_band_cues_on_first_exercise": True,
        "green_branch_printed": True,
        "cardio_block_in_draft": False,
    }


def test_the_registry_entry_names_no_clinical_specifics():
    """Public repo: the entry names the event by date only; the specifics stay in the owner-only row."""
    blob = json.dumps(sc.STANDING_CONSTRAINTS, default=str).lower()
    assert "owner-only" in blob and "memory#training#2026-10-10#" in blob


def test_action_draft_wires_the_gate_the_tripwire_and_the_cardio_block(monkeypatch):
    """`manage_hevy_routine draft` itself (`_action_draft`), every I/O seam patched: the persisted ideal
    carries the gate, no band cue, the cardio block last, and the reads on its snapshot. Mutation control:
    drop the `ideal.exercises.append(cardio)` line in `draft_constraint_gate.gate_draft` — this reds."""
    from types import SimpleNamespace

    from training import routine_generator, routine_repo

    from mcp import shared_quantities, tools_hevy_routine as thr, tools_plan

    ideal, floor = _draft_ir(), _draft_ir()
    floor.variant = "floor"
    persisted = []
    monkeypatch.setattr(recent_aerobic, "legs_loaded", lambda block: (True, "a long walk yesterday"))
    monkeypatch.setattr(thr, "_authoring_freshness_gate", lambda d: {"ok": True, "gaps": [], "data_current_through": "2026-10-16"})
    monkeypatch.setattr(thr, "_generator_inputs", lambda a: SimpleNamespace(target_date=DAY))
    monkeypatch.setattr(thr, "_gather_training_context", lambda d: _ctx())
    monkeypatch.setattr(routine_generator, "generate_routines", lambda inputs: [ideal, floor])
    monkeypatch.setattr(routine_repo, "draft_versioned", persisted.append)
    monkeypatch.setattr(dcg, "_read_memory_summary", lambda sk: MEMORY_TEXT)
    monkeypatch.setattr(tools_plan, "_protein_days_7d", lambda d: (6, 7))
    monkeypatch.setattr(shared_quantities, "recent_aerobic_layer", lambda d: {"state": "read"})
    out = thr._action_draft({"target_date": DAY})
    assert out["status"] == "drafted" and [r.variant for r in persisted] == ["ideal", "floor"]
    assert out["green_block"]["state"] == "tripped" and out["green_block"]["withheld"] is True
    assert out["cardio_block"]["appended"] is True and out["standing_constraint"]["memory_read"] == "ok"
    assert ideal.exercises[-1].movement_key == "cycling" and floor.exercises[-1].movement_key == "db_curl"
    assert "Take an ECG before you leave." in ideal.exercises[0].notes
    assert not [m for m in BAND_MARKERS if m in "\n".join(e.notes for e in ideal.exercises)]
    assert ideal.inputs_snapshot["standing_constraint"]["id"] == "hr_regime_change_2026_10_10"
