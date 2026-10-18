"""The Apple Watch's daily-metric map for the HAE webhook (#4970) — a cohesive sibling.

`health_auto_export_lambda.py` is a baselined large module (#1665 size guard); the watch's
own map entries, their dedup classes, the zero-is-absent rule and the wrist-temperature
unit conversion live here and are spliced into the webhook's `_METRIC_DEFS` and field sets
(the #1654 facade + sibling shape). Field semantics, privacy tiers and absence rules:
docs/SCHEMA.md "Apple Watch daily metrics (#4970)"; tiers: lambdas/privacy/field_tiers.py.

Lanes kept OUT on purpose: Apple sleep stages (`sleep_*_apple`) are #4971's, and ECG
results / heart-rate notifications / AFib burden / medications are #4972's owner-only
rhythm channel.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    from common.platform_logger import get_logger

    logger = get_logger("health-auto-export")
except ImportError:
    logger = logging.getLogger("health-auto-export")
    logger.setLevel(logging.INFO)

WATCH_METRIC_DEFS: list[tuple[set[str], dict[str, Any]]] = [
    # ── #4970: the Apple Watch's own daily metrics (Ultra 4, from 2026-10-16) ─────────
    # Title-Case names verified against the HAE automation config
    # (datadrops/hae_config, datadrops/logs/automations.json); the snake_case twins
    # follow HAE's JSON-v2 convention and are re-verified by #4969's raw-capture diff.
    # Tier 2 (Apple-device readings only), so a vendor mirror (Whoop, Oura) writing the
    # same HealthKit type can never land in an *_apple field — capture-all per source,
    # never a winner picked across vendors. `hae_summarize` is the HAE automation
    # setting each field expects (docs/SCHEMA.md "Apple Watch daily metrics (#4970)"):
    # every new field is deduped by reading timestamp (WATCH_SUM_DEDUP_FIELDS /
    # WATCH_AVG_DEDUP_FIELDS below), so raw samples (summarize OFF) are the contract —
    # a summarized daily point is also correct alone, but a mid-day switch between the
    # two double-counts the additive ones. Overnight sleep stages are #4971's lane and
    # ECG / notifications / medications / AFib burden are #4972's — NOT mapped here.
    (
        {"Apple Sleeping Wrist Temperature", "apple_sleeping_wrist_temperature", "sleeping_wrist_temperature"},
        {"field": "wrist_temp_sleep_c_apple", "agg": "avg", "tier": 2, "hae_summarize": False},
    ),
    (
        {"Breathing Disturbances", "breathing_disturbances"},
        {"field": "breathing_disturbances_apple", "agg": "avg", "tier": 2, "hae_summarize": False},
    ),
    ({"Cardio Recovery", "cardio_recovery"}, {"field": "cardio_recovery_bpm_apple", "agg": "avg", "tier": 2, "hae_summarize": False}),
    ({"Time in Daylight", "time_in_daylight"}, {"field": "daylight_minutes_apple", "agg": "sum", "tier": 2, "hae_summarize": False}),
    (
        {"Environmental Audio Exposure", "environmental_audio_exposure"},
        {"field": "environmental_audio_db_apple", "agg": "avg", "tier": 2, "hae_summarize": False},
    ),
    ({"Apple Exercise Time", "apple_exercise_time"}, {"field": "exercise_minutes_apple", "agg": "sum", "tier": 2, "hae_summarize": False}),
    ({"Apple Stand Time", "apple_stand_time"}, {"field": "stand_minutes_apple", "agg": "sum", "tier": 2, "hae_summarize": False}),
    ({"Apple Stand Hour", "apple_stand_hour"}, {"field": "stand_hours_apple", "agg": "sum", "tier": 2, "hae_summarize": False}),
]

# The watch's averaged daily metrics take the SAME timestamp-keyed mean as gait (#4628):
# the export is incremental, so a payload-local mean of HRV (193 samples over 10-17/18)
# would otherwise overwrite the day with whichever sync arrived last. The pre-existing
# watch-capable averages (HRV/RHR/RR/SpO2/walking HR/VO2/steadiness) join the new ones.
WATCH_AVG_DEDUP_FIELDS = frozenset(
    {
        "hrv_sdnn_apple",
        "resting_heart_rate_apple",
        "respiratory_rate_apple",
        "spo2_pct_apple",
        "walking_heart_rate_avg",
        "vo2max",
        "walking_steadiness_pct",
        "wrist_temp_sleep_c_apple",
        "breathing_disturbances_apple",
        "cardio_recovery_bpm_apple",
        "environmental_audio_db_apple",
    }
)

# The watch's additive daily metrics are the SUM over the unique-timestamp map (the
# water/caffeine path) — never a payload-local sum, never a max across syncs.
WATCH_SUM_DEDUP_FIELDS = frozenset({"daylight_minutes_apple", "exercise_minutes_apple", "stand_minutes_apple", "stand_hours_apple"})

# ADR-104: a 0 on a physiological reading is a failed measurement, not a value (the
# Withings SpO2 precedent, #2782) — dropped as ABSENT, never averaged in as a zero.
# Additive fields and breathing disturbances are NOT here: 0 exercise minutes or 0
# disturbances on a worn day is a real reading.
ZERO_IS_ABSENT_FIELDS = frozenset(
    {
        "hrv_sdnn_apple",
        "resting_heart_rate_apple",
        "respiratory_rate_apple",
        "spo2_pct_apple",
        "walking_heart_rate_avg",
        "vo2max",
        "wrist_temp_sleep_c_apple",
        "cardio_recovery_bpm_apple",
    }
)

_WRIST = "wrist_temp_sleep_c_apple"


def _f_to_c(value: float) -> float:
    return round((value - 32) * 5 / 9, 2)


def wrist_temp_to_celsius(fields: dict[str, Any], day_stamps: dict[str, Any] | None, units: str | None, date: str) -> None:
    """Store the sleeping wrist temperature in Celsius, in place (day value + its `_rd_` map).

    HAE reports the phone's display unit. degF is converted; an unknown unit is kept as
    Celsius and logged, never silently rescaled.
    """
    if fields.get(_WRIST) is None:
        return
    u = (units or "").lower().replace("°", "").strip()
    if u in ("degf", "f", "fahrenheit"):
        fields[_WRIST] = _f_to_c(float(fields[_WRIST]))
        if day_stamps and _WRIST in day_stamps:
            day_stamps[_WRIST] = {ts: _f_to_c(float(q)) for ts, q in day_stamps[_WRIST].items()}
    elif u and u not in ("degc", "c", "celsius"):
        logger.warning(f"[HAE] unexpected wrist-temperature units {u!r} for {date}; assuming Celsius")
