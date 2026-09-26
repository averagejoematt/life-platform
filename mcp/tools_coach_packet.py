"""tools_coach_packet.py — ONE read of the coaching input packet (#4082).

WHY THIS EXISTS

The owner read eight Claude-chat coaching sessions (2026-09-14 .. 09-22). Each opened by
spending ten or more MCP calls re-verifying the same inputs — per-muscle working sets, the
last session of each type, a week of MacroFactor, walking hours, the streaks, readiness, where
the block is — and the call the session got wrong was, more than once, the one it skipped or
read off a different window than the planner. `get_coach_session_packet` returns them
together, each with a read state, so a chat starts from one fixed set instead of an improvised
one.

NO SECOND DERIVATION

Every number in the packet comes from the function that already owns it; this module only
reads, labels and arranges. The table below is the contract — `SOURCES`, echoed in the
payload, and `tests/test_coach_session_packet_4082.py` holds it by AST (this module may not
import the counting / estimating primitives themselves):

  muscle_volume            `get_muscle_volume` (training.muscle_volume.working_sets_by_muscle,
                           #4071), called with plan_next_session's exact window — the 28
                           completed days before the target — whose `trailing_windows` carry
                           the 7d and 28d tables.
  last_session_by_type     the ONE sanctioned Hevy read (`tools_strength._read_hevy_all_phases`,
                           #4030/#4032), normalised by `training.muscle_volume.normalize_hevy_items`,
                           typed by `training.routine_title.resolve_archetype` (the performed-type
                           resolver the routine counters use), its program role from the v0.4
                           session sequence (`session_sequence.completed_positions` (the #4161 ledger),
                           #4110), loaded-or-not by
                           `training_streaks.is_loaded_session` (#4067).
  nutrition_7d             `get_nutrition` view=summary over plan_next_session's protein window,
                           and `tools_plan._protein_days_7d` for the days-below-floor count.
  walking_hours_7d         `tools_plan._walking_volume_last_7d` -> `shared_quantities.walking_layer`
                           (#4068/#4105 — THE definition).
  loss_rate                `tools_benchmark._loss_rate_block` -> `shared_quantities.loss_rate_from_rows`.
  streaks                  `tools_plan._training_streaks` -> `training_streaks.streaks` (#4067).
  readiness                `get_readiness_score`, tiered by `tools_plan._recovery_tier`.
  readiness_low_streak     `tools_plan._readiness_low_streak` (Whoop, #4072).
  block_position           `session_sequence.next_session` + `session_sequence.program_week` (#4110/#4147),
                           over the planner's block read `plan_hevy_windows._block_workouts`.

READ STATES (#4072's vocabulary, `plan_engine.input_status`)

Every field is `measured`, `absent` (read, and nothing there) or `read_failed` (the read broke —
with its error class). A failed read is never shown as an empty week.
"""

from __future__ import annotations

from typing import Any

from common.pacific_time import pacific_today, shift_day_key

PACKET_VERSION = "coach-session-packet@1.0.0"
# Long enough that each performed type is found once a block is running (a v0.4 role recurs
# weekly; an Engine day twice a week), bounded so the read stays one Hevy query.
LAST_SESSION_LOOKBACK_DAYS = 28
# The routine index's nearest-preceding-routine fallback needs rows from before the window.
ROUTINE_INDEX_LOOKBACK_DAYS = 90

SOURCES: dict[str, str] = {
    "muscle_volume": "get_muscle_volume (training.muscle_volume.working_sets_by_muscle, #4071) — plan_next_session's window",
    "last_session_by_type": (
        "tools_strength._read_hevy_all_phases + training.muscle_volume.normalize_hevy_items; type = "
        "training.routine_title.resolve_archetype, role = session_sequence.completed_positions (#4110/#4161), loaded = training_streaks.is_loaded_session"
    ),
    "nutrition_7d": "get_nutrition view=summary + tools_plan._protein_days_7d (plan_next_session's protein window)",
    "walking_hours_7d": "tools_plan._walking_volume_last_7d -> mcp.shared_quantities.walking_layer (#4068/#4105)",
    "loss_rate": "tools_benchmark._loss_rate_block -> mcp.shared_quantities.loss_rate_from_rows (#4068)",
    "streaks": "tools_plan._training_streaks -> training.training_streaks.streaks (#4067)",
    "readiness": "get_readiness_score, tier by tools_plan._recovery_tier",
    "readiness_low_streak": "tools_plan._readiness_low_streak (Whoop recovery, #4072)",
    "block_position": "training.session_sequence.next_session + program_week over plan_hevy_windows._block_workouts (#4110/#4147)",
}

