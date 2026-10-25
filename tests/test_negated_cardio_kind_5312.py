"""#5312 — a cardio note that rules a kind OUT never prescribes it; unnegated notes read as before."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from training import cardio_menu, cardio_note  # noqa: E402

# the live a035 note (draft_custom, 2026-10-25), tail elided as in the issue
A035 = "Recumbent, 30 min steady, talk test (full sentences). No intervals: keep it conversational the whole way."


@pytest.mark.parametrize(
    "note",
    [
        A035,
        "30 min easy. Not intervals today.",
        "Easy spin, without intervals.",
        "Steady 30. Skip the intervals.",
        "Steady 30, skip intervals",
        "Easy bike, no hills, no tempo",
        "Steady, not tempo",
    ],
)
def test_a_negated_kind_never_names_that_kind(note):
    assert cardio_note.shape_of(note) == "flat"
    assert cardio_menu.authored_kind("cycling", note) == "easy"
    assert cardio_menu.kind_of_performed("cycling", note) == "easy"


def test_the_real_a035_note_reads_easy_like_its_plain_text():
    assert cardio_menu.authored_kind("cycling", A035) == cardio_menu.authored_kind("cycling", "Recumbent, 30 min steady, talk test")


@pytest.mark.parametrize(
    "note,kind",
    [
        ("Intervals 5x2 at level 10", "intervals"),
        ("30 min steady then intervals", "intervals"),
        ("Hill repeats", "hills"),
        ("Tempo ride, hard", "tempo"),
        ("No problem, do intervals 4x3", "intervals"),
        ("Steady 30", "easy"),
    ],
)
def test_unnegated_notes_are_unchanged(note, kind):
    assert cardio_menu.kind_of_performed("cycling", note) == kind


def test_a_negation_of_one_kind_leaves_another_named_kind():
    assert cardio_menu.authored_kind("cycling", "No intervals, tempo instead") == "tempo"


def test_draft_custom_states_every_replaced_authored_note_in_warnings_and_never_prescribes_intervals():
    from test_cardio_cue_chat_path_3700 import _draft_custom

    out, ir = _draft_custom([{"movement_key": "cycling", "notes": A035, "sets": [{"duration_seconds": 1800}]}])
    bike = ir.exercises[0]
    assert "intervals" not in bike.notes.lower()
    assert ir.inputs_snapshot["cardio_notes_replaced"][0]["old_kind"] == "easy"
    msgs = [w for w in out["warnings"] if "Replaced your authored" in w]
    assert len(msgs) == 1 and "read as easy" in msgs[0] and "wrote easy" in msgs[0]
