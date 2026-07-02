"""tests/test_reading_auto_reason.py — the auto-recommender-reason path.

Two behaviors shipped together (the reading tail):
  * get_reading_recommendation persists each surfaced pick as an OPEN
    RECOMMENDATION# (reason stored under the allowlisted name `reasonString`),
    deduped so a re-run doesn't spam Cora's track record — this is also what
    makes log_outcome resolvable (the track record was write-less before).
  * update_status → "reading" auto-writes the public "why this book" note
    (noteId=coach-why, type=intention) from the latest rec's reasonString;
    a hand-authored coach-why is never overwritten; no rec → no note.
"""

from __future__ import annotations

import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")  # mcp.config reads these at import
os.environ.setdefault("USER_ID", "matthew")

import pytest  # noqa: E402

from mcp import tools_reading as tr  # noqa: E402


@pytest.fixture()
def store(monkeypatch):
    """A tiny in-memory double for the reading_store calls these paths touch."""

    class S:
        def __init__(self):
            self.recs, self.book_notes, self.status_calls = [], {}, []

        def track_record(self, limit=None):
            return list(reversed(self.recs))[:limit] if limit else list(reversed(self.recs))

        def put_recommendation(self, rec, **_kw):
            self.recs.append(dict(rec))
            return rec

        def notes(self, book_id):
            return self.book_notes.get(book_id, [])

        def add_note(self, book_id, *, note_id, type, text, public=False, **_kw):
            n = {"bookId": book_id, "noteId": note_id, "type": type, "text": text, "public": public}
            self.book_notes.setdefault(book_id, []).append(n)
            return n

        def update_reading_status(self, book_id, status, **_kw):
            self.status_calls.append((book_id, status))
            return {"bookId": book_id, "status": status}

    s = S()
    for name in ("track_record", "put_recommendation", "notes", "add_note", "update_reading_status"):
        monkeypatch.setattr(tr.reading_store, name, getattr(s, name))
    return s


def test_recommendation_persists_open_rec_with_reason_string(store, monkeypatch):
    monkeypatch.setattr(tr, "_candidates_from_queue", lambda: [{"bookId": "b1"}])
    monkeypatch.setattr(tr, "_build_recommender_state", lambda: {})
    monkeypatch.setattr(
        tr.reading_recommender,
        "rank",
        lambda c, s, top_n: {
            "recommendations": [{"bookId": "b1", "title": "Dark Matter", "reason": "Recommended because it fits."}],
            "confidence": "low",
        },
    )
    tr.tool_get_reading_recommendation({})
    assert len(store.recs) == 1
    rec = store.recs[0]
    assert rec["bookId"] == "b1" and rec["status"] == "open"
    assert rec["reasonString"] == "Recommended because it fits."  # allowlisted name, not `reason`
    # re-run → deduped, no second open rec
    tr.tool_get_reading_recommendation({})
    assert len(store.recs) == 1


def test_status_reading_auto_writes_coach_why(store):
    store.recs.append({"bookId": "b1", "reasonString": "Recommended because it fits.", "status": "open"})
    tr._action_update_status({"bookId": "b1", "status": "reading"}, dry_run=False)
    ns = store.book_notes.get("b1", [])
    assert len(ns) == 1
    n = ns[0]
    assert n["noteId"] == "coach-why" and n["type"] == "intention" and n["public"] is True
    assert n["text"] == "Recommended because it fits."


def test_hand_authored_coach_why_never_overwritten(store):
    store.book_notes["b1"] = [{"noteId": "coach-why", "type": "intention", "text": "HAND WRITTEN", "public": True}]
    store.recs.append({"bookId": "b1", "reasonString": "auto reason", "status": "open"})
    tr._action_update_status({"bookId": "b1", "status": "reading"}, dry_run=False)
    assert [n["text"] for n in store.book_notes["b1"]] == ["HAND WRITTEN"]


def test_no_rec_no_note_and_other_statuses_untouched(store):
    tr._action_update_status({"bookId": "b1", "status": "reading"}, dry_run=False)
    assert store.book_notes.get("b1") is None  # never recommended → honest no-why
    store.recs.append({"bookId": "b2", "reasonString": "r", "status": "open"})
    tr._action_update_status({"bookId": "b2", "status": "finished"}, dry_run=False)
    assert store.book_notes.get("b2") is None  # only the reading transition writes it
