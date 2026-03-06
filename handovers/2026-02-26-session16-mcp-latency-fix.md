# Session 16 Handover — MCP Latency Fix + Expanded Cache Warmer

**Date:** 2026-02-26  
**Version:** v2.33.0 (deployed & verified)  
**Session focus:** MCP latency investigation, critical hotfix, memory optimization, cache expansion

---

## What Happened

### Investigation
- CloudWatch analysis revealed MCP Lambda had bimodal latency: 12-30ms (protocol), 80-170ms (light), 1-6s (analytics), 36-46s (mega)
- **Critical finding:** MCP server completely broken since v2.31.0 deploy — `NameError: tool_get_day_type_analysis not defined` on every invocation
- Root cause: 3 tool functions + `_load_cgm_readings` helper placed AFTER the TOOLS dict that references them at module load time
- Second bug found: 5 functions referenced undefined `get_table()` instead of module-level `table`
- No DynamoDB scans found — all queries already use pk+sk range. GSIs unnecessary.

### Deployed Changes (all verified)
1. **Hotfix: function ordering** — moved 3 tool functions + helper before TOOLS dict, all 72 references verified
2. **Hotfix: `get_table()` removal** — 5 functions patched to use module-level `table`
3. **Memory bump:** 512 MB → 1024 MB (2x CPU allocation, halves heavy query execution)
4. **Expanded cache warmer:** 6 → 12 tools pre-computed nightly
5. **Inline cache reads:** 6 tools check DDB cache before computing (default queries only)
6. **Skipped:** Provisioned concurrency ($10.80/month — not worth budget impact)

### Warmer Results (verified)
All 12 tools: COMPLETE in 7.0 seconds. Cache is warm.

---

## Files Created
- `deploy_mcp_hotfix.sh` — Steps 1 & 2 (deployed ✅)
- `deploy_v233_warmer.sh` — Step 3 (deployed ✅)
- `deploy_hotfix_gettable.sh` — get_table fix (deployed ✅)

## Files Modified
- `mcp_server.py` — function reorder, get_table removal, cache warmer expansion, cache reads, version 2.33.0
- `CHANGELOG.md` — v2.33.0 entry
- `PROJECT_PLAN.md` — v2.33.0 state, latency issue resolved, architecture note
- `SCHEMA.md` — v2.33.0, 12 cached tools table
- `ARCHITECTURE.md` — v2.33.0, 61 tools, 1024 MB, warmer expanded to 12 tools

---

## Pending Actions

| Priority | Item | Notes |
|----------|------|-------|
| **March 7** | DST cron update | `deploy_dst_spring_2026.sh` ready, run before 6 AM PDT March 8 |
| Tier 1 | Monarch Money (#9) | Biggest remaining data gap — financial pillar |
| Tier 2 | Daily Brief v2.4 | Integrate derived metrics into brief |
| Tier 2 | Health trajectory (#15) | Long-range goal tracking |
| Infra | WAF rate limiting (#10) | ~$5/month |
| Infra | API key rotation (#11) | 30 min |
| Infra | S3 2.3GB growth investigation | Raw data accumulation |

---

## Platform State

| Metric | Value |
|--------|-------|
| Version | v2.33.0 |
| MCP tools | 61 |
| Cached tools | 12 (was 6) |
| Lambda memory | 1024 MB (was 512 MB) |
| Data sources | 16 |
| Lambdas | 20 |
| Warmer runtime | 7.0s (12 tools) |
| Monthly cost | ~$25 (+$1 from memory bump) |
