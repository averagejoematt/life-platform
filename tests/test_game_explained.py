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

import copy
import os
import sys

import pytest

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
    from health import character_engine as ce

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


# ── Cast guard (#1891) ───────────────────────────────────────────────────────
# The page shipped "owner Dr. Peter Attia" — a real, non-consenting clinician
# named as platform staff — because the pillar owners never got the pilot-era
# cast rename. These lock the fix AND prove the guards are not no-ops.


def test_every_pillar_owner_is_on_the_live_roster():
    """The regression guard: an owner off the public roster fails the build."""
    roster = gx.public_roster()
    assert len(roster) >= 8, f"roster resolved to {roster} — the guard would be validating against nothing"
    for name, p in gx.load_config()["pillars"].items():
        owner = p.get("owner")
        assert owner in roster or owner in gx.OWNER_ROLE_LABELS, (
            f"pillar {name!r} owner {owner!r} is not on the live public roster {sorted(roster)} "
            "nor an allowed role label — update config/character_sheet.json to the current cast"
        )


def test_no_real_public_figure_on_the_rendered_page():
    """The published page passes the same privacy gate as AI-published content."""
    gx.assert_no_real_figures(_page())


def test_cast_guard_rejects_a_real_public_figure():
    """Proves the cast guard fires — a guard that never fires is worse than none."""
    config = copy.deepcopy(gx.load_config())
    config["pillars"]["metabolic"]["owner"] = "Dr. Peter Attia"
    with pytest.raises(SystemExit, match="off the live roster"):
        gx.render(config)


def test_cast_guard_rejects_retired_pilot_cast():
    """maya_rodriguez is still IN config/personas.json but off the public roster — must fail."""
    config = copy.deepcopy(gx.load_config())
    config["pillars"]["mind"]["owner"] = "Coach Maya Rodriguez"
    with pytest.raises(SystemExit, match="off the live roster"):
        gx.render(config)


def test_privacy_gate_catches_a_real_figure_outside_the_owner_field():
    """Owner validation alone wouldn't catch a real name in prose; the privacy gate does."""
    from privacy import privacy_guard

    with pytest.raises(privacy_guard.PrivacyViolation):
        gx.assert_no_real_figures("<p>Voice shaped by Andrew Huberman's protocols</p>")


def test_missing_vocabulary_holds_the_regen_instead_of_crashing(monkeypatch, tmp_path):
    """#2370 fail-closed, correctly scoped: no content-filter vocabulary means the
    page must not REGENERATE (the committed artifact was screened when written) —
    but crashing took down the whole reconcile lane over a missing CI secret
    (2026-08-10, three red main runs). main() exits 0 and writes nothing."""
    from privacy.content_filter_channel import ContentFilterUnavailable

    def _raise(*a, **k):
        raise ContentFilterUnavailable("no vocabulary in this environment")

    monkeypatch.setattr(gx, "render", _raise)
    sentinel = tmp_path / "index.html"
    sentinel.write_text("committed artifact", encoding="utf-8")
    monkeypatch.setattr(gx, "OUT_PATH", sentinel)

    assert gx.main() == 0
    assert sentinel.read_text(encoding="utf-8") == "committed artifact"
