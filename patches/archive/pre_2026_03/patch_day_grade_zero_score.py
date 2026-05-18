#!/usr/bin/env python3
"""
Patch: Day Grade Zero-Score Fix (v2.22.1)

Fixes two bugs where missing data scores 0 instead of being excluded:
1. score_journal: returns 0 when no entries → changed to None
2. score_hydration: trace amounts (Apple Health food-water noise) score 0 →
   added 118ml (4oz) minimum threshold; below = "not tracked" (None)

Impact: Prevents untracked components from dragging down the weighted grade.
Before: Feb 24 scored 69 (C+) with journal=0, hydration=0
After:  Feb 24 would score ~77 (B) with those components excluded

Algorithm version bumped to 1.1 for retrocompute tracking.
"""

import re

LAMBDA_FILE = "daily_brief_lambda.py"

def patch():
    with open(LAMBDA_FILE, "r") as f:
        code = f.read()

    # -------------------------------------------------------------------------
    # Fix 1: score_journal — return None instead of 0 when no entries
    # -------------------------------------------------------------------------
    old_journal = '''def score_journal(data, profile):
    entries = data.get("journal_entries", [])
    if not entries:
        return 0, {"entries": 0}'''

    new_journal = '''def score_journal(data, profile):
    entries = data.get("journal_entries", [])
    if not entries:
        return None, {"entries": 0}'''

    if old_journal not in code:
        print("[ERROR] Could not find score_journal target block")
        return False
    code = code.replace(old_journal, new_journal)
    print("[OK] Fix 1: score_journal returns None when no entries")

    # -------------------------------------------------------------------------
    # Fix 2: score_hydration — add 118ml (4oz) minimum threshold
    # Below this is almost certainly Apple Health food-content noise,
    # not intentional water tracking. Treat as "not tracked".
    # -------------------------------------------------------------------------
    old_hydration = '''def score_hydration(data, profile):
    apple = data.get("apple")
    water_ml = safe_float(apple, "water_intake_ml") if apple else None
    target_ml = profile.get("water_target_ml", 2957)
    if water_ml is None:
        return None, {}'''

    new_hydration = '''def score_hydration(data, profile):
    apple = data.get("apple")
    water_ml = safe_float(apple, "water_intake_ml") if apple else None
    target_ml = profile.get("water_target_ml", 2957)
    # Minimum 118ml (4oz / ~half cup) to count as tracked.
    # Below this is Apple Health food-content noise, not intentional logging.
    if water_ml is None or water_ml < 118:
        return None, {}'''

    if old_hydration not in code:
        print("[ERROR] Could not find score_hydration target block")
        return False
    code = code.replace(old_hydration, new_hydration)
    print("[OK] Fix 2: score_hydration treats <118ml as not tracked")

    # -------------------------------------------------------------------------
    # Fix 3: Bump algorithm version default from 1.0 to 1.1
    # -------------------------------------------------------------------------
    old_algo = 'profile.get("day_grade_algorithm_version", "1.0")'
    new_algo = 'profile.get("day_grade_algorithm_version", "1.1")'

    if old_algo in code:
        code = code.replace(old_algo, new_algo)
        print("[OK] Fix 3: Algorithm version default bumped to 1.1")
    else:
        print("[WARN] Could not find algorithm_version default — may already be patched")

    # -------------------------------------------------------------------------
    # Update version comment at top of file
    # -------------------------------------------------------------------------
    code = code.replace(
        "Daily Brief Lambda — v2.2.0 (Intelligence Upgrade)",
        "Daily Brief Lambda — v2.2.1 (Day Grade Zero-Score Fix)"
    )
    print("[OK] Version header updated to v2.2.1")

    with open(LAMBDA_FILE, "w") as f:
        f.write(code)

    print("\n[DONE] Patch applied. Run deploy_daily_brief_v221.sh to deploy.")
    return True


if __name__ == "__main__":
    patch()
