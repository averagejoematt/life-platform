"""tests/test_prereg_min_effect_derived_3495.py — every stored hypothesis bar is DERIVED from
the subject's own trailing variance, and a hand-typed bar cannot pass for one (#3495 box 4,
QS-5; ADR-105 rule 4).

WHAT WAS STILL OPEN
───────────────────
#3552 derived the two genesis bars and LABELLED every other one. The weekly generator's bar
stayed the number the model typed: `hyp_protein_recovery_lag` (stored 2026-10-04) serves
`min_effect: 10` labelled `model_proposed`, and `experiment_gates` itself says a labelled
model bar does not meet ADR-105's bar. The sealed cycle-17 genesis artifact still carries the
bare literals 0.1 and 3 and can never be re-frozen (no further resets).

WHAT THIS PINS
──────────────
1. A deterministic fixture: a known outcome series re-prices a model-proposed 10 to exactly
   the bar the rule computes by hand (0.5 x the mean-successive-difference sigma), with the
   window, statistic, value, k, n and n floor stored beside it as `min_effect_basis`, the
   criterion sentence reading THAT number, and the arm floor kept.
2. `experiment_gates.min_effect_meets_rigor_bar` recognises that derived bar as meeting
   ADR-105 rule 4 — and (MUTATION CONTROLS) refuses the live model-proposed record, a
   hand-typed number wearing a derivation's label, a basis under the n floor, a foreign
   statistic, and the sealed genesis artifact's literals.
"""

from __future__ import annotations

import json
import math
import os
import sys
import unittest.mock as mock
from decimal import Decimal
from pathlib import Path

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

