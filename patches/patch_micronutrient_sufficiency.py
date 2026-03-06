"""
patch_micronutrient_sufficiency.py — Add micronutrient_sufficiency to macrofactor_lambda.py

Derived Metrics Phase 1e: Per-nutrient % of optimal daily target.
Uses Board of Directors recommended targets (Attia/Patrick/Huberman consensus).

Targets:
  - Fiber: 38g (IOM recommendation for adult males)
  - Potassium: 3400mg (adequate intake, adult males)
  - Magnesium: 420mg (RDA adult males; Patrick recommends higher)
  - Vitamin D: 100mcg / 4000 IU (Attia/Patrick therapeutic target)
  - Omega-3: 3g total (Attia/Huberman anti-inflammatory target)

New fields on macrofactor record:
  - micronutrient_sufficiency (map): {nutrient: {actual, target, pct}}
  - micronutrient_avg_pct (float): average sufficiency across tracked nutrients
"""

LAMBDA_FILE = "macrofactor_lambda.py"

HELPER_CODE = '''

# ── Micronutrient Sufficiency (Derived Metrics Phase 1e) ─────────────────────
# Board of Directors consensus targets for adult male, active, weight loss phase.
MICRONUTRIENT_TARGETS = {
    "fiber_g":         {"target": 38,   "label": "Fiber"},
    "potassium_mg":    {"target": 3400, "label": "Potassium"},
    "magnesium_mg":    {"target": 420,  "label": "Magnesium"},
    "vitamin_d_mcg":   {"target": 100,  "label": "Vitamin D"},   # 4000 IU
    "omega3_total_g":  {"target": 3,    "label": "Omega-3"},
}


def compute_micronutrient_sufficiency(totals_prefixed):
    """
    Compute per-nutrient sufficiency as % of optimal daily target.
    Returns (sufficiency_map, avg_pct) or (None, None) if no data.
    
    sufficiency_map: {nutrient_key: {"actual": float, "target": float, "pct": float}}
    Pct is capped at 100 — exceeding target still scores 100%.
    """
    sufficiency = {}
    pcts = []

    for nutrient_key, config in MICRONUTRIENT_TARGETS.items():
        total_key = f"total_{nutrient_key}"
        actual = totals_prefixed.get(total_key)
        if actual is None:
            continue
        actual = float(actual)
        target = config["target"]
        pct = min(round(actual / target * 100, 1), 100.0)
        sufficiency[nutrient_key] = {
            "actual": round(actual, 1),
            "target": target,
            "pct": pct,
        }
        pcts.append(pct)

    if not pcts:
        return None, None

    avg_pct = round(sum(pcts) / len(pcts), 1)
    return sufficiency, avg_pct

'''

# Code to insert into build_day_items after protein distribution calc
SUFFICIENCY_CALC = '''
        # ── Micronutrient sufficiency (Phase 1e) ──
        micro_suff, micro_avg = compute_micronutrient_sufficiency(totals_prefixed)
'''


def patch():
    with open(LAMBDA_FILE, "r") as f:
        code = f.read()

    if "compute_micronutrient_sufficiency" in code:
        print("Already patched (compute_micronutrient_sufficiency found). Skipping.")
        return

    # ── Patch 1: Add helper function before build_day_items ──
    # Insert after protein distribution helper (which was added in Phase 1d)
    anchor = "\ndef build_day_items(rows):"
    if anchor not in code:
        raise ValueError("Could not find build_day_items function definition")
    code = code.replace(anchor, HELPER_CODE + anchor)

    # ── Patch 2: Add computation after protein distribution calc ──
    # Find the protein distribution line added in Phase 1d
    after_protein = "        pds_score, pds_above, pds_total, pds_snacks = compute_protein_distribution(food_log)"
    if after_protein not in code:
        raise ValueError("Could not find protein distribution calc (Phase 1d must be applied first)")
    code = code.replace(after_protein, after_protein + SUFFICIENCY_CALC)

    # ── Patch 3: Add fields to the item dict ──
    # Insert after protein distribution fields
    old_protein_block = '''            **({"protein_distribution_score": pds_score,
                "meals_above_30g_protein": pds_above,
                "total_meals": pds_total,
                "total_snacks": pds_snacks} if pds_score is not None else {}),'''

    new_block = old_protein_block + '''
            **({"micronutrient_sufficiency": micro_suff,
                "micronutrient_avg_pct": micro_avg} if micro_suff is not None else {}),'''

    if old_protein_block not in code:
        raise ValueError("Could not find protein distribution fields in item construction")
    code = code.replace(old_protein_block, new_block, 1)

    with open(LAMBDA_FILE, "w") as f:
        f.write(code)

    print(f"✅ Patched {LAMBDA_FILE} with micronutrient_sufficiency (5 nutrients)")


if __name__ == "__main__":
    patch()
