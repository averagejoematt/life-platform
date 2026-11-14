"""compute/sealed_hypotheses.py — the sealed genesis hypotheses are visible to their grader and graded on their own window (#5518).

WHY THIS EXISTS

The cycle-17 pre-registration was frozen at 2026-09-06T02:13Z — 19:13 Pacific on 09-05, the evening BEFORE genesis.
The seeder writes its two hypotheses (``genesis_prereg_h1``, ``genesis_prereg_h2``) through the engine's own
``store_hypothesis``, and that writer stamps the WALL-CLOCK phase, so both rows were stamped ``phase=pilot``. The
engine's loader applied the ADR-058 phase filter, so for 68 days neither row was loaded, checked, graded or voided
(``check_count=0``): a sealed bet the grader could not see. (The seeder's ``write_predictions`` was fixed for the same
seam by #3874's ``genesis_cycle_stamp``; ``write_hypotheses`` never was.)

THE RULES

1. **Visible regardless of the stamp.** A row is graded when the phase filter passes it OR it is a sealed genesis
   hypothesis of THIS cycle: id prefix ``genesis_prereg_``, not tombstoned (every earlier cycle's copy carries the
   reset's tombstone — 26 of them on the live table at filing), and written no earlier than the day before the current
   genesis (the freeze runs the evening before). The predicate is ``grader_visible``.

2. **Graded on the window it sealed, not on today's trailing 30 days.** The engine's weekly check reads the last 30
   days; for a row whose window closed weeks ago that is data the hypothesis never named. A sealed row whose window has
   closed is graded ONCE, deterministically, on condition days ``[since, since + window - 1]`` (outcome read at the
   spec's lag), with the engine's own ``evaluate_test_spec``. The verdict maps exactly as the weekly check's
   window-done branch does: contradicted -> refuted; supported -> confirmed; inconclusive -> archived with
   ``expired_undecided`` and the arm counts as the stated reason (a void with a reason, never a silent archive).
   No LLM narrates it: the deterministic sentence is the record.

3. **A day with nothing logged is not a logged day** (ADR-105; the #5533 (c) rule, ``grading_quality``). A
   MacroFactor row with ``entries_count = 0`` carries a pre-filled ~80 kcal default; read as intake it would land in
   an "at or under target" arm. Such rows are removed before the window's daily rows are built, so they read as
   missing (the window's n says so).

4. **A window that spans the heart-rate regime marker is not graded on one scale** (the #5533 (e) rule). If the
   outcome is heart-rate derived and ``grading_quality.regime_split`` names a marker inside the window, the row is
   voided ``expired_undecided`` with the marker in the reason, never graded across two regimes.

Pure over injected I/O: ``grade_closed_window`` takes the engine's own fetch / narrative / test / sentence callables;
``load_visible`` takes the table. No clock is read here: every function takes the day it reasons about.
"""

from __future__ import annotations

from typing import Any, Callable

from common.constants import EXPERIMENT_PHASE_CURRENT, EXPERIMENT_START_DATE
from common.pacific_time import parse_day_key, shift_day_key
from experiment.phase_filter import with_phase_filter

SEALED_ID_PREFIX = "genesis_prereg_"
#: Marks every evidence line this module writes, so the record says how the row was graded.
LATE_GRADE_TAG = "[#5518 sealed-window grade]"
#: Spec outcome metrics derived from heart rate (the engine's vocabulary names: whoop recovery, HRV, resting HR).
HR_OUTCOME_METRICS = frozenset({"recovery", "hrv", "rhr"})
#: The behavioral source whose zero-entry rows are missing days, not intake (rule 3).
FOOD_SOURCE = "macrofactor"


def _day(value: Any) -> str:
    return str(value or "")[:10]


def _shift(day: str, days: int) -> str:
    return shift_day_key(day, days)


def phase_visible(item: dict) -> bool:
    """The ADR-058 query filter, item-level: no phase, or the current one."""
    phase = item.get("phase")
    return phase is None or phase == EXPERIMENT_PHASE_CURRENT


def is_sealed(item: dict, genesis: str = EXPERIMENT_START_DATE) -> bool:
    """A sealed genesis hypothesis of the cycle that starts on ``genesis`` (rule 1)."""
    if not str(item.get("hypothesis_id") or "").startswith(SEALED_ID_PREFIX) or item.get("tombstone"):
        return False
    written = _day(item.get("created_at") or item.get("pre_registered_at"))
    return parse_day_key(written) is not None and written >= _shift(genesis, -1)


def grader_visible(item: dict, genesis: str = EXPERIMENT_START_DATE) -> bool:
    """True when the engine must load this row: the phase filter passes it, or it is sealed (rule 1)."""
    return phase_visible(item) or is_sealed(item, genesis)


