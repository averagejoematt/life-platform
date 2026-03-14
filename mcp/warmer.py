"""
Nightly cache warmer — pre-computes expensive tools.
"""
import json
import time
import logging
from datetime import datetime, timedelta

from mcp.config import logger, SOURCES
from mcp.core import ddb_cache_set, mem_cache_set

# Tool functions imported individually for the warmer
from mcp.tools_data import tool_get_sources, tool_get_field_stats
from mcp.tools_health import tool_get_health_dashboard, tool_get_health_risk_profile, tool_get_health_trajectory
from mcp.tools_habits import tool_get_habit_dashboard
from mcp.tools_training import tool_get_training_load, tool_get_seasonal_patterns, tool_get_personal_records, tool_get_training_periodization, tool_get_training_recommendation
from mcp.tools_character import tool_get_character_sheet
from mcp.tools_cgm import tool_get_cgm_dashboard

WARMER_CORE_SOURCES = [s for s in SOURCES if s not in ("apple_health", "hevy")]


def nightly_cache_warmer():
    """Pre-compute expensive tool results and store in DynamoDB cache.
    Excludes apple_health from aggregate queries (3000+ items, ~20s paginate).
    Lambda timeout is 300s; typical warmer runtime ~60-90s.
    Per-step timing is logged so slowdowns are easy to diagnose.
    """
    warmer_start = time.time()
    today    = datetime.utcnow().strftime("%Y-%m-%d")
    five_yrs = (datetime.utcnow() - timedelta(days=365 * 5)).strftime("%Y-%m-%d")
    two_yrs  = (datetime.utcnow() - timedelta(days=365 * 2)).strftime("%Y-%m-%d")
    results  = {}
    logger.info(f"[warmer] START date={today} sources={WARMER_CORE_SOURCES}")

    # 1. get_aggregated_summary — year view (5 years, core sources only)
    _t = time.time()
    try:
        logger.info("[warmer] computing aggregated_summary year (core sources)")
        source_data = parallel_query_sources(WARMER_CORE_SOURCES, five_yrs, today, lean=True)
        agg_result = {}
        for src, items in source_data.items():
            if items:
                agg_result[src] = aggregate_items(items, "year")
        data = {"period": "year", "start_date": five_yrs, "end_date": today,
                "sources": agg_result, "note": "warmer: apple_health excluded"}
        cache_key = f"aggregated_summary_year_{five_yrs}_{today}_{','.join(WARMER_CORE_SOURCES)}"
        ddb_cache_set(cache_key, data)
        mem_cache_set(cache_key, data)
        results["aggregated_summary_year"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] aggregated_summary year failed: {e}")
        results["aggregated_summary_year"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 2. get_aggregated_summary — month view (2 years, core sources only)
    _t = time.time()
    try:
        logger.info("[warmer] computing aggregated_summary month (core sources)")
        source_data = parallel_query_sources(WARMER_CORE_SOURCES, two_yrs, today, lean=True)
        agg_result = {}
        for src, items in source_data.items():
            if items:
                agg_result[src] = aggregate_items(items, "month")
        data = {"period": "month", "start_date": two_yrs, "end_date": today,
                "sources": agg_result, "note": "warmer: apple_health excluded"}
        cache_key = f"aggregated_summary_month_{two_yrs}_{today}_{','.join(WARMER_CORE_SOURCES)}"
        ddb_cache_set(cache_key, data)
        mem_cache_set(cache_key, data)
        results["aggregated_summary_month"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] aggregated_summary month failed: {e}")
        results["aggregated_summary_month"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 3. get_personal_records
    _t = time.time()
    try:
        logger.info("[warmer] computing personal_records")
        data = tool_get_personal_records({"end_date": today})
        ddb_cache_set("personal_records_all", data)
        mem_cache_set("personal_records_all", data)
        results["personal_records"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] personal_records failed: {e}")
        results["personal_records"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 4. get_seasonal_patterns (core sources only — apple_health volume)
    _t = time.time()
    try:
        logger.info("[warmer] computing seasonal_patterns (core sources)")
        data = tool_get_seasonal_patterns({"start_date": "2010-01-01", "end_date": today,
                                           "source": None})
        ddb_cache_set("seasonal_patterns_all", data)
        mem_cache_set("seasonal_patterns_all", data)
        results["seasonal_patterns"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] seasonal_patterns failed: {e}")
        results["seasonal_patterns"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 5. get_health_dashboard
    _t = time.time()
    try:
        logger.info("[warmer] computing health_dashboard")
        data = tool_get_health_dashboard({})
        ddb_cache_set("health_dashboard_today", data)
        mem_cache_set("health_dashboard_today", data)
        results["health_dashboard"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] health_dashboard failed: {e}")
        results["health_dashboard"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 6. get_habit_dashboard
    _t = time.time()
    try:
        logger.info("[warmer] computing habit_dashboard")
        data = tool_get_habit_dashboard({})
        ddb_cache_set("habit_dashboard_today", data)
        mem_cache_set("habit_dashboard_today", data)
        results["habit_dashboard"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] habit_dashboard failed: {e}")
        results["habit_dashboard"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 7. get_health_risk_profile (board vote 11-0: warm before get_health consolidation)
    _t = time.time()
    try:
        logger.info("[warmer] computing health_risk_profile")
        data = tool_get_health_risk_profile({})
        ddb_cache_set("health_risk_profile_today", data)
        mem_cache_set("health_risk_profile_today", data)
        results["health_risk_profile"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] health_risk_profile failed: {e}")
        results["health_risk_profile"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 8. get_health_trajectory (board vote 11-0: warm before get_health consolidation)
    _t = time.time()
    try:
        logger.info("[warmer] computing health_trajectory")
        data = tool_get_health_trajectory({"domain": "all"})
        ddb_cache_set("health_trajectory_today", data)
        mem_cache_set("health_trajectory_today", data)
        results["health_trajectory"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] health_trajectory failed: {e}")
        results["health_trajectory"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 9. get_training_load (fix: imported but never cached before SIMP-1 Phase 1c)
    _t = time.time()
    try:
        logger.info("[warmer] computing training_load")
        data = tool_get_training_load({})
        ddb_cache_set("training_load_today", data)
        mem_cache_set("training_load_today", data)
        results["training_load"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] training_load failed: {e}")
        results["training_load"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 10. get_training_periodization (board vote 11-0: warm with Phase 1c consolidation)
    _t = time.time()
    try:
        logger.info("[warmer] computing training_periodization")
        data = tool_get_training_periodization({})
        ddb_cache_set("training_periodization_today", data)
        mem_cache_set("training_periodization_today", data)
        results["training_periodization"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] training_periodization failed: {e}")
        results["training_periodization"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 11. get_training_recommendation (board vote 11-0: warm with Phase 1c consolidation)
    _t = time.time()
    try:
        logger.info("[warmer] computing training_recommendation")
        data = tool_get_training_recommendation({})
        ddb_cache_set("training_recommendation_today", data)
        mem_cache_set("training_recommendation_today", data)
        results["training_recommendation"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] training_recommendation failed: {e}")
        results["training_recommendation"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 12. get_character_sheet (board vote 11-0: reads pre-computed DDB partition, fast)
    _t = time.time()
    try:
        logger.info("[warmer] computing character_sheet")
        data = tool_get_character_sheet({})
        ddb_cache_set("character_sheet_today", data)
        mem_cache_set("character_sheet_today", data)
        results["character_sheet"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] character_sheet failed: {e}")
        results["character_sheet"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    # 13. get_cgm_dashboard (board vote 11-0: apple_health query, warm for latency)
    _t = time.time()
    try:
        logger.info("[warmer] computing cgm_dashboard")
        data = tool_get_cgm_dashboard({})
        ddb_cache_set("cgm_dashboard_today", data)
        mem_cache_set("cgm_dashboard_today", data)
        results["cgm_dashboard"] = {"status": "ok", "ms": int((time.time()-_t)*1000)}
    except Exception as e:
        logger.error(f"[warmer] cgm_dashboard failed: {e}")
        results["cgm_dashboard"] = {"status": f"error: {e}", "ms": int((time.time()-_t)*1000)}

    total_ms = int((time.time() - warmer_start) * 1000)
    errors   = [k for k, v in results.items() if not v.get("status", "").startswith("ok")]
    status   = "COMPLETE" if not errors else f"PARTIAL — {len(errors)} step(s) failed: {errors}"
    logger.info(f"[warmer] {status} total_ms={total_ms} steps={json.dumps(results)}")
    if errors:
        logger.error(f"[warmer] FAILED steps: {errors}")

    return {"warmer": status, "date": today, "total_ms": total_ms, "results": results}
