"""#3615 box 5 — no page may advertise a feed the platform declares empty.

THE DEFECT. `https://averagejoematt.com/podcast/feed.xml` is 200 / 593 bytes: a complete
`<channel>` with an `<itunes:author>`, artwork, and ZERO `<item>` elements. Eleven pages
under /story/ carried `<link rel="alternate" type="application/rss+xml" …>` pointing at
it, and every podcast client treats that as a real subscription offer. A reader could
subscribe to a show that has never published an episode — the #3495 class: a claim a
reader would believe that the platform's own data does not support.

WHAT THIS FILE GUARDS, AND WHY IT IS A SET GUARD. The fix is a DERIVATION, not a deleted
line: `scripts/v4_chrome.syndication_links()` emits the feed block minus every feed whose
`hook_registry` cell carries `Absence(contract="declared_dark")`. So there is ONE
statement about whether the podcast has episodes, and both consumers read it — the
nightly census (which probes the live feed) and the site build (which decides whether to
advertise it). The tests below hold the two ends together in BOTH directions:

  * declared dark  → NO committed page may advertise it (the 11-page defect cannot come
    back by way of a hand-edited shell, a new /story/ section, or a fresh generator run);
  * NOT declared dark → the generator-owned shells MUST advertise it. This is the half
    that matters on the day the TTS episodes ship: deleting the Absence without
    re-running `scripts/v4_build_dispatches.py` reds here rather than silently leaving
    the now-real feed unadvertised.

A repo-tree sweep, so it belongs to the pre-merge lane (tests/conftest.py's
`_PREMERGE_EXTRA_FILES`): its verdict depends only on the committed tree, and the failure
it catches — a page that advertises a dead feed — is invisible to anything post-merge.
"""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "lambdas"))

import v4_chrome  # noqa: E402
from operational import hook_registry as reg  # noqa: E402

ALTERNATE_RE = re.compile(r"""<link\b[^>]*\brel=["']alternate["'][^>]*\bhref=["']([^"']+)["'][^>]*>""", re.I)

# The shells `scripts/v4_build_dispatches.py` owns: the /story/ hub plus one per SECTION.
# Derived from the generator itself so a new section joins the population automatically.
import v4_build_dispatches  # noqa: E402

GENERATED_STORY_SHELLS = [REPO / "site" / "story" / "index.html"] + [
    REPO / "site" / "story" / key / "index.html" for key, _label, _desc in v4_build_dispatches.SECTIONS
]


def _site_html():
    """Every committed page under site/, minus the frozen /legacy tree."""
    for path in sorted((REPO / "site").rglob("*.html")):
        if "legacy" in path.relative_to(REPO / "site").parts:
            continue
        yield path


def _advertised_feeds(path: Path):
    return set(ALTERNATE_RE.findall(path.read_text(encoding="utf-8", errors="replace")))


# ── the sweep must not be able to go blind ───────────────────────────────────
def test_the_sweep_finds_feed_links_at_all():
    """A guard that scans an empty set passes forever (#2934)."""
    pages = list(_site_html())
    assert len(pages) >= 50, f"the site sweep found only {len(pages)} pages — it has gone blind"
    advertising = [p for p in pages if _advertised_feeds(p)]
    assert len(advertising) >= 10, "no page advertises any feed — the regex no longer matches the emitted markup"
    assert all(shell.exists() for shell in GENERATED_STORY_SHELLS)


def test_the_registry_still_declares_at_least_one_feed_dark():
    """If this ever goes empty, every assertion below is vacuously true — say so loudly."""
    assert v4_chrome.dark_feeds(), (
        "no hook_registry cell carries Absence(contract='declared_dark') any more. If the podcast feed "
        "gained episodes, that is CORRECT — re-run scripts/v4_build_dispatches.py so the pages advertise "
        "it again, and rewrite this test's floor deliberately."
    )


