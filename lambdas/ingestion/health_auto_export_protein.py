"""
health_auto_export_protein.py — the same-day protein feed for the breakfast nudge (#5187, epic #5094).

Why a sibling: the HAE webhook drops `protein` whole (a Tier-3 skip — MacroFactor is the SOT for the
DAILY protein figure, which arrives as an end-of-day upload). But MacroFactor also writes every logged
food into Apple Health as it is logged, and HAE exports those samples intraday (measured 2026-10-22 over
the raw archive: median ~1 h from the entry's own time to the payload's receipt). That per-entry stream,
timed, is what a breakfast-window nudge needs. It is CAPTURED here, beside — never on — the daily field.

The contract (docs/SCHEMA.md "HAE intraday protein"):

  * ONE OWN FIELD. `_rd_protein_hae` on the apple_health day row, a map of the entries as delivered. This
    module never writes `protein_g`, `total_protein_g` or any macro rollup, and the generic path still skips
    `protein` (SKIP_METRICS), so there is no second writer for the daily figure. Capture-all, interpret on
    read: `health.protein_engine.hae_feeding_rows` turns the map into the same `{time, protein_g}` rows the
    MacroFactor food log carries.
  * DAY FRAME. The row is the UTC day of the entry's instant (`day_of` = the webhook's own `parse_date_str`,
    #3677 keep-UTC). For a Pacific morning that UTC day IS the Pacific date; the reader still filters on the
    Pacific date of each entry.
  * RE-SENDS. HAE re-delivers the same samples with the seconds jittered (08:59:15 / 08:59:35 for one
    entry) and the chunk split re-drawn (the pair always sums to the same grams). An entry is therefore keyed
    by its UTC MINUTE, and the LATEST delivery wins a collision (not stored-wins: a re-draw is the vendor's
    correction, and mixing two draws would break the pair's sum). A payload carrying only some of a pair's
    minutes is the one case that can mix draws; it is bounded by the pair and noted, not guarded.
  * ABSENCE (ADR-104). A reading with no usable quantity or time is skipped; units other than grams are
    skipped (never converted by guess). No entries -> no field.
  * FUTURE-DATED ENTRIES. MacroFactor files planned foods at their planned time (a 09:00 entry arrives at
    04:30). `seen_at` (payload receipt) is stored on every entry so a reader can tell logged-after-eating
    from planned-ahead; the nudge counts both as "logged" (the charter's word).
"""

import logging
from datetime import datetime, timezone
from decimal import Decimal

from ingestion.health_auto_export_sleep import parse_instant

try:
    from common.platform_logger import get_logger

    logger = get_logger("health-auto-export")
except ImportError:
    logger = logging.getLogger("health-auto-export")
    logger.setLevel(logging.INFO)

PROTEIN_METRIC_NAMES = frozenset({"protein", "Protein"})
RD_FIELD = "_rd_protein_hae"
HAE_PROTEIN_FIELDS = (RD_FIELD,)
_MAX_ENTRY_G = 500.0  # a single HealthKit protein sample beyond this is a unit error, not food


def _grams(reading, units):
    if (units or "g").strip().lower() not in ("g", "gram", "grams"):
        return None
    try:
        g = float(reading.get("qty"))
    except (TypeError, ValueError):
        return None
    return g if 0 <= g <= _MAX_ENTRY_G else None  # NaN fails both comparisons


def entries_from_metrics(metrics, day_of, seen_at):
    """`{utc_day: {minute_key: entry}}` for every protein sample in one payload."""
    out = {}
    for metric in metrics or ():
        if metric.get("name") not in PROTEIN_METRIC_NAMES:
            continue
        units = metric.get("units")
        for reading in metric.get("data") or ():
            at = parse_instant(reading.get("date") or reading.get("start"))
            g = _grams(reading, units)
            if at is None or g is None:
                continue
            day = day_of(at.isoformat())
            key = at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
            out.setdefault(day, {})[key] = {
                "t": at.isoformat(),
                "g": round(g, 3),
                "source": (reading.get("source") or "").strip(),
                "units_reported": (units or "g"),
                "seen_at": seen_at,
            }
    return out


def _plain(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    return obj


def _to_ddb(obj):
    if isinstance(obj, float):
        return Decimal(str(round(obj, 4)))
    if isinstance(obj, dict):
        return {k: _to_ddb(v) for k, v in obj.items() if v is not None}
    return obj


def write_hae_protein(metrics, table, day_of, key_of, now=None):
    """Merge each day's protein samples into its apple_health row's `_rd_protein_hae`. Returns days written.

    Read-merge-write per day; an unreadable stored map SKIPS the day (a partial payload must never overwrite
    a fuller stored map — the sleep writer's #3119 lesson); a failed write also skips the day, never raises; the next re-send heals it."""
    seen_at = (now or datetime.now(timezone.utc)).isoformat()
    written = 0
    for day, new_entries in sorted(entries_from_metrics(metrics, day_of, seen_at).items()):
        key = key_of(day)
        try:
            stored = table.get_item(Key=key, ProjectionExpression="#rd", ExpressionAttributeNames={"#rd": RD_FIELD}).get("Item", {})
        except Exception as e:  # noqa: BLE001 — fail toward stored history
            logger.warning("[HAE protein] %s: stored map unreadable, day skipped: %s", day, e)
            continue
        merged = {**_plain(stored.get(RD_FIELD) or {}), **new_entries}
        try:
            table.update_item(
                Key=key,
                UpdateExpression="SET #rd = :rd, #src = if_not_exists(#src, :src), #dt = if_not_exists(#dt, :dt)",
                ExpressionAttributeNames={"#rd": RD_FIELD, "#src": "source", "#dt": "date"},
                ExpressionAttributeValues={":rd": _to_ddb(merged), ":src": "apple_health", ":dt": day},
            )
        except Exception as e:  # noqa: BLE001 — an optional owner-only feed never aborts the webhook handler (blood pressure follows)
            logger.warning("[HAE protein] %s: write failed, day skipped: %s", day, e)
            continue
        written += 1
    if written:
        logger.info("[HAE protein] intraday protein: %d day(s) written", written)
    return written
