#!/usr/bin/env python3
"""scripts/v9_reference_copies.py — keep the pages the v9 cut-over supersedes (#5534, epic #5529).

Owner rulings: every superseded layout is kept as a served, `noindex`, out-of-navigation reference
page at /reference/<date>-<slug>/ with the last live sha in its head comment (2026-10-18; precedent
site/reference/2026-10-22-home-v5/); retired pages go to the footnote appendix, never deleted
(2026-10-04); no URL moves, no 301s (2026-09-26).

What `--apply` writes (dry-run by default — a bare invocation changes nothing):

  1. For each page in deploy/www_owned_paths.SUPERSEDED (the four live v8 kit pages `/`, /start/,
     /story/, /coaches/, and the two v5 pages the build also replaces at their URL, /data/ and
     /privacy/): a byte-copy to site/reference/<CUTOVER_DATE>-<slug>-<layout>/index.html with
       * a head comment naming the path and the last live sha (origin/main's tip),
       * <meta name="robots" content="noindex,nofollow">,
       * <link rel="canonical"> → the v9 URL that replaces the page (plan §C: `/`, /story/, /data/,
         /privacy/ keep their addresses; /start/ has no v9 twin → `/`; /coaches/ → /system/, which
         carries the coaches list — there is no /system/coaches/ index page in the build).
     Asset links (`/assets/...`, `data-ck-base`) are left as they are: the copies render from the
     served v8/v5 assets exactly as the precedent does.
  2. The two pages with no v9 twin, /start/ and /coaches/, stay served from site/ and get the same
     noindex + canonical-to-successor in place (the issue's acceptance), so an indexable page never
     carries a canonical that is not its own URL (tests/test_v4_build_sitemap_3567.py).

The copies are listed in the v9 appendix by scripts/publish_snapshot.py::reference_copies() (group
"Earlier front pages"), are EXEMPT from qa/qa_manifest.py like the precedent, and are never touched
by a generator (scripts/v4_apply_chrome.py prunes site/reference/). Idempotent: an existing copy is
left alone unless --force; an already-marked page is not marked twice.

  python3 scripts/v9_reference_copies.py            # plan only
  python3 scripts/v9_reference_copies.py --apply    # write
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from deploy.www_owned_paths import CUTOVER_DATE, SUPERSEDED  # noqa: E402

SITE = os.path.join(REPO, "site")
HOST = "https://averagejoematt.com"
#: Pages with no v9 twin: kept at their URL, noindex, canonical to the successor (not replaced by a route).
TWINLESS = ("/start/", "/coaches/")
NOINDEX_TAG = '<meta name="robots" content="noindex,nofollow">'
_CANONICAL_RE = re.compile(r'<link rel="canonical" href="[^"]*">')
_HEAD_RE = re.compile(r"<head>\n", re.I)


def last_live_sha() -> str:
    for ref in ("origin/main", "HEAD"):
        try:
            return subprocess.check_output(["git", "rev-parse", ref], cwd=REPO, text=True).strip()
        except subprocess.CalledProcessError:
            continue
    return "0" * 40


def source_file(path: str) -> str:
    return os.path.join(SITE, path.strip("/"), "index.html") if path != "/" else os.path.join(SITE, "index.html")


def reference_dir(path: str) -> str:
    slug, layout, _succ = SUPERSEDED[path]
    return f"{CUTOVER_DATE}-{slug}-{layout}"


def reference_html(html: str, path: str, sha: str) -> str:
    slug, layout, successor = SUPERSEDED[path]
    comment = (
        f"<!-- reference copy of {path} at {sha} (the {layout} layout, last live on main before the #5534 v9 cut-over), "
        f"replaced {CUTOVER_DATE}. Served, noindex, out of navigation, canonical to its v9 successor {successor}, listed in the "
        "footnote appendix (owner ruling 2026-10-18). Not rebuilt by any generator: scripts/v4_apply_chrome.py prunes site/reference/. -->"
    )
    if not _HEAD_RE.search(html):
        raise ValueError(f"{path}: no <head> to annotate")
    html = _HEAD_RE.sub(lambda m: m.group(0) + comment + "\n  " + NOINDEX_TAG + "\n", html, count=1)
    return _set_canonical(html, path, successor)


def _set_canonical(html: str, path: str, successor: str) -> str:
    tag = f'<link rel="canonical" href="{HOST}{successor}">'
    if _CANONICAL_RE.search(html):
        return _CANONICAL_RE.sub(tag, html, count=1)
    raise ValueError(f"{path}: no canonical link to repoint")


def mark_twinless(html: str, path: str) -> str:
    """noindex + canonical → successor, in place, for a page the build does not replace."""
    _slug, _layout, successor = SUPERSEDED[path]
    if 'name="robots" content="noindex' not in html:
        html = _HEAD_RE.sub(lambda m: m.group(0) + "  " + NOINDEX_TAG + "\n", html, count=1)
    return _set_canonical(html, path, successor)


def plan(apply: bool, force: bool) -> int:
    sha = last_live_sha()
    print(f"v9 reference copies — cut-over {CUTOVER_DATE}, last live sha {sha} ({'APPLY' if apply else 'DRY RUN'})")
    rc = 0
    for path in SUPERSEDED:
        src = source_file(path)
        dest_dir = os.path.join(SITE, "reference", reference_dir(path))
        dest = os.path.join(dest_dir, "index.html")
        rel = os.path.relpath(dest, REPO)
        if not os.path.isfile(src):
            print(f"  ✗ {path}: source {os.path.relpath(src, REPO)} missing")
            rc = 1
            continue
        if os.path.exists(dest) and not force:
            print(f"  = {path} → {rel} (exists, kept)")
            continue
        with open(src, encoding="utf-8") as fh:
            html = reference_html(fh.read(), path, sha)
        print(f"  + {path} → {rel} (canonical → {SUPERSEDED[path][2]})")
        if apply:
            os.makedirs(dest_dir, exist_ok=True)
            with open(dest, "w", encoding="utf-8") as fh:
                fh.write(html)
    for path in TWINLESS:
        src = source_file(path)
        with open(src, encoding="utf-8") as fh:
            before = fh.read()
        after = mark_twinless(before, path)
        if after == before:
            print(f"  = {path} already noindex + canonical → {SUPERSEDED[path][2]}")
            continue
        print(f"  ~ {path} stays served from {os.path.relpath(src, REPO)}: noindex + canonical → {SUPERSEDED[path][2]}")
        if apply:
            with open(src, "w", encoding="utf-8") as fh:
                fh.write(after)
    if not apply:
        print("dry run — nothing written. Re-run with --apply.")
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write the copies and mark the twinless pages (default: plan only)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing reference copy")
    args = ap.parse_args(argv)
    return plan(args.apply, args.force)


if __name__ == "__main__":
    sys.exit(main())
