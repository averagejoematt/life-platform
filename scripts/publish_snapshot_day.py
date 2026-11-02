#!/usr/bin/env python3
"""scripts/publish_snapshot_day.py — the Day object for the v9 build (#5585, epic #5577).

One object per day since the start, at /data/day/<YYYY-MM-DD>/: the day's readings exactly as
/api/pulse_history serves them, each against its own trailing normals (the 7-day and 30-day means
with their n — computed HERE, at export, never in the browser), the program week the day falls in
(its chapter, whatever that chapter's state), the neighbouring days, and whether the three
window-bound endpoints (workouts, sleep nights, nutrition days) still serve the day — the flags the
M4 exporter will fill with the day's own detail.

M4 (#5586) adds the day's layers 2–3, each read from the public API and nothing else: the session set by
set (/api/workouts, fetched in ≤ 92-day windows), the night by both devices (/api/sleep_detail, windowed),
the food as logged (/api/nutrition_overview, windowed) with the PLATFORM's logging-gap flag (the `gap`
the behavioral nutrition series carry, /api/series — lambdas/web/site_api_series.logging_gap — never a
threshold typed here), the engine's score that morning (/api/character?date=, only when the sheet served
IS that day's), the coaches' lines exactly as /api/coach_moves?date= serves them (its quotability and
privacy filter is the gate), and the calls settled that day / open as of it (the ledger already exported).
Every block carries a state, so a day the platform cannot serve says why in place.

Kept beside scripts/publish_snapshot.py (over the 1000-line module ceiling, tests/test_module_size_guard.py)
like scripts/publish_snapshot_journey.py. `day_objects` is pure (no network, no clock) so the fixture
and the live export share it (tests/test_web_day_object_5585.py).
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from typing import Any, Callable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from publish_snapshot_contract import ID_RE, ISO_DAY, SchemaError, envelope, log  # noqa: E402
from publish_snapshot_corrections import annotate_coach_lines  # noqa: E402

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

# ── M4: the day's layers 2–3 (#5586) ───────────────────────────────────────────────────────
WINDOW_MAX_DAYS = 92  # lambdas/web/day_window.py: the most days one ?from=&to= request may span
WORKOUT_STATES = ("served", "none logged", "older than the served window", "not served")
NIGHT_STATES = ("served", "none recorded", "older than the served window", "not served")
FOOD_STATES = ("served", "not logged", "older than the served window", "not served")
GRADED = ("confirmed", "refuted", "inconclusive")  # a settled call with a verdict (expired is not a grade)
OPEN_CAP = 6  # open calls listed per day, nearest settle date first; the count says how many in all
# The night's hours target the recovery decomposition reads against: the platform's own default
# (profile.sleep_target_hours_ideal, lambdas/health/scoring_engine.py and daily_metrics_compute_lambda.py).
SLEEP_TARGET_H = 7.5
# The behavioral nutrition series whose per-day `gap` is the platform's zero-entry rule (#5519).
GAP_SERIES = ("total_calories_kcal", "total_protein_g")
LAYER_SOURCES = [
    "/api/workouts",
    "/api/sleep_detail",
    "/api/nutrition_overview",
    "/api/series",
    "/api/character",
    "/api/coach_moves",
    "/api/ledger_export",
]
PILLAR_ORDER = ("sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency")


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
    detail: dict[str, dict] | None = None,
) -> list[dict]:
    """The Day objects for the pulse rows (pure). A row without an ISO date or a day number is dropped
    and logged — never guessed. `detail` (date -> `day_detail(...)`) carries the M4 layers; a day
    without one gets every block in its "not served" state."""
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
        extra = dict((detail or {}).get(day) or empty_detail())
        layer_edges = extra.pop("_edges", [])
        edges = layer_edges + edges
        if chapter_id:
            edges.insert(0, {"type": "chapter", "id": chapter_id, "rel": "this_week"})
        in_window = {}
        for k in WINDOWS:
            span = windows.get(k)
            in_window[k] = bool(span and span[0] <= day <= span[1])
        in_window.update(extra.pop("_in_window", {}))
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
                sleep_target_h=SLEEP_TARGET_H,
                **extra,
            )
        )
    annotate_coach_lines(out)  # dated corrections beside the verbatim lines (the owner's acceptance ruling, 2026-11-02)
    for o in out:
        check_day(o)
    return out


# ── M4 layers (#5586): pure mappers, one per block ──────────────────────────────────────────
def empty_detail() -> dict:
    """Every M4 block in its "not served" state (the endpoint was not read for this snapshot)."""
    return {
        "workout": None,
        "workout_state": "not served",
        "night": None,
        "night_state": "not served",
        "food": None,
        "food_state": "not served",
        "engine": None,
        "coach_lines": [],
        "calls_settled": [],
        "calls_open": [],
        "calls_open_count": 0,
    }


def _str(v: Any) -> str | None:
    return v.strip() if isinstance(v, str) and v.strip() else None


def workout_of(rows: list[dict]) -> dict | None:
    """The day's Hevy session as /api/workouts serves it: every set with its type, reps, load and RPE.
    Two sessions on one day: the one that moved the most (the page names the session, not a sum)."""
    rows = [r for r in rows if isinstance(r, dict) and _str(r.get("title"))]
    if not rows:
        return None
    r = max(rows, key=lambda x: (_num(x.get("total_volume_kg")) or 0, _num(x.get("duration_min")) or 0))
    exercises = []
    for e in r.get("exercises") or []:
        if not isinstance(e, dict) or not _str(e.get("name")):
            continue
        sets = [
            {
                "type": _str(s.get("type")) or "normal",
                "reps": _num(s.get("reps")),
                "weight_kg": _num(s.get("weight_kg")),
                "rpe": _num(s.get("rpe")),
            }
            for s in (e.get("sets") or [])
            if isinstance(s, dict)
        ]
        exercises.append({"name": _str(e.get("name")), "sets": sets})
    return {
        "title": _str(r.get("title")),
        "duration_min": _num(r.get("duration_min")),
        "volume_kg": _num(r.get("total_volume_kg")),
        "exercises": exercises,
    }


def _device(d: Any, hours_key: str, score_key: str) -> dict | None:
    if not isinstance(d, dict):
        return None
    out = {
        "night_of": str(d.get("night_of")) if ISO_DAY.match(str(d.get("night_of") or "")) else None,
        "hours": _num(d.get(hours_key)),
        "deep_hours": _num(d.get("deep_hours")),
        "rem_hours": _num(d.get("rem_hours")),
        "light_hours": _num(d.get("light_hours")),
        "score": _num(d.get(score_key)),
    }
    return out if any(v is not None for k, v in out.items() if k != "night_of") else None


def night_of(row: dict | None) -> dict | None:
    """The night that ended on the day (/api/sleep_detail's sleep_trend row dated that morning), by both devices."""
    if not isinstance(row, dict):
        return None
    start = _str(row.get("sleep_start"))
    return {
        "score": _num(row.get("sleep_score")),
        "efficiency": _num(row.get("efficiency")),
        "hours": _num(row.get("hours")),
        "deep_pct": _num(row.get("deep_pct")),
        "rem_pct": _num(row.get("rem_pct")),
        "light_pct": _num(row.get("light_pct")),
        "sleep_start": start,
        "by_device": {
            "eightsleep": _device(row.get("eightsleep"), "total_sleep_hours", "sleep_score"),
            "whoop": _device(row.get("whoop"), "total_sleep_hours", "quality_score"),
        },
    }


def food_of(row: dict | None, *, logging_gap: bool, floor_g: Any = None, tdee: Any = None) -> dict | None:
    """The four macros as logged, plus the platform's logging-gap flag. No row is no food object —
    a day with no entries is missing, never zero intake."""
    if not isinstance(row, dict):
        return None
    macros = {k: _num(row.get(k)) for k in ("calories", "protein_g", "carbs_g", "fat_g")}
    if all(v is None for v in macros.values()):
        return None
    return {**macros, "logging_gap": bool(logging_gap), "floor_g": _num(floor_g), "tdee": _num(tdee)}


def engine_of(payload: Any, day: str) -> dict | None:
    """The character sheet as of that morning — only when the record served IS the day's (the endpoint
    falls back to the latest record at-or-before the date, which would be another day's score)."""
    if not isinstance(payload, dict):
        return None
    c = payload.get("character")
    if not isinstance(c, dict) or c.get("pre_experiment") or str(c.get("as_of_date") or "") != day or _num(c.get("level")) is None:
        return None
    by_name = {str(p.get("name")): p for p in payload.get("pillars") or [] if isinstance(p, dict)}
    pillars = []
    for name in PILLAR_ORDER:
        p = by_name.get(name)
        if p is None:
            continue
        ni = bool(p.get("not_instrumented"))
        pillars.append({"name": name, "score": None if ni else _num(p.get("raw_score")), "not_instrumented": ni})
    return {
        "level": _num(c.get("level")),
        "composite": _num(c.get("composite_score")),
        "delta": _num(c.get("composite_delta_1d")),
        "pillars": pillars,
    }


def coach_lines_of(payload: Any, day: str) -> list[dict]:
    """The day's lines exactly as /api/coach_moves?date= serves them (the filter lives there)."""
    if not isinstance(payload, dict) or str(payload.get("date") or day) != day:
        return []
    out = []
    for line in payload.get("lines") or []:
        if not isinstance(line, dict):
            continue
        coach, cid, move, text = _str(line.get("coach")), _str(line.get("coach_id")), _str(line.get("move")), _str(line.get("text"))
        if not (coach and cid and ID_RE.match(cid) and move and text):
            continue
        out.append({"coach": coach, "coach_id": cid, "move": move, "move_label": _str(line.get("move_label")), "text": text})
    return out


def clip(text: Any, limit: int = 110) -> str:
    """A claim shortened at a word boundary, with an ellipsis when cut (the ledger page has it whole)."""
    t = " ".join(str(text or "").split())
    if len(t) <= limit:
        return t
    cut = t[: limit - 1]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > 40 else cut).rstrip(" ,;:—-") + "…"


