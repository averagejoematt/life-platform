"""draft_standing_constraint.py — the draft obeys the standing constraint and the 🟢 tripwire (#5000).

The 2026-10-18 draft (`2167c0e68e25f311d46f1015cbefc047`) shipped three defects against the
owner's hand-built routine (`014e1142aaad30b3b3b1fb5e90046dc2`):

  1. Whoop-band tier cues on the first exercise, though the standing constraint of 2026-10-10
     (the HR regime change) invalidates every HR-derived tier — the gate is that morning's ECG
     plus feel;
  2. the 🟢 branch printed although `protein_floor_missed` was tripped 6 of 7 — and that
     tripwire's action withholds the 🟢 block for the week (#4503 OD5, `training.green_block`);
  3. `cardio_pick` computed (recumbent cycling) but no cardio block in the draft, and the pick
     carried an HR ceiling and target the constraint forbids.

This module is the draft path's I/O for all three, each fail-soft and NAMED when it fails — a
failed read never costs the draft and never reads as "no constraint" or "tripwire clear":

  * `read_standing_constraint` — THE reader: `training.standing_constraints.active_constraint`
    (the code registry, the part the draft acts on) plus the stop list, read verbatim from the
    platform-memory row the registry entry names;
  * `protein_tripwire` — the `protein_floor_missed` state over THE protein-gate window
    (`mcp.tools_plan._protein_days_7d`, the count the critics read) against the owner's threshold;
  * `cardio_block` — the day's block from the charter's cardio menu (#5076: kind, machine, minutes
    and dose), appended to the ideal routine;
  * `apply_gate` — the ECG + feel gate in place of the band cues when a constraint is active.

Nothing here changes the v0.4 structure (split, order, templates, accessories, loads): the gate
only writes NOTES and caps RPE at or below the plan's own ceiling, and the cardio block is
appended after the last lift.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger("draft_standing_constraint")

GREEN_TRIPWIRE = "protein_floor_missed"


def _read_memory_summary(memory_sk: str) -> str | None:
    """The one platform-memory row's summary by its exact key (a Query, so a tombstoned or
    soft-deleted note reads as absent). None when the row is not there."""
    from boto3.dynamodb.conditions import Attr, Key

    from mcp.tools_memory import _DELETED_AT_FIELD, _get_table, _memory_pk

    resp = _get_table().query(
        KeyConditionExpression=Key("pk").eq(_memory_pk()) & Key("sk").eq(memory_sk),
        FilterExpression=Attr(_DELETED_AT_FIELD).not_exists() & Attr("tombstone").not_exists(),
    )
    items = resp.get("Items") or []
    return str(items[0].get("summary") or "") if items else None


def read_standing_constraint(target_date: str, memory_reader: Callable[[str], str | None] | None = None) -> dict[str, Any] | None:
    """The active standing constraint for `target_date`, with its stop list — or None when none is active.

    `memory_read` is `ok` | `missing` | `failed:<ExceptionType>`; on anything but `ok` the stop list
    is None and the gate says, in the routine, that it could not be read."""
    from training import standing_constraints

    c = standing_constraints.active_constraint(target_date)
    if c is None:
        return None
    reader = memory_reader or _read_memory_summary
    stop_list, state = None, "missing"
    try:
        summary = reader(c["memory_sk"])
        if summary:
            stop_list = standing_constraints.stop_list_from(summary, c["stop_list_rule"])
            state = "ok" if stop_list else "missing"
    except Exception as e:  # noqa: BLE001 — named on the record, never a lost draft
        logger.warning("standing constraint: memory read failed: %s", e)
        state = f"failed:{type(e).__name__}"
    return {**c, "stop_list": stop_list, "memory_read": state}


def protein_tripwire(target_date: str, reader: Callable[[str], tuple[int | None, int | None]] | None = None) -> dict[str, Any]:
    """`protein_floor_missed` for the draft: tripped | clear | unknown, with the counts."""
    from training import owner_redlines

    t = next(x for x in owner_redlines.TRIPWIRES if x["id"] == GREEN_TRIPWIRE)
    try:
        read = reader
        if read is None:
            from mcp.tools_plan import _protein_days_7d

            read = _protein_days_7d
        missed, measured = read(target_date)
    except Exception as e:  # noqa: BLE001 — unknown, never clear
        logger.warning("green block: protein read failed: %s", e)
        return {"id": GREEN_TRIPWIRE, "state": "unknown", "detail": f"protein read failed ({type(e).__name__})"}
    if missed is None:
        return {"id": GREEN_TRIPWIRE, "state": "unknown", "detail": "no intake rollup for the trailing 7 days"}
    tripped = int(missed) >= int(t["threshold_days"])
    return {
        "id": GREEN_TRIPWIRE,
        "state": "tripped" if tripped else "clear",
        "missed": int(missed),
        "measured": measured,
        "threshold_days": int(t["threshold_days"]),
        "provenance": t["provenance"],
    }


def green_withheld_reason(trip: dict[str, Any]) -> str | None:
    """The words the routine carries when the tripwire withholds 🟢, or None when it does not (#4503 OD5)."""
    from training import green_block

    if trip.get("id") in green_block.GREEN_BLOCKED_BY and trip.get("state") == "tripped":
        return f"protein floor missed {trip['missed']} of 7"
    return None


def cardio_block(
    target_date: str,
    archetype: str,
    constraint: dict[str, Any] | None,
    layer: Any = None,
    cardio_index: dict[str, list] | None = None,
    previous: dict[str, Any] | None = None,
) -> tuple[Any, dict[str, Any]]:
    """(ExerciseBlock | None, pick) — the day's block from the charter's cardio menu (#5076).

    The kind and the machine are `cardio_menu.choose_kind` over this week's performed cardio
    (`cardio_index`, None = unread: no conditioning is counted, so the placement starts the week) and the
    48 h walking load in `layer`; the minutes are the menu's (`cardio_menu.block_minutes`). The block's
    `rationale_tag` carries the kind (`cardio:<key>:menu:<kind>`) so the history pass that follows
    (`attach_cardio_cues`) doses the same block rather than re-placing it. `pick` is
    `recent_aerobic.cardio_pick` (the served stage-1 pick, HR fields dropped under the constraint) with the
    menu's choice under `menu`. Under a constraint that forbids HR prescriptions the note carries no HR.
    `previous` (`cardio_menu.previous_performed`) is the previous performed session: the recumbent serves a
    conditioning block only the day after the heavy lower session (owner ruling 2026-10-25 on #5076)."""
    from training import cardio_menu, cardio_note, recent_aerobic
    from training.routine_ir import ExerciseBlock, Set

    try:
        if layer is None:
            from mcp import shared_quantities

            layer = shared_quantities.recent_aerobic_layer(target_date)
        pick = recent_aerobic.cardio_pick(layer, archetype, target_date)
        hist = cardio_menu.history_context(cardio_index, _catalog(), target_date)
        menu = cardio_menu.choose_kind(
            target_date=target_date,
            archetype=archetype,
            week_kinds=hist["week_kinds"],
            prior_day_kind=hist["prior_day_kind"],
            legs_loaded=recent_aerobic.legs_loaded(layer)[0],
            last_tempo_or_hills=hist["last_tempo_or_hills"],
            previous=previous,
        )
    except Exception as e:  # noqa: BLE001 — named, never a lost draft
        logger.warning("cardio block: pick failed: %s", e)
        return None, {"state": "failed", "error": type(e).__name__}
    key, kind = menu["machine"], menu["kind"]
    compose = lambda k, m: cardio_note.compose(  # noqa: E731 — one call shape, used twice below
        movement_key=key,
        minutes=m,
        target_date=target_date,
        archetype=archetype,
        kind=k,
        treadmill_sessions=hist["by_machine"].get(cardio_menu.TREADMILL),
        aerobic_block=layer,
        constraint=constraint,
        hr_ceiling_bpm=pick.get("hr_ceiling_bpm"),
        placement_why=menu["why"],
        previous=previous,
    )
    minutes = cardio_menu.block_minutes(kind)
    notes, audit = compose(kind, minutes)
    if audit["kind"] != kind:  # the no-push gate demoted a hard kind: the minutes and the pick follow the kind the note carries
        kind = audit["kind"]
        minutes = cardio_menu.block_minutes(kind)
        notes, audit = compose(kind, minutes)
    pick = cardio_menu.align_pick(pick, kind, key)  # #5201: pick, block and note name one modality and one cue
    block = ExerciseBlock(
        movement_key=key,
        sets=[Set(duration_seconds=minutes * 60)],
        notes=notes,
        rationale_tag=f"cardio:{key}:menu:{audit['kind']}",
    )
    menu_out = {"kind": audit["kind"], "machine": key, "minutes": minutes, "why": menu["why"], "previous_session": previous}
    return block, {**pick, "menu": menu_out}


def _catalog() -> dict[str, Any]:
    from training.routine_generator import _load_json

    return _load_json("movement_catalog.json")


def _cardio_index_failsoft() -> dict[str, list] | None:
    """His cardio history for the placement, or None (named in the log) when it cannot be read."""
    try:
        from training.exercise_history import DEFAULT_LOOKBACK_DAYS, FLOOR_LOOKBACK_DAYS, load_history_indexes

        return load_history_indexes(lookback_days=max(DEFAULT_LOOKBACK_DAYS, FLOOR_LOOKBACK_DAYS))[1]
    except Exception as e:  # noqa: BLE001 — the placement then counts no conditioning this week
        logger.warning("cardio block: history read failed: %s", e)
        return None


def _refresh_session_shape(ideal: Any) -> None:
    """#5201: the shape the generator stamped was computed BEFORE this path appended the cardio block, so its
    `cardio_blocks` read empty. Re-run the charter's shape enforcement over the routine as it now stands (one cardio
    block, the cap) and fold the answer into `inputs_snapshot["session_shape"]`. Fail-soft: the block keeps its minutes."""
    try:
        from training import program_structure

        shape = program_structure.enforce_session_shape(ideal.exercises, _catalog().get("movements") or {})
        snap = ideal.inputs_snapshot or {}
        ideal.inputs_snapshot = {**snap, "session_shape": {**(snap.get("session_shape") or {}), **shape}}
    except Exception as e:  # noqa: BLE001 — named, never a lost draft
        logger.warning("cardio block: session shape refresh failed: %s", e)


def _is_accessory(ex: Any) -> bool:
    return str(getattr(ex, "rationale_tag", "") or "").split(":")[0] == "accessory"


def apply_gate(
    ir: Any, ctx: dict[str, Any], inputs_current_through: str | None, constraint: dict[str, Any], green_withheld: str | None
) -> dict:
    """The ECG + feel gate in place of the Whoop-band block (#5000). Writes notes only.

    First exercise: the gate (sinus → the plan, ≤ RPE 8; not sinus → ≤ RPE 7, accessories and
    cardio optional; the 🟢 withheld line when tripped; the stop list), then the subtract-only load
    rule. Primaries: the gate cue instead of the 🟢/🟡/🔴 line. Accessories: optional when not sinus.
    The stashed branches carry the sinus cap as the ceiling, so adherence grades against ≤ RPE 8.

    #5167 (owner ruling 2026-10-23, the date split): a draft dated on/after the constraint's
    `lifting_caps_retired_from` carries no lifting cap — the gate lines and the per-lift cue name the
    charter's `effort_ceilings`, and every stashed branch's `rpe_cap` is the charter compound ceiling
    (none when the charter cannot be read: adherence then falls to the program default). A draft dated
    before that day is byte-identical to the pre-#5167 output."""
    from training import effort_ceilings, standing_constraints

    from mcp.recovery_authoring import SUBTRACT_ONLY_RULE, render_loaded_streak_line

    day = str(getattr(ir, "target_date", "") or "")[:10] or None
    caps = standing_constraints.lifting_caps_active(constraint, day)
    bands = None if caps else effort_ceilings.class_bands()
    lines = standing_constraints.gate_lines(constraint, constraint.get("stop_list"), green_withheld, target_date=day, ceilings=bands)
    lines.append(f"Load: {SUBTRACT_ONLY_RULE}")
    streak_line = render_loaded_streak_line(ctx)
    if streak_line:
        lines.append(streak_line)
    if inputs_current_through:
        lines.append(f"inputs_current_through: {inputs_current_through}")
    first = ir.exercises[0]
    first.notes = ("\n".join(lines) + ("\n\n" + first.notes if first.notes else "")).strip()

    g = constraint["gate"]
    cue = standing_constraints.gate_cue(constraint, target_date=day, ceilings=bands)
    if caps:
        sinus_cap, not_sinus_cap = g["sinus_rpe_cap"], g["not_sinus_rpe_cap"]
    else:  # #5167: the charter's compound ceiling on every branch — no cap below it
        comp = effort_ceilings.ceiling(effort_ceilings.COMPOUNDS)
        sinus_cap = not_sinus_cap = int(comp) if comp is not None and float(comp).is_integer() else comp
    structured: dict[str, Any] = {"session": ctx, "gate": constraint["id"], "exercises": {}}
    if not caps:
        structured["lifting_caps"] = {"retired_from": constraint.get("lifting_caps_retired_from"), "ceiling_rpe": sinus_cap}
    for ex in [e for e in ir.exercises if getattr(e, "skill_tier", 1) >= 2][:2]:
        ex.notes = ((ex.notes + "\n") if ex.notes else "") + cue
        structured["exercises"][ex.movement_key] = {
            "gate_cue": cue,
            "green": {
                "rpe_cap": sinus_cap,
                "cue": "sinus rhythm + feel fine",
                **({"withheld": green_withheld} if green_withheld else {}),
            },
            "yellow": {"rpe_cap": sinus_cap, "cue": "sinus rhythm + feel fine"},
            "red": {"rpe_cap": not_sinus_cap, "cue": "ECG not sinus, or feel off"},
        }
    if "accessory" in g["optional_when_not_sinus"]:
        for ex in ir.exercises:
            if _is_accessory(ex):
                ex.notes = ((ex.notes + "\n") if ex.notes else "") + "Optional if the ECG is not sinus."
    return structured


def gate_draft(ideal: Any, target_date: str, adapt: Callable[[dict[str, Any] | None, str | None], dict]) -> dict[str, Any]:
    """`_action_draft`'s #5000 step on the ideal routine: read the constraint and the tripwire, run the
    adaptation (`adapt(constraint, green_withheld)`), append the cardio block, stamp the reads on the
    snapshot. Returns the payload keys plus `adaptation` (the structured branches). No ideal → no-op."""
    if ideal is None:
        return {"adaptation": {}, "standing_constraint": None, "green_block": None, "cardio_block": None}
    constraint = read_standing_constraint(target_date)
    protein = protein_tripwire(target_date)
    withheld = green_withheld_reason(protein)
    adaptation = adapt(constraint, withheld)
    layer = None
    try:
        from mcp import shared_quantities

        layer = shared_quantities.recent_aerobic_layer(target_date)
    except Exception as e:  # noqa: BLE001 — cardio_block names the failure itself on a None layer read below
        logger.warning("cardio block: recent-aerobic read failed: %s", e)
    from training.cardio_cues import with_served_kinds

    # #5076: an empty-note ride counts as the kind its routine prescribed, so a performed tempo is not re-placed
    cardio_index = with_served_kinds(_cardio_index_failsoft(), target_date)
    from training.cardio_cues import previous_of

    previous = previous_of(ideal, target_date)  # #5076: the session the Hevy sequence last credited, from the calendar
    cardio, pick = cardio_block(
        target_date, getattr(ideal, "archetype", "") or "", constraint, layer=layer, cardio_index=cardio_index, previous=previous
    )
    if cardio is not None:
        ideal.exercises.append(cardio)
        _refresh_session_shape(ideal)
        # #5048: the level comes from his ride history (fail-soft: a failed load keeps the note, no level)
        try:
            from training.routine_generator import attach_cardio_cues

            attach_cardio_cues(ideal, cardio_index=cardio_index, aerobic_block=layer)
        except Exception as e:  # noqa: BLE001 — the block keeps the note cardio_block wrote
            logger.warning("cardio block: level pass failed: %s", e)
    summary = {k: constraint.get(k) for k in ("id", "active_from", "memory_read")} if constraint else None
    green = {**protein, "withheld": bool(withheld)}
    ideal.inputs_snapshot = {**(ideal.inputs_snapshot or {}), "standing_constraint": summary, "green_block": green, "cardio_pick": pick}
    return {
        "adaptation": adaptation,
        "standing_constraint": summary,
        "green_block": green,
        "cardio_block": {
            "appended": cardio is not None,
            "pick": pick,
            # the gym cardio minutes the drafted routine adds to the day's steps/movement goal (#5076 -> #5056)
            "movement_minutes": (ideal.inputs_snapshot.get("cardio_plan") or {}).get("movement_minutes"),
        },
    }