# ── direction 1: a declared-dark feed is advertised NOWHERE ──────────────────
def test_no_committed_page_advertises_a_declared_dark_feed():
    dark = v4_chrome.dark_feeds()
    offenders = {}
    for path in _site_html():
        named = _advertised_feeds(path) & dark
        if named:
            offenders[str(path.relative_to(REPO))] = sorted(named)
    assert not offenders, (
        "these committed pages advertise a feed the hook registry declares EMPTY, so a reader can subscribe "
        f"to a show with no episodes: {offenders}. Either withdraw the link (re-run the page's generator — the "
        "feed block comes from v4_chrome.syndication_links()) or, if the feed now has episodes, delete its "
        "Absence in lambdas/operational/hook_registry.py and regenerate. (#3615 box 5)"
    )


def test_the_generator_emits_no_declared_dark_feed():
    emitted = set(ALTERNATE_RE.findall(v4_chrome.syndication_links()))
    assert emitted, "syndication_links() emitted nothing at all"
    assert not (emitted & v4_chrome.dark_feeds())


def test_the_story_shell_carries_no_hardcoded_feed_link():
    """The generator must take its feed block from v4_chrome, not from a literal.

    The eleven pages were built from ONE hardcoded three-line block in the shell; a
    re-hardcoded line would reinstate the whole defect in a single commit.
    """
    source = (REPO / "scripts" / "v4_build_dispatches.py").read_text(encoding="utf-8")
    assert "{feeds}" in source
    assert 'rel="alternate"' not in source, "the story shell hardcodes a feed link again — emit v4_chrome.syndication_links()"


# ── direction 2: a feed that is NOT declared dark stays advertised ───────────
def test_every_feed_not_declared_dark_is_still_advertised_on_the_story_shells():
    live_feeds = {href for href, _title in v4_chrome.FEED_LINKS} - v4_chrome.dark_feeds()
    assert live_feeds, "every feed is declared dark — the site now offers no syndication at all, which needs a ruling"
    missing = {}
    for shell in GENERATED_STORY_SHELLS:
        gap = live_feeds - _advertised_feeds(shell)
        if gap:
            missing[str(shell.relative_to(REPO))] = sorted(gap)
    assert not missing, (
        "these generator-owned shells do NOT advertise a feed the registry has not declared dark: "
        f"{missing} — re-run `python3 scripts/v4_build_dispatches.py` so the committed HTML matches the "
        "generator (the stored-artifact regen rule, docs/SITE_UPLEVEL_PLAYBOOK.md)"
    )


# ── the declaration itself has to stay honest ────────────────────────────────
def test_the_podcast_row_declares_a_dated_owned_absence():
    cell = next(((h, a) for h, a in reg.cells() if a.locator == "/podcast/feed.xml"), None)
    assert cell is not None, "the podcast feed lost its registry row — the census would stop probing it entirely"
    _hook, artifact = cell
    assert artifact.absence is not None and artifact.absence.contract == "declared_dark"
    assert artifact.absence.issue and artifact.absence.declared_on
    assert "v4_chrome" in artifact.absence.reason, (
        "the podcast Absence no longer says that the site withholds the advertisement — the declaration and "
        "the withdrawal are one decision and the row is where it is written down"
    )


def test_the_site_build_refuses_to_guess_when_the_registry_is_unreadable(monkeypatch):
    """Fail LOUD, never fall back to 'advertise everything' — that republishes the offer."""
    real_import = __import__

    def _boom(name, *args, **kwargs):
        if name == "operational" or name.startswith("operational."):
            raise ImportError("simulated: registry unreadable")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "operational.hook_registry", raising=False)
    monkeypatch.delitem(sys.modules, "operational", raising=False)
    monkeypatch.setattr("builtins.__import__", _boom)
    try:
        v4_chrome.dark_feeds()
    except RuntimeError as exc:
        assert "hook_registry" in str(exc)
    else:  # pragma: no cover — the whole point is that this branch never runs
        raise AssertionError("dark_feeds() swallowed an unreadable registry and would have advertised every feed")