def calls_for(predictions: list[dict], day: str) -> tuple[list[dict], list[dict], int]:
    """The calls graded on the day, and the calls open as of it (logged by then, due after it, not yet
    settled) nearest settle date first — read off the exported ledger, never re-graded."""
    settled, open_ = [], []
    for p in predictions:
        if p.get("visibility", "public") != "public":
            continue
        logged = str(p.get("logged_date") or "")[:10]
        due, done = p.get("due_date"), p.get("settled_date")
        if done == day and p.get("status") in GRADED:
            settled.append(
                {
                    "prediction_id": p["id"],
                    "coach_name": p["coach_name"],
                    "verdict": p["status"],
                    "claim_short": clip(p.get("claim") or p["title"]),
                }
            )
        elif (
            ISO_DAY.match(logged)
            and logged <= day
            and due
            and due > day
            and (done is None or done > day)
            and p.get("status") != "observation"
        ):
            open_.append(
                {"prediction_id": p["id"], "coach_name": p["coach_name"], "due_date": due, "text": clip(p.get("claim") or p["title"])}
            )
    settled.sort(key=lambda c: c["prediction_id"])
    open_.sort(key=lambda c: (c["due_date"], c["prediction_id"]))
    return settled, open_[:OPEN_CAP], len(open_)


