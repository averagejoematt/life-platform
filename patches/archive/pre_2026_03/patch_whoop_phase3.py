"""
patch_whoop_phase3.py — Enhance Whoop ingestion Lambda (Phase 3 API gap closure)

Adds:
  1. Sleep start/end timestamps from main sleep record
  2. Nap data: nap_count, nap_duration_hours from nap=True records

Run from ~/Documents/Claude/life-platform/
Requires whoop_lambda.py extracted first (see below).
"""

import os
import sys


def extract_whoop_source():
    """Extract lambda_function.py from whoop_lambda.zip if needed."""
    if os.path.exists("whoop_lambda.py"):
        print("whoop_lambda.py already exists, using it.")
        return

    if not os.path.exists("whoop_lambda.zip"):
        print("ERROR: whoop_lambda.zip not found. Cannot extract source.")
        sys.exit(1)

    import zipfile
    with zipfile.ZipFile("whoop_lambda.zip", "r") as zf:
        # Extract lambda_function.py and rename to whoop_lambda.py for local editing
        with zf.open("lambda_function.py") as src:
            with open("whoop_lambda.py", "wb") as dst:
                dst.write(src.read())
    print("Extracted whoop_lambda.zip → whoop_lambda.py")


def patch():
    extract_whoop_source()

    with open("whoop_lambda.py", "r") as f:
        code = f.read()

    # ── 1. Add sleep start/end timestamps to extract_sleep_fields ─────────
    # Insert after sleep_performance/quality extraction, before return
    old_sleep_return = '''    perf = score.get("sleep_performance_percentage")
    if perf is not None:
        _set_dec(fields, "sleep_performance_percentage", perf, log)
        _set_dec(fields, "sleep_quality_score", perf, log)  # backward-compat alias

    return fields'''

    new_sleep_return = '''    perf = score.get("sleep_performance_percentage")
    if perf is not None:
        _set_dec(fields, "sleep_performance_percentage", perf, log)
        _set_dec(fields, "sleep_quality_score", perf, log)  # backward-compat alias

    # ── Sleep timing (Phase 3 — previously missing) ──
    sleep_start = main_sleep.get("start")
    sleep_end = main_sleep.get("end")
    if sleep_start:
        fields["sleep_start"] = sleep_start
        log(f"[INFO] sleep_start: {sleep_start}")
    if sleep_end:
        fields["sleep_end"] = sleep_end
        log(f"[INFO] sleep_end: {sleep_end}")

    # ── Nap data (Phase 3 — previously filtered out) ──
    naps = [r for r in records if r.get("nap", False)]
    if naps:
        fields["nap_count"] = len(naps)
        log(f"[INFO] nap_count: {len(naps)}")
        total_nap_ms = 0
        for nap in naps:
            nap_score = nap.get("score") or {}
            nap_stage = nap_score.get("stage_summary") or {}
            in_bed = nap_stage.get("total_in_bed_time_milli", 0)
            awake = nap_stage.get("total_awake_time_milli", 0)
            total_nap_ms += (in_bed - awake)
        if total_nap_ms > 0:
            nap_hours = round(total_nap_ms / 3_600_000, 2)
            _set_dec(fields, "nap_duration_hours", nap_hours, log)

    return fields'''

    if old_sleep_return not in code:
        raise RuntimeError("Could not find extract_sleep_fields return block")
    code = code.replace(old_sleep_return, new_sleep_return)

    # ── 2. Add new fields to ALL_DAILY_FIELDS for summary output ──────────
    old_all_fields = '''    ALL_DAILY_FIELDS = [
        # recovery
        "recovery_score", "hrv", "resting_heart_rate",
        "spo2_percentage", "skin_temp_celsius",
        # sleep
        "sleep_duration_hours", "rem_sleep_hours", "slow_wave_sleep_hours",
        "light_sleep_hours", "time_awake_hours", "disturbance_count",
        "respiratory_rate", "sleep_efficiency_percentage",
        "sleep_consistency_percentage", "sleep_performance_percentage",
        "sleep_quality_score",
        # cycle
        "strain", "kilojoule", "average_heart_rate", "max_heart_rate",
    ]'''

    new_all_fields = '''    ALL_DAILY_FIELDS = [
        # recovery
        "recovery_score", "hrv", "resting_heart_rate",
        "spo2_percentage", "skin_temp_celsius",
        # sleep
        "sleep_duration_hours", "rem_sleep_hours", "slow_wave_sleep_hours",
        "light_sleep_hours", "time_awake_hours", "disturbance_count",
        "respiratory_rate", "sleep_efficiency_percentage",
        "sleep_consistency_percentage", "sleep_performance_percentage",
        "sleep_quality_score",
        # sleep timing + naps (Phase 3)
        "nap_count", "nap_duration_hours",
        # cycle
        "strain", "kilojoule", "average_heart_rate", "max_heart_rate",
    ]'''

    if old_all_fields not in code:
        raise RuntimeError("Could not find ALL_DAILY_FIELDS")
    code = code.replace(old_all_fields, new_all_fields)

    # ── 3. Handle string fields (sleep_start/end) in summary builder ──────
    # The summary builder assumes all fields are numeric. We need to add
    # sleep_start and sleep_end as string fields.
    old_summary_builder = '''    summary = {}
    for key in ALL_DAILY_FIELDS:
        val = normalized.get(key)
        if val is None:
            summary[key] = None
        elif isinstance(val, int):
            summary[key] = val
        else:
            summary[key] = float(val)
    summary["workout_count"] = len(workout_records)
    return summary'''

    new_summary_builder = '''    summary = {}
    for key in ALL_DAILY_FIELDS:
        val = normalized.get(key)
        if val is None:
            summary[key] = None
        elif isinstance(val, int):
            summary[key] = val
        elif isinstance(val, str):
            summary[key] = val
        else:
            summary[key] = float(val)
    # String fields not in ALL_DAILY_FIELDS
    for str_key in ("sleep_start", "sleep_end"):
        if str_key in normalized:
            summary[str_key] = normalized[str_key]
    summary["workout_count"] = len(workout_records)
    return summary'''

    if old_summary_builder not in code:
        raise RuntimeError("Could not find summary builder")
    code = code.replace(old_summary_builder, new_summary_builder)

    # ── 4. Update sleep docstring ─────────────────────────────────────────
    old_sleep_doc = '''    """
    Sleep fields written:
      sleep_duration_hours, sleep_quality_score (alias for sleep_performance_percentage),
      rem_sleep_hours, slow_wave_sleep_hours, light_sleep_hours, time_awake_hours,
      disturbance_count, respiratory_rate, sleep_efficiency_percentage,
      sleep_consistency_percentage, sleep_performance_percentage
    """'''

    new_sleep_doc = '''    """
    Sleep fields written:
      sleep_duration_hours, sleep_quality_score (alias for sleep_performance_percentage),
      rem_sleep_hours, slow_wave_sleep_hours, light_sleep_hours, time_awake_hours,
      disturbance_count, respiratory_rate, sleep_efficiency_percentage,
      sleep_consistency_percentage, sleep_performance_percentage,
      sleep_start, sleep_end (ISO timestamps, Phase 3),
      nap_count, nap_duration_hours (from nap=True records, Phase 3)
    """'''

    if old_sleep_doc not in code:
        raise RuntimeError("Could not find sleep docstring")
    code = code.replace(old_sleep_doc, new_sleep_doc)

    with open("whoop_lambda.py", "w") as f:
        f.write(code)

    print(f"✅ Patched whoop_lambda.py")
    print("   - Added sleep_start, sleep_end timestamps")
    print("   - Added nap_count, nap_duration_hours from nap records")
    print("   - Updated ALL_DAILY_FIELDS and summary builder")
    print(f"\nNext: run deploy_whoop_phase3.sh to push to Lambda")


if __name__ == "__main__":
    patch()
