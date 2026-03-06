#!/usr/bin/env python3
"""
patch_labs_genome_tools.py — Patch MCP server v2.8.0 → v2.11.0
Adds 8 new labs/DEXA/genome tools (47 → 55 tools).

New tools:
  1. get_lab_results             — single draw biomarkers with genome annotations
  2. get_lab_trends              — biomarker trajectory + slope + projection + derived ratios
  3. get_out_of_range_history    — persistent flags across all draws + genome drivers
  4. search_biomarker            — free-text search across all draws
  5. get_genome_insights         — SNP query by category/risk + labs/nutrition cross-ref
  6. get_body_composition_snapshot — DEXA interpretation + FFMI + training context
  7. get_health_risk_profile     — multi-domain risk synthesis (CV, metabolic, longevity)
  8. get_next_lab_priorities     — genome-informed next blood panel recommendations

Usage:
  python3 patch_labs_genome_tools.py          # dry run
  python3 patch_labs_genome_tools.py --apply  # patches mcp_server.py in place
"""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MCP_PATH = os.path.join(SCRIPT_DIR, "mcp_server.py")

# ═══════════════════════════════════════════════════════════════════════════════
# CODE BLOCKS TO INSERT
# ═══════════════════════════════════════════════════════════════════════════════

HELPERS_CODE = '''

# ── Labs / DEXA / Genome helpers (v2.11.0) ───────────────────────────────────

_GENOME_CACHE_V2 = None

def _get_genome_cached():
    """Query all genome SNPs once per Lambda invocation."""
    global _GENOME_CACHE_V2
    if _GENOME_CACHE_V2 is not None:
        return _GENOME_CACHE_V2
    pk = f"{USER_PREFIX}genome"
    kwargs = {"KeyConditionExpression": Key("pk").eq(pk)}
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if not resp.get("LastEvaluatedKey"):
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    _GENOME_CACHE_V2 = decimal_to_float(items)
    return _GENOME_CACHE_V2


def _query_all_lab_draws():
    """Query all blood draw items from labs source, sorted chronologically."""
    pk = f"{USER_PREFIX}labs"
    kwargs = {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with("DATE#")}
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if not resp.get("LastEvaluatedKey"):
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return decimal_to_float(sorted(items, key=lambda x: x.get("sk", "")))


def _query_dexa_scans():
    """Query all DEXA scan items, sorted chronologically."""
    pk = f"{USER_PREFIX}dexa"
    kwargs = {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with("DATE#")}
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if not resp.get("LastEvaluatedKey"):
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return decimal_to_float(items)


def _query_lab_meta():
    """Query labs provider metadata items (non-DATE# SKs)."""
    pk = f"{USER_PREFIX}labs"
    kwargs = {"KeyConditionExpression": Key("pk").eq(pk)}
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if not resp.get("LastEvaluatedKey"):
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    all_items = decimal_to_float(items)
    return [i for i in all_items if not i.get("sk", "").startswith("DATE#")]


_GENOME_LAB_XREF = {
    "ldl_c":             ["ABCG8", "SLCO1B1"],
    "cholesterol_total": ["ABCG8"],
    "triglycerides":     ["ADIPOQ"],
    "glucose":           ["FTO", "IRS1", "TCF7L2"],
    "hba1c":             ["FTO", "IRS1", "TCF7L2"],
    "vitamin_d_25oh":    ["VDR", "GC", "CYP2R1"],
    "homocysteine":      ["MTHFR", "MTRR"],
    "ferritin":          ["HFE"],
    "crp_hs":            ["CRP", "IL6"],
    "folate":            ["MTHFR", "MTRR"],
    "vitamin_b12":       ["MTHFR", "MTRR"],
    "omega_3_index":     ["FADS2"],
    "testosterone_total":["SHBG"],
    "apolipoprotein_b":  ["ABCG8", "SLCO1B1"],
}


def _genome_context_for_biomarkers(biomarker_keys):
    """Return genome annotations relevant to a set of biomarker keys."""
    genes_needed = set()
    for bk in biomarker_keys:
        genes_needed.update(_GENOME_LAB_XREF.get(bk, []))
    if not genes_needed:
        return {}
    all_snps = _get_genome_cached()
    relevant = [s for s in all_snps if s.get("gene") in genes_needed]
    if not relevant:
        return {}
    result = {}
    for bk in biomarker_keys:
        genes = _GENOME_LAB_XREF.get(bk, [])
        if not genes:
            continue
        matches = [s for s in relevant if s.get("gene") in genes]
        if matches:
            result[bk] = [{
                "gene": s.get("gene"), "rsid": s.get("rsid"),
                "genotype": s.get("genotype"), "risk_level": s.get("risk_level"),
                "summary": s.get("summary"),
            } for s in matches]
    return result


def _linear_regression(points):
    """Simple OLS on list of (x, y) tuples. Returns slope, intercept, r_squared."""
    n = len(points)
    if n < 2:
        return None, None, None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    mx, my = sum(xs)/n, sum(ys)/n
    ss_xx = sum((x - mx)**2 for x in xs)
    if ss_xx == 0:
        return 0, my, 0
    ss_xy = sum((x - mx)*(y - my) for x, y in zip(xs, ys))
    slope = ss_xy / ss_xx
    intercept = my - slope * mx
    ss_yy = sum((y - my)**2 for y in ys)
    r_sq = (ss_xy**2 / (ss_xx * ss_yy)) if ss_yy > 0 else 0
    return round(slope, 4), round(intercept, 2), round(r_sq, 3)


'''

