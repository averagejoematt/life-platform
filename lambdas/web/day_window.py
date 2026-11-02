"""web/day_window.py — the optional day window on three read routes (#5584, epic #5577).

The Day pages need the session, the night and the food for ANY day of the experiment, but
``/api/workouts``, ``/api/sleep_detail`` and ``/api/nutrition_overview`` each served only a
trailing window (30 days of Hevy sessions, 30 nights, 30 food days). Owner decision 4
(2026-11-02): add date parameters to these three read-only routes rather than build a
publication archive. This module is the ONE parse of that window, shared by all three.

THE CONTRACT (the ``/api/series`` pattern — ``web.site_api_series._window``):

  * ``?from=YYYY-MM-DD&to=YYYY-MM-DD`` — an inclusive day window. A missing ``to`` is today;
    a missing ``from`` is the start of a ``MAX_SPAN_DAYS`` window ending at ``to``.
  * ``?date=YYYY-MM-DD`` — sugar for ``from=to=date``. Combining it with ``from``/``to`` is a 400.
  * Floor ``EXPERIMENT_START`` and ceiling today (Pacific) — the window is clamped into
    that range. A span over ``MAX_SPAN_DAYS`` is clamped to the ``MAX_SPAN_DAYS`` ending at
    ``to``. The served window is echoed back as ``window: {from, to}``.
  * A value that is not a calendar day, ``from`` after ``to``, or a window lying wholly
    outside the experiment (before genesis, or in the future) is a 400 in the one error
    envelope (``site_api_common._error``).
  * No parameter (none of the three keys carries a value) → ``None``: the route serves its
    default response, byte for byte as before. Other query keys are ignored, as they were.

The routes read the SAME partitions over the SAME ``DATE#`` key range as their default path
— only the bounds move — and project the same per-day shape, so no new field is served and
the nutrition/sleep privacy rules apply unchanged. CloudFront's ``/api/*`` cache policy keys
on every query string (``cdk/stacks/web_cloudfront_policies.py`` ``default_cache``), so a
windowed response never answers a default request, or another window.
"""

from __future__ import annotations

import json
from typing import Any

from common.pacific_time import pacific_today, parse_day_key, shift_day_key

from web.site_api_common import EXPERIMENT_START, _error

#: The longest window one request serves (days) — a quarter. The Day pages ask for one day;
#: a week or a month is the working range; this bounds the read, not the use.
MAX_SPAN_DAYS = 92
PARAM_KEYS = ("from", "to", "date")
BAD_DAY = "from/to/date must be calendar days (YYYY-MM-DD)."
BOTH_FORMS = "Use date= or from=/to=, not both."
REVERSED = "from must not be after to."
OUTSIDE = "The window lies outside the experiment (from {floor} through today)."


def _param(qs: dict | None, key: str) -> str:
    return str((qs or {}).get(key) or "").strip()


def requested(qs: dict | None) -> bool:
    """Does this query ask for a window? (Any of ``from``/``to``/``date`` carries a value.)"""
    return any(_param(qs, k) for k in PARAM_KEYS)


def parse(qs: dict | None, today: str | None = None, floor: str | None = None) -> tuple[tuple[str, str] | None, dict | None]:
    """``(window, None)`` for a servable request, ``(None, error_response)`` for a 400.

    ``window`` is ``None`` when no window was asked for (the default response), else the
    clamped inclusive ``(from, to)`` pair.
    """
    if not requested(qs):
        return None, None
    today = today or pacific_today()
    floor = floor or EXPERIMENT_START
    day, start, end = _param(qs, "date"), _param(qs, "from"), _param(qs, "to")
    if day and (start or end):
        return None, _error(400, BOTH_FORMS)
    if day:
        start = end = day
    end = end or today
    if parse_day_key(end) is None or (start and parse_day_key(start) is None):
        return None, _error(400, BAD_DAY)
    start = start or shift_day_key(end, -(MAX_SPAN_DAYS - 1))
    if start > end:
        return None, _error(400, REVERSED)
    start, end = max(start, floor), min(end, today)
    if start > end:
        return None, _error(400, OUTSIDE.format(floor=floor))
    if (parse_day_key(end) - parse_day_key(start)).days >= MAX_SPAN_DAYS:  # both parsed above
        start = shift_day_key(end, -(MAX_SPAN_DAYS - 1))
    return (start, end), None


def attach(resp: dict, window: tuple[str, str] | None) -> dict:
    """Echo the served window on a windowed 200. The default response is returned untouched."""
    if window is None or resp.get("statusCode") != 200:
        return resp
    body: dict[str, Any] = json.loads(resp["body"])
    body["window"] = {"from": window[0], "to": window[1]}
    return {**resp, "body": json.dumps(body)}
