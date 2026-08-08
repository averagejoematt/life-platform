#!/usr/bin/env python3
"""tests/test_scoring_engine_behavior.py — behavioral contracts of
`lambdas/health/scoring_engine.py`, the day-grade core.

Part of #1658 tranche 2, on that issue's "deploy_critical core" priority. This
module produces the single number and letter a reader sees at the top of the
brief and the cockpit every day, and the component breakdown every coach
narrates from. `tests/test_business_logic.py` covers a slice of it; this file
covers the component scorers' actual arithmetic and, above all, their
**absence semantics** — which component drops out of the grade when its source
is silent, and which one scores zero instead.

Every expected value below is hand-derived from the documented weighting, not
copied from a run of the code.
"""

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

_import_err = None
try:
    from health import scoring_engine as se
except ImportError as _e:  # pragma: no cover — only when the bundle layout changes
    _import_err = _e
    se = None  # type: ignore

if _import_err is not None:  # pragma: no cover
    pytestmark = pytest.mark.skip(reason=f"scoring_engine unavailable: {_import_err}")  # type: ignore


DATE = "2026-05-09"  # a Saturday — used by the weekday-applicability tests


# ──────────────────────────────────────────────────────────────────────────────
# Primitives
# ──────────────────────────────────────────────────────────────────────────────


class TestPrimitives:
    def test_safe_float_converts_a_present_field(self):
        assert se.safe_float({"x": "3.5"}, "x") == 3.5

    def test_safe_float_returns_the_default_for_an_absent_field(self):
        assert se.safe_float({"y": 1}, "x") is None
        assert se.safe_float({"y": 1}, "x", default=0) == 0

    def test_safe_float_returns_the_default_for_an_unconvertible_value(self):
        assert se.safe_float({"x": "n/a"}, "x", default=7) == 7

    def test_safe_float_tolerates_a_missing_record(self):
        assert se.safe_float(None, "x") is None

    def test_avg_skips_absent_values_and_is_none_on_an_empty_window(self):
        assert se.avg([1, None, 3]) == 2.0
        assert se.avg([None]) is None
        assert se.avg([]) is None

    def test_clamp_bounds_both_ends(self):
        assert (se.clamp(-1), se.clamp(101), se.clamp(50)) == (0, 100, 50)


# ──────────────────────────────────────────────────────────────────────────────
# Sleep
# ──────────────────────────────────────────────────────────────────────────────


class TestScoreSleep:
    def test_no_sleep_record_drops_the_component_out_of_the_grade(self):
        """None (not 0) is what keeps an unmeasured night from being graded as
        a bad night — ADR-104."""
        assert se.score_sleep({}, {}) == (None, {})

    def test_a_record_with_no_usable_field_scores_none_but_still_reports_details(self):
        score, details = se.score_sleep({"sleep": {"unrelated": 1}}, {})
        assert score is None
        assert "sleep_score" in details

    def test_the_documented_weighting_of_score_efficiency_and_duration(self):
        # 40% whoop score, 30% efficiency, 30% duration-vs-target.
        # duration 7.5 == target → duration sub-score 100.
        data = {"sleep": {"sleep_score": 80, "sleep_efficiency_pct": 90, "sleep_duration_hours": 7.5}}
        score, details = se.score_sleep(data, {"sleep_target_hours_ideal": 7.5})
        assert details["duration_score"] == 100.0
        assert score == round(80 * 0.40 + 90 * 0.30 + 100 * 0.30)

    def test_present_parts_are_renormalised_when_a_field_is_missing(self):
        data = {"sleep": {"sleep_score": 80}}
        assert se.score_sleep(data, {})[0] == 80

    def test_duration_two_hours_off_target_scores_zero_on_that_sub_part(self):
        """The duration ramp is |Δ| / 2h → a two-hour miss is a total miss."""
        data = {"sleep": {"sleep_duration_hours": 5.5}}
        score, details = se.score_sleep(data, {"sleep_target_hours_ideal": 7.5})
        assert details["duration_score"] == 0.0
        assert score == 0

    def test_oversleeping_is_penalised_symmetrically_with_undersleeping(self):
        under = se.score_sleep({"sleep": {"sleep_duration_hours": 6.5}}, {"sleep_target_hours_ideal": 7.5})[0]
        over = se.score_sleep({"sleep": {"sleep_duration_hours": 8.5}}, {"sleep_target_hours_ideal": 7.5})[0]
        assert under == over == 50

    def test_the_profile_target_is_honoured_rather_than_a_hard_coded_seven_and_a_half(self):
        data = {"sleep": {"sleep_duration_hours": 9.0}}
        assert se.score_sleep(data, {"sleep_target_hours_ideal": 9.0})[1]["duration_score"] == 100.0

    def test_stage_percentages_are_reported_but_do_not_move_the_score(self):
        base = {"sleep_score": 80}
        plain = se.score_sleep({"sleep": dict(base)}, {})[0]
        staged = se.score_sleep({"sleep": dict(base, deep_pct=20, rem_pct=25, light_pct=55)}, {})
        assert staged[0] == plain
        assert staged[1]["deep_pct"] == 20


