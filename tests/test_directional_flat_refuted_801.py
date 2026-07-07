"""tests/test_directional_flat_refuted_801.py — #801 [R22-SCI-01].

The directional evaluator used to be asymmetric: a coach's directional call
(up/down) could only be graded 'refuted' if the metric moved the OPPOSITE way.
If the metric stayed flat, the call was always 'inconclusive' — even though a
directional prediction is a bet that something moves, and "nothing happened"
is evidence against that bet, not a non-result.

These tests pin the new symmetric grading directly against
`_evaluate_directional`, monkeypatching `_get_ewma_trend` so each case can
supply an exact (direction, slope) pair without needing real DynamoDB data.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "coach"))

import coach_prediction_evaluator as ev  # noqa: E402

THRESH = ev.DIRECTIONAL_NOISE_THRESHOLD


def _spec(metric="resting_heart_rate", condition="up"):
    return {"type": "directional", "metric": metric, "condition": condition}


class TestFlatIsNowRefuted:
    def test_predicted_up_flat_actual_is_refuted(self, monkeypatch):
        monkeypatch.setattr(ev, "_get_ewma_trend", lambda *a, **k: ("flat", 0.005))
        result = ev._evaluate_directional({}, _spec(condition="up"), {}, "2026-07-06")
        assert result["status"] == "refuted"
        assert result["beats_null"] is False
        assert "predicted up" in result["reason"]
        assert "flat" in result["reason"]

    def test_predicted_down_flat_actual_is_refuted(self, monkeypatch):
        monkeypatch.setattr(ev, "_get_ewma_trend", lambda *a, **k: ("flat", -0.001))
        result = ev._evaluate_directional({}, _spec(condition="down"), {}, "2026-07-06")
        assert result["status"] == "refuted"
        assert "predicted down" in result["reason"]


class TestOppositeDirectionStillRefuted:
    def test_predicted_up_actual_down_is_refuted_unchanged(self, monkeypatch):
        monkeypatch.setattr(ev, "_get_ewma_trend", lambda *a, **k: ("down", -0.05))
        result = ev._evaluate_directional({}, _spec(condition="up"), {}, "2026-07-06")
        assert result["status"] == "refuted"
        assert result["beats_null"] is False


class TestConfirmedPathUnchanged:
    def test_predicted_up_actual_up_sufficient_magnitude_is_confirmed(self, monkeypatch):
        monkeypatch.setattr(ev, "_get_ewma_trend", lambda *a, **k: ("up", THRESH + 0.03))
        result = ev._evaluate_directional({}, _spec(condition="up"), {}, "2026-07-06")
        assert result["status"] == "confirmed"
        assert result["beats_null"] is True


class TestMatchingDirectionInsufficientMagnitudeUnchanged:
    """Verify (not change) the pre-existing, unrelated edge case: if the trend
    function ever reports a direction that matches the prediction but with a
    slope that doesn't clear the noise threshold, the result is 'refuted' — it
    falls through both the confirmed branch (magnitude insufficient) and the
    'flat' branch (actual_direction isn't 'flat' here), landing in the final
    else. This is today's behavior and is out of scope for #801; pinned so a
    future change to this branch is deliberate, not accidental.
    """

    def test_direction_matches_but_magnitude_too_small_is_refuted(self, monkeypatch):
        monkeypatch.setattr(ev, "_get_ewma_trend", lambda *a, **k: ("up", THRESH / 2))
        result = ev._evaluate_directional({}, _spec(condition="up"), {}, "2026-07-06")
        assert result["status"] == "refuted"


class TestMissingDataStaysInconclusive:
    def test_no_trend_data_is_inconclusive(self, monkeypatch):
        monkeypatch.setattr(ev, "_get_ewma_trend", lambda *a, **k: (None, None))
        result = ev._evaluate_directional({}, _spec(condition="up"), {}, "2026-07-06")
        assert result["status"] == "inconclusive"
        assert result["beats_null"] is False

    def test_invalid_predicted_direction_stays_inconclusive(self, monkeypatch):
        # A malformed/qualitative predicted direction (e.g. "flat" or "stable")
        # never reaches the up/down comparison at all — still inconclusive.
        monkeypatch.setattr(ev, "_get_ewma_trend", lambda *a, **k: ("up", 0.05))
        result = ev._evaluate_directional({}, _spec(condition="flat"), {}, "2026-07-06")
        assert result["status"] == "inconclusive"
