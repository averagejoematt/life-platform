"""tests/test_scroll_region_focus_3277.py — keyboard reach for horizontally-scrolling
boxes (#3277).

15 reader pages carried axe `scrollable-region-focusable` (serious) at 390px (33 nodes;
chromium 2026-08-31 live re-measurement, 14/32 in webkit — the one-page difference is
/data/vitals/): the block-scroll tables (.rd-tbl), the code wells (<pre>, .rd-code), one
<figure> and one .rd-drv strip become horizontally-scrolling boxes below the tablet
breakpoint with no way to focus or scroll them from the keyboard — and no gate audited
that viewport.
The fix lives in motion.js as a self-contained primitive (fenced by
SCROLL_REGION_START/END sentinels) that decides scrollability from the LIVE box.

Same discipline as tests/test_freshness_pulse_589.py: rather than re-implementing the
predicate in Python (which would test a duplicate, not the shipped code), this extracts
the exact fenced block from motion.js and runs it in Node against a minimal element
stub — so a regression in the actual shipped file fails here.

NEGATIVE CONTROL (#2578 — an armed gate that cannot fire reads as coverage). The 390px
axe pass is proven able to red by injecting this into a THROWAWAY copy of site/ (never
committed) and running the gate against the copy:

    <style>
      #ctl3277 { width: 200px; white-space: nowrap; overflow-x: hidden; }
      @media (max-width: 700px) { #ctl3277 { overflow-x: auto; } }
    </style>
    <div id="ctl3277" tabindex="-1">
      <span style="display:inline-block;width:2000px">unreachable</span>
    </div>

    cp -R site /tmp/site-trap && <inject into /tmp/site-trap/data/labs/index.html>
    python3 tests/pr_render_gate.py --a11y --site-dir /tmp/site-trap

It scrolls ONLY below the tablet breakpoint (so the desktop pass cannot see it) and
carries tabindex="-1" — programmatic focus, not keyboard reach — which the primitive
never overrides, so what is left being tested is the GATE, not the fix. Recorded verdict
2026-08-31: `NEW serious a11y violation @390px (axe: scrollable-region-focusable) … e.g.
#ctl3277`, 15/16 pages clean, `GATE FAILED`. Two earlier trap shapes did NOT fire, which
is itself the lesson: a `data-scroll-region="auto"` marker is stripped by the desktop
scan and then re-owned at 390 (the fix rescued the trap), and a trap that scrolls at both
viewports proves only the pre-existing desktop pass.
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
    with open(_MOTION, encoding="utf-8") as f:
        return f.read()


def _extract_block() -> str:
    m = re.search(r"// SCROLL_REGION_START\n(.*?)\n\s*// SCROLL_REGION_END", _motion_source(), re.DOTALL)
    assert m, "SCROLL_REGION_START/END sentinels not found in motion.js — did the primitive move or get renamed?"
    return m.group(1)


# ── structural ────────────────────────────────────────────────────────────────


def test_primitive_present_and_runs_before_the_reduced_motion_return():
    """Keyboard reach is not motion: the primitive must execute BEFORE the
    `if (reduce) { … return; }` branch, or reduced-motion readers lose it."""
    src = _motion_source()
    i_block = src.index("// SCROLL_REGION_START")
    i_reduce = src.index("if (reduce) {")
    assert i_block < i_reduce, "scroll-region primitive must run before the reduced-motion early return"
    assert "srScan();" in src[i_block:i_reduce], "the initial scan must happen before the reduced-motion branch"
    assert 'window.addEventListener("resize", srSchedule)' in src, "must re-scan on resize (390 vs 1440 is the whole point)"
    assert "window.__srScan = srScan" in src


def test_motion_js_is_loaded_by_every_page_that_renders_tables_or_code():
    """The primitive only helps pages that load motion.js — every page the live
    re-measurement found carrying the violation must carry the script tag."""
    site = os.path.join(_ROOT, "site")
    affected = (
        "data/vitals",
        "story/attempts",
        "method",
        "method/game",
        "method/grade-your-coach",
        "data/labs",
        "data/habits",
        "method/cycles",
        "method/predictions",
        "method/calibration",
        "method/voicefidelity",
        "method/pipeline",
        "method/wrong",
        "method/verify",
        "method/inference",
    )
    for rel in affected:
        with open(os.path.join(site, rel, "index.html"), encoding="utf-8") as f:
            assert "/assets/js/motion.js" in f.read(), f"/{rel}/ does not load motion.js — the scroll-region fix never runs there"


def test_no_role_region_on_table_in_shipped_markup():
    """role="region" on a <table> destroys table semantics — the primitive never
    does it (SR_NAMED keeps the implicit role) and no shell may hand-add it."""
    block = _extract_block()
    assert "TABLE: 1" in block.split("SR_NAMED")[1].split("\n")[0]
    assert "TABLE" not in block.split("SR_GENERIC = ")[1].split("\n")[0]


def test_generic_elements_get_group_never_the_landmark_role_region():
    """MEASURED, not preferred: with role="region" the same 15-page sweep traded 33
    serious scrollable-region-focusable nodes for 3 NEW moderate `landmark-unique`
    findings (/method/verify/, /method/predictions/, /method/calibration/ — two
    same-named region landmarks in one section). role="group" names the box and adds
    nothing to the landmark menu; the re-measurement introduced zero new rules."""
    block = _extract_block()
    assert '"role", "group"' in block, "generic scroll regions must be role=group"
    assert '"role", "region"' not in block, "role=region is a LANDMARK — it re-introduces landmark-unique (#3277)"


# ── behavioural (the shipped block, run in Node against a stub element) ────────

_HARNESS = r"""
// Minimal element stub: just the surface the fenced block touches.
function makeEl(tag, o) {
  var a = Object.assign({}, o.attrs || {});
  var el = {
    tagName: tag, className: a["class"] || "", namespaceURI: "http://www.w3.org/1999/xhtml",
    scrollWidth: o.scrollWidth, clientWidth: o.clientWidth, _ox: o.overflowX,
    getAttribute: function (k) { return k in a ? a[k] : null; },
    setAttribute: function (k, v) { a[k] = String(v); },
    hasAttribute: function (k) { return k in a; },
    removeAttribute: function (k) { delete a[k]; },
    querySelector: function (sel) {
      if (sel === ":scope > caption" || sel === ":scope > figcaption") return o.caption ? {} : null;
      return o.focusableInside ? {} : null; // the SR_FOCUSABLE descendant probe
    },
    closest: function () { return { querySelector: function () { return o.heading ? { textContent: "  " + o.heading + "\n " } : null; } }; },
    attrs: a,
  };
  return el;
}
globalThis.window = globalThis;
globalThis.document = { body: { getElementsByTagName: function () { return []; } }, querySelector: function () { return null; } };
globalThis.getComputedStyle = function (el) { return { overflowX: el._ox }; };
var cases = JSON.parse(process.argv[1]);
var out = {};
Object.keys(cases).forEach(function (name) {
  var c = cases[name];
  var el = makeEl(c.tag, c);
  srApply(el);
  var after = Object.assign({}, el.attrs);
  var reverted = null;
  if (c.thenShrink) { el.clientWidth = el.scrollWidth; srApply(el); reverted = Object.assign({}, el.attrs); }
  out[name] = { after: after, reverted: reverted };
});
console.log(JSON.stringify(out));
"""

_CASES = {
    # the headline class: a block-scroll .rd-tbl at 390px, no caption/label
    "table_unnamed": {"tag": "TABLE", "scrollWidth": 640, "clientWidth": 358, "overflowX": "auto", "heading": "Lipids", "thenShrink": True},
    # generator tables already carry aria-label (v4_build_game_explained) — keep it, no role change
    "table_labelled": {
        "tag": "TABLE",
        "scrollWidth": 640,
        "clientWidth": 358,
        "overflowX": "auto",
        "attrs": {"aria-label": "sleep components"},
    },
    # the /method/verify/ raw-payload <pre>
    "pre_code_well": {"tag": "PRE", "scrollWidth": 900, "clientWidth": 358, "overflowX": "auto", "heading": "Verify it yourself"},
    # the /data/habits/ .rd-drv div
    "div_strip": {"tag": "DIV", "scrollWidth": 700, "clientWidth": 358, "overflowX": "auto", "attrs": {"class": "rd-drv"}, "heading": None},
    # the /story/attempts/ figure with a figcaption — already named, role must stay figure
    "figure_captioned": {"tag": "FIGURE", "scrollWidth": 640, "clientWidth": 358, "overflowX": "auto", "caption": True},
    # not overflowing (desktop): untouched
    "table_desktop": {"tag": "TABLE", "scrollWidth": 640, "clientWidth": 1200, "overflowX": "auto"},
    # overflowing content but overflow-x hidden/visible: not a scroll region, untouched
    "div_overflow_hidden": {"tag": "DIV", "scrollWidth": 700, "clientWidth": 358, "overflowX": "hidden"},
    # already contains focusable content (the .ev-side tile strip): axe passes it, we leave it
    "strip_with_links": {"tag": "DIV", "scrollWidth": 700, "clientWidth": 358, "overflowX": "auto", "focusableInside": True},
    # already focusable by the author: never override
    "author_tabindex": {"tag": "DIV", "scrollWidth": 700, "clientWidth": 358, "overflowX": "auto", "attrs": {"tabindex": "-1"}},
    # a generic element whose author gave it a role: keep the role, still name + focus it
    "div_with_role": {
        "tag": "DIV",
        "scrollWidth": 700,
        "clientWidth": 358,
        "overflowX": "scroll",
        "attrs": {"role": "group"},
        "heading": "Stack",
    },
}


@pytest.fixture(scope="module")
def outcomes():
    if _NODE is None:
        pytest.skip("node not available in this environment")
    harness = _extract_block() + "\n" + _HARNESS
    run = subprocess.run([_NODE, "-e", harness, json.dumps(_CASES)], capture_output=True, text=True, timeout=20)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout.strip())


def test_block_scroll_table_becomes_focusable_and_named_then_reverts(outcomes):
    after = outcomes["table_unnamed"]["after"]
    assert after["tabindex"] == "0"
    assert after["aria-label"] == "Scrollable table: Lipids"
    assert "role" not in after, "never role=region on a <table>"
    assert after["data-scroll-region"] == "auto"
    # widened back to desktop: everything the primitive added is removed
    assert outcomes["table_unnamed"]["reverted"] == {}


def test_labelled_table_keeps_its_own_name(outcomes):
    after = outcomes["table_labelled"]["after"]
    assert after["tabindex"] == "0" and after["aria-label"] == "sleep components" and "data-sr-label" not in after


def test_pre_and_generic_div_get_group_role_and_name(outcomes):
    pre = outcomes["pre_code_well"]["after"]
    assert pre["tabindex"] == "0" and pre["role"] == "group" and pre["aria-label"] == "Scrollable code: Verify it yourself"
    div = outcomes["div_strip"]["after"]
    assert div["tabindex"] == "0" and div["role"] == "group" and div["aria-label"] == "Scrollable content"


def test_captioned_figure_is_focusable_without_role_or_label_change(outcomes):
    after = outcomes["figure_captioned"]["after"]
    assert after["tabindex"] == "0" and "role" not in after and "aria-label" not in after


@pytest.mark.parametrize("name", ["table_desktop", "div_overflow_hidden", "strip_with_links"])
def test_non_scroll_regions_and_already_reachable_boxes_are_untouched(outcomes, name):
    assert outcomes[name]["after"] == {}, f"{name} must not be touched"


def test_author_tabindex_is_never_overridden(outcomes):
    assert outcomes["author_tabindex"]["after"] == {"tabindex": "-1"}


def test_author_role_is_kept(outcomes):
    after = outcomes["div_with_role"]["after"]
    assert after["role"] == "group" and after["tabindex"] == "0" and after["aria-label"] == "Scrollable content: Stack"
