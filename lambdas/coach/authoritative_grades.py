"""authoritative_grades.py — every coach-facing summary reads each call's CURRENT grade (owner ruling 2026-11-03).

THE RULING (verbatim): "Corrected authoritative grades must flow into coach-facing summaries and future narratives. A
coach must not continue claiming a prediction was wrong, right or measurable after its authoritative classification
has changed. However: Preserve original historical quotations verbatim. Add dated corrections rather than rewriting
what was originally said. Regenerate derived summaries from current authoritative records. Include provenance and an
as-of timestamp. Do not let generated narratives invent explanations for a correction."

WHERE THE STALE COPIES WERE. A grade correction (``coach.grade_corrections.apply_correction``) rewrites the
``PREDICTION#`` row (``status``, ``corrections[]``, ``original_grade``) and writes a ``CORRECTION#`` ledger row. It
never rewrites the ``LEARNING#`` row the first grade wrote, the ``CONFIDENCE#`` posterior, or any text already
generated from either. The generation inputs read the ``LEARNING#`` copy:

* ``coach_narrative_orchestrator._track_record_block`` — the brief's "Your Track Record";
* ``coach_history_summarizer._gather_learning`` — the compressed state AND the weekly stance's grounding;
* ``coach_memoir_lambda`` — the quarterly "what I got right / wrong".

Each now passes its ``LEARNING#`` rows through ``reconcile`` (the read-time #5626 pattern of
``web.trail_corrections``, applied where text is GENERATED): a row whose call's current status differs is served at
the current status, with ``grade_correction`` naming the original, the recorded instant and the registered reason
(``web.correction_rules`` through ``web.correction_history`` — never a second copy, never invented words).

READ-TIME STALENESS (``stale_corrections``). A stored derived text is stale when a correction that changed a verdict was
recorded after the text was built, on a call the text was built from (``derived_from.predictions``) — or on ANY call of
that coach when the text does not say which calls it was built from (every row written before this module). A stale
text is not served as current: the read site serves ``records_summary`` — a dated, deterministic sentence built from
the ``CORRECTION#`` rows — and the corrections themselves, and the text waits for its regeneration.

PROVENANCE (``derived_from``). Every derived text written from now on carries ``derived_from = {as_of, predictions,
records}``: when it was built and from which prediction rows. The name is deliberately not ``provenance``/``sources``:
the publication gate (a parallel change) stamps input SOURCE FAMILIES for privacy under its own key; the two coexist.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from coach import prediction_windows
from coach.verdict_claims import DECIDED

logger = logging.getLogger(__name__)

#: The status buckets the ledger serves (``web.site_api_ledger_export.BUCKETS`` reads this tuple).
BUCKETS = ("confirmed", "refuted", "pending", "inconclusive", "expired", "observational")

#: The verdict keys a LEARNING# row (and the summarizers' copies of it) carry a grade under.
_VERDICT_KEYS = ("status", "verdict", "outcome", "result")

_PROJECTION = (
    "sk, prediction_id, #st, evaluation, claim_natural, corrections, verdict_correction, respecified_at, "
    "respecified_from, respecified_reason, created_date, outcome_date, coach_id, classification_review"
)


def status_of(row: dict) -> str:
    """The served (authoritative) status of one PREDICTION# row — the ledger's own classification."""
    ev = row.get("evaluation") if isinstance(row.get("evaluation"), dict) else {}
    status = str(row.get("status") or "pending")
    if status == "observation" or (not prediction_windows.is_gradeable(ev) and status in ("pending", "confirming")):
        return "observational"
    return status if status in BUCKETS else "pending"


#: The prediction rows' sort-key prefix — READ here, never written (writers are pinned by tests/test_filing_rules_5607.py).
_PRED_PREFIX = "PREDICTION#"


def prediction_key(coach_id: str, pid: str) -> dict:
    """The GetItem key of one call's row."""
    return {"pk": f"COACH#{coach_id}", "sk": _PRED_PREFIX + pid}


