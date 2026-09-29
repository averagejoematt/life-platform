"""common/strava_read_seam.py — the ONE multi-device dedupe of the `strava` partition (#4419).

When two devices recorded the same session (WHOOP and a Garmin watch, both pushing to
Strava — or Hevy's own push of a lifting session), the `strava` day row holds the activity
twice. Before #4419 the duplicates were removed PER CONSUMER: ten modules called
`dedup_activities`, about 65 read the partition, and everything else — including the MCP
history tools chats use to reconstruct 2024–25 — counted every duplicated walk or run twice
(386 walk records over 2024-09-04 → 2025-05-10 for ~214 real walks).

This module is the seam. `strava_read_seam(source, rows)` is called by every generic DDB
reader that can be handed the `strava` partition (the MCP `query_source` chokepoint, the
shared `digest_utils.query_range*`, the site-api `_query_source`, and each module's local
`fetch_range`/`fetch_date`); it is a no-op for any other source. For `strava` it dedupes
each day row's `activities` and recomputes the day totals the ingest writer derives from
them (`day_totals`, pinned to the writer's formula by a parity test). The per-consumer
`dedup_activities` calls that predate the seam still run; the rule is idempotent, so they
are redundant and harmless. `tests/test_shared_modules.py` holds the guard over the SET of
readers (an AST sweep): a new reader that can see `activities` and skips the seam reds CI.

THE PAIR RULE (`dedup_activities`) — two activities of the same sport are one session when
  (a) they start within 15 minutes of each other (the original rule), or
  (b) they come from DIFFERENT devices and >= 80% of the shorter one's wall-clock interval
      lies inside the other's. Found on the real 2024 data: the Garmin records one long walk,
      WHOOP auto-detects it in chunks, and the second chunk starts an hour or more after the
      Garmin's start — 29 surviving same-sport overlaps in the 2024-09-04 → 2025-05-10
      window under rule (a) alone, 22 of them walks.
The RICHER copy is kept (measured distance > duration > polyline). Its heart rate is only
kept if it is plausible: the 2024 Garmin copies of walks carry an average of 49–57 bpm
(physically not a walk; WHOOP recorded 103–124 for the same minutes). When the kept copy's
average HR is missing or below `PLAUSIBLE_ACTIVITY_AVG_HR` and the dropped copy's is not,
the HR family (`average_heartrate`, `max_heartrate`, `has_heartrate`, `zone*_seconds`,
`hr_recovery`) is taken from the dropped copy as a unit and the kept copy is stamped
`hr_from_strava_id`. The distance stays with the device that measured it.

Garmin has been paused since ADR-074, so live days are single-device and this is a no-op on
them; it bites every historical read and would return on the day a second device syncs.
Pure — no boto3, no I/O, no clock reads.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from common.pacific_time import parse_iso_utc  # #1964: THE ISO parser (naive == UTC)

#: The partition this seam normalises. Every other source passes through untouched.
STRAVA_SOURCE = "strava"
#: Start-time window (minutes) inside which two same-sport activities are one session.
START_WINDOW_MIN = 15
#: Share of the shorter activity's interval that must lie inside the other's (rule b).
CONTAINMENT_SHARE = 0.8
#: An activity average HR below this is not a real exercise reading (a walk at 49 bpm is
#: below the owner's resting HR). Used ONLY to choose between two copies of one session.
PLAUSIBLE_ACTIVITY_AVG_HR = 70.0
#: Sport tokens that name the same kind of session (a Zwift ride and a WHOOP-detected ride).
_SPORT_ALIASES = {"virtualride": "ride", "virtualrun": "run"}
#: Totals the seam writes onto a deduped row even when the stored row lacked them.
_ALWAYS_RESTATED = frozenset({"activity_count", "total_moving_time_seconds"})
#: Day-row marker: the row's `activities` already went through the seam.
DEDUPED_MARKER = "activities_deduped"


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN -> None


def _sport(a: Dict[str, Any]) -> str:
    s = str(a.get("sport_type") or a.get("type") or "").replace("_", "").lower()
    return _SPORT_ALIASES.get(s, s)


def _start(a: Dict[str, Any]) -> Optional[datetime]:
    return parse_iso_utc(a.get("start_date_local") or a.get("start_date") or "")


def _duration_s(a: Dict[str, Any]) -> float:
    return _num(a.get("elapsed_time_seconds")) or _num(a.get("moving_time_seconds")) or 0.0


def _richness(a: Dict[str, Any]) -> float:
    score = 0.0
    if (_num(a.get("distance_meters")) or 0) > 0:
        score += 1000
    score += _num(a.get("moving_time_seconds")) or 0
    if a.get("summary_polyline"):
        score += 500
    return score


def _hr_plausible(a: Dict[str, Any]) -> bool:
    hr = _num(a.get("average_heartrate"))
    return hr is not None and hr >= PLAUSIBLE_ACTIVITY_AVG_HR


def _is_hr_key(k: str) -> bool:
    return k in ("average_heartrate", "max_heartrate", "has_heartrate", "hr_recovery") or (k.startswith("zone") and k.endswith("_seconds"))


def _graft_hr(keep: Dict[str, Any], donor: Dict[str, Any]) -> Dict[str, Any]:
    """`keep` with its HR family replaced, as a unit, by `donor`'s (a new dict)."""
    out = {k: v for k, v in keep.items() if not _is_hr_key(k)}
    out.update({k: v for k, v in donor.items() if _is_hr_key(k)})
    out["hr_from_strava_id"] = donor.get("strava_id")
    return out


