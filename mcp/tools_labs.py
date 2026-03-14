"""
Lab results, genome, DEXA tools.
"""
import json
import math
import re
import logging
from datetime import datetime, timedelta
from collections import defaultdict

from mcp.config import (
    table, s3_client, S3_BUCKET, USER_PREFIX, USER_ID, SOURCES,
    P40_GROUPS, FIELD_ALIASES, logger,
    INSIGHTS_PK, EXPERIMENTS_PK, TRAVEL_PK,
)
from mcp.core import (
    query_source, parallel_query_sources, query_source_range,
    get_profile, get_sot, decimal_to_float,
    ddb_cache_get, ddb_cache_set, mem_cache_get, mem_cache_set,
    date_diff_days, resolve_field,
)
from mcp.helpers import (
    aggregate_items, flatten_strava_activity,
    compute_daily_load_score, compute_ewa, pearson_r, _linear_regression,
    classify_day_type, query_chronicling, _habit_series,
)
from mcp.labs_helpers import (
    _get_genome_cached, _query_all_lab_draws, _query_dexa_scans,
    _query_lab_meta, _genome_context_for_biomarkers, _GENOME_LAB_XREF,
)
def tool_get_lab_results(args):
    """Single draw detail with genome annotations, or summary of all draws."""
    draw_date = args.get("draw_date")
    category = args.get("category")
    draws = _query_all_lab_draws()
    if not draws:
        return {"error": "No lab draws found in DynamoDB"}

    if not draw_date:
        summaries = []
        for d in draws:
            summaries.append({
                "draw_date": d.get("draw_date"),
                "provider": d.get("lab_provider"),
                "lab_network": d.get("lab_network"),
                "fasting": d.get("fasting"),
                "total_biomarkers": d.get("total_biomarkers"),
                "out_of_range_count": d.get("out_of_range_count"),
                "out_of_range": d.get("out_of_range", []),
            })
        return {"total_draws": len(draws), "draws": summaries,
                "hint": "Pass draw_date to see full biomarkers for a specific draw."}

    draw = next((d for d in draws if d.get("draw_date") == draw_date), None)
    if not draw:
        return {"error": f"No draw for {draw_date}",
                "available_dates": [d.get("draw_date") for d in draws]}

    biomarkers = draw.get("biomarkers", {})
    if category:
        biomarkers = {k: v for k, v in biomarkers.items()
                      if v.get("category") == category}

    genome_ctx = _genome_context_for_biomarkers(list(biomarkers.keys()))
    categories = sorted(set(v.get("category", "")
                            for v in draw.get("biomarkers", {}).values()))

    return {
        "draw_date": draw_date,
        "provider": draw.get("lab_provider"),
        "lab_network": draw.get("lab_network"),
        "physician": draw.get("physician"),
        "fasting": draw.get("fasting"),
        "total_biomarkers": draw.get("total_biomarkers"),
        "out_of_range_count": draw.get("out_of_range_count"),
        "out_of_range": draw.get("out_of_range", []),
        "biomarkers": biomarkers,
        "genome_context": genome_ctx if genome_ctx else None,
        "categories_in_draw": categories,
    }


