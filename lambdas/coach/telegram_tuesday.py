"""coach/telegram_tuesday.py — the Tuesday question's transport on the coach worker (#4584, epic #4580).

The worker's three Telegram-shaped jobs for the Tuesday question, split out of ``telegram_worker_lambda`` (which sits
under the #1665 size ceiling) the way ``telegram_group`` is: every decision lives in ``content.tuesday_question``; this
file only resolves the worker's own seams (the table, the bot token, the send, the clock, the lead's seat) and calls
it. The worker is imported lazily inside each function, so a test that monkeypatches a worker seam is honoured here.

  * ``handle({"kind": "tuesday_question"})``  — the scheduled send (rule ``TuesdayQuestion``, serve_stack.py).
  * ``handle({"kind": "voice_reply", ...})``  — a voice note quoting the question gets the fixed "type it" answer.
  * ``answer(order)``                         — a text quoting the question is his answer; None for every other text.

No inference anywhere on these paths and no coach voice: the question is the Story Desk's, and every other word sent
is a fixed sentence in ``content.tuesday_question``.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("telegram-worker")

TUESDAY_ANSWER_METRIC = "TuesdayAnswerStored"
VOICE_DROPPED = "voice_dropped"


def handle(event: dict) -> dict:
    """The worker's dispatch for the two ``kind``s this module owns."""
    if event.get("kind") == "voice_reply":
        return _voice_reply(event)
    return _send(event)


def _send(event: dict) -> dict:
    from content import tuesday_question
    from experiment.phase_taxonomy import experiment_stamp_for

    from coach import coach_outbound, telegram_worker_lambda as w
    from coach.persona_registry import LEAD_PERSONA_ID, resolve

    route = (resolve(LEAD_PERSONA_ID, w._s3_client(), w.S3_BUCKET) or {}).get("telegram_route")
    token, chat_id = w._bot_seat(LEAD_PERSONA_ID)
    out = tuesday_question.send_tuesday_question(
        table=w._table(),
        now_pt=w._pacific_now(),
        user_id=os.environ.get("USER_ID", "matthew"),
        seat=(token, chat_id, route),
        quiet=coach_outbound.in_quiet_hours,
        stamp=experiment_stamp_for,
        force=bool(event.get("force")),
    )
    w.logger.info("[tuesday-question] %s", out)
    return out


def _matched(order: dict) -> Optional[dict]:
    """The sent question this order quotes, or None (including when the partition cannot be read — an unreadable
    partition must never swallow a coach message)."""
    from content import tuesday_question

    from coach import telegram_worker_lambda as w

    try:
        rows = tuesday_question.recent_questions(w._table())
    except Exception as e:  # noqa: BLE001
        w.logger.warning("[tuesday-question] partition unreadable (%s) — not an answer", e)
        return None
    return tuesday_question.match_question(
        rows, chat_id=order.get("chat_id"), reply_to_message_id=order.get("reply_to_message_id"), route=order.get("coach_id")
    )


def answer(order: dict) -> Optional[dict]:
    """A 1:1 text that quotes the Tuesday question: stored verbatim, screened, acknowledged in a fixed sentence, and
    never a coach turn. None for every other message (the coach path runs exactly as before)."""
    if order.get("reply_to_message_id") is None or order.get("is_group"):
        return None
    q = _matched(order)
    if q is None:
        return None
    from content import tuesday_question
    from experiment.phase_taxonomy import experiment_stamp_for

    from coach import telegram_worker_lambda as w

    ack = tuesday_question.handle_reply(
        table=w._table(),
        question=q,
        text=order.get("text") or "",
        received_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        message_id=order.get("message_id"),
        stamp=experiment_stamp_for,
    )
    token = w._bot_token(order.get("coach_id"))
    if token:
        w._tg(token, "sendMessage", {"chat_id": order.get("chat_id"), "text": ack})
    w._emit_metric(TUESDAY_ANSWER_METRIC, "tuesday_question")
    return {"ok": True, "reason": "tuesday_answer", "ack": ack}


def _voice_reply(order: dict) -> dict:
    """A voice note quoting the question gets a plain 'type it' answer; any other voice note is dropped, exactly as
    before #4584. Nothing is stored either way — the channel does not transcribe."""
    from content import tuesday_question

    from coach import telegram_worker_lambda as w

    q = _matched(order) if not order.get("is_group") else None
    token = w._bot_token(order.get("coach_id")) if q is not None else None
    if not token:
        return {"ok": True, "reason": VOICE_DROPPED}
    w._tg(token, "sendMessage", {"chat_id": order.get("chat_id"), "text": tuesday_question.ACK_VOICE})
    return {"ok": True, "reason": "voice_not_transcribed"}
