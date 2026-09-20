"""tests/test_cardio_progression_3700.py — cardio gets a progression loop (#3700).

WHAT WENT WRONG

ADR-068 pulls a factual "Last: …" cue into every generated routine. `render_history_cue`
reads a top-set weight and a reps list; a cardio set carries neither, so every cycling
block hit `if not weight or not reps: return ""`. The outer half of the defect is worse:
`load_recent_history` drops any set whose `reps` is not > 0, so a ride never reached the
index the renderer reads. Notes and numbers went in and nothing came back out.

THE FIXTURES ARE THE WIRE

`tests/fixtures/cardio_progression_3700/*.json` are field-projected copies of LIVE
DynamoDB records read 2026-09-19 — every Hevy workout carrying a duration-bearing block
since 2026-05-31, every Whoop workout row over the same window, and the actual stored
routine spec for 2026-09-19. They carry the noise that matters and that a shape written
from a comment would not have:

  * the wire field is `exercises[].notes` — PLURAL, on the exercise. The issue's own
    comment calls it `note`.
  * "Level 9 - 5.6 miles" — a level followed by a DECIMAL, which the shared level span
    pattern reads as the range "9 to 5" and which silently cost this exact ride its level.
  * "Level 9 for 20 and then level 6 for 10" — one ride, two levels.
  * "L9-10 i think is easy …" — a calibration statement, not a session level.
  * `Stretching`, duration-bearing on the same wire as a ride and carrying nothing.
  * a Whoop "Cross Training" row spanning the WHOLE two-hour gym session, and (09-12) a
    workout whose duration matches two different blocks in the same session.

EACH TEST NAMES THE MUTATION THAT REDS IT.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import (
    cardio_progression as cp,  # noqa: E402
    exercise_history as eh,  # noqa: E402
    routine_generator as rg,  # noqa: E402
)

FIXTURES = Path(__file__).parent / "fixtures" / "cardio_progression_3700"
CYCLING_TID = "D8F7F851"  # config/movement_catalog.json -> movements.cycling
STRETCH_TID = "527DA061"
POSITIVE_CONTROL_CUE = "Last: level 9, 5.60 mi in 30:00 (11.2 mph)"


def _live_hevy() -> list[dict[str, Any]]:
    return json.loads((FIXTURES / "hevy_cardio_2026-05-31_09-19.json").read_text())


def _live_whoop() -> list[dict[str, Any]]:
    return json.loads((FIXTURES / "whoop_workouts_2026-05-31_09-19.json").read_text())


def _live_routine() -> dict[str, Any]:
    return json.loads((FIXTURES / "routine_2026-09-19_push.json").read_text())


def _indexes(items: list[dict[str, Any]] | None = None):
    """Drive the REAL `load_history_indexes` with the live records through a stub Query.

    Deliberately not a hand-built index: the loader is half the fix (a cardio set never
    reached the old index at all), so a test that hand-shapes the index would pass over
    the very code that was broken.
    """
    items = _live_hevy() if items is None else items
    table = MagicMock()
    table.query.return_value = {"Items": items}
    with patch.object(eh, "_table", return_value=table):
        return eh.load_history_indexes(lookback_days=365, today=__import__("datetime").date(2026, 9, 19))


def _whoop_index() -> dict[str, list[dict[str, Any]]]:
    table = MagicMock()
    table.query.return_value = {"Items": _live_whoop()}
    with patch.object(eh, "_table", return_value=table):
        return eh.load_whoop_workout_index(lookback_days=365, today=__import__("datetime").date(2026, 9, 19))


# ── acceptance box 1: the positive control ────────────────────────────────────────────


def test_the_live_2026_09_07_ride_renders_the_cue_that_render_history_cue_returns_empty_for():
    """THE positive control the issue states verbatim. The old renderer must still return
    '' for this record and the new one must render the line.

    Mutation control: delete the `modality == "cardio"` branch in
    `exercise_history.render_history_cue` — the second assertion reds with ''.
    """
    only_0907 = [w for w in _live_hevy() if w["date"] == "2026-09-07"]
    weighted, cardio = _indexes(only_0907)

    # the defect, still reproducible through the weighted path
    assert eh.render_history_cue(eh.history_facts(CYCLING_TID, weighted)) == ""

    facts = eh.history_facts(CYCLING_TID, weighted, cardio_index=cardio, whoop_index=_whoop_index())
    cue = eh.render_history_cue(facts)
    assert cue.startswith(POSITIVE_CONTROL_CUE), cue
    assert '"Level 9 - 5.6 miles"' in cue  # the raw note is sovereign and is quoted


def test_the_cardio_block_reaches_the_index_the_weighted_one_drops_it_from():
    """Mutation control: restore the old `if not sets: continue` ordering so the cardio
    collection sits after the reps filter — `cardio` loses the cycling key entirely."""
    weighted, cardio = _indexes()
    assert CYCLING_TID not in weighted, "a ride has no weighted sets and must not enter the weighted index"
    assert cardio[CYCLING_TID], "the cycling block must reach the cardio index"
    assert weighted, "strength templates must still be indexed"


def test_the_weighted_index_shape_is_untouched_by_the_cardio_arm():
    """The load-floor machinery reads `top_weight_kg`/`sets` off these sessions. A cardio
    session folded in would be a zero-weight session in a movement's history.

    Mutation control: merge `cardio` into `index` in `load_history_indexes` — a rep-less
    session appears here and the assertion reds. (A zero `top_weight_kg` is NOT the tell:
    bodyweight movements legitimately carry one. Rep-bearing sets are.)
    """
    weighted, cardio = _indexes()
    for tid, sessions in weighted.items():
        for s in sessions:
            assert s["sets"] and all(x["reps"] > 0 for x in s["sets"]), f"{tid} carries a rep-less session"
            assert set(s) == {"date", "sets", "top_weight_kg"}, f"{tid} session shape changed"
    assert not (set(cardio) & set(weighted)), "no template may appear in both indexes"


def test_the_note_is_read_from_the_plural_exercises_notes_field():
    """The live wire field is `notes`, on the EXERCISE. The issue's own comment says
    `note`, and the workout-level `description` was empty on the record it was filed
    against.

    Mutation control: read `ex.get("note")` only — every cardio session's note goes empty
    and the assertion reds.
    """
    _, cardio = _indexes()
    by_date = {s["date"]: s for s in cardio[CYCLING_TID]}
    assert by_date["2026-09-07"]["note"] == "Level 9 - 5.6 miles"
    assert by_date["2026-09-19"]["note"] == "Level 15 flat"


# ── acceptance box 5 (structured level) ───────────────────────────────────────────────


def test_level_regex_is_held_identical_to_the_notes_taxonomy_pattern():
    """Two copies of a level parser that disagree is how one ride becomes two facts.

    Mutation control: change either pattern — this reds. (It is a COPY on purpose: the
    structured level must not depend on the extractor module being importable.)
    """
    from training import training_notes

    assert cp.LEVEL_RE.pattern == training_notes._LEVEL_SPAN_RE.pattern


def test_a_descending_span_is_not_a_range_because_the_live_note_says_level_9_minus_5_point_6_miles():
    """ "Level 9 - 5.6 miles" must be level 9, not the span 9→5.

    Mutation control: drop the `_is_decimal_head` / `high < low` guard in
    `structured_level` — status becomes `level_range`, `level` becomes None, and the
    positive control loses its "level 9,".
    """
    out = cp.structured_level("Level 9 - 5.6 miles")
    assert out["status"] == "ok" and out["level"] == 9, out


def test_a_two_level_ride_refuses_to_report_a_single_level():
    """Live 2026-06-22. Reporting "level 9" for a ride that spent a third of itself at 6
    would put a number on the record nobody logged.

    Mutation control: return the first match instead of refusing — status becomes `ok`
    and this reds.
    """
    out = cp.structured_level("Level 9 for 20 and then level 6 for 10 - more of a flush")
    assert out["status"] == "multi_level_session" and out["level"] is None


def test_a_level_span_is_a_calibration_claim_not_a_session_level():
    """Live 2026-06-25. "L9-10 … is easy" says what a level MEANS; it is not what the ride
    was done at.

    Mutation control: accept the span's low bound as the level — status becomes `ok`.
    """
    out = cp.structured_level("L9-10 i think is easy - probably for my weight and heavy legs.")
    assert out["status"] == "level_range" and out["level"] is None


def test_the_structured_level_never_depends_on_the_llm_extractor():
    """Box 1: a level decision must survive the extractor layer being unavailable.

    Mutation control: import `calibration_anchors` at module scope in
    `cardio_progression` instead of inside `_calibration_anchors` — the import error
    escapes and this reds.
    """
    with patch.dict("sys.modules", {"training.training_notes": None}):
        out = cp.structured_level("Level 15 flat")
        assert out["level"] == 15
        assert cp._calibration_anchors("L9-10 is easy") == []


# ── acceptance box 5 (distance + duration on every ride, observable not asserted) ──────


def test_speed_is_none_not_zero_when_a_ride_has_no_distance():
    """A machine that shut off mid-ride (live 2026-09-10 note) has an UNKNOWN distance. A
    0.0 mph row in a speed series is a measurement claim nobody made (ADR-104).

    Mutation control: `return 0.0` instead of None — this reds, and the excluded-count
    test below stops counting the ride.
    """
    assert cp.speed_mph(None, 1800) is None
    assert cp.speed_mph(0, 1800) is None
    assert cp.speed_mph(9012, 1800) == 11.2


def test_rides_dropped_from_the_series_are_counted_by_reason_not_silently_lost():
    """A thin series must be legible as WHICH rides were dropped, never as a short history.

    Mutation control: drop the `excluded` bookkeeping — the dict is empty and this reds.
    """
    _, cardio = _indexes()
    facts = cp.cardio_facts(CYCLING_TID, cardio, _whoop_index())
    assert facts["sessions_count"] == 19
    assert facts["excluded"]["multi_level_session"] == 2
    assert facts["excluded"]["no_note"] == 7
    assert len(facts["series"]) + sum(facts["excluded"].values()) == facts["sessions_count"]


# ── acceptance box 5 (HR windowed to the ride) ────────────────────────────────────────


def test_the_session_scoped_whoop_average_is_never_substituted_for_hr_at_level():
    """Live 2026-09-07: the only Whoop workout carrying an average HR runs 3,959 s across
    the whole gym session, against an 1,800 s bike block. Calling 118 bpm "HR at level 9"
    would be the exact ADR-104 violation this issue was filed against.

    Mutation control: widen HR_DURATION_TOLERANCE to 2.0 (or fall back to the nearest
    candidate) — status becomes `ok` and this reds.
    """
    _, cardio = _indexes()
    ride = [s for s in cardio[CYCLING_TID] if s["date"] == "2026-09-07"][0]
    out = cp.join_whoop_hr(
        ride["session_start"],
        ride["session_end"],
        ride["duration_sec"],
        _whoop_index()["2026-09-07"],
        sibling_block_seconds=ride["sibling_block_seconds"],
    )
    assert out["status"] == "no_ride_scoped_match"
    assert out["average_heart_rate"] is None


def test_a_whoop_workout_that_also_matches_a_sibling_block_is_refused():
    """Live 2026-09-12: a 1,739 s "Hiking" row matches the 1,800 s CYCLING block and,
    equally, the 1,800 s WALKING block beside it. A per-block join blind to siblings sees
    one candidate and reports the treadmill's heart rate as the bike's.

    Mutation control: stop passing `sibling_block_seconds` (or drop the collision check)
    — status becomes `ok` with average_heart_rate 123 and this reds.
    """
    _, cardio = _indexes()
    ride = [s for s in cardio[CYCLING_TID] if s["date"] == "2026-09-12"][0]
    out = cp.join_whoop_hr(
        ride["session_start"],
        ride["session_end"],
        ride["duration_sec"],
        _whoop_index()["2026-09-12"],
        sibling_block_seconds=ride["sibling_block_seconds"],
    )
    assert out["status"] == "ambiguous_sibling_block"
    assert out["average_heart_rate"] is None


def test_the_join_does_fire_when_a_whoop_workout_really_is_the_ride():
    """Live 2026-09-19: "Cross Training" 16:23–17:07 (2,639 s) inside a session holding a
    2,700 s bike and a 3,600 s treadmill. Unique, in-window, duration-matched -> 103 bpm.

    Mutation control: narrow HR_DURATION_TOLERANCE to 0.01 — the only ride-scoped HR the
    corpus has disappears and this reds. (A refusal-only join is not evidence of care.)
    """
    _, cardio = _indexes()
    ride = [s for s in cardio[CYCLING_TID] if s["date"] == "2026-09-19"][0]
    out = cp.join_whoop_hr(
        ride["session_start"],
        ride["session_end"],
        ride["duration_sec"],
        _whoop_index()["2026-09-19"],
        sibling_block_seconds=ride["sibling_block_seconds"],
    )
    assert out["status"] == "ok" and out["average_heart_rate"] == 103
    assert out["scope"] == "ride"


def test_the_day_level_whoop_row_is_never_read_as_a_rides_heart_rate():
    """The `DATE#` row's average_heart_rate is a 24-hour figure — mostly sleeping.

    Mutation control: drop the `"#WORKOUT#" not in sk: continue` guard in
    `load_whoop_workout_index` — the day rows join the index and this reds.
    """
    idx = _whoop_index()
    day_rows = [r for r in _live_whoop() if "#WORKOUT#" not in r["sk"]]
    assert not day_rows, "fixture projection should already be workout-only"
    table = MagicMock()
    table.query.return_value = {
        "Items": [
            {"sk": "DATE#2026-09-07", "date": "2026-09-07", "average_heart_rate": 71},
            {"sk": "DATE#2026-09-07#WORKOUT#x", "date": "2026-09-07", "average_heart_rate": 118},
        ]
    }
    with patch.object(eh, "_table", return_value=table):
        built = eh.load_whoop_workout_index(lookback_days=30, today=__import__("datetime").date(2026, 9, 19))
    assert [r["average_heart_rate"] for r in built["2026-09-07"]] == [118.0]
    assert idx  # the live index still builds


# ── acceptance box 4: the rule, and the claim it refuses to make ──────────────────────


def test_n_required_is_derived_from_the_effect_size_rather_than_picked():
    """`k` is the block size whose mean is precise to half the effect; the rule needs two
    such blocks. Both follow from EFFECT_IN_SD — neither is a typed-in integer.

    Mutation control: hard-code BLOCK_K = 3 — the derivation no longer holds and this reds.
    """
    import math

    assert cp.BLOCK_K == math.ceil(4.0 * (1.0 / cp.EFFECT_IN_SD) ** 2)
    assert cp.N_REQUIRED_AT_LEVEL == 2 * cp.BLOCK_K


def test_no_improvement_is_claimed_off_the_live_corpus_at_any_level():
    """Box 5 of the filed acceptance, and box 4 of the owner's amendment: no surface may
    render "your cardio is improving" below n. Level 15 has n=1 and level 10 — his busiest
    — has n=5 against a required 8.

    Mutation control: let `level_verdict` fall through to the block comparison without the
    `len(at) < N_REQUIRED_AT_LEVEL` return — a verdict is emitted on five rides and
    `claims_improvement` can go True.
    """
    _, cardio = _indexes()
    facts = cp.cardio_facts(CYCLING_TID, cardio, _whoop_index())
    for level in {r["level"] for r in facts["series"]}:
        v = cp.level_verdict(facts["series"], level)
        assert v["claims_improvement"] is False, (level, v)
        assert v["verdict"] == "insufficient_n", (level, v)
    ten = cp.level_verdict(facts["series"], 10)
    assert ten["n_at_level"] == 5 and ten["n_required"] == 8
    assert ten["within_level_sd_mph"] == 1.23  # his own measured spread, not a chosen number


def _series(level: int, speeds: list[float]) -> list[dict[str, Any]]:
    return [{"date": f"2026-0{1 + i // 28}-{1 + i % 28:02d}", "level": level, "speed_mph": s} for i, s in enumerate(speeds)]


def test_a_raise_needs_a_gain_larger_than_his_own_within_level_spread():
    """Mutation control: compare `delta > 0` instead of `delta >= effect_mph` — the hold
    case below flips to `raise` and that test reds."""
    v = cp.level_verdict(_series(10, [10.0, 10.1, 9.9, 10.0, 13.0, 13.1, 12.9, 13.0]), 10)
    assert v["verdict"] == "raise" and v["claims_improvement"] is True
    assert v["delta_mph"] >= v["effect_mph"]


def test_a_gain_inside_his_own_noise_is_a_hold_not_a_raise():
    """Eight sessions, a real but small upward drift. The rule must hold.

    Mutation control: set EFFECT_IN_SD = 0.1 — the same series becomes a `raise`.
    """
    v = cp.level_verdict(_series(10, [10.0, 11.5, 9.0, 11.0, 10.4, 11.8, 9.4, 11.2]), 10)
    assert v["verdict"] == "hold" and v["claims_improvement"] is False
    assert v["delta_mph"] < v["effect_mph"]


def test_the_hr_arm_reports_its_own_insufficiency_by_name():
    """Speed alone confounds fitness with effort, so a speed-only verdict must say so
    rather than read as a two-signal verdict.

    Mutation control: drop the `hr_arm` block — this reds on the key.
    """
    _, cardio = _indexes()
    facts = cp.cardio_facts(CYCLING_TID, cardio, _whoop_index())
    v = cp.level_verdict(facts["series"], 10)
    assert v["hr_arm"]["status"] == "insufficient_hr_n"
    assert v["hr_arm"]["n_with_ride_scoped_hr"] == 0
    assert "confounds fitness with effort" in v["hr_arm"]["note"]


def test_the_cue_suggests_nothing_while_n_is_insufficient():
    """Box 4: at low n the cue states the baseline and suggests nothing.

    Mutation control: append the verdict basis unconditionally in `render_cardio_cue` —
    "n=1 at level 15" lands in a routine note and this reds.
    """
    _, cardio = _indexes()
    facts = cp.cardio_facts(CYCLING_TID, cardio, _whoop_index())
    cue = cp.render_cardio_cue(facts, cp.level_verdict(facts["series"], facts["last_level"]))
    assert cue.startswith("Last: level 15,")
    for banned in ("hold level", "raise level", "improv", "insufficient", "n="):
        assert banned not in cue, cue


def test_a_decided_verdict_does_reach_the_cue_with_its_basis():
    """The suppression above must be about n, not about never suggesting anything.

    Mutation control: never append the verdict — this reds.
    """
    facts = {
        "sessions_count": 8,
        "modality": "cardio",
        "last_date": "2026-09-19",
        "last_duration_sec": 2700,
        "last_distance_m": 17220,
        "last_speed_mph": 14.27,
        "last_level": 10,
        "last_note": "Level 10 flat",
        "calibration": [],
    }
    v = cp.level_verdict(_series(10, [10.0, 10.1, 9.9, 10.0, 13.0, 13.1, 12.9, 13.0]), 10)
    cue = cp.render_cardio_cue(facts, v)
    assert "raise level 10:" in cue and "mph" in cue


# ── acceptance box 3: his own calibration rides along ─────────────────────────────────


def test_the_athletes_own_calibration_is_carried_into_the_cue():
    """ "L9-10 i think is easy - probably for my weight and heavy legs" is the single most
    useful line in the cycling history for setting a level. It must be in front of the
    next decision, not in a note nobody reads.

    Mutation control: stop appending the calibration clause — this reds.
    """
    _, cardio = _indexes()
    cue = cp.cardio_cue(CYCLING_TID, cardio, _whoop_index())
    assert "his calibration: L9-10 is easy" in cue, cue


# ── acceptance box 2: the cue reaches a real generated routine ────────────────────────


def test_the_cue_lands_on_the_cycling_block_of_the_live_stored_routine():
    """The 2026-09-19 push routine as it is stored in DynamoDB today, cycling block and
    all. Its note was hand-written by a coaching session; the deterministic baseline now
    rides in front of it.

    Mutation control: drop the `tmpl:` / catalog template resolution in
    `attach_cardio_cues` — nothing is stamped and this reds.
    """
    _, cardio = _indexes()

    class Blk:
        def __init__(self, d):
            self.movement_key = d.get("movement_key")
            self.notes = d.get("notes") or ""

    class Spec:
        pass

    spec = Spec()
    spec.exercises = [Blk(e) for e in _live_routine()["exercises"]]
    stamped = rg.attach_cardio_cues(spec, cardio_index=cardio, whoop_index=_whoop_index())
    assert stamped == 1
    cycling = [b for b in spec.exercises if b.movement_key == "cycling"][0]
    assert cycling.notes.startswith("Last: level 15,")
    assert "Level 10 flat, 40 min, hold 115-120 bpm" in cycling.notes  # the coach's own note survives
    # and a re-draft never stacks a second cue
    assert rg.attach_cardio_cues(spec, cardio_index=cardio, whoop_index=_whoop_index()) == 0


def test_a_duration_only_block_renders_no_cue_at_all():
    """`Stretching` is duration-bearing on exactly the same wire as a ride. "Last: 15:00 —
    19 Sep" is true, useless, and indistinguishable at a glance from a cue that carries
    something.

    Mutation control: remove the level/distance/note content check in `render_cardio_cue`
    — the stretching block gets a cue and this reds.
    """
    _, cardio = _indexes()
    assert cardio[STRETCH_TID], "the fixture must contain the stretching blocks"
    assert cp.cardio_cue(STRETCH_TID, cardio, _whoop_index()) == ""


def test_a_failed_index_load_leaves_every_note_untouched():
    """Fail-soft: a cue that cannot be built must never empty or mangle a note that a
    coaching session wrote.

    Mutation control: drop the try/except around the loaders in `attach_cardio_cues` —
    the exception escapes and this reds.
    """

    class Blk:
        def __init__(self, d):
            self.movement_key = d.get("movement_key")
            self.notes = d.get("notes") or ""

    class Spec:
        pass

    spec = Spec()
    spec.exercises = [Blk(e) for e in _live_routine()["exercises"]]
    before = [b.notes for b in spec.exercises]
    with patch.object(eh, "load_history_indexes", side_effect=RuntimeError("ddb down")):
        assert rg.attach_cardio_cues(spec) == 0
    assert [b.notes for b in spec.exercises] == before


# ── the generator path ────────────────────────────────────────────────────────────────


def test_history_facts_falls_through_to_the_cardio_arm_only_when_there_is_no_weighted_history():
    """Strength wins when both exist; nothing about the weighted path changed.

    Mutation control: check the cardio index FIRST in `history_facts` — a weighted
    template would start rendering a cardio cue and this reds.
    """
    weighted, cardio = _indexes()
    strength_tid = next(iter(weighted))
    assert eh.history_facts(strength_tid, weighted, cardio_index=cardio).get("modality") != "cardio"
    assert eh.history_facts(CYCLING_TID, weighted, cardio_index=cardio)["modality"] == "cardio"
    assert eh.history_facts(CYCLING_TID, weighted)["sessions_count"] == 0  # unchanged without the cardio index


def test_load_recent_history_still_returns_the_weighted_index_alone():
    """Every existing caller and test names `load_recent_history`. Its contract is a dict.

    Mutation control: return the tuple from `load_recent_history` — this reds, and so does
    the whole of tests/test_exercise_history.py.
    """
    table = MagicMock()
    table.query.return_value = {"Items": _live_hevy()}
    with patch.object(eh, "_table", return_value=table):
        idx = eh.load_recent_history(lookback_days=365, today=__import__("datetime").date(2026, 9, 19))
    assert isinstance(idx, dict)
    assert CYCLING_TID not in idx


@pytest.mark.parametrize(
    "notes,expected",
    [
        ("Level 10 flat", 10),
        ("Low effort level 10 for whole thing", 10),
        ("Level 8 but after a while i stopped for a water break", 8),
        ("Level 15 flat", 15),
        ("", None),
        ("3 incline, 2.8 speed - used rails", None),
    ],
)
def test_structured_level_over_the_live_note_vocabulary(notes, expected):
    """Every distinct live cardio note form, so a regex tweak cannot pass on one shape.

    Mutation control: any change to LEVEL_RE or the span guards reds a row here.
    """
    assert cp.structured_level(notes)["level"] == expected
