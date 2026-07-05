"""
ingestion_validator.py — DATA-2: Shared ingestion validation layer.

Validates incoming data items BEFORE writing to DynamoDB.
Invalid records are logged and written to S3 `validation-errors/` prefix
for audit. Critical validation failures skip DDB write entirely.

USAGE:

    from ingestion_validator import validate_item, validate_and_write

    result = validate_item("whoop", item, date_str="2026-03-08")
    if result.should_skip_ddb:
        logger.error("Skipping DDB write", errors=result.errors)
        result.archive_to_s3(s3_client, bucket)
        return
    if result.warnings:
        logger.warning("Validation warnings", warnings=result.warnings)

    table.put_item(Item=item)  # or safe_put_item()

VALIDATION RULES:

    Each source has:
      - required_fields: list of fields that MUST be present (critical if missing)
      - typed_fields: {field: type} — warns if value fails type check
      - range_checks: {field: (min, max)} — warns if value out of expected range
      - critical_range_checks: {field: (min, max)} — SKIPS write if out of range
      - at_least_one_of: list of fields — warns if ALL are absent

    Severity levels:
      CRITICAL — skip DDB write, archive to S3, log error
      WARNING  — write proceeds, issue logged and archived

SOURCES COVERED (20):
  whoop, garmin, apple_health, macrofactor, macrofactor_workouts, strava,
  eightsleep, withings, habitify, notion, todoist, weather, supplements,
  computed_metrics, character_sheet, day_grade, habit_scores,
  computed_insights, google_calendar, adaptive_mode
  (20 total: 13 ingestion + 6 compute + 1 calendar)

v1.0.0 — 2026-03-08 (DATA-2)
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal as _Decimal

logger = logging.getLogger(__name__)
REGION = os.environ.get("AWS_REGION", "us-west-2")

# ── Validation result ──────────────────────────────────────────────────────────


@dataclass
class ValidationResult:
    source: str
    date_str: str
    errors: list[str] = field(default_factory=list)  # CRITICAL — skip write
    warnings: list[str] = field(default_factory=list)  # non-blocking

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    @property
    def should_skip_ddb(self) -> bool:
        return len(self.errors) > 0

    def archive_to_s3(self, s3_client, bucket: str, item: dict):
        """Write the rejected item to S3 validation-errors/ prefix for audit."""
        try:
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            key = f"validation-errors/{self.source}/{self.date_str}/{ts}.json"
            payload = {
                "source": self.source,
                "date": self.date_str,
                "archived_at": datetime.now(timezone.utc).isoformat(),
                "errors": self.errors,
                "warnings": self.warnings,
                "item_keys": list(item.keys()),
                "item": {k: str(v)[:200] for k, v in item.items()},
            }
            s3_client.put_object(
                Bucket=bucket,
                Key=key,
                Body=json.dumps(payload, default=str, indent=2),
                ContentType="application/json",
            )
            logger.info(f"[validator] Archived validation failure to s3://{bucket}/{key}")
        except Exception as e:
            logger.warning(f"[validator] Failed to archive validation error (non-fatal): {e}")


# ── Per-source validation schemas ─────────────────────────────────────────────

# Format:
#   required_fields:        list[str] — CRITICAL if missing
#   typed_fields:           {str: type} — WARNING if wrong type
#   range_checks:           {str: (min, max)} — WARNING if out of range
#   critical_range_checks:  {str: (min, max)} — CRITICAL if out of range (skip write)
#   at_least_one_of:        list[str] — WARNING if ALL absent

_SCHEMAS: dict[str, dict] = {
    # #480/A-7: field names matched to what the writer ACTUALLY stores —
    # the old sleep_score checks could never fire (written name is
    # sleep_quality_score, since ever).
    "whoop": {
        "required_fields": ["pk", "sk", "date"],
        "typed_fields": {
            "recovery_score": (int, float),
            "sleep_quality_score": (int, float),
            "hrv": (int, float),
            "resting_heart_rate": (int, float),
            "sleep_duration_hours": (int, float),
        },
        "range_checks": {
            "recovery_score": (0, 100),
            "sleep_quality_score": (0, 100),
            "hrv": (0, 300),
            "resting_heart_rate": (20, 200),
            "sleep_duration_hours": (0, 24),
            "sleep_efficiency_percentage": (0, 100),
        },
        "critical_range_checks": {
            "recovery_score": (-1, 101),  # allow float edge cases
            "sleep_quality_score": (-1, 101),
        },
        "at_least_one_of": ["recovery_score", "sleep_quality_score", "hrv"],
    },
    # #480/A-7: whoop per-workout sub-records (sk DATE#{d}#WORKOUT#{id}) carry
    # strain/HR/zones, not the night fields — they were tripping the whoop
    # at_least_one_of warning 1,500+ times per fortnight. Their own mini-schema.
    "whoop_workout": {
        "required_fields": ["pk", "sk", "date"],
        "typed_fields": {
            "strain": (int, float),
            "average_heart_rate": (int, float),
            "max_heart_rate": (int, float),
        },
        "range_checks": {
            "strain": (0, 21),
            "average_heart_rate": (20, 220),
            "max_heart_rate": (20, 230),
        },
        "at_least_one_of": ["strain", "average_heart_rate", "kilojoule", "sport_name"],
    },
    "garmin": {
        "required_fields": ["pk", "sk", "date"],
        "typed_fields": {
            "steps": (int, float),
            "resting_heart_rate": (int, float),
            "stress_level_avg": (int, float),
            "body_battery_highest": (int, float),
        },
        "range_checks": {
            "steps": (0, 100_000),
            "resting_heart_rate": (20, 200),
            "stress_level_avg": (0, 100),
            "body_battery_highest": (0, 100),
            "sleep_duration_seconds": (0, 86_400),
        },
        "at_least_one_of": ["steps", "resting_heart_rate", "body_battery_highest"],
    },
    "apple_health": {
        "required_fields": ["pk", "sk", "date"],
        "typed_fields": {
            "steps": (int, float),
            "active_energy_kcal": (int, float),
            "blood_glucose_avg": (int, float),
        },
        "range_checks": {
            "steps": (0, 100_000),
            "active_energy_kcal": (0, 5_000),
            "blood_glucose_avg": (50, 400),
            "blood_glucose_min": (30, 400),
            "blood_glucose_max": (50, 600),
            "blood_glucose_time_in_range_pct": (0, 100),
            "water_intake_ml": (0, 20_000),
            "walking_speed_mph": (0, 10),
            "walking_asymmetry_pct": (0, 100),
            # #483/X-3: the HAE webhook writes BP via update_item — give it ranges so
            # validate_fields can flag implausible cuff readings before the merge.
            "bp_systolic": (50, 300),
            "bp_diastolic": (30, 200),
            "blood_pressure_systolic": (50, 300),
            "blood_pressure_diastolic": (30, 200),
        },
        "critical_range_checks": {
            "blood_glucose_avg": (30, 600),
        },
        "at_least_one_of": ["steps", "active_energy_kcal", "blood_glucose_avg"],
    },
    "macrofactor": {
        "required_fields": ["pk", "sk", "date", "entries_count"],
        "typed_fields": {
            "total_calories_kcal": (int, float),
            "total_protein_g": (int, float),
            "total_fat_g": (int, float),
            "total_carbs_g": (int, float),
            "entries_count": (int, float),
        },
        "range_checks": {
            "total_calories_kcal": (0, 10_000),
            "total_protein_g": (0, 1_000),
            "total_fat_g": (0, 1_000),
            "total_carbs_g": (0, 2_000),
            "total_fiber_g": (0, 200),
        },
        "critical_range_checks": {},
        "at_least_one_of": ["total_calories_kcal", "total_protein_g"],
    },
    "macrofactor_workouts": {
        "required_fields": ["pk", "sk", "date", "workouts_count"],
        "typed_fields": {
            "workouts_count": (int, float),
            "total_sets": (int, float),
            "total_volume_lbs": (int, float),
        },
        "range_checks": {
            "workouts_count": (0, 20),
            "total_sets": (0, 500),
            "total_volume_lbs": (0, 200_000),
        },
        "at_least_one_of": ["workouts"],
    },
    "strava": {
        "required_fields": ["pk", "sk", "date", "activity_count"],
        "typed_fields": {
            "activity_count": (int, float),
            "total_moving_time_seconds": (int, float),
        },
        "range_checks": {
            "activity_count": (0, 20),
            "total_moving_time_seconds": (0, 86_400),
            "total_distance_miles": (0, 500),
            "total_zone2_seconds": (0, 86_400),
        },
        "at_least_one_of": ["activities"],
    },
    "eightsleep": {
        "required_fields": ["pk", "sk", "date"],
        "typed_fields": {
            "sleep_efficiency_pct": (int, float),
            "sleep_duration_hours": (int, float),
        },
        "range_checks": {
            "sleep_efficiency_pct": (0, 100),
            "sleep_duration_hours": (0, 24),
            "hr_avg": (20, 200),  # #480/A-7: written name (was heart_rate_avg — never fired)
        },
        "at_least_one_of": ["sleep_efficiency_pct", "sleep_duration_hours"],  # bed_temp_f retired — ADR-118, #489
    },
    "withings": {
        "required_fields": ["pk", "sk", "date"],
        "typed_fields": {
            "weight_lbs": (int, float),
            "bmi": (int, float),
        },
        "range_checks": {
            "weight_lbs": (50, 700),
            "bmi": (10, 80),
            "fat_mass_pct": (0, 80),
            "muscle_mass_pct": (0, 100),
        },
        "critical_range_checks": {
            "weight_lbs": (50, 700),
        },
        "at_least_one_of": ["weight_lbs", "bmi"],
    },
    "habitify": {
        "required_fields": ["pk", "sk", "date"],
        "typed_fields": {
            "total_completed": (int, float),
            "total_possible": (int, float),
        },
        "range_checks": {
            "total_completed": (0, 200),
            "total_possible": (0, 200),
        },
        "at_least_one_of": ["habits", "total_completed"],
    },
    "notion": {
        "required_fields": ["pk", "sk", "date"],
        "typed_fields": {},
        "range_checks": {},
        "at_least_one_of": ["raw_text", "enriched_mood", "enriched_energy"],
    },
    # #480/A-7: written names are completed_count/active_count/overdue_count
    # (the old tasks_completed/tasks_added matched nothing).
    "todoist": {
        "required_fields": ["pk", "sk", "date"],
        "typed_fields": {
            "completed_count": (int, float),
            "active_count": (int, float),
        },
        "range_checks": {
            "completed_count": (0, 500),
            "active_count": (0, 500),
            "overdue_count": (0, 500),
        },
        "at_least_one_of": ["completed_count", "active_count", "overdue_count"],
    },
    "weather": {
        "required_fields": ["pk", "sk", "date"],
        "typed_fields": {
            "temp_high_f": (int, float),
            "temp_low_f": (int, float),
            "temp_avg_f": (int, float),
        },
        "range_checks": {
            "temp_high_f": (-100, 150),
            "temp_low_f": (-100, 150),
            "temp_avg_f": (-100, 150),
            "precipitation_mm": (0, 2_000),
            "uv_index_max": (0, 20),
        },
        "at_least_one_of": ["temp_high_f", "temp_avg_f"],
    },
    # #480/E-5: both writers (habitify bridge + MCP log_supplement) store a
    # `supplements` list — the old batches/total_supplements_logged spec
    # matched no writer ever.
    "supplements": {
        "required_fields": ["pk", "sk", "date"],
        "typed_fields": {},
        "range_checks": {},
        "at_least_one_of": ["supplements"],
    },
    "computed_metrics": {
        "required_fields": ["pk", "sk", "date", "computed_at"],
        "typed_fields": {
            "day_grade_score": (int, float),
            "readiness_score": (int, float),
            "recovery_pct": (int, float),
            "hrv_ms": (int, float),
            "rhr_bpm": (int, float),
            "protein_g_avg": (int, float),
        },
        "range_checks": {
            "day_grade_score": (0, 100),
            "readiness_score": (0, 100),
            # Phase-3 canonical vitals — impossible values warn (CTL/ATL ≥0 already
            # clamped at compute; these catch a bad recovery/HRV slipping through).
            "recovery_pct": (0, 100),
            "hrv_ms": (0, 400),
            "rhr_bpm": (20, 150),
            "protein_g_avg": (0, 400),
        },
        "at_least_one_of": ["day_grade_score", "component_scores"],
    },
    "character_sheet": {
        "required_fields": ["pk", "sk", "date", "character_level"],
        "typed_fields": {
            "character_level": (int, float),
            "character_score": (int, float),
        },
        "range_checks": {
            "character_level": (1, 100),
            "character_score": (0, 100),
        },
        "at_least_one_of": ["character_level", "character_tier"],
    },
    "day_grade": {
        "required_fields": ["pk", "sk", "date", "total_score", "letter_grade"],
        "typed_fields": {
            "total_score": (int, float),
        },
        "range_checks": {
            "total_score": (0, 100),
        },
        "at_least_one_of": ["total_score"],
    },
    "habit_scores": {
        "required_fields": ["pk", "sk", "date"],
        "typed_fields": {
            "tier0_done": (int, float),
            "tier0_total": (int, float),
        },
        "range_checks": {
            "tier0_done": (0, 50),
            "tier0_total": (0, 50),
            "composite_score": (0, 100),
        },
        "at_least_one_of": ["tier0_done", "composite_score"],
    },
    "google_calendar": {  # R8-ST1 — added v3.7.22
        "required_fields": ["pk", "sk", "date"],
        "typed_fields": {
            "event_count": (int, float),
            "meeting_minutes": (int, float),
        },
        "range_checks": {
            "event_count": (0, 100),
            "meeting_minutes": (0, 1440),  # max 24h of meetings
            "focus_block_count": (0, 20),  # null is valid (not computable) — skip range check if absent
        },
        "critical_range_checks": {},
        "at_least_one_of": ["event_count", "events"],
    },
    "adaptive_mode": {  # Feature #50 — added v3.7.25
        "required_fields": ["pk", "sk", "date", "engagement_score", "brief_mode", "computed_at"],
        "typed_fields": {
            "engagement_score": (int, float),
        },
        "range_checks": {
            "engagement_score": (0, 100),
        },
        "critical_range_checks": {},
        "at_least_one_of": ["brief_mode", "engagement_score"],
    },
    "computed_insights": {  # IC-2 — added v3.7.25
        "required_fields": ["pk", "sk", "date", "computed_at"],
        "typed_fields": {},
        "range_checks": {},
        "critical_range_checks": {},
        "at_least_one_of": ["momentum_signal", "ai_context_block"],
    },
}

# Default schema for any source not explicitly listed — minimal checks only
_DEFAULT_SCHEMA = {
    "required_fields": ["pk", "sk", "date"],
    "typed_fields": {},
    "range_checks": {},
    "critical_range_checks": {},
    "at_least_one_of": [],
}


# ── Core validation function ───────────────────────────────────────────────────


def validate_item(source: str, item: dict, date_str: str = "") -> ValidationResult:
    """Validate a DynamoDB item for the given source against its schema.

    Args:
        source:   Source name (e.g. "whoop", "strava", "macrofactor")
        item:     The item dict about to be written to DynamoDB
        date_str: Date string for logging context (YYYY-MM-DD)

    Returns:
        ValidationResult with errors (critical) and warnings (non-blocking).
        Check result.should_skip_ddb before calling table.put_item().

    Example:
        result = validate_item("whoop", item, date_str=date_str)
        if result.should_skip_ddb:
            result.archive_to_s3(s3_client, bucket, item)
            return
        table.put_item(Item=item)
    """
    # #480/A-7: whoop per-workout sub-records get their own schema — validating
    # them against the night schema flooded ~100 false warnings/day.
    if source == "whoop" and "#WORKOUT#" in str(item.get("sk", "")):
        source = "whoop_workout"
    schema = _SCHEMAS.get(source, _DEFAULT_SCHEMA)
    result = ValidationResult(source=source, date_str=date_str)

    # 1. Required fields (CRITICAL if missing)
    for req_field in schema.get("required_fields", []):
        if req_field not in item or item[req_field] is None:
            result.errors.append(f"Required field missing: '{req_field}'")

    # 2. Type checks (WARNING — not critical, Decimal/int mismatches are common)
    # _Decimal imported at module level — do not re-import inside this loop.
    for fld, expected_types in schema.get("typed_fields", {}).items():
        if fld not in item or item[fld] is None:
            continue
        # Allow Decimal (DynamoDB) as valid for numeric types
        actual = item[fld]
        if isinstance(expected_types, tuple):
            valid_types = expected_types + (_Decimal,)
        else:
            valid_types = (expected_types, _Decimal)
        if not isinstance(actual, valid_types):
            result.warnings.append(f"Type mismatch '{fld}': expected {expected_types}, got {type(actual).__name__} ({actual!r:.40})")

    # 3. Range checks (WARNING)
    for fld, (lo, hi) in schema.get("range_checks", {}).items():
        if fld not in item or item[fld] is None:
            continue
        try:
            val = float(item[fld])
            if not (lo <= val <= hi):
                result.warnings.append(f"Value out of expected range '{fld}': {val} (expected {lo}–{hi})")
        except (TypeError, ValueError):
            result.warnings.append(f"Cannot parse numeric value for range check '{fld}': {item[fld]!r:.40}")

    # 4. Critical range checks (CRITICAL — skip write on violation)
    for fld, (lo, hi) in schema.get("critical_range_checks", {}).items():
        if fld not in item or item[fld] is None:
            continue
        try:
            val = float(item[fld])
            if not (lo <= val <= hi):
                result.errors.append(f"CRITICAL: value '{fld}' = {val} outside hard bounds ({lo}–{hi})")
        except (TypeError, ValueError):
            result.errors.append(f"CRITICAL: cannot parse '{fld}' for hard-bound check: {item[fld]!r:.40}")

    # 5. At-least-one-of check (WARNING)
    at_least_one = schema.get("at_least_one_of", [])
    if at_least_one:
        present = [f for f in at_least_one if item.get(f) is not None]
        if not present:
            result.warnings.append(f"All optional fields absent — expected at least one of: {at_least_one}")

    # 6. Date format sanity check (WARNING)
    date_in_item = item.get("date", date_str or "")
    if date_in_item:
        try:
            datetime.strptime(str(date_in_item), "%Y-%m-%d")
        except ValueError:
            result.warnings.append(f"Date field format unexpected: '{date_in_item}'")

    # 7. Schema version check (WARNING if missing — DATA-1 prerequisite)
    if "schema_version" not in item:
        result.warnings.append("schema_version field missing — not yet migrated to DATA-1")

    # Log summary
    if result.errors:
        logger.error(
            "[validator] CRITICAL validation failures for %s/%s: %s",
            source,
            date_str,
            result.errors,
        )
    elif result.warnings:
        logger.warning(
            "[validator] Validation warnings for %s/%s: %s",
            source,
            date_str,
            result.warnings,
        )

    return result


def validate_fields(source: str, fields: dict, date_str: str = "") -> ValidationResult:
    """Validate a PARTIAL field dict headed for an ``update_item`` MERGE (not a full-item
    put). Reuses the source's typed_fields / range_checks / critical_range_checks but SKIPS
    the whole-item checks (required_fields, at_least_one_of, schema_version, date) that a
    merge fragment cannot satisfy.

    This is the validation entry point for the Apple Health / HAE webhook path (#483/X-3),
    which writes CGM/BP/steps/water via update_item and previously merged them unvalidated.
    Check ``result.errors`` before merging: a critical-range violation (e.g. an implausible
    glucose average) should drop rather than corrupt the day's aggregate.

    Args:
        source:   Source name whose schema supplies the ranges (e.g. "apple_health").
        fields:   The partial {field: value} dict about to be merged.
        date_str: Date string for logging context (YYYY-MM-DD).

    Returns:
        ValidationResult — ``errors`` (critical, drop) and ``warnings`` (log, keep).
    """
    schema = _SCHEMAS.get(source, _DEFAULT_SCHEMA)
    result = ValidationResult(source=source, date_str=date_str)

    # Type checks (WARNING) — same policy as validate_item, allowing Decimal.
    for fld, expected_types in schema.get("typed_fields", {}).items():
        if fields.get(fld) is None:
            continue
        valid_types = (expected_types if isinstance(expected_types, tuple) else (expected_types,)) + (_Decimal,)
        if not isinstance(fields[fld], valid_types):
            result.warnings.append(
                f"Type mismatch '{fld}': expected {expected_types}, got {type(fields[fld]).__name__} ({fields[fld]!r:.40})"
            )

    # Range checks (WARNING).
    for fld, (lo, hi) in schema.get("range_checks", {}).items():
        if fields.get(fld) is None:
            continue
        try:
            val = float(fields[fld])
            if not (lo <= val <= hi):
                result.warnings.append(f"Value out of expected range '{fld}': {val} (expected {lo}–{hi})")
        except (TypeError, ValueError):
            result.warnings.append(f"Cannot parse numeric value for range check '{fld}': {fields[fld]!r:.40}")

    # Critical range checks (CRITICAL — caller should drop the offending field/merge).
    for fld, (lo, hi) in schema.get("critical_range_checks", {}).items():
        if fields.get(fld) is None:
            continue
        try:
            val = float(fields[fld])
            if not (lo <= val <= hi):
                result.errors.append(f"CRITICAL: value '{fld}' = {val} outside hard bounds ({lo}–{hi})")
        except (TypeError, ValueError):
            result.errors.append(f"CRITICAL: cannot parse '{fld}' for hard-bound check: {fields[fld]!r:.40}")

    if result.errors:
        logger.error("[validator] CRITICAL field-merge failures for %s/%s: %s", source, date_str, result.errors)
    elif result.warnings:
        logger.warning("[validator] Field-merge warnings for %s/%s: %s", source, date_str, result.warnings)

    return result


def validate_and_write(table, s3_client, bucket: str, source: str, item: dict, date_str: str = "", use_safe_put: bool = False) -> bool:
    """Convenience wrapper: validate → archive on failure → put_item on success.

    Returns True if item was written, False if skipped.

    Args:
        table:        boto3 DynamoDB Table resource
        s3_client:    boto3 S3 client
        bucket:       S3 bucket name (for archiving failures)
        source:       Source name for schema lookup
        item:         Item dict to validate and write
        date_str:     Date string for logging/archiving
        use_safe_put: If True, use safe_put_item (item_size_guard) instead of put_item

    Example (replaces bare table.put_item calls):
        written = validate_and_write(table, s3_client, bucket, "whoop", item, date_str)
        if not written:
            return  # critical validation failure, already logged + archived
    """
    result = validate_item(source, item, date_str)

    if result.should_skip_ddb:
        result.archive_to_s3(s3_client, item=item, bucket=bucket)
        return False

    if result.warnings:
        # Non-blocking — log but proceed
        pass

    if use_safe_put:
        try:
            from item_size_guard import safe_put_item

            safe_put_item(table, item, source=source, date_str=date_str)
        except ImportError:
            table.put_item(Item=item)
    else:
        table.put_item(Item=item)

    return True


def list_supported_sources() -> list[str]:
    """Return list of sources with explicit validation schemas."""
    return list(_SCHEMAS.keys())
