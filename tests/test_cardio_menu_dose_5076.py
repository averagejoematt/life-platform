"""tests/test_cardio_menu_dose_5076.py — the cardio menu with a dose, read from the charter (#5076).

Every block carries a dose (a bike's level + his speed at it, a treadmill's incline + mph) and an RPE /
talk-test target; the incline treadmill walk is the default 'cardio'; conditioning is placed twice a week
(one tempo-or-hills, one intervals), never the same hard shape on consecutive days, the recumbent for
conditioning the day after Lower-heavy or on loaded legs (ruling 2026-10-25); progression is the same RPE at a higher level / incline, written as the reason;
the 2026-10-10 constraint's "no push" half is retired from 2026-10-18; the `draft` path appends the day's
block from the menu; and gym cardio minutes are exposed as `movement_minutes`.

No clock is read (every date is passed in), no AWS is reached (every loader is stubbed) and no AI is called.
The treadmill history is the wire: the 3700 fixture's live Hevy records through the REAL loader.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import sys
from unittest.mock import MagicMock, patch

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO))

import datetime  # noqa: E402

from training import (  # noqa: E402
    cardio_menu as cm,
    cardio_note as cn,
    exercise_history as eh,
    routine_generator as rg,
    standing_constraints as sc,
    training_charter as tc,
)
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402

CYCLING_TID = "D8F7F851"
TREADMILL_TID = "243710DE"
STRETCHING_TID = "527DA061"
CONSTRAINT = sc.active_constraint("2026-10-18")
SEQ = tc.charter_value("split.sequence")
FIX3700 = REPO / "tests" / "fixtures" / "cardio_progression_3700" / "hevy_cardio_2026-05-31_09-19.json"
# Generic words only: a specific vocabulary would itself publish what it screens for (ER-06, #2503).
MEDICAL = ("ecg", "sinus", "clinician", "diagnos")


def _live_cardio_index() -> dict:
    table = MagicMock()
    table.query.return_value = {"Items": json.loads(FIX3700.read_text())}
    with patch.object(eh, "_table", return_value=table):
        return eh.load_history_indexes(lookback_days=365, today=datetime.date(2026, 9, 19))[1]


def _ride(date: str, note: str, level_mph: float = 13.4, minutes: int = 30) -> dict:
    return {"date": date, "note": note, "duration_sec": minutes * 60.0, "distance_m": round(level_mph * 1609.344 * minutes / 60, 1)}


def _bike_facts(level: int = 11, mph: float = 13.4) -> dict:
    return {"last_level": level, "series": [{"date": f"2026-10-1{i}", "level": level, "speed_mph": mph} for i in range(4)]}


# ── the menu: every kind, dosed, from the charter ─────────────────────────────────────
def test_the_menu_covers_every_charter_block_and_names_the_incline_walk_the_default():
    blocks = tc.charter_value("cardio_menu.blocks")
    machine_blocks = {k for k, v in blocks.items() if v.get("machines")}
    assert machine_blocks == set(cm.KINDS), "a menu block the engine cannot place, or a kind the charter does not carry"
    assert cm.default_kind() == "incline_treadmill_walk" == tc.charter_value("cardio_menu.default")
    assert blocks["incline_treadmill_walk"].get("default") is True
    assert cm.conditioning_per_wk() == tc.charter_value("cardio_menu.conditioning_sessions_per_wk") == 2
    assert set(cm.HARD) | set(cm.EASY) == set(cm.KINDS)


def test_every_block_carries_a_dose_and_an_rpe_or_talk_test_target():
    """Every kind on every machine it lists: line 1 matches the grammar, carries a level (a bike, rower, elliptical — #5428:
    never its speed, an output under the iPad) or incline + mph (treadmill), and an RPE number; never a bare modality."""
    tread = _live_cardio_index()[TREADMILL_TID]
    offenders = []
    for kind in cm.KINDS:
        for machine in cm.block(kind)["machines"]:
            note, audit = cn.compose(
                movement_key=machine,
                minutes=cm.block_minutes(kind),
                target_date="2026-10-20",
                kind=kind,
                facts=_bike_facts(),
                treadmill_sessions=tread,
            )
            line1 = note.split("\n")[0]
            m = cn.LINE1_RE.match(line1)
            walk = machine == cm.TREADMILL
            dosed = m and ((m.group("level") and not walk and "mph" not in note) or (walk and m.group("incline") and m.group("walk_mph")))
            if not (dosed and re.search(r"\bRPE \d", line1) and audit["kind"] == kind and len(note.split("\n")) <= 3):
                offenders.append(f"{kind}/{machine}: {line1!r}")
    assert not offenders, "\n".join(offenders)


def test_the_bike_carries_level_and_rpe_and_keeps_its_speed_in_the_audit():
    note, audit = cn.compose(movement_key="cycling", minutes=30, target_date="2026-10-20", kind="easy", facts=_bike_facts())
    lo, hi = tc.charter_value("cardio_menu.blocks.easy.rpe")
    assert note == f"Recumbent · L11 · RPE {lo}–{hi} (full sentences)"
    assert audit["mph"] == 13.4  # his speed at the level: on the record, never on the wire (#5428)


def test_the_numbers_are_read_from_the_charter_not_restated(monkeypatch):
    """Mutation: move the easy band in the charter — line 1 follows. A hand copy would not."""
    real = tc.charter_value

    def moved(dotted, default=None):
        v = real(dotted, default)
        if dotted == "cardio_menu":
            v["blocks"]["easy"]["rpe"] = [3, 4]
        return v

    monkeypatch.setattr(tc, "charter_value", moved)
    note = cn.compose(movement_key="cycling", minutes=30, target_date="2026-10-20", kind="easy", facts=_bike_facts())[0]
    assert "RPE 3–4" in note.split("\n")[0]


# ── the default and the incline walk's starting dose (his treadmill history) ───────────
def test_fresh_legs_on_an_upper_day_with_the_week_done_get_the_default_incline_walk():
    pick = cm.choose_kind(target_date="2026-10-23", archetype="Upper-volume", week_kinds=["tempo", "intervals"], legs_loaded=False)
    assert pick == {
        "kind": "incline_treadmill_walk",
        "machine": "treadmill",
        "why": "the week's conditioning is done: easy; the incline walk: an easy day stays on the walk (the session before was not read)",
        "needed": [],
    }


def test_the_incline_walk_starts_at_the_band_floor_from_his_treadmill_history():
    """His live treadmill notes (0.5-1.5 % at 3.0 mph, 6 % at 2.8 mph on 23 Jun) sit under the 8-12 % band:
    the walk starts at the floor incline at the speed of his steepest walk, and says so."""
    dose = cm.treadmill_dose(_live_cardio_index()[TREADMILL_TID])
    lo_inc = tc.charter_value("cardio_menu.blocks.incline_treadmill_walk.starting_dose.incline_pct")[0]
    assert dose["incline_pct"] == lo_inc and dose["mph"] == 2.8 and dose["basis"] == "his steepest walk"
    assert dose["reason"] == f"start: {lo_inc}% (the menu's floor; your steepest walk on record is 6% at 2.8 mph) at 2.8 mph"


def test_no_treadmill_history_starts_at_the_band_floor():
    dose = cm.treadmill_dose([])
    band = tc.charter_value("cardio_menu.blocks.incline_treadmill_walk.starting_dose")
    assert (dose["incline_pct"], dose["mph"]) == (band["incline_pct"][0], band["mph"][0])


# ── progression: same RPE at a higher level / incline, written as the reason ───────────
def test_a_raise_verdict_moves_the_bike_one_level_and_writes_why():
    verdict = {
        "verdict": "raise",
        "basis": "last 4 at level 11 averaged 14.2 mph vs 13.4 mph before (+0.8), clearing his own 0.3 mph within-level spread",
    }
    note, audit = cn.compose(
        movement_key="cycling", minutes=30, target_date="2026-10-20", kind="easy", facts=_bike_facts(), verdict=verdict
    )
    assert note.split("\n")[0].startswith("Recumbent · L12 · RPE ")
    # #5428: the reason is the audit's (the chat tells the story), never a tail on the wire
    assert audit["dose_reason"] == f"+1 level: {verdict['basis']} — same RPE, one level up"
    assert "\n" not in note
    assert audit["level"] == 12 and audit["hold_level"] == 11


def test_a_tempo_day_after_a_raise_is_one_level_up_never_two():
    """Review round 2: last_level 11 + a `raise` verdict + tempo -> level 12 (baseline + the tempo step),
    never 13 (the raise AND the tempo step stacked). The easy block on the same facts is also 12."""
    facts, verdict = {"last_level": 11}, {"verdict": "raise", "basis": "his speed cleared his spread"}
    tempo = cm.bike_dose("tempo", facts, verdict)
    assert (tempo["level"], tempo["hold_level"]) == (11 + cm.TEMPO_LEVEL_STEP, 11) == (12, 11), tempo
    assert "+1 level" not in tempo["reason"], "the raise is not applied on top of the tempo step"
    assert cm.bike_dose("easy", facts, verdict)["level"] == 12
    assert cm.bike_dose("tempo", facts, {"verdict": "hold"})["level"] == 12, "tempo is baseline + step with or without a raise"


def test_a_missing_charter_default_is_a_loud_error_not_a_fallback(monkeypatch):
    real = tc.charter_value
    monkeypatch.setattr(
        tc, "charter_value", lambda dotted, default=None: None if dotted == "cardio_menu.default" else real(dotted, default)
    )
    try:
        cm.default_kind()
    except KeyError:
        return
    raise AssertionError("default_kind() fell back to a literal when the charter key was missing")


def test_two_held_walks_step_the_incline_then_the_top_steps_the_speed():
    def walk(date, inc, mph):
        return {"date": date, "note": f"{inc} incline", "duration_sec": 1800.0, "distance_m": round(mph * 1609.344 / 2, 1)}

    held = cm.treadmill_dose([walk("2026-10-22", 9, 2.8), walk("2026-10-20", 9, 2.8)])
    assert (held["incline_pct"], held["mph"]) == (10.0, 2.8)
    assert held["reason"] == "+1%: your last 2 walks held 9% at 2.8 mph — same RPE, one step steeper"
    once = cm.treadmill_dose([walk("2026-10-22", 9, 2.8), walk("2026-10-20", 8, 2.8)])
    assert (once["incline_pct"], once["mph"]) == (9.0, 2.8) and once["reason"].startswith("hold 9% at 2.8 mph")
    top = cm.treadmill_dose([walk("2026-10-22", 12, 2.8), walk("2026-10-20", 12, 2.8)])
    assert (top["incline_pct"], top["mph"]) == (12.0, 2.9) and top["reason"].startswith("+0.1 mph: 12% is the top of the band")


# ── the weekly placement over a 7-day fixture ─────────────────────────────────────────
WEEK = [
    {"date": "2026-10-19", "archetype": SEQ[0]},
    {"date": "2026-10-20", "archetype": SEQ[1]},
    {"date": "2026-10-21", "archetype": SEQ[2]},
    {"date": "2026-10-22", "archetype": SEQ[3]},
    {"date": "2026-10-23", "archetype": SEQ[4]},
    {"date": "2026-10-24", "archetype": None},
    {"date": "2026-10-25", "archetype": None},
]


def test_the_week_places_two_conditioning_blocks_and_the_rest_easy():
    placed = cm.place_week(WEEK)
    kinds = [p["kind"] if p else None for p in placed]
    machines = [p["machine"] if p else None for p in placed]
    assert kinds == ["tempo", "incline_treadmill_walk", "intervals", "incline_treadmill_walk", "incline_treadmill_walk", None, None], kinds
    assert machines == ["cycling", "treadmill", "cycling", "treadmill", "treadmill", None, None], machines
    hard = [k for k in kinds if k in cm.HARD]
    assert len(hard) == cm.conditioning_per_wk() and "intervals" in hard and ({"tempo", "hills"} & set(hard))
    assert all(not (a in cm.HARD and a == b) for a, b in zip(kinds, kinds[1:])), "the same hard shape on consecutive days"
    # ruling 2026-10-25 (#5076, "a"): the recumbent only for conditioning the day after Lower-heavy; lower days walk
    assert placed[2]["why"].endswith(
        f"the recumbent: conditioning the day after {SEQ[1]} (the session before was lower_heavy on 2026-10-20)"
    )
    assert placed[1]["why"].endswith("the incline walk: an easy day stays on the walk (the session before was upper_heavy on 2026-10-19)")
    assert "the recumbent" not in placed[4]["why"]
    # tempo on a fresh Monday rides the bike by the menu's own machines (no treadmill tempo), never by the recumbent rule
    assert placed[0]["why"].endswith(
        "tempo on the bike: the menu's machines for tempo (cardio_menu.blocks.tempo.machines), not the recumbent rule"
    )


def test_tempo_and_hills_alternate_week_to_week():
    assert cm.place_week(WEEK, last_tempo_or_hills="tempo")[0]["kind"] == "hills"
    assert cm.place_week(WEEK, last_tempo_or_hills="hills")[0]["kind"] == "tempo"


def test_never_the_same_hard_shape_on_consecutive_days_even_when_the_week_is_short():
    pick = cm.choose_kind(
        target_date="2026-10-19", archetype=SEQ[3], prior_day_kind="tempo", last_tempo_or_hills="hills", days_left=1, legs_loaded=False
    )
    assert pick["kind"] == "intervals"


def test_a_heavy_walking_weekend_puts_an_easy_day_on_the_recumbent():
    pick = cm.choose_kind(target_date="2026-10-22", archetype=SEQ[3], week_kinds=["tempo", "intervals"], legs_loaded=True)
    assert (pick["kind"], pick["machine"]) == ("easy", "cycling") and "heavy walking load" in pick["why"]


def test_yellow_or_red_is_easy_whatever_the_week_needs():
    for band in ("yellow", "red"):
        assert cm.choose_kind(target_date="2026-10-19", archetype=SEQ[0], recovery_band=band, legs_loaded=False)["kind"] in cm.EASY


def test_the_lower_predicate_is_the_charters_sequence():
    assert {s for s in SEQ if cm.is_lower(s)} == {s for s in SEQ if "lower" in s.lower()}
    from training import recent_aerobic

    assert all(recent_aerobic.is_lower(s) == cm.is_lower(s) for s in SEQ + ["lower", "legs", "upper", "push"])


# ── the retired no-push gate, said neutrally ──────────────────────────────────────────
def test_the_no_push_gate_is_retired_from_the_ruling_day_and_the_hr_half_stays():
    assert sc.intensity_gate_active(CONSTRAINT, "2026-10-17") is True
    assert sc.intensity_gate_active(CONSTRAINT, "2026-10-18") is False
    assert sc.intensity_gate_active(None, "2026-10-17") is False
    assert CONSTRAINT["hr_prescriptions_allowed"] is False  # the HR half stands: no HR target on any block
    for kind in cm.KINDS:
        machine = cm.block(kind)["machines"][0]
        note, audit = cn.compose(
            movement_key=machine,
            minutes=30,
            target_date="2026-10-20",
            kind=kind,
            facts=_bike_facts(),
            constraint=CONSTRAINT,
            hr_ceiling_bpm=120,
        )
        assert audit["kind"] == kind and audit["no_push_gate"] is False
        assert "No push" not in note and "bpm" not in note and "HR" not in note  # #5428: RPE + talk test lead


def test_the_retirement_names_nothing_medical():
    text = json.dumps(
        {k: CONSTRAINT[k] for k in ("intensity_gate_retired_from",)} | {"p": CONSTRAINT["provenance"]["intensity_gate_retired_from"]}
    ).lower()
    notes = " ".join(
        cn.compose(movement_key=cm.block(k)["machines"][0], minutes=30, target_date=d, kind=k, facts=_bike_facts(), constraint=CONSTRAINT)[
            0
        ]
        for k in cm.KINDS
        for d in ("2026-10-17", "2026-10-20")
    ).lower()
    assert not [w for w in MEDICAL if w in text or re.search(rf"\b{w}\b", notes)]
    src = (REPO / "lambdas" / "training" / "cardio_menu.py").read_text().lower()
    assert not [w for w in MEDICAL if re.search(rf"\b{w}\b", src)]


# ── the draft path produces the day's block from the menu ─────────────────────────────
def test_the_draft_path_appends_the_menus_block_with_its_dose_and_movement_minutes(monkeypatch):
    """`gate_draft` (the `manage_hevy_routine draft` step the nightly predraft runs): a week that already
    did its tempo and intervals, fresh legs, an upper day -> the default incline walk, dosed, 30 min.
    Mutation control: drop `ideal.exercises.append(cardio)` in gate_draft — this reds on the first assert."""
    from mcp import draft_standing_constraint as dcg, shared_quantities

    index = {
        CYCLING_TID: [_ride("2026-10-21", "Level 11 intervals 5x2"), _ride("2026-10-19", "Level 12 tempo", minutes=40)],
        TREADMILL_TID: list(_live_cardio_index()[TREADMILL_TID]),
        STRETCHING_TID: [{"date": "2026-10-21", "note": "", "duration_sec": 600.0, "distance_m": None}],
    }
    layer = {"state": "read", "totals": {"weight_bearing_hr_48h": 0.5, "walks_over_75_min_48h": 0}}
    monkeypatch.setattr(dcg, "read_standing_constraint", lambda d: {**CONSTRAINT, "stop_list": "x", "memory_read": "ok"})
    monkeypatch.setattr(dcg, "protein_tripwire", lambda d: {"id": dcg.GREEN_TRIPWIRE, "state": "clear"})
    monkeypatch.setattr(dcg, "_cardio_index_failsoft", lambda: index)
    monkeypatch.setattr(shared_quantities, "recent_aerobic_layer", lambda d: layer)
    monkeypatch.setattr(eh, "load_whoop_workout_index", lambda *a, **k: {})
    lift = ExerciseBlock(movement_key="barbell_bench_press", sets=[Set(weight_kg=60.0, reps=8)], rationale_tag="primary:chest")
    ideal = RoutineSpec(routine_id="fixture-5076", target_date="2026-10-22", archetype=SEQ[3], variant="ideal", exercises=[lift])
    out = dcg.gate_draft(ideal, "2026-10-22", lambda c, w: {})
    cardio = ideal.exercises[-1]
    assert out["cardio_block"]["appended"] is True and cardio is not lift
    assert cardio.movement_key == "treadmill" and cardio.rationale_tag == "cardio:treadmill:menu:incline_treadmill_walk"
    minutes = tc.charter_value("split.session_minutes.cardio_block_max")
    assert [s.duration_seconds for s in cardio.sets] == [minutes * 60]
    # #5428: the speed and grade are settings, so they are prescribed — `today`, because his own logged walks (his
    # usual, 0.5-1.5 % at 3.0 mph) differ from the menu's band; no minutes on line 1 (the set row shows them)
    assert cardio.notes.split("\n")[0].startswith("Treadmill · today 2.8 mph, 8% · RPE ")
    assert out["cardio_block"]["pick"]["menu"]["kind"] == "incline_treadmill_walk"
    plan = ideal.inputs_snapshot["cardio_plan"]
    assert plan["movement_minutes"] == minutes == out["cardio_block"]["movement_minutes"]
    assert plan["week_kinds_before"] == ["tempo", "intervals"] and plan["charter_version"] == tc.charter_version()


def test_the_draft_path_with_no_history_starts_the_week_on_conditioning(monkeypatch):
    from mcp import draft_standing_constraint as dcg

    block, pick = dcg.cardio_block(
        "2026-10-19", SEQ[0], None, layer={"state": "read", "totals": {"weight_bearing_hr_48h": 0.0}}, cardio_index=None
    )
    assert pick["menu"]["kind"] == "tempo" and block.rationale_tag == "cardio:cycling:menu:tempo"
    # #5201: the menu names 40, the split caps one cardio block at 30 — the block is the capped one and its note
    # drops the label that would claim 40
    assert [s.duration_seconds for s in block.sets] == [tc.charter_value("split.session_minutes.cardio_block_max") * 60]
    assert "RPE 6–7 (short phrases)" in block.notes and "hard flat 40" not in block.notes and " min ·" not in block.notes


# ── movement minutes ──────────────────────────────────────────────────────────────────
def test_movement_minutes_count_gym_cardio_and_nothing_else():
    exercises = [
        ExerciseBlock(movement_key="cycling", sets=[Set(duration_seconds=1800)]),
        ExerciseBlock(movement_key="treadmill", sets=[Set(duration_seconds=600), Set(duration_seconds=600)]),
        ExerciseBlock(movement_key="plank", sets=[Set(duration_seconds=60)]),
    ]
    assert cm.movement_minutes(exercises) == 50
    index = {
        CYCLING_TID: [_ride("2026-10-21", "Level 11 flat", minutes=30)],
        STRETCHING_TID: [{"date": "2026-10-21", "duration_sec": 600.0}],
    }
    ids = cm.machine_template_ids(rg._load_json("movement_catalog.json"))
    assert ids[CYCLING_TID] == "cycling" and STRETCHING_TID not in ids
    assert cm.performed_movement_minutes(index, "2026-10-21", ids) == 30
    assert tc.charter_value("steps.gym_cardio_minutes_count_toward_movement") is True


def test_a_redraft_keeps_the_kind_it_placed():
    spec = RoutineSpec(
        routine_id="x",
        target_date="2026-10-19",
        archetype=SEQ[0],
        exercises=[ExerciseBlock(movement_key="cycling", sets=[Set(duration_seconds=2400)])],
    )
    index = {CYCLING_TID: [_ride("2026-10-16", "Level 11 flat")]}
    rg.attach_cardio_cues(
        spec, cardio_index=index, whoop_index={}, aerobic_block={"state": "read", "totals": {"weight_bearing_hr_48h": 0.0}}
    )
    first = spec.exercises[0].notes
    assert spec.inputs_snapshot["cardio_notes"][0]["kind"] == "tempo"
    rg.attach_cardio_cues(
        spec, cardio_index=index, whoop_index={}, aerobic_block={"state": "read", "totals": {"weight_bearing_hr_48h": 0.0}}
    )
    assert spec.exercises[0].notes == first