def tool_get_lab_trends(args):
    """Biomarker trajectory across all draws with slope, projection, derived ratios."""
    biomarkers_req = args.get("biomarkers", [])
    single = args.get("biomarker")
    if single:
        biomarkers_req = [single]
    include_derived = args.get("include_derived_ratios", True)
    draws = _query_all_lab_draws()
    if not draws:
        return {"error": "No lab draws found"}

    from datetime import datetime as _dt

    trends = {}
    for bm_key in biomarkers_req:
        points = []
        for d in draws:
            bms = d.get("biomarkers", {})
            if bm_key in bms:
                val = bms[bm_key].get("value_numeric") or bms[bm_key].get("value")
                if isinstance(val, (int, float)):
                    date = d.get("draw_date", "")
                    points.append({"date": date, "value": round(val, 2),
                                   "flag": bms[bm_key].get("flag", "normal"),
                                   "ref": bms[bm_key].get("ref_text", ""),
                                   "unit": bms[bm_key].get("unit", "")})
        if not points:
            trends[bm_key] = {"error": f"No data for '{bm_key}'",
                              "hint": "Use search_biomarker to find valid names."}
            continue

        base = _dt.strptime(points[0]["date"], "%Y-%m-%d")
        reg_pts = [( (_dt.strptime(p["date"], "%Y-%m-%d") - base).days, p["value"] ) for p in points]
        slope, intercept, r_sq = _linear_regression(reg_pts)

        if slope is not None:
            direction = "rising" if slope > 0.001 else ("falling" if slope < -0.001 else "stable")
            slope_per_year = round(slope * 365.25, 2)
        else:
            direction, slope_per_year = "insufficient_data", None

        projected_1yr = None
        if slope is not None and len(reg_pts) >= 2:
            projected_1yr = round(intercept + slope * (reg_pts[-1][0] + 365), 2)

        trends[bm_key] = {
            "values": points, "data_points": len(points),
            "direction": direction, "slope_per_year": slope_per_year,
            "r_squared": r_sq, "projected_1yr": projected_1yr,
            "latest": points[-1]["value"], "earliest": points[0]["value"],
            "total_change": round(points[-1]["value"] - points[0]["value"], 2),
        }

    derived = {}
    if include_derived:
        for d in draws:
            bms = d.get("biomarkers", {})
            date = d.get("draw_date", "")
            tg_v = bms.get("triglycerides", {}).get("value_numeric") or bms.get("triglycerides", {}).get("value")
            hdl_v = bms.get("hdl", {}).get("value_numeric") or bms.get("hdl", {}).get("value")
            tc_v = bms.get("cholesterol_total", {}).get("value_numeric") or bms.get("cholesterol_total", {}).get("value")

            if isinstance(tg_v, (int, float)) and isinstance(hdl_v, (int, float)) and hdl_v > 0:
                derived.setdefault("tg_hdl_ratio", []).append({
                    "date": date, "value": round(tg_v / hdl_v, 2),
                    "interpretation": "optimal <1.0, good <2.0, elevated >=2.0 (insulin resistance proxy)"})
            if isinstance(tc_v, (int, float)) and isinstance(hdl_v, (int, float)):
                derived.setdefault("non_hdl_cholesterol", []).append({
                    "date": date, "value": round(tc_v - hdl_v, 1),
                    "interpretation": "optimal <130, borderline 130-159, high >=160"})
            if isinstance(tc_v, (int, float)) and isinstance(hdl_v, (int, float)) and hdl_v > 0:
                derived.setdefault("tc_hdl_ratio", []).append({
                    "date": date, "value": round(tc_v / hdl_v, 2),
                    "interpretation": "optimal <3.5, good <5.0, elevated >=5.0"})

    genome_ctx = _genome_context_for_biomarkers(biomarkers_req)
    result = {"trends": trends, "total_draws": len(draws),
              "date_range": f"{draws[0].get('draw_date')} to {draws[-1].get('draw_date')}"}
    if derived:
        result["derived_ratios"] = derived
    if genome_ctx:
        result["genome_context"] = genome_ctx
    return result


