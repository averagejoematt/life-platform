#!/usr/bin/env python3
"""
v4_build_rss.py — generate site/rss.xml from the live chronicle posts.json.

Replaces the previously hand-maintained (and stale: wrong/duplicate pubDates)
static feed. Pulls the published chronicle index, sorts newest-first, and emits
a valid RSS 2.0 feed whose items deep-link into the v4 Story hub
(/story/chronicle/#<week>). pubDate is derived from each post's own date, and
lastBuildDate is stamped at generation time.

stdlib only (urllib — matches the repo's no-external-HTTP convention). Run from
the repo root, then deploy site/ (sync_site_to_s3.sh calls this automatically):
    python3 scripts/v4_build_rss.py
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.request import urlopen

SRC = "https://averagejoematt.com/chronicle/posts.json"
BASE = "https://averagejoematt.com"
OUT = Path("site/rss.xml")
TITLE = "The Measured Life — averagejoematt"
DESC = ("The weekly chronicle of an ordinary life, measured in full — every number, "
        "every week, including the weeks it dips. Written by Elena Voss.")


def rfc822(date_str: str) -> str:
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=12, tzinfo=timezone.utc)
    return format_datetime(dt)


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=False)


def main() -> int:
    with urlopen(SRC, timeout=20) as r:
        data = json.load(r)
    posts = data.get("posts", data if isinstance(data, list) else [])
    posts = [p for p in posts if p.get("date") and p.get("title")]
    posts.sort(key=lambda p: p["date"], reverse=True)

    now = format_datetime(datetime.now(timezone.utc))
    items = []
    for p in posts:
        link = f"{BASE}/story/chronicle/#{p.get('week')}"
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
        "    </image>\n"
        + "\n".join(items) + "\n"
        "  </channel>\n"
        "</rss>\n"
    )
    OUT.write_text(xml, encoding="utf-8")
    print(f"✅ wrote {OUT} — {len(items)} items, newest {posts[0]['date'] if posts else 'n/a'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
