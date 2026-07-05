"""Tests for web.portrait_raster — the code-drawn portrait rasterizer (#593, ADR-106)."""

import json
import os

import pytest
from web import portrait_raster as pr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECIPE_DIR = os.path.join(ROOT, "config", "portraits")


def _load(pid):
    with open(os.path.join(RECIPE_DIR, f"{pid}.json")) as f:
        return json.load(f)


def test_path_parser_handles_core_commands():
    # M/L/H/V + Z closes the subpath back to the start
    subs = pr.path_to_subpaths("M10,10 L20,10 H30 V20 Z")
    assert len(subs) == 1
    assert subs[0][0] == (10.0, 10.0)
    assert subs[0][-1] == (10.0, 10.0)  # closed


def test_cubic_bezier_flattens_to_polyline():
    subs = pr.path_to_subpaths("M0,0 C0,10 10,10 10,0")
    assert len(subs) == 1
    assert len(subs[0]) > 2  # curve was sampled into segments
    assert subs[0][-1] == pytest.approx((10.0, 0.0))


def test_relative_and_arc_commands_parse():
    # lowercase (relative) + an arc — must not raise, must produce points
    subs = pr.path_to_subpaths("M50,50 a5,5 0 1 0 3.6,0 l4,4")
    assert subs and all(len(s) >= 1 for s in subs)


def test_render_mono_produces_transparent_ink_stamp():
    recipe = _load("sarah_chen")
    img = pr.render_recipe(recipe, size=96, mode="mono", ink=(236, 227, 210))
    assert img.mode == "RGBA"
    # height == size, width scaled by the 100/120 viewBox aspect
    assert img.height == 96
    assert img.width == round(96 * (100.0 / 120.0))
    alpha = img.getchannel("A")
    opaque = sum(1 for a in alpha.getdata() if a > 10)
    assert opaque > 200  # real line art drawn, not a blank canvas


def test_render_full_paints_palette_tones():
    recipe = _load("sarah_chen")
    mono = pr.render_recipe(recipe, size=96, mode="mono", ink=(236, 227, 210), with_frame=False)
    full = pr.render_recipe(recipe, size=96, mode="full", ink=(236, 227, 210), with_frame=False)
    mono_opaque = sum(1 for a in mono.getchannel("A").getdata() if a > 10)
    full_opaque = sum(1 for a in full.getchannel("A").getdata() if a > 10)
    # tone fills (skin/hair/cloth) cover far more area than ink contours alone
    assert full_opaque > mono_opaque * 2


def test_render_is_deterministic():
    recipe = _load("marcus_webb")
    a = pr.render_recipe(recipe, size=96, mode="full", ink=(236, 227, 210))
    b = pr.render_recipe(recipe, size=96, mode="full", ink=(236, 227, 210))
    assert a.tobytes() == b.tobytes()


def test_every_signed_recipe_renders():
    # No signed recipe should throw in either mode.
    import v4_build_portraits as vbp

    recipes = vbp.load_recipes()
    signed = {p: r for p, r in recipes.items() if vbp.is_signed(r)}
    assert signed, "expected at least one signed recipe"
    for pid, recipe in signed.items():
        for mode in ("mono", "full"):
            img = pr.render_recipe(recipe, size=64, mode=mode, ink=(236, 227, 210))
            assert img.height == 64
