#!/usr/bin/env python3
"""
v4_build_rss.py — generate site/rss.xml from the live chronicle posts.json.

Replaces the previously hand-maintained (and stale: wrong/duplicate pubDates)
static feed. Pulls the published chronicle index (the genesis-anchored live feed),
sorts newest-first, and emits a valid RSS 2.0 feed whose items deep-link to their
per-post permalink pages. A chronicle item's pubDate is its PUBLICATION instant —
the owner's approval, served as ``published_at`` by /api/chapters — never the post's
``date``, which is the week's data dateline (#5946: the feed dated an item three days
before it existed). An item with no recorded publication carries no pubDate (RSS 2.0
makes it optional): a missing date stays missing. lastBuildDate is stamped at
generation time.

stdlib only (urllib — matches the repo's no-external-HTTP convention). Run from
the repo root, then deploy site/ (sync_site_to_s3.sh calls this automatically):
    python3 scripts/v4_build_rss.py
"""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.request import urlopen

# Reuse the ONE word-boundary truncation helper (#1224) so the RSS excerpt cut lands on
# a word boundary with an ellipsis instead of a raw fixed-length mid-word slice (#1261).
# text_utils lives in lambdas/ (bundled into every function's package, #781); scripts run
# from the repo root, so put lambdas/ on sys.path — the same pattern the other lambdas-
# importing scripts use (e.g. scripts/publish_board_answer.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambdas"))
from common.text_utils import truncate_at_word  # noqa: E402
from common.utm import with_utm  # noqa: E402  — the ONE canonical outbound UTM tagger (#1621)
from content import (
    chapter_corrections,  # noqa: E402  — #6177: approved platform corrections + the persona disclosure
    chronicle_schema,  # noqa: E402  — #4191: a stored excerpt may still open on the envelope head
)

# /journal/posts.json is the live genesis-anchored chronicle feed (served from
# generated/journal/posts.json on S3).  The old /chronicle/posts.json was a
# dead season-1 snapshot frozen at the pre-reset experiment; don't use it.
SRC = "https://averagejoematt.com/journal/posts.json"
# The publication instant of each published chapter (#5946): /api/chapters serves
# ``published_at`` (the chronicle row's approved_at) per week, keyed here by the post url.
CHAPTERS_SRC = "https://averagejoematt.com/api/chapters"
# Matt-authored essays ("In my own words", #741) — a local committed manifest that
# deploys with site/; read from the tree (not the live URL) so a new post lands in
# the feed on the same deploy that publishes its permalink page.
BLOG_SRC = Path(__file__).resolve().parent.parent / "site" / "journal" / "blog.json"
BASE = "https://averagejoematt.com"
# #1672 (The Social Membrane): the Broadcast feed's own RSS, sourced from the live
# read-only /api/broadcast (cleared, origin:human posts). A SEPARATE feed — never
# merged into the chronicle feed, which would spam chronicle subscribers with social
# posts. Item <link>/<guid> point at the on-site permalink so RSS lands readers on the
# site (a reader surface, not a link farm — the story's whole point).
BROADCAST_SRC = f"{BASE}/api/broadcast"
BROADCAST_TITLE = "The Measured Life — Broadcast (averagejoematt)"
BROADCAST_DESC = "Matthew's own public posts, self-hosted — the platform's copy of his voice, with permalinks and a feed."
# #1377 (The Wrong Feed): a SEPARATE feed of graded failures, sourced from the live
# read-only /api/wrong obituaries. Every item is a deterministic verdict — never AI-
# asserted. Item <link>/<guid> point at the on-site moments permalink shell.
WRONG_SRC = f"{BASE}/api/wrong"
WRONG_TITLE = "The Measured Life — The Wrong Feed (averagejoematt)"
WRONG_DESC = (
    "Every graded failure, in public — what the model believed, the number that killed it, and what changed. Deterministic verdicts only."
)
OUT = Path("site/rss.xml")
# L-06: some readers probe /feed.xml instead of /rss.xml — emit an identical alias.
OUT_ALIAS = Path("site/feed.xml")
TITLE = "The Measured Life — averagejoematt"
DESC = (
    "The weekly chronicle of an ordinary life, measured in full — every number, "
    "every week, including the weeks it dips. Written by Elena Voss, an AI editorial persona (a language model writing "
    "from the platform's data); Matthew approves each chapter before it publishes."
)
# #6177 (owner ruling 2026-11-22 §6): four early chapters were published by the 48-hour rule, not by a separate approval,
# so the channel stops saying he approved each one. Read behind the ONE switch, www/src/lib/chapter_truth.js
# CHAPTER_TRUTH_LIVE (scripts/www_launch_switch.py reads the line as text); off = DESC above, byte for byte.
DESC_TRUE = (
    "The weekly chronicle of an ordinary life, measured in full — every number, "
    "every week, including the weeks it dips. Written by Elena Voss, an AI editorial persona (a language model writing "
    "from the platform's data). Earlier chapters were published either after Matthew's approval or automatically under "
    "a 48-hour rule he had authorised; a chapter now publishes only after he approves it."
)


