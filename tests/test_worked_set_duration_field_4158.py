"""tests/test_worked_set_duration_field_4158.py — the reader must read the writer's key
(#4158).

**The bug, live-replayed:** ``lambdas/health/tdee.py``'s ``worked_set_seconds`` read
``duration_seconds`` only. No stored Hevy set row has ever carried that key — the
ingestion writer (``training.hevy_common._normalize_set``) stores it under
``duration_sec`` — so ``sets_with_logged_duration`` read 0 on every day replayed
2026-09-08 -> 09-22, and Hevy-logged cardio (cycling/treadmill/walking — a timed set
with distance and no ``reps``) earned ZERO exercise energy while every unlogged rep set
was still charged the flat 40 s assumption. This file pins two things:

1. The writer and both readers of the stored field (``health.tdee.worked_set_seconds``,
   ``training.training_load.hevy_session_load``) derive the key from ONE shared
   constant (``common.hevy_schema.SET_DURATION_FIELD``) — never a re-typed literal.
2. A Hevy cycling block that carries ONLY the real stored key contributes its energy.
   Because the fixture below carries `duration_sec` and nothing else, a reader
   "put back" on reading `duration_seconds` alone (the pre-fix bug) sees no duration on
   this set and this file goes red — that IS the mutation control; no separate
   hand-rolled reimplementation is needed to prove it.
"""

from __future__ import annotations

import ast
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from common import met_energy  # noqa: E402
from common.hevy_schema import SET_DURATION_FIELD  # noqa: E402
from health import tdee  # noqa: E402

# Pre-merge lane (#2258): the failure this file pins IS the class of bug a PR's own
# diff should catch before merge, same reasoning as test_tdee_worked_set_3931_behavior.py.
pytestmark = pytest.mark.premerge


@pytest.fixture(autouse=True)
def _stub_aws(monkeypatch):
    """Stub the boto3 clients `training.hevy_common` creates at module load time."""
    import types

    fake_boto3 = types.ModuleType("boto3")

    class _FakeTable:
        def put_item(self, **kw):
            pass

        def get_item(self, **kw):
            return {}

    class _FakeDDBResource:
        def Table(self, name):
            return _FakeTable()

    fake_boto3.client = lambda name, region_name=None: object()
    fake_boto3.resource = lambda name, region_name=None: _FakeDDBResource()
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)


# ══════════════════════════════════════════════════════════════════════════════
# 1. The constant IS "duration_sec" — the writer's actual stored key
# ══════════════════════════════════════════════════════════════════════════════


def test_the_shared_constant_is_the_writers_actual_stored_key():
    assert SET_DURATION_FIELD == "duration_sec"


def test_the_writer_stores_a_sets_measured_duration_under_the_shared_constant():
    """`training.hevy_common._normalize_set` (the schema owner) writes the OUTPUT key
    from the shared constant, not a hand-typed literal."""
    from training.hevy_common import _normalize_set

    # Raw Hevy wire payload: the API's own field name (`duration_seconds`).
    raw_set = {"index": 0, "type": "normal", "distance_meters": 15000.0, "duration_seconds": 1800}
    normalized = _normalize_set(raw_set, "kg")
    assert normalized[SET_DURATION_FIELD] == 1800
    assert "duration_seconds" not in normalized


def test_both_stored_set_duration_readers_derive_from_the_one_constant():
    """Neither reader may re-type the literal `"duration_sec"` — both import
    `common.hevy_schema.SET_DURATION_FIELD` (grep-level pin so a future edit that
    reintroduces a second spelling in either file is caught here, not downstream)."""
    tdee_src = ROOT + "/lambdas/health/tdee.py"
    training_load_src = ROOT + "/lambdas/training/training_load.py"
    with open(tdee_src, encoding="utf-8") as f:
        tdee_text = f.read()
    with open(training_load_src, encoding="utf-8") as f:
        tl_text = f.read()
    assert "from common.hevy_schema import SET_DURATION_FIELD" in tdee_text
    assert "from common.hevy_schema import SET_DURATION_FIELD" in tl_text


def test_health_tdee_still_imports_nothing_from_training():
    """The shared constant lives in `common/`, not `training/`, precisely so this holds
    (tests/test_training_load_worked_set_4075.py's own boundary,
    test_the_energy_targets_load_input_is_the_stored_tsb_not_a_recompute)."""
    tree = ast.parse(open(ROOT + "/lambdas/health/tdee.py", encoding="utf-8").read())
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not any(m and "training" in m for m in imported)


