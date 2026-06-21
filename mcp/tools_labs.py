"""
Lab results, genome, DEXA tools.
"""

# ── SEC-GENOME: Privacy guardrail for public content ─────────────────────────
# Raw genome identifiers (gene names, rsIDs, genotypes) must NEVER appear
# in any public-facing content: chronicle posts, daily brief excerpts,
# public_stats.json, site API responses, or email digests.
#
# ALLOWED in public content:
#   "genetic predisposition to obesity"
#   "variants affecting vitamin D metabolism"
#   "genomic data suggests elevated LDL baseline"
#
# NEVER in public content:
#   "FTO rs9939609 A;T"
#   "MTHFR compound heterozygous"
#   "SLCO1B1 C;T — 4.5x statin myopathy risk"
#
# This notice is appended to all genome-bearing tool outputs.
# ─────────────────────────────────────────────────────────────────────────────
_GENOME_PRIVACY_NOTICE = (
    "PRIVACY GUARDRAIL: This data contains raw genome identifiers (gene names, "
    "rsIDs, genotypes). These must NEVER appear in any public-facing content "
    "including chronicle posts, daily briefs, emails, site API responses, or "
    "public_stats.json. When referencing genome insights in public content, use "
    "non-specific language only (e.g. 'genetic predisposition to X', 'genomic "
    "variants affecting Y metabolism'). Never publish specific gene names, "
    "rsID numbers, or genotype strings (e.g. 'A;T', 'C;C'). This data is for "
    "private MCP use and Matthew's personal reference only."
)

