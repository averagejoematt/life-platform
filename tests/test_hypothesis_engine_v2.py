"""
tests/test_hypothesis_engine_v2.py — #530/ADR-105: the deterministic hypothesis engine.

Pins the v2 contract:
- test_spec validation (the pre-registration gate: no parseable spec, no hypothesis)
- evaluate_test_spec verdicts are pure Python — supported / contradicted /
  inconclusive from arms + bootstrap CI, no LLM anywhere
- lag pairing, median split, and thin-arm guards
- the calibration-ledger row builder (one row per resolution, spec copied frozen)
- v1 legacy hypotheses (no spec) are never checked (they age out via hard expiry)
"""

import os
import random
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

import hypothesis_engine_lambda as eng  # noqa: E402


def _spec(**over):
    base = {
        "condition_metric": "protein_g",
        "condition_op": ">=",
        "condition_threshold": 150,
        "outcome_metric": "deep_sleep_hrs",
        "direction": "higher",
        "min_effect": 0,
        "lag_days": 0,
    }
    base.update(over)
    return base


def _rows(n, cond_fn, out_fn, start_day=1):
    """Synthetic daily rows: date + condition metric + outcome metric."""
    rows = []
    for i in range(n):
        day = start_day + i
        rows.append(
            {
                "date": f"2026-06-{day:02d}" if day <= 30 else f"2026-07-{day - 30:02d}",
                "protein_g": cond_fn(i),
                "deep_sleep_hrs": out_fn(i),
            }
        )
    return rows


class TestValidateTestSpec:
    def test_valid_threshold_spec(self):
        ok, issues = eng.validate_test_spec(_spec())
        assert ok, issues

    def test_valid_median_split_needs_no_threshold(self):
        ok, issues = eng.validate_test_spec(_spec(condition_op="median_split", condition_threshold=None))
        assert ok, issues

    def test_unknown_metric_rejected(self):
        ok, issues = eng.validate_test_spec(_spec(condition_metric="vibes"))
        assert not ok and any("vocabulary" in i for i in issues)

    def test_same_metric_both_sides_rejected(self):
        ok, issues = eng.validate_test_spec(_spec(outcome_metric="protein_g"))
        assert not ok

    def test_threshold_required_for_threshold_ops(self):
        ok, issues = eng.validate_test_spec(_spec(condition_threshold="lots"))
        assert not ok

    def test_bad_direction_and_lag(self):
        assert not eng.validate_test_spec(_spec(direction="sideways"))[0]
        assert not eng.validate_test_spec(_spec(lag_days=9))[0]
        assert not eng.validate_test_spec(_spec(lag_days=-1))[0]

    def test_not_a_dict(self):
        assert not eng.validate_test_spec("protein up, sleep up")[0]

    def test_hypothesis_without_spec_rejected(self):
        hyp = {
            "hypothesis_id": "hyp_x",
            "hypothesis": "Protein above 150g improves deep sleep.",
            "domains": ["nutrition", "sleep"],
            "evidence": "On 2026-06-20 protein was 180g and deep sleep hit 1.9h.",
            "confirmation_criteria": "deep sleep increases by 0.3 hours on days with protein >= 150g",
            "monitoring_window_days": 21,
            "confidence": "medium",
            "actionable_if_confirmed": "Keep protein above 150g.",
        }
        ok, issues = eng.validate_hypothesis(hyp)
        assert not ok and any("test_spec" in i for i in issues)
        hyp["test_spec"] = _spec()
        ok, issues = eng.validate_hypothesis(hyp)
        assert ok, issues


