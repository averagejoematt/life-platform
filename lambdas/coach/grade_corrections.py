"""grade_corrections.py — a changed grade keeps its history (#5533, owner requirement B, 2026-10-31).

THE RULE
--------
A grade is never silently rewritten. When the grader's rules change and a row's verdict
changes with them, the operator must be able to show, for that row: what the grade was,
when it was written, what it became, when, why, and under which evaluator version — and
every published aggregate (the K of N record, Brier/skill, the "nothing changes"
comparison) must read the CORRECTED grade.

THE SHAPE
---------
Two writes, in this order, per correction (``apply_correction``):

1. **The ledger row** ``COACH#{coach_id}`` / ``CORRECTION#{prediction_id}#{corrected_at}``
   (a diary claim's correction lands on its own partition the same way) — the correction
   entry plus the row's identity. Written FIRST, so a failure between the two writes leaves
   a visible ledger row and an untouched grade, never a changed grade with no record.
2. **The prediction row**: ``corrections[]`` gains the same entry (``list_append``);
   ``original_grade`` is snapshotted ONCE (``if_not_exists``) with the pre-correction
   ``status / outcome / outcome_date / outcome_notes / baseline / quality_flags /
   evaluator_version``, so the first grade survives even if the list is edited; and only
   then are ``status`` / ``outcome`` / ``outcome_date`` / ``outcome_notes`` (plus
   ``evaluator_version``, ``quality_flags`` and ``baseline`` when the re-grade produced
   them) set to the corrected values — conditional on the row still carrying the status the
   correction was planned against, so a stale plan or a second run writes nothing.

Each entry is ``{original_status, original_outcome_date, original_outcome_notes,
corrected_status, corrected_outcome_date, corrected_outcome_notes, corrected_at, reason,
evaluator_version}``. Every numeric leaf is a Decimal (``common.numeric.floats_to_decimal``).

Readers need no change: ``coach_record``, ``experiment.calibration_core`` and
``coach_baseline`` read ``status`` — the corrected value — and ``tests/test_grader_fixes_5533.py``
pins that a corrected row scores under its corrected status.

NOT rewritten: the ``CONFIDENCE#`` Beta posterior and the ``LEARNING#`` row the original
grade wrote (the same residual the #4617/#4618 corrections carried). The served record is
counted from ``PREDICTION#`` rows only (#4220), which is what a correction changes.

A run's aggregate impact is one ``CORRECTION#SUMMARY#{ts}`` row on the evaluator's own
state partition (``EVALUATOR#coach_prediction``, SYSTEM_STATE in the phase taxonomy):
``summary_row``.

Pure over an injected table handle; the clock is a parameter (``now``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from common.numeric import floats_to_decimal
from experiment.phase_taxonomy import experiment_stamp_for

CORRECTION_PREFIX = "CORRECTION#"
SUMMARY_PREFIX = "CORRECTION#SUMMARY#"
#: The evaluator's own state partition (``coach_prediction_evaluator._LAST_DECIDED_PK``).
SUMMARY_PK = "EVALUATOR#coach_prediction"

#: What ``original_grade`` snapshots the first time a row is corrected.
ORIGINAL_FIELDS = ("status", "outcome", "outcome_date", "outcome_notes", "baseline", "quality_flags", "evaluator_version")

#: The entry's own keys, in the order the issue names them.
ENTRY_FIELDS = (
    "original_status",
    "original_outcome_date",
    "original_outcome_notes",
    "corrected_status",
    "corrected_outcome_date",
    "corrected_outcome_notes",
    "corrected_at",
    "reason",
    "evaluator_version",
)


def now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def entry(row: dict, corrected: dict, *, reason: str, evaluator_version: str, corrected_at: str) -> dict:
    """One correction entry — the original grade off ``row``, the corrected grade off
    ``corrected`` (``{status, outcome_date, outcome_notes}``)."""
    return {
        "original_status": row.get("status"),
        "original_outcome_date": row.get("outcome_date"),
        "original_outcome_notes": row.get("outcome_notes"),
        "corrected_status": corrected.get("status"),
        "corrected_outcome_date": corrected.get("outcome_date"),
        "corrected_outcome_notes": corrected.get("outcome_notes"),
        "corrected_at": corrected_at,
        "reason": reason,
        "evaluator_version": evaluator_version,
    }


def original_grade(row: dict, snapshot_at: str) -> dict:
    """The pre-correction grade, as it stood — present fields only, plus when it was taken."""
    out = {k: row.get(k) for k in ORIGINAL_FIELDS if row.get(k) is not None}
    out["snapshot_at"] = snapshot_at
    return out


def prediction_id(row: dict) -> str:
    return str(row.get("prediction_id") or str(row.get("sk") or "").replace("PREDICTION#", "", 1))


def correction_row(row: dict, e: dict) -> dict:
    """The ledger row for one entry, on the prediction's own partition."""
    pk, sk = str(row["pk"]), f"{CORRECTION_PREFIX}{prediction_id(row)}#{e['corrected_at']}"
    return {
        **experiment_stamp_for(pk, sk),
        "pk": pk,
        "sk": sk,
        "prediction_id": prediction_id(row),
        "prediction_sk": row.get("sk"),
        "coach_id": row.get("coach_id") or "",
        **e,
    }


