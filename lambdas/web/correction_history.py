"""correction_history.py — every grade correction a PREDICTION# row stores, in ONE served shape (#5610).

WHY. Owner ruling 2026-11-02 (decision D): "I want the historical corrections visible … Readers
should be able to see the original verdict, corrected verdict, explanation and when the correction
actually occurred. Keep event dates, prediction dates, grading dates and correction-publication
dates distinct. Never invent missing timestamps." Before this module ``/api/ledger_export`` served
only ``corrections[]`` — the #5533 shape — so the 25 corrections the older writers left on the rows
(measured 2026-11-02) were invisible: each such row was served with ``corrections: []``.

THE THREE STORED SHAPES (read, never rewritten):

1. ``corrections[]`` (``coach.grade_corrections.entry``, #5533 and later): the nine-field entry.
2. ``verdict_correction`` — ONE map per row, written by the #3551/#4541/#4617/#4618 scripts under
   ``scripts/regrade_*``. #4617/#4618 store ``{issue, action, corrected_at, reason, new_status,
   prior: {status, outcome_date, outcome_notes, target_date?, …}, named_day?}``; #4541 stores
   ``{issue, prior_status, prior_reason, corrected_at, regraded_as, correction}`` (no new status);
   #3551 stores ``{prior: {status, outcome_notes, corrected_at, reason}, regraded_as, new_status}``.
3. ``respecified_at`` / ``respecified_from`` / ``respecified_reason`` — #4618's trail on a call that
   was still OPEN: the target was re-derived, the grade came later on the new target.

THE SERVED ENTRY. The nine #5533 keys, unchanged in name and meaning, plus what a reader needs:

    {source, kind, rules: [{id, version}], explanation,
     said_on,                                   # the day the call was made (the item's logged_date)
     original_status, original_outcome_date,    # the first grade and the DAY it was graded
     original_outcome_notes,
     corrected_status, corrected_outcome_date,  # the grade after, and the day THAT grade names
     corrected_outcome_notes,
     target_before, target_after,               # the day the call was about, before and after (when it moved)
     corrected_at,                              # when the correction was written — the stored instant, verbatim
     published_on,                              # when it first appeared publicly — NOT RECORDED: always null
     reason,                                    # the STORED reason, verbatim — the audit record, never reworded
     evaluator_version}

NEVER INVENTED. Every date is the stored one or null. No writer recorded the TIME a call was first
graded — only the day (``outcome_date``) — so the original grading is a day, never an instant. The
older writers did not record the corrected grade's own day: ``corrected_outcome_date`` is null on
them, not ``corrected_at[:10]``. No writer recorded when a correction first reached the public site,
so ``published_on`` is null on every entry; ``corrected_at`` is the correction's recorded time and is
labelled as such. The one derivation: #4541 stored no ``new_status``; its write set the row's status
to the corrected grade, so the row's CURRENT status is that grade — used only when no later correction
on the row could have moved it, otherwise null.

The explanation comes from ``web.correction_rules`` (one registry). An unknown rule id yields
``explanation: None`` here (the ledger stays up, logged loudly) and fails the snapshot export
(``scripts/publish_snapshot_contract.validate_correction``) — a page never prints engineering text.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

from web import correction_rules

logger = logging.getLogger(__name__)

#: The served keys, in order — the snapshot contract (``CORRECTION_FIELDS``) and the zod schema declare the same.
FIELDS = (
    "source",
    "kind",
    "rules",
    "explanation",
    "said_on",
    "original_status",
    "original_outcome_date",
    "original_outcome_notes",
    "corrected_status",
    "corrected_outcome_date",
    "corrected_outcome_notes",
    "target_before",
    "target_after",
    "corrected_at",
    "published_on",
    "reason",
    "evaluator_version",
)

_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RULE_5533 = re.compile(r"^#(\d+) \(([a-z])\)(?: \+ owner ruling (\d{4}-\d{2}-\d{2}))?:")
_ISSUE = re.compile(r"#(\d{3,5})\b")
#: verdict_correction actions → the served kind.
_KIND_OF_ACTION = {"restate": "restate", "regrade": "regrade", "withdraw:not-a-forecast": "withdraw", "withdraw:no-reading": "withdraw"}


def _map(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _day(value: Any) -> str | None:
    s = str(value or "")[:10]
    return s if _ISO_DAY.match(s) else None


def _text(value: Any) -> str | None:
    s = str(value).strip() if value is not None else ""
    return s or None


def _notes_text(value: Any) -> str | None:
    """Stored outcome notes as the string they are stored as (a JSON string on every writer); a map is serialised."""
    if value is None or value == "":
        return None
    return value if isinstance(value, str) else json.dumps(value, default=str, sort_keys=True)


def _version(value: Any) -> str | None:
    s = str(value).strip() if value is not None else ""
    return s or None


def rule_ids_of_reason(reason: str) -> list[str]:
    """The rule ids in a ``corrections[]`` entry's stored reason — ``" | "``-joined parts, one id each.
    A part no pattern names yields ``unknown:<first 40 chars>`` (never silently dropped)."""
    ids = []
    for part in [p.strip() for p in str(reason or "").split(" | ") if p.strip()] or [""]:
        if part.startswith("REVERT"):
            ids.append("revert")
            continue
        m = _RULE_5533.match(part)
        if m:
            ids.append(f"#{m.group(1)}:{m.group(2)}" + (f"+owner-{m.group(3)}" if m.group(3) else ""))
        else:
            ids.append(f"unknown:{part[:40]}")
    return ids


def rule_id_of_verdict_correction(vc: dict) -> str:
    """``#<issue>:<action or regraded_as>`` — the writer and its outcome, as stored."""
    prior = _map(vc.get("prior"))
    issue = _text(vc.get("issue"))
    if not issue:
        m = _ISSUE.search(str(prior.get("reason") or vc.get("reason") or vc.get("correction") or ""))
        issue = f"#{m.group(1)}" if m else "unknown"
    what = _text(vc.get("action")) or _text(vc.get("regraded_as")) or "unknown"
    return f"{issue}:{what}"


