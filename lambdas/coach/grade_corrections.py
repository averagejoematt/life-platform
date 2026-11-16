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

THE INVARIANTS (#5613, owner integrity item 7, 2026-11-02)
---------------------------------------------------------
Versioned rules never silently rewrite history. Three rules, each enforced in code here:

1. **A settled grade changes only through this module.** ``is_settled`` names a settled row
   (a terminal status that is neither the #2221 provisional second look nor the #813 reclaim,
   or ANY row already carrying a correction history). ``status / outcome / outcome_notes``
   on such a row are written only by ``apply_correction`` (and its ledgered inverse
   ``revert_correction``), which keep the original and record ``corrected_at``, ``reason``
   and ``evaluator_version``. The scheduled grader's own write is ``write_first_grade``,
   which REFUSES a settled row and is conditional on the row still reading as it did.
   ``tests/test_settled_grade_writers_5613.py`` fails on any other writer of those fields
   on a ``PREDICTION#`` row in ``lambdas/``, ``deploy/``, ``scripts/`` or ``mcp/``.
2. **A version stamp is only written beside the text that version produced.** The
   ``evaluator_version`` on a row names the rule that wrote its ``outcome_notes``. A re-grade
   whose verdict stands therefore records a ``basis="restate"`` correction (unchanged
   status, the new version's notes / flags / baseline, the old grade kept in
   ``original_grade``) — never a bare stamp. The bare stamp (``stamp_quality``, used by the
   2026-11-01 #5533 run) is removed; ``grade_text_version`` reads which rule wrote the text.
3. **A corrected row is never re-selected by an automated re-grade.** Selection keys on the
   structure (``has_correction_history``: an ``original_grade`` snapshot or any
   ``corrections[]`` entry), never on a reason's wording or an evaluator version — so a
   rule bump (1.1 → 1.2) cannot re-grade an owner ruling. A further change to such a row is
   a deliberate, per-row ``apply_correction`` (``basis="ruling"``, ``ruled_by=...``).

4. **A settled grade under classification review is changed by no automated path** (owner ruling 2026-11-03,
   ``coach/classification_review.py``). ``write_first_grade``, ``revert_correction`` and every non-``ruling``
   ``apply_correction`` refuse a row carrying ``classification_review`` (``ClassificationReviewError``) and are
   conditional on its absence, so a review set between the read and the write still wins. An owner ruling
   (``basis="ruling"``) is what the review waits for: it is allowed, and it RESOLVES the review — a
   ``CLASSREVIEW#`` audit row first, ``resolves_classification_review`` on the entry, and the flag REMOVEd in
   the same conditional update.

Each entry also carries ``basis`` (``regrade | restate | first_grade | ruling``),
``verdict_changed`` and, for a ruling, ``ruled_by`` — structured provenance a reader and a
selector can key on.

Pure over an injected table handle; the clock is a parameter (``now``).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from common.numeric import floats_to_decimal
from experiment.phase_taxonomy import experiment_stamp_for

from coach import (
    classification_review,  # owner ruling 2026-11-03: a disputed settled grade is no automated path's
    evaluation_hold,  # #5607: the per-row grading hold write_first_grade honours
)
from coach.prediction_grading import grading_window_still_open, was_terminalized_by_duplicate_grader

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
    "basis",  # #5613: structured provenance (``ruled_by`` rides beside it on a ruling)
    "verdict_changed",
)

#: The structured provenance every entry written since #5613 carries beside ``ENTRY_FIELDS``.
REGRADE, RESTATE, FIRST_GRADE, RULING = "regrade", "restate", "first_grade", "ruling"
BASES = (REGRADE, RESTATE, FIRST_GRADE, RULING)

#: A grade in one of these statuses is decided (``is_settled`` adds the two provisional exceptions).
TERMINAL_STATUSES = ("confirmed", "refuted", "inconclusive", "expired")


class SettledGradeError(RuntimeError):
    """A write that would change a settled grade outside ``apply_correction``."""


def has_correction_history(row: dict) -> bool:
    """Has this row ever been corrected (or reverted)? Structural: an ``original_grade`` snapshot or any
    ``corrections[]`` entry — never the reason's wording, never the version (#5613 rule 3)."""
    if not isinstance(row, dict):
        return False
    if isinstance(row.get("original_grade"), dict) and row["original_grade"]:
        return True
    return any(isinstance(e, dict) for e in row.get("corrections") or [])


def is_settled(row: dict) -> bool:
    """A decided grade the scheduled grader may no longer write (#5613 rule 1): a terminal status that
    is not provisional (#2221) or an unreal #813 inconclusive — or any terminal row with a correction
    history (a corrected row is the ledger's, even if its corrected notes read provisional)."""
    if not isinstance(row, dict) or str(row.get("status") or "") not in TERMINAL_STATUSES:
        return False
    if has_correction_history(row):
        return True
    return not (grading_window_still_open(row) or was_terminalized_by_duplicate_grader(row))


def grade_text_version(row: dict) -> str | None:
    """The rule version that WROTE the row's grade text — ``outcome_notes.algo_version`` — or None."""
    try:
        notes = json.loads(row.get("outcome_notes") or "{}")
    except (TypeError, ValueError):
        return None
    v = notes.get("algo_version") if isinstance(notes, dict) else None
    return str(v) if v is not None else None


def write_first_grade(table: Any, row: dict, evaluation: dict, *, outcome_notes: str, evaluator_version: str) -> bool:
    """The scheduled grader's write-back of a grade onto a row that is NOT settled (pending, confirming, a
    provisional second look, an #813 reclaim). Refuses a settled row (``SettledGradeError``) and is
    conditional on the stored status and notes still being the ones this grade was computed from, so a
    row corrected between the read and the write is never overwritten. Refuses a row whose grading is held
    (``HeldGradeError``, #5607) and is conditional on it carrying no hold. Returns True when it landed."""
    if is_settled(row):
        raise SettledGradeError(f"{row.get('pk')} / {row.get('sk')} is settled ({row.get('status')}): only apply_correction may change it")
    if evaluation_hold.is_grading_held(row):  # #5607: a held row is not graded until the owner rules on it
        raise evaluation_hold.HeldGradeError(f"{row.get('pk')} / {row.get('sk')} is held for review: {evaluation_hold.hold_reason(row)}")
    classification_review.refuse_automated(row, "the scheduled grader")  # a disputed verdict waits for a ruling
    pk = row.get("pk") or f"COACH#{row.get('coach_id', '')}"
    sk = row.get("sk") or f"PREDICTION#{row.get('prediction_id', '')}"
    values: dict[str, Any] = {
        ":status": evaluation["status"],
        ":outcome": evaluation["status"],
        ":odate": evaluation["evaluated_date"],
        ":notes": outcome_notes,
        ":qf": list(evaluation.get("quality_flags") or []),
        ":ver": evaluator_version,
    }
    conds = [
        f"attribute_not_exists({evaluation_hold.ATTR})",  # #5607: a hold set after the read still wins
        f"attribute_not_exists({classification_review.ATTR})",  # and so does a classification review
    ]
    if row.get("status") is not None:
        conds.append("#status = :prior")
        values[":prior"] = row["status"]
    if row.get("outcome_notes") is not None:
        conds.append("outcome_notes = :prior_notes")
        values[":prior_notes"] = row["outcome_notes"]
    kwargs: dict[str, Any] = {
        "Key": {"pk": pk, "sk": sk},
        "UpdateExpression": (
            "SET #status = :status, outcome = :outcome, outcome_date = :odate, outcome_notes = :notes, "
            "quality_flags = :qf, evaluator_version = :ver"  # #5533 (a): the grader's own flags, top-level for projected reads
        ),
        "ExpressionAttributeNames": {"#status": "status"},
        "ExpressionAttributeValues": values,
    }
    kwargs["ConditionExpression"] = " AND ".join(conds)
    table.update_item(**kwargs)
    return True


def now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def entry(
    row: dict,
    corrected: dict,
    *,
    reason: str,
    evaluator_version: str,
    corrected_at: str,
    basis: str = REGRADE,
    ruled_by: str | None = None,
) -> dict:
    """One correction entry — the original grade off ``row``, the corrected grade off
    ``corrected`` (``{status, outcome_date, outcome_notes}``), plus its structured provenance
    (``basis``, ``verdict_changed``, and ``ruled_by`` on a ruling)."""
    if basis not in BASES:
        raise ValueError(f"basis must be one of {BASES}, not {basis!r}")
    if basis == RULING and not ruled_by:
        raise ValueError("a ruling names who ruled (ruled_by)")
    out = {
        "original_status": row.get("status"),
        "original_outcome_date": row.get("outcome_date"),
        "original_outcome_notes": row.get("outcome_notes"),
        "corrected_status": corrected.get("status"),
        "corrected_outcome_date": corrected.get("outcome_date"),
        "corrected_outcome_notes": corrected.get("outcome_notes"),
        "corrected_at": corrected_at,
        "reason": reason,
        "evaluator_version": evaluator_version,
        "basis": basis,
        "verdict_changed": corrected.get("status") != row.get("status"),
    }
    if ruled_by:
        out["ruled_by"] = ruled_by
    return out


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
    """Has this row a correction under ``evaluator_version`` (and ``reason_prefix``)? A READ for reports and
    the #5533 revert's scope only — re-grade SELECTION keys on ``has_correction_history`` (#5613 rule 3):
    a reason prefix and a version both miss an owner ruling once the rules move on."""
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
    basis: str = REGRADE,
    ruled_by: str | None = None,
) -> dict:
    """Write one correction: the ledger row, then the prediction row. Returns the entry.

    ``corrected`` is ``{status, outcome_date, outcome_notes}`` plus, optionally, ``baseline``
    and ``quality_flags`` from the re-grade. ``update_grade=False`` records the entry and the
    snapshot without touching the grade fields — for a row the evaluator's own write path
    has just graded for the first time (a retired coach's sealed bet), so the ledger still
    shows the pending → graded transition.

    ``basis="restate"`` is a re-grade whose verdict stands (#5613 rule 2): the status must not
    change, and the row's notes / flags / baseline / ``evaluator_version`` become the new
    rule's together, with the old text kept in ``original_grade``.
    """
    if basis == RESTATE and corrected.get("status") != row.get("status"):
        raise ValueError("a restate keeps the verdict; a changed verdict is a regrade")
    if basis != RULING:  # a disputed verdict changes only by an owner ruling (classification_review)
        classification_review.refuse_automated(row, f"a {basis} correction")
    at = now_iso(now)
    e = entry(row, corrected, reason=reason, evaluator_version=evaluator_version, corrected_at=at, basis=basis, ruled_by=ruled_by)
    review = classification_review.review_of(row) if basis == RULING else None
    if review is not None:
        # The ruling the review waited for: the review's resolution is on the record BEFORE anything changes.
        e["resolves_classification_review"] = review
        table.put_item(Item=floats_to_decimal(classification_review_resolution_row(row, review, e, ruled_by=ruled_by)))
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
        if row.get("outcome_notes") is not None:  # #5613: the text the plan read is still the text on the row
            values[":prior_notes"] = row["outcome_notes"]
            kwargs["ConditionExpression"] += " AND outcome_notes = :prior_notes"
    if basis != RULING:  # a review set after the plan read the row still wins
        cond = f"attribute_not_exists({classification_review.ATTR})"
        kwargs["ConditionExpression"] = f"{kwargs['ConditionExpression']} AND {cond}" if kwargs.get("ConditionExpression") else cond
    kwargs["UpdateExpression"] = "SET " + ", ".join(sets) + (f" REMOVE {classification_review.ATTR}" if review is not None else "")
    kwargs["ExpressionAttributeValues"] = floats_to_decimal(values)
    if names:
        kwargs["ExpressionAttributeNames"] = names
    table.update_item(**kwargs)
    return e


