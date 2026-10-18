"""edition_life_rows.py — /api/edition's ``life`` block, the whole-life rows (#4586; split out for the module-size
ceiling, #1665, by #4580 round 1 lane E).

One served FACT per area, each a door to its own page. No verdict on any row: whether an
area is "going well" is decided by the scorecard's written rules (#4595, web/edition_scorecard.py). A row whose source failed is `unavailable`; one with nothing to say is `absent`;
one whose fact is older than LIFE_STALE_DAYS says which day it is from.

Behind the same entrypoint: ``site_api_edition.compose`` calls ``life_rows(...)`` and nothing else here is public
to the route. Pure — it reads only the upstream bodies ``compose`` already holds.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable

from common.pacific_time import day_in_words, parse_day_key

from web.prediction_reason import measure_unit
from web.site_api_edition import LIFE_ORDER, LIFE_STALE_DAYS, SOURCES, _block, _days_between, _fmt_num, _num, _rows_by_date, _unavailable

_RUNNING = {"active", "running", "in_progress"}


def _row(src: Any, what: str, body: dict | None, build: Callable[[dict], tuple | None], nothing: str, today: str) -> dict:
    """One whole-life row. ``build(body)`` returns ``(text, as_of)`` — or ``(text, as_of, fields)``, the served
    numbers beside the sentence (#4580 round 1) — or None for nothing to say."""
    if body is None:
        return _unavailable(src, what)
    made = build(body)
    if not made:
        return _block("absent", None, src, nothing)
    text, as_of = made[0], made[1]
    data = {"text": text, **(made[2] if len(made) > 2 and isinstance(made[2], dict) else {})}
    age = _days_between(as_of, today) if as_of else None
    if age is not None and age > LIFE_STALE_DAYS:
        return _block("stale", as_of, src, f"Nothing newer than {day_in_words(as_of)}.", data)
    return _block("ok", as_of or today, src, nothing, data)


def _life_body(body: dict) -> tuple | None:
    j = body.get("journey") or {}
    lost, left, goal = _num(j.get("lost_lbs")), _num(j.get("remaining_lbs")), _num(j.get("goal_weight_lbs"))
    if j.get("pre_start") or lost is None or left is None or goal is None:
        return None
    way = "down" if lost >= 0 else "up"
    return f"{_fmt_num(abs(lost))} lb {way} so far; {_fmt_num(left)} lb to go to reach {_fmt_num(goal)}.", j.get("last_weighin_date")


def _life_training(today: str) -> Callable[[dict], tuple | None]:
    def build(body: dict) -> tuple | None:
        names = [str(e.get("name")) for e in body.get("exercises") or [] if isinstance(e, dict) and e.get("name")]
        if body.get("state") != "served" or str(body.get("date") or "") != today or not names:
            return None
        rest = len(names) - 2
        more = f" and {rest} more" if rest > 0 else ""
        return f"Planned for today: {', '.join(names[:2])}{more}.", today

    return build


def _life_sleep(pulse: dict | None) -> Callable[[dict], tuple | None]:
    """#4580 round 1: the row reads the SAME stored row the week block reads — /api/pulse_history's row for the
    wake date — so the two never disagree inside one response (the Oct 16 night read 5.3 h here, Eight Sleep's
    provisional figure, and 8.8 h in the week). /api/sleep_detail names the night; the hours and recovery come
    from the pulse row when it has them, else from sleep_detail itself (its own figure, same night)."""

    def build(body: dict) -> tuple | None:
        d = body.get("sleep_detail") or {}
        night = d.get("night_of")
        if not parse_day_key(str(night or "")):
            return None
        # The night of the 3rd is the sleep he woke from on the 4th: the row is about that morning.
        wake = (
            d.get("as_of_date") if parse_day_key(str(d.get("as_of_date") or "")) else (parse_day_key(night) + timedelta(days=1)).isoformat()
        )
        row = _rows_by_date((pulse or {}).get("pulse_history")).get(wake) or {}
        hours, recovery, read_from = _num(row.get("sleep_hours")), _num(row.get("recovery_pct")), SOURCES["pulse"]
        if hours is None:
            hours, recovery, read_from = _num(d.get("total_sleep_hours")), _num(d.get("recovery_score")), SOURCES["sleep"]
        if hours is None:
            return None
        rec = f"; recovery {_fmt_num(recovery)} out of 100" if recovery is not None else ""
        extra = {
            "hours": hours,
            "unit": measure_unit("sleep"),
            "recovery": {"value": recovery, "unit": measure_unit("recovery")} if recovery is not None else None,
            "night_of": night,
            "wake_date": wake,
            "read_from": read_from,
        }
        return f"Slept {_fmt_num(hours)} hours on the night of {day_in_words(night)}{rec}.", wake, extra

    return build


def _life_food(body: dict) -> tuple | None:
    n = body.get("nutrition") or {}
    hit, logged, floor = _num(n.get("protein_floor_hit_days")), _num(n.get("days_logged")), _num(n.get("protein_floor_g"))
    if hit is None or not logged or floor is None:
        return None
    return f"At or above the {_fmt_num(floor)} g protein floor on {int(hit)} of {int(logged)} logged days.", n.get("latest_date")


def _life_habits(body: dict) -> tuple | None:
    h = body.get("habit_streaks") or {}
    done, total, day = _num(h.get("tier0_done")), _num(h.get("tier0_total")), h.get("as_of_date")
    if done is None or not total or not parse_day_key(str(day or "")):
        return None
    return f"{int(done)} of {int(total)} daily habits kept on {day_in_words(day)}.", day


def _life_supplements(body: dict) -> tuple | None:
    count = sum(len((g or {}).get("items") or []) for g in (body.get("groups") or {}).values() if isinstance(g, dict))
    if not count:
        return None
    return f"{count} in the daily stack.", body.get("as_of_date")


def _life_experiments(today: str) -> Callable[[dict], tuple | None]:
    def build(body: dict) -> tuple | None:
        rows = [e for e in body.get("experiments") or [] if isinstance(e, dict)]
        if not rows:
            return None
        running = [str(e.get("name")) for e in rows if e.get("status") in _RUNNING and e.get("name")]
        ready = sum(1 for e in rows if e.get("status") == "available")
        if running:
            more = f" and {len(running) - 1} more" if len(running) > 1 else ""
            return f"Running now: {running[0]}{more}.", today
        return f"None running right now; {ready} ready to start.", today

    return build


def _life_mind(his_words: dict) -> dict:
    src = his_words.get("source")
    if his_words.get("state") == "unavailable":
        return _unavailable(src, "His own words")
    day = his_words.get("as_of")
    if his_words.get("state") == "ok" and day:
        return _block("ok", day, src, "Nothing in his own words yet.", {"text": f"His latest words are from {day_in_words(day)}."})
    return _block(his_words.get("state") or "absent", day, src, his_words.get("absent_text") or "Nothing in his own words yet.")


def life_rows(b: dict, his_words: dict, today: str) -> dict:
    parts = {
        "body": _row(SOURCES["journey"], "The weight so far", b["journey"], _life_body, "No weigh-in yet.", today),
        "training": _row(
            SOURCES["session"], "Today's session", b["session"], _life_training(today), "No session is planned for today.", today
        ),
        "sleep": _row(
            [SOURCES["pulse"], SOURCES["sleep"]],
            "Last night's sleep",
            b["sleep"],
            _life_sleep(b["pulse"]),
            "No sleep has been recorded yet.",
            today,
        ),
        "food": _row(SOURCES["nutrition"], "The food log", b["nutrition"], _life_food, "No food has been logged yet.", today),
        "habits": _row(SOURCES["habits"], "The daily habits", b["habits"], _life_habits, "No habits have been recorded yet.", today),
        "supplements": _row(
            SOURCES["supplements"], "The supplement stack", b["supplements"], _life_supplements, "No supplements are listed.", today
        ),
        "experiments": _row(
            SOURCES["experiments"], "The experiments", b["experiments"], _life_experiments(today), "No experiments are listed.", today
        ),
        "mind": _life_mind(his_words),
    }
    src = sorted({str(x) for p in parts.values() for x in (p["source"] if isinstance(p["source"], list) else [p["source"]]) if x})
    if all(p["state"] == "unavailable" for p in parts.values()):
        return _unavailable(src, "How the whole thing is going")
    return _block("ok", today, src, "Nothing is recorded yet.", {"order": list(LIFE_ORDER), "rows": parts})
