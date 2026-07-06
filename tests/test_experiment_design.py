"""tests/test_experiment_design.py — n-of-1 pre-registration + paired analysis (#539, ADR-105).

Pins the deterministic core: design validation (what a pre-registration may say),
window derivation (baseline / washout / analysis dates), the paired-analysis verdict
rule (supported only when the CI excludes zero in the predicted direction AND the
effect clears the frozen minimum), and run-to-run determinism.
"""

import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import experiment_design as ed  # noqa: E402


def _design(**over):
    d = {
        "baseline_days": 14,
        "washout_days": 3,
        # #728: required — a pre-registration must declare its stop before the data exists.
        "stopping_rule": "run the full 21 days regardless of interim trend; abort only if recovery < 40% for 3 consecutive days",
        "criterion": {"metric": "deep_pct", "direction": "higher", "min_effect": 2},
    }
    d.update(over)
    return d


class TestValidateDesign:
    def test_valid(self):
        ok, issues = ed.validate_design(_design())
        assert ok and issues == []

    def test_washout_optional(self):
        d = _design()
        del d["washout_days"]
        ok, _ = ed.validate_design(d)
        assert ok

    def test_rejects_bad_baseline(self):
        for bad in (3, 90, "14", None, True):
            ok, issues = ed.validate_design(_design(baseline_days=bad))
            assert not ok and any("baseline_days" in i for i in issues)

    def test_rejects_unknown_metric(self):
        d = _design()
        d["criterion"]["metric"] = "vibes"
        ok, issues = ed.validate_design(d)
        assert not ok and any("criterion.metric" in i for i in issues)

    def test_rejects_bad_direction_and_effect(self):
        d = _design()
        d["criterion"]["direction"] = "sideways"
        d["criterion"]["min_effect"] = -1
        ok, issues = ed.validate_design(d)
        assert not ok and len(issues) == 2

    def test_rejects_unknown_fields(self):
        ok, issues = ed.validate_design(_design(surprise=1))
        assert not ok and any("unknown design fields" in i for i in issues)
        d = _design()
        d["criterion"]["p_hacking"] = True
        ok, issues = ed.validate_design(d)
        assert not ok and any("unknown criterion fields" in i for i in issues)

    def test_non_dict(self):
        ok, issues = ed.validate_design("14 days")
        assert not ok

    # #728: the stopping rule is REQUIRED and must be substantive free text.
    def test_rejects_missing_stopping_rule(self):
        d = _design()
        del d["stopping_rule"]
        ok, issues = ed.validate_design(d)
        assert not ok and any("stopping_rule" in i for i in issues)

    def test_rejects_trivial_or_bloated_stopping_rule(self):
        for bad in ("stop", "  ", 14, "x" * 501):
            ok, issues = ed.validate_design(_design(stopping_rule=bad))
            assert not ok and any("stopping_rule" in i for i in issues), repr(bad)

    def test_stopping_rule_boundary_lengths_pass(self):
        assert ed.validate_design(_design(stopping_rule="a" * 20))[0]
        assert ed.validate_design(_design(stopping_rule="a" * 500))[0]


class TestDesignWindows:
    def test_windows(self):
        w = ed.design_windows("2026-06-01", "2026-06-30", _design())
        assert w == {
            "baseline_start": "2026-05-18",
            "baseline_end": "2026-05-31",
            "analysis_start": "2026-06-04",  # washout 3d excluded
            "analysis_end": "2026-06-30",
        }

    def test_zero_washout(self):
        w = ed.design_windows("2026-06-01", "2026-06-15", _design(washout_days=0))
        assert w["analysis_start"] == "2026-06-01"

    def test_washout_consumes_window(self):
        assert ed.design_windows("2026-06-01", "2026-06-02", _design(washout_days=5)) is None


