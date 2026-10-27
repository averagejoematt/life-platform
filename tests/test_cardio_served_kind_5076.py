"""tests/test_cardio_served_kind_5076.py — a performed ride counts as the kind its routine prescribed (#5076).

The live defect (read-only DDB, 2026-10-24): every nightly pre-draft from 10-21 to 10-24 placed
"conditioning 1 of 2 this week" — tempo on the recumbent — and none served the default incline walk. He logs
the menu's rides with an EMPTY note, and the placement read a performed ride's kind from its note alone, so
the tempo he rode on 10-23 (routine `1dcbb545…`, tagged `cardio:cycling:menu:tempo`, performed as Hevy
routine `019d2c85…`) counted as easy: `cardio_plan.week_kinds_before` on the 10-24 draft (`74beb045…`) read
`["easy", "easy", "easy"]`. The week's conditioning never registered, so every draft re-placed tempo — and
tempo is a block the charter never runs on the treadmill (`cardio_menu.blocks.tempo.machines`), so the walk
could not appear.

Every test drives the REAL draft path the nightly runs — `nightly_predraft._draft` -> `manage_hevy_routine
draft` (`tools_hevy_routine._action_draft`) -> `draft_standing_constraint.gate_draft` -> the cardio cue pass —
with the history read through the REAL loader (`exercise_history.load_history_indexes`) over Hevy records
shaped like the live 10-19/10-21/10-23 ones. Only the I/O seams and the programmer (`generate_routines`) are
stubbed. No clock is read (every date is passed in), no AWS is reached and no AI is called.
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib
import re
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO))

from training import cardio_menu as cm, exercise_history as eh, training_charter as tc  # noqa: E402
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402

from mcp.recovery_authoring import derive_training_context  # noqa: E402

CYCLING_TID = "D8F7F851"  # config/movement_catalog.json -> movements.cycling
DAY = "2026-10-24"  # the live Saturday pre-draft (SHOULDERS+ARMS W5)
FIX5000 = json.loads((REPO / "tests" / "fixtures" / "routine_2026_10_18_standing_constraint_5000.json").read_text(encoding="utf-8"))
MEMORY_TEXT = "STANDING: (1) rule one. (2) rule two. (3) PLACEHOLDER-STOP-LIST means stop."
LOADED = {"state": "read", "totals": {"weight_bearing_hr_48h": 1.67, "walks_over_75_min_48h": 1}}  # the live 10-24 read
FRESH = {"state": "read", "totals": {"weight_bearing_hr_48h": 0.4, "walks_over_75_min_48h": 0}}


def _hevy_item(day: str, routine: str | None, seconds: float, meters: float, note: str = "") -> dict:
    """One per-workout Hevy record in the live wire shape: a cycling block (an EMPTY note unless given), plus stretching."""
    wid = f"wk-{day}"
    item = {
        "pk": "USER#matthew#SOURCE#hevy",
        "sk": f"DATE#{day}#WORKOUT#{wid}",
        "source": "hevy",
        "date": day,
        "source_workout_id": wid,
        "hevy_routine_id": routine,
        "start_time": f"{day}T01:00:00+00:00",
        "end_time": f"{day}T02:30:00+00:00",
        "exercises": [
            {
                "name": "Cycling",
                "template_id": CYCLING_TID,
                "notes": note,
                "sets": [{"duration_sec": seconds, "distance_m": meters, "reps": None}],
            },
            {
                "name": "Stretching",
                "template_id": "527DA061",
                "notes": "",
                "sets": [{"duration_sec": 600.0, "distance_m": None, "reps": None}],
            },
        ],
    }
    if not routine:
        del item["hevy_routine_id"]
    return item


# the live week of 2026-10-19 (Mon): his three rides, every note empty, each with the Hevy routine he performed —
# after the rides he did annotate: his calibration note (the easy span the live 10-24 dose read its level from,
# `level_basis: his calibration note's easy span`) and the last week's "Level 10 flat" / "Level 11 flat"
LIVE_ITEMS = [
    _hevy_item("2026-06-25", None, 1800.0, 9000.0, note="L9-10 is easy"),
    _hevy_item("2026-10-16", None, 2700.0, 15900.0, note="Level 10 flat"),
    _hevy_item("2026-10-18", None, 2700.0, 16769.0, note="Level 11 flat"),
    _hevy_item("2026-10-19", "hevy-419f", 2700.0, 3605.0),
    _hevy_item("2026-10-21", "hevy-ba78", 2400.0, 15257.0),
    _hevy_item("2026-10-23", "hevy-019d", 2700.0, 17139.0),
]


def _served(hevy_id: str, day: str, archetype: str, tag: str = "custom", notes: str = "") -> RoutineSpec:
    ride = ExerciseBlock(movement_key="cycling", sets=[Set(duration_seconds=1800)], notes=notes, rationale_tag=tag)
    ir = RoutineSpec(routine_id=f"served-{hevy_id}", target_date=day, archetype=archetype, exercises=[ride])
    ir.hevy_routine_id = hevy_id
    return ir


# the routine records those workouts were performed from, as `routine_repo` holds them
LIVE_ROUTINES = [
    # 04dd6124: a chat-drafted ride whose note is prose — it names no kind, so the ride reads as easy
    _served("hevy-419f", "2026-10-19", "lower", notes="Last: level 11, 10.42 mi in 45:00 (13.9 mph) — 18 Oct"),
    # 4d30269c: dated 10-20, performed 10-21 — a composed easy note
    _served("hevy-ba78", "2026-10-20", "upper", notes="Recumbent bike · 30 min · level 10 at 12.3 mph flat · RPE 4–5, full sentences"),
    # 1dcbb545: the menu's tempo, placed by the nightly pre-draft
    _served(
        "hevy-019d",
        "2026-10-23",
        "lower",
        tag="cardio:cycling:menu:tempo",
        notes="Recumbent bike · 30 min · level 11 at 12.3 mph flat · tempo: RPE 6–7, short phrases",
    ),
]


def _ideal(archetype: str, role: str, advanced_by: dict | None = None) -> RoutineSpec:
    d = FIX5000["draft_2167c0e68e25f311d46f1015cbefc047"]
    exercises = [
        ExerciseBlock(
            movement_key=e["movement_key"],
            sets=[Set(weight_kg=20.0, rep_range_start=8, rep_range_end=12) for _ in range(e["sets"])],
            notes="VOLUME: program note.",
            skill_tier=e["skill_tier"],
            rationale_tag=e["rationale_tag"],
        )
        for e in d["exercises"]
    ]
    snap = {"calendar": {"session_role": role, "advanced_by": advanced_by}}
    return RoutineSpec(
        routine_id=f"fixture-{role}", target_date=DAY, archetype=archetype, variant="ideal", exercises=exercises, inputs_snapshot=snap
    )


def _predraft(
    monkeypatch, *, archetype: str, role: str, layer: dict, items=None, routines=None, routines_fail: bool = False, advanced_by=None
) -> tuple:
    """The nightly pre-draft's draft step for DAY, every I/O seam patched. Returns (the persisted ideal, the payload)."""
    from training import routine_generator, routine_repo

    from mcp import draft_standing_constraint as dcg, nightly_predraft, shared_quantities, tools_hevy_routine as thr, tools_plan

    table = MagicMock()
    table.query.return_value = {"Items": list(LIVE_ITEMS if items is None else items)}
    monkeypatch.setattr(eh, "_table", lambda: table)
    # the real loader over the live-shaped rows, at a passed-in day (no clock)
    monkeypatch.setattr(
        dcg, "_cardio_index_failsoft", lambda: eh.load_history_indexes(lookback_days=30, today=datetime.date(2026, 10, 24))[1]
    )
    monkeypatch.setattr(eh, "load_whoop_workout_index", lambda *a, **k: {})

    def _list(start, end, limit=100):
        if routines_fail:
            raise RuntimeError("ddb down")
        return [r for r in (LIVE_ROUTINES if routines is None else routines) if start <= r.target_date <= end]

    monkeypatch.setattr(routine_repo, "list_by_date_range", _list)
    ideal = _ideal(archetype, role, advanced_by)
    persisted: list = []
    ctx = FIX5000["draft_2167c0e68e25f311d46f1015cbefc047"]["training_context"]
    monkeypatch.setattr(thr, "_authoring_freshness_gate", lambda d: {"ok": True, "gaps": [], "data_current_through": "2026-10-23"})
    monkeypatch.setattr(thr, "_generator_inputs", lambda a: SimpleNamespace(target_date=DAY))
    monkeypatch.setattr(
        thr, "_gather_training_context", lambda d: derive_training_context(ctx["loaded_lifting_streak"], ctx["deficit_state"], DAY)
    )
    monkeypatch.setattr(routine_generator, "generate_routines", lambda inputs: [ideal])
    monkeypatch.setattr(routine_repo, "draft_versioned", persisted.append)
    monkeypatch.setattr(dcg, "_read_memory_summary", lambda sk: MEMORY_TEXT)
    monkeypatch.setattr(tools_plan, "_protein_days_7d", lambda d: (0, 7))
    monkeypatch.setattr(shared_quantities, "recent_aerobic_layer", lambda d: layer)
    out = nightly_predraft._draft(DAY)
    assert out["status"] == "drafted" and persisted == [ideal], out
    return ideal, out


