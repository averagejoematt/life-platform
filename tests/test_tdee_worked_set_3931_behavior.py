"""tests/test_tdee_worked_set_3931_behavior.py — TDEE may not charge rest time (#3931).

THE SPECIMEN IS LIVE
--------------------
Every number this file replays comes off the payload #3931 was filed against:

    exercise_kcal_7d   = 20,276 kcal   (2,897 kcal/day)
    tdee               =  5,059 kcal
    published deficit  =  3,529 kcal/day  -> a 69.8% deficit label
    intake             =  5,059 - 3,529 = 1,530 kcal/day
    weight trend       = 11.7 lb over 13 days

The cause named in the issue: `lambdas/health/tdee.py`'s ~6 kcal/kg/hour duration proxy
was applied across the FULL logged gym duration — rest between sets included — charging
roughly 3,000 kcal to one 3.5-hour lifting session. A minute spent sitting on a bench is
already inside the 24-hour BMR term; charging it a second time at ~6x resting is the
inflation.

Two reconstruction parameters are named here rather than buried, because the issue does
not state them and this file will not invent a profile read:

  * ``SPECIMEN_WEIGHT_KG = 142.88`` (315.0 lb) — the weight at which the issue's own
    "roughly 3,000 kcal for one 3.5-hour session" is EXACT: 6 x 142.88 x 3.5 = 3,000.5.
  * ``BMR_FROM_ISSUE = 2,162`` — not a Mifflin evaluation, but the issue's own
    arithmetic: 5,059 published TDEE minus the published 20,276/7 = 2,897 exercise term.

With those two, the 7-day window reconstructed below reproduces the issue's numbers to
the kcal (test_the_specimen_window_replays_the_published_tdee_exactly), which is what
makes the post-fix number a replay rather than a fresh guess.

The Hevy set fixtures are the wire shape — ``workout.exercises[].sets[]`` carrying
``type``/``weight_kg``/``reps`` with an optional ``duration_seconds``, the shape
``lambdas/training/hevy_compiler._set_to_wire`` writes and
``mcp/strength_helpers.normalize_hevy_items`` reads.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from health import tdee

pytestmark = pytest.mark.premerge


# ── the specimen's reconstruction parameters (see the module docstring) ────────
SPECIMEN_WEIGHT_KG = 142.88  # 315.0 lb
SESSION_SECONDS = 12600  # the issue's 3.5-hour logged lifting session
SETS_PER_SESSION = 20
PUBLISHED_EXERCISE_KCAL_7D = 20276
PUBLISHED_TDEE = 5059
PUBLISHED_DEFICIT = 3529
SPECIMEN_INTAKE = PUBLISHED_TDEE - PUBLISHED_DEFICIT  # 1,530 kcal/day
BMR_FROM_ISSUE = PUBLISHED_TDEE - round(PUBLISHED_EXERCISE_KCAL_7D / 7)  # 2,162
SPECIMEN_TREND_LB_WK = round(-11.7 * 7 / 13, 2)  # -6.3 lb/wk over 13 days

# The red-team band the issue's own owner ruling was written against: Mifflin RMR
# ~2,350 plus measured activity puts a defensible TDEE at ~3,300-4,000 kcal.
DEFENSIBLE_TDEE_LO, DEFENSIBLE_TDEE_HI = 3300, 4000


def lifting_set(reps: int = 8, **extra) -> dict:
    """One weight-rep working set — no `duration_seconds`, like every Hevy strength set."""
    return {"type": "normal", "weight_kg": 60.0, "reps": reps, **extra}


def hevy_session(n_sets: int = SETS_PER_SESSION, **set_kwargs) -> dict:
    return {"exercises": [{"name": "Bench Press (Barbell)", "sets": [lifting_set(**set_kwargs) for _ in range(n_sets)]}]}


def strava_lift_day(date: str, seconds: int = SESSION_SECONDS) -> dict:
    """A Hevy session as it reaches Strava: sport_type WeightTraining, full wall duration."""
    return {
        "date": date,
        "total_moving_time_seconds": seconds,
        "activities": [{"sport_type": "WeightTraining", "type": "WeightTraining", "moving_time_seconds": seconds}],
    }


def strava_walk_day(date: str, seconds: int) -> dict:
    return {
        "date": date,
        "total_moving_time_seconds": seconds,
        "activities": [{"sport_type": "Walk", "type": "Walk", "moving_time_seconds": seconds}],
    }


# ══════════════════════════════════════════════════════════════════════════════
# 1. The lifting term — worked-set time, on the Hevy wire shape
# ══════════════════════════════════════════════════════════════════════════════


def test_a_three_and_a_half_hour_session_costs_hundreds_of_kcal_not_three_thousand():
    """THE BUG. Same session, same rate — the denominator is worked time, not wall time.

    20 sets x the stated 40 s assumption = 800 s of work, so
    6 kcal/kg/hour x 142.88 kg x (800/3600) h = 190.5 -> 191 kcal.
    The retired form charged the full 12,600 s: 6 x 142.88 x 3.5 = 3,000 kcal.
    """
    out = tdee.exercise_energy([strava_lift_day("2026-09-01")], SPECIMEN_WEIGHT_KG, [hevy_session()])
    assert out["lifting"]["sets"] == 20
    assert out["lifting"]["worked_seconds"] == 800.0
    assert out["lifting"]["logged_seconds"] == 12600.0
    assert 150 <= out["kcal"] <= 500, out
    assert out["kcal"] == 191.0
    # and the same fixture under the retired treatment — a row with no per-activity
    # breakdown to split — still charges the full duration, which is what 3,000 looks like.
    legacy = [{"date": "2026-09-01", "total_moving_time_seconds": SESSION_SECONDS}]
    assert tdee.exercise_energy(legacy, SPECIMEN_WEIGHT_KG)["kcal"] == 3000.0


def test_the_40_second_assumption_is_labelled_wherever_it_is_applied():
    """ADR-104/105: an assumption wearing a number must say it is one, on the payload."""
    out = tdee.exercise_energy([strava_lift_day("2026-09-01")], SPECIMEN_WEIGHT_KG, [hevy_session()])
    assert "assumed_40s_per_unlogged_set" in out["lifting"]["basis"]
    assert "assumed_40s_per_unlogged_set" in out["basis"]
    assert tdee.WORK_SECONDS_PER_REP_SET == 40.0


def test_a_logged_set_duration_is_used_instead_of_the_assumption():
    """A duration-style set (plank, sled, machine interval) carries real measured work."""
    session = {"exercises": [{"name": "Plank", "sets": [{"type": "normal", "duration_seconds": 90} for _ in range(4)]}]}
    ws = tdee.worked_set_seconds([session])
    assert (ws["seconds"], ws["measured_seconds"], ws["assumed_seconds"]) == (360.0, 360.0, 0.0)
    assert ws["sets_with_logged_duration"] == 4
    out = tdee.lifting_energy([session], SPECIMEN_WEIGHT_KG)
    assert out["basis"] == "worked_set_time_from_hevy_set_log"


def test_a_warmup_set_is_work_the_thing_excluded_is_rest():
    """Deliberate: a warmup set moves a load. Only REST between sets is dropped."""
    session = {"exercises": [{"name": "Squat", "sets": [lifting_set(), {"type": "warmup", "weight_kg": 40.0, "reps": 10}]}]}
    assert tdee.worked_set_seconds([session])["sets"] == 2


def test_a_set_with_neither_reps_nor_a_duration_contributes_nothing():
    """ADR-104: an empty set row is ABSENT work, never 40 s of fabricated work."""
    session = {"exercises": [{"name": "Squat", "sets": [{"type": "normal", "weight_kg": 60.0}]}]}
    assert tdee.worked_set_seconds([session])["seconds"] == 0.0


def test_without_a_set_log_the_lifting_duration_is_charged_at_the_stated_work_fraction():
    """A Hevy outage costs precision, never correctness — and the branch names itself.

    12,600 s x 0.25 = 3,150 s -> 6 x 142.88 x (3150/3600) = 750 kcal. Still 4x below the
    retired 3,000, and nothing about it is silent.
    """
    out = tdee.exercise_energy([strava_lift_day("2026-09-01")], SPECIMEN_WEIGHT_KG)
    assert out["kcal"] == 750.0
    assert out["lifting"]["basis"] == "lifting_duration_x0.25_no_set_log"
    assert "lifting_duration_x0.25_no_set_log" in out["basis"]


def test_cardio_is_still_charged_by_duration_exactly_as_before():
    """Cardio was never the bug. A walk/run/ride's logged duration IS moving time.

    3,600 s at 142.88 kg -> 6 x 142.88 x 1.0 = 857 kcal, identical to the retired form.
    """
    walk = strava_walk_day("2026-09-02", 3600)
    legacy = [{"date": "2026-09-02", "total_moving_time_seconds": 3600}]
    assert tdee.exercise_energy([walk], SPECIMEN_WEIGHT_KG)["kcal"] == tdee.exercise_energy(legacy, SPECIMEN_WEIGHT_KG)["kcal"] == 857.0
    assert tdee.exercise_energy([walk], SPECIMEN_WEIGHT_KG)["basis"] == "duration_proxy_6_kcal_per_kg_hour"


def test_a_kilojoule_reading_still_wins_over_the_proxy():
    """The #2310 measured-kJ branch is untouched: 900 kJ day, fully covered -> 900 kcal."""
    row = {
        "date": "2026-09-02",
        "total_moving_time_seconds": 3600,
        "total_kilojoules": 900,
        "kilojoules_moving_time_seconds": 3600,
    }
    out = tdee.exercise_energy([row], SPECIMEN_WEIGHT_KG)
    assert (out["kcal"], out["basis"]) == (900.0, "measured_kilojoules")


