#!/usr/bin/env python3
"""
v4_build_sitemap.py — regenerate sitemap.xml for the v4 indexable surface.

After the cutover the old sitemap listed pre-cutover URLs that now 301. This
emits only what should be indexed: the Story (/), the Evidence index + topic
pages, and root System pages — EXCLUDING anything noindex (the Cockpit /now and
the entire /legacy tree) plus assets/api/config/data and the 404.

Scans the real site/ tree, so it self-maintains as Evidence topics are added.
Writes site/sitemap.xml. Run from repo root:  python3 scripts/v4_build_sitemap.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

SITE = Path("site")
BASE = "https://averagejoematt.com"
SKIP_TOP = {"legacy", "now", "assets", "api", "config", "data", "404"}


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


def main() -> int:
    if not (SITE / "index.html").exists():
        print("error: run from repo root.", file=sys.stderr)
        return 2
    today = date.today().isoformat()
    urls = sorted({url_for(p) for p in SITE.rglob("*.html") if indexable(p)})
    # Story root first, then the rest.
    urls.sort(key=lambda u: (u != f"{BASE}/", u))

    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        prio = "1.0" if u == f"{BASE}/" else ("0.8" if u.rstrip("/").endswith("/evidence") else "0.6")
        lines.append(f"  <url><loc>{u}</loc><lastmod>{today}</lastmod>" f"<priority>{prio}</priority></url>")
    lines.append("</urlset>")
    (SITE / "sitemap.xml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote site/sitemap.xml — {len(urls)} indexable URL(s) (Story + Evidence + system; " f"/now and /legacy excluded as noindex).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