def day_detail(
    day: str,
    *,
    workouts: list[dict],
    night_row: dict | None,
    food_row: dict | None,
    covered: dict[str, set[str] | None],
    gap_days: set[str],
    floor_g: Any = None,
    tdee: Any = None,
    character: Any = None,
    coach_moves: Any = None,
    predictions: list[dict] | None = None,
    coach_ids: set[str] | None = None,
) -> dict:
    """One day's M4 fields (pure). `covered[k]` is the set of days endpoint k was asked for and answered
    (None: not served at all), so a day outside it is "older than the served window", never "none"."""

    def state(k: str, value: Any, none_word: str) -> str:
        if value is not None:
            return "served"
        cov = covered.get(k)
        if cov is None:
            return "not served"
        return none_word if day in cov else "older than the served window"

    workout = workout_of(workouts)
    night = night_of(night_row)
    food = food_of(food_row, logging_gap=day in gap_days, floor_g=floor_g, tdee=tdee)
    lines = coach_lines_of(coach_moves, day)
    settled, open_, n_open = calls_for(predictions or [], day)
    edges, seen = [], set()
    for kind, oid, rel in (
        [("coach", ln["coach_id"], "spoke") for ln in lines if ln["coach_id"] in (coach_ids or set())]
        + [("prediction", c["prediction_id"], "graded_that_day") for c in settled]
        + [("prediction", c["prediction_id"], "open") for c in open_]
    ):
        if (kind, oid) not in seen:
            seen.add((kind, oid))
            edges.append({"type": kind, "id": oid, "rel": rel})
    return {
        "workout": workout,
        "workout_state": state("workouts", workout, "none logged"),
        "night": night,
        "night_state": state("sleep", night, "none recorded"),
        "food": food,
        "food_state": state("nutrition", food, "not logged"),
        "engine": engine_of(character, day),
        "coach_lines": lines,
        "calls_settled": settled,
        "calls_open": open_,
        "calls_open_count": n_open,
        "_edges": edges,
        "_in_window": {k: bool(covered.get(k) is not None and day in covered[k]) for k in WINDOWS},
    }


