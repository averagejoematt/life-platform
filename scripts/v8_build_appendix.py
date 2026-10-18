#!/usr/bin/env python3
"""v8_build_appendix.py — generate /next/v8/appendix/ from scripts/v8_appendix_pages.json (#4586).

The appendix is one plain list at the foot of the preview: every live page that is off the
usual path, so that nothing is deleted and nothing has to sit in a menu. It is a reference
list, never a second navigation: rows are grouped by what a page IS (at most five kinds, a
small label each, Tools first) and sorted by title inside a kind. A jump list of plain links
at the top reaches each kind (#4580 round 1: 69 rows over nine screens had no anchors). A
row that is the earlier version of a v8 page says so; a page whose own name is an internal
codename is listed under a plain title with the codename in the small print. A kind with no
rows yet prints its `empty` sentence — the "Replaced layouts" kind lists the reference copies
the cut-over makes (ruling 2026-10-18), and is empty until it copies the first.

The page is a kit page (docs/design/v8/README.md): `site/assets/css/clean.css` only, `ck-`
classes only, no page-scoped style and no script beyond the theme boot. Each row is the
kit's two-line row — a name, then one soft line — because a title beside a sentence does
not fit a phone column.

The data file is the source. Change a row there, then run this; never edit the HTML.
`tests/test_v8_appendix_4586.py` fails a hand edit, a row whose page does not exist, a held
page that slipped in, and a sitemap address that is in neither list.

Run from repo root:  python3 scripts/v8_build_appendix.py          (write)
                     python3 scripts/v8_build_appendix.py --check  (exit 1 if stale)
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(__file__).resolve().parent / "v8_appendix_pages.json"
OUT = ROOT / "site" / "next" / "v8" / "appendix" / "index.html"

MAX_KINDS = 5
TITLE = "Appendix — Average Joe Matt"
DESCRIPTION = "Everything else on the site, in one list."
# The share image is the wordmark card until the daily mark is ruled (#4646, owner 2026-10-18).
OG_IMAGE = "https://averagejoematt.com/assets/og/wordmark-1200x630.png"
OG_IMAGE_ALT = "Average Joe Matt. 327 to 185, in public. Every coach call checked."
INTRO = "Everything else on the site, in one list, by kind. These pages are older or more detailed than the ones you came from."
EARLIER_DESIGN = "These pages still use the site’s earlier design."


def esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def load(path: Path = DATA) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def problems(data: dict) -> list[str]:
    """Everything wrong with the data file's own shape. [] when it can be rendered."""
    out = []
    kinds = [k["key"] for k in data.get("kinds", [])]
    if not 1 <= len(kinds) <= MAX_KINDS:
        out.append(f"{len(kinds)} kinds — the appendix groups by at most {MAX_KINDS}")
    for k in data.get("kinds", []):
        if not str(k.get("key", "")).strip() or not str(k.get("label", "")).strip():
            out.append(f"{k!r}: a kind has a `key` and a `label`")
        if not any(r.get("kind") == k.get("key") for r in data.get("pages", [])) and not str(k.get("empty", "")).strip():
            out.append(f"{k.get('key')}: a kind with no rows carries an `empty` sentence")
    seen = set()
    for row in data.get("pages", []):
        url = row.get("url", "")
        for field in ("url", "title", "line", "kind"):
            if not str(row.get(field, "")).strip():
                out.append(f"{url or row!r}: no `{field}`")
        if row.get("kind") not in kinds:
            out.append(f"{url}: kind {row.get('kind')!r} is not one of {kinds}")
        if not (url.startswith("/") and url.endswith("/")):
            out.append(f"{url}: a row's url is a site path that starts and ends with a slash")
        if url in seen:
            out.append(f"{url}: listed twice")
        seen.add(url)
    return out


def grouped(data: dict) -> list[tuple[str, list[dict]]]:
    """[(label, rows sorted by title)] in the file's kind order; a kind with no rows is dropped
    here (its `empty` sentence is rendered by `kinds_to_render`)."""
    return [(label, rows) for _key, label, rows, _empty in kinds_to_render(data) if rows]


def kinds_to_render(data: dict) -> list[tuple[str, str, list[dict], str]]:
    """[(key, label, rows sorted by title, empty sentence)] in the file's kind order, every kind."""
    out = []
    for kind in data["kinds"]:
        rows = sorted((r for r in data["pages"] if r["kind"] == kind["key"]), key=lambda r: r["title"].lower())
        out.append((kind["key"], kind["label"], rows, str(kind.get("empty", ""))))
    return out


