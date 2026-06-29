"""
tests/test_prediction_gradability.py — C-3 prediction gradability routing.

The coach pipeline used to write every metric-backed prediction as a `machine`
spec with threshold=None, which the daily evaluator can only ever score
`inconclusive` (248/248 machine preds had no threshold; the LEARNING# trail was
100% inconclusive). The fix routes metric+direction claims to the `directional`
(EWMA-trend) evaluator, which needs no threshold. These tests pin that routing.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "coach"))

import coach_state_updater as m  # noqa: E402


class TestInferDirection:
    def test_explicit_extractor_direction_wins(self):
        assert m._infer_direction("up", "anything at all") == "up"
        assert m._infer_direction("down", "anything at all") == "down"

    def test_keyword_inference_up(self):
        assert m._infer_direction(None, "HRV should improve over two weeks") == "up"
        assert m._infer_direction(None, "I expect recovery to rebound") == "up"

    def test_keyword_inference_down(self):
        assert m._infer_direction(None, "weight will drop below the plateau") == "down"
        assert m._infer_direction(None, "resting heart rate should come down") == "down"

    def test_ambiguous_or_none_returns_none(self):
        assert m._infer_direction(None, "sleep will stay about the same") is None
        # both up and down words present → ambiguous → None (stay qualitative)
        assert m._infer_direction(None, "calories drop as protein rises") is None


class TestEvalSpecRouting:
    def test_metric_plus_direction_is_directional(self):
        spec = m._build_prediction_eval_spec("hrv", "up", 14)
        assert spec["type"] == "directional"
        assert spec["condition"] == "up"
        assert spec["metric"] == "hrv"
        assert spec["evaluation_window_days"] == 14

    def test_metric_without_direction_stays_qualitative(self):
        # The old bug: this would become a machine spec with threshold=None.
        spec = m._build_prediction_eval_spec("weight_lbs", None, 14)
        assert spec["type"] == "qualitative"
        assert spec["threshold"] is None

    def test_no_metric_is_qualitative(self):
        spec = m._build_prediction_eval_spec(None, "up", 14)
        assert spec["type"] == "qualitative"

    def test_directional_spec_never_carries_dead_threshold(self):
        # A directional spec must not pretend to a numeric threshold the
        # evaluator would try (and fail) to compare against.
        spec = m._build_prediction_eval_spec("recovery_score", "down", 21)
        assert spec["type"] == "directional"
        assert spec["threshold"] is None
        assert spec["condition"] in ("up", "down")


class TestGradabilityMetric:
    """SS-06: the write-time gradable-share metric (leading indicator of
    extraction drift, ahead of the Sentinel's daily closed-window check)."""

    def _capture(self, monkeypatch, gradable, qualitative):
        calls = {}

        class _CW:
            def put_metric_data(self, **kw):
                calls["kw"] = kw

        monkeypatch.setattr(m, "_cw", _CW())
        m._emit_prediction_gradability(gradable, qualitative)
        return calls

    def test_emits_counts_and_share(self, monkeypatch):
        calls = self._capture(monkeypatch, 3, 1)
        data = {d["MetricName"]: d["Value"] for d in calls["kw"]["MetricData"]}
        assert calls["kw"]["Namespace"] == "LifePlatform/Predictions"
        assert data["PredictionsGradable"] == 3.0
        assert data["PredictionsQualitative"] == 1.0
        assert abs(data["PredictionGradableShare"] - 0.75) < 1e-9

    def test_empty_run_emits_nothing(self, monkeypatch):
        # No predictions written → no metric (so an idle run doesn't read as 0% gradable).
        calls = self._capture(monkeypatch, 0, 0)
        assert calls == {}

    def test_all_qualitative_is_zero_share(self, monkeypatch):
        # The exact regression signature SS-06 must surface at the source.
        calls = self._capture(monkeypatch, 0, 4)
        data = {d["MetricName"]: d["Value"] for d in calls["kw"]["MetricData"]}
        assert data["PredictionGradableShare"] == 0.0
