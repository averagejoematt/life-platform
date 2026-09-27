"""self_added_volume.py — "training above the prescription two weeks running", computed (#4081).

WHY THIS EXISTS

The v0.3 redlines (owner-approved 2026-09-21, #3753) carry a tripwire the red team's
lived-experience seat argued for: `self_added_volume` — training above the prescription two
weeks running, originally read as an anxiety tell rather than enthusiasm ("the 21-hour week is
not his strength, it is his hiding place"). It shipped `evaluated_by_engine: False`, so the
engine named it and never looked. The record it would have read was on the table the whole
time: across cycle 17's first two weeks he performed 4 sets where the committed routine
prescribed 3 on most movements, and finished isolation work at RPE 9.5–10 — against a program
whose authoring rule is subtract-only ("never add").

The owner overruled that reading on 2026-09-23 (#4111): "Just give me an end of week report or
update — I don't think this is anxiety, it's me wanting to do more." `owner_redlines`'s action
for this tripwire changed to a report; the COMPUTATION below did not — the same `evaluate` still
answers `tripped` / `clear` / `unknown` with the same set-level evidence, now read for a report
instead of a veto.

THE COUNT IS NOT COMPUTED HERE

`health.adherence_calc.calculate_adherence` already compares each performed Hevy workout to
the routine that was COMMITTED for it (matched by the Hevy routine id the workout was started
from, else by the Pacific day) and stores the per-movement `programmed_sets` /
`performed_sets` on the workout row at ingest (`adherence.movements`). This module reads
those stored counts and does no set counting of its own — a second counter would be a second
answer (derivation guard). Two consequences it inherits and states:

  * both sides count every logged set, warm-ups included, exactly as adherence does;
  * a performed exercise the routine did not name is `adherence.extra` — it is reported as
    evidence but never counted as added volume here, because a swap (the #3929 alias class)
    and a treadmill block both land in `extra` and a template id alone cannot tell them apart.

`adherence.sets_adherence.performed_sets` is NOT used: it is capped per muscle at the
prescription (it is a completion measure), so it can never show a surplus.

OFF-PROGRAM COMPLEMENTS (#4312, owner 2026-09-26: "Flex-folder / archetype=flex sessions are
off-program complements") are reported on their OWN line and never counted against the plan.
A row whose routine archetype resolves exactly to one outside the program's session archetypes
(`session_sequence.off_program_archetype`, read from the annotation `routine_title.
annotate_with_routine_index` stores at the read seam) goes to the week's `off_program` bucket —
its matched-routine set counts and added sets are listed there, and it is neither a matched nor an
unmatched program session for the verdict. A separate line, not a silent exclusion: #4111 made
this a report, and the Sunday reader should see the Flex adds as what they are. A row with no
annotation (the index was not read) counts as it always did, and the week says so.

THE RULE

A Pacific calendar week (Mon–Sun) is ABOVE the prescription when, across its sessions that
matched a committed routine, the sets performed on prescribed movements exceed the sets
prescribed for them (net: a set added to one movement is offset by a set skipped on
another). The tripwire fires when the `threshold_weeks` most recent COMPLETE weeks are all
above. The week containing `end_date` is in progress and never counts toward the run — it
is reported beside it. Pure: rows are injected, nothing is fetched.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from common.pacific_time import parse_day_key

LOOKBACK_WEEKS = 3
"""Complete weeks read before the in-progress one. Two are the threshold; the third shows the run's length."""

RULE = (
    "a Mon–Sun Pacific week is above the prescription when the sets performed on prescribed movements, across its sessions "
    "matched to a committed routine, exceed the sets prescribed for them (net; per-movement counts are health.adherence_calc's, "
    "stored on the Hevy row at ingest); fires when the most recent `threshold_weeks` complete weeks are all above"
)

ABOVE, AT_OR_BELOW, NO_SESSIONS, UNASSESSABLE = "above", "at_or_below", "no_sessions", "unassessable"


