"""protein_nudge_runner.py — the IO around `health.protein_engine.nudge_decide` (#5098): the read, the claim, the send.

`coach_nudge_lambda.lambda_handler` (the hourly :10 UTC tick) runs `run(...)` as a pass beside the coach nudge and the
steps nudge (#5056) — its own ledger row (`COACH#protein_nudge` / `PROTEIN_NUDGE#<date>`), so a protein note never
spends the coach's one-a-day slot. No new EventBridge rule: the hourly cron covers the charter's breakfast window
(`nutrition.protein.breakfast_nudge`) in both PDT and PST. Owner-only email; deterministic, no model.

DEAD-MAN: every in-window tick (sent or not) overwrites `COACH#protein_nudge` / `EVAL#<date>` with its verdict;
`nudge_ledger_qa.check_protein_nudge_liveness` reds when a recent day has no eval row (the pass never ran).

THE EVENING PASS (`run_evening`, #5793): the same ledger row, a distinct slot (`PROTEIN_NUDGE#<date>#evening`, the
engine's `evening_key`), stamped on every in-window tick as `EVAL_EVENING#<date>` (outside the breakfast dead-man's
`EVAL#` range, so neither pass can feed the other's liveness). The evening Pacific day spans two UTC apple_health rows
(after 17:00 PDT / 16:00 PST the entries land on the next UTC date), so the HAE read merges both; the engine keeps
only the entries whose own Pacific date is the day.
"""

from __future__ import annotations

import logging
from datetime import date as _date, datetime, timedelta
from typing import Callable

from common.numeric import floats_to_decimal
from common.pacific_time import PACIFIC
from health import protein_engine
from ingestion import health_auto_export_protein as hae_protein

logger = logging.getLogger()

LEDGER_PK = "COACH#protein_nudge"
EVAL_PREFIX = "EVAL#"
EVENING_EVAL_PREFIX = "EVAL_EVENING#"
CHANNEL = "email"


def _today_row(table, date: str, user: str) -> dict | None:
    item = table.get_item(Key={"pk": f"USER#{user}#SOURCE#macrofactor", "sk": f"DATE#{date}"}).get("Item")
    return None if not item or item.get("tombstone") else item


def _hae_entries(table, utc_date: str, user: str) -> dict:
    item = table.get_item(
        Key={"pk": f"USER#{user}#SOURCE#apple_health", "sk": f"DATE#{utc_date}"},
        ProjectionExpression="#rd",
        ExpressionAttributeNames={"#rd": hae_protein.RD_FIELD},
    ).get("Item")
    return dict((item or {}).get(hae_protein.RD_FIELD) or {})


def _hae_row(table, date: str, user: str) -> dict | None:
    """The same-day path (#5187): the timed protein entries Health Auto Export delivers intraday, as a food-log row.
    The apple_health row is the UTC day; a Pacific morning is the same date, and the engine filters on each entry's own
    Pacific date."""
    return protein_engine.hae_feeding_rows(_hae_entries(table, date, user), date)


def _hae_evening_row(table, date: str, user: str) -> dict | None:
    """The whole Pacific day's HAE entries: its own UTC row plus the next one (a Pacific evening is past UTC midnight).
    Entries are keyed by their UTC minute, so the two maps never collide; the engine filters on each one's Pacific date."""
    nxt = (_date.fromisoformat(date) + timedelta(days=1)).isoformat()
    return protein_engine.hae_feeding_rows({**_hae_entries(table, date, user), **_hae_entries(table, nxt, user)}, date)


def _read_row(table, date: str, user: str) -> dict | None:
    """The end-of-day MacroFactor row when it exists (the fuller record), else the intraday HAE entries."""
    return _today_row(table, date, user) or _hae_row(table, date, user)


def _claim(table, date: str, verdict: dict, now_utc: datetime, key: str | None = None) -> bool:
    """Conditional put of `PROTEIN_NUDGE#<date>` (or the evening slot's `key`) BEFORE the send — one attempt per
    Pacific day and slot across racing ticks."""
    try:
        table.put_item(
            Item=floats_to_decimal(
                {
                    "pk": LEDGER_PK,
                    "sk": key or protein_engine.idempotency_key(date),
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


def _settle(table, date: str, status: str, text: str = "", error: str = "", key: str | None = None) -> None:
    table.update_item(
        Key={"pk": LEDGER_PK, "sk": key or protein_engine.idempotency_key(date)},
        UpdateExpression="SET #s = :s, #t = :t, #e = :e",
        ExpressionAttributeNames={"#s": "status", "#t": "text", "#e": "error"},
        ExpressionAttributeValues={":s": status, ":t": text, ":e": error[:300]},
    )


def _stamp_eval(table, date: str, verdict: dict, now_utc: datetime, prefix: str = EVAL_PREFIX) -> None:
    try:
        table.put_item(
            Item={
                "pk": LEDGER_PK,
                "sk": f"{prefix}{date}",
                "reason": str(verdict.get("reason")),
                "send": bool(verdict.get("send")),
                "evaluated_at": now_utc.isoformat(),
                "version": str(verdict.get("version") or protein_engine.NUDGE_VERSION),
                "source": str(verdict.get("source") or "none"),
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
            date=date, now_pt=now_pt, row=None if sent else _read_row(table, date, user), already_sent=sent, budget_tier=budget_tier
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


def run_evening(
    table, send: Callable[[str], None], now_utc: datetime, budget_tier: int, *, user: str = "matthew", dry_run: bool = False
) -> dict:
    """One evening-nudge pass (#5793). `send(text)` delivers the owner email. Never raises into the coach nudge's tick.
    Logs carry reasons only, never a gram figure (the floor and the intake are owner-only numbers)."""
    now_pt = now_utc.astimezone(PACIFIC)
    date = now_pt.date().isoformat()
    if not protein_engine.in_evening_window(now_pt):
        return {"send": False, "reason": "outside_window"}
    key = protein_engine.evening_key(date)
    try:
        sent = bool(table.get_item(Key={"pk": LEDGER_PK, "sk": key}).get("Item"))
        row = None if sent else (_today_row(table, date, user) or _hae_evening_row(table, date, user))
        verdict = protein_engine.evening_decide(date=date, now_pt=now_pt, row=row, already_sent=sent, budget_tier=budget_tier)
    except Exception as e:  # noqa: BLE001
        logger.error("[protein-evening] evaluation failed: %s", type(e).__name__)
        return {"send": False, "reason": f"error:{type(e).__name__}"}
    _stamp_eval(table, date, verdict, now_utc, prefix=EVENING_EVAL_PREFIX)
    if not verdict["send"]:
        return {"send": False, "reason": verdict["reason"]}
    if not _claim(table, date, verdict, now_utc, key=key):
        return {"send": False, "reason": "already_sent"}
    try:
        send(verdict["text"])
    except Exception as e:  # noqa: BLE001
        logger.error("[protein-evening] send failed: %s", type(e).__name__)
        _settle(table, date, "failed", error=str(e), key=key)
        return {"send": False, "reason": "send_failed"}
    _settle(table, date, "dry_run" if dry_run else "sent", text=verdict["text"], key=key)
    return {"send": True, "reason": verdict["reason"], "key": key}
