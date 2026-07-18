"""tests/test_wave_render_guard.py — HOME waveform honesty guards (#1214 + #1213).

The home waveform (`site/assets/js/story.js` `renderWave`) had a `meaningfulSpread`
guard that gated only COLOR, leaving two dataviz lies live when the window spread was
below threshold:

  • #1214 — bar HEIGHTS were min-max normalized (14%..100%) regardless of the guard, so
    a real ~2.8% score decline rendered as an ~86% visual collapse.
  • #1213 — the tier fell back to the POSITIVE 'up' (ember) tier, so three monotonically
    declining days painted as three ember 'strong' bars.

The fix extracts the pure height + tier logic into `barHeight()` / `barTier()` inside a
`WAVE_PURE_START … WAVE_PURE_END` marker block. These tests extract that block VERBATIM
and run it under node, so they exercise the ACTUAL shipped source (not a re-typed copy).
Each guard also re-derives the PRE-FIX formula and asserts it VIOLATES the bound — so the
guard is provably non-vacuous: revert the fix and the test goes red.

This is a Python test (collected by the CI `Test` job's full `pytest tests/` sweep, and
by the site PR render gate lane) that shells out to node — node is preinstalled on the
GitHub ubuntu-latest runners the suite runs on, and the repo already depends on it (the
#377 JS parse gate, the Playwright render sweeps).
"""

import os
import re
import shutil
import subprocess
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STORY_JS = os.path.join(_ROOT, "site", "assets", "js", "story.js")


def _extract_pure_block():
    """Return the WAVE_PURE marker block from story.js verbatim (barHeight/barTier/tierOfRel)."""
    with open(_STORY_JS) as f:
        src = f.read()
    m = re.search(r"//\s*>>> WAVE_PURE_START.*?<<< WAVE_PURE_END", src, re.DOTALL)
    assert m, "the WAVE_PURE_START…WAVE_PURE_END marker block must exist in story.js"
    block = m.group(0)
    # Sanity: the extracted block must be self-contained (only tierOfRel is an internal dep).
    for fn in ("function barHeight", "function barTier", "function tierOfRel"):
        assert fn in block, f"extracted block is missing {fn}"
    return block


def _run_node(harness_js):
    node = shutil.which("node")
    assert node, "node is required to run the waveform render guard (present on CI ubuntu-latest)"
    full = _extract_pure_block() + "\n\n" + harness_js
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as tf:
        tf.write(full)
        path = tf.name
    try:
        return subprocess.run([node, path], capture_output=True, text=True)
    finally:
        os.unlink(path)


# The live /api/journey_waveform payload the fullreview verifier reproduced: 3 scored days,
# monotonically declining, all API color:'amber', spread below threshold (len<4).
_FIXTURE = """
const days = [
  { date: "2026-07-14", score: 236.3, color: "amber" },
  { date: "2026-07-15", score: 232.7, color: "amber" },
  { date: "2026-07-16", score: 229.6, color: "amber" },
];
const scores = days.map((d) => d.score || 0).filter(Boolean);
const lo = Math.min(...scores);
const span = Math.max(1, Math.max(...scores) - lo);
const meaningfulSpread = scores.length >= 4 && (Math.max(...scores) - lo) >= 8;
const ratio = Math.max(...scores) / Math.min(...scores);
function assert(c, m) { if (!c) { console.error("GUARD_FAIL: " + m); process.exit(1); } }
assert(meaningfulSpread === false, "fixture must sit below the meaningfulSpread threshold");
"""


def test_height_guard_1214():
    """#1214 — below-threshold, near-1 max/min ratio window: scored bar heights stay near-equal
    (max/min < 1.3), NOT the min-max 100/14 collapse. Proves non-vacuous vs the old formula."""
    harness = (
        _FIXTURE
        + """
assert(ratio < 1.05, "fixture max/min ratio must be <1.05 (guard-1 window); got " + ratio);

// NEW (extracted) heights must be near-equal below threshold.
const nH = days.map((d) => barHeight(d.score, lo, span, meaningfulSpread));
const nMax = Math.max(...nH), nMin = Math.min(...nH);
assert(nMax / nMin < 1.3, "#1214: scored bar height max/min must be <1.3 below threshold; got " + (nMax / nMin));

// NON-VACUOUS: the PRE-FIX min-max formula (14 + pos*86) must VIOLATE the bound.
const oldH = days.map((d) => (d.score ? 14 + ((d.score - lo) / span) * 86 : 6));
const oMax = Math.max(...oldH), oMin = Math.min(...oldH);
assert(oMax / oMin >= 1.3, "pre-fix height must VIOLATE guard-1 (non-vacuous); got ratio " + (oMax / oMin));

console.log("HEIGHT_GUARD_OK new=" + JSON.stringify(nH) + " old_ratio=" + (oMax / oMin).toFixed(2));
"""
    )
    r = _run_node(harness)
    assert r.returncode == 0, f"height guard failed:\nSTDOUT {r.stdout}\nSTDERR {r.stderr}"
    assert "HEIGHT_GUARD_OK" in r.stdout, r.stdout


def test_tier_guard_1213():
    """#1213 — a below-threshold monotonic decline: no scored bar gets tier 'up'. Proves
    non-vacuous by re-deriving the old `: "up"` fallback and asserting it WOULD paint 'up'."""
    harness = (
        _FIXTURE
        + """
// declining precondition
for (let i = 1; i < scores.length; i++) assert(scores[i] < scores[i - 1], "fixture must be monotonically declining");

// NEW (extracted) tiers must never be 'up' below threshold.
const nT = days.map((d) => barTier(d.score, d.score ? (d.score - lo) / span : null, meaningfulSpread));
assert(!nT.includes("up"), "#1213: no scored bar may be tier 'up' below threshold; got " + JSON.stringify(nT));
assert(nT.every((t) => t === "mid"), "#1213: below-threshold scored bars should read 'mid' (muted ink); got " + JSON.stringify(nT));

// NON-VACUOUS: the PRE-FIX fallback (meaningfulSpread ? tierOfRel(pos) : "up") must include 'up'.
const oldT = days.map((d) => (d.score == null ? "none" : meaningfulSpread ? tierOfRel((d.score - lo) / span) : "up"));
assert(oldT.includes("up"), "pre-fix tier must include 'up' (non-vacuous); got " + JSON.stringify(oldT));

console.log("TIER_GUARD_OK new=" + JSON.stringify(nT) + " old=" + JSON.stringify(oldT));
"""
    )
    r = _run_node(harness)
    assert r.returncode == 0, f"tier guard failed:\nSTDOUT {r.stdout}\nSTDERR {r.stderr}"
    assert "TIER_GUARD_OK" in r.stdout, r.stdout
