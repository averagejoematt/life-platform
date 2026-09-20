"""mcp/nutrition_micronutrients.py — the micronutrient report behind `get_nutrition(view="micronutrients")`.

Split out of mcp/tools_nutrition.py on 2026-09-20 (#3754 + #3931 together pushed that module past the
1,000-logical-line ceiling, tests/test_module_size_guard.py). Same public entrypoint — `tools_nutrition`
re-imports `_get_micronutrient_report` so `tool_get_nutrition`'s dispatch and every test that reads
`tools_nutrition._get_micronutrient_report` are unchanged. The default date range is resolved through
`tools_nutrition._nutrition_default_range` AT CALL TIME so the tests' `tools_nutrition.pacific_today`
freeze still governs it.
"""

from collections import defaultdict

from mcp.core import query_source


def _nutrition_default_range(*args, **kwargs):
    from mcp import tools_nutrition as _tn  # call-time: keeps the pacific_today freeze effective

    return _tn._nutrition_default_range(*args, **kwargs)


_MICRONUTRIENT_TARGETS = {
    "total_fiber_g": {"rda": 38, "optimal": 50, "unit": "g", "category": "Macros", "score": True},
    "total_omega3_total_g": {"rda": 1.6, "optimal": 4.0, "unit": "g", "category": "Fatty Acids", "score": True},
    "total_omega3_dha_g": {"rda": 0.5, "optimal": 2.0, "unit": "g", "category": "Fatty Acids", "score": True},
    "total_omega3_epa_g": {"rda": 0.5, "optimal": 1.5, "unit": "g", "category": "Fatty Acids", "score": True},
    "total_omega6_g": {"rda": None, "optimal": None, "unit": "g", "category": "Fatty Acids"},
    "total_sodium_mg": {"rda": 1500, "optimal": 1500, "unit": "mg", "category": "Minerals", "upper_limit": 2300},
    "total_potassium_mg": {"rda": 3400, "optimal": 4700, "unit": "mg", "category": "Minerals", "score": True},
    "total_calcium_mg": {"rda": 1000, "optimal": 1200, "unit": "mg", "category": "Minerals", "score": True, "upper_limit": 2500},
    "total_magnesium_mg": {"rda": 420, "optimal": 500, "unit": "mg", "category": "Minerals", "score": True},
    "total_iron_mg": {"rda": 8, "optimal": 18, "unit": "mg", "category": "Minerals", "score": True, "upper_limit": 45},
    "total_zinc_mg": {"rda": 11, "optimal": 15, "unit": "mg", "category": "Minerals", "score": True, "upper_limit": 40},
    "total_selenium_mcg": {"rda": 55, "optimal": 100, "unit": "mcg", "category": "Minerals", "score": True, "upper_limit": 400},
    "total_copper_mg": {"rda": 0.9, "optimal": 2.0, "unit": "mg", "category": "Minerals", "score": True, "upper_limit": 10},
    "total_phosphorus_mg": {"rda": 700, "optimal": 1000, "unit": "mg", "category": "Minerals", "score": True},
    "total_vitamin_a_mcg": {"rda": 900, "optimal": 1500, "unit": "mcg", "category": "Vitamins", "score": True, "upper_limit": 3000},
    "total_vitamin_c_mg": {"rda": 90, "optimal": 500, "unit": "mg", "category": "Vitamins", "score": True},
    "total_vitamin_d_mcg": {"rda": 20, "optimal": 50, "unit": "mcg", "category": "Vitamins", "score": True, "upper_limit": 100},
    "total_vitamin_e_mg": {"rda": 15, "optimal": 30, "unit": "mg", "category": "Vitamins", "score": True, "upper_limit": 1000},
    "total_vitamin_k_mcg": {"rda": 120, "optimal": 300, "unit": "mcg", "category": "Vitamins", "score": True},
    "total_b1_thiamine_mg": {"rda": 1.2, "optimal": 5.0, "unit": "mg", "category": "B Vitamins", "score": True},
    "total_b2_riboflavin_mg": {"rda": 1.3, "optimal": 3.0, "unit": "mg", "category": "B Vitamins", "score": True},
    "total_b3_niacin_mg": {"rda": 16, "optimal": 25, "unit": "mg", "category": "B Vitamins", "score": True, "upper_limit": 35},
    "total_b5_pantothenic_mg": {"rda": 5, "optimal": 10, "unit": "mg", "category": "B Vitamins", "score": True},
    "total_b6_pyridoxine_mg": {"rda": 1.7, "optimal": 5.0, "unit": "mg", "category": "B Vitamins", "score": True, "upper_limit": 100},
    "total_b12_cobalamin_mcg": {"rda": 2.4, "optimal": 10.0, "unit": "mcg", "category": "B Vitamins", "score": True},
    "total_folate_mcg": {"rda": 400, "optimal": 600, "unit": "mcg", "category": "B Vitamins", "score": True, "upper_limit": 1000},
    "total_choline_mg": {"rda": 550, "optimal": 750, "unit": "mg", "category": "Other", "score": True},
    "total_caffeine_mg": {"rda": None, "optimal": None, "unit": "mg", "category": "Other", "upper_limit": 400},
}
_MICRO_CATEGORY_ORDER = ["Macros", "Fatty Acids", "Minerals", "Vitamins", "B Vitamins", "Other"]
# Simopoulos 2002; ratio approach debated — some authorities question its validity
_OMEGA_RATIO_TARGET = 4.0  # Attia / Simopoulos: keep O6:O3 < 4:1
# Phillips 2016 MPS threshold; older adults may need 3g+ (anabolic resistance)
# ONE fiber target for the whole module. `view=summary` published 30 g/day, `view=macros`
# published 25 under `targets`, and the macros hit test compared against a THIRD literal 25
# — so 27 g/day was simultaneously "90% of target" and "a hit" depending on which view was
# asked. One tool must not answer one question two ways. (The 38 g in
# `_MICRONUTRIENT_TARGETS` is a different quantity — the NIH RDA, not Matthew's target.)


