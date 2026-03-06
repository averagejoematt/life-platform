"""
patch_cgm_optimal.py — Add blood_glucose_time_in_optimal_pct to health_auto_export_lambda.py

Derived Metrics Phase 1c: Attia optimal range (70-120 mg/dL), stricter than standard 70-180.
Adds one counter + one field to the process_blood_glucose function.
"""

import re

LAMBDA_FILE = "health_auto_export_lambda.py"


def patch():
    with open(LAMBDA_FILE, "r") as f:
        code = f.read()

    # ── Patch 1: Add in_optimal counter alongside existing counters ──
    old_counters = """\
        in_range = sum(1 for v in values if 70 <= v <= 180)
        below_70 = sum(1 for v in values if v < 70)
        above_140 = sum(1 for v in values if v > 140)"""

    new_counters = """\
        in_range = sum(1 for v in values if 70 <= v <= 180)
        in_optimal = sum(1 for v in values if 70 <= v <= 120)
        below_70 = sum(1 for v in values if v < 70)
        above_140 = sum(1 for v in values if v > 140)"""

    if "in_optimal" in code:
        print("Already patched (in_optimal found). Skipping.")
        return

    if old_counters not in code:
        raise ValueError("Could not find counter block to patch")

    code = code.replace(old_counters, new_counters)

    # ── Patch 2: Add field to daily_agg dict ──
    old_field = """\
            "blood_glucose_time_in_range_pct": round(in_range / n * 100, 1),"""

    new_field = """\
            "blood_glucose_time_in_range_pct": round(in_range / n * 100, 1),
            "blood_glucose_time_in_optimal_pct": round(in_optimal / n * 100, 1),"""

    if old_field not in code:
        raise ValueError("Could not find time_in_range_pct field to patch")

    code = code.replace(old_field, new_field)

    # ── Patch 3: Update docstring ──
    old_doc = """\
  blood_glucose_time_in_range_pct (70-180 mg/dL),"""

    new_doc = """\
  blood_glucose_time_in_range_pct (70-180 mg/dL),
  blood_glucose_time_in_optimal_pct (70-120 mg/dL, Attia optimal),"""

    if old_doc in code:
        code = code.replace(old_doc, new_doc)
    else:
        print("Warning: docstring patch target not found (non-critical)")

    with open(LAMBDA_FILE, "w") as f:
        f.write(code)

    print(f"✅ Patched {LAMBDA_FILE} with blood_glucose_time_in_optimal_pct")


if __name__ == "__main__":
    patch()
