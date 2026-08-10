"""coach_outbound.py — the bounded UNSOLICITED half of the coach chat (Act 1b).

Everything the coaches have done on Telegram so far is REACTIVE: Matthew texts, a
coach answers. This module is the other direction — a coach opening a thread he
did not ask for — and the whole file is really one argument: *an unsolicited text
is a different risk class from a reply, so it gets a different gate*.

A wrong reply is a wrong answer to a question he asked. An unsolicited text is the
platform deciding, on its own, that his phone should buzz. Get that wrong twice and
the coaches become notifications — the thing every one of these personas is written
NOT to be. So:

  * **Two kinds, one budget.** Referral handoffs and Eli's morning check-in share a
    single daily ledger (``COACH#outbound_ledger`` / ``DAY#{PT-date}``), cap 2, with
    a referral sub-cap of 1. Two features cannot each politely spend "only one" and
    add up to a noisy morning. The claim is an atomic conditional update, and it is
    taken BEFORE inference — the nudge engine's idiom (#1382), for the same reason:
    a crash between generating and sending must never license a second send.
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

PROVENANCE_REFERRAL = "telegram_referral"
PROVENANCE_CHECKIN = "telegram_checkin"

# How much of the referring conversation the referred coach is shown.
REFERRAL_TAIL_TURNS = 6

# ── The shared daily budget ───────────────────────────────────────────────────

LEDGER_PK = "COACH#outbound_ledger"
LEDGER_SK_PREFIX = "DAY#"
DAILY_OUTBOUND_CAP = 2
DAILY_REFERRAL_CAP = 1
LEDGER_TTL_DAYS = 30

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


def claim_outbound(
    table,
    date_pt: str,
    *,
    referral: bool = False,
    cap: int = DAILY_OUTBOUND_CAP,
    referral_cap: int = DAILY_REFERRAL_CAP,
    now_ts: Optional[float] = None,
) -> bool:
    """Atomically claim one unsolicited-outbound slot for the day. False = don't send.

    One row per PT day carrying ``total`` and ``referrals``; the conditional
    ``ADD`` is what makes two concurrent workers unable to both pass the cap. Any
    storage error returns False — a ledger the platform cannot write is a ledger
    it cannot be trusted to count, and the safe reading of "I don't know how many
    I've sent" is "don't send another".
    """
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