def _get_micronutrient_report(args):
    """
    Score ~25 micronutrients against RDA and longevity-optimal targets.
    Flags chronic deficiencies (avg < 60% RDA), near-miss gaps (60-90%), upper-limit exceedances,
    omega-6:omega-3 ratio, and generates actionable longevity commentary.
    """
    start_date, end_date = _nutrition_default_range(args)

    items = query_source("macrofactor", start_date, end_date)
    if not items:
        return {"error": "No MacroFactor data for range.", "start_date": start_date, "end_date": end_date}

    n = len(items)
    totals_sum = defaultdict(float)
    totals_count = defaultdict(int)
    for item in items:
        for field in _MICRONUTRIENT_TARGETS:
            v = item.get(field)
            if v is not None:
                totals_sum[field] += float(v)
                totals_count[field] += 1

    categories = {}
    deficiencies = []
    near_gaps = []
    exceedances = []

    for cat in _MICRO_CATEGORY_ORDER:
        cat_rows = []
        for field, meta in _MICRONUTRIENT_TARGETS.items():
            if meta.get("category") != cat:
                continue
            if totals_count[field] == 0:
                continue
            avg_val = round(totals_sum[field] / totals_count[field], 2)
            rda = meta.get("rda")
            optimal = meta.get("optimal")
            ul = meta.get("upper_limit")
            unit = meta["unit"]
            days_logged = totals_count[field]
            row = {"field": field, "average": avg_val, "unit": unit, "days_logged": days_logged}
            if rda:
                pct_rda = round(avg_val / rda * 100, 1)
                row["rda"] = rda
                row["pct_rda"] = pct_rda
                if meta.get("score"):
                    # ADR-105: the deficiency / near-gap lists are the part a reader quotes, and
                    # the docstring calls them CHRONIC. Each entry carries the n it averaged over,
                    # so a one-day shortfall cannot read as a thirty-day one.
                    entry = {
                        "field": field,
                        "average": avg_val,
                        "unit": unit,
                        "pct_rda": pct_rda,
                        "rda": rda,
                        "days_logged": days_logged,
                    }
                    if pct_rda < 60:
                        row["status"] = "DEFICIENT"
                        deficiencies.append(entry)
                    elif pct_rda < 90:
                        row["status"] = "LOW"
                        near_gaps.append(entry)
            # Upper-limit exceedance must NOT depend on `score` or on `rda` being set (#2248):
            # total_sodium_mg and total_caffeine_mg both carry an `upper_limit` but no `score`
            # (and caffeine has no `rda` at all), so nesting this under either silently excluded
            # the two most actionable overages in the table. Checked independently here, it fires
            # for every upper_limit entry regardless of score/rda. A scored+rda'd nutrient that
            # isn't DEFICIENT/LOW and isn't over its limit still lands on ADEQUATE, unchanged.
            if ul and avg_val > ul:
                row["status"] = "ABOVE_UPPER_LIMIT"
                exceedances.append({"field": field, "average": avg_val, "unit": unit, "upper_limit": ul, "days_logged": days_logged})
            elif meta.get("score") and rda and "status" not in row:
                row["status"] = "ADEQUATE"
            if optimal:
                row["optimal"] = optimal
                row["pct_optimal"] = round(avg_val / optimal * 100, 1)
            cat_rows.append(row)
        if cat_rows:
            categories[cat] = sorted(cat_rows, key=lambda r: r.get("pct_rda", 999))

    # ADR-104 — a nutrient that appears in NO record has no average, not an average of 0.
    # `totals_sum.get(f, 0) / max(totals_count.get(f, 1), 1)` turned every absence into a
    # factual 0.0, and every threshold below is a `<`, so a range that only logged fiber
    # fired ALL THREE longevity flags — three fabricated deficiencies, each with a
    # supplement recommendation attached. Every other number in this function is already
    # gated on `totals_count[field] == 0`; the flag block and the omega ratio were not.
    def logged_avg(field):
        count = totals_count.get(field, 0)
        return (totals_sum.get(field, 0.0) / count) if count else None

    omega6 = logged_avg("total_omega6_g")
    omega3 = logged_avg("total_omega3_total_g")
    o6_o3 = round(omega6 / omega3, 1) if (omega6 is not None and omega3) else None

    longevity_flags = []
    if o6_o3 and o6_o3 > _OMEGA_RATIO_TARGET:
        longevity_flags.append(
            f"Omega-6:Omega-3 ratio is {o6_o3}:1 (target <{_OMEGA_RATIO_TARGET}:1). Pro-inflammatory — increase EPA/DHA or reduce seed oils."
        )
    dha_avg = logged_avg("total_omega3_dha_g")
    if dha_avg is not None and dha_avg < 1.0:
        longevity_flags.append(
            f"DHA averages {round(dha_avg, 2)}g/day — below the 1g+ associated with cognitive protection (Rhonda Patrick). Add fatty fish ≥3x/week or algae-based DHA supplement."
        )
    mag_avg = logged_avg("total_magnesium_mg")
    if mag_avg is not None and mag_avg < 350:
        longevity_flags.append(
            f"Magnesium averages {round(mag_avg)}mg/day. Sub-optimal magnesium is linked to poor sleep quality, elevated cortisol, and lower HRV. Target 400-500mg from food + glycinate supplement."
        )
    vd_avg = logged_avg("total_vitamin_d_mcg")
    if vd_avg is not None and vd_avg < 25:
        longevity_flags.append(
            f"Vitamin D from food averages {round(vd_avg, 1)}mcg/day. Difficult to reach optimal serum levels (60-80 ng/mL) from diet alone in the Pacific Northwest — consider 4,000-5,000 IU D3+K2 supplement."
        )

    return {
        "period": {"start_date": start_date, "end_date": end_date, "days_with_data": n},
        "summary": {
            "deficiencies": len(deficiencies),
            "near_gaps": len(near_gaps),
            "exceedances": len(exceedances),
            "omega6_omega3_ratio": o6_o3,
            "omega6_omega3_status": "OK" if o6_o3 and o6_o3 <= _OMEGA_RATIO_TARGET else "HIGH" if o6_o3 else "insufficient_data",
        },
        "longevity_flags": longevity_flags,
        "deficiencies": deficiencies,
        "near_gaps": near_gaps,
        "exceedances": exceedances,
        "by_category": categories,
    }