def _keys(o: Any, want: set[str], where: str) -> None:
    if not isinstance(o, dict) or set(o) != want:
        raise SchemaError(f"{where}: expected exactly {sorted(want)}")


def _nums(o: dict, keys: tuple[str, ...], where: str) -> None:
    for k in keys:
        if o[k] is not None and _num(o[k]) is None:
            raise SchemaError(f"{where}.{k}: a number or null")


def check_layers(o: dict, where: str) -> None:
    """The M4 shapes (strict, mirrored by www/src/content.config.ts)."""
    for k, states in (("workout_state", WORKOUT_STATES), ("night_state", NIGHT_STATES), ("food_state", FOOD_STATES)):
        if o[k] not in states:
            raise SchemaError(f"{where}.{k}: {o[k]!r} not in {states}")
    for k, block in (("workout", "workout"), ("night", "night"), ("food", "food")):
        if (o[block] is None) != (o[f"{k}_state"] != "served"):
            raise SchemaError(f"{where}.{block}: present exactly when its state is served")
    w = o["workout"]
    if w is not None:
        _keys(w, {"title", "duration_min", "volume_kg", "exercises"}, f"{where}.workout")
        _nums(w, ("duration_min", "volume_kg"), f"{where}.workout")
        for e in w["exercises"]:
            _keys(e, {"name", "sets"}, f"{where}.workout.exercise")
            for st in e["sets"]:
                _keys(st, {"type", "reps", "weight_kg", "rpe"}, f"{where}.workout.set")
                _nums(st, ("reps", "weight_kg", "rpe"), f"{where}.workout.set")
    n = o["night"]
    if n is not None:
        _keys(n, {"score", "efficiency", "hours", "deep_pct", "rem_pct", "light_pct", "sleep_start", "by_device"}, f"{where}.night")
        _nums(n, ("score", "efficiency", "hours", "deep_pct", "rem_pct", "light_pct"), f"{where}.night")
        _keys(n["by_device"], {"eightsleep", "whoop"}, f"{where}.night.by_device")
        for dev in n["by_device"].values():
            if dev is not None:
                _keys(dev, {"night_of", "hours", "deep_hours", "rem_hours", "light_hours", "score"}, f"{where}.night.device")
                _nums(dev, ("hours", "deep_hours", "rem_hours", "light_hours", "score"), f"{where}.night.device")
    f = o["food"]
    if f is not None:
        _keys(f, {"calories", "protein_g", "carbs_g", "fat_g", "logging_gap", "floor_g", "tdee"}, f"{where}.food")
        _nums(f, ("calories", "protein_g", "carbs_g", "fat_g", "floor_g", "tdee"), f"{where}.food")
        if not isinstance(f["logging_gap"], bool):
            raise SchemaError(f"{where}.food.logging_gap: a boolean")
    e = o["engine"]
    if e is not None:
        _keys(e, {"level", "composite", "delta", "pillars"}, f"{where}.engine")
        for p in e["pillars"]:
            _keys(p, {"name", "score", "not_instrumented"}, f"{where}.engine.pillar")
            if p["not_instrumented"] and p["score"] is not None:
                raise SchemaError(f"{where}.engine.pillar {p['name']}: an absent area carries no score (never 50)")
    for ln in o["coach_lines"]:
        _keys(ln, {"coach", "coach_id", "move", "move_label", "text", "corrections"}, f"{where}.coach_lines")
        if not isinstance(ln["corrections"], list) or not all(isinstance(c, str) and c for c in ln["corrections"]):
            raise SchemaError(f"{where}.coach_lines.corrections: a list of sentences")
    for c in o["calls_settled"]:
        _keys(c, {"prediction_id", "coach_name", "verdict", "claim_short"}, f"{where}.calls_settled")
    for c in o["calls_open"]:
        _keys(c, {"prediction_id", "coach_name", "due_date", "text"}, f"{where}.calls_open")


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
    check_layers(o, where)


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


