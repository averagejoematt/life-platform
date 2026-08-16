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
    "headcoach": "headcoach",  # Dr. Eli Marsh — the lead's own line (v2 roster)
    "nutrition": "nutrition",
    "sleep": "sleep",
    "mind": "mind",
    "physical": "physical",
    "explorer": "explorer",
    "pattern": "pattern",  # Dr. Nora Vale (chat tier, v2 roster)
    "career": "career",  # Steve Brooks (chat tier, v2 roster)
    "board": "board",
    "glucose": "glucose",  # deliberately uncreated bot, addable later — see ROUTE_GAPS
    "labs": "labs",  # Dr. Okafor — granted a bot by ADR-153's 2026-08-12 amendment
}

# #2677: "training" WAS a key here and is deliberately gone.
#
# ADR-153's 2026-08-12 amendment reversed its own 2026-08-10 one: the `training`
# succession alias retired, `@ajm_training_bot` became the Performance seat's PRIMARY
# route (key `physical`), and the ADR states the consequence in as many words —
# "`training` is now deliberately unmapped and fails CLOSED in gateway.resolve_coach,
# which is correct: there is no separate training seat."
#
# That amendment updated the ADR, `config/personas.json` and the setup roster's own
# comment. It left three artifacts behind: this key, the comment above it that still
# described the reversed 08-10 decision, and a test asserting the old behaviour. So the
# key kept resolving to a coach id no persona claims, and `resolve_coach` — the gate the
# ADR names — never got the chance to fail closed.
#
# Deletion, not a re-added alias. The alias was retired for a load-bearing reason: the
# PRIMARY `telegram_route` is the canonical OUTBOUND route, so a seat reachable only by
# alias can be texted but can never text first, and Max's morning check-ins would have
# stayed dark. Making the key "work" by restoring the alias would silently undo that.
#
# What remains unresolvable is declared below rather than deleted, because deleting it
# would break something real. `tests/test_telegram_route_provisioning_2677.py` requires
# every ROUTING key to resolve to a persona or appear here with a reason, so the next
# dead route is loud on the day it lands instead of found in a bug bash.
# #2719 RESOLVED (owner decision, 2026-08-16): `board` left this registry — Grand
# Rounds is CHAIRED BY THE LEAD. eli_marsh claims the route via
# telegram_route_aliases, the sanctioned mechanism (a board message lands in his
# one thread, the same deliberate merge the `training` → physical succession
# made); the true multi-coach room remains epic #2363's slice to build. The
# nameless-fallback class the gap documented is separately closed: the worker
# refuses absent persona ids outright (TelegramUnmappedRouteRefused, #2677/#2719).
ROUTE_GAPS = {
    "glucose": (
        "NO PERSONA ROUTE, NO BOT — and the key must stay. setup_telegram_bots.OPTIONAL_BOTS lists "
        "@ajm_glucose_bot as deliberately NOT created ('an unused bot is a live public webhook endpoint, so "
        "it is attack surface bought for no benefit') while remaining addable with an explicit argument, and "
        "tests/test_telegram_transport.py requires every roster key to be routable. The gap worth naming is "
        "that creating the bot would NOT be enough: glucose_coach has no telegram_route, so the day the bot "
        "exists a message would resolve no persona and be REFUSED (TelegramUnmappedRouteRefused — the "
        "nameless-coach class #2719 closed). Grant the route in the same change that creates the bot."
    ),
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


def lambda_handler(event: dict, context: object) -> dict:  # noqa: ARG001 — Lambda signature
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
