"""tests/test_cockpit_carry_scope_guards.py — the cockpit/home scope + carry-forward
regression guards for the #1251 / #1252 / #1244 site-ux slice.

Three reader-facing honesty fixes on the shared cockpit/home front-end:

  • #1251 — the cockpit "daily line" (morning brief's read of YESTERDAY's data) sat
    directly above the last-night panel with no permanent scope label, so its number
    read as conflicting with last night's. The fix stamps an explicit "yesterday's
    read" scope into the PERMANENT attribution (not the dismiss-once intro card).

  • #1252 — carried-forward cross_phase levers (ADR-077) render pre-genesis "as of /
    last prescribed" dates a few days into a fresh cycle, which read as staleness. The
    fix co-renders a "carried from prep" marker when a lever/supplement date predates
    the current cycle's genesis (cockpit training lever + /protocols/ supplements).

  • #1244 — the cycle-vs-cycle "season premiere" comparison (already served by
    /api/cycle_compare) was footer-buried on /method/. The fix adds a SELF-HIDING Home
    beat that appears only inside a fresh cycle (window_days in [1,21], >=1 prior start)
    and disappears once the window has passed.

Each guard extracts the SHIPPED source (a marker block run under node, or the exact
render line) so it exercises real code, and is proven NON-VACUOUS — reverting the fix
turns it red. Python test shelling to node (preinstalled on the CI ubuntu-latest
runners, same shape as tests/test_wave_render_guard.py); imports no layer-only dep, so
it can't red the suite at collection.
"""

import os
import re
import shutil
import subprocess
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_COCKPIT_JS = os.path.join(_ROOT, "site", "assets", "js", "cockpit.js")
_STORY_JS = os.path.join(_ROOT, "site", "assets", "js", "story.js")
_EVIDENCE_BODY_JS = os.path.join(_ROOT, "site", "assets", "js", "evidence_body.js")
_INDEX_HTML = os.path.join(_ROOT, "site", "index.html")


def _read(path):
    with open(path) as f:
        return f.read()


def _extract(src, start, end):
    """Return the //>>> START … <<< END marker block verbatim, or fail loudly."""
    m = re.search(r"//\s*>>> " + re.escape(start) + r".*?<<< " + re.escape(end), src, re.DOTALL)
    assert m, f"the {start}…{end} marker block must exist (the fix is missing)"
    return m.group(0)


def _run_node(harness_js):
    node = shutil.which("node")
    assert node, "node is required for the render guards (present on CI ubuntu-latest)"
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False) as tf:
        tf.write(harness_js)
        path = tf.name
    try:
        return subprocess.run([node, path], capture_output=True, text=True)
    finally:
        os.unlink(path)


_ASSERT = 'function assert(c,m){if(!c){console.error("GUARD_FAIL: "+m);process.exit(1);}}\n'


# ── #1251 — permanent yesterday-scope on the daily line ─────────────────────────
def test_daily_line_carries_permanent_yesterday_scope():
    src = _read(_COCKPIT_JS)
    m = re.search(r'const who = `<p class="vd-who[^`]*`', src)
    assert m, "the vd-who daily-line attribution template must exist in cockpit.js"
    who = m.group(0)
    # The scope must be a PERMANENT token in the attribution itself, not the intro card.
    assert "yesterday" in who.lower(), "#1251: the daily-line attribution must carry an explicit yesterday-scope token; " f"got: {who}"
    # Non-vacuous: the pre-fix template read `the daily line · from the morning brief`
    # with NO scope token — this assertion fails on that string.
    assert "daily line · yesterday" in who.lower(), f"scope token must sit on the daily-line kicker; got: {who}"


# ── #1252 — carried-from-prep marker only for pre-genesis dates (cockpit) ────────
def test_carry_mark_pre_genesis_only():
    block = _extract(_read(_COCKPIT_JS), "CARRY_MARK_START", "CARRY_MARK_END")
    harness = (
        block
        + "\n"
        + _ASSERT
        + """
const GEN = "2026-07-18";
assert(/carried from prep/.test(carryMark("2026-06-26", GEN)), "pre-genesis date must co-render 'carried from prep'");
assert(carryMark("2026-07-20", GEN) === "", "post-genesis date must NOT get the marker");
assert(carryMark("2026-07-18", GEN) === "", "genesis-day date is not pre-genesis");
assert(carryMark("", GEN) === "", "empty date -> no marker");
assert(carryMark("2026-06-26", "") === "", "no genesis -> no marker (fail-soft)");
assert(_isPreGenesis("2026-06-26", GEN) === true, "isPreGenesis true for an earlier date");
assert(_isPreGenesis("2026-07-20", GEN) === false, "isPreGenesis false for a later date");
console.log("CARRY_MARK_OK");
"""
    )
    r = _run_node(harness)
    assert r.returncode == 0, f"carry-mark guard failed:\nSTDOUT {r.stdout}\nSTDERR {r.stderr}"
    assert "CARRY_MARK_OK" in r.stdout, r.stdout


