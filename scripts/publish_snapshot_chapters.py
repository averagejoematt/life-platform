#!/usr/bin/env python3
"""scripts/publish_snapshot_chapters.py — the chapter and call vocabulary the v9 pages share (acceptance, 2026-11-02).

Kept beside scripts/publish_snapshot.py (over the 1000-line module ceiling, tests/test_module_size_guard.py).
Three pure pieces the owner's Journey/Day review asked to be one thing everywhere:

* `CALL_OUTCOME` — a call's OWN outcome in words. A prediction's `summary` is this word; it used to be the
  simple guess's result ("wrong" = the nothing-changes guess was wrong), which the Connected rail printed
  under a call the ledger graded right. Pinned equal to www/src/lib/format.js CALL_OUTCOME.
* `apply_week_intervals` — every program-week chapter carries the explicit interval `/api/chapters` serves
  (`week_start`..`week_end`), else genesis + 7·(n−1) .. +6; a prologue (week 0) carries none. Every page that
  places a date in a week reads these two fields — never a chapter's publication `date` (Week 1 is
  6–12 September and was published on the 8th; inferring the week from that date put 12 September in Week 2).
* `clean_excerpt` — a chapter's excerpt without the editor's note the body already opens with, and without the
  Markdown emphasis markers the feed carries literally. The body itself is never touched.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from publish_snapshot_contract import ISO_DAY  # noqa: E402

CALL_OUTCOME = {
    "confirmed": "right",
    "refuted": "wrong",
    "expired": "could not be checked",
    "inconclusive": "inconclusive",
    "pending": "open",
    "observation": "not graded",
}
WEEK_LENGTH = 7
_EDITOR_NOTE = re.compile(r"^\s*[*_]*\s*Editor[’']s note\b[\s\S]*?(?:\n\s*\n|$)", re.IGNORECASE)
_EMPHASIS = re.compile(r"(?<![\w*])[*_]{1,3}(?=\S)|(?<=\S)[*_]{1,3}(?![\w*])")


# Installments withdrawn from public access, by their permanent URL (fail closed: even if /journal/posts.json lists
# one again, it is never a chapter, so it has no v9 page, link or sitemap entry; the stored installment is untouched).
#   week-02 — the pilot instalment "The Night Before Everything" (owner rulings 2026-11-06 redirect, 2026-11-09 held).
#   week-03 — "The Plan, On the Record": it quotes day-one sealed calls verbatim, two of which the owner ruled private
#             on 2026-11-09 (#5720); withdrawn 2026-11-10.
WITHDRAWN_CHAPTER_URLS = frozenset({"/journal/posts/week-02/", "/journal/posts/week-03/"})


def week_id(url: str | None) -> str | None:
    """The chapter id of a journal permalink ("/journal/posts/week-04/" -> "week-04"), or None — and None for a
    withdrawn installment (WITHDRAWN_CHAPTER_URLS), so no caller can make one a chapter."""
    if (url or "").rstrip("/") + "/" in WITHDRAWN_CHAPTER_URLS:
        return None
    m = re.search(r"/week-(\d+)/?$", url or "")
    return f"week-{int(m.group(1)):02d}" if m else None


def call_outcome(status: str) -> str:
    return CALL_OUTCOME.get(status, status)


def week_interval(n: int, genesis: str | None, spans: dict[int, tuple[str, str]]) -> tuple[str | None, str | None]:
    """The served interval for program week `n`, else the arithmetic from the genesis day (day 1–7 = week 1)."""
    if n in spans:
        return spans[n]
    if n < 1 or not genesis or not ISO_DAY.match(genesis):
        return None, None
    start = date.fromisoformat(genesis) + timedelta(days=WEEK_LENGTH * (n - 1))
    return start.isoformat(), (start + timedelta(days=WEEK_LENGTH - 1)).isoformat()


def served_spans(chapters_api: dict | None) -> dict[int, tuple[str, str]]:
    out: dict[int, tuple[str, str]] = {}
    for w in (chapters_api or {}).get("weeks") or []:
        n, a, b = w.get("week"), str(w.get("start") or ""), str(w.get("end") or "")
        if isinstance(n, int) and not isinstance(n, bool) and ISO_DAY.match(a) and ISO_DAY.match(b) and a <= b:
            out[n] = (a, b)
    return out


def apply_week_intervals(chapters: list[dict], chapters_api: dict | None, genesis: str | None) -> None:
    spans = served_spans(chapters_api)
    genesis = genesis or (chapters_api or {}).get("genesis")
    for c in chapters:
        n = c.get("week")
        a, b = week_interval(n, genesis, spans) if isinstance(n, int) and not isinstance(n, bool) and n >= 1 else (None, None)
        c["week_start"], c["week_end"] = a, b


def clean_excerpt(text: str | None) -> str | None:
    if not isinstance(text, str):
        return text
    out = _EDITOR_NOTE.sub("", text, count=1) if _EDITOR_NOTE.match(text) else text
    out = _EMPHASIS.sub("", out).strip()
    return out or None
