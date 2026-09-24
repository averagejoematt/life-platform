"""session_sequence.py — the program's sessions as a SEQUENCE, not a weekday calendar (#4110),
counted into program weeks on BOTH sessions and the calendar (#4161).

WHY THIS EXISTS

#4064 bound each v0.3 session to a weekday: block 1 Thu 09-24 / Sat 09-26 / Mon 09-28, then
Mon/Wed/Fri. Owner, 2026-09-23: "we plan 7 days a week of exercise with seldom rest days but
sometimes I'll listen to body and do a walk instead, so more just focusing on planned sequence
and not forgetting next if I audible a change." Under a weekday calendar a walk on a lifting
day silently SKIPPED that session, and the next date's session was served although the
previous one never happened. The same evening the owner switched to v0.4 Upper/Lower (#4147),
ORDER-BASED: Upper-heavy -> Lower-heavy -> Upper-volume -> Lower-volume, repeating, the next
session being the one after the last PERFORMED lift. This module serves that order.

#4161 (the 2026-09-24 evidence red team, owner-approved the same day): a program week used to
be four completed sessions, so at his pace (5–6 lifts a week) the load ramp, the
`not_before_week` gates and the deload arrived 25–50 % faster than calendar time — and tendon
adapts on calendar time (Kubo 2010; Bohm 2015). A week is now HYBRID: it advances only when
its 4-session cycle is complete AND >= 7 Pacific days have passed since the previous advance.

THE RULE, AS ARITHMETIC (pure — every Hevy row is injected; the numbers are
`program_structure.SESSION_SEQUENCE` and `WEEK_RULE`, one definition each)

  completed   = the distinct Pacific days in [block start, the planned day) carrying a LOADED
                Hevy session — `training_streaks.is_loaded_session`, the ONE definition (#4105):
                a non-warm-up set with weight > 0 on an exercise that is not a cardio modality.
                A walk, an Engine day (treadmill + bike + stretching) or a rest day carries no
                load, so it never advances the position.
  index       = len(completed)                       (0-based: the next UNDONE session)
  role        = session_roles[(offset + index) % 4]  offset = the index of `first_role`
                                                     (Lower-heavy — the committed first v0.4 session)
  week        = walk the sessions in order (`ledger`): week 1 opens on the block start; a session
                opens the NEXT week only when the current week already holds >= 4 sessions AND
                its day is >= 7 days after the day the current week opened. A session that has
                the four but not the seven days is an EXTRA session of the current week
                (`advance_blocked_by: "calendar_floor"`). The role still rotates by index — the
                order never waits on the calendar; only the ramp clock does.
  deload      = one pre-planned deload window (`owner_redlines` `lifting_sessions_per_wk.deload`):
                it opens on the first session in program week >= 6 dated on/after
                `program_structure.BLOCK_LOCK['locked_until']` (2026-11-04) — the LATER of the two —
                and covers `days` (7) calendar days at −40 % sets, loads held, never a week off.
                The next one is due `every_nth_week` program weeks after the week it opened.
  block       = (week - 1) // weeks_per_block + 1

RULINGS (#4110/#4147/#4161 — stated so a reader can dispute them, not discover them)

  * The weekday calendar is RETIRED, not kept as a suggestion: two answers to "what is next"
    is the defect. Before the block start the weekday grid still answers (as it did).
  * The sequence starts at Lower-heavy, the session the owner committed from chat on 2026-09-23
    (target 2026-09-25). Counting starts 2026-09-24, the first Pacific day after the switch, so
    a lift on Thursday advances it exactly as Friday's would; no pre-switch lift ever does.
  * A session logged ON the planned day is the one that day's plan served; it advances the
    NEXT day's plan. So the plan for a date is stable all day — a re-run after the workout (the
    stage-2 critics, the commit gate) sees the same session the draft was built for.
  * Two loaded logs on one Pacific day are ONE session (a split or re-started log), never two.
  * Any loaded session advances the position — the plan does not try to decide from a Hevy
    title whether he "really" did the upper day. The session that advanced it is named
    (`advanced_by`: date, title, workout id) so a mismatch is visible, not inferred.
  * #4161: "the 4-session cycle is complete" is read as ">= 4 sessions in the CURRENT week",
    not "at a multiple of 4 in the sequence": with the latter, one blocked advance would push the
    next boundary four more sessions out and a week would run ~9 days at his pace — slower than
    the calendar the rule exists to follow. The week that opens after a blocked advance opens at
    the first session on/after day 7, whatever its role.
  * The redline's calendar ceiling (3–4 lifting sessions a week) is reported as an ADVISORY
    beside the served session (`spacing`), never by skipping it — the owner audibles, the plan
    remembers. v0.3's "non-consecutive days" advisory is gone: the order alternates upper and
    lower, so back-to-back days never load the same region twice.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from common.pacific_time import parse_day_key, shift_day_key

from training import program_structure, training_streaks

ISSUE = "#4110"
PROGRAM_ISSUE = "#4147"
WEEK_ISSUE = "#4161"

WEEK_RULE: dict[str, Any] = {
    "sessions_per_week": "program_structure.SESSION_SEQUENCE['sessions_per_week']",
    "floor_days": 7,
    "rule": "a program week advances only when its 4-session cycle is complete AND >= 7 Pacific days have passed since the previous advance",
    "provenance": "population-derived",
    "evidence": (
        "tendon adapts on calendar time, not session count: Kubo 2010 JSCR 24(2):322 doi:10.1519/JSC.0b013e3181c865e2 "
        "(tendon stiffness lags muscle over weeks of training); Bohm 2015 Sports Med Open 1:7 doi:10.1186/s40798-015-0009-9 "
        "(tendon adaptation needs weeks of loading at high strain)"
    ),
    "approved": "owner, 2026-09-24 (the red team's recommendation, session chat)",
    "stated": "2026-09-24",
    "issue": WEEK_ISSUE,
}
"""The hybrid week (ADR-105: the 7 days is the calendar week the ramp was written in; the evidence says why a calendar floor at all)."""


def _seq() -> dict[str, Any]:
    return program_structure.SESSION_SEQUENCE


def block_start() -> str:
    return str(_seq()["block_start"])


def _floor_days() -> int:
    return int(WEEK_RULE["floor_days"])


def _check_day(day: str) -> str:
    if parse_day_key(day) is None:
        raise ValueError(f"not a YYYY-MM-DD day key: {day!r}")
    return day


def _days(a: str, b: str) -> int:
    """Whole Pacific days from day key `a` to day key `b`."""
    pa, pb = parse_day_key(a), parse_day_key(b)
    if pa is None or pb is None:
        raise ValueError(f"not a YYYY-MM-DD day key: {a!r} / {b!r}")
    return (pb - pa).days


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


# ── the deload and the block lock (#4161) ─────────────────────────────────────────────
def deload_cfg() -> dict[str, Any]:
    """The owner's deload, one home (`owner_redlines`), with the lock date resolved from `BLOCK_LOCK`."""
    cfg = program_structure._deload_cfg()
    cfg["not_before_date"] = str(program_structure.BLOCK_LOCK["locked_until"])
    return cfg


