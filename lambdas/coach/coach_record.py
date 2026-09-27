"""coach_record.py — ONE producer of a coach's record: "K of N through <day>" (#4220, epic #4182).

THE DEFECT THIS CLOSES
----------------------
On 2026-09-26 one coach's record was served three ways on one day. ``/api/coaches``
counted ``LEARNING#`` rows and printed Webb "80% hit-rate · n=25"; ``/api/calibration``
and ``/api/predictions`` counted ``PREDICTION#`` rows and printed 0 of 5; ``/api/wrong``
counted ``LEARNING#`` rows again and printed 20 confirmed / 5 refuted. Twenty of Webb's
twenty-five learnings were ONE dispute docket re-recorded daily (#4216 — the resolver
re-grades a stranded pre-cycle ``OPEN#`` row every run). Nothing asserted the producers
agreed, so nothing noticed.

THE RULE
--------
The ``PREDICTION#`` partition is the ledger — the row the grader writes its verdict on
(``coach_prediction_evaluator._update_prediction_status``) and the row the Brier score is
computed from (``experiment.calibration_core``). A coach's record is counted from it and
from nothing else:

  * **A prediction resolves once.** Its record entry is the EARLIEST graded row that
    carries its ``prediction_id``; every later same-id row is a re-write (the
    ``_put_unique`` ``-2``…``-5`` suffix trail #4216 documents — measured live on Webb's
    partition 2026-09-27: five ``PREDICTION#docket-…`` rows, one ``prediction_id``) and
    never counts. ``resolved_once`` is the partition as if that were always so.
  * **It belongs to the cycle it resolved in.** A resolution counts in the current record
    only when its row is phase-visible (ADR-058 ``singleton_visible`` — the reset's
    tombstone/pilot stamp hides an archived cycle) AND its ``outcome_date`` is not before
    genesis. A docket that resolved before Day 1 is therefore in its own cycle's career
    record at most once and in this cycle's record never.
  * **Graded means confirmed or refuted.** Pending, observational, inconclusive and
    expired calls are not checked calls (the same vocabulary as ``latest_checked``).
  * **Absence is absence** (ADR-104). n = 0 → "no checked call yet"; a failed read → None,
    never a zero that reads as a clean slate. Below ``PERCENT_FLOOR`` decided calls the
    headline prints counts, never a percentage.

Every public surface that prints a coach's record — ``/api/coaches`` (``record`` +
``headline_stat``), ``/api/calibration.coaches[]`` (``record`` beside the Brier numbers,
whose season pairs are built from the SAME row-set), ``/api/predictions.by_coach``
(``record``, and its graded season counts walk the same row-set) and
``/api/wrong.predictions.by_coach`` — derives from ``record_from_rows`` /
``resolved_once`` / ``counts_this_cycle`` here. The cross-endpoint contract is pinned in
``tests/test_coaches_api.py`` and the producer/consumer pair is enrolled in
``tests/pair_contract_registry.py`` (charter rule 3).

Pure over an injected table handle: no clock, no write, one Query on the coach's own
partition (unfiltered — the tombstoned original of a re-written row is exactly what
decides which cycle the resolution belongs to).
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from boto3.dynamodb.conditions import Key
from experiment.phase_filter import singleton_visible

logger = logging.getLogger(__name__)

#: The terminal verdicts a record counts. Anything else is not a checked call.
GRADED_STATUSES = ("confirmed", "refuted")

#: Below this many decided calls the headline prints counts, never a percentage
#: (#4220 acceptance: "below n = 10 the page prints counts").
PERCENT_FLOOR = 10

#: Hard ceiling on pages walked; a coach's partition is a few hundred rows (one page).
_MAX_PAGES = 5

_PROJECTION_NAMES = {
    "#pid": "prediction_id",
    "#st": "status",
    "#oc": "outcome",
    "#od": "outcome_date",
    "#ph": "phase",
    "#tomb": "tombstone",
    "#sk": "sk",
}


def graded_status(row: dict) -> str | None:
    """'confirmed' / 'refuted' for a graded row, else None."""
    status = str(row.get("status") or row.get("outcome") or "").strip().lower()
    return status if status in GRADED_STATUSES else None


def prediction_key(row: dict) -> str:
    """The identity a re-write shares with its original: ``prediction_id``, or the sk with
    the ``PREDICTION#`` prefix removed. Empty when the row carries neither."""
    pid = str(row.get("prediction_id") or "").strip()
    if pid:
        return pid
    return str(row.get("sk") or "").replace("PREDICTION#", "", 1).strip()


