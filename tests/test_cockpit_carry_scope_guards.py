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
    # #1995: the kicker text moved to the ONE shared constant in daily_line.js
    # (BRIEF_LINE_KICKER, imported by cockpit/coaching/story). Resolve it across
    # the module boundary and assert on the RENDERED text, not the reference —
    # a hollowed-out constant must turn this red (the re-export-is-not-a-patch-point
    # lesson applied to a guard).
    daily_line = _read(os.path.join(_ROOT, "site", "assets", "js", "daily_line.js"))
    km = re.search(r'export const BRIEF_LINE_KICKER = "([^"]+)"', daily_line)
    assert km, "#1995: daily_line.js must export the BRIEF_LINE_KICKER constant"
    assert "${BRIEF_LINE_KICKER}" in who, f"#1995: the cockpit attribution must render the shared kicker constant; got: {who}"
    who = who.replace("${BRIEF_LINE_KICKER}", km.group(1))
    # The scope must be a PERMANENT token in the attribution itself, not the intro card.
    assert "yesterday" in who.lower(), "#1251: the daily-line attribution must carry an explicit yesterday-scope token; " f"got: {who}"
    # Non-vacuous: the pre-fix template read `the daily line · from the morning brief`
    # with NO scope token — this assertion fails on that string.
    assert "daily line · yesterday" in who.lower(), f"scope token must sit on the daily-line kicker; got: {who}"


# ── #1252 — carried-from-prep marker only for pre-genesis dates (cockpit) ────────
def test_carry_mark_pre_genesis_only():
    block = _extract(_read(_COCKPIT_JS), "CARRY_MARK_START", "CARRY_MARK_END")
    harness = block + "\n" + _ASSERT + """
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


# ── #1244 RETIRED — the Home season-premiere beat is GONE (launch re-anchor) ────
# Owner decision, 2026-08-31 (the September 1st launch, Session O Phase D1): 2026-09-01
# is the official launch of averagejoematt.com and reads as THE starting point, so the
# home page no longer opens on "Start N, day D — how it compares to the D starts before
# it". The section, its renderer (story.js cycleBeat/homeCycleBeat) and the season banner
# it mounted were removed together.
#
# What this guard pins now is the ABSENCE, and it is deliberately the same shape as the
# old presence guard: a re-added mount, wrap or derivation turns it red, so the retirement
# cannot silently regress on the next site sweep. The comparison itself was NOT retired —
# /api/cycle_compare is unchanged and /method/cycles/ still renders the matched-window
# story — so the two assertions below check the archive route still exists on the site,
# which is what makes removing the home beat a re-placement rather than a deletion.
_RETIRED_HOME_CYCLE_MARKERS = (
    "data-home-cycle-wrap",
    "data-home-cycle-kicker",
    "data-home-cycle-h",
    "data-home-cycle-note",
    'class="beat beat-cycle"',
)


def test_home_season_premiere_beat_stays_retired():
    """The home page must carry no cycle-comparison beat (launch re-anchor, 2026-08-31)."""
    html = _read(_INDEX_HTML)
    # Comments record the retirement; the markers must be absent from the MARKUP.
    markup = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    for marker in _RETIRED_HOME_CYCLE_MARKERS:
        assert marker not in markup, f"the retired home cycle beat is back in site/index.html: {marker}"


def test_home_cycle_renderer_stays_retired():
    """story.js must carry neither the derivation nor the mount — a dead wrap plus a live
    renderer is exactly how this would come back (the renderer would mount into whatever
    [data-home-cycle-wrap] a later edit reintroduces)."""
    story = _read(_STORY_JS)
    code = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", story, flags=re.DOTALL))
    for symbol in ("cycleBeat", "homeCycleBeat", "data-home-cycle-wrap", "CYCLE_BEAT_START"):
        assert symbol not in code, f"the retired home cycle-beat renderer is back in story.js: {symbol}"


def test_the_comparison_story_still_has_a_home_on_the_site():
    """Non-vacuous counterpart: the retirement RE-PLACED the comparison, it did not delete
    it. /method/cycles/ must still exist and still be carried by the method registry (the
    index links its pages from the embedded page-data registry, not from static hrefs)."""
    page = os.path.join(_ROOT, "site", "method", "cycles", "index.html")
    assert os.path.isfile(page), "the matched-window comparison must still live at /method/cycles/"
    method_index = _read(os.path.join(_ROOT, "site", "method", "index.html"))
    assert '"slug": "cycles"' in method_index, "/method/cycles/ must stay in the method registry"
    assert '"endpoint": "/api/cycle_compare"' in method_index, "the comparison must still be served by /api/cycle_compare"
