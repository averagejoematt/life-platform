#!/usr/bin/env python3
"""
v4_build_home_proof.py — bake Home's static core + data-driven OG into `/` (#1395).

Home (site/index.html) is the platform's most-shared URL, yet it shipped as a pure
cinematic JS shell: curl / a crawler / an HN or Twitter unfurl / a search snippet saw
only shimmer placeholders ("·· days into the experiment") — a BLANK growth surface
(frontier review Epic G, trust-leak #10). This gives `/` the #729/#730/#788/#804
treatment the cockpit/coaching/story doors already have:

  1. a <noscript> static core with the REAL headline numbers (baseline → goal, the
     day-of-experiment or the pre-start countdown, the live character level) + an
     honest "as of" stamp, so the no-JS/crawler view is real content, not an empty
     shell; and
  2. per-page data-driven OG/Twitter tags whose title + description carry a dated,
     falsifiable number (316 lb → 185 lb, the genesis date, the level) instead of the
     old generic "the measured life" boilerplate.

Data comes from the SAME APIs Home's own JS renders (/api/journey + /api/character),
via scripts/v4_proof, with the committed proof_snapshot.json as the offline fallback.
Nothing is fabricated (ADR-104/105): a missing value is dropped, and if neither the
API nor the snapshot has the numbers the existing baked block/OG is left untouched
(last-known-good, like the other sync-regenerated proof artifacts).

The static core lives in <noscript>, so it is inert the instant scripts run — a
JS browser gets the rich constellation, never a flash of duplicate content. Injection
is idempotent (sentinel-delimited block; OG tags set in place). Wired into
deploy/sync_site_to_s3.sh so every deploy refreshes the numbers.

Writes site/index.html. Run from repo root:
    python3 scripts/v4_build_home_proof.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v4_proof import apply_og, home_block_html, home_og, load_character, load_journey  # noqa: E402

HOME = Path("site/index.html")

_START = "<!-- home-proof:start -->"
_END = "<!-- home-proof:end -->"

# First-time injection point: just before the story's <main>, so a no-JS browser
# renders the proof where the live arc would sit.
_MARKER = '<main id="arc" class="arc">'


def inject(html: str, block: str) -> str | None:
    """Return html with the proof block injected/replaced, or None if no anchor.

    Idempotent: replaces the sentinel-delimited block when present; otherwise injects
    before the story <main> marker."""
    payload = f"{_START}\n  {block}\n  {_END}"
    if _START in html and _END in html:
        start = html.index(_START)
        end = html.index(_END) + len(_END)
        return html[:start] + payload + html[end:]
    if _MARKER in html:
        return html.replace(_MARKER, payload + "\n  " + _MARKER, 1)
    return None


def main() -> int:
    if not HOME.exists():
        print("error: site/index.html not found — run from repo root.", file=sys.stderr)
        return 2
    journey = load_journey()
    char = load_character()
    html = HOME.read_text(encoding="utf-8")

    # Data-driven OG first (always safe — falls back to sensible baseline strings).
    html = apply_og(html, home_og(journey, char))

    block = home_block_html(journey, char)
    if not block:
        # No numbers at all (API + snapshot both empty) — keep any existing baked
        # block rather than blanking Home's only static content (last-known-good).
        HOME.write_text(html, encoding="utf-8")
        print("  ⚠️  no journey data (API + snapshot both empty) — OG refreshed, keeping any existing baked block.", file=sys.stderr)
        return 0
    out = inject(html, block)
    if out is None:
        print("error: no injection anchor found in site/index.html.", file=sys.stderr)
        return 2
    HOME.write_text(out, encoding="utf-8")
    print("updated site/index.html — home static core + data-driven OG baked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
