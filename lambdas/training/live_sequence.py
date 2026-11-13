"""live_sequence.py — the week's sessions in the nightly SEQUENCE: the short week and the adherence dip (#5861 FIX5). LIVE only:
every entry point checks `selection_engine.mode(lib) == "live"` first and returns None otherwise, so the sequence the cron
serves while the library is `proposed` is today's, byte for byte (`tests/test_no_live_change_5861_l6.py`).

WHY IT EXISTS. A fifth independent red team (2026-11-13) found the short-week and adherence-dip role choices only in the
sample-week generator: production never set `short_week` and never skipped a role, so the samples showed weeks the nightly job
would never draft — and a 3-day week crashed the draft (`total_sets 23 > cap 20`). This module is the ONE decision both read:

  * `week_plan` — for a calendar week (Monday to Sunday, Pacific): which roles it does NOT draft, which session takes a
    partner role's anchors (a full-body day), and which session hosts the week's carry and trunk floor. A SHORT week (fewer
    lifting mornings than roles: `SHORT_WEEK_PLANS`) or an ADHERENCE DIP (`live_balance.adherence_response`, judged on the
    record before the Monday) gives a plan; a normal week gives None.
  * `sequence_skip` — the plan as the callable `session_sequence.ledger` / `next_session` step over (`_skip_roles`), so the
    order SKIPS a role that week instead of sliding, and the credit check reads the role the plan served.
  * `entry_week` — the plan for the served day, carried on the day entry (`live_week`) into the draft
    (`live_session.for_live_draft`).

THE SHORT WEEK'S INPUT. Production has no "mornings this week" record; `days_available` counts the nominal lifting days
(`program_structure.NOMINAL_LIFTING_DAYS`) not covered by a dated charter travel window (`travel.windows`). The sample
generator passes its profile's day count. A per-week declared count would be better — the owner's call (named on the PR).

`sequence_rule_from` (library `programming_settings`, default None = from the block start): the first Monday the rule
judges. Set it to the approval's Monday so weeks served before the flip keep the positions they were credited at.

Every rule is a labelled PLATFORM HEURISTIC (practitioner consensus at best), owner-adjustable; none is validated.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)
ISSUE = "#5861"
HEURISTIC = "heuristic"

SHORT_WEEK_PLANS: dict[int, dict[str, Any]] = {
    4: {
        "skip": ("shoulders_arms",),
        "partners": {},
        "host": "lower_volume",
        "label": HEURISTIC,
        "basis": "four mornings: shoulders+arms goes first (L5's rule) — both lower days and both upper days keep their anchors; "
        "the delts and arms sit at their floor for one week",
    },
    3: {
        "skip": ("shoulders_arms", "upper_volume"),
        "partners": {"lower_volume": "upper_volume"},
        "host": "lower_volume",
        "label": HEURISTIC,
        "basis": "three mornings: upper heavy, lower heavy, then a FULL-BODY day (lower volume + the upper-volume anchors) — legs "
        "and the upper body each train twice (an A/B/full week; practitioner consensus: two exposures a week per muscle)",
    },
    2: {
        "skip": ("shoulders_arms", "upper_volume", "lower_volume"),
        "partners": {"upper_heavy": "lower_volume", "lower_heavy": "upper_volume"},
        "host": "lower_heavy",
        "label": HEURISTIC,
        "basis": "two mornings: two FULL-BODY days (upper heavy + the lower-volume anchors; lower heavy + the upper-volume "
        "anchors) — never an upper half and a lower half (the fifth red team's 2-day week: chest 2 sets, abs 0)",
    },
    1: {
        "skip": ("lower_heavy", "shoulders_arms", "upper_volume", "lower_volume"),
        "partners": {"upper_heavy": "lower_volume"},
        "host": "upper_heavy",
        "label": HEURISTIC,
        "basis": "one morning: one full-body session (upper heavy + the lower-volume anchors) — a holding week",
    },
}
"""Mornings this week -> the plan. A partner role's ANCHORS join its host session (`live_rules.full_body`); the session set cap
(`live_rules.fit_set_cap`) and the 75-minute fit then hold the session. Days >= the split's roles: no plan."""


def _live(lib: dict[str, Any] | None) -> bool:
    from training import selection_engine as se

    return se.mode(lib) == se.MODE_LIVE


def _settings(lib: dict[str, Any] | None) -> dict[str, Any]:
    from training import live_program

    return live_program.settings(lib)


def monday_of(day: str) -> str:
    from training.live_balance import week_start

    return week_start(str(day)[:10])


def days_available(monday: str) -> int:
    """The nominal lifting days of the week starting `monday` that no dated charter travel window covers."""
    from common.pacific_time import shift_day_key

    from training import program_structure as ps
    from training.training_charter import charter_value

    windows = [w for w in charter_value("travel.windows", []) or [] if isinstance(w, dict) and w.get("start") and w.get("end")]
    days = [shift_day_key(monday, int(i)) for i in ps.NOMINAL_LIFTING_DAYS]
    return sum(1 for d in days if not any(str(w["start"]) <= d <= str(w["end"]) for w in windows))