def _same_session(a: Dict[str, Any], ta: datetime, b: Dict[str, Any], tb: datetime) -> bool:
    if abs((tb - ta).total_seconds()) / 60 <= START_WINDOW_MIN:
        return True
    dev_a, dev_b = str(a.get("device_name") or "").lower(), str(b.get("device_name") or "").lower()
    if not dev_a or dev_a == dev_b:
        return False
    da, db = _duration_s(a), _duration_s(b)
    if da <= 0 or db <= 0:
        return False
    ea, eb = ta + timedelta(seconds=da), tb + timedelta(seconds=db)
    overlap = (min(ea, eb) - max(ta, tb)).total_seconds()
    return overlap >= CONTAINMENT_SHARE * min(da, db)


def _dedup_plan(activities: List[Dict[str, Any]]) -> Tuple[List[int], Dict[int, Dict[str, Any]]]:
    """(kept indices in start order, then untimed ones; {index: the kept record if it changed})."""
    timed = [(i, t) for i, t in ((i, _start(a)) for i, a in enumerate(activities)) if t is not None]
    timed.sort(key=lambda x: x[1])
    eff: Dict[int, Dict[str, Any]] = {}
    removed: set = set()
    for pos, (i, ti) in enumerate(timed):
        if i in removed:
            continue
        end_i = ti + timedelta(seconds=_duration_s(activities[i]))
        for k, tk in timed[pos + 1 :]:
            if tk - ti > timedelta(minutes=START_WINDOW_MIN) and tk >= end_i:
                break
            a_i, a_k = eff.get(i, activities[i]), eff.get(k, activities[k])
            if k in removed or _sport(a_i) != _sport(a_k) or not _same_session(a_i, ti, a_k, tk):
                continue
            win, lose = (i, k) if _richness(a_i) >= _richness(a_k) else (k, i)
            a_win, a_lose = eff.get(win, activities[win]), eff.get(lose, activities[lose])
            if not _hr_plausible(a_win) and _hr_plausible(a_lose):
                eff[win] = _graft_hr(a_win, a_lose)
            removed.add(lose)
            if lose == i:
                break  # i is gone; its survivor k meets the rest on its own turn
    kept = [i for i, _ in timed if i not in removed]
    timed_ids = {i for i, _ in timed}
    return kept + [i for i in range(len(activities)) if i not in timed_ids], eff