def _cardio(ideal: RoutineSpec) -> tuple[ExerciseBlock, dict]:
    block = ideal.exercises[-1]
    audit = ideal.inputs_snapshot["cardio_notes"][-1]
    return block, audit


# ── the live reproduction: 10-24, Shoulders+arms, loaded legs ────────────────────────────
def test_the_performed_tempo_counts_and_the_week_moves_to_its_intervals(monkeypatch):
    """The 10-24 draft with the routines read: 10-23's empty-note ride is the tempo it was served, so the week has
    done its tempo-or-hills and the next slot is the intervals (never tempo twice running). Intervals is a block the
    charter runs off the treadmill, and the note says so with the charter key on the audit."""
    ideal, out = _predraft(monkeypatch, archetype="upper", role="shoulders_arms", layer=LOADED)
    block, audit = _cardio(ideal)
    assert ideal.inputs_snapshot["cardio_plan"]["week_kinds_before"] == ["easy", "easy", "tempo"]
    assert out["cardio_block"]["pick"]["menu"]["kind"] == "intervals" and audit["kind"] == "intervals"
    assert block.movement_key == "cycling" and block.rationale_tag == "cardio:cycling:menu:intervals"
    assert "cycling" in tc.charter_value("cardio_menu.blocks.intervals.machines")
    assert "treadmill" not in tc.charter_value("cardio_menu.blocks.intervals.machines")
    assert audit["off_default"]["charter"] == "cardio_menu.blocks.intervals.machines"
    line1, line2 = block.notes.split("\n")[:2]
    # #5428: the dose is the easy/hard levels and the hard RPE (no bike speed); line 2 is the ride clock with every start
    assert re.match(r"^Recumbent · L\d+/L\d+ · hard RPE 8 \(a few words\)$", line1) and "mph" not in block.notes
    assert line2.startswith("⌚ ride clock: L") and " min at min " in line2
    # the route's why leaves the wire (the corpus dropped it) and stays on the audit, with its charter key
    assert "Intervals is conditioning" not in block.notes
    assert "Intervals is conditioning, which the menu runs on the bike, air bike, rower or elliptical" in audit["why"]
    assert "the incline walk is the easy-day default." in audit["why"]