import json
import logging
import math
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from mcp.config import (
    EXPERIMENTS_PK,
    FIELD_ALIASES,
    INSIGHTS_PK,
    P40_GROUPS,
    S3_BUCKET,
    SOURCES,
    TRAVEL_PK,
    USER_ID,
    USER_PREFIX,
    logger,
    s3_client,
    table,
)
from mcp.core import (
    date_diff_days,
    ddb_cache_get,
    ddb_cache_set,
    decimal_to_float,
    get_profile,
    get_sot,
    mem_cache_get,
    mem_cache_set,
    parallel_query_sources,
    query_source,
    query_source_range,
    resolve_field,
)
from mcp.helpers import (
    _habit_series,
    _linear_regression,
    aggregate_items,
    classify_day_type,
    compute_daily_load_score,
    compute_ewa,
    flatten_strava_activity,
    pearson_r,
    query_chronicling,
)
from mcp.labs_helpers import (
    _GENOME_LAB_XREF,
    _genome_context_for_biomarkers,
    _get_genome_cached,
    _query_all_lab_draws,
    _query_dexa_scans,
    _query_lab_meta,
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
            summaries.append(
                {
                    "draw_date": d.get("draw_date"),
                    "provider": d.get("lab_provider"),
                    "lab_network": d.get("lab_network"),
                    "fasting": d.get("fasting"),
                    "total_biomarkers": d.get("total_biomarkers"),
                    "out_of_range_count": d.get("out_of_range_count"),
                    "out_of_range": d.get("out_of_range", []),
                }
            )
        return {"total_draws": len(draws), "draws": summaries, "hint": "Pass draw_date to see full biomarkers for a specific draw."}

    draw = next((d for d in draws if d.get("draw_date") == draw_date), None)
    if not draw:
        return {"error": f"No draw for {draw_date}", "available_dates": [d.get("draw_date") for d in draws]}

    biomarkers = draw.get("biomarkers", {})
    if category:
        biomarkers = {k: v for k, v in biomarkers.items() if v.get("category") == category}

    genome_ctx = _genome_context_for_biomarkers(list(biomarkers.keys()))
    categories = sorted(set(v.get("category", "") for v in draw.get("biomarkers", {}).values()))

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
                    points.append(
                        {
                            "date": date,
                            "value": round(val, 2),
                            "flag": bms[bm_key].get("flag", "normal"),
                            "ref": bms[bm_key].get("ref_text", ""),
                            "unit": bms[bm_key].get("unit", ""),
                        }
                    )
        if not points:
            trends[bm_key] = {"error": f"No data for '{bm_key}'", "hint": "Use search_biomarker to find valid names."}
            continue

        base = _dt.strptime(points[0]["date"], "%Y-%m-%d")
        reg_pts = [((_dt.strptime(p["date"], "%Y-%m-%d") - base).days, p["value"]) for p in points]
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
            "values": points,
            "data_points": len(points),
            "direction": direction,
            "slope_per_year": slope_per_year,
            "r_squared": r_sq,
            "projected_1yr": projected_1yr,
            "latest": points[-1]["value"],
            "earliest": points[0]["value"],
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
                derived.setdefault("tg_hdl_ratio", []).append(
                    {
                        "date": date,
                        "value": round(tg_v / hdl_v, 2),
                        "interpretation": "optimal <1.0, good <2.0, elevated >=2.0 (insulin resistance proxy)",
                    }
                )
            if isinstance(tc_v, (int, float)) and isinstance(hdl_v, (int, float)):
                derived.setdefault("non_hdl_cholesterol", []).append(
                    {"date": date, "value": round(tc_v - hdl_v, 1), "interpretation": "optimal <130, borderline 130-159, high >=160"}
                )
            if isinstance(tc_v, (int, float)) and isinstance(hdl_v, (int, float)) and hdl_v > 0:
                derived.setdefault("tc_hdl_ratio", []).append(
                    {"date": date, "value": round(tc_v / hdl_v, 2), "interpretation": "optimal <3.5, good <5.0, elevated >=5.0"}
                )

    genome_ctx = _genome_context_for_biomarkers(biomarkers_req)
    result = {"trends": trends, "total_draws": len(draws), "date_range": f"{draws[0].get('draw_date')} to {draws[-1].get('draw_date')}"}
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
                oor_map[key].append(
                    {
                        "date": date,
                        "value": val,
                        "flag": bm_data["flag"],
                        "unit": bm_data.get("unit", ""),
                        "ref_text": bm_data.get("ref_text", ""),
                        "category": bm_data.get("category", ""),
                    }
                )

    total_draws = len(draws)
    flagged = []
    for key, occurrences in sorted(oor_map.items(), key=lambda x: -len(x[1])):
        tested_count = sum(1 for d in draws if key in d.get("biomarkers", {}))
        flagged_rate = round(100 * len(occurrences) / max(tested_count, 1), 1)
        flagged.append(
            {
                "biomarker": key,
                "category": occurrences[0]["category"],
                "times_flagged": len(occurrences),
                "times_tested": tested_count,
                "flag_rate_pct": flagged_rate,
                "persistence": "chronic" if flagged_rate >= 60 else ("recurring" if flagged_rate >= 30 else "occasional"),
                "occurrences": occurrences,
            }
        )

    chronic_keys = [f["biomarker"] for f in flagged if f["persistence"] == "chronic"]
    genome_ctx = _genome_context_for_biomarkers(chronic_keys)

    return {
        "total_draws": total_draws,
        "date_range": f"{draws[0].get('draw_date')} to {draws[-1].get('draw_date')}",
        "flagged_biomarkers": flagged,
        "total_unique_flags": len(flagged),
        "chronic_flags": chronic_keys,
        "genome_drivers": genome_ctx if genome_ctx else None,
        "insight": (
            ("Chronic out-of-range biomarkers with genome drivers suggest genetic baseline " "rather than lifestyle failure.")
            if genome_ctx
            else None
        ),
    }


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
                matches[key].append(
                    {
                        "date": date,
                        "value": val,
                        "flag": bm_data.get("flag", "normal"),
                        "unit": bm_data.get("unit", ""),
                        "ref_text": bm_data.get("ref_text", ""),
                        "category": cat,
                    }
                )

    if not matches:
        all_keys = set()
        for d in draws:
            all_keys.update(d.get("biomarkers", {}).keys())
        return {"error": f"No match for '{query}'", "available_biomarkers": sorted(all_keys)}

    results = []
    for key, values in sorted(matches.items()):
        numeric_vals = [v["value"] for v in values if isinstance(v["value"], (int, float))]
        entry = {
            "biomarker": key,
            "category": values[0]["category"],
            "unit": values[0]["unit"],
            "data_points": len(values),
            "values": values,
        }
        if len(numeric_vals) >= 2:
            entry["latest"] = numeric_vals[-1]
            entry["earliest"] = numeric_vals[0]
            entry["change"] = round(numeric_vals[-1] - numeric_vals[0], 2)
            entry["direction"] = "rising" if entry["change"] > 0.5 else ("falling" if entry["change"] < -0.5 else "stable")
        results.append(entry)

    genome_ctx = _genome_context_for_biomarkers([r["biomarker"] for r in results])
    return {"query": query, "matches": len(results), "results": results, "genome_context": genome_ctx if genome_ctx else None}


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
        entry = {
            "gene": s.get("gene"),
            "rsid": s.get("rsid"),
            "genotype": s.get("genotype"),
            "category": s.get("category"),
            "risk_level": s.get("risk_level"),
            "summary": s.get("summary"),
        }
        if s.get("actionable_recs"):
            entry["actionable_recs"] = s["actionable_recs"]
        if s.get("related_biomarkers"):
            entry["related_biomarkers"] = s["related_biomarkers"]
        snps_out.append(entry)

    result = {
        "total_snps": len(snps_out),
        "filters_applied": {k: v for k, v in {"category": category, "risk_level": risk_level, "gene": gene}.items() if v},
        "snps": snps_out,
    }

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
                    lab_links[bm_key] = {
                        "latest_value": val,
                        "latest_date": latest.get("draw_date"),
                        "flag": bms[bm_key].get("flag"),
                        "unit": bms[bm_key].get("unit"),
                    }
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
                    "period": f"{week_ago} to {today}",
                    "days": len(mf),
                    "avg_calories": round(sum(d.get("total_calories_kcal", 0) for d in mf) / len(mf)),
                    "avg_protein_g": round(sum(d.get("total_protein_g", 0) for d in mf) / len(mf), 1),
                    "avg_fat_g": round(sum(d.get("total_fat_g", 0) for d in mf) / len(mf), 1),
                    "avg_omega3_g": round(sum(d.get("total_omega3_g", 0) for d in mf) / len(mf), 2),
                }
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

    result["_privacy"] = _GENOME_PRIVACY_NOTICE
    return result


