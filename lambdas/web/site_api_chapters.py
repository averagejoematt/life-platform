"""site_api_chapters.py — GET /api/chapters: every program week since genesis and its chapter's state (#5532).

THE GAP THIS CLOSES (#5520). The chronicle is keyed by date in DynamoDB
(``USER#…#SOURCE#chronicle`` / ``DATE#<day>``, one row per installment, ``week_number`` on
the row) and by a ``week-NN`` counter on the site (``generated/journal/posts.json``), and
the two have drifted: week 7 was never written (the AI budget paused), week 8 sat as a
``draft`` awaiting approval, and every door said only "the next draft is due Wednesday".
Nothing served the weeks that had no chapter. This route does, from the two readers the
story already has — the chronicle partition and the published manifest — one row per
7-day program week from genesis (``EXPERIMENT_START``, the week is the unit of the
experiment, ADR-077):

    {genesis, as_of, week_length_days: 7,
     weeks: [{week, start, end, status, date, title, url, label, drafted_at, reason}]}

  * ``published``  — the manifest carries a post for the week dated on or before today:
                     ``date``, ``title``, ``url``, ``label`` are the manifest's.
  * ``held``       — a chronicle row exists for the week in a non-published status
                     (``draft`` / ``changes_requested``): ONLY ``status`` and ``drafted_at``
                     (the row's ``generated_at``) are served. No title, excerpt or body — a
                     draft is the owner's until he approves it (#5520: approval stays his).
  * ``skipped``    — the week has ended with no row and no post: ``reason`` is the pending
                     marker's (``chronicle_store._set_chronicle_pending``, the writer's own
                     words for why no week landed) when the marker names this week, else
                     "no chapter was published".
  * ``pending``    — the week in progress, with nothing yet: the draft day has not come.

The prologue (manifest ``week`` 0, dated before genesis) is not a program week and is not
listed. A tombstoned or pre-genesis row is not read (``_query_source`` applies the phase
filter and the genesis clamp).

THE EDITION'S ``held``. `/api/edition` ``blocks.chapter.data.held`` reads the SAME marker
through ``held_marker`` below — one reader for "a draft is waiting", so the front page and
this route cannot disagree about it. The edition does not read the chronicle partition (its
upstream set and latency ceiling are pinned, ``tests/test_edition_latency_4607.py``); the
per-week ``held`` state from the row is this route's.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable

from common.pacific_time import pacific_today, parse_day_key

from web.site_api_common import EXPERIMENT_START, _error, _load_s3_json, _ok, _query_source, logger

SOURCE = "/api/chapters"
CACHE_SECONDS = 600
WEEK_DAYS = 7
MANIFEST_KEY = "generated/journal/posts.json"
NO_CHAPTER = "no chapter was published"
UNAVAILABLE = "The chapter list is not served right now."
HELD_STATUSES = ("draft", "changes_requested")
#: The chronicle row attributes this route reads — never the title or body of an unpublished week.
ROW_PROJECTION = ("date", "week_number", "status", "generated_at")


def held_marker(journal: dict | None) -> dict | None:
    """The manifest's ``pending`` marker (emails/chronicle_store._set_chronicle_pending): the week a draft
    was generated and withheld, with the writer's reason. A publish clears it. None when no draft is
    held — a page says a chapter is waiting ONLY when this is served (#4580 round 1; the edition's
    ``blocks.chapter.data.held`` is this)."""
    held = (journal or {}).get("pending") if isinstance(journal, dict) else None
    if not isinstance(held, dict) or not held.get("week"):
        return None
    return {"week": held.get("week"), "reason": held.get("reason"), "display": held.get("display"), "noted_at": held.get("noted_at")}


def _int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def program_weeks(genesis: str, today: str) -> list[dict]:
    """``[{week, start, end}]`` — every 7-day bin from genesis whose first day is on or before today."""
    g, t = date.fromisoformat(genesis), date.fromisoformat(today)
    out = []
    k = 1
    while True:
        start = g + timedelta(days=WEEK_DAYS * (k - 1))
        if start > t:
            break
        out.append({"week": k, "start": start.isoformat(), "end": (start + timedelta(days=WEEK_DAYS - 1)).isoformat()})
        k += 1
    return out


def week_of_day(day: str | None, genesis: str) -> int | None:
    """The program week a calendar day falls in (1-based), None before genesis or unparseable."""
    if not day or parse_day_key(str(day)[:10]) is None:
        return None
    n = (date.fromisoformat(str(day)[:10]) - date.fromisoformat(genesis)).days
    return n // WEEK_DAYS + 1 if n >= 0 else None


def row_week(row: dict, genesis: str) -> int | None:
    """Which program week a chronicle row is about: its ``week_number``, else the week its date falls in."""
    wk = _int(row.get("week_number"))
    if wk is not None and wk >= 1:
        return wk
    day = row.get("date") or str(row.get("sk") or "").replace("DATE#", "")
    return week_of_day(day, genesis)


def _published_posts(journal: dict | None, today: str) -> dict[int, dict]:
    """``{week: post}`` for the manifest's program-week posts dated on or before today (the newest per week)."""
    out: dict[int, dict] = {}
    for p in (journal or {}).get("posts") or []:
        if not isinstance(p, dict) or not p.get("title") or not p.get("url"):
            continue
        wk, day = _int(p.get("week")), str(p.get("date") or "")[:10]
        if not wk or wk < 1 or parse_day_key(day) is None or day > today:
            continue
        if wk not in out or (day, p.get("sequence") or 0) > (str(out[wk].get("date") or ""), out[wk].get("sequence") or 0):
            out[wk] = p
    return out


