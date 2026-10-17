#!/usr/bin/env python3
"""The continuity clock — the dead-man's switch behind the Permanence Contract (#1400).

A dead-man's switch is only as honest as its definition of "dead". This one
measures exactly one thing and says so: **the number of days since the platform
last received data that only exists because a person did something.**

Deriving that set is the whole design problem, and the registry already solved
it. ``lambdas/ingestion/source_registry.py`` carries a ``behavioral`` facet
meaning "staleness here is a logging lapse, not an outage" — i.e. a row appears
only when Matthew logs, lifts, weighs, eats, writes or posts. That is precisely
the presence semantics this needs, so the watched set is **derived** from the
registry rather than hand-listed; a new behavioral source joins the clock the
day it lands.

Two corrections on top of the derived set:

* **Apple Health is watched on a value, not on the partition.** Its rows keep
  arriving from other automations even when nothing is moving (the DI-1.6 "413
  blind spot" the freshness checker already chases), so a fresh partition is
  not evidence of a person. The clock reads the most recent day with non-zero
  steps instead.
* **A source that cannot be read is not a silent source.** Query failures are
  counted separately and, if nothing at all could be read, the verdict is
  ``unknown`` — never ``triggered``. An outage in this file must never be able
  to announce that somebody stopped living (ADR-104).

The thresholds escalate rather than act: 30 days notifies, 60 warns, 90 trips.
Any new signal from any watched source moves the state back down — the switch
is a measurement, and measurements are reversible.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Optional

from ingestion.source_registry import SOURCE_REGISTRY

try:
    from common.platform_logger import get_logger

    logger = get_logger("continuity-watch")
except ImportError:  # pragma: no cover - logging fallback only
    logger = logging.getLogger("continuity-watch")
    logger.setLevel(logging.INFO)

STATE_ACTIVE = "active"
STATE_NOTICE = "notice"
STATE_WARNING = "warning"
STATE_TRIGGERED = "triggered"
STATE_UNKNOWN = "unknown"

NOTICE_DAYS = 30
WARNING_DAYS = 60
TRIGGER_DAYS = 90

ESCALATING_STATES = (STATE_NOTICE, STATE_WARNING, STATE_TRIGGERED)

# Sources watched on a value rather than on partition freshness, because the
# partition stays warm for reasons that have nothing to do with a person.
VALUE_GATED: dict[str, tuple[str, int]] = {
    "apple_health": ("steps", 14),  # (numeric field that must exceed zero, days of history to read)
}

# Every non-behavioural registry source, with the reason it cannot serve as a
# presence signal. tests/test_continuity_watch_1400.py asserts this dict plus
# the derived behavioural set covers the registry exactly — a new source cannot
# join the platform without someone deciding which side of the clock it is on.
AMBIENT_REASONS: dict[str, str] = {
    "apple_health": "watched on a value instead: the partition stays fresh from automations that need no person",
    "dropbox": "a transport poller — it reports on itself, not on anyone",
    "eightsleep": "device telemetry that continues while the bed is empty",
    "garmin": "paused at the vendor's insistence (ADR-074) — no live schedule to be silent",
    "habitify": "the habit engine writes a daily row whether or not anything was ticked",
    "todoist": "a daily snapshot of the task list, written even when nothing is touched",
    "weather": "an external forecast pull — the sky reports whether or not anyone is here",
    "whoop": "device telemetry; a charging strap on a desk still produces rows",
}


def presence_sources() -> tuple[str, ...]:
    """The watched set, derived from the registry's ``behavioral`` facet.

    Paused sources are excluded: a source with no live schedule is silent for
    a reason that has nothing to do with the person, and counting it would let
    a vendor lockout drag the clock.
    """
    return tuple(sorted(k for k, v in SOURCE_REGISTRY.items() if v.get("behavioral") and not v.get("paused")))


def watched_sources() -> tuple[str, ...]:
    """Everything the clock reads: the derived behavioural set plus the
    value-gated exceptions."""
    return tuple(sorted(set(presence_sources()) | set(VALUE_GATED)))


def liveness_role(source: str) -> str:
    """``presence`` | ``value_gated`` | ``ambient``. Raises on an unknown
    source so a new registry entry cannot default into silence."""
    if source not in SOURCE_REGISTRY:
        raise KeyError(f"{source} is not in the source registry")
    if source in VALUE_GATED:
        return "value_gated"
    if source in presence_sources():
        return "presence"
    return "ambient"


def state_for(days_silent: Optional[int]) -> str:
    """Map a day count to a contract state. ``None`` means unmeasurable."""
    if days_silent is None:
        return STATE_UNKNOWN
    if days_silent >= TRIGGER_DAYS:
        return STATE_TRIGGERED
    if days_silent >= WARNING_DAYS:
        return STATE_WARNING
    if days_silent >= NOTICE_DAYS:
        return STATE_NOTICE
    return STATE_ACTIVE


# ── Reading the sources ─────────────────────────────────────────────────────
def _parse_day(sk: str) -> Optional[str]:
    raw = sk.replace("DATE#", "")[:10]
    try:
        datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return None
    return raw


def _last_partition_day(table, user_id: str, source: str) -> tuple[str, Optional[str]]:
    """(status, YYYY-MM-DD) for the newest DATE# row. status in ok|empty|error."""
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :pfx)",
            ExpressionAttributeValues={":pk": f"USER#{user_id}#SOURCE#{source}", ":pfx": "DATE#"},
            ScanIndexForward=False,
            Limit=1,
            ProjectionExpression="sk",
        )
    except Exception as exc:  # noqa: BLE001 - an unreadable source is not a silent source
        logger.warning("continuity: %s unreadable (%s)", source, type(exc).__name__)
        return "error", None
    items = resp.get("Items") or []
    if not items:
        return "empty", None
    day = _parse_day(items[0].get("sk", ""))
    return ("ok", day) if day else ("empty", None)


