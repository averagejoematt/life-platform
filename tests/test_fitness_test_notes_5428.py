"""tests/test_fitness_test_notes_5428.py — a fitness-test block keeps its protocol note and lints by its own grammar (#5428).

Found 2026-11-08 replaying the 11-01 and 11-07 nightly predrafts (the test-day role, `Foundation - Upper - 17 - 48`):

  * the linter read the dead-hang and pull-up test blocks as LIFTS — L3 "not the effort grammar" and L6 "0 RPE
    expressions" on §3.8's sanctioned `Test · ‹protocol›` line (6 problems a night, state `problems`);
  * `fitness_tests.test_note` put the charter's whole protocol on one line — 166 chars for the pull-up (L7 > 120);
  * `cardio_cues.attach_cardio_cues` composed a menu dose over the six-minute walk test block, so the wire said
    `Treadmill · today 2.8 mph, 8% · RPE 4–5` where the charter's protocol says 0 % incline, the fastest steady walk.

Each class has a test here, and each fix a negative control that shows the check can fail.
"""

from __future__ import annotations

import json
import pathlib
import sys
from types import SimpleNamespace

_REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))

from training import (  # noqa: E402
    cardio_cues,
    fitness_tests,
    hevy_note_grammar as g,  # noqa: E402
    hevy_note_lint as lint,  # noqa: E402
)
from training.routine_ir import ExerciseBlock, Set  # noqa: E402

_SPEC = fitness_tests.tests_spec(fitness_tests.protocol())


def _ex(name: str, note: str, kind: str = "other") -> lint.LintExercise:
    return lint.LintExercise(name=name, kind=kind, rows=[("N", None, None)], note=note)


def _test_problems(notes: list[tuple[str, str, str]]) -> list[str]:
    """Lint test blocks as they sit AFTER a lift-day exercise 1 (the test-day role's shape), and keep only their rows."""
    ex1 = lint.LintExercise(name="Bench", kind="barbell", rows=[("N", 100.0, "8")], note="")
    res = lint.lint_routine(lint.LintRoutine(exercises=[ex1, *[_ex(n, t, k) for n, t, k in notes]]))
    return [ln for ln in res.lines() if "[1]" not in ln and "routine" not in ln]


# ── the composer: one protocol sentence per line, every line inside the phone budget ─────────────────────────────
def test_every_charter_test_note_is_its_protocol_one_sentence_per_line_within_budget():
    assert _SPEC, "the charter carries no fitness tests — the sweep went blind"
    for tid, row in _SPEC.items():
        note = fitness_tests.test_note(row)
        lines = note.split("\n")
        assert g.is_test_note(note) and lines[0] == g.fitness_test_line(str(row["label"])), tid
        assert " ".join(lines[1:]) == str(row["protocol"]).strip(), f"{tid}: the charter's words changed"
        assert max(len(ln) for ln in lines) <= g.LINE_MAX_CHARS, tid
        assert g.phone_lines(note) <= g.TEST_MAX_LINES, f"{tid}: {g.phone_lines(note)} phone lines"


def test_every_charter_test_note_lints_clean_as_a_test_block():
    notes = [
        (str(r["label"]), fitness_tests.test_note(r), "cardio" if "walk" in tid or "bike" in tid else "other") for tid, r in _SPEC.items()
    ]
    assert _test_problems(notes) == []


# ── the linter: §3.8's grammar, never the lift's — and it can still fail ─────────────────────────────────────────
def test_the_11_07_single_line_pull_up_note_is_still_an_L7():
    old = "Test · assisted pull-up assistance\n" + str(_SPEC["assisted_pull_up"]["protocol"]).strip()
    probs = _test_problems([("Pull Up (Assisted)", old, "other")])
    assert any(p.startswith("L7") and "chars > 120" in p for p in probs), probs
    assert not any(p.startswith(("L3", "L6")) for p in probs), probs  # the false L3/L6 pair is gone


def test_a_test_note_over_its_phone_budget_is_an_L7():
    long = "Test · dead hang\n" + "\n".join(["Hold on."] * g.TEST_MAX_LINES)
    probs = _test_problems([("Dead Hang", long, "other")])
    assert any(p.startswith("L7") and "test note" in p for p in probs), probs


def test_a_lift_note_that_only_mentions_a_test_is_still_a_lift():
    probs = _test_problems([("Pull Up (Assisted)", "Test day: go light", "other")])
    assert any(p.startswith("L3") for p in probs), probs


# ── the cardio composer leaves a test block's protocol alone ─────────────────────────────────────────────────────
def _treadmill(tag: str, notes: str) -> ExerciseBlock:
    return ExerciseBlock(movement_key="treadmill", sets=[Set(duration_seconds=360)], notes=notes, rationale_tag=tag)


def test_the_cardio_composer_skips_a_fitness_test_block_and_still_composes_a_menu_block():
    catalog = json.loads((_REPO / "config" / "movement_catalog.json").read_text())
    walk = fitness_tests.test_note(_SPEC["six_minute_walk"])
    test_block = _treadmill(f"{fitness_tests.FITNESS_TEST_TAG_PREFIX}six_minute_walk", walk)
    menu_block = _treadmill("cardio:treadmill", "")
    spec = SimpleNamespace(exercises=[test_block, menu_block], target_date="2026-11-07", archetype="upper", inputs_snapshot={})
    n = cardio_cues.attach_cardio_cues(spec, catalog=catalog, cardio_index={}, whoop_index={})
    assert test_block.notes == walk, "the six-minute walk test lost its protocol note"
    assert n == 1 and menu_block.notes and not g.is_test_note(menu_block.notes)  # control: the composer still runs


