"""test_golden_surface_eval.py — the falsifiability contract for EVERY AI surface (#812).

The generalization of #742's contract: for each of the five runtime-gated
surfaces (board_ask, chronicle, memoir, state_of_matthew, field_notes), the
golden set draws zero false flags, every seeded fault is caught by the expected
check, and each adapter is provably wired to the surface's ACTUAL gate function
(a silently-disabled gate is the exact "unfalsifiable 0 flags" failure this
harness exists to kill).

Fully offline — no AWS, no Bedrock.
"""

import os
import sys

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import golden_surface_eval as h  # noqa: E402
import pytest  # noqa: E402

# Deploy-gating (#416/ADR-117), matching test_golden_brief_eval: a broken honesty
# gate on ANY reader-facing surface must block the deploy, not just red main.
pytestmark = pytest.mark.deploy_critical


# ── the headline verdict ─────────────────────────────────────────────────────
def test_deterministic_verdict_is_ok():
    r = h.run()
    assert r["verdict"] == h.OK, r
    assert not r["golden_defects"], r["golden_defects"]
    assert not r["canary_misses"], r["canary_misses"]


def test_covers_all_five_surfaces_with_real_packs():
    r = h.run()
    assert set(r["surfaces"]) == set(h.SURFACES)
    for s in h.SURFACES:
        info = r["per_surface"][s]
        assert info["golden_count"] >= 2, f"{s}: need >=2 goldens, have {info['golden_count']}"
        assert info["canary_count"] >= 2, f"{s}: need >=2 canaries, have {info['canary_count']}"


# ── canaries span every deterministic dimension of each surface's gate ────────
def test_canaries_span_each_surfaces_check_dimensions():
    for s in h.SURFACES:
        _, canaries = h.load_fixtures(s)
        covered = {c for cn in canaries for c in cn["expect_checks"]}
        required = h.SURFACE_CHECKS[s]
        assert required.issubset(covered), f"{s}: canaries cover {covered}, gate enforces {required}"


def test_canaries_are_labeled_synthetic():
    """Honesty rule: a seeded fault must SAY it's a seeded fault — never
    presentable as a real recorded output."""
    for s in h.SURFACES:
        _, canaries = h.load_fixtures(s)
        for cn in canaries:
            assert "SEEDED FAULT" in (cn.get("mutation") or ""), f"{s}/{cn['id']} lacks the seeded-fault label"


def test_goldens_carry_provenance():
    for s in h.SURFACES:
        golden, _ = h.load_fixtures(s)
        for fx in golden:
            prov = fx.get("provenance") or ""
            assert prov.startswith(("REAL", "AUTHORED")), f"{s}/{fx['id']} provenance must start REAL/AUTHORED: {prov[:60]}"


# ── the adapters call the ACTUAL gate paths (wiring, not re-implementation) ──
def test_board_ask_adapter_is_the_live_gate():
    from web import site_api_ai_lambda as ai

    findings = ai.board_grounding_findings("STANCE: recovery 64%", "how is he?", "Recovery hit 91% overnight.")
    assert any(f["type"] == "fabricated_number" for f in findings), findings
    assert ai.board_grounding_findings("STANCE: recovery 64%", "how is he?", "Recovery sat at 64%.") == []


def test_chronicle_adapter_is_the_live_gate():
    import wednesday_chronicle_lambda as chron

    findings = chron.installment_grounding_findings("prompt", "packet: weight 300.8", "The scale read 287.4 this week.")
    assert any(f["type"] == "fabricated_number" for f in findings), findings
    assert chron.installment_grounding_findings("prompt", "packet: weight 300.8", "The scale read 300.8 this week.") == []


def test_memoir_adapter_is_the_live_gate():
    from compute import coach_memoir_lambda as memoir

    facts = {"total_evaluations": 4, "learnings_raw": [{"status": "refuted", "metric": "deep_sleep", "subdomain": "deep_sleep"}]}
    ok, reasons = memoir.gate_check("I graded 4 calls and my deep_sleep call was wrong.", facts)
    assert ok, reasons
    ok, reasons = memoir.gate_check("I graded 19 calls, all triumphant.", facts)
    assert not ok and len(reasons) == 2, reasons  # fabricated 19 + dodged miss


def test_state_of_matthew_adapter_is_the_live_gate():
    from compute import state_of_matthew_lambda as som

    state = {"as_of": "2026-07-05", "forecast": {"expectations": [{"metric": "recovery_pct", "point": 73.6}]}}
    findings, causal = som.narration_gate(state, "Recovery projected at 73.6 because the deficit lifted.")
    assert causal == ["because"], causal
    findings, causal = som.narration_gate(state, "Recovery is projected at 88.2 tomorrow.")
    assert findings and not causal, (findings, causal)


def test_field_notes_adapter_is_the_live_gate():
    import field_notes_lambda as fnl

    rec = {"date": "2026-07-01", "recovery_pct": 55, "hrv_ms": 38.7, "rhr_bpm": 64}
    hits = fnl.note_contradiction_hits({"ai_present": "recovery is only 25% today", "ai_cautionary": "", "ai_affirming": ""}, rec)
    assert hits and hits[0]["metric"] == "Whoop recovery", hits
    assert fnl.note_contradiction_hits({"ai_present": "recovery held at 55%", "ai_cautionary": "", "ai_affirming": ""}, rec) == []


# ── the generic (harvested-fixture) replay path ──────────────────────────────
def test_generic_mode_replays_allowed_list():
    fx = {"mode": "generic", "inputs": {"allowed": [73.6, 300.8]}}
    assert h.evaluate_fixture("chronicle", fx, "Weight 300.8, recovery 73.6.") == []
    findings = h.evaluate_fixture("chronicle", fx, "Weight dropped from 306.2 to 300.8.")
    assert any(f["check"] == "evidence_ceiling" for f in findings), findings


def test_generic_mode_keeps_surface_extra_checks():
    """A harvested state_of_matthew fixture still runs the surface's real causal check."""
    fx = {"mode": "generic", "inputs": {"allowed": [73.6]}}
    findings = h.evaluate_fixture("state_of_matthew", fx, "Recovery hit 73.6 because the deficit eased.")
    assert any(f["check"] == "causal_language" for f in findings), findings


# ── report plumbing ──────────────────────────────────────────────────────────
def test_ops_line_marks_pass_and_fail():
    ok = h.ops_line({"verdict": h.OK, "golden_count": 11, "surfaces": list(h.SURFACES), "canary_count": 12, "canary_misses": []})
    assert ok.startswith("✓") and "OK" in ok
    bad = h.ops_line(
        {"verdict": h.FAIL, "golden_count": 11, "surfaces": list(h.SURFACES), "canary_count": 12, "canary_misses": [{"id": "x"}]}
    )
    assert bad.startswith("✗") and "11/12 canaries" in bad


def test_unknown_expect_checks_never_count_as_caught():
    """A canary with empty expect_checks must NOT read as caught (vacuous subset)."""
    report = h.run()
    for c in [c for s in report["per_surface"].values() for c in s["canary_results"]]:
        assert c["expect_checks"], f"{c['id']} has empty expect_checks — would be vacuously caught"
