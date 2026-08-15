"""#2665 — get_reading_shelf returned identifiers, not books.

Measured against the deployed `life-platform-mcp` Lambda on 2026-08-15, BEFORE the fix:

    get_reading_shelf {}
      -> {"reading": [{"GSI2PK": "READING_STATUS#reading",
                       "GSI2SK": "2026-06-30T03:53:44.212490+00:00",
                       "status": "reading",
                       "bookId": "e2dab9d2d2ed4236",
                       "statusChangedAt": "2026-06-30T03:53:44.212490+00:00"}],
          "queue": [ …five more of the same… ]}

Six rows, no title, no author. `current_and_queue` returns READING_STATE items, and a
reading-state item carries the book's ID and its own index keys — the book's facts live on
a separate BOOK# record. So the caller could not name a single book on the shelf without a
second lookup per row, from the one tool you call PRECISELY BECAUSE you do not know what
is on the shelf.

THE JOIN ALREADY EXISTED ON THE OTHER SURFACE. `site_api_reading._public_shelf_item` has
always joined `get_book(bookId)` onto the state, so averagejoematt.com renders titles
today. The operator tool was the surface that skipped it: a reader on the public site
could read Matthew's shelf and Matthew, through his own tools, could not.

The MCP surface is PRIVATE, so it returns the full book record rather than the public
allowlist projection — and the raw GSI key attributes are dropped, because they are the
index's own copy of the keys, not data anyone should reason about. `statusChangedAt` is
the same instant as GSI2SK and is the one that means something, so it stays.

ADR-104: a state row whose BOOK# record is missing reports `book_record_missing: true`
rather than rendering `title: null` and leaving the caller to guess whether the book has
no title or the join broke. Those are different facts and the response distinguishes them.
"""

from __future__ import annotations

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

import pytest  # noqa: E402

from mcp import tools_reading as tr  # noqa: E402

# The exact row shape the live GSI2 query returns — index keys and an id, nothing else.
STATES = {
    "reading": [
        {
            "GSI2PK": "READING_STATUS#reading",
            "GSI2SK": "2026-06-30T03:53:44.212490+00:00",
            "status": "reading",
            "bookId": "e2dab9d2d2ed4236",
            "statusChangedAt": "2026-06-30T03:53:44.212490+00:00",
        }
    ],
    "want": [
        {"GSI2PK": "READING_STATUS#want", "GSI2SK": "2026-06-30T03:57:34.304780+00:00", "status": "want", "bookId": "456f82574520bb77"},
        # the orphan: a state row whose BOOK# record is not there
        {"GSI2PK": "READING_STATUS#want", "GSI2SK": "2026-06-30T03:57:32.526312+00:00", "status": "want", "bookId": "missing-book"},
    ],
    "abandoned": [
        {"GSI2PK": "READING_STATUS#abandoned", "GSI2SK": "2026-05-01T00:00:00+00:00", "status": "abandoned", "bookId": "bd1540f875fbe0af"}
    ],
    "finished": [
        {"GSI2PK": "READING_STATUS#finished", "GSI2SK": "2026-04-01T00:00:00+00:00", "status": "finished", "bookId": "0161d408f99efdfd"}
    ],
}

BOOKS = {
    "e2dab9d2d2ed4236": {"bookId": "e2dab9d2d2ed4236", "title": "The Beginning of Infinity", "author": "David Deutsch", "pageCount": 487},
    "456f82574520bb77": {"bookId": "456f82574520bb77", "title": "Seeing Like a State", "author": "James C. Scott"},
    "bd1540f875fbe0af": {"bookId": "bd1540f875fbe0af", "title": "Gödel, Escher, Bach", "author": "Douglas Hofstadter"},
    "0161d408f99efdfd": {"bookId": "0161d408f99efdfd", "title": "Thinking in Systems", "author": "Donella Meadows"},
}


