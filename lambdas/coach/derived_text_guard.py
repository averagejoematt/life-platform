"""derived_text_guard.py — the OUTPUT# write's verdict check and provenance stamp (owner ruling 2026-11-03).

``coach_state_updater._write_output_record`` calls ``guard_output_item`` on the item it is about to write (the module
sits at the #1665 size ratchet, so the substance lives here — the #2221 shape). Two things happen:

1. **The verdict check.** The coach's PREDICTION# partition is read once and every call is put at its authoritative
   (post-correction) status (``coach.authoritative_grades``). ``coach.verdict_claims.findings`` then reads the derived
   reader prose (``coach_derived_prose.DERIVED_PROSE_FIELDS``) and the narrative itself:

   * a derived field that calls a call right / wrong / checked against its current grade HOLDS the derived set (the
     #2418 hold) and puts a deterministic, records-built ``public_summary`` in its place — the coach's prose is not
     rewritten by a model and no explanation is invented;
   * a narrative (``content``) that does the same is kept as written (it is the coach's dated words) and the row is
     stamped ``verdict_findings`` — every read site treats such a row as stale (``authoritative_grades.stale_corrections``)
     and serves the dated records summary instead.

2. **The stamp.** ``derived_from = {as_of, predictions, records}`` — when the text was built and the prediction rows it
   was built from (the orchestrator's brief for the day names them: ``derived_from_predictions``). No brief → the
   ``predictions`` key is absent and the read-time rule treats the text as built from every call of the coach.

A partition that cannot be read leaves the item unchecked (``verdict_check: "unavailable"``, logged); the read-time
staleness rule still applies to it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from coach import authoritative_grades, coach_derived_prose
from coach.verdict_claims import findings as _findings

logger = logging.getLogger(__name__)


def _brief_predictions(table: Any, coach_id: str, date: str) -> list[str] | None:
    from experiment.phase_filter import singleton_visible  # ADR-058/#946: a tombstoned brief names no calls

    try:
        it = table.get_item(Key={"pk": f"COACH#{coach_id}", "sk": f"BRIEF#{date}"}).get("Item") or {}
    except Exception as e:  # noqa: BLE001
        logger.warning("[derived_text_guard] %s: BRIEF#%s unreadable (%s)", coach_id, date, e)
        return None
    if not singleton_visible(it):
        return None
    preds = (it.get("brief") or {}).get("derived_from_predictions") if isinstance(it.get("brief"), dict) else None
    return [str(p) for p in preds] if isinstance(preds, list) else None


def guard_output_item(item: dict, table: Any, coach_id: str, date: str, *, cited: list[str] | None = None, now: str | None = None) -> dict:
    """Check and stamp one OUTPUT# item in place; returns it. Never raises."""
    as_of = now or datetime.now(timezone.utc).isoformat()
    try:
        cited = cited if cited is not None else _brief_predictions(table, coach_id, date)
        stamp = authoritative_grades.derived_from(as_of, cited or [], [f"COACH#{coach_id}/BRIEF#{date}"] if cited is not None else [])
        if cited is None:
            stamp.pop("predictions")  # unknown — the read-time rule then covers every call of the coach
        item["derived_from"] = stamp
        try:
            rows = authoritative_grades.prediction_rows(table, coach_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("[derived_text_guard] %s: PREDICTION# read failed (%s) — verdict check unavailable", coach_id, e)
            item["verdict_check"] = "unavailable"
            return item
        calls = authoritative_grades.calls_of(rows)
        derived = coach_derived_prose.prose_blob(item)
        derived_hits = _findings(derived, calls) if derived else []
        content_hits = _findings(str(item.get("content") or ""), calls)
        item["verdict_check"] = "checked"
        if derived_hits:
            logger.warning(
                "[derived_text_guard] %s: derived prose contradicts %d current grade(s) %s — held, records summary served",
                coach_id,
                len(derived_hits),
                [h.get("prediction_id") for h in derived_hits][:3],
            )
            for field in coach_derived_prose.DERIVED_PROSE_FIELDS:
                item[field] = None
            item["derived_prose_held"] = True
            item["public_summary"] = authoritative_grades.records_summary(item, [{"flagged_at_write": True}])
            item["public_summary_basis"] = "records"
        if content_hits or derived_hits:
            item["verdict_findings"] = [
                {"prediction_id": h.get("prediction_id"), "asserted": h.get("asserted"), "status": h.get("status")}
                for h in (content_hits + derived_hits)
            ][:10]
    except Exception as e:  # noqa: BLE001 — a guard failure never costs the record
        logger.warning("[derived_text_guard] %s: guard failed (%s)", coach_id, e)
        item.setdefault("verdict_check", "unavailable")
    return item
