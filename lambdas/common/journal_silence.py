"""The journal's silence is never reader copy (#4583, #4580).

ONE pattern, read by two gates: the Story Desk (``content/story_desk.py``: journal presence is NOT a story, and
the story-auditor's privacy class "journal content or journal-silence probing" is BLOCKING) and the daily
coach-moves gate (``coach/coach_moves_sheet.py``). Live 2026-10-18 the front page served a coach line reading
"... yet 39 days of journal silence. My read is the block was never nutritional ..." because only the desk applied it.
"""

from __future__ import annotations

import json
import re
from typing import Any

_GAP = (
    r"(?:silen(?:t|ce)|quiet|blank|empty|dark|absen(?:t|ce)|gaps?|missing|missed|unwritten|unused|untouched|dry|dormant|"
    r"no\s+entr(?:y|ies)|not\s+(?:been\s+)?(?:written|used|opened|kept|filled)|stopped|lapsed?)"
)
_J = r"(?:journal\w*|diar(?:y|ies))"
_WORDS = r"(?:\W+\w+){0,6}?\W+"

JOURNAL_SILENCE = re.compile(
    rf"\b{_J}{_WORDS}{_GAP}\b|\b{_GAP}{_WORDS}{_J}\b"
    rf"|\bno\s+{_J}|\bblank\s+page\b"
    r"|\b(?:hasn['’]?t|has\s+not|haven['’]?t|have\s+not|hadn['’]?t|didn['’]?t|did\s+not)\s+(?:written|journal(?:ed|led)|logged\s+a\s+journal)\b"
    r"|\bnot\s+(?:written|journal(?:ed|led))\s+(?:in|a\s+word)\b",
    re.IGNORECASE,
)


def mentions_journal_silence(text: Any) -> bool:
    return bool(JOURNAL_SILENCE.search(str(text or "")))


# ══════════════════════════════════════════════════════════════════════════════
# #5131 — the PUBLIC-SURFACE guard. The pattern above was applied by two producers (the desk, the daily
# coach gate), so a line stored before the daily gate learned it kept being served: the 2026-10-18 line was
# still on /api/edition and /api/coaching-dashboard on 2026-10-23, and an open action on the dashboard carried
# the same class from a producer no gate read. A producer-side refusal cannot reach a row it never wrote.
# These functions are the SURFACE side: every reader-facing writer — the public API Lambdas' handlers, the
# generated/ text writers, the reader-mail senders, the coaches' public slots — passes its outgoing text
# through one of them, and `tests/test_journal_silence_public_surfaces_5131.py` derives that writer set from
# code and fails on a member that is neither guarded nor exempt with a reason.
#
# Degradation, chosen per shape (an empty slot is the honest-empty state the front-ends already render):
#   * a LIST element whose subtree carries the pattern is DROPPED — a card, a coach line, an open action;
#     cutting one sentence out of an attributed quote would misquote the coach.
#   * any other string (a standalone answer, a paragraph, a document) loses only the SENTENCE carrying it.
#   * dict KEYS are never rewritten; only values are reader copy.
# Clean text is returned unchanged, so wiring a writer through these is a no-op on every clean artifact.
# ══════════════════════════════════════════════════════════════════════════════

# A sentence ends at terminal punctuation followed by whitespace, or at a markup/line boundary, so a document
# scrub never cuts across an HTML tag. A decimal point ("25.1") is not a boundary.
_LEFT_BOUNDARY = re.compile(r"[.!?][\"'”’)\]]*\s+|[<>\n]")
_RIGHT_BOUNDARY = re.compile(r"[.!?][\"'”’)\]]*(?=\s|$|<)|(?=[<>\n])")
_MAX_PASSES = 200
WITHHELD_HEADER = "x-journal-silence-withheld"


def scrub_document(text: Any) -> str:
    """`text` with every sentence that mentions the journal's silence removed (clean text: unchanged)."""
    s = "" if text is None else str(text)
    for _ in range(_MAX_PASSES):
        m = JOURNAL_SILENCE.search(s)
        if not m:
            break
        start = 0
        for b in _LEFT_BOUNDARY.finditer(s, 0, m.start()):
            start = b.end()
        right = _RIGHT_BOUNDARY.search(s, m.end())
        end = right.end() if right else len(s)
        s = s[:start] + s[end:].lstrip(" \t")
    else:  # pragma: no cover — a pathological document: withhold all of it rather than serve a residue
        return ""
    return s if s.strip() else ""


def _scrub(node: Any) -> tuple[Any, int]:
    """(scrubbed node, withheld-span count). A list drops every element whose subtree hit."""
    if isinstance(node, str):
        if not JOURNAL_SILENCE.search(node):
            return node, 0
        return scrub_document(node), 1
    if isinstance(node, dict):
        out, hits = {}, 0
        for k, v in node.items():
            out[k], h = _scrub(v)
            hits += h
        return out, hits
    if isinstance(node, (list, tuple)):
        kept, hits = [], 0
        for v in node:
            nv, h = _scrub(v)
            if h:
                hits += h
            else:
                kept.append(nv)
        return kept, hits
    return node, 0


def scrub_payload(payload: Any) -> tuple[Any, int]:
    """A JSON-shaped public payload with journal-silence copy withheld, and the number of spans withheld."""
    return _scrub(payload)


def _scrub_text_body(text: str, content_type: str = "") -> tuple[str, int]:
    """A serialised body: JSON (by content type, or a body that parses as an object/array) structurally,
    anything else by sentence."""
    if not JOURNAL_SILENCE.search(text):
        return text, 0
    if "json" in (content_type or "").lower() or text.lstrip()[:1] in ("{", "["):
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if isinstance(parsed, (dict, list)):
            scrubbed, hits = _scrub(parsed)
            return json.dumps(scrubbed, ensure_ascii=False, default=str), hits
    return scrub_document(text), 1


def public_body(body: Any, content_type: str = "") -> Any:
    """The S3 `Body` of a generated/ artifact, guarded. Bytes stay bytes; a body that is not UTF-8 text (an
    image, audio) and a clean body are returned untouched."""
    if isinstance(body, (bytes, bytearray)):
        try:
            text = bytes(body).decode("utf-8")
        except UnicodeDecodeError:
            return body
        out, hits = _scrub_text_body(text, content_type)
        return out.encode("utf-8") if hits else body
    if isinstance(body, str):
        out, hits = _scrub_text_body(body, content_type)
        return out if hits else body
    return body


def guard_api_response(response: Any, logger: Any = None) -> Any:
    """The public API Lambdas' last step before the wire. A base64 body (an image) and a non-dict result pass
    through untouched. Header `x-journal-silence-withheld` carries the withheld count, so a scrub on the wire
    is visible rather than silent."""
    if not isinstance(response, dict) or response.get("isBase64Encoded"):
        return response
    body = response.get("body")
    if not isinstance(body, str):
        return response
    headers = dict(response.get("headers") or {})
    new_body, hits = _scrub_text_body(body, str(headers.get("Content-Type") or headers.get("content-type") or ""))
    if not hits:
        return response
    headers[WITHHELD_HEADER] = str(hits)
    if logger is not None:
        logger.warning("journal-silence copy withheld from a public response: %d span(s) (#5131)", hits)
    return {**response, "headers": headers, "body": new_body}


def reader_mail(text: Any) -> str:
    """READER mail (subscribers, the friends-and-family list, the partner): a subject or body with every
    journal-silence sentence removed. The owner's own mail is not a reader surface and does not call this."""
    return scrub_document(text)
