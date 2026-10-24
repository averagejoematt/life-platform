"""coach_checkin_queue_qa.py — the coach check-in queue's age check (#5127).

THE DEFECT THIS EXISTS FOR. From 2026-10-10 to 2026-10-23 the coach check-in queue held the same
three nutrition questions. All three were driven by the food-delivery channel ("Food delivery is
the longest-dark manual channel (196d dark)"), the source #5006 then paused, and an open question
never left the queue — so no other coach was ever asked, and nothing reported it.

The queue tool now retires an open question whose driving source is paused, or that has stood past
its rotation window (`coach_checkin.QUEUE_ROTATE_HOURS`, 72 h; a prescription follow-up keeps its
week), and stamps `last_served_at` each time it hands a question out. This nightly check is the
alarm on that mechanism. It WARNs (the alarmed `qa-smoke-warnings` count) on two things:

* **stuck** — an open question that was SERVED after its rotation deadline. The queue was used and
  did not move: the rotation is broken. This is the "no question changed for 72 hours" condition,
  measured where it can be told apart from a quiet week.
* **dark** — an open question whose driving source is paused. The queue retires these at the next
  call, so one standing overnight is either the pre-#5127 specimen or a retire write failing.

What it deliberately does NOT alarm on: an open question nobody has opened for 72 hours. The queue
moves only when Matthew opens a check-in, and whether he does is a behaviour, not an outage — the
source registry's behavioral/infrastructure rule (a logging lapse is reported, never paged). The ok
line still names the oldest open question's age, so a quiet queue is visible without being red.

Read-only: one bounded Query per coach partition (the same read the queue tool makes).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from coach import coach_checkin as cc

CHECK_NAME = "coach_checkin:queue_age"


def _coach_ids() -> list:
    from coach.persona_registry import OPERATIONAL_SHORT_IDS

    return list(OPERATIONAL_SHORT_IDS)


def _hours(delta: timedelta) -> int:
    return int(delta.total_seconds() // 3600)


def assess(items: list, *, now, paused: set, registry: Optional[dict] = None) -> dict:
    """{open, stuck, dark, oldest_hours} over the queue's rows. Pure."""
    open_items = cc.open_checkins(items)
    stuck, dark, ages = [], [], []
    for it in open_items:
        asked = cc.parse_iso(it.get("asked_at"))
        if asked is not None:
            ages.append(_hours(now - asked))
        src = cc.question_source(it, registry)
        if src and src in paused:
            dark.append((it, src))
            continue
        served = cc.parse_iso(it.get("last_served_at"))
        if asked is not None and served is not None and served >= asked + timedelta(hours=cc.rotate_hours_for(it)):
            stuck.append((it, _hours(served - asked)))
    return {"open": open_items, "stuck": stuck, "dark": dark, "oldest_hours": max(ages) if ages else None}


def _name(it: dict) -> str:
    return f"{it.get('coach_id') or '?'}/{it.get('sk')}"


def check_queue_age(table, Check, tier, *, coach_ids=None, now=None, paused=None, registry=None):
    c = Check(CHECK_NAME, "Data Freshness", tier)
    now = now or cc.utcnow()
    try:
        items = cc.recent_checkins(table, coach_ids or _coach_ids())
        paused = cc.paused_sources(registry) if paused is None else paused
    except Exception as exc:  # noqa: BLE001
        c.warn(f"coach check-in queue unreadable (no verdict was reached): {type(exc).__name__}: {exc}")
        return [c]
    a = assess(items, now=now, paused=paused, registry=registry)
    problems = []
    if a["stuck"]:
        names = ", ".join(f"{_name(it)} ({h}h old when last served)" for it, h in a["stuck"][:3])
        problems.append(
            f"{len(a['stuck'])} open question(s) were served past the {cc.QUEUE_ROTATE_HOURS}h rotation window and never rotated: "
            f"{names} — the queue is being used and not moving (#5127)"
        )
    if a["dark"]:
        names = ", ".join(f"{_name(it)} (source {src})" for it, src in a["dark"][:3])
        problems.append(
            f"{len(a['dark'])} open question(s) are driven by a PAUSED source: {names} — the next get_coach_checkin_queue call "
            "retires them; standing overnight means it was not called or the retire write failed (#5127, #5006)"
        )
    if problems:
        c.warn("; ".join(problems))
        return [c]
    oldest = "no open question" if a["oldest_hours"] is None else f"oldest open question {a['oldest_hours']}h"
    c.ok(f"coach check-in queue rotating: {len(a['open'])} open, {oldest}, none served past rotation, none on a paused source")
    return [c]
