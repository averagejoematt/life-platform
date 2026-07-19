#!/usr/bin/env python3
"""
v4_build_cockpit_proof.py — bake the cockpit's static proof into /cockpit/ (#788).

The Cockpit (site/cockpit/index.html) is the flagship page and the first door in the
nav, yet it shipped as a pure JS shell: curl saw only shimmer placeholders and
"··" dots — blank to no-JS visitors, crawlers, and link bots (R22-UX-01). This
gives /cockpit/ the same treatment #729/#730 gave the scorecard and chronicle: the
current character level + tier, the Body/Mind rollups, each pillar score, and an
honest "as of" stamp, baked into the served HTML inside <noscript>.

Data comes from the SAME source the page's JS renders (/api/character — the body
/api/snapshot carries), via scripts/v4_proof.load_character(), with the committed
proof_snapshot.json as the offline fallback. Nothing is fabricated (ADR-104/105):
a missing pillar is omitted, and if neither the API nor the snapshot has a level
the existing baked block is left untouched (last-known-good, like the other
sync-regenerated artifacts).

Injection is idempotent — the block lives between sentinel comments and is
replaced in place on every run (the #733 chronicle-noscript pattern). Wired into
deploy/sync_site_to_s3.sh, so every site deploy refreshes the numbers.

Writes site/cockpit/index.html. Run from repo root:
    python3 scripts/v4_build_cockpit_proof.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v4_proof import apply_og, cockpit_block_html, cockpit_og, load_character  # noqa: E402

NOW = Path("site/cockpit/index.html")

_START = "<!-- cockpit-proof:start -->"
_END = "<!-- cockpit-proof:end -->"

# First-time injection point: right before the app-shell panel, inside <main>,
# so a no-JS browser renders the proof where the live panel would sit.
_MARKER = '<article class="panel" aria-busy="true">'


def inject(html: str, block: str) -> str | None:
    """Return html with the proof block injected/replaced, or None if no anchor.

    Idempotent: replaces the sentinel-delimited block when present; otherwise
    injects before the panel marker.
    """
    payload = f"{_START}\n    {block}\n    {_END}"
    if _START in html and _END in html:
        start = html.index(_START)
        end = html.index(_END) + len(_END)
        return html[:start] + payload + html[end:]
    if _MARKER in html:
        return html.replace(_MARKER, payload + "\n    " + _MARKER, 1)
    return None


def main() -> int:
    if not NOW.exists():
        print("error: site/cockpit/index.html not found — run from repo root.", file=sys.stderr)
        return 2
    char = load_character()
    html = NOW.read_text(encoding="utf-8")
    # #1395: data-driven OG first (the cockpit shell shipped with NO OG tags at all) —
    # always safe, falls back to a topical title when no level is available.
    html = apply_og(html, cockpit_og(char))

    block = cockpit_block_html(char)
    if not block:
        # No live data AND no snapshot — keep the existing baked block rather
        # than blanking the page's only static content (last-known-good).
        NOW.write_text(html, encoding="utf-8")
        print("  ⚠️  no character data (API + snapshot both empty) — OG refreshed, keeping the existing baked block.", file=sys.stderr)
        return 0
    out = inject(html, block)
    if out is None:
        print("error: no injection anchor found in site/cockpit/index.html.", file=sys.stderr)
        return 2
    NOW.write_text(out, encoding="utf-8")
    print("updated site/cockpit/index.html — cockpit proof + data-driven OG baked (level + pillars + as-of).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