# ══════════════════════════════════════════════════════════════════════════════
# 2. The live fixture: a Hevy cycling block, `duration_sec` 1800, contributes energy
# ══════════════════════════════════════════════════════════════════════════════

CYCLING_SECONDS = 1800  # 30 minutes
WEIGHT_KG = 80.0


def _cycling_session() -> dict:
    """A Hevy-logged cardio block exactly as it is STORED: a timed set with distance
    and no `reps`, keyed by the real stored field. No `duration_seconds` key anywhere
    in this fixture — a reader that only checks that spelling sees no duration here."""
    return {
        "exercises": [
            {
                "name": "Cycling",
                "sets": [
                    {"type": "normal", "reps": None, "distance_m": 12000.0, SET_DURATION_FIELD: CYCLING_SECONDS},
                ],
            }
        ]
    }


def test_a_hevy_cycling_block_with_the_stored_duration_key_contributes_its_energy():
    """THE ACCEPTANCE (#4158). Before the fix this read `sets_with_logged_duration: 0`
    and `seconds: 0.0` for every such block — no other device recorded it, so the
    exercise term was silently zero."""
    ws = tdee.worked_set_seconds([_cycling_session()])
    assert ws["sets_with_logged_duration"] == 1
    assert ws["measured_seconds"] == float(CYCLING_SECONDS)
    assert ws["seconds"] == float(CYCLING_SECONDS)

    out = tdee.lifting_energy([_cycling_session()], WEIGHT_KG)
    # #4158 owner ruling 2026-09-25: a Hevy cardio block is charged at its MODALITY's
    # MET rate, never the lifting proxy — "Cycling" is not a walk-name fragment, so it
    # takes CARDIO_LIGHT_MET_KCAL_PER_KG_HOUR (4.0), not PROXY_KCAL_PER_KG_HOUR (6.0).
    assert out["basis"] == "worked_set_time_from_hevy_set_log_plus_light_cardio_at_4.0_met"
    assert out["kcal"] > 0
    # 4.0 kcal/kg/hour x 80 kg x (1800/3600) h = 160 kcal exactly.
    assert out["kcal"] == 160.0


