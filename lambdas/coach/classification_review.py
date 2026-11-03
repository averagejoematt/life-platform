"""classification_review.py — a SETTLED grade flagged as disputed, pending classification (owner ruling 2026-11-03).

THE RULING (verbatim). "Glucose 09-15: Yes, add it to classification review immediately. A recovery score is not an
acceptable substitute for measured nocturnal glucose or cortisol unless that proxy was explicitly established in the
original frozen criteria. Preserve the existing verdict in the audit history, but flag it as disputed pending
classification. Do not silently re-grade it."

THE SHAPE. A row under review carries one map attribute, ``classification_review``::

    {"reason": str, "set_at": ISO-8601, "set_by": "owner", "ruling_ref": str, "verdict": <status at review>, "issue"?: str}

It is written and removed ONLY by ``scripts/classification_review.py`` (an audit row
``CLASSREVIEW#{prediction_id}#{ISO}`` first — carrying the verdict as it stood — then a conditional update that touches
nothing but this attribute, and only on a SETTLED row: ``grade_corrections.is_settled``). ``status`` / ``outcome`` /
``outcome_date`` / ``outcome_notes`` / ``evaluation`` / ``claim_natural`` are never touched: the verdict is preserved,
not re-graded.

``reason`` is SERVED (``/api/ledger_export`` ``classification_review_reason``): it is written for a public reader —
no private detail, no quotation of the claim. A row whose claim words are held serves ``DEFAULT_READER_REASON``.

WHAT REVIEW DOES TO GRADE WRITERS (the #5613 settled-grade guard, extended). While the flag is present no automated
path changes the grade:

  * ``grade_corrections.write_first_grade`` (the scheduled evaluator) refuses the row and is conditional on
    ``attribute_not_exists(classification_review)``;
  * ``grade_corrections.apply_correction`` refuses every basis but ``ruling`` (``regrade`` / ``restate`` /
    ``first_grade`` — the re-grade scripts' bases) and is conditional on the flag's absence for those bases;
  * ``grade_corrections.revert_correction`` (``deploy/revert_regrade.py``) refuses the row, conditionally too;
  * ``deploy/regrade_predictions.py`` and ``deploy/revert_regrade.py`` do not select it.

An OWNER RULING is what review waits for: ``apply_correction(..., basis="ruling", ruled_by=...)`` is allowed, and it
RESOLVES the review — a ``CLASSREVIEW#`` audit row (``action: "resolved"``) first, the correction entry carries
``resolves_classification_review`` (the review map), and the same conditional update REMOVEs the flag.

COUNTING (owner ruling 2026-11-03, verbatim: "Keep the original verdict preserved but explicitly disputed and excluded
from any claim that its outcome has been reliably verified, pending classification."). While under review the row is
OUT of every verified aggregate — K of N, accuracy, Brier / calibration, the simple-guess comparison, the quality and
class counts — and DISCLOSED beside them as ``under_review: N``. Its stored status is untouched (still the verdict it
was graded with), and it stays listed on the ledger, shown as disputed. Two chokepoints carry the exclusion:
``coach.coach_record.decided_rows`` (the record's row-set: every K of N, comparison and quality block is taken over
it) and ``experiment.calibration_core.pairs_from_prediction_records`` (every Brier / calibration input). The
per-status tallies that do not go through ``decided_rows`` (``/api/predictions`` buckets, ``record_bodies``) read
``is_under_review`` themselves. Releasing the review (or a ruling resolving it) restores normal counting on the next
read of the rows (no count is stored; a served response is cached only for its own TTL).
"""

from __future__ import annotations

ATTR = "classification_review"
AUDIT_SK_PREFIX = "CLASSREVIEW#"
DEFAULT_READER_REASON = "Disputed: the owner has put this verdict under classification review. The verdict is kept as graded."


class ClassificationReviewError(RuntimeError):
    """An automated grade write onto a row whose settled verdict is under classification review."""


def review_of(row: dict) -> dict | None:
    """The row's review map, or None. Any truthy value counts — a malformed flag fails CLOSED (still under review)."""
    if not isinstance(row, dict):
        return None
    r = row.get(ATTR)
    if not r:
        return None
    return r if isinstance(r, dict) else {"reason": str(r)}


def is_under_review(row: dict) -> bool:
    return review_of(row) is not None


def review_reason(row: dict) -> str:
    """The stored (public) reason, or a plain default."""
    r = review_of(row) or {}
    return str(r.get("reason") or "").strip() or DEFAULT_READER_REASON


def served_fields(row: dict, *, words_held: bool = False) -> dict:
    """What a public item carries when its verdict is under review: the flag and the public reason — or the plain
    default when the row's claim words are held (a stored reason must never travel where the words may not)."""
    return {"classification_review": True, "classification_review_reason": DEFAULT_READER_REASON if words_held else review_reason(row)}


def refuse_automated(row: dict, what: str) -> None:
    """Raise ``ClassificationReviewError`` when ``row`` is under review — for every automated grade writer."""
    if is_under_review(row):
        raise ClassificationReviewError(
            f"{row.get('pk')} / {row.get('sk')} is under classification review ({review_reason(row)}): "
            f"{what} may not change it — only an owner ruling (apply_correction basis='ruling') resolves it"
        )
