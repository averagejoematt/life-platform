"""tests/test_portrait_recipes.py — the portrait recipe schema is a contract (#586, ADR-106).

scripts/v4_build_portraits.py is the schema authority AND the bundler; this test pins both:
every checked-in recipe validates, the sign-off gate actually gates, the generated
site/assets/js/portrait_data.js never drifts from a regeneration, and the schema rejects
the failure modes the runbook names (missing head, unknown layers, blown line budget,
missing provenance). Fixtures in tests/fixtures/portraits/ are the two hand-stubbed
placeholder recipes the story ships dark with — they never enter config/portraits/.
"""

import copy
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from scripts.v4_build_portraits import (  # noqa: E402
    LAYER_IDS,
    MAX_STROKED,
    build,
    is_signed,
    load_recipes,
    validate_recipe,
)

FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures", "portraits")
OUT_PATH = os.path.join(ROOT, "site", "assets", "js", "portrait_data.js")


def _fixture(name):
    with open(os.path.join(FIXTURE_DIR, name + ".json")) as f:
        return json.load(f)


def test_placeholder_fixtures_validate():
    for name in ("test_placeholder_a", "test_placeholder_b"):
        recipe = _fixture(name)
        errs = validate_recipe(recipe, persona_id=name)
        assert errs == [], f"{name}: {errs}"
        assert is_signed(recipe), f"{name} fixture must carry a sign_off (it exercises the full schema)"


def test_all_checked_in_recipes_validate():
    # load_recipes raises SystemExit with the problem list on any invalid recipe.
    recipes = load_recipes()
    for pid, recipe in recipes.items():
        assert validate_recipe(recipe, persona_id=pid) == []


def test_generated_bundle_never_drifts():
    content, _skipped = build()
    with open(OUT_PATH) as f:
        on_disk = f.read()
    assert on_disk == content, "portrait_data.js drifted — run: python3 scripts/v4_build_portraits.py"


def test_unsigned_recipes_are_not_bundled():
    # The ADR-106 §3 gate: valid-but-unsigned recipes must be excluded from the bundle.
    unsigned = _fixture("test_placeholder_a")
    unsigned["_meta"].pop("sign_off")
    assert validate_recipe(unsigned, persona_id="test_placeholder_a") == [], "unsigned is still VALID"
    assert not is_signed(unsigned), "…but it must not be SHIPPABLE"


def test_bundle_only_contains_signed_config_recipes():
    content, skipped = build()
    payload = json.loads(content.split("export const PORTRAITS = ", 1)[1].rstrip().rstrip(";"))
    recipes = load_recipes()
    assert set(payload) == {pid for pid, r in recipes.items() if is_signed(r)}
    assert set(skipped) == {pid for pid, r in recipes.items() if not is_signed(r)}
    for pid in payload:
        assert pid not in skipped


def _broken(mutate):
    recipe = copy.deepcopy(_fixture("test_placeholder_a"))
    mutate(recipe)
    return validate_recipe(recipe, persona_id="test_placeholder_a")


def test_schema_rejects_the_named_failure_modes():
    assert _broken(lambda r: r["layers"].pop("head")), "missing head must fail"
    assert _broken(lambda r: r["layers"].update({"props": [{"d": "M0,0 L1,1"}]})), "unknown layer id must fail"
    assert _broken(lambda r: r.update({"viewBox": "0 0 100 100"})), "wrong viewBox must fail"
    assert _broken(lambda r: r.pop("_meta")), "missing provenance must fail"
    assert _broken(lambda r: r["_meta"].pop("traced_by")), "missing tracer must fail"
    assert _broken(lambda r: r["_meta"].update({"source": "some-image-model", "prompt": None})), "model source without prompt must fail"
    assert _broken(lambda r: r["layers"]["eyes-open"][0].update({"d": 'M0,0 <script>"'})), "non-path characters must fail"
    assert _broken(lambda r: r["layers"].update({"hatch": [{"d": "M0,0 l1,1"}] * (MAX_STROKED + 1)})), "blown line budget must fail"


def test_tone_palette_contract():
    # #587 round 4: character-colour tones. A toned element needs a palette entry
    # (accent excepted — it falls back to the coach channel); hexes are validated.
    r = copy.deepcopy(_fixture("test_placeholder_a"))
    r["layers"]["hair"].append({"d": "M0,0 l1,1 Z", "tone": "hair"})
    assert any("without palette entries" in e for e in validate_recipe(r, persona_id="test_placeholder_a"))
    r["palette"] = {"hair": "#4a4a52"}
    assert validate_recipe(r, persona_id="test_placeholder_a") == []
    r["layers"]["hair"].append({"d": "M0,0 l1,1 Z", "tone": "accent"})  # accent needs no entry
    assert validate_recipe(r, persona_id="test_placeholder_a") == []
    r["palette"]["skin"] = "not-a-hex"
    assert any("#rrggbb" in e for e in validate_recipe(r, persona_id="test_placeholder_a"))
    del r["palette"]["skin"]
    r["layers"]["hair"].append({"d": "M0,0 l1,1", "tone": "chrome"})
    assert any("unknown tone" in e for e in validate_recipe(r, persona_id="test_placeholder_a"))


def test_layer_registry_matches_the_runbook():
    # The fixed 13-layer schema (PORTRAIT_RUNBOOK §1) — renderer + validator share it.
    assert LAYER_IDS == (
        "frame",
        "bust",
        "head",
        "hair",
        "brow",
        "eyes-open",
        "eyes-closed",
        "glasses",
        "nose",
        "mouth-rest",
        "mouth-a",
        "mouth-b",
        "hatch",
    )


def test_fixtures_stay_out_of_config():
    shipped = {os.path.basename(p) for p in glob.glob(os.path.join(ROOT, "config", "portraits", "*.json"))}
    assert "test_placeholder_a.json" not in shipped
    assert "test_placeholder_b.json" not in shipped
