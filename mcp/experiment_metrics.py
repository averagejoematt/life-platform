"""mcp/experiment_metrics.py — the before/after experiment comparison's metric table (#4630 split).

Split out of mcp/tools_lifestyle.py at its module-size ceiling (#1665) when #4630 routed the
steps row through the registry's truth facet: the table and its field extractor are pure
data + one pure helper, re-exported by tools_lifestyle so every caller keeps its import.
"""

from common.metric_truth import resolved_source_id

# ── Experiment metrics ──

_EXPERIMENT_METRICS = [
    # Sleep
    ("whoop", "sleep_score", "Sleep Score", True),  # normalized from sleep_quality_score
    ("whoop", "sleep_efficiency_pct", "Sleep Efficiency %", True),  # normalized from sleep_efficiency_percentage
    ("whoop", "deep_pct", "Deep Sleep %", True),  # normalized from slow_wave_sleep_hours
    ("whoop", "rem_pct", "REM Sleep %", True),  # normalized from rem_sleep_hours
    ("eightsleep", "time_to_sleep_min", "Sleep Onset Latency", False),  # writer: eightsleep_lambda.py (#2221)
    # Recovery
    ("whoop", "recovery_score", "Whoop Recovery", True),
    ("whoop", "hrv", "HRV (rMSSD)", True),  # writer: whoop_lambda.py stores `hrv` (#2221)
    ("whoop", "resting_heart_rate", "Resting HR", False),
    # Stress & Energy
    ("garmin", "avg_stress", "Garmin Stress", False),  # writer: garmin_lambda.py (#2221)
    ("garmin", "body_battery_high", "Body Battery Peak", True),
    # Body
    ("withings", "weight_lbs", "Weight (lbs)", None),  # direction depends on goal
    # Nutrition
    ("macrofactor", "calories_kcal", "Calories", None),  # writer: macrofactor_lambda.py (#2221)
    ("macrofactor", "protein_g", "Protein (g)", None),
    # Movement
    # #4630: steps resolve per day (registry METRIC_TRUTH facet) — a resolved pseudo-source.
    (resolved_source_id("steps"), "steps", "Steps", True),
    # Glucose (if available) — writer: health_auto_export_lambda.py stores blood_glucose_* (#2221)
    ("apple_health", "blood_glucose_avg", "Mean Glucose", False),
    ("apple_health", "blood_glucose_time_in_range_pct", "CGM Time in Range %", True),
]


def _extract_metric(item, field_path):
    """Extract a numeric value from a DynamoDB item, handling nested dicts."""
    val = item
    for part in field_path.split("."):
        if isinstance(val, dict):
            val = val.get(part)
        else:
            return None
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
