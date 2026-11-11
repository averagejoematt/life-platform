"""tests/test_draft_custom_keeps_caller_cues_5782.py — draft_custom keeps the caller's effort cap and conditional cue.

Live, 2026-11-11, routine f4569682 (draft_custom): the chat wrote `RPE 7 · per hand. Last 30x8 was RPE 8.5: if set 1
stalls short of 8 at RPE 7, drop to 25.` on the seated incline curl, and `RPE 7 · per hand. …` / `RPE 7 · replaces …` on
two more accessories. The note composer (`lift_note.compose_blocks`, via `draft_custom_session.compose_custom_notes`)
kept an authored effort only when a sentence WAS `RPE 7`, and no cue carrying a number, so all three went to Hevy as the
slot default `RPE 8–9, last set RPE 9–10` and the conditional was lost.

Mutation controls (run on the lane, recorded on the PR): (M1) make `_authored_effort` return only exact effort lines (the
old rule) -> the payload tests red on line 1; (M2) drop `own.get("conditional")` from the composed body -> the
conditional tests red; (M3) make `keep_stricter` return the charter line always -> the stricter-caller tests red.
"""

from __future__ import annotations

import os

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import test_hevy_notes_followups_5428 as h  # noqa: E402 — the offline draft_custom harness (tests/ is on sys.path)
from training import hevy_note_lint, lift_note, session_block  # noqa: E402
from training.hevy_compiler import to_create_body  # noqa: E402
from training.routine_title import format_why_note  # noqa: E402

SLOT_DEFAULT = "RPE 8–9, last set RPE 9–10"
LIVE_CURL_NOTE = "RPE 7 · per hand. Last 30x8 was RPE 8.5: if set 1 stalls short of 8 at RPE 7, drop to 25."
CONDITIONAL = "If set 1 stalls short of 8 at RPE 7, drop to 25."


def _payload(curl_note: str, fly_note: str | None = None) -> list[dict]:
    """Exercise 1 (the session block's) plus the two accessories, as the chat drafted them."""
    return [
        {"movement_key": "lat_pulldown", "sets": [{"weight_lbs": 160, "rep_range_start": 8, "rep_range_end": 12, "count": 2}]},
        {
            "movement_key": "seated_incline_curl_dumbbell",
            "sets": [{"weight_lbs": 30, "rep_range_start": 8, "rep_range_end": 12, "count": 2}],
            "notes": curl_note,
        },
        {
            "movement_key": "triceps_rope_pushdown",
            "sets": [{"weight_lbs": 40, "rep_range_start": 8, "rep_range_end": 15, "count": 2}],
            **({"notes": fly_note} if fly_note is not None else {}),
        },
    ]


def _compiled(exercises):
    ir, out = h._draft_custom(exercises, target_date="2026-10-26", role="upper_volume")
    notes = {b.movement_key: b.notes.split("\n") for b in ir.exercises}
    why = session_block.why_note_for(ir, format_why_note(ir))
    body = to_create_body(ir, lambda k: "T-" + k, why_note=why)
    # the compiled body keeps the IR's exercise order: key each wire note by its block's movement
    wire = {b.movement_key: e.get("notes") or "" for b, e in zip(ir.exercises, body["routine"]["exercises"])}
    return ir, notes, wire, hevy_note_lint.lint_wire(body, ir)


def test_the_live_note_keeps_its_rpe_7_cap_and_its_conditional_on_the_compiled_note():
    _ir, notes, wire, lint = _compiled(_payload(LIVE_CURL_NOTE, "RPE 7 cap. Elbows pinned to your sides."))
    curl = notes["seated_incline_curl_dumbbell"]
    assert curl[0] == "RPE 7", curl  # was the slot default
    assert CONDITIONAL in curl, curl
    assert notes["triceps_rope_pushdown"][0] == "RPE 7" and "Elbows pinned to your sides." in notes["triceps_rope_pushdown"]
    # the compiled Hevy body carries both, and the linter (L1–L15) passes it
    curl_wire = wire["seated_incline_curl_dumbbell"]
    assert curl_wire.startswith("RPE 7\n") and CONDITIONAL in curl_wire, curl_wire
    assert lint.ok, lint.lines()