def resolved_once(rows: Iterable[Any]) -> list[dict]:
    """The partition with every re-write removed.

    Every ungraded row passes through unchanged; for each prediction that carries a grade,
    exactly ONE row survives — the earliest ``outcome_date`` (a missing date sorts first:
    the original, if any, is older than any re-write that stamped one). Order of the input
    is preserved for the survivors. A graded row with no identity at all is its own
    resolution — de-duplication never collapses rows it cannot prove are the same call.
    """
    first: dict[str, dict] = {}
    for row in rows or []:
        if not isinstance(row, dict) or graded_status(row) is None:
            continue
        key = prediction_key(row)
        if not key:
            continue
        held = first.get(key)
        if held is None or str(row.get("outcome_date") or "") < str(held.get("outcome_date") or ""):
            first[key] = row
    survivors = set(id(r) for r in first.values())
    out: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if graded_status(row) is None or not prediction_key(row) or id(row) in survivors:
            out.append(row)
    return out


def counts_this_cycle(row: dict, genesis: str | None) -> bool:
    """Is this row part of the CURRENT cycle's record?

    Phase-visible per ADR-058, and — for a graded row — resolved on or after ``genesis``
    (an ISO ``YYYY-MM-DD``; ``None`` skips the date test). An ungraded row is judged by
    visibility alone, the same predicate every season count already applied.
    """
    if not singleton_visible(row):
        return False
    if genesis and graded_status(row) is not None:
        outcome_date = str(row.get("outcome_date") or "")[:10]
        if outcome_date and outcome_date < genesis:
            return False
    return True


def record_from_rows(rows: Iterable[Any], *, genesis: str | None, career: bool = False) -> dict:
    """``{confirmed, refuted, n, through}`` over a coach's PREDICTION# rows.

    ``through`` is the latest ``outcome_date`` counted (ISO), or None when no counted row
    carries one. ``career=True`` counts every cycle (each resolution once); the default is
    the current cycle only.
    """
    confirmed = refuted = 0
    through = ""
    for row in resolved_once(rows):
        status = graded_status(row)
        if status is None:
            continue
        if not career and not counts_this_cycle(row, genesis):
            continue
        if status == "confirmed":
            confirmed += 1
        else:
            refuted += 1
        outcome_date = str(row.get("outcome_date") or "")[:10]
        if outcome_date > through:
            through = outcome_date
    return {"confirmed": confirmed, "refuted": refuted, "n": confirmed + refuted, "through": through or None}


_MONTH_WORDS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def day_words(iso: str | None) -> str:
    """'2026-09-26' -> 'September 26' (no ISO date reaches a reader sentence).

    A calendar day, read from the string's own slices — never parsed to an instant
    (#3609: a YYYY-MM-DD day needs no parser; every date comparison in this module is
    likewise lexical on the ISO string).
    """
    text = str(iso or "")[:10]
    if len(text) != 10 or not (text[5:7].isdigit() and text[8:10].isdigit()):
        return ""
    month, day = int(text[5:7]), int(text[8:10])
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return ""
    return f"{_MONTH_WORDS[month - 1]} {day}"


def headline(record: dict | None) -> str:
    """The one-line record a roster prints.

    None (read failed) → "record unavailable"; n = 0 → "no checked call yet"; below
    ``PERCENT_FLOOR`` → "0 of 5 checked calls right through September 26"; at or above it
    the percentage rides beside the counts, never instead of them.
    """
    if record is None:
        return "record unavailable"
    n = int(record.get("n") or 0)
    if n == 0:
        return "no checked call yet"
    k = int(record.get("confirmed") or 0)
    calls = "checked call" if n == 1 else "checked calls"
    through = day_words(record.get("through"))
    tail = f" through {through}" if through else ""
    if n < PERCENT_FLOOR:
        return f"{k} of {n} {calls} right{tail}"
    return f"{k} of {n} {calls} right ({round(k / n * 100):.0f}%){tail}"


def _query_rows(table: Any, coach_id: str) -> list:
    kwargs: dict = {
        "KeyConditionExpression": Key("pk").eq(f"COACH#{coach_id}") & Key("sk").begins_with("PREDICTION#"),
        "ExpressionAttributeNames": dict(_PROJECTION_NAMES),
        "ProjectionExpression": ", ".join(_PROJECTION_NAMES),
    }
    rows: list = []
    for _ in range(_MAX_PAGES):
        resp = table.query(**kwargs)
        rows.extend(resp.get("Items") or [])
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs = dict(kwargs, ExclusiveStartKey=last)
    return rows


def for_coach(table: Any, coach_id: str, *, genesis: str | None) -> dict | None:
    """The current-cycle record for one coach, or None when the read failed."""
    if not coach_id or table is None:
        return None
    try:
        return record_from_rows(_query_rows(table, coach_id), genesis=genesis)
    except Exception as exc:  # noqa: BLE001 — absence is the honest degradation, logged
        logger.warning("[coach_record] %s: %s", coach_id, exc)
        return None
