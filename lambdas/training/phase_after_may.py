"""training/phase_after_may.py — the dated prompt to write the post-deadline plan, and its dead-man (#5130, epic #5120).

The target date ends PHASE ONE: a milestone with a plan after it, never a finish line (the charter's
`governing_goal.target_date_role` and `phase_after_may.target_date_is`). Where that plan lives is named in the
charter (`phase_after_may.plan_location`): `phase_after_may.plan`, null until the owner writes it and rules it in.

This module turns the charter's `phase_after_may.plan_prompt` into ONE calibration-cadence row (kind
`post_may_plan`), so the prompt and the dead-man ride the paths every other owner-only cadence already uses
(`training.calibration_cadence.read`: the coach-event trigger sends the prompt, `coach.calibration_deadman_alert`
sends the dead-man as fixed text, and `mcp.calibration_leg` counts it for the email alarm):

  ok        the plan is written, or today is before `weeks_before_target` weeks ahead of the target date
  due       inside the prompt window and the plan is still null (one prompt: the key is the window's start)
  missed_2  `dead_man_weeks_before_target` weeks ahead of the target date (or later) and the plan is still null
  unknown   the charter carries no target date or no prompt weeks (nothing is guessed)

Pure: the clock is the `today` argument, the charter is read through `charter_value`, nothing here touches AWS.
OWNER-ONLY: `phase_after_may` and `governing_goal` are never published (`training_charter.NEVER_PUBLISHED`), and the
cadence block that carries this row is `tier: owner_only`.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Callable, Optional

CALIBRATION_KIND = "post_may_plan"
SOURCE = "config/training_charter.json phase_after_may.plan (owner-only)"
ISSUE = 5130

CharterReader = Callable[[str], Any]


def _default_reader(dotted: str) -> Any:
    from training.training_charter import charter_value  # noqa: PLC0415 — lazy: import-safe offline

    return charter_value(dotted)


def _day(v: Any) -> Optional[_dt.date]:
    from common.pacific_time import parse_day_key  # noqa: PLC0415 — THE calendar-day parse; no clock is read

    return parse_day_key(str(v)[:10]) if v else None


def _weeks(v: Any) -> Optional[int]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return int(v) if v >= 0 else None


def calibration_row(today: str, read: Optional[CharterReader] = None) -> dict[str, Any]:
    """The post_may_plan row for `today`. Never raises."""
    from training import calibration_cadence as cc  # noqa: PLC0415 — the shared state names

    read = read or _default_reader
    base: dict[str, Any] = {"kind": CALIBRATION_KIND, "source": SOURCE, "prompt": None, "last_logged": None, "missed_cycles": 0}
    t, target = _day(today), _day(read("governing_goal.target_date"))
    lead, dead = _weeks(read("phase_after_may.plan_prompt.weeks_before_target")), _weeks(
        read("phase_after_may.plan_prompt.dead_man_weeks_before_target")
    )
    if t is None or target is None or lead is None or dead is None:
        return {**base, "state": cc.UNKNOWN, "detail": "no valid today, or the charter carries no target date or no plan-prompt weeks"}
    due = target - _dt.timedelta(weeks=lead)
    deadman = target - _dt.timedelta(weeks=dead)
    row = {
        **base,
        "cycle_start": due.isoformat(),
        "due_on": due.isoformat(),
        "dead_man_on": deadman.isoformat(),
        "days_until_due": (due - t).days,
        "prompt_key": cc.prompt_key(CALIBRATION_KIND, due.isoformat()),
    }
    if read("phase_after_may.plan"):
        return {**row, "state": cc.OK, "detail": "the post-deadline plan is written (phase_after_may.plan)"}
    if t < due:
        return {**row, "state": cc.OK}
    if t < deadman:
        row["state"] = cc.DUE
        row["prompt"] = (
            f"Phase one of the plan ends on {target.isoformat()}: a milestone, not a finish line. Write the plan for what comes "
            "after it (the long-term goal and maintenance) and tell your coach, so it lands in the charter as "
            f"phase_after_may.plan before {deadman.isoformat()}."
        )
        return row
    return {
        **row,
        "state": cc.MISSED_2,
        "missed_cycles": 1,
        "alert": (
            f"No post-deadline plan is written and phase one ends on {target.isoformat()}. The charter's "
            "phase_after_may.plan is still empty, so nothing says what the weeks after that date hold. Write it this week."
        ),
    }
