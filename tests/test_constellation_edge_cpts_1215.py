"""tests/test_constellation_edge_cpts_1215.py — the home constellation's edge evidence
must ride the site's ONE shared readout (#1215).

The constellation edges (measured pillar co-movement) carry r, n, and significance. Before
#1215 that evidence lived ONLY in a native SVG ``<title>`` on a non-focusable ``<line>`` —
hover-only, unreachable on touch and keyboard, and inconsistent with the ``data-cpts`` readout
(``site/assets/js/motion.js``) that every other chart on the site uses. So the ADR-105 ``n``
behind the home page's strongest visual claim was invisible to mobile readers.

The fix (``site/assets/js/story.js`` ``drawConstellation``) publishes one ``data-cpts`` focus
point per edge, at its midpoint, on the svg itself — the exact contract charts.js's radar /
pillar-ring use (``data-cpts`` + ``data-cpts-hit="xy"``). motion.js then wires the shared focus
dot + tip and hover + tap + keyboard exploration, and the native ``<title>`` is dropped.

These tests serve site/ locally (pr_render_gate's harness rules: catch-all route FIRST so
specific mocks win, service workers blocked) with a fixed 3-edge coupling payload, drive the
REAL shipped JS in headless Chromium, and assert what a reader can actually reach:

  * the svg carries a ``data-cpts`` attribute whose point count == the served edge count,
    plus ``data-cpts-hit="xy"``, and NO ``<title>`` survives on the edge lines;
  * motion.js wired the readout: the svg is keyboard-focusable and ArrowRight reveals the
    edge tip (carrying "r=…"), and a synthetic touch pointerdown reveals it too.

Non-vacuity (mirrors the wave-render guard's "revert the fix → red" property): the second
test re-serves the SAME source with the three ``data-cpts`` stamping lines stripped out — the
pre-#1215 behaviour — and asserts the svg then carries NO ``data-cpts`` while the edges still
render, so the guard is provably not vacuous.

Skips cleanly when Playwright (or its chromium) isn't installed.
"""

import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

pytest.importorskip("playwright.sync_api", reason="playwright not installed — render check runs where it is")

from pr_render_gate import _serve, _wait_port  # noqa: E402

_STORY_JS = os.path.join(REPO, "site", "assets", "js", "story.js")

# Three valid edges over NODES keys (see story.js NODES). Signs + significance vary so the
# label text ("r=+…", "r=-…", " (not significant)") is exercised.
_EDGES = [
    {"a": "sleep", "b": "movement", "r": 0.62, "n": 18, "significant": True},
    {"a": "mind", "b": "metabolic", "r": -0.41, "n": 12, "significant": True},
    {"a": "relationships", "b": "consistency", "r": 0.19, "n": 9, "significant": False},
]
_PILLAR_NAMES = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]
_CHARACTER = {
    "character": {"level": 4, "active_effects": []},
    "pillars": [{"name": n, "raw_score": 55, "xp_delta": 1} for n in _PILLAR_NAMES],
}
_COUPLING = {"window_days": 14, "edges": _EDGES}


