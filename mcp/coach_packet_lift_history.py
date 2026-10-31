"""coach_packet_lift_history.py — per-lift history for the day's programmed lifts, on the session packet (#5501).

WHY THIS EXISTS

The ORDER contract (`training.coach_context.ORDER`) lists `get_exercise_history` and `get_exercise_notes` in the
pre-flight set. The PR #5500 eval over real planning conversations read the chat calling neither before planning
(`get_exercise_history` 0 of 4, `get_exercise_notes` 1 of 4, 2026-10-29..31), while every one of them called
`get_coach_session_packet` first. Option (a) of #5501: the packet carries the per-lift history for the lifts the
program serves on `target_date`, so the pre-flight set is one call. `coach_context.PRE_FLIGHT` then lets a packet
call that carried this field (`PACKET_LIFT_HISTORY`) satisfy the two members.

NO SECOND DERIVATION

  * the lifts      — `mcp.draft_custom_session.resolve_program_session` (`program_structure.planned_session`: the
                     session sequence's next undone session and its §3 prescription — the session
                     `manage_hevy_routine draft` builds), each exposure's Hevy template id through
                     `training.in_block_variant.template_id_for` (#4431, the one slot-template resolver; no network);
  * the history    — `mcp.tools_strength.tool_get_exercise_history` (template_id, the last
                     `LIFT_HISTORY_LOOKBACK_DAYS`), inside a `plan_call_scope` HEVY_ALL_PHASES memo so N lifts are one
                     Hevy read (#5313's stage-2 precedent, `plan_draft_evidence._gather_draft_evidence`);
  * the notes      — `mcp.tools_training_notes.tool_get_exercise_notes` (template_id, the pre-flight lookback).

This module picks rows and clips text; it computes no load, no 1RM and no trend.

THE SIZE CAP (stated once, here; tests/test_coach_packet_lift_history_5501.py holds the serialized bound)

  at most `LIFT_HISTORY_MAX_LIFTS` lifts, `LIFT_HISTORY_SESSIONS_PER_LIFT` performed sessions per lift (newest first,
  each one top set + the working-set count, not every set), one latest note per lift, every free-text note clipped to
  `LIFT_HISTORY_NOTE_CHARS`. The whole field serializes under `LIFT_HISTORY_MAX_BYTES`.

READ STATES

  measured     at least one programmed lift has a performed session in the window;
  absent       `target_date` is not a program lifting session, or no programmed lift has a session in the window;
  read_failed  the program session could not be resolved (raised, via the packet's `_wrap`), or every lift's
               history read failed. One lift's failed read is that lift's own `read_failed`, never an empty history.
"""

from __future__ import annotations

from typing import Any

from common.pacific_time import pacific_weekday, shift_day_key

ISSUE = "#5501"
LIFT_HISTORY_MAX_LIFTS = 10
LIFT_HISTORY_SESSIONS_PER_LIFT = 3
LIFT_HISTORY_LOOKBACK_DAYS = 180
LIFT_HISTORY_NOTE_CHARS = 240
LIFT_HISTORY_MAX_BYTES = 20_000  # the worst case (10 lifts x 3 noted sessions, every note at the clip) is ~17.6 KB

SOURCE = (
    "mcp.coach_packet_lift_history (#5501): the lifts = draft_custom_session.resolve_program_session (program_structure.planned_session) "
    "+ in_block_variant.template_id_for; per lift tools_strength.tool_get_exercise_history (template_id, last "
    f"{LIFT_HISTORY_LOOKBACK_DAYS} days, newest {LIFT_HISTORY_SESSIONS_PER_LIFT} sessions) + tools_training_notes.tool_get_exercise_notes "
    f"(template_id); at most {LIFT_HISTORY_MAX_LIFTS} lifts, notes clipped to {LIFT_HISTORY_NOTE_CHARS} chars"
)


def _clip(text: Any) -> str | None:
    s = str(text or "").strip()
    if not s:
        return None
    return s if len(s) <= LIFT_HISTORY_NOTE_CHARS else s[: LIFT_HISTORY_NOTE_CHARS - 1] + "…"


def _catalog() -> dict[str, Any]:
    from training.routine_generator import _load_json

    return (_load_json("movement_catalog.json") or {}).get("movements") or {}


def programmed_lifts(target_date: str) -> dict[str, Any] | None:
    """The program session served on `target_date` and its lifts, or None when the day is not a program lifting session.
    Raises when the block record cannot be read (the packet reports that as read_failed, never as 'no lifts')."""
    from training.in_block_variant import template_id_for

    from mcp.draft_custom_session import resolve_program_session
    from mcp.plan_hevy_windows import _block_workouts

    planned = resolve_program_session(target_date, _block_workouts(target_date))
    if not planned:
        return None
    rx = planned.get("prescription") or {}
    catalog = _catalog()
    lifts: list[dict[str, Any]] = []
    for e in rx.get("exposures") or []:
        key = e.get("movement_key")
        tid, tid_source = (e.get("template_id"), e.get("template_id_source")) if e.get("template_id") else template_id_for(key, catalog)
        lifts.append(
            {
                "movement_key": key,
                "kind": e.get("kind"),
                "pattern": e.get("pattern"),
                "slot": e.get("slot"),
                "intensity": e.get("intensity"),
                "template_id": tid,
                "template_id_source": tid_source,
            }
        )
    return {
        "date": target_date,
        "weekday": pacific_weekday(target_date),  # #5274
        "session_role": planned.get("session_role"),
        "role_label": rx.get("role_label"),
        "position_label": planned.get("position_label"),
        "lifts": lifts,
    }


