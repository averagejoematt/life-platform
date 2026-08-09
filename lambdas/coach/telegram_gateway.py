"""telegram_gateway.py — the transport decisions for the coach chat (#2364, epic #2363).

Split from the Lambda handler for the same reason ``coach_chat`` is split from it:
the decisions that matter for SAFETY are pure functions here, so they can be tested
and mutation-proved without a webhook, a bot token, or AWS.

Three decisions live in this file, in the order the request meets them:

  1. **Is this actually Telegram?** A FunctionURL is a public, unauthenticated URL.
     Telegram echoes a secret token we register with ``setWebhook`` on every delivery
     (``X-Telegram-Bot-Api-Secret-Token``); anything without it is not Telegram.

  2. **Which coach was texted?** One bot per coach is what makes them separate
     contacts in the address book, so the bot that received the message IS the
     routing key. Resolved from a declared mapping, never guessed from message text.

  3. **Is this Matthew?** The bot username is discoverable — anyone can find it and
     start a chat. Without this check a stranger could interrogate his health data in
     a coach's trusted voice and spend his Bedrock budget doing it. An unknown
     ``chat_id`` is dropped BEFORE inference and answered with nothing revealing.

The ordering is deliberate: the cheapest, least revealing check runs first, and no
path reaches the model before all three pass.
"""

from __future__ import annotations

import hmac
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# The HEADER NAME Telegram echoes the shared secret in — not a secret itself.
TELEGRAM_SECRET_HEADER = "x-telegram-bot-api-secret-token"  # noqa: S105

# What a rejected caller is told. Deliberately incurious: a stranger poking the URL
# learns only that it exists, never whose it is, which coach answers, or why they
# were refused. Telegram itself ignores the body of a 200, so this costs nothing.
_SILENT_OK = {"statusCode": 200, "body": "{}"}


class Rejected(Exception):
    """A request that must not reach inference. Carries a log reason, not a reply."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _lower_headers(headers) -> dict:
    """Header names are case-insensitive over the wire and Lambda does not normalize."""
    return {str(k).lower(): v for k, v in (headers or {}).items()}


def verify_secret(headers, expected: Optional[str]) -> None:
    """Constant-time check of Telegram's echoed secret token.

    ``hmac.compare_digest`` rather than ``==`` because the comparison is against a
    caller-supplied value; the timing signal is small but the cost of removing it is
    zero. A missing EXPECTED secret is a misconfiguration, and it fails CLOSED — an
    unconfigured webhook that accepted everything would be strictly worse than one
    that accepts nothing, because it would look like it was working.
    """
    if not expected:
        raise Rejected("no webhook secret configured — failing closed")
    got = _lower_headers(headers).get(TELEGRAM_SECRET_HEADER) or ""
    if not hmac.compare_digest(str(got), str(expected)):
        raise Rejected("secret token mismatch")


def parse_update(body, is_base64: bool = False) -> dict:
    """Telegram's update JSON -> dict, tolerating base64 and malformed bodies."""
    if is_base64:
        import base64 as _b64

        body = _b64.b64decode(body or "").decode("utf-8", "replace")
    try:
        return json.loads(body or "{}") or {}
    except (ValueError, TypeError) as e:
        raise Rejected(f"unparseable update body: {e}")


def extract_message(update: dict) -> dict:
    """The message we act on, or ``{}``.

    Telegram delivers many update kinds (edits, reactions, joins, callbacks). Only a
    plain new text message starts a coach turn — an edit is deliberately NOT a new
    turn, because re-answering an edited question would produce two contradictory
    replies in the scrollback with no way to tell which is current.
    """
    msg = (update or {}).get("message") or {}
    return msg if msg.get("text") else {}


def resolve_coach(bot_key: str, routing: dict) -> str:
    """Which coach owns this bot. Declared mapping only — never inferred.

    Inferring a coach from message content would mean a stranger (or Matthew's own
    phrasing) could redirect a question to a coach whose persona and fact block were
    never built for it, which is how a nutrition coach ends up citing a single-night
    HRV reading — the #2343 shape exactly.
    """
    coach = (routing or {}).get(bot_key)
    if not coach:
        raise Rejected(f"no coach mapped for bot {bot_key!r}")
    return coach


