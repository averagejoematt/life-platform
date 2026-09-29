"""
mcp/tool_output_schemas.py — MCP `outputSchema` for the ten most-called tools (#4286 box 2).

WHICH TEN. Ranked by the trailing-30-day `LifePlatform/MCP` `ToolInvocations` metric
(dimension `ToolName`, the EMF `mcp/handler.py::_emit_tool_metric` emits per dispatch),
read 2026-09-29 for the window 2026-08-30 → 2026-09-29:

    get_weight_loss_progress 243 · get_sources 193 · get_todoist_snapshot 193 ·
    manage_hevy_routine 157 · get_workout_detail 65 · plan_next_session 65 ·
    get_workouts 40 · get_freshness_status 36 · get_date_range 33 · get_capture_queues 28

The rest are tracked by `tests/test_mcp_registry.py` (every tool either carries a schema here
or is counted as not-yet-typed), not silently omitted.

WHAT A SCHEMA PROMISES. The MCP spec (2025-06-18): a tool that declares `outputSchema` MUST
return `structuredContent` conforming to it, and a client validates it — so a schema that
over-claims breaks the tool in Claude Desktop / claude.ai. Every schema below therefore:
  * types only keys READ from the handler's success-path return statements, and lists as
    `required` only the keys EVERY success path returns (derived by AST over the handler,
    then pinned by running each tool over its test fixture);
  * leaves `additionalProperties` open — a new key is not a breaking change;
  * allows `null` wherever the handler can emit one.
A tool's ERROR payloads (`mcp_error(...)` or an ad-hoc `{"error": ...}`) are not in the schema:
the handler returns them with `isError: true` and no `structuredContent`, which the spec
exempts from validation (`handler._call_result`).

`conformance_errors` is a deliberately small JSON-Schema subset (type, properties, required,
items, additionalProperties, anyOf) — the repo carries no `jsonschema` dependency, and these
schemas use nothing outside it. The handler runs it on every structured result: a result that
does not conform is still returned in full as text, flagged `isError`, logged, and counted
(`OutputSchemaMismatch`), so a drifted schema degrades one call visibly instead of silently
failing client-side validation.
"""

from __future__ import annotations

from typing import Any

_STR = {"type": "string"}
_NUM = {"type": "number"}
_OBJ = {"type": "object"}
_ARR = {"type": "array"}
_BOOL = {"type": "boolean"}


def _opt(schema: dict[str, Any]) -> dict[str, Any]:
    """The same schema, also allowing null."""
    t = schema["type"]
    return {**schema, "type": (t if isinstance(t, list) else [t]) + ["null"]}


