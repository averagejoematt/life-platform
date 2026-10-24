"""lambdas/web/og_front_frame.py — the front page's daily mark as a link-preview card (#4646).

THE RULING
──────────
The owner ruled on 2026-10-23 that the front page's daily mark is drawing C, "the year
frame", and the issue's fix sketch makes the same drawing the front page's ``og:image``:
1200x630, redrawn daily, with no new Lambda and no new schedule (epic #4580, rule 5). So the
card is one more entry in ``og_image_lambda.PAGES`` (``og-front``), drawn by the existing
19:30 UTC ``og-image-generator`` run.

THE DRAWING (the same one ``site/assets/js/ck_front.js::yearFrame`` draws on the page)
──────────────────────────────────────────────────────────────────────────────────────
One frame one year (365 days) wide, starting on the experiment's first day; past a year it
is the 365 days ending today. The frame's top is the start weight and its floor the goal.
Each weigh-in is one thin column at its day, as tall as the weight still above the goal
(``clamp((lbs - goal) / (start - goal), 0, 1)``), standing on the floor. A day with no
weigh-in draws nothing; the empty right of the frame is the year not yet lived. Columns are
neutral ink: a column is weight still to lose, and the kit's accent means progress only.

WHERE THE NUMBERS COME FROM
───────────────────────────
``generated/public_stats.json`` carries only the last 30 weigh-ins, which cannot fill a
year, and the Lambda's IAM reads nothing else that would. So the card reads the site's OWN
public API, ``/api/edition`` (the payload the front page itself draws from), over HTTPS with
``urllib.request`` — the same pattern ``og_moments`` already uses from this Lambda. It can
therefore never say more than the site already publishes, and no IAM changes.

FAIL SAFE
─────────
Any fetch error, unusable block or missing number makes ``load_front_inputs`` return None;
the builder then returns None and the handler skips writing ``og-front`` at all, so
yesterday's file stays served. A wrong number is never drawn.

WHY A SEPARATE MODULE
─────────────────────
``og_image_lambda`` imports Pillow at module scope and Pillow is absent from the CI runner
(see tests/test_og_card_coverage.py). Everything here is pure stdlib so
``tests/test_og_front_frame_4646.py`` can test the geometry, the copy and the fail-safe;
the builder only puts on the canvas what this module returns.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable

from common.pacific_time import day_in_words, parse_day_key, shift_day_key

YEAR_DAYS = 365
EDITION_URL = "https://averagejoematt.com/api/edition"
# Well under the Lambda's 60 s timeout, and kept short on purpose: the whole daily run
# already takes ~50-57 s (CloudWatch REPORT lines, 10-10..10-23), almost all of it the
# moments sweep. A slow API must cost this card, never the sweep.
FETCH_TIMEOUT_S = 6

_USABLE_STATES = ("ok", "stale")


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _days_between(a: str, b: str) -> int:
    da, db = parse_day_key(a), parse_day_key(b)
    assert da is not None and db is not None
    return (db - da).days


def year_frame(series: Any, today_iso: str, start: Any, goal: Any, start_iso: str | None) -> dict | None:
    """{"from": iso, "cols": [{"date", "lbs", "day", "height"}]} or None.

    A line-for-line port of ``ck_front.js::yearFrame``: ``day`` is 0..364 from the frame's
    first day, ``height`` the weight still above the goal as a share of the whole distance
    (0 at the goal, 1 at the start or above). The frame starts on ``start_iso``; past a year
    it is the 365 days ending today. Weigh-ins after today are ignored. None without a
    start above the goal, a parseable today, or a weigh-in inside the frame.
    """
    s, g = _num(start), _num(goal)
    if parse_day_key(today_iso) is None or s is None or g is None or s <= g:
        return None
    weighed = [
        (w["date"], _num(w.get("lbs")))
        for w in (series or [])
        if isinstance(w, dict) and parse_day_key(w.get("date")) is not None and _num(w.get("lbs")) is not None and w["date"] <= today_iso
    ]
    if start_iso and parse_day_key(start_iso) is not None and start_iso <= today_iso:
        frm: str | None = start_iso
    else:
        frm = min((d for d, _ in weighed), default=None)
    if not frm:
        return None
    if _days_between(frm, today_iso) >= YEAR_DAYS:
        frm = shift_day_key(today_iso, -(YEAR_DAYS - 1))
    by_day: dict[str, float] = {}
    for d, lbs in weighed:
        if d >= frm and lbs is not None:
            by_day[d] = lbs  # the last reading served for a day wins, as the JS Map does
    cols = [
        {"date": d, "lbs": by_day[d], "day": _days_between(frm, d), "height": max(0.0, min(1.0, (by_day[d] - g) / (s - g)))}
        for d in sorted(by_day)
    ]
    return {"from": frm, "cols": cols} if cols else None


def column_rects(frame: dict, x0: float, y0: float, width: float, height: float) -> list[tuple[float, float, float, float]]:
    """The columns as (left, top, right, bottom) pixel boxes inside a frame box.

    Day ``d`` sits at ``x0 + d * width / 365``, 80% of a day wide (at least 1 px); its
    height is ``height * share`` (at least 1 px, so a weigh-in at the goal still shows),
    standing on the floor ``y0 + height``. Mirrors ``ck_front.js::markHTML``.
    """
    step = width / YEAR_DAYS
    w = max(1.0, step * 0.8)
    floor = y0 + height
    rects = []
    for c in frame["cols"]:
        h = max(1.0, c["height"] * height)
        left = x0 + c["day"] * step
        rects.append((left, floor - h, left + w, floor))
    return rects


def _goal_words(goal: float) -> str:
    """185.0 -> "185", 185.5 -> "185.5" (ck_front.js: String(Number(goal.toFixed(1))))."""
    r = round(goal, 1)
    return str(int(r)) if r == int(r) else f"{r:.1f}"


def front_card_lines(frame: dict, start: float, goal: float) -> tuple[str, str]:
    """(the premise line, the line naming the frame). Numbers from served data only; the
    day is in words, never ISO; no count of earlier starts."""
    g = _goal_words(goal)
    premise = f"{start:.1f} to {g}, in public. Every coach call checked."
    names = f"One year from {day_in_words(frame['from'], weekday=False)}. One column per weigh-in, as tall as the weight still above {g}."
    return premise, names


def parse_edition(payload: Any) -> dict | None:
    """/api/edition -> {"series", "start", "goal", "start_iso"} or None when any part the
    card needs is absent or unusable (never a partial card)."""
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("data"), dict) and "blocks" not in payload:
        payload = payload["data"]
    blocks = payload.get("blocks")
    if not isinstance(blocks, dict):
        return None
    today, week = blocks.get("today"), blocks.get("week")
    for b in (today, week):
        if not isinstance(b, dict) or b.get("state") not in _USABLE_STATES or not isinstance(b.get("data"), dict):
            return None
    assert isinstance(today, dict) and isinstance(week, dict)
    t = today["data"]
    start, goal = _num(t.get("start_weight_lbs")), _num(t.get("goal_weight_lbs"))
    start_iso = t.get("start_date")
    series = week["data"].get("weight_series")
    if start is None or goal is None or start <= goal or parse_day_key(start_iso) is None or not isinstance(series, list):
        return None
    return {"series": series, "start": start, "goal": goal, "start_iso": start_iso}


def fetch_edition(url: str = EDITION_URL, timeout: float = FETCH_TIMEOUT_S, opener: Callable[..., Any] | None = None) -> dict | None:
    """GET the public edition. None (and a log line) on ANY failure."""
    open_ = opener or urllib.request.urlopen
    try:
        req = urllib.request.Request(url, headers={"accept": "application/json", "user-agent": "life-platform-og-image-generator"})
        with open_(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            if status != 200:
                print(f"[og-front] edition fetch HTTP {status}; skipping the card")
                return None
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[og-front] edition fetch failed ({type(e).__name__}: {e}); skipping the card")
        return None


def load_front_inputs(today_iso: str, fetch: Callable[[], Any] | None = None) -> dict | None:
    """Everything the card draws, or None (fail safe: the handler keeps yesterday's file)."""
    payload = (fetch or fetch_edition)()
    if payload is None:
        return None
    parsed = parse_edition(payload)
    if parsed is None:
        print("[og-front] /api/edition lacks a usable today/week block or start/goal; skipping the card")
        return None
    frame = year_frame(parsed["series"], today_iso, parsed["start"], parsed["goal"], parsed["start_iso"])
    if frame is None:
        print("[og-front] no weigh-in inside the year frame; skipping the card")
        return None
    premise, names = front_card_lines(frame, parsed["start"], parsed["goal"])
    return {"frame": frame, "start": parsed["start"], "goal": parsed["goal"], "premise": premise, "names": names}