def prediction_id_of(row: dict) -> str:
    return str(row.get("prediction_id") or str(row.get("sk") or "").replace("PREDICTION#", "", 1)).strip()


def corrections_of(row: dict) -> list[dict]:
    """Every correction the row stores, oldest recorded first, in the ledger's one served shape (#5610)."""
    from web import correction_history  # pure; the one served shape and the registered reasons

    return correction_history.history(row, said_on=str(row.get("created_date") or "")[:10] or None, due_of=lambda _spec: None)


def latest_verdict_correction(row: dict) -> dict | None:
    """The newest recorded correction that produced the row's current status (a verdict change), else None."""
    current = status_of(row)
    for c in reversed(corrections_of(row)):
        if c.get("original_status") != c.get("corrected_status") and c.get("corrected_status") in (current, row.get("status")):
            return c
    return None


def note_of(row: dict) -> dict | None:
    """``{prediction_id, claim, original_status, current_status, corrected_at, explanation}`` for a corrected call, else None."""
    c = latest_verdict_correction(row)
    if not c:
        return None
    return {
        "prediction_id": prediction_id_of(row),
        "claim": str(row.get("claim_natural") or "").strip(),
        "original_status": c.get("original_status"),
        "current_status": status_of(row),
        "corrected_at": c.get("corrected_at"),
        "explanation": c.get("explanation"),
    }


def prediction_rows(table: Any, coach_id: str, *, max_pages: int = 10) -> dict[str, dict]:
    """``{prediction_id: row}`` for one coach partition — one paginated, projected Query. Raises on a failed read."""
    from boto3.dynamodb.conditions import Key

    kwargs: dict = {
        "KeyConditionExpression": Key("pk").eq(f"COACH#{coach_id}") & Key("sk").begins_with("PREDICTION#"),
        "ProjectionExpression": _PROJECTION,
        "ExpressionAttributeNames": {"#st": "status"},
    }
    out: dict[str, dict] = {}
    for _ in range(max_pages):
        resp = table.query(**kwargs)
        for it in resp.get("Items", []):
            pid = prediction_id_of(it)
            if pid:
                out[pid] = it
        if not resp.get("LastEvaluatedKey"):
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return out


def calls_of(rows: dict[str, dict]) -> list[dict]:
    """The validator's view of a partition: ``[{prediction_id, claim, status}]`` at the authoritative status."""
    from coach import classification_review

    return [
        {
            "prediction_id": pid,
            "claim": str(r.get("claim_natural") or ""),
            # #5643: a verdict under classification review is disputed — "excluded from any claim that its outcome has
            # been reliably verified" (owner, 2026-11-03): a text calling it right or wrong contradicts it too.
            "status": "under_review" if classification_review.is_under_review(r) else status_of(r),
            "said_on": str(r.get("created_date") or "")[:10] or None,
        }
        for pid, r in rows.items()
    ]


def _record_status(rec: dict) -> str:
    for k in _VERDICT_KEYS:
        v = str(rec.get(k) or "").strip().lower()
        if v:
            return v
    return ""


