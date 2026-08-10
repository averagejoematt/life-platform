"""prediction_grading.py — the grading-lifecycle predicates behind coach_prediction_evaluator.

Two small, heavily-reasoned rules the evaluator leans on, kept beside it rather than inside
it (#1665: coach_prediction_evaluator.py is a baselined god-module that may only shrink).

1. **The EWMA observation floor.** `_get_ewma_trend` compares the current EWMA against the
   EWMA as of ``EWMA_PRIOR_LAG`` observations ago. That prior must smooth at least
   ``EWMA_MIN_PRIOR_POINTS`` readings — comparing a smoothed level against a single raw
   reading is not a trend, and grading a coach's directional call off one would manufacture
   confidence (ADR-105). #2221: the evaluator used to *guard* on a documented floor of five
   observations while the branch below it needed ``len(values) - 7 >= 2``, so 5-8
   observations silently returned ``(None, None)`` and the stated contract was a lie. The
   floor is DERIVED here so guard, docstring and behaviour cannot disagree again.

2. **Provisional vs terminal grades.** A forecast graded ``inconclusive`` purely because the
   metric had no reading on the day its window closed used to be terminal: the write stamps
   ``algo_version``, so ``EVALUABLE_STATUSES`` and the #813 reclaim discriminator both
   refused it forever — even though a reading arriving one day later would have decided it,
   and even though ``_check_expiry``/``EXPIRY_MULTIPLIER`` plainly intend a 2x-window grace
   period. ``EXPIRY_MULTIPLIER`` was therefore unreachable for any prediction the daily run
   saw on schedule. Such a write now carries ``grading_open`` and is re-graded each day until
   it decides or expiry retires it — which clears the flag, so the second look is bounded.
"""

import json
from datetime import datetime
from typing import Any

# How far back the "prior" EWMA is taken, and the minimum readings it must smooth.
EWMA_PRIOR_LAG = 7
EWMA_MIN_PRIOR_POINTS = 2
EWMA_MIN_OBSERVATIONS = EWMA_PRIOR_LAG + EWMA_MIN_PRIOR_POINTS

# Expiry multiplier — a call undecided past this many windows is retired, not left open.
EXPIRY_MULTIPLIER = 2


def check_expiry(pred: dict[str, Any], effective_window: int, today: datetime) -> bool:
    """True once a prediction's grace period has closed.

    A call expires when more than EXPIRY_MULTIPLIER windows have elapsed since it was
    made and it is STILL undecided — 'inconclusive' for want of data, or 'pending' on a
    precondition that never arrived (#2221). Retirement is not a verdict: it moves no
    Bayesian confidence, it just stops the call being carried forever.
    """
    created_date = pred.get("created_date")
    if not created_date:
        return False
    try:
        created_dt = datetime.strptime(created_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        return False
    return (today - created_dt).days > effective_window * EXPIRY_MULTIPLIER


def grading_window_still_open(item: dict[str, Any]) -> bool:
    """True for an 'inconclusive' written while the 2x grace period was still open.

    Deterministic discriminator, mirroring the #813 one: this evaluator stamps
    ``grading_open`` only on a provisional grade, and never on a terminal outcome
    (confirmed / refuted / expired), so re-grading stays one-way once a call is decided.
    """
    if item.get("status") != "inconclusive":
        return False
    try:
        notes = json.loads(item.get("outcome_notes") or "{}")
    except (ValueError, TypeError):
        return False
    return isinstance(notes, dict) and notes.get("grading_open") is True


def build_outcome_notes(evaluation: dict[str, Any], algo_version: str) -> str:
    """The ``outcome_notes`` JSON blob written onto a graded PREDICTION# record.

    ``grading_open`` is present ONLY on a provisional grade — its absence is what makes a
    terminal outcome terminal, so it is written here beside the algo_version stamp that
    the #813 reclaim discriminator reads, rather than at the call site.
    """
    notes: dict[str, Any] = {
        "actual_value": evaluation.get("actual_value"),
        "reason": evaluation.get("reason", ""),
        "beats_null": evaluation.get("beats_null", False),
        "bayesian_update": evaluation.get("bayesian_update"),
        "algo_version": algo_version,
    }
    if evaluation.get("grading_open"):
        notes["grading_open"] = True
    return json.dumps(notes)
