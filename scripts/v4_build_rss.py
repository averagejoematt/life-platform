#!/usr/bin/env python3
"""
v4_build_rss.py — generate site/rss.xml from the live chronicle posts.json.

Replaces the previously hand-maintained (and stale: wrong/duplicate pubDates)
static feed. Pulls the published chronicle index (the genesis-anchored live feed),
sorts newest-first, and emits a valid RSS 2.0 feed whose items deep-link to their
per-post permalink pages. pubDate is derived from each post's own date, and
lastBuildDate is stamped at generation time.

stdlib only (urllib — matches the repo's no-external-HTTP convention). Run from
the repo root, then deploy site/ (sync_site_to_s3.sh calls this automatically):
    python3 scripts/v4_build_rss.py
"""
from __future__ import annotations

import html
import json
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
from text_utils import truncate_at_word  # noqa: E402
from utm import with_utm  # noqa: E402  — the ONE canonical outbound UTM tagger (#1621)

# /journal/posts.json is the live genesis-anchored chronicle feed (served from
# generated/journal/posts.json on S3).  The old /chronicle/posts.json was a
# dead season-1 snapshot frozen at the pre-reset experiment; don't use it.
SRC = "https://averagejoematt.com/journal/posts.json"
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
OUT = Path("site/rss.xml")
# L-06: some readers probe /feed.xml instead of /rss.xml — emit an identical alias.
OUT_ALIAS = Path("site/feed.xml")
TITLE = "The Measured Life — averagejoematt"
DESC = (
    "The weekly chronicle of an ordinary life, measured in full — every number, "
    "every week, including the weeks it dips. Written by Elena Voss."
)


def rfc822(date_str: str) -> str:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=12, tzinfo=timezone.utc)
    return format_datetime(dt)


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
    return [p for p in data.get("posts", []) if p.get("date") and p.get("title") and p.get("url")]


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


def main() -> int:
    with urlopen(SRC, timeout=20) as r:
        data = json.load(r)
    posts = data.get("posts", data if isinstance(data, list) else [])
    posts = [p for p in posts if p.get("date") and p.get("title")]
    posts.sort(key=lambda p: p["date"], reverse=True)

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
        excerpt = " ".join((p.get("excerpt") or "").split())
        # Word-boundary truncation (#1224 helper) — never a mid-word slice (#1261).
        excerpt = truncate_at_word(excerpt, 360)
        items.append(
            "    <item>\n"
            f"      <title>{esc(p['title'])}</title>\n"
            f"      <link>{esc(tagged_link)}</link>\n"
            f'      <guid isPermaLink="true">{esc(link)}</guid>\n'
            f"      <description>{esc(excerpt)}</description>\n"
            f"      <pubDate>{rfc822(p['date'])}</pubDate>\n"
            "    </item>"
        )

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        "  <channel>\n"
        f"    <title>{esc(TITLE)}</title>\n"
        f"    <link>{BASE}/story/chronicle/</link>\n"
        f"    <description>{esc(DESC)}</description>\n"
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