def row_line(row: dict) -> str:
    """The row's small print: its line, then that it is an earlier version of a v8 page
    (`earlier_of` names the page) or that the page calls itself by a codename."""
    parts = [row["line"]]
    if row.get("earlier_of"):
        parts.append(f"Earlier version of “{row['earlier_of']}”, superseded.")
    if row.get("codename"):
        parts.append(f"Called “{row['codename']}” on the page.")
    return " ".join(parts)


def _row(row: dict) -> str:
    return (
        f'        <li><a class="ck-coach__name ck-link" href="{esc(row["url"])}">{esc(row["title"])}</a>'
        f'<span class="ck-coach__job">{esc(row_line(row))}</span></li>'
    )


def _group(key: str, label: str, rows: list[dict], empty: str) -> str:
    body = (
        f"""      <ul class="ck-coach">
{chr(10).join(_row(r) for r in rows)}
      </ul>"""
        if rows
        else f"""      <p class="ck-soft">{esc(empty)}</p>"""
    )
    return f"""    <section class="ck-section" id="kind-{esc(key)}">
      <p class="ck-label">{esc(label)}</p>
{body}
    </section>"""


def _jump_list(data: dict) -> str:
    links = " · ".join(
        f'<a class="ck-link" href="#kind-{esc(key)}">{esc(label)}</a>' for key, label, _rows, _empty in kinds_to_render(data)
    )
    return f'      <p class="ck-soft">{links}</p>'


def render(data: dict) -> str:
    groups = "\n\n".join(_group(*kind) for kind in kinds_to_render(data))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <title>{esc(TITLE)}</title>
  <meta name="description" content="{esc(DESCRIPTION)}">
  <meta name="robots" content="noindex,nofollow">
  <link rel="canonical" href="https://averagejoematt.com/next/v8/appendix/">
  <meta property="og:title" content="{esc(TITLE)}">
  <meta property="og:description" content="{esc(DESCRIPTION)}">
  <meta property="og:type" content="website">
  <meta property="og:url" content="https://averagejoematt.com/next/v8/appendix/">
  <meta property="og:image" content="{OG_IMAGE}">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:image:alt" content="{esc(OG_IMAGE_ALT)}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{esc(TITLE)}">
  <meta name="twitter:description" content="{esc(DESCRIPTION)}">
  <meta name="twitter:image" content="{OG_IMAGE}">
  <meta name="twitter:image:alt" content="{esc(OG_IMAGE_ALT)}">
  <meta name="theme-color" media="(prefers-color-scheme: light)" content="#FFFFFF">
  <meta name="theme-color" media="(prefers-color-scheme: dark)" content="#0D0F10">
  <link rel="icon" href="/favicon.ico">
  <link rel="preload" href="/assets/fonts/clean/geist-latin.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="stylesheet" href="/assets/css/clean.css">
  <script src="/assets/js/boot_theme.js"></script>
</head>
<!-- GENERATED by scripts/v8_build_appendix.py from scripts/v8_appendix_pages.json. Do not edit by hand. -->
<body data-ck-page="appendix" data-ck-base="/next/v8/" data-ck-ready="1">
<div class="ck-page">
  <a class="ck-skip" href="#main">Skip to content</a>
  <header class="ck-header">
    <a class="ck-header__back" id="ck-back" href="/next/v8/">← Average Joe Matt</a>
  </header>

  <main class="ck-main" id="main">
    <section class="ck-section ck-section--tight">
      <h1>Appendix</h1>
      <p class="ck-soft">{esc(INTRO)}</p>
      <p class="ck-soft">{esc(EARLIER_DESIGN)}</p>
{_jump_list(data)}
    </section>

{groups}
  </main>

  <footer class="ck-footer">
    <nav class="ck-footer__nav" aria-label="Site">
      <a href="/next/v8/start/">Start here</a>
      <a href="/next/v8/story/">The story</a>
      <a href="/next/v8/coaches/">The AI coaches</a>
      <a href="/next/v8/built/">How it’s built</a>
      <a href="/next/v8/appendix/">Appendix</a>
      <a href="https://github.com/averagejoematt/life-platform" rel="noopener">The code</a>
    </nav>
  </footer>
  <p class="ck-small">Preview.</p>
</div>
</body>
</html>
"""


def main(argv: list[str]) -> int:
    data = load()
    bad = problems(data)
    if bad:
        print("v8_build_appendix: the data file cannot be rendered:")
        for b in bad:
            print(f"  - {b}")
        return 1
    page = render(data)
    if "--check" in argv:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != page:
            print(f"v8_build_appendix: {OUT.relative_to(ROOT)} is stale — run python3 scripts/v8_build_appendix.py")
            return 1
        print("v8_build_appendix: up to date")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"v8_build_appendix: wrote {OUT.relative_to(ROOT)} ({len(data['pages'])} pages in {len(grouped(data))} kinds)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
