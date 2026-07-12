"""Chrome (doors nav + canonical footer) regression guards — #1009 / #1104.

`scripts/v4_chrome.py` is the single source for the doors nav and the `.site-foot`
footer; `scripts/v4_apply_chrome.py` re-flattens every page to it and (since #1104)
converts the retired slim footer variants (`story-foot`, `dx-foot-bar`) on doors-nav
pages to the canonical footer. These tests put chrome drift in the CI Unit Tests gate
(`--check` was previously only run by the attended `sync_site_to_s3.sh` path):

1. `v4_apply_chrome.py --check` must be green — every chrome-bearing page embeds the
   canonical partial byte-exactly, and no content page carries a variant footer.
2. The five pages standardized by #1104 (home, 404, privacy, subscribe, confirm) must
   embed the canonical `site_footer()` — home with its live `data-bind="asof"` stamp.
3. The 0-second redirect stubs (`/mind/`, `/subscribe.html`) must stay chrome-free:
   adding nav/footer to a page that instantly navigates away would be wrong (#1104).
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"

sys.path.insert(0, str(ROOT / "scripts"))
import v4_chrome  # noqa: E402


def _read(rel: str) -> str:
    return (SITE / rel).read_text(encoding="utf-8")


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
    for path in SITE.rglob("*.html"):
        if "legacy" in path.relative_to(SITE).parts:
            continue
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
        assert 'http-equiv="refresh"' in html or "location.replace" in html, f"{rel}: no longer looks like a redirect stub"