TOOLS_CODE = '''

# ═══════════════════════════════════════════════════════════════════════════════
# Labs / DEXA / Genome tools (v2.11.0)
# ═══════════════════════════════════════════════════════════════════════════════


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


def tool_get_body_composition_snapshot(args):
    """DEXA scan interpretation with FFMI, posture, Withings anchoring."""
    scans = _query_dexa_scans()
    if not scans:
        return {"error": "No DEXA scans found."}

    scan_date = args.get("date")
    if scan_date:
        scan = next((s for s in scans if s.get("scan_date") == scan_date), None)
        if not scan:
            return {"error": f"No scan for {scan_date}",
                    "available": [s.get("scan_date") for s in scans]}
    else:
        scan = scans[-1]

    bc = scan.get("body_composition", {})
    posture = scan.get("posture")
    interp = scan.get("interpretations", {})

    profile = get_profile()
    height_in = profile.get("height_inches", 72)
    height_m = height_in * 0.0254
    lean_lb = bc.get("lean_mass_lb", 0)
    lean_kg = lean_lb * 0.4536
    weight_lb = bc.get("weight_lb", 0)
    weight_kg = weight_lb * 0.4536

    ffmi = round(lean_kg / (height_m ** 2), 1) if height_m > 0 else None
    ffmi_norm = round(ffmi + 6.1 * (1.80 - height_m), 1) if ffmi else None
    ffmi_class = None
    if ffmi:
        if ffmi >= 25: ffmi_class = "exceptional (near natural limit)"
        elif ffmi >= 22: ffmi_class = "advanced"
        elif ffmi >= 20: ffmi_class = "above average"
        elif ffmi >= 18: ffmi_class = "average"
        else: ffmi_class = "below average"

    vat_g = bc.get("visceral_fat_g") or 999
    ag = bc.get("ag_ratio") or 99
    bmd_t = bc.get("bmd_t_score") or -9

    result = {
        "scan_date": scan.get("scan_date"), "provider": scan.get("provider"),
        "body_composition": {
            "weight_lb": bc.get("weight_lb"), "body_fat_pct": bc.get("body_fat_pct"),
            "fat_mass_lb": bc.get("fat_mass_lb"), "lean_mass_lb": lean_lb,
            "visceral_fat_g": bc.get("visceral_fat_g"),
            "visceral_fat_category": "elite" if vat_g < 500 else ("normal" if vat_g < 1000 else "elevated"),
            "android_fat_pct": bc.get("android_fat_pct"), "gynoid_fat_pct": bc.get("gynoid_fat_pct"),
            "ag_ratio": bc.get("ag_ratio"),
            "ag_status": "optimal" if ag <= 1.0 else ("slightly elevated" if ag <= 1.2 else "elevated"),
            "bmd_t_score": bc.get("bmd_t_score"),
            "bmd_status": "excellent" if bmd_t >= 1.0 else ("normal" if bmd_t >= -1.0 else "low")},
        "derived_metrics": {
            "ffmi": ffmi, "ffmi_normalized": ffmi_norm, "ffmi_classification": ffmi_class,
            "bmi": round(weight_kg / (height_m ** 2), 1) if height_m > 0 else None},
        "interpretations": interp}

    if posture:
        captures = []
        for key in ["capture_1", "capture_2"]:
            cap = posture.get(key, {})
            sag = cap.get("sagittal", {})
            trans = cap.get("transverse", {})
            if sag or trans:
                captures.append({
                    "shoulder_forward_in": sag.get("shoulder_forward_in"),
                    "hip_forward_in": sag.get("hip_forward_in"),
                    "shoulder_rotation_deg": trans.get("shoulder_rotation_deg"),
                    "shoulder_rotation_dir": trans.get("shoulder_rotation_dir")})
        if captures:
            avg_sh = round(sum(c.get("shoulder_forward_in", 0) for c in captures) / len(captures), 1)
            avg_hip = round(sum(c.get("hip_forward_in", 0) for c in captures) / len(captures), 1)
            flags = []
            if avg_sh > 2.0: flags.append("Forward shoulder posture — possible upper-cross syndrome")
            if avg_hip > 2.5: flags.append("Forward hip — possible anterior pelvic tilt")
            result["posture_summary"] = {
                "avg_shoulder_forward_in": avg_sh, "avg_hip_forward_in": avg_hip,
                "primary_rotation": captures[0].get("shoulder_rotation_dir", "unknown"),
                "flags": flags}

    try:
        from datetime import datetime as _dt, timedelta as _td
        today = _dt.now().strftime("%Y-%m-%d")
        week_ago = (_dt.now() - _td(days=7)).strftime("%Y-%m-%d")
        withings = query_source("withings", week_ago, today)
        if withings:
            lw = withings[-1]
            result["withings_current"] = {
                "date": lw.get("date"), "weight_lb": lw.get("weight_lbs"),
                "body_fat_pct": lw.get("body_fat_pct"),
                "weight_delta_since_dexa": round((lw.get("weight_lbs") or 0) - (bc.get("weight_lb") or 0), 1) if lw.get("weight_lbs") else None,
                "note": "Withings bioimpedance is less accurate than DEXA. Use DEXA as calibration anchor."}
    except Exception as e:
        logger.warning(f"Withings anchor failed: {e}")

    return result


def tool_get_health_risk_profile(args):
    """Multi-domain risk synthesis: cardiovascular, metabolic, longevity."""
    domain = args.get("domain")
    draws = _query_all_lab_draws()
    genome = _get_genome_cached()
    genome_snps = [s for s in genome if s.get("sk", "").startswith("GENE#")]
    dexa = _query_dexa_scans()

    from datetime import datetime as _dt, timedelta as _td
    today = _dt.now().strftime("%Y-%m-%d")
    result = {"assessment_date": today}

    def _get_bm(bms, key):
        b = bms.get(key, {})
        return b.get("value_numeric") or b.get("value")

    if not domain or domain == "cardiovascular":
        cv = {"domain": "cardiovascular", "factors": []}
        if draws:
            bms = draws[-1].get("biomarkers", {})
            ldl = _get_bm(bms, "ldl_c"); hdl = _get_bm(bms, "hdl")
            tg = _get_bm(bms, "triglycerides"); tc = _get_bm(bms, "cholesterol_total")
            apob = _get_bm(bms, "apolipoprotein_b"); crp = _get_bm(bms, "crp_hs")

            if isinstance(ldl, (int, float)):
                cv["factors"].append({"marker": "LDL-C", "value": ldl, "unit": "mg/dL",
                    "risk": "elevated" if ldl >= 100 else "optimal",
                    "note": "Attia target <100; <70 if high-risk"})
            if isinstance(hdl, (int, float)):
                cv["factors"].append({"marker": "HDL", "value": hdl, "unit": "mg/dL",
                    "risk": "optimal" if hdl >= 50 else "low"})
            if isinstance(tg, (int, float)) and isinstance(hdl, (int, float)) and hdl > 0:
                r = round(tg / hdl, 2)
                cv["factors"].append({"marker": "TG/HDL ratio", "value": r,
                    "risk": "optimal" if r < 1.0 else ("good" if r < 2.0 else "elevated"),
                    "note": "Insulin resistance proxy — target <1.0"})
            if isinstance(apob, (int, float)):
                cv["factors"].append({"marker": "ApoB", "value": apob, "unit": "mg/dL",
                    "risk": "optimal" if apob < 80 else ("borderline" if apob < 100 else "elevated"),
                    "note": "Best single predictor of atherosclerotic CV risk"})
            if isinstance(crp, (int, float)):
                cv["factors"].append({"marker": "hs-CRP", "value": crp, "unit": "mg/L",
                    "risk": "optimal" if crp < 1.0 else ("borderline" if crp < 3.0 else "elevated")})

        cv_genes = [s for s in genome_snps if s.get("gene") in ("ABCG8", "SLCO1B1")]
        if cv_genes:
            cv["genetic_factors"] = [{"gene": s["gene"], "genotype": s.get("genotype"),
                "risk_level": s.get("risk_level"), "summary": s.get("summary")} for s in cv_genes]

        if dexa:
            vat = dexa[-1].get("body_composition", {}).get("visceral_fat_g")
            if vat is not None:
                cv["factors"].append({"marker": "Visceral fat", "value": vat, "unit": "g",
                    "risk": "elite" if vat < 500 else ("normal" if vat < 1000 else "elevated")})

        try:
            whoop = query_source("whoop", (_dt.now() - _td(days=30)).strftime("%Y-%m-%d"), today, lean=True)
            if whoop:
                hrvs = [d.get("hrv") for d in whoop if d.get("hrv")]
                if hrvs:
                    cv["factors"].append({"marker": "30d avg HRV", "value": round(sum(hrvs)/len(hrvs), 1),
                        "unit": "ms", "note": "Higher = better CV health"})
        except Exception:
            pass

        elevated = sum(1 for f in cv["factors"] if f.get("risk") in ("elevated", "high", "low"))
        cv["overall_risk"] = "elevated" if elevated >= 2 else ("borderline" if elevated == 1 else "low")
        result["cardiovascular"] = cv

    if not domain or domain == "metabolic":
        met = {"domain": "metabolic", "factors": []}
        if draws:
            bms = draws[-1].get("biomarkers", {})
            glu = _get_bm(bms, "glucose"); a1c = _get_bm(bms, "hba1c")

            if isinstance(glu, (int, float)):
                met["factors"].append({"marker": "Fasting glucose", "value": glu, "unit": "mg/dL",
                    "risk": "optimal" if glu < 90 else ("borderline" if glu < 100 else "elevated"),
                    "note": "Attia optimal <90"})
                glu_trend = [{"date": d.get("draw_date"), "value": _get_bm(d.get("biomarkers", {}), "glucose")}
                             for d in draws if isinstance(_get_bm(d.get("biomarkers", {}), "glucose"), (int, float))]
                if len(glu_trend) >= 2:
                    met["factors"][-1]["trend"] = glu_trend

            if isinstance(a1c, (int, float)):
                met["factors"].append({"marker": "HbA1c", "value": a1c, "unit": "%",
                    "risk": "optimal" if a1c < 5.4 else ("borderline" if a1c < 5.7 else "prediabetic" if a1c < 6.5 else "diabetic"),
                    "note": "Attia optimal <5.4"})

        fto = [s for s in genome_snps if s.get("gene") == "FTO"]
        irs = [s for s in genome_snps if s.get("gene") == "IRS1"]
        if fto or irs:
            met["genetic_factors"] = []
            if fto:
                unfav = sum(1 for s in fto if s.get("risk_level") == "unfavorable")
                met["genetic_factors"].append({"cluster": "FTO obesity variants", "total": len(fto),
                    "unfavorable": unfav, "implication": "Exercise + protein + PUFA mitigate risk"})
            for s in irs:
                met["genetic_factors"].append({"gene": s["gene"], "genotype": s.get("genotype"),
                    "risk_level": s.get("risk_level"), "summary": s.get("summary")})

        if dexa:
            bc = dexa[-1].get("body_composition", {})
            bf = bc.get("body_fat_pct"); ag = bc.get("ag_ratio")
            if bf is not None:
                met["factors"].append({"marker": "Body fat %", "value": bf, "source": "DEXA",
                    "risk": "lean" if bf < 15 else ("healthy" if bf < 20 else "elevated")})
            if ag is not None:
                met["factors"].append({"marker": "A/G ratio", "value": ag, "source": "DEXA",
                    "risk": "optimal" if ag <= 1.0 else "slightly elevated",
                    "note": "Target <=1.0"})

        elevated = sum(1 for f in met["factors"] if f.get("risk") in ("elevated", "prediabetic", "diabetic"))
        met["overall_risk"] = "elevated" if elevated >= 2 else ("borderline" if elevated == 1 else "low")
        result["metabolic"] = met

    if not domain or domain == "longevity":
        lon = {"domain": "longevity", "factors": []}

        if dexa:
            bc = dexa[-1].get("body_composition", {})
            bmd = bc.get("bmd_t_score")
            if bmd is not None:
                lon["factors"].append({"marker": "BMD T-score", "value": bmd,
                    "risk": "excellent" if bmd >= 1.0 else ("normal" if bmd >= -1.0 else "low"),
                    "note": "Critical for fracture risk in aging"})
            lean_lb = bc.get("lean_mass_lb", 0)
            profile = get_profile()
            height_m = profile.get("height_inches", 72) * 0.0254
            if lean_lb and height_m > 0:
                ffmi = round((lean_lb * 0.4536) / (height_m ** 2), 1)
                lon["factors"].append({"marker": "FFMI", "value": ffmi,
                    "risk": "excellent" if ffmi >= 22 else ("good" if ffmi >= 20 else "average"),
                    "note": "Muscle mass protects against all-cause mortality"})

        if draws:
            a1c_vals = [_get_bm(d.get("biomarkers", {}), "hba1c") for d in draws]
            a1c_vals = [v for v in a1c_vals if isinstance(v, (int, float))]
            if a1c_vals:
                lon["factors"].append({"marker": "HbA1c range", "value": f"{min(a1c_vals)}-{max(a1c_vals)}%",
                    "risk": "optimal" if max(a1c_vals) < 5.4 else "monitor"})

        telo = [s for s in genome_snps if "telomere" in (s.get("summary", "") + " " + s.get("category", "")).lower()]
        if telo:
            unfav = sum(1 for s in telo if s.get("risk_level") == "unfavorable")
            lon["genetic_factors"] = {"telomere_variants": len(telo), "unfavorable": unfav,
                "mitigations": ["stress reduction", "omega-3", "exercise", "sleep optimization"]}

        try:
            whoop = query_source("whoop", (_dt.now() - _td(days=90)).strftime("%Y-%m-%d"), today, lean=True)
            if whoop:
                hrvs = [d.get("hrv") for d in whoop if d.get("hrv")]
                if hrvs:
                    lon["factors"].append({"marker": "90d avg HRV", "value": round(sum(hrvs)/len(hrvs), 1),
                        "unit": "ms", "note": "Higher HRV correlates with longevity"})
        except Exception:
            pass

        good = len([f for f in lon["factors"] if f.get("risk") in ("excellent", "optimal")])
        lon["overall_assessment"] = "strong" if good >= 2 else "moderate"
        result["longevity"] = lon

    return result


def tool_get_next_lab_priorities(args):
    """Genome-informed recommendations for next blood panel."""
    genome = _get_genome_cached()
    genome_snps = [s for s in genome if s.get("sk", "").startswith("GENE#")]
    draws = _query_all_lab_draws()

    recs = []
    existing = set()
    latest_date = None
    if draws:
        latest_date = draws[-1].get("draw_date")
        for d in draws:
            existing.update(d.get("biomarkers", {}).keys())

    mthfr = [s for s in genome_snps if s.get("gene") in ("MTHFR", "MTRR")]
    if mthfr:
        recs.append({"test": "Homocysteine", "priority": "high",
            "reason": f"MTHFR/MTRR variants ({len(mthfr)} SNPs) — impaired methylation",
            "already_tested": "homocysteine" in existing,
            "genome_drivers": [f"{s['gene']} {s['rsid']} ({s['genotype']})" for s in mthfr],
            "action": "Monitor quarterly; supplement 5-methylfolate + methylcobalamin"})

    vdr = [s for s in genome_snps if s.get("gene") in ("VDR", "GC", "CYP2R1")]
    if vdr:
        has_vitd = any(k for k in existing if "vitamin_d" in k or "25oh" in k)
        recs.append({"test": "Vitamin D (25-OH)", "priority": "high",
            "reason": f"Triple deficiency risk — {len(vdr)} SNPs across VDR/GC/CYP2R1",
            "already_tested": has_vitd,
            "genome_drivers": [f"{s['gene']} {s['rsid']} ({s['genotype']})" for s in vdr],
            "action": "Target 50-80 ng/mL with D3+K2", "cadence": "quarterly"})

    fads = [s for s in genome_snps if s.get("gene") == "FADS2"]
    if fads:
        recs.append({"test": "Omega-3 Index", "priority": "high",
            "reason": "FADS2 — poor ALA→EPA conversion; need direct EPA/DHA",
            "already_tested": any(k for k in existing if "omega" in k),
            "genome_drivers": [f"{s['gene']} {s['rsid']} ({s['genotype']})" for s in fads],
            "action": "Target index >8%; supplement EPA/DHA directly"})

    slco = [s for s in genome_snps if s.get("gene") == "SLCO1B1"]
    if slco:
        recs.append({"test": "CK + liver enzymes (pre-statin baseline)", "priority": "medium",
            "reason": "SLCO1B1 statin sensitivity",
            "genome_drivers": [f"{s['gene']} {s['rsid']} ({s['genotype']})" for s in slco],
            "action": "If statins needed: rosuvastatin/pravastatin only + CoQ10"})

    choline = [s for s in genome_snps if "choline" in (s.get("summary", "") + " " + str(s.get("actionable_recs", ""))).lower()]
    if choline:
        recs.append({"test": "Choline / Betaine / TMAO", "priority": "medium",
            "reason": f"{len(choline)} choline-related variants",
            "action": "Increase dietary choline or supplement phosphatidylcholine"})

    if draws:
        ldl_flags = sum(1 for d in draws if "ldl_c" in d.get("out_of_range", []))
        if ldl_flags >= 2:
            recs.append({"test": "NMR LipoProfile (advanced lipid panel)", "priority": "high",
                "reason": f"LDL-C flagged {ldl_flags}/{len(draws)} draws",
                "action": "LDL particle count + size — more predictive than LDL-C alone",
                "genome_note": "ABCG8 T;T explains genetic LDL elevation"})

    recs.append({"test": "CMP + CBC + HbA1c + lipids", "priority": "routine",
        "reason": "Baseline monitoring", "cadence": "annually", "last_tested": latest_date})

    priority_order = {"high": 0, "medium": 1, "routine": 2}
    return {
        "total_recommendations": len(recs), "latest_draw": latest_date,
        "total_historical_draws": len(draws), "genome_snps_analyzed": len(genome_snps),
        "recommendations": sorted(recs, key=lambda r: priority_order.get(r.get("priority", "routine"), 3)),
        "note": "Data-driven suggestions based on genome + lab history. Discuss with physician."}


'''

