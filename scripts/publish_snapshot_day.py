#!/usr/bin/env python3
"""scripts/publish_snapshot_day.py — the Day object for the v9 build (#5585, epic #5577).

One object per day since the start, at /data/day/<YYYY-MM-DD>/: the day's readings exactly as
/api/pulse_history serves them, each against its own trailing normals (the 7-day and 30-day means
with their n — computed HERE, at export, never in the browser), the program week the day falls in
(its chapter, whatever that chapter's state), the neighbouring days, and whether the three
window-bound endpoints (workouts, sleep nights, nutrition days) still serve the day — the flags the
M4 exporter will fill with the day's own detail.

Kept beside scripts/publish_snapshot.py (over the 1000-line module ceiling, tests/test_module_size_guard.py)
like scripts/publish_snapshot_journey.py. `day_objects` is pure (no network, no clock) so the fixture
and the live export share it (tests/test_web_day_object_5585.py).
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from publish_snapshot_contract import ID_RE, ISO_DAY, SchemaError, envelope, log  # noqa: E402

# Optional endpoints the day reads (merged into publish_snapshot.LIVE_ENDPOINTS / OPTIONAL_ENDPOINTS).
# The three window-bound ones are read for their DATES only: nothing they serve is published here.
DAY_ENDPOINTS = {
    "pulse_history": "/api/pulse_history",  # one row per day since the start: the readings (#5585)
    "workouts": "/api/workouts",  # the served workouts window (dates only) — in_window.workouts
    "sleep_detail": "/api/sleep_detail",  # the served nights window (dates only) — in_window.sleep
    "nutrition_overview": "/api/nutrition_overview",  # the served food-log window (dates only) — in_window.nutrition
}

# The pulse row's reading keys, in tile order, and the public metric each one is (None: no metric page yet).
READINGS = ("weight_lbs", "recovery_pct", "sleep_hours", "hrv_ms", "rhr_bpm", "strain", "steps", "active_kcal")
READING_METRIC = {
    "weight_lbs": "weight_lbs",
    "recovery_pct": "recovery_score",
    "sleep_hours": "sleep_duration_hours",
    "hrv_ms": "hrv",
    "rhr_bpm": "resting_hr",
    "strain": None,
    "steps": "steps",
    "active_kcal": None,
}
WINDOWS = ("workouts", "sleep", "nutrition")
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
WEEK_LENGTH = 7


def _num(v: Any) -> float | int | None:
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _mean(vals: list[float]) -> float | None:
    return round(sum(vals) / len(vals), 2) if vals else None


def normals_for(by_date: dict[str, dict], day: str) -> dict[str, dict]:
    """Per reading: the trailing 7- and 30-calendar-day means ENDING ON (and including) the day, over
    the days that carry a reading, with how many did. A window with no reading has a null mean, n 0."""
    d0 = date.fromisoformat(day)
    out: dict[str, dict] = {}
    for key in READINGS:
        row: dict[str, Any] = {}
        for span in (7, 30):
            vals = []
            for back in range(span):
                r = by_date.get((d0 - timedelta(days=back)).isoformat())
                v = _num(r.get(key)) if r else None
                if v is not None:
                    vals.append(float(v))
            row[f"mean{span}"] = _mean(vals)
            row[f"n{span}"] = len(vals)
        out[key] = row
    return out


def title_of(day: str) -> str:
    d = date.fromisoformat(day)
    return f"{_WEEKDAYS[d.weekday()]} {d.day} {_MONTHS[d.month - 1]} {d.year}"


def _summary(readings: dict) -> str:
    parts = []
    if readings.get("weight_lbs") is not None:
        parts.append(f"{readings['weight_lbs']:.1f} lb")
    else:
        parts.append("no weigh-in")
    if readings.get("sleep_hours") is not None:
        parts.append(f"slept {readings['sleep_hours']:g} hours")
    if readings.get("recovery_pct") is not None:
        parts.append(f"recovery {readings['recovery_pct']:g}")
    return " · ".join(parts)


def week_of(day_number: int, day: str, week_spans: list[tuple[int, str, str]] | None = None) -> int:
    """The program week a day falls in: the served week span that contains it (/api/chapters), else
    the arithmetic the platform's weeks follow (day 1–7 = week 1)."""
    for n, start, end in week_spans or []:
        if start <= day <= end:
            return n
    return (day_number - 1) // WEEK_LENGTH + 1


