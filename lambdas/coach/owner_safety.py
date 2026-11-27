"""owner_safety.py — the safety gate on the owner's own Telegram coaches (#6303, epic #6284).

The public reader doors have run ``ai.safety_contract`` since #3050. The owner's own channel
had nothing: a first-person statement of self-harm intent texted to a coach went straight to a
model turn and came back as coaching, or as an emoji reaction. This module is the transport
half of the owner-channel policy; the policy itself (which classes, the fixed copy, the
boundary lines) is ``safety_contract.owner_channel_check`` so there is ONE classifier and ONE
place for the copy.

WHAT HAPPENS ON A HIT (self_harm, acute_symptom)
  * the fixed owner reply is sent INSTEAD of a model call, and no coaching follows that turn;
  * one event row is written to the addressed coach's own chat partition: class and timestamp,
    no message text (``event_row``). His message is NOT stored as a chat turn either, so it
    never reaches a later coach prompt or the daily chat summary;
  * after self_harm only, the day's unsolicited outbound budget is closed
    (``coach_outbound.hold_day``): no check-in, event ping or referral later that day;
  * one CloudWatch count (``METRIC_FIXED``). No alarm reads it, nothing emails, nothing
    notifies a person. The reply itself says the chat does not monitor him, and the platform
    must not behave as if it did.

THE GATE FAILS SAFE — ON PURPOSE, AND THE OPPOSITE OF THE PUBLIC DOOR
The public door fails closed: a stranger who gets one unhelpful-but-safe answer has lost
nothing. Here a classifier bug that failed closed would silence every coach he texts, on the
channel that is the product, for as long as the bug lived. So an exception in the classifier
lets the turn proceed exactly as it did before this gate existed, and is logged and counted
(``METRIC_ERROR``) so the failure is visible rather than silent. ``safety_contract`` has no I/O
and nothing that should raise; the guard is for the bug nobody has written yet.

LIMITS (stated, not glossed): English only, first person, input only, and it misses euphemism
and understatement — the classifier's own docstring. It reads one message, not a conversation.
It is a floor, not a monitor.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from ai import safety_contract

from coach import coach_chat, coach_outbound

try:  # the worker's own logger: a handler of its own at INFO, so these lines reach CloudWatch (#3283 / #5106)
    from common.platform_logger import get_logger

    logger: logging.Logger = get_logger("telegram-worker")
except ImportError:  # pragma: no cover
    logger = logging.getLogger("telegram-worker")
    logger.setLevel(logging.INFO)

# The event row's role. Every chat reader filters to ROLE_MATTHEW/ROLE_COACH (the worker's
# thread, the daily summary, open loops, the context pilot), so this row is invisible to every
# prompt by construction and visible to a count.
SAFETY_EVENT_ROLE = "safety_event"
SAFETY_EVENT_RECORD_TYPE = "owner_safety_event"
STATUS_SAFETY_REPLY = "safety_reply"

METRIC_FIXED = "TelegramSafetyReply"
METRIC_ERROR = "TelegramSafetyGateError"

# The verdict a turn proceeds on when the classifier itself failed: no hazard, no boundary.
PROCEED = safety_contract.OwnerVerdict(None, "", "", frozenset())


def screen(text: str, *, on_error: Optional[Callable[[], None]] = None) -> safety_contract.OwnerVerdict:
    """The owner-channel verdict for one inbound message. Fails SAFE (see module doc)."""
    try:
        return safety_contract.owner_channel_check(text)
    except Exception as e:  # noqa: BLE001 — any classifier bug must not silence his coach
        logger.error("[owner-safety] classifier failed (turn proceeds ungated): %s", type(e).__name__)
        if on_error is not None:
            try:
                on_error()
            except Exception:  # noqa: BLE001 — the metric is a witness, never a blocker
                pass
        return PROCEED


def event_row(partition_id: str, hazard: str, *, date_pt: str, stamp: Optional[str] = None) -> dict:
    """The one stored trace of a fixed reply: which class, when, on which coach. NEVER text."""
    return {
        "pk": coach_chat.chat_pk(partition_id),
        "sk": coach_chat.new_chat_sk(date_pt),
        "role": SAFETY_EVENT_ROLE,
        "record_type": SAFETY_EVENT_RECORD_TYPE,
        "hazard": hazard,
        "provenance": coach_chat.PROVENANCE,
        "created_at": stamp or coach_chat.now_iso(),
    }


def answer(
    verdict: safety_contract.OwnerVerdict,
    *,
    send: Callable[[str], bool],
    table: Callable[[], Any],
    partition_id: str,
    date_pt: str,
    emit: Callable[[str], None],
) -> dict:
    """Send the fixed reply, then record it. Each step after the send is fail-soft.

    The send goes FIRST: if storage, the hold or the metric fails, he has still had the reply.
    ``table`` is a factory so that even constructing the client cannot cost him the reply.
    """
    hazard = verdict.hazard or ""
    sent = False
    try:
        sent = bool(send(verdict.reply))
    except Exception as e:  # noqa: BLE001
        logger.error("[owner-safety] fixed reply send failed: %s", type(e).__name__)
    try:
        t = table()
        t.put_item(Item=event_row(partition_id, hazard, date_pt=date_pt))
        if hazard == safety_contract.SELF_HARM:
            coach_outbound.hold_day(t, date_pt)
    except Exception as e:  # noqa: BLE001
        logger.warning("[owner-safety] event record failed (reply %s): %s", "sent" if sent else "not sent", type(e).__name__)
    try:
        emit(METRIC_FIXED)
    except Exception:  # noqa: BLE001
        pass
    # Class only: the log line must never carry what he wrote.
    logger.info("[owner-safety] fixed reply (%s) sent=%s", hazard, sent)
    return {"ok": True, "status": STATUS_SAFETY_REPLY, "hazard": hazard, "sent": sent}


def gate_direct(order: dict, token: str) -> Optional[dict]:
    """The 1:1 worker's gate: the handler's return value on a hit, else None (the turn proceeds).

    A group order passes straight through: the room gates inside ``telegram_group.group_turn``,
    after it has decided which ONE bot answers. The boundary line for a proceeding turn is not
    returned here — ``coach_chat.run_turn`` derives it from the same inbound text. Imports the
    worker lazily, the way the room does, because the worker sits at the module-size ceiling.
    """
    if order.get("is_group"):
        return None
    from coach import telegram_worker_lambda as worker

    coach_id, chat_id = order.get("coach_id") or "", order.get("chat_id")
    verdict = screen(order.get("text") or "", on_error=lambda: worker._emit_metric(METRIC_ERROR, coach_id))
    if not verdict.hazard:
        return None
    return answer(
        verdict,
        send=lambda reply: worker._send_text(token, chat_id, reply),
        table=worker._table,
        partition_id=worker._partition_id(coach_id),
        date_pt=worker._pacific_now().strftime("%Y-%m-%d"),
        emit=lambda name: worker._emit_metric(name, coach_id),
    )
