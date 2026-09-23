"""training_streaks.py — the two streaks the joints/tendons critic reads, and which one asks for rest (#4067).

WHY THIS EXISTS

On 2026-09-22 the joints/tendons critic read `consecutive_training_days = 16` and asked for a
rest day. The 16 was every day with ANY Hevy session — the v0.3 Engine days (treadmill + bike +
stretching, no load) and the Hevy-logged walking blocks counted as training days, so under a
program that puts cardio in Hevy on the off days the streak could only ever grow, and the
rest-day ask fired on a number that measures being active. (The #4067 filing put the loaded
streak at 4; read off the performed record with `is_loaded_session`, a plan for 09-23 sits on
a loaded streak of 1 — 09-21 was an Engine day. Either way: no rest-day ask.)

Tendons answer to LOAD. So there are two streaks now, each named in the critic's output:

  active_day_streak      consecutive days before the session with ANY activity — a Hevy
                         session of any kind or a Strava activity. Context only; never a
                         reason to rest (he was active on 97 % of the 2024–25 days).
  loaded_lifting_streak  consecutive days before the session with a Hevy session carrying
                         LOAD — a working set with weight > 0 on a non-cardio exercise.
                         The rest-day ask keys on this one alone.

THE THRESHOLDS ARE HIS (ADR-105 — thresholds from personal variance)

Measured read-only from DynamoDB on 2026-09-22, over the 2024–25 campaign that worked
(2024-09-15 .. 2025-05-09, 237 days), from `USER#matthew#SOURCE#hevy` per-workout rows
(`DATE#…#WORKOUT#…`; the 153 legacy daily aggregates tombstoned
`legacy_daily_aggregate_superseded_by_per_workout` excluded), with `is_loaded_session` below
as the predicate:

  loaded-lifting days  146 of 237 (61.6 %)
  loaded streaks       n = 59; lengths 1:17  2:23  3:8  4:2  5:3  6:6
                       median 2, mean 2.47, p75 3, p90 6, MAX 6 — never a 7th day
  gaps between streaks median 1 rest day
  active-day streaks   (the #4067 filing, same window) longest 84, median 18, 97 % of days active

So: a session that would be the 7th consecutive loaded day is outside anything he did in the
campaign that worked → the rest-day ask (`REST_ASK_AT_STREAK` = 6 prior days). A session that
would be day 6 is inside his record but in its upper tail (6 of 59 streaks reached it) → an
info line (`UPPER_TAIL_AT_STREAK` = 5 prior days). Day 5 and below carries no flag at all —
and no flag means the model has no handle to escalate a rest-day ask from (`critics.reconcile`).
"""

from __future__ import annotations

from typing import Any, Iterable

from common.pacific_time import parse_day_key, shift_day_key

from training import walking_volume

# ── calibration (see module docstring for the measurement) ───────────────────────────
REST_ASK_AT_STREAK = 6
UPPER_TAIL_AT_STREAK = 5
CALIBRATION: dict[str, Any] = {
    "window": "2024-09-15..2025-05-09",
    "source": "USER#matthew#SOURCE#hevy per-workout rows, legacy daily aggregates excluded",
    "measured_at": "2026-09-22",
    "loaded_streaks_n": 59,
    "loaded_streak_lengths": {1: 17, 2: 23, 3: 8, 4: 2, 5: 3, 6: 6},
    "loaded_streak_max": 6,
    "loaded_streak_median": 2,
    "loaded_streak_p90": 6,
    "loaded_days": 146,
    "window_days": 237,
    "active_streak_longest": 84,
    "active_streak_median": 18,
    "active_day_pct": 97,
    "provenance": "owner-history",
}


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def is_loaded_session(workout: dict[str, Any]) -> bool:
    """True when the session carries LOAD: a non-warm-up set with weight > 0 on an exercise
    that is not a counted cardio modality (`walking_volume`'s lexicon — one list, so a treadmill
    block can never be a lift here and a walk there). Accepts both the raw per-workout row
    (`weight_kg`, `type`) and `normalize_hevy_items` output (`weight_kg`/`weight_lbs`, `set_type`)."""
    for ex in workout.get("exercises") or []:
        name = (ex.get("name") or ex.get("exercise_name") or "").strip()
        if walking_volume._modality_for_hevy(name) is not None:
            continue
        for s in ex.get("sets") or []:
            if (s.get("set_type") or s.get("type") or "normal") == "warmup":
                continue
            if _num(s.get("weight_kg")) > 0 or _num(s.get("weight_lbs")) > 0:
                return True
    return False


def _day(row: dict[str, Any]) -> str:
    return str(row.get("date") or str(row.get("sk") or "").replace("DATE#", ""))[:10]


def streak_before(days: Iterable[str], target_date: str) -> int:
    """Consecutive days immediately before `target_date` present in `days`."""
    have = {d for d in days if d}
    if parse_day_key(target_date) is None:
        return 0
    n = 0
    while shift_day_key(target_date, -(n + 1)) in have:
        n += 1
    return n


def streaks(
    hevy_workouts: list[dict[str, Any]] | None,
    strava_items: list[dict[str, Any]] | None,
    target_date: str,
    *,
    window_start: str | None = None,
) -> dict[str, Any]:
    """{active_day_streak, loaded_lifting_streak, *_is_floor}. A streak that reaches back to
    `window_start` is a FLOOR — the read window ended before the streak did. `hevy_workouts`
    None (unreadable) → both streaks None; `strava_items` None → the active streak is a floor
    of the Hevy-only days and says so."""
    if hevy_workouts is None:
        return {"active_day_streak": None, "loaded_lifting_streak": None, "active_is_floor": None, "loaded_is_floor": None}
    loaded_days = {_day(w) for w in hevy_workouts if is_loaded_session(w)}
    active_days = {_day(w) for w in hevy_workouts}
    for item in strava_items or []:
        if item.get("activities"):
            active_days.add(_day(item))
    loaded = streak_before(loaded_days, target_date)
    active = streak_before(active_days, target_date)

    def _floor(n: int) -> bool:
        if not window_start or not n:
            return False
        return shift_day_key(target_date, -n) <= window_start

    return {
        "active_day_streak": active,
        "loaded_lifting_streak": loaded,
        "active_is_floor": _floor(active) or strava_items is None,
        "loaded_is_floor": _floor(loaded),
    }
