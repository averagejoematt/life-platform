"""site_api_coach_moves.py — GET /api/coach_moves?date=YYYY-MM-DD: one day's coach lines (#4648).

The preview day page (`/next/v8/day/?d=<date>`, epic #4580) shows what the coaches said on
that day. The lines are the daily moves `coach.coach_moves` writes (#4583, one row a day at
`COACH#eli_marsh / MOVES#<date>`). Before this route the only public read of them was the
NEWEST day, as `/api/coaching-dashboard` `moves` and `/api/edition` `coach_lines`; nothing
served a day by its date.

The narrowest read that does: ONE `GetItem` on that one key, through the role's existing
table read — no new Lambda, no new schedule, no new IAM. A row from before the current
phase is not visible (`singleton_visible`), exactly as it is not for the newest-day read.

WHAT IS SERVED is what the front page printed on that day and nothing more: each line's
coach (no honorific), its move, the words as written, who it replies to and the day a bet
settles. The same filter the edition applies stands here (`honest_text`): a line carrying a
figure the honest-number rules keep off the page is not served by date either. The row's
internals — the fact sheet, the held and dropped lines, the token cost, who sat out and
why — are not part of this contract.

    {state: "ok" | "absent", date, source, absent_text, lines: [...]}

A day with no row, or a row with no servable line, is `absent` with `lines: []` (200): the
day page prints nothing for it. With no `date` the day is today in Pacific time (so the bare
route has a shape to baseline); a `date` that is not a calendar day is a 400; a failed read
is a 503, never an empty day.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from coach import coach_moves
from common.pacific_time import day_in_words, parse_day_key
from experiment.phase_filter import singleton_visible

from web.site_api_common import PT, _decimal_to_float, _error, _ok, logger
from web.site_api_edition import _HONORIFIC, honest_text, plain_name

SOURCE = "/api/coach_moves"
BAD_DATE = "Name one day as ?date=YYYY-MM-DD."
UNAVAILABLE = "The coaches’ lines for this day are not served right now."


def lines_of(moves: dict | None) -> list:
    """The reader's view of one served day of moves (`coach_moves.served`) — pure."""
    out = []
    for ln in (moves or {}).get("lines") or []:
        text = str((ln or {}).get("text") or "").strip() if isinstance(ln, dict) else ""
        if not text or not ln.get("move") or not honest_text(text):
            continue
        bet = ln.get("bet") if isinstance(ln.get("bet"), dict) else {}
        out.append(
            {
                "coach_id": str(ln.get("coach_id") or ""),
                "coach": plain_name(ln.get("name")),
                "move": ln["move"],
                "move_label": ln.get("move_label"),
                "text": _HONORIFIC.sub("", text),
                "replies_to": plain_name(ln.get("replies_to_name")) or None,
                "bet_settles": bet.get("resolution_date") or None,
            }
        )
    return out


def compose(day: str, item: Any) -> dict:
    """The document for one day from its stored row (or None) — pure."""
    lines = lines_of(coach_moves.served(_decimal_to_float(item))) if isinstance(item, dict) else []
    return {
        "state": "ok" if lines else "absent",
        "date": day,
        "source": SOURCE,
        "absent_text": f"No coach line is recorded for {day_in_words(day)}.",
        "lines": lines,
    }


def handle_coach_moves(event, *, table, today: str | None = None):
    """GET /api/coach_moves?date=YYYY-MM-DD — that day's coach lines (see module docstring)."""
    asked = str(((event or {}).get("queryStringParameters") or {}).get("date") or "").strip()
    day = asked or today or datetime.now(PT).strftime("%Y-%m-%d")
    if not parse_day_key(day):
        return _error(400, BAD_DATE)
    try:
        item = table.get_item(Key={"pk": coach_moves.PK, "sk": f"{coach_moves.SK_PREFIX}{day}"}).get("Item")
    except Exception as exc:  # noqa: BLE001 — a failed read is said, never served as an empty day
        logger.error(f"[{SOURCE}] read {day} failed: {exc}")
        return _error(503, UNAVAILABLE, state="unavailable", absent_text=UNAVAILABLE)
    return _ok(compose(day, item if item and singleton_visible(item) else None), cache_seconds=300)
