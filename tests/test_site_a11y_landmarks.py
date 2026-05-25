"""Guard against accessibility regressions on the two highest-traffic pages.

The 2026-05-24 a11y sweep (P2.4) added skip-links, <main> landmarks, aria-hidden
on the six decorative gauge SVGs, and lifted the --c-text-muted token from a
3.9:1 to 5.2:1 contrast ratio. This test pins those fixes so a future refactor
can't silently drop them.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"


def _read(rel: str) -> str:
    return (SITE / rel).read_text(encoding="utf-8")


def test_homepage_has_skip_link():
    html = _read("index.html")
    assert 'class="skip-link"' in html
    assert 'href="#main"' in html


def test_homepage_has_main_landmark():
    html = _read("index.html")
    assert '<main id="main">' in html
    assert html.count("</main>") >= 1


def test_homepage_gauges_marked_aria_hidden():
    """All six decorative gauge SVGs must be aria-hidden — the gauge value and
    label are in adjacent visible text, so the ring SVG is purely decorative."""
    html = _read("index.html")
    decorative_rings = html.count('viewBox="0 0 88 88" aria-hidden="true"')
    assert decorative_rings >= 6, f"expected ≥6 aria-hidden gauges, found {decorative_rings}"


def test_subscribe_has_skip_link_and_main():
    html = _read("subscribe/index.html")
    assert 'class="skip-link"' in html
    assert '<main id="main">' in html


def test_text_muted_token_passes_contrast():
    """--c-text-muted on #080c0a needs ≥4.5:1. #5a7565 was 3.9:1 (failing);
    #708a7a is 5.2:1 (passing). This pin guards against regression to the
    old value during a future palette change."""
    tokens = (SITE / "assets/css/tokens.css").read_text(encoding="utf-8")
    assert "--c-text-muted:     #708a7a" in tokens
    assert "--c-text-muted:     #5a7565" not in tokens


def test_email_cta_template_uses_h2_not_h3():
    """components.js injects the email-CTA footer into #amj-subscribe on every
    page. It must use <h2> (not <h3>) so heading-order stays sequential under
    the page <h1>."""
    js = (SITE / "assets/js/components.js").read_text(encoding="utf-8")
    assert "'<h2 " in js, "email-CTA template should use <h2>"
    # Specific old line shouldn't reappear.
    assert "'<h3 style=\"font-family:var(--font-display);font-size:var(--text-h3);color:var(--text);" not in js
