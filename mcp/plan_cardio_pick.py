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

from typing import Any


def draft_cardio_warnings(blocks: list[Any], archetype: str, target_date: str) -> list[str]:
    """One warning per timed weight-bearing block the pick would not have drafted."""
    from training import recent_aerobic

    timed_wb = [
        b
        for b in blocks
        if any(getattr(s, "duration_seconds", None) for s in getattr(b, "sets", None) or [])
        and recent_aerobic._hevy_modality(str(getattr(b, "movement_key", "")).replace("_", " ")) in recent_aerobic.WEIGHT_BEARING
    ]
    if not timed_wb:
        return []
    try:
        from mcp import shared_quantities

        pick = recent_aerobic.cardio_pick(shared_quantities.recent_aerobic_layer(target_date), archetype)
    except Exception as e:  # noqa: BLE001 — named, never a lost draft
        return [f"cardio: the recent-aerobic pick could not be computed ({type(e).__name__}) — the modality is unchecked (#4387)"]
    if pick["movement_key"] == "treadmill":
        return []
    return [
        f"cardio: {b.movement_key} drafted, but the pick from the last 3 days is {pick['modality']} (HR avg ≤ {pick['hr_ceiling_bpm']} bpm, target {pick['hr_target_bpm']}) — "
        f"{pick['reason']}. Stage 2's joints_tendons critic swaps it when the legs are loaded (#4387)."
        for b in timed_wb
    ]
