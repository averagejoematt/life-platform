"""tests/test_cardio_note_prescription_5048.py — the cardio note in Hevy is a prescription first (#5048).

The fixture is the wire: `tests/fixtures/cardio_note_2026_10_18_5048.json` is the live 2026-10-18 cycling
block (routine `014e1142…`, VERSION#current), the cycling sessions before that day as
`exercise_history.load_history_indexes` returned them, and the `recent_aerobic` totals for the day — all
read from DynamoDB on 2026-10-18 (read-only; two notes trimmed for the public repo, see `_privacy`).

No clock is read: every date is passed in (the standing constraint is looked up for the fixture's day).
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
from types import SimpleNamespace

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO))

from training import cardio_note as cn, routine_generator as rg, standing_constraints as sc  # noqa: E402
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402

FIX = json.loads((REPO / "tests" / "fixtures" / "cardio_note_2026_10_18_5048.json").read_text(encoding="utf-8"))
DAY = FIX["target_date"]
CYCLING_TID = "D8F7F851"  # config/movement_catalog.json -> movements.cycling
CONSTRAINT = sc.active_constraint(DAY)
READ_WEEK = {
    "state": "read",
    "totals": {"weight_bearing_hr_48h": 1.0, "week_to_date": {"over_ramp": False, "hours": 5.0, "ramp_ceiling_hr": 7.0}},
}

# The #5428 standard's line 1 (HEVY_NOTE_STANDARD.md §3.7), written out again here rather than imported, so the module's
# own regex is held to it: machine · levels · [hard ]RPE a[–b] (talk words). No minutes, no bike speed.
GRAMMAR = re.compile(
    r"^(?:Recumbent|Upright bike|Treadmill|Elliptical|Rower|Air bike) · [^·]+ · (?:hard )?RPE \d(?:–\d)? "
    r"\((?:full sentences|short phrases|a few words)\)$"
)


def reader_offences(note: str) -> list[str]:
    """What a reader test refuses on a cardio note: > 4 lines, a first line off the grammar, "Last:" on
    line 1, a sentence starting with "Not", "Optional" on the block (it is the gate's line)."""
    lines = note.split("\n")
    out = []
    if len(lines) > 4:
        out.append("more than four lines")
    if not GRAMMAR.match(lines[0]):
        out.append("line 1 is not the prescription grammar")
    if "Last:" in lines[0]:
        out.append("'Last:' on line 1")
    for sentence in re.split(r"(?<=[.!?])\s+|\n|—\s*|·\s*", note):
        if sentence.strip().startswith("Not "):
            out.append(f"a sentence starts with 'Not': {sentence.strip()[:40]!r}")
    if "optional" in note.lower():
        out.append("'optional' on the cardio block")
    return out


def _cardio_index() -> dict:
    return {CYCLING_TID: list(FIX["cycling_sessions"])}


def _live_spec() -> RoutineSpec:
    block = ExerciseBlock(movement_key="cycling", sets=[Set(duration_seconds=FIX["minutes"] * 60)], notes=FIX["live_note"])
    return RoutineSpec(routine_id="fixture-5048", target_date=DAY, archetype=FIX["archetype"], exercises=[block])


def _redraft() -> RoutineSpec:
    spec = _live_spec()
    assert rg.attach_cardio_cues(spec, cardio_index=_cardio_index(), whoop_index={}, aerobic_block=FIX["recent_aerobic"]) == 1
    return spec


# ── the reproduction, and the reader's own control ────────────────────────────────────
def test_the_live_note_fails_the_reader_on_every_count_it_was_filed_for():
    """Mutation control for the reader: the live 2026-10-18 note (the issue's quote) must red it."""
    assert FIX["live_note"].startswith("Last: level 11, 10.60 mi in 45:30 (14.0 mph) — 16 Oct")
    got = reader_offences(FIX["live_note"])
    assert "line 1 is not the prescription grammar" in got
    assert "'Last:' on line 1" in got
    assert any(o.startswith("a sentence starts with 'Not'") for o in got)
    assert "'optional' on the cardio block" in got


# ── box 1 + 4: the rewritten live note ────────────────────────────────────────────────
def test_the_rewritten_2026_10_18_note_is_one_line_with_the_prescription_first():
    """#5428: the easy ride is ONE line — the level from his log, the RPE and the talk test. No minutes (the set row), no
    speed (an output under the iPad), no recovery answer, no why tail (the audit keeps it); nothing follows the block,
    so no After line."""
    spec = _redraft()
    note = spec.exercises[0].notes
    assert reader_offences(note) == [], note
    assert note == "Recumbent · L11 · RPE 4–5 (full sentences)"
    assert cn.LINE1_RE.match(note)
    assert "No push" not in note and "mph" not in note and " min" not in note
    assert not re.search(r"\d+\s*bpm|\bHR\b", note)
    audit = spec.inputs_snapshot["cardio_notes"][0]
    assert audit["why"] and audit["mph"] == 13.4  # the speed and the why stay on the record, off the wire
    # the author's prose is replaced, never silently lost
    rep = spec.inputs_snapshot["cardio_notes_replaced"]
    assert [(r["movement_key"], r["notes"]) for r in rep] == [("cycling", FIX["live_note"])]


def test_the_level_is_still_derived_from_the_last_ride_and_the_week_shapes_are_read():
    spec = _redraft()
    audit = spec.inputs_snapshot["cardio_notes"][0]
    assert audit["level"] == 11 and audit["level_basis"] == "last ride's level"
    assert spec.inputs_snapshot["cardio_plan"]["week_kinds_before"] == ["easy", "easy", "easy"]  # 10-13, 10-15, 10-16
    assert audit["kind"] == "easy" and audit["placement_why"] == "the author's note names it"
    assert audit["constraint"] == "hr_regime_change_2026_10_10" and audit["no_push_gate"] is False


def test_a_redraft_recomposes_the_same_note_and_never_stacks():
    spec = _redraft()
    first = spec.exercises[0].notes
    rg.attach_cardio_cues(spec, cardio_index=_cardio_index(), whoop_index={}, aerobic_block=FIX["recent_aerobic"])
    assert spec.exercises[0].notes == first


def test_MUTATION_CONTROL_the_day_before_the_ruling_the_no_push_gate_still_holds():
    """Executed: the same history replayed on 2026-10-17 (the gate's last day) composes the no-push answer;
    on 2026-10-18 it does not. A replay of an older day composes what that day composed."""
    spec = _live_spec()
    spec.target_date = "2026-10-17"
    rg.attach_cardio_cues(spec, cardio_index=_cardio_index(), whoop_index={}, aerobic_block=FIX["recent_aerobic"])
    assert spec.inputs_snapshot["cardio_notes"][0]["no_push_gate"] is True
    assert _redraft().inputs_snapshot["cardio_notes"][0]["no_push_gate"] is False
    # the gate's effect on the wire is the KIND: a tempo asked for on 10-17 is written easy, on 10-18 as itself
    held = cn.compose(
        movement_key="cycling", minutes=30, target_date="2026-10-17", kind="tempo", facts={"last_level": 11}, constraint=CONSTRAINT
    )
    free = cn.compose(
        movement_key="cycling", minutes=30, target_date="2026-10-18", kind="tempo", facts={"last_level": 11}, constraint=CONSTRAINT
    )
    assert cn.composed_kind(held[0]) == "easy" and "⌚" not in held[0]
    assert cn.composed_kind(free[0]) == "tempo" and "⌚ ride clock:" in free[0]


# ── box 2: the recovery question leaves the wire (#5428 standard §3.7: the chat carries it) ─────────
def _flat(**kw):
    base = dict(movement_key="cycling", minutes=20, target_date="2026-09-30", facts={"last_level": 11}, aerobic_block=READ_WEEK)
    base.update(kw)
    return cn.compose(**base)[0]


def test_the_note_is_the_same_whatever_the_recovery_band_and_the_audit_keeps_the_band():
    notes = {band: _flat(recovery_band=band) for band in (None, "green", "yellow", "red")}
    assert set(notes.values()) == {"Recumbent · L11 · RPE 4–5 (full sentences)"}
    audit = cn.compose(movement_key="cycling", minutes=20, target_date="2026-09-30", facts={"last_level": 11}, recovery_band="yellow")[1]
    assert audit["recovery_band"] == "yellow"


def test_no_hr_reaches_the_wire_with_or_without_a_constraint():
    """Standard §3.7: no HR target until his zones are re-derived — even a caller passing the redline cap prints none."""
    for constraint in (None, CONSTRAINT):
        for day in ("2026-10-17", "2026-10-28"):
            note = _flat(constraint=constraint, hr_ceiling_bpm=120, target_date=day)
            assert "bpm" not in note and "HR" not in note and "No push" not in note, note


def test_every_number_the_note_acts_on_is_labelled_and_the_label_stays_off_the_wire():
    """ADR-105: the interval steps, the hill climb and the tempo check-ins are platform-chosen; the audit says so, the
    note does not (#5428: engine words never reach Hevy)."""
    assert set(cn.LABELS.values()) == {"platform-chosen"}
    for kind in ("easy", "tempo", "intervals", "hills"):
        note, audit = cn.compose(movement_key="cycling", minutes=30, target_date="2026-10-28", kind=kind, facts={"last_level": 11})
        assert "platform-chosen" not in note and audit["labels"]["interval_level_step"] == "platform-chosen"


# ── box 3: the default is easy; the harder kinds are the menu's placement (#5076) ─────────
def test_the_default_kind_is_easy_flat_and_the_treadmills_is_the_incline_walk():
    assert cn.compose(movement_key="cycling", minutes=20, target_date="2026-09-30")[1]["kind"] == "easy"
    assert _flat() == "Recumbent · L11 · RPE 4–5 (full sentences)"
    assert cn.compose(movement_key="treadmill", minutes=30, target_date="2026-09-30")[1]["kind"] == "incline_treadmill_walk"


def test_the_gate_holds_a_hard_kind_easy_only_before_its_retirement():
    for kind in ("tempo", "intervals", "hills"):
        assert cn.composed_kind(_flat(kind=kind, constraint=CONSTRAINT, target_date="2026-10-17")) == "easy", kind
        assert _flat(kind=kind, constraint=CONSTRAINT, target_date="2026-10-18") != _flat(
            kind="easy", constraint=CONSTRAINT, target_date="2026-10-18"
        )


def test_a_performed_rides_shape_is_read_from_its_own_note():
    assert cn.shape_of("Level 11 flat") == "flat"
    assert cn.shape_of("Level 11 intervals 5x2") == "intervals"
    assert cn.shape_of("Level 11 hill program") == "hill"
    assert cn.shape_of("") == "flat"


# ── the level derivation ──────────────────────────────────────────────────────────────
def test_the_level_falls_back_to_his_calibration_and_rises_only_on_a_raise_verdict_without_the_constraint():
    cal = {"last_level": None, "calibration": [{"anchors": [{"level_low": 9, "level_high": 10, "verdict": "easy"}]}]}
    assert cn.prescribed_level(cal, None, constrained=False) == (10, 10)
    assert cn.prescribed_level({"last_level": 11}, {"verdict": "raise"}, constrained=False) == (12, 11)
    assert cn.prescribed_level({"last_level": 11}, {"verdict": "raise"}, constrained=True) == (11, 11)
    assert cn.prescribed_level({"last_level": 11}, {"verdict": "insufficient_n"}, constrained=False) == (11, 11)
    assert cn.prescribed_level({}, None, constrained=False) == (None, None)


# ── the gate keeps "optional" ─────────────────────────────────────────────────────────
def test_cardio_optional_lives_only_in_the_gate_line():
    lines = sc.gate_lines(CONSTRAINT, "x", None)
    assert any("accessories and cardio optional" in ln for ln in lines)
    note = cn.compose(movement_key="cycling", minutes=20, target_date="2026-10-17", facts={"last_level": 11}, constraint=CONSTRAINT)[0]
    assert "optional" not in note.lower()


def test_a_block_is_left_alone_when_the_history_cannot_be_read(monkeypatch):
    from training import exercise_history as eh

    spec = SimpleNamespace(target_date=DAY, archetype="push", inputs_snapshot={}, exercises=[_live_spec().exercises[0]])

    def boom(**kw):
        raise RuntimeError("ddb down")

    monkeypatch.setattr(eh, "load_history_indexes", boom)
    assert rg.attach_cardio_cues(spec, whoop_index={}) == 0
    assert spec.exercises[0].notes == FIX["live_note"]