def authorize_chat(message: dict, allowed_chat_ids) -> int:
    """Only Matthew (and the declared board group) may talk to a coach.

    Returns the chat id on success. Ids are compared as STRINGS: Telegram ids are
    64-bit and arrive as JSON numbers, but they are configured as environment
    strings, and ``123 != "123"`` would silently reject the real owner — a failure
    that looks exactly like a broken bot.
    """
    chat_id = ((message or {}).get("chat") or {}).get("id")
    if chat_id is None:
        raise Rejected("update carries no chat id")
    allowed = {str(a).strip() for a in (allowed_chat_ids or []) if str(a).strip()}
    if not allowed:
        raise Rejected("no authorized chat ids configured — failing closed")
    if str(chat_id) not in allowed:
        raise Rejected(f"unauthorized chat id {str(chat_id)[:4]}…")
    return chat_id


def silent_ok() -> dict:
    """The response to EVERY request, accepted or rejected.

    Always 200, always empty. Two reasons, and both matter:

      * Telegram retries any non-2xx, so a 403 on a stranger's message would make
        Telegram redeliver it on a schedule — turning a rejected request into a
        recurring one.
      * A distinguishable rejection is an oracle. Identical responses mean probing
        the URL reveals nothing about which bots exist or who is authorized.
    """
    return dict(_SILENT_OK)


def route(event: dict, *, secret: Optional[str], routing: dict, allowed_chat_ids, bot_key_of=None) -> dict:
    """Run the three gates. Returns the work order, or raises ``Rejected``.

    The returned dict is deliberately small — coach id, chat id, text — because it is
    what crosses the async invoke boundary to the worker. Nothing about the transport
    travels with it; the worker deals in coaches and messages, not webhooks.
    """
    verify_secret(event.get("headers"), secret)
    update = parse_update(event.get("body"), bool(event.get("isBase64Encoded")))
    message = extract_message(update)
    if not message:
        raise Rejected("no actionable text message in update")

    bot_key = (bot_key_of or _bot_key_from_path)(event)
    coach_id = resolve_coach(bot_key, routing)
    chat_id = authorize_chat(message, allowed_chat_ids)

    return {
        "coach_id": coach_id,
        "chat_id": chat_id,
        "text": message.get("text") or "",
        "message_id": message.get("message_id"),
        "is_group": str(((message.get("chat") or {}).get("type") or "")).endswith("group"),
        # Telegram redelivers pending updates after an outage/late webhook
        # registration — update_id is the dedupe key, date the staleness signal.
        "update_id": update.get("update_id"),
        "message_date": message.get("date"),
    }


# Telegram retries within ~24h; go-live registered the webhook hours after the
# first texts and every backlogged message got a fresh late answer. Older than
# this and a reply reads as a bot waking up, not a person answering.
STALE_AFTER_S = 6 * 3600


def is_stale(message_date, now_ts: float, stale_after_s: int = STALE_AFTER_S) -> bool:
    """True when an inbound message is too old to answer like a live text.

    A missing/garbled timestamp is NOT stale — dropping real messages on a parse
    edge would look exactly like a broken bot, the failure this module exists to
    avoid.
    """
    try:
        age = float(now_ts) - float(message_date)
    except (TypeError, ValueError):
        return False
    return age > stale_after_s


def _bot_key_from_path(event: dict) -> str:
    """The last path segment identifies the bot.

    Each bot's webhook registers a distinct path (``/telegram/<bot_key>``), so the
    URL says which contact was texted without the payload having to. Telegram's
    update body does NOT name the receiving bot, so this is the only honest source —
    reading it from the message would mean trusting the sender to say who they meant.
    """
    raw = event.get("rawPath") or (event.get("requestContext") or {}).get("http", {}).get("path") or ""
    return raw.rstrip("/").rsplit("/", 1)[-1]
