"""verification_record.py — an auditable, APPEND-ONLY verification record per graded call (owner 2026-11-09).

THE SPEC (owner, verbatim). "Implement an auditable verification record containing: Prediction ID and original
wording/criteria version. Original verdict and current verdict. Grading ruleset version. Evidence sources and their
availability. Verification timestamp. Whether the verdict was independently reproduced, corrected or could not be
verified. The stamp must distinguish an unchanged verdict from a genuinely validated classification. ... Do not rewrite
historical timestamps or imply the calls were verified when originally graded."

THE ROW. One ``put_item`` per verification, never overwritten (``attribute_not_exists(sk)``), on the call's own
partition — the ``CORRECTION#`` / ``CLASSREVIEW#`` audit pattern (``coach.grade_corrections``,
``coach.classification_review``)::

    pk = COACH#<coach_id>     sk = VERIFY#<prediction_id>#<verified_at ISO>

    {prediction_id, prediction_sk, coach_id, record_type: "verification", schema_version,
     claim_hash,                 # sha256 of the stored words (the words stay on the PREDICTION# row; never copied)
     criteria_hash,              # sha256 of the frozen evaluation spec, canonical JSON
     criteria_version,           # the filing rules version the spec was filed under, when stored (else null)
     original_status, original_outcome_date,   # the FIRST grade (``original_grade`` when the row was corrected)
     current_status, current_outcome_date,     # the grade as it stands — both copied, never rewritten
     ruleset_version,            # the evaluator version the re-run used (``grading_quality.EVALUATOR_VERSION``)
     grade_text_version,         # the version that WROTE the stored grade text (``outcome_notes.algo_version``)
     rerun_status, rerun_reason, # what the current evaluator says now, from the frozen spec and the stored readings
     classification: {value, approved, ruling_ref},   # the owner's classification ruling, when one exists
     evidence: [{source, metric, dates: {from, to, with_readings: [...]}, available: bool}],
     verified_at,                # this record's instant — never the original grading day
     outcome,                    # reproduced | corrected | could_not_verify
     outcome_reason,
     verdict_unchanged,          # current_status == original_status — a FACT about the history ...
     classification_validated}   # ... kept apart from this: True only when an owner classification ruling exists
                                 # AND the verdict was reproduced/corrected AND the call is not under review

THE OUTCOME (re-run = the current evaluator, pure, over the frozen spec and the readings in the table):

  * ``reproduced``       the re-run gives the stored verdict, and the stored verdict is the first one;
  * ``corrected``        the re-run gives the stored verdict, and the stored verdict is a recorded correction of
                         the first one (``grade_corrections``) — the correction is what was reproduced;
  * ``could_not_verify`` no re-run grade (held, not gradeable, a docket bet, an evaluator error) or a re-run that
                         disagrees with the stored verdict. A disagreement is NOT written as a new verdict: changing a
                         grade is ``grade_corrections.apply_correction``'s, on its own ruling.

THE POINTER. The PREDICTION# row gains at most ONE attribute, ``latest_verification`` = ``{sk, outcome, verified_at,
ruleset_version, classification_validated}`` — written conditionally (the row exists, its status is still the one the
record was computed against, and no NEWER verification already points there). Nothing else on the row is touched:
not ``status`` / ``outcome`` / ``outcome_date`` / ``outcome_notes``, not any original timestamp.

ONE WRITER. ``write_verification`` is the only function that writes a ``VERIFY#`` row or the pointer
(``tests/test_settled_grade_writers_5613.py`` sweeps the repo for any other). ``scripts/record_verification.py``
plans with ``plan_writes`` and is dry-run by default.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Iterable

from common.numeric import floats_to_decimal
from common.pacific_time import shift_day_key
from experiment.measurable_metrics import METRIC_SOURCES, base_metric
from experiment.phase_taxonomy import experiment_stamp_for

from coach import classification_review, grade_corrections, repeat_family
from coach.grading_quality import window_end
from coach.prediction_point_grader import POINT_GRACE_DAYS
from coach.prediction_windows import effective_window_days

VERIFY_PREFIX = "VERIFY#"
POINTER_ATTR = "latest_verification"
SCHEMA_VERSION = 1
RECORD_TYPE = "verification"

REPRODUCED, CORRECTED, COULD_NOT_VERIFY = "reproduced", "corrected", "could_not_verify"
OUTCOMES = (REPRODUCED, CORRECTED, COULD_NOT_VERIFY)
#: The outcomes under which a verdict counts as verified (the re-run gave the stored verdict).
VERIFIED_OUTCOMES = (REPRODUCED, CORRECTED)

#: The pointer's fields — and exactly the ``verification`` object a public item serves.
POINTER_FIELDS = ("sk", "outcome", "verified_at", "ruleset_version", "classification_validated")
SERVED_FIELDS = ("outcome", "verified_at", "ruleset_version", "classification_validated")

#: How many dated readings an evidence entry lists (a 30-day aggregate is the longest window a point call reads).
MAX_EVIDENCE_DAYS = 62


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def claim_hash(row: dict) -> str | None:
    """sha256 of the stored words — the record names them without copying them."""
    words = str((row or {}).get("claim_natural") or "").strip()
    return _sha(words) if words else None


def criteria_hash(row: dict) -> str | None:
    """sha256 of the frozen evaluation spec as canonical JSON (sorted keys; a Decimal and a float of one value agree)."""
    spec = (row or {}).get("evaluation")
    if not isinstance(spec, dict) or not spec:
        return None

    def _norm(v: Any) -> Any:
        if isinstance(v, dict):
            return {str(k): _norm(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [_norm(x) for x in v]
        if isinstance(v, bool) or v is None or isinstance(v, str):
            return v
        try:
            f = float(v)
        except (TypeError, ValueError):
            return str(v)
        return int(f) if f.is_integer() else f

    return _sha(json.dumps(_norm(spec), sort_keys=True, separators=(",", ":")))


def criteria_version(row: dict) -> str | None:
    """The filing rules version the call was filed under (``filing.filing_rules_version``), when the row stores one."""
    filing = (row or {}).get("filing")
    v = filing.get("filing_rules_version") if isinstance(filing, dict) else None
    return str(v) if v is not None else None


def original_verdict(row: dict) -> dict:
    """The FIRST grade: ``original_grade`` when the row was ever corrected, else the row as it stands."""
    og = row.get("original_grade") if grade_corrections.has_correction_history(row) else None
    src = og if isinstance(og, dict) and og else row
    return {"status": src.get("status"), "outcome_date": src.get("outcome_date")}


def classification_of(entry: dict | None, row: dict | None = None) -> dict:
    """The owner's classification for this call, from a verification manifest entry. Only an APPROVED value with a
    ruling reference is a ruling; a proposed value is recorded as proposed and validates nothing.

    ``family`` (owner ruling 2026-11-09, B): the call's repeat family — the ``repeat_family`` marker stored on the row
    (``coach.repeat_family``), which the entry may restate but never contradict (``ValueError``). An entry naming a
    family the row does not carry is refused too: the family is the row's stored record, not the manifest's say-so."""
    entry = entry or {}
    approved = entry.get("approved_classification")
    ruling_ref = str(entry.get("classification_ruling_ref") or "").strip() or None
    if approved and ruling_ref:
        out = {"value": str(approved), "approved": True, "ruling_ref": ruling_ref}
    else:
        proposed = entry.get("proposed_classification")
        out = {"value": str(proposed) if proposed else None, "approved": False, "ruling_ref": None}
    marker = (row or {}).get(repeat_family.ATTR) if row is not None else None
    stored = str(marker.get("family_id") or "").strip() if isinstance(marker, dict) else ""
    named = str(entry.get("family") or "").strip()
    if named and named != stored:
        raise ValueError(f"the entry names family {named!r} but the row carries {stored or 'no family marker'!r}")
    if stored:
        out["family"] = stored
    return out


def outcome_of(row: dict, rerun: dict | None) -> tuple[str, str]:
    """``(outcome, why)`` — see the module docstring. ``rerun`` is the evaluator's evaluation dict, or None."""
    current = str(row.get("status") or "")
    if rerun is None:
        return COULD_NOT_VERIFY, "the current evaluator produced no grade for this call"
    got = str(rerun.get("status") or "")
    if got != current:
        return COULD_NOT_VERIFY, f"the re-run gives {got!r}, not the stored {current!r}; the stored verdict is not reproduced"
    if original_verdict(row)["status"] != current:
        return CORRECTED, "the re-run reproduces the recorded correction of the first grade"
    return REPRODUCED, "the re-run reproduces the stored verdict"


