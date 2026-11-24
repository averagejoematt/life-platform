"""tests/test_next_previews_retired_6223.py — the /next/ preview pages are retired, and stay retired (#6223).

Owner authorisation 2026-11-23: the 21 preview pages committed under site/next/ (nine v7 pages, twelve v8 kit pages) are
obsolete — the v9 build has owned the root since 2026-11-01 — and every site deploy was re-publishing them. The
retirement is a repo change, so this file holds the repo to it:

  * nothing is committed under site/next/, and the two generators that wrote there are gone;
  * every retired address is a 301 in redirects.map AND in the generated edge function, to a page the site serves
    today (a page under site/, or one of the v9 build's fixed routes), in one hop, never into /next/ or /legacy/;
  * the v9 rehearsal prefix /next/v9/ is not redirected (deploy/www_preview_sync.sh still rehearses there);
  * the public-copies guard holds site/next/ RETIRED, with the v9 preview carved out;
  * the post-deploy smoke asserts the redirects from the map, not from a second list.

The served objects in S3 are removed by a human with deploy/quarantine_public_copy.sh (the sync never deletes);
scripts/check_public_copies.py rule B is what reports them until then (tests/test_check_public_copies_6083.py).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# premerge-gate: sweeps site/next/ in the repo tree and reads the regenerated redirects.map and deploy/generated/v4_redirects_function.js (#2372, #3477)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_public_copies as G  # noqa: E402
import v4_migration_inventory as INV  # noqa: E402

#: The 21 pages that were committed under site/next/ at the retirement (git ls-files site/next at 6eac5726b), as URLs.
RETIRED = (
    "/next/",
    "/next/coaching/",
    "/next/cockpit/",
    "/next/data/",
    "/next/method/",
    "/next/protocols/",
    "/next/story/",
    "/next/story/about/",
    "/next/subscribe/",
    "/next/v8/",
    "/next/v8/appendix/",
    "/next/v8/built/",
    "/next/v8/call/",
    "/next/v8/coach/",
    "/next/v8/coaches/",
    "/next/v8/day/",
    "/next/v8/sheet/",
    "/next/v8/start/",
    "/next/v8/story/",
    "/next/v8/trend/",
    "/next/v8/week/",
)


def _map() -> dict[str, str]:
    out = {}
    for line in (ROOT / "redirects.map").read_text(encoding="utf-8").splitlines():
        if "\t" in line:
            src, dst = line.split("\t", 1)
            out[src] = dst
    return out


def _edge() -> dict[str, str]:
    src = (ROOT / "deploy" / "generated" / "v4_redirects_function.js").read_text(encoding="utf-8")
    m = re.search(r"var R = (\{.*?\});\nfunction handler", src, re.DOTALL)
    assert m, "no `var R = {...};` table in the generated function"
    return json.loads(m.group(1))


def _served(path: str) -> bool:
    """A page the site serves today: an index.html under site/ that the v9 build does not replace, or a fixed v9 route."""
    owned = json.loads((ROOT / "www" / "owned_paths.json").read_text(encoding="utf-8"))
    if owned.get("live_at_root") and path in set(owned["static_routes"]):
        return True
    return (ROOT / "site" / path.lstrip("/") / "index.html").is_file()


def redirect_findings(table: dict[str, str]) -> list[str]:
    """Everything wrong with `table` as the retirement's redirect set. Empty = every retired address has a real home."""
    out = []
    ours = {s: d for s, d in table.items() if s.startswith("/next/")}
    for src in sorted(set(RETIRED) - set(ours)):
        out.append(f"{src}: retired, with no redirect (the address would 404)")
    for src in sorted(set(ours) - set(RETIRED)):
        out.append(f"{src}: redirected, but not one of the 21 retired pages")
    for src, dst in sorted(ours.items()):
        if src.startswith("/next/v9/"):
            out.append(f"{src}: the v9 rehearsal prefix must not be redirected")
        if dst.startswith(("/next/", "/legacy/")):
            out.append(f"{src} → {dst}: lands in a retired or never-linked location")
        elif dst in table:
            out.append(f"{src} → {dst}: a second hop ({dst} is itself redirected)")
        elif not _served(dst):
            out.append(f"{src} → {dst}: no page the site serves")
    return out


def test_nothing_is_committed_under_the_preview_prefix_and_its_generators_are_gone():
    back = (
        sorted(str(p.relative_to(ROOT)) for p in (ROOT / "site" / "next").rglob("*") if p.is_file())
        if (ROOT / "site" / "next").exists()
        else []
    )
    assert not back, f"files are back under site/next/ — every site deploy would publish them again: {back[:5]}"
    for gone in ("scripts/v7_build.py", "scripts/v7", "scripts/v8_build_appendix.py", "scripts/v8_appendix_pages.json"):
        assert not (ROOT / gone).exists(), f"{gone} writes the retired preview — it was removed with the pages (#6223)"


def test_every_retired_address_redirects_in_one_hop_to_a_page_the_site_serves():
    assert len(RETIRED) == 21 and set(INV.NEXT_PREVIEW_REDIRECTS) == set(RETIRED), "the generator's table is the retired set, exactly"
    in_map = {s: d for s, d in _map().items() if s.startswith("/next/")}
    assert in_map == INV.NEXT_PREVIEW_REDIRECTS, "redirects.map is stale — run python3 scripts/v4_migration_inventory.py"
    in_edge = {s: d for s, d in _edge().items() if s.startswith("/next/")}
    assert (
        in_edge == in_map
    ), "the edge function is stale — regenerate deploy/generated/v4_redirects_function.js (deploy/v4_cutover.sh step 2)"
    findings = redirect_findings(_map())
    assert not findings, "the retired previews' redirects:\n  " + "\n  ".join(findings)


def test_the_redirect_check_can_fail():
    """The control: a missing redirect, a hop into /legacy/, a chain, an unserved target and a redirected v9 preview
    are each named (a synthetic table — the committed map is untouched)."""
    good = _map()
    missing = {s: d for s, d in good.items() if s != "/next/v8/day/"}
    assert any("/next/v8/day/: retired, with no redirect" in f for f in redirect_findings(missing))
    assert any("never-linked" in f for f in redirect_findings({**good, "/next/v8/": "/legacy/"}))
    assert any("second hop" in f for f in redirect_findings({**good, "/next/v8/built/": "/now/"}))
    assert any("no page the site serves" in f for f in redirect_findings({**good, "/next/v8/coach/": "/system/coaches/"}))
    assert any("rehearsal prefix" in f for f in redirect_findings({**good, "/next/v9/": "/"}))


def test_the_guard_and_the_smoke_both_know_the_retirement():
    assert "site/next/" in G.RETIRED_PREFIXES and G.PREVIEW_PREFIX == "site/next/v9/"
    assert "next" not in G.LEGACY_LOCATIONS, "site/next/ is retired; declaring it legacy would let a re-publication pass"
    smoke = (ROOT / "deploy" / "smoke_test_site.sh").read_text(encoding="utf-8")
    block = smoke[smoke.index("Retired /next/ previews") :]
    block = block[: block.index("Bare door URLs")]
    assert "redirects.map" in block and '/next/*) check_redirect "$_old → $_new" "$BASE$_old" "$_new"' in block, "the smoke reads the map"
    assert os.path.isfile(ROOT / "lambdas" / "operational" / "redirect_spotcheck.py"), "the weekly spot-check rotates over the whole map"
