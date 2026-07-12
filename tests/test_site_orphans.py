"""Orphan-page audit (#1111, pairs with #1109's registry flag) — R5.4 posture.

Every page under `site/` must be reachable on purpose: menu/editorial-linked
(a real href somewhere on the site, an archive-registry tile, or a story
sub-nav section) or EXPLICITLY flagged unlisted — either `"unlisted"` in
`scripts/v4_build_evidence.REGISTRY` (footer/direct-URL only, e.g. the ledger)
or a documented entry in UNLISTED_PAGES below. An unlinked-and-unflagged page
fails this test, so the orphan class gets a standing audit instead of periodic
manual discovery (the 2026-07-11 review found /story/agents/ that way).

Link corpus (mirrors the review verifier's zero-href sweep):
  * every `href="…"` in site HTML, including hrefs escaped inside embedded JSON
    (the evidence registry's editorial blocks) — legacy excluded, external
    hosts + assets ignored;
  * directory-shaped absolute-path string literals in site/assets/js/*.js —
    runtime-built links (tiles, popovers, editorial renderers) live there;
  * the archive registries themselves: a listed entry in
    v4_build_evidence.REGISTRY IS the /data/ · /protocols/ · /method/ tile
    rail; v4_build_dispatches.SECTIONS IS the story app's section set.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

sys.path.insert(0, str(ROOT / "scripts"))
import v4_build_dispatches  # noqa: E402
import v4_build_evidence  # noqa: E402
import v4_chrome  # noqa: E402

# Pages with a DELIBERATE reason to have no menu/editorial path. Adding a page
# here is a recorded decision — keep the reason honest. (Registry-unlisted pages
# like /data/ledger/ are flagged at the source instead, per #1109.)
UNLISTED_PAGES = {
    "/mind/": "0-second redirect stub to /data/reading/ — chrome-free by design (#1104)",
    "/subscribe/confirm/": "email-flow landing — reached from the confirmation email, never from menus",
}

HREF = re.compile(r'href=\\?"([^"\\]+)\\?"')  # plain hrefs + hrefs escaped in embedded JSON
JSPATH = re.compile(r'["\'](/[a-z0-9_\-]+(?:/[a-z0-9_\-]+)*/)["\']')  # "/dir/" literals in JS


def _norm(url: str) -> str | None:
    """Site-internal directory URL for an href, else None."""
    url = url.replace("https://averagejoematt.com", "").split("#")[0].split("?")[0]
    if not url.startswith("/"):
        return None
    last = url.rsplit("/", 1)[-1]
    return url if url.endswith("/") else (url if "." in last else url + "/")


def _pages() -> set[str]:
    out = set()
    for p in SITE.rglob("index.html"):
        rel = p.relative_to(SITE).parent
        if "legacy" in rel.parts:
            continue
        out.add("/" if str(rel) == "." else f"/{rel.as_posix()}/")
    return out


def _linked_and_flagged() -> tuple[set[str], set[str]]:
    linked: set[str] = set()
    for p in SITE.rglob("*.html"):
        if "legacy" in p.relative_to(SITE).parts:
            continue
        for m in HREF.finditer(p.read_text(encoding="utf-8")):
            u = _norm(m.group(1))
            if u:
                linked.add(u)
    for p in (SITE / "assets" / "js").glob("*.js"):
        for m in JSPATH.finditer(p.read_text(encoding="utf-8")):
            linked.add(m.group(1))
    flagged: set[str] = set()
    for pillar in v4_build_evidence.PILLARS:
        for e in v4_build_evidence.registry_json(pillar["groups"]):
            (flagged if e.get("unlisted") else linked).add(f"{pillar['base']}{e['slug']}/")
    for key, _label, _desc in v4_build_dispatches.SECTIONS:
        linked.add(f"/story/{key}/")
    return linked, flagged


def test_every_page_is_linked_or_explicitly_unlisted():
    linked, flagged = _linked_and_flagged()
    orphans = sorted(_pages() - linked - flagged - set(UNLISTED_PAGES))
    assert not orphans, (
        f"orphan pages (no href/registry path anywhere, not flagged unlisted): {orphans} — "
        "link each from a menu/footer/editorial surface, or record the unlisted intent "
        '(registry "unlisted" flag / UNLISTED_PAGES here)'
    )


def test_unlisted_allowlist_stays_honest():
    """An UNLISTED_PAGES entry must exist and must still be unlinked — else prune it."""
    pages = _pages()
    linked, _ = _linked_and_flagged()
    for url, reason in UNLISTED_PAGES.items():
        assert url in pages, f"UNLISTED_PAGES has a dead entry {url} ({reason}) — the page is gone, prune it"
        assert url not in linked, f"UNLISTED_PAGES entry {url} is now linked — the flag is stale, prune it"


def test_this_prs_ia_moves_are_live():
    """#1109/#1110/#1111: the footer carries the new homes; build left the sub-nav."""
    foot = v4_chrome.site_footer()
    for url in ("/data/ledger/", "/story/agents/", "/story/build/", "/gear/", "/method/"):
        assert f'href="{url}"' in foot, f"footer lost {url}"
    assert "The Technology" in foot, "footer lost the Technology column (#1110)"
    dispatches_js = (SITE / "assets" / "js" / "dispatches.js").read_text(encoding="utf-8")
    build_entry = next(line for line in dispatches_js.splitlines() if 'key: "build"' in line)
    assert "unlisted: true" in build_entry, "build log is back in the story sub-nav (#1110)"
    ledger = [r for r in v4_build_evidence.REGISTRY if r[0] == "ledger"]
    assert ledger and "unlisted" in ledger[0], "ledger lost its explicit unlisted flag (#1109)"