def evidence_window(row: dict, rerun: dict | None, today: str) -> tuple[str, str] | None:
    """``(from, to)``: the days the verdict reads — the re-run's own window when it reports one, a number call's
    target day and its grace days after filing, else filing → the stated window's end."""

    win = (rerun or {}).get("window")
    if isinstance(win, dict) and win.get("start") and win.get("end"):
        return str(win["start"])[:10], str(win["end"])[:10]
    raw_spec = row.get("evaluation")
    spec: dict = raw_spec if isinstance(raw_spec, dict) else {}
    created = str(row.get("created_date") or "")[:10]
    if not created:
        return None
    end = window_end(row, spec, spec.get("evaluation_window_days") or effective_window_days(spec, row.get("subdomain") or ""), today)
    if not end:
        return None
    if spec.get("type") == "point" and spec.get("target_date"):
        start = max(shift_day_key(end, -POINT_GRACE_DAYS), shift_day_key(created, 1))
        return start, end
    return created, end


def _metrics(spec: Any) -> list[str]:
    out: list[str] = []
    if isinstance(spec, dict):
        for k, v in spec.items():
            if k == "metric" and isinstance(v, str) and v.strip():
                out.append(v.strip())
            elif isinstance(v, (dict, list, tuple)):
                out.extend(_metrics(v))
    elif isinstance(spec, (list, tuple)):
        for v in spec:
            out.extend(_metrics(v))
    return list(dict.fromkeys(out))