def reconcile(records: Iterable[dict], rows: dict[str, dict] | None) -> tuple[list[dict], list[dict]]:
    """``(records, notes)`` — LEARNING#-shaped records read against their calls' current rows. Pure.

    A record tied to a prediction (``prediction_id``) whose row's status differs is returned as a NEW dict at the
    current status (every verdict key it carried), with ``grade_correction``; the input is never mutated. A record
    whose call no longer exists passes through. ``rows is None`` (the partition could not be read) drops every
    prediction-tied record: it cannot be checked, so it is not handed to a model as if it had been.
    ``notes`` = one ``note_of`` per distinct corrected call the records named.
    """
    out: list[dict] = []
    notes: dict[str, dict] = {}
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        pid = str(rec.get("prediction_id") or "").strip()
        if not pid or (rec.get("channel") or "data") == "conversation":
            out.append(rec)
            continue
        if rows is None:
            continue
        row = rows.get(pid)
        if not row:
            out.append(rec)
            continue
        current, original = status_of(row), _record_status(rec)
        if not original or current == original:
            out.append(rec)
            continue
        fixed = dict(rec)
        for k in _VERDICT_KEYS:
            if k in fixed or k == "status":
                fixed[k] = current
        n = note_of(row) or {"prediction_id": pid, "original_status": original, "current_status": current, "corrected_at": None}
        when = day_words(n.get("corrected_at")) or "a date not recorded"
        recorded = str(n.get("explanation") or "").strip() or "no reason recorded"
        fixed["reason"] = f"Re-graded on {when} from {original} to {current}. Recorded reason: {recorded}"
        fixed["grade_correction"] = {
            "original_reason": rec.get("reason"),
            "original_status": original,
            "current_status": current,
            "corrected_at": n.get("corrected_at"),
            "explanation": n.get("explanation"),
        }
        notes.setdefault(pid, {**n, "claim": n.get("claim") or str(row.get("claim_natural") or "")})
        out.append(fixed)
    return out, list(notes.values())


def reconcile_from_table(table: Any, coach_id: str, records: list[dict]) -> tuple[list[dict], list[dict], dict[str, dict] | None]:
    """``reconcile`` with the partition read here; a failed read drops the prediction-tied records (logged)."""
    try:
        rows = prediction_rows(table, coach_id)
    except Exception as e:  # noqa: BLE001 — generation inputs degrade, never break the run
        logger.warning("[authoritative_grades] %s: PREDICTION# read failed (%s) — graded records withheld from the prompt", coach_id, e)
        rows = None
    out, notes = reconcile(records, rows)
    return out, notes, rows


# ── read-time staleness ─────────────────────────────────────────────────────────────────────────────


def verdict_corrections(table: Any, coach_id: str, *, max_pages: int = 5) -> list[dict]:
    """The coach's ``CORRECTION#`` ledger rows that CHANGED a verdict, oldest first. Raises on a failed read."""
    from boto3.dynamodb.conditions import Key

    kwargs: dict = {"KeyConditionExpression": Key("pk").eq(f"COACH#{coach_id}") & Key("sk").begins_with("CORRECTION#")}
    out = []
    for _ in range(max_pages):
        resp = table.query(**kwargs)
        for it in resp.get("Items", []):
            if str(it.get("sk", "")).startswith("CORRECTION#SUMMARY#"):
                continue
            if it.get("original_status") == it.get("corrected_status") or not it.get("corrected_at"):
                continue  # a restate keeps the verdict: no text built on it is contradicted
            out.append(it)
        if not resp.get("LastEvaluatedKey"):
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return sorted(out, key=lambda r: str(r.get("corrected_at") or ""))


def _instant(value: Any) -> str:
    """An ISO instant normalised for comparison (``Z`` and ``+00:00`` alike; a bare day is its midnight)."""
    s = str(value or "").strip().replace("+00:00", "Z")
    if len(s) == 10:
        s += "T00:00:00Z"
    return s


def as_of_of(item: dict) -> str | None:
    """When a stored derived text was built: ``derived_from.as_of``, else ``created_at`` / ``generated_at``."""
    raw = item.get("derived_from")
    df: dict = raw if isinstance(raw, dict) else {}
    return df.get("as_of") or item.get("created_at") or item.get("generated_at") or None


def cited_of(item: dict) -> set[str] | None:
    """The prediction ids a stored text was built from, or None when it does not say (every pre-ruling row)."""
    raw = item.get("derived_from")
    df: dict = raw if isinstance(raw, dict) else {}
    preds = df.get("predictions")
    return {str(p) for p in preds} if isinstance(preds, list) else None


