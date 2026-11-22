#!/usr/bin/env python3
"""scripts/publish_snapshot_chapter_editions.py — second editions of published chapters into the snapshot (#6193).

An approved second (or later) edition reaches the public only through ``/api/chapters``' ``editions`` field, which the
Site API serves only while ``content.chapter_editions.LIVE`` is True. This module carries that field into the snapshot as
``chapter_editions.json``; ``www/src/lib/chapter_editions.js`` makes the chapter page serve the edition's text with its
edition line, and builds ``/story/<id>/first-edition/`` only for a chapter whose archival rendering was approved.

THE SWITCH, TWICE. The file is written only when the repo's ``chapter_editions.LIVE`` is True AND the route served the
field (live mode) — or, in fixture mode, when ``WEB_EDITIONS=1`` is set (the build gate's mutation and local review).
Otherwise ``resolve`` returns None and NO file is written: a switch-off snapshot, and so the built site, is unchanged.

Fail closed, loudly: a served ``null`` (the route could not read the rows), a malformed entry, an edition of a chapter
that is not a published chapter of this snapshot, a first-published day that disagrees with the chapter's served one, a
carried correction that is not approved, an emptied body or a body the truth checks refuse — each is a schema error
(exit 2); the build stops rather than publish an edition it cannot vouch for.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))
from content import chapter_corrections as CC, chapter_editions as CE, story_checks  # noqa: E402 — the record's rules, one copy

CHAPTERS_PATH = "/api/chapters"
FIXTURE_NAME = "chapter_editions.json"
FIXTURE_ENV = "WEB_EDITIONS"
KEYS = {"state", "source", "editions"}


def enabled(mode: str) -> bool:
    return CE.LIVE or (mode == "fixture" and os.environ.get(FIXTURE_ENV) == "1")


def compose(payload: Any) -> Optional[dict]:
    """``/api/chapters`` as served → the data file, or None when the route did not serve the field (switch off there)."""
    if not isinstance(payload, dict) or "editions" not in payload:
        return None
    if payload["editions"] is None:
        raise ValueError(f"chapter_editions.json: the route could not read the editions ({payload.get('editions_error')})")
    return {"state": "ok", "source": [CHAPTERS_PATH], "editions": payload["editions"]}


def live(get: Callable[[str], Any], log: Callable[[str], None]) -> Optional[dict]:
    try:
        payload = get(CHAPTERS_PATH)
    except Exception as exc:  # noqa: BLE001 — with the switch on, an edition is never dropped quietly
        raise ValueError(
            f"chapter_editions.json: /api/chapters unreadable ({type(exc).__name__}); refusing to build without its editions"
        ) from exc
    doc = compose(payload)
    if doc is None:
        log("  chapter editions: switch on in the repo, but the route serves no editions field (Site API not yet deployed) — none")
    return doc


def fixture(fixtures_dir: str) -> Optional[dict]:
    path = os.path.join(fixtures_dir, FIXTURE_NAME)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    # The fixture's records are synthetic: there is no coach partition to echo and no private vocabulary to read (the
    # filter is off-repo and CI has no channel), so those two gates see nothing; the truth checks run for real.
    view = CE.public_view(doc.get("records") or [], tainted=lambda _t: False, filter_hits=lambda _t: [])
    return {"state": "ok", "source": [CHAPTERS_PATH], "editions": view}


def _day(value: Any) -> Optional[str]:
    return str(value)[:10] if isinstance(value, str) and CE.ISO_DAY.match(str(value)[:10]) else None


def validate(doc: Any, public: dict, corrections: Optional[dict]) -> dict:
    """Exact shape, every entry re-derived and re-checked; every chapter a published public chapter of this snapshot."""
    if not isinstance(doc, dict) or set(doc) != KEYS or doc["state"] != "ok" or not isinstance(doc["editions"], list):
        raise ValueError(f"chapter_editions.json: keys must be exactly {sorted(KEYS)}, state ok, a list of editions")
    chapters = {c["id"]: c for c in public.get("chapter", []) if c.get("status") == "published"}
    approved = {(c["chapter_id"], c["id"]) for c in ((corrections or {}).get("corrections") or [])}
    seen = set()
    for e in doc["editions"]:
        if not isinstance(e, dict) or set(e) != set(CE.PUBLIC_FIELDS):
            raise ValueError(f"chapter_editions.json: an edition is exactly {sorted(CE.PUBLIC_FIELDS)}")
        cid = str(e["chapter_id"])
        if not CE.CHAPTER_ID.match(cid) or cid in seen:
            raise ValueError(f"chapter_editions.json: malformed or repeated chapter id {cid!r}")
        seen.add(cid)
        if cid not in chapters:
            raise ValueError(f"chapter_editions.json: {cid} is not a published chapter of this snapshot; an edition has no page to serve")
        try:
            line = CE.edition_line(e["edition"], e["revised_on"], e["first_published"])
            sig = CE.signature(e["edition"], e["revised_on"])
        except (CE.EditionError, CC.CorrectionError) as exc:
            raise ValueError(f"chapter_editions.json: {cid}: {exc}") from exc
        if e["edition_line"] != line or e["signature"] != sig:
            raise ValueError(f"chapter_editions.json: {cid}: the edition line and signature must be the platform's ({line!r})")
        served_day = _day(chapters[cid].get("published_at"))
        if served_day and served_day != e["first_published"]:
            raise ValueError(
                f"chapter_editions.json: {cid}: first published {e['first_published']}, but the chapter was published {served_day}"
            )
        if not isinstance(e["approvals"], list) or not e["approvals"] or any(a.get("by") != CC.APPROVER for a in e["approvals"]):
            raise ValueError(f"chapter_editions.json: {cid}: no owner approval")
        missing = [c for c in e["carries"] or [] if (cid, c) not in approved]
        if missing:
            raise ValueError(f"chapter_editions.json: {cid}: carries corrections that are not approved and served: {missing}")
        texts = [("body", e["body_html"])]
        a = e["archival"]
        if a is not None:
            if not isinstance(a, dict) or set(a) != set(CE.PUBLIC_ARCHIVAL_FIELDS):
                raise ValueError(f"chapter_editions.json: {cid}: an archival rendering is exactly {sorted(CE.PUBLIC_ARCHIVAL_FIELDS)}")
            if a["note"] != CE.archival_note(e["first_published"], e["revised_on"]) or a["signature"] != CE.archival_signature(
                a["approved_on"]
            ):
                raise ValueError(f"chapter_editions.json: {cid}: the archival note and signature are the platform's fixed words only")
            texts.append(("archival", a["body_html"]))
        for what, body in texts:
            plain = CE.plain_text(body)
            if not isinstance(body, str) or len(plain.strip()) < CE.MIN_TEXT:
                raise ValueError(f"chapter_editions.json: {cid}: the {what} is empty (a withheld or unread text never renders as blank)")
            found = story_checks.staged_encounter_findings(plain) + story_checks.reader_surface(plain)
            if found:
                raise ValueError(f"chapter_editions.json: {cid}: the {what} fails the truth checks ({len(found)} finding(s))")
    return doc


def resolve(
    mode: str, fixtures_dir: str, get: Callable[[str], Any], log: Callable[[str], None], public: dict, corrections: Optional[dict]
) -> Optional[dict]:
    """The producer's one call: None (write nothing) while the switch is off. A malformed file is a SchemaError (exit 2)."""
    from publish_snapshot_contract import SchemaError  # noqa: PLC0415

    if not enabled(mode):
        return None
    try:
        doc = fixture(fixtures_dir) if mode == "fixture" else live(get, log)
        return None if doc is None else validate(doc, public, corrections)
    except ValueError as exc:
        raise SchemaError(str(exc)) from exc
