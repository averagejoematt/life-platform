#!/usr/bin/env python3
"""
v4_build_sitemap.py — regenerate sitemap.xml for the v4 indexable surface.

After the cutover the old sitemap listed pre-cutover URLs that now 301. This
emits only what should be indexed: the Story (/), the Evidence index + topic
pages, and root System pages — EXCLUDING anything noindex (the Cockpit /now and
the entire /legacy tree) plus assets/api/config/data and the 404.

Scans the real site/ tree, so it self-maintains as Evidence topics are added.
Also fetches live /journal/posts.json and adds each published post URL (priority
0.8); these pages live in S3 generated/ and are absent from site/, so sitemap is
the only way search engines discover them. As a side-effect, injects a <noscript>
fallback link-list into site/story/chronicle/index.html so crawlers without JS
can follow the same links.

Writes site/sitemap.xml. Run from repo root:  python3 scripts/v4_build_sitemap.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from urllib.request import urlopen

SITE = Path("site")
BASE = "https://averagejoematt.com"
POSTS_URL = f"{BASE}/journal/posts.json"
CHRONICLE_HUB = SITE / "story" / "chronicle" / "index.html"

# NB: "data" is NOT skipped — it's now the Data pillar (HTML pages). The JSON data
# files under /data/ aren't *.html so they're never picked up regardless.
SKIP_TOP = {"legacy", "now", "assets", "api", "config", "404"}

_NOSCRIPT_START = "<!-- noscript-posts:start -->"
_NOSCRIPT_END = "<!-- noscript-posts:end -->"


def url_for(p: Path) -> str:
    rel = p.relative_to(SITE)
    if rel.name == "index.html":
        parent = rel.parent.as_posix()
        return f"{BASE}/" if parent == "." else f"{BASE}/{parent}/"
    return f"{BASE}/{rel.with_suffix('').as_posix()}"


def indexable(p: Path) -> bool:
    rel = p.relative_to(SITE)
    top = rel.parts[0] if len(rel.parts) > 1 else rel.name
    if top in SKIP_TOP or rel.name == "404.html":
        return False
    try:
        html = p.read_text(encoding="utf-8")
    except OSError:
        return False
    return 'name="robots" content="noindex"' not in html


def _fetch_posts() -> list[dict]:
    """Return published posts from the live posts.json, newest-first."""
    try:
        with urlopen(POSTS_URL, timeout=15) as r:
            data = json.load(r)
        posts = data.get("posts", data) if isinstance(data, dict) else data
        published = [p for p in posts if p.get("url") and p.get("status", "published") == "published" and p.get("date")]
        published.sort(key=lambda p: p["date"], reverse=True)
        return published
    except Exception as e:
        print(f"  ⚠️  could not fetch posts ({e}) — skipping post URLs", file=sys.stderr)
        return []


def _update_chronicle_noscript(posts: list[dict]) -> None:
    """Inject a <noscript> static link-list into the chronicle hub HTML so
    crawlers without JS can follow post links. Idempotent — replaces the
    block between the sentinel comments on every run."""
    if not posts or not CHRONICLE_HUB.exists():
        return
    html = CHRONICLE_HUB.read_text(encoding="utf-8")
    items = "\n".join(f'    <li><a href="{BASE}{p["url"]}">{p.get("title", p["url"])}</a></li>' for p in posts)
    block = f'{_NOSCRIPT_START}\n<noscript><ul class="dx-list-static">\n{items}\n</ul></noscript>\n{_NOSCRIPT_END}'
    if _NOSCRIPT_START in html:
        start = html.index(_NOSCRIPT_START)
        end = html.index(_NOSCRIPT_END) + len(_NOSCRIPT_END)
        html = html[:start] + block + html[end:]
    else:
        # First time: inject right after the dx-list element
        marker = '<ul class="dx-list" data-dx-list aria-label="Entries"></ul>'
        if marker in html:
            html = html.replace(marker, marker + "\n      " + block)
    CHRONICLE_HUB.write_text(html, encoding="utf-8")


def main() -> int:
    if not (SITE / "index.html").exists():
        print("error: run from repo root.", file=sys.stderr)
        return 2
    today = date.today().isoformat()
    urls = sorted({url_for(p) for p in SITE.rglob("*.html") if indexable(p)})
    # Story root first, then the rest.
    urls.sort(key=lambda u: (u != f"{BASE}/", u))

    posts = _fetch_posts()
    post_urls = {f"{BASE}{p['url'].rstrip('/')}/" for p in posts}

    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        prio = "1.0" if u == f"{BASE}/" else ("0.8" if u.rstrip("/").endswith(("/data", "/protocols", "/coaching", "/story")) else "0.6")
        lines.append(f"  <url><loc>{u}</loc><lastmod>{today}</lastmod>" f"<priority>{prio}</priority></url>")
    for u in sorted(post_urls):
        lines.append(f"  <url><loc>{u}</loc><lastmod>{today}</lastmod><priority>0.8</priority></url>")
    lines.append("</urlset>")
    (SITE / "sitemap.xml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"wrote site/sitemap.xml — {len(urls)} static URL(s) + {len(post_urls)} post URL(s) "
        f"(Story + Evidence + system; /now and /legacy excluded as noindex)."
    )

    _update_chronicle_noscript(posts)
    if posts:
        print(f"updated chronicle hub noscript — {len(posts)} post link(s).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
