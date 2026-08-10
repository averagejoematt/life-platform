"""coach_open_loops.py — the promise a coach made in a text, kept on the day (#2486/#2491).

A coach that says "I'll check in Friday" and then never does is worse than one that
never offered. Same shape from the other side: Matthew mentions a presentation on
Thursday, and nobody says a word on Thursday morning. Both are OPEN LOOPS — a future
obligation created inside a conversation and then dropped, because nothing between the
chat turn and the outbound sweep was looking for one.

This module is that missing look. It is the extractor half; the delivery half already
exists and is NOT rebuilt here — #2490/#2527 shipped the outbound claim, the shared
daily cap, quiet hours, the two-ignored silence rule, the frames and the sweep
heartbeat. An open loop becomes an ordinary event candidate on that existing path.

WHERE THE RECORD LIVES — the partition decision, stated once.

There is **no new row class**. The record of a promise is the ``CHAT#`` turn it was
made in, re-read. Three reasons, in order of weight:

1. **Honesty (ADR-104).** A derived row is a paraphrase, and a paraphrase can drift
   from what was actually said. Re-reading the stored turn means the follow-up is
   grounded in the coach's own sentence, verbatim, forever — there is no second copy
   to fall out of sync with the first.
2. **One writer per partition.** ``COMMITMENT#`` is written ONLY by
   ``coach_state_updater``, nightly, from the ``OUTPUT#`` extraction, and it means the
   opposite thing: an action the coach holds MATTHEW to, graded kept/broken by
   ``coach_prediction_evaluator`` and counted by ``relationship_engine``. Writing a
   coach's own promise into that prefix would put two extractors on one partition and
   feed rows nobody grades into a ledger whose whole job is grading. Adding a third
   prefix instead would avoid the collision but keep the copy. Reading beats both:
   the chat path stays the only writer of ``CHAT#``, and this module only reads.
3. **Reset-safety, for free.** ADR-153 already classifies ``COACH#*``/``CHAT#`` as
   ``CROSS_PHASE``. A promise therefore survives an experiment reset exactly as the
   conversation that contains it does, with no new entry that could silently escape
   ``phase_taxonomy``'s coverage assertion. The only state this feature writes is the
   fire-once claim in ``COACH#outbound_events``, which is already ``SYSTEM_STATE`` and
   whose only writer is already the sweep.

WHAT MAY BECOME A FOLLOW-UP. Deterministic parsing, never inference. ADR-104's bar
here is not "probably meant to check in" — it is a sentence he can be shown:

  * the coach must have used a first-person FUTURE commitment ("I'll", "I'm going to")
    attached to a CONTACT verb (check in, follow up, text you, ask you) — a promise to
    think about something is not a promise to text;
  * an offer is not a promise: a question, or a hedge ("if you want", "I could",
    "want me to"), is discarded;
  * the sentence must name a day this module can resolve without guessing. No day
    means no follow-up — silence, not a guess at when he meant.

Same three rules for the pre-event half, over MATTHEW's turns instead: a curated noun
list of things that are hard on a specific morning, stated as fact ("I have a
presentation Thursday"), with a resolvable day.

WHO TEXTS. The coach he told — deliberately, and this is a correction to #2491, which
named the mind lane. A coach can only remember what was said to THEM; routing an open
loop to a seat that was not in the conversation would have that coach open a thread
about a transcript it never saw. When he tells the mind coach, the mind coach texts.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

KIND_PROMISE = "promise"
KIND_PRE_EVENT = "pre_event"

# How far back a turn may be read for an open loop. Comfortably wider than the
# longest due horizon below, so a promise made two weeks out is still readable on
# the morning it comes due.
LOOKBACK_DAYS = 21
# The furthest ahead a stated day is trusted. Past this the sentence is far more
# likely to be prose than a schedule ("I'll check in in a month or two").
MAX_HORIZON_DAYS = 14

# A promise may be kept a day late — a kept promise is still worth keeping when the
# cap or a hold cost it its own morning. A pre-event has no grace at all: "good luck
# with the presentation" the day after the presentation is not support, it is noise.
GRACE_DAYS = {KIND_PROMISE: 1, KIND_PRE_EVENT: 0}

_ROLE_COACH = "coach"
_ROLE_MATTHEW = "matthew"

# ── The sentence gates ────────────────────────────────────────────────────────

# One sentence at a time, so a commitment in one clause cannot borrow a day from
# another ("I'll think about it. Friday was rough.").
_SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]?")

# A first-person future commitment attached to a verb that means CONTACT. "I'll
# look at it" is not a promise to text; "I'll check in" is.
_PROMISE_RE = re.compile(
    r"\b(?:i'?ll|i will|i'?m going to|i am going to|i'?m gonna)\b[^.!?]{0,48}?"
    r"\b(?:check in|check back|check on you|follow up|circle back|text you|message you|"
    r"ping you|ask you|remind you|get back to you)\b",
    re.IGNORECASE,
)

# The things that are hard on a specific morning. A curated list, on purpose: a
# general "something important" classifier is exactly the inference ADR-104 forbids.
_PRE_EVENT_NOUNS = (
    "presentation",
    "interview",
    "flight",
    "exam",
    "surgery",
    "procedure",
    "deadline",
    "performance review",
    "board meeting",
    "big meeting",
    "race",
    "competition",
    "defense",
    "closing",
    "funeral",
    "hearing",
)
_PRE_EVENT_RE = re.compile(
    r"\b(?:i have|i'?ve got|i have got|i'?ve|i got|there'?s)\b[^.!?]{0,48}?\b(" + "|".join(_PRE_EVENT_NOUNS) + r")\b",
    re.IGNORECASE,
)

# An offer, a hypothetical or a musing — none of them is a thing he was told would
# happen. Discarded before any day is resolved.
_HEDGE_RE = re.compile(
    r"\b(?:if you|if that|if it|if i|unless|want me to|should i|do you want|would you like|"
    r"maybe|might|i could|i can|probably|perhaps|thinking about|hoping to|trying to|"
    r"was going to|used to)\b",
    re.IGNORECASE,
)

# ── Day resolution ────────────────────────────────────────────────────────────

_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_WEEKDAY_RE = re.compile(r"\b(next\s+)?(" + "|".join(_WEEKDAYS) + r")\b", re.IGNORECASE)
_IN_N_DAYS_RE = re.compile(r"\bin\s+(\d{1,2}|one|two|three|four|five|six|seven|ten)\s+days?\b", re.IGNORECASE)
_WORD_N = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "ten": 10}


def _day(value) -> Optional[object]:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def resolve_due(sentence: str, made_on: str) -> Optional[str]:
    """The day a sentence names, as an ISO date — or None, which means "don't fire".

    Resolved relative to the day the sentence was SAID, never to the day the sweep
    runs, so re-reading the same turn a week later produces the same answer. Only
    strictly-future days resolve: "I'll check in Friday" said ON Friday means the
    next one, because a promise to come back cannot be due in the moment it is made,
    and a same-day reference cannot be served by a once-a-day morning sweep at all.
    """
    base = _day(made_on)
    if base is None:
        return None
    text = (sentence or "").lower()

    offset: Optional[int] = None
    if "day after tomorrow" in text:
        offset = 2
    elif "tomorrow" in text:
        offset = 1
    elif re.search(r"\bnext week\b", text):
        offset = 7
    elif re.search(r"\bin a week\b", text):
        offset = 7
    else:
        m = _IN_N_DAYS_RE.search(text)
        if m:
            raw = m.group(1).lower()
            offset = _WORD_N.get(raw, int(raw) if raw.isdigit() else 0)
        else:
            w = _WEEKDAY_RE.search(text)
            if w:
                ahead = (_WEEKDAYS[w.group(2).lower()] - base.weekday()) % 7
                offset = (ahead or 7) + (7 if w.group(1) else 0)
    if not offset or offset < 1 or offset > MAX_HORIZON_DAYS:
        return None
    return (base + timedelta(days=offset)).isoformat()


# ── Extraction ────────────────────────────────────────────────────────────────


def _sentences(text: str) -> list:
    return [s.strip() for s in _SENTENCE_RE.findall(str(text or "")) if s.strip()]


def _row_date(row: dict) -> str:
    """The PT-ish day a turn was stored, off the sk (``CHAT#{date}#{uid}``)."""
    sk = str((row or {}).get("sk") or "")
    part = sk[len("CHAT#") :].split("#")[0] if sk.startswith("CHAT#") else ""
    return part if _day(part) else str((row or {}).get("created_at") or "")[:10]


def extract_open_loops(rows: list, persona_id: str) -> list:
    """Every open loop visible in one coach's stored turns. Pure, no clock, no I/O.

    Both halves are the same shape and deliberately share one function: they differ
    only in whose turn is read and which sentence gate applies. The ``event_id`` is
    derived from the STORED ROW (its sk plus the sentence's index), so re-reading the
    same thread on ten consecutive sweeps derives one id, and two promises inside one
    reply stay distinct.
    """
    loops: list = []
    for row in rows or []:
        role = (row or {}).get("role")
        made_on = _row_date(row)
        if not _day(made_on):
            continue
        if role == _ROLE_COACH:
            kind, gate = KIND_PROMISE, _PROMISE_RE
        elif role == _ROLE_MATTHEW:
            kind, gate = KIND_PRE_EVENT, _PRE_EVENT_RE
        else:
            continue
        for idx, sentence in enumerate(_sentences(row.get("text"))):
            if "?" in sentence or _HEDGE_RE.search(sentence) or not gate.search(sentence):
                continue
            due = resolve_due(sentence, made_on)
            if not due:
                continue
            loops.append(
                {
                    "kind": kind,
                    "persona_id": persona_id,
                    "made_on": made_on,
                    "due": due,
                    "sentence": sentence,
                    "source_sk": str(row.get("sk") or ""),
                    "loop_id": f"{kind}#{persona_id}#{row.get('sk')}#{idx}",
                }
            )
    return loops


def is_due(loop: dict, today: str) -> bool:
    """Due today, or inside this kind's grace window. Never early, never stale."""
    due, now = _day((loop or {}).get("due")), _day(today)
    if due is None or now is None:
        return False
    age = (now - due).days
    return 0 <= age <= GRACE_DAYS.get(loop.get("kind"), 0)


def evidence_lines(loop: dict, today: str) -> list:
    """The only thing the coach is allowed to stand on — his own sentence, verbatim.

    Quoted rather than summarised. A follow-up that paraphrases the promise is a
    follow-up that can get the promise wrong, and the whole trust value of keeping
    one is that it is recognisably the thing that was said.
    """
    kind = (loop or {}).get("kind")
    who = "You texted Matthew" if kind == KIND_PROMISE else "Matthew texted you"
    late = (_day(today) - _day(loop["due"])).days if _day(today) and _day(loop.get("due")) else 0
    when = f"That day is today ({today})." if not late else f"That day was {loop['due']} — {late} day late; today is {today}."
    return [
        f'{who} on {loop.get("made_on")}: "{loop.get("sentence")}"',
        when,
        (
            "Nothing else here is evidence. If the sentence does not support something, do not say it."
            if kind == KIND_PROMISE
            else "That single sentence is everything the platform knows about it — do not add detail he did not give."
        ),
    ]


# ── The fetch half ────────────────────────────────────────────────────────────


def read_chat_rows(table, persona_id: str, today: str, lookback_days: int = LOOKBACK_DAYS) -> list:
    """One coach's recent ``CHAT#`` turn rows. A read failure is simply no rows.

    A key-RANGE query rather than a prefix query with a limit: ``CHAT#summary#``
    rows live inside the same prefix by design (one cross-phase family) and sort
    above every dated turn, so bounding by date excludes them structurally instead
    of relying on the role filter alone.
    """
    end = _day(today)
    if end is None:
        return []
    from coach.coach_chat import chat_pk

    start = (end - timedelta(days=lookback_days)).isoformat()
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :lo AND :hi",
            ExpressionAttributeValues={":pk": chat_pk(persona_id), ":lo": f"CHAT#{start}", ":hi": f"CHAT#{today}~"},
        )
        return [r for r in (resp.get("Items") or []) if r.get("role") in (_ROLE_COACH, _ROLE_MATTHEW)]
    except Exception as e:  # noqa: BLE001 — an unreadable thread costs a text, never invents one
        logger.warning("[open-loops] chat read failed for %s: %s", persona_id, e)
        return []


def gather_open_loops(table, today: str, persona_ids: Optional[list] = None) -> list:
    """Every open loop across every coach who can text, unfiltered by due date.

    The due filter stays in the detector so the whole set is testable as data, and
    so a caller can see "there are loops, none due today" rather than an ambiguous
    empty list.
    """
    if persona_ids is None:
        from coach.persona_registry import TEXTING_PERSONA_IDS

        persona_ids = list(TEXTING_PERSONA_IDS)
    loops: list = []
    for pid in persona_ids:
        loops.extend(extract_open_loops(read_chat_rows(table, pid, today), pid))
    return loops