# ══════════════════════════════════════════════════════════════════════════════
# THE "NOTHING CHANGES" VERDICT, RE-SCORED (owner ruling 2026-11-09, third, A — verbatim intent):
# "Correct the historical 'nothing changes' baseline verdicts under the current direction rule. Use the original
# frozen prediction, observation window and underlying evidence. Apply the current rule consistently to every affected
# call, whether it benefits the coaches or the baseline. Preserve original verdicts; record each correction with
# ruleset version, reason, timestamp. Do NOT rewrite the historical baseline as though the new verdict had been the
# original verdict."
#
# So a baseline correction is an OVERLAY. ``apply_baseline_correction`` writes, in this order:
#   1. the ledger row ``CORRECTION#BASELINE#{prediction_id}#{corrected_at}`` on the call's own partition (append-only,
#      ``attribute_not_exists(sk)``) — the entry plus its evidence;
#   2. ONE conditional ``list_append`` of the same entry to the row's ``baseline_corrections[]``.
# The frozen ``baseline`` map, ``status`` / ``outcome*``, ``corrections[]`` and ``original_grade`` are never touched,
# so the first verdict stays readable as the first verdict. Readers take ``coach_baseline.effective`` (the latest
# entry's ``corrected_baseline``, else the frozen stamp). The coach's own grade is not this function's to change.
# ══════════════════════════════════════════════════════════════════════════════

