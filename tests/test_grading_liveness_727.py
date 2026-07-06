"""#727 — scientific-liveness heartbeat: the evaluator's decided/gradable counts
and the DaysSinceLastDecided gauge that monitoring_stack.GradingStalled alarms on.

Pure-logic tests: the CloudWatch client and the DynamoDB last-decided marker are
monkeypatched, so no AWS is touched. Mirrors tests/test_stance_event_refresh_534.py's
import pattern (the evaluator module imports cleanly; only the moving parts are stubbed).
"""

import os
import sys

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "coach"))

import coach_prediction_evaluator as ev  # noqa: E402


class _CWCapture:
    """Stub CloudWatch client that records put_metric_data calls."""

    def __init__(self):
        self.calls = []

    def put_metric_data(self, **kwargs):
        self.calls.append(kwargs)


def _last_metrics(capture):
    """Flatten the most recent put_metric_data into {MetricName: Value}."""
    md = capture.calls[-1]["MetricData"]
    return {m["MetricName"]: m["Value"] for m in md}


class TestGradingLiveness:
    def test_decided_count_is_confirmed_plus_refuted(self, monkeypatch):
        cw = _CWCapture()
        monkeypatch.setattr(ev, "_cw", cw)
        monkeypatch.setattr(ev, "_write_last_decided_date", lambda d: None)
        monkeypatch.setattr(ev, "_read_last_decided_date", lambda: None)

        out = ev.emit_grading_liveness(
            {"confirmed": 3, "refuted": 2, "inconclusive": 5, "expired": 1},
            gradable_count=17,
            today_str="2026-07-06",
        )
        assert out["decided_count"] == 5  # only confirmed+refuted, not inconclusive/expired
        assert out["gradable_count"] == 17
        m = _last_metrics(cw)
        assert m["DecidedCount"] == 5.0
        assert m["GradableCount"] == 17.0
        assert m["DaysSinceLastDecided"] == 0.0  # decided > 0 -> reset

    def test_decided_run_resets_days_and_stamps_marker_to_today(self, monkeypatch):
        cw = _CWCapture()
        monkeypatch.setattr(ev, "_cw", cw)
        stamped = {}
        monkeypatch.setattr(ev, "_write_last_decided_date", lambda d: stamped.update(date=d))
        # An old marker must be IGNORED on a decided run — today is the new truth.
        monkeypatch.setattr(ev, "_read_last_decided_date", lambda: "2026-01-01")

        out = ev.emit_grading_liveness({"confirmed": 1, "refuted": 0}, 4, "2026-07-06")
        assert out["days_since_last_decided"] == 0
        assert stamped["date"] == "2026-07-06"

    def test_zero_decided_with_marker_counts_days_and_does_not_restamp(self, monkeypatch):
        cw = _CWCapture()
        monkeypatch.setattr(ev, "_cw", cw)
        wrote = []
        monkeypatch.setattr(ev, "_write_last_decided_date", lambda d: wrote.append(d))
        monkeypatch.setattr(ev, "_read_last_decided_date", lambda: "2026-06-22")  # exactly 14 days before

        out = ev.emit_grading_liveness({"confirmed": 0, "refuted": 0, "inconclusive": 9}, 9, "2026-07-06")
        assert out["days_since_last_decided"] == 14
        assert wrote == []  # a zero-decided run must NOT advance the marker

    def test_zero_decided_no_marker_is_never_sentinel_and_would_fire(self, monkeypatch):
        cw = _CWCapture()
        monkeypatch.setattr(ev, "_cw", cw)
        monkeypatch.setattr(ev, "_write_last_decided_date", lambda d: None)
        monkeypatch.setattr(ev, "_read_last_decided_date", lambda: None)

        out = ev.emit_grading_liveness({}, 0, "2026-07-06")
        assert out["decided_count"] == 0
        assert out["days_since_last_decided"] == ev._NEVER_DECIDED_DAYS
        # "fires on the current state if deployed today": the sentinel clears the
        # GradingStalled alarm threshold (>= 14), so the never-graded state alarms.
        assert out["days_since_last_decided"] >= 14

    def test_days_since_helper(self):
        assert ev._days_since("2026-07-06", "2026-06-22") == 14
        assert ev._days_since("2026-07-06", "2026-07-06") == 0
        assert ev._days_since("2026-07-06", None) == ev._NEVER_DECIDED_DAYS
        assert ev._days_since("2026-07-06", "not-a-date") == ev._NEVER_DECIDED_DAYS

    def test_emit_is_fail_soft_on_cloudwatch_error(self, monkeypatch):
        class _Boom:
            def put_metric_data(self, **kwargs):
                raise RuntimeError("cw down")

        monkeypatch.setattr(ev, "_cw", _Boom())
        monkeypatch.setattr(ev, "_read_last_decided_date", lambda: None)
        monkeypatch.setattr(ev, "_write_last_decided_date", lambda d: None)

        # A metrics error must never sink the evaluation run.
        out = ev.emit_grading_liveness({"confirmed": 0, "refuted": 0}, 0, "2026-07-06")
        assert out["days_since_last_decided"] == ev._NEVER_DECIDED_DAYS