class TestEvaluateTestSpec:
    def test_supported_on_clear_effect(self):
        rng = random.Random(3)
        # protein alternates low/high; deep sleep clearly higher on high days
        rows = _rows(
            24,
            cond_fn=lambda i: 180 if i % 2 else 100,
            out_fn=lambda i: (2.0 if i % 2 else 1.0) + rng.gauss(0, 0.1),
        )
        r = eng.evaluate_test_spec(_spec(), rows, "2026-06-01")
        assert r["verdict"] == "supported"
        assert r["n_condition"] == 12 and r["n_comparison"] == 12
        assert r["effect_size"] > 0.8
        assert r["ci95_low"] > 0

    def test_contradicted_on_opposite_effect(self):
        rng = random.Random(5)
        rows = _rows(
            24,
            cond_fn=lambda i: 180 if i % 2 else 100,
            out_fn=lambda i: (1.0 if i % 2 else 2.0) + rng.gauss(0, 0.1),
        )
        r = eng.evaluate_test_spec(_spec(), rows, "2026-06-01")
        assert r["verdict"] == "contradicted"
        assert r["ci95_high"] < 0

    def test_inconclusive_on_noise(self):
        rng = random.Random(7)
        rows = _rows(
            24,
            cond_fn=lambda i: 180 if i % 2 else 100,
            out_fn=lambda i: 1.5 + rng.gauss(0, 0.5),
        )
        r = eng.evaluate_test_spec(_spec(), rows, "2026-06-01")
        assert r["verdict"] == "inconclusive"

    def test_min_effect_gate(self):
        rng = random.Random(3)
        rows = _rows(
            24,
            cond_fn=lambda i: 180 if i % 2 else 100,
            out_fn=lambda i: (2.0 if i % 2 else 1.0) + rng.gauss(0, 0.1),
        )
        # Real effect ~1.0h but the spec demands >= 2h — direction right, magnitude short
        r = eng.evaluate_test_spec(_spec(min_effect=2.0), rows, "2026-06-01")
        assert r["verdict"] == "inconclusive"
        assert r["effect_size"] > 0.8

    def test_thin_arm_is_inconclusive(self):
        rows = _rows(12, cond_fn=lambda i: 180 if i < 3 else 100, out_fn=lambda i: 1.5)
        r = eng.evaluate_test_spec(_spec(), rows, "2026-06-01")
        assert r["verdict"] == "inconclusive"
        assert r["n_condition"] == 3  # counted, but below MIN_DAYS_PER_ARM

    def test_since_date_respected(self):
        rng = random.Random(3)
        rows = _rows(
            24,
            cond_fn=lambda i: 180 if i % 2 else 100,
            out_fn=lambda i: (2.0 if i % 2 else 1.0) + rng.gauss(0, 0.1),
        )
        r = eng.evaluate_test_spec(_spec(), rows, "2026-06-20")
        assert r["days_observed"] < 24

    def test_lag_pairing(self):
        rng = random.Random(9)
        # Outcome responds ONE DAY AFTER the condition day; lag=1 must see the
        # effect and lag=0 must not (outcome on the condition day itself is flat).
        rows = []
        for i in range(26):
            high_yesterday = (i - 1) % 2 == 1
            rows.append(
                {
                    "date": f"2026-06-{i + 1:02d}",
                    "protein_g": 180 if i % 2 else 100,
                    "deep_sleep_hrs": (2.0 if high_yesterday else 1.0) + rng.gauss(0, 0.05),
                }
            )
        lagged = eng.evaluate_test_spec(_spec(lag_days=1), rows, "2026-06-01")
        same_day = eng.evaluate_test_spec(_spec(), rows, "2026-06-01")
        assert lagged["verdict"] == "supported"
        assert same_day["verdict"] in ("contradicted", "inconclusive")

    def test_median_split(self):
        rng = random.Random(11)
        rows = _rows(
            24,
            cond_fn=lambda i: 100 + i * 5,  # rising protein
            out_fn=lambda i: (2.0 if i >= 12 else 1.0) + rng.gauss(0, 0.1),
        )
        r = eng.evaluate_test_spec(_spec(condition_op="median_split", condition_threshold=None), rows, "2026-06-01")
        assert r["verdict"] == "supported"
        assert r["n_condition"] >= eng.MIN_DAYS_PER_ARM

    def test_deterministic_repeatable(self):
        rng = random.Random(3)
        rows = _rows(24, cond_fn=lambda i: 180 if i % 2 else 100, out_fn=lambda i: 1.5 + rng.gauss(0, 0.3))
        r1 = eng.evaluate_test_spec(_spec(), rows, "2026-06-01")
        r2 = eng.evaluate_test_spec(_spec(), rows, "2026-06-01")
        assert r1 == r2


