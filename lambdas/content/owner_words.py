"""content/owner_words.py — his own words: ONE store, two inlets, one outlet (#4584, epic #4580).

WHY
  The epic's second rule is that the person leads: his words sit above the AI's. The site had no steady source of
  them (on 2026-10-03 its own absence fact read "Nothing in my journal for 24 days"). The owner ruled on 2026-10-04
  that he will supply his words "either via email or my claude chat program", so this is a store with two doors,
  not a new channel with its own schedule:

    INLET A  his Claude chat — the MCP tool ``log_owner_note`` (``mcp/tools_owner_words.py``).
    INLET B  email — his reply to the Story Desk's Monday questions (``insight-email-parser``, #4546). Each answer
             still lands as a ``STORYQA#W`` row for the chronicle exactly as before; it ALSO lands here, one entry
             per answered question, with the question as the ``prompt``.
    OUTLET   ``GET /api/owner_words`` (``web.site_api_thirdwall``), and through it ``/api/edition``'s ``his_words``.

  No Lambda, no schedule, no model call. Nothing here generates or edits a word in his voice: the text is stored
  byte for byte as it arrived and served byte for byte, or not at all.

THE RECORD — pk ``USER#matthew#SOURCE#owner_words``, sk ``WORDS#<PT date>#<content hash 12>``
  ``text``          his words EXACTLY as received (no trim, no copyedit, no marker removed)
  ``date``          the Pacific day the words are about (the chat tool's ``date`` argument, else the PT day received)
  ``received_at``   the UTC instant the store received them
  ``channel``       ``chat`` | ``email``
  ``prompt``        the question the words answer, if any (served beside them, so it is screened with them)
  ``verdict``       ``clean`` | ``held``; ``hold_kinds`` names the KIND of each hold, never a matched term
  ``off_record``    true when he marked it so (the flag, or the desk's "off record" / "OTR" marker in the text)

  The sk is a hash of (channel, prompt, text) under the day, written with ``attribute_not_exists(sk)``: a replayed
  tool call or a redelivered email finds the entry it already wrote and writes nothing twice.

  Absence semantics at birth (ADR-104): no row = he has said nothing through either door. A held row is stored and
  never served, and the served payload cannot tell it from silence. Silence is ``SILENCE_SENTENCE``, never filled.

THE FILTER — fail closed, at write AND at serve
  ``privacy.broadcast_sensitivity_gate.deterministic_findings`` (the off-repo vocabulary through ``privacy_guard``,
  the real-name guard, the PII patterns) plus the vocabulary's own display names and keywords, the desk's off-record
  marker, and tool-call residue. An unloadable vocabulary is a HOLD, never a pass. The serve path screens again, so
  a vocabulary that grew after the words were stored still applies; a hold recorded at write time is final.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

SOURCE = "owner_words"
PK = f"USER#matthew#SOURCE#{SOURCE}"
SK_PREFIX = "WORDS#"

CHANNEL_CHAT = "chat"
CHANNEL_EMAIL = "email"
CHANNELS = (CHANNEL_CHAT, CHANNEL_EMAIL)

VERDICT_CLEAN = "clean"
VERDICT_HELD = "held"

HOLD_OFF_RECORD = "off_record"
HOLD_FILTER_UNAVAILABLE = "filter_unavailable"
HOLD_TOO_LONG = "too_long"
HOLD_RESIDUE = "tool_call_residue"

#: The longest entry the page will carry. Longer words are still stored, word for word, and held.
MAX_CHARS = 4000
#: How many served entries the route returns, newest first.
SERVE_LIMIT = 10
#: How many stored rows the route reads to find them (held rows are skipped, so read past the limit).
READ_LIMIT = 100

STATE_OK = "ok"
STATE_ABSENT = "absent"
STATE_READ_FAILED = "read_failed"

#: The one sentence silence prints as. The edition's own absent sentence, so the two read the same.
SILENCE_SENTENCE = "Nothing in his own words yet."

# The verdict in plain words, for the person who just said them. General terms only: a hit is never named.
SAID_PUBLISHED = "Stored. It is public on the site word for word."
SAID_OFF_RECORD = "Stored as off the record. It never goes on the site."
SAID_HELD = "Stored, and held: the privacy filter matched something in it, so it does not go on the site."
SAID_UNAVAILABLE = "Stored, and held: the privacy filter could not be loaded, so it does not go on the site."
SAID_TOO_LONG = f"Stored, and held: it is longer than {MAX_CHARS} characters, so it does not go on the site."
SAID_RESIDUE = "Stored, and held: it carries tool-call markup, so it does not go on the site."


def _off_marker() -> "re.Pattern[str]":
    """The desk's off-record marker — ONE spelling, owned by ``content.story_questions`` (#4546)."""
    from content import story_questions

    return story_questions._OFF