def compose(rows: list, journal: dict | None, genesis: str, today: str) -> dict:
    """The document — pure: the chronicle rows, the manifest, genesis and today in; the weeks out."""
    posts = _published_posts(journal, today)
    marker = held_marker(journal)
    marker_week = _int((marker or {}).get("week")) if marker else None
    by_week: dict[int, dict] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        wk = row_week(row, genesis)
        if wk is None:
            continue
        prev = by_week.get(wk)
        if prev is None or str(row.get("generated_at") or "") > str(prev.get("generated_at") or ""):
            by_week[wk] = row
    weeks = []
    for bin_ in program_weeks(genesis, today):
        wk = bin_["week"]
        entry: dict[str, Any] = {
            **bin_,
            "status": None,
            "date": None,
            "title": None,
            "url": None,
            "label": None,
            "drafted_at": None,
            "reason": None,
        }
        post, row = posts.get(wk), by_week.get(wk)
        row_status = str((row or {}).get("status") or "").strip().lower()
        if post is not None:
            entry.update(status="published", date=post.get("date"), title=post.get("title"), url=post.get("url"), label=post.get("label"))
        elif row is not None and row_status in HELD_STATUSES:
            entry.update(status="held", drafted_at=row.get("generated_at"))
            if marker_week == wk and marker:
                entry["reason"] = marker.get("display") or marker.get("reason")
        elif row is not None and row_status == "published":
            # Published in the store, not yet in the manifest (a publish in flight): the state is the store's.
            entry.update(status="published", date=str(row.get("date") or "")[:10] or None)
        elif bin_["end"] >= today:
            entry["status"] = "pending"
        else:
            entry["status"] = "skipped"
            entry["reason"] = (marker.get("display") or marker.get("reason")) if (marker and marker_week == wk) else NO_CHAPTER
        weeks.append(entry)
    return {
        "genesis": genesis,
        "as_of": today,
        "week_length_days": WEEK_DAYS,
        "weeks": weeks,
        "held": marker,
        "counts": {s: sum(1 for w in weeks if w["status"] == s) for s in ("published", "held", "skipped", "pending")},
        "source": SOURCE,
    }


def _read_manifest() -> dict | None:
    doc = _load_s3_json(MANIFEST_KEY, "chapters")
    return doc if isinstance(doc, dict) and doc else None


def handle_chapters(
    event,
    *,
    query: Callable = _query_source,
    read_manifest: Callable[[], dict | None] = _read_manifest,
    today: str | None = None,
):
    """GET /api/chapters — see the module docstring. ``query`` / ``read_manifest`` are the injectable readers."""
    today = today or pacific_today()
    genesis = EXPERIMENT_START
    if genesis > today:
        return _ok(
            {"genesis": genesis, "as_of": today, "week_length_days": WEEK_DAYS, "weeks": [], "held": None, "source": SOURCE},
            cache_seconds=CACHE_SECONDS,
        )
    try:
        rows = query("chronicle", genesis, today, projection=ROW_PROJECTION)
    except Exception as e:  # noqa: BLE001 — a failed partition read is a 503, never "every week skipped"
        logger.error(f"[chapters] chronicle read failed: {type(e).__name__}: {e}")
        return _error(503, UNAVAILABLE)
    journal = read_manifest()
    doc = compose(rows, journal, genesis, today)
    degraded = None
    if journal is None:
        degraded = "journal manifest unreadable — published weeks may read as skipped"
        logger.error(f"[chapters] {degraded}")
    return _ok(doc, cache_seconds=CACHE_SECONDS, degraded=degraded)
