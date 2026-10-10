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
  * the TTL only moves forward, never shortens a record a newer write already stamped.
Fail-soft: a renewal that cannot run logs and returns — it must never break the hold itself.

The reader already serves `generated_at`/`data_through` beside the text, so a renewed
(older) record is labelled with its own age, never presented as this week's (#4188).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

# The horizons the analyzer stamps on a fresh write — a renewal uses the same number, so a
# held record lives exactly as long as a fresh one would have.
WEEKLY_TTL_DAYS = 8  # EXPERT#<domain>, EXPERT#integrator
ROLLUP_TTL_DAYS = 10  # EXPERT#experiment_arc, EXPERT#integrator_month

# The board-level records the "all" pass writes only when >=3 domain reads came back. A run
# whose domain reads were held below that floor held these too (they were never attempted).
BOARD_RECORDS = (
    ("EXPERT#integrator", WEEKLY_TTL_DAYS),
    ("EXPERT#integrator_month", ROLLUP_TTL_DAYS),
    ("EXPERT#experiment_arc", ROLLUP_TTL_DAYS),
)


def ttl_from(now: datetime, days: int) -> int:
    """The epoch-seconds TTL `days` after the instant `now`."""
    return int((now + timedelta(days=days)).timestamp())


def renew_held(table: Any, pk: str, sk: str, days: int, *, now: datetime | None = None) -> None:
    """Extend the prior `pk`/`sk` record's TTL to `now + days` because this run HELD its
    replacement. Returns None so a hold site can `return renew_held(...)` in one line."""
    now = now or datetime.now(timezone.utc)
    new_ttl = ttl_from(now, days)
    try:
        table.update_item(
            Key={"pk": pk, "sk": sk},
            UpdateExpression="SET #ttl = :ttl, held_renewed_at = :at",
            ConditionExpression="attribute_exists(pk) AND attribute_not_exists(tombstone) AND (attribute_not_exists(#ttl) OR #ttl < :ttl)",
            ExpressionAttributeNames={"#ttl": "ttl"},
            ExpressionAttributeValues={":ttl": new_ttl, ":at": now.isoformat()},
        )
        logger.info("[held-ttl] %s HELD — prior record's ttl renewed to %d (+%dd) so it keeps serving (#4703)", sk, new_ttl, days)
    except Exception as e:  # noqa: BLE001 — a renewal must never break the hold it serves
        code = getattr(e, "response", {}).get("Error", {}).get("Code") if hasattr(e, "response") else None
        if code == "ConditionalCheckFailedException":
            logger.info("[held-ttl] %s HELD — no live prior record to renew (absent, tombstoned or already newer)", sk)
        else:
            logger.warning("[held-ttl] %s HELD — ttl renewal failed (%s: %s); prior record keeps its own expiry", sk, type(e).__name__, e)
    return None