REGISTRY_CODE = '''    "get_lab_results": {
        "fn": tool_get_lab_results,
        "schema": {
            "name": "get_lab_results",
            "description": (
                "Get blood work results. Without a date, returns summary of all 7 draws (2019-2025). "
                "With a date, returns full biomarkers with genome cross-reference annotations. "
                "Filter by category: lipids, cbc, metabolic, thyroid, liver, kidney, etc. "
                "Use for: 'show my latest blood work', 'lipids in 2024', 'all lab draws'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "draw_date": {"type": "string", "description": "Draw date YYYY-MM-DD. Omit to list all."},
                    "category":  {"type": "string", "description": "Filter: lipids, cbc, metabolic, thyroid, liver, kidney, electrolytes, minerals, diabetes, hormones, etc."},
                },
                "required": [],
            },
        },
    },
    "get_lab_trends": {
        "fn": tool_get_lab_trends,
        "schema": {
            "name": "get_lab_trends",
            "description": (
                "Track biomarker trajectory across all 7 draws (2019-2025). Slope per year, 1-year projection, "
                "derived ratios (TG/HDL, non-HDL, TC/HDL). Genome flags for genetic drivers. "
                "Use for: 'LDL trend', 'cholesterol trajectory', 'is glucose rising', 'TG/HDL ratio over time'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "biomarker":  {"type": "string", "description": "Single key: 'ldl_c', 'hba1c', 'glucose'. Use search_biomarker to find names."},
                    "biomarkers": {"type": "array", "items": {"type": "string"}, "description": "Multiple keys."},
                    "include_derived_ratios": {"type": "boolean", "description": "Include TG/HDL, non-HDL, TC/HDL. Default true."},
                },
                "required": [],
            },
        },
    },
    "get_out_of_range_history": {
        "fn": tool_get_out_of_range_history,
        "schema": {
            "name": "get_out_of_range_history",
            "description": (
                "All out-of-range biomarkers across draws with persistence (chronic/recurring/occasional) "
                "and genome-driven explanations. Use for: 'flagged biomarkers', 'persistent issues', 'genetic vs lifestyle flags'."
            ),
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
    },
    "search_biomarker": {
        "fn": tool_search_biomarker,
        "schema": {
            "name": "search_biomarker",
            "description": (
                "Free-text biomarker search across all draws. Values over time + trend. "
                "Use when you don't know the exact key. 'find cholesterol', 'search thyroid', 'iron markers'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search term: 'cholesterol', 'thyroid', 'liver', 'iron'."},
                },
                "required": ["query"],
            },
        },
    },
    "get_genome_insights": {
        "fn": tool_get_genome_insights,
        "schema": {
            "name": "get_genome_insights",
            "description": (
                "Query 110 genome SNPs by category/risk/gene. Cross-reference with labs or nutrition. "
                "Categories: metabolism, cardiovascular, nutrients, methylation, inflammation, longevity, etc. "
                "Risks: unfavorable, mixed, neutral, favorable. "
                "Use for: 'genome metabolism', 'unfavorable SNPs', 'FTO variants', 'genome + labs cross-ref'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "category":        {"type": "string", "description": "SNP category filter."},
                    "risk_level":      {"type": "string", "description": "unfavorable, mixed, neutral, favorable."},
                    "gene":            {"type": "string", "description": "Gene name: FTO, MTHFR, ABCG8."},
                    "cross_reference": {"type": "string", "description": "'labs' or 'nutrition' for cross-ref data."},
                },
                "required": [],
            },
        },
    },
    "get_body_composition_snapshot": {
        "fn": tool_get_body_composition_snapshot,
        "schema": {
            "name": "get_body_composition_snapshot",
            "description": (
                "DEXA scan: FFMI, visceral fat, BMD, A/G ratio, posture analysis, Withings delta. "
                "Use for: 'DEXA results', 'body composition', 'FFMI', 'posture', 'weight change since DEXA'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Scan date YYYY-MM-DD. Omit for latest."},
                },
                "required": [],
            },
        },
    },
    "get_health_risk_profile": {
        "fn": tool_get_health_risk_profile,
        "schema": {
            "name": "get_health_risk_profile",
            "description": (
                "Health risk synthesis: cardiovascular, metabolic, longevity. Combines 7 lab draws, "
                "110 genome SNPs, DEXA, wearable HRV into unified assessment. "
                "Use for: 'health risk profile', 'CV risk', 'metabolic health', 'longevity assessment'."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "'cardiovascular', 'metabolic', 'longevity'. Omit for all."},
                },
                "required": [],
            },
        },
    },
    "get_next_lab_priorities": {
        "fn": tool_get_next_lab_priorities,
        "schema": {
            "name": "get_next_lab_priorities",
            "description": (
                "Genome-informed next blood panel recommendations. Tests to add based on genetic risk, "
                "persistent flags, and gaps. Priority levels + rationale. "
                "Use for: 'what to test next', 'plan next blood draw', 'missing tests'."
            ),
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
    },
'''