def evidence(row: dict, rerun: dict | None, today: str, series: Callable[[str, str, str, str], Iterable[tuple]]) -> list[dict]:
    """One entry per metric the frozen spec names: its source, the days the verdict reads and whether readings exist
    there. ``series(source, base_metric, from, to)`` is the evaluator's own read (injected; dry-run is read-only)."""
    window = evidence_window(row, rerun, today)
    out: list[dict[str, Any]] = []
    for metric in _metrics(row.get("evaluation")):
        base = base_metric(metric)
        source = METRIC_SOURCES.get(base)
        if not source or window is None:
            out.append({"source": source, "metric": metric, "dates": None, "available": False})
            continue
        lo, hi = window
        try:
            days = sorted({str(d)[:10] for d, _v in series(source, base, lo, hi) if lo <= str(d)[:10] <= hi})
        except Exception:  # noqa: BLE001 — a failed read is "not available", said so, never a crash
            days = []
        out.append(
            {
                "source": source,
                "metric": metric,
                "dates": {"from": lo, "to": hi, "with_readings": days[-MAX_EVIDENCE_DAYS:]},
                "available": bool(days),
            }
        )
    return out


def build_record(
    row: dict,
    rerun: dict | None,
    *,
    evidence_entries: list[dict],
    classification: dict,
    ruleset_version: str,
    verified_at: str,
) -> dict:
    """The VERIFY# row for one call — pure."""
    pk = str(row["pk"])
    pid = grade_corrections.prediction_id(row)
    sk = f"{VERIFY_PREFIX}{pid}#{verified_at}"
    outcome, why = outcome_of(row, rerun)
    original = original_verdict(row)
    under_review = classification_review.is_under_review(row)
    validated = bool(classification.get("approved") and classification.get("ruling_ref")) and outcome in VERIFIED_OUTCOMES
    return {
        **experiment_stamp_for(pk, sk),
        "pk": pk,
        "sk": sk,
        "record_type": RECORD_TYPE,
        "schema_version": SCHEMA_VERSION,
        "prediction_id": pid,
        "prediction_sk": row.get("sk"),
        "coach_id": row.get("coach_id") or pk.replace("COACH#", "", 1),
        "claim_hash": claim_hash(row),
        "criteria_hash": criteria_hash(row),
        "criteria_version": criteria_version(row),
        "original_status": original["status"],
        "original_outcome_date": original["outcome_date"],
        "current_status": row.get("status"),
        "current_outcome_date": row.get("outcome_date"),
        "ruleset_version": str(ruleset_version),
        "grade_text_version": grade_corrections.grade_text_version(row),
        "rerun_status": (rerun or {}).get("status"),
        "rerun_reason": (rerun or {}).get("reason"),
        "classification": dict(classification),
        "under_classification_review": under_review,
        "evidence": list(evidence_entries),
        "verified_at": verified_at,
        "outcome": outcome,
        "outcome_reason": why,
        "verdict_unchanged": original["status"] == row.get("status"),
        "classification_validated": bool(validated and not under_review),
    }


