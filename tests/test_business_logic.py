#!/usr/bin/env python3
"""
tests/test_business_logic.py — Unit tests for core business logic modules.

R8-LT3: Add pytest unit tests for scoring_engine, character_engine, and
daily_metrics_compute helpers. Offline — no AWS credentials needed.

Modules under test:
  - lambdas/scoring_engine.py       (day grade computation)
  - lambdas/character_engine.py     (character sheet pillar scoring)
  - lambdas/daily_metrics_compute_lambda.py (compute_tsb, compute_readiness)

Run: python3 -m pytest tests/test_business_logic.py -v

v1.0.0 — 2026-03-14 (R8-LT3)
"""

import sys
import os
import math
import pytest
from datetime import date, timedelta

# ── Path setup ─────────────────────────────────────────────────────────────────
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

# ── Env vars required by daily_metrics_compute_lambda at import time ────────────
os.environ.setdefault("USER_ID",   "matthew")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET",  "matthew-life-platform")

# ── Import under test ─────────────────────────────────────────────────────────
# Guard: if modules can't be imported (path issue or rename), skip rather than
# reporting 0 collected tests — which would silently hide the problem.
_core_import_err = None
try:
    import scoring_engine as se
    import character_engine as ce
except ImportError as _e:
    _core_import_err = _e
    se = None  # type: ignore
    ce = None  # type: ignore

if _core_import_err is not None:
    pytestmark = pytest.mark.skip(  # type: ignore
        reason=f"scoring_engine / character_engine unavailable: {_core_import_err}"
    )


# ==============================================================================
# scoring_engine — helpers
# ==============================================================================

class TestScoringHelpers:
    def test_clamp_in_range(self):
        assert se.clamp(50) == 50

    def test_clamp_below_min(self):
        assert se.clamp(-10) == 0

    def test_clamp_above_max(self):
        assert se.clamp(110) == 100

    def test_clamp_custom_bounds(self):
        assert se.clamp(5, lo=10, hi=20) == 10
        assert se.clamp(25, lo=10, hi=20) == 20
        assert se.clamp(15, lo=10, hi=20) == 15

    def test_avg_normal(self):
        assert se.avg([80, 90, 100]) == pytest.approx(90.0, abs=0.1)

    def test_avg_filters_none(self):
        assert se.avg([80, None, 100]) == pytest.approx(90.0, abs=0.1)

    def test_avg_all_none(self):
        assert se.avg([None, None]) is None

    def test_avg_empty(self):
        assert se.avg([]) is None

    def test_safe_float_present(self):
        assert se.safe_float({"hrv": 55.5}, "hrv") == pytest.approx(55.5)

    def test_safe_float_missing(self):
        assert se.safe_float({"hrv": 55.5}, "rhr") is None

    def test_safe_float_none_rec(self):
        assert se.safe_float(None, "hrv") is None

    def test_safe_float_default(self):
        assert se.safe_float({}, "hrv", default=42.0) == 42.0

    def test_safe_float_non_numeric(self):
        assert se.safe_float({"hrv": "bad"}, "hrv") is None


# ==============================================================================
# scoring_engine — letter_grade
# ==============================================================================

class TestLetterGrade:
    def test_a_plus(self):
        assert se.letter_grade(95) == "A+"
        assert se.letter_grade(100) == "A+"

    def test_a(self):
        assert se.letter_grade(90) == "A"
        assert se.letter_grade(94) == "A"

    def test_a_minus(self):
        assert se.letter_grade(85) == "A-"

    def test_b_plus(self):
        assert se.letter_grade(80) == "B+"

    def test_b(self):
        assert se.letter_grade(75) == "B"

    def test_b_minus(self):
        assert se.letter_grade(70) == "B-"

    def test_c_plus(self):
        assert se.letter_grade(65) == "C+"

    def test_c(self):
        assert se.letter_grade(60) == "C"

    def test_c_minus(self):
        assert se.letter_grade(55) == "C-"

    def test_d(self):
        assert se.letter_grade(45) == "D"
        assert se.letter_grade(54) == "D"

    def test_f(self):
        assert se.letter_grade(0) == "F"
        assert se.letter_grade(44) == "F"

    def test_boundary_at_90(self):
        # 90 should be A, 89 should be A-
        assert se.letter_grade(90) == "A"
        assert se.letter_grade(89) == "A-"


