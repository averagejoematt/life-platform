"""
constants.py — Runtime constants shared across life-platform Lambdas.

GENERATED FILE. Do not edit by hand. Source of truth is config/user_goals.json.
Regenerate with: python3 deploy/sync_constants_from_config.py --apply

Ships inside every function bundle (ADR-058, #781). Changes reach the fleet
via `cdk deploy --all` or `bash deploy/deploy_fleet.sh`.
"""

from datetime import date

EXPERIMENT_START_DATE = "2026-09-06"
EXPERIMENT_START_DOW = "Sunday"
EXPERIMENT_TZ = "America/Los_Angeles"

EXPERIMENT_PHASE_CURRENT = "experiment"
EXPERIMENT_PHASE_PRIOR = "pilot"

EXPERIMENT_BASELINE_WEIGHT_LBS = 327.34
EXPERIMENT_BASELINE_WEIGHT_KG = 148.478

EXPERIMENT_GOAL_WEIGHT_LBS = 185

# The plan's protein floor (targets.nutrition in the plan root; the figure experiment.plan_facts
# derives). The plan states ONE protein line — a floor. Every surface that names a protein
# target/floor reads this, never PROFILE#v1 and never a literal (#4540; guard:
# tests/test_protein_contract.py). The calorie target is NOT generated here: it is resolved by
# health.calorie_target from the charter's nutrition.calories block (#5095; guard:
# tests/test_calorie_target_one_resolver_5095.py).
PLAN_DAILY_PROTEIN_MIN_G = 170


def day_n(today_iso: str) -> int:
    """1-indexed Day-N relative to EXPERIMENT_START_DATE. Returns 0 for pre-genesis dates."""
    d = date.fromisoformat(today_iso)
    start = date.fromisoformat(EXPERIMENT_START_DATE)
    delta = (d - start).days
    return delta + 1 if delta >= 0 else 0