def entry_sk(day: str, channel: str, text: str, prompt: Optional[str]) -> str:
    digest = hashlib.sha256("\x1f".join((channel, prompt or "", text)).encode("utf-8")).hexdigest()[:12]
    return f"{SK_PREFIX}{day}#{digest}"


# ── the filter ───────────────────────────────────────────────────────────────────────────────────────────────────


def screen(text: str, *, off_record: bool = False, vocabulary: Optional[Dict[str, Any]] = None) -> Tuple[str, List[str]]:
    """``(verdict, hold_kinds)``. Fail closed: an unavailable vocabulary or any error is a hold. Kinds only — the
    matched term never leaves this function (a leak through the stored row is still a leak)."""
    text = text if isinstance(text, str) else ""
    kinds: List[str] = []
    if off_record or _off_marker().search(text):
        kinds.append(HOLD_OFF_RECORD)
    if len(text) > MAX_CHARS:
        kinds.append(HOLD_TOO_LONG)
    try:
        from common.text_guards import find_tool_call_residue
        from privacy import broadcast_sensitivity_gate, content_filter_channel

        if find_tool_call_residue(text) is not None:
            kinds.append(HOLD_RESIDUE)
        data = vocabulary if vocabulary is not None else content_filter_channel.load(require=True)
        if not data:
            return VERDICT_HELD, kinds + [HOLD_FILTER_UNAVAILABLE]
        for k in broadcast_sensitivity_gate.deterministic_findings(text):
            if k not in kinds:
                kinds.append(k)
        # The display names and keywords of THIS vocabulary: privacy_guard reads the channel's own copy, and an
        # injected or freshly grown vocabulary must still bite.
        lowered = text.lower()
        names = [
            v.strip().lower()
            for v in (data.get("blocked_vices") or []) + (data.get("blocked_vice_keywords") or [])
            if isinstance(v, str) and v.strip()
        ]
        vice = broadcast_sensitivity_gate.CATEGORY_VICE
        if vice not in kinds and any(re.search(r"\b" + re.escape(n) + r"\b", lowered) for n in names):
            kinds.append(vice)
    except Exception:  # noqa: BLE001 — ContentFilterUnavailable and every other failure: hold, never pass
        return VERDICT_HELD, kinds + [HOLD_FILTER_UNAVAILABLE]
    return (VERDICT_HELD, kinds) if kinds else (VERDICT_CLEAN, [])


def screen_entry(text: str, prompt: Optional[str], *, off_record: bool = False, vocabulary=None) -> Tuple[str, List[str]]:
    """The words and the question they answer are served together, so both pass or neither is served."""
    verdict, kinds = screen(text, off_record=off_record, vocabulary=vocabulary)
    if prompt:
        p_verdict, p_kinds = screen(prompt, vocabulary=vocabulary)
        if p_verdict != VERDICT_CLEAN:
            kinds = kinds + [k for k in p_kinds if k not in kinds]
            verdict = VERDICT_HELD
    return verdict, kinds


def verdict_in_words(entry: Dict[str, Any]) -> str:
    """What happened to the words, for the person who said them. Never names what the filter matched."""
    if entry.get("verdict") == VERDICT_CLEAN:
        return SAID_PUBLISHED
    kinds = entry.get("hold_kinds") or []
    for kind, said in (
        (HOLD_OFF_RECORD, SAID_OFF_RECORD),
        (HOLD_FILTER_UNAVAILABLE, SAID_UNAVAILABLE),
        (HOLD_TOO_LONG, SAID_TOO_LONG),
        (HOLD_RESIDUE, SAID_RESIDUE),
    ):
        if kind in kinds:
            return said
    return SAID_HELD


# ── the write (both inlets) ──────────────────────────────────────────────────────────────────────────────────────


