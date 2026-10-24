"""plan_event_reads.py — the deload recommendation's event-signal reads for stage 1 of `plan_next_session` (#5146).

Extracted beside `mcp/tools_plan.py` (which re-exposes it as `_event_inputs`) so that module stays under the
1000-line ceiling (`tests/test_module_size_guard.py`), the same seam `mcp/plan_hevy_windows.py` is. The rule the reads
feed is pure and lives in `training.deload_word.event_signals`; this module only READS, each read with its state:

  * the sick-day store — `manage_sick_days`'s own list read (`mcp.tools_sick_days._get_sick_days`, cleared rows
    already dropped, #4378) over `deload_word.SICK_DAY_LOOKBACK_DAYS` through the target day
  * the deficit band — `get_deficit_sustainability` (ONE call; its raw return goes back to the caller so
    `nutrition_critics` reuses it instead of calling the tool twice). Its own refusal ("Need ≥7 days ...") is an
    ABSENCE, not a broken read.

The third event source, the charter travel windows, is a bundled read inside the engine.
"""

from __future__ import annotations

from typing import Any, Callable

from common.pacific_time import shift_day_key


def read(target_date: str, read_fn: Callable[..., tuple[Any, dict[str, Any]]]) -> tuple[dict[str, Any], Any]:
    """(`constraint_block(event_inputs=...)`, the deficit tool's raw return — None when it raised, as `_safe` gave).

    `read_fn` is `tools_plan._read`: `(value, input status)`, a raise or a tool error dict is `read_failed`."""
    from training import deload_word
    from training.plan_engine import ABSENT, READ_FAILED, input_status as st

    from mcp.tools_nutrition import tool_get_deficit_sustainability
    from mcp.tools_sick_days import _get_sick_days

    status: dict[str, dict[str, Any]] = {}
    window = {"start_date": shift_day_key(target_date, -deload_word.SICK_DAY_LOOKBACK_DAYS), "end_date": target_date}
    listed, status["sick_days"] = read_fn("sick_days", _get_sick_days, window)
    rows = listed.get("sick_days") if isinstance(listed, dict) else None
    if not rows and status["sick_days"]["state"] != READ_FAILED:
        status["sick_days"] = st(ABSENT, f"no sick day logged {window['start_date']}..{target_date}")
        rows = []
    raw: dict[str, Any] = {}

    def _deficit() -> Any:
        raw["res"] = tool_get_deficit_sustainability({"critics_model": False})  # #5114: no narrative on the plan surface
        return raw["res"]

    deficit, status["deficit"] = read_fn("deficit", _deficit)
    res = raw.get("res")
    refusal = str(res.get("error") or "") if isinstance(res, dict) else ""
    if deficit is None and refusal.startswith("Need "):
        status["deficit"] = st(ABSENT, f"the deficit tool declined: {refusal[:160]}")
    return {"sick_days": rows, "deficit": deficit, "status": status}, res
