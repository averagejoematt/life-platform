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
    # The WHOOP walk's own proxy charge is untouched (still PROXY_KCAL_PER_KG_HOUR — that
    # is `exercise_energy`'s residual, #4158 review item 2, not changed by this PR). The
    # Hevy side's uncovered treadmill seconds take WALK_MET, not the lifting proxy.
    expected_proxy = tdee.PROXY_KCAL_PER_KG_HOUR * WEIGHT_KG * (WHOOP_COVERED_SECONDS / 3600.0)
    expected_lift = round(met_energy.WALK_MET_KCAL_PER_KG_HOUR * WEIGHT_KG * (UNCOVERED_SECONDS / 3600.0), 0)
    assert out["lifting"]["kcal"] == expected_lift
    assert out["kcal"] == round(expected_proxy + expected_lift, 0)


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
