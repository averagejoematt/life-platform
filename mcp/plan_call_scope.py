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

#5813 — THE STAGE-1 READ SET. A second read-only profile (draft_custom f4569682, 2026-11-11: ~440 AWS
calls, 14-21 s on a laptop) found the duplicates that were left, now memoized here per call:

  * `training_notes_health` (the note layer's ~28-query health sweep) ran once in stage 1 and once
    more per DRAFTED exercise inside `tool_get_exercise_notes` — 252 of the call's queries;
  * `core.query_source` read the same (source, window) for several readers — the deficit tool, the
    reference, the walking layer, the readiness streak each re-read Strava / Hevy / Whoop / Habitify;
  * the template alias registry (`tools_strength.template_alias_map`, three S3 reads) once per drafted
    exercise's history read.

Each of these hands every caller its OWN copy (`memoized_copy`). Nothing is cached across calls.

THE READER CLOCK. `reading(name)` times one stage-1 reader (`tools_plan._read` wraps every labelled
read in it; the few readers that are not a `_read` carry `timed`). Only the OUTERMOST reader is
timed, so the parts never sum past the whole, and nothing is recorded once stage 2 starts
(`stage_1_done`). `plan_call` puts the result on the call's output as `timing_ms`: every name in
`STAGE_1_READERS` (0 when it did not run), `other` (stage-1 time no named reader accounts for) and
`total`, under `stage_1`, beside the call's `total`.
"""

from __future__ import annotations

import copy
import functools
import time
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal
from typing import Any, Callable, Iterator

ANCHOR_INDEXES = "anchor_indexes"
HEVY_ALL_PHASES = "hevy_all_phases"
# #5781: the block's Hevy record (`plan_hevy_windows._block_workouts`) — read by stage 1 and twice more by the commit
# gate's floors (`v03_load_rule`, `_in_block_performed`) on a draft_custom stage 2. Its consumers are not all checked
# read-only, so every caller gets its OWN copy (`memoized_copy`): the read is shared, the rows never are.
BLOCK_WORKOUTS = "block_workouts"
# #5813: the per-call memos for the stage-1 duplicates (module docstring). Every caller gets its own copy.
NOTES_HEALTH = "notes_health"
SOURCE_RANGE = "source_range"
ALIAS_MAP = "alias_map"
_CALL_KINDS = (ANCHOR_INDEXES, BLOCK_WORKOUTS, NOTES_HEALTH, SOURCE_RANGE, ALIAS_MAP)

# #5813: the stage-1 readers `timing_ms.stage_1` always names — the `_read` labels stage 1 uses (directly, and through
# `_owner_word_records`, `plan_event_reads`, `_read_guidance_cap`, `_attach_session_loads`) and the `timed` readers.
# A reader not listed still lands under its own name; tests/test_stage1_reads_5813.py holds this list to the `_read` set.
STAGE_1_READERS = (
    "reference",
    "recovery_tier",
    "acwr_flag",
    "muscle_volume",
    "protein_days_missed_7d",
    "dxa_scans",
    "loss_rate",
    "readiness_low_streak_days",
    "notes_layer_health",
    "pain_dismissals",
    "deload_records",
    "disruption_records",
    "sick_days",
    "deficit",
    "steps_window",
    "training_memory_constraints",
    "draft_evidence",
    "pain_evidence_scope",
    "walk_hr_wk_now",
    "recent_aerobic",
    "hevy_workouts_rotation_window",
    "hevy_workouts_prescription_window",
    "catalog",
    "block_workouts",
    "guidance_cap",
    "session_loads",
    "morning_note",
    "coach_context",
    "calibration_due",
    "withings_full_scans",
)

# Must sit below the handler's cap with room for what follows the write (one put_versioned, the
# coach-thread put, the notes block, the response): tests/test_plan_stage2_latency_5313.py holds it there.
STAGE_2_WRITE_DEADLINE_SECS = 26.0
# The model wait ends this long before the write deadline, leaving room for apply/recheck/precheck.
MODEL_RESERVE_SECS = 2.0

_ACTIVE: ContextVar[dict[str, dict[Any, Any]] | None] = ContextVar("plan_call_memo", default=None)
_STARTED: ContextVar[float | None] = ContextVar("plan_call_started", default=None)
_READERS: ContextVar[dict[str, Any] | None] = ContextVar("plan_call_readers", default=None)


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


_ATOMS = (str, int, float, bool, type(None), Decimal)


def _copy(value: Any) -> Any:
    """A deep copy of a read result. Rows are JSON-shaped (dict / list / tuple of scalars), so they are copied by a plain
    walk, several times faster than `copy.deepcopy` on the ~2,000-row reads this memo holds (#5813); anything else falls
    back to `copy.deepcopy`. Values never alias each other inside a read, so the walk loses nothing deepcopy keeps."""
    if isinstance(value, _ATOMS):
        return value
    if type(value) is dict:
        return {k: _copy(v) for k, v in value.items()}
    if type(value) is list:
        return [_copy(v) for v in value]
    if type(value) is tuple:
        return tuple(_copy(v) for v in value)
    return copy.deepcopy(value)


def memoized_copy(kind: str, key: Any, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """`memoized`, handing every caller a deep copy — for a value whose consumers may mutate it."""
    if (_ACTIVE.get() or {}).get(kind) is None:
        return fn(*args, **kwargs)
    return _copy(memoized(kind, key, fn, *args, **kwargs))


MISS = object()


def memo_get(kind: str, key: Any) -> Any:
    """A copy of the value memoized under (kind, key), else `MISS` — always `MISS` outside a scope for `kind`. For a
    reader whose read must stay inline (an AST guard names the function that holds it); pair with `memo_put`."""
    memo = (_ACTIVE.get() or {}).get(kind)
    if memo is None or key not in memo:
        return MISS
    return _copy(memo[key])


def memo_put(kind: str, key: Any, value: Any) -> Any:
    """Store a copy of `value` under (kind, key) while a scope for `kind` is open; return `value` itself."""
    memo = (_ACTIVE.get() or {}).get(kind)
    if memo is not None:
        memo[key] = _copy(value)
    return value


def anchor_indexes() -> tuple[dict[str, list], dict[str, float]]:
    """(Hevy history index, bodyweight index) at the floor lookback — the pair both the session
    loads and the commit gate's floor clamp read, memoized under `anchor_indexes`."""
    from training.exercise_history import DEFAULT_LOOKBACK_DAYS, FLOOR_LOOKBACK_DAYS, load_bodyweight_index, load_history_indexes

    lookback = max(DEFAULT_LOOKBACK_DAYS, FLOOR_LOOKBACK_DAYS)
    history = memoized(ANCHOR_INDEXES, ("history", lookback), lambda: load_history_indexes(lookback_days=lookback)[0])
    weights = memoized(ANCHOR_INDEXES, ("bodyweight",), load_bodyweight_index)
    return history, weights


def notes_health(table: Any) -> dict[str, Any]:
    """`training.training_notes.training_notes_health(table)`, once per plan call (#5813) — read through the module
    at call time, so a test's patch of it still applies; each caller gets its own copy."""
    from training import training_notes

    with reading("notes_layer_health"):
        return memoized_copy(NOTES_HEALTH, ("health", id(table)), training_notes.training_notes_health, table)


@contextmanager
def reading(name: str) -> Iterator[None]:
    """Time one stage-1 reader under `name` — only the outermost, only inside a plan call, only before stage 2."""
    rec = _READERS.get()
    if rec is None or rec["depth"] or rec["stage_1_end"] is not None:
        yield
        return
    rec["depth"] += 1
    t0 = time.monotonic()
    try:
        yield
    finally:
        rec["depth"] -= 1
        rec["ms"][name] = rec["ms"].get(name, 0.0) + (time.monotonic() - t0) * 1000


def timed(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """`reading(name)` around every call of the decorated reader."""

    def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with reading(name):
                return fn(*args, **kwargs)

        return wrapper

    return deco


def stage_1_done() -> None:
    """Mark the end of stage 1 (stage 2 starts here); later reads are stage 2's own (`critics.timing_ms`)."""
    rec = _READERS.get()
    if rec is not None and rec["stage_1_end"] is None:
        rec["stage_1_end"] = time.monotonic()


def _timing(rec: dict[str, Any]) -> dict[str, Any]:
    end = time.monotonic()
    stage_1_ms = ((rec["stage_1_end"] or end) - rec["t0"]) * 1000
    readers = {name: round(rec["ms"].get(name, 0.0)) for name in STAGE_1_READERS}
    readers.update({name: round(ms) for name, ms in rec["ms"].items() if name not in readers})
    named = sum(rec["ms"].values())
    stage_1 = {**readers, "other": max(0, round(stage_1_ms - named)), "total": round(stage_1_ms)}
    return {"stage_1": stage_1, "total": round((end - rec["t0"]) * 1000)}


def plan_call(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Run `fn` as one plan call: the clock stamped, the per-call memos open, the stage-1 readers timed (`timing_ms`)."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        t0 = time.monotonic()
        token = _STARTED.set(t0)
        rec: dict[str, Any] = {"t0": t0, "ms": {}, "depth": 0, "stage_1_end": None}
        rtoken = _READERS.set(rec)
        try:
            with scope(*_CALL_KINDS):
                out = fn(*args, **kwargs)
            if isinstance(out, dict) and "error" not in out:
                out["timing_ms"] = _timing(rec)
            return out
        finally:
            _READERS.reset(rtoken)
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
