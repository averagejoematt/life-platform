"""Coach stance / stage-playbook loader + rung resolver (CC-09).

Each operational coach has a hand-authored ``config/coaches/<coach>_stance.json``
stage ladder: per band of the experiment (weight, or logging-consistency for
nutrition) → read_of_him / cares_most / cares_less_right_now / plan /
graduation_gate / watches. The *ladder* is stable config; the *current rung*
resolves from real data at render/batch time (no inference).

Consumed by the coach pages (CC-01) and the My Team view (CC-10). Shape +
wellbeing guardrails enforced by tests/test_coach_stance.py.
"""

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

# Canonical computable signals a stage `watches` entry may reference. Keeping
# this list tight is what stops a stance from "watching" something the platform
# can't actually measure (enforced by tests/test_coach_stance.py).
KNOWN_SIGNALS = {
    # body / nutrition
    "weight_lbs",
    "body_fat_pct",
    "muscle_volume",
    "total_calories_kcal",
    "total_protein_g",
    "logging_consistency",
    "deficit_sustainability",
    "metabolic_adaptation",
    # glucose
    "blood_glucose_avg",
    "blood_glucose_std_dev",
    "time_in_range_pct",
    "glucose_meal_response",
    # recovery / cardio
    "hrv",
    "resting_heart_rate",
    "recovery_score",
    "hr_recovery",
    # sleep
    "sleep_duration_hours",
    "sleep_score",
    "sleep_consistency",
    "deep_pct",
    "rem_pct",
    # bed_temp_f retired — ADR-118, #489 (Eight Sleep temp pipeline dead)
    # training
    "steps",
    "moving_time_seconds",
    "zone2_minutes",
    "acwr",
    "session_frequency",
    "load_progression",
    "joint_discomfort_flags",
    # mind
    "som_avg_valence",
    "mood_variability",
    "journal_sentiment",
    # labs
    "labs_panel",
    "biomarker_trend",
    "supplement_adherence",
    # explorer / stats
    "correlation_strength",
    "sample_size_n",
}

_cache: dict[str, Any] = {}  # coach_id -> {"data": dict, "ts": float}
_TTL_S = 300


def _local_path(coach_id):
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "config", "coaches", f"{coach_id}_stance.json")


def load_stance(coach_id, s3_client=None, bucket=None, force_refresh=False):
    """Load one coach's stance config. Prefers S3, falls back to the local repo
    file (tests / offline). Warm-container cached ~5 min. Returns {} on failure."""
    now = time.time()
    hit = _cache.get(coach_id)
    if not force_refresh and hit and (now - hit["ts"]) < _TTL_S:
        return hit["data"]

    data = None
    key = f"config/coaches/{coach_id}_stance.json"
    if s3_client and bucket:
        try:
            resp = s3_client.get_object(Bucket=bucket, Key=key)
            data = json.loads(resp["Body"].read().decode("utf-8"))
        except Exception as e:
            logger.warning("[coach_stance] S3 read failed for %s (%s) — trying local", coach_id, e)

    if data is None:
        try:
            with open(_local_path(coach_id), encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as e:
            logger.warning("[coach_stance] local read failed for %s: %s", coach_id, e)
            return hit["data"] if hit else {}

    _cache[coach_id] = {"data": data, "ts": now}
    return data


def resolve_stage(ladder, value):
    """Return the stage whose half-open band [min, max) contains ``value``
    (None bound = unbounded). Returns None if value is None or no band matches."""
    if value is None:
        return None
    for stage in ladder or []:
        e = stage.get("entry", {})
        lo, hi = e.get("min"), e.get("max")
        if (lo is None or value >= lo) and (hi is None or value < hi):
            return stage
    return None


def current_stage(coach_id, value, s3_client=None, bucket=None):
    """Convenience: load a coach's stance and resolve the current rung from value."""
    stance = load_stance(coach_id, s3_client, bucket)
    return resolve_stage(stance.get("stage_ladder", []), value)
