"""The 2026-10-04 value sweep of the Instagram recap cards: five numbers drawn from the
wrong place, each pinned here against the live shape that exposed it.

1. Protein under "ATE" was `computed_metrics.protein_g_avg` — a running average over the
   cycle — beside the day's MacroFactor calories (day 22: 148 g drawn, 92 g logged).
2. Carbs/fat came from the compute cron's snapshot, so a meal logged after it ran was
   missing (10-01: 44 g carbs drawn, 51 g logged). MacroFactor outranks every macro.
3. Walked miles summed every Walk/Hike, so two devices recording one walk with distance
   counted it twice.
4. "N working sets" counted every set, walking and stretching entries included.
5. The week's weight change ran first-to-last weigh-in INSIDE the week, dropping the
   boundary day (wk4: −3.5 drawn, −2.9 real), so weeks did not sum to the total.
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "lambdas"))

from content import recap_data  # noqa: E402


def _facts(monkeypatch, *, computed=None, mf=None, strava=None, hevy=None):
    days = {"computed_metrics": computed, "macrofactor": mf, "strava": strava}
    monkeypatch.setattr(recap_data, "_get_day", lambda table, source, date: days.get(source))
    monkeypatch.setattr(recap_data, "_query_prefix", lambda table, source, prefix: (hevy or []) if source == "hevy" else [])
    return recap_data.day_facts(None, "2026-09-27")


def test_protein_is_the_days_macrofactor_total_not_the_running_average(monkeypatch):
    f = _facts(
        monkeypatch, computed={"protein_g_avg": 148.4, "protein_g_target": 170}, mf={"total_protein_g": 92, "total_calories_kcal": 1170}
    )
    assert f.protein_g == 92
    assert f.calories == 1170


def test_no_macrofactor_row_means_no_protein_never_the_average(monkeypatch):
    f = _facts(monkeypatch, computed={"protein_g_avg": 148.4})
    assert f.protein_g is None


def test_macrofactor_outranks_the_compute_snapshot_for_carbs_and_fat(monkeypatch):
    computed = {"component_details": {"nutrition": {"carbs_g": 44, "fat_g": 82, "calories": 1500}}}
    f = _facts(monkeypatch, computed=computed, mf={"total_carbs_g": 51, "total_fat_g": 84, "total_calories_kcal": 1690})
    assert (f.carbs_g, f.fat_g, f.calories) == (51, 84, 1690)


def test_one_walk_recorded_by_two_devices_counts_once():
    acts = [
        # 2024-09-11 shape: Garmin and the Strava app both carried distance for one walk.
        {"sport_type": "Walk", "start_date": "2024-09-19T22:55:00Z", "elapsed_time_seconds": 3600, "distance_miles": 3.0},
        {"sport_type": "Walk", "start_date": "2024-09-19T22:57:00Z", "elapsed_time_seconds": 3480, "distance_miles": 2.99},
        # a separate walk later the same day still counts
        {"sport_type": "Hike", "start_date": "2024-09-20T02:00:00Z", "elapsed_time_seconds": 1800, "distance_miles": 1.5},
        # WHOOP's copy carries no distance
        {"sport_type": "Walk", "start_date": "2024-09-19T22:57:00Z", "elapsed_time_seconds": 3480, "distance_miles": None},
        {"sport_type": "WeightTraining", "start_date": "2024-09-19T20:00:00Z", "distance_miles": 9.9},
    ]
    assert recap_data.walk_miles(acts) == 4.5


def test_working_sets_exclude_walking_and_stretching_entries():
    w = recap_data._workout_facts(
        [
            {
                "title": "Upper",
                "exercises": [
                    {"name": "Bench Press", "sets": [{"reps": 8, "weight_lbs": 185}, {"reps": 8, "weight_lbs": 185}]},
                    {"name": "Treadmill", "sets": [{"duration_sec": 1800, "distance_m": 3000}]},
                    {"name": "Stretching", "sets": [{"duration_sec": 600}]},
                ],
            }
        ]
    )[0]
    assert (w.n_sets, w.n_working_sets) == (4, 2)

    from web import recap_templates

    class F:
        workouts = [w]

    assert recap_templates._workout_copy(F)["lines"][0] == "2 working sets"


def test_week_weight_change_runs_from_the_weigh_in_before_the_week(monkeypatch):
    from web import recap_card_lambda as C

    weights = {"2026-09-26": 313.8, "2026-09-27": 314.5, "2026-10-03": 311.0}

    def fake(table, date, experiment_start=None):
        f = recap_data.DayFacts(date=date)
        f.weight_lb = weights.get(date, 312.0)
        return f

    monkeypatch.setattr(recap_data, "day_facts", fake)
    monkeypatch.setattr(C, "EXPERIMENT_START_DATE", "2026-09-06")
    assert C._week_totals(None, "2026-09-27", "2026-10-03")["weight_delta"] == -2.8
