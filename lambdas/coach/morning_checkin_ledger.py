"""morning_checkin_ledger.py — #5132: the morning check-in's outcome row (the dead-man's food).

``telegram-coach-worker._morning_checkin`` (the ``TelegramMorningCheckin`` rule, 17:15Z Mon-Fri) used to leave its
outcome as a log line only: sent, or one of six skip reasons. The owner's ``two_consecutive_ignored`` latch held it
silent from 2026-10-01 to 2026-10-25 and nothing read the reason, so a quiet feature and a dead feature looked the
same. This module is the write half of the fix: every weekday run overwrites ONE row

    pk ``COACH#morning_checkin`` / sk ``EVAL#<Pacific day>``   {reason, evaluated_at, version}

(the same shape as ``COACH#evening_checkin`` / ``EVAL#<day>``, #5106, so it sits inside the worker's existing
``COACH#*`` LeadingKeys write scope: no new grant). The read half is
``operational.nudge_ledger_qa.check_morning_checkin_liveness``, which reds when two weekdays in a row carry neither
a send nor a sanctioned skip.

``reason`` is a closed vocabulary, normalised from the worker's own result reasons by ``reason_token`` so the stored
tokens never drift with a log-line rewording.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

try:  # the worker's own logger: a handler of its own at INFO, so these lines reach CloudWatch (#3283)
    from common.platform_logger import get_logger

    logger: logging.Logger = get_logger("telegram-worker")
except ImportError:  # pragma: no cover
    logger = logging.getLogger("telegram-worker")
    logger.setLevel(logging.INFO)

VERSION = "morning-checkin-eval@1.0.0"
LEDGER_PK = "COACH#morning_checkin"
EVAL_PREFIX = "EVAL#"

SENT = "sent"
# Sanctioned skips: the worker deliberately stood down. Each is a rule firing, not the feature failing.
SANCTIONED_SKIPS = ("dark", "quiet_hours", "silence_respected", "budget", "capped", "held")
SANCTIONED = (SENT,) + SANCTIONED_SKIPS

# worker result["reason"] -> stored token. ``weekend`` is deliberately absent: a weekend run is never stamped.
_TOKENS = {
    "dark": "dark",
    "quiet hours": "quiet_hours",
    "silence respected": "silence_respected",
    "budget": "budget",
    "capped": "capped",
    "held": "held",
    "empty": "empty",  # the send returned no bubble: NOT sanctioned, the dead-man counts it as silence
}


def reason_token(result: dict) -> str:
    """The stored outcome for a worker result dict: ``sent`` when it carries a delivered ``bubbles`` count."""
    if result.get("bubbles"):
        return SENT
    raw = str(result.get("reason") or "")
    return _TOKENS.get(raw, f"unknown:{raw}"[:60])


def stamp(table, day: str, reason: str, now_utc: datetime) -> None:
    """Overwrite the day's outcome row. Fail-soft: the stamp is the dead-man's food and must never block the run."""
    try:
        table.put_item(
            Item={"pk": LEDGER_PK, "sk": f"{EVAL_PREFIX}{day}", "reason": reason, "evaluated_at": now_utc.isoformat(), "version": VERSION}
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("[morning-checkin] eval stamp failed: %s", type(e).__name__)


def run_stamped(run: Callable[[], dict], table, now_pt: datetime) -> dict:
    """Run the morning check-in (``run``) and leave its outcome as the day's row.

    A weekend run is never stamped (the rule is MON-FRI and the dead-man never counts those days); a crash is stamped
    ``error:<class>`` (not a sanctioned outcome) and re-raised so the Lambda still fails loudly.
    """
    day = now_pt.strftime("%Y-%m-%d")
    try:
        result = run()
    except Exception as e:  # noqa: BLE001
        stamp(table, day, f"error:{type(e).__name__}", datetime.now(timezone.utc))
        raise
    if result.get("reason") != "weekend":
        stamp(table, day, reason_token(result), datetime.now(timezone.utc))
    return result