def test_the_orchestrator_payload_rpe_7_and_drop_to_25_if_short_of_8():
    _ir, notes, wire, lint = _compiled(_payload("RPE 7. Drop to 25 if short of 8."))
    curl = notes["seated_incline_curl_dumbbell"]
    assert curl[0] == "RPE 7" and "Drop to 25 if short of 8." in curl, curl
    assert "Drop to 25 if short of 8." in wire["seated_incline_curl_dumbbell"]
    assert lint.ok, lint.lines()


def test_the_slot_default_applies_only_when_the_caller_gave_no_effort():
    _ir, notes, _wire, lint = _compiled(_payload("Hands to the walls; don't turn it into a row."))
    curl = notes["seated_incline_curl_dumbbell"]
    assert curl[0] == SLOT_DEFAULT and "Hands to the walls; don't turn it into a row." in curl, curl
    assert notes["triceps_rope_pushdown"][0] == SLOT_DEFAULT  # no note at all: the slot default
    assert lint.ok, lint.lines()


def test_authored_lines_reads_each_dot_separated_part():
    assert lift_note.authored_lines("RPE 7 · per hand. Hands to the walls; don't turn it into a row.") == {
        "effort": "RPE 7",
        "line": "Hands to the walls; don't turn it into a row.",  # `per hand` is a unit qualifier, never the cue
    }
    assert lift_note.authored_lines(LIVE_CURL_NOTE) == {"effort": "RPE 7", "conditional": CONDITIONAL}
    for cap in ("RPE 7 cap", "cap at RPE 7", "RPE ≤7", "RPE 7 max", "RPE 6-7"):
        assert lift_note.authored_lines(cap + ".")["effort"] in ("RPE 7", "RPE 6–7"), cap


def test_an_effort_inside_a_restated_row_is_not_a_cap_and_a_row_never_rides_as_the_conditional():
    """Must-fail controls: the 10-25 chat note's `3 sets of 8-15 @ RPE 8-9` is a restated row, not a cap (the composer's
    line 1 stands, #5428), and a conditional that restates a row (`if 30x8 stalls`) or uses `@` stays off the wire."""
    assert "effort" not in lift_note.authored_lines("3 sets of 8-15 @ RPE 8-9; last set RPE 9-10.")
    assert "conditional" not in lift_note.authored_lines("If 30x8 stalls, drop a step.")
    assert "conditional" not in lift_note.authored_lines("If set 1 stalls @ 30, drop to 25.")
    assert "conditional" not in lift_note.authored_lines("If the critic flags it, drop to 25.")  # L1 banned word


def test_a_conditional_that_goes_up_never_reaches_the_wire():
    """Must-fail control: the subtract-only gate's own class (#3971, `recovery_authoring.find_conditional_up`) — `If set 1
    feels good, go up to 85.` is a load jump the session's load rule does not allow, so draft_custom keeps it off the
    wire (on the stored record as `detail`, as before) while a conditional that drops the load rides."""
    note = "RPE 7. If set 1 feels good, go up to 40."
    _ir, notes, wire, _lint = _compiled(_payload(note))
    curl = notes["seated_incline_curl_dumbbell"]
    assert curl[0] == "RPE 7" and not any("go up" in ln for ln in curl), curl
    assert "go up" not in wire["seated_incline_curl_dumbbell"]


def test_a_stricter_charter_cap_still_wins_and_never_raises_a_lower_caller_cap():
    assert lift_note.keep_stricter("RPE 6", "RPE 7") == "RPE 6"
    assert lift_note.keep_stricter("RPE 8", "RPE 7") == "RPE 7"
    assert lift_note.keep_stricter("RPE 7", "RPE 6–7") == "RPE 6–7"  # a tie keeps the charter's band (#5754 ruling)
    assert lift_note.keep_stricter(None, "RPE 7") == "RPE 7"
    # the critic's downstream cap (#5754 `add_capped_reason`): the slot band comes down to the cap, a lower caller cap stays
    clause = "Same load all sets: 2nd session back after 19 weeks off."
    assert session_block.add_capped_reason(SLOT_DEFAULT, clause, 7).split("\n")[0] == "RPE 7"
    assert session_block.add_capped_reason("RPE 6", clause, 7).split("\n")[0] == "RPE 6"
