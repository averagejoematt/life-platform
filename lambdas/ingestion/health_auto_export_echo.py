"""The untagged-echo guard for Health Auto Export day totals (#4969, owner ruling 2026-10-27, option c).

WHAT IT GUARDS
--------------
On 2026-10-25 the owner reconfigured the HAE automation. The old automation exported
`step_count` / `active_energy` with NO source tag, stamped at the phone's second offsets
(`13:26:14 -0700`); the reconfigured one re-exported the same day tagged with the watch's
source (`Matthew’s Apple Watch`, alone or combined with the phone), minute-aligned
(`13:26:00 -0700`). Both copies land in the stored per-reading map, under different keys,
so both were summed: 144 of 218 untagged step readings and 423 of 713 untagged
active-energy readings on 10-25 shared a minute with a tagged one.

THE RULING (verbatim intent): a minute re-exported once with NO source tag and once tagged
with the watch's source is ONE reading, not two, on any day — so a future HAE
reconfiguration cannot double-count.

THE RULE, exactly
-----------------
* An UNTAGGED reading (source missing, empty, or the writers' `_unknown` bucket) is an
  ECHO when a reading whose source names the watch (`watch_presence.is_watch_source`, so
  the combined `Watch|Matt 17` tag counts) falls in the same UTC minute of the same
  field-day map. An echo is excluded from the day total; the tagged reading counts.
* Nothing else is ever excluded. Two real devices are never resolved against each other
  (WHOOP vs watch vs phone keep their existing rules), a tagged reading is never dropped,
  and an untagged reading in a minute with no watch reading still counts.
* Capture-all (owner rule 2026-10-04): this changes only what the TOTAL counts. The stored
  maps keep every copy — raw S3 is untouched, the additive archive object keeps the
  `_unknown` bucket, and the `_rd_<field>` map keeps every key.
* `is_apple_device` still treats a missing source as Apple: an untagged reading is captured
  and counted exactly as before unless a watch reading covers its minute.

THE TWO MAPS IT APPLIES TO
--------------------------
1. The additive archive (`health_auto_export_additive`, the five #4628 fields): readings
   are stored per source, `{source: {ts: qty}}`, so the class of every reading is known —
   `counted_by_source` filters before `day_value` sums.
2. The DynamoDB `_rd_<field>` maps (watch sums/means, gait, water, caffeine): keyed by
   timestamp only, sources merged, so the class is NOT recoverable from the map. The
   webhook now stores a companion `_rdc_<field>` map, `{ts: "untagged" | "watch"}`, for the
   readings of those two classes (`reading_map` builds it per delivery, `merge_field`
   merges it with the stored one). A key written before this guard has no class and is
   never treated as an echo — the guard only applies where it can prove both copies.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ingestion.watch_presence import is_watch_source, reading_epoch

UNTAGGED = "untagged"
WATCH = "watch"

# The additive writer buckets a missing source as "_unknown" (health_auto_export_additive.payload_readings),
# the generic path as "_unknown" too (process_generic_metrics' src_key).
_UNTAGGED_KEYS = ("", "_unknown")

# The companion map's attribute prefix on the apple_health day row: `_rdc_<field>`.
CLASS_MAP_PREFIX = "_rdc_"


def source_class(source: Any) -> str | None:
    """UNTAGGED for a missing/empty/`_unknown` source, WATCH for a watch tag, None for any other device."""
    if source is None or (isinstance(source, str) and source.strip() in _UNTAGGED_KEYS):
        return UNTAGGED
    return WATCH if is_watch_source(source) else None


def reading_minute(stamp: Any) -> int | None:
    """The reading's UTC minute (epoch // 60), or None when the stamp is not an instant."""
    epoch = reading_epoch(stamp)
    return int(epoch // 60) if epoch is not None else None


def echo_stamps(classes: Mapping[str, str]) -> set[str]:
    """The untagged timestamps whose UTC minute also holds a watch-tagged reading."""
    watch_minutes = {reading_minute(ts) for ts, c in classes.items() if c == WATCH}
    watch_minutes.discard(None)
    return {ts for ts, c in classes.items() if c == UNTAGGED and reading_minute(ts) in watch_minutes}


def counted_by_source(readings: Mapping[str, Mapping[str, float]]) -> dict[str, dict[str, float]]:
    """A `{source: {ts: qty}}` map minus the untagged echoes — what a day total sums (the archive path).

    Each source bucket is its own copy, so an untagged reading at the very stamp of a watch
    reading is an echo too (the minute holds a watch reading)."""
    watch_minutes = {reading_minute(ts) for src, tsq in readings.items() if source_class(src) == WATCH for ts in tsq}
    watch_minutes.discard(None)
    return {
        src: ({ts: q for ts, q in tsq.items() if reading_minute(ts) not in watch_minutes} if source_class(src) == UNTAGGED else dict(tsq))
        for src, tsq in readings.items()
    }


def echo_count(readings: Mapping[str, Mapping[str, float]]) -> int:
    """How many stored readings `counted_by_source` leaves out (a count, never a value)."""
    kept = counted_by_source(readings)
    return sum(len(tsq) for tsq in readings.values()) - sum(len(tsq) for tsq in kept.values())


class ReadingMap(dict[str, float]):
    """A `{ts: qty}` reading map that also carries its readings' classes (`{ts: UNTAGGED | WATCH}`).

    A plain dict to every existing caller (equality, iteration, `.items()`); the webhook's
    DynamoDB merge reads `.classes` to write the `_rdc_<field>` companion."""

    classes: dict[str, str]

    def __init__(self, readings: Mapping[str, float] | None = None, classes: Mapping[str, str] | None = None) -> None:
        super().__init__(readings or {})
        self.classes = dict(classes or {})


def reading_map(per_source: Mapping[str, Mapping[str, float]]) -> ReadingMap:
    """One delivery's `{ts: qty}` for a field-day, merged across the chosen sources in order
    (a later source wins an identical stamp, the pre-#4969 merge), with each reading's class."""
    merged = ReadingMap()
    for src, tsq in per_source.items():
        merged.update(tsq)
        cls = source_class(src)
        for ts in tsq:
            if cls is not None and merged.classes.get(ts) != WATCH:
                merged.classes[ts] = cls
            elif cls is None and merged.classes.get(ts) == UNTAGGED:
                del merged.classes[ts]  # another device's reading now holds this stamp: not an untagged copy
    return merged


def merge_classes(stored: Mapping[str, Any] | None, new: Mapping[str, str] | None) -> dict[str, str]:
    """Union of a stored `_rdc_` map and a delivery's classes; WATCH wins a stamp both carry."""
    out = {str(k): str(v) for k, v in (stored or {}).items()}
    for ts, cls in (new or {}).items():
        if out.get(ts) != WATCH:
            out[ts] = cls
    return out


def counted_map(merged: Mapping[str, float], classes: Mapping[str, str] | None) -> dict[str, float]:
    """A `{ts: qty}` map minus the untagged echoes its classes prove (the `_rd_` path)."""
    echoes = echo_stamps({ts: c for ts, c in (classes or {}).items() if ts in merged})
    return {ts: q for ts, q in merged.items() if ts not in echoes}


def merge_field(new: Mapping[str, float], item: Mapping[str, Any], field: str, mean: bool) -> tuple[ReadingMap, float]:
    """Merge one field's delivery into the stored `_rd_<field>` map of the day row `item`; return
    (merged ReadingMap, day value).

    The stored quantity wins a collision (the #3119 rule, unchanged); the day value is the sum —
    or, for the averaged fields, the mean — of the merged map minus the untagged echoes its
    classes (the delivery's + the stored `_rdc_<field>`) prove."""
    stored_map = item.get(f"_rd_{field}") or {}
    stored = {k: float(str(v)) for k, v in stored_map.items()}
    merged = ReadingMap({**new, **stored}, merge_classes(item.get(f"{CLASS_MAP_PREFIX}{field}"), getattr(new, "classes", None)))
    counted = counted_map(merged, merged.classes)
    return merged, round(sum(counted.values()) / ((len(counted) or 1) if mean else 1), 2)


def reconverted(source: Mapping[str, float], values: Mapping[str, float]) -> dict[str, float]:
    """`values` (a unit-converted copy of `source`) keeping `source`'s classes, when it has any."""
    return ReadingMap(values, getattr(source, "classes", None)) if isinstance(source, ReadingMap) else dict(values)
