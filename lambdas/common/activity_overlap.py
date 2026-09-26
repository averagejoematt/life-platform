"""common/activity_overlap.py — the ONE HR-covered-interval / overlap derivation (#4158).

A Hevy-logged cardio block (a timed set carrying `distance_m`, no `reps` — cycling,
treadmill, walking) and a Strava/Whoop activity can describe the SAME wall-clock
minutes twice: once on the training-load side (`training.training_load.hevy_session_load`,
#4075) and, since #4158 fixed `health.tdee.worked_set_seconds` to read the field the Hevy
writer actually stores, once on the calorie side too. Both need the identical answer to
"how much of this Hevy block did an HR-bearing, non-echo Strava/Whoop activity already
score", so this is ONE derivation, not two.

Moved here from `training_load.py`, where it originated for #4075, so `health.tdee` can
import it without importing the `training` package — `tdee.py`'s own dependency-free
contract (ADR-152; enforced by
`tests/test_training_load_worked_set_4075.py::test_the_energy_targets_load_input_is_the_stored_tsb_not_a_recompute`,
the same boundary that moved `SET_DURATION_FIELD` to `common/hevy_schema.py`).

Pure — no boto3, no I/O, no clock reads (every `datetime` here comes from a caller-supplied
timestamp, never `.now()`).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable, List, Mapping, Optional, Tuple

from common.pacific_time import parse_iso_utc  # #1964: THE ISO parser (naive == UTC)

#: Strava sport/type tokens for a Hevy-pushed weight-training echo (#4075).
LIFT_SPORTS = frozenset({"weighttraining"})
#: The Strava `device_name` Hevy's own push carries (#4075's cardio-echo find).
HEVY_DEVICE = "hevy"


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN -> None


def _sport(act: Mapping[str, Any]) -> str:
    return str(act.get("sport_type") or act.get("type") or "").replace("_", "").lower()


def is_hevy_echo(act: Mapping[str, Any]) -> bool:
    """True when this Strava activity is Hevy's own copy of a Hevy session (#4075)."""
    if _sport(act) in LIFT_SPORTS:
        return True
    return str(act.get("device_name") or "").strip().lower() == HEVY_DEVICE


def hr_intervals(activities: Optional[Iterable[Mapping[str, Any]]]) -> List[Tuple[datetime, datetime]]:
    """Merged UTC [start, end] intervals covered by HR-bearing, non-echo Strava activities.

    These are the minutes an HR record already scored. A Hevy-logged cardio block
    overlapping them must not be charged again — on the TSB-load side
    (`training_load.hevy_session_load`) or the calorie side (`health.tdee.worked_set_seconds`).
    """
    spans = []
    for act in activities or []:
        if not (_num(act.get("average_heartrate")) or 0) > 0 or is_hevy_echo(act):
            continue
        start = parse_iso_utc(act.get("start_date"))
        secs = _num(act.get("elapsed_time_seconds")) or _num(act.get("moving_time_seconds")) or 0
        if start is None or secs <= 0:
            continue
        spans.append((start, start + timedelta(seconds=secs)))
    spans.sort()
    merged: List[Tuple[datetime, datetime]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def overlap_seconds(start: Optional[datetime], end: Optional[datetime], intervals: Optional[Iterable[Tuple[datetime, datetime]]]) -> float:
    """Total seconds ``[start, end]`` spends inside any of the merged ``intervals``."""
    if start is None or end is None or end <= start:
        return 0.0
    total = 0.0
    for a, b in intervals or []:
        lo, hi = max(a, start), min(b, end)
        if hi > lo:
            total += (hi - lo).total_seconds()
    return total