def _int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _num(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def window_start(end_date: str, weeks: int = LOOKBACK_WEEKS) -> str | None:
    """The Monday `weeks` whole weeks before the Monday of `end_date`'s week."""
    d = parse_day_key(end_date)
    if d is None:
        return None
    return (d - timedelta(days=d.weekday() + 7 * weeks)).isoformat()


def _label(movement_key: str, row: dict[str, Any]) -> str:
    """A readable name for an adherence movement key (`tmpl:<id>` resolves through the row's own exercises)."""
    key = str(movement_key or "")
    if key.startswith("tmpl:"):
        tid = key[5:]
        for ex in row.get("exercises") or []:
            if str(ex.get("template_id") or "") == tid:  # the normalized row shape (adherence_calc reads the raw one)
                return str(ex.get("name") or ex.get("title") or key)
    return key


def _week(start: Any, end_date: Any) -> dict[str, Any]:
    end = start + timedelta(days=6)
    return {
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "complete": end < end_date,
        "sessions_matched": 0,
        "sessions_unmatched": 0,
        "programmed_sets": 0,
        "performed_sets": 0,
        "net_sets": 0,
        "added_sets": 0,
        "added": [],
        "unprogrammed_exercises": 0,
        "unmatched": [],
        # #4312: off-program complements (Flex) — their own line, never counted against the plan
        "off_program": {"sessions": 0, "archetypes": [], "programmed_sets": 0, "performed_sets": 0, "added_sets": 0, "added": []},
        "sessions_archetype_unresolved": 0,
    }


def _movement_adds(adh: dict[str, Any], row: dict[str, Any], day: Any, bucket: dict[str, Any], **extra: Any) -> None:
    """Accumulate one matched session's per-movement programmed/performed counts into `bucket`."""
    for m in adh["movements"]:
        prog, perf = _int(m.get("programmed_sets")), _int(m.get("performed_sets"))
        bucket["programmed_sets"] += prog
        bucket["performed_sets"] += perf
        if perf > prog:
            bucket["added_sets"] += perf - prog
            bucket["added"].append(
                {
                    "date": day.isoformat(),
                    "movement": _label(m.get("movement_key"), row),
                    "programmed_sets": prog,
                    "performed_sets": perf,
                    "max_rpe": _num((m.get("intensity") or {}).get("max_rpe")) if isinstance(m.get("intensity"), dict) else None,
                    **extra,
                }
            )


def weekly_excess(hevy_rows: list[dict[str, Any]], end_date: str, weeks: int = LOOKBACK_WEEKS) -> list[dict[str, Any]]:
    """Per-week programmed vs performed sets, oldest week first, the in-progress week last."""
    end = parse_day_key(end_date)
    start_key = window_start(end_date, weeks)
    if end is None or start_key is None:
        return []
    first = parse_day_key(start_key)
    out = [_week(first + timedelta(days=7 * i), end) for i in range(weeks + 1)]
    from training import session_sequence
    from training.routine_title import routine_archetype

    for row in sorted(hevy_rows or [], key=lambda r: (str(r.get("date") or ""), str(r.get("sk") or ""))):
        if row.get("tombstone"):
            continue
        day = parse_day_key(str(row.get("date") or ""))
        if day is None or day < first or day > end:
            continue
        wk = out[(day - first).days // 7]
        adh = row.get("adherence") if isinstance(row.get("adherence"), dict) else None
        matched = adh is not None and adh.get("status") == "matched" and isinstance(adh.get("movements"), list)
        off = session_sequence.off_program_archetype(row)
        if off is not None:  # #4312: a complement — its own bucket, never a program session for the verdict
            op = wk["off_program"]
            op["sessions"] += 1
            if off not in op["archetypes"]:
                op["archetypes"].append(off)
            if matched and adh is not None:
                _movement_adds(adh, row, day, op, archetype=off)
            continue
        if routine_archetype(row) == (None, None):
            wk["sessions_archetype_unresolved"] += 1
        if not matched or adh is None:
            wk["sessions_unmatched"] += 1
            wk["unmatched"].append(
                {"date": day.isoformat(), "title": row.get("title"), "status": (adh or {}).get("status") or "no_adherence_record"}
            )
            continue
        wk["sessions_matched"] += 1
        wk["unprogrammed_exercises"] += len(adh.get("extra") or [])
        _movement_adds(adh, row, day, wk)
    for wk in out:
        wk["net_sets"] = wk["performed_sets"] - wk["programmed_sets"]
        if wk["sessions_matched"]:
            wk["verdict"] = ABOVE if wk["net_sets"] > 0 else AT_OR_BELOW
        elif wk["sessions_unmatched"]:
            wk["verdict"] = UNASSESSABLE
        else:
            wk["verdict"] = NO_SESSIONS
    return out


def _off_program_line(wk: dict[str, Any]) -> str:
    """The complements' own line (#4312), or '' when the week held none."""
    op = wk.get("off_program") or {}
    if not op.get("sessions"):
        return ""
    kinds = "/".join(op.get("archetypes") or []) or "off-program"
    return (
        f"off-program complements ({kinds}): {op['added_sets']} set(s) added over {op['sessions']} session(s) "
        "— not counted against the plan"
    )


def _week_line(wk: dict[str, Any]) -> str:
    return (
        f"week of {wk['week_start']}: {wk['performed_sets']} sets performed vs {wk['programmed_sets']} prescribed "
        f"({wk['net_sets']:+d} net, {wk['added_sets']} added) over {wk['sessions_matched']} matched session(s)"
        + (f", {wk['sessions_unmatched']} unmatched" if wk["sessions_unmatched"] else "")
        + (f"; {_off_program_line(wk)}" if _off_program_line(wk) else "")
    )


def evaluate(hevy_rows: list[dict[str, Any]], end_date: str, threshold_weeks: int, weeks: int = LOOKBACK_WEEKS) -> dict[str, Any]:
    """The tripwire verdict: `tripped` / `clear` / `unknown`, with the per-week, per-set evidence.

    `unknown` when the window holds no session at all (nothing to compare — never `clear`),
    or when a week the verdict depends on held sessions none of which matched a committed
    routine. A week with no sessions is NOT above the prescription, so it breaks the run.
    """
    wks = weekly_excess(hevy_rows, end_date, weeks)
    base: dict[str, Any] = {"rule": RULE, "threshold_weeks": threshold_weeks, "window_end": end_date, "weeks": wks}
    if not wks:
        return {**base, "state": "unknown", "run_weeks": None, "observed": None, "detail": f"unparseable end date {end_date!r}"}
    complete = [w for w in wks if w["complete"]]
    current = wks[-1]
    base["window_start"] = wks[0]["week_start"]
    if all(w["verdict"] == NO_SESSIONS for w in wks):
        off = sum(w["off_program"]["sessions"] for w in wks)
        return {
            **base,
            "state": "unknown",
            "run_weeks": None,
            "observed": None,
            "detail": f"no Hevy session in {wks[0]['week_start']}..{end_date} matched to the program — nothing to compare against a prescription"
            + (f" ({off} off-program complement session(s) only — not the program's, #4312)" if off else ""),
        }
    run = 0
    for w in reversed(complete):
        if w["verdict"] != ABOVE:
            break
        run += 1
    base["run_weeks"] = run
    recent = complete[-threshold_weeks:]
    lines = "; ".join(_week_line(w) for w in recent)
    now = f" — in progress, {_week_line(current)}" if (current["sessions_matched"] or current["sessions_unmatched"]) else ""
    if run >= threshold_weeks:
        return {
            **base,
            "state": "tripped",
            "observed": f"{run} consecutive complete week(s) above the prescription",
            "detail": lines + now,
        }
    if any(w["verdict"] in (AT_OR_BELOW, NO_SESSIONS) for w in recent):
        return {
            **base,
            "state": "clear",
            "observed": f"{run} consecutive complete week(s) above the prescription (threshold {threshold_weeks})",
            "detail": lines + now,
        }
    return {
        **base,
        "state": "unknown",
        "observed": f"{run} consecutive complete week(s) above the prescription (threshold {threshold_weeks})",
        "detail": "a week the verdict depends on held no session matched to a committed routine — " + lines + now,
    }
