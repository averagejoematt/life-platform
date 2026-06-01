"""
tools_hevy_routine.py — `manage_hevy_routine` fat MCP tool (ADR-066).

One tool, nine actions:

  draft         — generate IR + persist as ROUTINE# draft (no Hevy write)
  dry_run       — compile a draft IR into the Hevy wire body for preview
  commit        — push a draft IR to Hevy via the compiler (write tool)
  list          — list ROUTINE# items in a date range
  get           — return one IR by routine_id
  archive       — rename + folder-move (Hevy has no DELETE)
  floor         — generate floor variant explicitly
  re_entry      — force re-entry mode regardless of last-workout date
  adherence     — programmed-vs-performed report for a routine_id

Commit-gate principle: `commit` and `archive` require an explicit
routine_id. No write on inferred intent.

Reminder: the public site / chronicle must never describe this feature
as "autoregulated" while the readiness signal is unvalidated (per Lena's
dissent in REVIEW §4). Correct phrasing: "deterministic volume-landmark
programming with red-day deload guard."
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from mcp.utils import mcp_error

logger = logging.getLogger("tools_hevy_routine")

_VALID_ACTIONS = {
    "draft", "dry_run", "commit", "list", "get",
    "archive", "floor", "re_entry", "adherence",
}


def _ts_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generator_inputs(args: dict[str, Any]):
    from routine_generator import GeneratorInputs
    return GeneratorInputs(
        target_date=args.get("target_date") or datetime.now(timezone.utc).date().isoformat(),
        recovery_tier=args.get("recovery_tier", "yellow"),
        acwr_flag=args.get("acwr_flag", "safe"),
        volume_7d=args.get("volume_7d") or {},
        z2_minutes_7d=float(args.get("z2_minutes_7d") or 0),
        days_since_last_workout=int(args.get("days_since_last_workout") or 2),
        add_load_enabled=False,  # never permitted from chat; SSM-gated only
    )


def _action_draft(args: dict[str, Any]) -> dict[str, Any]:
    from routine_generator import generate_routines
    from routine_repo import put_versioned
    inputs = _generator_inputs(args)
    routines = generate_routines(inputs)
    ideal = next((r for r in routines if r.variant == "ideal"), None)
    floor = next((r for r in routines if r.variant == "floor"), None)
    for ir in routines:
        put_versioned(ir)
    return {
        "status": "drafted",
        "target_date": inputs.target_date,
        "ideal_routine_id": getattr(ideal, "routine_id", None),
        "floor_routine_id": getattr(floor, "routine_id", None),
        "variants_persisted": [r.variant for r in routines],
        "rationale": (ideal.rationale if ideal else []),
        "note": "Use action=dry_run before action=commit. Commit requires explicit routine_id.",
    }


def _action_dry_run(args: dict[str, Any]) -> dict[str, Any]:
    routine_id = args.get("routine_id")
    if not routine_id:
        return mcp_error("dry_run requires routine_id", error_code="MISSING_ARG")
    from hevy_compiler import to_create_body
    from hevy_template_cache import resolve_movement
    from routine_repo import get_current
    ir = get_current(routine_id)
    if not ir:
        return mcp_error(f"routine_id={routine_id} not found", error_code="NOT_FOUND")
    body = to_create_body(ir, resolve_movement)
    return {
        "status": "preview",
        "routine_id": routine_id,
        "wire_body": body,
        "rationale": ir.rationale,
    }


def _action_commit(args: dict[str, Any]) -> dict[str, Any]:
    routine_id = args.get("routine_id")
    if not routine_id:
        return mcp_error(
            "commit requires explicit routine_id — no inferred intent",
            error_code="MISSING_ARG",
        )
    from hevy_compiler import from_hevy_response, to_create_body, to_update_body
    from hevy_template_cache import resolve_movement
    import hevy_write_client as wc
    from routine_repo import get_current, put_versioned, upsert_id_map
    from routine_title import build_title_context, format_why_note
    ir = get_current(routine_id)
    if not ir:
        return mcp_error(f"routine_id={routine_id} not found", error_code="NOT_FOUND")
    try:
        title_ctx = build_title_context(ir)
        why = format_why_note(ir)
        if ir.hevy_routine_id:
            body = to_update_body(ir, resolve_movement,
                                  title_context=title_ctx, why_note=why)
            resp = wc.update_routine_with_guard(
                ir.hevy_routine_id, body, expected_updated_at=ir.hevy_updated_at,
            )
        else:
            body = to_create_body(ir, resolve_movement,
                                  title_context=title_ctx, why_note=why)
            resp = wc.create_routine(body)
        parsed = from_hevy_response(resp)
        ir.hevy_routine_id = parsed["hevy_routine_id"] or ir.hevy_routine_id
        ir.hevy_updated_at = parsed["updated_at"]
        ir.hevy_pushed_at = _ts_now()
        ir.status = "active"
        ir.parent_version = ir.version
        ir.version += 1
        put_versioned(ir)
        if ir.hevy_routine_id:
            try:
                upsert_id_map(ir.routine_id, ir.hevy_routine_id)
            except Exception:
                logger.info(f"id-map already present for routine {ir.routine_id}")
        return {
            "status": "committed",
            "routine_id": ir.routine_id,
            "hevy_routine_id": ir.hevy_routine_id,
            "version": ir.version,
        }
    except wc.HevyOrphanCreated as e:
        # Hevy returned 4xx but created the routine anyway. Link the id locally
        # so future updates target it (instead of POSTing a third copy).
        ir.hevy_routine_id = e.hevy_routine_id
        ir.hevy_updated_at = e.hevy_updated_at
        ir.hevy_pushed_at = _ts_now()
        ir.status = "active"
        ir.parent_version = ir.version
        ir.version += 1
        put_versioned(ir)
        try:
            upsert_id_map(ir.routine_id, ir.hevy_routine_id)
        except Exception:
            pass
        return mcp_error(
            f"Hevy returned {e.status} but created routine {e.hevy_routine_id}. "
            f"Local IR linked to it so future commits target the same routine. "
            f"Inspect in the Hevy app and delete or fix as needed. "
            f"Original Hevy body: {e.body[:200]}",
            error_code="HEVY_ORPHAN_CREATED",
        )
    except wc.HevyConflict as e:
        return mcp_error(
            f"Hevy in-app edit detected — refusing to clobber. {e}",
            error_code="HEVY_CONFLICT",
        )
    except wc.HevyAuthError as e:
        return mcp_error(f"Hevy auth failed (rotate life-platform/hevy-write?): {e}",
                         error_code="HEVY_AUTH")
    except wc.HevyRetryable as e:
        return mcp_error(f"Hevy transient error after retries: {e}",
                         error_code="HEVY_RETRYABLE")


def _action_list(args: dict[str, Any]) -> dict[str, Any]:
    from routine_repo import list_by_date_range
    start = args.get("start_date") or args.get("date") or "2026-05-31"
    end = args.get("end_date") or args.get("date") or start
    items = list_by_date_range(start, end, limit=int(args.get("limit") or 50))
    return {
        "status": "ok",
        "count": len(items),
        "routines": [
            {
                "routine_id": ir.routine_id,
                "target_date": ir.target_date,
                "archetype": ir.archetype,
                "variant": ir.variant,
                "status": ir.status,
                "hevy_routine_id": ir.hevy_routine_id,
                "version": ir.version,
            }
            for ir in items
        ],
    }


def _action_get(args: dict[str, Any]) -> dict[str, Any]:
    routine_id = args.get("routine_id")
    if not routine_id:
        return mcp_error("get requires routine_id", error_code="MISSING_ARG")
    from routine_ir import serialize
    from routine_repo import get_current
    ir = get_current(routine_id)
    if not ir:
        return mcp_error(f"routine_id={routine_id} not found", error_code="NOT_FOUND")
    return {"status": "ok", "routine": serialize(ir)}


def _action_archive(args: dict[str, Any]) -> dict[str, Any]:
    routine_id = args.get("routine_id")
    if not routine_id:
        return mcp_error(
            "archive requires explicit routine_id — no inferred intent",
            error_code="MISSING_ARG",
        )
    from hevy_compiler import to_update_body
    from hevy_template_cache import resolve_movement
    import hevy_write_client as wc
    from routine_repo import get_current, put_versioned
    ir = get_current(routine_id)
    if not ir:
        return mcp_error(f"routine_id={routine_id} not found", error_code="NOT_FOUND")
    if not ir.hevy_routine_id:
        ir.status = "archived"
        ir.parent_version = ir.version
        ir.version += 1
        put_versioned(ir)
        return {"status": "archived_local_only", "routine_id": ir.routine_id,
                "note": "Routine was never pushed to Hevy; nothing to rename."}
    # Ensure an Archive folder, then rename + folder-move in Hevy. Hevy has no DELETE.
    folders = wc.list_folders()
    archive_folder_id = None
    for f in folders.get("routine_folders") or folders.get("folders") or []:
        if (f.get("title") or "").lower() == "archive":
            archive_folder_id = f.get("id")
            break
    if not archive_folder_id:
        created = wc.create_folder("Archive")
        new_folder = created.get("routine_folder") or created
        archive_folder_id = new_folder.get("id")
    ir.title = f"[archived {datetime.now(timezone.utc).date().isoformat()}] {ir.title or ir.archetype}"
    ir.hevy_folder_id = archive_folder_id
    body = to_update_body(ir, resolve_movement)
    try:
        wc.update_routine_with_guard(ir.hevy_routine_id, body,
                                     expected_updated_at=ir.hevy_updated_at)
    except wc.HevyConflict as e:
        return mcp_error(f"Hevy in-app edit detected on archive — refusing to clobber. {e}",
                         error_code="HEVY_CONFLICT")
    ir.status = "archived"
    ir.parent_version = ir.version
    ir.version += 1
    put_versioned(ir)
    return {"status": "archived", "routine_id": ir.routine_id,
            "archive_folder_id": archive_folder_id}


def _action_floor(args: dict[str, Any]) -> dict[str, Any]:
    from routine_generator import generate_routines
    from routine_repo import put_versioned
    inputs = _generator_inputs(args)
    routines = generate_routines(inputs)
    floor = next((r for r in routines if r.variant == "floor"), None)
    if not floor:
        return mcp_error("Generator did not produce a floor variant", error_code="INTERNAL")
    put_versioned(floor)
    return {"status": "drafted_floor", "routine_id": floor.routine_id,
            "target_date": floor.target_date}


def _action_re_entry(args: dict[str, Any]) -> dict[str, Any]:
    from routine_generator import GeneratorInputs, generate_routines
    from routine_repo import put_versioned
    base = _generator_inputs(args)
    inputs = GeneratorInputs(
        target_date=base.target_date,
        recovery_tier=base.recovery_tier,
        acwr_flag=base.acwr_flag,
        volume_7d=base.volume_7d,
        z2_minutes_7d=base.z2_minutes_7d,
        days_since_last_workout=max(base.days_since_last_workout, 7),
        history_last_dates=base.history_last_dates,
        add_load_enabled=False,
    )
    routines = generate_routines(inputs)
    re_entry = next((r for r in routines if r.variant == "re_entry"), None)
    if not re_entry:
        return mcp_error("Generator did not produce a re_entry variant",
                         error_code="INTERNAL")
    put_versioned(re_entry)
    return {"status": "drafted_re_entry", "routine_id": re_entry.routine_id,
            "target_date": re_entry.target_date}


def _action_adherence(args: dict[str, Any]) -> dict[str, Any]:
    routine_id = args.get("routine_id")
    if not routine_id:
        return mcp_error("adherence requires routine_id", error_code="MISSING_ARG")
    from adherence_calc import calculate_adherence
    import hevy_write_client as wc
    from routine_repo import get_current
    ir = get_current(routine_id)
    if not ir:
        return mcp_error(f"routine_id={routine_id} not found", error_code="NOT_FOUND")
    workouts = wc.get_workouts(page=1, page_size=10).get("workouts") or []
    performed: dict[str, Any] = {}
    for w in workouts:
        if (w.get("start_time") or "")[:10] == ir.target_date:
            performed = w
            break
    if not performed:
        return {"status": "no_workout_for_date", "routine_id": routine_id,
                "target_date": ir.target_date}
    return {"status": "ok",
            "routine_id": routine_id,
            "adherence": calculate_adherence(ir, performed)}


_DISPATCH = {
    "draft": _action_draft,
    "dry_run": _action_dry_run,
    "commit": _action_commit,
    "list": _action_list,
    "get": _action_get,
    "archive": _action_archive,
    "floor": _action_floor,
    "re_entry": _action_re_entry,
    "adherence": _action_adherence,
}


def tool_manage_hevy_routine(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Single fat tool for the Hevy routine write-loop. See module docstring."""
    args = args or {}
    action = (args.get("action") or "").strip().lower()
    if action not in _VALID_ACTIONS:
        return mcp_error(
            f"action must be one of: {sorted(_VALID_ACTIONS)}",
            error_code="INVALID_ACTION",
        )
    return _DISPATCH[action](args)