def test_a_legacy_row_with_no_activity_breakdown_is_named_not_silently_split():
    """Pre-2026-05 rows carry no `activities`, so they cannot be split. Say so."""
    out = tdee.exercise_energy([{"date": "2026-09-01", "total_moving_time_seconds": 7200}], SPECIMEN_WEIGHT_KG)
    assert out["unsplit_legacy_days"] == 1
    assert out["proxy_seconds"] == 7200.0


# ══════════════════════════════════════════════════════════════════════════════
# 2. The 13-day specimen replay
# ══════════════════════════════════════════════════════════════════════════════
#
# The reconstructed 7-day exercise window: 3 lifting sessions of 3.5 h (the issue's own
# session) + 4 walking days of 11,837 s. Under the retired treatment that totals the
# published 20,276 kcal; that equality is asserted FIRST, so the post-fix number below is
# a replay of the specimen rather than a fresh construction that happens to look better.

WALK_SECONDS = 11837
SPECIMEN_LIFT_DATES = ("2026-09-01", "2026-09-03", "2026-09-05")
SPECIMEN_WALK_DATES = ("2026-09-02", "2026-09-04", "2026-09-06", "2026-09-07")


def specimen_window():
    rows = [strava_lift_day(d) for d in SPECIMEN_LIFT_DATES]
    rows += [strava_walk_day(d, WALK_SECONDS) for d in SPECIMEN_WALK_DATES]
    hevy = [hevy_session() for _ in SPECIMEN_LIFT_DATES]
    return rows, hevy


