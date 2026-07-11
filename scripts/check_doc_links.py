#!/usr/bin/env python3
"""scripts/check_doc_links.py — dead-link checker for the engineering wiki.

Resolves every relative markdown link (and #anchor) across docs/**/*.md, the root
README.md, and CLAUDE.md. External URLs are ignored (a weekly job could probe them;
CI must stay hermetic). Part of the wiki drift machinery (CONVENTIONS §7, layer 2).

WHAT COUNTS AS A LINK:
  [text](RELATIVE_PATH)          — file must exist (resolved from the doc's dir)
  [text](RELATIVE_PATH#anchor)   — file must exist AND contain a heading that
                                   slugifies to `anchor` (GitHub slug rules, simplified)
  [text](#anchor)                — same-file anchor

SKIPPED:
  http(s)://, mailto:, absolute /paths (site URLs), images are checked like files,
  code spans/fenced blocks (links inside them are illustrative), and everything under
  docs/archive/ + docs/specs/ + handovers/ (frozen history is not maintained).

USAGE:
  python3 scripts/check_doc_links.py           # report; exit 1 on any dead link
  python3 scripts/check_doc_links.py --list    # also list every link checked
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCAN_ROOTS = [ROOT / "docs", ROOT / "README.md", ROOT / "CLAUDE.md"]
SKIP_DIRS = (  # frozen history / machine-written — not maintained surfaces
    "docs/archive/",
    "docs/specs/",
    "docs/restart/",
    "docs/reviews/",
    "docs/audits/",
    "docs/v2-audits/",
    "docs/rca/",
    "docs/briefs/",
    "docs/site-reviews/",
)

_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$", re.MULTILINE)
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_CODESPAN_RE = re.compile(r"`[^`\n]*`")


def _slugify(heading: str) -> str:
    """GitHub-style anchor slug (simplified: lowercase, strip punctuation, dashes)."""
    text = re.sub(r"[*_`]", "", heading.strip())
    text = re.sub(r"[^\w\- ]", "", text.lower())
    return re.sub(r"\s+", "-", text.strip())


def _anchors(path: Path) -> set[str]:
    try:
        src = path.read_text(encoding="utf-8")
    except Exception:
        return set()
    slugs = set()
    counts: dict[str, int] = {}
    for m in _HEADING_RE.finditer(src):
        slug = _slugify(m.group(1))
        n = counts.get(slug, 0)
        counts[slug] = n + 1
        slugs.add(slug if n == 0 else f"{slug}-{n}")
    # explicit <a name="..."> anchors
    slugs.update(re.findall(r'<a\s+(?:name|id)="([^"]+)"', src))
    return slugs


def _files_to_scan() -> list[Path]:
    files = []
    for root in SCAN_ROOTS:
        if root.is_file():
            files.append(root)
        else:
            for p in sorted(root.rglob("*.md")):
                rel = str(p.relative_to(ROOT))
                if any(rel.startswith(s) for s in SKIP_DIRS):
                    continue
                files.append(p)
    return files


def main():
    verbose = "--list" in sys.argv
    dead = []
    checked = 0
    anchor_cache: dict[Path, set[str]] = {}

    for doc in _files_to_scan():
        src = doc.read_text(encoding="utf-8")
        # remove fenced blocks + code spans — links there are illustrative
        stripped = _CODESPAN_RE.sub("", _FENCE_RE.sub("", src))
        for m in _LINK_RE.finditer(stripped):
            target = m.group(1)
            if target.startswith(("http://", "https://", "mailto:", "/")):
                continue
            checked += 1
            frag = None
            if "#" in target:
                target, frag = target.split("#", 1)
            dest = doc if target == "" else (doc.parent / target).resolve()
            rel_doc = doc.relative_to(ROOT)
            if verbose:
                print(f"  {rel_doc}: {m.group(1)}")
            if target and not dest.exists():
                dead.append(f"{rel_doc}: dead file link → {m.group(1)}")
                continue
            if frag and dest.suffix == ".md":
                if dest not in anchor_cache:
                    anchor_cache[dest] = _anchors(dest)
                if frag not in anchor_cache[dest]:
                    dead.append(f"{rel_doc}: dead anchor → {m.group(1)}")

    if dead:
        print(f"❌ {len(dead)} dead link(s) of {checked} checked:")
        for d in dead:
            print(f"   {d}")
        sys.exit(1)
    print(f"✅ doc links OK — {checked} relative links resolve.")


if __name__ == "__main__":
    main()
