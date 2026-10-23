"""steps_nudge_runner.py — the IO around `training.steps_nudge` (#5056): reads, the idempotent claim, the owner email.

Two callers, both owner-only:
  * `coach_nudge_lambda.lambda_handler` (the hourly :10 UTC tick) runs `run(...)` as a SECOND pass beside the coach
    nudge — its own ledger row (`COACH#steps_nudge` / `STEPS_NUDGE#<date>`), so a steps nudge never spends the coach's
    one-a-day slot, and the coach's day never blocks the walk. No new EventBridge rule: the existing hourly cron already
    covers 19:00-20:00 PT in both PDT and PST (see `steps_nudge.WINDOW_*`).
  * `daily_brief_lambda` reads `brief_line(...)` — the day's steps floor/target line.

DEAD-MAN: every in-window tick (sent or not) overwrites `COACH#steps_nudge` / `EVAL#<date>` with its verdict;
`nudge_ledger_qa.check_steps_nudge_liveness` reds when a recent day has no eval row (the pass never ran).

The ramp is computed WITHOUT the lift-note strain flags (those are an MCP-side read of performed-lift evidence); it
still sees the standing constraints and the owner's DELOAD# word. A lower-leg strain hold the ramp cannot see can only
mean the note names a target above the held level — the copy says it is skippable and states the numbers.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Optional

from boto3.dynamodb.conditions import Key
from common.numeric import floats_to_decimal
from common.pacific_time import PACIFIC, parse_iso_utc
from common.strava_read_seam import strava_read_seam
from training import deload_word, steps_nudge, steps_ramp, steps_resolver

logger = logging.getLogger()

LEDGER_PK = "COACH#steps_nudge"
EVAL_PREFIX = "EVAL#"
CHANNEL = "email"
AS_OF_FIELDS = ("ingested_at", "fetched_at", "webhook_ingested_at")  # the writers' own stamps, in precedence order


def _pk(source: str, user: str) -> str:
    return f"USER#{user}#SOURCE#{source}"


def make_fetch(table, user: str = "matthew") -> Callable[[str, str, str], list]:
    """`steps_resolver` FetchFn over one DDB table: the day rows of `source` in [start, end], tombstones dropped."""

    def fetch(source: str, start: str, end: str) -> list:
        items: list = []
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": Key("pk").eq(_pk(source, user)) & Key("sk").between(f"DATE#{start}", f"DATE#{end}~")
        }
        while True:
            resp = table.query(**kwargs)
            items.extend(i for i in resp.get("Items", []) if not i.get("tombstone"))
            if "LastEvaluatedKey" not in resp:
                return strava_read_seam(source, items)  # #4419: a no-op for every non-strava steps source
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    return fetch


def _deload_records(table) -> list:
    try:
        resp = table.query(KeyConditionExpression=Key("pk").eq(deload_word.DELOAD_PK) & Key("sk").begins_with(deload_word.DELOAD_SK_PREFIX))
        return list(resp.get("Items", []))
    except Exception as e:  # noqa: BLE001 — fail-soft: no recorded word means no hold from it
        logger.warning("[steps-nudge] deload read failed: %s", e)
        return []


def read_ramp(table, date: str, user: str = "matthew") -> dict[str, Any]:
    window = steps_resolver.steps_range(*steps_ramp.window_days(date), fetch=make_fetch(table, user), derived=False)
    return steps_ramp.compute(date, window, deload_records=_deload_records(table))


def brief_line(table, date: str) -> Optional[str]:
    """The morning brief's steps line (fail-soft: None when the ramp does not read)."""
    try:
        return steps_nudge.target_line(read_ramp(table, date))
    except Exception as e:  # noqa: BLE001
        logger.warning("[steps-nudge] brief line failed (non-fatal): %s", e)
        return None


def _first_session_pt(hevy_rows: list) -> Optional[datetime]:
    parsed = [parse_iso_utc(str(w.get("start_time"))) for w in hevy_rows if w.get("start_time")]
    starts: list[datetime] = [s for s in parsed if s is not None]
    return min(starts).astimezone(PACIFIC) if starts else None


def _steps_as_of_pt(date: str, resolution: dict, fetch) -> Optional[datetime]:
    """When the winning steps row was written (`ingested_at`, else a sibling stamp), Pacific; None when unknown."""
    winner = resolution.get("winner")
    if not winner:
        return None
    rows = steps_resolver._day_rows(fetch(winner, date, date)).get(date, [])
    row = steps_resolver._measured_day_row(rows) or {}
    for field in AS_OF_FIELDS:
        parsed = parse_iso_utc(str(row[field])) if row.get(field) else None
        if parsed is not None:
            return parsed.astimezone(PACIFIC)
    return None