def load_visible(table, pk: str, decode: Callable[[list], list], genesis: str = EXPERIMENT_START_DATE) -> list:
    """Every HYPOTHESIS# row the engine grades, newest first, paginated.

    ``include_pilot=True`` on purpose (#5518): the phase filter is applied item-level by ``grader_visible`` instead,
    so a sealed row stamped ``pilot`` by the wall clock is not dropped server-side before this predicate can see it."""
    from boto3.dynamodb.conditions import Key

    kwargs = {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with("HYPOTHESIS#"), "ScanIndexForward": False}
    items: list = []
    while True:
        resp = table.query(**with_phase_filter(kwargs, include_pilot=True))
        items.extend(decode(resp.get("Items", [])))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return [h for h in items if grader_visible(h, genesis)]


def window_bounds(hyp: dict) -> tuple[str, str, int] | None:
    """``(since, last_condition_day, lag_days)`` for a hypothesis's sealed window, or None when undated."""
    since = _day(hyp.get("created_at"))
    if parse_day_key(since) is None:
        return None
    try:
        window = int(float(hyp.get("monitoring_window_days") or 0))
        lag = int(float((hyp.get("test_spec") or {}).get("lag_days") or 0))
        return since, _shift(since, max(window, 1) - 1), lag
    except (TypeError, ValueError):
        return None


def window_closed(hyp: dict, today: str) -> bool:
    """True once every outcome day of the sealed window is in the past (the window's last outcome day < today)."""
    bounds = window_bounds(hyp)
    if not bounds:
        return False
    _since, last, lag = bounds
    return _shift(last, lag) < _day(today)


def due_for_window_grade(hyp: dict, today: str, genesis: str = EXPERIMENT_START_DATE) -> bool:
    """A sealed row, still open, whose window has closed: graded once by ``grade_closed_window``."""
    return is_sealed(hyp, genesis) and hyp.get("status") in ("pending", "confirming") and window_closed(hyp, today)


def without_unlogged_days(data: dict) -> tuple[dict, list[str]]:
    """``data`` with every zero-entry food row removed (rule 3), and the days removed."""
    from coach.grading_quality import is_zero_entry_day

    food = data.get(FOOD_SOURCE) or []
    dropped = sorted({_day(r.get("date") or str(r.get("sk", "")).replace("DATE#", "")) for r in food if is_zero_entry_day(r)})
    if not dropped:
        return data, []
    return {**data, FOOD_SOURCE: [r for r in food if not is_zero_entry_day(r)]}, dropped


def regime_marker(hyp: dict) -> str | None:
    """The HR regime marker inside a heart-rate outcome's window (rule 4), else None."""
    spec = hyp.get("test_spec") or {}
    if spec.get("outcome_metric") not in HR_OUTCOME_METRICS:
        return None
    bounds = window_bounds(hyp)
    if not bounds:
        return None
    from coach.grading_quality import regime_split

    since, last, lag = bounds
    split = regime_split(since, _shift(last, lag))
    return split["marker_date"] if split else None


def grade_closed_window(
    hyp: dict,
    gather: Callable[..., dict | None],
    narrate_rows: Callable[[dict], list],
    evaluate: Callable[[dict, list, str], dict],
    describe: Callable[[dict, dict], str],
) -> tuple[dict, str, str, dict, str]:
    """Grade one sealed row on its own window, through the engine's own ``gather_data`` (called with an explicit
    ``start_date``/``end_date``), ``build_data_narrative``, ``evaluate_test_spec`` and ``deterministic_evidence``.
    Returns the engine's update tuple ``(hyp, new_status, evidence, stats, resolution)``; pure apart from
    ``gather`` (a read)."""
    spec = hyp.get("test_spec") or {}
    since, last, lag = window_bounds(hyp)
    window_txt = f"window {since}..{last} (lag {lag}d)"
    marker = regime_marker(hyp)
    if marker:
        stats = {"verdict": "inconclusive", "days_observed": 0, "n_condition": 0, "n_comparison": 0}
        reason = f"not graded: the {window_txt} spans the heart-rate regime marker {marker}, so its outcome is on two scales"
        return hyp, "archived", f"{LATE_GRADE_TAG} {reason}.", stats, "expired_undecided"
    data, unlogged = without_unlogged_days(gather(start_date=since, end_date=_shift(last, lag)) or {})
    rows = [r for r in narrate_rows(data) if since <= r.get("date", "") <= _shift(last, lag)]
    stats = evaluate(spec, rows, since)
    verdict = stats.get("verdict")
    if verdict == "contradicted":
        new_status, resolution = "refuted", "refuted"
    elif verdict == "supported":
        new_status, resolution = "confirmed", "confirmed"
    else:
        new_status, resolution = "archived", "expired_undecided"
    gap = f"; {len(unlogged)} day(s) with nothing logged read as missing ({', '.join(unlogged)})" if unlogged else ""
    void = " Voided: archived expired-undecided — its own window's evidence cannot decide it." if resolution == "expired_undecided" else ""
    evidence = f"{LATE_GRADE_TAG} graded on its sealed {window_txt}{gap}. {describe(spec, stats)}{void}"
    return hyp, new_status, evidence, stats, resolution