# Model-facing prose + schema live beside the tool (the #4078 manage_pending_writes precedent), so
# mcp/registry.py pays one import line and one entry against its #1665 baseline.
COACH_PACKET_DESCRIPTION = (
    "CALL FIRST in any training-coaching conversation (#4082). ONE read of the coaching input packet a chat "
    "otherwise spends 10+ calls re-verifying: working sets per muscle over the 7 and 28 completed days, the "
    "last session of each type (and each v0.4 session role — the order-based sequence) with every set and every note, MacroFactor kcal + "
    "protein over 7 days with the protein-floor count, weekly walking hours (THE one definition), the loss "
    "rate, the active-day and loaded-lifting streaks, readiness + the readiness-floor streak, and the v0.4 "
    "sequence position (the next undone session, #4110). Every field states `measured`, `absent` (read, nothing there) or `read_failed` (with the "
    "error class) — a failed read is never an empty week — and names the canonical function it came from; "
    "nothing here is a second computation of any number. Quote it rather than re-pulling a measured field. "
    "It is the planner's INPUTS, not its verdict: plan_next_session still builds the constraint block."
)

COACH_PACKET_INPUT = {
    "type": "object",
    "properties": {
        "target_date": {
            "type": "string",
            "description": "The session being coached, YYYY-MM-DD (default today, Pacific). Volume, walking and streaks read the completed days before it.",
        },
    },
    "required": [],
}


def _st(state: str, detail: str | None = None, **extra: Any) -> dict[str, Any]:
    from training.plan_engine import input_status

    return input_status(state, detail, **extra)


def _field(name: str, value: Any, status: dict[str, Any]) -> dict[str, Any]:
    return {**status, "source": SOURCES[name], "value": value}


# ── the readers that are this module's own (arrangement only — no counting) ───────────
def _muscle_volume(target_date: str) -> tuple[Any, dict[str, Any]]:
    from training.plan_engine import ABSENT, READ_FAILED

    from mcp.tools_plan import _VOLUME_TABLE_KEYS, _read
    from mcp.tools_strength import tool_get_muscle_volume

    start, end = shift_day_key(target_date, -28), shift_day_key(target_date, -1)
    vol, status = _read("muscle_volume", tool_get_muscle_volume, {"start_date": start, "end_date": end})
    if vol is None:
        return None, status
    if not any(k in vol for k in _VOLUME_TABLE_KEYS) or "trailing_windows" not in vol:
        return None, _st(READ_FAILED, error=f"InputShapeError: get_muscle_volume carried no muscle table (keys: {sorted(vol)[:12]})")
    trailing = vol.get("trailing_windows") or {}
    value = {
        "window_7d": trailing.get("7d"),
        "window_28d": trailing.get("28d"),
        "landmark_status_28d": {m: r.get("volume_landmark_status") for m, r in (vol.get("muscle_volume") or {}).items()},
        "unattributed": vol.get("unattributed"),
        "completeness": vol.get("completeness"),
        "method": vol.get("method"),
    }
    if not any((r or {}).get("total_sets") for r in ((trailing.get("28d") or {}).get("muscles") or {}).values()):
        return value, _st(ABSENT, f"no working set in {start}..{end}")
    return value, status


def _session_row(item: dict[str, Any], archetype: str | None, role: str | None) -> dict[str, Any]:
    from training.muscle_volume import normalize_hevy_items
    from training.training_streaks import is_loaded_session

    norm = (normalize_hevy_items([item]) or [{}])[0]
    adh = item.get("adherence") if isinstance(item.get("adherence"), dict) else {}
    return {
        "date": str(item.get("date") or "")[:10],
        "title": item.get("title") or norm.get("workout_name"),
        "workout_uid": item.get("workout_uid"),
        "archetype": archetype,
        "session_role": role,
        "loaded": is_loaded_session(item),
        "duration_sec": item.get("duration_sec"),
        "adherence": {"status": adh.get("status"), "overall_pct": adh.get("overall_pct")} if adh else None,
        "description": item.get("description") or "",
        "exercises": norm.get("exercises") or [],
    }


