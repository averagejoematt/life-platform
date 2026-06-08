#!/usr/bin/env python3
"""
v4_relocate_legacy.py — preserve the current static site verbatim under /legacy.

Part of the averagejoematt.com v4 "one engine, three doors" cutover
(CLAUDE_CODE_PROMPT_V4_PASTE_READY.md, MIGRATION_MAP_V4_2026_06_01.md).

Strategy (locked with Matthew 2026-06-01): SCRIPTED PATH-REWRITE.
  * Move every legacy *page* (and the assets/ dir) into site/legacy/.
  * Rewrite only the root-relative URLs that physically moved:
      - /assets/...        -> /legacy/assets/...   (assets moved)
      - internal page nav  -> /legacy/<path>        (pages moved)
  * LEAVE untouched (shared, live, or system — must keep resolving for both
    legacy and v4):
      - /api/*             CloudFront behaviour -> site-api Lambda
      - /config/, /generated/, /.well-known/
      - /data/*.json       shared config blobs (the /data PAGE moves, json stays)
      - root static files  /favicon.ico /sitemap.xml /rss.xml /*.png ...
      - system pages       /privacy /subscribe (+/confirm, subscribe.html) /404(.html)
  * Inject <meta name="robots" content="noindex"> into every moved legacy page.

Idempotent-ish: refuses to run if site/legacy/ already exists (delete it first to
re-run). Local filesystem only — NO S3, NO CloudFront. Fully reversible via git.

Run from repo root:  python3 scripts/v4_relocate_legacy.py [--apply]
Without --apply it prints the move plan and exits (dry run).
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

SITE = Path("site")
LEGACY = SITE / "legacy"

# Top-level dirs that STAY at root (system pages + live/shared behaviours).
KEEP_DIRS = {"api", "config", "generated", ".well-known", "privacy", "subscribe", "404", "legacy"}
# Root-level files that STAY at root.
KEEP_FILES = {
    "404.html",
    "subscribe.html",
    "favicon.ico",
    "robots.txt",
    "sitemap.xml",
    "rss.xml",
    "site.webmanifest",
    "DEPLOY.md",
    "apple-touch-icon.png",
    "apple-touch-icon-precomposed.png",
}
# In the /data dir: move pages (*.html), keep everything else (the json blobs).
SPLIT_DIRS = {"data"}

# URL-rewrite rules (applied only to files now under site/legacy/).
# First path segment that must NOT be prefixed with /legacy:
NO_PREFIX_SEG = {"api", "config", "generated", ".well-known", "privacy", "subscribe", "404"}
# Root-level static-file extensions that must NOT be prefixed.
NO_PREFIX_ROOT_EXT = {".ico", ".png", ".svg", ".xml", ".txt", ".json", ".webmanifest", ".jpg", ".jpeg", ".gif", ".webp", ".pdf"}


def _should_prefix(path: str) -> bool:
    """True if a root-relative URL points at something that moved into /legacy."""
    if not path.startswith("/") or path.startswith("//"):
        return False  # absolute, protocol-relative, or not root-relative
    if path.startswith("/legacy/") or path == "/legacy":
        return False  # already rewritten (idempotent)
    rest = path[1:]
    seg = rest.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if seg in NO_PREFIX_SEG:
        return False
    # Root-level static file like /favicon.ico, /sitemap.xml, /apple-touch-icon.png
    if "/" not in rest.split("?", 1)[0].split("#", 1)[0]:
        dot = seg.rfind(".")
        if dot != -1 and seg[dot:].lower() in NO_PREFIX_ROOT_EXT:
            return False
        if seg in {"404.html", "subscribe.html"}:
            return False
    return True


def _prefixed(path: str) -> str:
    return "/legacy" + path if _should_prefix(path) else path


_ATTR_RE = re.compile(r"""(\b(?:href|src|action|poster)\s*=\s*)(["'])(/[^"']*)\2""")
_URL_RE = re.compile(r"""url\(\s*(['"]?)(/[^)'"]*)\1\s*\)""")
_SRCSET_RE = re.compile(r"""(\bsrcset\s*=\s*)(["'])([^"']*)\2""")


def _rewrite_text(text: str, *, is_js: bool) -> str:
    if is_js:
        # Conservative: only asset loads from JS string literals.
        return re.sub(r"""(['"])/assets/""", r"\g<1>/legacy/assets/", text)

    def attr(m):
        return f"{m.group(1)}{m.group(2)}{_prefixed(m.group(3))}{m.group(2)}"

    def url(m):
        return f"url({m.group(1)}{_prefixed(m.group(2))}{m.group(1)})"

    def srcset(m):
        items = []
        for part in m.group(3).split(","):
            part = part.strip()
            if not part:
                continue
            bits = part.split()
            bits[0] = _prefixed(bits[0])
            items.append(" ".join(bits))
        return f"{m.group(1)}{m.group(2)}{', '.join(items)}{m.group(2)}"

    text = _ATTR_RE.sub(attr, text)
    text = _SRCSET_RE.sub(srcset, text)
    text = _URL_RE.sub(url, text)
    return text


_NOINDEX = '<meta name="robots" content="noindex">'


def _add_noindex(html: str) -> str:
    if "noindex" in html:
        return html
    m = re.search(r"<head[^>]*>", html, re.IGNORECASE)
    if not m:
        return html
    i = m.end()
    return html[:i] + "\n  " + _NOINDEX + html[i:]


def _process_file(p: Path) -> None:
    suffix = p.suffix.lower()
    if suffix not in {".html", ".htm", ".css", ".js"}:
        return  # binaries (fonts/images) copied as-is
    try:
        text = p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return
    new = _rewrite_text(text, is_js=(suffix == ".js"))
    if suffix in {".html", ".htm"}:
        new = _add_noindex(new)
    if new != text:
        p.write_text(new, encoding="utf-8")


def _plan() -> list[tuple[Path, Path]]:
    """Return list of (src, dest) moves without performing them."""
    moves: list[tuple[Path, Path]] = []
    for entry in sorted(SITE.iterdir()):
        name = entry.name
        if name in KEEP_DIRS or name in KEEP_FILES:
            continue
        if entry.is_dir() and name in SPLIT_DIRS:
            for f in sorted(entry.rglob("*.html")):
                moves.append((f, LEGACY / f.relative_to(SITE)))
            continue
        moves.append((entry, LEGACY / name))
    return moves


def main() -> int:
    if not (SITE / "index.html").exists() and not LEGACY.exists():
        print("error: run from repo root (site/index.html not found).", file=sys.stderr)
        return 2
    if LEGACY.exists():
        print(
            f"error: {LEGACY}/ already exists. Delete it to re-run " f"(`rm -rf {LEGACY}` — it's git-tracked/reversible).", file=sys.stderr
        )
        return 2

    moves = _plan()
    apply = "--apply" in sys.argv
    print(f"\nv4 legacy relocation — {len(moves)} top-level move(s) into {LEGACY}/")
    print(f"  mode: {'APPLY' if apply else 'DRY RUN (pass --apply to execute)'}\n")
    for src, dest in moves:
        kind = "dir " if src.is_dir() else "file"
        print(f"  move {kind}  {src}  ->  {dest}")

    if not apply:
        print("\n(dry run — nothing changed)")
        return 0

    LEGACY.mkdir(parents=True, exist_ok=True)
    page_count = 0
    for src, dest in moves:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))

    # Rewrite every text file now under /legacy.
    rewritten = 0
    for p in LEGACY.rglob("*"):
        if p.is_file():
            before = p.read_bytes() if p.suffix.lower() in {".html", ".htm", ".css", ".js"} else None
            _process_file(p)
            if before is not None and p.read_bytes() != before:
                rewritten += 1
            if p.suffix.lower() in {".html", ".htm"}:
                page_count += 1

    print(
        f"\napplied: moved {len(moves)} entries; rewrote {rewritten} text file(s); "
        f"{page_count} legacy HTML page(s) now under {LEGACY}/."
    )
    print("verify:  grep -rE '(href|src)=\"/assets/' site/legacy --include='*.html' | wc -l   # expect 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