def already_corrected(row: dict, *, evaluator_version: str, reason_prefix: str | None = None) -> bool:
    """Has this row a correction under ``evaluator_version`` (and ``reason_prefix``)? The
    planner's idempotence: a second run selects nothing it already corrected."""
    for e in row.get("corrections") or []:
        if not isinstance(e, dict) or str(e.get("evaluator_version")) != str(evaluator_version):
            continue
        if reason_prefix is None or str(e.get("reason") or "").startswith(reason_prefix):
            return True
    return False


def apply_correction(
    table: Any,
    row: dict,
    corrected: dict,
    *,
    reason: str,
    evaluator_version: str,
    now: datetime | None = None,
    update_grade: bool = True,
) -> dict:
    """Write one correction: the ledger row, then the prediction row. Returns the entry.

    ``corrected`` is ``{status, outcome_date, outcome_notes}`` plus, optionally, ``baseline``
    and ``quality_flags`` from the re-grade. ``update_grade=False`` records the entry and the
    snapshot without touching the grade fields — for a row the evaluator's own write path
    has just graded for the first time (a retired coach's sealed bet), so the ledger still
    shows the pending → graded transition.
    """
    at = now_iso(now)
    e = entry(row, corrected, reason=reason, evaluator_version=evaluator_version, corrected_at=at)
    table.put_item(Item=floats_to_decimal(correction_row(row, e)))

    sets = [
        "corrections = list_append(if_not_exists(corrections, :empty), :entry)",
        "original_grade = if_not_exists(original_grade, :orig)",
    ]
    names: dict[str, str] = {}
    values: dict[str, Any] = {":empty": [], ":entry": [e], ":orig": original_grade(row, at)}
    kwargs: dict[str, Any] = {"Key": {"pk": row["pk"], "sk": row["sk"]}}
    if update_grade:
        names["#status"] = "status"
        sets += ["#status = :st", "outcome = :st", "outcome_date = :od", "outcome_notes = :on", "evaluator_version = :ev"]
        values.update({":st": corrected.get("status"), ":od": corrected.get("outcome_date"), ":on": corrected.get("outcome_notes")})
        values[":ev"] = evaluator_version
        if corrected.get("quality_flags") is not None:
            sets.append("quality_flags = :qf")
            values[":qf"] = list(corrected["quality_flags"])
        if corrected.get("baseline"):
            sets.append("baseline = :bl")
            values[":bl"] = corrected["baseline"]
        values[":prior"] = row.get("status")
        kwargs["ConditionExpression"] = "#status = :prior"
    kwargs["UpdateExpression"] = "SET " + ", ".join(sets)
    kwargs["ExpressionAttributeValues"] = floats_to_decimal(values)
    if names:
        kwargs["ExpressionAttributeNames"] = names
    table.update_item(**kwargs)
    return e


def stamp_quality(table: Any, row: dict, quality_flags: list, *, evaluator_version: str) -> bool:
    """A grade that STANDS under the new rules is not corrected — only annotated: the row
    gains ``quality_flags`` / ``evaluator_version`` once (``attribute_not_exists``), never a
    ledger entry. Returns whether the write landed; a refused condition is the no-op."""
    try:
        table.update_item(
            Key={"pk": row["pk"], "sk": row["sk"]},
            UpdateExpression="SET quality_flags = :qf, evaluator_version = :ev",
            ConditionExpression="attribute_not_exists(quality_flags)",
            ExpressionAttributeValues={":qf": list(quality_flags or []), ":ev": evaluator_version},
        )
        return True
    except Exception:  # noqa: BLE001 — ConditionalCheckFailed is the idempotent path
        return False


def summary_row(summary: dict, *, now: datetime | None = None) -> dict:
    """The one aggregate-impact row for a correction run (``CORRECTION#SUMMARY#{ts}``)."""
    at = now_iso(now)
    pk, sk = SUMMARY_PK, f"{SUMMARY_PREFIX}{at}"
    return floats_to_decimal({**experiment_stamp_for(pk, sk), "pk": pk, "sk": sk, "written_at": at, **summary})


