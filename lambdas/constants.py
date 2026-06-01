"""
constants.py — Runtime constants shared across life-platform Lambdas.

GENERATED FILE. Do not edit by hand. Source of truth is config/user_goals.json.
Regenerate with: python3 deploy/sync_constants_from_config.py --apply

Part of the shared Lambda layer (ADR-058). Changes require layer rebuild
(`bash deploy/build_layer.sh`) before deploying dependent functions.
"""

from datetime import date

EXPERIMENT_START_DATE = "2026-05-30"
EXPERIMENT_START_DOW = "Saturday"
EXPERIMENT_TZ = "America/Los_Angeles"

EXPERIMENT_PHASE_CURRENT = "experiment"
EXPERIMENT_PHASE_PRIOR = "pilot"

EXPERIMENT_BASELINE_WEIGHT_LBS = 304.3
EXPERIMENT_BASELINE_WEIGHT_KG = 138.028

EXPERIMENT_GOAL_WEIGHT_LBS = 185


def day_n(today_iso: str) -> int:
    """1-indexed Day-N relative to EXPERIMENT_START_DATE. Returns 0 for pre-genesis dates."""
    d = date.fromisoformat(today_iso)
    start = date.fromisoformat(EXPERIMENT_START_DATE)
    delta = (d - start).days
    return delta + 1 if delta >= 0 else 0
