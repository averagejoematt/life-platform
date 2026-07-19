"""Chrome (doors nav + loop-forward close + canonical footer) regression guards —
#1009 / #1104 / #1468.

`scripts/v4_chrome.py` is the single source for the doors nav, the `.loop-forward`
"next station on the loop" close, and the `.site-foot` footer; `scripts/v4_apply_chrome.py`
re-flattens every page to it and (since #1104) converts the retired slim footer variants
(`story-foot`, `dx-foot-bar`) on doors-nav pages to the canonical footer. These tests put
chrome drift in the CI Unit Tests gate (`--check` was previously only run by the attended
`sync_site_to_s3.sh` path):

1. `v4_apply_chrome.py --check` must be green — every chrome-bearing page embeds the
   canonical partials byte-exactly, and no content page carries a variant footer.
2. The five pages standardized by #1104 (home, 404, privacy, subscribe, confirm) must
   embed the canonical `site_footer()` — home with its live `data-bind="asof"` stamp.
3. The 0-second redirect stubs (`/mind/`, `/subscribe.html`) must stay chrome-free:
   adding nav/footer to a page that instantly navigates away would be wrong (#1104).
4. #1468 — every doors-nav (real content) page carries exactly one `.loop-forward` close
   with a real forward link, immediately before the footer: the "zero dead-end pages"
   acceptance criterion, verified structurally over the actual page inventory rather
   than a hand-maintained list.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

sys.path.insert(0, str(ROOT / "scripts"))
import v4_chrome  # noqa: E402

LOOP_FWD_RE = re.compile(r'<aside class="loop-forward".*?</aside>', re.DOTALL)
HREF_RE = re.compile(r'<a href="([^"]+)"')


def _read(rel: str) -> str:
    return (SITE / rel).read_text(encoding="utf-8")


def _non_legacy_pages():
    for path in sorted(SITE.rglob("*.html")):
        if "legacy" in path.relative_to(SITE).parts:
            continue
        yield path


def test_apply_chrome_check_is_green():
    """No page's chrome may drift from v4_chrome.py (byte-exact, idempotent)."""
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "v4_apply_chrome.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"chrome drift — run scripts/v4_apply_chrome.py and commit:\n{proc.stdout}\n{proc.stderr}"


def test_standardized_pages_embed_canonical_footer():
    """#1104: the ex-variant pages carry site_footer(); home keeps the live asof stamp."""
    canonical = v4_chrome.site_footer()
    for rel in ("404.html", "privacy/index.html", "subscribe/index.html", "subscribe/confirm/index.html"):
        html = _read(rel)
        assert canonical in html, f"{rel} lost the canonical site_footer()"
    home = _read("index.html")
    assert v4_chrome.site_footer(with_asof=True) in home, "home lost the canonical footer (with the asof stamp)"
    assert 'data-bind="asof"' in home, "home lost the live 'updated' stamp (story.js binds it)"


def test_no_content_page_keeps_a_variant_footer():
    """The slim variants are retired on content pages — one footer, one source (#1104)."""
    for path in _non_legacy_pages():
        html = path.read_text(encoding="utf-8")
        if '<nav class="doors"' in html:
            assert '<footer class="site-foot"' in html, f"{path.relative_to(SITE)}: doors-nav page without the canonical footer"
            assert (
                'class="story-foot"' not in html and 'class="dx-foot-bar"' not in html
            ), f"{path.relative_to(SITE)}: doors-nav page still carries a variant footer"


def test_redirect_stubs_stay_chrome_free():
    """The /mind/ and /subscribe.html redirect stubs must never gain chrome (#1104)."""
    for rel in ("mind/index.html", "subscribe.html"):
        html = _read(rel)
        assert '<nav class="doors"' not in html, f"{rel}: redirect stub grew a doors nav"
        assert "<footer" not in html, f"{rel}: redirect stub grew a footer"
        assert '<aside class="loop-forward"' not in html, f"{rel}: redirect stub grew a loop-forward close"
        assert 'http-equiv="refresh"' in html or "location.replace" in html, f"{rel}: no longer looks like a redirect stub"


def test_every_content_page_has_one_loop_forward_close_before_the_footer():
    """#1468 — zero dead-end pages: every doors-nav page gets exactly one `.loop-forward`
    close with at least one real, non-self href, positioned before the `.site-foot`."""
    checked = 0
    for path in _non_legacy_pages():
        html = path.read_text(encoding="utf-8")
        if '<nav class="doors"' not in html:
            continue
        checked += 1
        matches = LOOP_FWD_RE.findall(html)
        assert len(matches) == 1, f"{path.relative_to(SITE)}: expected exactly one .loop-forward, found {len(matches)}"
        block = matches[0]
        hrefs = HREF_RE.findall(block)
        assert hrefs, f"{path.relative_to(SITE)}: .loop-forward has no forward link"
        for href in hrefs:
            assert href not in ("#", ""), f"{path.relative_to(SITE)}: .loop-forward link is not a real destination ({href!r})"
        lf_pos = html.find(block)
        foot_pos = html.find('<footer class="site-foot"')
        assert foot_pos != -1, f"{path.relative_to(SITE)}: doors-nav page missing the canonical footer"
        assert lf_pos < foot_pos, f"{path.relative_to(SITE)}: .loop-forward must sit before the footer"
    assert checked > 0, "no doors-nav pages found — the sweep didn't run over anything"


def test_loop_forward_never_self_links_the_return_trigger():
    """#1468 audit finding: /subscribe/ and /subscribe/confirm/ swap the universal
    "follow by email" return trigger for a neutral loop link so it never points at
    the page the reader is already reading."""
    for rel in ("subscribe/index.html", "subscribe/confirm/index.html"):
        html = _read(rel)
        block = LOOP_FWD_RE.search(html).group(0)
        assert 'href="/subscribe/"' not in block, f"{rel}: loop-forward return trigger self-links"