# program_version is NOT structure (#4161 review): a version bump with no structural change must not read `violated`
_STRUCTURAL_KEYS = ("session_roles", "first_role", "sessions_per_week", "weeks_per_block", "block_start")


def structure_fingerprint() -> str:
    """sha256 over what `BLOCK_LOCK` calls STRUCTURE: the split, the order, the templates, the accessories."""
    body = {
        "split": program_structure.SPLIT,
        "sequence": {k: _seq().get(k) for k in _STRUCTURAL_KEYS},
        "templates": program_structure.SESSION_TEMPLATES,
        "accessory_pool": program_structure.ACCESSORY_POOL,
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:16]


def fingerprint_record_problems(lock: dict[str, Any] | None = None) -> list[str]:
    """Why `BLOCK_LOCK`'s recorded fingerprint is not an OWNER-attested record, or [] (#4161 review).

    A re-recorded `structure_fingerprint` must travel with `structure_fingerprint_record`: the same value,
    `provenance: "owner"`, a `stated` day key, and a `ref` naming the decision or issue that allowed it —
    so re-recording the lock can never be how a structural edit quietly passes the guard."""
    lock = lock if lock is not None else program_structure.BLOCK_LOCK
    rec = lock.get("structure_fingerprint_record") or {}
    out = []
    if rec.get("fingerprint") != lock.get("structure_fingerprint"):
        out.append(f"record names {rec.get('fingerprint')!r}, the lock holds {lock.get('structure_fingerprint')!r}")
    if rec.get("provenance") != "owner":
        out.append("record provenance is not 'owner'")
    if parse_day_key(str(rec.get("stated") or "")) is None:
        out.append("record carries no dated `stated`")
    if "#" not in str(rec.get("ref") or ""):
        out.append("record names no decision/issue `ref`")
    return out