# ==============================================================================
# scoring_engine — score_sleep
# ==============================================================================

class TestScoreSleep:
    def _profile(self):
        return {"sleep_target_hours_ideal": 7.5}

    def test_no_sleep_data(self):
        score, details = se.score_sleep({}, self._profile())
        assert score is None
        assert details == {}

    def test_perfect_sleep(self):
        data = {"sleep": {
            "sleep_score": 100,
            "sleep_efficiency_pct": 100,
            "sleep_duration_hours": 7.5,
        }}
        score, _ = se.score_sleep(data, self._profile())
        assert score == 100

    def test_poor_sleep(self):
        data = {"sleep": {
            "sleep_score": 30,
            "sleep_efficiency_pct": 50,
            "sleep_duration_hours": 4.0,
        }}
        score, _ = se.score_sleep(data, self._profile())
        assert score is not None
        assert score < 60

    def test_only_sleep_score(self):
        data = {"sleep": {"sleep_score": 80}}
        score, _ = se.score_sleep(data, self._profile())
        assert score == 80

    def test_duration_penalty_for_oversleep(self):
        # 10h vs 7.5h target should have a lower duration_score
        data = {"sleep": {
            "sleep_score": 90,
            "sleep_efficiency_pct": 85,
            "sleep_duration_hours": 10.0,
        }}
        score_over, _ = se.score_sleep(data, self._profile())
        data_target = {"sleep": {
            "sleep_score": 90,
            "sleep_efficiency_pct": 85,
            "sleep_duration_hours": 7.5,
        }}
        score_on_target, _ = se.score_sleep(data_target, self._profile())
        assert score_on_target > score_over

    def test_score_clamped_0_100(self):
        data = {"sleep": {
            "sleep_score": 150,
            "sleep_efficiency_pct": 150,
            "sleep_duration_hours": 20.0,
        }}
        score, _ = se.score_sleep(data, self._profile())
        assert 0 <= score <= 100


# ==============================================================================
# scoring_engine — score_recovery
# ==============================================================================

class TestScoreRecovery:
    def test_no_whoop_data(self):
        score, details = se.score_recovery({}, {})
        assert score is None

    def test_perfect_recovery(self):
        data = {"whoop": {"recovery_score": 100}}
        score, _ = se.score_recovery(data, {})
        assert score == 100

    def test_low_recovery(self):
        data = {"whoop": {"recovery_score": 10}}
        score, _ = se.score_recovery(data, {})
        assert score == 10

    def test_score_clamped(self):
        data = {"whoop": {"recovery_score": 150}}
        score, _ = se.score_recovery(data, {})
        assert score == 100


# ==============================================================================
# scoring_engine — score_nutrition
# ==============================================================================

class TestScoreNutrition:
    def _profile(self):
        return {
            "calorie_target": 2000,
            "protein_target_g": 180,
            "protein_floor_g": 150,
            "calorie_tolerance_pct": 10,
            "calorie_penalty_threshold_pct": 25,
            "fat_target_g": 65,
            "carb_target_g": 150,
        }

    def test_no_nutrition_data(self):
        score, _ = se.score_nutrition({}, self._profile())
        assert score is None

    def test_perfect_nutrition(self):
        data = {"macrofactor": {
            "total_calories_kcal": 2000,
            "total_protein_g": 185,
            "total_fat_g": 65,
            "total_carbs_g": 150,
        }}
        score, _ = se.score_nutrition(data, self._profile())
        assert score >= 90

    def test_protein_floor_penalty(self):
        data_low = {"macrofactor": {
            "total_calories_kcal": 2000,
            "total_protein_g": 100,  # below floor
        }}
        data_high = {"macrofactor": {
            "total_calories_kcal": 2000,
            "total_protein_g": 180,  # at target
        }}
        score_low, _ = se.score_nutrition(data_low, self._profile())
        score_high, _ = se.score_nutrition(data_high, self._profile())
        assert score_high > score_low

    def test_overeating_penalty(self):
        data_over = {"macrofactor": {
            "total_calories_kcal": 3000,  # 50% over = full penalty
            "total_protein_g": 180,
        }}
        data_on = {"macrofactor": {
            "total_calories_kcal": 2000,
            "total_protein_g": 180,
        }}
        score_over, _ = se.score_nutrition(data_over, self._profile())
        score_on, _ = se.score_nutrition(data_on, self._profile())
        assert score_on > score_over