def _sequence_positions(target_date: str) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """{day: the program position the session sequence credited to that day's session}, through
    `target_date` inclusive — `session_sequence.completed_positions` (#4110; weeks per #4161's ledger), over the
    planner's own block read (`plan_hevy_windows._block_workouts`). The role is the SEQUENCE's,
    never a weekday calendar's (v0.3's lives in `training.program_v03`, SUPERSEDED)."""
    from training import session_sequence
    from training.plan_engine import error_label

    from mcp.plan_hevy_windows import _block_workouts

    after = shift_day_key(target_date, 1)
    try:
        rows = _block_workouts(after)
        done = session_sequence.completed_positions(rows, after)  # #4161: the ledger's hybrid week, one definition
    except Exception as e:  # noqa: BLE001 — roles go unassigned and say why; the sessions still read
        return {}, {"state": "read_failed", "error": error_label(e)}
    out = {c["date"]: {k: v for k, v in c.items() if k not in ("title", "start_time", "loaded_logs_that_day")} for c in done}
    return out, {"state": "measured", "block_start": session_sequence.block_start(), "sessions_credited": len(done)}


def _last_sessions(target_date: str) -> dict[str, Any]:
    """The newest performed session of each type, with every set and every note."""
    from training.routine_title import _load_routine_index, resolve_archetype

    from mcp.tools_strength import _read_hevy_all_phases

    start = shift_day_key(target_date, -LAST_SESSION_LOOKBACK_DAYS)
    items, phases = _read_hevy_all_phases(start, target_date)
    workouts = sorted(
        (it for it in items or [] if "#WORKOUT#" in str(it.get("sk") or "")),
        key=lambda it: (str(it.get("date") or ""), str(it.get("start_time") or "")),
        reverse=True,
    )
    if items and not workouts:
        # Rows came back and none is a per-workout row: the writer's key scheme moved (#2847 seam,
        # hevy_common writes). That is a FAILED read, never "no session in the window" (#4072).
        from mcp.tools_plan import InputShapeError

        raise InputShapeError(f"{len(items)} Hevy row(s) in {start}..{target_date} and none is a DATE#<day>#WORKOUT#<id> row")
    index_state: dict[str, Any] = {"state": "measured"}
    try:
        index = _load_routine_index(shift_day_key(start, -ROUTINE_INDEX_LOOKBACK_DAYS))
    except Exception as e:  # noqa: BLE001 — the TYPE goes unresolved and says why; the sessions still read
        from training.plan_engine import error_label

        index, index_state = [], {"state": "read_failed", "error": error_label(e)}
    positions, sequence_state = _sequence_positions(target_date)
    by_type: dict[str, dict[str, Any]] = {}
    by_role: dict[str, dict[str, Any]] = {}
    for it in workouts:
        day = str(it.get("date") or "")[:10]
        pos = positions.get(day) or {}
        # The ONE loaded session the sequence credited for that day — a second log that day, or an
        # unloaded one, is not a program session and claims no role.
        credited = bool(pos) and pos.get("workout_id") in (None, it.get("source_workout_id") or it.get("workout_id"))
        role = pos.get("session_role") if credited else None
        archetype = resolve_archetype(it, index) or "unresolved"
        if archetype in by_type and (not role or role in by_role):
            continue
        row = _session_row(it, archetype, role)
        if credited:
            row["sequence_position"] = pos.get("position_label")
        by_type.setdefault(archetype, row)
        if role:
            by_role.setdefault(role, row)
    return {
        "window": {"start": start, "end": target_date},
        "sessions_read": len(workouts),
        "phases_read": phases,
        "routine_index": index_state,
        "session_sequence": sequence_state,
        "by_archetype": by_type,
        "by_session_role": by_role,
    }