def tool_get_labs(args):
    """Unified lab intelligence dispatcher."""
    VALID_VIEWS = {
        "results": tool_get_lab_results,
        "trends": tool_get_lab_trends,
        "out_of_range": tool_get_out_of_range_history,
    }
    view = (args.get("view") or "results").lower().strip()
    if view not in VALID_VIEWS:
        return {
            "error": f"Unknown view '{view}'.",
            "valid_views": list(VALID_VIEWS.keys()),
            "hint": "'results' for latest draws, 'trends' for trajectory, 'out_of_range' for persistent flags.",
        }
    out = VALID_VIEWS[view](args)
    # FH v2 augment (PR 4a, 2026-05-03): always attach cadence_trackers for the
    # annual-or-rarer sentinel panels (NfL, Galleri). Surfaced on every view so
    # callers don't have to remember a separate query.
    if isinstance(out, dict) and "cadence_trackers" not in out:
        try:
            out["cadence_trackers"] = _build_cadence_trackers()
        except Exception as e:
            logger.warning(f"cadence_trackers build failed: {e}")
    return out


# ── FH v2 augments (PR 4a, 2026-05-03) ───────────────────────────────────────
# Tonight decisions per Matthew's docs/specs/FUNCTION_HEALTH_V2_HANDOFF.md:
#   NfL cadence = 180 days (sensitive neurodegeneration baseline; warrants
#                            6-month tracking even though Galleri is annual)
#   Galleri cadence = 365 days (per GRAIL recommendation)
# Galleri framing wording borrowed from the Technical Board version:
#   "No signal detected at 24-month early-detection threshold"
#   instead of the raw "NO CANCER SIGNAL DETECTED" — Viktor's adversarial
#   pushback on framing absence-of-evidence as evidence-of-absence.

NFL_CADENCE_DAYS = 180
GALLERI_CADENCE_DAYS = 365

# ImmunoCAP IgE class boundaries (kU/L). Class 0 = no sensitization; 6 = max.
_IGE_CLASS_BOUNDARIES = [
    (0.10, 0),  # < 0.10 → Class 0
    (0.35, 1),  # 0.10–0.34 → Class 1
    (0.70, 2),  # 0.35–0.69 → Class 2
    (3.50, 3),  # 0.70–3.49 → Class 3
    (17.5, 4),  # 3.50–17.4 → Class 4
    (50.0, 5),  # 17.5–49.9 → Class 5
    # ≥ 50.0 → Class 6
]
_IGE_CLASS_LABELS = {
    0: "No detectable",
    1: "Low",
    2: "Moderate",
    3: "High",
    4: "Very High",
    5: "Extremely High",
    6: "Maximum",
}

# Allergen → category map. Categories used in the get_allergies response.
_ALLERGEN_CATEGORIES = {
    # dust mite
    "dust_mite_d_pteronyssinus": "dust_mite",
    "dust_mite_d_farinae": "dust_mite",
    # environmental pollen
    "alder": "environmental_pollen",
    "birch": "environmental_pollen",
    "oak": "environmental_pollen",
    "elm": "environmental_pollen",
    "mountain_cedar": "environmental_pollen",
    "cottonwood": "environmental_pollen",
    "maple_box_elder": "environmental_pollen",
    "walnut_tree": "environmental_pollen",
    "white_ash": "environmental_pollen",
    "sheep_sorrel": "environmental_pollen",
    "rough_pigweed": "environmental_pollen",
    "common_ragweed": "environmental_pollen",
    "nettle": "environmental_pollen",
    "timothy_grass": "environmental_pollen",
    # dander
    "cat_dander": "dander",
    "dog_dander": "dander",
    "mouse_urine_proteins": "dander",
    # mold
    "aspergillus_fumigatus": "mold",
    "cladosporium_herbarum": "mold",
    "penicillium_notatum": "mold",
    "alternaria_alternata": "mold",
    # other
    "cockroach": "other",
}


