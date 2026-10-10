"""tests/test_plan_morning_note_4189.py — the morning note reaches the readiness/constraint block (#4189 box 2).

THE GAP (live proof comment, 2026-10-10)
  `/api/morning_note` and the coach packet's `morning_note` field were live; `plan_next_session`
  stage 1 — the readiness/constraint block the planning chat drafts against — did not read the
  note at all (`git grep morning_note mcp/plan_*.py` returned nothing).

WHAT IS PINNED
  * THE PAIR CONTRACT: for the same stored row, `constraint_block.morning_note` equals the coach
    packet's `fields.morning_note.value` (+ its state) — one derivation, `coach.morning_note.coach_fact`.
  * three read states: measured / absent / read_failed, and a malformed row is read_failed, never absent;
  * the coach lookback (today or the morning before) — an older note is absence, never carried forward;
  * `felt_vs_recovery_tier` compares only an unambiguous tier (GREEN/RED), never YELLOW or unknown.

THE FIXTURE IS THE WIRE
  The row is the write door's own shape (`tests/test_coach_session_packet_4082.py::MORNING_NOTE_ROW`
  — the e2e write-path test holds that shape to the handler), read through the REAL
  `coach.morning_note.read_notes` query against `_FakeTable` (the #4072 fake, which evaluates the
  key condition the reader actually sends).
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from test_plan_input_read_state_4072 import TODAY, _FakeTable, _stage1, _whoop_rows, _wire  # noqa: E402

import mcp.config as mcp_config  # noqa: E402
import mcp.plan_helpers as pmn  # noqa: E402
import mcp.tools_coach_packet as pkt  # noqa: E402
import mcp.tools_plan as tp  # noqa: E402

NOTE_PK = "USER#matthew#SOURCE#morning_note"


def _note(day: str, **over) -> dict:
    row = {
        "pk": NOTE_PK,
        "sk": f"MORNING_NOTE#{day}",
        "date": day,
        "sleep_word": "heavy",
        "body_word": "stiff",
        "mood_word": "steady",
        "felt_recovered": False,
        "written_at": f"{day}T12:34:56+00:00",
        "tier": 1,
        "source": "site_api_morning_note",
    }
    row.update(over)
    return {k: v for k, v in row.items() if v is not None}


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(tp, "pacific_today", lambda: TODAY)


def _wire_both(monkeypatch, rows, raise_on_pk=None) -> _FakeTable:
    """One fake table under BOTH readers — the plan's (`mcp.core.table`) and the packet's (`mcp.config.table`)."""
    fake = _wire(monkeypatch, rows, raise_on_pk=raise_on_pk)
    monkeypatch.setattr(mcp_config, "table", fake)
    return fake


def _block(**overrides) -> dict:
    return _stage1(**overrides)["constraint_block"]


# ── 1. the pair contract: the block reads what the packet reads ────────────────────────────
def test_the_constraint_block_carries_the_same_note_the_coach_packet_serves(monkeypatch):
    """Mutation (run 2026-10-10): delete the `attach_morning_note(...)` line in
    `tool_plan_next_session` -> KeyError 'morning_note' here. Reshaping the words (e.g. a
    lower()/paraphrase) or a second query of the partition reds the equality."""
    _wire_both(monkeypatch, _whoop_rows() + [_note(TODAY)])
    block = _block()
    note = block["morning_note"]
    assert note["state"] == "measured"
    assert (note["sleep_word"], note["body_word"], note["mood_word"], note["felt_recovered"]) == ("heavy", "stiff", "steady", False)
    assert note["date"] == TODAY and note["day"] and note["written_at_pt"]
    assert block["inputs"]["morning_note"]["state"] == "measured"

    value, status = pkt._morning_note(TODAY)
    assert status["state"] == "measured"
    from_block = {k: v for k, v in note.items() if k not in ("state", "felt_vs_recovery_tier")}
    assert from_block == value, "plan_next_session and the coach packet must serve ONE derivation of the note"


def test_yesterdays_note_is_read_and_an_older_one_is_absence(monkeypatch):
    _wire_both(monkeypatch, _whoop_rows() + [_note("2026-09-21")])
    assert _block()["morning_note"]["date"] == "2026-09-21"

    _wire_both(monkeypatch, _whoop_rows() + [_note("2026-09-20")])
    block = _block()
    assert block["morning_note"]["state"] == "absent", "a note older than the coach lookback is never carried forward"
    assert "sleep_word" not in block["morning_note"]
    assert block["inputs"]["morning_note"]["state"] == "absent"


# ── 2. three read states ──────────────────────────────────────────────────────────────────
def test_no_note_is_absent_and_says_so(monkeypatch):
    _wire_both(monkeypatch, _whoop_rows())
    block = _block()
    assert block["morning_note"]["state"] == "absent"
    assert "felt_vs_recovery_tier" not in block["morning_note"]
    assert block["inputs"]["morning_note"]["state"] == "absent"


def test_a_failed_read_is_read_failed_never_absent(monkeypatch):
    _wire_both(monkeypatch, _whoop_rows(), raise_on_pk="morning_note")
    block = _block()
    assert block["morning_note"]["state"] == "read_failed"
    assert block["inputs"]["morning_note"]["state"] == "read_failed"
    assert block["inputs"]["morning_note"]["error"].startswith("ReadError")


def test_a_half_note_is_read_failed_with_its_error_class_never_a_blank_word(monkeypatch):
    _wire_both(monkeypatch, _whoop_rows() + [_note(TODAY, body_word=None)])
    block = _block()
    assert block["morning_note"]["state"] == "read_failed"
    assert block["inputs"]["morning_note"]["error"].startswith("ValueError")
    assert "sleep_word" not in block["morning_note"]


# ── 3. felt vs the recovery tier ─────────────────────────────────────────────────────────
def test_felt_vs_recovery_tier_compares_only_an_unambiguous_tier():
    cases = [
        (False, "green", False),
        (True, "green", True),
        (False, "red", True),
        (True, "red", False),
        (True, "yellow", None),
        (True, None, None),
    ]
    wrong = []
    for felt, tier, agrees in cases:
        out = pmn.felt_vs_recovery_tier({"state": "measured", "felt_recovered": felt}, tier)
        if out != {"felt_recovered": felt, "recovery_tier": tier, "agrees": agrees}:
            wrong.append((felt, tier, out))
    assert not wrong, wrong


def test_the_block_names_a_disagreement_with_a_green_tier(monkeypatch):
    """The #4072 fixture's readiness_score is 76.5 (GREEN); he wrote felt_recovered=False."""
    _wire_both(monkeypatch, _whoop_rows() + [_note(TODAY)])
    cmp = _block()["morning_note"]["felt_vs_recovery_tier"]
    assert cmp == {"felt_recovered": False, "recovery_tier": "green", "agrees": False}


def test_a_presence_only_note_carries_no_words_and_no_comparison():
    fact = {"state": "measured", "words": "withheld (presence-only tier)"}
    assert pmn.felt_vs_recovery_tier(fact, "green") is None


@pytest.fixture(autouse=True)
def _output_schema_conformance_4286(monkeypatch):
    """#4286: every stage-1 result here is validated against plan_next_session's declared outputSchema."""
    from test_mcp_registry import check_output_schema

    check_output_schema(monkeypatch, tp, "plan_next_session")
