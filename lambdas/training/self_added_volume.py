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

  * adherence's own counts include warm-ups on both sides (#3714); since #5008 it also stores the working-set twins
    (`programmed_working_sets` / `performed_working_sets`) and THIS report reads those — a warm-up is not added volume.
    Rows ingested before #5008 carry only the inclusive counts and are read as they were;
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
is reported beside it — UNLESS the caller says `end_date` is itself a finished day
(`end_day_complete=True`) and it is that week's Sunday: then the week is over and it is the
latest complete week. The weekly digest passes it (its `end_date` is yesterday); plan_engine and
the critic do not (theirs is a day still being planned or lived). Before #4111's fix a Monday
digest run treated the week that ended the day before as in progress, so the report skipped
the just-ended week. Pure: rows are injected, nothing is fetched.

THE PROPOSAL (#5796). The report stopped at the count: a set he added to the same movement week
after week left the program prescribing the lower number. Each week now also keeps, per prescribed
movement, every matched program session's (prescribed, performed) working sets (`by_movement`).
A movement above its prescription in each of the last `progression.set_raise_proposal.weeks_running`
complete weeks (a charter platform default) becomes a PROPOSAL (`propose_set_raises`): the weeks'
counts, the proposed per-session count, and the headroom under the `volume_ceiling` redline. It
rides the plan's constraint block beside the ceiling-change proposal (`set_raise_for_plan`) and is
never applied here (`auto_applied` is always False) — the owner approves it.
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


def _catalog_movements() -> dict[str, Any]:
    try:
        from health.adherence_calc import _load_catalog

        return (_load_catalog() or {}).get("movements", {}) or {}
    except Exception:  # noqa: BLE001 — a label is never worth a failed report
        return {}


def _label(movement_key: str, row: dict[str, Any]) -> str:
    """A readable name for an adherence movement key — ALWAYS the Hevy title when one is known (#5008 C4).

    The 10-16 report mixed namespaces: a chat-authored `tmpl:<id>` key printed its title ("Squat (Barbell)")
    beside catalog keys printed raw (`leg_press`). `tmpl:<id>` resolves through the row's own exercises, then
    the catalog's `hevy_template_id_hint`; a catalog key resolves to its catalog title; only a key with no
    title anywhere is printed as the key."""
    key = str(movement_key or "")
    movements = _catalog_movements()
    if key.startswith("tmpl:"):
        tid = key[5:]
        for ex in row.get("exercises") or []:
            if str(ex.get("template_id") or "") == tid:  # the normalized row shape (adherence_calc reads the raw one)
                return str(ex.get("name") or ex.get("title") or key)
        for entry in movements.values():
            if str((entry or {}).get("hevy_template_id_hint") or "").upper() == tid.upper() and (entry or {}).get("title"):
                return str(entry["title"])
        return key
    title = (movements.get(key) or {}).get("title")
    return str(title) if title else key


def _week(start: Any, end_date: Any, end_day_complete: bool = False) -> dict[str, Any]:
    end = start + timedelta(days=6)
    return {
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        # a week is over once its Sunday is: before `end_date`, or `end_date` itself when that day is finished (#4111)
        "complete": end < end_date or (end_day_complete and end == end_date),
        "sessions_matched": 0,
        "sessions_unmatched": 0,
        "programmed_sets": 0,
        "performed_sets": 0,
        "net_sets": 0,
        "added_sets": 0,
        "added": [],
        "unprogrammed_exercises": 0,
        "unmatched": [],
        # #5796: per prescribed movement, every matched program session's (prescribed, performed) working sets — the
        # set-raise proposal's evidence (off-program complements never land here)
        "by_movement": {},
        # #4312: off-program complements (Flex) — their own line, never counted against the plan
        "off_program": {"sessions": 0, "archetypes": [], "programmed_sets": 0, "performed_sets": 0, "added_sets": 0, "added": []},
        "sessions_archetype_unresolved": 0,
    }


def _movement_adds(adh: dict[str, Any], row: dict[str, Any], day: Any, bucket: dict[str, Any], **extra: Any) -> None:
    """Accumulate one matched session's per-movement programmed/performed counts into `bucket`."""
    for m in adh["movements"]:
        # #5008 C4: working sets when the row carries them (adherence stores both since #5008); older rows
        # carry only the warm-up-inclusive counts and fall back to them, unchanged
        prog = _int(m["programmed_working_sets"] if "programmed_working_sets" in m else m.get("programmed_sets"))
        perf = _int(m["performed_working_sets"] if "performed_working_sets" in m else m.get("performed_sets"))
        bucket["programmed_sets"] += prog
        bucket["performed_sets"] += perf
        if "by_movement" in bucket and m.get("movement_key"):
            mv = bucket["by_movement"].setdefault(str(m["movement_key"]), {"movement": _label(m.get("movement_key"), row), "sessions": []})
            mv["sessions"].append({"date": day.isoformat(), "programmed_sets": prog, "performed_sets": perf})
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


def weekly_excess(
    hevy_rows: list[dict[str, Any]], end_date: str, weeks: int = LOOKBACK_WEEKS, end_day_complete: bool = False
) -> list[dict[str, Any]]:
    """Per-week programmed vs performed sets, oldest week first, the week containing `end_date` last
    (in progress unless `end_day_complete` and `end_date` is its Sunday)."""
    end = parse_day_key(end_date)
    start_key = window_start(end_date, weeks)
    if end is None or start_key is None:
        return []
    first = parse_day_key(start_key)
    out = [_week(first + timedelta(days=7 * i), end, end_day_complete) for i in range(weeks + 1)]
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


def evaluate(
    hevy_rows: list[dict[str, Any]], end_date: str, threshold_weeks: int, weeks: int = LOOKBACK_WEEKS, end_day_complete: bool = False
) -> dict[str, Any]:
    """The tripwire verdict: `tripped` / `clear` / `unknown`, with the per-week, per-set evidence.

    `end_day_complete`: `end_date` is a finished day, so the week whose Sunday it is counts as
    complete (the weekly digest's yesterday). Default False: a planned or in-progress day.

    `unknown` when the window holds no session at all (nothing to compare — never `clear`),
    or when a week the verdict depends on held sessions none of which matched a committed
    routine. A week with no sessions is NOT above the prescription, so it breaks the run.
    """
    wks = weekly_excess(hevy_rows, end_date, weeks, end_day_complete)
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
    in_progress = not current["complete"] and (current["sessions_matched"] or current["sessions_unmatched"])
    now = f" — in progress, {_week_line(current)}" if in_progress else ""
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


# ── #5796: a set added three weeks running comes back as a proposed raise ─────────────────────────────────────────────
SET_RAISE_KEY = "progression.set_raise_proposal.weeks_running"
SET_RAISE_APPLIES = "a proposal only — the owner approves it; nothing here changes a prescription (auto_applied is always False)"


def set_raise_weeks() -> int:
    """The charter's run length (`progression.set_raise_proposal.weeks_running`, a platform default pending his ruling).
    Read with no fallback: a missing key is a loud error, never a silently different rule."""
    from training.training_charter import charter_value

    n = charter_value(SET_RAISE_KEY)
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise KeyError(f"training charter has no usable {SET_RAISE_KEY} ({n!r})")
    return n


def _volume_headroom(key: str, latest: dict[str, Any], added_per_wk: int, catalog: dict[str, Any]) -> dict[str, Any]:
    """The raise against the `volume_ceiling` redline (`owner_redlines`, sets per muscle per week): the latest complete
    week's prescribed working sets on the movement's primary muscle (catalog), the ceiling, the headroom left and
    whether the raise fits in it. An uncatalogued muscle is named, never guessed."""
    from health.adherence_calc import _catalog_entry_for

    from training import owner_redlines

    ceiling = int(next(t for t in owner_redlines.TRIPWIRES if t["id"] == "volume_ceiling")["threshold"]["sets_per_muscle_wk"])
    muscle_of = {k: _catalog_entry_for(k, catalog).get("primary_muscle") for k in latest["by_movement"]}
    muscle = muscle_of.get(key)
    out: dict[str, Any] = {"redline": "volume_ceiling", "ceiling_sets_per_muscle_wk": ceiling, "muscle": muscle}
    if not muscle:
        return {**out, "headroom_sets": None, "fits": None, "reason": "the movement's primary muscle is not in the catalog"}
    prescribed = sum(s["programmed_sets"] for k, mv in latest["by_movement"].items() if muscle_of.get(k) == muscle for s in mv["sessions"])
    headroom = ceiling - prescribed
    return {
        **out,
        "prescribed_sets_per_wk": prescribed,
        "added_sets_per_wk": added_per_wk,
        "headroom_sets": headroom,
        "fits": added_per_wk <= headroom,
    }


def _raise_for(key: str, run: list[dict[str, Any]], catalog: dict[str, Any]) -> dict[str, Any] | None:
    """One movement's proposal, or None. Above in a week = its sessions' performed working sets exceed the prescribed
    (net over the week); every week of the run must be above. The proposed count is the fewest he performed in any
    session of the run — the count he reached every time — and only a count above today's prescription is proposed."""
    mvs = [w["by_movement"].get(key) for w in run]
    if any(not mv or sum(s["performed_sets"] for s in mv["sessions"]) <= sum(s["programmed_sets"] for s in mv["sessions"]) for mv in mvs):
        return None
    latest = mvs[-1]["sessions"]
    current = latest[-1]["programmed_sets"]
    proposed = min(s["performed_sets"] for mv in mvs for s in mv["sessions"])
    if proposed <= current:
        return None
    weeks = [
        {
            "week_start": w["week_start"],
            "sessions": [{k: s[k] for k in ("date", "programmed_sets", "performed_sets")} for s in mv["sessions"]],
        }
        for w, mv in zip(run, mvs)
    ]
    headroom = _volume_headroom(key, run[-1], (proposed - current) * len(latest), catalog)
    fits = {True: "fits under", False: "would go past", None: "could not be checked against"}[headroom["fits"]]
    return {
        "movement_key": key,
        "movement": mvs[-1]["movement"],
        "weeks": weeks,
        "prescribed_sets_per_session": current,
        "proposed_sets_per_session": proposed,
        "volume_ceiling": headroom,
        "text": (
            f"{mvs[-1]['movement']}: above its prescription {len(run)} weeks running, at least {proposed} working sets every "
            f"session against {current} prescribed. Proposal: prescribe {proposed}. The raise {fits} the weekly volume ceiling "
            f"for {headroom['muscle'] or 'its muscle'}. Nothing changes until you approve."
        ),
    }


def propose_set_raises(weeks: list[dict[str, Any]], weeks_running: int, catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    """`proposed` / `none` / `insufficient` over `weekly_excess`'s weeks: a movement above its prescription in each of the
    last `weeks_running` complete weeks becomes a proposal to raise its prescribed working sets. Pure over its inputs."""
    base: dict[str, Any] = {"weeks_running": weeks_running, "proposals": [], "auto_applied": False, "applies": SET_RAISE_APPLIES}
    run = [w for w in weeks if w.get("complete")][-weeks_running:]
    if len(run) < weeks_running or any(not w.get("sessions_matched") for w in run):
        return {**base, "state": "insufficient", "reason": f"fewer than {weeks_running} complete weeks with a matched program session"}
    cat = catalog if catalog is not None else {"movements": _catalog_movements()}
    proposals = [p for p in (_raise_for(k, run, cat) for k in sorted(run[-1]["by_movement"])) if p]
    return {**base, "state": "proposed" if proposals else "none", "proposals": proposals}


def set_raise_for_plan(
    date: str, rows: list[dict[str, Any]] | None, read_state: str | None, catalog_movements: dict[str, Any] | None
) -> dict[str, Any]:
    """`plan_engine.constraint_block['set_raise_proposal']`, beside the ceiling-change proposal it mirrors (#5058): the
    proposals, or `unknown` when the prescription window was not read — never "no proposal" from a read that did not
    happen (#4072). `date` is the planned day, so its week is in progress and never counts."""
    weeks_running = set_raise_weeks()
    if rows is None or read_state is None:
        return {
            "state": "unknown",
            "reason": f"the prescription window was not read ({read_state or 'read_failed'})",
            "weeks_running": weeks_running,
            "proposals": [],
            "auto_applied": False,
            "applies": SET_RAISE_APPLIES,
        }
    catalog = {"movements": catalog_movements} if catalog_movements is not None else None
    return {"date": date, **propose_set_raises(weekly_excess(rows, date, max(weeks_running, LOOKBACK_WEEKS)), weeks_running, catalog)}
