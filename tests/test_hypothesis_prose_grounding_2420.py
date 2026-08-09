"""tests/test_hypothesis_prose_grounding_2420.py — #2420: the hypothesis engine's two
reader-bound prose paths pass the ADR-104 grounding chokepoint before persistence.

/api/hypotheses serves the stored HYPOTHESIS# rows verbatim, so the generated hypothesis
prose and the narrate_resolution sentence are reader text. The frozen test_spec protects
the VERDICT (ADR-105); these tests pin the gate on the WORDS around it:

  * a fabricated number in a generated hypothesis candidate is HELD (dropped before
    store_hypothesis ever sees it) while a faithful sibling in the same batch survives;
  * a fabricated number in the resolution narration triggers ONE correction pass, then
    holds to '' — the stored evidence stays the deterministic sentence (the frozen
    spec's own numbers, the designed fallback);
  * both paths are registered surfaces in tests/grounding_wiring.py and the #2390
    census counts the module as covered — and stripping the gate calls deregisters
    the surfaces, which is exactly what the wiring guard reds on (mutation proof).

Offline by construction: the model seam (common.retry_utils.call_anthropic_raw) is
monkeypatched; no AWS, no Bedrock.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKEKEY")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKESECRET")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "compute"))
sys.path.insert(0, os.path.join(_REPO, "tests"))

import hypothesis_engine_lambda as eng  # noqa: E402

MODULE = "lambdas/compute/hypothesis_engine_lambda.py"

# ── fixtures ─────────────────────────────────────────────────────────────────
HYP: dict = {
    "hypothesis": "Days with protein at or above 150g may improve deep sleep",
    "test_spec": {
        "condition_metric": "protein_g",
        "condition_op": ">=",
        "condition_threshold": 150,
        "outcome_metric": "deep_sleep_hrs",
        "direction": "higher",
        "min_effect": 0.4,
        "lag_days": 0,
    },
    "monitoring_window_days": 21,
    "created_at": "2026-07-20T00:00:00+00:00",
    "sk": "HYPOTHESIS#2026-07-20T00:00:00+00:00",
}
DET = (
    "Deterministic test: deep_sleep_hrs averaged 1.9 on 8 protein_g >= 150 days vs 1.4 "
    "on 13 comparison days — effect +0.5 (95% CI [0.2, 0.8]) → supported."
)
FAITHFUL = "On days with protein at or above 150g, deep sleep averaged 1.9 hours versus 1.4 — the pre-registered effect held."
# 2.6 appears nowhere in DET, the hypothesis text, or the frozen spec.
FABRICATED = "Protein above 150g lifted deep sleep from 1.4 to 2.6 hours a night."

DAILY_ROWS: list = [
    {"date": "2026-06-01", "protein_g": 160, "deep_sleep_hrs": 1.5},
    {"date": "2026-06-02", "protein_g": 120, "deep_sleep_hrs": 1.2},
]


def _seam(monkeypatch, texts):
    """Patch the model seam to yield `texts` in order (last one repeats); returns call log."""
    calls: list = []

    def fake(req, timeout=30):
        calls.append(req)
        text = texts[min(len(calls) - 1, len(texts) - 1)]
        return {"content": [{"type": "text", "text": text}]}

    import common.retry_utils as retry_utils

    monkeypatch.setattr(retry_utils, "call_anthropic_raw", fake)
    return calls


# ── narrate_resolution: regenerate once, then hold ───────────────────────────
class TestResolutionNarrationGate:
    def test_fabricated_number_regenerates_once_then_holds(self, monkeypatch):
        calls = _seam(monkeypatch, [FABRICATED, FABRICATED])
        out = eng.narrate_resolution(HYP, DET, "confirmed")
        assert out == "", "an ungrounded narration must HOLD to '' — the deterministic sentence is the stored evidence"
        assert len(calls) == 2, "regenerate-ONCE-then-hold: expected exactly one correction pass"

    def test_correction_pass_that_grounds_is_kept(self, monkeypatch):
        calls = _seam(monkeypatch, [FABRICATED, FAITHFUL])
        out = eng.narrate_resolution(HYP, DET, "confirmed")
        assert out == FAITHFUL
        assert len(calls) == 2

    def test_faithful_narration_survives_first_pass(self, monkeypatch):
        calls = _seam(monkeypatch, [FAITHFUL])
        out = eng.narrate_resolution(HYP, DET, "confirmed")
        assert out == FAITHFUL, "a gate that rejects everything is a gate nobody keeps"
        assert len(calls) == 1

    def test_seam_failure_stays_fail_soft(self, monkeypatch):
        import common.retry_utils as retry_utils

        def boom(req, timeout=30):
            raise RuntimeError("bedrock down")

        monkeypatch.setattr(retry_utils, "call_anthropic_raw", boom)
        assert eng.narrate_resolution(HYP, DET, "confirmed") == ""


# ── generate_hypotheses: hold the ungrounded candidate, keep the grounded one ─
class TestGenerationProseGate:
    @staticmethod
    def _candidate(hyp_id, evidence):
        return {
            "hypothesis_id": hyp_id,
            "hypothesis": "Days with protein at or above 150g may improve deep sleep",
            "domains": ["nutrition", "sleep"],
            "evidence": evidence,
            "confirmation_criteria": "deep sleep increases by 0.4+ hours on days with protein >= 150g",
            "test_spec": dict(HYP["test_spec"]),
            "effect_size_observed": "1.5 vs 1.2 hours of deep sleep",
            "monitoring_window_days": 21,
            "confidence": "low",
            "confidence_reason": "a small number of contrasting days support it",
            "actionable_if_confirmed": "Keep protein at or above 150g on training days",
        }

    def test_fabricated_candidate_is_held_and_faithful_sibling_ships(self, monkeypatch):
        good = self._candidate(
            "hyp_protein_sleep",
            "On 2026-06-01 protein hit 160g and deep sleep was 1.5 hours; on 2026-06-02 protein was 120g and deep sleep 1.2.",
        )
        # 33 and 87 appear nowhere in the prompt's data, the profile targets, or the spec.
        bad = self._candidate("hyp_fabricated", "HRV jumped from 33 to 87 after high-protein days.")
        _seam(monkeypatch, [json.dumps({"hypotheses": [good, bad]})])
        result = eng.generate_hypotheses(DAILY_ROWS, [], profile=None, journal_candidates=None)
        kept = [h["hypothesis_id"] for h in result["hypotheses"]]
        assert kept == [
            "hyp_protein_sleep"
        ], f"kept {kept} — the fabricated candidate must be HELD before persistence and the faithful one must survive"

    def test_a_fabricated_date_is_also_held(self, monkeypatch):
        bad = self._candidate(
            "hyp_fabricated_date",
            "On 2026-05-15 protein hit 160g and deep sleep was 1.5 hours.",  # date not in the data window
        )
        _seam(monkeypatch, [json.dumps({"hypotheses": [bad]})])
        result = eng.generate_hypotheses(DAILY_ROWS, [], profile=None, journal_candidates=None)
        assert result["hypotheses"] == []


# ── registration + census: the designed exit from UNGATED_READER_KNOWN ───────
class TestRegisteredSurfaceAndCensus:
    def test_both_prose_paths_are_registered_and_armed(self):
        from grounding_wiring import SURFACES, scan_tree

        found = scan_tree()
        for key in (f"{MODULE}::generate_hypotheses", f"{MODULE}::narrate_resolution"):
            assert key in SURFACES, f"{key} must be a registered grounding surface"
            assert {"numbers", "dates", "freshness"} <= found[key], f"{key} arms only {sorted(found[key])}"

    def test_census_counts_the_module_as_covered(self):
        import test_invoke_site_census_2390 as census

        assert MODULE not in census.UNGATED_READER_KNOWN, "the module must exit the tracked-defect table via SURFACES"
        assert MODULE in census.SITES, "precondition: the module still references a model seam"
        assert census.classify(MODULE, census.SURFACE_MODULES) == ["surfaces"]

    def test_stripping_the_gate_deregisters_both_surfaces(self):
        """Mutation proof: remove the chokepoint calls and the derivation loses the
        surfaces — exactly what test_registry_has_no_stale_entries (wiring) and the
        census's surfaces-bucket classification red on."""
        from grounding_wiring import scan_source

        src = open(os.path.join(_REPO, MODULE), encoding="utf-8").read()
        sabotaged = src.replace("grounding_findings(", "disabled_findings(")
        found = scan_source(MODULE, sabotaged)
        assert f"{MODULE}::generate_hypotheses" not in found
        assert f"{MODULE}::narrate_resolution" not in found
        # and the un-sabotaged source really is discovered (the scan is not vacuous)
        live = scan_source(MODULE, src)
        assert {f"{MODULE}::generate_hypotheses", f"{MODULE}::narrate_resolution"} <= set(live)