# ── #6020: a custom draft over a test day, and the battery draft's rationale ───────────────────────────────────
# Seen live 2026-11-15: `draft_custom` tags every block `custom`, so the two passes that skip a test block by its
# `fitness_test:` tag (the cardio composer, the lift-note composer) rewrote the protocol notes; and the battery draft's
# rationale still described the full session it replaced.


def _catalog() -> dict:
    return json.loads((_REPO / "config" / "movement_catalog.json").read_text())


def test_a_custom_draft_keeps_the_timed_test_note_on_a_custom_tagged_block():
    walk = fitness_tests.test_note(_SPEC["six_minute_walk"])
    block = _treadmill("custom", walk)
    spec = SimpleNamespace(exercises=[block], target_date="2026-11-07", archetype="upper", inputs_snapshot={})
    cardio_cues.attach_cardio_cues(spec, catalog=_catalog(), cardio_index={}, whoop_index={})
    assert block.notes == walk, "draft_custom wiped the six-minute walk protocol"


def test_a_custom_draft_keeps_every_test_note_through_the_lift_note_composer():
    from mcp import draft_custom_session

    blocks = []
    for tid in ("dead_hang", "assisted_pull_up"):
        row = _SPEC[tid]
        sets = [Set(rep_range_start=int(row["reps"]), rep_range_end=int(row["reps"]))] if row.get("reps") else [Set()]
        blocks.append(
            ExerciseBlock(movement_key=str(row["catalog_key"]), sets=sets, notes=fitness_tests.test_note(row), rationale_tag="custom")
        )
    want = [b.notes for b in blocks]
    ir = SimpleNamespace(exercises=blocks, target_date="2026-11-07", inputs_snapshot={})
    draft_custom_session.compose_custom_notes(ir, _catalog(), {}, [])
    assert [b.notes for b in blocks] == want, "draft_custom rewrote a fitness-test protocol note to the lift standard"


def test_a_lift_note_that_only_mentions_a_test_is_still_composed_on_the_custom_path():
    # negative control: the guard is the `Test ·` line 1, not the movement — an authored lift note is still the composer's
    from mcp import draft_custom_session

    key = str(_SPEC["assisted_pull_up"]["catalog_key"])
    block = ExerciseBlock(
        movement_key=key, sets=[Set(rep_range_start=8, rep_range_end=8)], notes="Test day: go light", rationale_tag="custom"
    )
    ir = SimpleNamespace(exercises=[block], target_date="2026-11-07", inputs_snapshot={})
    draft_custom_session.compose_custom_notes(ir, _catalog(), {}, [])
    assert block.notes != "Test day: go light"


def test_the_battery_draft_rationale_describes_the_session_served_not_the_one_it_replaced():
    anchor = ExerciseBlock(
        movement_key="db_shoulder_press",
        sets=[Set(rep_range_start=8, rep_range_end=10) for _ in range(3)],
        notes="RPE 7",
        rationale_tag="anchor:overhead_press:moderate",
    )
    accessory = ExerciseBlock(
        movement_key="db_curl", sets=[Set(rep_range_start=10, rep_range_end=12)] * 3, notes="", rationale_tag="accessory:curl"
    )
    replaced = [
        "week grid source=module (synthetic)",
        "archetype=upper; session_role=shoulders_arms",
        "rotated: Bicep Curl (Dumbbell) -> Seated Incline Curl (Dumbbell)",
        "today: new to you, RPE 7 once: Seated Incline Curl (Dumbbell)",
        "swapped: Seated Shoulder Press (Machine) -> Shoulder Press (Dumbbell)",
        "14 sets over 6 movements (~49 min) + 0 warm-up set(s)",
    ]
    ideal = SimpleNamespace(
        exercises=[anchor, accessory],
        title="SHOULDERS+ARMS",
        notes="",
        caps={},
        budget_used={},
        inputs_snapshot={},
        rationale=list(replaced),
        target_date="2026-11-07",
    )
    due = {"state": fitness_tests.DUE, "due_on": "2026-11-07", "due_program_week": 6}
    fitness_tests.apply_battery(ideal, _catalog()["movements"], due)
    text = "\n".join(ideal.rationale)
    served = [b.movement_key for b in ideal.exercises]
    assert "db_curl" not in served
    for stale in ("14 sets over 6 movements", "Seated Incline Curl", "Seated Shoulder Press"):
        assert stale not in text, f"the rationale still describes the replaced session: {stale!r}"
    n_sets = sum(1 for b in ideal.exercises for _ in b.sets)
    assert f"{n_sets} sets over {len(served)} movements" in text  # what is served
    assert "week grid source=module" in text  # the session-independent header is kept
    kept = ideal.inputs_snapshot["fitness_battery"]["replaced_rationale"]
    assert "14 sets over 6 movements (~49 min) + 0 warm-up set(s)" in kept  # nothing is lost, only moved off the live line
