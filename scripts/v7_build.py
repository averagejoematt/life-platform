#!/usr/bin/env python3
"""v7_build.py — the ONE generator for the nine v7 pages (#4182, plan D3).

    python3 scripts/v7_build.py --base /next/            # preview → site/next/**
    python3 scripts/v7_build.py --base /next/ --check    # exit 1 if the committed shells drift
    python3 scripts/v7_build.py --base / --allow-live    # the cut-over (writes the live nine)

WHAT IT IS. averagejoematt.com's v7 is nine pages (CONCEPT §3): Home · Today · This week
· His numbers · The coaches (the bottom bar) and What he's trying · Who he is · Under the
hood · Follow (the footer tier). They keep their existing URLs (plan D2) and are poured by
this one builder from one page table, so "build beside, then cut over" is one flag:
`--base /next/` writes the preview subtree `site/next/<path>/index.html` (served at
`https://averagejoematt.com/next/<path>/` by the existing `deploy/sync_site_to_s3.sh`,
which syncs every `*.html` under `site/`), and `--base /` writes the live nine.

WHAT IT WRITES THROUGH. Every page goes through `v4_apply_chrome.write_page` — the
normalizer-as-writer contract (#3721) — so the glossary pass runs at build time and the
chrome pass (`v4_apply_chrome.py --check`) sees a page it never needs to touch: a v7 shell
carries `nav.v7-bar` / `footer.v7-foot`, not `.doors` / `.site-foot`, and the pass keys
on those two classes. The bar and footer come from `v4_chrome.doors_nav()` /
`site_footer()` under `v4_chrome.EDITION = "v7"` (plan D5) — the same call sites the live
pages use, so the cut-over re-pour is the same switch.

WHAT IT MUST NEVER EMIT. A `/next/assets/…` reference: `deploy/hash_site_assets.py`
rewrites every `/assets/(js|css)/<name>` in every non-legacy HTML file to its hashed root
name, so v7 assets are flat, root-absolute, `v7_`-prefixed (`/assets/css/v7.css`,
`/assets/js/v7_shell.js`) in preview and after (plan D4). Machine vocabulary on a reader
page (CONCEPT §2 rule 5): the ruled glossary terms are a shrink-only ledger
(`tests/test_site_vocabulary_registry.py`), and `tests/site_text.reader_pages()` sweeps
`site/next/**` like any other page — by design, so the preview is held to the rule from
its first commit.

THE SCAFFOLD (2026-09-26). Each page body is an honest placeholder: the page's one job
and the day of the build week it is due. No data, no fake copy. The per-page templates
land with each page's lane.

THE CUT-OVER (ADR-157, 2026-09-27). `--base / --allow-live` is what `deploy/sync_site_to_s3.sh`
runs on every sync — this is the ONE writer of the nine (`v4_apply_chrome.write_page`
refuses the v4 generators at those paths). On the live base each page also carries:
  * its OG/Twitter card (`OG_CARD` — the existing daily cards at their existing URLs; the
    two sentinel bakers overwrite Home's and Today's title/description with the served
    numbers at deploy, exactly as they did on v4);
  * for /coaching/ /story/ /data/ /protocols/, the #1395 <noscript> static core baked by
    `scripts/v4_proof.v7_static_block` (links unwrapped — the reach rule) with today's
    "as of" stamp, which `scripts/check_proof_freshness.py` reads fail-closed at deploy;
  * the empty `<!-- home-proof -->` / `<!-- cockpit-proof -->` sentinel pairs the two
    bakers fill in place.
  * the syndication block (`v4_chrome.syndication_links()` — every feed the hook registry
    has not declared dark, #3615), on every page of the nine as on every v4 shell before.
`--check` masks those volatile regions (the proof blocks, the sentinel contents, every
og:/twitter: meta value) on both sides before comparing, so a shell whose numbers moved
is still "in sync" while a shell whose STRUCTURE drifted is not.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import v4_apply_chrome  # noqa: E402
import v4_chrome  # noqa: E402
import v4_proof  # noqa: E402 — the static cores + the OG helpers (ADR-157)
from v7 import (
    coaches,  # noqa: E402
    follow,  # noqa: E402
    home,  # noqa: E402
    hood,  # noqa: E402
    numbers,  # noqa: E402
    today,  # noqa: E402
    tries,  # noqa: E402
    week,  # noqa: E402
    who,  # noqa: E402
)

SITE_DIR = os.path.join(ROOT, "site")

# The nine, in CONCEPT §3 order. (page path under the base, title, the one job, build day)
# The job lines are the reader's words — no ruled glossary term appears in them, and the
# vocabulary census (tests/test_site_vocabulary_registry.py) holds that.
PAGES = (
    ("", "Home", "The case so far.", "Monday"),
    ("cockpit/", "Today", "Matthew’s morning screen, open to anyone.", "Monday"),
    ("story/", "This week", "The instalment: his own words, the finding, what comes next.", "Tuesday"),
    ("data/", "His numbers", "The evidence: weight, sleep, eating, training, blood tests.", "Tuesday"),
    ("coaching/", "The coaches", "The witnesses, on the record.", "Tuesday"),
    ("protocols/", "What he’s trying", "What he takes and tries, what it should move, how we’d know.", "Wednesday"),
    ("story/about/", "Who he is", "The subject, in the first person.", "Wednesday"),
    ("method/", "Under the hood", "How a number is made, and the corrections column.", "Wednesday"),
    ("subscribe/", "Follow", "The numbers every Sunday; the write-up every Wednesday.", "Wednesday"),
)

SITE_NAME = "averagejoematt"

# The OG card each page points its og:image at — the EXISTING daily cards
# (lambdas/web/og_image_lambda.py PAGES), at their existing URLs; no card is added. Where
# no bespoke card exists (the numbers, the coaches, who he is, under the hood, follow) the
# generic og-home card is the honest closest — the same choice the v4 hubs made.
# tests/test_og_card_coverage.py holds that every drawn card is still referenced by some
# non-legacy page; the archive topic pages keep serving theirs.
OG_CARD = {
    "": "og-home",
    "cockpit/": "og-character",
    "story/": "og-chronicle",
    "data/": "og-home",
    "coaching/": "og-home",
    "protocols/": "og-experiments",
    "story/about/": "og-home",
    "method/": "og-home",
    "subscribe/": "og-home",
}

# The volatile regions `--check` masks (see the module docstring).
_VOLATILE = (
    re.compile(r"<!-- home-proof:start -->.*?<!-- home-proof:end -->", re.DOTALL),
    re.compile(r"<!-- cockpit-proof:start -->.*?<!-- cockpit-proof:end -->", re.DOTALL),
    re.compile(r'<noscript><section class="proof-static.*?</section></noscript>', re.DOTALL),
    re.compile(r'(<meta (?:property|name)="(?:og|twitter):[a-z:_]+" content=")[^"]*(")'),
)


def volatile_mask(page_html: str) -> str:
    """The shell with its data-carrying regions blanked — what `--check` compares."""
    out = page_html
    for rx in _VOLATILE[:3]:
        out = rx.sub("", out)
    return _VOLATILE[3].sub(r"\1\2", out)


def og_tags(page: str, title: str, job: str, canonical: str) -> str:
    """The page's OG/Twitter meta block (one tag per line, two-space indent)."""
    og = v4_proof._og_tags(canonical, f"{title} — {SITE_NAME}", job, f"{OG_CARD[page]}.png")
    lines = []
    for (kind, key), value in og.items():
        attr = "property" if kind == "property" else "name"
        lines.append(f'  <meta {attr}="{key}" content="{_esc(value)}">\n')
    return "".join(lines)


