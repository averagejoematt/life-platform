"""edition_scorecard.py — /api/edition's ``scorecard`` block (#4595, epic #4580).

The whole-life scorecard: one measure per area over the last seven days, each decided HERE by
a written rule. Split out of ``web.site_api_edition`` (the module-size ceiling, #1665) behind the
same entrypoint: ``site_api_edition.compose`` calls ``scorecard(...)`` and nothing else here is
public to the route. Pure — it reads only the upstream bodies ``compose`` already holds (no new
upstream, so the edition's latency budget, #4607, is unchanged) and the record block.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from common.pacific_time import day_in_words, pacific_date_of, parse_day_key, parse_iso_utc

from web.site_api_edition import (
    SLEEP_BAR_HOURS,
    SOURCES,
    WEEK_DAYS,
    _block,
    _by_date,
    _fmt_num,
    _num,
    _training_minutes,
    _unavailable,
)

# One measure per area over the last seven days, each decided HERE by a written rule. The
# rule's own words and the day the rules were set are served with every row, so the page
# can print them and a reader can check the verdict against the number beside it.
#
# Four verdicts, never more: going well · faster than planned · not yet · not enough data.
# A row whose source failed is ``unavailable`` (the block contract), never a verdict. A row
# with too few readings is "not enough data" — never a guess from three days.
#
# Never computed or served here (ADR-104): a calorie-deficit figure, a single-day body-fat
# number, a percentage, anything before the experiment's start (``start_date`` clips every
# window), and "because" between a coach's advice and a result.
#
# The owner's open rulings (#4595), each built behind its default until ruled: Body may read
# "faster than planned" and Mind "not yet" in public (default: both shown — they are the
# rule's honest outcomes); Reading and People are not areas; nothing about connection.
SCORECARD_RULES_SET = "2026-10-09"
SCORECARD_ORDER = ("body", "training", "sleep", "food", "mind", "ai")
SCORECARD_NAMES = {"body": "Body", "training": "Training", "sleep": "Sleep", "food": "Food", "mind": "Mind", "ai": "The AI"}

GOING_WELL = "going_well"
FASTER_THAN_PLANNED = "faster_than_planned"
NOT_YET = "not_yet"
NOT_ENOUGH_DATA = "not_enough_data"
VERDICT_WORDS = {
    GOING_WELL: "Going well",
    FASTER_THAN_PLANNED: "Faster than planned",
    NOT_YET: "Not yet",
    NOT_ENOUGH_DATA: "Not enough data",
}

BODY_MIN_WEIGHINS = 3  # weigh-ins needed in EACH seven-day window for an average to mean anything
BODY_FAST_LBS_PER_WEEK = 2.5  # the planned ceiling on the weekly loss
TRAINING_MIN_DAYS = 5  # days with a training record (today's not-yet-logged zero is not one)
TRAINING_WELL_DAYS = (4, 6)  # trained on 4 to 6 days: at least one rest day
SLEEP_MIN_NIGHTS = 5
SLEEP_WELL_NIGHTS = 5  # nights of SLEEP_BAR_HOURS or more
FOOD_MIN_LOGGED = 5
FOOD_WELL_DAYS = 5  # logged days at or above the plan's protein floor
MIND_WELL_DAYS = 3  # days with an entry in his own words
MIND_SERVE_LIMIT = 10  # /api/owner_words serves this many entries, newest first (content.owner_words.SERVE_LIMIT)
AI_MIN_CALLS = 30  # checked calls before the coaches are compared with a simple guess at all

SCORECARD_RULE_TEXT = {
    "body": (
        f"The average of the last seven days' weigh-ins against the seven days before. Going well when it is lower; "
        f"faster than planned when it fell more than {_fmt_num(BODY_FAST_LBS_PER_WEEK)} lb in the week. "
        f"Fewer than {BODY_MIN_WEIGHINS} weigh-ins in either week is not enough data."
    ),
    "training": (
        f"Days trained in the last seven. Going well at {TRAINING_WELL_DAYS[0]} to {TRAINING_WELL_DAYS[1]}, so at least one rest day. "
        f"Fewer than {TRAINING_MIN_DAYS} days recorded is not enough data."
    ),
    "sleep": (
        f"Nights of {_fmt_num(SLEEP_BAR_HOURS)} hours or more in the last seven. Going well at {SLEEP_WELL_NIGHTS}. "
        f"Fewer than {SLEEP_MIN_NIGHTS} nights recorded is not enough data."
    ),
    "food": (
        f"Logged days at or above the plan's protein floor in the last seven. Going well at {FOOD_WELL_DAYS}. "
        f"Fewer than {FOOD_MIN_LOGGED} logged days is not enough data."
    ),
    "mind": f"Days in the last seven with an entry in his own words. Going well at {MIND_WELL_DAYS}.",
    "ai": (
        f"The coaches' checked calls against a simple guess that nothing changes from the last reading. "
        f"Going well when they beat it. Fewer than {AI_MIN_CALLS} checked calls is not enough data."
    ),
}


def _window(today: str, start_date: str, offset: int = 0) -> list:
    """Seven Pacific days ending ``offset`` weeks before ``today``, never before ``start_date``."""
    end = parse_day_key(today)
    start = parse_day_key(start_date or "")
    if not end:
        return []
    days = [end - timedelta(days=offset * WEEK_DAYS + i) for i in range(WEEK_DAYS - 1, -1, -1)]
    return [d.isoformat() for d in days if not start or d >= start]


def _verdict_row(area: str, src: Any, today: str, verdict: str, text: str) -> dict:
    data = {
        "name": SCORECARD_NAMES[area],
        "verdict": verdict,
        "verdict_text": VERDICT_WORDS[verdict],
        "text": text,
        "rule": SCORECARD_RULE_TEXT[area],
    }
    return _block("ok", today, src, f"{SCORECARD_NAMES[area]} has no verdict this week.", data)


def score_body(pulse: dict | None, today: str, start_date: str) -> dict:
    src = SOURCES["pulse"]
    if pulse is None:
        return _unavailable(src, "The weigh-ins")
    weights = _by_date(pulse.get("pulse_history"), "weight_lbs")
    now = [weights[d] for d in _window(today, start_date) if weights.get(d) is not None]
    before = [weights[d] for d in _window(today, start_date, offset=1) if weights.get(d) is not None]
    if len(now) < BODY_MIN_WEIGHINS or len(before) < BODY_MIN_WEIGHINS:
        text = f"{len(now)} weigh-ins this week and {len(before)} the week before; {BODY_MIN_WEIGHINS} in each are needed."
        return _verdict_row("body", src, today, NOT_ENOUGH_DATA, text)
    avg_now, avg_before = round(sum(now) / len(now), 1), round(sum(before) / len(before), 1)
    change = round(avg_now - avg_before, 1)
    way = f"down {_fmt_num(-change)} lb from" if change < 0 else f"up {_fmt_num(change)} lb from" if change > 0 else "level with"
    text = f"Seven-day average {avg_now:.1f} lb, {way} the seven days before."
    if change >= 0:
        verdict = NOT_YET
    elif -change > BODY_FAST_LBS_PER_WEEK:
        verdict = FASTER_THAN_PLANNED
    else:
        verdict = GOING_WELL
    return _verdict_row("body", src, today, verdict, text)


def score_training(training: dict | None, today: str, start_date: str) -> dict:
    src = SOURCES["training"]
    if training is None:
        return _unavailable(src, "Training")
    minutes = _training_minutes(training.get("daily_modality_minutes_30d"), today)
    seen = [minutes[d] for d in _window(today, start_date) if minutes.get(d) is not None]
    trained = sum(1 for m in seen if m > 0)
    if len(seen) < TRAINING_MIN_DAYS:
        return _verdict_row("training", src, today, NOT_ENOUGH_DATA, f"{len(seen)} days recorded; {TRAINING_MIN_DAYS} are needed.")
    low, high = TRAINING_WELL_DAYS
    verdict = GOING_WELL if low <= trained <= high else NOT_YET
    return _verdict_row("training", src, today, verdict, f"Trained on {trained} of {len(seen)} days recorded.")


def score_sleep(pulse: dict | None, today: str, start_date: str) -> dict:
    src = SOURCES["pulse"]
    if pulse is None:
        return _unavailable(src, "Sleep")
    hours = _by_date(pulse.get("pulse_history"), "sleep_hours")
    seen = [hours[d] for d in _window(today, start_date) if hours.get(d) is not None]
    if len(seen) < SLEEP_MIN_NIGHTS:
        return _verdict_row("sleep", src, today, NOT_ENOUGH_DATA, f"{len(seen)} nights recorded; {SLEEP_MIN_NIGHTS} are needed.")
    good = sum(1 for h in seen if h >= SLEEP_BAR_HOURS)
    verdict = GOING_WELL if good >= SLEEP_WELL_NIGHTS else NOT_YET
    text = f"{_fmt_num(SLEEP_BAR_HOURS)} hours or more on {good} of {len(seen)} nights recorded."
    return _verdict_row("sleep", src, today, verdict, text)


def score_food(nutrition: dict | None, today: str, start_date: str) -> dict:
    src = SOURCES["nutrition"]
    floor = _num(((nutrition or {}).get("nutrition") or {}).get("protein_floor_g"))
    # The floor is the plan's (served by the route from the plan root, #4540) — never a literal here.
    if nutrition is None or floor is None:
        return _unavailable(src, "The food log")
    protein = _by_date(nutrition.get("nutrition_trend"), "protein_g")
    logged = [protein[d] for d in _window(today, start_date) if protein.get(d) is not None]
    if len(logged) < FOOD_MIN_LOGGED:
        return _verdict_row("food", src, today, NOT_ENOUGH_DATA, f"{len(logged)} days logged; {FOOD_MIN_LOGGED} are needed.")
    hit = sum(1 for g in logged if g >= floor)
    verdict = GOING_WELL if hit >= FOOD_WELL_DAYS else NOT_YET
    text = f"At or above the {_fmt_num(floor)} g protein floor on {hit} of {len(logged)} logged days."
    return _verdict_row("food", src, today, verdict, text)


def score_mind(decisions: dict | None, owner_words: dict | None, today: str, start_date: str) -> dict:
    """Days with an entry in his own words — a dated note (#1569) or an owner-words entry (#4584).

    The owner-words route serves only its newest ``MIND_SERVE_LIMIT`` entries: when all of them
    fall inside the week the count is a floor, not a fact, so a short count reads "not enough
    data" rather than "not yet"."""
    src = [SOURCES["owner_words"], SOURCES["decisions"]]
    if decisions is None or owner_words is None:
        return _unavailable(src, "His own words")
    window = set(_window(today, start_date))
    entries = [e for e in owner_words.get("entries") or [] if isinstance(e, dict) and parse_day_key(str(e.get("date") or ""))]
    days = {str(e["date"]) for e in entries} & window
    for d in decisions.get("decisions") or []:
        if isinstance(d, dict) and str(d.get("note") or "").strip() and parse_iso_utc(d.get("note_at")) is not None:
            day = pacific_date_of(str(d["note_at"]))
            if day in window:
                days.add(day)
    n = len(days)
    text = f"An entry in his own words on {n} of {len(window)} days."
    if n >= MIND_WELL_DAYS:
        return _verdict_row("mind", src, today, GOING_WELL, text)
    truncated = len(entries) >= MIND_SERVE_LIMIT and all(str(e["date"]) in window for e in entries)
    return _verdict_row("mind", src, today, NOT_ENOUGH_DATA if truncated else NOT_YET, text)


def score_ai(record: dict, today: str) -> dict:
    """The record block's own comparison (#4585): the count is never served without it."""
    src = record.get("source")
    if record.get("state") == "unavailable":
        return _unavailable(src, "The coaches' record")
    data = record.get("data") or {}
    n, skill = data.get("skill_n"), data.get("brier_skill")
    if record.get("state") != "ok" or not isinstance(n, int) or n < AI_MIN_CALLS or not isinstance(skill, (int, float)):
        text = f"Fewer than {AI_MIN_CALLS} checked calls to compare with a simple guess."
        return _verdict_row("ai", src, today, NOT_ENOUGH_DATA, text)
    if data.get("beats_simple_guess"):
        return _verdict_row("ai", src, today, GOING_WELL, f"The coaches beat a simple guess across {n} checked calls.")
    return _verdict_row("ai", src, today, NOT_YET, f"The coaches do not yet beat a simple guess across {n} checked calls.")


def _went_right(rows: dict) -> dict:
    """The fixed block beside the rows: one sourced line for Matthew, one for the engine, or
    "Nothing this week." when no row of theirs is going well."""

    def line(areas: tuple) -> dict:
        for area in areas:
            row = rows.get(area) or {}
            if row.get("state") == "ok" and (row.get("data") or {}).get("verdict") == GOING_WELL:
                return {"area": area, "text": f"{row['data']['name']}: {row['data']['text']}", "source": row.get("source")}
        return {"area": None, "text": "Nothing this week.", "source": None}

    return {"matthew": line(("body", "training", "sleep", "food", "mind")), "engine": line(("ai",))}


def scorecard(b: dict, record: dict, today: str, start_date: str) -> dict:
    rows = {
        "body": score_body(b["pulse"], today, start_date),
        "training": score_training(b["training"], today, start_date),
        "sleep": score_sleep(b["pulse"], today, start_date),
        "food": score_food(b["nutrition"], today, start_date),
        "mind": score_mind(b["decisions"], b["owner_words"], today, start_date),
        "ai": score_ai(record, today),
    }
    src = sorted({str(x) for r in rows.values() for x in (r["source"] if isinstance(r["source"], list) else [r["source"]]) if x})
    if all(r["state"] == "unavailable" for r in rows.values()):
        return _unavailable(src, "The scorecard")
    window = _window(today, start_date)
    data = {
        "order": list(SCORECARD_ORDER),
        "names": dict(SCORECARD_NAMES),  # an unavailable row carries no data, so its name rides here
        "rows": rows,
        "went_right": _went_right(rows),
        "verdicts": dict(VERDICT_WORDS),
        "window": {"from": window[0] if window else None, "to": today},
        "rules_set": SCORECARD_RULES_SET,
        "rules_set_text": f"The rules were set on {day_in_words(SCORECARD_RULES_SET)}.",
    }
    return _block("ok", today, src, "Nothing is scored this week.", data)
