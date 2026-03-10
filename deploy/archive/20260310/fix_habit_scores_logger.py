#!/usr/bin/env python3
"""Fix the one remaining %s logger call in daily_metrics_compute_lambda.py"""
import os
path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "lambdas", "daily_metrics_compute_lambda.py")
with open(path) as f:
    c = f.read()

old = (
    '        logger.info("Stored habit_scores: %s T0=%s/%s T1=%s/%s",\n'
    '                    date_str, t0.get("done", 0), t0.get("total", 0),\n'
    '                    t1.get("done", 0), t1.get("total", 0))'
)
new = (
    "        logger.info(f\"Stored habit_scores: {date_str}"
    " T0={t0.get('done', 0)}/{t0.get('total', 0)}"
    " T1={t1.get('done', 0)}/{t1.get('total', 0)}\")"
)

if old in c:
    c = c.replace(old, new, 1)
    with open(path, "w") as f:
        f.write(c)
    print("✅ Fixed habit_scores logger line")
else:
    print("ℹ️  Already fixed or not found")