def test_the_specimen_window_replays_the_published_tdee_exactly():
    """Faithfulness check. Retired treatment on this window == the issue's own payload."""
    rows, _ = specimen_window()
    legacy = [{"date": r["date"], "total_moving_time_seconds": r["total_moving_time_seconds"]} for r in rows]
    old = tdee.exercise_energy(legacy, SPECIMEN_WEIGHT_KG)
    assert abs(old["kcal"] - PUBLISHED_EXERCISE_KCAL_7D) <= 2, old["kcal"]
    assert BMR_FROM_ISSUE + round(old["kcal"] / 7) == PUBLISHED_TDEE


def test_the_specimen_replays_to_a_defensible_tdee_under_the_fixed_method():
    """THE ACCEPTANCE. Same 13-day specimen, fixed method -> 3,854 kcal, not 5,059.

    Lifting worked time 3 x 20 x 40 s = 2,400 s; walking 47,348 s unchanged.
    6 x 142.88 x (49,748/3600) = 11,847 kcal over 7 days -> 1,692 kcal/day.
    TDEE = 2,162 BMR + 1,692 = 3,854 — inside the red-team's 3,300-4,000 band, and
    ~1,200 kcal/day below the number the reader was shown.
    """
    rows, hevy = specimen_window()
    new = tdee.exercise_energy(rows, SPECIMEN_WEIGHT_KG, hevy)
    replayed = BMR_FROM_ISSUE + round(new["kcal"] / 7)
    assert replayed == 3854
    assert DEFENSIBLE_TDEE_LO <= replayed <= DEFENSIBLE_TDEE_HI
    assert replayed < PUBLISHED_TDEE - 1000


def test_the_weight_trend_back_solve_is_offered_as_a_second_named_method():
    """Box 3. 11.7 lb over 13 days at intake 1,533 -> 1,533 + 6.3 x 3500/7 = 4,683.

    Named, and named as short-window: at 13 days the 3,500-kcal-per-lb constant is
    pricing water and glycogen as fat, which is why this back-solve lands ABOVE the
    red-team band. The second method's disagreement with the first is the product here —
    it is what the impossibility check below consumes.
    """
    out = tdee.tdee_from_trend(1533, SPECIMEN_TREND_LB_WK, days=13)
    assert out["method"] == "weight_trend_back_solve_3500_kcal_per_lb"
    assert out["tdee"] == 4683
    assert out["basis"] == "short_window_water_weight_inflates_this"
    assert out["inputs"]["tissue_kcal_per_day"] == 3150.0
    # and a 14-day-or-longer window drops the short-window caveat
    assert tdee.tdee_from_trend(1533, -2.0, days=28)["basis"] == "measured_trend"


