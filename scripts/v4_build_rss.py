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

# /journal/posts.json is the live genesis-anchored chronicle feed (served from
# generated/journal/posts.json on S3).  The old /chronicle/posts.json was a
# dead season-1 snapshot frozen at the pre-reset experiment; don't use it.
SRC = "https://averagejoematt.com/journal/posts.json"
BASE = "https://averagejoematt.com"
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


def main() -> int:
    with urlopen(SRC, timeout=20) as r:
        data = json.load(r)
    posts = data.get("posts", data if isinstance(data, list) else [])
    posts = [p for p in posts if p.get("date") and p.get("title")]
    posts.sort(key=lambda p: p["date"], reverse=True)

    _freshness_check(posts)

    now = format_datetime(datetime.now(timezone.utc))
    items = []
    for p in posts:
        # Use the per-post permalink URL from posts.json (e.g. /journal/posts/week-05/).
        # Week-number fragments (#3) collide across experiment cycles and aren't stable URLs.
        post_url = p.get("url") or f"/journal/posts/week-{str(p.get('week', '')).zfill(2)}/"
        link = f"{BASE}{post_url}"
        excerpt = " ".join((p.get("excerpt") or "").split())
        if len(excerpt) > 360:
            excerpt = excerpt[:357].rstrip() + "…"
        items.append(
            "    <item>\n"
            f"      <title>{esc(p['title'])}</title>\n"
            f"      <link>{esc(link)}</link>\n"
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
