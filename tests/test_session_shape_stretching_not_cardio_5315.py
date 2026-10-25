"""#5315: a Stretching block (a `tmpl:527DA061` Hevy template block) is never counted as a second cardio block."""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in (REPO / "lambdas", REPO):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from training import program_structure  # noqa: E402
from training.routine_ir import ExerciseBlock, Set  # noqa: E402

MOVEMENTS = json.loads((REPO / "config" / "movement_catalog.json").read_text())["movements"]


def _timed(key, minutes, tag=None):
    return ExerciseBlock(movement_key=key, sets=[Set(duration_seconds=int(minutes * 60))], rationale_tag=tag)


def _cardio_problems(blocks, movements):
    return [p for p in program_structure.session_shape_problems(blocks, movements) if "cardio blocks" in p]


def test_stretching_template_block_beside_one_cardio_block_passes_with_the_real_catalog():
    blocks = [_timed("cycling", 30), _timed("tmpl:527DA061", 10, "Stretching")]
    assert program_structure.session_shape_problems(blocks, MOVEMENTS) == []


def test_stretching_template_block_passes_on_its_tag_alone_with_an_empty_catalog():
    blocks = [_timed("cycling", 30), _timed("tmpl:527DA061", 10, "Stretching")]
    assert program_structure.session_shape_problems(blocks, {}) == []


def test_two_real_cardio_blocks_still_fail():
    assert _cardio_problems([_timed("cycling", 20), _timed("treadmill", 20)], MOVEMENTS)


def test_unknown_timed_template_is_reported_never_guessed_as_cardio():
    blocks = [_timed("cycling", 20), _timed("tmpl:DEADBEEF", 10)]
    problems = program_structure.session_shape_problems(blocks, MOVEMENTS)
    assert not _cardio_problems(blocks, MOVEMENTS)
    assert any("tmpl:DEADBEEF could not be classified" in p for p in problems)


def test_cooldown_title_is_mobility():
    assert program_structure.routine_minutes([_timed("cool_down", 5)], {})["cardio_blocks"] == []


def test_draft_warning_path_uses_the_real_catalog():
    from mcp import plan_cardio_pick

    blocks = [_timed("cycling", 30), _timed("tmpl:527DA061", 10)]
    out = plan_cardio_pick.draft_cardio_warnings(blocks, "lower", "2026-10-20")
    assert not [w for w in out if "cardio blocks" in w]
