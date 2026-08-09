"""telegram_worker_lambda.py — the async half of the coach chat (#2364, epic #2363).

The webhook Lambda answers Telegram inside its retry window and async-invokes this
worker with a small work order ({coach_id, chat_id, text, message_id}). Everything
slow happens here: the typing indicator, the memory reads, the Bedrock call, the
grounding gate, the reply, the storage.

This module is deliberately an ASSEMBLY of parts that are each already built and
tested elsewhere — the design rule of the whole epic:

  * WHO the coach is        → persona_core.persona_block (the voice specs)
  * WHAT they remember      → the COACH# partition (CHAT# thread, RELATIONSHIP#state)
  * WHAT is true today      → canonical_facts via the computed_metrics record — the
                              SAME record every coach card cites, so the phone and
                              the site cannot tell two truths
  * the turn itself         → coach_chat.run_turn (regenerate-or-hold, budget gates)
  * the grounding closure   → coach_chat_grounding.build_grounder (all five classes)
  * the model               → bedrock_client.invoke (ADR-062's single chokepoint)

The only genuinely new behaviour here is Telegram's sendMessage/sendChatAction —
urllib, per the no-HTTP-libraries rule.
"""

from __future__ import annotations

import logging
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Optional

import boto3

try:
    from common.platform_logger import get_logger

    logger = get_logger("telegram-worker")
except ImportError:  # pragma: no cover
    logger = logging.getLogger("telegram-worker")
    logger.setLevel(logging.INFO)

from coach import coach_chat
from coach.coach_chat_grounding import build_facts_block, build_grounder
from coach.persona_registry import display_name

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
STORE_PATH = os.environ.get("TELEGRAM_SECRET_ID", "life-platform/telegram")
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"

# Narrative register on a personal chat surface — Sonnet, same tier as the coach
# cards (structured tasks take Haiku; a coach texting in their own voice is not a
# structured task).
MODEL = os.environ.get("AI_MODEL", "us.anthropic.claude-sonnet-4-6")

_dynamodb = None
_secrets = None


def _table():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb", region_name=REGION)
    return _dynamodb.Table(TABLE_NAME)


def _bot_token(coach_key: str) -> Optional[str]:
    global _secrets
    if _secrets is None:
        _secrets = boto3.client("secretsmanager", region_name=REGION)
    from common.secret_cache import get_secret_json

    entry = (get_secret_json(STORE_PATH, _secrets) or {}).get(coach_key) or {}
    return entry.get("bot_token")


def _tg(token: str, method: str, payload: dict) -> None:
    """One Telegram Bot API call. Fire-and-log — a failed typing indicator or even a
    failed send must never crash the worker into Lambda retries (which would re-run
    inference and double-charge the budget for one message)."""
    try:
        req = urllib.request.Request(
            TELEGRAM_API.format(token=token, method=method),
            data=urllib.parse.urlencode(payload).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
    except Exception as e:
        logger.warning("[telegram] %s failed: %s", method, e)


# ── Memory + facts assembly ───────────────────────────────────────────────────


def _thread_today(coach_id: str, limit: int = 40) -> list:
    """Today's + yesterday's stored turns, oldest-first — the conversational memory."""
    try:
        resp = _table().query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :pfx)",
            ExpressionAttributeValues={":pk": coach_chat.chat_pk(coach_id), ":pfx": coach_chat.CHAT_SK_PREFIX},
            ScanIndexForward=False,
            Limit=limit,
        )
        items = list(reversed(resp.get("Items") or []))
        return [{"role": i.get("role"), "text": i.get("text")} for i in items]
    except Exception as e:
        logger.warning("[telegram] thread read failed for %s: %s", coach_id, e)
        return []


def _turns_today(thread: list) -> int:
    return len([t for t in thread if t.get("role") == coach_chat.ROLE_MATTHEW])


def _memory_block(coach_id: str) -> str:
    """What this coach knows about Matthew — relationship state + recent memory rows.

    Reads the SAME partition the dossier renders, so the phone conversation and the
    public 'what this coach knows' page cannot diverge. Fail-soft: a coach with an
    unreadable memory chats from persona + facts alone, honestly."""
    pk = coach_chat.chat_pk(coach_id)
    lines = []
    try:
        rel = _table().get_item(Key={"pk": pk, "sk": "RELATIONSHIP#state"}).get("Item") or {}
        phase = rel.get("phase")
        if phase:
            lines.append(f"Your working relationship with Matthew is in the '{phase}' phase.")
    except Exception as e:
        logger.warning("[telegram] relationship read failed: %s", e)
    for prefix, label, cap in (("COMMITMENT#", "Commitments you hold him to", 3), ("LEARNING#", "Things you have learned about him", 3)):
        try:
            resp = _table().query(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :pfx)",
                ExpressionAttributeValues={":pk": pk, ":pfx": prefix},
                ScanIndexForward=False,
                Limit=cap,
            )
            rows = [str(i.get("text") or i.get("commitment") or i.get("learning") or "").strip() for i in resp.get("Items") or []]
            rows = [r for r in rows if r]
            if rows:
                lines.append(f"{label}: " + " · ".join(rows))
        except Exception as e:
            logger.warning("[telegram] %s read failed: %s", prefix, e)
    return ("WHAT YOU REMEMBER ABOUT MATTHEW:\n" + "\n".join(f"- {ln}" for ln in lines)) if lines else ""