# The per-page body templates (scripts/v7/<page>.py — CSS, JS, body(base)). A page with no
# entry keeps the scaffold body below; each page's lane adds ONE line here.
BODIES = {
    "cockpit/": today,
    "": home,
    "story/": week,
    "coaching/": coaches,
    "story/about/": who,
    "protocols/": tries,
    "method/": hood,
    "data/": numbers,
    "subscribe/": follow,
}


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def render_page(page: str, title: str, job: str, due: str, base: str) -> str:
    """One v7 shell. `base` is the viewer prefix ("/" live, "/next/" preview)."""
    preview = base != "/"
    robots = '  <meta name="robots" content="noindex,nofollow">\n' if preview else ""
    notice = '  <p class="v7-preview">preview — the live site is at <a href="/">/</a></p>\n' if preview else ""
    mast = v4_chrome.v7_masthead(base)
    bar = v4_chrome.doors_nav(current_door=page)
    foot = v4_chrome.site_footer()
    canonical = f"https://averagejoematt.com{base}{page}"
    mod = BODIES.get(page)
    # The four doors' static cores ride on the live base only: the preview is noindex and
    # the smoke's static-core guard reads the six manifest pages at their live URLs.
    static_core = f"    {v4_proof.v7_static_block(page)}\n" if not preview and page in v4_proof.V7_STATIC_PAGES else ""
    page_css = f'  <link rel="stylesheet" href="{mod.CSS}">\n' if mod else ""
    page_js = f'  <script type="module" src="{mod.JS}"></script>\n' if mod else ""
    main_inner = (
        mod.body(base)
        if mod
        else (
            f"    <h1>{_esc(title)}</h1>\n"
            f'    <p class="v7-job">{_esc(job)}</p>\n'
            f'    <p class="v7-placeholder">Not built yet — {_esc(due)} of the build week.</p>\n'
        )
    )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en" class="v7">\n'
        "<head>\n"
        '  <meta charset="UTF-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">\n'
        f"  <title>{_esc(title)} — {SITE_NAME}</title>\n"
        f'  <meta name="description" content="{_esc(job)}">\n'
        f"{robots}"
        f'  <link rel="canonical" href="{canonical}">\n'
        f"{og_tags(page, title, job, canonical)}"
        f"{v4_chrome.syndication_links()}\n"
        f"{v4_chrome.head_chrome()}\n"
        '  <link rel="stylesheet" href="/assets/css/fonts.css">\n'
        '  <link rel="stylesheet" href="/assets/css/tokens.css">\n'
        '  <link rel="stylesheet" href="/assets/css/v7.css">\n'
        f"{page_css}"
        '  <script src="/assets/js/boot_theme.js"></script>\n'
        "</head>\n"
        '<body class="v7-body">\n'
        '  <a class="skip" href="#main">Skip to the page</a>\n'
        f"{notice}"
        f"  {mast}\n"
        f'  <main id="main" class="v7-main">\n'
        f"{main_inner}"
        f"{static_core}"
        "  </main>\n"
        f"  {foot}\n"
        f"  {bar}\n"
        '  <script type="module" src="/assets/js/v7_shell.js"></script>\n'
        f"{page_js}"
        "</body>\n"
        "</html>\n"
    )