def test_MUTATION_CONTROL_without_the_served_routines_the_live_defect_comes_back(monkeypatch):
    """Executed: the same day with the routine read failing (fail-soft) — the ride is read from its empty note alone,
    10-23's tempo counts as easy and the draft re-places tempo, byte for byte the live 10-24 draft's kind."""
    ideal, out = _predraft(monkeypatch, archetype="upper", role="shoulders_arms", layer=LOADED, routines_fail=True)
    assert ideal.inputs_snapshot["cardio_plan"]["week_kinds_before"] == ["easy", "easy", "easy"]
    assert out["cardio_block"]["pick"]["menu"]["kind"] == "tempo"
    assert out["cardio_block"]["pick"]["menu"]["why"].startswith("conditioning 1 of 2 this week")
    _, audit = _cardio(ideal)
    assert audit["off_default"]["charter"] == "cardio_menu.blocks.tempo.machines"


# ── the default: a week whose conditioning is done ──────────────────────────────────────
DONE_WEEK_ROUTINES = [
    _served("hevy-419f", "2026-10-19", "lower", tag="cardio:cycling:menu:easy"),
    _served("hevy-ba78", "2026-10-20", "upper", tag="cardio:cycling:menu:intervals"),
    _served("hevy-019d", "2026-10-23", "lower", tag="cardio:cycling:menu:tempo"),
]


