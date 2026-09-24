"""session_sequence.py — v0.3's sessions as a SEQUENCE, not a weekday calendar (#4110).

WHY THIS EXISTS

#4064 bound each v0.3 session to a weekday: block 1 Thu 09-24 / Sat 09-26 / Mon 09-28, then
Mon/Wed/Fri. Owner, 2026-09-23: "we plan 7 days a week of exercise with seldom rest days but
sometimes I'll listen to body and do a walk instead, so more just focusing on planned sequence
and not forgetting next if I audible a change." Under a weekday calendar a walk on a lifting
day silently SKIPPED that session, and the next date's session was served although the
previous one never happened.

THE RULE, AS ARITHMETIC (pure — every Hevy row is injected)

  completed   = the distinct Pacific days in [block start, the planned day) carrying a LOADED
                Hevy session — `training_streaks.is_loaded_session`, the ONE definition (#4105):
                a non-warm-up set with weight > 0 on an exercise that is not a cardio modality.
                A walk, an Engine day (treadmill + bike + stretching) or a rest day carries no
                load, so it never advances the position.
  index       = len(completed)                       (0-based: the next UNDONE session)
  week        = index // 3 + 1                       (3 loaded sessions = 1 program week)
  role        = session_roles[index % 3]             heavy -> moderate -> heavy-moderate
  deload      = week % every_nth_week == 0           (`owner_redlines`, one home: every 6th)
  block       = (week - 1) // weeks_per_block + 1

RULINGS (#4110 — stated so a reader can dispute them, not discover them)

  * The weekday calendar is RETIRED, not kept as a suggestion: two answers to "what is next"
    is the defect. Before the block start the weekday grid still answers (as it did).
  * A session logged ON the planned day is the one that day's plan served; it advances the
    NEXT day's plan. So the plan for a date is stable all day — a re-run after the workout (the
    stage-2 critics, the commit gate) sees the same session the draft was built for.
  * Two loaded logs on one Pacific day are ONE session (a split or re-started log), never two.
  * The optional 4th is retired as a sequence slot. Every loaded session advances the sequence;
    a 4th in seven days is simply the next session. The redline's calendar ceiling (3–4 lifting
    sessions a week) and its "non-consecutive days" are reported as ADVISORIES beside the
    served session (`spacing`), never by skipping the session — the owner audibles, the plan
    remembers.
  * Any loaded session advances the position — the plan does not try to decide from a Hevy
    title whether he "really" did the heavy day. The session that advanced it is named
    (`advanced_by`: date, title, workout id) so a mismatch is visible, not inferred.
"""

from __future__ import annotations

from typing import Any, Iterable

from common.pacific_time import parse_day_key, shift_day_key

from training import program_structure, training_streaks

ISSUE = "#4110"


def _seq() -> dict[str, Any]:
    return program_structure.SESSION_SEQUENCE


def block_start() -> str:
    return str(_seq()["block_start"])


def _deload_every() -> int:
    return int(program_structure._deload_cfg()["every_nth_week"])


def _check_day(day: str) -> str:
    if parse_day_key(day) is None:
        raise ValueError(f"not a YYYY-MM-DD day key: {day!r}")
    return day


def completed_sessions(workouts: Iterable[dict[str, Any]] | None, before_day: str) -> list[dict[str, Any]]:
    """The completed sessions of the program before `before_day`, oldest first — one per day.

    `workouts` is Hevy per-workout rows (the raw DDB shape or `normalize_hevy_items` output).
    Tombstoned rows are skipped; the day key is the row's own `date` (Pacific, as ingested).
    """
    _check_day(before_day)
    start = block_start()
    by_day: dict[str, dict[str, Any]] = {}
    for w in workouts or []:
        if w.get("tombstone"):
            continue
        d = training_streaks._day(w)
        if parse_day_key(d) is None or d < start or d >= before_day:
            continue
        if not training_streaks.is_loaded_session(w):
            continue
        rec = {
            "date": d,
            "title": w.get("title") or w.get("workout_name") or None,
            "workout_id": w.get("source_workout_id") or w.get("workout_id") or None,
            "start_time": w.get("start_time"),
        }
        prev = by_day.get(d)
        if prev is None:
            by_day[d] = {**rec, "loaded_logs_that_day": 1}
        else:
            prev["loaded_logs_that_day"] += 1
            if rec["start_time"] and (not prev["start_time"] or str(rec["start_time"]) < str(prev["start_time"])):
                prev.update(rec)
    out = [by_day[d] for d in sorted(by_day)]
    for i, r in enumerate(out):
        r["sequence_index"] = i
    return out


def position(index: int) -> dict[str, Any]:
    """The program position of the session at 0-based sequence `index`. Pure arithmetic."""
    seq = _seq()
    per = int(seq["sessions_per_week"])
    roles = seq["session_roles"]
    i = max(0, int(index))
    week = i // per + 1
    in_week = i % per + 1
    role = roles[i % per]
    deload = week % _deload_every() == 0
    block = (week - 1) // int(seq["weeks_per_block"]) + 1
    label = program_structure._ROLE_LABEL[role]
    return {
        "sequence_index": i,
        "week": week,
        "session_in_week": in_week,
        "sessions_per_week": per,
        "session_role": role,
        "block": block,
        "deload": deload,
        "position_label": f"week {week} · session {in_week} of {per} · {label.lower()}" + (" · DELOAD" if deload else ""),
    }


def preview(n_sessions: int, start_index: int = 0) -> list[dict[str, Any]]:
    """The next `n_sessions` positions from `start_index` — the sequence ahead, with no dates."""
    return [position(i) for i in range(start_index, start_index + max(0, int(n_sessions)))]


