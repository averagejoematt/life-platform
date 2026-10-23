"""warmup_sets.py — the climb to the working load, written into the routine (#5049).

THE DEFECT (owner, 2026-10-18): the routines the platform sent to Hevy started the big lifts
cold — the 10-18 upper session's bench press opened with its first 185 lb working set, so he
added warm-up sets by hand and re-ordered them above the working sets in the app. "I'd like it
to be sending warmup sets when it thinks it's applicable so I can climb to the target not just
go in cold. The notes itself could also recommend warmup stretches if applicable/relevant."

THE RULE (one table, `WARMUP_PRESCRIPTION`). For a COMPOUND lift (an anchor family in
`compound_families`) whose working load is at or above `floor_lb`, warm-up sets are placed
BEFORE the working sets, each a Hevy `warmup` set (`Set.type == "warmup"`, which the compiler
writes as the wire set's `type`):

  * the first warmed lift of the session climbs 50 % x 8, 70 % x 5, 85 % x 3 of its working load;
  * every later warmed compound gets one set, 70 % x 5 — the body is already warm by then.

"First" is the first lift that receives warm-ups, not the first compound slot: a light dumbbell
row under the floor does not climb anyone to a heavy squat. Loads round to the same 5 lb step
the v0.3 ramp rounds a working load to (`rep_scheme.load_step_kg`), in the pound he loads; a
warm-up that would round onto or above the working load (or onto the warm-up before it) is
dropped rather than prescribed. `weight_kg` on a dumbbell lift is one dumbbell, so a 70 lb
dumbbell press sits under the 95 lb floor and gets none — stated, not an accident.

WHAT THIS NEVER TOUCHES: the working sets, their loads, their rep ranges, their RPE ceilings,
and the v0.4 exercise order (owner-locked to 2026-11-04). It only PREPENDS sets typed `warmup`,
and only to a block that carries none — a block whose author already wrote warm-ups (the 10-16
squat, hand-drafted with four) is left exactly as written, and a re-draft never stacks.

THE CUE (`WARMUP_MOVEMENT_CUES`). A warmed lift's note gains one short clause naming one warm-up
movement from a rules table — band pull-aparts before bench, hip hinges before a hinge, ankle/hip
mobility before a squat; none otherwise. Rules, not AI.

THE READERS. A warm-up is not a working set anywhere: `training.routine_generator.
apply_prescription_floor`, `mcp.recovery_authoring.set_floors_kg` (the commit gate),
`load_ramp._rep_range_of`, `health.adherence_calc._working` (#5008's programmed/performed
working-set pair) and `coach.critics.draft_summary` all skip `type == "warmup"`. The session
set ceilings count WORKING sets (`working_set_count`) — a ceiling of hard sets is not breached
by the climb to the first one.

PROVENANCE (ADR-105). Every number in `WARMUP_PRESCRIPTION` is the owner's own issue text, labelled
`owner-pending`: #5049 carries `gate:owner` on exactly these numbers ("recommended: 50/70/85 %
x 8/5/3 for the first compound, 1 set at 70 % for later ones, floor 95 lb"). His word is a
one-line change to this table and to its `provenance`.
"""

from __future__ import annotations

import json
from typing import Any

from training.rep_scheme import LB_IN_KG, load_step_kg

WARMUP_SET_TYPE = "warmup"

WARMUP_PRESCRIPTION: dict[str, Any] = {
    # (fraction of the working load, reps), in climb order
    "first_compound": ((0.50, 8), (0.70, 5), (0.85, 3)),
    "later_compound": ((0.70, 5),),
    "floor_lb": 95.0,
    # the anchor families (`movement_catalog.anchor_family`) that are the big lifts the issue names:
    # bench / squat / deadlift (hinge) / overhead press / row. The vertical pull is not one of them.
    "compound_families": ("bench", "squat", "hinge", "overhead_press", "row"),
    "provenance": "owner-pending",
    "provenance_detail": (
        "#5049 gate:owner — the owner's recommended numbers (50/70/85 % x 8/5/3 first compound, "
        "1 set at 70 % later, floor 95 lb), built as the default until he confirms or changes them (ADR-105)"
    ),
}

WARMUP_MOVEMENT_CUES: dict[str, str] = {
    "bench": "band pull-aparts",
    "hinge": "hip hinges",
    "squat": "ankle/hip mobility",
}
"""One warm-up movement per anchor family (#5049); a family not listed gets none. Owner-pending
with the table above — the issue's own examples."""

CUE_MARKER = "Warm up:"


def is_warmup(s: Any) -> bool:
    """True for a warm-up set — an IR `Set` or a wire/performed dict (`type` or `set_type`)."""
    if isinstance(s, dict):
        t = s.get("type") or s.get("set_type")
    else:
        t = getattr(s, "type", None)
    return str(t or "normal").strip().lower() in ("warmup", "warm_up", "warm-up")


def working_set_count(sets: Any) -> int:
    """Sets that are not warm-ups — what a session set ceiling counts."""
    return sum(0 if is_warmup(s) else 1 for s in sets or [])


