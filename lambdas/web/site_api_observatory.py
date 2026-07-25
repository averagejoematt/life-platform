"""
lambdas/web/site_api_observatory.py — observatory page endpoint FACADE.

Extracted from lambdas/web/site_api_lambda.py (P1.1 Phase B step 2, 2026-05-26).
These serve /api/{nutrition,training,physical,mind}_overview plus supporting
endpoints (frequent meals, meal glucose, strength benchmarks, food delivery,
strength deep-dive, journal analysis, benchmark trends, meal responses, workouts).

#1654 slice 3 (god-module breakup): the handler LOGIC was split, by concern, into
cohesive sibling modules — logic lives there, the routed entrypoints stay HERE as
thin delegators so the router bindings, `handler.__module__ == "web.site_api_observatory"`,
and the test monkeypatch surface are all unchanged:

  web/site_api_nutrition.py — nutrition_overview, deficit_sustainability (+ the
      TDEE/deficit helpers _resolve_mf_tdee / _mifflin_tdee / _latest_weight_lbs /
      _recovery_deficit_overlay)
  web/site_api_meals.py     — protein_sources, frequent_meals, meal_glucose,
      food_delivery_overview, meal_responses
  web/site_api_training.py  — training_overview, strength_benchmarks,
      strength_deep_dive, benchmark_trends, workouts (+ muscle-volume helpers)
  web/site_api_physical.py  — weekly_physical_summary, physical_overview
      (+ _physical_cadences / DEXA_RECHECK_DAYS)
  web/site_api_mind.py      — journal_analysis, mind_overview

Each delegator hands its own globals() to the split handler as `_g`; the handler
reads the injectable/monkeypatched state (table / _query_source / _experiment_date /
EXPERIMENT_START) back via `_g["<name>"]`. The split modules do NOT import this
facade, so there is no import cycle. Tests that patch `obs.table` / `obs._query_source`
/ `obs.EXPERIMENT_START` / `obs._experiment_date` and then call `obs.handle_*` keep
working; tests that import `obs._recovery_deficit_overlay` / `_RDO_MIN_OVERLAP_DAYS`
/ `_mifflin_tdee` / `_resolve_mf_tdee` / `_physical_cadences` / `DEXA_RECHECK_DAYS`
read them through the re-exports below.
"""

# ── Split logic modules — the handler bodies live here; delegated to at call time. ──
from web import (
    site_api_meals as _meals,
    site_api_mind as _mind,
    site_api_nutrition as _nutrition,
    site_api_physical as _physical,
    site_api_training as _training,
)

# ── Monkeypatch/injection surface — kept on the facade so `monkeypatch.setattr(obs, …)`
# still lands here and the delegators can hand these to the split handlers via `_g`.
from web.site_api_common import (
    EXPERIMENT_START,
    _experiment_date,
    _query_source,
    table,
)

# ── Re-exports for tests that import these helpers/constants FROM this module
# (test_recovery_deficit_overlay_388, test_tdee_deficit_chain_484, test_physical_cadence_1119).
from web.site_api_nutrition import (  # noqa: F401 — re-export surface
    _RDO_MIN_OVERLAP_DAYS,
    _mifflin_tdee,
    _recovery_deficit_overlay,
    _resolve_mf_tdee,
)
from web.site_api_physical import (  # noqa: F401 — re-export surface
    DEXA_RECHECK_DAYS,
    _physical_cadences,
)

# These names have no direct in-file reference of their own — they are the facade's
# monkeypatch/hand-off surface: the split handlers read them via `_g` (`_g["<name>"]`,
# where `_g` is a delegator's globals()), and tests read/patch them on this module.
# Referenced here so the linter counts them as used.
__facade_state__ = (table, _query_source, _experiment_date, EXPERIMENT_START)


# ── Thin routed delegators — identical name/signature/__module__ to the pre-split
# handlers; each hands its own globals() to the split handler as `_g`. ──────────────
def handle_nutrition_overview() -> dict:
    """GET /api/nutrition_overview — delegated to web.site_api_nutrition."""
    return _nutrition.nutrition_overview(_g=globals())


def handle_deficit_sustainability() -> dict:
    """GET /api/deficit_sustainability — delegated to web.site_api_nutrition."""
    return _nutrition.deficit_sustainability(_g=globals())


def handle_protein_sources() -> dict:
    """GET /api/protein_sources — delegated to web.site_api_meals."""
    return _meals.protein_sources(_g=globals())


def handle_frequent_meals() -> dict:
    """GET /api/frequent_meals — delegated to web.site_api_meals."""
    return _meals.frequent_meals(_g=globals())


def handle_meal_glucose() -> dict:
    """GET /api/meal_glucose — delegated to web.site_api_meals."""
    return _meals.meal_glucose(_g=globals())


def handle_food_delivery_overview() -> dict:
    """GET /api/food_delivery_overview — delegated to web.site_api_meals."""
    return _meals.food_delivery_overview(_g=globals())


def handle_meal_responses() -> dict:
    """GET /api/meal_responses — delegated to web.site_api_meals."""
    return _meals.meal_responses(_g=globals())


def handle_training_overview() -> dict:
    """GET /api/training_overview — delegated to web.site_api_training."""
    return _training.training_overview(_g=globals())


def handle_strength_benchmarks() -> dict:
    """GET /api/strength_benchmarks — delegated to web.site_api_training."""
    return _training.strength_benchmarks(_g=globals())


def handle_strength_deep_dive() -> dict:
    """GET /api/strength_deep_dive — delegated to web.site_api_training."""
    return _training.strength_deep_dive(_g=globals())


def handle_benchmark_trends() -> dict:
    """GET /api/benchmark_trends — delegated to web.site_api_training."""
    return _training.benchmark_trends(_g=globals())


def handle_workouts() -> dict:
    """GET /api/workouts — delegated to web.site_api_training."""
    return _training.workouts(_g=globals())


def handle_weekly_physical_summary() -> dict:
    """GET /api/weekly_physical_summary — delegated to web.site_api_physical."""
    return _physical.weekly_physical_summary(_g=globals())


def handle_physical_overview() -> dict:
    """GET /api/physical_overview — delegated to web.site_api_physical."""
    return _physical.physical_overview(_g=globals())


def handle_journal_analysis() -> dict:
    """GET /api/journal_analysis — delegated to web.site_api_mind."""
    return _mind.journal_analysis(_g=globals())


def handle_mind_overview() -> dict:
    """GET /api/mind_overview — delegated to web.site_api_mind."""
    return _mind.mind_overview(_g=globals())
