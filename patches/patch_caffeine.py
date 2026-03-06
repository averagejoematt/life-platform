#!/usr/bin/env python3
"""
Patcher: Add caffeine_mg to Health Auto Export webhook
- Adds Dietary Caffeine to METRIC_MAP (Tier 1, sum)
- Apple Health caffeine SOT via water/caffeine tracking app
"""

import os

if os.path.exists("health_auto_export_lambda.py"):
    LAMBDA_FILE = "health_auto_export_lambda.py"
else:
    LAMBDA_FILE = "lambda_function.py"

with open(LAMBDA_FILE, "r") as f:
    code = f.read()

# Add caffeine to Tier 1 metrics, right after water intake
code = code.replace(
    '''    ({"Dietary Water", "dietary_water"},                       {"field": "water_intake_raw",            "agg": "sum",   "tier": 1}),

    # ── Tier 2:''',
    '''    ({"Dietary Water", "dietary_water"},                       {"field": "water_intake_raw",            "agg": "sum",   "tier": 1}),
    # Caffeine intake (water/caffeine tracking app → Apple Health)
    ({"Dietary Caffeine", "dietary_caffeine", "Caffeine", "caffeine"}, {"field": "caffeine_mg",            "agg": "sum",   "tier": 1}),

    # ── Tier 2:'''
)

with open(LAMBDA_FILE, "w") as f:
    f.write(code)

print("✅ Patched " + LAMBDA_FILE)
print("   - Added caffeine_mg (Tier 1, sum) from Dietary Caffeine → Apple Health")
