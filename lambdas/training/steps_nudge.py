"""steps_nudge.py — the day's steps line and the lifting-day nudge (#5056). PURE: no AWS, no clock.

The charter's steps rule (owner ruling 2026-10-18): a 12,000 floor and a 15,000 target EVERY day, lifting days
included; walking carries the volume. Two owner-only outputs read it:

  * `target_line(ramp)` — the one line the coach packet, the plan's constraint block and the morning brief state
    each day: today's step (the ramp's `today_target`, `training.steps_ramp`), the floor and the target.
  * `decide(...)` — the 19:00 PT lifting-day nudge: ONE owner-only note on a day with a LOADED Hevy session when the
    steps so far are behind the pace line, naming the walk that closes the gap.

THE PACE LINE (derived, stated on every verdict as `formula`)
    pace = today_target x clamp((now - day_start) / (22:00 PT - day_start), 0, 1)
    day_start = the earlier of 06:00 PT and the day's first Hevy session start (an early lifter's day began earlier;
                a late session never shortens the day)
    effective_steps = measured steps so far + gym cardio steps-equivalent
    gym cardio steps-equivalent = gym cardio minutes (Hevy cardio-machine blocks, `walking_volume.hevy_sessions`)
                x ASSUMED_CADENCE_SPM — the charter rule `steps.gym_cardio_minutes_count_toward_movement`. A treadmill
                walk may ALSO register on the wrist, so this can over-count; that only ever withholds a nudge.
    BEHIND = effective_steps < pace (strictly: exactly on the line is not behind).
The walk is sized to close the gap to TODAY'S TARGET, not the pace line: gap / cadence minutes, rounded up to 5.

NOT SENT: an off day (no loaded session), ahead of / on pace, no steps reading (never a nudge built on nothing,
ADR-104), no target (the ramp did not read), already sent today (`STEPS_NUDGE#<date>`), outside the evening window,
budget tier >= 2. The copy is information, never a command; skippable; no streak or loss language (SDT).
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Mapping, Optional

from training import training_charter, training_streaks, walking_volume

STEPS_NUDGE_VERSION = "steps-nudge@1.0.0"
CADENCE_SPM = walking_volume.ASSUMED_CADENCE_SPM
DAY_START_HOUR_PT = 6
DAY_END_HOUR_PT = 22
# The send window: the first tick at/after 19:00 PT. The coach-nudge cron is hourly at :10 UTC, so in PDT the 02:10Z
# tick is 19:10 PT and the 03:10Z tick 20:10 PT (a retry if the first read failed); in PST 03:10Z is 19:10 PT.
WINDOW_START_HOUR_PT = 19
WINDOW_END_HOUR_PT = 21
BUDGET_SILENCE_TIER = 2  # = coach_nudge_engine.BUDGET_SILENCE_TIER (pinned by the tests)
ROUND_WALK_MIN = 5
KEY_PREFIX = "STEPS_NUDGE#"

FORMULA = (
    "pace = today_target x clamp((now - day_start) / (22:00 PT - day_start), 0, 1); day_start = the earlier of 06:00 PT "
    "and the first Hevy session start; effective = measured steps + gym cardio minutes x 100 steps/min; "
    "behind = effective < pace (strictly)"
)


def idempotency_key(date: str) -> str:
    return f"{KEY_PREFIX}{date}"


def target_line(ramp: Optional[Mapping[str, Any]]) -> Optional[str]:
    """The day's steps line from `steps_ramp.compute`'s output, or None when it did not read a target."""
    if not ramp or ramp.get("state") in (None, "unknown"):
        return None
    floor = ramp.get("floor") or training_charter.charter_value("steps.floor")
    target = training_charter.charter_value("steps.target")
    today = ramp.get("today_target")
    if not (floor and target):
        return None
    base = f"Steps today: floor {int(floor):,}, target {int(target):,}"
    if today is None:
        return f"{base} (no ramp step read: {', '.join(ramp.get('held_by') or []) or 'no baseline'})"
    if int(today) < int(floor):
        return f"{base}; today's ramp step {int(today):,} ({ramp.get('state')})"
    return base


def _minutes_of_day(dt: datetime) -> float:
    return dt.hour * 60 + dt.minute + dt.second / 60.0


def pace(today_target: int, now_pt: datetime, first_session_pt: Optional[datetime] = None) -> int:
    """The steps he should have by `now_pt` to be on the line to `today_target` at 22:00 PT."""
    start = DAY_START_HOUR_PT * 60.0
    if first_session_pt is not None and first_session_pt.date() == now_pt.date():
        start = min(start, _minutes_of_day(first_session_pt))
    end = DAY_END_HOUR_PT * 60.0
    frac = max(0.0, min(1.0, (_minutes_of_day(now_pt) - start) / (end - start)))
    return int(round(today_target * frac))


def gym_cardio(hevy_rows: Optional[list]) -> dict[str, int]:
    """Gym cardio minutes and their steps-equivalent, from the day's Hevy rows (the walking layer's one definition)."""
    counted, _skipped = walking_volume.hevy_sessions(list(hevy_rows or []))
    minutes = int(round(sum(float(b["seconds"]) for b in counted) / 60.0))
    return {"minutes": minutes, "steps_equivalent": minutes * CADENCE_SPM}


def is_loaded_day(hevy_rows: Optional[list]) -> bool:
    return any(training_streaks.is_loaded_session(w) for w in hevy_rows or [])


def walk_minutes(gap: int) -> int:
    return int(math.ceil(max(gap, 1) / CADENCE_SPM / ROUND_WALK_MIN) * ROUND_WALK_MIN)


def copy(verdict: Mapping[str, Any]) -> str:
    gap = int(verdict["gap_to_target"])
    mins = int(verdict["walk_minutes"])
    return (
        f"Steps are at {int(verdict['effective_steps']):,} against a pace of {int(verdict['pace']):,} by now "
        f"(today's target {int(verdict['today_target']):,}). A {mins}-min walk after dinner closes about "
        f"{min(gap, mins * CADENCE_SPM):,} steps. Fine to skip; this is just where the day stands."
    )


def decide(
    *,
    date: str,
    now_pt: datetime,
    ramp: Optional[Mapping[str, Any]],
    steps_day: Optional[Mapping[str, Any]],
    hevy_rows: Optional[list],
    already_sent: bool,
    budget_tier: int,
    first_session_pt: Optional[datetime] = None,
) -> dict[str, Any]:
    """One verdict: `send` plus the reason it did or did not, with every number that decided it."""
    out: dict[str, Any] = {
        "date": date,
        "send": False,
        "reason": None,
        "key": idempotency_key(date),
        "formula": FORMULA,
        "version": STEPS_NUDGE_VERSION,
        "charter_version": training_charter.charter_version(),
    }
    if budget_tier >= BUDGET_SILENCE_TIER:
        return {**out, "reason": f"budget_tier_{budget_tier}"}
    if not WINDOW_START_HOUR_PT <= now_pt.hour < WINDOW_END_HOUR_PT:
        return {**out, "reason": "outside_window"}
    if already_sent:
        return {**out, "reason": "already_sent"}
    if not is_loaded_day(hevy_rows):
        return {**out, "reason": "off_day"}
    target = (ramp or {}).get("today_target")
    steps = (steps_day or {}).get("steps")
    if not target:
        return {**out, "reason": "no_target"}
    if steps is None:
        return {**out, "reason": "no_steps_reading", "today_target": int(target)}
    cardio = gym_cardio(hevy_rows)
    effective = int(steps) + cardio["steps_equivalent"]
    line = pace(int(target), now_pt, first_session_pt)
    out.update(
        today_target=int(target),
        steps=int(steps),
        gym_cardio=cardio,
        effective_steps=effective,
        pace=line,
        gap_to_target=max(0, int(target) - effective),
    )
    if effective >= line:
        return {**out, "reason": "ahead_of_pace"}
    out["walk_minutes"] = walk_minutes(out["gap_to_target"])
    out["send"], out["reason"] = True, "behind_pace"
    out["text"] = copy(out)
    return out