def test_mutation_control_a_reader_put_back_on_duration_seconds_alone_goes_red():
    """Simulates the pre-#4158 reader inline (only `duration_seconds`, never
    `duration_sec`) against the SAME real-shape fixture. It must see nothing — proving
    the acceptance test above is actually pinned to the field name, not incidental."""

    def buggy_worked_set_seconds(hevy_workouts):
        n_logged = 0
        for w in hevy_workouts:
            for ex in w.get("exercises") or []:
                for st in ex.get("sets") or []:
                    dur = st.get("duration_seconds")  # the pre-fix bug, reintroduced here only
                    if dur is not None and dur > 0:
                        n_logged += 1
        return n_logged

    assert buggy_worked_set_seconds([_cycling_session()]) == 0
    # ...while the live (fixed) reader sees it.
    assert tdee.worked_set_seconds([_cycling_session()])["sets_with_logged_duration"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# 3. The double-count driver review found (#4168 review, same issue #4158): a Hevy
#    cardio block and an HR-bearing Strava/Whoop activity can describe the SAME
#    wall-clock minutes twice. THE 09-19 SPECIMEN: a 3,600 s Hevy Treadmill block with
#    a WHOOP walk carrying HR over 3,539 s of it.
# ══════════════════════════════════════════════════════════════════════════════

TREADMILL_SECONDS = 3600
WHOOP_COVERED_SECONDS = 3539
UNCOVERED_SECONDS = TREADMILL_SECONDS - WHOOP_COVERED_SECONDS  # 61 s


def _treadmill_workout() -> dict:
    """The 09-19 specimen's Hevy side: one timed cardio set, no other device's numbers
    baked in — the discount is computed from `covered_intervals`, not hand-subtracted
    here."""
    return {
        "start_time": "2026-09-19T18:00:00Z",
        "end_time": "2026-09-19T19:00:00Z",  # exactly TREADMILL_SECONDS wall-clock
        "exercises": [
            {
                "name": "Treadmill",
                "sets": [{"type": "normal", "reps": None, "distance_m": 4800.0, SET_DURATION_FIELD: TREADMILL_SECONDS}],
            }
        ],
    }


def _whoop_walk_activity() -> dict:
    """The 09-19 specimen's Strava/Whoop side: an HR-bearing, non-echo walk covering
    WHOOP_COVERED_SECONDS of the SAME window."""
    return {
        "sport_type": "Walk",
        "type": "Walk",
        "average_heartrate": 92.0,
        "start_date": "2026-09-19T18:00:00Z",
        "moving_time_seconds": WHOOP_COVERED_SECONDS,
        "device_name": "whoop",
    }


def test_a_hevy_cardio_block_is_discounted_by_an_overlapping_hr_activity():
    """THE FIX. `covered_intervals` (from `common.activity_overlap.hr_intervals`, the
    SAME derivation `training.training_load.hevy_session_load` (#4075) uses) subtracts
    the WHOOP-covered share of the Hevy treadmill block before it is charged."""
    intervals = tdee.hr_intervals([_whoop_walk_activity()])
    ws = tdee.worked_set_seconds([_treadmill_workout()], covered_intervals=intervals)
    assert ws["cardio_seconds"] == float(TREADMILL_SECONDS)
    assert ws["cardio_seconds_hr_covered"] == float(WHOOP_COVERED_SECONDS)
    assert ws["measured_seconds"] == float(UNCOVERED_SECONDS)

    lift = tdee.lifting_energy([_treadmill_workout()], WEIGHT_KG, covered_intervals=intervals)
    # #4158 owner ruling 2026-09-25: "Treadmill" is a walk-name fragment -> WALK_MET
    # (3.5), never PROXY_KCAL_PER_KG_HOUR (6.0, the lifting/moderate-cycling rate).
    assert lift["basis"] == "worked_set_time_from_hevy_set_log_plus_walk_pace_cardio_at_3.5_met_cardio_hr_covered_discounted"
    assert lift["kcal"] == round(met_energy.WALK_MET_KCAL_PER_KG_HOUR * WEIGHT_KG * (UNCOVERED_SECONDS / 3600.0), 0)


def test_mutation_control_ignoring_overlap_reproduces_the_double_count():
    """If a future edit drops the `covered_intervals` wiring, THIS is the number it
    would silently reproduce — proving the discounted assertion above is a real
    regression pin, not a coincidence. `covered_intervals` omitted == overlap ignored."""
    intervals = tdee.hr_intervals([_whoop_walk_activity()])
    fixed = tdee.worked_set_seconds([_treadmill_workout()], covered_intervals=intervals)
    broken = tdee.worked_set_seconds([_treadmill_workout()])  # no covered_intervals: the bug
    assert broken["cardio_seconds_hr_covered"] == 0.0
    assert broken["measured_seconds"] == float(TREADMILL_SECONDS)  # the full, double-counted block
    assert fixed["measured_seconds"] == float(UNCOVERED_SECONDS)
    assert fixed["measured_seconds"] < broken["measured_seconds"]


def test_exercise_energy_does_not_double_count_an_hr_covered_hevy_cardio_block():
    """Integration: the 09-19 shape through the FULL `exercise_energy` pipeline — proves
    `covered_intervals` is actually wired from `strava_items` into `lifting_energy`, not
    only supported by the unit function in isolation."""
    day = {
        "date": "2026-09-19",
        "total_moving_time_seconds": WHOOP_COVERED_SECONDS,
        "activities": [_whoop_walk_activity()],
    }
    out = tdee.exercise_energy([day], WEIGHT_KG, [_treadmill_workout()])
    assert out["lifting"]["cardio_seconds_hr_covered"] == float(WHOOP_COVERED_SECONDS)
    # #4178: the WHOOP walk's own seconds now take WALK_MET too (before #4178 they took
    # PROXY_KCAL_PER_KG_HOUR — #4158 review item 2's residual, closed by #4178), and the
    # Hevy side's uncovered treadmill seconds take WALK_MET as they have since #4158 —
    # so the whole hour is ONE walk at ONE rate, split only by which device saw it.
    expected_walk = met_energy.WALK_MET_KCAL_PER_KG_HOUR * WEIGHT_KG * (WHOOP_COVERED_SECONDS / 3600.0)
    expected_lift = round(met_energy.WALK_MET_KCAL_PER_KG_HOUR * WEIGHT_KG * (UNCOVERED_SECONDS / 3600.0), 0)
    assert out["lifting"]["kcal"] == expected_lift
    assert out["kcal"] == round(expected_walk + expected_lift, 0)
    assert out["kcal_by_basis"] == {"met:walk": round(expected_walk, 0) + expected_lift}
    assert out["walk_pace_seconds"] == float(WHOOP_COVERED_SECONDS)


def test_mutation_control_the_double_count_would_charge_the_full_block_a_second_time():
    """Without the discount, `lifting_energy` would charge the FULL 3,600 s of Hevy
    cardio on top of the walk's own ~3,539 s proxy charge — the double count the driver
    review found. Asserts the broken number is nearly 60x the discounted one, so the
    fixed test above cannot pass by coincidence."""
    intervals = tdee.hr_intervals([_whoop_walk_activity()])
    fixed = tdee.lifting_energy([_treadmill_workout()], WEIGHT_KG, covered_intervals=intervals)
    broken = tdee.lifting_energy([_treadmill_workout()], WEIGHT_KG)  # overlap ignored: the bug
    assert broken["kcal"] > fixed["kcal"] * 10


# ══════════════════════════════════════════════════════════════════════════════
# 4. Owner ruling 2026-09-25 (option A): uncovered Hevy cardio takes a Compendium MET
#    rate, never PROXY_KCAL_PER_KG_HOUR (the lifting/moderate-cycling proxy).
# ══════════════════════════════════════════════════════════════════════════════

OWNER_FIXTURE_WEIGHT_KG = 143.0


def _uncovered_treadmill_block(seconds: int = TREADMILL_SECONDS) -> dict:
    """A Hevy treadmill block with NO overlapping HR activity at all — the owner's own
    fixture spec (2026-09-25 review item 4)."""
    return {
        "start_time": "2026-09-19T18:00:00Z",
        "end_time": "2026-09-19T19:00:00Z",
        "exercises": [
            {
                "name": "Treadmill",
                "sets": [{"type": "normal", "reps": None, "distance_m": 4800.0, SET_DURATION_FIELD: seconds}],
            }
        ],
    }


def test_an_uncovered_treadmill_block_charges_the_walk_met_not_the_lifting_proxy():
    """THE ACCEPTANCE (owner ruling 2026-09-25, option A). A 3,600 s uncovered
    treadmill block at 143 kg charges ~3.5 kcal/kg/h (~500 kcal), NOT 6 (~858 kcal) —
    the owner's own stated fixture and expected number."""
    out = tdee.lifting_energy([_uncovered_treadmill_block()], OWNER_FIXTURE_WEIGHT_KG)
    assert out["basis"] == "worked_set_time_from_hevy_set_log_plus_walk_pace_cardio_at_3.5_met"
    # 3.5 * 143 = 500.5 -> rounds to 500 or 501 depending on rounding mode; assert the
    # EXACT arithmetic (round-half-to-even at .5) rather than a hand-typed literal.
    expected = round(met_energy.WALK_MET_KCAL_PER_KG_HOUR * OWNER_FIXTURE_WEIGHT_KG * (TREADMILL_SECONDS / 3600.0), 0)
    assert out["kcal"] == expected
    assert 495 <= out["kcal"] <= 505, out["kcal"]  # the owner's own stated ~500 kcal


def test_mutation_control_the_6_kcal_per_kg_hour_rate_reds():
    """Mutation control (owner's own instruction): reverting the walk-pace rate to
    `PROXY_KCAL_PER_KG_HOUR` (6.0, moderate cycling/lifting) must fail this fixture."""
    out = tdee.lifting_energy([_uncovered_treadmill_block()], OWNER_FIXTURE_WEIGHT_KG)
    six_kcal_per_kg_hour_result = round(tdee.PROXY_KCAL_PER_KG_HOUR * OWNER_FIXTURE_WEIGHT_KG * (TREADMILL_SECONDS / 3600.0), 0)
    assert six_kcal_per_kg_hour_result == 858.0  # 6 * 143 — the retired, too-high number
    assert out["kcal"] != six_kcal_per_kg_hour_result
    assert out["kcal"] < six_kcal_per_kg_hour_result


# ══════════════════════════════════════════════════════════════════════════════
# 5. #4178 — the Strava side of the SAME ruling. Before this, `exercise_energy`'s own
#    no-kJ proxy still charged a Strava/Whoop/Garmin walk at PROXY_KCAL_PER_KG_HOUR
#    (~6 METs) while the Hevy path above took 3.5 — one walk, two rates. The ONE
#    predicate (`met_energy.is_walk_pace`) and the ONE rate pair now serve both.
# ══════════════════════════════════════════════════════════════════════════════

STRAVA_WALK_SECONDS = 3600


def _strava_activity(sport_type: str, name: str, seconds: int, distance_m: float = 0.0, device: str = "WHOOP", hr: float = 112.0) -> dict:
    """One Strava activity as the writer stores it (`ingestion/strava_lambda.py`): a WHOOP
    walk carries no distance (0), a Garmin one carries metres; both carry average HR."""
    return {
        "sport_type": sport_type,
        "type": sport_type,
        "name": name,
        "device_name": device,
        "start_date": "2026-09-14T17:00:00Z",
        "moving_time_seconds": seconds,
        "distance_meters": distance_m,
        "average_heartrate": hr,
    }


def _strava_day(*activities: dict, date: str = "2026-09-14") -> dict:
    return {
        "date": date,
        "total_moving_time_seconds": sum(a["moving_time_seconds"] for a in activities),
        "total_kilojoules": 0,
        "activities": list(activities),
    }


def test_a_one_hour_strava_walk_at_143_kg_charges_about_500_kcal():
    """THE ACCEPTANCE (#4178). A 3,600 s Strava-logged walk at 143 kg charges 3.5 kcal/kg/h
    (~500 kcal), the SAME figure the uncovered Hevy treadmill block above charges — not the
    ~858 the 6 kcal/kg/h lifting proxy produced. Provenance names the basis."""
    day = _strava_day(_strava_activity("Walk", "Afternoon Walk", STRAVA_WALK_SECONDS))
    out = tdee.exercise_energy([day], OWNER_FIXTURE_WEIGHT_KG)
    expected = round(met_energy.WALK_MET_KCAL_PER_KG_HOUR * OWNER_FIXTURE_WEIGHT_KG * (STRAVA_WALK_SECONDS / 3600.0), 0)
    assert out["kcal"] == expected
    assert 495 <= out["kcal"] <= 505, out["kcal"]  # the owner's own ~500 kcal
    assert out["basis"] == "activity_walk_pace_at_3.5_met"
    assert out["kcal_by_basis"] == {met_energy.BASIS_MET_WALK: expected}
    assert out["walk_pace_seconds"] == float(STRAVA_WALK_SECONDS)
    assert out["proxy_seconds"] == 0.0  # nothing on the 6 kcal/kg/h proxy


def test_mutation_control_the_strava_walk_on_the_6_kcal_per_kg_hour_rate_reds():
    """Mutation control (the issue's own box): the retired rate restored on the Strava
    proxy must fail the fixture above. 6 x 143 = 858 is the number a regression prints."""
    day = _strava_day(_strava_activity("Walk", "Afternoon Walk", STRAVA_WALK_SECONDS))
    out = tdee.exercise_energy([day], OWNER_FIXTURE_WEIGHT_KG)
    six_kcal_per_kg_hour_result = round(tdee.PROXY_KCAL_PER_KG_HOUR * OWNER_FIXTURE_WEIGHT_KG * (STRAVA_WALK_SECONDS / 3600.0), 0)
    assert six_kcal_per_kg_hour_result == 858.0
    assert out["kcal"] != six_kcal_per_kg_hour_result
    assert out["kcal"] < six_kcal_per_kg_hour_result
    assert "6_kcal_per_kg_hour" not in out["basis"]


def test_one_walk_one_rate_whichever_device_logged_it():
    """The issue's outcome line, as an equality: the same hour of walking priced through
    the Hevy path (`lifting_energy`, uncovered treadmill block) and through the Strava
    path (`exercise_energy`, a WHOOP walk) is the SAME kcal, from the SAME constant."""
    hevy_side = tdee.lifting_energy([_uncovered_treadmill_block(STRAVA_WALK_SECONDS)], OWNER_FIXTURE_WEIGHT_KG)
    strava_side = tdee.exercise_energy([_strava_day(_strava_activity("Walk", "Lunch Walk", STRAVA_WALK_SECONDS))], OWNER_FIXTURE_WEIGHT_KG)
    assert hevy_side["kcal"] == strava_side["kcal"] > 0
    assert hevy_side["kcal_by_basis"] == strava_side["kcal_by_basis"] == {met_energy.BASIS_MET_WALK: hevy_side["kcal"]}


def test_strava_activities_classify_by_the_shared_pace_predicate_and_the_lifting_proxy_stays_for_lifting():
    """The three live shapes in the 2026-08..09 strava partition, plus the one that is not
    there yet: a Garmin walk WITH distance (08-10's specimen: 4,496.9 m in 3,241 s, 1.39
    m/s) reads as walk pace by `met_energy.is_walk_pace`; a WeightTraining activity stays
    on the lifting proxy (the stated 0.25 work fraction, no set log); a no-kJ Ride above
    walk pace takes the light-cardio MET. Each names itself in `kcal_by_basis`."""
    garmin_walk = _strava_activity("Walk", "Morning Walk", 3241, distance_m=4496.9, device="Garmin epix (Gen2)", hr=99.6)
    lift = _strava_activity("WeightTraining", "Foundation - Push - 3 - 8", 3600, device="Hevy", hr=None)
    ride = _strava_activity("Ride", "Evening Ride", 3600, distance_m=30000.0, device="Garmin epix (Gen2)", hr=135.0)
    out = tdee.exercise_energy([_strava_day(garmin_walk, lift, ride)], OWNER_FIXTURE_WEIGHT_KG)
    w = OWNER_FIXTURE_WEIGHT_KG
    assert out["kcal_by_basis"] == {
        met_energy.BASIS_MET_WALK: round(met_energy.WALK_MET_KCAL_PER_KG_HOUR * w * (3241 / 3600.0), 0),
        met_energy.BASIS_MET_CARDIO_LIGHT: round(met_energy.CARDIO_LIGHT_MET_KCAL_PER_KG_HOUR * w * 1.0, 0),
        tdee.BASIS_PROXY_LIFTING: round(tdee.PROXY_KCAL_PER_KG_HOUR * w * (3600 * tdee.LIFTING_WORK_FRACTION_FALLBACK / 3600.0), 0),
    }
    assert out["walk_pace_seconds"] == 3241.0 and out["light_cardio_seconds"] == 3600.0
    assert out["lifting"]["basis"] == "lifting_duration_x0.25_no_set_log"
    assert out["basis"] == "activity_walk_pace_at_3.5_met_plus_activity_light_cardio_at_4.0_met_plus_lifting_duration_x0.25_no_set_log"
    # a walk-typed activity ABOVE walk pace is not walk pace — the pace half of the predicate
    brisk = _strava_activity("Walk", "Brisk Walk", 3600, distance_m=9000.0)  # 2.5 m/s
    assert tdee.exercise_energy([_strava_day(brisk)], w)["kcal_by_basis"] == {met_energy.BASIS_MET_CARDIO_LIGHT: round(4.0 * w, 0)}


def test_the_walk_met_code_is_pinned_to_the_published_compendium_row_and_the_cardio_code_is_honestly_absent():
    """#4178 box 2. WALK_MET_CODE was verified against the journal's own supplemental table
    (Ainsworth 2011, row `17190 3.5 walking, 2.8 to 3.2 mph, level, moderate pace, firm
    surface`) and is pinned. The published table carries NO stationary-bicycling row at
    4.0 (02011 is 3.5, 02017 is 4.8), so CARDIO_LIGHT_MET_CODE stays None and the module
    says why — never a guessed code."""
    assert met_energy.WALK_MET == 3.5
    assert met_energy.WALK_MET_CODE == "17190"
    assert met_energy.WALK_MET_DESCRIPTION == "walking, 2.8 to 3.2 mph, level, moderate pace, firm surface"
    assert met_energy.CARDIO_LIGHT_MET == 4.0
    assert met_energy.CARDIO_LIGHT_MET_CODE is None
    doc = met_energy.__doc__ or ""
    for fragment in ("17190", "02011", "02017", "No stationary-bicycling row carries 4.0", "sdc1.pdf"):
        assert fragment in doc, fragment
