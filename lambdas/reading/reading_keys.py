"""reading_keys.py — pure key / id / GSI discipline for the reading domain.

No boto3, no I/O — just deterministic construction of the pk/sk and GSI
attributes per `docs/SPEC_READING_MIND_2026-06-29.md` §1–§3. Kept pure so the
access-pattern tests can exercise it without AWS.

Entity → key map (single-table `life-platform`):
  BOOK#<bookId>      / META                  catalog (shared facts)
  READING#<bookId>   / STATE                 his relationship (state machine)
  READING#<bookId>   / SESSION#<iso-ts>      input event
  READING#<bookId>   / NOTE#<noteId>         highlight|reflection|synthesis
  READING#<bookId>   / RECALL#<promptId>     spaced retrieval (PRIVATE)
  READING#REC        / REC#<iso-ts>          recommendation audit / track record
  READING#PROFILE    / CURRENT               calibration state (one item)
  READING#IDEA#<id>  / META                  Constellation node (gated, Phase E)
  READING#IDEA#<id>  / EDGE#<otherId>        Constellation edge

GSIs (additive, sparse where noted — spec §3):
  GSI1 — recall due (SPARSE). Only RECALL# items with an active nextDue project:
         GSI1PK="RECALL_DUE", GSI1SK=<nextDue iso>.  Sweep: GSI1SK <= now.
  GSI2 — reading state/time. READING#/STATE -> GSI2PK="READING_STATUS#<status>",
         GSI2SK=<iso changedAt>.  SESSION# -> GSI2PK="READING_SESSION",
         GSI2SK=<iso date>.  Serves current-reading, queue, history-by-date.
"""

from __future__ import annotations

import hashlib
import re

# ── Partition / sort-key prefixes ─────────────────────────────────────────────
BOOK_PK = "BOOK#{book_id}"
READING_PK = "READING#{book_id}"
REC_PK = "READING#REC"
PROFILE_PK = "READING#PROFILE"
IDEA_PK = "READING#IDEA#{idea_id}"

SK_BOOK_META = "META"
SK_READING_STATE = "STATE"
SK_PROFILE = "CURRENT"
SK_IDEA_META = "META"

SK_SESSION_PREFIX = "SESSION#"
SK_NOTE_PREFIX = "NOTE#"
SK_RECALL_PREFIX = "RECALL#"
SK_REC_PREFIX = "REC#"
SK_EDGE_PREFIX = "EDGE#"

# ── GSI attribute / value constants ───────────────────────────────────────────
GSI1_PK_ATTR = "GSI1PK"
GSI1_SK_ATTR = "GSI1SK"
GSI2_PK_ATTR = "GSI2PK"
GSI2_SK_ATTR = "GSI2SK"

GSI1_NAME = "GSI1"
GSI2_NAME = "GSI2"

RECALL_DUE_VALUE = "RECALL_DUE"  # GSI1PK for active (un-answered) recall prompts
READING_SESSION_VALUE = "READING_SESSION"  # GSI2PK for input events
READING_STATUS_PREFIX = "READING_STATUS#"  # + <status> for state rows

VALID_STATUSES = ("want", "reading", "finished", "abandoned")
VALID_ABANDON_REASONS = ("wrong-time", "wrong-book", "stalled", "other")


# ── bookId — stable, deterministic ────────────────────────────────────────────
def _slug(text: str) -> str:
    """Lowercase, hyphenated, ascii-safe slug."""
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def canonical_source(isbn13: str | None = None, olid: str | None = None, title: str | None = None, author: str | None = None) -> str:
    """The canonical string a bookId is derived from (spec §1: ISBN-13 or OLID, else slug(title+author))."""
    if isbn13:
        digits = re.sub(r"[^0-9Xx]", "", isbn13)
        if digits:
            return f"isbn13:{digits}"
    if olid:
        return f"olid:{olid.strip().upper()}"
    return f"slug:{_slug(title or '')}|{_slug(author or '')}"


def book_id(isbn13: str | None = None, olid: str | None = None, title: str | None = None, author: str | None = None) -> str:
    """Stable 16-char hex id from the canonical source. Same book → same id, always."""
    src = canonical_source(isbn13, olid, title, author)
    return hashlib.sha1(src.encode("utf-8")).hexdigest()[:16]  # noqa: S324 — id derivation, not security


# ── key constructors ──────────────────────────────────────────────────────────
def book_key(book_id_: str) -> dict:
    return {"pk": BOOK_PK.format(book_id=book_id_), "sk": SK_BOOK_META}


def reading_state_key(book_id_: str) -> dict:
    return {"pk": READING_PK.format(book_id=book_id_), "sk": SK_READING_STATE}


def session_key(book_id_: str, iso_ts: str) -> dict:
    return {"pk": READING_PK.format(book_id=book_id_), "sk": f"{SK_SESSION_PREFIX}{iso_ts}"}


def note_key(book_id_: str, note_id: str) -> dict:
    return {"pk": READING_PK.format(book_id=book_id_), "sk": f"{SK_NOTE_PREFIX}{note_id}"}


def recall_key(book_id_: str, prompt_id: str) -> dict:
    return {"pk": READING_PK.format(book_id=book_id_), "sk": f"{SK_RECALL_PREFIX}{prompt_id}"}


def rec_key(iso_ts: str) -> dict:
    return {"pk": REC_PK, "sk": f"{SK_REC_PREFIX}{iso_ts}"}


def profile_key() -> dict:
    return {"pk": PROFILE_PK, "sk": SK_PROFILE}


def idea_key(idea_id: str) -> dict:
    return {"pk": IDEA_PK.format(idea_id=idea_id), "sk": SK_IDEA_META}


def edge_key(idea_id: str, other_idea_id: str) -> dict:
    return {"pk": IDEA_PK.format(idea_id=idea_id), "sk": f"{SK_EDGE_PREFIX}{other_idea_id}"}


# ── GSI stamping (mutates + returns the item dict) ────────────────────────────
def stamp_state_gsi(item: dict, status: str, changed_at: str) -> dict:
    """GSI2 for a READING#/STATE row → queryable by status + time."""
    item[GSI2_PK_ATTR] = f"{READING_STATUS_PREFIX}{status}"
    item[GSI2_SK_ATTR] = changed_at
    return item


def stamp_session_gsi(item: dict, date: str) -> dict:
    """GSI2 for a SESSION# row → history-by-date without a scan."""
    item[GSI2_PK_ATTR] = READING_SESSION_VALUE
    item[GSI2_SK_ATTR] = date
    return item


def stamp_recall_due_gsi(item: dict, next_due: str | None) -> dict:
    """GSI1 (SPARSE) for a RECALL# row. With next_due → projects into the due
    index; with next_due None (answered/retired) → attributes removed so the row
    DROPS OUT of the sparse index entirely."""
    if next_due:
        item[GSI1_PK_ATTR] = RECALL_DUE_VALUE
        item[GSI1_SK_ATTR] = next_due
    else:
        item.pop(GSI1_PK_ATTR, None)
        item.pop(GSI1_SK_ATTR, None)
    return item
