"""GET /api/coach_room_words?coach=<persona_id> — the owner-approved historical coach words, for the Coaching Room's CR2.

Owner ruling 2026-11-09 (third, D), conditional GO: the sealed day-one calls and the clean lead daily reads that passed
the record-level provenance and privacy check (``common.narrative_allowlist``, 35 rows by record key + text hash) may
be prepared for CR2. "NOT authorization to release all of CR2; remaining historical coach material stays withheld."

THE ONE ROUTE THAT OPENS THE CR2 SCOPE. ``scope_for(path)`` is the only place in the Lambda tree that enters
``narrative_allowlist.serving(SCOPE_CR2)``, and only for ``ROUTE``: the site API's handler runs this route's dispatch
AND its wire half (``narrative_publication.annotate``) inside it, so an approved row read here is served by the gate
and not scrubbed at the wire. Every other path — ``/api/coach/<id>``, the ledger, every live page — runs outside the
scope and reads these rows exactly as before (withheld). ``tests/test_coach_room_words_cr2.py`` pins both halves.

LIVE since the owner's CR2 GO (ruling 2026-11-11, second message): ``narrative_allowlist.CR2_PUBLIC`` is on. With it
off this route answers 404 for every coach, and the gate withholds the rows even if it did not (the allowlist honours
an entry only with the switch on).

WHAT IS SERVED — only the approved rows of the asked coach, each read through the public chokepoint
(``web.site_api_common.table``, the ``PublicationTable``) by its record key, and each served ONLY when the gate itself
published it under the allowlist in this request (``narrative_allowlist.is_approved_text``): a listed row whose words
changed, a row that now carries a provenance record of its own (private, unrecorded or malformed), a row the call
policy omits, or a row whose words the dossier filter flags is left out — omitted, never marked, never counted.

  * ``sealed_calls`` — a day-one call: its words, the day it was sealed, the metric, and the ledger's own verdict
    fields from ``web.site_api_ledger_export.export_item`` (the same derivation the ledger page serves);
  * ``lead_reads`` — a lead daily read: its words, when it was written, the data it read through, and the figures it
    cites (metric, value, day — never the source field names). An owner-approved ANNOTATED read
    (``common.narrative_annotations``, owner ruling 2026-11-11 second message, item 3) is one of them only WITH its
    ``correction``: the original words byte-identical, and the dated correction beside them. A read whose pair the
    annotation module will not build is left out, never served as bare words.
"""

from __future__ import annotations

import contextlib
from decimal import Decimal
from typing import Any, Callable, ContextManager, Optional

from common import narrative_allowlist as NA

ROUTE = "/api/coach_room_words"
CALL_PREFIX = "PREDICTION#"
LEAD_PREFIX = "LEAD_DAILY#"
METHOD = (
    "Historical coach words published by owner approval, row by row: each item passed a record-level check of what it "
    "was generated from, and is served only while its stored words are unchanged since that check. Every other "
    "historical coach text stays unpublished."
)


def scope_for(path: Any) -> ContextManager[None]:
    """The scope a request to ``path`` runs in: the CR2 scope for ``ROUTE`` only, no scope for every other path."""
    return NA.serving(NA.SCOPE_CR2) if path == ROUTE else contextlib.nullcontext()


def in_scope(path: Any, fn: Callable[[], Any]) -> Any:
    """``fn()`` run in the scope of ``path`` (the site API runs its dispatch and its wire half through this)."""
    with scope_for(path):
        return fn()


def _approved_annotations() -> list:
    from common import narrative_annotations as NANN

    return [a for a in NANN.INDEX.values() if a.owner_approved]


def coaches() -> list:
    """The persona ids with at least one approved row or approved annotated read (the only coaches this route answers for)."""
    keys = [e.pk for e in NA.APPROVED] + [a.pk for a in _approved_annotations()]
    return sorted({pk[len("COACH#") :] for pk in keys if pk.startswith("COACH#")})


def _f(v: Any) -> Any:
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def _dossier_safe(text: str) -> bool:
    """The dossier filter as a belt, failing CLOSED (a vocabulary that cannot load withholds the words)."""
    try:
        from coach import coach_dossier

        return coach_dossier.dossier_safe(text)
    except Exception:  # noqa: BLE001 — privacy.content_filter_channel.ContentFilterUnavailable and kin
        return False


def _published(item: Any, entry: NA.Entry) -> Optional[str]:
    """The approved words of ``item`` when the gate published them under the allowlist in this request; else None."""
    from web.narrative_publication import is_withheld

    if not isinstance(item, dict) or is_withheld(item):
        return None
    if str(item.get("sk") or "") != entry.sk:
        return None
    text = item.get(entry.field)
    if not isinstance(text, str) or not text.strip() or not NA.is_approved_text(text) or not _dossier_safe(text):
        return None
    return text