def window_chunks(first: str, last: str, max_days: int = WINDOW_MAX_DAYS) -> list[tuple[str, str]]:
    """first..last cut into consecutive ≤ max_days windows (the endpoints' own cap)."""
    a, b = date.fromisoformat(first), date.fromisoformat(last)
    out = []
    while a <= b:
        end = min(b, a + timedelta(days=max_days - 1))
        out.append((a.isoformat(), end.isoformat()))
        a = end + timedelta(days=1)
    return out


def _days(a: str, b: str) -> set[str]:
    d0, d1 = date.fromisoformat(a), date.fromisoformat(b)
    return {(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)}


# endpoint key -> (path, rows field, covered key)
WINDOWED = {
    "workouts": ("/api/workouts", "workouts", "workouts"),
    "sleep_detail": ("/api/sleep_detail", "sleep_trend", "sleep"),
    "nutrition_overview": ("/api/nutrition_overview", "nutrition_trend", "nutrition"),
}


def fetch_windowed(get: Callable[[str], Any], first: str, last: str, fallback: dict[str, Any]) -> tuple[dict, dict, dict]:
    """One call per endpoint per ≤ 92-day window. Returns (rows by endpoint, days covered by covered-key,
    nutrition context by day). A window the endpoint did not answer is not covered; an endpoint that
    answered no window falls back to its default (undated) payload, covering only the dates it served."""
    rows: dict[str, list[dict]] = {k: [] for k in WINDOWED}
    covered: dict[str, set[str] | None] = {}
    food_ctx: dict[str, tuple[Any, Any]] = {}
    for key, (path, field, ck) in WINDOWED.items():
        got: set[str] = set()
        answered = False
        for a, b in window_chunks(first, last):
            try:
                payload = get(f"{path}?from={a}&to={b}")
            except Exception as exc:  # noqa: BLE001 — any failure leaves the window uncovered, logged
                log(f"  day: {path} {a}..{b} unavailable ({exc})")
                continue
            if not isinstance(payload, dict) or not isinstance(payload.get("window"), dict):
                log(f"  day: {path} {a}..{b} answered without a window; not used")
                continue
            answered = True
            win = payload["window"]
            wa, wb = str(win.get("from") or a), str(win.get("to") or b)
            if ISO_DAY.match(wa) and ISO_DAY.match(wb) and wa <= wb:
                got |= _days(wa, wb)
            rows[key] += [r for r in payload.get(field) or [] if isinstance(r, dict)]
            if key == "nutrition_overview":
                nut = payload.get("nutrition") if isinstance(payload.get("nutrition"), dict) else {}
                for d in _days(wa, wb):
                    food_ctx[d] = (nut.get("protein_floor_g"), nut.get("tdee"))
        if not answered:
            fb = fallback.get(key) if isinstance(fallback.get(key), dict) else None
            span = _span([r.get("date") for r in (fb or {}).get(field) or [] if isinstance(r, dict)])
            if span:
                rows[key] = [r for r in fb.get(field) or [] if isinstance(r, dict)]
                got = _days(*span)
                if key == "nutrition_overview":
                    nut = fb.get("nutrition") if isinstance(fb.get("nutrition"), dict) else {}
                    for d in got:
                        food_ctx[d] = (nut.get("protein_floor_g"), nut.get("tdee"))
            covered[ck] = got if span else None
        else:
            covered[ck] = got
    return rows, covered, food_ctx