@pytest.fixture(autouse=True)
def _store(monkeypatch):
    monkeypatch.setattr(
        tr.reading_store, "current_and_queue", lambda statuses=("reading", "want"): {s: list(STATES.get(s, [])) for s in statuses}
    )
    monkeypatch.setattr(tr.reading_store, "finished", lambda *a, **k: list(STATES["finished"]))
    monkeypatch.setattr(tr.reading_store, "get_book", lambda book_id: BOOKS.get(book_id))


def _shelf():
    return tr.tool_get_reading_shelf({})


SHELVES = ("reading", "queue", "finished", "set_down")


# ── acceptance box 1 ─────────────────────────────────────────────────────────


def test_every_entry_on_every_shelf_has_a_title_and_an_author():
    out = _shelf()
    missing = []
    for shelf in SHELVES:
        for entry in out[shelf]:
            if entry.get("book_record_missing"):
                continue  # covered by its own test — an absent join is stated, not faked
            if not entry.get("title") or not entry.get("author"):
                missing.append(f"{shelf}: {entry}")
    assert not missing, "shelf entries with no human-readable name:\n  " + "\n  ".join(missing)


def test_the_fixture_covers_every_shelf():
    """Vacuity guard: an empty shelf passes the assertion above without proving anything."""
    out = _shelf()
    assert all(out[shelf] for shelf in SHELVES), {s: len(out[s]) for s in SHELVES}


def test_the_book_the_issue_named_is_nameable():
    entry = _shelf()["reading"][0]
    assert entry["title"] == "The Beginning of Infinity"
    assert entry["author"] == "David Deutsch"


# ── acceptance box 2 ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("shelf", SHELVES)
def test_raw_index_key_attributes_do_not_reach_the_caller(shelf):
    for entry in _shelf()[shelf]:
        leaked = [k for k in entry if k in tr._INDEX_KEY_ATTRS]
        assert not leaked, f"{shelf} entry carries index plumbing {leaked}: {entry}"


def test_the_meaningful_timestamp_survives_the_key_drop():
    """GSI2SK and statusChangedAt are the same instant; dropping both would lose the fact."""
    entry = _shelf()["reading"][0]
    assert entry["statusChangedAt"] == "2026-06-30T03:53:44.212490+00:00"
    assert entry["status"] == "reading"
    assert entry["bookId"] == "e2dab9d2d2ed4236"


def test_the_full_book_record_is_available_on_this_private_surface():
    """MCP is the operator view — it is not limited to the public allowlist projection."""
    assert _shelf()["reading"][0]["book"]["pageCount"] == 487


# ── ADR-104: a broken join is not an untitled book ───────────────────────────


def test_a_state_row_with_no_book_record_says_so_rather_than_rendering_a_blank():
    orphan = [e for e in _shelf()["queue"] if e["bookId"] == "missing-book"]
    assert len(orphan) == 1, "an orphan state row must still appear — dropping it hides the breakage"
    assert orphan[0]["book_record_missing"] is True
    assert orphan[0]["title"] is None and orphan[0]["book"] is None


def test_a_healthy_entry_does_not_carry_the_missing_flag():
    """The flag must mean something — set on every row, it would mean nothing."""
    assert all("book_record_missing" not in e for e in _shelf()["reading"])


# ── the counts + the control ─────────────────────────────────────────────────


def test_the_counts_match_the_rows_they_summarise():
    out = _shelf()
    assert out["counts"] == {shelf: len(out[shelf]) for shelf in SHELVES}


def test_the_shelf_still_reports_as_of():
    assert _shelf()["as_of"]


def test_one_book_lookup_per_shelf_row_and_no_more(monkeypatch):
    """The join is N+1 by construction; keep it honest about N rather than growing it."""
    calls = []
    monkeypatch.setattr(tr.reading_store, "get_book", lambda book_id: (calls.append(book_id), BOOKS.get(book_id))[1])
    out = _shelf()
    assert len(calls) == sum(len(out[shelf]) for shelf in SHELVES)
