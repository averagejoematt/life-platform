"""coach_packet_today.py — the session packet's "today so far" view (#4311).

WHY THIS EXISTS

A night-before debrief reviews TODAY. Every window in `get_coach_session_packet` (#4082) reads
the COMPLETED days before `target_date` — right for volume and walking floors, blind to the day
being debriefed — and `last_session_by_type` is a Hevy-only read. On 2026-09-26 a 1h42m Garmin
outdoor walk (Strava 20343117320, 5.16 mi, avg HR 116.8, max 171, 20:09Z) was invisible to the
packet and the coach reviewed the Hevy Flex session alone. This module is the missing field:
every activity on `target_date - 1` (Pacific) from Hevy AND Strava (every device — WHOOP,
Garmin, Apple, the Hevy mirror), each once.

WHAT IT REUSES (no second derivation)

  the rows        Hevy through the ONE sanctioned read (`tools_strength._read_hevy_all_phases`,
                  #4030/#4032); Strava through `mcp.core.query_source_range`. Both writers key a
                  row by the LOCAL day of its start (`hevy_common.local_date_of_start` mirrors
                  `strava_lambda`'s `start_date_local` keying), so `DATE#<day>` IS the Pacific
                  day — the day is read, not re-derived from timestamps.
  the de-dup      `training.walking_volume.dedup_strava` — the #4068 time rule, unchanged:
                  Hevy sessions claim their [start, end] first; Strava activities, longest
                  first, keep only the time nothing earlier claimed. For this LISTING every Hevy
                  session claims its interval (the walking layer needs only the cardio-bearing
                  ones because it never counts a WeightTraining row) — the Hevy->Strava mirror
                  and WHOOP's auto-detected block inside a session are that session seen by
                  another device.
  walking hours   `mcp.shared_quantities.walking_layer_for_day` — THE walking definition over
                  the one day, labelled partial, never extrapolated to a week.
  the type        `training.routine_title.resolve_archetype` (the performed-type resolver the
                  packet's `last_session_by_type` uses), `training_streaks.is_loaded_session`.
  the ceiling     `owner_redlines.REDLINES["walking_floor_hr_wk"]["hr_ceiling_bpm"]` — read,
                  never a literal.

READ STATES (#4072's vocabulary)

  measured     at least one source read and at least one activity is listed; a failed second
               source makes the list a FLOOR and the status says so;
  absent       both sources read and neither recorded anything on the day (so far);
  read_failed  neither source could be read, or the only readable one is empty — nothing can
               be shown and the read broke, which is never "a rest day".
The view is labelled PARTIAL until the day has completed: every figure is "so far".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from common.pacific_time import pacific_clock_label, pacific_today, parse_iso_utc, shift_day_key
from training import walking_volume

TODAY_VIEW_VERSION = "coach-packet-today@1.0.0"

RowReader = Callable[[str], list[dict[str, Any]]]


def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _instant(iso: Any) -> dict[str, Any] | None:
    """A UTC instant rendered twice: the wire value and its Pacific wall-clock label (#4185)."""
    dt = parse_iso_utc(iso)
    if dt is None:
        return None
    return {"utc": dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "pt": pacific_clock_label(str(iso), with_day=True)}


# ── the two partition reads ───────────────────────────────────────────────────────────
def read_hevy_day(day: str) -> list[dict[str, Any]]:
    """The day's per-workout Hevy rows through the ONE sanctioned read (#4030/#4032)."""
    from mcp.tools_strength import _read_hevy_all_phases

    items, _phases = _read_hevy_all_phases(day, day)
    return [it for it in items or [] if "#WORKOUT#" in str(it.get("sk") or "") and str(it.get("date") or "")[:10] == day]


def read_strava_day(day: str) -> list[dict[str, Any]]:
    """The day's Strava day-row(s) — `activities: [...]` per row."""
    from mcp import core

    return [it for it in core.query_source_range("strava", day, day) or [] if str(it.get("date") or it.get("sk") or "")[-10:] == day]


# ── activities, each once ─────────────────────────────────────────────────────────────
def _zones(a: dict[str, Any]) -> dict[str, float] | None:
    z = {f"zone{i}_s": _num(a.get(f"zone{i}_seconds")) for i in range(1, 6) if a.get(f"zone{i}_seconds") is not None}
    return {k: v for k, v in z.items() if v is not None} or None


def _strava_candidates(rows: list[dict[str, Any]], day: str) -> list[dict[str, Any]]:
    """Every Strava activity on the day in `dedup_strava`'s input shape, ALL types, with the wire
    row carried along under `row` (the spread in `dedup_strava` keeps every key)."""
    out: list[dict[str, Any]] = []
    for row in rows:
        for a in row.get("activities") or []:
            start = parse_iso_utc(a.get("start_date"))
            elapsed = _num(a.get("elapsed_time_seconds") or a.get("elapsed_time")) or 0.0
            moving = _num(a.get("moving_time_seconds") or a.get("moving_time")) or 0.0
            kind = (a.get("sport_type") or a.get("type") or "").strip() or "Activity"
            out.append(
                {
                    "_id": f"strava:{a.get('strava_id') or a.get('id') or id(a)}",
                    "date": day,
                    "source": "strava",
                    "modality": walking_volume.STRAVA_COUNTED_TYPES.get(kind.lower()),
                    "label": a.get("name") or kind,
                    "device": a.get("device_name"),
                    "seconds": moving,
                    "start": start,
                    "end": (start + timedelta(seconds=elapsed)) if (start is not None and elapsed > 0) else None,
                    "row": a,
                }
            )
    return out


def _hevy_interval(w: dict[str, Any]) -> tuple[datetime, datetime] | None:
    start, end = parse_iso_utc(w.get("start_time")), parse_iso_utc(w.get("end_time"))
    if start is None or end is None or end <= start:
        return None
    return start, end


def _strava_item(c: dict[str, Any], *, counted_seconds: float | None) -> dict[str, Any]:
    a = c["row"]
    kind = (a.get("sport_type") or a.get("type") or "").strip() or None
    moving = _num(a.get("moving_time_seconds") or a.get("moving_time"))
    item: dict[str, Any] = {
        "id": c["_id"],
        "source": "strava",
        "device": a.get("device_name"),
        "type": kind,
        "modality": c.get("modality"),
        "title": a.get("name"),
        "start": _instant(a.get("start_date")),
        "moving_time_s": moving,
        "elapsed_time_s": _num(a.get("elapsed_time_seconds") or a.get("elapsed_time")),
        "distance_mi": _num(a.get("distance_miles")),
        "avg_hr": _num(a.get("average_heartrate")),
        "max_hr": _num(a.get("max_heartrate")),
        "zones": _zones(a),
    }
    if counted_seconds is not None and moving is not None and counted_seconds < moving - 0.5:
        item["moving_time_s_counted"] = round(counted_seconds, 1)
        item["note"] = "partly overlaps a Hevy session or a longer Strava activity — only the unclaimed time counts toward walking hours"
    return item


def _hevy_item(w: dict[str, Any], index: list[dict[str, Any]]) -> dict[str, Any]:
    from training.routine_title import resolve_archetype
    from training.training_streaks import is_loaded_session

    blocks, _skipped = walking_volume.hevy_sessions([w])
    return {
        "id": f"hevy:{w.get('source_workout_id') or w.get('workout_uid')}",
        "source": "hevy",
        "device": None,
        "type": resolve_archetype(w, index) or "unresolved",
        "title": w.get("title"),
        "workout_uid": w.get("workout_uid"),
        "start": _instant(w.get("start_time")),
        "end": _instant(w.get("end_time")),
        "moving_time_s": _num(w.get("duration_sec")),
        "distance_mi": None,
        "avg_hr": None,
        "max_hr": None,
        "zones": None,
        "loaded": is_loaded_session(w),
        "exercise_count": w.get("exercise_count"),
        "set_count": w.get("set_count"),
        "cardio_blocks": [{"name": b["label"], "modality": b["modality"], "seconds": b["seconds"]} for b in blocks],
    }


def _sort_key(item: dict[str, Any]) -> str:
    return ((item.get("start") or {}).get("utc")) or "9999"


def activities_on_day(
    day: str, hevy_rows: list[dict[str, Any]] | None, strava_rows: list[dict[str, Any]] | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """(activities each once, the de-duplicated ones, the de-dup record) for the day.

    `None` for a source means it could not be read — it then claims nothing and contributes
    nothing, and the caller labels the list a floor."""
    from training.plan_engine import error_label

    hevy = list(hevy_rows or [])
    intervals = [iv for iv in (_hevy_interval(w) for w in hevy) if iv is not None]
    candidates = _strava_candidates(strava_rows or [], day)
    kept, record = walking_volume.dedup_strava(candidates, intervals)  # the #4068 rule, every Hevy session claiming
    kept_by_id = {k["_id"]: k for k in kept}

    index_state: dict[str, Any] = {"state": "measured"}
    index: list[dict[str, Any]] = []
    if hevy:
        try:
            from training.routine_title import ROUTINE_INDEX_LOOKBACK_DAYS, _load_routine_index

            index = _load_routine_index(shift_day_key(day, -ROUTINE_INDEX_LOOKBACK_DAYS))  # one home (#4312)
        except Exception as e:  # noqa: BLE001 — the TYPE goes unresolved and says why; the sessions still list
            index_state = {"state": "read_failed", "error": error_label(e)}

    items = [_hevy_item(w, index) for w in hevy]
    removed: list[dict[str, Any]] = []
    for c in candidates:
        k = kept_by_id.get(c["_id"])
        if k is not None or c["seconds"] <= 0.5:  # a zero-moving-time record is not a duplicate of anything
            items.append(_strava_item(c, counted_seconds=k["seconds"] if k is not None else None))
            continue
        inside = [
            w.get("title")
            for w, iv in ((w, _hevy_interval(w)) for w in hevy)
            if iv is not None and c["start"] is not None and c["end"] is not None and iv[0] < c["end"] and iv[1] > c["start"]
        ]
        dup = _strava_item(c, counted_seconds=0.0)
        dup.pop("moving_time_s_counted", None)
        dup.pop("note", None)
        dup["why"] = (
            f"recorded over the same minutes as the Hevy session {inside[0]!r} — that session seen by another device"
            if inside
            else "recorded over the same minutes as a longer Strava activity already listed — one activity seen by two devices"
        )
        dup["inside_hevy_session"] = inside or None
        removed.append(dup)
    items.sort(key=_sort_key)
    removed.sort(key=_sort_key)
    record = {**record, "routine_index": index_state}
    return items, removed, record


def _ingest_lag_line(names: list[str]) -> str:
    """The two sources' cadences, read from the registry — never hand-stated (#2003)."""
    try:
        from ingestion.source_registry import SOURCE_REGISTRY

        cadence = "; ".join(f"{n}: {SOURCE_REGISTRY[n].get('method')}" for n in sorted(names))
    except Exception:  # noqa: BLE001 — the line degrades to the fact without the cadence
        cadence = "cadence unreadable from source_registry"
    return f"an activity not yet ingested is not here ({cadence})"


# ── the field ─────────────────────────────────────────────────────────────────────────
def today_view(
    target_date: str,
    *,
    today: str | None = None,
    read_hevy: RowReader | None = None,
    read_strava: RowReader | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """(value, status) for the packet's `today` field: the day BEFORE `target_date` (Pacific) —
    what a night-before debrief reviews. Readers are injectable for the fixture; the
    definition (the day, the de-dup, the walking layer, the ceiling) is not."""
    from training import owner_redlines
    from training.plan_engine import ABSENT, MEASURED, READ_FAILED, error_label, input_status

    from mcp import shared_quantities

    day = shift_day_key(target_date, -1)
    now = today or pacific_today()
    if day > now:
        return None, input_status(ABSENT, f"{day} has not started yet (today is {now}) — nothing to review")

    rows: dict[str, list[dict[str, Any]] | None] = {}
    sources: dict[str, dict[str, Any]] = {}

    def _read(name: str, reader: RowReader) -> None:
        try:
            got = reader(day)
            rows[name] = list(got or [])
            sources[name] = {"status": "read" if rows[name] else "no_records", "rows": len(rows[name])}
        except Exception as e:  # noqa: BLE001 — reported by name, never swallowed into an empty day (#4072)
            rows[name] = None
            sources[name] = {"status": "read_failed", "rows": None, "error": error_label(e)}

    # The two sources are the walking layer's own two (`walking_volume.build(strava_items=, hevy_workouts=)`,
    # #3930/#4068) — read one statement each, as `shared_quantities` does; not a registry-derived list
    # (`evidence_for: workout` would add apple_health, which the layer refuses by construction).
    _read("hevy", read_hevy or read_hevy_day)
    _read("strava", read_strava or read_strava_day)

    failed = sorted(n for n, r in rows.items() if r is None)
    items, removed, record = activities_on_day(day, rows["hevy"], rows["strava"])

    def _inject(source: str, _s: str, _e: str) -> list[dict[str, Any]]:
        got = rows.get(source)
        if got is None:
            raise RuntimeError(f"{source} read failed")
        return got

    layer = shared_quantities.walking_layer_for_day(day, today=now, read=_inject)
    walking = (
        {k: layer.get(k) for k in ("total_hr", "by_source", "by_modality", "total_is_floor", "dedup", "honesty", "definition", "partial")}
        if layer
        else None
    )

    redline = owner_redlines.REDLINES["walking_floor_hr_wk"]
    ceiling = redline["hr_ceiling_bpm"]
    flags = [
        {
            "id": it["id"],
            "title": it.get("title"),
            "device": it.get("device"),
            "avg_hr": it["avg_hr"],
            "hr_ceiling_bpm": ceiling,
            "over_by_bpm": round(float(it["avg_hr"]) - float(ceiling), 1),
            "deduplicated": it in removed,
        }
        for it in items + removed
        if it.get("source") == "strava"
        and it.get("modality") == "walking"
        and it.get("avg_hr") is not None
        and float(it["avg_hr"]) > float(ceiling)
    ]

    partial = day >= now
    honesty: list[str] = []
    if partial:
        honesty.append(f"{day} is still in progress — every figure here is SO FAR (a floor), never the day's total")
    for n in failed:
        honesty.append(f"{n} could not be read ({sources[n]['error']}) — the list is a floor; an activity on that source is not here")
    honesty.append(_ingest_lag_line(list(rows)))

    value = {
        "day": day,
        "partial": partial,
        "label": "PARTIAL — the day in progress, so far" if partial else "the completed day",
        "read_at": _instant(datetime.now(timezone.utc).isoformat()),
        "sources": sources,
        "activities": items,
        "deduplicated": removed,
        "dedup": record,
        "dedup_rule": (
            record.get("rule", "")
            + " — for this listing EVERY Hevy session claims its interval (#4068 reused): the Hevy->Strava mirror and a "
            "WHOOP/Garmin activity recorded inside a session are that session seen by another device"
        ),
        "walking_hours_today": (layer or {}).get("total_hr"),
        "walking": walking,
        "walking_floor_hr_wk": {
            "hr_ceiling_bpm": ceiling,
            "source": "training.owner_redlines.REDLINES['walking_floor_hr_wk']['hr_ceiling_bpm']",
        },
        "hr_ceiling_flags": flags,
        "honesty": honesty,
        "version": TODAY_VIEW_VERSION,
    }
    if len(failed) == 2 or (failed and not items):
        errors = "; ".join(f"{n}: {sources[n]['error']}" for n in failed)
        return value, input_status(READ_FAILED, error=f"SourceReadError: {errors}")
    if not items and not removed:
        return value, input_status(ABSENT, f"no Hevy session and no Strava activity recorded on {day}" + (" so far" if partial else ""))
    detail = []
    if partial:
        detail.append("PARTIAL — the day is in progress")
    if failed:
        detail.append(f"FLOOR — {', '.join(failed)} read failed")
    return value, input_status(MEASURED, "; ".join(detail) or None)
