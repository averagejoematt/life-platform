#!/usr/bin/env python3
"""design_sync_capture.py — refresh the design-sync bundle's `reference/` layer with
CURRENT live-page captures (#1467, Epic #1460 D2: the reference-capture refresh).

Runs AFTER `scripts/design_sync_bundle.py` (which fully rebuilds the bundle — including
rmtree'ing any previous captures) and adds the one layer the deterministic builder cannot
produce: full-page screenshots of the site as it renders TODAY, taken over the network at
sync time. Tokens and components describe the system; these captures show how it actually
composes on live surfaces, with today's real data in the charts — without this refresh,
`reference/` rots into exactly the stale-snapshot problem the v5 design project exists to
fix (the issue's own words).

What it writes (all under `<bundle>/reference/`):

    captures/<slug>.png       full-page Chromium screenshot per page — 1440x900, dark,
                              scrolled top-to-bottom first so lazy data fetches and
                              .reveal animations have fired. The navigation + scroll
                              discipline is IMPORTED from tests/visual_qa.py (the
                              visual-QA sweep) — reuse, don't reinvent, per the issue's
                              evidence line.
    <slug>-capture.html       one card per capture with the first-line
                              `@dsCard group="reference"` marker, so captures render in
                              the Design System pane alongside foundations/ and
                              components/. Built via design_sync_bundle._page — the
                              byte-0 marker contract and the relative-asset discipline
                              are the same code path as every other card.
    captures_base64.json      {filename: base64} manifest of every capture PNG — the
                              binary-upload mirror of assets/fonts_base64.json (special
                              case #3 in design_sync_bundle.py), so a design-project
                              upload surface never has to re-derive binary payloads.

Page set — derived from THE page registry (tests/qa_manifest.py, #1426), never a hand
list here: every tier-1 entry (the doors — home, cockpit, story, data, protocols,
coaching) plus one data-dense readout surface (DATA_DENSE_PATH, asserted to still exist
in the manifest). A door added to the manifest is picked up automatically on the next
sync.

Non-determinism is the point: unlike the bundle builder (byte-identical on re-run), the
capture PNGs change whenever the live pages change — for live-data surfaces that is
essentially every run. `/design-sync`'s incremental diff (Phase 2 byte-compare) absorbs
that honestly: changed captures re-upload, everything else in the bundle stays a no-op.
The capture CARDS churn at most once per UTC day (they carry the capture date, never a
timestamp); only the PNGs + captures_base64.json churn with the data.

Network: read-only GETs against the live site — or QA_SITE_URL, the same override the
visual-QA harness honors, so a local static server works too. Requires
`playwright install chromium`. A page that fails to load FAILS the whole run: a partial
reference/ layer must never sync silently (stop-and-report, the same discipline as the
bundle builder's self-verification).

Usage:
    python3 scripts/design_sync_bundle.py             # first — builds the bundle
    python3 scripts/design_sync_capture.py            # then — adds the live captures
    python3 scripts/design_sync_capture.py --out DIR --repo-root DIR   # same flags
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT_DEFAULT = SCRIPT_DIR.parent

sys.path.insert(0, str(SCRIPT_DIR))
import design_sync_bundle as dsb  # noqa: E402  (sibling module — reuses _page/_esc + _verify_bundle)

# The one deliberate hand-pick: the doors derive from the manifest's tier-1 set; the
# issue's "data-dense surface" is a single archive readout page dense with charts and
# tables. Asserted against the manifest at derivation time so a route rename can't leave
# this pointing at a page that no longer exists.
DATA_DENSE_PATH = "/data/sleep/"

VIEWPORT = {"width": 1440, "height": 900}  # the visual-QA sweep's desktop profile


def _slug(path: str) -> str:
    return path.strip("/").replace("/", "-") or "home"


def capture_set(repo_root: Path = REPO_ROOT_DEFAULT) -> list[dict]:
    """The doors (every tier-1 manifest entry, in manifest order) + the data-dense surface.

    Derived from tests/qa_manifest.py — THE page registry (#1426) — never a hand list
    (memory: reference_new_site_page_registries). Returns [{path, name, slug}, …].
    """
    tests_dir = str(repo_root / "tests")
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
    from qa_manifest import MANIFEST, PAGES_BY_PATH  # noqa: E402  (repo tests/ path added just above)

    pages = [p for p in MANIFEST if p["tier"] == 1]
    if DATA_DENSE_PATH not in PAGES_BY_PATH:
        raise AssertionError(f"DATA_DENSE_PATH {DATA_DENSE_PATH!r} is not in tests/qa_manifest.py — route renamed? update this constant")
    if DATA_DENSE_PATH not in {p["path"] for p in pages}:
        pages.append(PAGES_BY_PATH[DATA_DENSE_PATH])
    out = [{"path": p["path"], "name": p["name"], "slug": _slug(p["path"])} for p in pages]
    slugs = [p["slug"] for p in out]
    if len(slugs) != len(set(slugs)):
        raise AssertionError(f"capture slugs collide: {slugs}")
    return out


def write_capture_card(reference_dir: Path, page_info: dict, captured_on: str) -> Path:
    """One @dsCard reference card wrapping a capture PNG (acceptance criterion #4).

    Uses design_sync_bundle._page so the first-line marker contract and the
    relative-asset discipline are the same code path as every foundations/components
    card. The route is documentation text (like the shells' data-live-route attrs),
    never an href — the bundle sweep bans absolute link refs.
    """
    slug, name, path = page_info["slug"], page_info["name"], page_info["path"]
    body = (
        f'<p class="ds-cap mono">route: {dsb._esc(path)} · {VIEWPORT["width"]}×{VIEWPORT["height"]} · dark · '
        f"captured {dsb._esc(captured_on)} (UTC) from the live site at sync time</p>\n"
        '<p class="ds-note">Live full-page capture — refreshed on every /design-sync run (#1467), never a '
        "checked-in artifact. Charts and numbers show real data as of the capture date.</p>\n"
        f'<img src="captures/{dsb._esc(slug)}.png" alt="Full-page capture of {dsb._esc(name)}"'
        ' style="max-width:100%;height:auto;border:var(--border-hair);border-radius:var(--radius);">'
    )
    card = reference_dir / f"{slug}-capture.html"
    card.write_text(dsb._page("reference", f"{name} — live capture", body), encoding="utf-8")
    return card


def write_captures_manifest(reference_dir: Path) -> Path:
    """{filename: base64} manifest of every capture PNG — the binary-upload mirror of
    assets/fonts_base64.json, and the byte-compare surface the /design-sync diff uses
    for the PNGs (changed captures re-upload; unchanged ones stay untouched)."""
    captures_dir = reference_dir / "captures"
    manifest = {p.name: base64.b64encode(p.read_bytes()).decode("ascii") for p in sorted(captures_dir.glob("*.png"))}
    if not manifest:
        raise AssertionError("no capture PNGs found under reference/captures/ — the capture step wrote nothing")
    out = reference_dir / "captures_base64.json"
    out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def capture_live_pages(pages: list[dict], captures_dir: Path, repo_root: Path) -> None:
    """Screenshot each page from the live site (or QA_SITE_URL), reusing the visual-QA
    harness's navigation-with-fallback + scroll/reveal discipline (tests/visual_qa.py).

    Lazy imports on purpose: playwright is not a dependency of the unit-test
    environment — a module-level import would red the whole suite at collection
    (memory: reference_test_layer_dep_import_collection_red), and visual_qa's SITE_URL
    is read here (not copied) so the QA_SITE_URL override keeps working identically.
    """
    tests_dir = str(repo_root / "tests")
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
    import visual_qa  # noqa: E402  (repo tests/ path added just above)
    from playwright.sync_api import sync_playwright  # noqa: E402

    captures_dir.mkdir(parents=True, exist_ok=True)
    failures = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            context = browser.new_context(viewport=VIEWPORT, color_scheme="dark")
            for pg in pages:
                page = context.new_page()
                try:
                    nav = visual_qa._navigate_with_fallback(page, f"{visual_qa.SITE_URL}{pg['path']}")
                    if nav and nav.startswith("Page load failed"):
                        failures.append(f"{pg['path']}: {nav}")
                        continue
                    visual_qa._scroll_and_reveal(page)
                    page.screenshot(path=str(captures_dir / f"{pg['slug']}.png"), full_page=True)
                except Exception as e:  # collected + raised below — never swallowed
                    failures.append(f"{pg['path']}: {e}")
                finally:
                    page.close()
        finally:
            browser.close()
    if failures:
        raise AssertionError(
            "design_sync_capture: live capture FAILED — a partial reference/ layer must never sync:\n  " + "\n  ".join(failures)
        )


def refresh(repo_root: Path, out: Path) -> list[dict]:
    reference_dir = out / "reference"
    if not reference_dir.is_dir():
        raise AssertionError(
            f"{reference_dir} not found — run scripts/design_sync_bundle.py first"
            " (this script only ADDS the live capture layer to a freshly built bundle)"
        )
    pages = capture_set(repo_root)
    capture_live_pages(pages, reference_dir / "captures", repo_root)
    captured_on = datetime.now(timezone.utc).date().isoformat()
    for pg in pages:
        write_capture_card(reference_dir, pg, captured_on)
    write_captures_manifest(reference_dir)
    # Re-run the bundle-wide sweep over the finished bundle (now including the capture
    # cards + manifest) — same stop-and-report guarantee as the builder itself.
    dsb._verify_bundle(out)
    return pages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="scratch/design_sync_bundle", help="bundle directory (repo-root-relative unless absolute)")
    parser.add_argument("--repo-root", default=str(REPO_ROOT_DEFAULT), help="repo root (default: this script's parent dir)")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    out = Path(args.out)
    if not out.is_absolute():
        out = repo_root / out

    pages = refresh(repo_root, out)
    print(f"design_sync_capture: refreshed {len(pages)} live captures under {out / 'reference'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
