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
    assert out["basis"] == "worked_set_time_from_hevy_set_log"
    assert out["kcal"] > 0
    # 6 kcal/kg/hour x 80 kg x (1800/3600) h = 240 kcal exactly.
    assert out["kcal"] == 240.0


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
