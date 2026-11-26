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
     weeks: [{week, start, end, status, date, title, url, label, drafted_at, reason,
              + published_at, covers_start, covers_end on a published week only}]}

  * ``published``  — the manifest carries a post for the week dated on or before today:
                     ``date``, ``title``, ``url``, ``label`` are the manifest's. A published week ALSO
                     serves (and only a published week does) ``published_at`` — the chronicle row's
                     ``approved_at``, the moment the owner approved it, null when the row has none —
                     and ``covers_start`` / ``covers_end``, the days the chapter is about, read off the
                     post's ``stats_line`` ("Day 60 to Day 66 · …", day N = genesis + N−1), null when
                     the line names no day span (the old "Weight: … | …" header). ``date`` is the
                     chronicle's DATA date, not the publication date (2026-11-14: Week 10 is dated 10 November,
                     covers 4–10 November and was approved on 13 November Pacific).
  * ``held``       — a chronicle row exists for the week in a non-published status
                     (``draft`` / ``changes_requested``): ONLY ``status`` and ``drafted_at``
                     (the row's ``generated_at``) are served. No title, excerpt or body — a
                     draft is the owner's until he approves it (#5520: approval stays his).
  * ``skipped``    — the week has ended with no row and no post: ``reason`` is the pending
                     marker's (``chronicle_store._set_chronicle_pending``, the writer's own
                     words for why no week landed) when the marker names this week, else
                     "no chapter was published".
  * ``pending``    — the week in progress, with nothing yet: the draft day has not come.
  * ``retired``    — (#6178, owner ruling 2026-11-22 §4; behind ``CHAPTERS_RETIRED_STATE``, default OFF) a draft
                     existed and the OWNER decided it will not be published: the row's status is ``retired``. Like a
                     held week, ONLY ``status`` and ``drafted_at`` are served. With the switch off a retired row is
                     served as ``held`` (a draft exists and is unpublished — true either way), never as skipped.
                     #6194: with the switch on, a skipped week's default reason is "no chapter was written" (there is
                     no row, so no draft) instead of "no chapter was published", which a retired week is too.