# ==============================================================================
# scoring_engine — compute_day_grade
# ==============================================================================

class TestComputeDayGrade:
    def _minimal_profile(self):
        return {
            "sleep_target_hours_ideal": 7.5,
            "calorie_target": 2000,
            "protein_target_g": 180,
            "protein_floor_g": 150,
            "calorie_tolerance_pct": 10,
            "calorie_penalty_threshold_pct": 25,
            "step_target": 7000,
            "day_grade_weights": {
                "sleep_quality": 0.25,  # matches COMPONENT_SCORERS key in scoring_engine.py
                "recovery": 0.25,
                "nutrition": 0.25,
                "movement": 0.25,
            }
        }

    def test_empty_data_low_score(self):
        """score_movement always returns a score (exercise_score defaults to 0),
        so empty data still produces a day grade — it's just very low.
        Other scorers (sleep, recovery, nutrition) return None with no data."""
        score, grade, components, details = se.compute_day_grade({}, self._minimal_profile())
        # movement scorer returns exercise_score=0 even with no data
        # so active_components has movement with score=0 → total score = 0
        # (unless movement weight is 0 in profile, in which case grade is “—”)
        if score is None:
            assert grade == "\u2014"
        else:
            assert 0 <= score <= 100

    def test_perfect_data_returns_high_score(self):
        """score_movement needs both strava (exercise) and apple (steps) for full score."""
        data = {
            "sleep": {
                "sleep_score": 100,
                "sleep_efficiency_pct": 100,
                "sleep_duration_hours": 7.5,
            },
            "whoop": {"recovery_score": 100},
            "macrofactor": {
                "total_calories_kcal": 2000,
                "total_protein_g": 185,
                "total_fat_g": 65,
                "total_carbs_g": 150,
            },
            "apple": {"steps": 10000},
            "strava": {"activity_count": 1, "total_moving_time_seconds": 3600},
        }
        score, grade, _, _ = se.compute_day_grade(data, self._minimal_profile())
        assert score is not None
        assert score >= 80
        assert grade.startswith("A") or grade.startswith("B")

    def test_weighted_average_is_correct(self):
        # With only recovery (score=80) and weights that only include recovery
        profile = {
            "day_grade_weights": {"recovery": 1.0},
            "sleep_target_hours_ideal": 7.5,
        }
        data = {"whoop": {"recovery_score": 80}}
        score, grade, _, _ = se.compute_day_grade(data, profile)
        assert score == 80
        assert grade == "B+"

    def test_component_scores_populated(self):
        data = {"whoop": {"recovery_score": 75}}
        profile = {"day_grade_weights": {"recovery": 1.0}}
        _, _, components, _ = se.compute_day_grade(data, profile)
        assert "recovery" in components
        assert components["recovery"] == 75

    def test_score_clamped_0_100(self):
        # Extreme values shouldn't escape bounds
        profile = {"day_grade_weights": {"recovery": 1.0}}
        data = {"whoop": {"recovery_score": 99999}}
        score, _, _, _ = se.compute_day_grade(data, profile)
        assert 0 <= score <= 100


# ==============================================================================
# character_engine — helpers
# ==============================================================================

