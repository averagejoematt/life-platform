"""tests/test_reading_store.py — every Phase A access pattern (spec §2).

Exercises the real query shapes against the FakeTable condition engine: GSI2
status/queue + history, sparse GSI1 due-recalls, begins_with notes/track-record,
the wheel join, and the write/state-machine helpers.
"""

from __future__ import annotations

import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

import pytest  # noqa: E402
from reading import reading_store as rs  # noqa: E402
from reading_fakes import FakeTable  # noqa: E402


@pytest.fixture(autouse=True)
def fake_table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(rs, "table", t)
    return t


def _no_enrich(_meta):
    return {}  # skip the LLM in store tests


# ── §2.1 current reading + queue (GSI2 by status) ─────────────────────────────
def test_current_and_queue_by_status():
    rs.add_book({"title": "Reading Now", "author": "A"}, initial_status="reading", enricher=_no_enrich, now="2026-06-20T00:00:00")
    rs.add_book({"title": "On Deck", "author": "B"}, initial_status="want", enricher=_no_enrich, now="2026-06-21T00:00:00")
    rs.add_book({"title": "Also Want", "author": "C"}, initial_status="want", enricher=_no_enrich, now="2026-06-22T00:00:00")
    out = rs.current_and_queue()
    assert {b["status"] for b in out["reading"]} == {"reading"}
    assert len(out["reading"]) == 1
    assert len(out["want"]) == 2


# ── §2.2 history over a date range (GSI2 sessions) ────────────────────────────
def test_history_by_date_range():
    bid = rs.add_book({"title": "T", "author": "A"}, enricher=_no_enrich)
    rs.log_session(bid, minutes=20, pages=15, date="2026-06-10", now="2026-06-10T20:00:00")
    rs.log_session(bid, minutes=30, pages=22, date="2026-06-15", now="2026-06-15T20:00:00")
    rs.log_session(bid, minutes=10, pages=8, date="2026-07-01", now="2026-07-01T20:00:00")
    window = rs.history("2026-06-01", "2026-06-30")
    dates = sorted(s["date"] for s in window)
    assert dates == ["2026-06-10", "2026-06-15"]  # July session excluded
    assert rs.history("2026-07-02", "2026-06-01") == []  # inverted window → empty


# ── §2.3 all notes for a book (begins_with NOTE#) ─────────────────────────────
def test_notes_for_book():
    bid = rs.add_book({"title": "T", "author": "A"}, enricher=_no_enrich)
    rs.add_note(bid, note_id="n1", type="highlight", text="one", public=True)
    rs.add_note(bid, note_id="n2", type="reflection", text="two", public=False)
    # a session on the same pk must NOT come back from a notes query
    rs.log_session(bid, minutes=5, date="2026-06-10")
    notes = rs.notes(bid)
    assert {n["noteId"] for n in notes} == {"n1", "n2"}


# ── §2.4 due recall prompts (SPARSE GSI1, due <= now) ─────────────────────────
def test_due_recalls_sparse_and_thresholded():
    bid = rs.add_book({"title": "T", "author": "A"}, enricher=_no_enrich)
    rs.put_recall(bid, prompt_id="p_due", prompt="due now", next_due="2026-06-01T00:00:00")
    rs.put_recall(bid, prompt_id="p_future", prompt="not yet", next_due="2026-12-01T00:00:00")
    rs.put_recall(bid, prompt_id="p_answered", prompt="answered", next_due=None)  # sparse: not in index
    due = rs.due_recalls(now="2026-06-15T00:00:00")
    ids = {r["promptId"] for r in due}
    assert ids == {"p_due"}  # future excluded; answered (no GSI1) never appears


def test_clearing_next_due_drops_from_index():
    bid = rs.add_book({"title": "T", "author": "A"}, enricher=_no_enrich)
    rs.put_recall(bid, prompt_id="p1", prompt="q", next_due="2026-06-01T00:00:00")
    assert {r["promptId"] for r in rs.due_recalls(now="2026-06-15T00:00:00")} == {"p1"}
    rs.put_recall(bid, prompt_id="p1", prompt="q", next_due=None)  # answered
    assert rs.due_recalls(now="2026-06-15T00:00:00") == []


