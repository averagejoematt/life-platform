"""telegram_group.py — the board room: Grand Rounds as a real group chat (epic #2363).

Every coach bot in the group receives every message through its OWN webhook (group
privacy mode is disabled for exactly this reason), so one message from Matthew
becomes N independent worker invocations — one per bot — each knowing only which
bot it is. The room therefore needs a WHO-SPEAKS rule, and the rule here is a pure
function of the update itself, computed identically by every worker with no
cross-Lambda coordination, no claim table, and no model call:

  1. A coach-bot @mention names the speaker(s). Everyone unmentioned is silent —
     including the chair.
  2. Failing that, a reply to a coach's message re-addresses that coach.
  3. Failing both, the CHAIR speaks. The chair is the lead — the same owner
     decision that put Eli behind @ajm_board_bot (#2719, 2026-08-16: "the lead
     chairs Grand Rounds").

Mentions are matched against the roster's naming convention (``ajm_*_bot``) rather
than a fetched roster: each worker can cheaply know its OWN username (``getMe``,
cached) but not its colleagues', and the convention is pinned by test against
``setup_telegram_bots``'s roster so a bot that breaks the pattern fails loudly at
registration time, not silently in the room.

The room's conversation is ONE shared thread (`ROOM_ID`'s CHAT# partition — the
phase-taxonomy CROSS_PHASE family by the ``COACH#*``+``CHAT#`` prefix rule), with
each coach turn stamped with its speaker. A coach answering in the room sees the
whole room's recent scrollback, colleagues' answers included — that is what makes
it a room and not eight private threads wearing one chat id.

What the room deliberately does NOT do (v1): referral handoffs (the colleague is
already present — Matthew can mention them), reactions, and the lazy daily chat
summary (it summarizes a persona's own thread; the room's multi-voice scrollback
would need its own summarizer to be honest — a later slice).
"""

from __future__ import annotations

import json
import logging
import re
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

# The shared room thread. Runs through coach_chat.chat_pk() like every other chat
# partition (→ COACH#board_room_coach) so storage, taxonomy classification and any
# future reader all derive it the same way instead of trusting a second literal.
ROOM_ID = "board_room"

# The route key whose worker speaks when nobody was addressed. This is the LEAD's
# telegram_route (config/personas.json: eli_marsh → "headcoach"), pinned by
# tests/test_telegram_board_room.py against the registry so the constant cannot
# drift from the persona config that actually owns the decision.
CHAIR_ROUTE = "headcoach"

# The roster convention every coach bot username follows (setup_telegram_bots.py's
# BOTS/OPTIONAL_BOTS — pinned by test). A group @mention matching this is a coach
# being addressed; one that doesn't (a human, a third-party bot) must NOT silence
# the chair.
BOT_MENTION = re.compile(r"^ajm_[a-z0-9_]+_bot$")

_TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"

# getMe answers per warm container, cached by token so the room decision costs one
# HTTP round-trip per bot per container lifetime, not per message.
_USERNAMES: dict = {}

# Appended to the speaker's colleagues block — the room context the persona prompt
# otherwise has no way to know. Deliberately short: the persona, voice and facts
# blocks carry everything else, and this must not become a second persona.
ROOM_FRAME = (
    "\n\nYou are in Grand Rounds — the group chat where Matthew and the coaching "
    "staff talk together. You were addressed (or you chair the room), so answer as "
    "yourself, briefly — a group chat rewards one good point, not a briefing. Never "
    "speak for a colleague; if their domain is the better home for the question, say "
    "so by name and leave it to them."
)


def bot_username(token: Optional[str]) -> Optional[str]:
    """This bot's @username, lowercased, via ``getMe`` — cached, fail-soft None.

    None (network refusal, malformed answer) means the worker cannot know who it
    is: ``who_speaks`` then declines every mention/reply claim, and only the chair
    fallback can still fire — a degraded room where the chair answers is better
    than one where an unsure bot answers a colleague's mention.
    """
    if not token:
        return None
    if token in _USERNAMES:
        return _USERNAMES[token]
    try:
        req = urllib.request.Request(_TELEGRAM_API.format(token=token, method="getMe"))
        with urllib.request.urlopen(req, timeout=10) as r:
            me = (json.loads(r.read().decode("utf-8")) or {}).get("result") or {}
        username = (me.get("username") or "").lower() or None
    except Exception as e:
        logger.warning("[board-room] getMe failed — this worker cannot claim mentions: %s", e)
        return None  # NOT cached: a transient refusal must not dark a bot all container long
    _USERNAMES[token] = username
    return username


def who_speaks(*, mentions, reply_to_bot, my_username, is_chair) -> bool:
    """The room's one rule. Pure, and identical in every worker — see module doc.

    ``mentions``/``reply_to_bot`` arrive lowercased from the gateway's wire
    extraction. Non-roster mentions (a human, some other bot) are ignored rather
    than treated as an address, so mentioning a friend never silences the chair.
    """
    coach_mentions = [m for m in (mentions or []) if BOT_MENTION.match(m or "")]
    if coach_mentions:
        return bool(my_username) and my_username in coach_mentions
    if reply_to_bot and BOT_MENTION.match(reply_to_bot):
        return bool(my_username) and reply_to_bot == my_username
    return bool(is_chair)