def _facts() -> dict:
    """The one authoritative daily fact set — the same computed_metrics record every
    coach card cites, through the SAME extraction (`build_canonical_facts`, which
    carries the #2113 semantics: a pre-genesis record is withheld). The read is the
    analyzer's own idiom — newest computed_metrics row, direct query. Fail-soft: an
    empty dict makes the facts block say 'no numbers to cite' out loud."""
    try:
        from decimal import Decimal

        from experiment import phase_taxonomy
        from experiment.canonical_facts import build_canonical_facts

        pk = "USER#matthew#SOURCE#computed_metrics"
        # #2113: computed_metrics is experiment-scoped — the read FLOORS at the cycle
        # genesis, exactly as the analyzer's _latest_item does, or a pre-genesis record
        # speaks for this cycle ("your recovery came in at 59%" against a cockpit
        # serving 44 — the incident the rider exists for).
        kwargs: dict = {
            "KeyConditionExpression": "pk = :pk",
            "ExpressionAttributeValues": {":pk": pk},
            "ScanIndexForward": False,
            "Limit": 1,
        }
        floor = phase_taxonomy.cycle_read_floor(pk)
        if floor:
            kwargs["KeyConditionExpression"] += " AND sk BETWEEN :lo AND :hi"
            kwargs["ExpressionAttributeValues"][":lo"] = f"DATE#{floor}"
            kwargs["ExpressionAttributeValues"][":hi"] = "DATE#9999-12-31"
        items = _table().query(**kwargs).get("Items") or []
        if not items:
            return {}
        record = {k: (float(v) if isinstance(v, Decimal) else v) for k, v in items[0].items()}
        return build_canonical_facts(record)
    except Exception as e:
        logger.warning("[telegram] facts unavailable: %s", e)
        return {}


def _current_tier() -> Optional[int]:
    try:
        from ai.budget_guard import current_tier

        return current_tier()
    except Exception as e:
        logger.warning("[telegram] tier read failed (proceeding — the hard backstop is bedrock_client): %s", e)
        return None


# ── The handler ───────────────────────────────────────────────────────────────


def lambda_handler(event, context):  # noqa: ARG001 — Lambda signature
    """One work order in, one Telegram reply out (or one honest refusal)."""
    order = event or {}
    coach_id = order.get("coach_id")
    chat_id = order.get("chat_id")
    text = order.get("text") or ""
    if not coach_id or chat_id is None or not text.strip():
        logger.warning("[telegram] malformed work order: %s", {k: order.get(k) for k in ("coach_id", "chat_id")})
        return {"ok": False, "reason": "malformed order"}

    token = _bot_token(coach_id)
    if not token:
        logger.warning("[telegram] no bot token for %s — dropping", coach_id)
        return {"ok": False, "reason": "no token"}

    _tg(token, "sendChatAction", {"chat_id": chat_id, "action": "typing"})

    coach_name = display_name(f"{coach_chat.normalize_coach_id(coach_id)}_coach") or coach_id
    thread = _thread_today(coach_id)
    facts = _facts()
    memory = _memory_block(coach_id)

    try:
        from coach.persona_core import persona_block

        persona = persona_block(f"{coach_chat.normalize_coach_id(coach_id)}_coach")
    except Exception as e:
        logger.warning("[telegram] persona load failed: %s", e)
        persona = ""

    from ai import bedrock_client

    result = coach_chat.run_turn(
        coach_id=coach_id,
        coach_name=coach_name,
        persona_block=persona,
        memory_block=memory,
        facts_block=build_facts_block(facts),
        thread=thread,
        inbound=text,
        model=MODEL,
        caller=lambda body: bedrock_client.invoke(body),
        # All five gate classes armed; the memory block and thread text widen the
        # NUMBER vocabulary (quoting memory is not fabrication) while the night map
        # stays facts-only — #2343's class is checked even on remembered figures.
        grounder=build_grounder(facts, extra_sources=(memory, " ".join(t.get("text") or "" for t in thread))),
        tier=_current_tier(),
        turns_today=_turns_today(thread),
    )

    _tg(token, "sendMessage", {"chat_id": chat_id, "text": result.text})

    # The exchange joins the coach's real memory — including a held turn, with its
    # findings, so a later reader sees the coach declined and why, not a gap.
    try:
        cycle = None
        try:
            ssm = boto3.client("ssm", region_name=REGION)
            cycle = int(ssm.get_parameter(Name="/life-platform/experiment-cycle")["Parameter"]["Value"])
        except Exception:
            pass
        table = _table()
        for item in coach_chat.turn_records(coach_id, coach_name, text, result, cycle=cycle):
            table.put_item(Item=item)
    except Exception as e:
        logger.warning("[telegram] turn storage failed (reply already sent): %s", e)

    logger.info("[telegram] %s turn %s (attempts=%d findings=%d)", coach_id, result.status, result.attempts, len(result.findings))
    return {"ok": True, "status": result.status}


def _now_iso() -> str:  # pragma: no cover — debugging aid
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Alias kept for callers/tests that used the short name pre-I3 rename.
handler = lambda_handler
