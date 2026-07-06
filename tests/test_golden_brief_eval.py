"""test_golden_brief_eval.py — the falsifiability contract for the honesty gate (#742).

These tests are the thing #742 exists to guarantee: they PIN that the golden set
draws zero false flags, that every seeded fault is caught by the expected check,
and — critically — that the contradiction detector is actually wired (a silently
disabled gate is the exact "unfalsifiable 0 flags" failure this harness kills).
CI additionally runs the harness on any change to the gate/prompt surface.

Fully offline — the deterministic verdict never touches AWS/Bedrock; the advisory
judge is only exercised through a stub.
"""

import os
import sys

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import golden_brief_eval as h  # noqa: E402
import pytest  # noqa: E402

# Deploy-gating (#416/ADR-117): a broken honesty gate is exactly the "core
# honesty/safety contract the running system depends on" the marker guards —
# a regression here must block the deploy, not just red main.
pytestmark = pytest.mark.deploy_critical


# ── the headline verdict ─────────────────────────────────────────────────────
def test_deterministic_verdict_is_ok():
    r = h.run()
    assert r["verdict"] == h.OK, r
    assert not r["golden_defects"], r["golden_defects"]
    assert not r["canary_misses"], r["canary_misses"]
    assert not r["distinctiveness_violations"], r["distinctiveness_violations"]


def test_covers_all_eight_coaches_and_enough_golden():
    r = h.run()
    assert set(r["coaches_covered"]) == set(h.ALL_COACH_IDS)
    assert r["golden_count"] >= 30
    assert r["canary_count"] >= 5


# ── golden: no false positives ───────────────────────────────────────────────
def test_every_golden_output_draws_zero_findings():
    golden, _ = h.load_fixtures()
    for fx in golden:
        facts = fx.get("authoritative_facts") or {}
        findings = h.evaluate_output(fx["coach_id"], fx["reference_output"], facts, h.allowed_for(fx))
        assert findings == [], f"{fx['id']} false-flagged: {findings}"


# ── canaries: every seeded fault is caught by the expected check ─────────────
def test_every_canary_is_caught():
    r = h.run()
    for c in r["canary_results"]:
        assert c["caught"], f"{c['id']} slipped the gate: expected {c['expect_checks']}, caught {c['caught_checks']}"


def test_canary_checks_span_all_three_deterministic_dimensions():
    """The five canaries must exercise every deterministic dimension — otherwise a
    whole check could rot undetected."""
    _, canaries = h.load_fixtures()
    covered = {c for cn in canaries for c in cn["expect_checks"]}
    assert {"evidence_ceiling", "grounding_contradiction", "anti_pattern"}.issubset(covered), covered


# ── the gate is actually wired (the unfalsifiable-0-flags failure mode) ──────
def test_contradiction_detector_is_wired_not_silently_disabled():
    """If grounding_guard failed to import, every contradiction canary would pass
    as 'clean' and the harness would report a false green. Assert both the import
    and a live contradiction firing."""
    assert h.grounding_guard is not None, "grounding_guard not importable — contradiction canaries would silently no-op"
    findings = h.evaluate_output("physical_coach", "your recovery is only 25% today", {"recovery_pct": 64}, set())
    assert any(f["check"] == "grounding_contradiction" for f in findings), findings


def test_fabricated_number_is_caught():
    findings = h.evaluate_output("sleep_coach", "your HRV jumped to 77 ms overnight", {"hrv_ms": 42}, {42.0})
    assert any(f["check"] == "evidence_ceiling" for f in findings), findings


def test_vendor_fourth_wall_leak_is_an_anti_pattern():
    findings = h.evaluate_output("mind_coach", "As Claude, I read your journal and felt...", {}, set())
    assert any(f["check"] == "anti_pattern" for f in findings), findings


def test_grounded_output_is_clean():
    # a benign, fully-grounded sentence draws nothing
    findings = h.evaluate_output(
        "physical_coach", "resting heart rate held at 54 and recovery came back at 64%", {"rhr_bpm": 54, "recovery_pct": 64}, {54.0, 64.0}
    )
    assert findings == [], findings


# ── distinctiveness ──────────────────────────────────────────────────────────
def test_distinctiveness_flags_converged_voices():
    """Two different coaches emitting near-identical prose must trip the check."""
    dup = "the recovery trend and the training load both moved in a healthy direction this week overall"
    fake = [
        {"id": "a", "coach_id": "sleep_coach", "reference_output": dup},
        {"id": "b", "coach_id": "training_coach", "reference_output": dup},
    ]
    assert h.distinctiveness_violations(fake), "identical cross-coach outputs should violate distinctiveness"


def test_real_golden_voices_are_distinct():
    golden, _ = h.load_fixtures()
    assert h.distinctiveness_violations(golden) == []


# ── the advisory judge never affects the verdict ─────────────────────────────
def test_verdict_computed_without_judge():
    r = h.run(judge=False)
    assert "judge" not in r
    assert r["verdict"] == h.OK


def test_judge_failure_is_soft(monkeypatch):
    # Force the judge's Bedrock path to be unavailable; the harness must not raise
    # and the deterministic verdict must be unchanged.
    import builtins

    real_import = builtins.__import__

    def _boom(name, *a, **k):
        if name == "bedrock_client":
            raise ImportError("simulated offline")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _boom)
    r = h.run(judge=True)
    assert r["verdict"] == h.OK
    assert r["judge"]["available"] is False


# ── ops line reflects the verdict ────────────────────────────────────────────
def test_ops_line_marks_pass_and_fail():
    ok = h.ops_line({"verdict": h.OK, "golden_count": 30, "coaches_covered": list(h.ALL_COACH_IDS), "canary_count": 5, "canary_misses": []})
    assert ok.startswith("✓") and "OK" in ok
    bad = h.ops_line(
        {"verdict": h.FAIL, "golden_count": 30, "coaches_covered": ["sleep_coach"], "canary_count": 5, "canary_misses": [{"id": "x"}]}
    )
    assert bad.startswith("✗") and "4/5 canaries" in bad
