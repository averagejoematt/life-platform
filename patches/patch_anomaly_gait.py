#!/usr/bin/env python3
"""
Patcher: Add gait metrics to anomaly detector
- walking_speed_mph (low is bad — strongest mortality predictor)
- walking_asymmetry_pct (high is bad — injury indicator)
Metrics: 9 → 11
"""
import os

if os.path.exists("anomaly_detector_lambda.py"):
    LAMBDA_FILE = "anomaly_detector_lambda.py"
else:
    LAMBDA_FILE = "lambda_function.py"

with open(LAMBDA_FILE, "r") as f:
    code = f.read()

# Add gait metrics after the existing apple_health steps entry
code = code.replace(
    '''    ("apple_health","steps",              "Steps",               True),''',
    '''    ("apple_health","steps",              "Steps",               True),
    ("apple_health","walking_speed_mph",  "Walking Speed",       True),   # low = clinical concern
    ("apple_health","walking_asymmetry_pct","Walking Asymmetry", False),  # spike = injury indicator'''
)

# Update docstring metric count and list
code = code.replace(
    "  1. Fetch yesterday's values for 9 key metrics across 6 sources",
    "  1. Fetch yesterday's values for 11 key metrics across 6 sources"
)
code = code.replace(
    "  Apple Health: steps",
    "  Apple Health: steps, walking_speed_mph, walking_asymmetry_pct"
)

# Version bump
code = code.replace(
    "Anomaly Detector Lambda — v1.0.0",
    "Anomaly Detector Lambda — v1.1.0"
)

with open(LAMBDA_FILE, "w") as f:
    f.write(code)

print("✅ Patched " + LAMBDA_FILE + " → v1.1.0")
print("   - Added walking_speed_mph (low is bad)")
print("   - Added walking_asymmetry_pct (high is bad)")
print("   - Metrics: 9 → 11")