def test_a_weight_gain_back_solves_below_intake():
    """Sign discipline: gaining 1 lb/wk on 3,000 kcal means maintenance is 2,500."""
    assert tdee.tdee_from_trend(3000, 1.0, days=28)["tdee"] == 2500


def test_the_back_solve_refuses_to_invent_a_number_from_absent_inputs():
    assert tdee.tdee_from_trend(None, -1.0) is None
    assert tdee.tdee_from_trend(2000, None) is None


# ══════════════════════════════════════════════════════════════════════════════
# 3. The impossibility check — and its must-fail control
# ══════════════════════════════════════════════════════════════════════════════


def test_the_specimen_deficit_is_refused_as_published():
    """The 69.8% label. 3,529 of a 5,059 TDEE is beyond anything publishable."""
    v = tdee.implied_deficit_vs_trend(PUBLISHED_TDEE, SPECIMEN_INTAKE, SPECIMEN_TREND_LB_WK, 13)
    assert v["publish"] is False
    assert v["basis"].startswith("refused: deficit_exceeds_50pct_of_tdee")
    # both numbers ride on the verdict — never a silent refusal
    assert v["implied_deficit_kcal_per_day"] == PUBLISHED_DEFICIT
    assert v["deficit_fraction_of_tdee"] == 0.698
    assert v["method"] == "implied_deficit_vs_measured_weight_trend"


def test_the_disagreement_clause_refuses_with_both_numbers_named():
    """A model deficit of 1,100 against a trend implying 200, over 14 measured days.

    tolerance = max(400, 0.40 x 1,100) = 440; gap = 900 > 440 -> refused, and the basis
    string carries 1100, 200, the gap and the tolerance so a reader can check the call.
    """
    v = tdee.implied_deficit_vs_trend(2900, 1800, -0.4, 14)
    assert v["publish"] is False
    assert v["basis"].startswith("refused: model_and_trend_disagree")
    assert v["implied_deficit_kcal_per_day"] == 1100
    assert v["trend_implied_deficit_kcal_per_day"] == 200
    assert (v["gap_kcal_per_day"], v["tolerance_kcal_per_day"]) == (900, 440)
    for fragment in ("1100", "200", "900", "440", "14 days"):
        assert fragment in v["basis"], v["basis"]


def test_the_must_fail_control_numbers_that_agree_are_published():
    """THE CONTROL. Without this, a check that refused everything would look correct.

    2,900 TDEE, 2,400 intake -> 500 kcal/day; -1.0 lb/wk -> 500 kcal/day. Gap 0.
    """
    v = tdee.implied_deficit_vs_trend(2900, 2400, -1.0, 14)
    assert v["publish"] is True
    assert v["basis"].startswith("agrees_with_measured_weight_trend")
    assert (v["implied_deficit_kcal_per_day"], v["trend_implied_deficit_kcal_per_day"]) == (500, 500)


def test_a_gap_inside_the_stated_tolerance_still_publishes():
    """The tolerance is real, not decorative: 300 kcal/day apart, floor is 400."""
    v = tdee.implied_deficit_vs_trend(2900, 2400, -1.6, 14)  # trend implies 800
    assert v["gap_kcal_per_day"] == 300 and v["tolerance_kcal_per_day"] == 400
    assert v["publish"] is True


def test_an_absent_or_short_trend_says_unverified_rather_than_agreed():
    """ "No data" may never read as "the check passed" (ADR-104)."""
    v = tdee.implied_deficit_vs_trend(2900, 2400, None, 0)
    assert v["publish"] is True and v["basis"] == "published_unverified_no_measured_weight_trend"
    short = tdee.implied_deficit_vs_trend(2900, 2400, -1.0, 3)
    assert short["publish"] is True and "below_7d_minimum" in short["basis"]


def test_the_check_refuses_when_there_is_no_tdee_or_intake_to_judge():
    v = tdee.implied_deficit_vs_trend(None, 2400, -1.0, 14)
    assert v["publish"] is False and v["basis"] == "refused: no_tdee_or_intake_to_check"


def test_the_stated_tolerance_is_a_named_constant_not_a_literal():
    assert tdee.TREND_TOLERANCE_FRACTION == 0.40
    assert tdee.TREND_TOLERANCE_FLOOR_KCAL == 400.0
    assert tdee.MAX_PUBLISHABLE_DEFICIT_FRACTION == 0.50
    assert tdee.MIN_TREND_DAYS == 7


