"""served_shape.py — THE ONE served shape for as-of instants and source-call references (owner review of #5644).

Owner, 2026-11-03: "Keep the as-of timestamps and source-call references. Ensure they remain consistent across coach
pages, Day pages and public APIs." Every coach surface that serves a correction beside a summary or a quotation —
/api/coaching-dashboard, /api/coach_analysis, /api/coach/<id> and the v9 Day snapshot — builds it here. Pure: no boto3,
no network (``scripts/publish_snapshot_corrections.py`` imports it in a job with no AWS dependencies).
"""

from __future__ import annotations

from typing import Any

#: One correction beside a summary or a quotation — /api/coaching-dashboard ``summary_corrections``, /api/coach_analysis
#: ``summary_corrections``, /api/coach/<id> ``stance.summary_corrections`` / ``*.grade_corrections``, and the Day
#: snapshot's ``coach_lines[].grade_corrections``. ``prediction_id`` + ``coach_id`` are the source-call reference
#: (null when the public ledger does not serve the call); every instant is ``instant()``-formatted.
CORRECTION_NOTE_FIELDS = ("prediction_id", "coach_id", "original_status", "corrected_status", "corrected_at", "explanation")
#: ``derived_from`` on every judged summary.
DERIVED_FROM_FIELDS = ("built_from", "as_of", "superseded_read_as_of", "predictions", "predictions_not_public")


def instant(value: Any) -> str | None:
    """THE served form of an as-of or correction time: ``YYYY-MM-DDTHH:MM:SSZ`` (UTC, whole seconds); a stored bare
    day stays a bare ``YYYY-MM-DD`` (no time is invented); anything unparseable is None."""
    from common.pacific_time import parse_day_key, parse_iso_utc

    s = str(value or "").strip()
    if not s:
        return None
    if len(s) == 10:
        return s if parse_day_key(s) else None
    dt = parse_iso_utc(s)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def short_coach(coach_id: Any) -> str | None:
    c = str(coach_id or "").strip()
    return (c[: -len("_coach")] if c.endswith("_coach") else c) or None


def correction_note(*, prediction_id, coach_id, original_status, corrected_status, corrected_at, explanation) -> dict:
    """One correction in the one served shape (``CORRECTION_NOTE_FIELDS``)."""
    pid = str(prediction_id or "").strip() or None
    return {
        "prediction_id": pid,
        "coach_id": short_coach(coach_id) if pid else None,
        "original_status": original_status or None,
        "corrected_status": corrected_status or None,
        "corrected_at": instant(corrected_at),
        "explanation": explanation or None,
    }


def provenance(
    *, built_from: str, as_of: Any, predictions: list[str] | None, not_public: int | None, superseded_read_as_of: Any = None
) -> dict:
    """``derived_from`` in the one served shape (``DERIVED_FROM_FIELDS``)."""
    return {
        "built_from": built_from,
        "as_of": instant(as_of),
        "superseded_read_as_of": instant(superseded_read_as_of),
        "predictions": sorted(predictions) if predictions is not None else None,
        "predictions_not_public": not_public,
    }
