"""tests/test_freshness_pulse_589.py — the honest freshness pulse (#589).

The pulse must be provably tied to a REAL timestamp, never a decorative loop. Rather
than re-implementing motion.js's predicate in Python (which would test a duplicate,
not the shipped code), this extracts the exact `freshWindowOk` function body from
motion.js (fenced by FRESH_WINDOW_OK_START/END sentinels) and runs it live in Node —
so a regression in the actual shipped file fails this test.
"""

import json
import os
import re
import shutil
import subprocess

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MOTION = os.path.join(_ROOT, "site", "assets", "js", "motion.js")

_NODE = shutil.which("node")


def _motion_source() -> str:
    with open(_MOTION) as f:
        return f.read()


def _extract_fresh_window_ok() -> str:
    src = _motion_source()
    m = re.search(r"// FRESH_WINDOW_OK_START\n(.*?)\n\s*// FRESH_WINDOW_OK_END", src, re.DOTALL)
    assert m, "FRESH_WINDOW_OK_START/END sentinels not found in motion.js — did the primitive move or get renamed?"
    return m.group(1)


def test_primitive_present_in_motion_js():
    src = _motion_source()
    assert "data-fresh-ts" in src
    assert "data-fresh-window" in src
    assert "function freshWindowOk" in src
    assert "wireFreshness" in src


def test_css_primitive_present():
    with open(os.path.join(_ROOT, "site", "assets", "css", "tokens.css")) as f:
        css = f.read()
    assert "[data-fresh-ts].fr-live" in css
    assert "fr-pulse" in css
    # The pulse keyframe itself must be reduced-motion-gated — state (color) is not.
    idx = css.find("@keyframes fr-pulse")
    assert idx != -1
    gated = css[max(0, idx - 400) : idx]
    assert "prefers-reduced-motion: no-preference" in gated


@pytest.mark.skipif(_NODE is None, reason="node not available in this environment")
@pytest.mark.parametrize(
    "label,ts_offset_s,window_s,now_offset_s,expected",
    [
        ("well inside the window", -60, 3600, 0, True),
        ("exactly at the window edge", -3600, 3600, 0, True),
        ("just past the window", -3601, 3600, 0, False),
        ("long stale (a day old, 1h window)", -86400, 3600, 0, False),
        ("within clock-skew grace (ts 30s in the future)", 30, 3600, 0, True),
        ("beyond clock-skew grace (ts 5min in the future)", 300, 3600, 0, False),
    ],
)
def test_fresh_window_ok_tied_to_real_timestamps(label, ts_offset_s, window_s, now_offset_s, expected):
    """Drives the ACTUAL shipped predicate (extracted verbatim) against real instants."""
    fn_src = _extract_fresh_window_ok()
    now_ms = 1_800_000_000_000  # arbitrary fixed instant — deterministic, no wall-clock dependence
    ts_ms = now_ms + ts_offset_s * 1000
    harness = f"""
{fn_src}
console.log(JSON.stringify(freshWindowOk(new Date({ts_ms}).toISOString(), {window_s}, {now_ms} + {now_offset_s} * 1000)));
"""
    out = subprocess.run([_NODE, "-e", harness], capture_output=True, text=True, timeout=10)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout.strip()) is expected, f"{label}: expected {expected}, got {out.stdout!r} ({out.stderr})"


@pytest.mark.skipif(_NODE is None, reason="node not available in this environment")
@pytest.mark.parametrize(
    "ts,window",
    [
        (None, 3600),
        ("not-a-date", 3600),
        ("2026-01-01T00:00:00Z", None),
        ("2026-01-01T00:00:00Z", 0),
        ("2026-01-01T00:00:00Z", -10),
        ("2026-01-01T00:00:00Z", "not-a-number"),
    ],
)
def test_fresh_window_ok_fails_closed_on_bad_input(ts, window):
    """No timestamp / no window / a non-positive window must never pulse — fail closed."""
    fn_src = _extract_fresh_window_ok()
    ts_js = "null" if ts is None else json.dumps(ts)
    window_js = "null" if window is None else json.dumps(window)
    harness = f"""
{fn_src}
console.log(JSON.stringify(freshWindowOk({ts_js}, {window_js}, Date.now())));
"""
    out = subprocess.run([_NODE, "-e", harness], capture_output=True, text=True, timeout=10)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout.strip()) is False