HELD IS ONE NEUTRAL STATE (#6178). A held week carries no ``reason``: the stored statuses do not say whether the owner
sent a week back (weeks 8 and 9 carry ``changes_requested`` written as a lock, not as his rejection) or whether it only
awaits his approval (a draft the audit refuses is not merely waiting). The page says one true line for every held week.
A row in a status this route does not know is a draft that exists and is unpublished: it is served as ``held``, never
as ``skipped`` ("no chapter was published" would erase that a draft exists).

THE CORRECTIONS (#6177). ``corrections`` lists every APPROVED dated public correction to a published chapter
(``content.chapter_corrections.public_view`` over the chronicle partition's ``CHAPTER_CORRECTION#`` rows): keyed by
the chapter's v9 id (the prologue included), platform-signed, with its approval history; a superseded one stays,
marked ``superseded_by``. An unapproved proposal is never read into the response. When the rows cannot be read the
field is ``null`` and ``corrections_error`` says so — never ``[]``, so a reader cannot take a failed read for "no
corrections" and drop a published correction from the site.

THE EDITIONS (#6193), only while ``content.chapter_editions.LIVE`` is True. Off, the rows are never read and the field
is never in the response — byte-identical to the response before #6193. On, ``editions`` lists, per chapter, the latest
APPROVED second (or later) edition that passes every publication gate at serve time (``chapter_editions.public_view``
with this request's ``narrative_publication.is_tainted``), with its approved archival rendering of the first edition when
one passes too, and ``edition_withdrawals`` lists the owner's dated withdrawals (#6193 B7); a failed read is ``null`` +
``editions_error``, never ``[]``. The weeks, their dates and their urls are
never changed by an edition: the chapter keeps its first-published date, and nothing here reaches a feed or a sender.

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

import re
from datetime import timedelta
from typing import Any, Callable

from common.pacific_time import pacific_today, parse_day_key
from content import chapter_corrections, chapter_editions, private_call_check

from web.site_api_common import EXPERIMENT_START, USER_ID, _error, _load_s3_json, _ok, _query_source, logger, table

SOURCE = "/api/chapters"
CACHE_SECONDS = 600
WEEK_DAYS = 7
MANIFEST_KEY = "generated/journal/posts.json"
NO_CHAPTER = "no chapter was published"
#: #6194: with the retired state on, a skipped week (no row in the store: no draft exists) says what is true of it beside
#: the retired weeks, whose drafts were written and also not published — "published" no longer tells the two apart.
NO_CHAPTER_WRITTEN = "no chapter was written"
UNAVAILABLE = "The chapter list is not served right now."
HELD_STATUSES = ("draft", "changes_requested")
#: #6178: the row status the owner sets when he decides a drafted week will not be published (equal to
#: content.autopublish_audit.RETIRED_STATUS, pinned by a test — this route does not import the audit's dependencies).
RETIRED_STATUS = "retired"
#: The switch that lets ``retired`` reach the page (default off): the site-api Lambda's environment.
RETIRED_SWITCH_ENV = "CHAPTERS_RETIRED_STATE"
#: Every status a week can be served with.
WEEK_STATUSES = ("published", "held", "skipped", "pending", "retired")


def retired_state_on(env=None) -> bool:
    """The #6178 switch, default OFF: only on/1/true turn it on."""
    import os

    return str((os.environ if env is None else env).get(RETIRED_SWITCH_ENV) or "").strip().lower() in ("on", "1", "true")


#: The chronicle row attributes this route reads — never the title or body of an unpublished week. ``approved_at``
#: is served for a published week only.
ROW_PROJECTION = ("date", "week_number", "status", "generated_at", "approved_at")
#: The covered-days span a stats_line opens with ("Day 60 to Day 66 · 292.6 lbs …").
_DAY_SPAN = re.compile(r"^\s*Day\s+(\d+)\s+to\s+Day\s+(\d+)\b")


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
    g, t = parse_day_key(genesis), parse_day_key(today)
    out: list[dict] = []
    if g is None or t is None:
        return out
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
    d, g = parse_day_key(str(day or "")[:10]), parse_day_key(genesis)
    if d is None or g is None:
        return None
    n = (d - g).days
    return n // WEEK_DAYS + 1 if n >= 0 else None


def row_week(row: dict, genesis: str) -> int | None:
    """Which program week a chronicle row is about: its ``week_number``, else the week its date falls in."""
    wk = _int(row.get("week_number"))
    if wk is not None and wk >= 1:
        return wk
    day = row.get("date") or str(row.get("sk") or "").replace("DATE#", "")
    return week_of_day(day, genesis)


def covered_days(stats_line: Any, genesis: str) -> tuple[str | None, str | None]:
    """``(covers_start, covers_end)`` — the ISO days a chapter's ``stats_line`` says it covers ("Day A to Day B",
    day N = genesis + N−1), else ``(None, None)``: no span is guessed from the chapter's date."""
    m = _DAY_SPAN.match(stats_line) if isinstance(stats_line, str) else None
    g = parse_day_key(genesis)
    if m is None or g is None:
        return None, None
    a, b = int(m.group(1)), int(m.group(2))
    if a < 1 or b < a:
        return None, None
    return (g + timedelta(days=a - 1)).isoformat(), (g + timedelta(days=b - 1)).isoformat()


def _approved_at(row: dict | None) -> str | None:
    value = (row or {}).get("approved_at")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _newer(row: dict, prev: dict | None) -> bool:
    return prev is None or str(row.get("generated_at") or "") > str(prev.get("generated_at") or "")


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


def compose(rows: list, journal: dict | None, genesis: str, today: str, *, retired_on: bool = False) -> dict:
    """The document — pure: the chronicle rows, the manifest, genesis and today in; the weeks out. ``retired_on`` is the
    #6178 switch (the handler reads it from the environment)."""
    posts = _published_posts(journal, today)
    marker = held_marker(journal)
    marker_week = _int((marker or {}).get("week")) if marker else None
    by_week: dict[int, dict] = {}
    published_rows: dict[int, dict] = {}  # the newest PUBLISHED row per week: its approved_at is the publication
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        wk = row_week(row, genesis)
        if wk is None:
            continue
        if _newer(row, by_week.get(wk)):
            by_week[wk] = row
        if str(row.get("status") or "").strip().lower() == "published" and _newer(row, published_rows.get(wk)):
            published_rows[wk] = row
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
            covers = covered_days(post.get("stats_line"), genesis)
            entry.update(published_at=_approved_at(published_rows.get(wk)), covers_start=covers[0], covers_end=covers[1])
        elif row is not None and row_status == "published":
            # Published in the store, not yet in the manifest (a publish in flight): the state is the store's.
            entry.update(status="published", date=str(row.get("date") or "")[:10] or None)
            entry.update(published_at=_approved_at(row), covers_start=None, covers_end=None)
        elif row is not None and row_status == RETIRED_STATUS and retired_on:
            entry.update(status="retired", drafted_at=row.get("generated_at"))
        elif row is not None:
            # draft / changes_requested, a retired row while the switch is off, or a status this route does not know: a
            # draft exists and is unpublished. One neutral state, no reason (#6178).
            entry.update(status="held", drafted_at=row.get("generated_at"))
        elif bin_["end"] >= today:
            entry["status"] = "pending"
        else:
            entry["status"] = "skipped"
            fallback = NO_CHAPTER_WRITTEN if retired_on else NO_CHAPTER  # #6194: the wire is unchanged while the switch is off
            entry["reason"] = (marker.get("display") or marker.get("reason")) if (marker and marker_week == wk) else fallback
        weeks.append(entry)
    return {
        "genesis": genesis,
        "as_of": today,
        "week_length_days": WEEK_DAYS,
        "weeks": weeks,
        "held": marker,
        # the wire is unchanged while the switch is off: `retired` is counted only when it can be served
        "counts": {s: sum(1 for w in weeks if w["status"] == s) for s in WEEK_STATUSES if s != RETIRED_STATUS or retired_on},
        "source": SOURCE,
    }


def _read_manifest() -> dict | None:
    doc = _load_s3_json(MANIFEST_KEY, "chapters")
    return doc if isinstance(doc, dict) and doc else None


def _read_corrections() -> list:
    """Every ``CHAPTER_CORRECTION#`` row of the chronicle partition (proposed and approved; ``public_view`` keeps the approved)."""
    from boto3.dynamodb.conditions import Key

    kw: dict = {
        "KeyConditionExpression": Key("pk").eq(chapter_corrections.pk(USER_ID)) & Key("sk").begins_with(chapter_corrections.SK_PREFIX)
    }
    out: list = []
    while True:
        resp = table.query(**kw)
        out.extend(resp.get("Items") or [])
        if not resp.get("LastEvaluatedKey"):
            return out
        kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def corrections_field(read_corrections: Callable[[], list]) -> dict:
    """``{"corrections": [...]}`` — or ``{"corrections": None, "corrections_error": ...}`` when the rows cannot be read."""
    try:
        return {"corrections": chapter_corrections.public_view(read_corrections(), log=logger.warning)}
    except Exception as e:  # noqa: BLE001 — a failed read is said, never served as "no corrections"
        logger.error(f"[chapters] corrections read failed: {type(e).__name__}: {e}")
        return {"corrections": None, "corrections_error": "the corrections could not be read for this response"}


def _read_editions() -> list:
    """Every ``CHAPTER_EDITION#`` row of the chronicle partition (#6193; ``public_view`` keeps the approved, gated ones)."""
    from boto3.dynamodb.conditions import Key

    kw: dict = {"KeyConditionExpression": Key("pk").eq(chapter_editions.pk(USER_ID)) & Key("sk").begins_with(chapter_editions.SK_PREFIX)}
    out: list = []
    while True:
        resp = table.query(**kw)
        out.extend(resp.get("Items") or [])
        if not resp.get("LastEvaluatedKey"):
            return out
        kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _is_tainted(text: str) -> bool:
    """The withheld graded record (#6111) OR a withheld coach output's words (#6193, ``web.withheld_outputs``); raises when
    either cannot be read, and the edition gate then withholds (fail closed)."""
    from web import narrative_publication, withheld_outputs  # noqa: PLC0415

    return narrative_publication.is_tainted(text) or withheld_outputs.matcher(withheld_outputs.load(table))(text)


_CALLS_CACHE: dict = {"at": None, "calls": None, "snap": None}
_CALLS_TTL_S = 900  # = publication_snapshot.TTL_S: the two publication reads age together


def _snapshot_call_rows() -> Any:
    """#6271: ``(key, rows)`` of the coach partitions' calls and asks from the request's complete publication snapshot
    (``publication_snapshot.coach_call_rows``), or None — no snapshot, or one partition without a fresh good read."""
    from web import publication_snapshot  # noqa: PLC0415

    try:
        publication_snapshot.complete()  # the request's freshness check (once per request; the edition gate needs it anyway)
        return publication_snapshot.coach_call_rows()
    except Exception:  # noqa: BLE001 — the check then reads every partition itself, exactly as before #6271
        return None


def _private_calls() -> Any:
    """#6199: the calls the publication policy classifies, read from the RAW table (cached ``_CALLS_TTL_S``); None when
    they cannot be read — every edition is then withheld (fail closed).

    #6271: the coach partitions' call and ask rows are the ones the request's publication snapshot already read whole
    (the same partitions, prefixes and order), so the set is built from them and only the forecast partition is read
    again — the second full read of every coach partition was a third of an uncached /api/chapters. The set is rebuilt
    whenever the snapshot re-reads a coach partition, so it is never older than the snapshot's own TTL. Without a fresh
    snapshot the check reads every partition itself, as before."""
    import time  # noqa: PLC0415

    now = time.monotonic()
    snap = _snapshot_call_rows()
    held = _CALLS_CACHE["calls"] is not None and _CALLS_CACHE["at"] is not None and now - _CALLS_CACHE["at"] < _CALLS_TTL_S
    if held and (snap is None or _CALLS_CACHE["snap"] == snap[0]):
        return _CALLS_CACHE["calls"]
    try:
        calls = private_call_check.load(table) if snap is None else private_call_check.load(table, coach_rows=snap[1])
    except Exception as e:  # noqa: BLE001
        logger.error(
            f"[chapters] #6199 private-call check: the coach calls could not be read ({type(e).__name__}: {e}) — editions withheld"
        )
        return None
    _CALLS_CACHE.update(at=now, calls=calls, snap=None if snap is None else snap[0])
    return calls


def editions_field(
    read_editions: Callable[[], list], tainted: Callable[[str], bool] = _is_tainted, private_calls: Callable[[], Any] = _private_calls
) -> dict:
    """``{}`` while the switch is off (the reader is never called); else ``{"editions": [...]}`` — or ``{"editions": None,
    "editions_error": ...}`` when the rows cannot be read."""
    if not chapter_editions.LIVE:
        return {}
    try:
        from privacy import privacy_guard  # noqa: PLC0415 — the chronicle's publish gate (fail-closed on no vocabulary)

        rows = read_editions()
        view = chapter_editions.public_view(
            rows,
            tainted=tainted,
            private_calls=private_call_check.for_text(private_calls()),
            filter_hits=privacy_guard.find_violations,
            log=logger.warning,
        )
        # #6193 B7: the owner's withdrawals (chapter, what, number, day — never a note), so a verifier can say "withdrawn";
        # the key is present only when there is one, so with none the response is exactly the one before it
        gone = chapter_editions.public_withdrawals(rows)
        return {"editions": view, **({"edition_withdrawals": gone} if gone else {})}
    except Exception as e:  # noqa: BLE001 — a failed read is said, never served as "no editions"
        logger.error(f"[chapters] editions read failed: {type(e).__name__}: {e}")
        return {"editions": None, "editions_error": "the editions could not be read for this response"}


def handle_chapters(
    event,
    *,
    query: Callable = _query_source,
    read_manifest: Callable[[], dict | None] = _read_manifest,
    read_corrections: Callable[[], list] = _read_corrections,
    read_editions: Callable[[], list] = _read_editions,
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
    doc = compose(rows, journal, genesis, today, retired_on=retired_state_on())
    doc.update(corrections_field(read_corrections))
    doc.update(editions_field(read_editions))  # #6193: {} while chapter_editions.LIVE is False
    degraded = None
    if journal is None:
        degraded = "journal manifest unreadable — published weeks may read as skipped"
        logger.error(f"[chapters] {degraded}")
    return _ok(doc, cache_seconds=CACHE_SECONDS, degraded=degraded)
