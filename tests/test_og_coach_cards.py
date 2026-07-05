"""Tests for web.og_coach_cards — per-coach OG share cards (#593, ADR-106)."""

import json
import os

from web import og_coach_cards as cc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _recipes():
    import v4_build_portraits as vbp

    return vbp.load_recipes()


def _members():
    with open(os.path.join(ROOT, "config", "board_of_directors.json")) as f:
        return json.load(f).get("members", {})


def test_coach_card_is_1200x630():
    recipes = _recipes()
    members = _members()
    ident = cc.coach_identity("sarah_chen", recipes["sarah_chen"], members)
    img = cc.build_coach_card("sarah_chen", recipes["sarah_chen"], ident)
    assert img.size == (1200, 630)
    assert img.mode == "RGB"


def test_identity_resolves_from_board():
    recipes = _recipes()
    ident = cc.coach_identity("marcus_webb", recipes["marcus_webb"], _members())
    assert ident["name"] == "Dr. Marcus Webb"
    assert ident["title"]
    assert ident["color"].startswith("#")


def test_identity_falls_back_without_board():
    recipes = _recipes()
    ident = cc.coach_identity("sarah_chen", recipes["sarah_chen"], {})
    assert ident["name"] == "Sarah Chen"
    assert ident["title"] == "AI Coach"


def test_build_all_only_signed_recipes():
    recipes = _recipes()
    cards = cc.build_all_coach_cards(recipes, _members())
    # every card corresponds to a signed recipe; unsigned recipes never produce a card
    assert cards
    for name in cards:
        assert name.startswith("og-coach-")
    signed = {p for p, r in recipes.items() if cc._is_signed(r)}
    assert len(cards) == len(signed)


def test_unsigned_recipe_excluded():
    recipes = dict(_recipes())
    # forge an unsigned recipe — must not yield a card
    fake = json.loads(json.dumps(recipes["sarah_chen"]))
    fake["persona_id"] = "unsigned_ghost"
    fake["_meta"].pop("sign_off", None)
    recipes["unsigned_ghost"] = fake
    cards = cc.build_all_coach_cards(recipes, _members())
    assert "og-coach-unsigned-ghost" not in cards


def test_load_signed_recipes_from_bundle():
    text = "// header\n" 'export const PORTRAITS = {"sarah_chen":{"persona_id":"sarah_chen","layers":{}}};\n' "export const ALIASES = {};\n"
    recipes = cc.load_signed_recipes_from_bundle(text)
    assert "sarah_chen" in recipes
    assert recipes["sarah_chen"]["persona_id"] == "sarah_chen"