# ──────────────────────────────────────────────────────────────────────────────
# Recovery
# ──────────────────────────────────────────────────────────────────────────────


class TestScoreRecovery:
    def test_recovery_is_the_whoop_score_itself(self):
        assert se.score_recovery({"whoop": {"recovery_score": 62}}, {}) == (62, {"recovery_score": 62.0})

    def test_an_absent_recovery_reading_drops_the_component(self):
        assert se.score_recovery({}, {}) == (None, {})
        assert se.score_recovery({"whoop": {}}, {}) == (None, {})

    def test_an_out_of_range_reading_is_clamped_into_the_grade_scale(self):
        assert se.score_recovery({"whoop": {"recovery_score": 140}}, {})[0] == 100


# ──────────────────────────────────────────────────────────────────────────────
# Nutrition
# ──────────────────────────────────────────────────────────────────────────────


_NUTRITION_PROFILE = {
    "calorie_target": 2000,
    "protein_target_g": 190,
    "protein_floor_g": 170,
    "calorie_tolerance_pct": 10,
    "calorie_penalty_threshold_pct": 25,
    "fat_target_g": 60,
    "carb_target_g": 125,
}


class TestScoreNutrition:
    def test_no_nutrition_record_drops_the_component(self):
        assert se.score_nutrition({}, _NUTRITION_PROFILE) == (None, {})

    def test_calories_inside_the_tolerance_band_score_full_marks(self):
        data = {"macrofactor": {"total_calories_kcal": 2100}}  # 5% over, inside 10%
        assert se.score_nutrition(data, _NUTRITION_PROFILE)[1]["cal_score"] == 100

    def test_calories_beyond_the_penalty_threshold_score_zero(self):
        data = {"macrofactor": {"total_calories_kcal": 3000}}  # 50% over
        assert se.score_nutrition(data, _NUTRITION_PROFILE)[1]["cal_score"] == 0

    def test_a_surplus_is_penalised_harder_than_an_equal_deficit(self):
        """Asymmetric by design: a surplus directly stalls weight loss."""
        over = se.score_nutrition({"macrofactor": {"total_calories_kcal": 2300}}, _NUTRITION_PROFILE)[1]["cal_score"]
        under = se.score_nutrition({"macrofactor": {"total_calories_kcal": 1700}}, _NUTRITION_PROFILE)[1]["cal_score"]
        assert over == under - 15

    def test_the_calorie_ramp_between_tolerance_and_penalty_is_linear(self):
        # 17.5% off is the midpoint of the 10%→25% ramp → 50 before the surplus
        # penalty; taken on the deficit side so no penalty applies.
        data = {"macrofactor": {"total_calories_kcal": 2000 - 350}}
        assert se.score_nutrition(data, _NUTRITION_PROFILE)[1]["cal_score"] == 50

    def test_protein_at_or_above_target_scores_full_marks(self):
        for grams in (190, 250):
            data = {"macrofactor": {"total_protein_g": grams}}
            assert se.score_nutrition(data, _NUTRITION_PROFILE)[1]["protein_score"] == 100

    def test_protein_at_the_floor_scores_eighty(self):
        data = {"macrofactor": {"total_protein_g": 170}}
        assert se.score_nutrition(data, _NUTRITION_PROFILE)[1]["protein_score"] == 80

    def test_protein_between_floor_and_target_ramps_from_eighty_to_one_hundred(self):
        data = {"macrofactor": {"total_protein_g": 180}}  # halfway
        assert se.score_nutrition(data, _NUTRITION_PROFILE)[1]["protein_score"] == 90

    def test_protein_below_the_floor_ramps_down_to_zero(self):
        data = {"macrofactor": {"total_protein_g": 85}}  # half the floor
        assert se.score_nutrition(data, _NUTRITION_PROFILE)[1]["protein_score"] == 40

    def test_macros_on_target_score_full_marks(self):
        data = {"macrofactor": {"total_fat_g": 60, "total_carbs_g": 125}}
        assert se.score_nutrition(data, _NUTRITION_PROFILE)[1]["macro_score"] == 100

    def test_macros_one_hundred_percent_off_on_both_score_zero(self):
        data = {"macrofactor": {"total_fat_g": 120, "total_carbs_g": 250}}
        assert se.score_nutrition(data, _NUTRITION_PROFILE)[1]["macro_score"] == 0

    def test_a_single_macro_alone_does_not_produce_a_macro_sub_score(self):
        data = {"macrofactor": {"total_fat_g": 60}}
        assert "macro_score" not in se.score_nutrition(data, _NUTRITION_PROFILE)[1]

    def test_the_component_composite_uses_the_documented_forty_forty_twenty_split(self):
        data = {
            "macrofactor": {
                "total_calories_kcal": 2000,  # cal 100
                "total_protein_g": 190,  # protein 100
                "total_fat_g": 90,  # 50% off
                "total_carbs_g": 125,  # on target → macro 100 - 50*0.5 = 75
            }
        }
        score, details = se.score_nutrition(data, _NUTRITION_PROFILE)
        assert (details["cal_score"], details["protein_score"], details["macro_score"]) == (100, 100, 75)
        assert score == round(100 * 0.40 + 100 * 0.40 + 75 * 0.20)

    def test_a_logged_day_carrying_no_usable_macro_field_drops_the_component(self):
        assert se.score_nutrition({"macrofactor": {"meals": 3}}, _NUTRITION_PROFILE)[0] is None


