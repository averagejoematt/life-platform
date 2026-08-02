"""#1991 — the axe audit gains a light-theme dimension: proof that a genuinely
light-only WCAG AA contrast regression is caught by a `color_scheme="light"`
Playwright pass and is NOT flagged under `color_scheme="dark"` on the same
fixture — the two passes are independent coverage, not one masking the other.

Renders a synthetic fixture whose CSS swaps colors via `prefers-color-scheme`
(the same OS-theme signal a Playwright context's color_scheme option drives)
so the contrast failure is genuine and theme-gated, not a rigged always-fail.
Runs the REAL tests/a11y_audit.py functions (run_axe/gate_findings) against it
— this is the regression guard the issue's acceptance criterion 3 asks for
("demonstrably catches the known cockpit light-theme failure... or a planted
equivalent").

Uses Playwright (a layer-only dep) → `pytest.importorskip` keeps `--collect-only`
clean where it isn't installed; a missing Chromium browser skips at run time
(memory: reference_test_layer_dep_import_collection_red).
"""

import os
import sys

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import a11y_audit  # noqa: E402

# Pale gray-on-white (~1.6:1) under `prefers-color-scheme: light` — fails the
# 4.5:1 AA floor for normal text hard; swaps to white-on-black (21:1) under
# `prefers-color-scheme: dark` — passes easily. No !important, no cheating:
# only one media query matches at a time, exactly like a reader's OS theme
# does — the same composite-failure class the issue's cockpit finding is
# (opacity/color-mix rules that only fail contrast in one theme). Otherwise a
# complete, valid document (lang attr + <title>) so axe finds nothing else —
# the ONLY finding in play is the planted contrast rule, either theme.
_FIXTURE_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>#1991 fixture</title>
<style>
  body { margin: 0; padding: 24px; font-family: sans-serif; font-size: 16px; background: #fff; }
  @media (prefers-color-scheme: light) {
    .txt { color: #cccccc; background: #ffffff; }
  }
  @media (prefers-color-scheme: dark) {
    body { background: #000000; }
    .txt { color: #ffffff; background: #000000; }
  }
</style></head>
<body><p class="txt">Light-only AA contrast regression fixture (#1991).</p></body>
</html>"""


def _axe_at(scheme):
    """Render the fixture under the given Playwright color_scheme and return
    the real axe-core violations tests/a11y_audit.run_axe() observes."""
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # browser binary not installed in this env
            pytest.skip(f"Chromium unavailable: {e}")
        page = browser.new_page(color_scheme=scheme)
        page.set_content(_FIXTURE_HTML, wait_until="load")
        violations = a11y_audit.run_axe(page)
        browser.close()
    return violations


def test_light_pass_catches_the_planted_light_only_violation():
    """THE proof (#1991 acceptance criterion 3): a light-only AA regression is
    surfaced by color_scheme='light' and, via gate_findings(theme='light')
    against an empty light baseline, lands in the gating 'new' bucket."""
    violations = _axe_at("light")
    cc = [v for v in violations if v["id"] == "color-contrast"]
    assert cc, f"expected a color-contrast violation under color_scheme='light', got: {violations}"
    assert cc[0]["impact"] in ("serious", "critical"), f"expected a gating impact, got {cc[0]['impact']}"

    empty_light_baseline = {"_meta": {}, "pages": {}, "pages_light": {}}
    gated = a11y_audit.gate_findings("/fixture/", violations, empty_light_baseline, theme="light")
    assert "color-contrast" in [v["id"] for v in gated["new"]], f"light-only violation did not gate: {gated}"


def test_dark_pass_does_not_see_the_same_fixture_fail():
    """Same fixture, dark context: the media-query swap makes contrast pass —
    proving the light pass is genuinely independent coverage, not a fixture
    that always fails regardless of theme. Without this, test #1 above could
    pass vacuously (any fixture 'fails' if axe always flags it)."""
    violations = _axe_at("dark")
    cc = [v for v in violations if v["id"] == "color-contrast"]
    assert not cc, f"fixture unexpectedly failed contrast under color_scheme='dark': {cc}"

    # A dark-theme gate over the SAME violations list (defensive — should be
    # empty already) must not gate either: proves the "new" bucket truly
    # reflects what dark observed, not a leftover light-pass finding.
    empty_dark_baseline = {"_meta": {}, "pages": {}, "pages_light": {}}
    gated = a11y_audit.gate_findings("/fixture/", violations, empty_dark_baseline, theme="dark")
    assert gated["new"] == []
