#!/usr/bin/env python3
"""Fix 2 remaining %s logger calls in daily_metrics_compute_lambda.py"""
import os
path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "lambdas", "daily_metrics_compute_lambda.py")
with open(path) as f:
    c = f.read()

fixes = [
    (
        '        logger.info("Stored habit_scores: %s T0=%s/%s T1=%s/%s",\n'
        '                    date_str, t0.get("done", 0), t0.get("total", 0),\n'
        '                    t1.get("done", 0), t1.get("total", 0))',
        "        logger.info(f\"Stored habit_scores: {date_str} T0={t0.get('done', 0)}/{t0.get('total', 0)} T1={t1.get('done', 0)}/{t1.get('total', 0)}\")"
    ),
    (
        '        logger.info("Sick day flagged for %s (%s) \u2014 storing sick record", yesterday_str, _sick_reason)',
        '        logger.info(f"Sick day flagged for {yesterday_str} ({_sick_reason}) \u2014 storing sick record")'
    ),
]

changed = 0
for old, new in fixes:
    if old in c:
        c = c.replace(old, new, 1)
        changed += 1
    else:
        print(f"  \u26a0\ufe0f  Not found: {old[:60]}")

with open(path, "w") as f:
    f.write(c)
print(f"\u2705 Fixed {changed} lines in daily_metrics_compute_lambda.py")
