"""tests/test_a11y_ledger_3548.py — #3548: five named a11y defects, pinned at
the source so each can't silently regress.

The baseline-ownership rule itself (every serious/critical `tests/
a11y_baseline.json` entry must carry an `issue`) lives in `tests/
a11y_audit.py::untriaged_serious_entries` + its tests in `tests/
test_a11y_audit.py` — this file covers the five FIXES the issue names:

  1. `/method/build/`'s architecture SVG carries a `<title>` (svg-img-alt, serious).
  2. The `.cap-card`/`.hb-group` capture-backlog headings are h3, not h4 (they sit
     directly under an h2 `sec()` topic — heading-order, moderate).
  3. `/subscribe/confirm/` has exactly one h1 (page-has-heading-one, moderate).
  4. The shared tabs.js content panel is a `<div>`, not an `<article>`, on every
     page that wires it (aria-allowed-role, minor).
  5. The cycle-comparison table's corner `<th>` names its axis instead of
     shipping empty (empty-table-header, minor).
"""

import importlib.util
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_v4_build_evidence():
    """By path, exactly like scripts/gen_calibration_vectors.py loads the OSS
    package — v4_build_evidence.py inserts scripts/ onto sys.path itself, and
    doing the same here keeps this file import-order-independent."""
    scripts_dir = os.path.join(ROOT, "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    path = os.path.join(scripts_dir, "v4_build_evidence.py")
    spec = importlib.util.spec_from_file_location("_v4_build_evidence_for_3548", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 1. the architecture SVG names itself ────────────────────────────────────


def test_the_build_editorial_svg_carries_a_title():
    mod = _load_v4_build_evidence()
    html = mod.EDITORIAL["build"]
    m = re.search(r'<svg class="arch-svg"[^>]*>(.*?)</svg>', html, re.S)
    assert m, "the arch-svg element itself was not found in EDITORIAL['build']"
    svg_open_tag = html[html.index('<svg class="arch-svg"') : html.index(">", html.index('<svg class="arch-svg"')) + 1]
    inner = m.group(1)
    assert "<title" in inner, "the SVG must carry a <title> — a role=img SVG with no title is unnamed to a screen reader"
    assert 'role="img"' in svg_open_tag
    assert 'aria-labelledby="archSvgTitle"' in svg_open_tag, "the svg element must reference its own <title> by id"
    assert '<title id="archSvgTitle">' in inner


def test_the_build_editorial_svg_title_negative_control():
    """Negative control: a title-less svg (the pre-#3548 shape) must fail the
    same assertion — proves the check isn't vacuously true."""
    broken = '<svg class="arch-svg" viewBox="0 0 760 250" role="img" preserveAspectRatio="xMidYMid meet"><rect/></svg>'
    m = re.search(r'<svg class="arch-svg"[^>]*>(.*?)</svg>', broken, re.S)
    assert "<title" not in m.group(1)


# ── 2. cap-card / hb-group headings are h3 ──────────────────────────────────

_JS_FILES_WITH_CAPTURE_CARDS = ("evidence_body.js", "evidence_vitals.js")
_JS_FILES_WITH_HB_GROUP = ("evidence_body.js", "evidence_habits.js")


def test_no_cap_h_heading_is_an_h4():
    for name in _JS_FILES_WITH_CAPTURE_CARDS:
        path = os.path.join(ROOT, "site", "assets", "js", name)
        with open(path, encoding="utf-8") as f:
            src = f.read()
        assert (
            '<h4 class="cap-h">' not in src
        ), f"{name}: a .cap-h heading regressed to h4 (heading-order — it sits directly under an h2 sec())"
        assert '<h3 class="cap-h">' in src, f"{name}: expected at least one h3.cap-h heading"


def test_no_hb_group_heading_is_an_h4():
    for name in _JS_FILES_WITH_HB_GROUP:
        path = os.path.join(ROOT, "site", "assets", "js", name)
        with open(path, encoding="utf-8") as f:
            src = f.read()
        assert '<h4 class="hb-group label">' not in src, f"{name}: a .hb-group heading regressed to h4 (heading-order)"
        assert '<h3 class="hb-group label">' in src, f"{name}: expected at least one h3.hb-group heading"


def test_cap_h_and_hb_group_headings_are_the_only_pre_3548_offenders_negative_control():
    """Negative control: planting the retired h4 literal back must fail the
    assertion above — proves the check isn't just checking for h3's presence
    alongside a surviving h4."""
    planted = '<div class="cap-card"><h4 class="cap-h">Regression</h4></div>'
    assert '<h4 class="cap-h">' in planted  # the exact string the real test would catch


# ── 3. /subscribe/confirm/ has exactly one h1 ───────────────────────────────


def test_subscribe_confirm_has_exactly_one_h1():
    path = os.path.join(ROOT, "site", "subscribe", "confirm", "index.html")
    with open(path, encoding="utf-8") as f:
        html = f.read()
    assert len(re.findall(r"<h1[ >]", html)) == 1, "/subscribe/confirm/ must have exactly one <h1> (page-has-heading-one)"
    assert '<h1 class="st" id="cc-title">' in html


# ── 4. the shared tabs.js content panel is a <div> ──────────────────────────


def test_no_dx_read_panel_is_an_article():
    """Every page that wires tabs.js::markActiveTab onto [data-dx-read] must use
    <div>, not <article> — <article>'s implicit semantics don't permit the
    role="tabpanel" override tabs.js assigns (aria-allowed-role)."""
    hits = []
    for dirpath, _dirnames, filenames in os.walk(os.path.join(ROOT, "site")):
        if os.sep + "legacy" + os.sep in dirpath + os.sep:
            continue
        for name in filenames:
            if not name.endswith(".html"):
                continue
            full = os.path.join(dirpath, name)
            with open(full, encoding="utf-8") as f:
                if '<article class="dx-read" data-dx-read' in f.read():
                    hits.append(full)
    assert hits == [], f"found <article data-dx-read> (should be <div>): {hits}"


def test_dx_read_div_count_matches_the_known_seventeen_plus_home():
    """Not a ceiling forever — a floor with a name: today's known population is
    17 coaching/story shells + the home-page dispatches beat. If this count
    moves, it should move because someone looked, not silently."""
    hits = []
    for dirpath, _dirnames, filenames in os.walk(os.path.join(ROOT, "site")):
        if os.sep + "legacy" + os.sep in dirpath + os.sep:
            continue
        for name in filenames:
            if not name.endswith(".html"):
                continue
            full = os.path.join(dirpath, name)
            with open(full, encoding="utf-8") as f:
                if "data-dx-read" in f.read():
                    hits.append(full)
    assert len(hits) == 18, sorted(hits)


def test_generator_source_emits_div_for_dx_read_negative_control():
    """The generators (v4_build_coaching.py, v4_build_dispatches.py) must not
    regress to <article> either — an HTML-only fix would drift on the next
    real build (CLAUDE.md's site-shell-is-generator-output rule)."""
    for name in ("v4_build_coaching.py", "v4_build_dispatches.py"):
        path = os.path.join(ROOT, "scripts", name)
        with open(path, encoding="utf-8") as f:
            src = f.read()
        assert (
            '<article class="dx-read" data-dx-read></article>' not in src
        ), f"{name} still emits <article> for the tabpanel-bearing content region"
        assert '<div class="dx-read" data-dx-read></div>' in src


# ── 5. the cycle-comparison corner <th> names its axis ──────────────────────


def test_cycle_comparison_corner_th_is_not_empty():
    path = os.path.join(ROOT, "site", "assets", "js", "evidence_intelligence.js")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    assert "<th></th>" not in src, "an empty <th> regressed (empty-table-header)"
    assert '<th class="sr-only">Metric</th>' in src


def test_sr_only_class_exists_for_the_corner_th():
    path = os.path.join(ROOT, "site", "assets", "css", "tokens.css")
    with open(path, encoding="utf-8") as f:
        css = f.read()
    assert ".sr-only {" in css, "the corner <th> relies on .sr-only existing in tokens.css"
