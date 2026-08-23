"""
tests/test_budget_ci_gate_visibility_1927.py — #1927: a budget-paused CI gate must
report PAUSED at the CI surface, and must not be in the first band to die.

The measured defect (#1927, corroborating #1920/ADR-147): `reader_truth_qa` and
`visual_ai_qa` sat at budget_guard cutoff 1, the tier the platform occupies most of
every month, so both AI gates were dark for 26 of 30 days — and the `visual-qa` job
still went green, because a gate that does not run produces no findings.

Two properties are pinned here, and each is negative-tested (i.e. the assertion is
about what the CI OUTPUT says, not about an internal flag):

  1. Re-band — the gates run at every tier below the hard stop (ladder membership
     itself is pinned in tests/test_budget_guard_ladder.py).
  2. Honest pause — when they DO pause (tier 3), every CI surface says so: the
     summary stdout line, the $GITHUB_STEP_SUMMARY block, and a `::warning::`
     annotation (the only one visible without opening the job log), plus the
     operator readout in the daily brief's budget line.

No AWS calls, no Playwright, no Bedrock.
"""

import json
import os
import sys
from datetime import datetime, timezone

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_TESTS_DIR)
for _p in (_TESTS_DIR, os.path.join(_ROOT, "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import visual_ai_qa  # noqa: E402
import visual_qa  # noqa: E402
from ai import budget_guard  # noqa: E402

_HIGH_VERDICT = {
    "renders_ok": False,
    "charts_populated": "no",
    "issues": [{"type": "chart", "severity": "high", "note": "blank chart frame"}],
    "severity": "high",
    "summary": "chart frame drawn but empty",
}


def _fake_bedrock(calls):
    def invoke(body, model_name=None):
        calls.append(body)
        return {"content": [{"type": "text", "text": json.dumps(_HIGH_VERDICT)}]}

    return type("B", (), {"invoke": staticmethod(invoke)})()


# A real 20x20 PNG (1039 bytes) — the fixture must be the wire twice over:
# _assess_page drops captures <= 256 bytes as empty-crop noise, and #3013's
# _prepare_image sniffs the IHDR and honestly refuses unparseable captures
# BEFORE any Bedrock call. The old `b"\x89PNG" + b"0"*300` fake passed the size
# filter but now (correctly) dies at the IHDR sniff, so this suite would measure
# the refusal path instead of the gate it exists to pin.
_REAL_PNG = __import__("base64").b64decode(
    "iVBORw0KGgoAAAAN"
    "SUhEUgAAABQAAAAUCAIAAAAC64paAAAD1klEQVR4AWNgUPXKn7LzHrOGb9H0PQ/ZtANKZ+1/wqkXXDH30HMew7DqBUdf8ZtE1i0+8VbIPKZx2ekPolbx"
    "LSvPfZawTWpniG5cfvazpH1cy6oL32ScEtvXXv4p75rSteHaHyWP9N7NN/+remdN2HaHScMvd/LO+6zagQXT9jzi0Aspnrn/KcO2uyza3kUzdz5g1/Mr"
    "nbPnMZdhYMX8/c94TUKqFx16KWAeXrf06Bthq6jGFSfei9nGtqw+/UnSIaF93bmvMs4MgpaJTatOfxaxSWlde+6buH16x4aLP6Wcsro3X/kj65rbt+36"
    "fwWPgok7bzEpexdP2XOXVc2vbPr+BxyagZWzGHKmbn/ApO2bP2PXY1a9gKLZe59xGAaXzjvwktskrGLh4Td85pHVS469F7SKqVt+8pOIbXzjqjNfxR2S"
    "Wtae/8Fw/KOIeWLL8lNfxK1S2led/S5lm9619sIvWYes3g2X/yo4507YfI1B2a1g8rabzGqexdN23mHT9Cmbuec+p44/g5Jv4dSddxlVA0pm7HnAohFc"
    "Pnv/Y3btsKp5h55x6UXWLjz6ktcwpmHJiTcCJvHNy0+/FzZPalt17pOYVWrnWobaRcffCJpFNyw99V7EMq55xdlP4jaJbasvfJWyT+lcd/mHrFN6z8Zr"
    "vxVcs/q33Pyn7JE7afsdRjXvgqm77rMw3Pin4gUM/duM6r7A0L/HohVQNufQQ3bd4Mr5R59wGYTVLDrxnNc4sn7p6VcCZjFNK869FbaMb1198YOYTRKD"
    "MSQSzCCRYAmJBJvkro0Xf8jbp/VuufJbySlzwvbr/1RdcybvusWo4ZE/bS8keg8w9G27918dFBcPmbRAcfGEVRcUF885DIBxcegVt3FIzdyjb/nMwusX"
    "nPggaBnVtBgUr7Gty4DxyvBSyCS2fsWpN6LmCU2rz76XsEpuXXfhk7RtWsfGy1/lHDK7t1z7oeic07f95m8Vt/yJu+78U/csmrL3PqOWTymDS97ELfcY"
    "VdwLp2x/yKLuVTJ91xN2Ld/yWXufc+kGVM098IrXILh2weG3AsZhDYuPfRA2i2xedvKzmGVM28ozDPNPvRMyi6pbdPajqGVs49ILXyRsElpWXP4ubZ/c"
    "vvraLzmntK51N/8qumb2brzDoOKRM2HLfWZ17/zJ2x+xaTH8knfJ7Nt846+Se87EbbdJy2MModULjwNDP6JuySlg6JOWxxg2QCJhMyQSSMtjDNzG0TVL"
    "QHERV78cFBek5DGGtP6Nt/6oumdO2nL3v4YXaXmM4eBrPsPouoVH3gmaxDUuIS2PAQBaHlG1dkhrXQAAAABJRU5ErkJggg=="
)


def _result(tmp_path, name="Cockpit"):
    shot = tmp_path / f"{name}.png"
    shot.write_bytes(_REAL_PNG)
    return {
        "page": name,
        "path": "/cockpit/",
        "tier": 1,
        "status": "PASS",
        "issues": [],
        "warnings": [],
        "screenshots": [{"kind": "page", "path": str(shot)}],
    }


# ── 1. the re-band, observed through the gate's own behaviour ────────────────


def test_both_ci_gates_run_at_the_default_operating_tier(tmp_path, monkeypatch, capsys):
    """Tier 1 is where the platform lives at the measured burn. Both gates must
    execute there — asserted via a real Bedrock call and a merged verdict, so a
    future re-band that silently skips them cannot pass this test."""
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 1)
    calls = []
    monkeypatch.setattr(visual_ai_qa, "_import_bedrock", lambda: _fake_bedrock(calls))
    results = [_result(tmp_path)]

    status = visual_ai_qa.assess_results(results)

    # #3013 added evaluated/unevaluated/no_shots counts to the status dict; this
    # test's claim is only that the gate RUNS at the default operating tier (not
    # paused) — pin the status key, not the diagnostic shape.
    assert status["status"] == "ok"
    assert calls, "the vision gate must actually run at tier 1 (#1927)"
    assert results[0]["status"] == "FAIL", "a genuine high verdict must still gate"
    assert "SKIPPED-BY-BUDGET" not in capsys.readouterr().out


def test_ci_gate_cutoffs_are_the_hard_stop_only(monkeypatch):
    for feature in budget_guard.CI_GATE_FEATURES:
        assert budget_guard._FEATURE_CUTOFF[feature] == budget_guard._HARD_STOP_TIER
        for tier in (0, 1, 2):
            monkeypatch.setattr(budget_guard, "current_tier", lambda t=tier: t)
            assert budget_guard.allow(feature), f"{feature} must be allowed at tier {tier}"
        monkeypatch.setattr(budget_guard, "current_tier", lambda: 3)
        assert not budget_guard.allow(feature), f"{feature} must pause at the hard stop"


# ── 2. the honest pause, at the CI surface ───────────────────────────────────


def test_paused_gate_raises_a_ci_annotation_that_says_it_did_not_run():
    """The step summary and stdout both live INSIDE the job log; the annotation is
    what a reviewer sees next to the check. Without it a paused gate is a green ✔."""
    line = visual_qa.gha_paused_gate_annotation("AI-vision QA", {"status": "skipped_by_budget", "tier": 3}, env={"GITHUB_ACTIONS": "true"})
    assert line.startswith("::warning title=AI-vision QA SKIPPED-BY-BUDGET::")
    assert "did NOT run" in line
    assert "tier 3" in line
    assert "not evidence about this deploy" in line


def test_a_gate_that_ran_raises_no_annotation():
    """Negative: the annotation must mean 'this gate did not run'. If a clean run
    also annotated, the signal would be noise within a week."""
    env = {"GITHUB_ACTIONS": "true"}
    assert visual_qa.gha_paused_gate_annotation("AI-vision QA", {"status": "ok"}, env=env) == ""
    assert visual_qa.gha_paused_gate_annotation("AI-vision QA", None, env=env) == ""
    assert visual_qa.gha_paused_gate_annotation("Reader-truth QA", {"status": "unavailable"}, env=env) == ""


def test_annotation_is_ci_only():
    """A local `python3 tests/visual_qa.py` run must not print CI markup."""
    assert visual_qa.gha_paused_gate_annotation("AI-vision QA", {"status": "skipped_by_budget", "tier": 3}, env={}) == ""


def test_step_summary_reports_both_paused_gates_as_not_a_pass(tmp_path):
    """The CI job summary is the artifact a human reads after the fact. A paused
    gate must appear there as its own state — the ADR-147 lane split applied to
    the budget dimension: not passed, not failed, NOT RUN."""
    summary = tmp_path / "summary.md"
    visual_qa._write_step_summary(
        str(summary),
        passed=6,
        failed=0,
        warns=2,
        results=[],
        reader_truth_status={"status": "skipped_by_budget", "tier": 3},
        ai_vision_status={"status": "skipped_by_budget", "tier": 3},
    )
    text = summary.read_text()
    assert "**AI-vision QA: SKIPPED-BY-BUDGET** (tier 3) — not run, not a pass." in text
    assert "**Reader-truth QA: SKIPPED-BY-BUDGET** (tier 3) — not run, not a pass." in text


def test_paused_run_never_claims_a_clean_gate_anywhere_in_the_ci_output(tmp_path, monkeypatch, capsys):
    """End-to-end over the CI output path: pause both gates, then assert the three
    surfaces a reviewer can consult (stdout, step summary, annotation) each carry
    the pause — and that no per-page verdict was fabricated to fill the gap."""
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 3)

    def _boom(*a, **k):
        raise AssertionError("Bedrock must not be called while paused")

    monkeypatch.setattr(visual_ai_qa, "_import_bedrock", lambda: type("B", (), {"invoke": staticmethod(_boom)})())
    results = [_result(tmp_path)]

    vision_status = visual_ai_qa.assess_results(results)
    stdout = capsys.readouterr().out

    assert vision_status == {"status": "skipped_by_budget", "tier": 3}
    assert "SKIPPED-BY-BUDGET" in stdout
    assert "ai_verdict" not in results[0], "a paused gate must not fabricate a verdict"
    assert any(w.startswith("SKIPPED-BY-BUDGET:") for w in results[0]["warnings"])

    summary = tmp_path / "summary.md"
    visual_qa._write_step_summary(str(summary), 1, 0, 1, results, ai_vision_status=vision_status)
    assert "SKIPPED-BY-BUDGET" in summary.read_text()

    annotation = visual_qa.gha_paused_gate_annotation("AI-vision QA", vision_status, env={"GITHUB_ACTIONS": "1"})
    assert "did NOT run" in annotation


