#!/usr/bin/env python3
"""
generate_rss.py — Generate RSS feed from journal posts for averagejoematt.com.

Scans site/journal/posts/*/index.html, extracts metadata from <meta> tags,
and generates site/rss.xml.

Usage:
  python3 deploy/generate_rss.py           # dry-run
  python3 deploy/generate_rss.py --apply   # write rss.xml

Output: site/rss.xml
"""

import re
import argparse
from pathlib import Path
from datetime import datetime
from xml.sax.saxutils import escape

SITE_DIR = Path(__file__).resolve().parent.parent / "site"
JOURNAL_DIR = SITE_DIR / "journal" / "posts"
OUTPUT = SITE_DIR / "rss.xml"
SITE_URL = "https://averagejoematt.com"

# Week start dates (manually mapped since posts don't always have explicit dates)
WEEK_DATES = {
    "week-00": "2026-02-12",
    "week-01": "2026-02-19",
    "week-02": "2026-02-26",
    "week-03": "2026-03-05",
    "week-04": "2026-03-12",
    "week-05": "2026-03-19",
    "week-06": "2026-03-26",
    "week-07": "2026-04-02",
    "week-08": "2026-04-09",
    "week-09": "2026-04-16",
    "week-10": "2026-04-23",
}


def extract_meta(html: str) -> dict:
    """Extract title, description, and OG metadata from HTML."""
    meta = {}

    # <title>
    m = re.search(r'<title>(.*?)</title>', html)
    if m:
        meta["title"] = m.group(1).strip()

    # <meta name="description" content="...">
    m = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', html)
    if m:
        meta["description"] = m.group(1)

    # <meta property="og:title" content="...">
    m = re.search(r'<meta\s+property="og:title"\s+content="([^"]*)"', html)
    if m:
        meta["og_title"] = m.group(1)

    # <meta property="og:description" content="...">
    m = re.search(r'<meta\s+property="og:description"\s+content="([^"]*)"', html)
    if m:
        meta["og_description"] = m.group(1)

    return meta


def build_rss(posts: list) -> str:
    """Build RSS XML from list of post dicts."""
    now = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")

    items = []
    for p in posts:
        pub_date = datetime.strptime(p["date"], "%Y-%m-%d").strftime("%a, %d %b %Y 12:00:00 +0000")
        items.append(f"""    <item>
      <title>{escape(p['title'])}</title>
      <link>{escape(p['url'])}</link>
      <guid isPermaLink="true">{escape(p['url'])}</guid>
      <description>{escape(p['description'])}</description>
      <pubDate>{pub_date}</pubDate>
    </item>""")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>The Measured Life — Matthew Walker</title>
    <link>{SITE_URL}/journal/</link>
    <description>Weekly chronicles from 19 data sources. Every number, every failure, every week. Written by Elena Voss.</description>
    <language>en-us</language>
    <lastBuildDate>{now}</lastBuildDate>
    <atom:link href="{SITE_URL}/rss.xml" rel="self" type="application/rss+xml"/>
    <image>
      <url>{SITE_URL}/assets/images/og-image.png</url>
      <title>The Measured Life</title>
      <link>{SITE_URL}/journal/</link>
    </image>
{chr(10).join(items)}
  </channel>
</rss>
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not JOURNAL_DIR.exists():
        print(f"✗ Journal directory not found: {JOURNAL_DIR}")
        return

    posts = []
    for post_dir in sorted(JOURNAL_DIR.iterdir()):
        if not post_dir.is_dir():
            continue
        slug = post_dir.name
        if slug == "TEMPLATE" or slug.startswith("."):
            continue

        index_html = post_dir / "index.html"
        if not index_html.exists():
            continue

        html = index_html.read_text()
        meta = extract_meta(html)

        title = meta.get("og_title") or meta.get("title") or slug
        description = meta.get("og_description") or meta.get("description") or ""
        date = WEEK_DATES.get(slug)

        if not date:
            # Try to parse week number from slug
            m = re.match(r"week-(\d+)", slug)
            if m:
                week_num = int(m.group(1))
                # Calculate from journey start
                from datetime import timedelta
                start = datetime(2026, 2, 9)
                date = (start + timedelta(weeks=week_num, days=3)).strftime("%Y-%m-%d")  # Wednesdays
            else:
                date = "2026-03-01"  # fallback

        posts.append({
            "slug": slug,
            "title": title,
            "description": description,
            "date": date,
            "url": f"{SITE_URL}/journal/posts/{slug}/",
        })

    # Sort by date descending (newest first)
    posts.sort(key=lambda p: p["date"], reverse=True)

    print(f"Found {len(posts)} journal posts:")
    for p in posts:
        print(f"  {p['date']} — {p['title']}")

    rss = build_rss(posts)

    if args.apply:
        OUTPUT.write_text(rss)
        print(f"\n✓ RSS feed written to {OUTPUT.relative_to(SITE_DIR.parent)}")
    else:
        print(f"\nDry run — {len(posts)} posts would be in RSS. Use --apply to write.")


if __name__ == "__main__":
    main()