# ──────────────────────────────────────────────────────────────────────────────
# Movement
# ──────────────────────────────────────────────────────────────────────────────


class TestScoreMovement:
    def test_an_hour_of_logged_exercise_scores_full_marks_on_that_half(self):
        """Base 70 for showing up, +0.5/min → 60 min reaches 100."""
        data = {"strava": {"activity_count": 1, "total_moving_time_seconds": 3600}}
        assert se.score_movement(data, {})[1]["exercise_score"] == 100

    def test_a_short_session_still_earns_the_showing_up_base(self):
        data = {"strava": {"activity_count": 1, "total_moving_time_seconds": 600}}
        assert se.score_movement(data, {})[1]["exercise_score"] == 75  # 70 + 10*0.5

    def test_a_strava_record_with_no_activities_scores_zero_exercise(self):
        data = {"strava": {"activity_count": 0, "total_moving_time_seconds": 0}}
        assert se.score_movement(data, {})[1]["exercise_score"] == 0

    def test_steps_are_scored_against_the_profile_target(self):
        data = {"apple": {"steps": 3500}}
        assert se.score_movement(data, {"step_target": 7000})[1]["step_score"] == 50

    def test_steps_beyond_the_target_do_not_score_above_one_hundred(self):
        data = {"apple": {"steps": 20000}}
        assert se.score_movement(data, {"step_target": 7000})[1]["step_score"] == 100

    def test_exercise_and_steps_are_weighted_equally(self):
        data = {"strava": {"activity_count": 1, "total_moving_time_seconds": 3600}, "apple": {"steps": 0}}
        assert se.score_movement(data, {"step_target": 7000})[0] == 50

    def test_a_day_with_no_movement_source_at_all_scores_zero_not_absent(self):
        """CHARACTERIZATION, not an endorsement. Every other component here
        returns None when its source is silent (and so drops out of the grade);
        movement instead scores a hard 0, because `exercise_score` is appended
        unconditionally. On a day when BOTH Strava and Apple Health failed to
        ingest, the day grade is therefore penalised as if nothing was done.
        The asymmetry is reported with this tranche — see the PR body."""
        score, details = se.score_movement({}, {})
        assert score == 0
        assert details["exercise_score"] == 0
        assert "step_score" not in details

    def test_the_step_count_is_reported_alongside_its_score(self):
        details = se.score_movement({"apple": {"steps": 8123}}, {"step_target": 7000})[1]
        assert details["steps"] == 8123