BASELINE_PREFIX = "CORRECTION#BASELINE#"


def baseline_correction_entry(
    row: dict,
    corrected_baseline: dict,
    *,
    reason: str,
    ruleset_version: str,
    corrected_at: str,
    ruled_by: str,
    ruling_ref: str,
    cause: str,
) -> dict:
    """One baseline correction entry — the verdict as it stood (the effective one), the re-scored verdict, and why."""
    from coach import coach_baseline

    if not isinstance(corrected_baseline, dict) or corrected_baseline.get("rule") != coach_baseline.RULE_ID:
        raise ValueError(f"a baseline correction carries a {coach_baseline.RULE_ID!r} stamp")
    if not isinstance(corrected_baseline.get("right"), bool) and not corrected_baseline.get("unscorable"):
        raise ValueError("a corrected baseline is right/wrong (a bool) or names why it is unscorable")
    if not (reason and ruleset_version and ruled_by and ruling_ref and cause):
        raise ValueError("a baseline correction names its reason, ruleset version, ruler, ruling and cause")
    before = coach_baseline.effective(row)
    if not isinstance(before, dict):
        raise ValueError(f"{row.get('pk')} / {row.get('sk')} has no frozen 'nothing changes' verdict to correct")
    if before.get("right") == corrected_baseline.get("right") and before.get("unscorable") == corrected_baseline.get("unscorable"):
        raise ValueError(f"{row.get('pk')} / {row.get('sk')}: the re-scored verdict equals the one it would correct")
    return {
        "original_baseline": dict(before),
        "corrected_baseline": dict(corrected_baseline),
        "original_right": before.get("right"),
        "corrected_right": corrected_baseline.get("right"),
        "corrected_at": corrected_at,
        "reason": reason,
        "ruleset_version": str(ruleset_version),
        "cause": cause,
        "basis": RULING,
        "ruled_by": ruled_by,
        "ruling_ref": ruling_ref,
        "verdict_changed": before.get("right") != corrected_baseline.get("right"),
    }


