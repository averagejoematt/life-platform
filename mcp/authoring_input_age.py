"""authoring_input_age.py — the authoring freshness gate's AGE check on Whoop and Hevy (#5085).

`recovery_authoring.assess_authoring_freshness` asks whether the platform's state COVERS the latest
ingested session (completeness) and whether Whoop recovery is within two days of the target. It never
asked the other question: has an input quietly stopped arriving? A poller that died on Monday leaves
every completeness check green on Thursday, because there is nothing newer to be incomplete against.

This module adds that check, with the thresholds read from the registry — never typed here:
`source_registry.SOURCE_REGISTRY[src]["stale_hours"]` (the facet the SLO freshness checker reads),
falling back to the registry's own `DEFAULT_STALE_HOURS` where a source declares none. A refusal names
its reason: `blocked_stale_inputs: whoop recovery 61 h old > 48 h`.

Ages run from the END of the newest stored UTC day (DATE# keys are day-grained and, for whoop, UTC-keyed,
#3913), so a record dated today is never "old" and the figure never overstates. Hevy counts only while a
lifting session is EXPECTED: an active disruption mode (travel) legitimately has no lifting, and is not
a dead poller. A layoff with no recorded disruption is refused by name — the owner's `override_freshness_gate`
is the answer when he really did not train. Pure core (`assess_input_age`); the one DDB read is fail-soft.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from ingestion.source_registry import DEFAULT_STALE_HOURS, SOURCE_REGISTRY

logger = logging.getLogger(__name__)

REASON_PREFIX = "blocked_stale_inputs"


def threshold_hours(source: str) -> int:
    """The registry's staleness bar for a source — its `stale_hours` facet, else the registry default."""
    declared = (SOURCE_REGISTRY.get(source) or {}).get("stale_hours")
    return int(declared) if declared is not None else int(DEFAULT_STALE_HOURS)


def age_hours(date_str: str, now: datetime) -> float:
    """Hours since the end of UTC day `date_str` (negative while that day is still open)."""
    day_end = datetime.strptime(date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
    return (now - day_end).total_seconds() / 3600.0


def _gap(source: str, label: str, date_str: str | None, now: datetime) -> dict[str, Any] | None:
    if not date_str:
        return None  # nothing on record is the existing gate's finding (recovery) or a first-ever session (hevy)
    try:
        age = age_hours(date_str, now)
    except (ValueError, TypeError):
        return None
    limit = threshold_hours(source)
    if age <= limit:
        return None
    reason = f"{label} {int(age)} h old > {limit} h"
    return {"input": source, "detail": f"{REASON_PREFIX}: {reason}", "reason": f"{REASON_PREFIX}: {reason}", "latest": date_str[:10]}


def assess_input_age(whoop_date: str | None, hevy_date: str | None, now: datetime, hevy_expected: bool = True) -> list[dict[str, Any]]:
    """Named gaps for a Whoop recovery or a Hevy workout older than its registry `stale_hours`."""
    gaps = [_gap("whoop", "whoop recovery", whoop_date, now)]
    if hevy_expected:
        gaps.append(_gap("hevy", "hevy last workout", hevy_date, now))
    return [g for g in gaps if g]


def _latest_hevy_date() -> str | None:
    from boto3.dynamodb.conditions import Key

    from mcp.config import table

    r = table.query(
        KeyConditionExpression=Key("pk").eq("USER#matthew#SOURCE#hevy") & Key("sk").begins_with("DATE#"),
        Limit=1,
        ScanIndexForward=False,
        ProjectionExpression="sk",
    )
    items = r.get("Items", [])
    return items[0]["sk"].split("DATE#", 1)[1][:10] if items else None


def _lifting_expected(target_date: str) -> bool:
    """False while his disruption mode is active on the day (no lifting is the plan, not an outage)."""
    try:
        from training import disruption

        return disruption.state(disruption.load_records_failsoft(), target_date).get("phase") != disruption.PHASE_ACTIVE
    except Exception as e:  # noqa: BLE001
        logger.warning("input age: disruption read failed (%s) — lifting is expected", e)
        return True


def add_input_age(gate: dict[str, Any], latest_recovery: str | None, target_date: str, now: datetime | None = None) -> dict[str, Any]:
    """Fold the age gaps into the gate dict `_authoring_freshness_gate` returns (ok flips, gaps append). Fail-soft."""
    now = now or datetime.now(timezone.utc)
    try:
        hevy_date = _latest_hevy_date()
    except Exception as e:  # noqa: BLE001
        logger.warning("input age: hevy read failed: %s", e)
        hevy_date = None
    gaps = assess_input_age(latest_recovery, hevy_date, now, hevy_expected=_lifting_expected(target_date))
    if gaps:
        gate["gaps"] = list(gate.get("gaps") or []) + gaps
        gate["ok"] = False
    gate["latest_hevy"] = hevy_date
    gate["latest_recovery"] = latest_recovery  # the gate dict reports what it read (moved here from the tool, #1665 ceiling)
    return gate