def test_a_shoulders_arms_day_on_fresh_legs_serves_the_incline_walk_with_its_dose(monkeypatch):
    """Conditioning done (intervals 10-21, tempo 10-23, both empty-note rides read from their routines), fresh legs,
    an upper day -> the charter's default, the incline treadmill walk, dosed (incline % + mph + RPE) for the menu's
    minutes, with no off-default reason."""
    ideal, out = _predraft(monkeypatch, archetype="upper", role="shoulders_arms", layer=FRESH, routines=DONE_WEEK_ROUTINES)
    block, audit = _cardio(ideal)
    assert ideal.inputs_snapshot["cardio_plan"]["week_kinds_before"] == ["easy", "intervals", "tempo"]
    assert tc.charter_value("cardio_menu.default") == "incline_treadmill_walk"
    assert block.movement_key == "treadmill" and block.rationale_tag == "cardio:treadmill:menu:incline_treadmill_walk"
    assert out["cardio_block"]["pick"]["menu"]["kind"] == "incline_treadmill_walk" and audit["off_default"] is None
    minutes = cm.block_minutes("incline_treadmill_walk")
    lo_i = tc.charter_value("cardio_menu.blocks.incline_treadmill_walk.starting_dose.incline_pct")[0]
    lo_s = tc.charter_value("cardio_menu.blocks.incline_treadmill_walk.starting_dose.mph")[0]
    lo, hi = tc.charter_value("cardio_menu.blocks.incline_treadmill_walk.rpe")
    # #5428: speed + grade (settings), no minutes on line 1; `today` only when his own logged walks differ
    line1 = block.notes.split("\n")[0]
    assert line1.removeprefix("Treadmill · ").removeprefix("today ") == f"{float(lo_s):.1f} mph, {lo_i:g}% · RPE {lo}–{hi} (full sentences)"
    assert [s.duration_seconds for s in block.sets] == [minutes * 60]
    assert audit["incline_pct"] == lo_i and audit["mph"] == lo_s


# ── the recumbent rule as ruled 2026-10-25 ("a"): conditioning, the day after Lower-heavy, only ─────────────────
AFTER_LOWER_HEAVY = {"date": "2026-10-23", "session_role": "lower_heavy", "was": "week 5 · session 2 of 5 · lower-heavy"}
AFTER_UPPER_VOLUME = {"date": "2026-10-23", "session_role": "upper_volume", "was": "week 5 · session 4 of 5 · upper-volume"}


