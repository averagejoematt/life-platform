"""web/journey_progress.py — the ONE arithmetic behind the displayed weight-journey figures.

Review 2026-11-14 (growth-2): the weekly recap share card read "36.7 lbs down" while the site read 38.8 on the same
day. Two writers — ``/api/journey`` and the public stats file — each derived lost / remaining / progress on their
own, from two different weigh-ins, and neither figure carried its weigh-in's date. This module is the arithmetic both
now call, so for one weigh-in there is one figure; the date travels beside it as ``weight_as_of``
(``web.site_stats_refresh_lambda``, ``emails.daily_brief_lambda``) and the share cards print it (``web.og_moments``).

Stdlib only, pure: no I/O, no clock.
"""

from __future__ import annotations

import math


def displayed_progress(start_weight_lbs: object, goal_weight_lbs: object, current_weight_lbs: object) -> tuple | None:
    """THE displayed weight-journey figures from one weigh-in, as ``(current, lost, remaining, progress_pct)``.
    None when any input is absent, non-numeric or non-finite.

    The #1225 display policy, in one place: weights are shown to ONE decimal and every delta is derived from those
    same displayed values, so shown_start − shown_now == shown_lost exactly. ``lost`` is signed (start − current)."""
    try:
        start, goal, cur = (round(float(v), 1) for v in (start_weight_lbs, goal_weight_lbs, current_weight_lbs))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (start, goal, cur)):
        return None
    lost = round(start - cur, 1)
    return cur, lost, round(cur - goal, 1), (round(lost / (start - goal) * 100, 1) if start != goal else 0)
