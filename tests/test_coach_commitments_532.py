"""tests/test_coach_commitments_532.py — #532 coach commitments & follow-through.

Recommendations a coach pushes become tracked COMMITMENT# records with a due window
and a deterministic follow-through check; the evaluator grades the metric-backed ones
kept/broken. These tests pin the extraction→write shape and the grade→status mapping.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "coach"))

import coach_state_updater as su  # noqa: E402


class TestTimeframeToWindow:
    def test_default_is_a_week(self):
        assert su._timeframe_to_window_days(None) == 7
        assert su._timeframe_to_window_days("") == 7

    def test_weeks_months_days(self):
        assert su._timeframe_to_window_days("this week") == 7
        assert su._timeframe_to_window_days("2 weeks") == 14
        assert su._timeframe_to_window_days("a month") == 30
        assert su._timeframe_to_window_days("3 days") == 3


class TestCommitmentRecordCreation:
    def _capture(self, monkeypatch):
        written = []
        monkeypatch.setattr(su, "_put_item", lambda item: written.append(item) or True)
        return written

    def test_metric_backed_commitment_gets_a_deterministic_check(self, monkeypatch):
        written = self._capture(monkeypatch)
        created, checkable = su._create_commitment_records(
            "sleep_coach",
            "2026-07-04",
            [
                {
                    "commitment_natural": "9:30 PM wind-down",
                    "action_check": "resting_heart_rate",
                    "direction": "down",
                    "timeframe_hint": "this week",
                }
            ],
        )
        assert created == 1 and checkable == 1
        rec = written[0]
        assert rec["sk"].startswith("COMMITMENT#commit_20260704_")
        assert rec["status"] == "pending"
        assert rec["action_check"] == {"metric": "resting_heart_rate", "direction": "down"}
        assert rec["due_date"] == "2026-07-11"  # +7 days
        assert rec["commitment_natural"] == "9:30 PM wind-down"

    def test_qualitative_commitment_has_no_machine_check(self, monkeypatch):
        written = self._capture(monkeypatch)
        created, checkable = su._create_commitment_records(
            "mind_coach",
            "2026-07-04",
            [{"commitment_natural": "call your brother this week", "action_check": None, "direction": None, "timeframe_hint": "this week"}],
        )
        assert created == 1 and checkable == 0
        assert written[0]["action_check"] is None

    def test_blank_commitments_are_skipped(self, monkeypatch):
        written = self._capture(monkeypatch)
        created, checkable = su._create_commitment_records("sleep_coach", "2026-07-04", [{"commitment_natural": "  "}])
        assert created == 0 and not written


class TestCommitmentGrading:
    def test_directional_outcome_maps_to_kept_broken(self, monkeypatch):
        import coach_prediction_evaluator as ev

        updates = []
        monkeypatch.setattr(ev, "_update_commitment_status", lambda c, s, r, t: updates.append((c["commitment_id"], s)))

        # Force the directional evaluator's verdict so the mapping is what's under test.
        def fake_directional(pred, spec, cache, today):
            return {"status": {"resting_heart_rate": "confirmed", "total_protein_g": "refuted"}[spec["metric"]], "reason": "x"}

        monkeypatch.setattr(ev, "_evaluate_directional", fake_directional)

        commitments = [
            {
                "commitment_id": "c_kept",
                "created_date": "2026-06-01",
                "window_days": 7,
                "action_check": {"metric": "resting_heart_rate", "direction": "down"},
            },
            {
                "commitment_id": "c_broken",
                "created_date": "2026-06-01",
                "window_days": 7,
                "action_check": {"metric": "total_protein_g", "direction": "up"},
            },
        ]
        stats = ev._evaluate_commitments(commitments, "2026-06-30", {})
        assert stats["kept"] == 1 and stats["broken"] == 1
        assert ("c_kept", "kept") in updates
        assert ("c_broken", "broken") in updates

    def test_not_yet_due_stays_pending(self, monkeypatch):
        import coach_prediction_evaluator as ev

        monkeypatch.setattr(ev, "_update_commitment_status", lambda *a: (_ for _ in ()).throw(AssertionError("should not write")))
        commitments = [
            {"commitment_id": "c1", "created_date": "2026-06-28", "window_days": 7, "action_check": {"metric": "hrv", "direction": "up"}},
        ]
        stats = ev._evaluate_commitments(commitments, "2026-06-30", {})  # only 2 days elapsed
        assert stats["pending"] == 1 and stats["kept"] == 0 and stats["broken"] == 0

    def test_qualitative_commitment_expires_to_unresolved(self, monkeypatch):
        import coach_prediction_evaluator as ev

        updates = []
        monkeypatch.setattr(ev, "_update_commitment_status", lambda c, s, r, t: updates.append((c["commitment_id"], s)))
        commitments = [
            {"commitment_id": "cq", "created_date": "2026-06-01", "window_days": 7, "action_check": None},  # 29d elapsed > 2x7
        ]
        stats = ev._evaluate_commitments(commitments, "2026-06-30", {})
        assert stats["unresolved"] == 1
        assert ("cq", "unresolved") in updates
