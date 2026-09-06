"""tests/test_v4_build_sitemap_3567.py — #3567.

`v4_build_sitemap.py` used to enumerate `site/**/*.html` directly and filter
with a hand-maintained SKIP_TOP set — a second, drifting vocabulary of "what's
a page" alongside `tests/qa_manifest.py` (the ONE page registry, #1426).
Two concrete defects fell out: `journal/essays/.../body.html` (an authoring
FRAGMENT, never a page) qualified via the glob and, because `url_for()` strips
`.html` from non-index files, shipped as a dead extensionless URL CloudFront
301s to a 404; and `/subscribe.html` (no noindex) shipped as a second entry
alongside its own target `/subscribe/`.

This pins: (1) the sitemap is derived from `tests/qa_manifest.MANIFEST`, not a
filesystem glob — a file present on disk but ABSENT from the registry is
structurally never a candidate, proven with a positive control; (2) neither
dead URL from #3567's own reproduction is in the real, generated sitemap;
(3) every indexable page's `<link rel="canonical">` (asserted PRESENT and
self-matching — the second G-7 acceptance box) — a static, network-free proof
of "returns 200 and is its own canonical" for the local build.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import qa_manifest  # noqa: E402
import v4_build_sitemap as sm  # noqa: E402

SITE = REPO_ROOT / "site"


def test_registry_derivation_ignores_a_file_absent_from_the_registry(tmp_path, monkeypatch):
    """Positive control: a stray file that exists on disk but was never added to
    the page registry must NOT become a sitemap candidate — proving this is a
    registry derivation, not a filesystem glob in disguise."""
    fake_site = tmp_path / "site"
    (fake_site / "real-page").mkdir(parents=True)
    (fake_site / "real-page" / "index.html").write_text("<html><body>real</body></html>", encoding="utf-8")
    # The #3567 defect, reproduced: a fragment that exists on disk...
    (fake_site / "orphan-fragment.html").write_text("<html><body>fragment, not a page</body></html>", encoding="utf-8")

    monkeypatch.setattr(sm, "SITE", fake_site)
    monkeypatch.setattr(sm, "_page_registry", lambda: [{"path": "/real-page/"}])  # orphan-fragment.html NOT registered

    urls = sm.registry_urls()
    assert urls == [f"{sm.BASE}/real-page/"]
    assert not any("orphan" in u for u in urls), "a file absent from the registry must never appear, even though it exists on disk"


def test_registry_derivation_respects_live_noindex():
    """A registered page whose OWN html asserts noindex is excluded (cockpit,
    the redirect stubs) — the same live check as before, just registry-scoped."""
    urls = sm.registry_urls()
    assert f"{sm.BASE}/cockpit/" not in urls, "noindex page leaked into the sitemap"
    assert f"{sm.BASE}/mind/" not in urls
    assert f"{sm.BASE}/subscribe/confirm/" not in urls


def test_real_repo_sitemap_has_no_dead_fragment_or_duplicate_subscribe_url():
    """#3567's exact reproduction, against the real generated site/sitemap.xml."""
    sitemap = (SITE / "sitemap.xml").read_text(encoding="utf-8")
    locs = re.findall(r"<loc>([^<]+)</loc>", sitemap)
    assert f"{sm.BASE}/journal/essays/org-chart-of-one/body" not in locs, "the dead extensionless fragment URL is back"
    assert f"{sm.BASE}/subscribe" not in locs, "the bare, no-trailing-slash duplicate of /subscribe/ is back"
    assert f"{sm.BASE}/subscribe/" in locs, "the real target must still be present"
    assert f"{sm.BASE}/journal/essays/org-chart-of-one/" in locs, "the real essay permalink must still be present"


def test_real_repo_subscribe_html_stub_is_noindex_with_a_matching_canonical():
    html = (SITE / "subscribe.html").read_text(encoding="utf-8")
    assert 'name="robots" content="noindex"' in html
    assert 'rel="canonical" href="https://averagejoematt.com/subscribe/"' in html
    assert 'http-equiv="refresh"' in html, "must still actually redirect"


def test_every_indexable_registry_page_has_a_self_matching_canonical():
    """Static, network-free proof of "every sitemap <loc> ... is its own
    canonical": for each page the sitemap will include, its own <link
    rel="canonical"> must be PRESENT and equal (mod trailing slash) to its own
    sitemap URL. #3567 named /cockpit/ and /subscribe/confirm/ as the two
    live pages missing this tag entirely."""
    missing, mismatched = [], []
    for p in qa_manifest.MANIFEST:
        f = sm.file_for_path(p["path"])
        if not f.exists() or not sm.indexable(f):
            continue
        url = sm.url_for_path(p["path"])
        html = f.read_text(encoding="utf-8")
        m = re.search(r'<link rel="canonical" href="([^"]+)"', html)
        if not m:
            missing.append(url)
        elif m.group(1).rstrip("/") != url.rstrip("/"):
            mismatched.append((url, m.group(1)))
    assert not missing, f"indexable page(s) missing a canonical link: {missing}"
    assert not mismatched, f"indexable page(s) whose canonical disagrees with their own URL: {mismatched}"


def test_positive_control_a_missing_canonical_is_detected(tmp_path):
    """The check above must actually be able to fail."""
    f = tmp_path / "index.html"
    f.write_text("<html><head><title>no canonical here</title></head><body></body></html>", encoding="utf-8")
    html = f.read_text(encoding="utf-8")
    assert re.search(r'<link rel="canonical" href="([^"]+)"', html) is None
