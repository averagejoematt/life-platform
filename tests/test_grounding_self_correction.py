"""Phase-4 grounding self-correction — the pure contradiction detector.

The Coherence Sentinel caught coaches serving a hallucinated RHR (53 vs the
canonical 64) that the layer validator missed (its regex only matches "resting
heart rate"/"resting HR", not the "RHR" abbreviation, and its 25% tolerance lets
a 17% RHR miss through). `_hard_canonical_contradictions` is the tighter, local
detector that drives a one-shot self-correction. These pin its precision: it must
catch the real contradiction AND not false-fire on legitimate prose (weight-loss
deltas, the correct number, HRV variance).
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "intelligence"))

import ai_expert_analyzer_lambda as az  # noqa: E402

FACTS = {"rhr_bpm": 64.0, "recovery_pct": 30.0, "hrv_ms": 25.2, "latest_weight": 300.77}


def test_catches_the_rhr_abbreviation_the_layer_validator_misses():
    # The exact incident: "your RHR dropped to 53" while canonical is 64.
    c = az._hard_canonical_contradictions("Strong week — your RHR dropped to 53, a real win.", FACTS)
    assert len(c) == 1 and c[0]["metric"] == "resting HR"
    assert c[0]["claimed"] == 53 and c[0]["canonical"] == 64.0


def test_catches_resting_heart_rate_spelled_out():
    c = az._hard_canonical_contradictions("Your resting heart rate is 52 bpm now.", FACTS)
    assert len(c) == 1 and c[0]["metric"] == "resting HR"


def test_catches_recovery_contradiction():
    c = az._hard_canonical_contradictions("With recovery up at 86 you're primed to push.", FACTS)
    assert len(c) == 1 and c[0]["metric"] == "Whoop recovery"
    assert c[0]["claimed"] == 86


def test_correct_numbers_do_not_fire():
    clean = "Resting HR sits at 64 bpm and recovery is 30% — both as reported."
    assert az._hard_canonical_contradictions(clean, FACTS) == []


def test_rhr_within_tolerance_does_not_fire():
    # 61 vs 64 is a 3-bpm, ~5% miss — rounding/recency noise, not a contradiction.
    assert az._hard_canonical_contradictions("Your RHR is around 61 these days.", FACTS) == []


def test_weight_loss_delta_is_not_treated_as_rhr_or_weight():
    # "13.8 pounds" is a loss total, not a vital — must not false-fire (weight is
    # deliberately out of scope; only RHR + recovery are checked).
    txt = "You've lost 13.8 pounds over four weeks; visceral fat is 3.21 pounds."
    assert az._hard_canonical_contradictions(txt, FACTS) == []


def test_missing_facts_are_safe():
    assert az._hard_canonical_contradictions("RHR dropped to 53.", {}) == []
    assert az._hard_canonical_contradictions("", FACTS) == []