def _json_handler(payload):
    def _h(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

    return _h


def _routes(context, story_js_override=None):
    """Catch-all FIRST (reverse-match order), then the specific payloads. Optionally serve a
    transformed story.js (used to reproduce the pre-fix state for the non-vacuity check)."""
    context.route("**/api/**", _json_handler({}))
    context.route("**/api/character", _json_handler(_CHARACTER))
    context.route("**/api/pillar_coupling", _json_handler(_COUPLING))
    context.route("**/public_stats.json", _json_handler({}))
    context.route("**/journal/**", _json_handler({}))
    if story_js_override is not None:

        def _story(route):
            route.fulfill(status=200, content_type="text/javascript", body=story_js_override)

        context.route("**/assets/js/story.js", _story)


def _read_constellation(story_js_override=None):
    """Render '/' locally and return a dict describing the constellation svg + a live keyboard
    and touch probe of the readout. Returns None (skip) if chromium is unavailable."""
    from playwright.sync_api import sync_playwright

    base_url, shutdown = _serve(os.path.join(REPO, "site"))
    host, port = base_url.replace("http://", "").split(":")
    assert _wait_port(host, int(port)), "local static server never came up"
    try:
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as e:  # noqa: BLE001 — chromium not installed
                pytest.skip(f"playwright chromium unavailable: {e}")
            context = browser.new_context(viewport={"width": 1440, "height": 900}, service_workers="block")
            _routes(context, story_js_override)
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda e, _errs=errors: _errs.append(str(e)))
            page.goto(base_url + "/", wait_until="networkidle", timeout=30000)
            page.wait_for_selector(".constellation svg [data-edges] line", timeout=8000)
            page.wait_for_timeout(800)  # let the re-attach + motion.js observer settle
            info = page.evaluate(
                """() => {
                const svg = document.querySelector('.constellation svg');
                const raw = svg.getAttribute('data-cpts');
                let cptsLen = null;
                try { const a = JSON.parse(raw); cptsLen = Array.isArray(a) ? a.length : -1; } catch (e) { cptsLen = null; }
                const lines = svg.querySelectorAll('[data-edges] line');
                let titles = 0; lines.forEach(l => { if (l.querySelector('title')) titles++; });
                // keyboard probe: focus the svg, ArrowRight, read the shared tip
                let kbText = null, kbShown = false;
                try {
                    svg.focus();
                    svg.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
                    const tip = document.querySelector('.constellation .chart-tip');
                    if (tip) { kbShown = !tip.hidden; kbText = tip.textContent; }
                } catch (e) {}
                // touch probe: synthetic pointerdown at the first edge midpoint
                let tapShown = false;
                try {
                    const r = svg.getBoundingClientRect();
                    // first edge midpoint: sleep(180,58)-movement(292,118) => (236, 88) in the 360 viewBox
                    const cx = r.left + r.width * (236 / 360), cy = r.top + r.height * (88 / 360);
                    svg.dispatchEvent(new PointerEvent('pointerdown', { clientX: cx, clientY: cy, pointerType: 'touch', bubbles: true }));
                    const tip = document.querySelector('.constellation .chart-tip');
                    tapShown = !!tip && !tip.hidden;
                } catch (e) {}
                return {
                    hasAttr: raw !== null,
                    cptsLen, edgeLines: lines.length, titles,
                    hit: svg.getAttribute('data-cpts-hit'),
                    tabindex: svg.getAttribute('tabindex'),
                    kbShown, kbText, tapShown,
                };
            }"""
            )
            info["errors"] = errors
            page.close()
            browser.close()
            return info
    finally:
        shutdown()


def test_constellation_edge_cpts_landed():
    """POST-FIX: the svg carries data-cpts (one point per edge), data-cpts-hit=xy, no <title>,
    and the readout is reachable by keyboard AND touch (not hover-only)."""
    info = _read_constellation()
    if info is None:
        pytest.skip("render unavailable")
    assert not info["errors"], f"page JS errors: {info['errors']}"
    assert info["edgeLines"] == len(_EDGES), f"expected {len(_EDGES)} edge lines, got {info['edgeLines']}"
    assert info["hasAttr"], "the constellation svg must carry a data-cpts attribute (#1215)"
    assert (
        info["cptsLen"] == info["edgeLines"]
    ), f"data-cpts point count ({info['cptsLen']}) must equal the served edge count ({info['edgeLines']})"
    assert info["hit"] == "xy", "edges are a scatter — the readout must hit-test 2-D (data-cpts-hit='xy')"
    assert info["titles"] == 0, "the native hover-only <title> must be dropped (it would double-announce)"
    assert info["tabindex"] == "0", "motion.js must make the svg keyboard-focusable (shared readout wired)"
    assert info["kbShown"], "ArrowRight must reveal the edge readout (keyboard reachability)"
    assert info["kbText"] and "r=" in info["kbText"], f"keyboard readout must carry the r=… evidence; got {info['kbText']!r}"
    assert info["tapShown"], "a touch pointerdown must reveal the edge readout (touch reachability)"


def test_constellation_edge_cpts_nonvacuous():
    """NON-VACUOUS: strip the three data-cpts stamping lines from the shipped story.js (the
    pre-#1215 behaviour) and the svg then carries NO data-cpts while the edges still render —
    so the landed guard genuinely fails against the pre-fix svg."""
    with open(_STORY_JS) as f:
        src = f.read()
    # Remove ONLY the constellation svg's stamping/re-attach lines (not the wave `inner.` one).
    prefix = re.sub(r'^\s*svg\.setAttribute\("data-cpts.*\n', "", src, flags=re.MULTILINE)
    prefix = re.sub(r"^\s*if \(edgeCpts\.length.*insertBefore\(svg, svg\.nextSibling\);\n", "", prefix, flags=re.MULTILINE)
    assert 'svg.setAttribute("data-cpts"' not in prefix, "strip must remove the svg data-cpts stamping"
    assert 'inner.setAttribute("data-cpts"' in prefix, "strip must NOT touch the wave-cpts data-cpts"

    info = _read_constellation(story_js_override=prefix)
    if info is None:
        pytest.skip("render unavailable")
    assert not info["errors"], f"pre-fix page JS errors: {info['errors']}"
    assert info["edgeLines"] == len(_EDGES), "pre-fix must still render the edges"
    assert not info["hasAttr"], "pre-fix svg must carry NO data-cpts — this is what makes the guard non-vacuous"
