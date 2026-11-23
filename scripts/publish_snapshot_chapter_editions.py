#!/usr/bin/env python3
"""scripts/publish_snapshot_chapter_editions.py — second editions of published chapters into the snapshot (#6193).

An approved second (or later) edition reaches the public only through ``/api/chapters``' ``editions`` field, which the
Site API serves only while ``content.chapter_editions.LIVE`` is True. This module carries that field into the snapshot as
``chapter_editions.json``; ``www/src/lib/chapter_editions.js`` makes the chapter page serve the edition's text with its
edition line, and builds ``/story/<id>/first-edition/`` only for a chapter whose archival rendering was approved.

THE SWITCH, TWICE. The file is written only when the repo's ``chapter_editions.LIVE`` is True AND the route served the
field (live mode) — or, in fixture mode, when ``WEB_EDITIONS=1`` is set (the build gate's mutation and local review).
Otherwise ``resolve`` returns None and NO file is written: a switch-off snapshot, and so the built site, is unchanged.

Fail closed, loudly — and per edition. A served ``null`` (the route could not read the rows) or a malformed FILE is a
schema error (exit 2). Each ENTRY is then checked on its own and HELD (logged, left out: its page keeps the first
edition) when it fails: a chapter that is not a published chapter of this snapshot, a first-published day that disagrees
with the chapter's served one, a carried correction that is not approved, text bytes that do not hash to the approved
SHA-256, a body that is not exactly the chronicle renderer's output for that text, an emptied body, or a body the truth
checks refuse — and (#6193 B4) a title line that is not the chapter's published title or a summary that is not the
text's own summary line, and (B9) a text that points at its first-edition address when no archival rendering of that
chapter is served (the edition and its archival page ship together, or neither does). One held edition never blocks an
unrelated verified one (owner ruling 2026-11-22, final approval §12).
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))
from content import (
    chapter_corrections as CC,
    chapter_editions as CE,
    story_checks,
)  # noqa: E402 — the record's rules, one copy

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
    # #6199: nor a call record to classify — the private-call check is not wired here (live mode carries the Site API's
    # view, which ran it on the real calls).
    view = CE.public_view(
        doc.get("records") or [], tainted=lambda _t: False, private_calls=CE.PRIVATE_CALLS_NOT_WIRED, filter_hits=lambda _t: []
    )
    return {"state": "ok", "source": [CHAPTERS_PATH], "editions": view}


def _day(value: Any) -> Optional[str]:
    return str(value)[:10] if isinstance(value, str) and CE.ISO_DAY.match(str(value)[:10]) else None


def _check_text(cid: str, what: str, block: dict, title: Optional[str] = None) -> None:
    """The served bytes are the approved bytes: the text hashes to the SHA-256 the approval is bound to, its presentation
    fields are the text's own title and summary lines, and the body is exactly the chronicle renderer's output for the
    rest of the text — so nothing between approval and page can change the prose or move a word out of its slot."""
    text, body = block.get("text"), block.get("body_html")
    if not isinstance(text, str) or CE.text_sha256(text) != block.get("text_sha256"):
        raise ValueError(f"chapter_editions.json: {cid}: the {what} text does not hash to its approved SHA-256")
    try:
        p = CE.presentation(text, edition=what == "edition")
    except CE.EditionError as exc:
        raise ValueError(f"chapter_editions.json: {cid}: {exc}") from exc
    if block.get("title") != p["title"] or (what == "edition" and block.get("summary") != p["summary"]):
        raise ValueError(f"chapter_editions.json: {cid}: the {what}'s title and summary are not its own title and summary lines")
    if p["title"] is not None and " ".join(p["title"].split()) != " ".join(str(title or "").split()):
        raise ValueError(
            f"chapter_editions.json: {cid}: the {what}'s title line {p['title']!r} is not the chapter's published title {title!r} "
            "(an edition never retitles a chapter)"
        )
    if not isinstance(body, str) or body != CE.render_html(p["body"]):
        raise ValueError(f"chapter_editions.json: {cid}: the {what} body is not the rendering of its approved text")
    plain = CE.plain_text(body)
    if len(plain.strip()) < CE.MIN_TEXT:
        raise ValueError(f"chapter_editions.json: {cid}: the {what} is empty (a withheld or unread text never renders as blank)")
    found = story_checks.staged_encounter_findings(plain) + story_checks.reader_surface(plain)
    if found:
        raise ValueError(f"chapter_editions.json: {cid}: the {what} fails the truth checks ({len(found)} finding(s))")


def _check_edition(e: dict, chapters: dict, approved: set) -> None:
    cid = str(e["chapter_id"])
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
    _check_text(cid, "edition", e, chapters[cid].get("title"))


def _check_archival(cid: str, e: dict, a: Any, title: Optional[str]) -> None:
    if not isinstance(a, dict) or set(a) != set(CE.PUBLIC_ARCHIVAL_FIELDS):
        raise ValueError(f"chapter_editions.json: {cid}: an archival rendering is exactly {sorted(CE.PUBLIC_ARCHIVAL_FIELDS)}")
    as_of = a.get("as_of")
    if as_of is not None and not (CE.ISO_DAY.match(str(as_of)) and e["first_published"] <= str(as_of) <= e["revised_on"]):
        raise ValueError(f"chapter_editions.json: {cid}: the archival as_of day is not between first publication and this revision")
    note = CE.archival_note(e["first_published"], e["revised_on"], as_of)
    if a["note"] != note or a["signature"] != CE.archival_signature(a["approved_on"]):
        raise ValueError(f"chapter_editions.json: {cid}: the archival note and signature are the platform's fixed words only")
    _check_text(cid, "archival", a, title)


def _anchored(cid: str, a: dict, approved: set, log: Callable[[str], None]) -> dict:
    """#6193 (rehearsal ruling §4): an anchor stays only when it names an APPROVED, served correction of this chapter and
    its passage is in the rendering exactly once; any other anchor is dropped (its correction stays at the top)."""
    body = CE.presentation(a["text"], edition=False)["body"]
    keep = []
    for x in a.get("anchors") or []:
        ok = isinstance(x, dict) and (cid, x.get("correction_id")) in approved and CE.placed_anchors([x], body) == [x]
        if ok:
            keep.append(x)
        else:
            log(
                f"  ✗ anchor dropped on {cid}: {x.get('correction_id') if isinstance(x, dict) else x!r} (not an approved correction, or its passage is not in the text once)"
            )
    return {**a, "anchors": keep}


def validate(doc: Any, public: dict, corrections: Optional[dict], log: Callable[[str], None] = print, held: Optional[list] = None) -> dict:
    """Exact shape (a malformed FILE stops the build); then every entry re-derived and re-checked ON ITS OWN. An entry
    that fails is withheld — its chapter serves the first edition — and named loudly, and the others go on: one held
    edition never blocks an unrelated verified one (final approval §12). A failing archival rendering drops only itself."""
    if not isinstance(doc, dict) or set(doc) != KEYS or doc["state"] != "ok" or not isinstance(doc["editions"], list):
        raise ValueError(f"chapter_editions.json: keys must be exactly {sorted(KEYS)}, state ok, a list of editions")
    chapters = {c["id"]: c for c in public.get("chapter", []) if c.get("status") == "published"}
    approved = {(c["chapter_id"], c["id"]) for c in ((corrections or {}).get("corrections") or [])}
    held = held if held is not None else []
    seen, kept = set(), []
    for e in doc["editions"]:
        if not isinstance(e, dict) or set(e) != set(CE.PUBLIC_FIELDS):
            raise ValueError(f"chapter_editions.json: an edition is exactly {sorted(CE.PUBLIC_FIELDS)}")
        cid = str(e["chapter_id"])
        if not CE.CHAPTER_ID.match(cid) or cid in seen:
            raise ValueError(f"chapter_editions.json: malformed or repeated chapter id {cid!r}")
        seen.add(cid)
        try:
            _check_edition(e, chapters, approved)
        except (ValueError, KeyError, TypeError) as exc:
            held.append(cid)
            log(f"  ✗ HELD edition {cid}: {exc} — its page keeps the first edition; other editions are unaffected")
            continue
        if e["archival"] is not None:
            try:
                _check_archival(cid, e, e["archival"], chapters[cid].get("title"))
            except (ValueError, KeyError, TypeError) as exc:
                held.append(f"{cid}#archival")
                log(f"  ✗ HELD archival rendering {cid}: {exc} — no first-edition page")
                e = {**e, "archival": None}
        if e["archival"] is not None:
            e = {**e, "archival": _anchored(cid, e["archival"], approved, log)}
        if e["archival"] is None and CE.references_archive(e.get("text"), cid):
            held.append(cid)
            log(
                f"  ✗ HELD edition {cid}: its text points readers at {CE.archive_path(cid)}, and no approved archival rendering is "
                "served — release the edition and its archival rendering together; its page keeps the first edition"
            )
            continue
        kept.append(e)
    return {**doc, "editions": kept}


def attach(data_files: dict, mode: str, fixtures_dir: str, get: Callable[[str], Any], log: Callable[[str], None], public: dict) -> None:
    """``data_files["chapter_editions"]`` only when the switch is on — no key = no file, so a switch-off snapshot is
    byte-identical to the one before #6193."""
    doc = resolve(mode, fixtures_dir, get, log, public, data_files.get("chapter_corrections"))
    if doc is not None:
        data_files["chapter_editions"] = doc


def resolve(
    mode: str, fixtures_dir: str, get: Callable[[str], Any], log: Callable[[str], None], public: dict, corrections: Optional[dict]
) -> Optional[dict]:
    """The producer's one call: None (write nothing) while the switch is off. A malformed file is a SchemaError (exit 2)."""
    from publish_snapshot_contract import SchemaError  # noqa: PLC0415

    if not enabled(mode):
        return None
    try:
        doc = fixture(fixtures_dir) if mode == "fixture" else live(get, log)
        return None if doc is None else validate(doc, public, corrections, log=log)
    except ValueError as exc:
        raise SchemaError(str(exc)) from exc