# ═══════════════════════════════════════════════════════════════════════════════
# PATCHER LOGIC
# ═══════════════════════════════════════════════════════════════════════════════

def apply():
    if not os.path.exists(MCP_PATH):
        print(f"ERROR: {MCP_PATH} not found.")
        sys.exit(1)

    with open(MCP_PATH, "r") as f:
        code = f.read()

    if "tool_get_lab_results" in code:
        print("ERROR: Labs tools already present. Aborting.")
        sys.exit(1)

    original_len = len(code)

    # 1. Update SOURCES
    old_src = 'SOURCES = ["whoop", "withings", "strava", "todoist", "apple_health", "hevy", "eightsleep", "chronicling", "macrofactor", "garmin", "habitify"]'
    new_src = 'SOURCES = ["whoop", "withings", "strava", "todoist", "apple_health", "hevy", "eightsleep", "chronicling", "macrofactor", "garmin", "habitify", "labs", "dexa", "genome"]'
    if old_src not in code:
        print("ERROR: Cannot find SOURCES line.")
        sys.exit(1)
    code = code.replace(old_src, new_src)
    print("  [1/4] SOURCES 11 → 14")

    # 2. Insert helpers + tools before registry
    anchor = "# ── Tool registry ─"
    if anchor not in code:
        print(f"ERROR: Cannot find '{anchor}'")
        sys.exit(1)
    code = code.replace(anchor, HELPERS_CODE + TOOLS_CODE + "\n" + anchor)
    print("  [2/4] Helpers + 8 tools inserted")

    # 3. Insert registry entries
    reg_anchor = "}\n\n\n# ── MCP protocol handlers"
    if reg_anchor not in code:
        print("ERROR: Cannot find registry anchor")
        sys.exit(1)
    code = code.replace(reg_anchor, REGISTRY_CODE + "}\n\n\n# ── MCP protocol handlers")
    print("  [3/4] 8 registry entries inserted")

    # 4. Version bump
    code = code.replace('"version": "2.8.0"', '"version": "2.11.0"')
    print("  [4/4] Version → 2.11.0")

    with open(MCP_PATH, "w") as f:
        f.write(code)

    # Verify
    tool_count = code.count('"fn":')
    new_tools = sum(1 for t in ["tool_get_lab_results", "tool_get_lab_trends",
                                 "tool_get_out_of_range_history", "tool_search_biomarker",
                                 "tool_get_genome_insights", "tool_get_body_composition_snapshot",
                                 "tool_get_health_risk_profile", "tool_get_next_lab_priorities"]
                    if t in code)
    helpers = sum(1 for h in ["_get_genome_cached", "_query_all_lab_draws",
                               "_query_dexa_scans", "_query_lab_meta",
                               "_genome_context_for_biomarkers", "_linear_regression",
                               "_GENOME_LAB_XREF"]
                  if h in code)

    print()
    print(f"  ✅ Patched: {MCP_PATH}")
    print(f"     Size: {len(code):,} bytes (+{len(code) - original_len:,})")
    print(f"     Tools: {tool_count}")
    print(f"     New tools: {new_tools}/8")
    print(f"     Helpers: {helpers}/7")


def dry_run():
    if not os.path.exists(MCP_PATH):
        print(f"ERROR: {MCP_PATH} not found.")
        sys.exit(1)

    with open(MCP_PATH, "r") as f:
        code = f.read()

    current = code.count('"fn":')
    print("DRY RUN — patch_labs_genome_tools.py")
    print(f"  Target: {MCP_PATH}")
    print(f"  Current tools: {current}")
    print(f"  After patch: {current + 8}")
    print(f"  Version: 2.8.0 → 2.11.0")
    print(f"  SOURCES: 11 → 14")
    print()
    for t in ["get_lab_results", "get_lab_trends", "get_out_of_range_history",
              "search_biomarker", "get_genome_insights", "get_body_composition_snapshot",
              "get_health_risk_profile", "get_next_lab_priorities"]:
        print(f"    + {t}")
    print()
    print("  Run with --apply to patch.")


if __name__ == "__main__":
    if "--apply" in sys.argv:
        print()
        print("═══════════════════════════════════════════════")
        print(" Patching MCP server → v2.11.0")
        print("═══════════════════════════════════════════════")
        print()
        apply()
    else:
        dry_run()
