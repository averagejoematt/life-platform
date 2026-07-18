"""Offline guard for the v4-redirects CloudFront viewer function (#1209).

The edge function (`deploy/generated/v4_redirects_function.js`, emitted by
`deploy/v4_cutover.sh` from `redirects.map`) does two things at the viewer edge:

  1. 301 every old URL to its v5 home via the generated redirect table `R`.
  2. #1209 — 301 any *bare extensionless path* (no trailing slash, no `.` in it)
     that has no redirect-map match to the same path + `/`. Without this, a bare
     door URL like `/data` fell through to the S3 website origin, which 302s it to
     the internal `/site/data/` prefix and 404s — so a hand-typed or
     autolinker-stripped shared link (Reddit et al. drop trailing slashes) landed
     on a dead page instead of the door.

This test ports the function's normalization to Python, parses the *real* `R`
table out of the generated artifact, and asserts behavior — so the guard is
CI-green without a live deploy. It also asserts the fix branch is present in both
the generator and the generated artifact, so a regeneration can't silently drop
it (they must not drift).
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATED = ROOT / "deploy" / "generated" / "v4_redirects_function.js"
GENERATOR = ROOT / "deploy" / "v4_cutover.sh"

# The six v5 doors — the bare-URL 404 class the issue reproduces (#1209).
DOORS = ["/data", "/cockpit", "/coaching", "/protocols", "/story", "/method"]


def _load_redirect_table() -> dict:
    """Parse `var R = {...};` out of the generated function into a dict."""
    src = GENERATED.read_text(encoding="utf-8")
    m = re.search(r"var R = (\{.*?\});\nfunction handler", src, re.DOTALL)
    assert m, "could not find the `var R = {...};` table in the generated function"
    return json.loads(m.group(1))


def _simulate(uri: str, table: dict) -> str:
    """Python port of the JS handler. Returns a redirect target, or '' for passthrough."""
    norm = uri
    if len(uri) > 1 and uri[-1] != "/" and "." not in uri:
        norm = uri + "/"
    if norm in table:
        return table[norm]
    if norm != uri:  # #1209: bare extensionless path with no map match
        return norm
    return ""  # passthrough to origin unchanged


def test_bare_doors_301_to_trailing_slash():
    """Each bare door URL 301s to its trailing-slash form — never falls through to /site/*."""
    table = _load_redirect_table()
    for door in DOORS:
        dst = _simulate(door, table)
        assert dst == door + "/", f"{door} should 301 to {door}/, got {dst!r}"
        # And the /site/* leak must never be the destination.
        assert not dst.startswith("/site/"), f"{door} 301s into the internal /site/* prefix: {dst}"


def test_already_slashed_doors_pass_through():
    """A live door with its trailing slash is served by the origin (no redirect loop)."""
    table = _load_redirect_table()
    for door in DOORS:
        assert _simulate(door + "/", table) == "", f"{door}/ should pass through, not redirect"


def test_existing_redirects_preserved():
    """The redirect map still wins for old URLs — bare or slashed both normalize into R."""
    table = _load_redirect_table()
    # Sample a few load-bearing legacy 301s (both bare and slashed forms).
    for src, expected in [
        ("/character", "/cockpit/"),
        ("/character/", "/cockpit/"),
        ("/now/", "/cockpit/"),
        ("/evidence/nutrition", "/data/nutrition/"),
        ("/mind/", "/data/reading/"),
        ("/story/coaches", "/coaching/coaches/"),
    ]:
        assert _simulate(src, table) == expected, f"{src} should 301 to {expected}"


def test_files_and_root_untouched():
    """Paths with an extension, and the root, are never rewritten."""
    table = _load_redirect_table()
    for uri in ["/sw.js", "/favicon.ico", "/robots.txt", "/manifest.webmanifest", "/"]:
        assert _simulate(uri, table) == "", f"{uri} must pass through untouched"


def test_fix_present_in_generator_and_artifact():
    """The #1209 fallback branch lives in BOTH the generator and the generated JS (no drift)."""
    gen = GENERATOR.read_text(encoding="utf-8")
    art = GENERATED.read_text(encoding="utf-8")
    for label, src in (("generator", gen), ("artifact", art)):
        assert "norm !== uri" in src, f"the #1209 bare-path fallback is missing from the {label}"
