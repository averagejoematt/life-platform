"""tests/test_recovery_authoring.py — Stage 2 recovery-adaptive authoring core.

One test per edge case in SPEC_RECOVERY_ADAPTIVE_AUTHORING_2026-06-21.md §5, plus the
subtract-only invariant. Pure functions — no AWS, no env, no model. The I/O wrapper in
tools_hevy_routine.py is exercised by the registry/wiring suite; this locks the logic.
"""

from mcp.recovery_authoring import (
    BAND_THRESHOLDS,
    DEFAULT_NOTE,
    LOWER_OF_RULE,
    RPE_BASE_YELLOW,
    RPE_GREEN_BONUS,
    _consecutive_days,
    assess_authoring_freshness,
    build_top_set_branches,
    derive_training_context,
    render_branch_block,
    render_session_block,
)

FRESH_VOL = {"stale": False, "note": "Includes the latest in-window session (2026-06-20)."}
STALE_VOL = {"stale": True, "note": "Aggregation current through 2026-06-19 but a more recent in-window session is ingested (2026-06-20)."}


# ── E3: stale volume blocks the compile (the headline) ──
def test_e3_stale_volume_blocks_authoring():
    r = assess_authoring_freshness(STALE_VOL, "2026-06-20", "2026-06-21")
    assert r["ok"] is False
    assert any(g["input"] == "muscle_volume" for g in r["gaps"])


def test_gate_passes_on_complete_fresh_inputs():
    r = assess_authoring_freshness(FRESH_VOL, "2026-06-20", "2026-06-21")
    assert r["ok"] is True
    assert r["gaps"] == []


def test_gate_flags_missing_recovery():
    r = assess_authoring_freshness(FRESH_VOL, None, "2026-06-21")
    assert r["ok"] is False
    assert any(g["input"] == "recovery" for g in r["gaps"])


def test_gate_flags_stale_recovery():
    # Recovery 5 days before target, default tolerance 2 → gap.
    r = assess_authoring_freshness(FRESH_VOL, "2026-06-16", "2026-06-21")
    assert r["ok"] is False
    assert any(g["input"] == "recovery" for g in r["gaps"])


# ── E1/E2: absent/late morning signal → YELLOW default in the always-present block ──
def test_e1_e2_yellow_default_rendered():
    block = render_session_block(None)
    assert DEFAULT_NOTE in block
    assert "🟡" in block


# ── E4: RED floor branch always present (no improvisation while depleted) ──
def test_e4_red_branch_always_present():
    b = build_top_set_branches(RPE_BASE_YELLOW, None)
    assert "red" in b and b["red"]["cue"]
    assert "🔴" in render_branch_block(b)


# ── E5: lower-of-band/feel rule present + feel-only-downgrades documented ──
def test_e5_lower_of_rule_and_feel_downgrade_only():
    assert LOWER_OF_RULE in render_branch_block(build_top_set_branches(RPE_BASE_YELLOW, None))
    block = render_session_block(None)
    assert LOWER_OF_RULE in block
    assert "never upgrade" in block


# ── E7: each day authored independently of prior-day ACTUALS (pure of them) ──
def test_e7_days_authored_independently():
    hist = ["2026-06-18", "2026-06-19", "2026-06-20"]
    a = derive_training_context(hist, "moderate", "2026-06-21")
    b = derive_training_context(hist, "moderate", "2026-06-25")
    # Same history, different target → independent results, no shared/carried state.
    assert a["consecutive_days"] == 3  # 18,19,20 before the 21st
    assert b["consecutive_days"] == 0  # nothing on 22,23,24 before the 25th


# ── E8: late-week streak raises floors / caps GREEN to quality ──
def test_e8_late_week_caps_green_to_quality():
    hist = ["2026-06-16", "2026-06-17", "2026-06-18", "2026-06-19", "2026-06-20"]
    ctx = derive_training_context(hist, "moderate", "2026-06-21")
    assert ctx["consecutive_days"] == 5
    assert ctx["late_week"] is True
    assert ctx["green_ceiling_quality"] is True
    b = build_top_set_branches(RPE_BASE_YELLOW, ctx)
    # GREEN must NOT add the bonus late-week — it collapses to the yellow baseline.
    assert b["green"]["rpe_cap"] == RPE_BASE_YELLOW


def test_deep_deficit_caps_green_to_quality():
    ctx = derive_training_context([], "deep", "2026-06-21")
    assert ctx["green_ceiling_quality"] is True
    b = build_top_set_branches(RPE_BASE_YELLOW, ctx)
    assert b["green"]["rpe_cap"] == RPE_BASE_YELLOW


def test_early_tissue_ramp_caps_green():
    ctx = derive_training_context([], "moderate", "2026-06-21", tissue_ramp_sessions=2)
    assert ctx["green_ceiling_quality"] is True


# ── E11: the session block is always present (re-stamp absent → branches intact) ──
def test_e11_session_block_always_present():
    assert render_session_block(None).strip() != ""
    assert render_session_block({"reasons": []}).strip() != ""


# ── Subtract-only invariant: green >= yellow >= red, green never exceeds the ceiling ──
def test_subtract_only_invariant():
    ceiling = RPE_BASE_YELLOW + RPE_GREEN_BONUS
    for ctx in (None, derive_training_context([], "moderate", "2026-06-21"), derive_training_context([], "deep", "2026-06-21")):
        b = build_top_set_branches(RPE_BASE_YELLOW, ctx)
        g, y, r = b["green"]["rpe_cap"], b["yellow"]["rpe_cap"], b["red"]["rpe_cap"]
        assert g >= y >= r, f"subtract-only violated: green={g} yellow={y} red={r}"
        assert g <= ceiling, f"green {g} exceeded authored ceiling {ceiling}"


def test_consecutive_days_counts_back_from_target():
    assert _consecutive_days(["2026-06-19", "2026-06-20"], "2026-06-21") == 2
    assert _consecutive_days(["2026-06-18", "2026-06-20"], "2026-06-21") == 1  # 19 missing breaks streak
    assert _consecutive_days([], "2026-06-21") == 0


def test_bands_match_whoop_thresholds():
    assert BAND_THRESHOLDS == {"green_min": 67, "yellow_min": 34}
