"""derived_summary_freshness.py — a stored coach summary is served as current only if no correction overtook it (owner ruling 2026-11-03).

THE DEFECT. ``/api/coaching-dashboard`` served the mind coach's read of 2 November ("the mechanism was wrong") after the
call it judged was re-graded on 3 November from refuted to could-not-be-checked (rule #5611:m). The text was right
about the grade it was written from; it was served as if that grade still stood.

THE RULE (``coach.authoritative_grades.stale_corrections``). A stored derived text (an OUTPUT# row's ``public_summary``,
the read behind ``position_summary``; the coach page's summary; the coach-analysis narrative) is STALE when a
correction that changed a verdict was recorded after the text was built, on a call it was built from — or on any call
of the coach when the text does not name its calls (every row written before this ruling) — or when its writer flagged
it (``verdict_findings``). A stale text is not served as current: the slot serves the dated, deterministic records
summary (``authoritative_grades.records_summary``), and the corrections it is replaced on account of are served beside
it with their registered explanations. The stored text itself is never rewritten; it waits for its regeneration.

PROVENANCE ON THE WIRE (owner, 2026-11-03: "ensure the provenance and as-of timestamps are available to the reader
where useful, not merely stored internally"). Every judged slot serves:

    summary_state        "current" | "superseded_by_correction" | "unverified"
    summary_as_of        when the served text was built (the stored text's build time; the request time for a records summary)
    derived_from         {built_from: "coach_read" | "ledger_records", as_of, predictions: [ids the public ledger serves] | null,
                          predictions_not_public: n}
    summary_corrections  [{prediction_id | null, original_status, corrected_status, corrected_at, explanation}]

``derived_from`` is this ruling's key; the privacy publication gate's source-family stamp is a different key.

A failed CORRECTION# read cannot show the text is current, so the text is withheld (``unverified``, empty) — the #5626
rule: unchecked is never served as checked.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from coach import authoritative_grades

from web.site_api_common import logger


def _public_ids(table: Any, coach_id: str, pids: list[str]) -> set[str]:
    """The ids among ``pids`` the public ledger serves (``trail_corrections.ledger_withholds`` — the #5131 scrub)."""
    from web import trail_corrections

    out = set()
    for pid in dict.fromkeys(p for p in pids if p):
        try:
            row = table.get_item(Key=authoritative_grades.prediction_key(coach_id, pid)).get("Item")
        except Exception as e:  # noqa: BLE001 — unread → not named
            logger.warning(f"[derived_summary_freshness] {coach_id}/{pid}: {e}")
            continue
        if row and not trail_corrections.ledger_withholds(coach_id, row):
            out.add(pid)
    return out


def judge(
    table: Any, coach_id: str, item: dict, served_text: str, *, corrections: list[dict] | None = None, now: str | None = None
) -> dict:
    """The served fields for one stored derived text. ``served_text`` is what the slot would serve if current.

    Every instant and every source-call reference is in the one served shape (``authoritative_grades.provenance`` /
    ``correction_note`` / ``instant``) — the same on the dashboard, the coach pages, coach_analysis and the Day pages.
    """
    now = now or datetime.now(timezone.utc).isoformat()
    as_of = authoritative_grades.as_of_of(item or {})
    cited = authoritative_grades.cited_of(item or {})
    if corrections is None:
        try:
            corrections = authoritative_grades.verdict_corrections(table, coach_id)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[derived_summary_freshness] {coach_id}: CORRECTION# read failed ({e}) — summary withheld")
            return {"text": "", "summary_state": "unverified", "summary_as_of": None, "derived_from": None, "summary_corrections": []}
    stale = authoritative_grades.stale_corrections(item or {}, corrections)
    if not stale:
        public = _public_ids(table, coach_id, sorted(cited)) if cited else set()
        return {
            "text": served_text,
            "summary_state": "current",
            "summary_as_of": authoritative_grades.instant(as_of),
            "derived_from": authoritative_grades.provenance(
                built_from="coach_read",
                as_of=as_of,
                predictions=sorted(public) if cited is not None else None,
                not_public=(len(cited) - len(public)) if cited is not None else None,
            ),
            "summary_corrections": [],
        }
    pids = [str(c.get("prediction_id") or "") for c in stale if c.get("prediction_id")]
    public = _public_ids(table, coach_id, pids)
    return {
        "text": authoritative_grades.records_summary(item or {}, stale),
        "summary_state": "superseded_by_correction",
        "summary_as_of": authoritative_grades.instant(now),
        "derived_from": authoritative_grades.provenance(
            built_from="ledger_records",
            as_of=now,
            predictions=sorted(public),
            not_public=len(set(pids) - public),
            superseded_read_as_of=as_of,
        ),
        "summary_corrections": authoritative_grades.served_corrections(stale, coach_id=coach_id, public_ids=public),
    }


def apply_to_entry(entry: dict, table: Any, coach_id: str, item: dict, text: str | None = None, text_key: str = "position_summary") -> dict:
    """Judge ``text`` (default ``entry[text_key]``; built from ``item``) into ``entry[text_key]`` in place: the served
    text, plus the provenance fields."""
    j = judge(table, coach_id, item, str((entry.get(text_key) if text is None else text) or ""))
    entry[text_key] = j.pop("text")
    entry.update(j)
    return entry


def apply_to_analysis(resp: dict, table: Any, coach_id: str, output: dict) -> dict:
    """``/api/coach_analysis``: the coach's latest read, judged. A superseded read serves the records summary in BOTH
    prose slots (``analysis``, ``public_read``) and drops the read's derived lines (``elena_quote``); the ask stays."""
    j = judge(table, coach_id, output, str(resp.get("analysis") or ""))
    text = j.pop("text")
    if j["summary_state"] != "current":
        resp["analysis"] = text or None
        resp["public_read"] = text or None
        resp["elena_quote"] = None
    resp.update(j)
    return resp


def annotate_timeline(entries: list[dict], table: Any, coach_id: str, text_keys: tuple[str, ...] = ("summary",)) -> list[dict]:
    """The coach page's dated timeline of past reads: historical record, never rewritten (owner, 2026-11-03).

    An entry whose words call a call right / wrong / checked against its CURRENT grade keeps its words and gains
    ``grade_corrections`` — the dated, recorded correction of that call (registered explanation; ``prediction_id`` only
    when the public ledger serves it). Nothing is withheld here: a dated quote is what was said that day.
    """
    from coach.verdict_claims import findings

    try:
        rows = authoritative_grades.prediction_rows(table, coach_id)
    except Exception as exc:  # noqa: BLE001 — unannotated, as before; logged
        logger.warning(f"[derived_summary_freshness] {coach_id}: timeline not checked ({exc})")
        return entries
    calls = authoritative_grades.calls_of(rows)
    for e in entries:
        if not isinstance(e, dict):
            continue
        day = str(e.get("date") or e.get("as_of") or "")[:10] or None
        hits = findings(" ".join(str(e.get(k) or "") for k in text_keys), calls, as_of=day)
        notes = []
        for h in hits:
            row = rows.get(str(h.get("prediction_id") or "")) or {}
            n = authoritative_grades.note_of(row)
            pid = str(h.get("prediction_id") or "")
            public = _public_ids(table, coach_id, [pid])
            notes.append(
                authoritative_grades.correction_note(
                    prediction_id=pid if pid in public else None,
                    coach_id=coach_id,
                    original_status=n.get("original_status") if n else None,
                    corrected_status=n.get("current_status") if n else h.get("status"),
                    corrected_at=n.get("corrected_at") if n else None,
                    explanation=n.get("explanation") if n else None,
                )
            )
        if notes:
            e["grade_corrections"] = list({json.dumps(n, sort_keys=True): n for n in notes}.values())
    return entries


def apply_to_stance(stance: dict, table: Any, coach_id: str) -> dict:
    """``/api/coach/<id>`` ``stance``: the coach's CURRENT read (STANCE#latest), judged like the dashboard read. A
    superseded stance serves the records summary as ``headline_read`` and withholds its reasoning prose
    (``how_my_read_changed``, ``stage.rationale``); the ladder and stage numbers are structure, not a verdict."""
    if not isinstance(stance, dict) or stance.get("source") in ("absent", "none"):
        return stance
    raw_stage = stance.get("stage")
    stage: dict = raw_stage if isinstance(raw_stage, dict) else {}
    if not (stance.get("headline_read") or stance.get("how_my_read_changed") or stage.get("rationale")):
        return stance  # no prose: nothing a correction can contradict
    j = judge(
        table,
        coach_id,
        {"created_at": stance.get("as_of"), "derived_from": stance.get("derived_from")},
        str(stance.get("headline_read") or ""),
    )
    text = j.pop("text")
    if j["summary_state"] != "current":
        # A headline the audience guard already withheld stays withheld; the records summary never fills a private slot's place.
        stance["headline_read"] = text if stance.get("headline_read") else ""
        stance["how_my_read_changed"] = None
        if isinstance(stance.get("stage"), dict) and stance["stage"].get("rationale"):
            stance["stage"] = {**stance["stage"], "rationale": None}
    stance.update(j)
    return stance


def judge_into(entry: dict, table: Any, item: dict, text: str) -> dict:
    """``/api/coaching-dashboard``: ``text`` (the audience-guarded blurb of ``item``, an OUTPUT# row) judged into
    ``entry["position_summary"]`` with the provenance fields; the coach is the row's own partition."""
    coach_id = str(item.get("pk") or "").replace("COACH#", "", 1)
    return apply_to_entry(entry, table, coach_id, item, text)