def pointer_of(record: dict) -> dict:
    return {k: record.get(k) for k in POINTER_FIELDS}


def plan_writes(row: dict, record: dict) -> list[dict]:
    """``[put_item, update_item]`` kwargs for one record — the audit row first, then the pointer. Pure."""
    put = {"Item": floats_to_decimal(record), "ConditionExpression": "attribute_not_exists(sk)"}
    update = {
        "Key": {"pk": row["pk"], "sk": row["sk"]},
        "UpdateExpression": f"SET {POINTER_ATTR} = :lv",
        "ConditionExpression": (
            f"attribute_exists(sk) AND #s IN (:status) AND (attribute_not_exists({POINTER_ATTR}) OR {POINTER_ATTR}.sk < :sk)"
        ),
        "ExpressionAttributeNames": {"#s": "status"},
        "ExpressionAttributeValues": floats_to_decimal({":lv": pointer_of(record), ":status": row.get("status"), ":sk": record["sk"]}),
    }
    return [{"op": "put_item", "kwargs": put}, {"op": "update_item", "kwargs": update}]


def write_verification(table: Any, row: dict, record: dict) -> dict:
    """THE ONE WRITER of a ``VERIFY#`` row and of ``latest_verification``: the append-only audit row first, then the
    conditional pointer. Returns the pointer written. A failure between the two leaves a visible audit row and the
    older pointer — the record is never lost, the row's grade never touched."""
    if not str(record.get("sk") or "").startswith(VERIFY_PREFIX) or record.get("pk") != row.get("pk"):
        raise ValueError("a verification record lives on its call's own partition under VERIFY#")
    put, update = plan_writes(row, record)
    table.put_item(**put["kwargs"])
    table.update_item(**update["kwargs"])
    return pointer_of(record)


# ── the read side (public items) ───────────────────────────────────────────────────────────────


def served(row: dict) -> dict | None:
    """The ``verification`` object a public item carries — read off ``latest_verification`` and nothing else. None when
    the call has no verification record: a version number is never read as a verification."""
    lv = (row or {}).get(POINTER_ATTR)
    if not isinstance(lv, dict) or lv.get("outcome") not in OUTCOMES:
        return None
    return {
        "outcome": lv.get("outcome"),
        "verified_at": lv.get("verified_at"),
        "ruleset_version": None if lv.get("ruleset_version") is None else str(lv.get("ruleset_version")),
        "classification_validated": bool(lv.get("classification_validated")),
    }


def is_verified(row: dict) -> bool:
    v = served(row)
    return v is not None and v["outcome"] in VERIFIED_OUTCOMES
