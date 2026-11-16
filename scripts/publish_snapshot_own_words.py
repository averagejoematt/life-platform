#!/usr/bin/env python3
"""scripts/publish_snapshot_own_words.py — the owner's own words, as the platform serves them (owner ruling 2026-11-15).

The site's narrator is the platform. The owner's first-person lines reach a page through one door only: the
consent-per-line record (ADR-142, ``mark_journal_quote``), whose public projection is ``/api/journal_quotes`` — a line
he marked publishable, grounded verbatim in that day's entry, and re-screened against the taboo list on every serve.

This module carries that projection into the snapshot as ``own_words.json``: the day and the exact words, nothing else
(no marked-at instant, no channel, no receipts link). It publishes nothing by itself. A page shows a line only where
``www/src/lib/own_words.js`` pins a placement the owner approved AND the served line matches it character for
character — so a line he revokes leaves the site on the next build, and an unpinned served line is shown nowhere.

No new endpoint, no non-public read: the route is anonymous and already in the public archive's route list.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

QUOTES_PATH = "/api/journal_quotes?limit=50"
FIXTURE_NAME = "own_words.json"
ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_CHARS = 500  # the consent record's own ceiling (lambdas/content/journal_quotes.py MAX_QUOTE_CHARS)
KEYS = {"state", "source", "absent_text", "quotes"}

ABSENT_OWN_WORDS = {
    "state": "absent",
    "source": [QUOTES_PATH.split("?")[0]],
    "absent_text": "The platform did not serve the owner's approved lines for this snapshot.",
    "quotes": [],
}


def compose(payload: Any) -> dict:
    """``/api/journal_quotes`` as served → the data file. Only the day and the words are carried."""
    rows = payload.get("quotes") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return dict(ABSENT_OWN_WORDS)
    quotes = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        day, words = str(r.get("date") or ""), r.get("quote")
        if ISO_DAY.match(day) and isinstance(words, str) and words.strip():
            quotes.append({"date": day, "quote": words})
    quotes.sort(key=lambda q: (q["date"], q["quote"]))
    return {"state": "ok", "source": [QUOTES_PATH.split("?")[0]], "absent_text": None, "quotes": quotes}


def live_own_words(get: Callable[[str], Any], log: Callable[[str], None]) -> dict:
    """Read the route; a route that does not answer is an absent file (every placement then renders nothing)."""
    try:
        return compose(get(QUOTES_PATH))
    except Exception as exc:  # noqa: BLE001 — optional: the pages degrade to no quotation, never to a guess
        log(f"  own words unavailable ({type(exc).__name__}) — no first-person line is placed in this build")
        return dict(ABSENT_OWN_WORDS)


def fixture_own_words(fixtures_dir: str) -> dict:
    path = os.path.join(fixtures_dir, FIXTURE_NAME)
    if not os.path.exists(path):
        return dict(ABSENT_OWN_WORDS)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def resolve(mode: str, fixtures_dir: str, get: Callable[[str], Any], log: Callable[[str], None]) -> dict:
    """The producer's one call: the fixture's file or the live route, validated. A malformed file is a schema error
    (exit 2), raised as the contract's own exception so the producer needs no wrapper."""
    from publish_snapshot_contract import SchemaError  # noqa: PLC0415 — the contract module is the producer's, imported at call time

    try:
        return validate(fixture_own_words(fixtures_dir) if mode == "fixture" else live_own_words(get, log))
    except ValueError as exc:
        raise SchemaError(str(exc)) from exc


def validate(doc: Any) -> dict:
    """Exact shape, or ValueError: a field that is not the day or the words cannot ride along under any name."""
    if not isinstance(doc, dict) or set(doc) != KEYS:
        raise ValueError(f"own_words.json: keys must be exactly {sorted(KEYS)}")
    if doc["state"] not in ("ok", "absent"):
        raise ValueError("own_words.json: state must be ok or absent")
    if not isinstance(doc["quotes"], list) or (doc["state"] == "absent" and doc["quotes"]):
        raise ValueError("own_words.json: quotes must be a list, empty when absent")
    seen = set()
    for q in doc["quotes"]:
        if not isinstance(q, dict) or set(q) != {"date", "quote"}:
            raise ValueError("own_words.json: a line is exactly {date, quote}")
        if not ISO_DAY.match(str(q["date"])) or not isinstance(q["quote"], str) or not q["quote"].strip():
            raise ValueError("own_words.json: a line needs a day and its words")
        if len(q["quote"]) > MAX_CHARS:
            raise ValueError(f"own_words.json: a line is at most {MAX_CHARS} characters")
        if (q["date"], q["quote"]) in seen:
            raise ValueError("own_words.json: a line is listed once")
        seen.add((q["date"], q["quote"]))
    return doc
