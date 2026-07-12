"""tests/test_game_explained.py — #1124 "The Game, Explained" drift guards.

The /method/game/ page states the character game's rules from the ACTUAL config
and engine constants. Three things this guards:

  1. Static-page drift (the issue's regression guard): the committed
     site/method/game/index.html must equal the generator's output byte-for-byte,
     so a config tuning change without a regen goes red instead of shipping a
     rulebook that lies about the running game.
  2. Prose drift: the page's mechanics prose (up-gates, neglect decay, the
     confidence blend) was verified against a recorded fingerprint of the
     engine's mechanics functions — same tripwire as methods_registry (#544).
     If this goes red, re-read the prose in scripts/v4_build_game_explained.py
     against lambdas/character_engine.py, then update RECORDED_ENGINE_FINGERPRINT.
  3. Derivation honesty: the load-bearing numbers (pillar weights, XP economy,
     tier bands, streak gates) actually appear on the page, and none of the
     config's emoji fields leak onto it (the site's visual identity is
     emoji-free by design).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

import v4_build_game_explained as gx  # noqa: E402

PAGE_PATH = os.path.join(os.path.dirname(__file__), "..", "site", "method", "game", "index.html")


def _page() -> str:
    with open(PAGE_PATH, encoding="utf-8") as f:
        return f.read()


def test_committed_page_matches_generator():
    """The drift check: config/engine changed => regenerate, or this goes red."""
    assert _page() == gx.render(gx.load_config()), (
        "site/method/game/index.html is stale against config/character_sheet.json + the engine — "
        "run `python3 scripts/v4_build_game_explained.py` and commit the result"
    )


def test_engine_mechanics_fingerprint_current():
    """Engine mechanics changed => a human re-reads the page's prose before shipping."""
    live = gx.engine_fingerprint()
    assert live == gx.RECORDED_ENGINE_FINGERPRINT, (
        f"character_engine mechanics changed (live {live} != recorded {gx.RECORDED_ENGINE_FINGERPRINT}). "
        "Re-read the mechanics prose in scripts/v4_build_game_explained.py against the changed functions, "
        "update RECORDED_ENGINE_FINGERPRINT, and regenerate the page."
    )


def test_load_bearing_config_values_render():
    config = gx.load_config()
    page = _page()
    leveling = config["leveling"]
    # every pillar, its weight, and its owner
    for name, p in config["pillars"].items():
        assert name.capitalize() in page, f"pillar {name} missing from the page"
        assert gx.pct(p["weight"]) in page, f"{name} weight {p['weight']} not rendered"
        assert p.get("owner", "") in page
    # the XP economy
    for key in ("xp_per_level", "xp_debt_cap", "xp_buffer_threshold", "xp_buffer_cap"):
        assert gx.num(leveling[key]) in page, f"leveling.{key} not rendered"
    # every tier band and its streak gates
    for t in config["tiers"]:
        assert t["name"] in page
        assert f'{t["min_level"]}–{t["max_level"]}' in page, f"tier band for {t['name']} not rendered"
    for tier_cfg in leveling["tier_streak_overrides"].values():
        for v in tier_cfg.values():
            assert f"{v} days" in page
    # every cross-pillar effect by name and modifier value
    for e in config.get("cross_pillar_effects", []):
        assert e["name"] in page, f"effect {e['name']} not rendered"
        for spec in e["targets"].values():
            assert gx.signed_pct(spec["value"]) in page
    # every XP band's score floor
    for band in config.get("xp_bands", []):
        assert f'{band["min_raw_score"]}–' in page
    # the coverage freeze + neglect knobs
    assert gx.pct(leveling["level_change_min_coverage"]) in page
    nd = leveling["neglect_decay"]
    assert gx.num(nd["rate"]) in page and gx.num(nd["n_grace_days"]) in page
    # versions: the page must state the engine + config it was generated from
    import character_engine as ce

    assert f"engine v{ce.ENGINE_VERSION}" in page
    assert f'config v{config["_meta"]["version"]}' in page


def test_no_emoji_leaks_from_config():
    """tiers/effects config carry emoji fields — the site's identity system bans them."""
    leaked = sorted({c for c in _page() if ord(c) > 0x2500})
    assert not leaked, f"emoji/high codepoints leaked onto /method/game/: {leaked}"


def test_render_is_deterministic():
    """Byte-stable output is what makes the drift check meaningful."""
    config = gx.load_config()
    assert gx.render(config) == gx.render(config)