def _last_value_day(table, user_id: str, source: str, field: str, window: int) -> tuple[str, Optional[str]]:
    """(status, YYYY-MM-DD) for the newest DATE# row whose ``field`` exceeds zero."""
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :pfx)",
            ExpressionAttributeValues={":pk": f"USER#{user_id}#SOURCE#{source}", ":pfx": "DATE#"},
            ScanIndexForward=False,
            Limit=window,
            ProjectionExpression=f"sk, {field}",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("continuity: %s unreadable (%s)", source, type(exc).__name__)
        return "error", None
    days: list[str] = []
    for item in resp.get("Items") or []:
        try:
            value = float(item.get(field) or 0)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        day = _parse_day(item.get("sk", ""))
        if day:
            days.append(day)
    if not days:
        # Read fine, found nothing recent. That is genuine silence within the
        # window, not an error — but it carries no date, so it cannot move the
        # maximum. Reported as `empty` so the quorum check stays honest.
        return "empty", None
    return "ok", max(days)


def read_signals(table, user_id: str = "matthew") -> dict[str, tuple[str, Optional[str]]]:
    """{source: (status, last_day)} across the whole watched set."""
    out: dict[str, tuple[str, Optional[str]]] = {}
    for source in presence_sources():
        out[source] = _last_partition_day(table, user_id, source)
    for source, (field, window) in sorted(VALUE_GATED.items()):
        out[source] = _last_value_day(table, user_id, source, field, window)
    return out