def out_dir_for(base: str, out: str | None) -> str:
    if out:
        return os.path.abspath(out)
    return os.path.join(SITE_DIR, base.strip("/")) if base != "/" else SITE_DIR


def build(base: str, out: str | None = None, check: bool = False) -> list[str]:
    """Write (or, with `check`, compare) the nine shells. Returns the drifted/written paths."""
    if not base.startswith("/") or not base.endswith("/"):
        raise SystemExit(f"--base must start and end with '/', got {base!r}")
    v4_chrome.EDITION = "v7"
    v4_chrome.V7_BASE = base
    root = out_dir_for(base, out)
    touched: list[str] = []
    for (
        page,
        title,
        job,
        due,
    ) in PAGES:
        path = os.path.join(root, page.replace("/", os.sep), "index.html")
        raw = render_page(page, title, job, due, base)
        # Plan D4: assets are root-absolute. Under a non-root base a `{base}assets/` reference
        # would be rewritten by the hasher to a hash that does not exist there; under the
        # root base "/assets/" IS the root-absolute form, so only the preview spelling is
        # the defect (found the first time --base / ran, at the cut-over).
        if "/next/assets/" in raw or (base != "/" and f"{base}assets/" in raw):
            raise SystemExit(f"{path}: a v7 page referenced an asset under the base — assets are root-absolute (plan D4)")
        if check:
            expected, *_ = v4_apply_chrome.rewrite(raw, self_path=base + page)
            current = open(path, encoding="utf-8").read() if os.path.exists(path) else None
            if current is None or volatile_mask(current) != volatile_mask(expected):
                touched.append(path)
            continue
        v4_apply_chrome.write_page(path, raw)
        touched.append(path)
    return touched


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the nine v7 pages (plan D3).")
    ap.add_argument("--base", required=True, help="viewer prefix: /next/ (preview) or / (live)")
    ap.add_argument("--out", help="output directory (default: site/<base> — site/next for /next/, site/ for /)")
    ap.add_argument("--check", action="store_true", help="exit 1 if any committed shell differs from a fresh build (no writes)")
    ap.add_argument("--allow-live", action="store_true", help="required with --base / — it overwrites the live nine (the cut-over)")
    args = ap.parse_args()
    if args.base == "/" and not args.out and not args.allow_live and not args.check:
        print("refusing: --base / writes the LIVE nine pages — pass --allow-live if this is the cut-over", file=sys.stderr)
        return 2
    touched = build(args.base, args.out, check=args.check)
    if args.check:
        if touched:
            print("CHECK FAILED: these v7 shells differ from a fresh build — run scripts/v7_build.py and commit:", file=sys.stderr)
            for p in touched:
                print(f"  {os.path.relpath(p, ROOT)}", file=sys.stderr)
            return 1
        print(f"v7 shells in sync ({len(PAGES)} pages under base {args.base}).")
        return 0
    for p in touched:
        print(f"  wrote {os.path.relpath(p, ROOT)}")
    print(f"Built {len(touched)} v7 pages under base {args.base}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