def day_objects(
    rows: list[dict],
    *,
    as_of: str,
    metric_ids: set[str],
    chapter_of_week: dict[int, str],
    week_spans: list[tuple[int, str, str]] | None = None,
    windows: dict[str, tuple[str, str] | None] | None = None,
    sample: bool = False,
    source: list[str] | None = None,
) -> list[dict]:
    """The Day objects for the pulse rows (pure). A row without an ISO date or a day number is dropped
    and logged — never guessed."""
    clean = []
    for r in rows:
        day = str(r.get("date") or "")
        n = r.get("day_number")
        if not ISO_DAY.match(day) or not isinstance(n, int) or isinstance(n, bool) or n < 1:
            log(f"  day: a pulse row without a date or day number was dropped ({day or '?'})")
            continue
        clean.append(r)
    clean.sort(key=lambda r: r["date"])
    by_date = {r["date"]: r for r in clean}
    windows = windows or {}
    out = []
    for i, r in enumerate(clean):
        day = r["date"]
        readings = {k: _num(r.get(k)) for k in READINGS}
        week = week_of(r["day_number"], day, week_spans)
        chapter_id = chapter_of_week.get(week)
        edges = [
            {"type": "metric", "id": READING_METRIC[k], "rel": "reading"}
            for k in READINGS
            if readings[k] is not None and READING_METRIC[k] and READING_METRIC[k] in metric_ids
        ]
        if chapter_id:
            edges.insert(0, {"type": "chapter", "id": chapter_id, "rel": "this_week"})
        in_window = {}
        for k in WINDOWS:
            span = windows.get(k)
            in_window[k] = bool(span and span[0] <= day <= span[1])
        out.append(
            envelope(
                id=day,
                type="day",
                as_of=as_of,
                data_through=day,
                source=list(source or ["/api/pulse_history"]),
                sample=sample,
                title=title_of(day),
                summary=_summary(readings),
                edges=edges,
                date=day,
                day_number=r["day_number"],
                weekday=_WEEKDAYS[date.fromisoformat(day).weekday()],
                readings=readings,
                normals=normals_for(by_date, day),
                chapter_id=chapter_id,
                prev_id=clean[i - 1]["date"] if i > 0 else None,
                next_id=clean[i + 1]["date"] if i + 1 < len(clean) else None,
                has_weighin=readings["weight_lbs"] is not None,
                in_window=in_window,
            )
        )
    for o in out:
        check_day(o)
    return out


def check_day(o: dict) -> None:
    """The nested shape the zod schema holds strictly (www/src/content.config.ts), checked at export too."""
    where = f"day {o.get('id')}"
    if set(o["readings"]) != set(READINGS) or any(_num(v) is None and v is not None for v in o["readings"].values()):
        raise SchemaError(f"{where}.readings: the eight readings, numbers or null")
    for k, n in o["normals"].items():
        if k not in READINGS or set(n) != {"mean7", "n7", "mean30", "n30"}:
            raise SchemaError(f"{where}.normals.{k}: mean7 · n7 · mean30 · n30")
    if set(o["in_window"]) != set(WINDOWS) or not all(isinstance(v, bool) for v in o["in_window"].values()):
        raise SchemaError(f"{where}.in_window: workouts · sleep · nutrition booleans")
    for k in ("prev_id", "next_id", "chapter_id"):
        if o[k] is not None and not ID_RE.match(o[k]):
            raise SchemaError(f"{where}.{k}: bad id {o[k]!r}")


def _span(dates: list[Any]) -> tuple[str, str] | None:
    ds = sorted(str(d)[:10] for d in dates if ISO_DAY.match(str(d or "")[:10]))
    return (ds[0], ds[-1]) if ds else None


def served_windows(fetched: dict[str, Any]) -> dict[str, tuple[str, str] | None]:
    """The first and last day each window-bound endpoint serves (dates only; nothing else is read)."""
    w = fetched.get("workouts") if isinstance(fetched.get("workouts"), dict) else {}
    s = fetched.get("sleep_detail") if isinstance(fetched.get("sleep_detail"), dict) else {}
    n = fetched.get("nutrition_overview") if isinstance(fetched.get("nutrition_overview"), dict) else {}
    return {
        "workouts": _span([x.get("date") for x in (w.get("workouts") or []) if isinstance(x, dict)]),
        "sleep": _span([x.get("date") for x in (s.get("sleep_trend") or []) if isinstance(x, dict)]),
        "nutrition": _span([x.get("date") for x in (n.get("nutrition_trend") or []) if isinstance(x, dict)]),
    }


def live_days(ctx: Any) -> None:
    """Fill ctx.objs["day"] from /api/pulse_history (runs after the chapters, week states and metrics)."""
    fetched = ctx.fetched.get("pulse_history")
    rows = fetched.get("pulse_history") if isinstance(fetched, dict) else None
    if not isinstance(rows, list) or not rows:
        log("  day: /api/pulse_history not served; no day pages in this snapshot")
        return
    chapter_of_week: dict[int, str] = {}
    for c in ctx.objs["chapter"]:
        if isinstance(c.get("week"), int) and c["week"] >= 1 and c.get("visibility") == "public":
            chapter_of_week.setdefault(c["week"], c["id"])
    spans = []
    for w in (ctx.fetched.get("chapters") or {}).get("weeks") or []:
        if isinstance(w.get("week"), int) and ISO_DAY.match(str(w.get("start") or "")) and ISO_DAY.match(str(w.get("end") or "")):
            spans.append((w["week"], w["start"], w["end"]))
    ctx.objs["day"] = day_objects(
        rows,
        as_of=ctx.as_of,
        metric_ids={o["id"] for o in ctx.objs["metric"]},
        chapter_of_week=chapter_of_week,
        week_spans=spans,
        windows=served_windows(ctx.fetched),
        source=["/api/pulse_history", "/api/chapters"],
    )