def _obj(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    missing = [k for k in required if k not in properties]
    if missing:  # a schema-authoring slip, caught at import rather than on the wire
        raise ValueError(f"required keys without a property schema: {missing}")
    return {"type": "object", "properties": properties, "required": sorted(required), "additionalProperties": True}


_WEIGHT_LOSS_PROGRESS = _obj(
    {
        "journey_start_date": _opt(_STR),
        "journey_start_weight": _opt(_NUM),
        "current_weight_lbs": _NUM,
        "current_bmi": _opt(_NUM),
        "current_bmi_category": _opt(_STR),
        "total_lost_lbs": _opt(_NUM),
        "avg_weekly_loss_lbs": _opt(_NUM),
        "projection": _opt(_OBJ),
        "plateau_detected": _opt(_OBJ),
        "milestones_achieved": _OBJ,
        "next_milestone": _opt(_OBJ),
        "weight_series": {"type": "array", "items": _OBJ},
        "recent_weights": {"type": "array", "items": _OBJ},
        "recent_weights_note": _STR,
        "clinical_note": _STR,
    },
    [
        "journey_start_date",
        "journey_start_weight",
        "current_weight_lbs",
        "current_bmi",
        "current_bmi_category",
        "total_lost_lbs",
        "avg_weekly_loss_lbs",
        "projection",
        "plateau_detected",
        "milestones_achieved",
        "next_milestone",
        "weight_series",
        "recent_weights",
        "recent_weights_note",
        "clinical_note",
    ],
)

# {source: {available, first_date, latest_date, state}} — one key per registered source.
_SOURCES = {
    "type": "object",
    "additionalProperties": _obj(
        {"available": _BOOL, "first_date": _opt(_STR), "latest_date": _opt(_STR), "state": {}},
        ["available", "first_date", "latest_date", "state"],
    ),
}

_TODOIST_LOAD = _obj(
    {
        "snapshot_date": _opt(_STR),
        "active_tasks": _opt(_NUM),
        "overdue_tasks": _opt(_NUM),
        "due_today": _opt(_NUM),
        "load_signal": _opt(_STR),
        "priority_breakdown": _OBJ,
        "recent_completions": _OBJ,
        "completions_by_project_yesterday": _OBJ,
    },
    ["snapshot_date", "active_tasks", "overdue_tasks", "due_today", "load_signal", "priority_breakdown", "recent_completions"],
)
_TODOIST_DAY = _obj(
    {
        "date": _opt(_STR),
        "completed_count": _NUM,
        "active_count": _NUM,
        "overdue_count": _NUM,
        "due_today_count": _NUM,
        "priority_breakdown": _opt(_OBJ),
        "completions_by_project": _opt(_OBJ),
        "completed_tasks": _opt(_ARR),
        "tasks_due_today": _opt(_ARR),
    },
    ["date", "completed_count", "active_count", "overdue_count", "due_today_count"],
)
_TODOIST_SNAPSHOT = {"type": "object", "anyOf": [_TODOIST_LOAD, _TODOIST_DAY]}  # MCP: the root is an object

# Eleven actions, eleven shapes (list/get/draft/dry_run/commit/archive/floor/...). No key is on
# every success path, so nothing is required; the keys typed are the ones every action that
# returns them returns as the same type.
_MANAGE_HEVY_ROUTINE = _obj({"status": _STR, "routine_id": _STR, "target_date": _STR}, [])

_WORKOUT_DETAIL = _obj({"workout": _OBJ}, ["workout"])

_PLAN_NEXT_SESSION = _obj(
    {
        "target_date": _STR,
        "constraint_block": _OBJ,
        "protein_days_measured_7d": _opt(_NUM),
        "how_to_use": _STR,
        "_disclaimer": _STR,
        "nutrition_critics": _OBJ,
        "critics": _OBJ,
        "predraft": _OBJ,
    },
    ["target_date", "constraint_block", "protein_days_measured_7d", "how_to_use", "_disclaimer", "nutrition_critics"],
)

_WORKOUTS = _obj(
    {
        "count": _NUM,
        "total": _NUM,
        "start_date": _opt(_STR),
        "end_date": _opt(_STR),
        "source_filter": _opt(_STR),
        "workouts": {"type": "array", "items": _OBJ},
    },
    ["count", "total", "start_date", "end_date", "source_filter", "workouts"],
)

_FRESHNESS_STATUS = _obj(
    {
        "checked_at": _STR,
        "status": _STR,
        "context": _STR,
        "evaluated_sources": _ARR,
        "fresh_count": _NUM,
        "fresh_sources": _ARR,
        "stale_count": _NUM,
        "stale_sources": _ARR,
        "paused_count": _NUM,
        "paused_sources": _ARR,
        "unreadable_count": _NUM,
        "interior_gap_count": _NUM,
        "interior_gaps": _OBJ,
        "macrofactor_format_drift": _opt(_OBJ),
        "output_artifacts": _ARR,
        "output_artifacts_not_ok": _ARR,
        "thresholds_note": _STR,
        "training_notes_health": _OBJ,
    },
    [
        "checked_at",
        "status",
        "context",
        "evaluated_sources",
        "fresh_count",
        "fresh_sources",
        "stale_count",
        "stale_sources",
        "paused_count",
        "paused_sources",
        "unreadable_count",
        "interior_gap_count",
        "interior_gaps",
        "output_artifacts",
        "output_artifacts_not_ok",
        "thresholds_note",
        "training_notes_health",
    ],
)

_DATE_RANGE = {
    "type": "object",
    "anyOf": [
        _obj({"note": _STR, "source": _STR, "items": {"type": "array", "items": _OBJ}}, ["note", "source", "items"]),
        _obj(
            {"note": _STR, "source": _STR, "period": _STR, "aggregated": {"type": "array", "items": _OBJ}},
            ["note", "source", "period", "aggregated"],
        ),
    ],
}

_CAPTURE_QUEUES = _obj(
    {
        "as_of": _STR,
        "how_to_use": _STR,
        "coach_checkin": _OBJ,
        "evening_intake": _OBJ,
        "field_note": _OBJ,
        "freshness_flags": _OBJ,
        "habit_reflection": _OBJ,
        "pending_writes": _OBJ,
        "reading_recalls": _OBJ,
        "suggested_rituals": _OBJ,
    },
    [
        "as_of",
        "how_to_use",
        "coach_checkin",
        "evening_intake",
        "field_note",
        "freshness_flags",
        "habit_reflection",
        "pending_writes",
        "reading_recalls",
        "suggested_rituals",
    ],
)

_SCHEMAS: dict[str, dict[str, Any]] = {
    "get_weight_loss_progress": _WEIGHT_LOSS_PROGRESS,
    "get_sources": _SOURCES,
    "get_todoist_snapshot": _TODOIST_SNAPSHOT,
    "manage_hevy_routine": _MANAGE_HEVY_ROUTINE,
    "get_workout_detail": _WORKOUT_DETAIL,
    "plan_next_session": _PLAN_NEXT_SESSION,
    "get_workouts": _WORKOUTS,
    "get_freshness_status": _FRESHNESS_STATUS,
    "get_date_range": _DATE_RANGE,
    "get_capture_queues": _CAPTURE_QUEUES,
}


def output_schema_for(tool_name: str) -> dict[str, Any] | None:
    """The tool's `outputSchema`, or None for a tool not yet typed."""
    return _SCHEMAS.get(tool_name)


def attach_output_schemas(tools: dict[str, Any]) -> None:
    """Set `schema.outputSchema` on each typed tool (called once from mcp/registry.py, like
    `tool_annotations.annotate_tools`). `handle_tools_list` emits `schema` verbatim."""
    for name, entry in tools.items():
        schema = output_schema_for(name)
        if schema is not None:
            entry["schema"]["outputSchema"] = schema


def is_error_payload(result: Any) -> bool:
    """A tool's own error return: `mcp_error(...)` or an ad-hoc `{"error": "..."}`."""
    return isinstance(result, dict) and isinstance(result.get("error"), str) and bool(result["error"])


_TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def conformance_errors(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Every way `value` violates `schema` (the subset this module uses); [] when it conforms."""
    if "anyOf" in schema:
        branches = [conformance_errors(value, s, path) for s in schema["anyOf"]]
        if any(not b for b in branches):
            return []
        return [f"{path}: matches no anyOf branch ({'; '.join(b[0] for b in branches)})"]
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_TYPE_CHECKS[x](value) for x in types):
            return [f"{path}: expected {'|'.join(types)}, got {type(value).__name__}"]
    errs: list[str] = []
    if isinstance(value, dict):
        props = schema.get("properties") or {}
        for k in schema.get("required") or []:
            if k not in value:
                errs.append(f"{path}: missing required key {k!r}")
        extra = schema.get("additionalProperties", True)
        for k, v in value.items():
            if k in props:
                errs.extend(conformance_errors(v, props[k], f"{path}.{k}"))
            elif extra is False:
                errs.append(f"{path}: unexpected key {k!r}")
            elif isinstance(extra, dict):
                errs.extend(conformance_errors(v, extra, f"{path}.{k}"))
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for i, v in enumerate(value):
            errs.extend(conformance_errors(v, schema["items"], f"{path}[{i}]"))
    return errs