def _call(item: dict, text: str, coach: str) -> dict:
    from web.site_api_ledger_export import export_item

    short = coach[: -len("_coach")] if coach.endswith("_coach") else coach
    led = export_item(short, item)
    return {
        "prediction_id": led.get("prediction_id"),
        "claim": text,
        "logged_date": led.get("logged_date"),
        "due_date": led.get("due_date"),
        "settled_date": led.get("settled_date"),
        "metric": led.get("metric"),
        "kind": led.get("kind"),
        "status": led.get("status"),
        "sealed": bool(led.get("sealed")),
    }


def _lead(item: dict, text: str) -> dict:
    cited = []
    for c in item.get("cited") or []:
        if isinstance(c, dict) and isinstance(c.get("metric"), str):
            cited.append({k: str(_f(c.get(k)) if c.get(k) is not None else "") for k in ("metric", "value", "as_of")})
    return {
        "date": str(item.get("sk") or "")[len(LEAD_PREFIX) :][:10],
        "text": text,
        "generated_at": str(item.get("generated_at") or "") or None,
        "data_through": str(item.get("data_through") or "")[:10] or None,
        "cited": cited,
    }


def _annotated(item: Any, a: Any) -> Optional[dict]:
    """An approved annotated read as served: the gate published its words in this request, and the annotation module
    builds the pair (words + dated correction) over the same row. Else None — never the words alone."""
    from common import narrative_annotations as NANN

    from web.narrative_publication import is_withheld

    if not isinstance(item, dict) or is_withheld(item) or str(item.get("sk") or "") != a.sk:
        return None
    text = item.get(a.field)
    if not isinstance(text, str) or not text.strip() or not NA.is_approved_text(text) or not _dossier_safe(text):
        return None
    pair = NANN.annotated_words(item, a.pk)
    if pair is None or pair["words"] != text:
        return None
    lead = _lead(item, text)
    lead["correction"] = pair["annotation"]
    return lead


def serve(coach: str, table: Any) -> dict:
    """The approved rows of one coach, read one by one through ``table`` (which must be the gated table)."""
    calls, leads = [], []
    for entry in NA.APPROVED:
        if entry.pk != f"COACH#{coach}":
            continue
        item = (table.get_item(Key={"pk": entry.pk, "sk": entry.sk}) or {}).get("Item")
        text = _published(item, entry)
        if text is None:
            continue
        if entry.sk.startswith(CALL_PREFIX):
            calls.append(_call(item, text, coach))
        elif entry.sk.startswith(LEAD_PREFIX):
            leads.append(_lead(item, text))
    for a in _approved_annotations():
        if a.pk != f"COACH#{coach}" or not a.sk.startswith(LEAD_PREFIX):
            continue
        item = (table.get_item(Key={"pk": a.pk, "sk": a.sk}) or {}).get("Item")
        lead = _annotated(item, a)
        if lead is not None:
            leads.append(lead)
    calls.sort(key=lambda c: (str(c.get("logged_date") or ""), str(c.get("prediction_id") or "")))
    leads.sort(key=lambda r: r["date"], reverse=True)
    body = {"coach_id": coach, "approved_at": NA.APPROVED_AT, "method": METHOD, "sealed_calls": calls, "lead_reads": leads}
    if f"COACH#{coach}" == NA.LEAD_PK:
        # the denominator: how many reads were written in the checked window, served or not (a count, no words)
        body["lead_window"] = dict(NA.LEAD_WINDOW)
    return body


def handle_coach_room_words(event: dict, *, table: Any = None) -> dict:
    from web.site_api_common import _error, _ok

    # Fail closed twice: the switch off, or a request that is not running inside the CR2 scope, is a 404.
    if not NA.CR2_PUBLIC or not NA.active():
        return _error(404, "Not found")
    coach = str(((event or {}).get("queryStringParameters") or {}).get("coach") or "").strip()
    if coach not in coaches():
        return _error(404, "Not found")
    if table is None:
        from web.site_api_common import table as _table

        table = _table
    from web.narrative_publication import PublicationTable

    if not isinstance(table, PublicationTable):  # never an ungated read: the gate is what publishes an approved row
        return _error(404, "Not found")
    body = serve(coach, table)
    stamps = [r["generated_at"] for r in body["lead_reads"] if r.get("generated_at")]
    return _ok(body, cache_seconds=300, content_as_of=max(stamps) if stamps else None)