def channel_desc(live: bool | None = None) -> str:
    """The channel description: DESC while the #6177 switch is off, DESC_TRUE when it is on."""
    if live is None:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from www_launch_switch import chapter_truth_live

        live = chapter_truth_live()
    return DESC_TRUE if live else DESC


HEADER_REVISIONS = Path(__file__).resolve().parent.parent / "www" / "src" / "lib" / "chapter_header_revisions.json"


def revised_excerpt(url: str | None, excerpt: str, live: bool | None = None, table: dict | None = None) -> str:
    """#6177 (owner ruling 2026-11-22 §10): an item whose served summary still begins with words an owner-approved
    replacement retires carries the replacement instead (www/src/lib/chapter_header_revisions.json, the table the site
    reads), after any October editor's note it opens with. Off, or no entry, or a summary that no longer begins with
    those words (a second edition's own): the excerpt unchanged. The item's guid and pubDate are never touched."""
    if live is None:
        live = channel_desc() == DESC_TRUE
    if not live:
        return excerpt
    if table is None:
        try:
            table = json.loads(HEADER_REVISIONS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return excerpt
    m = re.search(r"/(week-\d+)/?$", url or "")
    h = ((table or {}).get("headers") or {}).get(m.group(1)) if m else None
    if not isinstance(h, dict) or not h.get("replaces") or not h.get("text"):
        return excerpt
    lead = _EDITORS_NOTE.match(excerpt)
    rest = excerpt[lead.end() :].strip() if lead else excerpt
    if not rest.lstrip("*_ ").startswith(h["replaces"]):
        return excerpt
    return f"{lead.group(1)} {h['text']}" if lead else h["text"]


def rfc822(date_str: str) -> str:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=12, tzinfo=timezone.utc)
    return format_datetime(dt)