def stale_corrections(item: dict, corrections: list[dict]) -> list[dict]:
    """The verdict corrections recorded AFTER ``item`` was built on a call it rests on (any call, when unknown).

    A text with no recoverable build time is stale against every verdict correction (it cannot show it is newer).
    A text the writer flagged (``verdict_findings``) is stale outright — returned as a one-element marker list.
    """
    if item.get("verdict_findings"):
        return [{"prediction_id": None, "corrected_at": None, "flagged_at_write": True}]
    built = _instant(as_of_of(item))
    cited = cited_of(item)
    return [
        c
        for c in corrections
        if (not built or _instant(c.get("corrected_at")) > built) and (cited is None or str(c.get("prediction_id") or "") in cited)
    ]


_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")


def day_words(value: Any) -> str | None:
    s = str(value or "")[:10]
    try:
        y, m, d = int(s[:4]), int(s[5:7]), int(s[8:10])
        return f"{d} {_MONTHS[m - 1]} {y}"
    except (ValueError, IndexError):
        return None


#: What a stale read is replaced by on every public surface (owner review of #5644, 2026-11-03: "A concise explanation
#: such as 'This coach's earlier assessment is being updated following a prediction correction' would be preferable,
#: with the specific correction and dates available on demand"). The details ride ``summary_corrections``.
UPDATING_SENTENCE = "This coach's earlier assessment is being updated following a prediction correction."


def records_summary(item: dict, stale: list[dict]) -> str:
    """The sentence a stale read is replaced by — fixed, no model, no explanation invented. The specific corrections
    (dates, grades, registered explanation) are served beside it as ``correction_note`` entries, shown on demand."""
    return UPDATING_SENTENCE


# THE ONE SERVED SHAPE lives in the pure `coach.served_shape` (no boto3 — the publication snapshot imports it).
from coach.served_shape import (  # noqa: E402 — re-exported: every web read site reaches the shape through this module
    CORRECTION_NOTE_FIELDS,
    DERIVED_FROM_FIELDS,
    correction_note,
    instant,
    provenance,
    short_coach,
)


def registered_explanation(reason: str) -> str | None:
    """The registered reader words for a stored correction reason (``web.correction_rules``), or None — never improvised."""
    from web import correction_history, correction_rules

    try:
        return correction_rules.explain(correction_history.rule_ids_of_reason(str(reason or "")))
    except Exception:  # noqa: BLE001 — an unregistered rule has no reader words
        return None


def served_corrections(stale: list[dict], *, coach_id: str, public_ids: set[str] | None = None) -> list[dict]:
    """The corrections a stale read is replaced on account of (``correction_note`` shape). ``prediction_id`` only when
    the public ledger serves that call (``public_ids``); the explanation is the registered one, verbatim."""
    out = []
    for c in stale:
        if c.get("flagged_at_write"):
            continue
        pid = str(c.get("prediction_id") or "")
        out.append(
            correction_note(
                prediction_id=pid if (public_ids is not None and pid in public_ids) else None,
                coach_id=coach_id,
                original_status=c.get("original_status"),
                corrected_status=c.get("corrected_status"),
                corrected_at=c.get("corrected_at"),
                explanation=registered_explanation(str(c.get("reason") or "")),
            )
        )
    return out


def derived_from(as_of: str, predictions: Iterable[str], records: Iterable[str] = ()) -> dict:
    """The provenance stamp a derived text is written with: when it was built and from which records."""
    return {
        "as_of": as_of,
        "predictions": sorted({str(p) for p in predictions if p}),
        "records": sorted({str(r) for r in records if r}),
    }


__all__ = [
    "BUCKETS",
    "CORRECTION_NOTE_FIELDS",
    "DERIVED_FROM_FIELDS",
    "UPDATING_SENTENCE",
    "correction_note",
    "instant",
    "provenance",
    "registered_explanation",
    "short_coach",
    "DECIDED",
    "as_of_of",
    "calls_of",
    "cited_of",
    "derived_from",
    "note_of",
    "prediction_rows",
    "reconcile",
    "reconcile_from_table",
    "records_summary",
    "served_corrections",
    "stale_corrections",
    "status_of",
    "verdict_corrections",
]
