"""plan_cardio_pick.py — a chat-drafted cardio block checked against `recent_aerobic`'s pick (#4387).

The 2026-09-28 treadmill was not generated: the evening coach drafted it with `draft_custom`,
copying the last session's 60-min incline treadmill onto a lower session the morning after a
4.4 h walking weekend. The modality is now PICKED from the last three days
(`training.recent_aerobic.cardio_pick`, served on stage 1 as `constraint_block.recent_aerobic.
cardio_pick`); this module makes `draft_custom` say so, by name, when the drafted block disagrees.

A warning, never a rewrite: an explicit choice in the draft stands until stage 2, where the
joints_tendons critic swaps it on the loaded-legs trigger (`coach.critics_aerobic`). Fail-soft —
a read that fails is itself named, and never costs the draft.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("tools_hevy_routine")


def draft_cardio_warnings(blocks: list[Any], archetype: str, target_date: str) -> list[str]:
    """One warning per timed weight-bearing block the pick would not have drafted — after one per break of the charter's
    session shape (#5069, owner ruling 5: lifting minutes, ONE cardio block, the cardio and stretching caps). The chat path
    flags; the generator enforces (`program_structure.enforce_session_shape`)."""
    from training import program_structure, recent_aerobic
    from training.routine_generator import _load_json

    catalog = (_load_json("movement_catalog.json") or {}).get("movements") or {}  # #5315: the real catalog, never {}
    shape = [
        f"session shape: {w} — allowed for a custom session, just flagging (#5069)"
        for w in program_structure.session_shape_problems(blocks, catalog)
    ]

    timed_wb = [
        b
        for b in blocks
        if any(getattr(s, "duration_seconds", None) for s in getattr(b, "sets", None) or [])
        and recent_aerobic._hevy_modality(str(getattr(b, "movement_key", "")).replace("_", " ")) in recent_aerobic.WEIGHT_BEARING
    ]
    if not timed_wb:
        return shape
    try:
        from mcp import shared_quantities

        pick = recent_aerobic.cardio_pick(shared_quantities.recent_aerobic_layer(target_date), archetype, target_date)
    except Exception as e:  # noqa: BLE001 — named, never a lost draft
        return shape + [f"cardio: the recent-aerobic pick could not be computed ({type(e).__name__}) — the modality is unchecked (#4387)"]
    if pick["movement_key"] == "treadmill":
        return shape
    # #5000: under a standing constraint the pick carries the talk test, never an HR number
    how = pick.get("intensity") or f"HR avg ≤ {pick['hr_ceiling_bpm']} bpm, target {pick['hr_target_bpm']}"
    return shape + [
        f"cardio: {b.movement_key} drafted, but the pick from the last 3 days is {pick['modality']} ({how}) — "
        f"{pick['reason']}. Stage 2's joints_tendons critic swaps it when the legs are loaded (#4387)."
        for b in timed_wb
    ]


def attach_custom_cardio_notes(ir: Any, target_date: str) -> int:
    """#3700/#5048: `attach_cardio_cues` on a `draft_custom` routine. Returns how many cardio notes were written.

    `generate_routines` calls `attach_cardio_cues` at the end of its build; `draft_custom` builds its blocks
    straight from the caller's arguments and never reaches it, so this is the one call that path needs.
    It runs AFTER `_new_routine_id` (the id is content-derived — a routine must not get a new id because
    his history moved) and BEFORE `draft_versioned`, so `dry_run`/`commit` push the bytes this reports.
    The note is the prescription-first composed note (`training.cardio_note`): it REPLACES an authored
    cardio note (kept on the snapshot) and recomposes identically on a re-draft, so it never stacks.
    Fail-soft twice over: `attach_cardio_cues` returns 0 with every note untouched on an index-load
    failure, and the guard here means no cue path can cost a draft. The count is REPORTED, never assumed:
    0 on a routine with no cardio block is the honest answer."""
    try:
        from training import cardio_note
        from training.routine_generator import attach_cardio_cues

        layer = None
        if any(cardio_note.machine_for(b.movement_key) for b in ir.exercises):
            # the week's walking load decides whether a harder shape is allowed, and writes the why line
            try:
                from mcp import shared_quantities

                layer = shared_quantities.recent_aerobic_layer(target_date)
            except Exception as e:  # noqa: BLE001 — unread: the ride stays flat
                logger.warning(f"draft_custom: recent-aerobic read failed ({e}); the cardio shape stays flat")
        return attach_cardio_cues(ir, aerobic_block=layer)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"draft_custom: cardio cue pass failed ({e}); notes untouched")
        return 0


def replaced_note_warnings(ir: Any) -> list[str]:
    """#5312: one warning per authored cardio note the composer replaced (`inputs_snapshot.cardio_notes_replaced`,
    written by `training.cardio_cues`), stating the kind it was read as and the kind written."""
    return [
        f"Replaced your authored {r.get('movement_key')} note ({str(r.get('notes') or '')[:80]!r}): "
        f"read as {r.get('old_kind') or 'no recognised kind'}, wrote {r.get('new_kind')}. "
        "The original is kept on the draft's inputs_snapshot.cardio_notes_replaced."
        for r in (getattr(ir, "inputs_snapshot", None) or {}).get("cardio_notes_replaced") or []
    ]
