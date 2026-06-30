"""tests/test_reading_keys.py — bookId determinism + key/GSI discipline."""

from __future__ import annotations

import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

from reading import reading_keys as rk  # noqa: E402


def test_book_id_is_stable_and_isbn_normalized():
    a = rk.book_id(isbn13="978-0-553-41802-6")
    b = rk.book_id(isbn13="9780553418026")  # same ISBN, different punctuation
    assert a == b
    assert len(a) == 16 and a.isalnum()


def test_book_id_priority_isbn_over_title():
    # ISBN wins over title/author when present
    isbn_id = rk.book_id(isbn13="9780553418026", title="Wrong", author="Nobody")
    assert isbn_id == rk.book_id(isbn13="9780553418026")
    # falls back to slug(title+author) when no isbn/olid
    slug_id = rk.book_id(title="Project Hail Mary", author="Andy Weir")
    assert slug_id == rk.book_id(title="project hail mary", author="ANDY WEIR")
    assert isbn_id != slug_id


def test_olid_used_when_no_isbn():
    assert rk.book_id(olid="OL123M") == rk.book_id(olid="ol123m")


def test_key_constructors():
    assert rk.book_key("abc") == {"pk": "BOOK#abc", "sk": "META"}
    assert rk.reading_state_key("abc") == {"pk": "READING#abc", "sk": "STATE"}
    assert rk.session_key("abc", "2026-06-29T20:00:00")["sk"] == "SESSION#2026-06-29T20:00:00"
    assert rk.note_key("abc", "n1")["sk"] == "NOTE#n1"
    assert rk.recall_key("abc", "p1")["sk"] == "RECALL#p1"
    assert rk.rec_key("2026-06-29T20:00:00") == {"pk": "READING#REC", "sk": "REC#2026-06-29T20:00:00"}
    assert rk.profile_key() == {"pk": "READING#PROFILE", "sk": "CURRENT"}
    assert rk.idea_key("i1") == {"pk": "READING#IDEA#i1", "sk": "META"}
    assert rk.edge_key("i1", "i2")["sk"] == "EDGE#i2"


def test_state_gsi_stamp():
    item = {}
    rk.stamp_state_gsi(item, "reading", "2026-06-29T20:00:00")
    assert item["GSI2PK"] == "READING_STATUS#reading"
    assert item["GSI2SK"] == "2026-06-29T20:00:00"


def test_session_gsi_stamp():
    item = {}
    rk.stamp_session_gsi(item, "2026-06-29")
    assert item["GSI2PK"] == "READING_SESSION"
    assert item["GSI2SK"] == "2026-06-29"


def test_recall_due_gsi_is_sparse():
    # with a due date → projects into GSI1
    due = {}
    rk.stamp_recall_due_gsi(due, "2026-07-15T00:00:00")
    assert due["GSI1PK"] == "RECALL_DUE" and due["GSI1SK"] == "2026-07-15T00:00:00"
    # answered/retired (None) → attributes REMOVED so it drops out of the sparse index
    due_then_cleared = {"GSI1PK": "RECALL_DUE", "GSI1SK": "x"}
    rk.stamp_recall_due_gsi(due_then_cleared, None)
    assert "GSI1PK" not in due_then_cleared and "GSI1SK" not in due_then_cleared