def _claim(table, date: str, verdict: dict, now_utc: datetime) -> bool:
    """Conditional put of `STEPS_NUDGE#<date>` BEFORE the send — one attempt per Pacific day across racing ticks."""
    try:
        table.put_item(
            Item=floats_to_decimal(
                {
                    "pk": LEDGER_PK,
                    "sk": steps_nudge.idempotency_key(date),
                    "status": "attempting",
                    "channel": CHANNEL,
                    "attempted_at": now_utc.isoformat(),
                    "today_target": verdict.get("today_target"),
                    "effective_steps": verdict.get("effective_steps"),
                    "pace": verdict.get("pace"),
                    "charter_version": verdict.get("charter_version"),
                }
            ),
            ConditionExpression="attribute_not_exists(pk)",
        )
        return True
    except Exception as e:  # noqa: BLE001 — ConditionalCheckFailed = already claimed today
        if "ConditionalCheckFailed" not in type(e).__name__ and "ConditionalCheckFailed" not in str(e):
            logger.warning("[steps-nudge] claim failed (%s) — standing down", e)
        return False


def _settle(table, date: str, status: str, text: str = "", error: str = "") -> None:
    table.update_item(
        Key={"pk": LEDGER_PK, "sk": steps_nudge.idempotency_key(date)},
        UpdateExpression="SET #s = :s, #t = :t, #e = :e",
        ExpressionAttributeNames={"#s": "status", "#t": "text", "#e": "error"},
        ExpressionAttributeValues={":s": status, ":t": text, ":e": error[:300]},
    )


def _stamp_eval(table, date: str, verdict: dict, now_utc: datetime) -> None:
    try:
        table.put_item(
            Item=floats_to_decimal(
                {
                    "pk": LEDGER_PK,
                    "sk": f"{EVAL_PREFIX}{date}",
                    "reason": verdict.get("reason"),
                    "send": bool(verdict.get("send")),
                    "evaluated_at": now_utc.isoformat(),
                    "version": steps_nudge.STEPS_NUDGE_VERSION,
                }
            )
        )
    except Exception as e:  # noqa: BLE001 — the stamp is the dead-man's food; never block the pass
        logger.warning("[steps-nudge] eval stamp failed: %s", e)


def run(table, send: Callable[[str], None], now_utc: datetime, budget_tier: int, *, user: str = "matthew", dry_run: bool = False) -> dict:
    """One steps-nudge pass. `send(text)` delivers the owner email. Never raises into the coach nudge's tick."""
    now_pt = now_utc.astimezone(PACIFIC)
    date = now_pt.date().isoformat()
    if not steps_nudge.WINDOW_START_HOUR_PT <= now_pt.hour < steps_nudge.WINDOW_END_HOUR_PT:
        return {"send": False, "reason": "outside_window"}
    try:
        fetch = make_fetch(table, user)
        hevy_rows = fetch("hevy", date, date)
        sent = bool(table.get_item(Key={"pk": LEDGER_PK, "sk": steps_nudge.idempotency_key(date)}).get("Item"))
        resolution = steps_resolver.daily_steps(date, fetch=fetch, derived=False)
        verdict = steps_nudge.decide(
            date=date,
            now_pt=now_pt,
            ramp=read_ramp(table, date, user) if not sent else None,
            steps_day=resolution,
            hevy_rows=hevy_rows,
            already_sent=sent,
            budget_tier=budget_tier,
            first_session_pt=_first_session_pt(hevy_rows),
            steps_as_of_pt=_steps_as_of_pt(date, resolution, fetch),
        )
    except Exception as e:  # noqa: BLE001
        logger.error("[steps-nudge] evaluation failed: %s", e)
        return {"send": False, "reason": f"error:{type(e).__name__}"}
    _stamp_eval(table, date, verdict, now_utc)
    if not verdict["send"]:
        return {"send": False, "reason": verdict["reason"]}
    if not _claim(table, date, verdict, now_utc):
        return {"send": False, "reason": "already_sent"}
    try:
        send(verdict["text"])
    except Exception as e:  # noqa: BLE001
        logger.error("[steps-nudge] send failed: %s", e)
        _settle(table, date, "failed", error=str(e))
        return {"send": False, "reason": "send_failed"}
    _settle(table, date, "dry_run" if dry_run else "sent", text=verdict["text"])
    return {"send": True, "reason": verdict["reason"], "key": verdict["key"]}