def compound_family(movement_key: str, catalog_movements: dict[str, Any]) -> str | None:
    """The anchor family of a block, when it is one of the compound families; else None.

    A catalog key reads its entry's `anchor_family`; a `tmpl:<id>` key (a chat-drafted block
    resolved by Hevy title) reads the catalog entry whose `hevy_template_id_hint` is that id."""
    key = str(movement_key or "")
    entry = (catalog_movements or {}).get(key)
    if entry is None and key.startswith("tmpl:"):
        tid = key[5:].upper()
        entry = next(
            (e for e in (catalog_movements or {}).values() if str((e or {}).get("hevy_template_id_hint") or "").upper() == tid),
            None,
        )
    family = (entry or {}).get("anchor_family")
    return family if family in WARMUP_PRESCRIPTION["compound_families"] else None


def working_load_kg(sets: Any) -> float | None:
    """The heaviest working-set load of a block (the top set), or None when none is loaded."""
    loads = [float(s.weight_kg) for s in sets or [] if not is_warmup(s) and getattr(s, "weight_kg", None)]
    return max(loads) if loads else None


def warmup_ramp(working_kg: float, first: bool) -> list[Any]:
    """The warm-up `Set`s for one lift at `working_kg`, in climb order (may be shorter than the
    rule's when a rounded load would meet the working load or repeat the previous warm-up)."""
    from training.routine_ir import Set

    half_step_kg = 2.5 * LB_IN_KG
    out: list[Any] = []
    for frac, reps in WARMUP_PRESCRIPTION["first_compound" if first else "later_compound"]:
        kg = load_step_kg(float(working_kg) * frac)
        if kg <= 0 or kg >= float(working_kg) - half_step_kg:
            continue
        if out and kg <= out[-1].weight_kg + 1e-9:
            continue
        out.append(Set(type=WARMUP_SET_TYPE, weight_kg=kg, reps=int(reps)))
    return out


def cue_clause(family: str | None) -> str:
    """The note's one warm-up movement clause, or "" when the family has none."""
    move = WARMUP_MOVEMENT_CUES.get(family or "")
    return f"{CUE_MARKER} {move}, then the ramp sets." if move else ""


def attach_warmups(blocks: list[Any], catalog_movements: dict[str, Any]) -> dict[str, Any]:
    """Prepend warm-up sets (and the cue clause) to every qualifying compound block, IN PLACE.

    Returns the audit: the rule table and one row per compound block — what it got, or why it
    got none. Runs AFTER every load pass (floor, ramp, back-offs), so the climb is to the load the
    block actually carries."""
    floor_kg = float(WARMUP_PRESCRIPTION["floor_lb"]) * LB_IN_KG
    rows: list[dict[str, Any]] = []
    warmed = 0
    for block in blocks or []:
        family = compound_family(getattr(block, "movement_key", ""), catalog_movements)
        if family is None:
            continue
        row: dict[str, Any] = {"movement_key": block.movement_key, "family": family}
        rows.append(row)
        if any(is_warmup(s) for s in block.sets or []):
            row["status"] = "authored"  # the author wrote warm-ups — never stacked, never rewritten
            continue
        top = working_load_kg(block.sets)
        if top is None:
            row["status"] = "no_working_load"
            continue
        row["working_kg"] = round(top, 2)
        if top < floor_kg - 1e-6:
            row["status"] = "below_floor"
            continue
        ramp = warmup_ramp(top, first=warmed == 0)
        if not ramp:
            row["status"] = "no_distinct_load"
            continue
        block.sets = ramp + list(block.sets)
        warmed += 1
        row["status"] = "warmed"
        row["position"] = "first" if warmed == 1 else "later"
        row["warmups"] = [{"weight_kg": round(s.weight_kg, 2), "reps": s.reps} for s in ramp]
        clause = cue_clause(family)
        notes = getattr(block, "notes", "") or ""
        if clause and CUE_MARKER not in notes:
            block.notes = f"{notes} {clause}".strip()
        row["cue"] = clause or None
    return {
        "rule": json.loads(json.dumps(WARMUP_PRESCRIPTION)),  # tuples -> lists, so the audit is DDB-serialisable
        "cues": dict(WARMUP_MOVEMENT_CUES),
        "warmed": warmed,
        "warmup_sets": sum(len(r.get("warmups") or []) for r in rows),
        "movements": rows,
    }


def attach_and_note(blocks: list[Any], catalog_movements: dict[str, Any], rationale: list[str]) -> dict[str, Any]:
    """`attach_warmups` plus its one rationale line — the call both generator paths make."""
    audit = attach_warmups(blocks, catalog_movements)
    rationale.append(rationale_line(audit))
    return audit


def rationale_line(audit: dict[str, Any]) -> str:
    """One rationale line naming what the warm-up pass did (or that it did nothing)."""
    warmed = [r for r in audit.get("movements") or [] if r.get("status") == "warmed"]
    if not warmed:
        return f"warm-ups: none added (#5049; floor {WARMUP_PRESCRIPTION['floor_lb']:.0f} lb, {WARMUP_PRESCRIPTION['provenance']})"
    parts = []
    for r in warmed:
        loads = "/".join(f"{w['weight_kg'] / LB_IN_KG:.0f}x{w['reps']}" for w in r["warmups"])
        parts.append(f"{r['movement_key']} {loads}")
    return f"warm-ups (#5049, {WARMUP_PRESCRIPTION['provenance']}; not working sets): " + "; ".join(parts)