def _ige_class(value_kU_L):
    """Map an IgE value (kU/L) to ImmunoCAP class 0–6."""
    if value_kU_L is None:
        return None
    try:
        v = float(value_kU_L)
    except (TypeError, ValueError):
        return None
    for boundary, cls in _IGE_CLASS_BOUNDARIES:
        if v < boundary:
            return cls
    return 6


def _allergen_meta(biomarker_key):
    """Strip 'allergy_' prefix and look up category."""
    base = biomarker_key.replace("allergy_", "", 1)
    return base, _ALLERGEN_CATEGORIES.get(base, "other")


def _build_cadence_trackers():
    """Return cadence-tracker dict for NfL + Galleri. Returns {} if no draws."""
    draws = _query_all_lab_draws()
    if not draws:
        return {}
    today = datetime.now().date()

    def _latest_for(biomarker_key):
        """Find the latest draw containing this biomarker; return (date_str, value, unit) or None."""
        for d in reversed(draws):  # latest-first
            bms = d.get("biomarkers", {})
            if biomarker_key in bms:
                bm = bms[biomarker_key]
                return (
                    d.get("draw_date"),
                    bm.get("value_numeric") or bm.get("value"),
                    bm.get("unit", ""),
                )
        return None

    def _history_for(biomarker_key, value_field):
        """Return chronological history of a biomarker."""
        out = []
        for d in draws:
            bm = d.get("biomarkers", {}).get(biomarker_key)
            if bm:
                entry = {"date": d.get("draw_date")}
                if value_field == "numeric":
                    entry["value"] = bm.get("value_numeric") or bm.get("value")
                    entry["unit"] = bm.get("unit", "")
                else:
                    entry["signal"] = bm.get("value")
                out.append(entry)
        return out

    out = {}

    # NfL — neurodegeneration baseline; 180-day cadence per Matthew tonight
    nfl_latest = _latest_for("nfl_neurofilament_light_chain")
    if nfl_latest:
        last_date_str, last_value, last_unit = nfl_latest
        try:
            last_date = datetime.strptime(last_date_str, "%Y-%m-%d").date()
            days_since = (today - last_date).days
            next_due = (last_date + timedelta(days=NFL_CADENCE_DAYS)).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            days_since = None
            next_due = None
        out["nfl"] = {
            "last_drawn": last_date_str,
            "days_since_last": days_since,
            "recommended_cadence_days": NFL_CADENCE_DAYS,
            "next_due": next_due,
            "history": _history_for("nfl_neurofilament_light_chain", "numeric"),
        }

    # Galleri — annual cancer screen
    gal_latest = _latest_for("galleri_cancer_signal")
    if gal_latest:
        last_date_str, last_signal, _ = gal_latest
        try:
            last_date = datetime.strptime(last_date_str, "%Y-%m-%d").date()
            days_since = (today - last_date).days
            next_due = (last_date + timedelta(days=GALLERI_CADENCE_DAYS)).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            days_since = None
            next_due = None
        # Reframe per Technical Board (Viktor): absence-of-evidence ≠ evidence-of-absence
        signal_str = str(last_signal or "").upper()
        if "NO CANCER" in signal_str or "NO SIGNAL" in signal_str:
            framed_signal = "No signal detected at 24-month early-detection threshold"
        else:
            framed_signal = last_signal
        out["galleri"] = {
            "last_drawn": last_date_str,
            "days_since_last": days_since,
            "recommended_cadence_days": GALLERI_CADENCE_DAYS,
            "next_due": next_due,
            "last_signal": framed_signal,
            "raw_signal": last_signal,
            "history": _history_for("galleri_cancer_signal", "signal"),
        }

    return out