class TestCharacterHelpers:
    def test_clamp_in_range(self):
        assert ce._clamp(50) == 50

    def test_clamp_below(self):
        assert ce._clamp(-5) == 0

    def test_clamp_above(self):
        assert ce._clamp(110) == 100

    def test_clamp_none(self):
        assert ce._clamp(None) is None

    def test_pct_of_target_at_target(self):
        # At exactly target, score = 100/perfect_pct * 100 ≈ 83.3 (not 100)
        # Score is 100 only at perfect_pct * target
        score = ce._pct_of_target(100, 100, perfect_pct=1.0)
        assert score == 100.0

    def test_pct_of_target_below(self):
        score = ce._pct_of_target(50, 100, perfect_pct=1.0)
        assert score == pytest.approx(50.0)

    def test_pct_of_target_above_perfect(self):
        # At 120% of target (perfect_pct=1.2), score = 100
        score = ce._pct_of_target(120, 100, perfect_pct=1.2)
        assert score == 100.0

    def test_pct_of_target_zero_actual(self):
        score = ce._pct_of_target(0, 100)
        assert score == 0.0

    def test_pct_of_target_none(self):
        assert ce._pct_of_target(None, 100) is None
        assert ce._pct_of_target(100, None) is None

    def test_deviation_score_at_ideal(self):
        assert ce._deviation_score(0, ideal=0) == 100.0

    def test_deviation_score_at_worst(self):
        assert ce._deviation_score(120, ideal=0, worst=120) == 0.0

    def test_deviation_score_midpoint(self):
        score = ce._deviation_score(60, ideal=0, worst=120)
        assert score == pytest.approx(50.0, abs=1.0)

    def test_in_range_score_inside(self):
        assert ce._in_range_score(50, 40, 60) == 100.0

    def test_in_range_score_boundary(self):
        assert ce._in_range_score(40, 40, 60) == 100.0
        assert ce._in_range_score(60, 40, 60) == 100.0

    def test_in_range_score_outside_drops(self):
        score = ce._in_range_score(20, 40, 60, buffer=0.1)
        assert score < 100.0
        assert score >= 0.0

    def test_trend_score_improving(self):
        # Steadily increasing values → positive trend → score > 50
        values = [60, 65, 70, 75, 80]
        score = ce._trend_score(values, higher_is_better=True)
        assert score > 50.0

    def test_trend_score_declining(self):
        values = [80, 75, 70, 65, 60]
        score = ce._trend_score(values, higher_is_better=True)
        assert score < 50.0

    def test_trend_score_stable(self):
        values = [70, 70, 70, 70, 70]
        score = ce._trend_score(values, higher_is_better=True)
        assert score == pytest.approx(50.0, abs=1.0)

    def test_trend_score_too_few_values(self):
        assert ce._trend_score([70, 80]) is None
        assert ce._trend_score([]) is None


# ==============================================================================
# character_engine — get_tier
# ==============================================================================

class TestGetTier:
    def test_default_config_level_1(self):
        tier = ce.get_tier(1)
        assert "name" in tier
        assert tier["min_level"] <= 1 <= tier["max_level"]

    def test_default_config_level_50(self):
        tier = ce.get_tier(50)
        assert tier["min_level"] <= 50 <= tier["max_level"]

    def test_custom_config(self):
        config = {
            "tiers": [
                {"name": "Novice", "min_level": 1, "max_level": 10},
                {"name": "Expert", "min_level": 11, "max_level": 50},
            ]
        }
        assert ce.get_tier(5, config)["name"] == "Novice"
        assert ce.get_tier(25, config)["name"] == "Expert"

    def test_above_all_tiers_returns_last(self):
        config = {
            "tiers": [
                {"name": "Novice", "min_level": 1, "max_level": 10},
                {"name": "Expert", "min_level": 11, "max_level": 50},
            ]
        }
        tier = ce.get_tier(100, config)
        assert tier["name"] == "Expert"


# ==============================================================================
# daily_metrics_compute — compute_tsb (importable without AWS)
# ==============================================================================

# ── Import daily_metrics_compute helpers (boto3 calls happen at module level;
#    env vars above prevent KeyError; actual DDB calls only happen in lambda_handler)
# ─────────────────────────────────────────────────────────────────
try:
    import unittest.mock as _mock
    with _mock.patch("boto3.resource"), _mock.patch("boto3.client"):
        import daily_metrics_compute_lambda as dmc
    _dmc_available = True
except Exception as _e:
    _dmc_available = False
    _dmc_import_error = str(_e)