def baseline_correction_row(row: dict, e: dict, evidence: dict | None = None) -> dict:
    """The ledger row for one baseline correction, on the prediction's own partition."""
    pk, sk = str(row["pk"]), f"{BASELINE_PREFIX}{prediction_id(row)}#{e['corrected_at']}"
    out = {
        **experiment_stamp_for(pk, sk),
        "pk": pk,
        "sk": sk,
        "kind": "baseline",
        "prediction_id": prediction_id(row),
        "prediction_sk": row.get("sk"),
        "coach_id": row.get("coach_id") or "",
        **e,
    }
    if evidence:
        out["evidence"] = evidence
    return out


def apply_baseline_correction(
    table: Any,
    row: dict,
    corrected_baseline: dict,
    *,
    reason: str,
    ruleset_version: str,
    ruled_by: str,
    ruling_ref: str,
    cause: str,
    evidence: dict | None = None,
    now: datetime | None = None,
) -> dict:
    """Record one re-scored "nothing changes" verdict as an overlay (see the block comment above). Conditional on the row
    still carrying the frozen stamp, the grade and the number of earlier baseline corrections the plan read — a stale
    plan or a second run writes nothing. Only an owner ruling may do this (``basis="ruling"``). Returns the entry."""
    from coach import coach_baseline

    if str(row.get("status") or "") not in ("confirmed", "refuted"):
        raise ValueError(f"{row.get('pk')} / {row.get('sk')} is not graded right or wrong: no served verdict to correct")
    at = now_iso(now)
    e = baseline_correction_entry(
        row,
        corrected_baseline,
        reason=reason,
        ruleset_version=ruleset_version,
        corrected_at=at,
        ruled_by=ruled_by,
        ruling_ref=ruling_ref,
        cause=cause,
    )
    table.put_item(Item=floats_to_decimal(baseline_correction_row(row, e, evidence)), ConditionExpression="attribute_not_exists(sk)")
    prior = len(coach_baseline.baseline_corrections(row))
    attr = coach_baseline.CORRECTIONS_ATTR
    table.update_item(
        Key={"pk": row["pk"], "sk": row["sk"]},
        UpdateExpression=f"SET {attr} = list_append(if_not_exists({attr}, :empty), :entry)",
        ConditionExpression=(
            f"attribute_exists(sk) AND #status = :st AND baseline = :frozen AND "
            f"({'attribute_not_exists(' + attr + ')' if not prior else 'size(' + attr + ') = :n'})"
        ),
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues=floats_to_decimal(
            {":empty": [], ":entry": [e], ":st": row.get("status"), ":frozen": row.get("baseline"), **({":n": prior} if prior else {})}
        ),
    )
    return e