def _explained(entry: dict, rule_ids: list[str], where: str) -> dict:
    try:
        entry["explanation"] = correction_rules.explain(rule_ids)
    except correction_rules.UnknownCorrectionRule as e:
        logger.error(f"[correction_history] {where}: {e}")
        entry["explanation"] = None
    return entry


def _base(source: str, kind: str, rule_ids: list[str], version: str | None, said_on: str | None) -> dict:
    out: dict = {k: None for k in FIELDS}
    out.update(source=source, kind=kind, rules=[{"id": r, "version": version} for r in rule_ids], said_on=said_on)
    return out


def from_corrections_entry(e: dict, said_on: str | None, where: str) -> dict:
    reason = _text(e.get("reason"))
    ids = rule_ids_of_reason(reason or "")
    version = _version(e.get("evaluator_version"))
    kind = (
        "revert"
        if e.get("reverts") or ids == ["revert"]
        else ("restate" if e.get("original_status") == e.get("corrected_status") else "regrade")
    )
    out = _base("corrections", kind, ids, version, said_on)
    out.update(
        reason=reason,
        original_status=_text(e.get("original_status")),
        original_outcome_date=_day(e.get("original_outcome_date")),
        original_outcome_notes=_notes_text(e.get("original_outcome_notes")),
        corrected_status=_text(e.get("corrected_status")),
        corrected_outcome_date=_day(e.get("corrected_outcome_date")),
        corrected_outcome_notes=_notes_text(e.get("corrected_outcome_notes")),
        corrected_at=_text(e.get("corrected_at")),
        evaluator_version=version,
    )
    return _explained(out, ids, where)