def block_lock_state(day: str) -> dict[str, Any]:
    """The owner's v0.4 block lock as a guard the engine READS (#4161; it was recorded, not enforced).

    `locked` until `locked_until`. While locked, a structure whose fingerprint differs from the one
    recorded at the lock is `violated` — the served session says so and names both fingerprints, and
    `tests/test_hybrid_week_deload_lock_4161.py` refuses the edit at CI. Loads and deloads are not
    structure: they run as written."""
    lock = program_structure.BLOCK_LOCK
    locked = day < str(lock["locked_until"])
    live, recorded = structure_fingerprint(), str(lock.get("structure_fingerprint"))
    problems = fingerprint_record_problems(lock)
    state = ("violated" if live != recorded or problems else "locked") if locked else "open"
    return {
        "state": state,
        "locked_until": lock["locked_until"],
        "structure_fingerprint": live,
        "recorded_fingerprint": recorded,
        "rule": lock["rule"],
        "record_problems": problems,
        **(
            {
                "refusal": f"a STRUCTURAL edit to v{_seq().get('program_version')} before {lock['locked_until']} — the owner's block lock ({WEEK_ISSUE})"
            }
            if state == "violated"
            else {}
        ),
    }


# ── the ledger: every session's week, in order ─────────────────────────────────────────
def ledger(dates: list[str], day: str | None = None) -> list[dict[str, Any]]:
    """The program position of each completed session (`dates`, oldest first, one per day) and —
    when `day` is given — of the NEXT session served on `day`, as the last element. Pure.

    THE one place a week, a deload and a block are computed (#4161); every reader goes through it."""
    seq = _seq()
    per = int(seq["sessions_per_week"])
    roles = seq["session_roles"]
    offset = roles.index(seq.get("first_role") or roles[0])
    floor = _floor_days()
    dl = deload_cfg()
    dl_days, dl_every = int(dl["days"]), int(dl["every_nth_week"])
    due_week, not_before = int(dl["at_program_week"]), dl["not_before_date"]
    week, opened, in_week = 1, block_start(), 0
    dl_start: str | None = None
    dl_week = 0
    out: list[dict[str, Any]] = []
    for i, d in enumerate(list(dates) + ([day] if day is not None else [])):
        prev_opened, since, before = opened, _days(opened, d), in_week
        blocked, advanced = None, False
        if in_week >= per:
            if since >= floor:
                week, opened, in_week, advanced = week + 1, d, 0, True
            else:
                blocked = "calendar_floor"
        in_week += 1
        if dl_start is not None and _days(dl_start, d) >= dl_days:
            dl_start, due_week, not_before = None, dl_week + dl_every, None
        if dl_start is None and week >= due_week and (not_before is None or d >= not_before):
            dl_start, dl_week = d, week
        deload = dl_start is not None and _days(dl_start, d) < dl_days
        role = roles[(offset + i) % len(roles)]
        label = program_structure._ROLE_LABEL[role].lower()
        if in_week <= per:
            pos_label = f"week {week} · session {in_week} of {per} · {label}"
        else:
            pos_label = f"week {week} · session {in_week} (extra — the {floor}-day floor holds week {week + 1} until {shift_day_key(opened, floor)}) · {label}"
        out.append(
            {
                "sequence_index": i,
                "date": d,
                "program_version": seq.get("program_version"),
                "archetype": program_structure.SESSION_TEMPLATES[role]["archetype"],
                "week": week,
                "session_in_week": in_week,
                "sessions_per_week": per,
                "session_role": role,
                "block": (week - 1) // int(seq["weeks_per_block"]) + 1,
                "deload": deload,
                "position_label": pos_label + (" · DELOAD" if deload else ""),
                "week_basis": {
                    "rule": WEEK_RULE["rule"],
                    "sessions_completed": i,
                    "sessions_in_prior_week_state": before,
                    "week_opened_on": opened,
                    "previous_advance_on": prev_opened,
                    "days_since_last_advance": since,
                    "floor_days": floor,
                    "advanced_here": advanced,
                    "advance_blocked_by": blocked,
                    "next_advance_earliest": shift_day_key(opened, floor),
                },
                "deload_window": {"started_on": dl_start, "days": dl_days} if deload else None,
            }
        )
    return out


def preview(n_sessions: int, *, every_days: int = 1, start_day: str | None = None) -> list[dict[str, Any]]:
    """The next `n_sessions` positions assuming one session every `every_days` from `start_day`
    (default: the block start) — the ledger over synthetic dates, so a preview can never use a
    different week rule from the one served."""
    s = start_day or block_start()
    return ledger([shift_day_key(s, i * max(1, int(every_days))) for i in range(max(0, int(n_sessions)))])


def completed_positions(workouts: Iterable[dict[str, Any]] | None, before_day: str) -> list[dict[str, Any]]:
    """`completed_sessions` with each session's ledger position merged in (the coach packet's read)."""
    done = completed_sessions(workouts, before_day)
    return [{**pos, **c} for c, pos in zip(done, ledger([c["date"] for c in done]))]


