"""tests/test_cardio_prescribed_level_5076.py — an empty-note ride is read at the level its routine prescribed (#5076 box 2).

Box 2 of #5076 is "progression = same RPE at a higher level". The live defect (origin/main 4907f0a5a): `cardio_facts`
read `last_level` from the performed ride's NOTE alone, and he logs the menu's rides with an empty note, so `last_level`
was None on every menu ride and the bike dose fell through to his June calibration note ("L9-10 is easy" -> 10) night
after night — the level could never move. PR #5279 fixed the same gap for the ride's KIND; this is the LEVEL half: a
silent note takes the level the routine he performed printed on line 1 (`cardio_menu.served_levels`, joined by
`cardio_cues.with_served_kinds` on the workout's `hevy_routine_id`), stated as `prescribed_level`, never as a level he
logged. His own note (a logged level, a span, two levels, his clock shape) always wins; with neither, the level stays
absent (ADR-104).

The end-to-end tests drive the real nightly draft path through #5279's harness (`nightly_predraft._draft` ->
`gate_draft` -> the cardio cue pass) with only the I/O seams stubbed. No clock is read, no AWS, no AI.
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

from training import cardio_menu as cm, cardio_note as cn, cardio_progression as cp  # noqa: E402
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402

from tests.test_cardio_served_kind_5076 import (  # noqa: E402 — #5279's live-shaped harness, one home
    CYCLING_TID,
    FRESH,
    LIVE_ITEMS,
    LIVE_ROUTINES,
    _cardio,
    _predraft,
    _served,
)

PRESCRIBED_BASIS = "the level his last ride's routine prescribed"
EASY_L12 = "Recumbent bike · 30 min · level 12 at 12.3 mph flat · RPE 4–5, full sentences"
TEMPO_L11 = "Recumbent bike · 30 min · level 11 at 12.3 mph flat · tempo: RPE 6–7, short phrases"
SHAPED_NOTE = "8/12 for 2 mins for 20 mins / 8/14 for 2 mins for 20 mins / 8 level up every 2 mins from 40 to 60 to level 18"


def _rx(level: int, kind: str = "easy") -> dict:
    base = level - cm.TEMPO_LEVEL_STEP if kind == "tempo" else level
    return {"machine": "cycling", "kind": kind, "level": level, "base_level": base}


def _ride(day: str, note: str = "", rx: dict | None = None, mph: float | None = 12.0, hid: str | None = "hevy-x") -> dict:
    s = {"date": day, "name": "Cycling", "note": note, "duration_sec": 1800.0, "distance_m": None if mph is None else mph * 1609.344 * 0.5}
    if hid:
        s["hevy_routine_id"] = hid
    if rx:
        s["served_level"] = rx
    return s


def _facts(*rides: dict) -> dict:
    """`cardio_facts` over one cycling template, rides given most-recent first (the index's order)."""
    return cp.cardio_facts(CYCLING_TID, {CYCLING_TID: list(rides)}, {})


# ── the main fix: a silent note reads the prescription, and says so ────────────────────────
def test_an_empty_note_ride_reads_the_level_its_routine_prescribed():
    facts = _facts(_ride("2026-10-23", "", _rx(12)), _ride("2026-06-25", "L9-10 is easy", mph=None, hid=None))
    assert facts["last_level"] == 12 and facts["last_level_status"] == "prescribed_level"
    assert facts["last_prescription"] == {"machine": "cycling", "kind": "easy", "level": 12, "base_level": 12, "hevy_routine_id": "hevy-x"}
    # the dose reads it ahead of the June calibration, and names where it came from
    assert cn._base_level(facts) == (12, PRESCRIBED_BASIS)
    assert cm.bike_dose("easy", facts, cp.level_verdict(facts["series"], facts["last_level"], facts["shaped"]))["level"] == 12
    # the ride joins the speed series at that level, tagged as the prescription's
    assert facts["series"][-1]["level"] == 12 and facts["series"][-1]["level_source"] == "prescription"
    # a cue states it as prescribed, never as a level he logged
    assert cp.render_cardio_cue(facts).startswith("Last: level 12 as prescribed, ")


def test_a_note_with_no_level_still_reads_the_prescription():
    facts = _facts(_ride("2026-10-23", "felt strong, legs fine", _rx(12)))
    assert facts["last_level"] == 12 and facts["last_level_status"] == "prescribed_level"


def test_a_performed_tempo_is_read_at_its_base_so_the_level_never_ratchets():
    """Line 1 of a tempo block prints base + TEMPO_LEVEL_STEP (`bike_dose`). Reading that as the base would put the
    next easy block a level up with no `raise` behind it; the base is the level the dose was built on."""
    facts = _facts(_ride("2026-10-23", "", _rx(11, "tempo")))
    assert facts["last_level"] == 11 - cm.TEMPO_LEVEL_STEP and facts["last_prescription"]["level"] == 11
    # a conditioning ride is not speed at one easy-effort level: it never enters the hold/raise comparison
    assert facts["series"] == [] and facts["excluded"] == {"prescribed_not_easy": 1}
    assert cp.render_cardio_cue(facts).startswith("Last: level 11 as prescribed, ")


# ── his word wins ────────────────────────────────────────────────────────────────────────
def test_a_level_in_his_note_beats_the_prescription():
    facts = _facts(_ride("2026-10-23", "Level 10 flat", _rx(12)))
    assert facts["last_level"] == 10 and facts["last_level_status"] == "ok" and facts["last_prescription"] is None
    assert facts["series"][-1]["level"] == 10 and facts["series"][-1]["level_source"] == "note"
    assert cn._base_level(facts) == (10, "last ride's level")


def test_his_clock_shaped_ride_stays_shaped():
    facts = _facts(_ride("2026-10-25", SHAPED_NOTE, _rx(12)))
    assert facts["last_level"] is None and facts["last_level_status"] == "shaped_session" and facts["last_prescription"] is None
    assert facts["last_shape"]["base_level"] == 8
    assert cn._base_level(facts) == (8, "the lowest level of his last (clock-shaped) ride")


def test_a_span_or_two_levels_in_his_note_is_never_overridden():
    for note, status in (("L9-10 today", "level_range"), ("level 9 for 20 and then level 6 for 10", "multi_level_session")):
        facts = _facts(_ride("2026-10-23", note, _rx(12)))
        assert facts["last_level"] is None and facts["last_level_status"] == status and facts["last_prescription"] is None, note


def test_a_note_naming_another_kind_refuses_the_prescription():
    """Served tempo, but he wrote that he kept it easy: he did not ride the prescription, so its level is not his."""
    facts = _facts(_ride("2026-10-23", "kept it easy, legs dead", _rx(11, "tempo")))
    assert facts["last_level"] is None and facts["last_level_status"] == "no_level_in_note" and facts["last_prescription"] is None


# ── absent stays absent ──────────────────────────────────────────────────────────────────
def test_no_prescription_and_no_note_is_absent_never_a_default():
    facts = _facts(_ride("2026-10-23", "", None))
    assert facts["last_level"] is None and facts["last_level_status"] == "no_note" and facts["last_prescription"] is None
    assert cn.prescribed_level(facts, None, constrained=False) == (None, None)
    assert cm.bike_dose("easy", facts, None)["level"] is None
    assert facts["series"] == [] and facts["excluded"] == {"no_note": 1}
    # a malformed prescription is no prescription
    for bad in ({"machine": "cycling", "kind": "easy", "level": 0, "base_level": 0}, {"kind": "easy", "base_level": 12}, "12"):
        f = _facts(_ride("2026-10-23", "", bad))  # type: ignore[arg-type]
        assert f["last_level"] is None and f["last_prescription"] is None, bad


# ── progression: same RPE at a higher level, off prescribed rides ────────────────────────
def test_prescribed_easy_rides_carry_a_raise_to_the_next_level():
    """Eight empty-note easy rides at level 10, the last four clearly faster than the first four (beyond his own
    within-level spread) -> `raise`, and the next easy block is level 11. Before #5076 box 2 none of these rides
    had a level, the verdict could never leave `no_level`, and the dose sat on the calibration span."""
    speeds = [12.0, 12.1, 12.0, 12.1, 13.0, 13.1, 13.0, 13.1]  # oldest first
    rides = [_ride(f"2026-10-{10 + i:02d}", "", _rx(10), mph=v, hid=f"hevy-{i}") for i, v in enumerate(speeds)]
    facts = _facts(*reversed(rides))
    assert [r["level"] for r in facts["series"]] == [10] * 8
    verdict = cp.level_verdict(facts["series"], facts["last_level"], facts["shaped"])
    assert verdict["verdict"] == "raise" and verdict["claims_improvement"] is True
    assert cm.bike_dose("easy", facts, verdict)["level"] == 11


# ── the routine side: what a served block prescribed ─────────────────────────────────────
def _block(key: str, notes: str, tag: str = "custom") -> ExerciseBlock:
    return ExerciseBlock(movement_key=key, sets=[Set(duration_seconds=1800)], notes=notes, rationale_tag=tag)


def test_served_levels_reads_line_one_and_never_invents_one():
    walk = "Treadmill · 30 min · incline 8% at 2.5 mph walk · RPE 3–4, full sentences"
    no_level = "Recumbent bike · 30 min · flat · RPE 4–5, full sentences"
    gated = "Recumbent bike · 30 min · level 10 at 12.3 mph flat · RPE 4–5, full sentences"  # tagged tempo, written easy
    routines = []
    for hid, blocks in (
        ("h-easy", [_block("cycling", EASY_L12)]),
        ("h-tempo", [_block("cycling", TEMPO_L11, "cardio:cycling:menu:tempo")]),
        ("h-walk", [_block("treadmill", walk)]),
        ("h-nolevel", [_block("cycling", no_level)]),
        ("h-prose", [_block("cycling", "Last: level 11, 10.42 mi in 45:00 (13.9 mph) — 18 Oct")]),
        ("h-gated", [_block("cycling", gated, "cardio:cycling:menu:tempo")]),
    ):
        ir = RoutineSpec(routine_id=f"r-{hid}", target_date="2026-10-23", archetype="upper", exercises=blocks)
        ir.hevy_routine_id = hid
        routines.append(ir)
    out = cm.served_levels(routines)
    assert out == {
        "h-easy": {"cycling": {"machine": "cycling", "kind": "easy", "level": 12, "base_level": 12}},
        "h-tempo": {"cycling": {"machine": "cycling", "kind": "tempo", "level": 11, "base_level": 11 - cm.TEMPO_LEVEL_STEP}},
        # line 1 is what he rode: a tempo the gate wrote as an easy block reads as easy at its own level
        "h-gated": {"cycling": {"machine": "cycling", "kind": "easy", "level": 10, "base_level": 10}},
    }


# ── end to end: the nightly draft path ───────────────────────────────────────────────────
ROUTINES_EASY_L12 = [*LIVE_ROUTINES[:2], _served("hevy-019d", "2026-10-23", "lower", tag="cardio:cycling:menu:easy", notes=EASY_L12)]


def test_the_nightly_draft_doses_from_the_prescribed_level(monkeypatch):
    """The live 10-24 history (10-23's ride has an empty note) with 10-23's routine prescribing easy at level 12: the
    10-24 draft's bike dose holds level 12 — the prescription — not the June calibration's 10, and the audit says the
    level came from the routine. (Fresh legs on an upper day: the menu places the week's conditioning on the bike.)"""
    ideal, _out = _predraft(monkeypatch, archetype="upper", role="shoulders_arms", layer=FRESH, routines=ROUTINES_EASY_L12)
    block, audit = _cardio(ideal)
    assert block.movement_key == "cycling", block.notes
    assert audit["hold_level"] == 12 and audit["level_basis"] == PRESCRIBED_BASIS
    assert f" L{audit['level']} " in block.notes.split("\n")[0]  # #5428 line 1: "Recumbent · L12 · RPE …"


def test_the_live_tempo_ride_is_read_at_its_base(monkeypatch):
    """The live routines as they were: 10-23 served tempo at level 11. The next dose holds the tempo's base (10), never
    11: a performed tempo is not a raise."""
    ideal, _out = _predraft(monkeypatch, archetype="upper", role="shoulders_arms", layer=FRESH)
    _block_, audit = _cardio(ideal)
    assert audit["hold_level"] == 11 - cm.TEMPO_LEVEL_STEP and audit["level_basis"] == PRESCRIBED_BASIS


def test_MUTATION_CONTROL_with_the_routine_read_failing_the_calibration_comes_back(monkeypatch):
    """Executed: the same 10-24 draft with the routine read failing (fail-soft). The ride is read from its empty note
    alone, so the prescription's 12 is lost. Before #5428 the dose fell through to the June calibration span (10) — the
    live defect; since #5428 it falls to his logged steady level (the median of his last single-level rides) first, and
    reaches the calibration only when no single-level ride is on record (`test_steady_level_*` in
    test_cardio_steady_level_5428.py)."""
    ideal, _out = _predraft(monkeypatch, archetype="upper", role="shoulders_arms", layer=FRESH, routines_fail=True)
    _block_, audit = _cardio(ideal)
    assert audit["level_basis"].startswith("his logged steady level") and audit["hold_level"] == 10  # not the prescription's 12
    assert len(LIVE_ITEMS) == 6  # the harness's live week, unchanged