def tool_get_out_of_range_history(args):
    """Every flagged biomarker across all draws with persistence and genome drivers."""
    draws = _query_all_lab_draws()
    if not draws:
        return {"error": "No lab draws found"}

    oor_map = defaultdict(list)
    for d in draws:
        date = d.get("draw_date", "")
        bms = d.get("biomarkers", {})
        for key, bm_data in bms.items():
            if bm_data.get("flag") in ("high", "low"):
                val = bm_data.get("value_numeric") or bm_data.get("value")
                oor_map[key].append({
                    "date": date, "value": val, "flag": bm_data["flag"],
                    "unit": bm_data.get("unit", ""), "ref_text": bm_data.get("ref_text", ""),
                    "category": bm_data.get("category", "")})

    total_draws = len(draws)
    flagged = []
    for key, occurrences in sorted(oor_map.items(), key=lambda x: -len(x[1])):
        tested_count = sum(1 for d in draws if key in d.get("biomarkers", {}))
        flagged_rate = round(100 * len(occurrences) / max(tested_count, 1), 1)
        flagged.append({
            "biomarker": key, "category": occurrences[0]["category"],
            "times_flagged": len(occurrences), "times_tested": tested_count,
            "flag_rate_pct": flagged_rate,
            "persistence": "chronic" if flagged_rate >= 60 else ("recurring" if flagged_rate >= 30 else "occasional"),
            "occurrences": occurrences})

    chronic_keys = [f["biomarker"] for f in flagged if f["persistence"] == "chronic"]
    genome_ctx = _genome_context_for_biomarkers(chronic_keys)

    return {
        "total_draws": total_draws,
        "date_range": f"{draws[0].get('draw_date')} to {draws[-1].get('draw_date')}",
        "flagged_biomarkers": flagged, "total_unique_flags": len(flagged),
        "chronic_flags": chronic_keys,
        "genome_drivers": genome_ctx if genome_ctx else None,
        "insight": ("Chronic out-of-range biomarkers with genome drivers suggest genetic baseline "
                    "rather than lifestyle failure.") if genome_ctx else None}


def tool_search_biomarker(args):
    """Free-text search for a biomarker across all draws."""
    query = args.get("query", "").lower().strip()
    if not query:
        return {"error": "Provide a search query (e.g. 'ldl', 'cholesterol', 'thyroid')."}

    draws = _query_all_lab_draws()
    if not draws:
        return {"error": "No lab draws found"}

    matches = defaultdict(list)
    for d in draws:
        date = d.get("draw_date", "")
        bms = d.get("biomarkers", {})
        for key, bm_data in bms.items():
            cat = bm_data.get("category", "")
            if query in key.lower() or query in cat.lower():
                val = bm_data.get("value_numeric") or bm_data.get("value")
                matches[key].append({
                    "date": date, "value": val, "flag": bm_data.get("flag", "normal"),
                    "unit": bm_data.get("unit", ""), "ref_text": bm_data.get("ref_text", ""),
                    "category": cat})

    if not matches:
        all_keys = set()
        for d in draws:
            all_keys.update(d.get("biomarkers", {}).keys())
        return {"error": f"No match for '{query}'", "available_biomarkers": sorted(all_keys)}

    results = []
    for key, values in sorted(matches.items()):
        numeric_vals = [v["value"] for v in values if isinstance(v["value"], (int, float))]
        entry = {"biomarker": key, "category": values[0]["category"],
                 "unit": values[0]["unit"], "data_points": len(values), "values": values}
        if len(numeric_vals) >= 2:
            entry["latest"] = numeric_vals[-1]
            entry["earliest"] = numeric_vals[0]
            entry["change"] = round(numeric_vals[-1] - numeric_vals[0], 2)
            entry["direction"] = "rising" if entry["change"] > 0.5 else ("falling" if entry["change"] < -0.5 else "stable")
        results.append(entry)

    genome_ctx = _genome_context_for_biomarkers([r["biomarker"] for r in results])
    return {"query": query, "matches": len(results), "results": results,
            "genome_context": genome_ctx if genome_ctx else None}