def test_the_endpoint_trend_reads_dated_weigh_ins_and_refuses_a_single_point():
    rows = [{"date": "2026-09-01", "weight_lbs": 320.0}, {"date": "2026-09-14", "weight_lbs": 308.3}]
    trend, span = tdee.weight_trend_lb_per_wk(rows)
    assert span == 13 and trend == SPECIMEN_TREND_LB_WK
    assert tdee.weight_trend_lb_per_wk(rows[:1]) == (None, 0)
    # a body-composition-only row carries no weight and is ABSENT, never 0 lb
    assert tdee.weight_trend_lb_per_wk([rows[0], {"date": "2026-09-14", "fat_ratio": 38.0}]) == (None, 0)


# ══════════════════════════════════════════════════════════════════════════════
# 4. The target payload refuses rather than publishing
# ══════════════════════════════════════════════════════════════════════════════


def _budget(**kw):
    base = dict(weight_lbs=315.0, height_inches=74, age_years=37, exercise_kcal=11847, window_days=7)
    base.update(kw)
    return tdee.energy_budget(**base)


def test_a_refused_check_withholds_the_target_and_says_why():
    """Box 4. Not a smaller number, not the same number with a warning — None + a reason."""
    refusal = tdee.implied_deficit_vs_trend(PUBLISHED_TDEE, SPECIMEN_INTAKE, SPECIMEN_TREND_LB_WK, 13)
    out = _budget(trend_check=refusal)
    assert out["target"] is None
    assert out["target_published"] is False
    assert out["target_basis"].startswith("refused: ")
    assert out["trend_check"]["implied_deficit_kcal_per_day"] == PUBLISHED_DEFICIT
    # TDEE itself still publishes — it is a maintenance estimate, not a target (ADR-152).
    assert out["tdee"] > 0


def test_an_agreeing_check_publishes_the_target_under_the_new_method_name():
    out = _budget(trend_check=tdee.implied_deficit_vs_trend(2900, 2400, -1.0, 14))
    assert out["target"] == out["tdee"] - out["deficit"]
    assert out["target_published"] is True
    assert out["method"] == "mifflin_bmr_plus_worked_set_exercise"


def test_an_unchecked_target_names_the_method_in_its_basis():
    out = _budget()
    assert out["target_basis"] == "mifflin_bmr_plus_worked_set_exercise_minus_deficit"


# ══════════════════════════════════════════════════════════════════════════════
# 5. The method-name sweep — no consumer keeps the old number's old label
# ══════════════════════════════════════════════════════════════════════════════

_REPO = pathlib.Path(__file__).resolve().parents[1]
_SWEEP_DIRS = ("lambdas", "mcp", "site", "scripts", "deploy", "cdk", "tests")
_SWEEP_SUFFIXES = (".py", ".js", ".mjs", ".json", ".html", ".css")
# The one sanctioned mention: tdee.py's own `RETIRED_METHOD` constant and the docstring
# that explains the rename. Both are ABOUT the retired label, neither publishes it.
_ALLOWED = {"lambdas/health/tdee.py", "tests/test_tdee_worked_set_3931_behavior.py"}


def test_no_consumer_still_carries_the_retired_method_string():
    """#3931: the rename is the point. A surface still emitting
    `mifflin_bmr_plus_measured_7d_exercise` is emitting the old NUMBER under a label the
    platform no longer means — the exact failure mode the acceptance criterion names.
    """
    pattern = re.compile(re.escape(tdee.RETIRED_METHOD))
    offenders = []
    for d in _SWEEP_DIRS:
        root = _REPO / d
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in _SWEEP_SUFFIXES:
                continue
            rel = path.relative_to(_REPO).as_posix()
            if rel in _ALLOWED:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if pattern.search(text):
                offenders.append(rel)
    assert not offenders, f"the retired TDEE method label still ships from: {sorted(offenders)}"


def test_the_live_method_constant_is_the_new_name():
    assert tdee.METHOD == "mifflin_bmr_plus_worked_set_exercise"
    assert tdee.RETIRED_METHOD == "mifflin_bmr_plus_measured_7d_exercise"
    assert tdee.METHOD != tdee.RETIRED_METHOD


def test_every_exercise_energy_payload_names_its_method():
    """ADR-105: the number is checkable without reading the source."""
    out = tdee.exercise_energy([], SPECIMEN_WEIGHT_KG)
    assert out["method"] == tdee.METHOD
    assert out["basis"] == "no_activity_in_window"