def _nutrition(target_date: str) -> tuple[Any, dict[str, Any]]:
    from training import owner_redlines
    from training.plan_engine import ABSENT, READ_FAILED

    from mcp.tools_nutrition import tool_get_nutrition
    from mcp.tools_plan import _protein_days_7d, _read

    start = shift_day_key(target_date, -6)
    res, status = _read("nutrition_7d", tool_get_nutrition, {"view": "summary", "start_date": start, "end_date": target_date})
    if res is None:
        return None, status
    if "daily_breakdown" not in res:
        return None, _st(READ_FAILED, error=f"InputShapeError: get_nutrition summary carried no daily_breakdown (keys: {sorted(res)[:12]})")
    pair, pstatus = _read("protein_days_missed_7d", _protein_days_7d, target_date)
    missed, measured = pair or (None, None)
    avgs = res.get("daily_averages") or {}
    cmp_ = res.get("target_comparison") or {}
    value = {
        "window": {"start": start, "end": target_date},
        "days_logged": (res.get("period") or {}).get("days_with_data"),
        "calories_kcal": {"average": avgs.get("calories_kcal"), "vs_target": cmp_.get("calories_kcal")},
        "protein_g": {"average": avgs.get("protein_g"), "vs_target": cmp_.get("protein_g")},
        "protein_floor_g": owner_redlines.REDLINES["protein_floor_g"]["value"],
        "protein_days_below_floor": missed,
        "protein_days_measured": measured,
        "protein_floor_read": pstatus,
        "daily": [
            {"date": r.get("date"), "calories_kcal": r.get("calories_kcal"), "protein_g": r.get("protein_g")}
            for r in res["daily_breakdown"]
        ],
    }
    if not res["daily_breakdown"]:
        return value, _st(ABSENT, f"no MacroFactor day logged in {start}..{target_date}")
    return value, status


def _walking(target_date: str) -> tuple[Any, dict[str, Any]]:
    from training.plan_engine import ABSENT, READ_FAILED

    from mcp.tools_plan import _read, _walking_volume_last_7d

    layer, status = _read("walking_hours_7d", _walking_volume_last_7d, target_date)
    if status["state"] == READ_FAILED:
        return None, status
    if not layer:
        return None, _st(READ_FAILED, error="ValueError: the walking-volume layer could not be built for this window")
    keep = (
        "total_hr",
        "hr_wk",
        "window",
        "by_source",
        "by_modality",
        "total_is_floor",
        "honesty",
        "definition",
        "counting_rule",
        "overlap_rule",
    )
    value = {k: layer.get(k) for k in keep}
    if layer.get("total_hr") is None:
        srcs = layer.get("by_source") or {}
        if srcs and all((b or {}).get("status") == "unreadable" for b in srcs.values()):
            return value, _st(READ_FAILED, error="SourceReadError: neither Strava nor Hevy could be read for the window")
        return value, _st(ABSENT, "no walking/treadmill/cycling duration recorded in the 7 completed days")
    return value, status


def _loss_rate(target_date: str) -> tuple[Any, dict[str, Any]]:
    from training.plan_engine import ABSENT, MEASURED, READ_FAILED

    from mcp.tools_benchmark import _loss_rate_block

    block = _loss_rate_block(target_date)
    if "window" not in block:  # the block's own except-branch: the Withings read raised
        return None, _st(READ_FAILED, error=str(block.get("reason") or "unreadable"))
    if block.get("rate_lb_wk") is None:
        return block, _st(ABSENT, block.get("reason"))
    return block, _st(MEASURED, "provisional — reported, not argued from" if block.get("provisional") else None)


def _streaks(target_date: str) -> tuple[Any, dict[str, Any]]:
    from mcp.tools_plan import _read, _training_streaks

    return _read("streaks", _training_streaks, target_date)


def _readiness(target_date: str) -> tuple[Any, dict[str, Any]]:
    from training.plan_engine import ABSENT, READ_FAILED

    from mcp.tools_health import tool_get_readiness_score
    from mcp.tools_plan import _READINESS_SCORE_KEYS, _read, _recovery_tier

    res, status = _read("readiness", tool_get_readiness_score, {"date": target_date})
    if res is None:
        return None, status
    tier = _recovery_tier(res)
    value = {
        "readiness_score": res.get("readiness_score"),
        "label": res.get("label"),
        "recovery_tier": tier,
        "as_of": res.get("date"),
        "is_forward_dated": res.get("is_forward_dated"),
        "label_confidence": (res.get("label_confidence") or {}).get("level"),
        "missing_components": res.get("missing_components"),
        "recommendation": res.get("recommendation"),
    }
    if tier is None:
        if res and not any(k in res for k in _READINESS_SCORE_KEYS):
            return None, _st(READ_FAILED, error=f"InputShapeError: get_readiness_score carried none of {list(_READINESS_SCORE_KEYS)}")
        return value, _st(ABSENT, "get_readiness_score returned no score for the day")
    return value, status


