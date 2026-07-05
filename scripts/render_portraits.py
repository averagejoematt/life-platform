#!/usr/bin/env python3
"""render_portraits.py — rasterize signed coach portraits to email-ready PNGs (#593, ADR-106).

The site renders the layered-SVG recipe in the browser; email clients can't. This script is
the commit-time raster step: every SIGNED recipe (config/portraits/*.json) becomes a small
"ink on transparent" PNG in both themes' ink, committed under site/assets/portraits/ so email
lambdas reference self-hosted URLs instead of a coach-emoji map. It rides deploy/sync_site_to_s3.sh
exactly like scripts/v4_build_portraits.py.

One source of truth (the issue's parity guard): the PNGs are stamped against the recipe's
content hash in a manifest, and `--check` FAILS if any recipe was edited without re-rendering.
CI runs `--check` (tests/test_render_portraits_parity.py) so a face can never drift between the
site's SVG and the off-site PNG.

Usage:
    python3 scripts/render_portraits.py           # render + write PNGs + manifest
    python3 scripts/render_portraits.py --check    # verify PNGs are in sync with recipes (CI)
"""

import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

import v4_build_portraits as vbp  # noqa: E402  schema authority + is_signed
from web import portrait_raster  # noqa: E402

OUT_DIR = os.path.join(ROOT, "site", "assets", "portraits")
MANIFEST = os.path.join(OUT_DIR, "manifest.json")
BOARD = os.path.join(ROOT, "config", "board_of_directors.json")

SIZES = (96, 192)
# theme -> ink RGB. "ondark" is light ink for dark backgrounds (the chronicle email);
# "onlight" is near-black ink for light backgrounds. Same recipe, two inks, transparent bg.
THEMES = {
    "ondark": (236, 227, 210),  # #ECE3D2 tokens ink
    "onlight": (20, 18, 12),  # #14120C near-black
}


def recipe_hash(recipe):
    """Stable content hash of a recipe (drives the parity guard)."""
    canon = json.dumps(recipe, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canon.encode()).hexdigest()[:16]


def _members():
    try:
        with open(BOARD) as f:
            return json.load(f).get("members", {})
    except Exception:
        return {}


def _identity_name(pid, recipe, members):
    m = members.get(pid)
    if not m:
        for a in recipe.get("aliases") or []:
            if a in members:
                m = members[a]
                break
    return (m or {}).get("name") or pid.replace("_", " ").title()


def _files_for(pid):
    return [f"{pid}-{size}-{theme}.png" for size in SIZES for theme in THEMES]


def _render_pngs(pid, recipe):
    """Render + write all size/theme PNGs for one persona. Returns the filenames."""
    for size in SIZES:
        for theme, ink in THEMES.items():
            img = portrait_raster.render_recipe(recipe, size=size, mode="mono", ink=ink, with_frame=False)
            img.save(os.path.join(OUT_DIR, f"{pid}-{size}-{theme}.png"), format="PNG", optimize=True)
    return _files_for(pid)


def build_manifest(recipes, members):
    signed = {pid: r for pid, r in recipes.items() if vbp.is_signed(r)}
    portraits = {}
    for pid, recipe in sorted(signed.items()):
        portraits[pid] = {
            "hash": recipe_hash(recipe),
            "name": _identity_name(pid, recipe, members),
            "sizes": list(SIZES),
            "themes": sorted(THEMES),
            "files": _files_for(pid),
        }
    return {
        "_meta": {
            "generated_by": "scripts/render_portraits.py",
            "note": "Signed coach portraits rasterized to ink-on-transparent PNGs (#593, ADR-106). Do not hand-edit.",
            "url_base": "/assets/portraits/",
        },
        "portraits": portraits,
    }


def render_all():
    os.makedirs(OUT_DIR, exist_ok=True)
    recipes = vbp.load_recipes()
    members = _members()
    signed = {pid: r for pid, r in recipes.items() if vbp.is_signed(r)}
    for pid, recipe in sorted(signed.items()):
        _render_pngs(pid, recipe)
    manifest = build_manifest(recipes, members)
    with open(MANIFEST, "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    return signed, manifest


def check():
    """Return a list of parity problems (empty = in sync). Used by CI + the unit guard."""
    problems = []
    recipes = vbp.load_recipes()
    signed = {pid: r for pid, r in recipes.items() if vbp.is_signed(r)}
    if not os.path.exists(MANIFEST):
        return [f"missing manifest: {os.path.relpath(MANIFEST, ROOT)} — run scripts/render_portraits.py"]
    with open(MANIFEST) as f:
        manifest = json.load(f)
    recorded = manifest.get("portraits", {})

    missing = sorted(set(signed) - set(recorded))
    extra = sorted(set(recorded) - set(signed))
    if missing:
        problems.append(f"signed recipes with no rendered PNGs: {missing} — run scripts/render_portraits.py")
    if extra:
        problems.append(f"manifest has stale personas no longer signed: {extra} — run scripts/render_portraits.py")

    for pid, recipe in sorted(signed.items()):
        rec = recorded.get(pid)
        if not rec:
            continue
        if rec.get("hash") != recipe_hash(recipe):
            problems.append(f"{pid}: recipe changed since last render (hash mismatch) — run scripts/render_portraits.py")
        for fname in _files_for(pid):
            if not os.path.exists(os.path.join(OUT_DIR, fname)):
                problems.append(f"{pid}: missing PNG {fname} — run scripts/render_portraits.py")
    return problems


def main(argv):
    if "--check" in argv:
        problems = check()
        if problems:
            print("❌ portrait PNGs are out of sync with recipes:")
            for p in problems:
                print(f"  - {p}")
            return 1
        print("✅ portrait PNGs in sync with signed recipes")
        return 0
    signed, manifest = render_all()
    n_files = sum(len(v["files"]) for v in manifest["portraits"].values())
    print(f"✅ rendered {len(signed)} signed portrait(s) → {n_files} PNG(s) under site/assets/portraits/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