def tool_get_lab_deltas(args):
    """Cross-draw biomarker movement query.

    Args:
        comparison: "year_over_year" (default) | "since_first" | "latest_two"
        threshold: float, minimum |ratio−1| to include (default 0.5 = ±50% movement)
        direction: "any" (default) | "rising" | "falling"
        panel: optional panel filter (e.g. "lipid_standard")
        limit: max number of deltas in response (default 50)
    """
    comparison = (args.get("comparison") or "year_over_year").lower().strip()
    threshold = float(args.get("threshold", 0.5))
    direction = (args.get("direction") or "any").lower().strip()
    panel_filter = args.get("panel")
    limit = int(args.get("limit", 50))

    draws = _query_all_lab_draws()
    if len(draws) < 2:
        return {"error": "Need at least 2 draws to compute deltas", "total_draws": len(draws)}

    latest = draws[-1]
    latest_date_str = latest.get("draw_date")
    latest_date = datetime.strptime(latest_date_str, "%Y-%m-%d").date()

    if comparison == "since_first":
        baseline = draws[0]
    elif comparison == "latest_two":
        baseline = draws[-2]
    elif comparison == "year_over_year":
        # Find the draw closest to (latest - 365 days)
        target = latest_date - timedelta(days=365)
        baseline = min(draws[:-1], key=lambda d: abs((datetime.strptime(d.get("draw_date"), "%Y-%m-%d").date() - target).days))
    else:
        return {"error": f"Unknown comparison '{comparison}'.", "valid_comparisons": ["year_over_year", "since_first", "latest_two"]}

    baseline_date = baseline.get("draw_date")
    latest_bms = latest.get("biomarkers", {})
    baseline_bms = baseline.get("biomarkers", {})

    deltas = []
    new_biomarkers = []  # in latest but not baseline

    for key, bm in latest_bms.items():
        if panel_filter and bm.get("panel") != panel_filter:
            continue
        # Allergy panel uses ordinal class; exclude from numeric deltas (use get_allergies)
        if key.startswith("allergy_") and key != "allergy_total_ige":
            continue

        # Galleri/qualitative: skip if not numeric
        v_to_raw = bm.get("value_numeric")
        if v_to_raw is None:
            continue
        try:
            v_to = float(v_to_raw)
        except (TypeError, ValueError):
            continue

        if key not in baseline_bms:
            new_biomarkers.append(
                {
                    "biomarker": key,
                    "to": v_to,
                    "unit": bm.get("unit", ""),
                    "panel": bm.get("panel", ""),
                    "category": bm.get("category", ""),
                    "out_of_range": bm.get("flag") in ("high", "low"),
                }
            )
            continue

        v_from_raw = baseline_bms[key].get("value_numeric")
        if v_from_raw is None:
            continue
        try:
            v_from = float(v_from_raw)
        except (TypeError, ValueError):
            continue
        if v_from == 0:
            continue  # ratio undefined

        ratio = v_to / v_from
        pct_change = (ratio - 1) * 100
        movement = abs(ratio - 1)
        if movement < threshold:
            continue

        d_dir = "rising" if v_to > v_from else "falling"
        if direction != "any" and direction != d_dir:
            continue

        deltas.append(
            {
                "biomarker": key,
                "from": round(v_from, 4),
                "to": round(v_to, 4),
                "ratio": round(ratio, 3),
                "pct_change": round(pct_change, 1),
                "unit": bm.get("unit", ""),
                "direction": d_dir,
                "panel": bm.get("panel", ""),
                "category": bm.get("category", ""),
                "out_of_range": bm.get("flag") in ("high", "low"),
            }
        )

    # Sort by absolute pct_change descending — biggest movers first
    deltas.sort(key=lambda x: abs(x["pct_change"]), reverse=True)
    deltas = deltas[:limit]

    rising = sum(1 for d in deltas if d["direction"] == "rising")
    falling = sum(1 for d in deltas if d["direction"] == "falling")
    total_compared = sum(
        1
        for k, bm in latest_bms.items()
        if k in baseline_bms
        and bm.get("value_numeric") is not None
        and baseline_bms[k].get("value_numeric") is not None
        and not (k.startswith("allergy_") and k != "allergy_total_ige")
    )

    return {
        "comparison": comparison,
        "threshold": threshold,
        "direction_filter": direction,
        "panel_filter": panel_filter,
        "from_draw": baseline_date,
        "to_draw": latest_date_str,
        "deltas": deltas,
        "new_biomarkers": new_biomarkers,
        "summary": {
            "total_biomarkers_compared": total_compared,
            "moved_above_threshold": len(deltas),
            "rising": rising,
            "falling": falling,
            "new_in_latest": len(new_biomarkers),
        },
    }


