#!/usr/bin/env python3
"""scripts/publish_snapshot_story.py — the Human Story's data file (HS1), written ONLY for a dark build.

The owner's brief of 2026-11-08: "Proceed with the Human Story timeline and episode index using only already-approved
published material. Held installments and audio remain excluded." The timeline and the episode index are built dark,
behind ``WEB_STORY=1`` (the same switch as ``www/src/lib/story_dark.js``): with the switch off the producer neither
fetches nor writes this file, and the snapshot is byte-identical to one made without this module. The deploy workflow
never sets the switch.

WHAT COUNTS AS APPROVED AND PUBLISHED — fail closed. An installment is in the index only when ALL of these hold:
  * it is a PUBLIC chapter object in this snapshot (the producer's visibility partition already ran) whose ``status`` is
    ``published`` and whose ``approved`` record is the owner's, via ``chronicle-approve`` (the published manifest
    ``/journal/posts.json`` — scripts/publish_snapshot.py::_live_chapters);
  * it is a PROGRAM week (``week`` >= 1). The prologue is not a program week, and ``/api/chapters`` records no
    approval state for it — unknown is excluded;
  * ``/api/chapters`` (lambdas/web/site_api_chapters.py — the platform's own per-week state, read from the chronicle
    partition and the manifest) serves that week as ``published`` with the SAME url and the same title;
  * it is not on the owner's exclusion list below (EXCLUDED_WEEKS / EXCLUDED_IDS / EXCLUDED_DATES).
Anything else — held, draft, changes requested, skipped, pending, tombstoned, pre-genesis, a route that did not answer —
is excluded, and only its id and the reason are recorded (never a title, excerpt or body).

WHAT IS NEVER CARRIED: audio of any kind (no episode id, audio url, transcript, duration or byline — the Panel, the
narrated episodes, the debriefs and read-aloud are all out), excerpts and bodies (the existing chapter pages carry the
text as published), and anything about the journal, State of Mind or the video diary. A week without an installment is
just that: the file carries no held / skipped / pending distinction and no drafted-at clock.

No new endpoint, no non-public read: ``/api/chapters`` is a public Site API route the snapshot already reads.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

STORY_ENV = "WEB_STORY"
CHAPTERS_PATH = "/api/chapters"
FIXTURE_NAME = "story_chapters_api.json"  # the committed sample of the /api/chapters payload (fixture mode)
ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# The owner's exclusions (brief 2026-11-08), held even if the platform's state ever reads otherwise.
EXCLUDED_WEEKS = {
    2: "owner brief 2026-11-08: the Week 2 installment is excluded",
    8: "owner brief 2026-11-08: the Week 8 draft is excluded",
    9: "owner brief 2026-11-08: the Week 9 draft is excluded",
}
EXCLUDED_IDS = {
    "week-02": "owner brief 2026-11-08: the unlisted /journal/posts/week-02/ is excluded",
}
EXCLUDED_DATES = {
    "2026-05-16": "owner brief 2026-11-08: a held, non-current-phase draft",
    "2026-09-01": "owner brief 2026-11-08: a held, non-current-phase draft",
}
EXCLUDED_URL_PARTS = ("/journal/posts/week-02/",)

ABSENT_STORY = {
    "state": "absent",
    "absent_text": "The platform did not serve the week list for this snapshot.",
    "source": [CHAPTERS_PATH, "/journal/posts.json"],
    "as_of": None,
    "genesis": None,
    "story_weeks": [],
    "installments_index": [],
    "story_exclusions": [],
}


def story_live() -> bool:
    """The committed go-live switch, www/src/lib/story_dark.js STORY_LIVE, read as text (scripts/www_launch_switch.py; unreadable = dark)."""
    import sys

    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import www_launch_switch  # noqa: E402 — the one Python reader of the go-live constants

    return www_launch_switch.story_live()


def story_enabled(env: dict | None = None, live: bool | None = None) -> bool:
    """The Python twin of www/src/lib/story_dark.js::storyEnabled — on when committed live, or by the literal WEB_STORY=1."""
    if (story_live() if live is None else live) is True:
        return True
    return (os.environ if env is None else env).get(STORY_ENV) == "1"


def _int(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _approved_by_owner(c: dict) -> bool:
    a = c.get("approved")
    return isinstance(a, dict) and a.get("by") == "owner" and a.get("via") == "chronicle-approve"


def exclusion_reason(c: dict, served: dict[int, dict]) -> str | None:
    """Why chapter object ``c`` is NOT in the index, or None when it is approved and published. Fail closed: every
    unmet condition is a reason; the explicit owner exclusions are checked first."""
    week = _int(c.get("week"))
    cid = str(c.get("id") or "")
    url = c.get("url_legacy")
    if cid in EXCLUDED_IDS:
        return EXCLUDED_IDS[cid]
    if isinstance(url, str) and any(part in url for part in EXCLUDED_URL_PARTS):
        return EXCLUDED_IDS["week-02"]
    if week in EXCLUDED_WEEKS:
        return EXCLUDED_WEEKS[week]
    if str(c.get("date") or "")[:10] in EXCLUDED_DATES:
        return EXCLUDED_DATES[str(c.get("date"))[:10]]
    if c.get("visibility") not in (None, "public"):
        return "not a public object"
    if c.get("status") != "published":
        return f"status {c.get('status')!r}: not a published installment"
    if not _approved_by_owner(c):
        return "no owner approval recorded (chronicle-approve)"
    if week is None or week < 1:
        return "not a program week: /api/chapters records no approval state for it"
    row = served.get(week)
    if row is None:
        return "/api/chapters does not serve this week"
    if row.get("status") != "published":
        return "/api/chapters does not serve this week as published"
    if not isinstance(url, str) or not url or row.get("url") != url:
        return "/api/chapters serves a different url for this week"
    if row.get("title") != c.get("title"):
        return "/api/chapters serves a different title for this week"
    return None


def compose(chapters_api: Any, public: dict[str, list[dict]]) -> dict:
    """The data file from the served ``/api/chapters`` payload and the public chapter objects; ABSENT when the
    payload is missing or malformed (then nothing is included — unknown approval state is excluded)."""
    if not isinstance(chapters_api, dict) or not isinstance(chapters_api.get("weeks"), list):
        return json.loads(json.dumps(ABSENT_STORY))
    genesis = chapters_api.get("genesis")
    if not isinstance(genesis, str) or not ISO_DAY.match(genesis):
        return json.loads(json.dumps(ABSENT_STORY))
    served: dict[int, dict] = {}
    weeks: list[dict] = []
    for w in chapters_api["weeks"]:
        if not isinstance(w, dict):
            continue
        n, a, b = _int(w.get("week")), str(w.get("start") or ""), str(w.get("end") or "")
        if n is None or n < 1 or not ISO_DAY.match(a) or not ISO_DAY.match(b) or a > b or n in served:
            continue
        served[n] = w
        weeks.append({"week": n, "start": a, "end": b, "chapter_id": None})
    index: list[dict] = []
    exclusions: list[dict] = []
    for c in sorted(public.get("chapter", []), key=lambda o: (_int(o.get("week")) or 0, str(o.get("id")))):
        reason = exclusion_reason(c, served)
        if reason:
            exclusions.append({"ref": str(c.get("id")), "reason": reason})
            continue
        index.append({"chapter_id": c["id"], "week": c["week"], "date": str(c["date"])[:10], "title": c["title"]})
    by_week = {i["week"]: i["chapter_id"] for i in index}
    for w in weeks:
        w["chapter_id"] = by_week.get(w["week"])
    return {
        "state": "ok",
        "absent_text": None,
        "source": [CHAPTERS_PATH, "/journal/posts.json"],
        "as_of": chapters_api.get("as_of") if isinstance(chapters_api.get("as_of"), str) else None,
        "genesis": genesis,
        "story_weeks": sorted(weeks, key=lambda w: w["week"]),
        "installments_index": index,
        "story_exclusions": exclusions,
    }


def live_story(get: Callable[[str], Any], public: dict[str, list[dict]], log: Callable[[str], None] = print) -> dict:
    """Fetch the public week list; a failure leaves the story's data file absent (the pages then say so)."""
    try:
        return compose(get(CHAPTERS_PATH), public)
    except Exception as exc:  # noqa: BLE001 — any fetch/parse failure is an absent record, never a partial one
        log(f"  story week list unavailable ({exc}); story.json written absent")
        return json.loads(json.dumps(ABSENT_STORY))


