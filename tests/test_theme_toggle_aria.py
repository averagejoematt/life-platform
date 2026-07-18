"""tests/test_theme_toggle_aria.py — the theme toggle exposes its state to AT (#1250).

Before the fix, `site/assets/js/theme.js` set `documentElement.dataset.theme` (and the
`<meta name=theme-color>`) but never touched any aria attribute on `.theme-toggle`. The
button shipped a static `aria-label="Toggle light and dark"` and no `aria-pressed`, so a
screen-reader user could not tell which theme was active or confirm the toggle worked
(WCAG 4.1.2 name/role/value).

The fix adds `syncToggleState()`, called on every apply — from `initTheme` (boot) and
from `setTheme`'s apply (each toggle) — which sets `aria-pressed` (dark = pressed) and
swaps the accessible name to "Switch to light/dark theme".

These tests load the ACTUAL shipped `theme.js` ES module under node with a minimal DOM
mock (no re-typed copy) and assert the button's aria state tracks
`documentElement.dataset.theme` on boot AND after a click. Non-vacuity is baked in:
`test_guard_is_non_vacuous` runs the SAME harness against a mutant of theme.js with the
`aria-pressed` lines stripped and asserts the harness then FAILS — so if a future edit
drops the aria wiring, this test goes red rather than passing on nothing.

Python test (collected by CI's `pytest tests/` sweep) that shells out to node — node is
preinstalled on the GitHub ubuntu-latest runners and the repo already depends on it (the
#377 JS parse gate, the Playwright render sweeps, the #1214 waveform render guard).
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_THEME_JS = os.path.join(_ROOT, "site", "assets", "js", "theme.js")

# A self-contained node harness: mock just enough DOM for theme.js, import the REAL module
# by file URL (argv[2]), then drive boot + toggle and assert aria tracks the active theme.
_HARNESS = r"""
const themeUrl = process.argv[2];

function makeButton() {
  const attrs = {};
  return {
    dataset: {},
    _handlers: {},
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) { return k in attrs ? attrs[k] : null; },
    addEventListener(ev, fn) { this._handlers[ev] = fn; },
  };
}

const btn = makeButton();
let systemLight = false; // OS scheme when no explicit theme is set

global.matchMedia = (q) => ({
  matches: q.includes("prefers-color-scheme: light") ? systemLight : false, // reduced-motion → false
});
global.getComputedStyle = () => ({ getPropertyValue: () => "" });
global.localStorage = { setItem() {}, getItem() { return null; } };
global.document = {
  documentElement: { dataset: {} },
  head: { appendChild() {} },
  getElementById() { return null; },
  createElement() { return { setAttribute() {} }; },
  querySelectorAll(sel) { return sel === ".theme-toggle" ? [btn] : []; },
  // no startViewTransition → setTheme applies synchronously
};

function assert(c, m) { if (!c) { console.error("ARIA_FAIL: " + m); process.exit(1); } }

(async () => {
  const { initTheme, toggleTheme } = await import(themeUrl);

  // --- boot in DARK (pre-paint script set dataset.theme) ---
  document.documentElement.dataset.theme = "dark";
  initTheme();
  assert(btn.getAttribute("aria-pressed") === "true", "boot dark: aria-pressed must be 'true'");
  assert(btn.getAttribute("aria-label") === "Switch to light theme",
    "boot dark: label must invite switching to light; got " + btn.getAttribute("aria-label"));

  // --- click → LIGHT: aria must follow dataset.theme ---
  btn._handlers.click();
  assert(document.documentElement.dataset.theme === "light", "click must flip dataset.theme to light");
  assert(btn.getAttribute("aria-pressed") === "false", "after toggle to light: aria-pressed must be 'false'");
  assert(btn.getAttribute("aria-label") === "Switch to dark theme",
    "after toggle to light: label must invite switching to dark; got " + btn.getAttribute("aria-label"));

  // --- click → DARK again: state stays honest ---
  btn._handlers.click();
  assert(document.documentElement.dataset.theme === "dark", "second click must flip back to dark");
  assert(btn.getAttribute("aria-pressed") === "true", "after toggle back to dark: aria-pressed must be 'true'");

  // --- boot with NO explicit theme, OS = light → aria reflects the rendered (system) theme ---
  const b2 = makeButton();
  document.querySelectorAll = (sel) => (sel === ".theme-toggle" ? [b2] : []);
  document.documentElement.dataset = {}; // no explicit choice
  systemLight = true;
  initTheme();
  assert(b2.getAttribute("aria-pressed") === "false",
    "boot with system-light and no explicit theme: aria-pressed must be 'false'");

  console.log("ARIA_OK");
})().catch((e) => { console.error("ARIA_FAIL(exn): " + (e && e.stack || e)); process.exit(1); });
"""


def _node():
    node = shutil.which("node")
    assert node, "node is required for the theme-toggle aria guard (present on CI ubuntu-latest)"
    return node


def _run_harness(theme_js_path):
    """Run the harness against a given theme.js file; return the completed process."""
    url = Path(theme_js_path).resolve().as_uri()
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as tf:
        tf.write(_HARNESS)
        harness_path = tf.name
    try:
        return subprocess.run([_node(), harness_path, url], capture_output=True, text=True)
    finally:
        os.unlink(harness_path)


def test_toggle_exposes_aria_state():
    """The shipped theme.js sets aria-pressed + accessible name to match dataset.theme on
    boot and after each toggle."""
    r = _run_harness(_THEME_JS)
    assert r.returncode == 0, f"aria guard failed:\nSTDOUT {r.stdout}\nSTDERR {r.stderr}"
    assert "ARIA_OK" in r.stdout, r.stdout


def test_guard_is_non_vacuous():
    """Strip the aria-pressed wiring from a copy of theme.js and prove the SAME harness then
    FAILS — so this guard can never pass on a theme.js that stopped exposing toggle state."""
    with open(_THEME_JS) as f:
        src = f.read()
    mutant = "\n".join(line for line in src.splitlines() if "aria-pressed" not in line)
    assert "aria-pressed" not in mutant, "mutant must not set aria-pressed"
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as tf:
        tf.write(mutant)
        mutant_path = tf.name
    try:
        r = _run_harness(mutant_path)
    finally:
        os.unlink(mutant_path)
    assert r.returncode != 0, f"harness should FAIL on aria-stripped theme.js (non-vacuity); got 0:\n{r.stdout}"
    assert "ARIA_FAIL" in (r.stdout + r.stderr), f"expected an ARIA_FAIL assertion:\n{r.stdout}\n{r.stderr}"
