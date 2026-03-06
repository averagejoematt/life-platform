"""
patch_protein_distribution.py — Add protein_distribution_score to macrofactor_lambda.py

Derived Metrics Phase 1d: Per-meal protein distribution (Norton/Galpin ≥30g MPS threshold).
Groups food_log entries into meals by 30-min time proximity, filters out snacks (<400 kcal),
then counts meals ≥30g protein.

New fields on macrofactor record:
  - protein_distribution_score (float, 0-100): % of meals hitting ≥30g protein
  - meals_above_30g_protein (int): count of qualifying meals
  - total_meals (int): total distinct meals detected (≥400 kcal)
  - total_snacks (int): eating occasions excluded as snacks (<400 kcal)
"""

LAMBDA_FILE = "macrofactor_lambda.py"

# The helper function to add (meal grouping + protein distribution)
HELPER_CODE = '''

# ── Protein Distribution (Derived Metrics Phase 1d) ──────────────────────────
# Norton/Galpin: ≥30g protein per meal to maximize MPS via leucine threshold.
# Snacks (<400 kcal) excluded — only real meals count toward the score.
MEAL_CALORIE_THRESHOLD = 400  # kcal — eating occasions below this are "snacks"
PROTEIN_MPS_THRESHOLD = 30    # grams — minimum per meal for MPS


def compute_protein_distribution(food_log):
    """
    Group food_log entries into meals by 30-min time proximity.
    Exclude snacks (<MEAL_CALORIE_THRESHOLD kcal) from scoring.
    Returns (score_pct, meals_above_30g, total_meals, total_snacks).
    """
    if not food_log:
        return None, 0, 0, 0

    # Parse times, protein, and calories
    timed_entries = []
    for entry in food_log:
        time_str = entry.get("time")
        protein = entry.get("protein_g")
        calories = entry.get("calories_kcal")
        if not time_str or protein is None:
            continue
        try:
            parts = time_str.split(":")
            minutes_from_midnight = int(parts[0]) * 60 + int(parts[1])
            timed_entries.append((minutes_from_midnight, float(protein), float(calories or 0)))
        except (ValueError, IndexError):
            continue

    if not timed_entries:
        return None, 0, 0, 0

    timed_entries.sort(key=lambda x: x[0])

    # Group into eating occasions: entries within 30 min = same occasion
    occasions = []  # list of (total_protein, total_calories)
    cur_start = timed_entries[0][0]
    cur_protein = timed_entries[0][1]
    cur_calories = timed_entries[0][2]

    for i in range(1, len(timed_entries)):
        time_min, protein, calories = timed_entries[i]
        if time_min - cur_start <= 30:
            cur_protein += protein
            cur_calories += calories
        else:
            occasions.append((cur_protein, cur_calories))
            cur_start = time_min
            cur_protein = protein
            cur_calories = calories

    occasions.append((cur_protein, cur_calories))

    # Separate meals from snacks
    meals = [(p, c) for p, c in occasions if c >= MEAL_CALORIE_THRESHOLD]
    total_snacks = len(occasions) - len(meals)
    total_meals = len(meals)

    if total_meals == 0:
        # All eating occasions were snacks — return 0 score with context
        return 0.0, 0, 0, total_snacks

    above_30g = sum(1 for p, c in meals if p >= PROTEIN_MPS_THRESHOLD)
    score = round(above_30g / total_meals * 100, 1)

    return score, above_30g, total_meals, total_snacks

'''

# The code to insert into build_day_items, right before the item dict construction
DISTRIBUTION_CALC = '''
        # ── Protein distribution (Phase 1d) ──
        pds_score, pds_above, pds_total, pds_snacks = compute_protein_distribution(food_log)
'''


def patch():
    with open(LAMBDA_FILE, "r") as f:
        code = f.read()

    if "compute_protein_distribution" in code:
        print("Already patched (compute_protein_distribution found). Skipping.")
        return

    # ── Patch 1: Add helper function before build_day_items ──
    anchor = "\ndef build_day_items(rows):"
    if anchor not in code:
        raise ValueError("Could not find build_day_items function definition")
    code = code.replace(anchor, HELPER_CODE + anchor)

    # ── Patch 2: Add computation inside build_day_items, after food_log is built ──
    food_log_line = '        food_log = sorted(data["entries"], key=lambda e: e.get("time") or "00:00")'
    if food_log_line not in code:
        raise ValueError("Could not find food_log assignment line")
    code = code.replace(food_log_line, food_log_line + DISTRIBUTION_CALC)

    # ── Patch 3: Add fields to the item dict ──
    old_item_end = '            **totals_prefixed,'
    new_item_end = '''            **totals_prefixed,
            **({"protein_distribution_score": pds_score,
                "meals_above_30g_protein": pds_above,
                "total_meals": pds_total,
                "total_snacks": pds_snacks} if pds_score is not None else {}),'''

    if old_item_end not in code:
        raise ValueError("Could not find **totals_prefixed in item construction")
    code = code.replace(old_item_end, new_item_end, 1)

    with open(LAMBDA_FILE, "w") as f:
        f.write(code)

    print(f"✅ Patched {LAMBDA_FILE} with protein_distribution_score (≥{MEAL_CALORIE_THRESHOLD} kcal meal threshold)")


if __name__ == "__main__":
    MEAL_CALORIE_THRESHOLD = 400  # for print statement
    patch()
