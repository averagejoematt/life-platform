# Life Platform Handover — v3.7.19
**Date:** 2026-03-14
**Session type:** SIMP-1 Phase 1c+1d + R8-LT6/LT8 resolved

---

## What Was Done

### SIMP-1 Phase 1c — 5 clusters (−9 tools)
- `get_labs(view: results|trends|out_of_range)` → tools_labs.py
- `get_training(view: load|periodization|recommendation)` → tools_training.py
- `get_strength(view: progress|prs|standards)` → tools_strength.py
- `get_character(view: sheet|pillar|history)` → tools_character.py
- `get_cgm(view: dashboard|fasting)` → tools_cgm.py

### SIMP-1 Phase 1d — 4 clusters (−6 tools)
- `get_mood(view: trend|state_of_mind)` → tools_journal.py (lazy import state_of_mind from tools_lifestyle)
- `get_daily_metrics(view: movement|energy|hydration)` → tools_health.py (lazy import movement_score from tools_lifestyle)
- `get_todoist_snapshot(view: load|today)` → tools_todoist.py (args-dict adapter for positional-arg functions)
- `manage_sick_days(action: list|log|clear)` → tools_sick_days.py

### Warmer additions (board vote 11-0)
Added steps 9-13:
- Step 9: training_load (fix — imported but never cached)
- Step 10: training_periodization
- Step 11: training_recommendation
- Step 12: character_sheet (reads pre-computed DDB partition)
- Step 13: cgm_dashboard

### R8-LT6 — Lambda@Edge auth: confirmed manually managed
Verified `web_stack.py` has zero Lambda@Edge references. `life-platform-cf-auth` and `life-platform-buddy-auth` are manually deployed outside CDK. Intentional — Lambda@Edge requires us-east-1 which complicates CDK stack boundaries. Documented in ARCHITECTURE.md.

### R8-LT8 — DLQ consumer model: decision documented
ADR-024 written: retain schedule-triggered model (every 6h). DLQ messages are not time-critical. ESM adds CDK complexity for zero operational benefit at personal-project scale.

### Housekeeping
- test_mcp_registry.py R5 range updated: 100-130 → 75-105
- sync_doc_metadata.py PLATFORM_FACTS updated: v3.7.15/116 → v3.7.19/86

---

## Platform Status
- Version: v3.7.19
- MCP tools: 86 (was 116 pre-SIMP-1)
- Warmer steps: 13 (was 8)
- All alarms: OK
- CI: 7/7
- Smoke: 10/10
- DLQ: 0

---

## SIMP-1 Tool Count Trajectory
| Version | Tools | Delta | Phase |
|---------|-------|-------|-------|
| v3.7.14 | 116 | baseline | pre-SIMP-1 |
| v3.7.17 | 109 | −7 | Phase 1a: Habits |
| v3.7.18 | 101 | −8 | Phase 1b: Data/Health/Nutrition |
| v3.7.19 | 86 | −15 | Phase 1c+1d: 9 more clusters |
| Target | ≤80 | −6 more | Phase 2: EMF-driven (~2026-04-13) |

---

## Remaining Open Items

### Do Next (this session incomplete)
| ID | Item | Effort | Notes |
|----|------|--------|-------|
| R8-ST5 | Pre-compute composite scores → `SOURCE#composite_scores` DDB partition | M (3-4h) | Unlocks SIMP-1 Phase 2 pre-compute path |
| R8-LT3 | Unit tests for business logic — scoring_engine, character_engine, anomaly, day grade | M-L | Currently only static linters |
| R8-LT9 | Pre-compute weekly correlation matrix → `SOURCE#weekly_correlations` | M (3h) | Performance optimization |

### Gated
| ID | Item | Gate |
|----|------|------|
| SIMP-1 Phase 2 | EMF-driven cuts of low-use tools | ~2026-04-13 (30-day EMF data) |
| R8-LT1 | Architecture Review #9 | After Phase 2 complete |
| R8-ST1 | Google Calendar integration | Highest-priority unbuilt feature |

---

## Next Session Recommended Order
1. **R8-ST5: Pre-compute composite scores** — design `SOURCE#composite_scores` partition, write nightly Lambda, add to CDK compute stack
2. **R8-LT9: Weekly correlation matrix** — pre-compute and cache `SOURCE#weekly_correlations`
3. **R8-LT3: Unit tests** — scoring_engine + character_engine + day grade computation
4. **Google Calendar** (R8-ST1) — if time remains

---

## Files Changed This Session
- `mcp/tools_labs.py` — tool_get_labs dispatcher
- `mcp/tools_training.py` — tool_get_training dispatcher
- `mcp/tools_strength.py` — tool_get_strength dispatcher
- `mcp/tools_character.py` — tool_get_character dispatcher
- `mcp/tools_cgm.py` — tool_get_cgm dispatcher
- `mcp/tools_journal.py` — tool_get_mood dispatcher
- `mcp/tools_health.py` — tool_get_daily_metrics dispatcher
- `mcp/tools_todoist.py` — tool_get_todoist_snapshot dispatcher
- `mcp/tools_sick_days.py` — tool_manage_sick_days dispatcher
- `mcp/warmer.py` — steps 9-13 added
- `mcp/registry.py` — 24 removed, 9 added (101→86)
- `tests/test_mcp_registry.py` — R5 range 100-130 → 75-105
- `docs/ARCHITECTURE.md` — R8-LT6 Lambda@Edge note
- `docs/DECISIONS.md` — ADR-024 (DLQ consumer model)
- `docs/CHANGELOG.md` — v3.7.19 entry
- `deploy/sync_doc_metadata.py` — PLATFORM_FACTS updated
- `handovers/HANDOVER_v3.7.19.md` — this file
