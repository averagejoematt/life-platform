"""telegram_webhook_lambda.py — the public front door of the coach chat (#2364).

FunctionURL, unauthenticated at the AWS layer (like hevy-webhook was) — every real
gate lives in ``coach.telegram_gateway``, which this handler only *wires*:

  1. secret-token check (constant-time, fails closed when unconfigured),
  2. bot-path → coach resolution (declared map, never inferred from content),
  3. chat-id authorization (Matthew + the board group, fails closed).

The handler's own contract is SPEED and SILENCE: answer 200 inside Telegram's
retry window (a non-2xx makes Telegram redeliver the message on a schedule) and
answer identically for accepted and rejected requests (a distinguishable
rejection is an oracle — probing the URL must reveal nothing about which bots
exist or who is authorized). Inference, memory reads and the reply all happen in
the async worker; nothing slow runs here.
"""

from __future__ import annotations

import json
import logging
import os

import boto3

try:
    from common.platform_logger import get_logger

    logger = get_logger("telegram-webhook")
except ImportError:  # pragma: no cover
    logger = logging.getLogger("telegram-webhook")
    logger.setLevel(logging.INFO)

from coach import telegram_gateway as gateway

REGION = os.environ.get("AWS_REGION", "us-west-2")
STORE_PATH = os.environ.get("TELEGRAM_SECRET_ID", "life-platform/telegram")
WORKER_FUNCTION = os.environ.get("TELEGRAM_WORKER_FUNCTION", "telegram-coach-worker")

# bot path key -> platform coach id. DECLARED, never inferred: content-based
# routing would let phrasing redirect a question to a persona whose fact block was
# never built for it — the #2343 shape. Keys match setup_telegram_bots.py's roster.
ROUTING = {
    "nutrition": "nutrition",
    "training": "training",
    "sleep": "sleep",
    "mind": "mind",
    "physical": "physical",
    "explorer": "explorer",
    "board": "board",
    "glucose": "glucose",  # optional bots: routable the day they are created
    "labs": "labs",
}

_secrets = None
_lambda = None


def _store() -> dict:
    global _secrets
    if _secrets is None:
        _secrets = boto3.client("secretsmanager", region_name=REGION)
    from common.secret_cache import get_secret_json

    try:
        return get_secret_json(STORE_PATH, _secrets) or {}
    except Exception as e:
        logger.warning("[webhook] secret store unreadable — failing closed: %s", e)
        return {}


def _webhook_secret(store: dict) -> str:
    """The one token Telegram echoes on every delivery (set via setWebhook).

    Stored at the top level of the telegram secret; absent ⇒ empty ⇒ the gateway
    fails CLOSED, which is the correct posture for an unconfigured webhook.
    """
    return str(store.get("webhook_secret") or "")


def _allowed_chat_ids(store: dict) -> list:
    """The union of every configured bot's chat ids + the board group.

    Union rather than per-bot: every id in the store is Matthew (or his board
    group) by construction — the setup script discovers them from HIS messages —
    and a per-bot list would make the first message to a NEW bot unroutable until
    a re-run, a failure that looks exactly like a broken bot.
    """
    ids: list = []
    for key, entry in store.items():
        if isinstance(entry, dict):
            ids.extend(entry.get("chat_ids") or [])
    return ids


def lambda_handler(event, context):  # noqa: ARG001 — Lambda signature
    store = _store()
    try:
        order = gateway.route(
            event,
            secret=_webhook_secret(store),
            routing=ROUTING,
            allowed_chat_ids=_allowed_chat_ids(store),
        )
    except gateway.Rejected as r:
        # The reason goes to the log only. The caller sees the same 200 {} as a
        # success — Telegram retries non-2xx, and a distinguishable rejection is
        # an oracle for whoever is probing the URL.
        logger.warning("[webhook] rejected: %s", r.reason)
        return gateway.silent_ok()
    except Exception as e:  # a malformed event must not 500 into Telegram retries
        logger.warning("[webhook] error treated as rejection: %s", e)
        return gateway.silent_ok()

    global _lambda
    if _lambda is None:
        _lambda = boto3.client("lambda", region_name=REGION)
    try:
        _lambda.invoke(
            FunctionName=WORKER_FUNCTION,
            InvocationType="Event",  # async — the reply happens off the webhook path
            Payload=json.dumps(order).encode(),
        )
    except Exception as e:
        logger.error("[webhook] worker invoke failed — message dropped: %s", e)

    return gateway.silent_ok()


# Alias kept for callers/tests that used the short name pre-I3 rename.
handler = lambda_handler