# ── DI-2b parity: interior-gap detection (B3) ──
# The staleness check below only sees the newest DATE# per source (the high-water
# mark), so a hole *behind* it — a daily source going dead mid-window then resuming
# — reads green. This mirrors find_interior_gaps in emails/freshness_checker_lambda.py
# (TD-14 parity discipline: keep the two in sync). Sparse sources (strava, withings,
# food_delivery, measurements) have legitimate empty days → excluded here.
DAILY_SOURCES_INTERIOR = {"whoop", "apple_health", "eightsleep", "habitify"}
INTERIOR_GAP_WINDOW_DAYS = 14


def find_interior_gaps(present_dates, window_start: str, window_end: str) -> list:
    """Missing dates strictly inside the [first, last] present span in the window.

    Only the span between the earliest and latest present date is judged — a
    trailing or leading absence is recency (handled by the staleness check), not
    an interior hole. Returns a sorted list of 'YYYY-MM-DD'. Needs >=2 present
    dates to define an interior at all. Pure function — no AWS, no network.
    """
    present = sorted(d for d in present_dates if window_start <= d <= window_end)
    if len(present) < 2:
        return []
    pset = set(present)
    cur = datetime.strptime(present[0], "%Y-%m-%d").date()
    hi = datetime.strptime(present[-1], "%Y-%m-%d").date()
    gaps = []
    while cur <= hi:
        s = cur.isoformat()
        if s not in pset:  # lo/hi are present, so anything missing here is interior
            gaps.append(s)
        cur += timedelta(days=1)
    return gaps


