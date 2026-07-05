"""tests/test_field_note_interaction_writeback.py — #533 interaction memory,
piece 2: Matthew's field-note pushback flows into coach state.

A field note (field_notes_lambda) is the platform's single cross-domain voice —
it has no per-domain breakdown (ai_domains is aspirational, never populated),
so unlike the #531 board Q&A write-back (one coach per answer) this broadcasts
one INTERACTION# record to every operational coach's own partition. The weekly
summarizer (coach_history_summarizer) already folds any COACH#{id}/INTERACTION#
record into compression (#531) — this just adds a second write path into the
same mechanism, no new generation call.
"""

from __future__ import annotations

import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")  # mcp.config requires these at import
os.environ.setdefault("USER_ID", "matthew")

import pytest  # noqa: E402

from mcp import tools_lifestyle as tl  # noqa: E402

OPERATIONAL = [
    "sleep_coach",
    "training_coach",
    "nutrition_coach",
    "mind_coach",
    "physical_coach",
    "glucose_coach",
    "labs_coach",
    "explorer_coach",
]


class FakeTable:
    """Minimal in-memory DynamoDB stand-in: put_item / get_item / update_item."""

    def __init__(self):
        self.store: dict[tuple, dict] = {}

    def put_item(self, Item):
        self.store[(Item["pk"], Item["sk"])] = dict(Item)

    def get_item(self, Key):
        it = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": dict(it)} if it else {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues):
        it = self.store.setdefault((Key["pk"], Key["sk"]), {"pk": Key["pk"], "sk": Key["sk"]})
        # Parse "SET a = :a, b = :b" — good enough for this tool's fixed shape.
        assignments = UpdateExpression[len("SET ") :].split(", ")
        for a in assignments:
            field, placeholder = [s.strip() for s in a.split("=")]
            it[field] = ExpressionAttributeValues[placeholder]


@pytest.fixture(autouse=True)
def fake_table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(tl, "table", t)
    return t


def _seed_field_note(fake_table, week="2026-W20"):
    fake_table.put_item(
        Item={
            "pk": tl.FIELD_NOTES_PK,
            "sk": f"WEEK#{week}",
            "week": week,
            "week_label": "Week 3",
            "ai_present": "This week the data showed a dip in HRV alongside a busy travel stretch.",
            "ai_generated_at": "2026-05-18T18:00:00Z",
        }
    )


# ── the write-back helper ──────────────────────────────────────────────────


def test_write_field_note_interactions_broadcasts_to_every_operational_coach(fake_table):
    tl._write_field_note_interactions(
        "2026-W20", "Week 3", "disagree", "I don't think the HRV dip was travel — I was sick.", ["the travel framing"], "I was sick"
    )
    written = [k for k in fake_table.store if k[0].startswith("COACH#")]
    assert len(written) == len(OPERATIONAL)
    for coach_id in OPERATIONAL:
        item = fake_table.store[(f"COACH#{coach_id}", "INTERACTION#2026-05-11#fieldnote-2026-W20")]
        assert item["interaction_type"] == "field_note_pushback"
        assert item["channel"] == "field_notes"
        assert item["agreement"] == "disagree"
        assert "sick" in item["notes"]
        assert item["disputed"] == ["the travel framing"]


def test_field_note_interaction_sk_is_content_addressed_on_week(fake_table):
    """Re-logging a response for the SAME week overwrites rather than piling up —
    mirrors the #531 board-answer qhash overwrite semantics."""
    tl._write_field_note_interactions("2026-W20", "Week 3", "agree", "first pass", [], "")
    tl._write_field_note_interactions("2026-W20", "Week 3", "mixed", "revised take", [], "")
    written = [k for k in fake_table.store if k[0] == "COACH#sleep_coach"]
    assert len(written) == 1
    assert fake_table.store[written[0]]["notes"] == "revised take"


def test_write_field_note_interactions_is_fail_soft_per_coach(monkeypatch, fake_table):
    """One coach's write failing (e.g. a transient DDB error) must not stop the
    broadcast to the remaining coaches — mirrors #531's per-item fail-soft."""
    calls = {"n": 0}
    orig_put = fake_table.put_item

    def _flaky_put(Item):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("ddb down")
        return orig_put(Item)

    monkeypatch.setattr(fake_table, "put_item", _flaky_put)
    tl._write_field_note_interactions("2026-W21", "Week 4", "agree", "notes here", [], "")
    written = [k for k in fake_table.store if k[0].startswith("COACH#")]
    # One coach's write failed; the rest still landed (fail-soft PER coach).
    assert len(written) == len(OPERATIONAL) - 1


# ── the MCP tool end to end ─────────────────────────────────────────────────


def test_log_field_note_response_writes_coach_interactions(fake_table):
    _seed_field_note(fake_table, "2026-W20")
    out = tl.tool_log_field_note_response(
        {
            "week": "2026-W20",
            "notes": "I don't think the HRV dip was travel — I was sick.",
            "agreement": "disagree",
            "disputed": ["the travel framing"],
        }
    )
    assert out["status"] == "saved"
    # the field-note record itself still updated (pre-existing behavior)
    fn = fake_table.get_item(Key={"pk": tl.FIELD_NOTES_PK, "sk": "WEEK#2026-W20"})["Item"]
    assert fn["matthew_agreement"] == "disagree"
    # AND every coach now has the episodic record
    for coach_id in OPERATIONAL:
        key = (f"COACH#{coach_id}", "INTERACTION#2026-05-11#fieldnote-2026-W20")
        assert key in fake_table.store
        assert fake_table.store[key]["week"] == "2026-W20"


def test_log_field_note_response_still_succeeds_if_interaction_writeback_fails(monkeypatch, fake_table):
    """The primary response (the actual product feature) must never fail because
    the episodic memory write-back had a problem — even a totally unexpected one
    (not just the per-coach put_item failures _write_field_note_interactions
    already tolerates internally)."""
    _seed_field_note(fake_table, "2026-W20")
    monkeypatch.setattr(tl, "_write_field_note_interactions", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    out = tl.tool_log_field_note_response({"week": "2026-W20", "notes": "whatever", "agreement": "agree"})
    assert out["status"] == "saved"
    # the field-note record itself still updated despite the write-back blowing up
    fn = fake_table.get_item(Key={"pk": tl.FIELD_NOTES_PK, "sk": "WEEK#2026-W20"})["Item"]
    assert fn["matthew_agreement"] == "agree"
