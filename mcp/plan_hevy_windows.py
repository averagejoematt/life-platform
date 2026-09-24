"""plan_hevy_windows.py — the three Hevy partition windows stage 1 of `plan_next_session` reads.

Extracted from `mcp/tools_plan.py` (#4110) when the session-sequence read pushed that module
over the 1000-line ceiling (`tests/test_module_size_guard.py`). The three readers are one
cohesive seam — each turns a target date into the Hevy rows ONE engine input is computed
from — and `tools_plan` re-exports them under the same names, so `plan_next_session`'s call
sites and every `patch("mcp.tools_plan._rotation_window", ...)` keep working unchanged.

  * `_rotation_window`     — the accessory-rotation window (#3755)
  * `_prescription_window` — the self_added_volume window (#4081)
  * `_block_workouts`      — the v0.3 session sequence's record since the block start (#4110);
                             also read by `mcp.hevy_prescription_gate` for the ramp's week

A raise propagates to the caller (`tools_plan._read` records it as `read_failed`, #4072).
"""

from __future__ import annotations

from typing import Any

from mcp.plan_helpers import _minus_days


def _rotation_window(end_date: str) -> tuple[str | None, list[dict[str, Any]] | None]:
    """(window start, Hevy rows) for the program's trailing accessory-rotation window (#3755).

    Read DIRECTLY from the hevy partition, the same way `_walking_volume_last_7d` does and
    for the same reason: `get_workouts`'s `_slim_workout` projection drops `exercises`,
    which is the only place the movement NAMES live — and the names ARE the measurement
    here. A read that RAISES yields None, so the engine reports rotation `unknown` rather
    than reading an empty window as a clean rotation.
    """
    from common.pacific_time import shift_day_key
    from training import program_structure

    from mcp.core import query_source_range

    window_days = int(program_structure.ROTATION_RULE["window_days"])
    start = shift_day_key(end_date, -(window_days - 1))
    if start == end_date:  # unparseable day key — shift_day_key returns it unchanged
        return None, None
    # #4072: a raise propagates to `_read` at the call site, which records its error class.
    return start, query_source_range("hevy", start, end_date)


def _prescription_window(end_date: str) -> list[dict[str, Any]] | None:
    """Hevy rows for self_added_volume (#4081): Monday three whole weeks back through `end_date`.
    Direct partition read (as `_rotation_window`): rows carry the stored `adherence` block that
    `get_workouts`'s slim projection drops. None only for a bad date; a raise reaches `_read`."""
    from training import self_added_volume

    from mcp.core import query_source_range

    start = self_added_volume.window_start(end_date)
    if start is None:
        return None
    return query_source_range("hevy", start, end_date)


def _block_workouts(target_date: str) -> list[dict[str, Any]]:
    """Every Hevy row from the v0.3 block start to the day before `target_date` (#4110) — the
    record the session sequence advances on. Read through `tools_strength._read_hevy_all_phases`,
    the ONE sanctioned Hevy read path (#4030/#4032). Before the block start there is nothing to
    read and the answer is an empty list; a raise propagates to `_read` as `read_failed`."""
    from training import session_sequence

    from mcp.tools_strength import _read_hevy_all_phases

    start = session_sequence.block_start()
    end = _minus_days(target_date, 1)
    if end < start:
        return []
    items, _phases = _read_hevy_all_phases(start, end)
    return items