def tool_get_freshness_status(args):
    """Per-source data freshness summary (WR-48 Enhancement 4, PR-reentry-4).

    Independently computes staleness per source by querying the latest DATE# sk
    from each source partition — does NOT depend on the freshness-checker Lambda
    having run recently. Returns a status (green / yellow / orange / red) plus
    per-source last-date / age-days / threshold.

    Mirror of lambdas/freshness_checker_lambda.py SOURCES + SOURCE_STALE_HOURS
    (kept in sync manually; see TD-14 parity discipline).

    Args (all optional):
        sources: list[str] — restrict to these source keys; default = all 11
    """
    from datetime import date as _date

    # DI-1.1: legible source-state (live/paused/rate_limited/stale) so a deliberately-off
    # source (Strava) or a rate-limited one (Garmin) is never mistaken for silent breakage.
    from source_state import has_rate_limit_marker, resolve_source_state

    SOURCES = {
        "whoop": "Whoop recovery/sleep",
        "withings": "Withings weight/body comp",
        "strava": "Strava activities",
        "todoist": "Todoist tasks",
        "apple_health": "Apple Health",
        "eightsleep": "Eight Sleep",
        "macrofactor": "MacroFactor nutrition",
        "garmin": "Garmin biometrics",
        "habitify": "Habitify habits",
        "food_delivery": "Food delivery behavioral signal",
        "measurements": "Tape measure check-ins",
        "notion": "Notion journal",
    }
    SOURCE_STALE_HOURS = {
        "food_delivery": 90 * 24,
        "measurements": 60 * 24,
    }
    DEFAULT_STALE_HOURS = 48

    requested = args.get("sources") if args else None
    if requested:
        keys = [s for s in requested if s in SOURCES]
    else:
        keys = list(SOURCES.keys())

    today = datetime.now(timezone.utc).date()
    per_source = []
    stale_count = 0
    partial_count = 0  # we don't compute partial here — just stale

    for src in keys:
        threshold_hours = SOURCE_STALE_HOURS.get(src, DEFAULT_STALE_HOURS)
        threshold_days = threshold_hours / 24
        # Latest sk for this partition
        from boto3.dynamodb.conditions import Key as DDBKey

        pk = f"USER#matthew#SOURCE#{src}"
        try:
            resp = table.query(
                KeyConditionExpression=DDBKey("pk").eq(pk) & DDBKey("sk").begins_with("DATE#"),
                Limit=1,
                ScanIndexForward=False,
            )
        except Exception as e:
            per_source.append(
                {
                    "source": src,
                    "label": SOURCES[src],
                    "status": "unknown",
                    "error": str(e),
                }
            )
            continue
        _rl = has_rate_limit_marker(table, "matthew", src)
        items = resp.get("Items", [])
        if not items:
            per_source.append(
                {
                    "source": src,
                    "label": SOURCES[src],
                    "status": "no_data",
                    "source_state": resolve_source_state(src, None, today.isoformat(), rate_limited=_rl),
                    "threshold_days": threshold_days,
                }
            )
            stale_count += 1
            continue
        sk = items[0].get("sk", "")
        if not sk.startswith("DATE#"):
            continue
        try:
            d = datetime.strptime(sk.split("DATE#", 1)[1][:10], "%Y-%m-%d").date()
        except (ValueError, IndexError):
            continue
        age_days = (today - d).days
        is_stale = age_days >= threshold_days
        if is_stale:
            stale_count += 1
        per_source.append(
            {
                "source": src,
                "label": SOURCES[src],
                "last_date": d.isoformat(),
                "age_days": age_days,
                "threshold_days": int(threshold_days),
                "status": "stale" if is_stale else "fresh",
                "source_state": resolve_source_state(src, d.isoformat(), today.isoformat(), rate_limited=_rl),
            }
        )

    # Status escalation tiers (WR-48 Enhancement 2 logic, used here for reporting only)
    max_age_stale = max(
        (s["age_days"] for s in per_source if s.get("status") == "stale"),
        default=0,
    )
    if stale_count == 0:
        overall = "green"
    elif stale_count == 1 and max_age_stale < 7:
        overall = "yellow"
    elif stale_count >= 3 or max_age_stale > 14:
        overall = "red"
    else:
        overall = "orange"

    stale_sources = [s for s in per_source if s.get("status") in ("stale", "no_data")]
    fresh_sources = [s for s in per_source if s.get("status") == "fresh"]

    # ── MacroFactor format-drift (meal-grouping guard) ──
    # The diary export carries per-food timestamps (entries_count > 0); the daily-
    # summary export is one row/day with an empty food_log (entries_count == 0). When
    # MacroFactor silently reverts to summary format, the meal grouper has no input
    # and the meal view goes stale without a staleness alert (the date is still fresh).
    # Flag when the last N records all have entries_count == 0.
    macro_drift = None
    if "macrofactor" in keys:
        from boto3.dynamodb.conditions import Key as _DDBKey

        try:
            _resp = table.query(
                KeyConditionExpression=_DDBKey("pk").eq("USER#matthew#SOURCE#macrofactor") & _DDBKey("sk").begins_with("DATE#"),
                ScanIndexForward=False,
                Limit=5,
                ProjectionExpression="#d, entries_count",
                ExpressionAttributeNames={"#d": "date"},
            )
            recs = _resp.get("Items", [])
            empties = [r for r in recs if int(r.get("entries_count", 0) or 0) == 0]
            last_with_log = next((r.get("date") for r in recs if int(r.get("entries_count", 0) or 0) > 0), None)
            drifted = bool(recs) and len(empties) == len(recs)
            macro_drift = {
                "drifted": drifted,
                "records_checked": len(recs),
                "consecutive_empty": len(empties),
                "last_food_log_date": last_with_log,
                "note": (
                    "MacroFactor diary export appears to have reverted to daily-summary (empty food_log) — "
                    "the meal grouper is starved. Re-export the diary format."
                    if drifted
                    else "Diary export healthy (recent records carry a food_log)."
                ),
            }
        except Exception as _e:  # noqa: BLE001
            macro_drift = {"drifted": None, "error": str(_e)}

    # ── Training-notes extractor silent-failure guard (notes feedback loop §8) ──
    # Notes present but no derived records (or all degraded) = the extractor went dark.
    training_notes_health = None
    try:
        from training_notes import training_notes_health as _tnh

        training_notes_health = _tnh(table)
    except Exception as _e:  # noqa: BLE001
        training_notes_health = {"checked": False, "error": str(_e)}

    # ── B3: interior-gap scan (daily sources only) ──
    # A daily source can read "fresh" (newest record present) while a mid-window day
    # is silently missing behind the high-water mark — the exact blindness that hid
    # the Strava walks. Scan the trailing window for each daily source and surface
    # holes inside its present span.
    from boto3.dynamodb.conditions import Key as _GapKey

    _gap_end = today.isoformat()
    _gap_start = (today - timedelta(days=INTERIOR_GAP_WINDOW_DAYS)).isoformat()
    interior_gaps: dict[str, list] = {}
    for _src in keys:
        if _src not in DAILY_SOURCES_INTERIOR:
            continue
        try:
            _gresp = table.query(
                KeyConditionExpression=(
                    _GapKey("pk").eq(f"USER#matthew#SOURCE#{_src}") & _GapKey("sk").between(f"DATE#{_gap_start}", f"DATE#{_gap_end}~")
                ),
                ProjectionExpression="sk",
            )
            _present = []
            for _it in _gresp.get("Items", []):
                _sk = _it.get("sk", "")
                if _sk.startswith("DATE#"):
                    _present.append(_sk.split("DATE#", 1)[1][:10])
            _gaps = find_interior_gaps(_present, _gap_start, _gap_end)
            if _gaps:
                interior_gaps[_src] = _gaps
        except Exception as _e:  # noqa: BLE001
            logger.warning("interior-gap scan failed for %s: %s", _src, _e)
    interior_gap_count = sum(len(v) for v in interior_gaps.values())

    return {
        "status": overall,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "stale_count": stale_count,
        "fresh_count": len(fresh_sources),
        "stale_sources": stale_sources,
        "fresh_sources": fresh_sources,
        "interior_gaps": interior_gaps,
        "interior_gap_count": interior_gap_count,
        "macrofactor_format_drift": macro_drift,
        "training_notes_health": training_notes_health,
        "thresholds_note": (
            f"Default threshold {DEFAULT_STALE_HOURS}h. "
            f"food_delivery={SOURCE_STALE_HOURS['food_delivery']//24}d, "
            f"measurements={SOURCE_STALE_HOURS['measurements']//24}d. "
            "Mirrors freshness_checker_lambda.py."
        ),
        "context": ("Status tiers: green (all fresh) / yellow (1 stale <7d) / " "orange (mixed) / red (3+ stale OR any >14d)."),
    }


