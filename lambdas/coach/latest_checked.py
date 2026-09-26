"""latest_checked.py — the ledger line: one coach's most recent CHECKED call (E1, epic #4182).

WHAT IT SERVES
--------------
"On <date> I said <claim> — it came in at <value>." The v7 coaches page opens each
coach's read with the last prediction the platform actually graded, so a reader meets
a coach with a memory rather than a state in time. This module builds that one block
per coach, read-only, from the coach's own ``COACH#<id>`` / ``PREDICTION#`` partition:

    {prediction_id, claim, created_date, pre_registered_at, outcome_date,
     metric, eval_type, condition, threshold, actual_value, status}

THE PAIR IT READS (charter rule 3 — enrolled in tests/pair_contract_registry.py)
--------------------------------------------------------------------------------
Producer: ``coach.prediction_emission.build_prediction_record`` writes the row
(``claim_natural``, ``created_date``, ``evaluation{metric,condition,threshold}``),
and ``coach.coach_prediction_evaluator._update_prediction_status`` grades it in place
(``status``, ``outcome_date``, ``outcome_notes`` — a JSON string built by
``coach.prediction_grading.build_outcome_notes`` carrying ``actual_value``). The graded
PREDICTION# row alone carries everything the line needs, so no LEARNING# join is made:
the LEARNING# row is a second write of the same grade keyed by ``prediction_id``, and
reading one source of the grade is the whole point of a single producer.

THE RULES
---------
  * **Graded only.** ``confirmed`` or ``refuted`` with an ``outcome_date``. Pending,
    observational, inconclusive and expired calls are never a ledger line — an
    undecided call is not a checked one.
  * **Absence is null, never a placeholder** (ADR-104). No graded call → ``None``;
    a failed read → ``None`` (logged). The site owns the absence sentence.
  * **The claim is born guarded** (#2972 / #4213). ``claim_natural`` is the coach's own
    register; it reaches the public block only through ``audience_guard.public_blurb``,
    which rejects second-person / vocative address. A rejected claim is served as
    ``None`` beside the numbers — the engine's record still stands, the words do not
    cross. Nothing is rewritten.
  * **Dates are ISO strings**; the site formats them. ``pre_registered_at`` is the
    freeze instant for a sealed pre-registration (#3480: its ``created_date`` is the
    genesis it grades from, not the moment it was made), ``None`` for in-cycle calls.
  * **Current cycle only** — the ADR-058 phase filter on the query plus the
    ``singleton_visible`` item mirror, so a reset's tombstones never serve.
  * "6 of 7 days" is not stored — the evaluator resolves one value — so only the value
    form ships.

Pure over an injected table handle: no clock, no write, no new access pattern (one
Query on the coach's existing partition, paginated to a hard page cap).
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any

from boto3.dynamodb.conditions import Key
from experiment.phase_filter import singleton_visible, with_phase_filter

from coach import audience_guard

logger = logging.getLogger(__name__)

#: The terminal verdicts a ledger line may carry. Anything else is not "checked".
GRADED_STATUSES = ("confirmed", "refuted")

#: The public claim cut (guard first, truncate second — `public_blurb`'s own order).
#: Wide enough for a whole claim sentence; the site may shorten further.
CLAIM_CHAR_LIMIT = 480

#: Hard ceiling on pages walked. A coach's PREDICTION# partition is a few hundred
#: rows (one page); this only bounds a pathological partition.
_MAX_PAGES = 5

_PROJECTION_NAMES = {
    "#pid": "prediction_id",
    "#claim": "claim_natural",
    "#cd": "created_date",
    "#pra": "pre_registered_at",
    "#od": "outcome_date",
    "#ev": "evaluation",
    "#st": "status",
    "#on": "outcome_notes",
    "#tomb": "tombstone",
    "#sk": "sk",
}


def _plain(value: Any) -> Any:
    """Decimal → int/float (boto3 hands numbers back as Decimal); others unchanged."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def _actual_value(outcome_notes: Any) -> Any:
    """The graded value from the evaluator's ``outcome_notes`` JSON, or None."""
    if isinstance(outcome_notes, dict):
        notes = outcome_notes
    else:
        try:
            notes = json.loads(outcome_notes or "{}")
        except (TypeError, ValueError):
            return None
    if not isinstance(notes, dict):
        return None
    value = _plain(notes.get("actual_value"))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(value, 4) if isinstance(value, float) else value


def _is_graded(row: dict) -> bool:
    return (row.get("status") or "").lower() in GRADED_STATUSES and bool(row.get("outcome_date")) and singleton_visible(row)


def select_latest(rows: list) -> dict | None:
    """The most recently graded row: latest ``outcome_date``, then ``created_date``,
    then ``prediction_id`` (a deterministic tie-break). None when nothing is graded."""
    graded = [r for r in rows or [] if isinstance(r, dict) and _is_graded(r)]
    if not graded:
        return None
    return max(
        graded,
        key=lambda r: (str(r.get("outcome_date") or ""), str(r.get("created_date") or ""), str(r.get("prediction_id") or "")),
    )


def to_block(row: dict | None) -> dict | None:
    """Project one graded PREDICTION# row onto the public ``latest_checked`` block."""
    if not row:
        return None
    raw_eval = row.get("evaluation")
    evaluation: dict = raw_eval if isinstance(raw_eval, dict) else {}
    claim = audience_guard.public_blurb({"public_summary": row.get("claim_natural")}, limit=CLAIM_CHAR_LIMIT) or None
    prediction_id = row.get("prediction_id") or str(row.get("sk") or "").replace("PREDICTION#", "", 1) or None
    return {
        "prediction_id": prediction_id,
        "claim": claim,
        "created_date": row.get("created_date"),
        "pre_registered_at": row.get("pre_registered_at"),
        "outcome_date": row.get("outcome_date"),
        "metric": evaluation.get("metric"),
        # "directional" → condition is up/down, threshold None and actual_value is the
        # EWMA slope, not a level; the site must know which it is quoting.
        "eval_type": evaluation.get("type"),
        "condition": evaluation.get("condition"),
        "threshold": _plain(evaluation.get("threshold")),
        "actual_value": _actual_value(row.get("outcome_notes")),
        "status": (row.get("status") or "").lower(),
    }


def _query_rows(table: Any, coach_id: str) -> list:
    kwargs: dict = with_phase_filter(
        {
            "KeyConditionExpression": Key("pk").eq(f"COACH#{coach_id}") & Key("sk").begins_with("PREDICTION#"),
            "FilterExpression": "#st IN (:graded_confirmed, :graded_refuted)",
            "ExpressionAttributeNames": dict(_PROJECTION_NAMES),
            "ExpressionAttributeValues": {":graded_confirmed": "confirmed", ":graded_refuted": "refuted"},
            "ProjectionExpression": ", ".join(_PROJECTION_NAMES) + ", #phase",
            "ScanIndexForward": False,
        }
    )
    rows: list = []
    for _ in range(_MAX_PAGES):
        resp = table.query(**kwargs)
        rows.extend(resp.get("Items") or [])
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs = dict(kwargs, ExclusiveStartKey=last)
    return rows


def for_coach(table: Any, coach_id: str) -> dict | None:
    """The ``latest_checked`` block for one coach, or None (no graded call / read failed)."""
    if not coach_id or table is None:
        return None
    try:
        return to_block(select_latest(_query_rows(table, coach_id)))
    except Exception as exc:  # noqa: BLE001 — absence is the honest degradation, logged
        logger.warning("[latest_checked] %s: %s", coach_id, exc)
        return None