def write_summary(table: Any, summary: dict, *, now: datetime | None = None) -> dict:
    item = summary_row(summary, now=now)
    table.put_item(Item=item)
    return item


# ══════════════════════════════════════════════════════════════════════════════
# REVERT (owner ask, 2026-11-01): the exact pre-change grading state is restorable, on the record.
# A revert is itself a correction entry — the ledger row FIRST, then the prediction row — so the
# audit trail reads correction → reversal, never a deletion. `original_grade` is never removed:
# it is the proof of what the row said before anyone touched it.
# ══════════════════════════════════════════════════════════════════════════════

REVERT_REASON_PREFIX = "REVERT"


def reverted_already(row: dict) -> bool:
    """Has the row's current `original_grade` snapshot already been restored? (A second revert run selects nothing.)"""
    og = row.get("original_grade") or {}
    snap = og.get("snapshot_at")
    for e in row.get("corrections") or []:
        if isinstance(e, dict) and e.get("reverts") and str(e.get("restores_snapshot_at")) == str(snap):
            return True
    return False


def revert_entry(row: dict, *, reason: str, reverted_at: str) -> dict:
    """The reversal as a correction entry: the row's CURRENT grade is the 'original' of this entry and the
    snapshot's grade is the 'corrected' one — the same nine fields, plus the two that name it a reversal."""
    og = row.get("original_grade") or {}
    return {
        "original_status": row.get("status"),
        "original_outcome_date": row.get("outcome_date"),
        "original_outcome_notes": row.get("outcome_notes"),
        "corrected_status": og.get("status"),
        "corrected_outcome_date": og.get("outcome_date"),
        "corrected_outcome_notes": og.get("outcome_notes"),
        "corrected_at": reverted_at,
        "reason": reason,
        "evaluator_version": str(og.get("evaluator_version") or ""),
        "reverts": True,
        "restores_snapshot_at": og.get("snapshot_at"),
    }


def revert_correction(table: Any, row: dict, *, reason: str, now: datetime | None = None) -> dict | None:
    """Restore every field `original_grade` snapshotted to exactly its snapshotted value, and REMOVE a field the
    snapshot did not carry (it did not exist before the correction — `quality_flags`, `evaluator_version` on a
    row graded before the flags existed). Ledger row first; then one conditional update on the row still carrying
    the status being reverted. Returns the entry, or None when there is nothing to revert / it was reverted."""
    og = row.get("original_grade")
    if not isinstance(og, dict) or not og or reverted_already(row):
        return None
    at = now_iso(now)
    reason = reason if reason.startswith(REVERT_REASON_PREFIX) else f"{REVERT_REASON_PREFIX} {reason}"
    e = revert_entry(row, reason=reason, reverted_at=at)
    table.put_item(Item=floats_to_decimal(correction_row(row, e)))
    names: dict[str, str] = {"#status": "status"}
    values: dict[str, Any] = {":empty": [], ":entry": [e], ":prior": row.get("status")}
    sets = ["corrections = list_append(if_not_exists(corrections, :empty), :entry)"]
    removes: list[str] = []
    for k in ORIGINAL_FIELDS:
        names[f"#{k}"] = k
        if k in og:
            sets.append(f"#{k} = :{k}")
            values[f":{k}"] = og[k]
        else:
            removes.append(f"#{k}")
    expr = "SET " + ", ".join(sets) + (" REMOVE " + ", ".join(removes) if removes else "")
    table.update_item(
        Key={"pk": row["pk"], "sk": row["sk"]},
        UpdateExpression=expr,
        ConditionExpression="#status = :prior",
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=floats_to_decimal(values),
    )
    return e


def unstamp_quality(table: Any, row: dict, *, evaluator_version: str) -> bool:
    """Undo `stamp_quality` on a row the grader only annotated (no `original_grade`, so no correction): the two
    stamped attributes are REMOVED, conditional on the version that stamped them. Returns whether it landed; a
    row already un-stamped (or stamped by a later version) is the no-op."""
    if row.get("original_grade") or "quality_flags" not in row:
        return False
    try:
        table.update_item(
            Key={"pk": row["pk"], "sk": row["sk"]},
            UpdateExpression="REMOVE quality_flags, evaluator_version",
            ConditionExpression="evaluator_version = :ev AND attribute_not_exists(original_grade)",
            ExpressionAttributeValues={":ev": evaluator_version},
        )
        return True
    except Exception:  # noqa: BLE001 — ConditionalCheckFailed is the idempotent path
        return False