# ── The verdict ─────────────────────────────────────────────────────────────
def evaluate(signals: dict[str, tuple[str, Optional[str]]], today: date) -> dict:
    """Turn per-source readings into the published continuity state.

    Pure. ``today`` is passed in rather than read from the clock so the whole
    ladder is testable without waiting ninety days.
    """
    ok_days = [d for status, d in signals.values() if status == "ok" and d]
    errors = sorted(s for s, (status, _d) in signals.items() if status == "error")
    readable = sum(1 for status, _d in signals.values() if status != "error")

    last_day: Optional[str] = max(ok_days) if ok_days else None
    days_silent: Optional[int] = None
    if last_day is not None:
        days_silent = (today - date.fromisoformat(last_day)).days
        if days_silent < 0:
            # A future-dated row (timezone edge, backfill) is not evidence of
            # anything, but it is certainly not silence.
            days_silent = 0

    # No dated reading anywhere — either nothing could be read, or nothing has
    # ever been written. Both are unmeasurable; neither is news about a person.
    state = STATE_UNKNOWN if last_day is None else state_for(days_silent)

    return {
        "state": state,
        "days_silent": days_silent,
        "last_signal_date": last_day,
        "as_of": today.isoformat(),
        "sources_watched": len(signals),
        "sources_readable": readable,
        "sources_unreadable": len(errors),
        "thresholds_days": {"notice": NOTICE_DAYS, "warning": WARNING_DAYS, "triggered": TRIGGER_DAYS},
    }


def apply_transition(previous: Optional[dict], current: dict, now_iso: str) -> dict:
    """Fold the new verdict into the durable contract state.

    Returns the document published at the continuity address. Three rules:

    * ``unknown`` never escalates and never de-escalates — it carries the prior
      state's freeze forward and says the measurement failed. A broken query is
      not news about a person.
    * a *changed* state that is one of notice/warning/triggered asks for a
      notification exactly once, on the transition.
    * ``triggered`` freezes the archive; anything below it thaws. The dated
      final edition already written stays written — thawing resumes the nightly
      overwrite, it does not retract history.
    """
    prev = previous or {}
    prev_state = prev.get("state") or STATE_ACTIVE
    new_state = current["state"]

    doc = dict(current)
    doc["previous_state"] = prev_state

    if new_state == STATE_UNKNOWN:
        doc["state"] = STATE_UNKNOWN
        doc["changed"] = False
        doc["notify"] = False
        doc["frozen"] = bool(prev.get("frozen"))
        doc["triggered_at"] = prev.get("triggered_at")
        doc["measurement_failed"] = True
        return doc

    doc["changed"] = new_state != prev_state
    doc["notify"] = doc["changed"] and new_state in ESCALATING_STATES
    doc["frozen"] = new_state == STATE_TRIGGERED
    doc["measurement_failed"] = False
    if new_state == STATE_TRIGGERED:
        doc["triggered_at"] = prev.get("triggered_at") or now_iso
    else:
        doc["triggered_at"] = None
    return doc


def notification_subject(doc: dict) -> str:
    """The one-line subject for a continuity transition email."""
    state = doc.get("state")
    days = doc.get("days_silent")
    if state == STATE_TRIGGERED:
        return f"Continuity switch TRIGGERED — {days} days of platform silence"
    return f"Continuity {state}: {days} days of platform silence"


def notification_body(doc: dict, archive_url: str, manifest_url: str) -> str:
    """Plain-text body. Deliberately says what the number means and what it
    does not, because the recipient may be reading it in the worst week of
    their life and should not have to interpret a dashboard."""
    lines = [
        f"The platform has not received a signal from any source that requires a person for {doc.get('days_silent')} days.",
        f"Last signal: {doc.get('last_signal_date')}. Measured on {doc.get('as_of')}.",
        "",
        f"State: {doc.get('state')} (was {doc.get('previous_state')}).",
        f"Thresholds: notice at {NOTICE_DAYS} days, warning at {WARNING_DAYS}, switch at {TRIGGER_DAYS}.",
        "",
        "This measures data, not a person. A long holiday, a broken phone, or a",
        "vendor lockout produce the same silence. If everything is fine, no action is",
        "needed — one new reading from any watched source resets the clock by itself.",
        "",
        "The public archive of everything this platform publishes:",
        f"  {archive_url}",
        f"  {manifest_url}  (inventory + SHA-256 of the archive)",
        "",
        "You are welcome to keep a copy. That is the point of it.",
    ]
    if doc.get("frozen"):
        lines.insert(
            2,
            "The archive is now FROZEN: a dated final edition has been sealed and the nightly overwrite has stopped.",
        )
    return "\n".join(lines)
