"""tests/test_vs_band_stamp_clip_3734.py — #3734: text clipped inside its own container.

MEASURED LIVE, 2026-09-16, /data/vitals/ at a 390px viewport:

    band  .vs-band.vs-ember   clientWidth 353   right edge 372.3
    stamp .vs-stamp           width 372.4       right edge 403.2      -> escapes by 30.9px
    document scrollWidth - clientWidth                                -> 0

The sentence "10 days in — baseline still forming" clipped mid-word with no ellipsis and
no signal, and the page-level overflow measure read ZERO — because the band does not
scroll, so the overflow never reaches the viewport. Nine months of mobile sweeps ran over
that page and none could see it.

This file pins three things: that the CSS no longer pins the stamp to one line, that the
SET question the issue asks was answered from source rather than assumed, and that the new
container-level check can actually fail.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "site" / "assets" / "css" / "tokens.css"


def _visual_qa():
    spec = importlib.util.spec_from_file_location("_vq_3734", ROOT / "tests" / "visual_qa.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except SystemExit:  # the module guards a CLI entry point
        pass
    return mod


def _rule(selector: str) -> str:
    m = re.search(rf"^{re.escape(selector)} \{{.*$", TOKENS.read_text(encoding="utf-8"), re.M)
    assert m, f"{selector} rule not found — it was renamed; re-point this assertion, do not delete it"
    return m.group(0)


# ── box 1: the stamp wraps or shrinks rather than clipping ───────────────────────────────
def test_the_stamp_is_no_longer_pinned_to_one_line():
    rule = _rule(".vs-stamp")
    assert (
        "white-space: nowrap" not in rule
    ), "`.vs-stamp` carries a SENTENCE, not a chip — nowrap is what made it 372.4px inside a 353px band"
    assert "min-width: 0" in rule, "without min-width:0 a flex item refuses to shrink below min-content, so wrapping alone does not save it"


def test_the_band_lets_its_children_shrink():
    assert "min-width: 0" in _rule(".vs-band")


# ── box 2: the SET, answered from source rather than assumed ─────────────────────────────
def test_the_sibling_bands_are_CHIPS_not_sentences_so_they_keep_nowrap():
    """The issue says whether the siblings share the shape 'has NOT been measured and is the
    first step, not an assumption'. Answered structurally, which beats a live measurement
    because it cannot go stale between renders:

      .lmk-band  charts.js         an EMPTY <span> positioned by percentage — no text at all
      .vf-band   evidence_body.js  a one-word label chip
      .rcp-band  evidence_meta.js  a one-word tier chip from TIER_BANDS

    One cause, not several. If any of them ever starts carrying flowing text, this test is
    the thing that should be revisited.
    """
    charts = (ROOT / "site" / "assets" / "js" / "charts.js").read_text(encoding="utf-8")
    # The property that matters is EMPTINESS: `<span class="lmk-band" style="...">` with
    # nothing between the tags. Asserted by regex rather than a literal, because the span
    # carries a computed style attribute whose contents legitimately change.
    lmk = re.search(r'<span class="lmk-band"[^>]*>(.*?)</span>', charts, re.S)
    assert lmk, ".lmk-band span not found in charts.js — re-measure the Set (#3734 box 2)"
    assert lmk.group(1).strip() == "", (
        f".lmk-band now carries content ({lmk.group(1)[:40]!r}) — it used to be an empty positioned "
        "span, so the Set answer 'one cause, not several' must be re-measured (#3734 box 2)"
    )
    body = (ROOT / "site" / "assets" / "js" / "evidence_body.js").read_text(encoding="utf-8")
    assert "vf-band label vf-" in body, ".vf-band is no longer a label chip — re-measure the Set"
    meta = (ROOT / "site" / "assets" / "js" / "evidence_meta.js").read_text(encoding="utf-8")
    assert "TIER_BANDS.map" in meta, ".rcp-band is no longer driven by TIER_BANDS — re-measure the Set"


# ── box 3: the must-fail control ─────────────────────────────────────────────────────────
def test_the_container_overflow_check_exists_and_is_wired_into_the_mobile_pass():
    vq = _visual_qa()
    assert hasattr(vq, "_container_text_overflow"), "the #3734 container check is gone"
    assert ".vs-band" in vq.TEXT_CONTAINER_SEL
    src = (ROOT / "tests" / "visual_qa.py").read_text(encoding="utf-8")
    assert "_container_text_overflow(page)" in src, "the check exists but nothing calls it"
    assert "#3734 class" in src, "a finding from this check must name its class so a reader can trace it"


def test_the_check_measures_CONTAINERS_not_the_document():
    """The distinction is the whole point: `document.scrollWidth - clientWidth` read 0 on the
    live defect, because a child overflowing a non-scrolling parent never widens the page."""
    vq = _visual_qa()
    body = vq._container_text_overflow.__doc__ or ""
    assert "scrollWidth" in body, "the docstring must say why scrollWidth is the wrong measure here"
    src = (ROOT / "tests" / "visual_qa.py").read_text(encoding="utf-8")
    fn = src.split("def _container_text_overflow", 1)[1].split("\ndef ", 1)[0]
    assert (
        "getBoundingClientRect" in fn and "scrollWidth" not in fn.split('"""', 2)[-1]
    ), "the implementation must compare RECTS; scrollWidth cannot see this class"


def test_MUTATION_a_planted_overflowing_child_is_reported_and_a_fitting_one_is_not():
    """Drives the real evaluator through a headless page, so the control exercises the
    actual JS rather than a paraphrase of it. Skipped where chromium is unavailable — a
    named skip, never a silent pass (#3640)."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # pragma: no cover
        import pytest

        pytest.skip("SKIPPED in CI — no playwright/chromium (#3640)")

    vq = _visual_qa()
    html = """
      <style>.vs-band{display:flex;width:200px;overflow:visible}
             .wide{width:400px;white-space:nowrap}.narrow{width:50px}</style>
      <div class="vs-band"><span class="wide">xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx</span></div>
      <div class="vs-band"><span class="narrow">ok</span></div>
    """
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 390, "height": 844})
            pg.set_content(html)
            found = vq._container_text_overflow(pg)
            b.close()
    except Exception as exc:  # pragma: no cover
        import pytest

        pytest.skip(f"SKIPPED — chromium unavailable ({type(exc).__name__}) (#3640)")

    classes = {child for _parent, child, _px in found}
    assert "wide" in classes, "a child escaping its container was NOT reported — the check cannot fail"
    assert "narrow" not in classes, "a child that fits was reported — the check cries wolf"
