"""tests/test_cardio_cue_chat_path_3700.py — the chat path gets the cue, and the n-floor
is seen refusing on a real ride (#3700 residual).

WHAT WAS LEFT OPEN

PR #3975 shipped the cardio arm of the ADR-068 history cue: the structured level, the
speed-at-level / HR-at-level trend, and `routine_generator.attach_cardio_cues`, which
`generate_routines` calls at the end of its build. Two residuals stayed with the issue:

  1. `draft_custom` — the chat authoring path (ADR-069) — never reached
     `attach_cardio_cues`. It builds its blocks straight from the caller's argument list
     and never touches `_build_exercise_note`, so a chat-authored treadmill or cycling
     block went to Hevy with NO baseline in front of it while a generated block carrying
     the same template id got one. Matthew's real cardio blocks arrive through exactly
     this path (the deterministic selector budgets by landmark muscle and never picks a
     bike), so in practice the cue reached the routines that needed it least.

  2. The n-floor had never been seen refusing on a planted real-ride shape. The live
     corpus refuses because his busiest level has n=5 against a required 8 — true, but
     it cannot distinguish "the floor is holding" from "the data happens to be flat".
     The tests below plant an IMPROVING series below the floor, so the refusal has
     something to refuse, and then drop the floor by monkeypatch to show the same data
     does claim a raise once the floor is gone. That mutation is executed here, not
     described in a docstring.

THE FIXTURE IS THE WIRE

Every cardio history in this file comes from `tests/fixtures/cardio_progression_3700/`
— field-projected LIVE DynamoDB records — and is driven through the REAL
`exercise_history.load_history_indexes`, never a hand-shaped index. Planted rides
(the n-floor tests) reuse the live 2026-09-07 record's exact shape: `exercises[].notes`
plural on the exercise, a set row with `reps: None`, `weight_kg: None`, `distance_m`
and `duration_sec`. Both real cardio shapes are graded: cycling, whose notes carry a
level, and TREADMILL, whose eight live notes carry speed/incline and no level at all —
a cue that only worked for the bike would red on the treadmill assertions.
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import (  # noqa: E402
    cardio_progression as cp,
    exercise_history as eh,
)

from mcp import tools_hevy_routine as t  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "cardio_progression_3700"
CYCLING_TID = "D8F7F851"  # config/movement_catalog.json -> movements.cycling
TREADMILL_TID = "243710DE"  # -> movements.treadmill
TODAY = datetime.date(2026, 9, 19)

# Nothing that claims progress may render below the floor. `n=` catches the basis string,
# `improv` the verdict prose, `hold level` / `raise level` the suggestion clause itself.
CLAIM_WORDS = ("improv", "hold level", "raise level", "insufficient", "n=", "faster")


def _live_hevy() -> list[dict[str, Any]]:
    return json.loads((FIXTURES / "hevy_cardio_2026-05-31_09-19.json").read_text())


def _live_whoop() -> list[dict[str, Any]]:
    return json.loads((FIXTURES / "whoop_workouts_2026-05-31_09-19.json").read_text())


def _indexes(items: list[dict[str, Any]] | None = None):
    """The REAL loader over live (or planted-live-shaped) records."""
    table = MagicMock()
    table.query.return_value = {"Items": _live_hevy() if items is None else items}
    with patch.object(eh, "_table", return_value=table):
        return eh.load_history_indexes(lookback_days=365, today=TODAY)


def _whoop_index(items: list[dict[str, Any]] | None = None) -> dict[str, list[dict[str, Any]]]:
    table = MagicMock()
    table.query.return_value = {"Items": _live_whoop() if items is None else items}
    with patch.object(eh, "_table", return_value=table):
        return eh.load_whoop_workout_index(lookback_days=365, today=TODAY)


def _ride(date: str, notes: str, duration_sec: float, distance_m: float, tid: str = CYCLING_TID, name: str = "Cycling") -> dict[str, Any]:
    """One Hevy workout record carrying one cardio block, in the LIVE 2026-09-07 shape.

    `reps` and `weight_kg` are None on the set exactly as the wire has them — that pair is
    what made `load_recent_history` drop a ride before the renderer ever saw it, so a
    planted row that quietly carried reps would test nothing.
    """
    return {
        "pk": "USER#matthew#SOURCE#hevy",
        "sk": f"DATE#{date}#WORKOUT#planted-{date}",
        "source": "hevy",
        "date": date,
        "title": "Foundation - Push - 1 - 1",
        "source_workout_id": f"planted-{date}",
        "start_time": f"{date}T17:59:49+00:00",
        "end_time": f"{date}T20:00:38+00:00",
        "duration_sec": 7249.0,
        "exercises": [
            {
                "name": name,
                "template_id": tid,
                "notes": notes,
                "sets": [
                    {
                        "set_index": 0.0,
                        "type": "normal",
                        "reps": None,
                        "weight_kg": None,
                        "distance_m": distance_m,
                        "duration_sec": duration_sec,
                    }
                ],
            }
        ],
    }


def _ride_at(date: str, level: int, mph: float, duration_sec: float = 1800.0) -> dict[str, Any]:
    """A ride at a stated level and speed — distance derived so the loader computes `mph`."""
    return _ride(date, f"Level {level} steady", duration_sec, round(mph * cp.METERS_PER_MILE * (duration_sec / 3600.0), 1))


def _draft_custom(exercises: list[dict[str, Any]], **extra: Any):
    """Run the real `draft_custom` action offline; return (response, persisted IR).

    Only three things are stubbed: the draft write (`draft_versioned`) and the two index
    loaders `attach_cardio_cues` reaches for. Movement resolution, block building and the
    cue pass itself are the production code paths.
    """
    captured: dict[str, Any] = {}
    hist, cardio = extra.pop("indexes", None) or _indexes()
    whoop = extra.pop("whoop", None)
    whoop = _whoop_index() if whoop is None else whoop
    args = {"action": "draft_custom", "target_date": "2026-09-20", "archetype": "push", "exercises": exercises}
    args.update(extra)
    with (
        patch("training.routine_repo.draft_versioned", side_effect=lambda ir: captured.setdefault("ir", ir)),
        patch.object(eh, "load_history_indexes", return_value=(hist, cardio)),
        patch.object(eh, "load_whoop_workout_index", return_value=whoop),
    ):
        out = t.tool_manage_hevy_routine(args)
    return out, captured.get("ir")


# ── residual 1: the chat path reaches the cue ─────────────────────────────────────────


def test_a_chat_drafted_cycling_block_carries_the_SAME_cue_the_cron_path_stamps():
    """The whole residual, stated as one equality: the note a chat-authored cycling block
    gets must be byte-identical to what `cardio_cue` renders for the cron path. Two paths
    that "both have a cue" but disagree on its content is the next defect, not the fix.

    Mutation control: delete the `attach_cardio_cues(ir)` call in `_action_draft_custom` —
    the block's note is '' and this reds on the first assertion.
    """
    _, cardio = _indexes()
    whoop = _whoop_index()
    out, ir = _draft_custom(
        [
            {"movement_key": "barbell_bench_press", "sets": [{"weight_lbs": 155, "reps": 8}]},
            {"movement_key": "cycling", "sets": [{"duration_seconds": 2700}]},
        ]
    )
    assert out["status"] == "drafted_custom"
    bike = next(b for b in ir.exercises if b.movement_key == "cycling")
    assert bike.notes == cp.cardio_cue(CYCLING_TID, cardio, whoop)
    assert bike.notes.startswith("Last: level 15, 10.70 mi in 45:00 (14.3 mph)")
    # the strength block is untouched — the cardio arm never reaches a barbell
    assert next(b for b in ir.exercises if b.movement_key == "barbell_bench_press").notes == ""
    assert out["cardio_cues"] == 1


def test_a_chat_drafted_treadmill_block_gets_its_OWN_shape_not_the_bikes():
    """The treadmill is the second real cardio shape and it is deliberately awkward: his
    eight live treadmill notes read "0.5 incline 3mph" / "2.8 and 6 incline for minutes
    4-20" — speed and incline, never a level. The cue must render the measured distance,
    duration and pace and quote his words, while claiming NO level.

    Mutation control: make the cue require a parsed level before rendering (an easy
    "simplification" of `render_cardio_cue`) — the treadmill gets nothing and this reds.
    """
    out, ir = _draft_custom([{"movement_key": "treadmill", "sets": [{"duration_seconds": 3600}]}])
    tread = next(b for b in ir.exercises if b.movement_key == "treadmill")
    assert tread.notes.startswith("Last: 2.99 mi in 1:00:00 (3.0 mph)")
    assert '["0.5 incline 3mph"]' in tread.notes  # his own words, verbatim
    assert "level" not in tread.notes.lower()  # no level exists in his treadmill notes; none may be implied
    assert out["cardio_cues"] == 1


def test_the_authors_own_note_survives_in_front_of_the_cue():
    """A chat-authored block often carries the coach's instruction for the day. The
    baseline rides IN FRONT of it; it never replaces it.

    Mutation control: assign `ex.notes = cue` unconditionally in `attach_cardio_cues` —
    the authored instruction is destroyed and this reds.
    """
    _, ir = _draft_custom(
        [{"movement_key": "cycling", "notes": "Level 10 flat, 40 min, hold 115-120 bpm", "sets": [{"duration_seconds": 2400}]}]
    )
    bike = ir.exercises[0]
    assert bike.notes.startswith("Last: level 15,")
    assert bike.notes.endswith("— Level 10 flat, 40 min, hold 115-120 bpm")


def test_the_cue_is_on_the_PERSISTED_draft_because_that_is_what_commit_pushes():
    """`dry_run` and `commit` read the stored IR, not this response. A cue that existed
    only in the draft_custom reply would never reach Hevy.

    Mutation control: move the `attach_cardio_cues` call to AFTER `draft_versioned(ir)` —
    the persisted object no longer carries the cue and this reds.
    """
    persisted: dict[str, Any] = {}
    _, cardio = _indexes()

    def _capture(ir):
        # snapshot at write time, not after the call returns
        persisted["notes"] = [b.notes for b in ir.exercises]
        return ir

    with (
        patch("training.routine_repo.draft_versioned", side_effect=_capture),
        patch.object(eh, "load_history_indexes", return_value=({}, cardio)),
        patch.object(eh, "load_whoop_workout_index", return_value=_whoop_index()),
    ):
        t.tool_manage_hevy_routine(
            {
                "action": "draft_custom",
                "target_date": "2026-09-20",
                "archetype": "push",
                "exercises": [{"movement_key": "cycling", "sets": [{"duration_seconds": 2700}]}],
            }
        )
    assert persisted["notes"][0].startswith("Last: level 15,")


def test_a_strength_only_chat_draft_reports_zero_rather_than_omitting_the_count():
    """Absence is reported by name (ADR-104). `cardio_cues: 0` on a routine with no cardio
    block is the honest answer; a missing key would read as "not attempted" forever.

    Mutation control: only set `cardio_cues` in the response when it is non-zero — this
    reds on the key.
    """
    out, ir = _draft_custom([{"movement_key": "barbell_bench_press", "sets": [{"weight_lbs": 155, "reps": 8}]}])
    assert out["cardio_cues"] == 0
    assert all(b.notes == "" for b in ir.exercises)


def test_a_history_load_failure_never_costs_the_chat_draft():
    """Fail-soft: the cue is an enrichment. A DynamoDB blip must not turn an authored
    session into an error, nor empty a note the author wrote.

    Mutation control: remove the try/except around `attach_cardio_cues` in
    `_action_draft_custom` AND the one inside it — the draft raises and this reds.
    """
    captured: dict[str, Any] = {}
    with (
        patch("training.routine_repo.draft_versioned", side_effect=lambda ir: captured.setdefault("ir", ir)),
        patch.object(eh, "load_history_indexes", side_effect=RuntimeError("ddb down")),
    ):
        out = t.tool_manage_hevy_routine(
            {
                "action": "draft_custom",
                "target_date": "2026-09-20",
                "archetype": "push",
                "exercises": [{"movement_key": "cycling", "notes": "easy flush", "sets": [{"duration_seconds": 1200}]}],
            }
        )
    assert out["status"] == "drafted_custom"
    assert out["cardio_cues"] == 0
    assert captured["ir"].exercises[0].notes == "easy flush"


# ── residual 2: the n-floor, seen refusing on a planted real ride ─────────────────────


def test_a_single_real_ride_states_the_baseline_and_claims_nothing():
    """n=1, and it is THE live record the issue was filed against: `notes` "Level 9 - 5.6
    miles", `duration_sec` 1800, `distance_m` 9012. The cue must carry the fact and make
    no claim — "your cardio is improving" off one ride is an assertion, not a measurement
    (ADR-104/105).

    Mutation control: return the block comparison for `len(at) >= 2` instead of
    `>= N_REQUIRED_AT_LEVEL` — a verdict is emitted and the claim words appear.
    """
    _, cardio = _indexes([_ride("2026-09-07", "Level 9 - 5.6 miles", 1800.0, 9012.0)])
    facts = cp.cardio_facts(CYCLING_TID, cardio, _whoop_index())
    assert facts["sessions_count"] == 1
    verdict = cp.level_verdict(facts["series"], facts["last_level"])
    assert verdict["n_at_level"] == 1
    assert verdict["verdict"] == "insufficient_n"
    assert verdict["claims_improvement"] is False
    assert verdict["within_level_sd_mph"] is None  # one ride has no spread; none may be invented
    cue = cp.render_cardio_cue(facts, verdict)
    assert cue.startswith("Last: level 9, 5.60 mi in 30:00 (11.2 mph)")
    for banned in CLAIM_WORDS:
        assert banned not in cue.lower(), (banned, cue)


def _improving_below_the_floor() -> list[dict[str, Any]]:
    """Seven rides at level 9 — one short of the required eight — genuinely getting
    faster: ~10.0 mph for four, then ~13.0 for three. The point of an IMPROVING series is
    that the refusal has something to refuse; a flat series would pass a broken floor.
    """
    speeds = [10.0, 10.1, 9.9, 10.0, 13.0, 13.1, 12.9]
    return [_ride_at(f"2026-08-{1 + 2 * i:02d}", 9, mph) for i, mph in enumerate(speeds)]


def test_a_real_improving_series_below_the_floor_still_refuses_to_claim_improvement():
    """n=7 against `N_REQUIRED_AT_LEVEL`=8. The gain is large and real — and the rule still
    says nothing, because the floor is about n, not about the size of the delta.

    Mutation control: the test below drops the floor and shows THIS SAME DATA claiming a
    raise, so the refusal here is demonstrably the floor's doing and not flat data.
    """
    _, cardio = _indexes(_improving_below_the_floor())
    facts = cp.cardio_facts(CYCLING_TID, cardio, _whoop_index())
    assert len(facts["series"]) == 7 < cp.N_REQUIRED_AT_LEVEL
    verdict = cp.level_verdict(facts["series"], 9)
    assert verdict["verdict"] == "insufficient_n"
    assert verdict["claims_improvement"] is False
    assert verdict["delta_mph"] is None  # not computed, so it cannot leak into a surface
    cue = cp.render_cardio_cue(facts, verdict)
    assert cue.startswith("Last: level 9,")
    for banned in CLAIM_WORDS:
        assert banned not in cue.lower(), (banned, cue)


def test_MUTATION_CONTROL_removing_the_n_floor_makes_the_same_rides_claim_a_raise(monkeypatch):
    """The executed mutation. Drop `N_REQUIRED_AT_LEVEL` to 6 and `BLOCK_K` to 3 — nothing
    else changes, same seven planted rides — and the rule now returns `raise`,
    `claims_improvement` True, and the cue grows a suggestion clause.

    That is what the floor is buying, measured rather than asserted: without it this
    platform would tell him his cardio is improving off seven rides whose within-level
    spread it has barely estimated.
    """
    _, cardio = _indexes(_improving_below_the_floor())
    facts = cp.cardio_facts(CYCLING_TID, cardio, _whoop_index())

    monkeypatch.setattr(cp, "BLOCK_K", 3)
    monkeypatch.setattr(cp, "N_REQUIRED_AT_LEVEL", 6)
    verdict = cp.level_verdict(facts["series"], 9)
    assert verdict["verdict"] == "raise"
    assert verdict["claims_improvement"] is True
    assert verdict["delta_mph"] >= verdict["effect_mph"]
    assert "raise level 9:" in cp.render_cardio_cue(facts, verdict)


def test_the_chat_path_inherits_the_refusal_rather_than_re_deciding_it():
    """The wiring must not smuggle a second opinion in. A chat draft standing on the n=1
    ride gets the baseline line and no claim — the same verdict the cron path reaches,
    because it is literally the same call.

    Mutation control: have `_action_draft_custom` render its own cue instead of calling
    `attach_cardio_cues` — the two paths can then disagree and this reds.
    """
    indexes = _indexes([_ride("2026-09-07", "Level 9 - 5.6 miles", 1800.0, 9012.0)])
    _, ir = _draft_custom([{"movement_key": "cycling", "sets": [{"duration_seconds": 1800}]}], indexes=indexes)
    note = ir.exercises[0].notes
    assert note.startswith("Last: level 9, 5.60 mi in 30:00 (11.2 mph)")
    for banned in CLAIM_WORDS:
        assert banned not in note.lower(), (banned, note)
