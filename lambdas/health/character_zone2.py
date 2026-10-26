"""health/character_zone2.py - the character sheet's Zone 2 input: THE Zone 2 computation (#5389).

Split out of `character_engine` (a module-size-baselined file) - the engine's movement pillar calls
`zone2_minutes_7d` and nothing else here.
"""

from __future__ import annotations

from typing import Any

from training import zone2_minutes as z2m  # #4627: THE Zone 2 computation


def zone2_minutes_7d(data: dict[str, Any]) -> float:
    """Trailing-7-day Zone 2 minutes from THE Zone 2 computation (`training.zone2_minutes`, #4627).

    #5389: this read `zone2_minutes` / `time_in_zone_2_minutes` off the Strava rows — keys no writer
    stores (Strava writes `zone2_seconds` per activity; Whoop's zones sit on workout sub-rows) — so the
    component scored 0 whatever was trained. Now the same `zone2_window` over the same 7 dates
    `/api/zone2` serves as `trailing_7d`, each session counted once across Whoop, Strava and the Apple
    Watch (#5353) with Hevy anchoring a gym visit's parts (#5369). Inputs ride on `data`:
    `strava_7d`, `whoop_7d`, `apple_7d` (the last two fetched one UTC day past the window, their keys
    are UTC days) and `hevy_7d`. The window ends on `data["date"]`, the day the sheet scores."""

    def _live(key: str) -> list:
        # /api/zone2's `_query_source` drops superseded (`tombstone`) rows from every partition; so does this
        return [r for r in (data.get(key) or []) if not r.get("tombstone")]

    strava = _live("strava_7d")
    end = str(data.get("date") or "")[:10]
    if not end:
        end = max((str(r.get("date") or str(r.get("sk", ""))[5:15])[:10] for r in strava), default="")
    if not end:
        return 0.0
    start, end = z2m.trailing_window(end)
    whoop, apple, hevy = _live("whoop_7d"), _live("apple_7d"), _live("hevy_7d")
    sessions = z2m.counted_sessions(strava, whoop, apple, hevy_rows=hevy)
    return float(z2m.zone2_window(strava, whoop, hevy, start, end, sessions=sessions)["zone_2_minutes"])
