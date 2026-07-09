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

from routine_ir import ExerciseBlock, RoutineBranch, RoutineSpec, Set


def _primary_exercises(ir: RoutineSpec) -> list[ExerciseBlock]:
    """Pick the exercise list pushed as the routine's own set/rep content (#417 2b).

    Branchless routines (`ir.branches == []`) push `ir.exercises` unchanged —
    byte-identical to pre-#417 behavior. When branches exist, the RECOMMENDED
    branch's own `exercises` become the pushed exercise list, so the overnight
    re-stamp (which only re-orders/re-flags `recommended`) changes what the
    reader actually sees at the gym, not just a note. Every OTHER branch stays
    visible only in the notes menu (`render_branches_note`) — never pushed as
    the live set/rep list. Falls back to `ir.exercises` if the recommended
    branch carries no exercises of its own (e.g. a branch-light placeholder
    created before branches carried content).
    """
    if not ir.branches:
        return ir.exercises
    recommended = next((b for b in ir.branches if b.recommended), None)
    if recommended is not None and recommended.exercises:
        return recommended.exercises
    return ir.exercises


class MovementUnmappable(Exception):
    """Raised when a movement_key has no Hevy template_id and no resolver path."""


# Hevy's accepted set-type enum. Verified against 765 live sets (only normal/
# warmup ever observed) + the API docs. We historically authored "drop" — which
# Hevy 400-rejects (WORKORDER_HEVY_COMMIT_HARDENING, 2026-06-21) — and other
# aliases, so the wire boundary is the single place that normalizes them.
HEVY_SET_TYPES = ("normal", "warmup", "failure", "dropset")
_SET_TYPE_ALIASES = {
    "normal": "normal",
    "working": "normal",
    "work": "normal",
    "straight": "normal",
    "warmup": "warmup",
    "warm": "warmup",
    "warm-up": "warmup",
    "warm_up": "warmup",
    "failure": "failure",
    "fail": "failure",
    "amrap": "failure",
    "dropset": "dropset",
    "drop": "dropset",
    "drop-set": "dropset",
    "drop_set": "dropset",
}


def normalize_set_type(t: str | None) -> str | None:
    """Map an authored set type to Hevy's enum, or None if unmappable.

    None is the signal the dry_run validator uses to fail loudly naming the
    field. The compiler itself coerces an unmappable value to 'normal' so a
    skipped validation can never produce a silent 400 at commit.
    """
    if not t:
        return "normal"
    return _SET_TYPE_ALIASES.get(str(t).strip().lower())


def sanitize_note(note: str | None) -> str:
    """Strip characters that break the Hevy JSON write surface: C0/C1 control
    chars (except tab/newline) and lone surrogates. Emoji and ordinary unicode
    are PRESERVED — they are valid UTF-8 JSON and the 765-set live audit found
    no evidence Hevy rejects them; the dry_run validator surfaces (does not
    drop) non-ASCII so Matthew can decide. Lossless for real note content.
    """
    if not note:
        return ""
    out: list[str] = []
    for ch in note:
        o = ord(ch)
        if ch in ("\n", "\t"):
            out.append(ch)
        elif o < 0x20 or 0x7F <= o <= 0x9F:
            continue  # C0/C1 control
        elif 0xD800 <= o <= 0xDFFF:
            continue  # lone surrogate
        else:
            out.append(ch)
    return "".join(out)


def _set_to_wire(s: Set) -> dict[str, Any]:
    out: dict[str, Any] = {"type": normalize_set_type(s.type) or "normal"}
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
        "notes": sanitize_note(ex.notes),
        "sets": [_set_to_wire(s) for s in ex.sets],
    }


def render_branches_note(branches: list[RoutineBranch]) -> str:
    """Render a routine's first-class branches into an annotated notes block (#417).

    Hevy holds ONE exercise list per routine, so the branch MENU lives in the
    notes field — the only place the write client can carry alternatives. Every
    branch is rendered (self-selection preserved: the reader can choose any of
    them); the `recommended` branch is starred. Branches render in `order`, so
    the overnight re-stamp re-ordering surfaces here directly. Pure — no I/O.

    Returns "" when there are no branches, so a routine that defines none
    compiles and pushes byte-identical to before (backward compat).
    """
    if not branches:
        return ""
    ordered = sorted(branches, key=lambda b: (b.order, b.label))
    lines = ["— CHOOSE YOUR BRANCH —"]
    for b in ordered:
        marker = "★" if b.recommended else "•"
        rec = " (recommended)" if b.recommended else ""
        cue = f" — {b.cue}" if b.cue else ""
        lines.append(f"{marker} {b.label.upper()}{rec}{cue}")
    lines.append("You choose — every branch is yours to take; the star is only a suggestion.")
    return "\n".join(lines)


def _compose_notes(ir: RoutineSpec, why_note: str | None) -> str:
    """Base WHY note (or ir.notes) + the branch menu, both sanitized for the wire."""
    base = sanitize_note(why_note if why_note is not None else ir.notes)
    branch_block = sanitize_note(render_branches_note(ir.branches))
    if not branch_block:
        return base
    return f"{base}\n\n{branch_block}" if base else branch_block


def _resolve_title(ir: RoutineSpec, title_context: dict[str, Any] | None) -> str:
    """If a title_context is supplied use the ADR-067 format; otherwise keep
    the IR title (or a deterministic fallback). Lazy-imports routine_title so
    compiler unit tests can omit context and stay I/O-free.
    """
    if title_context is None:
        return (ir.title or f"{ir.archetype}-{ir.target_date}")[:60]
    from routine_title import format_title

    return format_title(ir, title_context)


def to_create_body(
    ir: RoutineSpec,
    template_resolver: Callable[[str], str],
    title_context: dict[str, Any] | None = None,
    why_note: str | None = None,
) -> dict[str, Any]:
    """IR -> POST /v1/routines body. Includes folder_id (set-on-create only).

    title_context: optional ADR-067 context (phase / type_count_in_phase /
    all_time_count). If supplied, the compiler renders the title via
    routine_title.format_title. If None, falls back to ir.title.

    why_note: optional one-line WHY summary projected into the Hevy notes
    field. If None, falls back to ir.notes.
    """
    return {
        "routine": {
            "title": _resolve_title(ir, title_context),
            "folder_id": ir.hevy_folder_id,
            "notes": _compose_notes(ir, why_note),
            "exercises": [_exercise_to_wire(ex, template_resolver) for ex in _primary_exercises(ir)],
        },
    }


def to_update_body(
    ir: RoutineSpec,
    template_resolver: Callable[[str], str],
    title_context: dict[str, Any] | None = None,
    why_note: str | None = None,
) -> dict[str, Any]:
    """IR -> PUT /v1/routines/{id} body. folder_id deliberately omitted
    (immutable per Hevy). title_context + why_note semantics match
    to_create_body."""
    return {
        "routine": {
            "title": _resolve_title(ir, title_context),
            "notes": _compose_notes(ir, why_note),
            "exercises": [_exercise_to_wire(ex, template_resolver) for ex in _primary_exercises(ir)],
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