# ── 3. the operator readout: WHICH features a tier switched off ──────────────


def test_paused_features_names_what_the_tier_switched_off():
    """#1927's 'why nobody noticed': the tier number alone requires reciting
    _FEATURE_CUTOFF from memory to interpret."""
    assert budget_guard.paused_features(0) == []
    tier1 = budget_guard.paused_features(1)
    assert "ensemble" in tier1 and "coherence_semantic" in tier1
    assert not set(budget_guard.CI_GATE_FEATURES) & set(tier1), "CI gates are not paused at tier 1 (#1927)"
    assert set(budget_guard.paused_features(1)) < set(budget_guard.paused_features(2))
    assert set(budget_guard.paused_features(3)) == set(budget_guard._FEATURE_CUTOFF)


def test_paused_features_lists_ci_gates_first_so_truncation_never_hides_them():
    """The clause truncates names; the gates an operator must know about must be
    the ones that survive truncation."""
    paused = budget_guard.paused_features(3)
    assert tuple(paused[: len(budget_guard.CI_GATE_FEATURES)]) == tuple(sorted(budget_guard.CI_GATE_FEATURES))
    clause = budget_guard.format_paused_clause(3)
    for gate in budget_guard.CI_GATE_FEATURES:
        assert gate in clause


def test_paused_features_is_fail_soft_on_junk():
    assert budget_guard.paused_features("nonsense") == []
    assert budget_guard.format_paused_clause("nonsense") == ""
    assert budget_guard.format_paused_clause(0) == ""


def test_daily_brief_budget_line_names_the_pause(monkeypatch):
    """The one budget line the brief already renders now answers 'what is off?'
    — the operator surface acceptance item 1 asks for, alongside the CI ones."""
    breakdown = {
        "tier": 1,
        "mtd": 13.43,
        "projected": 83.24,
        "ceiling": 85.0,
        "ai_daily": 1.79,
        "non_ai_daily": 0.89,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
    line = budget_guard.format_headroom_line(breakdown)
    assert "Budget: tier 1" in line
    assert "paused: 5 AI features" in line
    assert "ensemble" in line or "+2 more" in line
    # ...and at tier 0 the clause is absent entirely — no "0 features paused" noise.
    assert "paused:" not in budget_guard.format_headroom_line(dict(breakdown, tier=0))
