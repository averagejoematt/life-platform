"""
hevy_compiler.py — Sole owner of the Hevy routine wire format.

Pure functions only — no I/O. Converts a RoutineSpec IR to the JSON body
that POST/PUT /v1/routines expects, and parses the response back into a
diff-friendly summary.

Wire-format isolation is enforced by tests/test_hevy_compiler_isolation.py;
no other module may construct keys like `exercise_template_id`. If the
Hevy API ever changes, one file changes.

Hevy API surface (verified 2026-05-31, see PREREQS §A):
  - POST /v1/routines body  → workout object
  - PUT  /v1/routines/{id}  → workout object WITHOUT folder_id (immutable)
  - Sets nullable; populate the fields appropriate for the exercise type.

Movement -> template resolution is delegated to the template_resolver
callable so this module stays I/O-free.
"""
from __future__ import annotations

from typing import Any, Callable

from routine_ir import ExerciseBlock, RoutineSpec, Set


class MovementUnmappable(Exception):
    """Raised when a movement_key has no Hevy template_id and no resolver path."""


def _set_to_wire(s: Set) -> dict[str, Any]:
    out: dict[str, Any] = {"type": s.type}
    if s.weight_kg is not None:
        out["weight_kg"] = s.weight_kg
    if s.reps is not None:
        out["reps"] = s.reps
    if s.distance_meters is not None:
        out["distance_meters"] = s.distance_meters
    if s.duration_seconds is not None:
        out["duration_seconds"] = s.duration_seconds
    if s.custom_metric is not None:
        out["custom_metric"] = s.custom_metric
    if s.rep_range_start is not None or s.rep_range_end is not None:
        out["rep_range"] = {"start": s.rep_range_start, "end": s.rep_range_end}
    return out


def _exercise_to_wire(ex: ExerciseBlock, template_resolver: Callable[[str], str]) -> dict[str, Any]:
    template_id = template_resolver(ex.movement_key)
    if not template_id:
        raise MovementUnmappable(f"movement_key={ex.movement_key!r} has no Hevy template_id")
    return {
        "exercise_template_id": template_id,
        "superset_id": ex.superset_id,
        "rest_seconds": ex.rest_seconds,
        "notes": ex.notes or "",
        "sets": [_set_to_wire(s) for s in ex.sets],
    }


def to_create_body(ir: RoutineSpec, template_resolver: Callable[[str], str]) -> dict[str, Any]:
    """IR -> POST /v1/routines body. Includes folder_id (set-on-create only)."""
    return {
        "routine": {
            "title": ir.title or f"{ir.archetype}-{ir.target_date}",
            "folder_id": ir.hevy_folder_id,
            "notes": ir.notes or "",
            "exercises": [_exercise_to_wire(ex, template_resolver) for ex in ir.exercises],
        },
    }


def to_update_body(ir: RoutineSpec, template_resolver: Callable[[str], str]) -> dict[str, Any]:
    """IR -> PUT /v1/routines/{id} body. folder_id deliberately omitted (immutable per Hevy)."""
    return {
        "routine": {
            "title": ir.title or f"{ir.archetype}-{ir.target_date}",
            "notes": ir.notes or "",
            "exercises": [_exercise_to_wire(ex, template_resolver) for ex in ir.exercises],
        },
    }


def from_hevy_response(raw: dict[str, Any]) -> dict[str, Any]:
    """Parse a Hevy routine response into a diff-friendly summary.

    Used for: hevy_routine_id capture, updated_at conflict guard, round-trip
    test. Not a full IR — IR is the system of record.
    """
    routine = raw.get("routine", raw)
    if isinstance(routine, list):
        routine = routine[0] if routine else {}
    return {
        "hevy_routine_id": routine.get("id"),
        "title": routine.get("title", ""),
        "folder_id": routine.get("folder_id"),
        "notes": routine.get("notes", ""),
        "updated_at": routine.get("updated_at"),
        "created_at": routine.get("created_at"),
        "exercises": [
            {
                "exercise_template_id": e.get("exercise_template_id"),
                "set_count": len(e.get("sets", [])),
            }
            for e in routine.get("exercises", [])
        ],
    }
