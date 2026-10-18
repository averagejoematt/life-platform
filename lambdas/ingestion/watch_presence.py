"""The Apple Watch dead-man: has ANY watch-sourced reading arrived recently? (#4970)

WHY THIS EXISTS
---------------
Every Health Auto Export stream lands in the ONE `apple_health` partition, and the
phone keeps that partition fresh on its own (steps, water, nutrition mirrors). So a
watch with a dead battery, a revoked Health grant or a broken background sync reads
"fresh" at the partition level forever — the D-4/#468 class, one level down: not a
months-dark sensor stream, but a months-dark *device*.

The webhook therefore stamps one presence field per day, ``watch_last_reading_epoch_apple``
— the newest instant (epoch seconds, UTC) of any reading whose HealthKit source names
an Apple Watch, across EVERY metric in the payload (mapped, skipped or unmatched: a
watch-sourced sleep sample proves the watch is alive as well as an HRV sample does).
It rides the merge's GREATEST-on-write guard, so a late re-export of older readings can
never pull it backwards.

The threshold is a registry fact, never a constant here: the ``dead_man`` facet on the
``watch`` entry of ``apple_health.hae_datatypes`` in ``source_registry.py``
(``{"field", "stale_hours"}``). ``check_dead_men`` reads every entry carrying that facet,
so a second device dead-man is a registry row, not code.

WHO READS IT
------------
* ``emails/freshness_checker_lambda`` folds a not-ok row into ``stale_sources``, which
  is what ``StaleSourceCount`` counts — so a silent watch rides the existing
  registry-driven ``slo-source-freshness`` alarm (``to_digest=True``: the daily digest). No new alarm, Lambda or schedule.
* ``mcp/tools_labs.tool_get_freshness_status`` reports the same rows to the owner.

ABSENCE (ADR-104)
-----------------
No watch-sourced reading inside the lookback is reported as exactly that — status
``stale`` with ``age_hours: None`` and the lookback stated — never a fabricated age.
A check that could not read DynamoDB is ``unknown``, which the alarm path treats as
not-fresh (an unreadable dead-man is not a live watch).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, cast

# A HealthKit source string names the device the reading came from, e.g.
# "Matthew’s Apple\xa0Watch" (curly apostrophe + NO-BREAK SPACE, measured in the
# 2026-10-17/18 raw drops). The NBSP is why "apple watch" cannot be the needle.
WATCH_SOURCE_NEEDLE = "watch"

# The presence field the webhook writes (docs/SCHEMA.md apple_health, Tier 1 internal).
WATCH_PRESENCE_FIELD = "watch_last_reading_epoch_apple"

# How far back the dead-man looks for the newest presence stamp before saying
# "none in N days" (ADR-104: the lookback is stated, never an invented age).
DEAD_MAN_LOOKBACK_DAYS = 14

STATUS_OK = "ok"
STATUS_STALE = "stale"
STATUS_UNKNOWN = "unknown"


def is_watch_source(source: Any) -> bool:
    """True when a HealthKit reading's `source` names an Apple Watch.

    Normalises the NO-BREAK SPACE and case before matching. A missing source is NOT a
    watch: the hourly-summarised heart-rate export carries no source at all, and
    counting it would let the phone's summaries keep a dead watch looking alive.
    """
    if not source or not isinstance(source, str):
        return False
    return WATCH_SOURCE_NEEDLE in source.replace("\xa0", " ").casefold()


def reading_epoch(stamp: Any) -> float | None:
    """Epoch seconds for an HAE reading stamp ("2026-10-17 21:14:00 -0700", or ISO), or None.

    A stamp with no offset is read as UTC (the webhook's own partition rule, TD-19).
    A date-only stamp is not an instant and returns None — presence needs a time.
    """
    if not stamp or not isinstance(stamp, str):
        return None
    s = stamp.strip()
    if len(s) <= 10:
        return None
    s = s.replace(" ", "T", 1)
    if len(s) >= 24 and s[-5] in ("+", "-") and s[-3] != ":":
        s = s[:-2] + ":" + s[-2:]
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def presence_by_day(metrics: Any, day_of: Callable[[Any], str | None]) -> dict[str, int]:
    """{day: newest watch-sourced reading epoch} over EVERY metric in an HAE payload.

    `day_of` is the webhook's own partition-day function (parse_date_str), passed in so
    the presence stamp lands on exactly the DATE# row its reading would. Mapped, skipped
    and unmatched metrics all count — presence is a fact about the device, not the map.
    """
    out: dict[str, int] = {}
    for metric in metrics or []:
        if not isinstance(metric, dict):
            continue
        for reading in metric.get("data", []) or []:
            if not isinstance(reading, dict) or not is_watch_source(reading.get("source")):
                continue
            stamp = reading.get("date") or reading.get("end") or reading.get("sleepEnd")
            epoch = reading_epoch(stamp)
            day = day_of(stamp)
            if epoch is None or not day:
                continue
            if int(epoch) > out.get(day, 0):
                out[day] = int(epoch)
    return out


def dead_man_specs() -> list[dict[str, Any]]:
    """Every registry `hae_datatypes` entry carrying a `dead_man` facet, flattened.

    Each: {key, label, field, stale_hours}. Derived from the registry on every call —
    the threshold is never restated at a consumer.
    """
    from ingestion.source_registry import hae_datatype_thresholds

    out: list[dict[str, Any]] = []
    for d in hae_datatype_thresholds():
        dm = d.get("dead_man")
        if not isinstance(dm, dict):
            continue
        out.append({"key": str(d["key"]), "label": str(d["label"]), "field": str(dm["field"]), "stale_hours": float(dm["stale_hours"])})
    return out


def evaluate(spec: dict[str, Any], last_epoch: float | None, now: datetime, lookback_days: int = DEAD_MAN_LOOKBACK_DAYS) -> dict[str, Any]:
    """Pure verdict for one dead-man. `now` must be timezone-aware.

    Returns {key, label, status, age_hours, stale_hours, last_reading_at, detail}.
    """
    stale_hours = float(spec["stale_hours"])
    row: dict[str, Any] = {"key": spec["key"], "label": spec["label"], "stale_hours": stale_hours}
    if last_epoch is None:
        row.update(
            status=STATUS_STALE,
            age_hours=None,
            last_reading_at=None,
            detail=f"no {spec['label']} reading recorded in the last {lookback_days} days (threshold {stale_hours:.0f}h)",
        )
        return row
    age_hours = (now.timestamp() - float(last_epoch)) / 3600.0
    last_iso = datetime.fromtimestamp(float(last_epoch), tz=now.tzinfo).isoformat()
    stale = age_hours > stale_hours
    row.update(
        status=STATUS_STALE if stale else STATUS_OK,
        age_hours=round(age_hours, 1),
        last_reading_at=last_iso,
        detail=(
            f"last {spec['label']} reading {age_hours:.0f}h ago ({last_iso}) "
            f"{'>' if stale else '<='} {stale_hours:.0f}h dead-man threshold"
        ),
    )
    return row


def last_presence_epoch(table: Any, pk: str, field: str, floor_date: str) -> float | None:
    """Newest presence stamp on or after `floor_date` (YYYY-MM-DD), or None.

    Newest-first filtered query bounded below by the key condition, so DynamoDB never
    reads past the lookback. The value is re-checked in Python so a NULL-typed attribute
    cannot fake a sighting. Takes the max over the first page that holds any hit: the
    stamp only rises within a day, and a later day can only hold later readings.
    """
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :lo AND :hi",
        "ExpressionAttributeValues": {":pk": pk, ":lo": f"DATE#{floor_date}", ":hi": "DATE#~"},
        # The presence field is not a DynamoDB reserved word, so no name aliasing (the
        # same shape as freshness_checker's _find_last_seen_beyond_window).
        "FilterExpression": f"attribute_exists({field})",
        "ScanIndexForward": False,
        "ProjectionExpression": f"sk, {field}",
    }
    for _ in range(10):
        resp = table.query(**kwargs)
        vals: list[float] = []
        for it in cast("list[dict[str, Any]]", resp.get("Items", []) or []):
            v = it.get(field)
            if v is None:
                continue
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                continue
        if vals:
            return max(vals)
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            return None
        kwargs["ExclusiveStartKey"] = lek
    return None


def check_dead_men(
    table: Any, now: datetime, user_id: str = "matthew", lookback_days: int = DEAD_MAN_LOOKBACK_DAYS
) -> list[dict[str, Any]]:
    """Evaluate every registry dead-man against the apple_health partition.

    Fail-soft per row: a read error yields a STATUS_UNKNOWN row (reported, and treated
    as not-fresh by the alarm path) instead of raising.
    """
    pk = f"USER#{user_id}#SOURCE#apple_health"
    floor_date = (now.date() - timedelta(days=lookback_days)).isoformat()
    rows: list[dict[str, Any]] = []
    for spec in dead_man_specs():
        try:
            last = last_presence_epoch(table, pk, spec["field"], floor_date)
        except Exception as e:  # noqa: BLE001 — one unreadable dead-man must not sink the run
            rows.append(
                {
                    "key": spec["key"],
                    "label": spec["label"],
                    "stale_hours": spec["stale_hours"],
                    "status": STATUS_UNKNOWN,
                    "age_hours": None,
                    "last_reading_at": None,
                    "detail": f"the dead-man check itself failed ({type(e).__name__}: {e}) — status unknown, not fresh",
                }
            )
            continue
        rows.append(evaluate(spec, last, now, lookback_days))
    return rows


def not_ok(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rows that must reach the alarm path (stale or unknown)."""
    return [r for r in rows if r.get("status") != STATUS_OK]
