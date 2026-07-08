"""
Nightly cache warmer — pre-computes expensive tools.

v1.1.0 — 2026-03-14 (R10 A+ hardening): steps call SIMP-1 dispatchers
instead of underlying tool functions directly. Prevents silent bypass of any
pre/post-processing logic added to dispatchers in future phases.

v2.0.0 — 2026-07-08 (#395 ER-04 registry prune): trimmed to the surviving
registry. Steps that warmed pruned tools (aggregated_summary, personal_records,
seasonal_patterns, get_health views, get_habits dashboard, character sheet,
centenarian benchmarks) were removed with their tools — see
docs/MCP_TOOL_AUDIT.md. Remaining: training views + CGM dashboard.
"""

import json
import time
from datetime import datetime, timezone

from mcp.config import logger
from mcp.core import ddb_cache_set, mem_cache_set
from mcp.tools_cgm import tool_get_cgm
from mcp.tools_training import tool_get_training


def nightly_cache_warmer():
    """Pre-compute expensive tool results and store in DynamoDB cache.
    Lambda timeout is 300s; typical warmer runtime well under that.
    Per-step timing is logged so slowdowns are easy to diagnose.
    """
    warmer_start = time.time()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    results = {}
    logger.info(f"[warmer] START date={today}")

    steps = [
        # (result_key, cache_key, dispatcher, args)
        ("training_load", "training_load_today", tool_get_training, {"view": "load"}),
        ("training_periodization", "training_periodization_today", tool_get_training, {"view": "periodization"}),
        ("training_recommendation", "training_recommendation_today", tool_get_training, {"view": "recommendation"}),
        ("cgm_dashboard", "cgm_dashboard_today", tool_get_cgm, {"view": "dashboard"}),
    ]
    for result_key, cache_key, fn, args in steps:
        _t = time.time()
        try:
            logger.info(f"[warmer] computing {result_key} (via dispatcher)")
            data = fn(dict(args))
            ddb_cache_set(cache_key, data)
            mem_cache_set(cache_key, data)
            results[result_key] = {"status": "ok", "ms": int((time.time() - _t) * 1000)}
        except Exception as e:
            logger.error(f"[warmer] {result_key} failed: {e}")
            results[result_key] = {"status": f"error: {e}", "ms": int((time.time() - _t) * 1000)}

    total_ms = int((time.time() - warmer_start) * 1000)
    errors = [k for k, v in results.items() if not v.get("status", "").startswith("ok")]
    status = "COMPLETE" if not errors else f"PARTIAL — {len(errors)} step(s) failed: {errors}"
    logger.info(f"[warmer] {status} total_ms={total_ms} steps={json.dumps(results)}")
    if errors:
        logger.error(f"[warmer] FAILED steps: {errors}")

    return {"warmer": status, "date": today, "total_ms": total_ms, "results": results}
