"""intelligence/held_record_ttl.py — #4703: a held read renews the record it keeps serving.

Every reader-bound record ai-expert-analyzer writes is a single overwritten key in the
`ai_analysis` partition — `EXPERT#<domain>`, `EXPERT#integrator` (the weekly priority),
`EXPERT#integrator_month` and `EXPERT#experiment_arc` — and every write stamps a DynamoDB
`ttl` a little over one weekly cycle out. The TTL is deliberate: a pipeline that stops
running (cron gone, Lambda failing at import) must not serve a weeks-old read forever
(`test_the_record_expires_so_a_dead_pipeline_cannot_serve_forever`).

The grounding gate (#2391/#2421) HOLDS a draft it cannot ground and promises that "the
prior cached record keeps serving". With an 8-day TTL on a weekly writer that promise was
false by construction: one held Monday left the prior record to expire ~2 days later and
`/api/weekly_priority` served null until a later Monday passed the gate (the 2026-10-05
hold, live null from ~2026-10-06).

The fix keeps the TTL as the dead-pipeline backstop and makes a HOLD renew it: a run that
is alive, reached the gate and declined to replace the record extends the prior record's
TTL by the same horizon a fresh write would have set. A dead pipeline renews nothing, so
it still expires. Only the hold paths call this — a model/transport error does not.

The renewal is one conditional `update_item`:
  * `attribute_exists(pk)` — it never creates a record (no prior read means nothing to keep);
  * `attribute_not_exists(tombstone)` — a reset-wiped record is not resurrected or prolonged;
  * the TTL only moves forward, never shortens a record a newer write already stamped;
  * `generated_at >= :floor` — the record is young enough to keep serving (#5442, below).
Fail-soft: a renewal that cannot run logs and returns — it must never break the hold itself.

The reader already serves `generated_at`/`data_through` beside the text, so a renewed
(older) record is labelled with its own age, never presented as this week's (#4188).

#5442: A HOLD THAT NEVER RELEASES. The renewal had no bound on the record's age, so a domain
the gate held every Monday kept one read alive indefinitely. That is the very case the TTL
guards ("a weeks-old read forever"), reached through holds instead of a dead cron. The
2026-10-05 `EXPERT#sleep` read was renewed three times and served for three weeks while the
coherence sentinel flagged it stale and contradicting. So the renewal carries a fourth
condition: the prior record's `generated_at` is within `MAX_RENEWABLE_AGE_DAYS`. A record keeps
serving through at most two consecutive held or outage-skipped Mondays (renewed at ages 7 and
14 days). At the third, the renewal declines and the record lapses on its own TTL, so the
reader sees an honest absence rather than a read three weeks old. A record with no
`generated_at` cannot be aged, so it is never renewed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)
# #5442: without its own level this logger inherits the Lambda root's WARNING, so every
# "[held-ttl] … renewed" line was dropped. The 2026-10-12/10-18 holds renewed EXPERT#sleep
# with no trace in the analyzer's log. Same explicit level as the analyzer's own logger.
logger.setLevel(logging.INFO)

# The horizons the analyzer stamps on a fresh write — a renewal uses the same number, so a
# held record lives exactly as long as a fresh one would have.
WEEKLY_TTL_DAYS = 8  # EXPERT#<domain>, EXPERT#integrator
ROLLUP_TTL_DAYS = 10  # EXPERT#experiment_arc, EXPERT#integrator_month

# #5442: a renewal only extends a record GENERATED within this many days. The weekly writer
# reaches a held record at ages 7 and 14 (renewed) and 21 (declined): two missed Mondays
# keep serving, the third lets the read lapse. One day of slack absorbs a late cron.
MAX_RENEWABLE_AGE_DAYS = 15

# The board-level records the "all" pass writes only when >=3 domain reads came back. A run
# whose domain reads were held below that floor held these too (they were never attempted).
BOARD_RECORDS = (
    ("EXPERT#integrator", WEEKLY_TTL_DAYS),
    ("EXPERT#integrator_month", ROLLUP_TTL_DAYS),
    ("EXPERT#experiment_arc", ROLLUP_TTL_DAYS),
)
# The analyzer's `results` key for each board record — a record this run WROTE ("ok") is not renewed (#5442).
BOARD_RESULT_KEYS = {
    "EXPERT#integrator": "integrator",
    "EXPERT#integrator_month": "month_rollup",
    "EXPERT#experiment_arc": "experiment_arc",
}


def ttl_from(now: datetime, days: int) -> int:
    """The epoch-seconds TTL `days` after the instant `now`."""
    return int((now + timedelta(days=days)).timestamp())


# The four conditions, named once (a table double evaluates the same string): the record
# exists, is not a reset tombstone, is not already stamped later, and is young enough (#5442).
RENEW_CONDITION = (
    "attribute_exists(pk) AND attribute_not_exists(tombstone) AND (attribute_not_exists(#ttl) OR #ttl < :ttl)"
    " AND attribute_exists(generated_at) AND generated_at >= :floor"
)


def renewable_floor(now: datetime) -> str:
    """The oldest `generated_at` a renewal still extends — ISO-8601 UTC, the same form the
    analyzer stamps (`datetime.now(timezone.utc).isoformat()`), so DynamoDB's string
    comparison orders the two correctly."""
    return (now - timedelta(days=MAX_RENEWABLE_AGE_DAYS)).astimezone(timezone.utc).isoformat()


def renew_held(table: Any, pk: str, sk: str, days: int, *, now: datetime | None = None) -> None:
    """Extend the prior `pk`/`sk` record's TTL to `now + days` because this run HELD its
    replacement. Returns None so a hold site can `return renew_held(...)` in one line."""
    now = now or datetime.now(timezone.utc)
    new_ttl = ttl_from(now, days)
    try:
        table.update_item(
            Key={"pk": pk, "sk": sk},
            UpdateExpression="SET #ttl = :ttl, held_renewed_at = :at",
            ConditionExpression=RENEW_CONDITION,
            ExpressionAttributeNames={"#ttl": "ttl"},
            ExpressionAttributeValues={":ttl": new_ttl, ":at": now.isoformat(), ":floor": renewable_floor(now)},
        )
        logger.info("[held-ttl] %s HELD — prior record's ttl renewed to %d (+%dd) so it keeps serving (#4703)", sk, new_ttl, days)
    except Exception as e:  # noqa: BLE001 — a renewal must never break the hold it serves
        code = getattr(e, "response", {}).get("Error", {}).get("Code") if hasattr(e, "response") else None
        if code == "ConditionalCheckFailedException":
            logger.info(
                "[held-ttl] %s HELD — no prior record renewed (absent, tombstoned, already newer, or generated more than %dd ago, #5442)",
                sk,
                MAX_RENEWABLE_AGE_DAYS,
            )
        else:
            logger.warning("[held-ttl] %s HELD — ttl renewal failed (%s: %s); prior record keeps its own expiry", sk, type(e).__name__, e)
    return None