def from_verdict_correction(vc: dict, row: dict, said_on: str | None, later_change: bool, where: str) -> dict:
    prior = _map(vc.get("prior"))
    rid = rule_id_of_verdict_correction(vc)
    action = _text(vc.get("action")) or ""
    reason = _text(vc.get("reason")) or _text(vc.get("correction")) or _text(prior.get("reason") if not vc.get("issue") else None)
    original_status = _text(prior.get("status")) or _text(vc.get("prior_status"))
    corrected_status = _text(vc.get("new_status"))
    if corrected_status is None and not later_change:
        corrected_status = _text(row.get("status"))  # #4541: its write set the row's status to the corrected grade
    kind = _KIND_OF_ACTION.get(action) or ("restate" if original_status and original_status == corrected_status else "regrade")
    out = _base("verdict_correction", kind, [rid], None, said_on)
    out.update(
        reason=reason,
        original_status=original_status,
        original_outcome_date=_day(prior.get("outcome_date")),
        original_outcome_notes=_notes_text(prior.get("outcome_notes")),
        corrected_status=corrected_status,
        # The older writers kept the row's outcome_date; the re-grade's own day was not recorded.
        corrected_outcome_date=None,
        corrected_outcome_notes=None,
        target_before=_day(prior.get("target_date")),
        target_after=_day(vc.get("named_day")) if prior.get("target_date") else None,
        # #3551 kept its instant inside `prior`; every other writer at the top.
        corrected_at=_text(vc.get("corrected_at")) or _text(prior.get("corrected_at")),
    )
    return _explained(out, [rid], where)


def from_respecified(row: dict, said_on: str | None, due_of: Callable[[dict], str | None], later_change: bool, where: str) -> dict:
    old = _map(row.get("respecified_from"))
    reason = _text(row.get("respecified_reason"))
    m = _ISSUE.search(reason or "")
    issue = f"#{m.group(1)}" if m else "unknown"
    # #4618 wrote the same trail when it withdrew an OPEN call as "not a forecast" (its reason says so).
    rid = f"{issue}:withdraw:not-a-forecast" if "recollection" in (reason or "") else f"{issue}:respecify"
    out = _base("respecified", "respecify" if rid.endswith(":respecify") else "withdraw", [rid], None, said_on)
    old_spec = old.get("evaluation") if isinstance(old.get("evaluation"), dict) else None
    status = _text(row.get("status"))
    graded = status in ("confirmed", "refuted", "inconclusive", "expired")
    out.update(
        reason=reason,
        original_status=_text(old.get("status")),  # the call was open when its target moved: never graded on the old one
        corrected_status=None if later_change else status,
        corrected_outcome_date=_day(row.get("outcome_date")) if graded and not later_change else None,
        target_before=due_of(old_spec) if old_spec is not None else None,
        target_after=due_of(row.get("evaluation") if isinstance(row.get("evaluation"), dict) else {}),
        corrected_at=_text(row.get("respecified_at")),
    )
    return _explained(out, [rid], where)


def history(row: dict, *, said_on: str | None, due_of: Callable[[dict], str | None]) -> list[dict]:
    """Every correction the row stores, oldest recorded first. Pure. ``due_of(spec)`` is the due-day
    derivation the ledger already serves (``site_api_ledger_export._due``), applied to a stored spec."""
    where = str(row.get("prediction_id") or row.get("sk") or "?")
    newer = [e for e in (row.get("corrections") or []) if isinstance(e, dict)]
    out: list[dict] = []
    vc = row.get("verdict_correction")
    if row.get("respecified_at"):
        out.append(from_respecified(row, said_on, due_of, bool(newer) or (isinstance(vc, dict) and bool(vc)), where))
    if isinstance(vc, dict) and vc:
        out.append(from_verdict_correction(vc, row, said_on, bool(newer), where))
    out.extend(from_corrections_entry(e, said_on, where) for e in newer)
    # Stable: a missing instant sorts first, so the order is the stored order when the clock is absent.
    return sorted(out, key=lambda e: str(e.get("corrected_at") or ""))
