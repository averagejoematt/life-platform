"""evaluation_hold.py — a targeted, logged hold on grading one PREDICTION# row (#5607, owner ruling 2026-11-03, item 2).

THE RULING. "Prevent further suspect grading first. Authorize a targeted, logged evaluation hold on the
identified pending calls while their rulings are reviewed ... Leave unaffected evaluation running."

THE SHAPE. A held row carries one map attribute, ``evaluation_hold``::

    {"reason": str, "set_at": ISO-8601, "set_by": "owner", "ruling_ref": "#5607", "issue": optional}

It is written and removed ONLY by ``scripts/evaluation_hold.py`` (an audit row
``EVALHOLD#{prediction_id}#{ISO}`` first, then a conditional update that touches nothing but this
attribute, and only on a ``pending`` / ``confirming`` row). Status, outcome and notes are never touched.

WHAT A HOLD DOES. Every automatic grading path skips a held row — no grade, no confidence move, no
learning row, and NO EXPIRY while held:

  * ``coach_prediction_evaluator._evaluate_all`` — skipped before any window, grading or expiry logic,
    logged and counted in ``stats["held"]``;
  * ``coach_prediction_evaluator._retire_ungradeable`` — a held qualitative row is not retired;
  * ``grade_corrections.write_first_grade`` — the one first-grade write REFUSES a held row
    (``HeldGradeError``) and is conditional on ``attribute_not_exists(evaluation_hold)``, so a hold set
    between the grader's read and its write still wins.

The deliberate, ledgered correction path (``grade_corrections.apply_correction``) is NOT blocked: an
owner ruling on a held call is exactly what the hold waits for.

AFTER RELEASE. Normal rules resume on the next daily run. The time the row spent held is NOT paused or
credited: its window and its 2x expiry are still counted from ``created_date``, so a row released past
its 2x window can expire on the next run — unless the owner rules otherwise for that row.
"""

from __future__ import annotations

ATTR = "evaluation_hold"
AUDIT_SK_PREFIX = "EVALHOLD#"
#: The statuses a hold may be SET on — the evaluator's open set (EVALUABLE_STATUSES).
HOLDABLE_STATUSES = ("pending", "confirming")
DEFAULT_READER_REASON = "Grading is held for review: the owner is ruling on whether this call can be graded as written."


class HeldGradeError(RuntimeError):
    """A grade write onto a row whose grading is held (#5607)."""


def hold_of(row: dict) -> dict | None:
    """The row's hold map, or None. Any truthy value counts as held — a malformed hold fails CLOSED."""
    if not isinstance(row, dict):
        return None
    h = row.get(ATTR)
    if not h:
        return None
    return h if isinstance(h, dict) else {"reason": str(h)}


def is_grading_held(row: dict) -> bool:
    return hold_of(row) is not None


def hold_reason(row: dict) -> str:
    """The stored reason, or a plain default."""
    h = hold_of(row) or {}
    return str(h.get("reason") or "").strip() or DEFAULT_READER_REASON


def skip_held(row: dict, logger, stats: dict | None = None) -> bool:
    """True when the row is held — after ONE log line naming the call and the reason (and ``stats["held"] += 1``
    when a stats dict is given). The evaluator calls this before any window, grading or expiry logic."""
    if not is_grading_held(row):
        return False
    pid = row.get("prediction_id") or str(row.get("sk", "")).replace("PREDICTION#", "", 1)
    logger.info("[#5607] evaluation HELD — not graded, not expired: %s / %s — %s", row.get("pk", "?"), pid, hold_reason(row))
    if stats is not None:
        stats["held"] = stats.get("held", 0) + 1
    return True