REPO = Path(__file__).resolve().parent.parent
for _p in (REPO / "lambdas", REPO / "lambdas" / "compute"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from experiment import (
    experiment_gates as gates,  # noqa: E402
    prereg_effect,  # noqa: E402
)

with mock.patch("boto3.resource"), mock.patch("boto3.client"):
    import hypothesis_engine_lambda as eng  # noqa: E402

# The sealed, hash-stamped cycle-17 artifact (byte-identical to the live
# /experiments/prereg/genesis-2026-09-06.json) — read, never written.
_SEALED = json.loads((REPO / "deploy" / "generated" / "genesis_preregistration.json").read_text())

# ── the deterministic fixture ────────────────────────────────────────────────
# Recovery alternates 50/60 for seven days (2026-10-01..07): the six successive differences
# are +10/-10, so SD(diffs) = sqrt(6 x 100 / 5) = sqrt(120); sigma = sqrt(120)/sqrt(2) =
# sqrt(60) = 7.745967; the bar = 0.5 x sigma = 3.872983 -> 3.87 points. Hand-computed here,
# not read back from the module under test.
_RECOVERY = [50.0, 60.0, 50.0, 60.0, 50.0, 60.0, 50.0]
_ROWS = [{"date": f"2026-10-{i + 1:02d}", "recovery": v, "protein_g": 120.0 + 10 * i} for i, v in enumerate(_RECOVERY)]
_EXPECTED_SIGMA = math.sqrt(60)
_EXPECTED_BAR = 3.87

# The served record as /api/hypotheses returned it on 2026-10-11 — the wire, not a guess.
_LIVE_MODEL_PROPOSED_SPEC = {
    "lag_days": 1.0,
    "condition_metric": "protein_g",
    "min_days_per_arm": 5.0,
    "outcome_metric": "recovery",
    "min_effect_provenance": {"value": 10.0, "kind": "model_proposed", "source": prereg_effect.MODEL_PROPOSED_CITATION},
    "min_effect": 10.0,
    "direction": "lower",
    "condition_op": "<=",
    "condition_threshold": 140.0,
}


def _model_hyp():
    """A generator reply shaped like the live 2026-10-04 hypothesis, before the write."""
    return {
        "hypothesis_id": "hyp_protein_recovery_lag",
        "hypothesis": "Low-protein days are followed by lower recovery.",
        "domains": ["nutrition", "recovery"],
        "evidence": "Seen in the window.",
        "confirmation_criteria": "Recovery the next day averages 10+ points lower after protein <140g days over 21 days.",
        "monitoring_window_days": 21,
        "confidence": "low",
        "actionable_if_confirmed": "Hold the protein floor.",
        "test_spec": {
            "condition_metric": "protein_g",
            "condition_op": "<=",
            "condition_threshold": 140,
            "outcome_metric": "recovery",
            "direction": "lower",
            "min_effect": 10,
            "lag_days": 1,
        },
    }


def _stamped():
    return prereg_effect.stamp_spec_provenance(_model_hyp(), eng.MIN_DAYS_PER_ARM, _ROWS)


# ── 1. the fixture re-prices the model bar to the hand-computed derivation ────


def test_a_model_proposed_bar_is_replaced_by_the_hand_computed_derivation():
    spec = _stamped()["test_spec"]
    assert spec["min_effect"] == _EXPECTED_BAR
    basis = spec["min_effect_basis"]
    assert basis["metric"] == "recovery" and basis["unit"] == "points"
    assert basis["window_days"] == 7  # 2026-10-01..07 inclusive — the span read, not the lookback constant
    assert basis["statistic"] == prereg_effect.DERIVATION_STATISTIC
    assert basis["value"] == pytest.approx(_EXPECTED_SIGMA, abs=5e-4)
    assert basis["k"] == 0.5 and basis["n"] == 6 and basis["n_floor"] == prereg_effect.MIN_PAIRS
    # The model's number is kept, visibly, with the label it arrived under.
    assert basis["replaced"]["value"] == 10 and basis["replaced"]["kind"] == gates.MODEL_PROPOSED
    assert spec["min_effect_provenance"]["kind"] == gates.PERSONAL_DERIVATION
    assert spec["min_effect_provenance"]["value"] == _EXPECTED_BAR
    assert spec["min_days_per_arm"] == eng.MIN_DAYS_PER_ARM  # the arm floor stays


def test_the_criterion_sentence_reads_the_derived_number_and_the_arm_floor():
    out = _stamped()
    crit = out["confirmation_criteria"]
    assert f"at least {_EXPECTED_BAR} points lower" in crit
    assert "next-day recovery" in crit and "protein_g is at or below 140" in crit
    assert f"at least {eng.MIN_DAYS_PER_ARM} days in each arm" in crit
    assert "n=6" in crit and "trailing 7 days" in crit and "0.5 x" in crit
    assert "10+" not in crit, "the criterion still states the model's replaced bar"
    # The model's own sentence survives off the criterion, never silently discarded.
    assert "10+ points" in out["proposed_confirmation_criteria"]


def test_the_derived_hypothesis_still_passes_the_engines_own_validator():
    ok, issues = eng.validate_hypothesis(_stamped(), existing_texts=None)
    assert ok, issues


def test_the_derivation_is_idempotent():
    once = _stamped()
    assert prereg_effect.stamp_spec_provenance(once, eng.MIN_DAYS_PER_ARM, _ROWS) == once


def test_the_window_is_the_calendar_span_the_rows_cover():
    rows = [{"date": "2026-09-12"}, {"date": "2026-10-11"}, {"date": "2026-09-20"}]
    assert prereg_effect.window_days_of(rows) == 30
    assert prereg_effect.window_days_of([]) is None


# ── 2. the gate recognises the derived bar, and refuses every hand-typed one ──


def test_the_derived_bar_meets_the_rigor_bar():
    ok, reason = gates.min_effect_meets_rigor_bar(_stamped()["test_spec"])
    assert ok, reason


def test_the_live_model_proposed_record_does_not_meet_the_bar():
    """MUTATION CONTROL — the record that is live on /api/hypotheses today."""
    ok, reason = gates.min_effect_meets_rigor_bar(_LIVE_MODEL_PROPOSED_SPEC)
    assert not ok and "model_proposed" in reason


def test_a_hand_typed_number_in_a_derivations_label_fails():
    """MUTATION CONTROL — the label is not the evidence: overwrite the derived bar with a
    typed number and the recomputation from the basis refuses it."""
    spec = dict(_stamped()["test_spec"])
    spec["min_effect"] = 10
    ok, reason = gates.min_effect_meets_rigor_bar(spec)
    assert not ok and "does not recompute" in reason


def test_every_other_hand_edit_of_the_basis_fails():
    """MUTATION CONTROLS — one test that reports every offender (one census gate, not five)."""
    base = _stamped()["test_spec"]
    mutations = {
        "below the n floor": {"n": prereg_effect.MIN_PAIRS - 1},
        "a lowered floor": {"n_floor": 1},
        "a foreign statistic": {"statistic": "level_sd"},
        "a chosen multiplier": {"k": 0.2},
        "a missing window": {"window_days": None},
    }
    passed = []
    for label, edit in mutations.items():
        spec = dict(base)
        spec["min_effect_basis"] = {**base["min_effect_basis"], **edit}
        if gates.min_effect_meets_rigor_bar(spec)[0]:
            passed.append(label)
    spec = {k: v for k, v in base.items() if k != "min_effect_basis"}
    if gates.min_effect_meets_rigor_bar(spec)[0]:
        passed.append("no basis at all")
    assert not passed, f"hand-edited bars accepted as derived: {passed}"


def test_the_sealed_genesis_literals_do_not_meet_the_bar():
    """The sealed cycle-17 artifact's 0.1 and 3 are recorded as what they are — the
    predicate says so rather than the artifact being re-sealed (docs/DECISIONS.md ADR-105,
    2026-10-11 note)."""
    for hyp in _SEALED["hypotheses"]:
        assert not gates.min_effect_meets_rigor_bar(hyp["test_spec"])[0], hyp["hypothesis_id"]


def test_a_flat_or_short_series_keeps_the_model_bar_labelled_as_not_meeting_it():
    short = prereg_effect.stamp_spec_provenance(_model_hyp(), eng.MIN_DAYS_PER_ARM, _ROWS[:3])
    flat = prereg_effect.stamp_spec_provenance(_model_hyp(), eng.MIN_DAYS_PER_ARM, [{**r, "recovery": 55.0} for r in _ROWS])
    for out in (short, flat):
        assert out["test_spec"]["min_effect"] == 10
        assert not gates.min_effect_meets_rigor_bar(out["test_spec"])[0]


# ── 3. the engine write path carries it end to end ───────────────────────────


class _FakeTable:
    def __init__(self):
        self.puts = []

    def put_item(self, Item=None, **kwargs):
        self.puts.append(Item)
        return {}


def test_the_engine_stores_the_derived_bar_and_the_gate_still_recognises_it(monkeypatch):
    table = _FakeTable()
    monkeypatch.setattr(eng, "table", table)
    from common import compute_metadata

    monkeypatch.setattr(compute_metadata, "_emit_write_metric", lambda *a, **k: None)
    eng.store_hypothesis(_model_hyp(), _ROWS)
    spec = table.puts[0]["test_spec"]
    assert spec["min_effect"] == Decimal(str(_EXPECTED_BAR))
    assert spec["min_effect_basis"]["k"] == Decimal("0.5")
    # The DDB round trip hands Decimals back; the predicate must still recognise the bar.
    ok, reason = gates.min_effect_meets_rigor_bar(eng.d2f(spec))
    assert ok, reason


# ── 4. the verifier's repairs: an omitted bar, the floor's unit, the replaced label ──


def test_an_omitted_min_effect_is_derived_like_a_declared_zero():
    """A generated spec with NO `min_effect` key used to be stored with no bar, no
    provenance and no basis — an effective bar of 0 (the checker reads
    `spec.get("min_effect", 0)`). It is now a declared 0, re-priced like any other bar."""
    hyp = _model_hyp()
    del hyp["test_spec"]["min_effect"]
    spec = prereg_effect.stamp_spec_provenance(hyp, eng.MIN_DAYS_PER_ARM, _ROWS)["test_spec"]
    assert spec["min_effect"] == _EXPECTED_BAR
    assert spec["min_effect_provenance"]["kind"] == gates.PERSONAL_DERIVATION
    assert spec["min_effect_basis"]["replaced"]["value"] == 0
    ok, reason = gates.min_effect_meets_rigor_bar(spec)
    assert ok, reason
    # Too short to derive: still labelled (declared 0), never an unlabelled implicit bar.
    short = prereg_effect.stamp_spec_provenance(hyp, eng.MIN_DAYS_PER_ARM, _ROWS[:3])["test_spec"]
    assert short["min_effect"] == 0
    assert short["min_effect_provenance"]["kind"] == gates.MODEL_PROPOSED


def test_the_criterion_counts_differences_not_readings():
    """MIN_PAIRS counts successive DIFFERENCES — 'floor: 5 readings' would understate it."""
    crit = _stamped()["confirmation_criteria"]
    assert "n=6 successive differences" in crit
    assert f"floor: {prereg_effect.MIN_PAIRS} differences" in crit
    assert "readings)" not in crit


def test_a_replaced_model_bar_does_not_carry_the_kept_as_proposed_citation():
    replaced = _stamped()["test_spec"]["min_effect_basis"]["replaced"]
    assert replaced["source"] == prereg_effect.MODEL_PROPOSED_REPLACED_SOURCE
    assert "kept as proposed only when" not in replaced["source"]


def test_every_spec_metric_has_a_stated_unit():
    """The derived criterion is written after `validate_hypothesis`'s units check, so it is
    never re-validated — every outcome the generator can name gets its unit here."""
    missing = sorted(m for m in eng.SPEC_METRICS if m not in prereg_effect.OUTCOME_UNITS)
    assert not missing, f"SPEC_METRICS with no unit in OUTCOME_UNITS: {missing}"
