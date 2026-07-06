"""CI parity guard (#593): the committed portrait PNGs must stay in sync with the signed
recipes. This is the one-source-of-truth check — a recipe edit that isn't re-rendered fails
the build, so a coach's face can never drift between the site's SVG and the off-site PNGs."""

import importlib
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

pytest.importorskip("PIL")  # CI test lanes run without Pillow — skip this parity guard there

render_portraits = importlib.import_module("render_portraits")


def test_portrait_pngs_in_sync_with_recipes():
    problems = render_portraits.check()
    assert problems == [], "portrait PNGs out of sync — run `python3 scripts/render_portraits.py`:\n" + "\n".join(problems)


def test_manifest_covers_every_signed_recipe():
    import json

    import v4_build_portraits as vbp

    with open(render_portraits.MANIFEST) as f:
        manifest = json.load(f)
    recorded = set(manifest.get("portraits", {}))
    signed = {p for p, r in vbp.load_recipes().items() if vbp.is_signed(r)}
    assert recorded == signed


def test_recipe_hash_is_stable_and_changes_on_edit():
    import v4_build_portraits as vbp

    recipe = vbp.load_recipes()["sarah_chen"]
    h1 = render_portraits.recipe_hash(recipe)
    assert h1 == render_portraits.recipe_hash(recipe)  # stable
    edited = dict(recipe)
    edited["version"] = recipe.get("version", 1) + 1
    assert render_portraits.recipe_hash(edited) != h1  # sensitive to change


def test_all_png_files_exist():
    for name, rec in _portraits().items():
        for fname in rec["files"]:
            assert os.path.exists(os.path.join(render_portraits.OUT_DIR, fname)), f"missing {fname}"


def _portraits():
    import json

    with open(render_portraits.MANIFEST) as f:
        return json.load(f).get("portraits", {})