# ──────────────────────────────────────────────────────────────────────────────
# Habits
# ──────────────────────────────────────────────────────────────────────────────


def _habit_data(habits, date=DATE, **kw):
    return {"date": date, "habitify": {"habits": habits}, **kw}


class TestScoreHabitsRegistry:
    def test_no_habitify_record_drops_the_component(self):
        assert se.score_habits_registry({}, {"habit_registry": {"a": {"status": "active", "tier": 0}}}) == (None, {})

    def test_a_missing_registry_falls_back_to_the_legacy_mvp_list(self):
        data = _habit_data({"sleep": 1, "steps": 0})
        score, details = se.score_habits_registry(data, {"mvp_habits": ["sleep", "steps"]})
        assert score == 50
        assert details["mvp_status"] == {"sleep": True, "steps": False}

    def test_the_legacy_path_with_no_mvp_list_drops_the_component(self):
        assert se.score_habits_registry(_habit_data({"sleep": 1}), {}) == (None, {})

    def test_tier_zero_carries_three_times_the_weight_of_tier_one(self):
        """A missed non-negotiable must dominate a met nice-to-have."""
        registry = {"t0": {"status": "active", "tier": 0}, "t1": {"status": "active", "tier": 1}}
        missed_t0 = se.score_habits_registry(_habit_data({"t0": 0, "t1": 1}), {"habit_registry": registry})[0]
        missed_t1 = se.score_habits_registry(_habit_data({"t0": 1, "t1": 0}), {"habit_registry": registry})[0]
        # weights 3:1 → (0*3 + 100*1)/4 = 25 vs (100*3 + 0*1)/4 = 75
        assert (missed_t0, missed_t1) == (25, 75)

    def test_inactive_habits_are_excluded_entirely(self):
        registry = {"live": {"status": "active", "tier": 0}, "dead": {"status": "archived", "tier": 0}}
        score, details = se.score_habits_registry(_habit_data({"live": 1, "dead": 0}), {"habit_registry": registry})
        assert score == 100
        assert details["tier0"] == {"done": 1, "total": 1}

    def test_a_weekday_only_habit_does_not_penalise_a_weekend(self):
        registry = {"work": {"status": "active", "tier": 0, "applicable_days": "weekdays"}}
        # 2026-05-09 is a Saturday.
        assert se.score_habits_registry(_habit_data({"work": 0}, date="2026-05-09"), {"habit_registry": registry})[0] is None
        # 2026-05-08 is a Friday.
        assert se.score_habits_registry(_habit_data({"work": 0}, date="2026-05-08"), {"habit_registry": registry})[0] == 0

    def test_a_post_training_habit_is_skipped_on_a_day_with_no_training(self):
        registry = {"stretch": {"status": "active", "tier": 1, "applicable_days": "post_training"}}
        assert se.score_habits_registry(_habit_data({"stretch": 0}), {"habit_registry": registry})[0] is None

    def test_a_post_training_habit_counts_on_a_day_with_a_logged_activity(self):
        registry = {"stretch": {"status": "active", "tier": 1, "applicable_days": "post_training"}}
        data = _habit_data({"stretch": 1}, strava={"activities": [{"id": 1}]})
        assert se.score_habits_registry(data, {"habit_registry": registry})[0] == 100

    def test_an_unparseable_date_falls_back_to_treating_the_day_as_a_weekday(self):
        registry = {"work": {"status": "active", "tier": 0, "applicable_days": "weekdays"}}
        assert se.score_habits_registry(_habit_data({"work": 1}, date=""), {"habit_registry": registry})[0] == 100

    def test_a_tier_two_habit_is_scored_on_seven_day_frequency_not_the_single_day(self):
        registry = {"read": {"status": "active", "tier": 2, "target_frequency": 4}}
        week = [{"habits": {"read": 1}}, {"habits": {"read": 1}}, {"habits": {"read": 1}}]
        data = _habit_data({"read": 1}, habitify_7d=week)
        # today + 3 prior days = 4 of a 4/week target → 100
        assert se.score_habits_registry(data, {"habit_registry": registry})[0] == 100

    def test_a_tier_two_habit_below_its_frequency_target_scores_proportionally(self):
        registry = {"read": {"status": "active", "tier": 2, "target_frequency": 4}}
        data = _habit_data({"read": 1}, habitify_7d=[])
        assert se.score_habits_registry(data, {"habit_registry": registry})[0] == 25

    def test_scoring_weight_can_down_weight_an_emerging_evidence_habit(self):
        registry = {
            "solid": {"status": "active", "tier": 1},
            "emerging": {"status": "active", "tier": 1, "scoring_weight": 0.5},
        }
        # both done: (100 + 50) / 2 = 75
        assert se.score_habits_registry(_habit_data({"solid": 1, "emerging": 1}), {"habit_registry": registry})[0] == 75

    def test_vice_habits_are_reported_separately_from_the_tier_counts(self):
        registry = {"no_weed": {"status": "active", "tier": 1, "vice": True}}
        _, details = se.score_habits_registry(_habit_data({"no_weed": 1}), {"habit_registry": registry})
        assert details["vice_status"] == {"no_weed": True}
        assert details["vices"] == {"held": 1, "total": 1}

    def test_a_registry_whose_habits_are_all_inapplicable_drops_the_component(self):
        registry = {"work": {"status": "active", "tier": 0, "applicable_days": "weekdays"}}
        assert se.score_habits_registry(_habit_data({}, date="2026-05-10"), {"habit_registry": registry}) == (None, {})

    def test_an_untracked_habit_counts_as_not_done_rather_than_crashing(self):
        registry = {"ghost": {"status": "active", "tier": 0}}
        assert se.score_habits_registry(_habit_data({}), {"habit_registry": registry})[0] == 0

    def test_the_details_advertise_the_tier_weighted_method_the_writers_key_off(self):
        """`store_habit_scores` refuses to write unless this marker is present."""
        registry = {"a": {"status": "active", "tier": 0}}
        _, details = se.score_habits_registry(_habit_data({"a": 1}), {"habit_registry": registry})
        assert details["composite_method"] == "tier_weighted"


