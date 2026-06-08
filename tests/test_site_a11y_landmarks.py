"""Guard against accessibility regressions.

The 2026-05-24 a11y sweep (P2.4) added skip-links, <main> landmarks, aria-hidden
on the six decorative gauge SVGs, and lifted the --c-text-muted token from a
3.9:1 to 5.2:1 contrast ratio.

v4 cutover (2026-06-01): the old site is preserved verbatim under site/legacy/
(scripts/v4_relocate_legacy.py). The original guarantees below now pin the
PRESERVED legacy pages; new assertions pin the three v4 doors. System pages
(subscribe) stayed at root and are still checked there.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
LEGACY = SITE / "legacy"


def _read(rel: str) -> str:
    return (SITE / rel).read_text(encoding="utf-8")


def _read_legacy(rel: str) -> str:
    return (LEGACY / rel).read_text(encoding="utf-8")


# ── Preserved legacy guarantees (verbatim old site) ─────────────────────────
def test_legacy_homepage_has_skip_link():
    html = _read_legacy("index.html")
    assert 'class="skip-link"' in html
    assert 'href="#main"' in html


def test_legacy_homepage_has_main_landmark():
    html = _read_legacy("index.html")
    assert '<main id="main">' in html
    assert html.count("</main>") >= 1


def test_legacy_homepage_gauges_marked_aria_hidden():
    """All six decorative gauge SVGs must be aria-hidden — the gauge value and
    label are in adjacent visible text, so the ring SVG is purely decorative."""
    html = _read_legacy("index.html")
    decorative_rings = html.count('viewBox="0 0 88 88" aria-hidden="true"')
    assert decorative_rings >= 6, f"expected ≥6 aria-hidden gauges, found {decorative_rings}"


def test_subscribe_has_skip_link_and_main():
    """subscribe was re-skinned to the v4 design (ADR-071): v4 skip class + <main> landmark."""
    html = _read("subscribe/index.html")
    assert 'class="skip"' in html
    assert '<main id="main"' in html


def test_legacy_text_muted_token_passes_contrast():
    """--c-text-muted on #080c0a needs ≥4.5:1. #5a7565 was 3.9:1 (failing);
    #708a7a is 5.2:1 (passing). Pinned on the preserved legacy tokens."""
    tokens = (LEGACY / "assets/css/tokens.css").read_text(encoding="utf-8")
    assert "--c-text-muted:     #708a7a" in tokens
    assert "--c-text-muted:     #5a7565" not in tokens


def test_legacy_email_cta_template_uses_h2_not_h3():
    """components.js injects the email-CTA footer; must use <h2> (not <h3>) so
    heading-order stays sequential. Pinned on the preserved legacy asset."""
    js = (LEGACY / "assets/js/components.js").read_text(encoding="utf-8")
    assert "'<h2 " in js, "email-CTA template should use <h2>"
    assert "'<h3 style=\"font-family:var(--font-display);font-size:var(--text-h3);color:var(--text);" not in js


# ── v4 doors: every public door needs a skip link + a <main> landmark ───────
V4_DOORS = {
    "Story": "index.html",
    "Cockpit": "now/index.html",
    "Evidence": "evidence/index.html",
}


def test_v4_doors_have_skip_link_and_main():
    for name, rel in V4_DOORS.items():
        html = _read(rel)
        assert 'class="skip"' in html, f"{name} door missing skip link"
        assert "<main" in html and "</main>" in html, f"{name} door missing <main> landmark"


def test_v4_tokens_define_reduced_motion_and_both_modes():
    tokens = (SITE / "assets/css/tokens.css").read_text(encoding="utf-8")
    assert "prefers-reduced-motion: reduce" in tokens, "v4 tokens must ship a reduced-motion fallback"
    assert '[data-theme="light"]' in tokens, "v4 tokens must define an explicit light mode"
    # The one ember accent (Design System §2) must be present.
    assert "--ember:" in tokens


def test_v4_doors_link_tokens_first():
    """tokens.css is the single source of colour/type/spacing — every door loads it."""
    for name, rel in V4_DOORS.items():
        html = _read(rel)
        assert "/assets/css/tokens.css" in html, f"{name} door does not load tokens.css"