def dedup_activities(activities):
    """Remove multi-device duplicate activities (the pair rule in the module docstring).

    Returns the kept activities in start order, then any without a parseable start (kept
    unconditionally). Idempotent: survivors are pairwise not one session, so a second pass
    returns the same records — which is what makes the per-consumer calls that predate the
    #4419 seam harmless.
    """
    if not activities or len(activities) <= 1:
        return activities
    kept, eff = _dedup_plan(list(activities))
    return [eff.get(i, activities[i]) for i in kept]


def day_totals(activities: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The day-row totals derived from its activities — the ingest writer's formula (#4419).

    Mirrors `ingestion.strava_lambda.transform` key for key (the writer keeps its literal
    dict because `tests/test_freshness_completeness_writer_contract.py` derives the emitted
    field set from the writer's own source). The two cannot drift silently:
    `tests/test_shared_modules.py::test_the_ingest_writer_and_the_seam_share_one_totals_formula`
    runs both over a real 2024 day and asserts they agree.
    """
    return {
        "activity_count": len(activities),
        "total_distance_miles": round(sum(a.get("distance_miles") or 0 for a in activities), 2),
        "total_moving_time_seconds": sum(a.get("moving_time_seconds") or 0 for a in activities),
        "total_kilojoules": round(sum(a.get("kilojoules") or 0 for a in activities), 1),
        "kilojoules_moving_time_seconds": sum(a.get("moving_time_seconds") or 0 for a in activities if a.get("kilojoules")),
        "total_elevation_gain_feet": round(sum(a.get("total_elevation_gain_feet") or 0 for a in activities), 1),
        "sport_types": sorted(set(a.get("sport_type", "") for a in activities)),
        "total_zone2_seconds": sum(a.get("zone2_seconds") or 0 for a in activities),
    }


def dedup_strava_day(item):
    """One `strava` day row with its duplicate activities removed and its totals recomputed.

    Returns a NEW dict (the input is not mutated). Totals the row carries are recomputed; of
    the ones it lacks, only `activity_count` / `total_moving_time_seconds` are added (the two
    every pre-seam consumer dedupe already restated) — a legacy row is never handed a
    `total_kilojoules` its writer did not produce, where absent and 0 mean different things. The row gains
    `activities_deduped: True` and, when something was dropped, `duplicate_activity_count`.
    """
    if not isinstance(item, dict) or item.get(DEDUPED_MARKER):
        return item
    acts = item.get("activities")
    if not isinstance(acts, list):
        return item
    out = dict(item)
    out[DEDUPED_MARKER] = True
    if len(acts) <= 1:
        return out
    kept, eff = _dedup_plan(acts)
    if len(kept) == len(acts) and not eff:
        return out
    keep = set(kept)
    new_acts = [eff.get(i, a) for i, a in enumerate(acts) if i in keep]  # the writer's order, not start order
    out["activities"] = new_acts
    out.update({k: v for k, v in day_totals(new_acts).items() if k in item or k in _ALWAYS_RESTATED})
    out["duplicate_activity_count"] = len(acts) - len(new_acts)
    return out


def strava_read_seam(source, rows, keep_duplicates: str = ""):
    """THE read seam (#4419): dedupe `strava` day rows; every other source passes through.

    `rows` may be a list of day rows, a {date: row} dict of them, a single row, or None —
    the shapes the fleet's readers return. `keep_duplicates` is the explicit opt-out for a
    reader that must see the partition verbatim (a data export): pass the reason, and the
    rows come back untouched. The AST guard accepts that call as a decision made in code.
    """
    if keep_duplicates or source != STRAVA_SOURCE or not rows:
        return rows
    if isinstance(rows, list):
        return [dedup_strava_day(r) for r in rows]
    if isinstance(rows, dict) and "activities" not in rows and all(isinstance(v, dict) for v in rows.values()):
        return {k: dedup_strava_day(v) for k, v in rows.items()}
    return dedup_strava_day(rows)