# ──────────────────────────────────────────────────────────────────────────────
# Hydration / journal / glucose
# ──────────────────────────────────────────────────────────────────────────────


class TestScoreHydration:
    def test_water_is_scored_against_the_profile_target(self):
        assert se.score_hydration({"apple": {"water_intake_ml": 1478}}, {"water_target_ml": 2956})[0] == 50

    def test_exceeding_the_target_does_not_score_above_one_hundred(self):
        assert se.score_hydration({"apple": {"water_intake_ml": 6000}}, {"water_target_ml": 2956})[0] == 100

    def test_a_sub_five_hundred_millilitre_day_is_read_as_no_data_not_as_failure(self):
        """HAE truncates its payload on a partial sync and delivers ~350 ml;
        grading that as a 12% hydration day would be a lie about behaviour."""
        assert se.score_hydration({"apple": {"water_intake_ml": 350}}, {}) == (None, {})

    def test_no_apple_health_record_drops_the_component(self):
        assert se.score_hydration({}, {}) == (None, {})

    def test_the_details_report_both_units_so_no_surface_re_derives_them(self):
        _, details = se.score_hydration({"apple": {"water_intake_ml": 2957}}, {"water_target_ml": 2957})
        assert details["water_ml"] == 2957
        assert details["water_oz"] == round(2957 / 29.5735, 1)


