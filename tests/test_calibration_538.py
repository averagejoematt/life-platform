"""tests/test_calibration_538.py — #538 the calibration scoreboard.

stats_core gets Brier + reliability primitives; calibration_core turns resolved
predictions into (confidence, outcome) pairs and scores them; every credibility
surface reads the same numbers.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

import calibration_core as cc  # noqa: E402
import stats_core as sc  # noqa: E402


class TestBrierPrimitives:
    def test_perfect_and_baseline_and_worst(self):
        assert sc.brier_score([(1.0, 1), (0.0, 0)]) == 0.0
        assert sc.brier_score([(0.5, 1), (0.5, 0)]) == 0.25
        assert sc.brier_score([(1.0, 0), (0.0, 1)]) == 1.0

    def test_none_when_empty_or_malformed(self):
        assert sc.brier_score([]) is None
        assert sc.brier_score([(1.5, 1), ("x", 0), (0.5, 2)]) is None  # all invalid

    def test_skill_beats_base_rate(self):
        # A forecaster that separates outcomes beats the base rate → positive skill.
        s = sc.brier_skill_score([(0.9, 1), (0.85, 1), (0.15, 0), (0.1, 0)])
        assert s is not None and s > 0.5
        # All-identical outcomes → undefined skill.
        assert sc.brier_skill_score([(0.9, 1), (0.8, 1)]) is None

    def test_reliability_bins_shape(self):
        bins = sc.reliability_bins([(0.05, 0), (0.95, 1), (0.9, 0)], n_bins=10)
        assert {b["lo"] for b in bins} == {0.0, 0.9}
        top = next(b for b in bins if b["lo"] == 0.9)
        assert top["n"] == 2 and top["observed_rate"] == 0.5  # one hit of two


class TestPairExtraction:
    def test_confirmed_refuted_map_to_binary_others_excluded(self):
        recs = [
            {"confidence": 0.8, "status": "confirmed"},
            {"confidence": 0.3, "status": "refuted"},
            {"confidence": 0.5, "status": "inconclusive"},  # excluded
            {"confidence": 0.9, "status": "pending"},  # excluded
            {"confidence": 0.7, "status": "expired"},  # excluded
        ]
        pairs = cc.pairs_from_prediction_records(recs)
        assert pairs == [(0.8, 1), (0.3, 0)]

    def test_word_confidence_normalizes(self):
        rows = [{"stated_confidence": "high", "outcome": "confirmed"}, {"stated_confidence": "low", "outcome": "refuted"}]
        pairs = cc.pairs_from_calibration_rows(rows)
        assert pairs == [(0.85, 1), (0.2, 0)]

    def test_normalize_confidence_forms(self):
        assert cc.normalize_confidence(0.4) == 0.4
        assert cc.normalize_confidence("40%") == 0.4
        assert cc.normalize_confidence("0.4") == 0.4
        assert cc.normalize_confidence("high") == 0.85
        assert cc.normalize_confidence(None) == 0.5  # default
        assert cc.normalize_confidence(1.7) == 1.0  # clamped


class TestScorePairs:
    def test_excludes_unscorable_and_reports_brier(self):
        recs = [
            {"confidence": 0.85, "status": "confirmed"},
            {"confidence": 0.85, "status": "refuted"},
            {"confidence": 0.2, "status": "refuted"},
            {"confidence": 0.9, "status": "confirmed"},
            {"confidence": 0.5, "status": "inconclusive"},
        ]
        s = cc.score_pairs(cc.pairs_from_prediction_records(recs))
        assert s["n"] == 4  # inconclusive excluded
        assert s["confirmed"] == 2 and s["refuted"] == 2
        assert 0.0 <= s["brier"] <= 1.0
        assert s["reliability_bins"]  # non-empty

    def test_empty_is_honest_not_a_crash(self):
        s = cc.score_pairs([])
        assert s["n"] == 0
        assert s["brier"] is None
        assert s["accuracy_pct"] is None
        assert s["calibration"] == "insufficient_data"
        assert s["label"] == "nascent"

    def test_overconfident_verdict(self):
        # Says 90% every time but only right half → over-confident (>= 5 resolved).
        recs = [{"confidence": 0.9, "status": ("confirmed" if i % 2 else "refuted")} for i in range(8)]
        s = cc.score_pairs(cc.pairs_from_prediction_records(recs))
        assert s["calibration"] == "over-confident"


class TestHonestBadgeSemantics:
    """#1370 (ADR-104/105): brier_skill <= 0 can NEVER render the flattering states.

    The live bug this pins: /api/calibration's platform block carried
    brier_skill = -0.0047 (worse than the base-rate climatology) yet rendered
    "Well Calibrated" / "authoritative" / 90 — reliability alone was buying the
    flattering badge. Calibrated (reliability) and skilled (beats base rate) are
    different claims; a skill <= 0 surface must read "not_yet_skillful".
    """

    # 12 forecasts, all stated at 90%, 11 confirmed / 1 refuted. Base rate 11/12 —
    # the climatology forecast narrowly beats the forecaster: brier ≈ 0.0767 vs
    # base ≈ 0.0764 → skill ≈ -0.0037, the −0.0047-style live shape. Pre-fix this
    # scored brier ≤ 0.15, n ≥ 12, |gap| ≤ 0.15 → "well-calibrated"/"authoritative"/90.
    NEG_SKILL_PAIRS = [(0.9, 1)] * 11 + [(0.9, 0)]

    def test_negative_skill_never_well_calibrated(self):
        s = cc.score_pairs(self.NEG_SKILL_PAIRS)
        assert s["brier_skill"] is not None and s["brier_skill"] <= 0  # fixture is the bug shape
        assert s["calibration"] != "well-calibrated"
        assert s["calibration"] == "not_yet_skillful"

    def test_negative_skill_never_authoritative(self):
        s = cc.score_pairs(self.NEG_SKILL_PAIRS)
        assert s["brier"] <= 0.15 and s["n"] >= 12  # would have been authoritative pre-fix
        assert s["label"] != "authoritative"
        assert s["label"] == "not_yet_skillful"
        assert s["score"] < 70  # never the reliable/authoritative rungs either

    def test_skilled_flag_exposed(self):
        # The payload carries the calibrated-vs-skilled distinction explicitly so
        # every surface can copy it honestly (issue AC-3).
        s = cc.score_pairs(self.NEG_SKILL_PAIRS)
        assert s["skilled"] is False

    def test_positive_skill_keeps_well_calibrated(self):
        # A genuinely discriminating forecaster keeps the earned verdict.
        pairs = [(0.9, 1), (0.85, 1), (0.9, 1), (0.15, 0), (0.1, 0), (0.2, 0)]
        s = cc.score_pairs(pairs)
        assert s["brier_skill"] > 0
        assert s["skilled"] is True
        assert s["calibration"] == "well-calibrated"

    def test_undefined_skill_is_not_punished(self):
        # All-identical outcomes → skill is None (undefined vs a degenerate base
        # rate). That is "unknown", not "unskilled" — the coarse label falls back
        # to the Brier ladder rather than the not-yet-skillful state.
        pairs = [(0.9, 1)] * 12
        s = cc.score_pairs(pairs)
        assert s["brier_skill"] is None
        assert s["skilled"] is None
        assert s["label"] == "authoritative"
        assert s["calibration"] != "not_yet_skillful"
