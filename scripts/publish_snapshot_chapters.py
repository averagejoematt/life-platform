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
* `apply_chapter_dates` (run by `apply_week_intervals`) — a published chapter's TRUE dates, as `/api/chapters` serves
  them for a published week only: `published_at` (the owner's approval, as a Pacific day) and `covers_start`..
  `covers_end` (the days the chapter is about, from its "Day A to Day B" stats line). A chapter's `date` is the
  chronicle's DATA date — Week 10 is dated 10 November, covers 4–10 November and was approved on 13 November
  (2026-11-14). All three are null when not served (an older Lambda, fixture mode, a held/skipped/pending week);
  `approved.at` becomes the approval day when it is known and otherwise stays as it was.
* `clean_excerpt` — a chapter's excerpt without the editor's note the body already opens with, and without the
  Markdown emphasis markers the feed carries literally. The body itself is never touched.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

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
    apply_chapter_dates(chapters, chapters_api)


PACIFIC = ZoneInfo("America/Los_Angeles")  # the site's clock (#2506)


def pacific_day(ts: Any) -> str | None:
    """The Pacific calendar day of an ISO timestamp ("2026-11-14T00:24:35Z" -> "2026-11-13"); a bare day is itself;
    None when unreadable. A naive timestamp is read as UTC (the writers stamp UTC)."""
    s = str(ts or "").strip()
    if ISO_DAY.fullmatch(s):
        return s
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(PACIFIC).date().isoformat()


def served_dates(chapters_api: dict | None) -> dict[int, dict]:
    """``{week: {published_at, covers_start, covers_end}}`` for the PUBLISHED weeks `/api/chapters` serves — nothing
    is read off a held, skipped or pending week."""
    out: dict[int, dict] = {}
    for w in (chapters_api or {}).get("weeks") or []:
        n = w.get("week")
        if not isinstance(n, int) or isinstance(n, bool) or w.get("status") != "published":
            continue
        a, b = str(w.get("covers_start") or ""), str(w.get("covers_end") or "")
        span = (a, b) if ISO_DAY.fullmatch(a) and ISO_DAY.fullmatch(b) and a <= b else (None, None)
        out[n] = {"published_at": pacific_day(w.get("published_at")), "covers_start": span[0], "covers_end": span[1]}
    return out


def apply_chapter_dates(chapters: list[dict], chapters_api: dict | None) -> None:
    dates = served_dates(chapters_api)
    for c in chapters:
        n = c.get("week")
        d = dates.get(n) if c.get("status") == "published" and isinstance(n, int) and not isinstance(n, bool) else None
        d = d or {"published_at": None, "covers_start": None, "covers_end": None}
        c.update(d)
        if d["published_at"] and isinstance(c.get("approved"), dict):
            c["approved"] = {**c["approved"], "at": d["published_at"]}


_PARA = re.compile(r"<p(\s[^>]*)?>([\s\S]*?)</p>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_STAT_LINE = re.compile(r"^Day \d+\s*·")  # the machine header ("Day 31 · 327.3 → 308.9 lb · …"), never prose
_SENTENCE_END = re.compile(r"[.!?…](?:[\"”’)]*)(?=\s|$)")


def _text(fragment: str) -> str:
    import html as _html

    return re.sub(r"\s+", " ", _html.unescape(_TAG.sub("", fragment))).strip()


def _whole_sentences(text: str, limit: int) -> str:
    """The longest run of whole sentences within `limit` characters; a single over-long sentence is cut at a word."""
    if len(text) <= limit:
        return text
    cut = [m.end() for m in _SENTENCE_END.finditer(text) if m.end() <= limit]
    if cut:
        return text[: cut[-1]].strip()
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:—– ") + "…"


def chapter_summary(body_html: str | None, excerpt: str | None = None, limit: int = 300) -> str | None:
    """A chapter's summary read off its published body: the italic dek the narrator wrote for it when there is one,
    otherwise the opening paragraph — in whole sentences. An editor's note and the machine "Day N ·" stat line are
    never the summary (2026-11-14: the 300-character posts.json excerpt was mostly editor's note on chapters 0–4, so
    the front page and /story/ showed fragments such as "He is down 15 pounds from his first weigh-in in 24…")."""
    if isinstance(body_html, str) and body_html.strip():
        for _attrs, inner in _PARA.findall(body_html):
            t = _text(inner)
            if not t or t.lower().startswith("editor's note") or t.lower().startswith("editor’s note") or _STAT_LINE.match(t):
                continue
            return _whole_sentences(t, limit) or None
    return clean_excerpt(excerpt)  # no readable body: the served excerpt, cleaned as before


def whole_sentence_summary(text: str | None) -> str | None:
    """A served summary that may have been cut mid-word upstream (the episodes feed cuts at a fixed length: "…and
    been wrong every time until n") ends on its last whole sentence; stray markdown line-break backslashes go."""
    if not isinstance(text, str):
        return text
    t = re.sub(r"\s+", " ", re.sub(r"(?:\\\s*)+", " ", text)).strip()
    if not t:
        return None
    if _SENTENCE_END.search(t[-3:]):
        return t
    ends = [m.end() for m in _SENTENCE_END.finditer(t)]
    return t[: ends[-1]].strip() if ends else t


def clean_excerpt(text: str | None) -> str | None:
    if not isinstance(text, str):
        return text
    out = _EDITOR_NOTE.sub("", text, count=1) if _EDITOR_NOTE.match(text) else text
    out = _EMPHASIS.sub("", out).strip()
    return out or None


_KINDS = ("number", "direction", "yes_no", "sealed")


def versus_guess(comparison: dict | None) -> dict | None:
    """A coach's record against a guess that nothing changes, per kind of call, as /api/predictions serves it
    (`by_coach.<id>.comparison.records`) — counts and the producer's own verdict, nothing computed (2026-11-14: the
    coach page showed this only as one paragraph of kind-by-kind sentences). Kinds are never added together; a kind
    with no scored call is left out. None when the comparison is not served."""
    recs = (comparison or {}).get("records") if isinstance(comparison, dict) else None
    if not isinstance(recs, dict):
        return None
    kinds = []
    for k in _KINDS:
        r = recs.get(k)
        if not isinstance(r, dict) or not isinstance(r.get("scored"), int) or r["scored"] < 1:
            continue
        if not all(isinstance(r.get(f), int) for f in ("coach_right_on_scored", "rule_right")):
            continue
        kinds.append(
            {
                "kind": k,
                "scored": r["scored"],
                "coach_right": r["coach_right_on_scored"],
                "rule_right": r["rule_right"],
                "verdict": str(r.get("verdict") or ""),
            }
        )
    return {"kinds": kinds} if kinds else None


def quality_counts(q: Any) -> dict | None:
    """The grader's per-coach quality counts (#5533), as served: clean + flagged + unassessed == n."""
    if not isinstance(q, dict) or not all(isinstance(q.get(k), int) for k in ("clean", "flagged", "unassessed", "n")):
        return None
    by_flag = {str(k): int(v) for k, v in (q.get("by_flag") or {}).items() if isinstance(v, int)}
    return {"clean": q["clean"], "flagged": q["flagged"], "unassessed": q["unassessed"], "n": q["n"], "by_flag": by_flag}