def rfc822_instant(iso: str) -> str | None:
    """An ISO-8601 instant (``2026-11-14T00:24:35+00:00`` / ``…Z``) as an RFC 822 date, or None."""
    try:
        dt = datetime.fromisoformat(str(iso).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return format_datetime(dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def published_at_by_url(chapters) -> dict[str, str]:
    """``{post url: published_at}`` for every published week /api/chapters serves with one."""
    weeks = chapters.get("weeks") if isinstance(chapters, dict) else None
    return {w["url"]: w["published_at"] for w in weeks or [] if isinstance(w, dict) and w.get("url") and w.get("published_at")}


_EDITORS_NOTE = re.compile(r"^(\*Editor[’']s note\b[^*]*\*)", re.IGNORECASE)  # the stored note is one emphasised paragraph


def corrections_by_url(chapters) -> dict[str, list[dict]]:
    """``{post url: [approved corrections, standing first]}`` from /api/chapters' ``corrections`` (#6177). A served
    ``null`` means the platform could not read them — the feed is not built without them (an approved correction is
    never dropped quietly); a payload without the field (a Site API from before #6177) has none."""
    if not isinstance(chapters, dict) or "corrections" not in chapters:
        return {}
    if chapters["corrections"] is None:
        print("❌ /api/chapters could not read the chapter corrections — not building a feed without them", file=sys.stderr)
        raise SystemExit(1)
    out: dict[str, list[dict]] = {}
    for c in chapters["corrections"]:
        if isinstance(c, dict) and chapter_corrections.CHAPTER_ID.match(str(c.get("chapter_id") or "")):
            out.setdefault(f"/journal/posts/{c['chapter_id']}/", []).append(c)
    for url, cs in out.items():
        cs.sort(key=lambda c: (c.get("superseded_by") is not None, [-ord(ch) for ch in str(c.get("dated_on") or "")]))
    return out


def item_description(excerpt: str, corrections: list[dict] | None = None, limit: int = 360) -> str:
    """One item's description (#6177): the newest standing approved correction first, in the platform's signature; an
    October 2026 editor's note kept word for word with the persona disclosure right after it; then the excerpt, cut at
    a word boundary (#1224) — the correction and the disclosure are never cut."""
    text = " ".join((excerpt or "").split())
    lead = ""
    m = _EDITORS_NOTE.match(text)
    if m and chapter_corrections.names_legacy_persona(m.group(1)):
        lead = f"{m.group(1)} ({chapter_corrections.PERSONA_DISCLOSURE})"
        text = text[m.end() :].strip()
    elif chapter_corrections.names_legacy_persona(text):
        lead = f"({chapter_corrections.PERSONA_DISCLOSURE})"
    standing = [c for c in corrections or [] if not c.get("superseded_by")]
    head = chapter_corrections.summary_line(standing[0]) if standing else ""
    fixed = " ".join(x for x in (head, lead) if x)
    rest = truncate_at_word(text, max(80, limit - len(fixed))) if text else ""
    return " ".join(x for x in (fixed, rest) if x)


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=False)


def _freshness_check(posts: list[dict]) -> None:
    """Regression guard: fail the build if the newest post is older than 45 days."""
    if not posts:
        print("❌ RSS freshness check: no posts found — is the feed reachable?", file=sys.stderr)
        raise SystemExit(1)
    newest_date = datetime.strptime(posts[0]["date"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(days=45)
    if newest_date < cutoff:
        print(
            f"❌ RSS freshness check: newest post {posts[0]['date']} is older than 45 days "
            f"— the feed is probably sourcing a dead path.",
            file=sys.stderr,
        )
        raise SystemExit(1)


def _blog_posts() -> list[dict]:
    """Matt-authored posts from the committed blog manifest (fail-soft: no file /
    no posts → empty list — the chronicle feed still builds)."""
    try:
        data = json.loads(BLOG_SRC.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [p for p in (data.get("posts") or []) if p.get("date") and p.get("title") and p.get("url")]


def build_broadcast_feed() -> int:
    """#1672 — write the /story/broadcast/ RSS feed from the live /api/broadcast.

    FAIL-SOFT and self-contained: never raises, and any problem (endpoint 404 before
    the site-api ships this route, network blip, non-broadcast-shaped body) yields a
    valid EMPTY feed rather than a broken build. The output path derives from ``OUT``
    so the test harness that redirects ``OUT`` to a tmp dir redirects this too (no
    real-tree writes during unit tests). Returns the item count."""
    out = OUT.parent / "story" / "broadcast" / "rss.xml"
    try:
        with urlopen(BROADCAST_SRC, timeout=20) as r:
            data = json.load(r)
    except Exception:  # noqa: BLE001 — the endpoint may not be live yet; empty feed is valid
        data = {}
    posts = data.get("items", []) if isinstance(data, dict) else []
    posts = [p for p in posts if p.get("date")]
    posts.sort(key=lambda p: p["date"], reverse=True)

    now = format_datetime(datetime.now(timezone.utc))
    items = []
    for p in posts:
        # Land readers on-site: <link>/<guid> = the on-site permalink, not the raw
        # third-party URL. The facade card itself still links out to the platform.
        permalink = p.get("permalink") or f"/story/broadcast/#{p.get('id', '')}"
        link = f"{BASE}{permalink}"
        tagged_link = with_utm(link, source="rss", medium="feed", campaign="broadcast")
        title = p.get("caption") or p.get("excerpt") or "Post"
        desc = truncate_at_word(" ".join((p.get("excerpt") or p.get("caption") or "").split()), 360)
        items.append(
            "    <item>\n"
            f"      <title>{esc(title)}</title>\n"
            f"      <link>{esc(tagged_link)}</link>\n"
            f'      <guid isPermaLink="true">{esc(link)}</guid>\n'
            f"      <description>{esc(desc)}</description>\n"
            f"      <pubDate>{rfc822(p['date'])}</pubDate>\n"
            "    </item>"
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "  <channel>\n"
        f"    <title>{esc(BROADCAST_TITLE)}</title>\n"
        f"    <link>{BASE}/story/broadcast/</link>\n"
        f"    <description>{esc(BROADCAST_DESC)}</description>\n"
        "    <language>en-us</language>\n"
        f"    <lastBuildDate>{now}</lastBuildDate>\n"
        f'    <atom:link href="{BASE}/story/broadcast/rss.xml" rel="self" type="application/rss+xml"/>\n'
        + ("\n".join(items) + "\n" if items else "")
        + "  </channel>\n"
        "</rss>\n"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(xml, encoding="utf-8")
    print(f"✅ wrote {out} — {len(items)} broadcast items")
    return len(items)


def build_wrong_feed() -> int:
    """#1377 — write the /method/wrong/ RSS feed from the live /api/wrong obituaries.

    FAIL-SOFT and self-contained (same contract as build_broadcast_feed): never raises,
    any problem yields a valid EMPTY feed. The output path derives from ``OUT`` so the
    test harness that redirects ``OUT`` redirects this too. Returns the item count."""
    out = OUT.parent / "method" / "wrong" / "rss.xml"
    try:
        with urlopen(WRONG_SRC, timeout=20) as r:
            data = json.load(r)
        if isinstance(data.get("data"), dict):
            data = data["data"]
    except Exception:  # noqa: BLE001 — endpoint blip / not live yet; empty feed is valid
        data = {}
    obits = data.get("obituaries", []) if isinstance(data, dict) else []
    obits = [o for o in obits if o.get("date") and o.get("believed") and o.get("id")]
    obits.sort(key=lambda o: o["date"], reverse=True)

    now = format_datetime(datetime.now(timezone.utc))
    items = []
    for o in obits:
        permalink = o.get("permalink") or f"/moments/wrong/{o['id']}/"
        link = f"{BASE}{permalink}"
        tagged_link = with_utm(link, source="rss", medium="feed", campaign="wrong")
        title = f"The AI was wrong: {o['believed']}"
        desc_bits = [o.get("number") or "", o.get("what_changed") or ""]
        desc = truncate_at_word(" — ".join(b for b in (s.strip() for s in desc_bits) if b), 360)
        items.append(
            "    <item>\n"
            f"      <title>{esc(title)}</title>\n"
            f"      <link>{esc(tagged_link)}</link>\n"
            f'      <guid isPermaLink="true">{esc(link)}</guid>\n'
            f"      <description>{esc(desc)}</description>\n"
            f"      <pubDate>{rfc822(o['date'])}</pubDate>\n"
            "    </item>"
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "  <channel>\n"
        f"    <title>{esc(WRONG_TITLE)}</title>\n"
        f"    <link>{BASE}/method/wrong/</link>\n"
        f"    <description>{esc(WRONG_DESC)}</description>\n"
        "    <language>en-us</language>\n"
        f"    <lastBuildDate>{now}</lastBuildDate>\n"
        f'    <atom:link href="{BASE}/method/wrong/rss.xml" rel="self" type="application/rss+xml"/>\n'
        + ("\n".join(items) + "\n" if items else "")
        + "  </channel>\n"
        "</rss>\n"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(xml, encoding="utf-8")
    print(f"✅ wrote {out} — {len(items)} wrong-feed items")
    return len(items)


def main() -> int:
    with urlopen(SRC, timeout=20) as r:
        data = json.load(r)
    posts = data.get("posts", data if isinstance(data, list) else [])
    posts = [p for p in posts if p.get("date") and p.get("title")]
    posts.sort(key=lambda p: p["date"], reverse=True)
    with urlopen(CHAPTERS_SRC, timeout=20) as r:  # #5946: a fetch failure fails the build, as SRC does
        chapters = json.load(r)
    published = published_at_by_url(chapters)
    corrections = corrections_by_url(chapters)  # #6177: approved platform corrections, keyed by the post url
    for p in posts:  # chronicle items only: an essay's `date` (blog.json) is its publication day
        p["_pub"] = rfc822_instant(published[p["url"]]) if p.get("url") in published else None

    # Freshness-guard the CHRONICLE feed only (it detects a dead source path);
    # Matt's essays are occasional by nature and must never trip it — merge after.
    _freshness_check(posts)
    posts += _blog_posts()
    posts.sort(key=lambda p: p["date"], reverse=True)

    now = format_datetime(datetime.now(timezone.utc))
    items = []
    for p in posts:
        # Use the per-post permalink URL from posts.json (e.g. /journal/posts/week-05/).
        # Week-number fragments (#3) collide across experiment cycles and aren't stable URLs.
        post_url = p.get("url") or f"/journal/posts/week-{str(p.get('week', '')).zfill(2)}/"
        link = f"{BASE}{post_url}"
        # #1621: the reader-facing <link> is UTM-tagged through the ONE canonical
        # helper so RSS-sourced signups are attributable. The <guid> below stays the
        # BARE canonical deliberately — guid is a feed reader's identity key, so
        # tagging it would change every historical item's identity and re-notify
        # every subscriber of every past post on the next build.
        tagged_link = with_utm(link, source="rss", medium="feed", campaign="chronicle")
        # #4191: the manifest excerpts written before the fix open on the quoted title and
        # the bracketed stat line; the feed description is the BODY, same derivation as the writer.
        excerpt = " ".join(chronicle_schema.body_markdown(p.get("excerpt") or "", p.get("title") or "").split())
        # Word-boundary truncation (#1224 helper) — never a mid-word slice (#1261); #6177: an approved correction leads,
        # a Margaret-signed editor's note is followed by the persona disclosure, and neither is cut.
        excerpt = revised_excerpt(p.get("url"), excerpt)  # #6177: the owner-approved replacement summary, behind the switch
        excerpt = item_description(excerpt, corrections.get(p.get("url") or ""), 360)
        pub = p["_pub"] if "_pub" in p else rfc822(p["date"])  # #5946: chronicle = published_at; essay = its date
        items.append(
            "    <item>\n"
            f"      <title>{esc(p['title'])}</title>\n"
            f"      <link>{esc(tagged_link)}</link>\n"
            f'      <guid isPermaLink="true">{esc(link)}</guid>\n'
            f"      <description>{esc(excerpt)}</description>\n" + (f"      <pubDate>{pub}</pubDate>\n" if pub else "") + "    </item>"
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "  <channel>\n"
        f"    <title>{esc(TITLE)}</title>\n"
        f"    <link>{BASE}/story/chronicle/</link>\n"
        f"    <description>{esc(channel_desc())}</description>\n"
        "    <language>en-us</language>\n"
        f"    <lastBuildDate>{now}</lastBuildDate>\n"
        f'    <atom:link href="{BASE}/rss.xml" rel="self" type="application/rss+xml"/>\n'
        "    <image>\n"
        f"      <url>{BASE}/assets/images/og-image.png</url>\n"
        f"      <title>{esc(TITLE)}</title>\n"
        f"      <link>{BASE}/story/chronicle/</link>\n"
        "    </image>\n" + "\n".join(items) + "\n"
        "  </channel>\n"
        "</rss>\n"
    )
    OUT.write_text(xml, encoding="utf-8")
    OUT_ALIAS.write_text(xml, encoding="utf-8")
    print(f"✅ wrote {OUT} + {OUT_ALIAS} — {len(items)} items, newest {posts[0]['date'] if posts else 'n/a'}")

    # #1672 — the Broadcast feed's own RSS, independent + fail-soft (a broadcast-feed
    # problem must never break the chronicle feed above).
    try:
        build_broadcast_feed()
    except Exception as e:  # noqa: BLE001 — belt-and-braces; the builder is already fail-soft
        print(f"⚠️  broadcast feed skipped (non-fatal): {e}", file=sys.stderr)
    # #1377 — the Wrong Feed's own RSS, independent + fail-soft (never breaks chronicle).
    try:
        build_wrong_feed()
    except Exception as e:  # noqa: BLE001 — belt-and-braces; the builder is already fail-soft
        print(f"⚠️  wrong feed skipped (non-fatal): {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
