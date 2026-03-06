# Phase 7 — Documentation Health Review

**Date:** 2026-02-28  
**Platform:** v2.47.1 (97 MCP tools, 22 Lambdas)  
**Reviewer:** Claude (Expert Review)

---

## 7.1 Document Inventory & Freshness

| Document | Current Version | Platform Version | Staleness | Priority |
|----------|----------------|-----------------|-----------|----------|
| `CHANGELOG.md` | v2.47.1 | v2.47.1 | ✅ Current | — |
| `PROJECT_PLAN.md` | v2.47.1 | v2.47.1 | ✅ Current | — |
| `SCHEMA.md` | v2.47.1 | v2.47.1 | ✅ Current | — |
| `deploy/MANIFEST.md` | v2.47.1 | v2.47.1 | ✅ Current | — |
| `PIR-2026-02-28-ingestion-outage.md` | v2.47.1 | v2.47.1 | ✅ Current | — |
| `ARCHITECTURE.md` | v2.46.0 | v2.47.1 | ⚠️ 1 version behind | Low |
| `RUNBOOK.md` | v2.43.0 | v2.47.1 | ⚠️ 4 versions behind | Medium |
| `MCP_TOOL_CATALOG.md` | v2.41.0 | v2.47.1 | 🔴 6 versions behind | **High** |
| `FEATURES.md` | v2.41.0 | v2.47.1 | 🔴 6 versions behind | **High** |
| `USER_GUIDE.md` | v2.41.0 | v2.47.1 | 🔴 6 versions behind | **High** |
| `COST_TRACKER.md` | v2.33.0 | v2.47.1 | 🔴 14 versions behind | Medium |
| `DATA_DICTIONARY.md` | v2.33.0 | v2.47.1 | 🔴 14 versions behind | Medium |
| `INCIDENT_LOG.md` | v2.33.0 | v2.47.1 | 🔴 14 versions behind | Medium |

**Summary:** 5 of 13 documents are current. 3 are critically stale (6+ versions behind). 5 more are moderately stale.

---

## 7.2 Critical Staleness Issues

### MCP_TOOL_CATALOG.md (v2.41.0 → needs v2.47.1)
- **Missing 3 tools:** `get_habit_registry`, `get_habit_tier_report`, `get_vice_streak_history` (added v2.47.0)
- **Says 94 tools**, should say 97
- Missing tools added in v2.34.0–v2.41.0 may also be undocumented (N=1 experiments, health trajectory, travel, BP, state of mind, meditation, social connection)
- **Impact:** This is the primary reference for what the platform can do. Users and future sessions rely on it.

### FEATURES.md (v2.41.0 → needs v2.47.1)
- Missing: Habit Intelligence (tier-weighted scoring, registry), gap-aware backfill, remote MCP, engineering hardening
- Missing: Web dashboard Phase 2, CloudFront + custom domain
- **Impact:** External-facing document for anyone evaluating the platform's capabilities.

### USER_GUIDE.md (v2.41.0 → needs v2.47.1)
- Says "94 MCP tools", should say 97
- Missing usage examples for new tools (habit tier report, vice streaks, travel, BP, supplements, etc.)
- **Impact:** Primary reference for how to query the platform conversationally.

---

## 7.3 Moderate Staleness Issues

### INCIDENT_LOG.md (v2.33.0)
- **Missing the Feb 28 P0 ingestion outage** — the most significant incident in the platform's history. A PIR exists but the incident log itself wasn't updated.
- May be missing other incidents between v2.33.0 and v2.47.1.

### COST_TRACKER.md (v2.33.0)
- Cost breakdown is likely outdated — new Lambdas, weather API, MCP server at 1024 MB, CloudFront, etc. have been added since v2.33.0.
- Phase 4 (costing review) likely covers this, but the standing document needs updating.

### DATA_DICTIONARY.md (v2.33.0)
- Missing SOT entries for: supplements, weather, travel, state_of_mind, habit_scores (all added v2.34.0–v2.47.0).
- The SCHEMA.md is up to date and covers field-level detail, so DATA_DICTIONARY is partially redundant — but it serves a different purpose (metric → source mapping vs. field schema).

### RUNBOOK.md (v2.43.0)
- Missing: Habit registry operations, smoke test template reference, deploy manifest reference, Withings OAuth re-auth procedure.
- The PIR documented several operational procedures that should be cross-referenced here.

---

## 7.4 Documentation That Doesn't Exist But Should

1. **`docs/ONBOARDING.md`** — A "start here" document for a new Claude session. Currently the memory system + trigger phrase + handover file serve this purpose, but a standalone onboarding doc would help if you ever share the project or onboard a human collaborator. Low priority.

2. **`deploy/README.md`** — The deploy/ directory has 90+ scripts. A short README explaining naming conventions, which scripts are current vs. historical, and how to use MANIFEST.md + SMOKE_TEST_TEMPLATE.sh together would help. Low priority.

3. **`docs/DATA_FLOW_DIAGRAM.md`** — ARCHITECTURE.md describes the flow in prose, but a visual diagram (Mermaid format) showing Source → Lambda → S3/DDB → MCP → Claude would be valuable for quick comprehension. Low priority.

---

## 7.5 Documentation Quality Observations

**Strengths:**
- CHANGELOG is exemplary — detailed, consistent format, version-tagged, with root cause analysis for fixes
- SCHEMA.md is the gold standard — comprehensive, field-level, with notes on edge cases and access patterns
- Handover files are thorough and enable genuine session continuity
- The PIR is professional-grade — honest root cause analysis with concrete process improvements
- PROJECT_PLAN serves as a living dashboard with clear prioritization

**Weaknesses:**
- Rapid development velocity (v2.33.0 → v2.47.1 in 3 days) has outpaced doc updates — the "end of session" doc discipline broke down during the marathon build sprint
- Several docs are partially redundant (DATA_DICTIONARY vs SCHEMA, FEATURES vs USER_GUIDE vs MCP_TOOL_CATALOG) — consolidation would reduce the maintenance surface
- No automated staleness detection — nothing alerts when a doc falls behind

---

## 7.6 Consolidation Opportunity

Currently 13 documents, some overlapping:

| Potential Merge | Docs | Rationale |
|----------------|------|-----------|
| DATA_DICTIONARY → SCHEMA.md | 2 → 1 | SCHEMA already has field-level detail. DATA_DICTIONARY adds SOT mapping, but that's 1 table that could live in SCHEMA. |
| FEATURES + USER_GUIDE → single doc | 2 → 1 | Both describe "what the platform does" from slightly different angles. Merge into one comprehensive guide. |

This would reduce from 13 to 11 docs. Each merged doc would be easier to keep current.

---

## 7.7 Overall Documentation Grade: B-

**Strengths:** Core technical docs (CHANGELOG, SCHEMA, PROJECT_PLAN) are excellent. Handover system is best-in-class.

**Weaknesses:** 8 of 13 documents are stale. The sprint from v2.33 → v2.47 in 3 days was extraordinary engineering output but documentation couldn't keep pace.

**Top 3 recommendations (priority order):**
1. **Update MCP_TOOL_CATALOG.md to v2.47.1** (30 min — highest impact, it's the primary tool reference)
2. **Add Feb 28 P0 outage to INCIDENT_LOG.md** (10 min — cross-reference the PIR)
3. **Batch update FEATURES.md + USER_GUIDE.md** (45 min combined — bring external-facing docs current)