def gap_days_of(series: dict[str, dict]) -> set[str]:
    """The days the behavioral nutrition series mark as a logging gap (the platform's zero-entry rule)."""
    out: set[str] = set()
    for key in GAP_SERIES:
        for d in (series.get(key) or {}).get("days") or []:
            if isinstance(d, dict) and d.get("gap") is True and ISO_DAY.match(str(d.get("date") or "")):
                out.add(d["date"])
    return out


def layers_for(ctx: Any, get: Callable[[str], Any], rows: list[dict]) -> dict[str, dict]:
    """Every day's M4 fields from the live API: three windowed reads, two per-day reads (57 days → 114
    small GETs, nothing cached beyond the snapshot), the ledger and the series already exported."""
    dates = sorted(str(r.get("date")) for r in rows if ISO_DAY.match(str(r.get("date") or "")))
    if not dates:
        return {}
    got, covered, food_ctx = fetch_windowed(get, dates[0], dates[-1], ctx.fetched)
    by_date: dict[str, list[dict]] = {}
    for w in got["workouts"]:
        by_date.setdefault(str(w.get("date") or "")[:10], []).append(w)
    nights = {str(r.get("date") or "")[:10]: r for r in got["sleep_detail"]}
    foods = {str(r.get("date") or "")[:10]: r for r in got["nutrition_overview"]}
    gaps = gap_days_of(getattr(ctx, "series", {}) or {})
    if not gaps:
        log("  day: no behavioral nutrition series marks a gap in this snapshot")
    coach_ids = {o["id"] for o in ctx.objs.get("coach", [])}
    preds = ctx.objs.get("prediction", [])
    out = {}
    for day in dates:
        per = {}
        for key, path in (("character", "/api/character"), ("coach_moves", "/api/coach_moves")):
            try:
                per[key] = get(f"{path}?date={day}")
            except Exception as exc:  # noqa: BLE001 — a day the endpoint does not answer shows its absent state
                log(f"  day: {path}?date={day} unavailable ({exc})")
                per[key] = None
        floor_g, tdee = food_ctx.get(day, (None, None))
        out[day] = day_detail(
            day,
            workouts=by_date.get(day, []),
            night_row=nights.get(day),
            food_row=foods.get(day),
            covered=covered,
            gap_days=gaps,
            floor_g=floor_g,
            tdee=tdee,
            character=per["character"],
            coach_moves=per["coach_moves"],
            predictions=preds,
            coach_ids=coach_ids,
        )
    return out


def live_days(ctx: Any, get: Callable[[str], Any] | None = None) -> None:
    """Fill ctx.objs["day"] from /api/pulse_history (runs after the chapters, week states, ledger and
    metrics). With `get` (the exporter's public GET), each day also carries its M4 layers (#5586)."""
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
        source=["/api/pulse_history", "/api/chapters"] + (LAYER_SOURCES if get else []),
        detail=layers_for(ctx, get, rows) if get else None,
    )