def _spacing(completed: list[dict[str, Any]], day: str) -> dict[str, Any]:
    """The redline's calendar advisories beside the served session — never a reason to skip it."""
    from training import owner_redlines

    lift = owner_redlines.REDLINES["lifting_sessions_per_wk"]
    yesterday = shift_day_key(day, -1)
    week_ago = shift_day_key(day, -7)
    trailing = [c for c in completed if c["date"] >= week_ago]
    loaded_yesterday = bool(completed) and completed[-1]["date"] == yesterday
    advisories: list[str] = []
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
                f"the Hevy record since {block_start()} was not read — the next session in the v{_seq().get('program_version')} sequence is UNKNOWN "
                f"(it advances only on a completed loaded session, {ISSUE})"
            ),
        }
    done = completed_sessions(workouts, day)
    led = ledger([c["date"] for c in done], day)
    pos = {k: v for k, v in led[-1].items() if k != "date"}
    last = done[-1] if done else None
    basis = pos["week_basis"]
    dl = deload_cfg()
    return {
        **pos,
        "source": "session_sequence",
        "completed_sessions": len(done),
        # #4161: the week counter's basis, flat, so a reader of the served session sees WHY it is this week
        "days_since_last_advance": basis["days_since_last_advance"],
        "advance_blocked_by": basis["advance_blocked_by"],
        "deload_plan": {
            "rule": (
                f"one pre-planned deload at the LATER of program week {dl['at_program_week']} or {dl['not_before_date']} "
                f"(the block lock): {dl['sets_pct']} % sets for {dl['days']} days, loads {dl['loads']}, never a week off"
            ),
            "at_program_week": dl["at_program_week"],
            "not_before": dl["not_before_date"],
            "sets_pct": dl["sets_pct"],
            "days": dl["days"],
            "evidence": dl.get("evidence"),
        },
        "block_lock": block_lock_state(day),
        "advanced_by": (
            {k: last[k] for k in ("date", "title", "workout_id", "sequence_index", "loaded_logs_that_day")}
            | {"was": led[-2]["position_label"]}
            if last
            else None
        ),
        "advanced_by_note": (
            None if last else f"no loaded Hevy session since the block start ({block_start()}) — this is the first session of the program"
        ),
        "spacing": _spacing(done, day),
        "label": (
            f"{program_structure._ROLE_LABEL[pos['session_role']]} — week {pos['week']} · "
            + (
                f"session {pos['session_in_week']} of {pos['sessions_per_week']}"
                if pos["session_in_week"] <= pos["sessions_per_week"]
                else f"extra session {pos['session_in_week']} (the {basis['floor_days']}-day floor holds the next week until {basis['next_advance_earliest']})"
            )
            + f", block {pos['block']}"
            + (" (DELOAD)" if pos["deload"] else "")
        ),
        "rule": (
            f"the v{_seq().get('program_version')} sessions run as a SEQUENCE ("
            + " -> ".join(program_structure._ROLE_LABEL[r].lower() for r in _seq()["session_roles"])
            + f", from {program_structure._ROLE_LABEL[_seq()['first_role']].lower()}); the position advances only on a completed "
            f"loaded Hevy session, so a walk or rest day postpones a session and never skips it ({ISSUE}, {PROGRAM_ISSUE}); "
            f"the WEEK advances only when its {pos['sessions_per_week']}-session cycle is complete AND >= {basis['floor_days']} days "
            f"have passed since the previous advance ({WEEK_ISSUE})"
        ),
    }


def program_week(day: str, workouts: Iterable[dict[str, Any]] | None) -> int | None:
    """THE program week for `day` — 0 before the block start, None when the Hevy record was not
    read (or the day key is unreadable). Read by the `not_before_week` gate (#4098) and the load
    ramp (#4090) — one function, so the two can never disagree about which week it is.

    #4161: a program week is HYBRID — it advances only when its 4-session cycle is complete AND >= 7
    days have passed since the previous advance (`ledger`, `WEEK_RULE`). The deload and the block lock
    read the same ledger; `BLOCK_LOCK` is enforced as a guard (`block_lock_state`)."""
    try:
        entry = next_session(day, workouts)
    except ValueError:
        return None
    if entry is None:
        return 0
    return entry.get("week")


def block_boundaries(workouts: Iterable[dict[str, Any]] | None, before_day: str) -> list[str] | None:
    """The dates on which a block after the first opened (the session that opened its first week)."""
    if workouts is None:
        return None
    per_block = int(_seq()["weeks_per_block"])
    return [p["date"] for p in completed_positions(workouts, before_day) if p["week_basis"]["advanced_here"] and p["week"] % per_block == 1]


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
