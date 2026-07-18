"""#1249 — the home waveform day-bar anchors (.wave a.bar) must reach the 44px
tap-target floor on touch, and visual_qa's tap-target audit must GATE on it.

Renders a faithful waveform (the SHIPPED tokens.css + story.css) in headless
Chromium at a 390px viewport and runs the exact `_tap_target_audit` from
tests/visual_qa.py:

  * with the shipped CSS, the day-bars pass (the #1249 ::after lifts the effective
    touch height to 44px while the visible bar stays ~2px wide);
  * with the #1249 `.wave a.bar::after` rule stripped, the SAME audit flags the
    bars — proving the gate is non-vacuous (it fails on the pre-fix defect).

Uses Playwright (a layer-only dep) → `pytest.importorskip` keeps `--collect-only`
clean where it isn't installed; a missing Chromium browser skips at run time.
"""

import os
import re
import sys

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import visual_qa as VQ  # noqa: E402

CSS_DIR = os.path.join(REPO, "site", "assets", "css")

# The shipped #1249 hit-expander inside tokens.css. Stripping it must resurrect the
# defect — the regex is asserted to match so a rename can't silently no-op the test.
AFTER_RULE_RE = re.compile(r"\.wave a\.bar::after\s*\{[^}]*\}", re.S)


def _css(strip_after=False):
    with open(os.path.join(CSS_DIR, "tokens.css"), encoding="utf-8") as f:
        tokens = f.read()
    with open(os.path.join(CSS_DIR, "story.css"), encoding="utf-8") as f:
        story = f.read()
    if strip_after:
        tokens, n = AFTER_RULE_RE.subn("", tokens)
        assert n == 1, f"expected exactly one .wave a.bar::after rule in tokens.css, found {n}"
    return tokens + "\n" + story


def _harness(css):
    # 60 scored day-bars (low-score → short 13px) crammed into a 390px strip: each is
    # ~4px wide, so both own axes are far below the 44px floor — the exact defect.
    bars = "".join(f'<a class="bar" href="/cockpit/?d={i}" style="height:13px"></a>' for i in range(60))
    return (
        '<!doctype html><html><head><meta name="viewport" content="width=device-width">'
        f"<style>{css}</style></head><body>"
        f'<div class="waveform"><div class="wave"><div class="wave-cpts">{bars}</div></div></div>'
        "</body></html>"
    )


def _probe(css):
    """Render the harness at 390px; return (own_w, own_h of a bar, audit findings)."""
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # browser binary not installed in this env
            pytest.skip(f"Chromium unavailable: {e}")
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.set_content(_harness(css), wait_until="load")
        own = page.evaluate(
            """() => {
            const b = document.querySelector('.wave a.bar');
            if (!b) return null;
            const r = b.getBoundingClientRect();
            return {w: r.width, h: r.height, n: document.querySelectorAll('.wave a.bar').length};
        }"""
        )
        small = VQ._tap_target_audit(page, ".wave a.bar")
        browser.close()
    return own, small


def test_waveform_bars_are_thin_in_both_axes():
    """Precondition: the bars really are below the floor in BOTH own axes, so a passing
    audit is earned by the ::after expander — not by the bars happening to render large."""
    own, _ = _probe(_css())
    assert own and own["n"] == 60, f"harness did not render 60 bars: {own}"
    assert own["w"] < 44 and own["h"] < 44, f"bar own box not sub-floor in both axes: {own}"


def test_shipped_css_passes_the_tap_target_floor():
    """With the shipped #1249 CSS the day-bars clear the gate (effective height ≥ 44px)."""
    _, small = _probe(_css())
    assert small == [], f"shipped .wave a.bar unexpectedly flagged sub-floor: {small}"


def test_audit_is_non_vacuous_fails_without_the_after_rule():
    """Strip the #1249 ::after expander → the SAME audit must flag the bars (pre-fix defect)."""
    _, small = _probe(_css(strip_after=True))
    assert small, "audit did NOT flag the pre-fix 2px×13px day-bars — the gate is vacuous"
    assert any("bar" in s for s in small), f"expected a .wave a.bar finding, got: {small}"