class TestEvidenceAndCalibration:
    def test_deterministic_evidence_cites_the_numbers(self):
        rng = random.Random(3)
        rows = _rows(24, cond_fn=lambda i: 180 if i % 2 else 100, out_fn=lambda i: (2.0 if i % 2 else 1.0) + rng.gauss(0, 0.1))
        stats = eng.evaluate_test_spec(_spec(), rows, "2026-06-01")
        note = eng.deterministic_evidence(_spec(), stats)
        assert "Deterministic test" in note
        assert str(stats["mean_condition"]) in note
        assert "95% CI" in note and "supported" in note

    def test_inconclusive_evidence_names_the_gap(self):
        stats = {"verdict": "inconclusive", "days_observed": 4, "n_condition": 1, "n_comparison": 3, "effect_size": None}
        note = eng.deterministic_evidence(_spec(), stats)
        assert "inconclusive" in note and "per arm" in note

    def test_calibration_item_shape(self):
        hyp = {
            "sk": "HYPOTHESIS#2026-06-10T19:00:00+00:00",
            "hypothesis_id": "hyp_protein_sleep",
            "hypothesis": "Protein above 150g improves deep sleep.",
            "confidence": "high",
            "created_at": "2026-06-10T19:00:00+00:00",
            "test_spec": _spec(),
        }
        stats = {
            "verdict": "supported",
            "effect_size": 0.95,
            "ci95_low": 0.8,
            "ci95_high": 1.1,
            "cohens_d": 2.1,
            "n_condition": 12,
            "n_comparison": 12,
            "days_observed": 24,
        }
        item = eng.build_calibration_item(hyp, stats, "confirmed", "2026-07-04T19:00:00+00:00")
        assert item["pk"] == eng.CALIBRATION_PK
        assert item["sk"] == "CALIB#2026-07-04#hyp_protein_sleep"
        assert item["stated_confidence"] == "high"
        assert item["outcome"] == "confirmed"
        assert item["effect_size"] == 0.95
        assert item["test_spec"] == _spec()  # frozen spec copied for audit
        assert item["pre_registered_at"] == "2026-06-10T19:00:00+00:00"

    def test_calibration_partition_is_cross_phase(self):
        # The ledger must survive resets or the calibration question is unanswerable
        import phase_taxonomy as tax

        assert tax.SOURCE_CLASS["calibration"] == tax.CROSS_PHASE


class TestCheckPath:
    def _pending(self, created="2026-06-10T19:00:00+00:00", **over):
        hyp = {
            "sk": f"HYPOTHESIS#{created}",
            "hypothesis_id": "hyp_x",
            "hypothesis": "Protein above 150g improves deep sleep.",
            "status": "pending",
            "created_at": created,
            "check_count": 1,
            "monitoring_window_days": 21,
            "test_spec": _spec(),
        }
        hyp.update(over)
        return hyp

    def test_legacy_v1_without_spec_is_never_checked(self, monkeypatch):
        monkeypatch.setattr(eng, "narrate_resolution", lambda *a, **k: "")
        legacy = self._pending()
        del legacy["test_spec"]
        rows = _rows(24, cond_fn=lambda i: 180 if i % 2 else 100, out_fn=lambda i: 2.0 if i % 2 else 1.0)
        updates = eng.check_pending_hypotheses([legacy], rows)
        assert updates == []

    def test_contradicted_resolves_refuted(self, monkeypatch):
        monkeypatch.setattr(eng, "narrate_resolution", lambda *a, **k: "")
        rng = random.Random(5)
        rows = _rows(24, cond_fn=lambda i: 180 if i % 2 else 100, out_fn=lambda i: (1.0 if i % 2 else 2.0) + rng.gauss(0, 0.1))
        # Rows dated 2026-06-01..24; hypothesis created 2026-06-01 → 30+ days old vs "now",
        # but contradiction resolves regardless of window state.
        (hyp, status, evidence, stats, resolution), *_ = eng.check_pending_hypotheses(
            [self._pending(created="2026-06-01T00:00:00+00:00")], rows
        )
        assert status == "refuted" and resolution == "refuted"
        assert stats["verdict"] == "contradicted"
        assert "Deterministic test" in evidence

    def test_supported_before_window_end_is_confirming_not_confirmed(self, monkeypatch):
        monkeypatch.setattr(eng, "narrate_resolution", lambda *a, **k: "")
        from datetime import datetime, timedelta, timezone

        rng = random.Random(3)
        # Created 10 days ago (window 21d, not done) — supported → confirming
        created_dt = datetime.now(timezone.utc) - timedelta(days=10)
        rows = []
        for i in range(10):
            d = (created_dt + timedelta(days=i)).strftime("%Y-%m-%d")
            rows.append({"date": d, "protein_g": 180 if i % 2 else 100, "deep_sleep_hrs": (2.0 if i % 2 else 1.0) + rng.gauss(0, 0.05)})
        (hyp, status, evidence, stats, resolution), *_ = eng.check_pending_hypotheses([self._pending(created=created_dt.isoformat())], rows)
        assert stats["verdict"] == "supported"
        assert status == "confirming" and resolution is None

    def test_window_expired_undecided_archives_to_calibration(self, monkeypatch):
        monkeypatch.setattr(eng, "narrate_resolution", lambda *a, **k: "")
        rng = random.Random(7)
        rows = _rows(24, cond_fn=lambda i: 180 if i % 2 else 100, out_fn=lambda i: 1.5 + rng.gauss(0, 0.5))
        (hyp, status, evidence, stats, resolution), *_ = eng.check_pending_hypotheses(
            [self._pending(created="2026-06-01T00:00:00+00:00")], rows
        )
        assert status == "archived" and resolution == "expired_undecided"