class TestScoreJournal:
    def test_no_entries_drops_the_component_but_reports_the_zero_count(self):
        assert se.score_journal({}, {}) == (None, {"entries": 0})

    def test_both_bookend_templates_score_full_marks(self):
        data = {"journal_entries": [{"template": "Morning"}, {"template": "evening"}]}
        score, details = se.score_journal(data, {})
        assert score == 100
        assert details["has_morning"] and details["has_evening"]

    def test_one_bookend_template_scores_sixty(self):
        assert se.score_journal({"journal_entries": [{"template": "morning"}]}, {})[0] == 60

    def test_entries_with_neither_bookend_still_earn_credit_for_writing(self):
        assert se.score_journal({"journal_entries": [{"template": "stressor"}]}, {})[0] == 40

    def test_an_entry_with_no_template_is_counted_but_not_credited_as_a_bookend(self):
        score, details = se.score_journal({"journal_entries": [{"template": None}]}, {})
        assert score == 40
        assert details["entries"] == 1
        assert details["templates"] == []


class TestScoreGlucose:
    def test_no_apple_health_record_drops_the_component(self):
        assert se.score_glucose({}, {}) == (None, {})

    def test_a_record_with_no_glucose_fields_drops_the_component(self):
        assert se.score_glucose({"apple": {"steps": 8000}}, {}) == (None, {})

    def test_time_in_range_at_or_above_ninety_five_percent_scores_full_marks(self):
        assert se.score_glucose({"apple": {"blood_glucose_time_in_range_pct": 97}}, {})[1]["tir_score"] == 100

    def test_time_in_range_at_ninety_percent_scores_eighty(self):
        assert se.score_glucose({"apple": {"blood_glucose_time_in_range_pct": 90}}, {})[1]["tir_score"] == 80

    def test_time_in_range_at_seventy_percent_scores_zero(self):
        assert se.score_glucose({"apple": {"blood_glucose_time_in_range_pct": 70}}, {})[1]["tir_score"] == 0

    def test_an_average_glucose_under_ninety_five_scores_full_marks(self):
        assert se.score_glucose({"apple": {"blood_glucose_avg": 90}}, {})[1]["avg_score"] == 100

    def test_an_average_glucose_at_or_above_one_forty_scores_zero(self):
        assert se.score_glucose({"apple": {"blood_glucose_avg": 145}}, {})[1]["avg_score"] == 0

    def test_variability_under_fifteen_scores_full_marks_and_over_forty_scores_zero(self):
        base = {"blood_glucose_avg": 100}
        low = se.score_glucose({"apple": dict(base, blood_glucose_std_dev=10)}, {})[1]["var_score"]
        high = se.score_glucose({"apple": dict(base, blood_glucose_std_dev=45)}, {})[1]["var_score"]
        assert (low, high) == (100, 0)

    def test_the_composite_uses_the_documented_fifty_thirty_twenty_split(self):
        data = {
            "apple": {
                "blood_glucose_time_in_range_pct": 97,  # 100
                "blood_glucose_avg": 90,  # 100
                "blood_glucose_std_dev": 45,  # 0
            }
        }
        assert se.score_glucose(data, {})[0] == round(100 * 0.50 + 100 * 0.30 + 0 * 0.20)

    def test_the_reading_count_is_carried_so_a_thin_day_is_visible(self):
        """ADR-105: n travels with the claim."""
        data = {"apple": {"blood_glucose_avg": 100, "blood_glucose_readings_count": 3}}
        assert se.score_glucose(data, {})[1]["readings"] == 3


# ──────────────────────────────────────────────────────────────────────────────
# Grade assembly
# ──────────────────────────────────────────────────────────────────────────────


