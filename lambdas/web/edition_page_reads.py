"""edition_page_reads.py — the /api/edition blocks for what the pages read beside it (#4582 box 1).

Box 1 of #4582 is "the front page makes one data request". The front page read the edition and
then ten more routes — ``/api/calls`` for the clearest miss, ``/api/character`` for the sheet's
level, and seven days of ``/api/coach_moves`` for the argument and the last-heard line — and the
week page read ``/api/weekly_priority`` and ``/api/character``. Each of those is a block of the
edition now, built here, with the block contract every other block keeps (``state``, ``as_of``,
``source``, ``absent_text``, ``data``) and its route's own shape inside ``data``, so the page's
builders read the block unchanged.

Split from ``site_api_edition`` for the module-size ceiling (#1665), the way the scorecard was
(``web.edition_scorecard``); ``compose()`` and ``handle_edition()`` import it lazily.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Callable

from common.pacific_time import day_in_words, parse_day_key

from web.site_api_edition import SOURCES, _block, _days_between, _num, _unavailable, body_of

MOVES_DAYS = 7  # the argument's window: the edition's day and the six before it (ck_front.js ARGUMENT_DAYS)
CHARACTER_STALE_DAYS = 2  # the sheet is computed every morning
LEAD_READ_STALE_DAYS = 8  # a weekly read, the chapter's bound

# Each block carries its route's own body (or the subset the pages read, in the route's own
# shape), so the page builders that read those routes read the block's ``data`` unchanged.


def moves_days(today: str, n: int = MOVES_DAYS) -> list:
    """The edition's day and the ``n - 1`` before it, newest first."""
    end = parse_day_key(today)
    return [(end - timedelta(days=i)).isoformat() for i in range(n)] if end else []


def read_moves(read_route: Callable[[str, dict], Any], today: str) -> dict:
    """The seven days of ``/api/coach_moves`` bodies, one in-process read per day, newest
    first. A day whose read failed is that route's own unavailable body for the day — never
    an empty day, which would read as "nobody spoke"."""
    from web.site_api_coach_moves import UNAVAILABLE

    days = []
    for day in moves_days(today):
        body = body_of(read_route(SOURCES["moves"], {"date": day}))
        days.append(
            body
            if body is not None
            else {"state": "unavailable", "date": day, "source": SOURCES["moves"], "absent_text": UNAVAILABLE, "lines": []}
        )
    return {"days": days}


def moves_block(body: dict | None, today: str) -> dict:
    """The last seven days of coach lines, each day exactly as ``/api/coach_moves`` serves it.

    ``body`` is ``read_moves``' ``{"days": [...]}``, or — read through the route with no
    date, as ``read_bodies`` does without its narrow readers — the one day it served."""
    src = SOURCES["moves"]
    what = "The last seven days of coach lines"
    if body is None:
        return _unavailable(src, what)
    listed = body.get("days")
    raw: list = listed if isinstance(listed, list) else [body]
    window = set(moves_days(today))
    days = sorted(
        (d for d in raw if isinstance(d, dict) and str(d.get("date") or "") in window),
        key=lambda d: str(d["date"]),
        reverse=True,
    )
    if not days or all(d.get("state") == "unavailable" for d in days):
        return _unavailable(src, what)
    spoke = [d for d in days if d.get("state") == "ok" and d.get("lines")]
    if not spoke:
        return _block("absent", None, src, "No coach line is recorded in these seven days.")
    return _block("ok", str(spoke[0]["date"]), src, "No coach line is recorded in these seven days.", {"days": days})


#: The fields of a settled call the front page reads (ck_call.js lastCallPick/lastCallHTML,
#: ck_verdict.js showcasePair/callVerdictTag). The rest of a call (its claim verbatim, the
#: records, a bet's sides) is on its own page, read from /api/calls there.
FRONT_CALL_FIELDS = (
    "id",
    "kind",
    "coach_id",
    "coach_name",
    "called",
    "called_short",
    "happened_short",
    "settled_date",
    "verdict",
    "verdict_text",
    "actual",
    "simple_guess",
)


def calls_block(body: dict | None, today: str) -> dict:
    """The settled calls, newest first, as ``/api/calls`` serves them — only the fields the
    front page reads, and none settled after the edition's day (one ``as_of``)."""
    src = SOURCES["calls"]
    what = "The list of settled calls"
    if body is None or body.get("state") == "unavailable":
        return _unavailable(src, what)
    calls = [
        {k: c[k] for k in FRONT_CALL_FIELDS if k in c}
        for c in body.get("calls") or []
        if isinstance(c, dict) and c.get("id") and parse_day_key(str(c.get("settled_date") or "")) and str(c["settled_date"]) <= today
    ]
    nothing = str(body.get("absent_text") or "") or "No call has been checked against the data yet."
    if not calls:
        return _block("absent", None, src, nothing)
    calls.sort(key=lambda c: str(c["settled_date"]), reverse=True)
    return _block("ok", str(calls[0]["settled_date"]), src, nothing, {"calls": calls})


def sheet_block(body: dict | None, today: str) -> dict:
    """The character sheet's level and how many areas of his life it is across."""
    src = SOURCES["character"]
    if body is None:
        return _unavailable(src, "The character sheet")
    got = body.get("character")
    c: dict = got if isinstance(got, dict) else {}
    if _num(c.get("level")) is None:
        return _block("absent", None, src, "The character sheet has no level yet.")
    data = {"character": {k: c.get(k) for k in ("level", "composite_pillar_count", "composite_pillar_total")}}
    day = str(c.get("as_of_date") or "") or None
    age = _days_between(day, today) if day else None
    if age is not None and age > CHARACTER_STALE_DAYS:
        return _block("stale", day, src, f"The character sheet has not been updated since {day_in_words(day)}.", data)
    return _block("ok", day or today, src, "The character sheet has no level yet.", data)


def lead_read_block(body: dict | None, today: str) -> dict:
    """The lead coach's weekly read, as ``/api/weekly_priority`` serves it."""
    src = SOURCES["priority"]
    if body is None:
        return _unavailable(src, "The lead coach's weekly read")
    text = body.get("weekly_priority")
    day = str(body.get("data_through") or "")
    nothing = "No weekly read from the lead coach yet."
    if not isinstance(text, str) or not text.strip() or not parse_day_key(day):
        return _block("absent", None, src, nothing)
    data = {"weekly_priority": text, "data_through": day, "coach_name": body.get("coach_name")}
    age = _days_between(day, today)
    if age is not None and age > LEAD_READ_STALE_DAYS:
        return _block("stale", day, src, f"No weekly read from the lead coach since {day_in_words(day)}.", data)
    return _block("ok", day, src, nothing, data)