def _readiness_low_streak(target_date: str) -> tuple[Any, dict[str, Any]]:
    from mcp.tools_plan import _read, _readiness_low_streak as reader

    pair, status = _read("readiness_low_streak", reader, target_date)
    if not pair:
        return None, status
    days, inner = pair
    return {"days_below_floor": days, "threshold": inner.get("threshold"), "latest_day": inner.get("latest_day")}, inner


def _block_position(target_date: str) -> tuple[Any, dict[str, Any]]:
    """Where the program is: `session_sequence.next_session` over the planner's own block read
    (#4110/#4147 — v0.4 served IN ORDER). Passed through whole: position_label, week, role,
    advanced_by. A failed Hevy read raises -> `_wrap` -> read_failed (never session 1)."""
    from training import plan_engine, program_structure, session_sequence

    from mcp.plan_hevy_windows import _block_workouts

    if not program_structure.ACTIVE:
        return None, _st(plan_engine.ABSENT, f"TRAINING_PROGRAM v{program_structure.PROGRAM_VERSION} is not active — no session sequence")
    rows = _block_workouts(target_date)
    entry = session_sequence.next_session(target_date, rows)
    value = {
        "program_version": program_structure.SESSION_SEQUENCE.get("program_version"),
        "block_start": session_sequence.block_start(),
        "program_week": session_sequence.program_week(target_date, rows),
        "next_session": entry,
    }
    if entry is None:
        value["note"] = f"{target_date} is before the block start ({session_sequence.block_start()}) — week 0"
    return value, _st(plan_engine.MEASURED)


def _wrap(fn):
    """A reader that returns (value, status) and may raise -> (value, status) that never raises."""

    def run(target_date: str) -> tuple[Any, dict[str, Any]]:
        from training.plan_engine import READ_FAILED, error_label

        try:
            return fn(target_date)
        except Exception as e:  # noqa: BLE001 — reported by name, never swallowed into an empty field
            return None, _st(READ_FAILED, error=error_label(e))

    return run


def _last_sessions_field(target_date: str) -> tuple[Any, dict[str, Any]]:
    from training.plan_engine import ABSENT, MEASURED

    from mcp.tools_plan import _read

    value, status = _read("last_session_by_type", _last_sessions, target_date)
    if value is None:
        return None, status
    if not value["sessions_read"]:
        return value, _st(ABSENT, f"no Hevy session in {value['window']['start']}..{value['window']['end']}")
    return value, _st(MEASURED)


READERS = {
    "muscle_volume": _muscle_volume,
    "last_session_by_type": _last_sessions_field,
    "nutrition_7d": _nutrition,
    "walking_hours_7d": _walking,
    "loss_rate": _loss_rate,
    "streaks": _streaks,
    "readiness": _readiness,
    "readiness_low_streak": _readiness_low_streak,
    "block_position": _block_position,
}


def tool_get_coach_session_packet(args):
    """Every coaching input in one read, each with measured / absent / read_failed (#4082)."""
    args = args or {}
    target_date = str(args.get("target_date") or pacific_today())[:10]
    from common.pacific_time import parse_day_key

    if parse_day_key(target_date) is None:
        from mcp.utils import mcp_error

        return mcp_error(f"target_date must be YYYY-MM-DD, got {target_date!r}", error_code="INVALID_ARG")
    fields: dict[str, Any] = {}
    for name, reader in READERS.items():
        value, status = _wrap(reader)(target_date)
        fields[name] = _field(name, value, status)
    states = {name: f["state"] for name, f in fields.items()}
    return {
        "target_date": target_date,
        "packet_version": PACKET_VERSION,
        "states": states,
        "not_measured": sorted(n for n, s in states.items() if s != "measured"),
        "fields": fields,
        "how_to_use": (
            "Call this FIRST in a coaching session and quote its numbers — do not re-pull a field whose state is "
            "`measured` unless the owner disputes it. `absent` = read, nothing there (say so); `read_failed` = the "
            "read broke (name the error, never read it as zero). Windows: volume and walking are COMPLETED days before "
            "target_date; nutrition is plan_next_session's protein window. Planning a session is still "
            "plan_next_session (the constraint block + the red team) — this packet is its inputs, not its verdict."
        ),
        "_disclaimer": (
            "For personal health tracking only. Not medical advice. Descriptive of Matthew's own n=1 history. "
            "Consult a qualified healthcare provider before making health decisions based on this data."
        ),
    }