class TestLetterGrade:
    @pytest.mark.parametrize(
        "score,letter",
        [(100, "A+"), (95, "A+"), (94, "A"), (90, "A"), (89, "A-"), (85, "A-"), (84, "B+"), (80, "B+"), (79, "B"), (75, "B")],
    )
    def test_the_upper_bands_switch_at_their_documented_boundaries(self, score, letter):
        assert se.letter_grade(score) == letter

    @pytest.mark.parametrize(
        "score,letter",
        [(74, "B-"), (70, "B-"), (69, "C+"), (65, "C+"), (64, "C"), (60, "C"), (59, "C-"), (55, "C-"), (54, "D"), (45, "D"), (44, "F")],
    )
    def test_the_lower_bands_switch_at_their_documented_boundaries(self, score, letter):
        assert se.letter_grade(score) == letter

    def test_a_zero_score_is_an_f_not_an_error(self):
        assert se.letter_grade(0) == "F"

    def test_the_grade_colour_families_follow_the_letter(self):
        colours = {se.grade_colour(g) for g in ("A+", "A", "A-")}
        assert len(colours) == 1
        assert se.grade_colour("B") != se.grade_colour("A")
        assert se.grade_colour("C") != se.grade_colour("B")
        assert se.grade_colour("F") == se.grade_colour("D")


class TestComputeDayGrade:
    def test_every_registered_component_is_scored_and_reported(self):
        """Guard the SET: the expectation is derived from COMPONENT_SCORERS, so
        adding a ninth component cannot silently skip the breakdown the cockpit
        and the coaches read."""
        score, grade, comp_scores, comp_details = se.compute_day_grade({}, {})
        assert set(comp_scores) == set(se.COMPONENT_SCORERS)
        assert set(comp_details) == set(se.COMPONENT_SCORERS)

    def test_a_day_with_no_weights_configured_is_ungraded_rather_than_zero(self):
        """ADR-104: '—' is honest; a 0 would read as the worst possible day."""
        data = {"whoop": {"recovery_score": 90}}
        score, grade, _, _ = se.compute_day_grade(data, {})
        assert score is None
        assert grade == "—"

    def test_a_component_with_no_data_is_excluded_from_the_weighted_average(self):
        data = {"whoop": {"recovery_score": 80}}
        weights = {"recovery": 0.5, "sleep_quality": 0.5}
        score, _, _, _ = se.compute_day_grade(data, {"day_grade_weights": weights})
        assert score == 80  # sleep absent → recovery carries the whole grade

    def test_a_component_weighted_zero_is_scored_but_never_counted(self):
        data = {"whoop": {"recovery_score": 20}, "sleep": {"sleep_score": 100}}
        weights = {"recovery": 0.0, "sleep_quality": 1.0}
        score, _, comp_scores, _ = se.compute_day_grade(data, {"day_grade_weights": weights})
        assert comp_scores["recovery"] == 20
        assert score == 100

    def test_the_grade_is_the_weight_normalised_mean_of_the_active_components(self):
        data = {"whoop": {"recovery_score": 90}, "sleep": {"sleep_score": 50}}
        weights = {"recovery": 0.3, "sleep_quality": 0.1}
        score, _, _, _ = se.compute_day_grade(data, {"day_grade_weights": weights})
        assert score == round((90 * 0.3 + 50 * 0.1) / 0.4)

    def test_the_letter_agrees_with_the_numeric_score(self):
        data = {"whoop": {"recovery_score": 88}}
        score, grade, _, _ = se.compute_day_grade(data, {"day_grade_weights": {"recovery": 1.0}})
        assert grade == se.letter_grade(score)

    def test_an_ungraded_day_still_returns_the_component_detail_it_did_gather(self):
        data = {"whoop": {"recovery_score": 90}}
        _, _, comp_scores, comp_details = se.compute_day_grade(data, {})
        assert comp_scores["recovery"] == 90
        assert comp_details["recovery"] == {"recovery_score": 90.0}
