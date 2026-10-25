"""plan_call_scope.py — one `plan_next_session` call: its reads made once, its clock, its write deadline (#5313).

WHY THIS EXISTS. Stage 2 (the red team) hit the MCP tool cap (`mcp.handler.TOOL_TIMEOUT_SECS`,
30 s) on 2026-10-20 and 2026-10-25, so its verdicts were never stored. A read-only profile of
the live stage-2 call (laptop, live DynamoDB, every non-read API call refused, no model) found
the same reads repeated INSIDE the one call:

  * the Hevy history + bodyweight indexes (`exercise_history.load_history_indexes`, a
    full-partition query) were read twice — once for the scheduled session's loads
    (`tools_plan._load_anchor_indexes`) and again for the critics' floor clamp
    (`hevy_prescription_gate._load_indexes`);
  * the 400-day Hevy read behind `get_exercise_history` was read once PER DRAFTED
    EXERCISE in `plan_draft_evidence._gather_draft_evidence`, over the identical window.

THE MEMO. Inside a `scope(kind, ...)` block, `memoized(kind, key, fn, ...)` runs `fn` once per
key and hands every later caller the same value. Outside a scope it is a plain call, so the
commit path, the cron and every other tool are unchanged. Scoped by KIND on purpose: a memo
shares one object between callers, which is only safe where every caller reads it without
mutating it, so each kind is opened only where that was checked — `anchor_indexes` (read-only
consumers: `load_ramp`, `derive_load_floors`) for the whole plan call; `hevy_all_phases` only
around the per-exercise history loop (its consumer, `tool_get_exercise_history`, builds new
rows — whereas `_block_workouts` annotates ITS rows in place, so that kind is not open there).
A raise is never cached: the next caller reads again and meets its own failure.

THE CLOCK. `plan_call` stamps the call's start. Stage 2 stores its verdicts only if it reaches
the write before `STAGE_2_WRITE_DEADLINE_SECS`; past it, it stores nothing and says so. That is
what makes the handler's timeout message true by construction: a stage 2 the cap cut off never
started its write, so "the verdicts were NOT written" is a fact, not a guess. The critics' model
calls get the time left before that deadline as their wait (`model_budget_secs`).

State lives in ContextVars, so it belongs to the thread running the tool (the handler's worker
thread) and is dropped when the call returns.
"""

from __future__ import annotations

import functools
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Iterator

ANCHOR_INDEXES = "anchor_indexes"
HEVY_ALL_PHASES = "hevy_all_phases"

# Must sit below the handler's cap with room for what follows the write (one put_versioned, the
# coach-thread put, the notes block, the response): tests/test_plan_stage2_latency_5313.py holds it there.
STAGE_2_WRITE_DEADLINE_SECS = 26.0
# The model wait ends this long before the write deadline, leaving room for apply/recheck/precheck.
MODEL_RESERVE_SECS = 2.0

_ACTIVE: ContextVar[dict[str, dict[Any, Any]] | None] = ContextVar("plan_call_memo", default=None)
_STARTED: ContextVar[float | None] = ContextVar("plan_call_started", default=None)


@contextmanager
def scope(*kinds: str) -> Iterator[None]:
    """Open a memo for each kind not already open; close only the ones this block opened."""
    current = _ACTIVE.get() or {}
    opened = [k for k in kinds if k not in current]
    if not opened:
        yield
        return
    token = _ACTIVE.set({**current, **{k: {} for k in opened}})
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def memoized(kind: str, key: Any, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """`fn(*args, **kwargs)`, once per (kind, key) while a scope for `kind` is open."""
    memo = (_ACTIVE.get() or {}).get(kind)
    if memo is None:
        return fn(*args, **kwargs)
    if key in memo:
        return memo[key]
    value = fn(*args, **kwargs)
    memo[key] = value
    return value


def anchor_indexes() -> tuple[dict[str, list], dict[str, float]]:
    """(Hevy history index, bodyweight index) at the floor lookback — the pair both the session
    loads and the commit gate's floor clamp read, memoized under `anchor_indexes`."""
    from training.exercise_history import DEFAULT_LOOKBACK_DAYS, FLOOR_LOOKBACK_DAYS, load_bodyweight_index, load_history_indexes

    lookback = max(DEFAULT_LOOKBACK_DAYS, FLOOR_LOOKBACK_DAYS)
    history = memoized(ANCHOR_INDEXES, ("history", lookback), lambda: load_history_indexes(lookback_days=lookback)[0])
    weights = memoized(ANCHOR_INDEXES, ("bodyweight",), load_bodyweight_index)
    return history, weights


def plan_call(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Run `fn` as one plan call: the clock stamped, the `anchor_indexes` memo open."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        token = _STARTED.set(time.monotonic())
        try:
            with scope(ANCHOR_INDEXES):
                return fn(*args, **kwargs)
        finally:
            _STARTED.reset(token)

    return wrapper


def elapsed_secs() -> float | None:
    """Seconds since the plan call started, or None outside one."""
    started = _STARTED.get()
    return None if started is None else time.monotonic() - started


def model_budget_secs() -> float | None:
    """How long the critics may wait on the model: up to the write deadline less the reserve. None = unbounded
    (outside a plan call); never below 1 s, so a late start still asks once."""
    e = elapsed_secs()
    return None if e is None else max(1.0, STAGE_2_WRITE_DEADLINE_SECS - MODEL_RESERVE_SECS - e)


def past_write_deadline() -> str | None:
    """The refusal sentence when stage 2 reaches its write after the deadline, else None."""
    e = elapsed_secs()
    if e is None or e <= STAGE_2_WRITE_DEADLINE_SECS:
        return None
    return (
        f"NOT WRITTEN — stage 2 reached its write {e:.1f}s into the call, past the {STAGE_2_WRITE_DEADLINE_SECS:.0f}s write "
        "deadline that keeps it inside the MCP cap, so the verdicts below were NOT stored and the routine is NOT red-teamed. "
        "Run stage 2 again (plan_next_session with routine_id)."
    )