def classification_review_resolution_row(row: dict, review: dict, e: dict, *, ruled_by: str | None) -> dict:
    """The ``CLASSREVIEW#`` audit row an owner ruling writes when it resolves a classification review — the
    review it resolves, the verdict as it stood and the verdict the ruling sets, at the correction's instant."""
    pk = str(row["pk"])
    sk = f"{classification_review.AUDIT_SK_PREFIX}{prediction_id(row)}#{e['corrected_at']}"
    return {
        **experiment_stamp_for(pk, sk),
        "pk": pk,
        "sk": sk,
        "action": "resolved",
        "prediction_id": prediction_id(row),
        "prediction_sk": row.get("sk"),
        "actor": ruled_by or "owner",
        "ruling_ref": review.get("ruling_ref"),
        "at": e["corrected_at"],
        "reason": e.get("reason"),
        "resolved_review": review,
        "prior_status": row.get("status"),
        "ruled_status": e.get("corrected_status"),
        "verdict_changed": e.get("verdict_changed"),
    }


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
    snapshot's grade is the 'corrected' one — the entry fields, plus the two that name it a reversal."""
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
        "basis": "revert",
        "verdict_changed": og.get("status") != row.get("status"),
    }


def revert_correction(table: Any, row: dict, *, reason: str, now: datetime | None = None) -> dict | None:
    """Restore every field `original_grade` snapshotted to exactly its snapshotted value, and REMOVE a field the
    snapshot did not carry (it did not exist before the correction — `quality_flags`, `evaluator_version` on a
    row graded before the flags existed). Ledger row first; then one conditional update on the row still carrying
    the status being reverted. Returns the entry, or None when there is nothing to revert / it was reverted."""
    og = row.get("original_grade")
    if not isinstance(og, dict) or not og or reverted_already(row):
        return None
    classification_review.refuse_automated(row, "a revert")  # a disputed verdict waits for a ruling
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
        ConditionExpression=f"#status = :prior AND attribute_not_exists({classification_review.ATTR})",
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