def test_carry_mark_wired_into_training_lever():
    src = _read(_COCKPIT_JS)
    assert (
        "carryMark(when, scrubState.genesis || GENESIS_ISO)" in src
    ), "#1252: the training lever must derive the marker from the runtime genesis"
    assert re.search(
        r"last prescribed \$\{escapeHTML\(when\)\}\$\{carry\}", src
    ), "#1252: the 'last prescribed' branch must append the carry marker"


# ── #1252 — carried-from-prep marker on the /protocols/ supplements 'as of' ──────
def test_supplements_asof_carry_marker():
    src = _read(_EVIDENCE_BODY_JS)
    assert "GENESIS_ISO" in src, "#1252: evidence_body.js must import genesis for the comparison"
    assert "asof < GENESIS_ISO" in src, "#1252: supplements must compare as_of to genesis"
    assert (
        'fig(d.as_of_date, "as of", asofCarried ? "carried from prep" : null)' in src
    ), "#1252: the supplements 'as of' fig must co-render the carried marker when pre-genesis"


# ── #1244 — self-hiding Home season-premiere beat ───────────────────────────────
def test_cycle_beat_self_hides_by_window():
    block = _extract(_read(_STORY_JS), "CYCLE_BEAT_START", "CYCLE_BEAT_END")
    harness = (
        block
        + "\n"
        + _ASSERT
        + """
const cyc = [1,2,3,4,5,6,7].map((n) => ({ cycle: n, genesis: "x" }));

// Fresh cycle, day 4 -> VISIBLE, numbers derived from the API (never hardcoded).
const fresh = cycleBeat({ window_days: 4, current_cycle: 7, cycles: cyc, note: "N" });
assert(fresh && /day 4/.test(fresh.h), "window_days<=21 fresh cycle must render; got: " + JSON.stringify(fresh));
assert(/Start 7/.test(fresh.h), "cycle number must derive from current_cycle; got: " + fresh.h);
assert(/6 starts before/.test(fresh.h), "prior-start count must derive from the API; got: " + fresh.h);
assert(fresh.note === "N", "the API's matched-window note carries through; got: " + fresh.note);

// Past day 21 -> HIDDEN (self-hiding once the window has passed).
assert(cycleBeat({ window_days: 22, current_cycle: 7, cycles: cyc }) === null, "window_days>21 must self-hide");
assert(cycleBeat({ window_days: 28, current_cycle: 7, cycles: cyc }) === null, "a deep window must self-hide");
// Day-21 boundary is inclusive.
assert(cycleBeat({ window_days: 21, current_cycle: 7, cycles: cyc }) !== null, "day 21 is still a fresh window");
// Pre-start -> HIDDEN.
assert(cycleBeat({ window_days: 4, current_cycle: 7, cycles: cyc, pre_start: true }) === null, "pre-start must self-hide");
// No prior cycle -> HIDDEN (nothing to compare against).
assert(cycleBeat({ window_days: 4, current_cycle: 1, cycles: [{ cycle: 1 }] }) === null, "no prior start -> nothing to compare");
// Missing/garbage payload -> HIDDEN.
assert(cycleBeat(null) === null, "no payload -> hidden");
assert(cycleBeat({ window_days: 0, current_cycle: 7, cycles: cyc }) === null, "window 0 (pre-genesis) -> hidden");

// Singular prior wording.
const one = cycleBeat({ window_days: 2, current_cycle: 2, cycles: [{ cycle: 1 }, { cycle: 2 }] });
assert(one && /1 start before/.test(one.h) && !/starts before/.test(one.h), "singular prior wording; got: " + (one && one.h));

console.log("CYCLE_BEAT_OK");
"""
    )
    r = _run_node(harness)
    assert r.returncode == 0, f"cycle-beat guard failed:\nSTDOUT {r.stdout}\nSTDERR {r.stderr}"
    assert "CYCLE_BEAT_OK" in r.stdout, r.stdout


def test_cycle_beat_html_ships_hidden_and_links_reset_log():
    html = _read(_INDEX_HTML)
    assert "data-home-cycle-wrap hidden" in html, "#1244: the Home cycle beat must ship hidden (self-hiding)"
    assert 'href="/method/cycles/"' in html, "#1244: the beat must link the reset log (/method/cycles/)"
    # The self-hiding mount must exist in story.js and be gated on pre-start.
    story = _read(_STORY_JS)
    assert "homeCycleBeat" in story, "#1244: the self-hiding mount IIFE must exist"
    assert 'querySelector("[data-home-cycle-wrap]")' in story, "#1244: the mount must target the beat wrap"
