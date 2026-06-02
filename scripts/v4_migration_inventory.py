#!/usr/bin/env python3
"""
v4_migration_inventory.py - coverage gate + redirect map for the v4 cutover.

POST-RELOCATION MODE. The old site is preserved verbatim under site/legacy/
(see scripts/v4_relocate_legacy.py). This script walks that preserved tree as
the authoritative list of OLD URLs, classifies each into a v4 destination, and
writes redirects.map (old URL -> v4 home). Exit 1 if any old URL is unmapped,
so it gates the big-bang cutover and CI.

Destinations:
  cockpit  -> /now                      (the single daily door; pillar pages fold in)
  story    -> /                         (the scrollytelling door)
  evidence -> /evidence/<topic>/        (the archival readout; topic page exists)
  legacy   -> /legacy/<path>            (archived v1 — served verbatim, already there)
System pages (privacy, subscribe, 404) were NOT relocated; they stay at root,
ported as-is, and need no redirect — so they don't appear here.

Read-only except for redirects.map. Run from repo root:
    python3 scripts/v4_migration_inventory.py
"""
from __future__ import annotations
import sys
from pathlib import Path

LEGACY_DIR = Path("site/legacy")

# Top-level segment (of the ORIGINAL url) -> v4 destination.
RULES: dict[str, str] = {
    # Cockpit — daily state, score, time-views
    "character": "cockpit", "observatory": "cockpit", "live": "cockpit",
    "week": "cockpit", "weekly": "cockpit", "recap": "cockpit",
    "status": "cockpit", "achievements": "cockpit",
    # Story — narrative, journey, the cast, public face
    "": "story",  # the old root index.html
    "chronicle": "story", "journal": "story", "elena": "story", "story": "story",
    "mission": "story", "about": "story", "first-person": "story",
    "field-notes": "story", "progress": "story",
    "builders": "story", "community": "story",
    "start": "story",
    # Evidence — depth, protocols, data, credibility
    "nutrition": "evidence", "sleep": "evidence", "training": "evidence",
    "physical": "evidence", "mind": "evidence", "supplements": "evidence",
    "labs": "evidence", "biology": "evidence", "glucose": "evidence",
    "protocols": "evidence", "habits": "evidence", "experiments": "evidence",
    "challenges": "evidence", "benchmarks": "evidence", "methodology": "evidence",
    "intelligence": "evidence", "predictions": "evidence", "stack": "evidence",
    "board": "evidence", "coaches": "evidence", "ledger": "evidence",
    "discoveries": "evidence", "accountability": "evidence",
    "kitchen": "evidence", "results": "evidence", "cost": "evidence",
    "explorer": "evidence", "data": "evidence", "tools": "evidence",
    "platform": "evidence", "ask": "evidence",
    # Legacy — already-archived v1, preserved not rehomed
    "archive": "legacy",
}

DEST_ORDER = ["cockpit", "story", "evidence", "legacy"]


def original_url(html_path: Path) -> str:
    """Map site/legacy/<path>/index.html back to the OLD url /<path>/."""
    rel = html_path.relative_to(LEGACY_DIR)
    parts = rel.as_posix()
    if rel.name == "index.html":
        parent = rel.parent.as_posix()
        return "/" if parent == "." else f"/{parent}/"
    return "/" + rel.with_suffix("").as_posix()


def seg_of(url: str) -> str:
    return url.strip("/").split("/", 1)[0]


def classify(url: str) -> str | None:
    return RULES.get(seg_of(url))


def new_url(url: str, dest: str) -> str:
    if dest == "cockpit":
        return "/now/"   # trailing slash: bare /now 302s to /site/now/ via the S3 origin
    if dest == "story":
        return "/"
    if dest == "evidence":
        remap = {"coaches": "board", "accountability": "vices"}
        seg = seg_of(url)
        return f"/evidence/{remap.get(seg, seg)}/"   # collapse subpaths; remap rehomed slugs
    if dest == "legacy":
        return f"/legacy{url}"               # served verbatim from its preserved location
    return url


def main() -> int:
    if not LEGACY_DIR.is_dir():
        print(f"error: '{LEGACY_DIR}/' not found. Run scripts/v4_relocate_legacy.py "
              f"--apply first (from the repo root).", file=sys.stderr)
        return 2

    pages = sorted(LEGACY_DIR.rglob("*.html"))
    buckets: dict[str, list[str]] = {d: [] for d in DEST_ORDER}
    unmapped: list[str] = []
    redirects: list[tuple[str, str]] = []

    for p in pages:
        url = original_url(p)
        dest = classify(url)
        if dest is None:
            unmapped.append(url)
            continue
        buckets[dest].append(url)
        new = new_url(url, dest)
        if new != url:           # legacy pages already live at /legacy/* — still record the 301
            redirects.append((url, new))

    print(f"\nv4 migration inventory - {len(pages)} preserved page(s) under {LEGACY_DIR}/\n")
    for d in DEST_ORDER:
        print(f"  {d:8} {len(buckets[d]):4}")
    print(f"  {'UNMAPPED':8} {len(unmapped):4}")

    if unmapped:
        print("\nUNMAPPED - every one needs a destination before cutover:")
        for u in unmapped:
            print(f"  ! {u}")

    Path("redirects.map").write_text(
        "\n".join(f"{o}\t{n}" for o, n in sorted(redirects)) + "\n", encoding="utf-8")
    print(f"\nwrote redirects.map ({len(redirects)} 301s; review before wiring to the edge).")

    if unmapped:
        print(f"\nFAIL: {len(unmapped)} page(s) have no home.")
        return 1
    print("\nPASS: every preserved page maps to a v4 destination.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