def first_private_chat_id(chat_ids) -> Optional[object]:
    """The first PRIVATE (positive) chat id — the only kind outbound may text.

    Group/supergroup ids are negative. A group id that lands in a bot's
    ``chat_ids`` (discovery picks up whatever chatted with the bot) must never
    become the destination of a morning check-in or an event ping: an unsolicited
    text belongs in the 1:1 thread, not broadcast to the room.
    """
    for cid in chat_ids or []:
        try:
            if int(cid) > 0:
                return cid
        except (TypeError, ValueError):
            continue
    return None


def _room_rows(worker) -> list:
    """The room's recent turn rows, oldest-first — the shared scrollback."""
    return worker._chat_rows(ROOM_ID)


def room_thread(rows: list) -> list:
    """Room rows -> run_turn thread, with coach turns speaker-prefixed.

    In a 1:1 thread "assistant said X" is unambiguous. In the room it is not —
    the model needs to see WHICH colleague said what, or it will absorb their
    words as its own. Matthew's turns stay bare; his identity is the role.
    """
    out = []
    for r in rows:
        text = r.get("text") or ""
        if r.get("role") == "coach" and r.get("coach_name"):
            text = f"[{r['coach_name']}] {text}"
        out.append({"role": r.get("role"), "text": text, "status": r.get("status")})
    return out


def group_turn(order: dict, token: str) -> dict:
    """One room message, one worker's whole part in it: decide, then speak or stay silent.

    Runs INSTEAD of the 1:1 path (the worker branches here before its typing
    indicator — eight bots typing at once would be the room's tell). Imported
    lazily by the worker and importing the worker lazily back: the worker module
    is fully loaded by the time any order arrives, and the size ceiling
    (tests/test_module_size_guard.py) is why this logic lives here and not there.
    """
    from coach import telegram_worker_lambda as worker

    coach_id = order["coach_id"]
    chat_id = order["chat_id"]
    me = bot_username(token)
    speak = who_speaks(
        mentions=order.get("mentions") or [],
        reply_to_bot=order.get("reply_to_bot"),
        my_username=me,
        is_chair=(coach_id == CHAIR_ROUTE),
    )
    if not speak:
        # The silent half of the room is invisible by design — the metric is the
        # only witness that N-1 workers each decided "not me" rather than died.
        worker._emit_metric("TelegramGroupListenerSilent", coach_id)
        return {"ok": True, "reason": "group_listener"}
    worker._emit_metric("TelegramGroupSpeaker", coach_id)

    persona_id, refusal = worker._resolve_persona(coach_id)
    if refusal:
        return refusal
    worker._tg(token, "sendChatAction", {"chat_id": chat_id, "action": "typing"})

    a = worker._assemble(persona_id, coach_id, allow_referral=False)
    thread = room_thread(_room_rows(worker))

    from ai import bedrock_client

    from coach import coach_chat

    result = coach_chat.run_turn(
        coach_id=coach_id,
        persona_id=persona_id,
        coach_name=a["coach_name"],
        persona_block=a["persona"],
        memory_block=a["memory"],
        facts_block=a["facts_block"],
        thread=thread,
        inbound=order.get("text") or "",
        model=worker.MODEL,
        caller=lambda body: bedrock_client.invoke(body),
        # Same arming as the 1:1 path — the room reuses the worker's registered
        # grounder closure, including the just-sent inbound as evidence (#2517).
        grounder=worker._grounder_for(a, order.get("text") or ""),
        tier=worker._current_tier(),
        turns_today=worker._turns_today(thread),
        last_reply_had_emoji=worker._last_reply_had_emoji(thread),
        last_reply_had_em_dash=worker._last_reply_had_em_dash(thread),
        colleagues_block=(a["colleagues"] or "") + ROOM_FRAME,
    )
    if not result.grounded:
        worker._emit_hold(coach_id, worker.HOLD_KIND_REPLY, result.status)

    sent = worker._send_bubbles(token, chat_id, result.bubbles or [result.text], persona_id=persona_id, status=result.status)
    reply_text = "\n\n".join(sent) if sent else result.text

    # The exchange joins the ROOM's shared thread, speaker-stamped. Held turns are
    # stored too, same honesty rule as the 1:1 path.
    try:
        table = worker._table()
        for item in coach_chat.turn_records(ROOM_ID, a["coach_name"], order.get("text") or "", result, cycle=worker._cycle()):
            if item.get("role") == coach_chat.ROLE_COACH:
                item["text"] = reply_text
                item["speaker"] = persona_id
            table.put_item(Item=item)
    except Exception as e:
        logger.warning("[board-room] turn storage failed (reply already sent): %s", e)

    logger.info("[board-room] %s spoke (%s, attempts=%d)", coach_id, result.status, result.attempts)
    return {"ok": True, "status": result.status, "room": ROOM_ID}