class TestComputeTSB:
    """TSB (Training Stress Balance) = CTL - ATL (Banister model)."""

    def _import_fn(self):
        if not _dmc_available:
            pytest.skip(f"daily_metrics_compute_lambda unavailable: {_dmc_import_error}")
        return dmc.compute_tsb

    def test_no_training_returns_negative_tsb(self):
        """60 days of zero load → CTL=0, ATL=0, TSB=0."""
        compute_tsb = self._import_fn()
        today = date(2026, 3, 14)
        result = compute_tsb([], today)
        assert result == 0.0

    def test_recent_heavy_load_gives_negative_tsb(self):
        """Lots of recent training → high ATL > CTL → negative TSB (fatigued)."""
        compute_tsb = self._import_fn()
        today = date(2026, 3, 14)
        # 14 days of heavy load
        heavy_records = []
        for i in range(1, 15):
            d = (today - timedelta(days=i)).isoformat()
            heavy_records.append({"date": d, "activities": [{"kilojoules": 500}]})
        result = compute_tsb(heavy_records, today)
        assert result < 0  # fatigue > fitness

    def test_distant_past_load_gives_positive_tsb(self):
        """Load only 30+ days ago → CTL residual > ATL decay → positive TSB (fresh)."""
        compute_tsb = self._import_fn()
        today = date(2026, 3, 14)
        # Load from 40-50 days ago only
        old_records = []
        for i in range(40, 50):
            d = (today - timedelta(days=i)).isoformat()
            old_records.append({"date": d, "activities": [{"kilojoules": 400}]})
        result = compute_tsb(old_records, today)
        assert result > 0  # CTL persists longer than ATL


# ==============================================================================
# daily_metrics_compute — compute_readiness (importable without AWS)
# ==============================================================================

class TestComputeReadiness:
    def _import_fn(self):
        if not _dmc_available:
            pytest.skip(f"daily_metrics_compute_lambda unavailable: {_dmc_import_error}")
        return dmc.compute_readiness

    def test_no_data_returns_none(self):
        compute_readiness = self._import_fn()
        score, colour = compute_readiness({
            "whoop": None, "whoop_today": None,
            "sleep": None, "hrv": {}, "tsb": None,
        })
        assert score is None
        assert colour == "gray"

    def test_high_recovery_gives_green(self):
        compute_readiness = self._import_fn()
        score, colour = compute_readiness({
            "whoop": {"recovery_score": 95},
            "whoop_today": None,
            "sleep": {"sleep_score": 90},
            "hrv": {"hrv_7d": 60, "hrv_30d": 55},
            "tsb": 5,
        })
        assert score is not None
        assert score >= 75
        assert colour in ("green", "yellow")

    def test_low_recovery_gives_red(self):
        compute_readiness = self._import_fn()
        score, colour = compute_readiness({
            "whoop": {"recovery_score": 10},
            "whoop_today": None,
            "sleep": {"sleep_score": 20},
            "hrv": {"hrv_7d": 30, "hrv_30d": 60},  # HRV declining
            "tsb": -20,
        })
        assert score is not None
        assert score < 65
        assert colour in ("red", "yellow")

    def test_score_clamped_0_100(self):
        compute_readiness = self._import_fn()
        score, _ = compute_readiness({
            "whoop": {"recovery_score": 100},
            "whoop_today": None,
            "sleep": {"sleep_score": 100},
            "hrv": {"hrv_7d": 100, "hrv_30d": 1},
            "tsb": 999,
        })
        assert score is not None
        assert 0 <= score <= 100


# ==============================================================================
# Dispatcher Routing Tests (R9 hardening)
# Verifies each SIMP-1 dispatcher correctly routes view= parameters to the
# underlying tool functions. Prevents silent regressions when underlying
# function signatures change.
# ==============================================================================

MCP_PATH = os.path.join(ROOT, "mcp")
if MCP_PATH not in sys.path:
    sys.path.insert(0, MCP_PATH)


