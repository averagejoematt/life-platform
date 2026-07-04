"""tests/test_forecast_engine.py — the deterministic forecast engine (#541, ADR-105).

Pins the pure core: the frozen-forecast row builder, the calibration-resolution
row (the CROSS_PHASE graded record), interval-coverage math, and the resolution
sweep against a faked table. The EWMA math itself is pinned in test_stats_core.
"""

import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas", "compute"))

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import forecast_engine_lambda as eng  # noqa: E402

RECOVERY_CFG = eng.METRICS[0]


def _fc(horizon=1):
    return {"point": 64.2, "lo": 55.0, "hi": 73.4, "alpha": 0.25, "sigma": 7.1, "n": 30, "horizon": horizon, "confidence": 0.80}


class TestBuildForecastItem:
    def test_shape(self):
        item = eng.build_forecast_item(RECOVERY_CFG, _fc(1), "2026-07-04", "2026-07-05")
        assert item["pk"] == "USER#matthew#SOURCE#forecast"
        assert item["sk"] == "FORECAST#2026-07-05#recovery_pct#h1"
        assert item["record_type"] == "forecast"
        assert item["model"] == "ewma-v1"
        assert item["point"] == 64.2 and item["lo"] == 55.0 and item["hi"] == 73.4
        assert item["confidence"] == 0.80
        assert item["resolved_at"] is None

    def test_h7_distinct_sk(self):
        h1 = eng.build_forecast_item(RECOVERY_CFG, _fc(1), "2026-07-04", "2026-07-05")
        h7 = eng.build_forecast_item(RECOVERY_CFG, _fc(7), "2026-07-04", "2026-07-11")
        assert h1["sk"] != h7["sk"]
        assert h7["sk"].endswith("#h7")


class TestBuildCalibrationItem:
    def _row(self):
        return eng.build_forecast_item(RECOVERY_CFG, _fc(1), "2026-07-04", "2026-07-05")

    def test_covered(self):
        calib = eng.build_forecast_calibration_item(self._row(), 60.0, True, "2026-07-05")
        assert calib["pk"] == "USER#matthew#SOURCE#calibration"
        assert calib["sk"] == "CALIB#2026-07-05#forecast-recovery_pct-h1-2026-07-05"
        assert calib["record_type"] == "forecast_resolution"
        assert calib["covered"] is True
        assert calib["actual"] == 60.0
        assert abs(calib["abs_error"] - 4.2) < 1e-9

    def test_sk_never_collides_with_hypothesis_rows(self):
        calib = eng.build_forecast_calibration_item(self._row(), 60.0, True, "2026-07-05")
        assert "#forecast-" in calib["sk"]


class _FakeTable:
    """Query returns canned rows; put_item/update_item are captured for assertions."""

    def __init__(self, rows):
        self.rows = rows
        self.puts = []
        self.updates = []

    def query(self, **kw):
        return {"Items": self.rows}

    def put_item(self, Item):
        self.puts.append(Item)

    def update_item(self, **kw):
        self.updates.append(kw)


class TestResolveMatured:
    def _forecast_row(self, target, metric="recovery_pct", h=1, resolved=None):
        cfg = next(c for c in eng.METRICS if c["metric"] == metric)
        row = eng.build_forecast_item(cfg, _fc(h), "2026-07-03", target)
        row["sk"] = f"FORECAST#{target}#{metric}#h{h}"
        if resolved:
            row["resolved_at"] = resolved
        return row

    def test_resolves_when_actual_exists(self, monkeypatch):
        fake = _FakeTable([self._forecast_row("2026-07-04")])
        monkeypatch.setattr(eng, "table", fake)
        actuals = {"whoop": {"2026-07-04": {"recovery_score": 71.0}}}
        res = eng.resolve_matured("2026-07-04", actuals)
        assert len(res) == 1
        assert res[0]["actual"] == 71.0
        assert res[0]["covered"] is True  # 55.0 <= 71 <= 73.4
        # one calibration put + one in-place forecast update
        assert len(fake.puts) == 1 and fake.puts[0]["record_type"] == "forecast_resolution"
        assert len(fake.updates) == 1
        assert fake.updates[0]["ExpressionAttributeValues"][":c"] is True

    def test_outside_interval_marks_uncovered(self, monkeypatch):
        fake = _FakeTable([self._forecast_row("2026-07-04")])
        monkeypatch.setattr(eng, "table", fake)
        actuals = {"whoop": {"2026-07-04": {"recovery_score": 40.0}}}
        res = eng.resolve_matured("2026-07-04", actuals)
        assert res[0]["covered"] is False

    def test_skips_already_resolved_and_missing_actual(self, monkeypatch):
        rows = [
            self._forecast_row("2026-07-03", resolved="2026-07-03"),
            self._forecast_row("2026-07-04"),  # no actual available
        ]
        fake = _FakeTable(rows)
        monkeypatch.setattr(eng, "table", fake)
        res = eng.resolve_matured("2026-07-04", {"whoop": {}})
        assert res == []
        assert fake.puts == [] and fake.updates == []


class TestComputeCoverage:
    def test_no_resolutions_returns_none(self, monkeypatch):
        monkeypatch.setattr(eng, "table", _FakeTable([]))
        assert eng.compute_coverage("2026-07-04") is None

    def test_coverage_math_overall_and_per_horizon(self, monkeypatch):
        def row(h, covered):
            return {
                "record_type": "forecast",
                "horizon_days": h,
                "resolved_at": "2026-07-04",
                "covered": covered,
            }

        rows = [row(1, True), row(1, True), row(1, False), row(7, True)]
        monkeypatch.setattr(eng, "table", _FakeTable(rows))
        cov = eng.compute_coverage("2026-07-04")
        assert cov["n_resolved"] == 4 and cov["n_covered"] == 3
        assert cov["coverage_pct"] == 75.0
        assert cov["h1"]["n_resolved"] == 3 and cov["h1"]["coverage_pct"] == 66.7
        assert cov["h7"]["coverage_pct"] == 100.0


class TestDecimalDiscipline:
    def test_to_decimal_recursive(self):
        out = eng.to_decimal({"a": 1.5, "b": [2.5, {"c": 3.5}], "d": "s"})
        assert isinstance(out["a"], Decimal)
        assert isinstance(out["b"][0], Decimal)
        assert isinstance(out["b"][1]["c"], Decimal)
        assert out["d"] == "s"


class TestBoundsClamp:
    def test_interval_clamped_to_metric_bounds(self):
        fc = {"point": 98.0, "lo": 80.0, "hi": 112.0, "alpha": 0.3, "sigma": 9.0, "n": 30, "horizon": 7, "confidence": 0.80}
        item = eng.build_forecast_item(RECOVERY_CFG, fc, "2026-07-04", "2026-07-11")
        assert item["hi"] == 100.0  # a 112% recovery ceiling is an artifact, not an expectation
        assert item["lo"] == 80.0

    def test_unbounded_metric_untouched(self):
        weight_cfg = next(c for c in eng.METRICS if c["metric"] == "weight_lbs")
        fc = {"point": 216.0, "lo": 214.0, "hi": 218.0, "alpha": 0.3, "sigma": 1.0, "n": 30, "horizon": 1, "confidence": 0.80}
        item = eng.build_forecast_item(weight_cfg, fc, "2026-07-04", "2026-07-05")
        assert (item["lo"], item["hi"]) == (214.0, 218.0)