def _spacing(completed: list[dict[str, Any]], day: str) -> dict[str, Any]:
    """The redline's calendar advisories beside the served session — never a reason to skip it."""
    from training import owner_redlines

    lift = owner_redlines.REDLINES["lifting_sessions_per_wk"]
    yesterday = shift_day_key(day, -1)
    week_ago = shift_day_key(day, -7)
    trailing = [c for c in completed if c["date"] >= week_ago]
    loaded_yesterday = bool(completed) and completed[-1]["date"] == yesterday
    advisories: list[str] = []
    if loaded_yesterday:
        advisories.append(
            "a loaded session was logged yesterday — the redline puts lifting on non-consecutive days; a walk or Engine day "
            "today keeps this session next, it does not skip it"
        )
    if len(trailing) >= int(lift["high"]):
        advisories.append(
            f"{len(trailing)} loaded sessions in the 7 days before this one — at the redline's {lift['low']}–{lift['high']}/wk "
            "ceiling; another today would exceed it"
        )
    return {
        "loaded_yesterday": loaded_yesterday,
        "loaded_sessions_prior_7d": len(trailing),
        "redline_sessions_per_wk": [lift["low"], lift["high"]],
        "advisories": advisories,
    }


def next_session(day: str, workouts: Iterable[dict[str, Any]] | None) -> dict[str, Any] | None:
    """The next UNDONE session as of `day`, or None before the block start.

    Same shape the generator reads (archetype / session_role / label / week / block / deload)
    plus the position, the count completed and the session that last advanced it.
    `workouts` None means the Hevy record was NOT read: the position is unknown and the
    result says so (`source: "sequence_unreadable"`, no role) — never session 1 by default.
    """
    _check_day(day)
    if day < block_start():
        return None
    if workouts is None:
        return {
            "source": "sequence_unreadable",
            "archetype": None,
            "week": None,
            "note": (
                f"the Hevy record since {block_start()} was not read — the next session in the v0.3 sequence is UNKNOWN "
                f"(it advances only on a completed loaded session, {ISSUE})"
            ),
        }
    done = completed_sessions(workouts, day)
    pos = position(len(done))
    last = done[-1] if done else None
    return {
        **pos,
        "archetype": "full",
        "source": "session_sequence",
        "completed_sessions": len(done),
        "advanced_by": (
            {k: last[k] for k in ("date", "title", "workout_id", "sequence_index", "loaded_logs_that_day")}
            | {"was": position(last["sequence_index"])["position_label"]}
            if last
            else None
        ),
        "advanced_by_note": (
            None if last else f"no loaded Hevy session since the block start ({block_start()}) — this is the first session of the program"
        ),
        "spacing": _spacing(done, day),
        "label": (
            f"full-body {program_structure._ROLE_LABEL[pos['session_role']]} — week {pos['week']} · session {pos['session_in_week']} "
            f"of {pos['sessions_per_week']}, block {pos['block']}" + (" (DELOAD)" if pos["deload"] else "")
        ),
        "rule": (
            "the v0.3 sessions run as a SEQUENCE (heavy -> moderate -> heavy-moderate); the position advances only on a completed "
            f"loaded Hevy session, so a walk or rest day postpones a session and never skips it ({ISSUE})"
        ),
    }


def program_week(day: str, workouts: Iterable[dict[str, Any]] | None) -> int | None:
    """THE program week for `day` — 0 before the block start, None when the Hevy record was not
    read (or the day key is unreadable). Read by the `not_before_week` gate (#4098) and the load
    ramp (#4090) — one function, so the two can never disagree about which week it is."""
    try:
        entry = next_session(day, workouts)
    except ValueError:
        return None
    if entry is None:
        return 0
    return entry.get("week")


def block_boundaries(workouts: Iterable[dict[str, Any]] | None, before_day: str) -> list[str] | None:
    """The dates on which a block after the first opened (its first session completed)."""
    if workouts is None:
        return None
    per_block = int(_seq()["sessions_per_week"]) * int(_seq()["weeks_per_block"])
    return [c["date"] for c in completed_sessions(workouts, before_day) if c["sequence_index"] and c["sequence_index"] % per_block == 0]


# ── the one DDB read (the generator path; MCP reads through its sanctioned helper) ──────
def load_block_workouts(before_day: str) -> list[dict[str, Any]]:
    """Every Hevy per-workout row in [block start, `before_day`) — raises on a failed read.

    Same key shape `exercise_history.load_history_indexes` reads (per-workout rows only,
    `source_workout_id` present); the phase filter off (ADR-058: training continuity), and
    tombstoned rows dropped. MCP callers use `mcp.tools_strength._read_hevy_all_phases`
    instead — the ONE sanctioned Hevy read on that side (#4030/#4032) — and hand the rows to
    the same pure functions above.
    """
    from boto3.dynamodb.conditions import Key
    from experiment.phase_filter import with_phase_filter

    from training import exercise_history

    _check_day(before_day)
    start = block_start()
    if before_day <= start:
        return []
    last_day = shift_day_key(before_day, -1)
    pk = f"USER#{exercise_history.USER_ID}#SOURCE#hevy"
    rows: list[dict[str, Any]] = []
    last_key = None
    while True:
        kwargs: dict[str, Any] = with_phase_filter(
            # #4129: the per-workout rows are DATE#<day>#WORKOUT#<id>, so the END day is closed with
            # "~" — and the end day is the day BEFORE `before_day`, keeping the window [start, before_day).
            {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(f"DATE#{start}", f"DATE#{last_day}~")},
            include_pilot=True,
        )
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key
        resp = exercise_history._table().query(**kwargs)
        for item in resp.get("Items", []):
            if item.get("source_workout_id") and not item.get("tombstone"):
                rows.append(item)
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
    return rows
