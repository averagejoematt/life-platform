"""tests/test_legacy_locations_redirects_6115.py — the three retired legacy locations redirect only to a real successor.

Owner ruling 2026-11-16 (#6115): an old address under /chronicle/, /evidence/ or /now/ either lands on the page that
genuinely replaced it, or is gone and returns 404 — "do not redirect unrelated historical pages to the homepage merely
to avoid returning 404". The per-page audit is docs/audits/AUDIT_2026-11-16_legacy_locations.md.

What this pins, offline, over the committed redirects.map and the generated edge function:
  * no redirect from these locations targets `/`;
  * a redirect lands on a door index (/data/, /story/, …) only from a location's own index — a page goes to a page;
  * every destination is a page the current site serves: a page under the repo's site/ tree, a v9 route the build
    declares (www/owned_paths.json), or a data-built v9 route named with its live evidence (KNOWN_V9_DESTINATIONS_6115);
  * the generated CloudFront function carries exactly the map's entries for these locations (what the driver publishes);
  * the guard holds the three locations RETIRED (rule B: must hold nothing), not declared legacy.
"""

import fnmatch
import json
import os
import re
import sys
from pathlib import Path

# premerge-gate: reads the regenerated deploy/generated/v4_redirects_function.js and redirects.map (#3477)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import check_public_copies as G  # noqa: E402
from test_v4_redirects_function import KNOWN_V9_DESTINATIONS_6115  # noqa: E402 — one list of data-built v9 destinations

LOCATIONS = ("/chronicle/", "/evidence/", "/now/")
DOOR_INDEXES = {"/", "/data/", "/story/", "/system/", "/privacy/", "/method/", "/protocols/", "/coaching/", "/start/", "/cockpit/"}
#: A location's own index may land on the door that replaced it (/evidence/ → /data/); nothing else may land on a door.
#: /now/ was the cockpit door itself, renamed to /cockpit/ (#1108) — the same page, not a fallback.
INDEX_SOURCES = set(LOCATIONS)


def _map() -> dict[str, str]:
    out = {}
    for line in (ROOT / "redirects.map").read_text(encoding="utf-8").splitlines():
        if "\t" in line:
            src, dst = line.split("\t", 1)
            out[src] = dst
    return out


def _artifact() -> dict[str, str]:
    src = (ROOT / "deploy" / "generated" / "v4_redirects_function.js").read_text(encoding="utf-8")
    m = re.search(r"var R = (\{.*?\});\nfunction handler", src, re.DOTALL)
    assert m, "no `var R = {...};` table in the generated function"
    return json.loads(m.group(1))


def _legacy(table: dict[str, str]) -> dict[str, str]:
    return {s: d for s, d in table.items() if s.startswith(LOCATIONS)}


def _served(path: str) -> bool:
    owned = json.loads((ROOT / "www" / "owned_paths.json").read_text(encoding="utf-8"))
    if (ROOT / "site" / path.lstrip("/") / "index.html").is_file():
        return True
    if path in KNOWN_V9_DESTINATIONS_6115:
        return True
    return bool(owned.get("live_at_root")) and path in set(owned["routes"]) | set(owned["static_routes"])


def test_every_legacy_redirect_lands_on_a_real_successor():
    legacy = _legacy(_map())
    assert len(legacy) >= 40, f"the legacy redirects went missing from redirects.map ({len(legacy)} found)"
    offenders = []
    for src, dst in sorted(legacy.items()):
        if dst == "/":
            offenders.append(f"{src} → / (the home page is not a successor)")
        elif dst in DOOR_INDEXES and src not in INDEX_SOURCES:
            offenders.append(f"{src} → {dst} (a page sent to a door index)")
        elif not _served(dst):
            offenders.append(f"{src} → {dst} (no page the current site serves)")
        elif any(fnmatch.fnmatchcase(dst, loc + "*") for loc in LOCATIONS):
            offenders.append(f"{src} → {dst} (lands inside a retired location)")
    assert not offenders, "legacy redirects without a real successor:\n  " + "\n  ".join(offenders)


def test_the_published_function_carries_the_maps_legacy_entries():
    """The driver publishes deploy/generated/v4_redirects_function.js; it must say what redirects.map says."""
    in_map, in_js = _legacy(_map()), _legacy(_artifact())
    assert in_map == in_js, (
        f"map-only: {sorted(set(in_map.items()) - set(in_js.items()))}; js-only: {sorted(set(in_js.items()) - set(in_map.items()))} "
        "— regenerate deploy/generated/v4_redirects_function.js from redirects.map (deploy/v4_cutover.sh step 2)"
    )


def test_the_three_locations_are_retired_not_declared_legacy():
    for loc in ("chronicle", "evidence", "now"):
        assert f"site/{loc}/" in G.RETIRED_PREFIXES, f"site/{loc}/ must be retired (rule B: must hold nothing)"
        assert loc not in G.LEGACY_LOCATIONS, f"site/{loc}/ is retired; declaring it legacy would let a re-publication pass"


def test_a_redirect_to_home_from_a_legacy_page_would_be_caught():
    """The rule, shown failing on the shape the owner ruled out (a synthetic map; the real one is untouched)."""
    bad = {"/chronicle/posts/week-01/": "/", "/evidence/stack/": "/data/", "/chronicle/posts/week-02/": "/nowhere/"}
    hits = [
        s
        for s, d in bad.items()
        if d == "/" or (d in DOOR_INDEXES and s not in INDEX_SOURCES) or not _served(d)  # the same three tests as above
    ]
    assert sorted(hits) == sorted(bad), hits
    assert os.path.isdir(ROOT / "site"), "the repo site/ tree is the evidence for most destinations"