def _top_set(sets: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The heaviest logged set (the first at that load) — a pick, not a computation."""
    working = [s for s in sets or [] if s.get("weight_lbs") is not None]
    if not working:
        return None
    top = max(working, key=lambda s: s.get("weight_lbs") or 0)
    return {"weight_lbs": top.get("weight_lbs"), "reps": top.get("reps"), "rpe": top.get("rpe")}


def _session_row(s: dict[str, Any]) -> dict[str, Any]:
    day = str(s.get("date") or "")[:10]
    return {
        "date": day,
        "weekday": pacific_weekday(day),  # #5274: quote it, never derive it
        "exercise_name": s.get("exercise_name"),
        "top_set": _top_set(s.get("sets") or []),
        "working_sets": s.get("set_count"),
        "load_convention": s.get("load_convention"),
        "note": _clip(s.get("note_raw")),
    }


def _history(tid: str, target_date: str) -> dict[str, Any]:
    from mcp.tools_strength import tool_get_exercise_history

    start = shift_day_key(target_date, -LIFT_HISTORY_LOOKBACK_DAYS)
    try:
        res = tool_get_exercise_history({"template_id": tid, "start_date": start, "end_date": target_date}) or {}
    except Exception as e:  # noqa: BLE001 — this lift's history is read_failed by name, the other lifts still read
        return {"state": "read_failed", "error": f"{type(e).__name__}: {e}"[:200]}
    if res.get("error") and not res.get("sessions"):
        if res.get("n_sessions") == 0:
            return {"state": "absent", "detail": f"no logged set for template {tid} in {start}..{target_date}", "sessions": []}
        return {"state": "read_failed", "error": str(res.get("error"))[:200]}
    sessions = list(res.get("sessions") or [])
    newest = sorted(sessions, key=lambda s: str(s.get("date") or ""), reverse=True)[:LIFT_HISTORY_SESSIONS_PER_LIFT]
    return {
        "state": "measured" if newest else "absent",
        "window": {"start": start, "end": target_date},
        "sessions_in_window": len(sessions),
        "sessions": [_session_row(s) for s in newest],
    }


def _notes(tid: str) -> dict[str, Any]:
    from mcp.tools_training_notes import tool_get_exercise_notes

    try:
        res = tool_get_exercise_notes({"template_id": tid}) or {}
    except Exception as e:  # noqa: BLE001
        return {"state": "read_failed", "error": f"{type(e).__name__}: {e}"[:200]}
    if res.get("error"):
        return {"state": "read_failed", "error": str(res.get("error"))[:200]}
    timeline = res.get("timeline") or []
    latest = timeline[-1] if timeline else None
    return {
        "state": "measured" if latest else "absent",
        "layer_status": res.get("layer_status"),
        "pain_flag_any": res.get("pain_flag_any"),  # PROMINENT — confirm or dismiss before loading the movement
        "pain_dates": list(res.get("pain_dates") or [])[-LIFT_HISTORY_SESSIONS_PER_LIFT:],
        "latest_progression": res.get("latest_progression"),
        "latest": (
            {
                "date": latest.get("date"),
                "weekday": pacific_weekday(str(latest.get("date") or "")[:10]),
                "note": _clip(latest.get("note_raw")),
                "pain_flag": latest.get("pain_flag"),
                "sentiment": latest.get("sentiment"),
            }
            if latest
            else None
        ),
    }


def lift_history(target_date: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """(value, status) for the packet's `lift_history` field."""
    from training.plan_engine import ABSENT, MEASURED, READ_FAILED, input_status

    from mcp import plan_call_scope

    session = programmed_lifts(target_date)
    if session is None:
        empty: dict[str, Any] = {"session": None, "lifts": [], "cap": _cap()}
        return empty, input_status(ABSENT, f"{target_date} is not a program lifting session — no programmed lift to read")
    lifts = session.pop("lifts")
    rows: list[dict[str, Any]] = []
    with plan_call_scope.scope(plan_call_scope.HEVY_ALL_PHASES):  # N lifts, one Hevy read (#5313)
        for lift in lifts[:LIFT_HISTORY_MAX_LIFTS]:
            tid = lift.get("template_id")
            if not tid:
                rows.append({**lift, "history": {"state": "no_template_id"}, "notes": {"state": "no_template_id"}})
                continue
            rows.append({**lift, "history": _history(str(tid), target_date), "notes": _notes(str(tid))})
    value: dict[str, Any] = {
        "session": session,
        "lifts": rows,
        "lifts_dropped_by_cap": max(0, len(lifts) - LIFT_HISTORY_MAX_LIFTS),
        "cap": _cap(),
    }
    states = [r["history"]["state"] for r in rows if r["history"]["state"] != "no_template_id"]
    if any(s == "measured" for s in states):
        return value, input_status(MEASURED)
    if states and all(s == "read_failed" for s in states):
        return value, input_status(READ_FAILED, error="ReadError: every programmed lift's history read failed")
    return value, input_status(ABSENT, f"no programmed lift has a logged session in the last {LIFT_HISTORY_LOOKBACK_DAYS} days")


def _cap() -> dict[str, int]:
    return {
        "max_lifts": LIFT_HISTORY_MAX_LIFTS,
        "sessions_per_lift": LIFT_HISTORY_SESSIONS_PER_LIFT,
        "lookback_days": LIFT_HISTORY_LOOKBACK_DAYS,
        "note_chars": LIFT_HISTORY_NOTE_CHARS,
    }
