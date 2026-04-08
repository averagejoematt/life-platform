"""
tests/test_coach_intelligence.py — Unit tests for Coach Intelligence system.

Tests prompt construction, data maturity, validator checks, thread operations,
action lifecycle, and credibility scoring using mocks (no DynamoDB/API calls).

V2.2 — 2026-04-07
"""
import json
import os
import sys
import pytest
from unittest.mock import patch, MagicMock
from decimal import Decimal

# Set required env vars before importing
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))


# ── Data Maturity Tests ─────────────────────────────────────────────────────

class TestDataMaturity:
    def test_orientation_phase(self):
        from intelligence_common import build_data_maturity
        inventory = {"whoop": {"exists": True, "records": 3, "days_of_data": 3}}
        maturity = build_data_maturity(inventory)
        assert maturity["sleep"]["phase"] == "orientation"
        assert maturity["sleep"]["days"] == 3

    def test_emerging_phase(self):
        from intelligence_common import build_data_maturity
        inventory = {"whoop": {"exists": True, "records": 15, "days_of_data": 15}}
        maturity = build_data_maturity(inventory)
        assert maturity["sleep"]["phase"] == "emerging"

    def test_established_phase(self):
        from intelligence_common import build_data_maturity
        inventory = {"whoop": {"exists": True, "records": 45, "days_of_data": 45}}
        maturity = build_data_maturity(inventory)
        assert maturity["sleep"]["phase"] == "established"

    def test_training_orientation_zero_workouts(self):
        from intelligence_common import build_data_maturity
        inventory = {"strava": {"exists": False, "records": 0, "days_of_data": 0}}
        maturity = build_data_maturity(inventory)
        assert maturity["training"]["phase"] == "orientation"

    def test_labs_uses_correct_source(self):
        from intelligence_common import build_data_maturity
        # Labs should check 'labs' source, not 'whoop'
        inventory = {
            "whoop": {"exists": True, "records": 100, "days_of_data": 100},
            "labs": {"exists": False, "records": 0, "days_of_data": 0},
        }
        maturity = build_data_maturity(inventory)
        assert maturity["labs"]["phase"] == "orientation"


# ── Validator Tests ─────────────────────────────────────────────────────────

class TestValidator:
    def test_catches_null_claim_when_data_exists(self):
        from intelligence_common import validate_coach_output
        inventory = {"dexa": {"exists": True, "records": 2, "latest": "2026-03-15"}}
        maturity = {"physical": {"phase": "emerging", "days": 10}}
        narrative = "Unfortunately, body composition data remains unavailable at this time."
        flags = validate_coach_output("physical", "physical", narrative, inventory, maturity)
        errors = [f for f in flags if f["severity"] == "error"]
        assert len(errors) > 0
        assert any("dexa" in f["detail"].lower() or "body composition" in f["detail"].lower() for f in errors)

    def test_catches_stale_action(self):
        from intelligence_common import validate_coach_output
        inventory = {"dexa": {"exists": True, "records": 1, "latest": "2026-03-15"}}
        maturity = {"physical": {"phase": "emerging", "days": 10}}
        narrative = "This week's action: Obtain a DEXA scan to establish your baseline."
        flags = validate_coach_output("physical", "physical", narrative, inventory, maturity)
        stale = [f for f in flags if f["check"] == "stale_action"]
        assert len(stale) > 0

    def test_no_false_positive_when_data_missing(self):
        from intelligence_common import validate_coach_output
        inventory = {"dexa": {"exists": False, "records": 0}}
        maturity = {"physical": {"phase": "orientation", "days": 3}}
        narrative = "Body composition data is not yet available. I recommend obtaining a DEXA scan."
        flags = validate_coach_output("physical", "physical", narrative, inventory, maturity)
        errors = [f for f in flags if f["severity"] == "error"]
        assert len(errors) == 0

    def test_overconfidence_in_orientation(self):
        from intelligence_common import validate_coach_output
        inventory = {}
        maturity = {"glucose": {"phase": "orientation", "days": 2, "unit": "days"}}
        narrative = "Your pattern shows a clear trend toward improved glucose control."
        flags = validate_coach_output("glucose", "glucose", narrative, inventory, maturity)
        overconf = [f for f in flags if f["check"] == "overconfidence"]
        assert len(overconf) > 0


# ── Coach Preamble Tests ────────────────────────────────────────────────────

class TestCoachPreamble:
    def test_first_person_directive(self):
        from intelligence_common import build_coach_preamble
        goals = {"targets": {}, "coach_briefing": "Test briefing", "known_constraints": []}
        inventory = {}
        maturity = {"sleep": {"phase": "orientation", "days": 3, "threshold": 7, "unit": "nights", "target_date": "April 15"}}
        result = build_coach_preamble("Dr. Lisa Park", "sleep", goals, inventory, maturity)
        assert "FIRST PERSON" in result
        assert "Dr. Lisa Park" in result

    def test_null_targets_shown_correctly(self):
        from intelligence_common import build_coach_preamble
        goals = {"targets": {"weight": {"goal_lbs": None}}, "coach_briefing": "", "known_constraints": []}
        inventory = {}
        maturity = {"sleep": {"phase": "emerging", "days": 10, "threshold": 7, "unit": "nights"}}
        result = build_coach_preamble("Dr. Lisa Park", "sleep", goals, inventory, maturity)
        assert "not yet set" in result


# ── Credibility Tests ───────────────────────────────────────────────────────

class TestCredibility:
    @patch("intelligence_common.read_coach_thread")
    def test_nascent_with_few_predictions(self, mock_read):
        mock_read.return_value = [
            {"predictions": [
                {"status": "confirmed", "confidence": "medium"},
                {"status": "pending", "confidence": "low"},
            ]}
        ]
        from intelligence_common import compute_credibility
        result = compute_credibility("glucose")
        assert result["label"] == "nascent"

    @patch("intelligence_common.read_coach_thread")
    def test_reliable_with_good_track_record(self, mock_read):
        preds = [{"status": "confirmed", "confidence": "high"} for _ in range(8)]
        preds += [{"status": "refuted", "confidence": "medium"} for _ in range(3)]
        mock_read.return_value = [{"predictions": preds}]
        from intelligence_common import compute_credibility
        result = compute_credibility("glucose")
        assert result["label"] == "reliable"
        assert result["accuracy_pct"] > 60