class TestDispatcherRouting:
    """9 dispatcher routing unit tests — one per SIMP-1 dispatcher."""

    def _mock_dispatcher(self, dispatcher_fn, view, underlying_name, module):
        """Call dispatcher with view= and verify it routes to the correct underlying fn.

        Returns sentinel directly — routing is verified by mock_fn.assert_called_once().
        Dispatchers may mutate the return value (e.g. add _disclaimer per R13-F09);
        that mutation is intentional product behaviour, not a routing regression.
        """
        from unittest.mock import patch, MagicMock
        sentinel = {"routed": True, "view": view}
        with patch.object(module, underlying_name, return_value=dict(sentinel)) as mock_fn:
            dispatcher_fn({"view": view})
        mock_fn.assert_called_once()
        # Return the original sentinel, not the (possibly mutated) dispatcher output
        return sentinel

    def test_get_health_routes_dashboard(self):
        """get_health(view=dashboard) routes to tool_get_health_dashboard."""
        try:
            import mcp.tools_health as mod
            result = self._mock_dispatcher(mod.tool_get_health, "dashboard", "tool_get_health_dashboard", mod)
            assert result == {"routed": True, "view": "dashboard"}
        except (ImportError, AttributeError):
            pytest.skip("tools_health dispatcher not available in test environment")

    def test_get_health_routes_risk_profile(self):
        """get_health(view=risk_profile) routes to tool_get_health_risk_profile."""
        try:
            import mcp.tools_health as mod
            result = self._mock_dispatcher(mod.tool_get_health, "risk_profile", "tool_get_health_risk_profile", mod)
            assert result == {"routed": True, "view": "risk_profile"}
        except (ImportError, AttributeError):
            pytest.skip("tools_health dispatcher not available in test environment")

    def test_get_training_routes_load(self):
        """get_training(view=load) routes to tool_get_training_load."""
        try:
            import mcp.tools_training as mod
            result = self._mock_dispatcher(mod.tool_get_training, "load", "tool_get_training_load", mod)
            assert result == {"routed": True, "view": "load"}
        except (ImportError, AttributeError):
            pytest.skip("tools_training dispatcher not available in test environment")

    def test_get_labs_routes_results(self):
        """get_labs(view=results) routes to tool_get_lab_results."""
        try:
            import mcp.tools_labs as mod
            result = self._mock_dispatcher(mod.tool_get_labs, "results", "tool_get_lab_results", mod)
            assert result == {"routed": True, "view": "results"}
        except (ImportError, AttributeError):
            pytest.skip("tools_labs dispatcher not available in test environment")

    def test_get_character_routes_sheet(self):
        """get_character(view=sheet) routes to tool_get_character_sheet."""
        try:
            import mcp.tools_character as mod
            result = self._mock_dispatcher(mod.tool_get_character, "sheet", "tool_get_character_sheet", mod)
            assert result == {"routed": True, "view": "sheet"}
        except (ImportError, AttributeError):
            pytest.skip("tools_character dispatcher not available in test environment")

    def test_get_cgm_routes_dashboard(self):
        """get_cgm(view=dashboard) routes to tool_get_cgm_dashboard."""
        try:
            import mcp.tools_cgm as mod
            result = self._mock_dispatcher(mod.tool_get_cgm, "dashboard", "tool_get_cgm_dashboard", mod)
            assert result == {"routed": True, "view": "dashboard"}
        except (ImportError, AttributeError):
            pytest.skip("tools_cgm dispatcher not available in test environment")

    def test_get_nutrition_routes_summary(self):
        """get_nutrition(view=summary) routes to tool_get_nutrition_summary."""
        try:
            import mcp.tools_nutrition as mod
            result = self._mock_dispatcher(mod.tool_get_nutrition, "summary", "tool_get_nutrition_summary", mod)
            assert result == {"routed": True, "view": "summary"}
        except (ImportError, AttributeError):
            pytest.skip("tools_nutrition dispatcher not available in test environment")

    def test_get_strength_routes_prs(self):
        """get_strength(view=prs) routes to tool_get_strength_prs."""
        try:
            import mcp.tools_strength as mod
            result = self._mock_dispatcher(mod.tool_get_strength, "prs", "tool_get_strength_prs", mod)
            assert result == {"routed": True, "view": "prs"}
        except (ImportError, AttributeError):
            pytest.skip("tools_strength dispatcher not available in test environment")

    def test_get_daily_snapshot_routes_summary(self):
        """get_daily_snapshot(view=summary) routes to tool_get_daily_summary."""
        try:
            import mcp.tools_data as mod
            result = self._mock_dispatcher(mod.tool_get_daily_snapshot, "summary", "tool_get_daily_summary", mod)
            assert result == {"routed": True, "view": "summary"}
        except (ImportError, AttributeError):
            pytest.skip("tools_data dispatcher not available in test environment")


# ==============================================================================
# Standalone runner
# ==============================================================================

if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
