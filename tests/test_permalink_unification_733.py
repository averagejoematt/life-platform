"""#733 — permalink unification: one content identity, posts in the sitemap, a
subscribe CTA + share affordance on every post.

The distributability contract, pinned so a future edit can't regress it:
  1. RSS items deep-link the per-post permalink (never the hub).
  2. The sitemap includes every published post URL.
  3. Each rendered post carries a subscribe CTA AND a share affordance that shares
     the crawlable permalink.

Assertions are string-presence over the source (the codebase's established
pattern for the vanilla-JS build scripts + ES modules — see test_build_dispatches).
"""

import os

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(rel):
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return f.read()


DISPATCHES_JS = _read("site/assets/js/dispatches.js")
RSS_BUILDER = _read("scripts/v4_build_rss.py")
SITEMAP_BUILDER = _read("scripts/v4_build_sitemap.py")


# ── AC1: RSS links the permalink, not the hub ─────────────────────────────────


def test_rss_items_link_per_post_permalink():
    # each item's <link>/<guid> is built from the post's own url, not a constant hub
    assert 'p.get("url")' in RSS_BUILDER
    assert "<guid" in RSS_BUILDER and 'isPermaLink="true"' in RSS_BUILDER
    assert 'link = f"{BASE}{post_url}"' in RSS_BUILDER


# ── AC2: the sitemap carries every published post URL ─────────────────────────


def test_sitemap_includes_published_post_urls():
    assert "_fetch_posts" in SITEMAP_BUILDER
    assert "post_urls" in SITEMAP_BUILDER
    # a crawler without JS still sees the list (noscript link-list injected into the hub)
    assert "_update_chronicle_noscript" in SITEMAP_BUILDER


# ── AC3: subscribe CTA + share affordance on every post ───────────────────────


def test_every_post_has_a_subscribe_cta():
    assert "dx-subscribe" in DISPATCHES_JS
    assert 'href="/subscribe/"' in DISPATCHES_JS
    assert 'href="/rss.xml"' in DISPATCHES_JS


def test_every_post_has_a_share_affordance():
    assert "dx-share-btn" in DISPATCHES_JS
    assert "shareDispatch" in DISPATCHES_JS
    # native share sheet where supported, clipboard copy otherwise
    assert "navigator.share" in DISPATCHES_JS
    assert "navigator.clipboard" in DISPATCHES_JS


def test_share_uses_the_crawlable_permalink():
    # the shared URL is the post's own permalink (location.origin + ent.url) — the
    # same identity RSS + the sitemap point at, not the in-app hash route by default
    assert "location.origin + ent.url" in DISPATCHES_JS


def test_share_handler_is_wired_after_render():
    assert ".dx-share-btn" in DISPATCHES_JS
    assert "shareDispatch(shb)" in DISPATCHES_JS


def test_share_has_no_blocking_dialog_fallback():
    # per the browser-automation + UX rule: no prompt()/alert()/confirm() fallback
    for banned in ("prompt(", "alert(", "confirm("):
        assert banned not in DISPATCHES_JS, f"share fallback must not use {banned}"
