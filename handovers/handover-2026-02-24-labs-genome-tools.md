# Life Platform — Handover: Labs/DEXA/Genome MCP Tools
**Date:** 2026-02-24  
**Version:** v2.11.0  
**Session:** MCP tool development — 8 new tools for labs, DEXA, and genome data  
**Status:** Deployed to Lambda, pending Claude Desktop restart for verification

---

## What Was Done

### 8 New MCP Tools (47 → 55 tools)

Expert panel convened (Attia, Rhonda Patrick, Galpin, Internal Medicine synthesis) to design optimal tool set for 7 blood draws + 1 DEXA scan + 110 genome SNPs.

| # | Tool | Description |
|---|------|-------------|
| 1 | `get_lab_results` | Single draw biomarkers with genome cross-reference annotations; no date = summary of all 7 draws |
| 2 | `get_lab_trends` | Biomarker trajectory across all draws — linear regression slope, 1-year projection, derived ratios (TG/HDL, non-HDL cholesterol, TC/HDL) |
| 3 | `get_out_of_range_history` | Every flagged biomarker across all draws with persistence classification (chronic/recurring/occasional) + genome drivers |
| 4 | `search_biomarker` | Free-text search across all draws — returns all values over time with trend direction |
| 5 | `get_genome_insights` | Query 110 SNPs by category/risk/gene; cross-reference with labs or MacroFactor nutrition data |
| 6 | `get_body_composition_snapshot` | DEXA interpretation with FFMI, visceral fat category, BMD, A/G ratio, posture analysis, current Withings delta |
| 7 | `get_health_risk_profile` | Multi-domain risk synthesis (cardiovascular, metabolic, longevity) combining labs + genome + DEXA + wearable HRV |
| 8 | `get_next_lab_priorities` | Genome-informed recommendations for next blood panel — what to add, what to retest, priority + rationale |

### 7 New Helper Functions

| Helper | Purpose |
|--------|---------|
| `_get_genome_cached()` | Query all genome SNPs once per Lambda invocation (in-memory cache) |
| `_query_all_lab_draws()` | Query all blood draw items from labs source, sorted chronologically |
| `_query_dexa_scans()` | Query all DEXA scan items |
| `_query_lab_meta()` | Query labs provider metadata items (non-DATE# SKs) |
| `_genome_context_for_biomarkers()` | Return genome annotations relevant to a set of biomarker keys |
| `_linear_regression()` | Simple OLS for trend slope, intercept, r² |
| `_GENOME_LAB_XREF` | Map of biomarker keys → genome genes that explain/modify interpretation |

### Key Design Decisions

1. **Genome cross-referencing is automatic** — when you query LDL trends, ABCG8/SLCO1B1 context surfaces without asking. The `_GENOME_LAB_XREF` dict maps 14 biomarker keys to their genetic drivers.

2. **Derived ratios computed across all draws** — `get_lab_trends` computes TG/HDL ratio (insulin resistance proxy), non-HDL cholesterol, and TC/HDL ratio as first-class trend data, not just raw biomarkers.

3. **Persistence classification** — `get_out_of_range_history` classifies each flag as chronic (≥60% flag rate), recurring (≥30%), or occasional, distinguishing genetic baselines from lifestyle-driven anomalies.

4. **DEXA as calibration anchor** — `get_body_composition_snapshot` computes FFMI/FFMI-normalized, fetches current Withings for delta tracking, and interprets posture assessment flags.

5. **Risk profile is multi-source** — `get_health_risk_profile` is the first tool that synthesizes labs + genome + DEXA + Whoop HRV into a single clinical picture across 3 domains.

6. **SOURCES updated** — `labs`, `dexa`, `genome` added to SOURCES list (11 → 14), enabling `get_sources` and `get_latest` to include these new data types.

---

## Files Changed

| File | Change |
|------|--------|
| `mcp_server.py` | Patched v2.8.0 → v2.11.0: +42KB, 8 tool functions, 7 helpers, 8 registry entries, SOURCES 11→14 |
| `patch_labs_genome_tools.py` | **NEW** — patcher script (idempotent, has safety checks) |
| `deploy_labs_genome_tools.sh` | Already existed from prior session; calls patcher + packages + deploys |

---

## Verification Needed (After Restart)

Test each tool in Claude Desktop:

```
# Foundation tools
"Show me all my lab draws"                              → get_lab_results (no args)
"What were my lipids in June 2024?"                     → get_lab_results (draw_date + category)
"How has my LDL trended over time?"                     → get_lab_trends (biomarker: ldl_c)
"Which biomarkers have been persistently flagged?"       → get_out_of_range_history
"Find everything about cholesterol"                      → search_biomarker (query: cholesterol)

# Genome tools
"What does my genome say about metabolism?"              → get_genome_insights (category: metabolism)
"Show my unfavorable SNPs with lab cross-reference"      → get_genome_insights (risk: unfavorable, cross_ref: labs)

# DEXA tool
"Show my DEXA body composition and FFMI"                → get_body_composition_snapshot

# Synthesis tools
"Give me my overall health risk profile"                → get_health_risk_profile
"What should I test on my next blood draw?"             → get_next_lab_priorities
```

---

## Current State

- **MCP Server:** v2.11.0, 55 tools, deployed to Lambda `life-platform-mcp`
- **Data Sources:** 14 (11 automated + labs/dexa/genome manual)
- **DynamoDB:** ~8,000+ items — 7 lab draws, 1 DEXA scan, 111 genome items (110 SNPs + 1 summary)
- **Infrastructure:** Unchanged — all alarms, logging, budgets intact

---

## What's Next

Top priorities from the backlog:
1. **Verify all 8 tools** work end-to-end after Claude Desktop restart
2. **Exercise timing vs sleep quality** (PROJECT_PLAN item 3) — Strava end times + Eight Sleep
3. **Zone 2 training identifier** (item 4) — Garmin HR zone data is already ingested; tool to surface it
4. **Data completeness alerting** (item 16) — detect silent data gaps across all sources
5. **Notion Journal integration** (item 9) — closes the "why" gap in biometric insights
