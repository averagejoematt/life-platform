"""protein_nudge_runner.py — the IO around `health.protein_engine.nudge_decide` (#5098): the read, the claim, the send.

`coach_nudge_lambda.lambda_handler` (the hourly :10 UTC tick) runs `run(...)` as a pass beside the coach nudge and the
steps nudge (#5056) — its own ledger row (`COACH#protein_nudge` / `PROTEIN_NUDGE#<date>`), so a protein note never
spends the coach's one-a-day slot. No new EventBridge rule: the hourly cron covers the charter's breakfast window
(`nutrition.protein.breakfast_nudge`) in both PDT and PST. Owner-only email; deterministic, no model.

DEAD-MAN: every in-window tick (sent or not) overwrites `COACH#protein_nudge` / `EVAL#<date>` with its verdict;
`nudge_ledger_qa.check_protein_nudge_liveness` reds when a recent day has no eval row (the pass never ran).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

from common.numeric import floats_to_decimal
from common.pacific_time import PACIFIC
from health import protein_engine

logger = logging.getLogger()

LEDGER_PK = "COACH#protein_nudge"
EVAL_PREFIX = "EVAL#"
CHANNEL = "email"


def _today_row(table, date: str, user: str) -> dict | None:
    item = table.get_item(Key={"pk": f"USER#{user}#SOURCE#macrofactor", "sk": f"DATE#{date}"}).get("Item")
    return None if not item or item.get("tombstone") else item


def _claim(table, date: str, verdict: dict, now_utc: datetime) -> bool:
    """Conditional put of `PROTEIN_NUDGE#<date>` BEFORE the send — one attempt per Pacific day across racing ticks."""
    try:
        table.put_item(
            Item=floats_to_decimal(
                {
                    "pk": LEDGER_PK,
                    "sk": protein_engine.idempotency_key(date),
                    "status": "attempting",
                    "channel": CHANNEL,
                    "attempted_at": now_utc.isoformat(),
                    "reason": verdict.get("reason"),
                    "by": verdict.get("by"),
                    "charter_version": verdict.get("charter_version"),
                }
            ),
            ConditionExpression="attribute_not_exists(pk)",
        )
        return True
    except Exception as e:  # noqa: BLE001 — ConditionalCheckFailed = already claimed today
        if "ConditionalCheckFailed" not in type(e).__name__ and "ConditionalCheckFailed" not in str(e):
            logger.warning("[protein-nudge] claim failed (%s) — standing down", e)
        return False


def _settle(table, date: str, status: str, text: str = "", error: str = "") -> None:
    table.update_item(
        Key={"pk": LEDGER_PK, "sk": protein_engine.idempotency_key(date)},
        UpdateExpression="SET #s = :s, #t = :t, #e = :e",
        ExpressionAttributeNames={"#s": "status", "#t": "text", "#e": "error"},
        ExpressionAttributeValues={":s": status, ":t": text, ":e": error[:300]},
    )


def _stamp_eval(table, date: str, verdict: dict, now_utc: datetime) -> None:
    try:
        table.put_item(
            Item={
                "pk": LEDGER_PK,
                "sk": f"{EVAL_PREFIX}{date}",
                "reason": str(verdict.get("reason")),
                "send": bool(verdict.get("send")),
                "evaluated_at": now_utc.isoformat(),
                "version": protein_engine.NUDGE_VERSION,
            }
        )
    except Exception as e:  # noqa: BLE001 — the stamp is the dead-man's food; never block the pass
        logger.warning("[protein-nudge] eval stamp failed: %s", e)


def run(table, send: Callable[[str], None], now_utc: datetime, budget_tier: int, *, user: str = "matthew", dry_run: bool = False) -> dict:
    """One breakfast-nudge pass. `send(text)` delivers the owner email. Never raises into the coach nudge's tick."""
    now_pt = now_utc.astimezone(PACIFIC)
    date = now_pt.date().isoformat()
    if not protein_engine.in_window(now_pt):
        return {"send": False, "reason": "outside_window"}
    try:
        sent = bool(table.get_item(Key={"pk": LEDGER_PK, "sk": protein_engine.idempotency_key(date)}).get("Item"))
        verdict = protein_engine.nudge_decide(
            date=date, now_pt=now_pt, row=None if sent else _today_row(table, date, user), already_sent=sent, budget_tier=budget_tier
        )
    except Exception as e:  # noqa: BLE001
        logger.error("[protein-nudge] evaluation failed: %s", e)
        return {"send": False, "reason": f"error:{type(e).__name__}"}
    _stamp_eval(table, date, verdict, now_utc)
    if not verdict["send"]:
        return {"send": False, "reason": verdict["reason"]}
    if not _claim(table, date, verdict, now_utc):
        return {"send": False, "reason": "already_sent"}
    try:
        send(verdict["text"])
    except Exception as e:  # noqa: BLE001
        logger.error("[protein-nudge] send failed: %s", e)
        _settle(table, date, "failed", error=str(e))
        return {"send": False, "reason": "send_failed"}
    _settle(table, date, "dry_run" if dry_run else "sent", text=verdict["text"])
    return {"send": True, "reason": verdict["reason"], "key": verdict["key"]}