def test_the_day_after_lower_heavy_a_conditioning_block_rides_the_recumbent_and_says_why(monkeypatch):
    """The live 10-24 week (tempo done 10-23, intervals still due), fresh legs, and the Hevy sequence's last credited
    session was Lower-heavy YESTERDAY (`calendar.advanced_by`) -> the intervals on the recumbent, and the menu's why
    names the rule and the session before; the pick carries the previous session it read."""
    assert "the day immediately after a heavy lower session, for a conditioning block only" in tc.charter_value(
        "cardio_menu.placement.recumbent_after"
    )
    ideal, out = _predraft(monkeypatch, archetype="upper", role="shoulders_arms", layer=FRESH, advanced_by=AFTER_LOWER_HEAVY)
    block, audit = _cardio(ideal)
    menu = out["cardio_block"]["pick"]["menu"]
    assert block.movement_key == "cycling" and audit["kind"] == "intervals" == menu["kind"]
    assert menu["why"].endswith("the recumbent: conditioning the day after Lower-heavy (the session before was lower_heavy on 2026-10-23)")
    assert menu["previous_session"] == {"role": "lower_heavy", "date": "2026-10-23", "day_before": True}
    assert audit["placement_why"] == "placed by the draft"  # the cue pass doses the block the menu placed, never re-places it


def test_the_day_after_lower_heavy_an_easy_day_stays_on_the_incline_walk(monkeypatch):
    """Same day after Lower-heavy, the week's conditioning done -> the incline treadmill walk, never the bike: the ruling
    keeps easy days on the walk. No off-default reason, and the why says the walk held on purpose."""
    ideal, out = _predraft(
        monkeypatch, archetype="upper", role="shoulders_arms", layer=FRESH, routines=DONE_WEEK_ROUTINES, advanced_by=AFTER_LOWER_HEAVY
    )
    block, audit = _cardio(ideal)
    assert block.movement_key == "treadmill" and audit["kind"] == "incline_treadmill_walk" and audit["off_default"] is None
    assert out["cardio_block"]["pick"]["menu"]["why"].endswith(
        "the incline walk: an easy day stays on the walk, also the day after Lower-heavy (the session before was lower_heavy on 2026-10-23)"
    )


def test_a_lower_day_itself_is_no_longer_a_recumbent_day(monkeypatch):
    """Before the ruling a lower session put its own easy block on the bike ("a lower day"). Now a Lower-volume day after
    Upper-volume, conditioning done, fresh legs -> the incline walk."""
    ideal, out = _predraft(
        monkeypatch, archetype="lower", role="lower_volume", layer=FRESH, routines=DONE_WEEK_ROUTINES, advanced_by=AFTER_UPPER_VOLUME
    )
    block, audit = _cardio(ideal)
    assert block.movement_key == "treadmill" and audit["kind"] == "incline_treadmill_walk" and audit["off_default"] is None
    assert "the recumbent" not in out["cardio_block"]["pick"]["menu"]["why"]


# ── the pure seams ──────────────────────────────────────────────────────────────────────
def test_his_own_note_still_wins_over_the_served_kind():
    assert cm.kind_of_performed("cycling", "Level 11 intervals 5x2", "tempo") == "intervals"
    assert cm.kind_of_performed("cycling", "kept it easy, legs dead", "tempo") == "easy"
    assert cm.kind_of_performed("cycling", "", "tempo") == "tempo"
    assert cm.kind_of_performed("cycling", "Level 11 flat", "tempo") == "tempo"  # tempo is flat too
    assert cm.kind_of_performed("cycling", "", None) == "easy"
    # a served kind the menu never runs on the machine he actually used does not carry
    assert cm.kind_of_performed("treadmill", "", "tempo") == "incline_treadmill_walk"
    assert cm.kind_of_performed("treadmill", "", "hills") == "hills"


def test_no_routine_id_on_any_ride_means_no_routine_read(monkeypatch):
    from training import cardio_cues, routine_repo

    def boom(*a, **k):
        raise AssertionError("read the routines with no routine id to match")

    monkeypatch.setattr(routine_repo, "list_by_date_range", boom)
    index = {CYCLING_TID: [{"date": "2026-10-23", "note": "", "duration_sec": 1800.0}]}
    assert cardio_cues.with_served_kinds(index, DAY) is index
