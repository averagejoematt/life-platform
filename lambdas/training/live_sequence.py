"""live_sequence.py — the week's sessions in the nightly SEQUENCE: declared mornings and the adherence dip (#5861). LIVE only:
every entry point checks `selection_engine.mode(lib) == "live"` first, so the sequence served while the library is `proposed` is
today's, byte for byte (tests/test_no_live_change_5861_l6.py).

  * `week_plan` — for a calendar week: the mornings declared (`declared_days`: the nominal lifting days no dated charter travel
    window covers — WHICH days, not only how many: a guest squat or hinge the morning before the heavy lower day goes low-spine) -> `live_volume.SHORT_WEEKS` (1-3: full-body mornings; 4: shoulders+arms skipped). An ADHERENCE DIP (5+ of the
    fortnight's 10 planned sessions missed, `DIP_MISSED`) is one 4-morning week (owner ruling 2) — never two in a row.
  * `sequence_skip` / `entry_week` / `serve` / `cron_*` — the plan as the sequence's skip and on the served day entry.
  * `rule_from` — owner ruling #4: the rules judge from the Monday after approval; earlier history is never re-sequenced."""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)
ISSUE = "#5861"
DIP_MISSED = 5
"""Heuristic: 5 or more of the fortnight's 10 planned sessions missed (over a fully covered window) is an adherence dip — owner
ruling 2: one 4-morning week to get back into the routine, no make-up sets. A dip week is never followed by a second one for the
same gap (the eighth red team: a 12-day layoff produced two dip weeks in a row)."""


def _live(lib: dict[str, Any] | None) -> bool:
    from training import selection_engine as se

    return se.mode(lib) == se.MODE_LIVE


def rule_from(lib: dict[str, Any] | None) -> str | None:
    """The first Monday the sequence rules judge (owner ruling #4, fix round 8): `sequence_rule_from` when set, else the Monday
    AFTER the library's `approved_on` stamp (the approval day itself is never re-judged; earlier history is kept for baselines
    and analysis, never re-sequenced). Live mode requires the stamp (`selection_engine.mode`, fix round 11), so there is no
    "from the block start" fallback: None only for a library that is not live."""
    from common.pacific_time import shift_day_key

    from training import live_settings, selection_engine as se

    since = live_settings.settings(lib).get("sequence_rule_from")
    if since:
        return monday_of(str(since))
    stamp = se.approved_stamp(lib)
    return shift_day_key(monday_of(stamp), 7) if stamp else None


def week_start(day: str) -> str:
    """The Monday (Pacific day key) of `day`'s ISO week."""
    from common.pacific_time import parse_day_key, shift_day_key

    d = parse_day_key(str(day)[:10])
    return shift_day_key(str(day)[:10], -d.weekday()) if d is not None else str(day)[:10]


monday_of = week_start


def declared_days(monday: str) -> list[str]:
    """The mornings declared for the week starting `monday`: the nominal lifting days no dated charter travel window covers."""
    from common.pacific_time import shift_day_key

    from training import program_structure as ps
    from training.training_charter import charter_value

    windows = [w for w in charter_value("travel.windows", []) or [] if isinstance(w, dict) and w.get("start") and w.get("end")]
    days = [shift_day_key(monday, int(i)) for i in ps.NOMINAL_LIFTING_DAYS]
    return [d for d in days if not any(str(w["start"]) <= d <= str(w["end"]) for w in windows)]


def days_available(monday: str) -> int:
    """How many mornings are declared this week (`declared_days`)."""
    return len(declared_days(monday))


LEFT_OUT_WORDS = {"hinge": "deadlift / RDL", "vertical_pull": "pulldown", "overhead_press": "overhead press"}


def _left_out(shape: dict[str, Any]) -> list[str]:
    """The usual anchors a 1-3 morning week does not carry (owner ruling 2026-11-14: a short week balances coverage, recovery and
    movement priorities — it does not have to carry every strength anchor, and says which it left out)."""
    from training import program_structure as ps

    kept = set()
    for host in shape["roles"]:
        kept |= {(host, pat) for pat, _i in ps.SESSION_TEMPLATES[host]["anchors"]}
        for prole, patterns in (shape.get("partners") or {}).get(host) or ():
            kept |= {(prole, pat) for pat in patterns}
    out = []
    for role in ps.SPLIT_ROLES:
        for pat, intensity in ps.SESSION_TEMPLATES[role]["anchors"]:
            if (role, pat) not in kept:
                out.append(f"{'heavy' if intensity == 'heavy' else 'volume'} {LEFT_OUT_WORDS.get(pat, pat)}")
    return list(dict.fromkeys(out))