# ── §2.5 roundedness wheel (finished + BOOK#.domainTags) ──────────────────────
def test_wheel_distribution_joins_domain_tags():
    b1 = rs.add_book({"title": "F1", "author": "A", "domainTags": ["fiction", "classics"]}, enricher=_no_enrich)
    b2 = rs.add_book({"title": "F2", "author": "B", "domainTags": ["fiction"]}, enricher=_no_enrich)
    b3 = rs.add_book({"title": "H1", "author": "C", "domainTags": ["history"]}, enricher=_no_enrich)
    rs.update_reading_status(b1, "finished")
    rs.update_reading_status(b2, "finished")
    # b3 left as 'want' → must NOT count toward the wheel
    _ = b3
    wheel = rs.wheel_distribution()
    assert wheel == {"fiction": 2, "classics": 1}


# ── §2.6 Lena's track record (begins_with REC#) ───────────────────────────────
def test_track_record():
    rs.put_recommendation({"bookId": "b1", "reasonString": "r", "confidence": "low"}, now="2026-06-10T00:00:00")
    rs.put_recommendation({"bookId": "b2", "reasonString": "r", "confidence": "med"}, now="2026-06-12T00:00:00")
    recs = rs.track_record()
    assert [r["bookId"] for r in recs] == ["b2", "b1"]  # newest first
    assert len(rs.track_record(limit=1)) == 1


# ── §2.7 Constellation node + edges (exact key; enum deferred to Phase E) ─────
def test_idea_and_edges():
    rs.put_idea({"ideaId": "i1", "label": "entropy", "sourceBookIds": ["b1"]})
    rs.put_edge("i1", "i2", weight=0.5, rationale="both about decay")
    rs.put_edge("i1", "i3", weight=0.2, rationale="loose")
    assert rs.idea("i1")["label"] == "entropy"
    edges = rs.idea_edges("i1")
    assert {e["otherIdeaId"] for e in edges} == {"i2", "i3"}


# ── write path / state machine ────────────────────────────────────────────────
def test_add_book_writes_book_and_state(fake_table):
    bid = rs.add_book({"title": "Klara and the Sun", "author": "Ishiguro", "isbn13": "9780571364886"}, enricher=_no_enrich)
    assert rs.get_book(bid)["title"] == "Klara and the Sun"
    assert rs.get_reading_state(bid)["status"] == "want"


def test_add_book_merges_enrichment():
    def enr(_meta):
        return {"domainTags": ["fiction"], "themes": ["memory"], "difficulty": {"composite": 2.0}}

    bid = rs.add_book({"title": "T", "author": "A"}, enricher=enr)
    book = rs.get_book(bid)
    assert book["domainTags"] == ["fiction"] and book["difficulty"]["composite"] == 2.0


def test_finish_and_abandon_transitions():
    bid = rs.add_book({"title": "T", "author": "A"}, enricher=_no_enrich)
    rs.update_reading_status(bid, "reading", now="2026-06-01T00:00:00")
    assert rs.get_reading_state(bid)["startedAt"] == "2026-06-01T00:00:00"
    rs.update_reading_status(bid, "finished", now="2026-06-10T00:00:00")
    st = rs.get_reading_state(bid)
    assert st["status"] == "finished" and st["finishedAt"] == "2026-06-10T00:00:00"


def test_abandon_requires_reason():
    bid = rs.add_book({"title": "T", "author": "A"}, enricher=_no_enrich)
    with pytest.raises(ValueError):
        rs.update_reading_status(bid, "abandoned")  # no reason
    rs.update_reading_status(bid, "abandoned", abandon_reason="wrong-time")
    st = rs.get_reading_state(bid)
    assert st["status"] == "abandoned" and st["abandonReason"] == "wrong-time"


def test_invalid_status_rejected():
    with pytest.raises(ValueError):
        rs.put_reading_state("b", "halfway")


def test_update_cover_key():
    bid = rs.add_book({"title": "T", "author": "A"}, enricher=_no_enrich)
    rs.update_cover_key(bid, "generated/covers/x.jpg", "openlibrary")
    book = rs.get_book(bid)
    assert book["coverS3Key"] == "generated/covers/x.jpg" and book["coverSource"] == "openlibrary"
