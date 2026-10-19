"""draft_custom_session.py — a chat-drafted routine inherits its program slot (#5005).

On 2026-10-18 a `draft_custom` of the same upper-volume movements as the engine draft carried
`rationale_tag: custom` on every block. The commit gate reads a block's slot off that tag
(`load_ramp.slot_of(sets, rationale_tag)` — the last `:` field is the exposure intensity), so
"custom" resolved to NO intensity, the rep cap fell back to the lowest program RPE ceiling
(8, not the volume slot's 9; `ceiling_basis` "unknown intensity", #4149) and the bench floor
recomputed to 79.38 kg against the engine's 83.91 kg on identical sets. Same session, two
floors, depending only on which path wrote the draft.

This module closes that: when the custom draft's target date resolves to a program session
(`program_structure.planned_session`, the session SEQUENCE's answer — the same resolver the
planner and `hevy_prescription_gate.v03_load_rule` read), every block whose movement the
prescription contains gets the engine's own tag (`{kind}:{pattern or key}:{intensity}`, the
string `full_body_session._blocks_from_prescription` writes), and the routine is stamped with
the slot's `session_role`. A movement the prescription does not contain stays `custom`.

Nothing here computes a load, a floor or a ceiling: the gate derives every floor from the tag
exactly as it does for the engine draft, so this makes the two paths check the SAME numbers and
never loosens either. Fail-soft: a read that fails leaves every block `custom` (the old
behaviour) and says so by name in the result — it never costs the draft.

#5049: the same module gives the chat draft the warm-up climb the generator writes
(`attach_draft_warmups`, over `training.warmup_sets` — one rule table for both paths).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

CUSTOM_TAG = "custom"
CALENDAR_KEYS = ("source", "week", "block", "deload", "label", "session_role", "session_in_week", "sequence_index", "position_label")


def engine_tag(exposure: dict[str, Any]) -> str:
    """The rationale tag the engine draft writes for one exposure (`full_body_session`)."""
    return f"{exposure['kind']}:{exposure.get('pattern') or exposure.get('movement_key')}:{exposure['intensity']}"


def _exposure_index(rx: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """movement key -> exposure; a title-only in-block variant also answers to `tmpl:<id>` (#4409)."""
    out: dict[str, dict[str, Any]] = {}
    for e in (rx or {}).get("exposures") or []:
        if e.get("movement_key"):
            out.setdefault(str(e["movement_key"]), e)
        if e.get("template_id"):
            out.setdefault(f"tmpl:{e['template_id']}", e)
    return out


def inherit_tags(blocks: list[Any], rx: dict[str, Any]) -> list[dict[str, Any]]:
    """Re-tag, IN PLACE, every block whose movement `rx` prescribes; return one row per block.
    Pure. A block the prescription lacks keeps its tag (`custom`, or the title of a tmpl block)."""
    index = _exposure_index(rx)
    rows: list[dict[str, Any]] = []
    for b in blocks:
        key = str(getattr(b, "movement_key", "") or "")
        e = index.get(key)
        if e is None:
            rows.append({"movement_key": key, "rationale_tag": b.rationale_tag, "intensity": CUSTOM_TAG, "inherited": False})
            continue
        b.rationale_tag = engine_tag(e)
        rows.append({"movement_key": key, "rationale_tag": b.rationale_tag, "intensity": e["intensity"], "inherited": True})
    return rows


def resolve_program_session(
    target_date: str, block_workouts: list[dict[str, Any]] | None, deload_records: list[dict[str, Any]] | None = None
) -> dict[str, Any] | None:
    """The program session the sequence serves on `target_date` (with its prescription), or None
    when the date is not a program session (program inactive, before the block start, a
    non-lifting role, or the sequence unreadable). The engine's own inputs: the catalog, the
    week grid's skill ceiling and the in-block record (`planned_session`)."""
    from training import deload_word, program_structure
    from training.program_seam import resolve_week_grid
    from training.routine_generator import _load_json

    if not program_structure.ACTIVE:
        return None
    week = resolve_week_grid(_load_json).week or {}
    planned = program_structure.planned_session(
        target_date,
        block_workouts=block_workouts,
        catalog_movements=(_load_json("movement_catalog.json") or {}).get("movements") or {},
        skill_ceiling=int(week.get("skill_ceiling", 2)),
        # #5070: a deload applies only on his recorded word — injected like block_workouts; None = one fail-soft read here
        deload_records=deload_records if deload_records is not None else deload_word.load_records_failsoft(),
    )
    if planned.get("source") != "session_sequence" or not planned.get("prescription"):
        return None
    return planned


def inherit_program_session(
    blocks: list[Any], target_date: str, block_workouts_reader=None, deload_records: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """The draft_custom seam: resolve the slot, re-tag the blocks, and return what to stamp.

    `{"status": "inherited", "calendar": {...session_role...}, "movements": [...]}` on a program
    session; otherwise `{"status": "not_a_program_session" | "read_failed", ...}` with every
    block left as it was."""
    if block_workouts_reader is None:
        from mcp.plan_hevy_windows import _block_workouts as block_workouts_reader
    try:
        planned = resolve_program_session(target_date, block_workouts_reader(target_date), deload_records)
    except Exception as e:  # noqa: BLE001 — named on the draft, never a lost draft
        return {"status": "read_failed", "error": f"{type(e).__name__}: {e}"[:200], "rule": "#5005: every block stays custom"}
    if planned is None:
        return {"status": "not_a_program_session", "rule": "#5005: no program slot on this date — every block stays custom"}
    calendar = {k: planned.get(k) for k in CALENDAR_KEYS}
    calendar["inherited_by"] = "draft_custom"
    return {
        "status": "inherited",
        "calendar": calendar,
        "movements": inherit_tags(blocks, planned["prescription"]),
        "rule": "#5005: a movement the slot prescribes carries the engine's tag; any other stays custom",
    }


def stamp_program_slot(ir: Any, block_workouts_reader=None, deload_records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """`inherit_program_session` on a built draft IR, IN PLACE: re-tags its blocks, stamps
    `inputs_snapshot.program_slot` (always) and `inputs_snapshot.calendar` (on a program session —
    the key `nightly_predraft._routine_role` and the site read the role from), and records one
    rationale line. Runs AFTER the content-derived routine id, so the id never moves with it."""
    slot = inherit_program_session(list(ir.exercises or []), ir.target_date, block_workouts_reader, deload_records)
    ir.inputs_snapshot["program_slot"] = slot
    if slot.get("calendar"):
        ir.inputs_snapshot["calendar"] = slot["calendar"]
        n = sum(1 for m in slot["movements"] if m["inherited"])
        ir.rationale.append(
            f"program slot {slot['calendar'].get('session_role')} ({slot['calendar'].get('position_label')}): "
            f"{n} of {len(slot['movements'])} movements carry the slot's intensity; the rest stay custom (#5005)"
        )
    else:
        ir.rationale.append(f"program slot: {slot['status']} — every movement stays custom (#5005)")
    return slot


def attach_draft_warmups(ir: Any, catalog: dict[str, Any], args: dict[str, Any]) -> dict[str, Any] | None:
    """#5049: the chat path gets the SAME warm-up climb the generator writes — the 10-18 bench shipped
    through draft_custom and opened on its 185 lb working set. A block that already carries warm-ups is
    left as authored; `warmups=false` opts the whole draft out. Runs after `_new_routine_id` (as the
    cardio cue does) and before `draft_versioned`, so the persisted draft is what dry_run/commit push.
    Fail-soft: no warm-up path can cost a draft; the snapshot records what happened."""
    if args.get("warmups") is False or str(args.get("warmups")).lower() == "false":
        ir.inputs_snapshot["warmups"] = {"status": "opted_out"}
        return None
    try:
        from training.warmup_sets import attach_warmups, rationale_line

        audit = attach_warmups(ir.exercises, catalog)
        ir.rationale.append(rationale_line(audit))
        ir.inputs_snapshot["warmups"] = audit
        return audit
    except Exception as e:  # noqa: BLE001
        logger.warning(f"draft_custom: warm-up pass failed ({e}); sets untouched")
        ir.inputs_snapshot["warmups"] = {"status": "failed", "error": str(e)[:200]}
        return None


def _history_index() -> dict[str, list]:
    from training.exercise_history import FLOOR_LOOKBACK_DAYS, load_history_indexes

    return load_history_indexes(lookback_days=FLOOR_LOOKBACK_DAYS)[0]


def _authored_top(sets: list[Any] | None, rep_range: tuple[int, int] | None) -> tuple[float, int]:
    """(heaviest non-warm-up `weight_kg`, authored reps) of a draft_custom block — read straight off
    the sets, with no reps requirement: a block authored `rep_range_start/end` and no `reps` is a
    sanctioned input (tools_hevy_routine `reps|rep_range_start/end`), and `load_progression.top_set`
    would drop it as a non-working set. Reps are the range's bottom (or `reps`), so 'carried' means
    the authored prescription already holds the step at its least demanding end."""
    loads = [
        float(s.weight_kg)
        for s in sets or []
        if str(getattr(s, "type", None) or "normal").lower() not in {"warmup", "warm_up", "warm-up"} and getattr(s, "weight_kg", None)
    ]
    return (max(loads) if loads else 0.0), (rep_range[0] if rep_range else 0)


def attach_step_due(ir: Any, catalog: dict[str, Any], history_reader=None) -> list[dict[str, Any]]:
    """#5057: the chat draft names the stall rule's step on every block where it is due.

    The generator APPLIES the step (`routine_generator._progress_block` → `load_progression`);
    draft_custom's loads are the caller's, verbatim (ADR-069), so here the step is reported, not
    written: a block authored below it gets the reason in its exercise note, and every due step
    is returned for the response and recorded in `inputs_snapshot.step_due`. Same rule, same
    numbers (`load_progression.stall_step`). Fail-soft: a failed read is named, never a lost draft."""
    try:
        from training import load_progression as lp
        from training.load_ramp import _rep_range_of

        index = (history_reader or _history_index)()
        rows: list[dict[str, Any]] = []
        for b in ir.exercises or []:
            key = str(getattr(b, "movement_key", "") or "")
            tid = ((catalog or {}).get(key) or {}).get("hevy_template_id_hint") or (
                key[len("tmpl:") :] if key.startswith("tmpl:") else None
            )
            step = lp.stall_step(list(index.get(tid) or []) if tid else [], rep_range=_rep_range_of(b.sets))
            if step is None:
                continue
            load_kg, reps = _authored_top(b.sets, _rep_range_of(b.sets))
            carried = load_kg >= step["next_load_kg"] - lp.LOAD_TOLERANCE_KG and reps >= int(step["next_reps"] or 0)
            if not carried:
                b.notes = f"Step due: {step['reason']}. {b.notes}".strip()  # #5083: the step LEADS the note
            rows.append({"movement_key": key, "carried": carried, **step})
        ir.inputs_snapshot["step_due"] = rows
        return rows
    except Exception as e:  # noqa: BLE001
        logger.warning(f"draft_custom: step_due pass failed ({e}); blocks untouched")
        ir.inputs_snapshot["step_due"] = {"status": "failed", "error": str(e)[:200]}
        return []


def finish_custom_draft(ir: Any, catalog: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    """The draft_custom passes that run after the content-derived id and before `draft_versioned`,
    in order — the slot tags (#5005), the warm-up climb (#5049), the stall rule's step (#5057) —
    returned as the response's `warmup_sets` / `program_slot` / `step_due` fields."""
    ir.inputs_snapshot["departure_reason"] = departure_reason(args)  # #5055: on the IR, so the spec-ledger row carries it
    program_slot = stamp_program_slot(ir)
    warmups = attach_draft_warmups(ir, catalog, args)
    return {"warmup_sets": (warmups or {}).get("warmup_sets", 0), "program_slot": program_slot, "step_due": attach_step_due(ir, catalog)}


MIN_REASON_CHARS = 12
_EXERCISES_USAGE = (
    "draft_custom requires a non-empty 'exercises' list "
    "[{movement_key|title, sets:[{weight_lbs|weight_kg, reps|rep_range_start/end, "
    "count?}], rest_seconds?, superset_id?, notes?}]"
)
_REASON_USAGE = (
    "draft_custom requires 'departure_reason': the engine authors the loads (manage_hevy_routine action=draft is the default); "
    f"say in one line (>= {MIN_REASON_CHARS} chars) why this session departs from the engine's draft, or call action=draft instead."
)


def departure_reason(args: dict[str, Any]) -> str:
    """#5055: the stated reason a chat session authored loads itself instead of taking the engine's `draft`."""
    return " ".join(str(args.get("departure_reason") or "").split())


def custom_args_refusal(args: dict[str, Any]) -> tuple[str, str] | None:
    """(message, error_code) when `draft_custom`'s args are unusable — no exercises, or no departure_reason (#5055)."""
    exercises = args.get("exercises")
    if not isinstance(exercises, list) or not exercises:
        return _EXERCISES_USAGE, "MISSING_ARG"
    if len(departure_reason(args)) < MIN_REASON_CHARS:
        return _REASON_USAGE, "DEPARTURE_REASON_REQUIRED"
    return None