def tool_get_allergies(args):
    """Allergy panel surface — ordinal IgE class semantics, grouped by category.

    Args:
        draw_date: optional YYYY-MM-DD. Default = latest draw with allergy data.
        min_class: int 0–6 (default 1). Filter out below this class.
        category: optional str. "dust_mite" | "environmental_pollen" | "dander" |
                  "mold" | "other" | None=all.
    """
    draw_date = args.get("draw_date")
    min_class = int(args.get("min_class", 1))
    category_filter = args.get("category")

    draws = _query_all_lab_draws()
    if not draws:
        return {"error": "No lab draws found"}

    # Latest draw with allergy data
    if draw_date:
        target = next((d for d in draws if d.get("draw_date") == draw_date), None)
        if not target:
            return {"error": f"No draw for {draw_date}", "available_dates": [d.get("draw_date") for d in draws]}
    else:
        target = None
        for d in reversed(draws):
            if any(k.startswith("allergy_") for k in d.get("biomarkers", {})):
                target = d
                break
        if not target:
            return {
                "error": "No draw with allergy panel data found",
                "hint": "Function Health 2026 (2026-04-03) was the first draw with the allergy panel.",
            }

    bms = target.get("biomarkers", {})
    sensitizations = []
    total_ige_obj = None

    for key, bm in bms.items():
        if not key.startswith("allergy_"):
            continue
        if key == "allergy_total_ige":
            v = bm.get("value_numeric")
            ref = bm.get("ref_text", "")
            ref_max = None
            try:
                ref_max = float(ref.replace("<", "").strip()) if ref else None
            except ValueError:
                pass
            x_above = round(float(v) / ref_max, 2) if (v and ref_max and ref_max > 0) else None
            total_ige_obj = {
                "value": v,
                "unit": bm.get("unit", "kU/L"),
                "ref_max": ref_max,
                "x_above_max": x_above,
                "flag": bm.get("flag"),
            }
            continue

        v = bm.get("value_numeric")
        cls = _ige_class(v)
        if cls is None or cls < min_class:
            continue

        allergen_name, cat = _allergen_meta(key)
        if category_filter and cat != category_filter:
            continue

        sensitizations.append(
            {
                "allergen": allergen_name,
                "ige_kU_L": v,
                "class": cls,
                "class_label": _IGE_CLASS_LABELS.get(cls, ""),
                "category": cat,
            }
        )

    # Sort: highest class first, then by IgE value desc
    sensitizations.sort(key=lambda x: (-(x["class"] or 0), -(x["ige_kU_L"] or 0)))

    high_class = sum(1 for s in sensitizations if s["class"] >= 3)
    moderate_class = sum(1 for s in sensitizations if s["class"] == 2)
    low_class = sum(1 for s in sensitizations if s["class"] == 1)
    cats_present = sorted(set(s["category"] for s in sensitizations))

    return {
        "draw_date": target.get("draw_date"),
        "total_ige": total_ige_obj,
        "min_class_filter": min_class,
        "category_filter": category_filter,
        "sensitizations": sensitizations,
        "summary": {
            "total_sensitizations": len(sensitizations),
            "high_class_count": high_class,  # class >= 3
            "moderate_class_count": moderate_class,
            "low_class_count": low_class,
            "categories_present": cats_present,
        },
        "context": (
            "Allergy results surface for completeness but are not actionable in the "
            "platform's optimization loop (per the Technical Board consult, 2026-05-02). "
            "IgE class is ordinal: 0 = no detectable, 6 = maximum. ImmunoCAP scale."
        ),
    }
