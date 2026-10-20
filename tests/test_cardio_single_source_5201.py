"""tests/test_cardio_single_source_5201.py — the engine draft's cardio block agrees with itself (#5201).

The 2026-10-20 nightly draft read: `cardio_pick` said treadmill / talk-test while the block was a recumbent-bike tempo at
"short phrases"; the block ran 40 min against the charter's 30-min cardio cap; `session_shape.cardio_blocks` was empty;
the note's audit verdict read `no_level` although a level was given. The ONE source is `training.cardio_menu`
(`prescription` / `block_minutes` / `align_pick`); these tests pin the four acceptance cases and the class (every menu
entry: the pick's modality + cue equal the block's).

No clock is read: every date is passed in.
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

from training import cardio_menu, cardio_note, recent_aerobic  # noqa: E402
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402
from training.training_charter import charter_value  # noqa: E402

from mcp import draft_standing_constraint as dcg  # noqa: E402

DAY = "2026-10-21"
PAIRS = [(k, m) for k in cardio_menu.KINDS for m in cardio_menu.block(k).get("machines", [])]


def _tempo_on_bike(monkeypatch):
    monkeypatch.setattr(recent_aerobic, "legs_loaded", lambda block: (False, "fresh"))
    monkeypatch.setattr(
        cardio_menu,
        "choose_kind",
        lambda **kw: {"kind": "tempo", "machine": cardio_menu.RECUMBENT, "why": "conditioning 1 of 2", "needed": []},
    )
    return dcg.cardio_block(DAY, "upper", None, layer={"state": "read"}, cardio_index={})


def test_every_menu_entry_has_one_prescription_the_pick_and_the_note_share():
    """The class: for every (kind, machine) on the menu, a stage-1 pick of the OTHER modality, once aligned, names the
    block's modality and cue, and the composed note's line 1 names the same machine and the same RPE words."""
    assert PAIRS
    for kind, machine in PAIRS:
        rx = cardio_menu.prescription(kind, machine)
        stale = {
            "movement_key": "treadmill" if machine != "treadmill" else "cycling",
            "modality": "x",
            "intensity": "talk-test",
            "reason": "r",
        }
        pick = cardio_menu.align_pick(stale, kind, machine)
        assert (pick["movement_key"], pick["modality"], pick["intensity"]) == (machine, rx["modality"], rx["intensity"]), (kind, machine)
        assert pick["stage1_pick"]["movement_key"] == stale["movement_key"]
        note, audit = cardio_note.compose(movement_key=machine, minutes=rx["minutes"], target_date=DAY, kind=kind)
        line1 = note.split("\n")[0]
        assert line1.startswith(cardio_note.machine_for(machine)), (kind, machine, line1)
        assert rx["intensity"].split(",")[0] in line1, (kind, machine, line1)  # the RPE words
        assert audit["kind"] == kind and f"{rx['minutes']} min" in line1
    agreeing = {"movement_key": "cycling", "intensity": cardio_menu.effort_words("easy")}
    assert cardio_menu.align_pick(agreeing, "easy", "cycling") is agreeing


def test_the_block_duration_is_clamped_to_the_charter_cap(monkeypatch):
    cap = int(charter_value("split.session_minutes.cardio_block_max"))
    assert cardio_menu.own_minutes("tempo") > cap, "the fixture premise: the menu names a tempo longer than the cap"
    assert all(cardio_menu.block_minutes(k) <= cap for k in cardio_menu.KINDS)
    block, pick = _tempo_on_bike(monkeypatch)
    assert [s.duration_seconds for s in block.sets] == [cap * 60]
    assert f"{cap} min" in block.notes.split("\n")[0] and "hard flat 40" not in block.notes  # the label would claim 40
    assert pick["menu"]["minutes"] == cap


def test_the_pick_names_the_blocks_modality_and_cue(monkeypatch):
    block, pick = _tempo_on_bike(monkeypatch)
    assert pick["movement_key"] == block.movement_key == "cycling"
    assert pick["modality"] == "cycling (recumbent)" and pick["intensity"] == cardio_menu.effort_words("tempo")
    assert "short phrases" in block.notes and "treadmill" not in pick["modality"]


def test_session_shape_lists_the_appended_cardio_block(monkeypatch):
    block, _ = _tempo_on_bike(monkeypatch)
    lift = ExerciseBlock(movement_key="barbell_bench_press", sets=[Set(rep_range_start=5, rep_range_end=8)] * 3, rest_seconds=120)
    ir = RoutineSpec(routine_id="f-5201", target_date=DAY, archetype="upper", variant="ideal", exercises=[lift])
    ir.inputs_snapshot = {"session_shape": {"cardio_blocks": [], "lifting_cap_minutes": 75}}
    ir.exercises.append(block)
    dcg._refresh_session_shape(ir)
    shape = ir.inputs_snapshot["session_shape"]
    assert [c["movement_key"] for c in shape["cardio_blocks"]] == ["cycling"]
    assert shape["cardio_blocks"][0]["minutes"] <= shape["cardio_block_max_minutes"]
    assert shape["lifting_cap_minutes"] == 75  # the generator's keys survive the merge


def test_the_verdict_reads_the_given_level_not_no_level():
    facts = {"last_level": None, "calibration": [{"anchors": [{"verdict": "easy", "level_high": 10}]}]}
    verdict = {"verdict": "no_level", "claims_improvement": False}
    _, audit = cardio_note.compose(movement_key="cycling", minutes=30, target_date=DAY, kind="easy", facts=facts, verdict=verdict)
    assert audit["level"] == 10 and audit["verdict"] == "calibration_level"
    # a genuinely level-less block still says so
    _, bare = cardio_note.compose(movement_key="cycling", minutes=30, target_date=DAY, kind="easy", facts={}, verdict=verdict)
    assert bare["level"] is None and bare["verdict"] == "no_level"


def test_other_verdicts_pass_through_unchanged():
    for word in ("insufficient_n", "hold", "raise"):
        _, audit = cardio_note.compose(
            movement_key="cycling", minutes=30, target_date=DAY, kind="easy", facts={"last_level": 9}, verdict={"verdict": word}
        )
        assert audit["verdict"] == word