def plan_for_days(days: Any, lib: dict[str, Any] | None, mode: str = "short") -> dict[str, Any] | None:
    """The week for the declared mornings (1-4; `live_volume.SHORT_WEEKS`), else None (a normal week). `days`: the declared
    mornings as day keys — the week then follows WHICH mornings they are (fix round 12) — or a bare count, read as consecutive
    days (the conservative case) and said so."""
    from training import live_volume, program_structure as ps

    dates = sorted(str(d)[:10] for d in days) if isinstance(days, list | tuple) else None
    n = len(dates) if dates is not None else int(days)
    if n >= len(ps.SPLIT_ROLES) or n < 1:
        return None
    shape = live_volume.week_shape(n)
    skip = tuple(r for r in ps.SPLIT_ROLES if r not in shape["roles"])
    partners = {h: tuple(p for p, _ in ps_) for h, ps_ in (shape.get("partners") or {}).items()}
    full = "; ".join(f"{h} + {', '.join(p)} anchors" for h, p in partners.items())
    line = f"{'short' if mode == 'short' else 'adherence dip'} week (live, {n} mornings): {', '.join(shape['roles'])}" + (
        f" — full body: {full}" if full else f" — {', '.join(skip)} skipped"
    )
    if partners:
        left = _left_out(shape)
        line += f"; left out this week: {', '.join(left)} — {n} morning(s) carry a squat, a hinge, a press and a pull, not every anchor"
        line += "" if dates is not None or n == 1 else "; spacing not declared: consecutive days assumed"
    return {
        "skip": skip,
        "partners": partners,
        "host": shape["host"],
        "mode": mode,
        "days": n,
        "line": line,
        "roles": tuple(shape["roles"]),
        "dates": dates,
    }


def _dip(workouts: Any, monday: str) -> bool:
    from training import fatigue_model, program_structure as ps

    before = None if workouts is None else [w for w in workouts if str(w.get("date") or str(w.get("sk") or "")[5:15])[:10] < monday]
    adh = fatigue_model.adherence(before, as_of=monday, planned_per_week=len(ps.SPLIT_ROLES))
    if adh.get("state") == "unknown" or not adh.get("window_covered"):
        return False
    return int(adh["planned"]) - int(adh["performed"]) >= DIP_MISSED


def week_plan(monday: str, workouts: Any, lib: dict[str, Any] | None, days: Any = None) -> dict[str, Any] | None:
    """The plan for the calendar week starting `monday` (module doc), or None (a normal week, or not live). `days`: the mornings
    declared — day keys, or a bare count (default `declared_days`)."""
    from common.pacific_time import shift_day_key

    if not _live(lib):
        return None
    since = rule_from(lib)
    if since and monday < since:
        return None
    short = plan_for_days(declared_days(monday) if days is None else days, lib)
    if short:
        return short
    if _dip(workouts, monday) and not _dip(workouts, shift_day_key(monday, -7)):
        return plan_for_days(4, lib, mode="dip")
    return None


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


def entry_week(day: str, role: str, workouts: Any, lib: dict[str, Any] | None, days: Any = None) -> dict[str, Any] | None:
    """The week plan for the served session on `day` — {host, partner, skip, line, mode} — carried on the day entry as `live_week`
    (`live_session.for_live_draft` reads it); None in a normal week or when not live."""
    return for_role(week_plan(monday_of(day), workouts, lib, days), role)


def for_role(plan: dict[str, Any] | None, role: str) -> dict[str, Any] | None:
    """One session's view of a week plan (the day entry's `live_week`). `heavy_lower_tomorrow` (fix round 12): the NEXT declared
    morning is the heavy lower day and falls on the next calendar day — or the spacing was not declared (a bare count is read as
    consecutive days) — so this morning's guest squat and hinge take low-spinal-load members (`live_program.axial_neighbours`)."""
    if not plan:
        return None
    from common.pacific_time import shift_day_key

    roles, dates = list(plan.get("roles") or ()), plan.get("dates")
    i = roles.index(role) if role in roles else -1
    nxt = roles[i + 1] if 0 <= i < len(roles) - 1 else None
    adjacent = dates is None or (0 <= i < len(dates) - 1 and shift_day_key(dates[i], 1) == dates[i + 1])
    return {
        "host": plan["host"],
        "partner": plan["partners"].get(role),
        "skip": list(plan["skip"]),
        "line": plan["line"],
        "mode": plan["mode"],
        "days": plan["days"],
        "heavy_lower_tomorrow": bool(nxt == "lower_heavy" and adjacent),
    }


def week_roles(days: Any, monday: str, workouts: Any, lib: dict[str, Any] | None) -> tuple[list[str], dict[str, Any] | None]:
    """The week's drafted roles in the charter's order from its first role (the sample generator's view of a week that starts
    at upper heavy): the plan's skips stepped over, one per declared morning; and the plan (None = a normal week). `days`: the
    declared mornings (day keys) or a bare count."""
    from training import program_structure as ps

    plan = week_plan(monday, workouts, lib, days)
    roles = [r for r in ps.SPLIT_ROLES if not plan or r not in plan["skip"]]
    return roles[: len(days) if isinstance(days, list | tuple) else int(days)], plan


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
