#!/usr/bin/env python3
"""scripts/publish_snapshot_chapter_corrections.py — dated public corrections to published chapters (#6177).

The platform's corrections to a published chapter live in their own records (``lambdas/content/chapter_corrections.py``)
and reach the public only through ``/api/chapters``' ``corrections`` field — approved, platform-signed, with the
approval history. This module carries that field into the snapshot as ``chapter_corrections.json``. It publishes
nothing by itself: ``www/src/lib/chapter_corrections.js`` places each one beside its chapter, never inside the
chapter's text.

Fixture mode reads ``content/fixtures/chapter_corrections.json`` — sample RECORDS, approved and not, as the table holds
them — and runs the platform's own ``public_view`` over them, so the build gate exercises the same filter the route
applies (an unapproved sample carries a sentinel the scan refuses to find in any page).

Fail closed, loudly: a served ``null`` (the route could not read the records) or a malformed entry is a schema error
(exit 2) — the build stops rather than publish a site that silently drops an approved correction. A route that does
not serve the field at all (a Site API from before #6177) reads as absent: there is nothing approved to drop.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))
from content import chapter_corrections as CC  # noqa: E402 — the record's rules, one copy

CHAPTERS_PATH = "/api/chapters"
FIXTURE_NAME = "chapter_corrections.json"
KEYS = {"state", "source", "absent_text", "corrections"}
ABSENT = {
    "state": "absent",
    "source": [CHAPTERS_PATH],
    "absent_text": "The platform did not serve chapter corrections for this snapshot.",
    "corrections": [],
}


def compose(payload: Any) -> dict:
    """``/api/chapters`` as served → the data file. A missing field is absent; a served null is an error."""
    if not isinstance(payload, dict) or "corrections" not in payload:
        return dict(ABSENT)
    if payload["corrections"] is None:
        raise ValueError(f"chapter_corrections.json: the route could not read the corrections ({payload.get('corrections_error')})")
    return {"state": "ok", "source": [CHAPTERS_PATH], "absent_text": None, "corrections": payload["corrections"]}


def live(get: Callable[[str], Any], log: Callable[[str], None]) -> dict:
    import urllib.error  # noqa: PLC0415

    try:
        payload = get(CHAPTERS_PATH)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:  # a Site API from before the route: nothing approved can exist to drop
            log("  chapter corrections: /api/chapters not served (404) — absent")
            return dict(ABSENT)
        raise ValueError(f"chapter_corrections.json: /api/chapters answered {exc.code}; refusing to build without its corrections") from exc
    except Exception as exc:  # noqa: BLE001 — any other failure stops the build: an approved correction is never dropped quietly
        raise ValueError(
            f"chapter_corrections.json: /api/chapters unreadable ({type(exc).__name__}); refusing to build without its corrections"
        ) from exc
    return compose(payload)


def fixture(fixtures_dir: str) -> dict:
    path = os.path.join(fixtures_dir, FIXTURE_NAME)
    if not os.path.exists(path):
        return dict(ABSENT)
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    return {"state": "ok", "source": [CHAPTERS_PATH], "absent_text": None, "corrections": CC.public_view(doc.get("records") or [])}


def validate(doc: Any, public: dict) -> dict:
    """Exact shape, every entry re-checked against the record's rules, every chapter a published public chapter of this
    snapshot. Raises ValueError."""
    if not isinstance(doc, dict) or set(doc) != KEYS:
        raise ValueError(f"chapter_corrections.json: keys must be exactly {sorted(KEYS)}")
    if doc["state"] not in ("ok", "absent") or not isinstance(doc["corrections"], list):
        raise ValueError("chapter_corrections.json: state ok|absent and a list of corrections")
    published = {c["id"] for c in public.get("chapter", []) if c.get("status") == "published"}
    kept, seen = [], set()
    personas = CC.persona_names()
    for c in doc["corrections"]:
        if not isinstance(c, dict) or set(c) != set(CC.PUBLIC_FIELDS):
            raise ValueError(f"chapter_corrections.json: a correction is exactly {sorted(CC.PUBLIC_FIELDS)}")
        if not CC.CHAPTER_ID.match(str(c["chapter_id"])) or not CC.CORRECTION_ID.match(str(c["id"])) or c["kind"] not in CC.KINDS:
            raise ValueError(f"chapter_corrections.json: malformed ids or kind on {c.get('id')!r}")
        if not CC.ISO_DAY.match(str(c["dated_on"])) or c["signature"] != CC.signature(c["kind"], c["dated_on"]):
            raise ValueError(f"chapter_corrections.json: {c['id']} is not signed by the platform ({c['signature']!r})")
        if any(n in c["signature"] for n in personas):
            raise ValueError(f"chapter_corrections.json: {c['id']} is signed with a persona name")
        for f in ("published_said", "record_shows", "evidence"):
            if not isinstance(c[f], str) or not c[f].strip():
                raise ValueError(f"chapter_corrections.json: {c['id']}.{f} is empty (a withheld or unread text never renders as blank)")
        if not isinstance(c["approvals"], list) or not c["approvals"]:
            raise ValueError(f"chapter_corrections.json: {c['id']} carries no approval")
        for a in c["approvals"]:
            if (
                not isinstance(a, dict)
                or set(a) != set(CC.PUBLIC_APPROVAL_FIELDS)
                or a["by"] != CC.APPROVER
                or not CC.ISO_DAY.match(str(a["on"]))
            ):
                raise ValueError(f"chapter_corrections.json: {c['id']} has a malformed approval")
        if (c["chapter_id"], c["id"]) in seen:
            raise ValueError(f"chapter_corrections.json: {c['id']} is listed twice")
        seen.add((c["chapter_id"], c["id"]))
        if c["chapter_id"] in published:  # a withdrawn or held chapter has no page, so nothing to place it beside
            kept.append(c)
    return {**doc, "corrections": kept}


def resolve(mode: str, fixtures_dir: str, get: Callable[[str], Any], log: Callable[[str], None], public: dict) -> dict:
    """The producer's one call. A malformed file is the contract's SchemaError (exit 2)."""
    from publish_snapshot_contract import SchemaError  # noqa: PLC0415

    try:
        return validate(fixture(fixtures_dir) if mode == "fixture" else live(get, log), public)
    except ValueError as exc:
        raise SchemaError(str(exc)) from exc
