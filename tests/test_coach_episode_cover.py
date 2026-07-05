"""Tests for scripts/make_coach_episode_cover — per-episode Panel art (#593).

Runs headless: the composer's font loader falls back to Pillow's default when the macOS
system fonts are absent (CI/Linux), so the image still builds and can be asserted on."""

import importlib
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

cover = importlib.import_module("make_coach_episode_cover")
vbp = importlib.import_module("v4_build_portraits")


def _recipes():
    return vbp.load_recipes()


def test_episode_cover_is_1500_square():
    img = cover.build_episode_cover("sarah_chen", _recipes(), cover._members(), title="Building The Base", episode=4)
    assert img.size == (1500, 1500)
    assert img.mode == "RGB"


def test_unsigned_guest_rejected():
    recipes = dict(_recipes())
    fake = {"persona_id": "ghost", "layers": {"head": [{"d": "M10,10 L20,20"}]}, "_meta": {}}
    recipes["ghost"] = fake
    with pytest.raises(SystemExit):
        cover.build_episode_cover("ghost", recipes, {})


def test_cover_composites_two_portraits_when_host_present():
    # With the host recipe present, both host + guest are drawn — the middle band has
    # substantially more non-background pixels than an empty frame would.
    img = cover.build_episode_cover("marcus_webb", _recipes(), cover._members(), episode=5)
    band = img.crop((100, 440, 1400, 910)).convert("RGB")
    non_bg = sum(1 for px in band.getdata() if px != cover.PAGE)
    assert non_bg > 5000