def plan_for_days(days: int, lib: dict[str, Any] | None) -> dict[str, Any] | None:
    """SHORT_WEEK_PLANS for `days` mornings (the `short_week_rule` setting: `slide` keeps today's sliding sequence), else None."""
    from training import program_structure as ps

    if days >= len(ps.SPLIT_ROLES) or days < 1 or _settings(lib).get("short_week_rule") != "skip_shoulders_arms":
        return None
    plan = SHORT_WEEK_PLANS.get(int(days))
    if plan is None:
        return None
    kept = [r for r in ps.SPLIT_ROLES if r not in plan["skip"]]
    full = [f"{r} + {p} anchors" for r, p in plan["partners"].items()]
    line = (
        f"short week (live, {days} of {len(ps.SPLIT_ROLES)} mornings): {', '.join(kept)} — {', '.join(plan['skip'])} skipped"
        + (f"; full body: {'; '.join(full)}" if full else "")
        + f"; the carry and trunk floor ride {plan['host']} (SHORT_WEEK_PLANS, heuristic)"
    )
    return {
        "skip": tuple(plan["skip"]),
        "partners": dict(plan["partners"]),
        "host": plan["host"],
        "mode": "short",
        "days": days,
        "line": line,
    }


def week_plan(monday: str, workouts: Any, lib: dict[str, Any] | None, days: int | None = None) -> dict[str, Any] | None:
    """The plan for the calendar week starting `monday` (module doc), or None (a normal week, or not live). `days`: the mornings
    available (default `days_available`)."""
    if not _live(lib):
        return None
    since = _settings(lib).get("sequence_rule_from")
    if since and monday < monday_of(str(since)):
        return None
    short = plan_for_days(days_available(monday) if days is None else int(days), lib)
    if short:
        return short
    from training import live_balance, live_week, program_structure as ps

    dip = live_balance.adherence_response(workouts, monday, lib)
    if not dip:
        return None
    _roles, line = live_week.behind_schedule_roles(list(ps.SPLIT_ROLES), dip)
    return {"skip": ("shoulders_arms",), "partners": {}, "host": "lower_volume", "mode": dip["mode"], "dip": dip, "line": line}


def sequence_skip(workouts: Any, lib: dict[str, Any] | None, days_fn: Callable[[str], int] | None = None) -> Any:
    """The callable `session_sequence.next_session(skip=...)` reads (day -> the roles its week skips), cached per Monday; None
    when not live (the sequence is today's)."""
    if not _live(lib):
        return None
    cache: dict[str, tuple[str, ...]] = {}

    def skip(day: str) -> tuple[str, ...]:
        m = monday_of(day)
        if m not in cache:
            plan = week_plan(m, workouts, lib, days_fn(m) if days_fn else None)
            cache[m] = tuple(plan["skip"]) if plan else ()
        return cache[m]

    return skip


def entry_week(day: str, role: str, workouts: Any, lib: dict[str, Any] | None, days: int | None = None) -> dict[str, Any] | None:
    """The week plan for the served session on `day` — {host, partner, skip, line, mode} — carried on the day entry as `live_week`
    (`live_session.for_live_draft` reads it); None in a normal week or when not live."""
    return for_role(week_plan(monday_of(day), workouts, lib, days), role)


def for_role(plan: dict[str, Any] | None, role: str) -> dict[str, Any] | None:
    """One session's view of a week plan (the day entry's `live_week`)."""
    if not plan:
        return None
    return {
        "host": plan["host"],
        "partner": plan["partners"].get(role),
        "skip": list(plan["skip"]),
        "line": plan["line"],
        "mode": plan["mode"],
    }


def week_roles(days: int, monday: str, workouts: Any, lib: dict[str, Any] | None) -> tuple[list[str], dict[str, Any] | None]:
    """The week's drafted roles in the charter's order from its first role (the sample generator's view of a week that starts
    at upper heavy): the plan's skips stepped over, `days` of them; and the plan (None = a normal week)."""
    from training import program_structure as ps

    plan = week_plan(monday, workouts, lib, days)
    roles = [r for r in ps.SPLIT_ROLES if not plan or r not in plan["skip"]]
    return roles[: int(days)], plan


def serve(seq: dict[str, Any] | None, day: str, workouts: Any, lib: dict[str, Any] | None) -> dict[str, Any] | None:
    """The cron's step (`routine_generator._schedule_entry_for_date`, live only): the served entry carries its week plan."""
    if not seq or seq.get("source") != "session_sequence" or not _live(lib):
        return seq
    week = entry_week(day, str(seq.get("session_role")), workouts, lib)
    return {**seq, "live_week": week} if week else seq


def cron_skip(block_workouts: Any) -> tuple[Any, Any]:
    """(the skip callable for the sequence, the library read) for `routine_generator._schedule_entry_for_date`; (None, lib) unless
    the exercise library is approved — the sequence is then today's. Never raises."""
    if block_workouts is None:
        return None, None
    try:
        from training import selection_engine as se

        lib = se.load_library_failsoft()
        return sequence_skip(block_workouts, lib), lib
    except Exception as e:  # noqa: BLE001 — the live week rule never blocks a draft
        logger.warning(f"live week rule failed ({type(e).__name__}) — the sequence is served as it slides")
        return None, None


def cron_entry(seq: dict[str, Any], day: str, block_workouts: Any, lib: Any) -> dict[str, Any]:
    """`serve`, never raising (the cron's step)."""
    try:
        return serve(seq, day, block_workouts, lib) or seq
    except Exception as e:  # noqa: BLE001 — never blocks a draft
        logger.warning(f"live week entry failed ({type(e).__name__})")
        return seq
