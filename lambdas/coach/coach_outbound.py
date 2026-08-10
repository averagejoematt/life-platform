"""coach_outbound.py — the bounded UNSOLICITED half of the coach chat (Act 1b).

Everything the coaches have done on Telegram so far is REACTIVE: Matthew texts, a
coach answers. This module is the other direction — a coach opening a thread he
did not ask for — and the whole file is really one argument: *an unsolicited text
is a different risk class from a reply, so it gets a different gate*.

A wrong reply is a wrong answer to a question he asked. An unsolicited text is the
platform deciding, on its own, that his phone should buzz. Get that wrong twice and
the coaches become notifications — the thing every one of these personas is written
NOT to be. So:

  * **Many kinds, one budget.** Referral handoffs, Eli's morning check-in and the
    data-triggered pings (#2490) share a single daily ledger
    (``COACH#outbound_ledger`` / ``DAY#{PT-date}``), cap 2, with a referral sub-cap
    of 1. Features cannot each politely spend "only one" and add up to a noisy
    morning. The claim is an atomic conditional update, and it is taken BEFORE
    inference — the nudge engine's idiom (#1382), for the same reason: a crash
    between generating and sending must never license a second send.
  * **Two slots, ranked.** Once several features contend for the same two slots,
    first-come-first-served silently starves whichever one fires last in the day.
    Each outbound therefore declares a PROVENANCE class, and from a cutoff hour the
    day's second slot is reserved for the high-priority (reactive) classes. The cap
    is unchanged — this is ordering, not a raise.
  * **An event fires once, ever.** A ping the DATA started also claims the event
    itself (``COACH#outbound_events`` / ``EVENT#{event-id}``, conditional put, no
    update path), so the same lift PR or the same three-day slide can never produce
    a second text on a later sweep.
  * **Quiet hours are structural, not prompted.** 21:00–07:00 PT, checked in code.
    A prompt rule is a request; this is the guarantee (the podcast-gate lesson).
  * **Everything fails DARK.** Unknown persona, no bot token, a chat id that isn't
    on that bot's roster, a ledger write that errors — every one of them is "don't
    send". This is the opposite posture from the inbound dedupe row (which fails
    OPEN, because a dropped real message looks like a broken bot). Here silence is
    always the safe answer.
  * **The marker is a request, never a guarantee.** A coach signals a handoff by
    ending its reply with a line containing only ``[[refer: <handoff-id>]]``. The
    parse fails soft to "no handoff", the line is stripped before ANY bubble is
    sent, and the deterministic gate below decides — never the model.

Nothing here talks to Telegram, Bedrock or boto3 clients: the transport work lives
in ``telegram_worker_lambda``. What lives here is the part worth unit-testing
without AWS — the marker parsing, the frames, the silence rule, the ledger claim.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Optional

logger = logging.getLogger(__name__)

# ── The referral marker ───────────────────────────────────────────────────────

# A marker line is a WHOLE line: `[[refer: pattern_coach]]`. Anchored so a coach
# writing about the syntax mid-sentence cannot trip it, and tolerant of spacing
# because the model produces this, not a parser.
REFERRAL_MARKER_RE = re.compile(r"^\s*\[\[\s*refer\s*:\s*([^\]\[]+?)\s*\]\]\s*$", re.IGNORECASE)

# The one sentence that permits the marker. Joins the colleagues block (the
# existing prompt seam) rather than the shared system-prompt builder, so the
# board, the observatory and every other persona surface stay untouched.
REFERRAL_RULE = (
    "HANDOFF: if this conversation genuinely belongs in a colleague's lane and they should text Matthew once "
    "themselves, you may end your reply with a final line containing ONLY [[refer: handoff-id]] — at most once, "
    "and only when the handoff actually helps him. It is never a way to avoid answering: say your own piece first. "
    "The line is stripped before Matthew sees it, and the handoff ids exist for that marker alone — never write one "
    "in your prose."
)

# What the REFERRED coach is told. Deliberately explicit that Matthew did not
# write to them: the failure mode of an outbound turn is a coach answering a
# message that was never sent ("great question!").
REFERRAL_FRAME = (
    "[Referral: {referring} was just texting with Matthew and flagged this for you — it is your lane, not theirs. "
    "Matthew has NOT texted you; you are opening this thread yourself. Send ONE short text that lands naturally on "
    "the handoff: name {referring} the way a colleague would, then say the one thing that is yours to say. Do not "
    "greet him as if he wrote to you, do not recap their conversation back at him, and do not hand him on to anyone "
    "else.]\n\nThe tail of their conversation:\n{tail}"
)

CHECKIN_FRAME = (
    "[Morning check-in — there is no inbound message. Matthew has not texted you; you are opening the day. Send him "
    "one short good-morning carrying the single thing that matters most today, grounded in the facts above. If the "
    "facts are thin, keep it purely human — never invent a number or a plan just to have something to say. Two "
    "bubbles at most. Do not greet him as if he wrote to you, and do not ask him to reply.]"
)

CELEBRATION_FRAME = (
    "[Something in the data is worth naming and it is YOUR lane. There is no inbound message — Matthew has not "
    "texted you; you are opening this thread yourself. Send ONE short text that says the thing plainly, the way a "
    "colleague who noticed would: no preamble, no congratulation theatre, no stacked exclamation marks, no plan "
    "bolted on, no question at the end. Use ONLY the evidence below — if it does not support a sentence, do not "
    "write that sentence.]\n\nWhat happened:\n{evidence}"
)

PROMISE_FRAME = (
    "[You told Matthew you would come back to him, and today is the day you named. There is no inbound message — "
    "he has not texted you; you are keeping your word. Send ONE short text that simply DOES the thing you said you "
    "would do — pick the thread back up where you left it. Do not announce that you are keeping a promise, do not "
    "apologise for the gap, do not recap the conversation, and do not open with an apology or a preamble. Use ONLY "
    "the evidence below.]\n\nWhat you said:\n{evidence}"
)

PRE_EVENT_FRAME = (
    "[Matthew told you he has a hard thing today, and this is the morning of it. There is no inbound message — he "
    "has not texted you; you are opening this thread yourself. Send ONE short text that shows you remembered: name "
    "the thing once, plainly, and say the human thing. No advice, no protocol, no list, no plan, no question at the "
    "end, and never invent a detail he did not give you. Use ONLY the evidence below.]\n\nWhat he told you:\n{evidence}"
)

CONCERN_FRAME = (
    "[Something in the data has been sliding for a few days and it is YOUR lane. There is no inbound message — "
    "Matthew has not texted you; you are opening this thread yourself. Send ONE short text that checks in like a "
    "person, not a monitor: name what you noticed once, lightly, and leave the door open. No diagnosis, no "
    "protocol, no list, no alarm, and never imply you know why — you do not. Use ONLY the evidence "
    "below.]\n\nWhat you noticed:\n{evidence}"
)

# ── Provenance: what KIND of unsolicited text this is ─────────────────────────
#
# Six features can now open a thread and the day holds two slots, so provenance
# is no longer a label on a stored row — it is the RANK that decides who gets to
# speak. The order is the owner's, and it reads as a claim about what a coach
# owes him: breaking a promise is the worst thing a coach can do, so a kept one
# outranks everything; a referral is contextual to a conversation he JUST had;
# support before a thing he told us about beats noticing a thing after it;
# concern beats celebration, because checking on him matters more than
# congratulating him; and the routine morning check-in — the one that fires
# whether or not anything happened — outranks only the pleasantry.
PROVENANCE_PROMISE = "telegram_promise"
PROVENANCE_REFERRAL = "telegram_referral"
PROVENANCE_PRE_EVENT = "telegram_pre_event"
PROVENANCE_CONCERN = "telegram_concern"
PROVENANCE_CHECKIN = "telegram_checkin"
PROVENANCE_CELEBRATION = "telegram_celebration"

OUTBOUND_PRIORITY = {
    PROVENANCE_PROMISE: 0,
    PROVENANCE_REFERRAL: 1,
    PROVENANCE_PRE_EVENT: 2,
    PROVENANCE_CONCERN: 3,
    PROVENANCE_CHECKIN: 4,
    PROVENANCE_CELEBRATION: 5,
}
# An unrecognised provenance ranks LAST, never first: a new outbound feature that
# forgets to register itself may be starved, but it can never starve a promise.
LOWEST_PRIORITY = max(OUTBOUND_PRIORITY.values()) + 1

EVENT_FRAMES = {
    PROVENANCE_CELEBRATION: CELEBRATION_FRAME,
    PROVENANCE_CONCERN: CONCERN_FRAME,
    # #2486/#2491: the two open-loop classes. They ride the SAME frame lookup as the
    # data-triggered pings — an unsolicited text is an unsolicited text, whatever
    # opened the loop — so nothing downstream needs a new branch to send one.
    PROVENANCE_PROMISE: PROMISE_FRAME,
    PROVENANCE_PRE_EVENT: PRE_EVENT_FRAME,
}

# How much of the referring conversation the referred coach is shown.
REFERRAL_TAIL_TURNS = 6

# ── The shared daily budget ───────────────────────────────────────────────────

LEDGER_PK = "COACH#outbound_ledger"
LEDGER_SK_PREFIX = "DAY#"
DAILY_OUTBOUND_CAP = 2
DAILY_REFERRAL_CAP = 1
LEDGER_TTL_DAYS = 30

# The reserved second slot. The cap is NOT raised — this is ordering, and it
# exists because first-come-first-served has a specific failure: the scheduled
# features fire in the morning, the reactive ones fire when Matthew actually
# talks to someone, so a routine ping can pre-spend the day before the valuable
# text has any chance to happen. From the cutoff hour onward the day's LAST slot
# belongs to the reactive classes; the first slot is never reserved, so whatever
# fires first in the morning still gets to speak.
#
# 09:00 PT is chosen as the hour by which every SCHEDULED outbound has run in
# both PDT and PST (the sweep at 09:00/08:00, the check-in at 10:15/09:15 — the
# UTC-fixed crons drift an hour between them, and the cutoff has to sit under
# both). Quiet hours end at 07:00, so the unreserved window is deliberately two
# hours wide and nothing routine is scheduled inside it.
RESERVED_SLOT_CUTOFF_HOUR = 9
RESERVED_SLOT_MAX_PRIORITY = OUTBOUND_PRIORITY[PROVENANCE_PRE_EVENT]

# ── The event ledger: one real-world event, one text, ever ────────────────────

EVENT_LEDGER_PK = "COACH#outbound_events"
EVENT_SK_PREFIX = "EVENT#"
EVENT_TTL_DAYS = 90

# Quiet hours, Pacific. Inclusive of 21:00, exclusive of 07:00.
QUIET_START_HOUR = 21
QUIET_END_HOUR = 7


def ledger_sk(date_pt: str) -> str:
    return f"{LEDGER_SK_PREFIX}{date_pt}"


def in_quiet_hours(now_pt) -> bool:
    """True when an unsolicited text would land in his evening or his sleep.

    Takes the datetime rather than reading the clock so every caller and every
    test states the moment explicitly (the wall-clock discipline: a fixture date
    plus now-math is a time bomb).
    """
    try:
        hour = now_pt.hour
    except AttributeError:  # pragma: no cover — a caller passing something odd
        return True  # unknown time ⇒ do not text: the dark direction is the safe one
    return hour >= QUIET_START_HOUR or hour < QUIET_END_HOUR


def priority(provenance: Optional[str]) -> int:
    """Rank of an outbound class — lower speaks first. Unknown ranks last."""
    return OUTBOUND_PRIORITY.get(provenance or "", LOWEST_PRIORITY)


def effective_cap(provenance: Optional[str], now_pt, cap: int = DAILY_OUTBOUND_CAP) -> int:
    """The cap THIS class may spend against right now.

    Implemented as a smaller cap rather than a separate rule so the reservation
    rides inside the same atomic conditional update the day budget already uses —
    two workers cannot race their way around it, and there is no second ledger
    field to keep consistent. Returns ``cap`` untouched for a high-priority class,
    or before the cutoff hour; a low-priority class after the cutoff sees one
    fewer slot, which is exactly "you may open the day, you may not close it".
    """
    if priority(provenance) <= RESERVED_SLOT_MAX_PRIORITY:
        return cap
    try:
        hour = now_pt.hour
    except AttributeError:  # pragma: no cover — an odd caller; keep the reservation ON
        return max(1, cap - 1)
    return cap if hour < RESERVED_SLOT_CUTOFF_HOUR else max(1, cap - 1)


def event_sk(event_id: str) -> str:
    return f"{EVENT_SK_PREFIX}{event_id}"


def claim_event(table, event_id: str, *, now_ts: Optional[float] = None) -> bool:
    """Write-once claim on ONE real-world event. False = it already fired.

    The event id is derived from the FACT (the lift and its date, the milestone
    id, the day a slide started), never from the moment of evaluation — which is
    what makes a sweep idempotent and a three-day slide that runs to four days
    silent on day four. The conditional put is the whole mechanism; there is
    deliberately no update path and no delete path, so an event cannot be
    un-fired by anything short of a manual write.

    Any storage error returns False, matching ``claim_outbound``: a ledger the
    platform cannot write is one it cannot be trusted to read, and the safe
    reading of "I don't know whether I already said this" is "don't say it".
    """
    if not event_id:
        return False
    now = now_ts if now_ts is not None else time.time()
    try:
        table.put_item(
            Item={
                "pk": EVENT_LEDGER_PK,
                "sk": event_sk(event_id),
                "record_type": "coach_outbound_event",
                "event_id": event_id,
                "claimed_ts": int(now),
                "ttl": int(now + EVENT_TTL_DAYS * 86400),
            },
            ConditionExpression="attribute_not_exists(sk)",
        )
        return True
    except Exception as e:  # noqa: BLE001 — ConditionalCheckFailed = already fired
        if "ConditionalCheckFailed" in type(e).__name__ or "ConditionalCheckFailed" in str(e):
            logger.info("[outbound] event %s already fired — standing down", event_id)
        else:
            logger.warning("[outbound] event claim failed (%s) — standing down", e)
        return False


def claim_outbound(
    table,
    date_pt: str,
    *,
    referral: bool = False,
    cap: int = DAILY_OUTBOUND_CAP,
    referral_cap: int = DAILY_REFERRAL_CAP,
    now_ts: Optional[float] = None,
    provenance: Optional[str] = None,
    now_pt=None,
) -> bool:
    """Atomically claim one unsolicited-outbound slot for the day. False = don't send.

    One row per PT day carrying ``total`` and ``referrals``; the conditional
    ``ADD`` is what makes two concurrent workers unable to both pass the cap. Any
    storage error returns False — a ledger the platform cannot write is a ledger
    it cannot be trusted to count, and the safe reading of "I don't know how many
    I've sent" is "don't send another".

    ``provenance`` + ``now_pt`` arm the reserved-slot rule (see ``effective_cap``).
    Both are optional and default to the un-reserved behaviour, so a caller that
    passes neither gets exactly the pre-#2490 cap — the reservation is something a
    feature opts into by declaring what kind of text it is.
    """
    if provenance is not None and now_pt is not None:
        cap = effective_cap(provenance, now_pt, cap)
    names = {"#total": "total", "#ttl": "ttl"}  # both are DynamoDB reserved words
    values = {
        ":one": 1,
        ":cap": cap,
        ":rt": "coach_outbound_ledger",
        ":ttl": int((now_ts if now_ts is not None else time.time()) + LEDGER_TTL_DAYS * 86400),
    }
    condition = "(attribute_not_exists(#total) OR #total < :cap)"
    add_clause = "#total :one"
    if referral:
        names["#ref"] = "referrals"
        values[":rcap"] = referral_cap
        condition += " AND (attribute_not_exists(#ref) OR #ref < :rcap)"
        add_clause += ", #ref :one"
    try:
        table.update_item(
            Key={"pk": LEDGER_PK, "sk": ledger_sk(date_pt)},
            UpdateExpression=f"SET record_type = :rt, #ttl = if_not_exists(#ttl, :ttl) ADD {add_clause}",
            ConditionExpression=condition,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
        return True
    except Exception as e:  # noqa: BLE001 — ConditionalCheckFailed = cap reached
        if "ConditionalCheckFailed" in type(e).__name__ or "ConditionalCheckFailed" in str(e):
            logger.info("[outbound] daily cap reached for %s (referral=%s) — standing down", date_pt, referral)
        else:
            logger.warning("[outbound] ledger claim failed (%s) — standing down", e)
        return False


# ── Marker parsing + stripping ────────────────────────────────────────────────


def parse_referral(text: str) -> Optional[str]:
    """The handoff id a reply asked for, or None. Never raises.

    Returns the LAST marker in the text: the instruction says "end your reply
    with", and if a model emits two the later one is the one it settled on. The
    payload is returned RAW — resolution to a real persona is a separate,
    registry-backed step, so an unknown id is a no-handoff rather than a lookup
    against a name the model invented.
    """
    found = None
    for line in (text or "").splitlines():
        m = REFERRAL_MARKER_RE.match(line)
        if m:
            found = m.group(1).strip()
    return found or None


def strip_referral_markers(bubbles: list) -> list:
    """Remove every marker line from the bubbles that are about to be sent.

    Runs on EVERY outbound path, not only when a handoff was granted: the marker
    is machine syntax and must never reach Matthew's phone, whether or not the
    gate below lets the handoff through, and whether or not the referred coach
    was supposed to emit one.

    This is a formatter touching text the grounding gate has already adjudicated,
    which the chat engine normally forbids. It is safe in exactly one direction:
    the operation only REMOVES a line that matches machine syntax, so it cannot
    invent a claim the gate never saw. A bubble that was nothing but a marker
    disappears; a reply that was nothing but a marker degrades to one empty-safe
    bubble rather than an empty send.
    """
    out = []
    for b in bubbles or []:
        kept = "\n".join(line for line in str(b).splitlines() if not REFERRAL_MARKER_RE.match(line)).strip()
        if kept:
            out.append(kept)
    return out


def resolve_referral_target(payload: Optional[str], personas: dict, self_persona_id: str) -> Optional[str]:
    """Marker payload → a real persona_id, or None (which means: no handoff).

    Accepts the persona_id (what the prompt asks for) and, fail-soft, the display
    name — a model that writes ``[[refer: Dr. Nora Vale]]`` has expressed exactly
    the same intent and there is no reason to punish it with silence. A
    self-referral resolves to None: a coach cannot hand a conversation to itself.
    """
    raw = (payload or "").strip().strip("`'\"")
    if not raw or not personas:
        return None
    if raw in personas:
        return None if raw == self_persona_id else raw
    low = raw.lower()
    for pid, p in personas.items():
        if str((p or {}).get("name") or "").lower() == low:
            return None if pid == self_persona_id else pid
    return None


# ── Frames ────────────────────────────────────────────────────────────────────


def render_tail(turns: list, matthew_label: str, coach_label: str, limit: int = REFERRAL_TAIL_TURNS) -> str:
    """The last few turns of the referring conversation, attributed by NAME.

    Attributed rather than role-tagged because the referred coach is reading a
    colleague's conversation, not resuming its own — 'Dr. Lisa Park:' is the
    frame that keeps it from answering as though Matthew wrote those lines.
    """
    lines = []
    for t in (turns or [])[-limit:]:
        text = str((t or {}).get("text") or "").strip()
        if not text:
            continue
        who = matthew_label if (t or {}).get("role") == "matthew" else coach_label
        lines.append(f"{who}: {text}")
    return "\n".join(lines)


def referral_frame(referring_name: str, tail: str) -> str:
    return REFERRAL_FRAME.format(referring=referring_name or "a colleague", tail=tail or "(no transcript available)")


def checkin_frame() -> str:
    return CHECKIN_FRAME


def event_frame(provenance: str, evidence: str) -> str:
    """The frame for a data-triggered ping — or "" when there is nothing behind it.

    Empty evidence returns an empty frame ON PURPOSE, and every caller treats ""
    as "do not send". An unsolicited text with no rows behind it is the exact
    thing the grounding gate exists to stop, and it is cheaper to make it
    unrepresentable here than to catch it three layers later.
    """
    template = EVENT_FRAMES.get(provenance)
    body = (evidence or "").strip()
    return template.format(evidence=body) if template and body else ""


# ── Silence respect ───────────────────────────────────────────────────────────


def two_consecutive_ignored(rows: list, provenance: str, role_coach: str = "coach", role_matthew: str = "matthew") -> bool:
    """True when the last two check-ins of this kind both went unanswered.

    A coach who texts first and gets nothing back twice running has been told
    something, and the honest response to that is to stop — not to keep the
    cadence because a cron says so. ``rows`` is the coach's own chat partition,
    OLDEST-FIRST; "answered" means any Matthew turn stored after that check-in.
    Fewer than two check-ins on record is never a silence signal.
    """
    ordered = list(rows or [])
    marks = [i for i, r in enumerate(ordered) if (r or {}).get("role") == role_coach and (r or {}).get("provenance") == provenance]
    if len(marks) < 2:
        return False
    for i in marks[-2:]:
        if any((r or {}).get("role") == role_matthew for r in ordered[i + 1 :]):
            return False
    return True
