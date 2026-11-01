#!/usr/bin/env python3
"""
v4_build_sitemap.py — regenerate sitemap.xml for the v4 indexable surface.

#3567: this used to enumerate `site/**/*.html` directly and filter with a
hand-maintained SKIP_TOP set — a SECOND, drifting vocabulary of "what's a
page" alongside `qa/qa_manifest.py` (the charter's ONE page registry,
#1426). Two concrete defects fell out of that duplication: `body.html` (the
essay permalink's verbatim prose FRAGMENT, `v4_build_journal.py`'s authoring
include — never a page in its own right) qualified as a real URL, and because
it's a non-index file, `url_for()` stripped its `.html` suffix into an
extensionless URL CloudFront 301s straight to a 404; and `/subscribe.html`
(the legacy meta-refresh stub) had no noindex, so both it and its target
`/subscribe/` shipped as separate sitemap entries.

Now: candidate URLs are exactly the paths in `qa/qa_manifest.MANIFEST` —
the registry every other QA surface already derives from — resolved to their
real file under site/, then filtered by the SAME live noindex check as
before (a page is indexable unless its own HTML asserts
`noindex`). A page absent from the registry (an authoring fragment, a
never-a-page artifact) is structurally never a candidate, regardless of what
exists on disk. Self-maintaining: add a page to the registry (or its own
generator, for the Evidence/essay facets the registry derives FROM) and it's
sitemap-eligible; nothing here needs a second edit.

Also fetches live /journal/posts.json and adds each published post URL (priority
0.8); these pages live in S3 generated/ and are absent from site/, so sitemap is
the only way search engines discover them. As a side-effect, injects a <noscript>
fallback link-list into site/story/chronicle/index.html so crawlers without JS
can follow the same links.

#5534 (the v9 cut-over) — ONE writer per sitemap file. This generator writes the KEPT site/ pages to
`site/sitemap-site.xml` on every deploy. `site/sitemap.xml` has two writers across time but one at a
time, arbitrated by the committed switch `live_at_root` in www/owned_paths.json: while it is false the
v9 build is a /next/v9/ preview and THIS script also writes sitemap.xml (as it always has); once it is
true the v9 build writes sitemap.xml (its sitemap index, www/scripts/postbuild.mjs) and this script
leaves that file alone. robots.txt lists both files. A page the v9 build owns (`owner: www` in the
registry) is in the build's sitemap, never this one.

Writes site/sitemap-site.xml (+ site/sitemap.xml before the cut-over). Run from repo root:
    python3 scripts/v4_build_sitemap.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import v4_apply_chrome as _apply_chrome  # noqa: E402 — the post-build chrome normalizer (#3721)
import v4_chrome  # noqa: E402 — #4604: HELD_UNTIL_RULED, the pages held out of the sitemap

SITE = Path("site")
BASE = "https://averagejoematt.com"
POSTS_URL = f"{BASE}/journal/posts.json"
CHRONICLE_HUB = SITE / "story" / "chronicle" / "index.html"

_NOSCRIPT_START = "<!-- noscript-posts:start -->"
_NOSCRIPT_END = "<!-- noscript-posts:end -->"


def _page_registry():
    """qa/qa_manifest.MANIFEST — the ONE page registry (#1426/#3567)."""
    sys.path.insert(0, str(REPO_ROOT))
    from qa import qa_manifest  # noqa: E402 — local import, path just inserted

    return qa_manifest.MANIFEST


def v9_owns_sitemap_xml() -> bool:
    """#5534: once the v9 build owns `/`, it owns sitemap.xml too (www/owned_paths.json: live_at_root)."""
    sys.path.insert(0, str(REPO_ROOT))
    from deploy import www_owned_paths  # noqa: E402 — the one reader of the switch

    try:
        return www_owned_paths.live_at_root()
    except (OSError, ValueError):
        return False


def file_for_path(path: str) -> Path:
    """A registry `path` ("/x/y/" or a bare file like "/404.html") -> its real
    file under site/. Registry paths are always root-relative with a leading
    slash; a trailing slash means a directory index."""
    rel = path.strip("/")
    if not rel or path.endswith("/"):
        return SITE / rel / "index.html" if rel else SITE / "index.html"
    return SITE / rel


def url_for_path(path: str) -> str:
    return f"{BASE}{path}"


def indexable(p: Path) -> bool:
    """A registered page is indexable unless its OWN HTML asserts noindex —
    the live source of truth (cockpit/mind/subscribe-confirm/404 all bake
    this in already; #3567 adds it to the subscribe.html stub too)."""
    try:
        html = p.read_text(encoding="utf-8")
    except OSError:
        return False
    # #4588: a reference copy of a replaced layout asserts `noindex,nofollow`; the prefix match sees both forms.
    return 'name="robots" content="noindex' not in html


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
    _apply_chrome.write_page(CHRONICLE_HUB, html)  # #3721


def registry_urls() -> list[str]:
    """Every indexable URL in the page registry — the #3567 derivation. A path
    the registry doesn't know about (a fragment, an off-tree artifact) is
    structurally never a candidate; a path whose real file is missing (an
    offline/partial build) is skipped, never fabricated. A path held until the
    owner rules (`v4_chrome.HELD_UNTIL_RULED`, #4604) is never a candidate."""
    urls = []
    for p in _page_registry():
        if p["path"] in v4_chrome.HELD_UNTIL_RULED:
            continue  # #4604: held until the owner's per-page ruling — out even if its noindex goes missing
        if p.get("owner") == "www":
            continue  # #5534: the v9 build's page — in the build's own sitemap, never this one
        f = file_for_path(p["path"])
        if not f.exists():
            continue
        if not indexable(f):
            continue
        urls.append(url_for_path(p["path"]))
    return sorted(set(urls))


def main() -> int:
    if not (SITE / "index.html").exists():
        print("error: run from repo root.", file=sys.stderr)
        return 2
    today = date.today().isoformat()
    urls = registry_urls()
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
    body = "\n".join(lines) + "\n"
    (SITE / "sitemap-site.xml").write_text(body, encoding="utf-8")
    written = "site/sitemap-site.xml"
    if v9_owns_sitemap_xml():
        print("site/sitemap.xml left to the v9 build (www/owned_paths.json live_at_root=true, #5534).")
    else:
        (SITE / "sitemap.xml").write_text(body, encoding="utf-8")
        written += " + site/sitemap.xml"
    print(
        f"wrote {written} — {len(urls)} registry URL(s) + {len(post_urls)} post URL(s) "
        f"(derived from qa/qa_manifest.MANIFEST, #3567; noindex pages excluded live)."
    )

    _update_chronicle_noscript(posts)
    if posts:
        print(f"updated chronicle hub noscript — {len(posts)} post link(s).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
