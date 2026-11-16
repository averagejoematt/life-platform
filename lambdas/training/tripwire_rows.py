"""tripwire_rows.py — the two #5802 pieces plan_engine's tripwire rows read, kept out of plan_engine (the #1665 size ratchet).

  volume_ceiling_read  the `volume_ceiling` row over the 28-day per-muscle weekly sets stage 1 already reads (report-only)
  stall_input          `weight_stall_with_adherence` as `health.nutrition_critics` evaluated it, with the input status the
                       engine reports — ONE evaluation, two readers; the engine computes no stall of its own

Pure. `stall_input` imports plan_engine and `health.tripwire_readers` at call time (plan_engine imports this module).
"""

from __future__ import annotations

from typing import Any

from training import owner_redlines


def volume_ceiling_read(muscle_volume: dict[str, Any]) -> tuple[str, Any, str]:
    """(state, observed, detail) for `volume_ceiling` over `{muscle: weekly working sets}` (the trailing-28-day average).
    The per-muscle arm only: the per-session lines are the generator's own ceiling (`training.green_block`), enforced
    when a session is drafted, so stage 1 has no session of its own to read."""
    t = next(t for t in owner_redlines.TRIPWIRES if t["id"] == "volume_ceiling")
    ceiling = float(t["threshold"]["sets_per_muscle_wk"])
    weekly = {m: float(v) for m, v in muscle_volume.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    over = {m: round(v, 1) for m, v in sorted(weekly.items()) if v > ceiling}
    detail = f"{len(over)} of {len(weekly)} muscle(s) above {ceiling:g} sets/wk (28-day average); per-session lines: the generator's"
    return ("tripped" if over else "clear"), over, detail


def stall_input(nutrition_block: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """(the stall evaluation, its input status) from the nutrition critics block — the MCP caller's one line."""
    from health.tripwire_readers import stall_from_block

    from training import plan_engine as pe

    ev = stall_from_block(nutrition_block)
    if ev["state"] == pe.READ_FAILED:
        return ev, pe.input_status(pe.READ_FAILED, error=f"NutritionCriticsError: {ev.get('error')}"[:200])
    return ev, pe.input_status(pe.MEASURED if ev["state"] in ("tripped", "clear") else pe.ABSENT, ev["detail"])
