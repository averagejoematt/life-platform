"""intelligence/training_session_facts.py — the AI training analyst's session facts over THE count (#5398).

Split out of `ai_expert_analyzer_lambda` (a module at its size ceiling). The analyst summed Hevy's minutes
beside the Strava minutes and counted Strava day rows as sessions, so a gym visit (Hevy's whole-session push
plus the ride inside it) read as lift + ride. This reads `training.session_count` (THE count): a visit is
counted once and its minutes are claimed once. Pure — no I/O.
"""

from __future__ import annotations

from typing import Any

from training import session_count


def session_facts(strava_rows: Any, hevy_rows: Any) -> dict[str, Any]:
    """`sessions`/`minutes` = every visit once, minutes claimed once; `outside_*` = the visits with no Hevy
    session in them (the aerobic/NEAT secondary signal); `other_parts` = the non-lifting parts by sport."""
    vs = session_count.visits(strava=strava_rows, hevy=hevy_rows)
    outside = [v for v in vs if not v["hevy_sessions"]]
    other: dict[str, int] = {}
    for v in vs:
        for p in v["parts"]:
            if p["family"] != "strength":
                other[p["sport"]] = other.get(p["sport"], 0) + 1
    return {
        "sessions": len(vs),
        "minutes": sum(v["seconds"] for v in vs) / 60.0,
        "outside_sessions": len(outside),
        "outside_min": sum(v["seconds"] for v in outside) / 60.0,
        "other_parts": other,
    }