def fixture_story(fixtures_dir: str, public: dict[str, list[dict]]) -> dict:
    """The committed sample of the served payload (content/fixtures/story_chapters_api.json)."""
    path = os.path.join(fixtures_dir, FIXTURE_NAME)
    if not os.path.exists(path):
        return json.loads(json.dumps(ABSENT_STORY))
    with open(path, encoding="utf-8") as fh:
        return compose(json.load(fh), public)


def validate(payload: dict, public: dict[str, list[dict]]) -> dict:
    """Every indexed installment and every week's chapter_id must be a public chapter in this snapshot. Raises
    ValueError (the caller maps it to SchemaError) otherwise."""
    if payload.get("state") != "ok":
        return payload
    ids = {o["id"] for o in public.get("chapter", [])}
    for i in payload.get("installments_index") or []:
        if i.get("chapter_id") not in ids:
            raise ValueError(f"story.json: installment {i.get('chapter_id')!r} is not a public chapter")
        if not ISO_DAY.match(str(i.get("date") or "")) or not isinstance(i.get("title"), str):
            raise ValueError(f"story.json: installment {i.get('chapter_id')!r} needs a date and a title")
    for w in payload.get("story_weeks") or []:
        if w.get("chapter_id") is not None and w["chapter_id"] not in ids:
            raise ValueError(f"story.json: week {w.get('week')} names a chapter that is not public")
    return payload