def tool_get_genome_insights(args):
    """Query genome SNPs by category/risk/gene with optional cross-reference."""
    category = args.get("category")
    risk_level = args.get("risk_level")
    gene = args.get("gene")
    cross_ref = args.get("cross_reference")

    all_snps = _get_genome_cached()
    if not all_snps:
        return {"error": "No genome data found."}

    filtered = [s for s in all_snps if s.get("sk", "").startswith("GENE#")]
    if category:
        filtered = [s for s in filtered if s.get("category") == category]
    if risk_level:
        filtered = [s for s in filtered if s.get("risk_level") == risk_level]
    if gene:
        g = gene.upper()
        filtered = [s for s in filtered if s.get("gene", "").upper() == g]

    snps_out = []
    for s in filtered:
        entry = {"gene": s.get("gene"), "rsid": s.get("rsid"),
                 "genotype": s.get("genotype"), "category": s.get("category"),
                 "risk_level": s.get("risk_level"), "summary": s.get("summary")}
        if s.get("actionable_recs"):
            entry["actionable_recs"] = s["actionable_recs"]
        if s.get("related_biomarkers"):
            entry["related_biomarkers"] = s["related_biomarkers"]
        snps_out.append(entry)

    result = {"total_snps": len(snps_out),
              "filters_applied": {k: v for k, v in {"category": category, "risk_level": risk_level, "gene": gene}.items() if v},
              "snps": snps_out}

    if cross_ref == "labs" and snps_out:
        draws = _query_all_lab_draws()
        if draws:
            latest = draws[-1]
            bms = latest.get("biomarkers", {})
            snp_genes = set(s["gene"] for s in snps_out)
            lab_links = {}
            for bm_key, gene_list in _GENOME_LAB_XREF.items():
                if any(g in snp_genes for g in gene_list) and bm_key in bms:
                    val = bms[bm_key].get("value_numeric") or bms[bm_key].get("value")
                    lab_links[bm_key] = {"latest_value": val, "latest_date": latest.get("draw_date"),
                                         "flag": bms[bm_key].get("flag"), "unit": bms[bm_key].get("unit")}
            if lab_links:
                result["lab_cross_reference"] = lab_links

    if cross_ref == "nutrition" and snps_out:
        from datetime import datetime as _dt, timedelta as _td
        today = _dt.now().strftime("%Y-%m-%d")
        week_ago = (_dt.now() - _td(days=7)).strftime("%Y-%m-%d")
        try:
            mf = query_source("macrofactor", week_ago, today)
            if mf:
                result["nutrition_cross_reference"] = {
                    "period": f"{week_ago} to {today}", "days": len(mf),
                    "avg_calories": round(sum(d.get("total_calories_kcal", 0) for d in mf) / len(mf)),
                    "avg_protein_g": round(sum(d.get("total_protein_g", 0) for d in mf) / len(mf), 1),
                    "avg_fat_g": round(sum(d.get("total_fat_g", 0) for d in mf) / len(mf), 1),
                    "avg_omega3_g": round(sum(d.get("total_omega3_g", 0) for d in mf) / len(mf), 2)}
        except Exception as e:
            logger.warning(f"Nutrition cross-ref failed: {e}")

    if not category and not risk_level and not gene:
        cats, risks = defaultdict(int), defaultdict(int)
        for s in snps_out:
            cats[s.get("category", "unknown")] += 1
            risks[s.get("risk_level", "unknown")] += 1
        result["category_breakdown"] = dict(sorted(cats.items()))
        result["risk_breakdown"] = dict(sorted(risks.items()))
        result["available_categories"] = sorted(cats.keys())

    return result


def tool_get_labs(args):
    """Unified lab intelligence dispatcher."""
    VALID_VIEWS = {
        "results":      tool_get_lab_results,
        "trends":       tool_get_lab_trends,
        "out_of_range": tool_get_out_of_range_history,
    }
    view = (args.get("view") or "results").lower().strip()
    if view not in VALID_VIEWS:
        return {"error": f"Unknown view '{view}'.", "valid_views": list(VALID_VIEWS.keys()),
                "hint": "'results' for latest draws, 'trends' for trajectory, 'out_of_range' for persistent flags."}
    return VALID_VIEWS[view](args)
