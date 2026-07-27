"""Self-tests for the standalone calibration-core package.

Runnable on its own, with nothing but pytest and the standard library::

    cd oss/calibration-core && python3 -m pytest tests/ -v

Every expectation here comes from ``vectors/calibration_vectors.json`` — the same
fixture the JS port and the platform grader this package was extracted from are
held to. Exact equality throughout: a calibration scorer that is "close enough"
is a calibration scorer nobody should trust.
"""

import importlib.util
import json
import math
import os

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG = os.path.join(os.path.dirname(_HERE), "src", "calibration_core.py")

_spec = importlib.util.spec_from_file_location("calibration_core_under_test", _PKG)
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)

VECTORS = cc.load_vectors()


def _exact(a, b, ctx=""):
    """Structural equality that treats floats bit-exactly (0.1 != 0.100000001)."""
    assert type(a) is type(b) or (isinstance(a, (int, float)) and isinstance(b, (int, float))), f"{ctx}: type {type(a)} != {type(b)}"
    if isinstance(a, float) or isinstance(b, float):
        if isinstance(a, float) and math.isnan(a):
            assert isinstance(b, float) and math.isnan(b), ctx
            return
        assert a == b, f"{ctx}: {a!r} != {b!r}"
        return
    if isinstance(a, dict):
        assert set(a) == set(b), f"{ctx}: keys {sorted(a)} != {sorted(b)}"
        for k in a:
            _exact(a[k], b[k], f"{ctx}.{k}")
        return
    if isinstance(a, (list, tuple)):
        assert len(a) == len(b), f"{ctx}: len {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            _exact(x, y, f"{ctx}[{i}]")
        return
    assert a == b, f"{ctx}: {a!r} != {b!r}"


@pytest.mark.parametrize("case", VECTORS["core_cases"], ids=lambda c: c["id"])
def test_score_pairs_matches_vectors(case):
    got = cc.score_pairs([tuple(p) for p in case["pairs"]], n_bins=case["n_bins"])
    _exact(got, case["expected"], case["id"])


@pytest.mark.parametrize("case", VECTORS["confidence_cases"], ids=lambda c: repr(c["input"]))
def test_normalize_confidence_matches_vectors(case):
    _exact(cc.normalize_confidence(case["input"]), case["expected"], repr(case["input"]))


@pytest.mark.parametrize("case", VECTORS["outcome_cases"], ids=lambda c: repr(c["input"]))
def test_outcome_to_binary_matches_vectors(case):
    assert cc.outcome_to_binary(case["input"]) == case["expected"]


@pytest.mark.parametrize("case", VECTORS["record_cases"], ids=lambda c: c["id"])
def test_record_extractors_match_vectors(case):
    fn = {
        "prediction_records": cc.pairs_from_prediction_records,
        "calibration_rows": cc.pairs_from_calibration_rows,
        "forecast_resolution_rows": cc.pairs_from_forecast_resolution_rows,
    }[case["kind"]]
    _exact([list(p) for p in fn(case["records"])], case["expected_pairs"], case["id"])


@pytest.mark.parametrize("case", VECTORS["adapter_cases"]["ledger_text_cases"], ids=lambda c: c["id"])
def test_parse_ledger_text_matches_vectors(case):
    _exact(cc.parse_ledger_text(case["text"]), case["expected"], case["id"])


# ── properties the vectors alone would not pin ────────────────────────────


def test_brier_of_the_always_fifty_forecaster_is_exactly_a_quarter():
    assert cc.brier_score([(0.5, 1), (0.5, 0), (0.5, 1), (0.5, 0)]) == 0.25


def test_skill_is_none_not_zero_when_every_outcome_is_identical():
    """Undefined skill is 'unknown', never punished as 'unskilled' (ADR-104)."""
    assert cc.brier_skill_score([(0.8, 1), (0.9, 1), (0.7, 1)]) is None
    assert cc.score_pairs([(0.8, 1), (0.9, 1), (0.7, 1)])["skilled"] is None


def test_reliability_without_skill_never_reads_well_calibrated():
    """The #1370 rule: 'calibrated' and 'skilled' are different claims."""
    summary = cc.score_pairs([(0.5, 1)] * 5 + [(0.5, 0)] * 3)
    assert summary["skilled"] is False
    assert summary["calibration"] != "well-calibrated"
    assert summary["label"] == "not_yet_skillful"


def test_nothing_resolved_yields_none_not_zero():
    """An empty ledger reports None everywhere — never a flattering zero."""
    s = cc.score_pairs([])
    assert s["n"] == 0
    assert s["brier"] is None and s["brier_skill"] is None and s["accuracy_pct"] is None
    assert s["calibration"] == "insufficient_data"


def test_unresolved_rows_are_counted_not_scored():
    parsed = cc.parse_ledger_text("0.8,confirmed\n0.6,pending\n0.4,pending")
    assert parsed["pairs"] == [[0.8, 1]]
    assert parsed["unresolved"] == 2
    assert parsed["rejected"] == []


def test_unreadable_rows_are_reported_never_defaulted():
    """A silently-defaulted 0.5 would put a number on the scorecard nobody stated."""
    parsed = cc.parse_ledger_text("banana,confirmed")
    assert parsed["pairs"] == []
    assert parsed["rejected"] == [{"line": 1, "raw": "banana,confirmed", "reason": "unreadable confidence"}]


def test_vectors_file_declares_its_schema():
    assert VECTORS["schema"] == "calibration-core/test-vectors@1"
    assert VECTORS["core_cases"], "the shared fixture must not be empty"


def test_demo_ledger_ships_with_provenance():
    demo_dir = os.path.join(os.path.dirname(_HERE), "demo")
    for name in sorted(os.listdir(demo_dir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(demo_dir, name), "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        assert payload.get("provenance"), f"{name} must say where its data came from"
        assert "synthetic" in payload["provenance"], f"{name} must state whether it is real or synthetic"