class TestEvaluateDesign:
    def _series(self, mean, n, seed, sd=1.0):
        rng = random.Random(seed)
        return [mean + rng.gauss(0, sd) for _ in range(n)]

    def test_supported(self):
        base = self._series(20.0, 14, seed=1)
        win = self._series(25.0, 20, seed=2)  # +5, min_effect 2 → supported
        r = ed.evaluate_design(_design(), base, win)
        assert r["verdict"] == "supported"
        assert r["ci95_low"] > 0
        assert r["n_baseline"] == 14 and r["n_window"] == 20

    def test_contradicted(self):
        base = self._series(25.0, 14, seed=3)
        win = self._series(20.0, 20, seed=4)  # predicted higher, went lower
        r = ed.evaluate_design(_design(), base, win)
        assert r["verdict"] == "contradicted"

    def test_below_min_effect_is_inconclusive_even_if_significant(self):
        base = self._series(20.0, 30, seed=5, sd=0.3)
        win = self._series(21.0, 30, seed=6, sd=0.3)  # +1 < min_effect 2, CI excludes 0
        r = ed.evaluate_design(_design(), base, win)
        assert r["ci95_low"] > 0  # significant...
        assert r["verdict"] == "inconclusive"  # ...but doesn't clear the frozen bar

    def test_thin_arms_inconclusive_with_honest_ns(self):
        r = ed.evaluate_design(_design(), [20, 21, 22], [25, 26, 27, 28])
        assert r["verdict"] == "inconclusive"
        assert r["effect_size"] is None
        assert r["n_baseline"] == 3 and r["n_window"] == 4

    def test_lower_direction(self):
        d = _design()
        d["criterion"] = {"metric": "resting_heart_rate", "direction": "lower", "min_effect": 2}
        base = self._series(60.0, 14, seed=7)
        win = self._series(55.0, 20, seed=8)
        r = ed.evaluate_design(d, base, win)
        assert r["verdict"] == "supported"

    def test_deterministic_repeatable(self):
        base = self._series(20.0, 14, seed=9)
        win = self._series(24.0, 20, seed=10)
        assert ed.evaluate_design(_design(), base, win) == ed.evaluate_design(_design(), list(base), list(win))


class TestAnalysisSummary:
    def test_full_sentence(self):
        base = [20.0, 21.0, 19.5, 20.5, 22.0, 20.0, 21.5]
        win = [25.0, 26.0, 24.5, 25.5, 27.0, 25.0, 26.5]
        stats = ed.evaluate_design(_design(), base, win)
        s = ed.analysis_summary(_design(), stats)
        assert "Pre-registered criterion" in s
        assert "95% CI" in s
        assert s.endswith(f"-> {stats['verdict']}.")

    def test_inconclusive_sentence_carries_ns(self):
        stats = ed.evaluate_design(_design(), [1, 2], [3, 4])
        s = ed.analysis_summary(_design(), stats)
        assert "inconclusive" in s and "2 intervention days" in s.replace("2 intervention", "2 intervention")


class TestMetricRegistry:
    def test_every_metric_has_source_field_label(self):
        for slug, (source, field, label) in ed.DESIGN_METRICS.items():
            assert source and field and label, slug


class TestCreateExperimentGate:
    """The MCP tool rejects an invalid pre-registration outright — no DDB touched
    (validation runs before the duplicate check)."""

    def test_invalid_design_rejected(self):
        os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
        os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
        os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
        os.environ.setdefault("S3_BUCKET", "test-bucket")
        os.environ.setdefault("TABLE_NAME", "life-platform-test")
        os.environ.setdefault("USER_ID", "matthew")
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from mcp.tools_lifestyle import tool_create_experiment

        try:
            tool_create_experiment(
                {
                    "name": "Test",
                    "hypothesis": "x",
                    "design": {"baseline_days": 2, "criterion": {"metric": "vibes", "direction": "up", "min_effect": -1}},
                }
            )
            raise AssertionError("expected ValueError")
        except ValueError as e:
            assert "pre-registration rejected" in str(e)