def make_entry(
    text: str,
    *,
    channel: str,
    day: str,
    received_at: str,
    prompt: Optional[str] = None,
    off_record: bool = False,
    extra: Optional[Dict[str, Any]] = None,
    vocabulary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One entry, screened. ``text`` is kept exactly as given — this function never alters it."""
    if channel not in CHANNELS:
        raise ValueError(f"unknown channel {channel!r}")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("an entry needs words")
    prompt = prompt if isinstance(prompt, str) and prompt.strip() else None
    marked = bool(off_record) or bool(_off_marker().search(text))
    verdict, kinds = screen_entry(text, prompt, off_record=marked, vocabulary=vocabulary)
    item: Dict[str, Any] = {
        "pk": PK,
        "sk": entry_sk(day, channel, text, prompt),
        "date": day,
        "received_at": received_at,
        "channel": channel,
        "text": text,
        "verdict": verdict,
        "hold_kinds": kinds,
        "off_record": marked,
        "source": SOURCE,
    }
    if prompt is not None:
        item["prompt"] = prompt
    for k, v in (extra or {}).items():
        if k not in item and v is not None:
            item[k] = v
    return item


def record(
    table: Any, entry: Dict[str, Any], *, stamp: Optional[Callable[[str, str], Dict[str, Any]]] = None
) -> Tuple[Dict[str, Any], bool]:
    """Write one entry once. ``(stored_entry, created)``: a replay returns the entry already stored, unchanged."""
    item = dict(entry)
    if stamp is not None:
        item.update(stamp(item["pk"], item["sk"]))
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(sk)")
        return item, True
    except Exception as e:  # noqa: BLE001
        if e.__class__.__name__ != "ConditionalCheckFailedException":
            raise
    existing = table.get_item(Key={"pk": item["pk"], "sk": item["sk"]}).get("Item")
    return (existing or item), False


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def entries_from_story_reply(
    answers: List[Dict[str, Any]], *, week: int, received_at: str, source_key: str, vocabulary=None
) -> List[Dict[str, Any]]:
    """INLET B. One entry per answered question of a Story Desk reply (``story_questions.parse_reply(...,
    keep_raw=True)``). The text is his answer as typed (``raw``), the question is the prompt; an answer he marked
    off record is stored off record. An unanswered question yields nothing — there is no row to write."""
    from common.pacific_time import pacific_date_of

    day = pacific_date_of(received_at)
    out = []
    for a in answers or []:
        raw = a.get("raw")
        if not isinstance(raw, str) or not raw.strip():
            continue
        out.append(
            make_entry(
                raw,
                channel=CHANNEL_EMAIL,
                day=day,
                received_at=received_at,
                prompt=a.get("question"),
                off_record=bool(a.get("off_record")),
                extra={"week": week, "q": a.get("q"), "source_key": source_key},
                vocabulary=vocabulary,
            )
        )
    return out


# ── the serve (read-only; GET /api/owner_words) ──────────────────────────────────────────────────────────────────


def recent(table: Any, limit: int = READ_LIMIT) -> List[Dict[str, Any]]:
    """The newest stored rows, newest day first."""
    from boto3.dynamodb.conditions import Key

    resp = table.query(KeyConditionExpression=Key("pk").eq(PK) & Key("sk").begins_with(SK_PREFIX), ScanIndexForward=False, Limit=limit)
    return list(resp.get("Items") or [])


def _servable(row: Dict[str, Any], vocabulary) -> bool:
    text = row.get("text")
    if row.get("verdict") != VERDICT_CLEAN or row.get("off_record") or row.get("channel") not in CHANNELS:
        return False
    if not isinstance(text, str) or not text.strip():
        return False
    return screen_entry(text, row.get("prompt"), vocabulary=vocabulary)[0] == VERDICT_CLEAN


def public_view(rows: List[Dict[str, Any]], *, vocabulary: Optional[Dict[str, Any]] = None, limit: int = SERVE_LIMIT) -> Dict[str, Any]:
    """``{state, entries, count, sentence}``. A held row is simply not there: the payload cannot tell it from
    silence. Each entry is ``{text, date, date_text, channel, prompt}`` with ``text`` exactly as stored."""
    from common.pacific_time import day_in_words, parse_day_key

    served = [r for r in rows if parse_day_key(str(r.get("date") or "")) and _servable(r, vocabulary)]
    served.sort(key=lambda r: (str(r.get("date")), str(r.get("received_at") or "")), reverse=True)
    entries = [
        {
            "text": r["text"],
            "date": r["date"],
            "date_text": day_in_words(r["date"]),
            "channel": r["channel"],
            "prompt": r.get("prompt") or None,
        }
        for r in served[:limit]
    ]
    if not entries:
        return {"state": STATE_ABSENT, "entries": [], "count": 0, "sentence": SILENCE_SENTENCE}
    return {"state": STATE_OK, "entries": entries, "count": len(entries), "sentence": None}


def read_public(table: Any) -> Dict[str, Any]:
    """The served payload, or ``{state: read_failed}`` — a failed read is never shown as silence."""
    try:
        rows = recent(table)
    except Exception:  # noqa: BLE001
        return {"state": STATE_READ_FAILED, "entries": [], "count": 0, "sentence": None}
    return public_view(rows)
