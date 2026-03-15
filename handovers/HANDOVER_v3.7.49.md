# Life Platform Handover — v3.7.49
**Date:** 2026-03-15
**Pointer:** `handovers/HANDOVER_LATEST.md` → this file

---

## Platform State

| Metric | Value |
|--------|-------|
| Version | v3.7.49 |
| MCP tools | 87 |
| Data sources | 19 active |
| Lambdas | 42 CDK + 2 Lambda@Edge |
| CloudWatch alarms | ~49 |
| Tests | 83/83 passing |
| MCP connector | ✅ Connected in claude.ai |
| Latest review | R16 — Grade: A |

---

## What Was Done This Session

### v3.7.48 — R16 sweep + housekeeping
- All 7 R16 findings closed (see HANDOVER_v3.7.48_R16sweep.md)
- PROJECT_PLAN Key Metrics corrected (89→87 tools, 11→9 secrets, 20→19 sources)
- MCP_TOOL_CATALOG ADR-030 note added (R14-F04 closed)
- PLATFORM_FACTS `secret_count` corrected 10→9, pre-commit hook now stable
- GitHub Actions unblock: support ticket filed 2026-03-15

### v3.7.49 — Board-recommended bug fixes + health coaching features
Both boards (Technical + Health) convened on live data. Five items actioned:

| Fix | File | Root Cause |
|-----|------|-----------|
| **Bug #1**: `get_character` `ValueError: Unknown format code 'd' for object of type 'float'` | `mcp/tools_character.py` | `{level:3d}` applied to float from DDB Decimal→float conversion. Fixed: `{int(level):3d}` |
| **Bug #2**: `get_health(trajectory)` biomarkers: `name 'Key' is not defined` | `mcp/labs_helpers.py` | `Key` from `boto3.dynamodb.conditions` used in `_get_genome_cached()` and `_query_all_lab_draws()` but never imported. Fixed: added import. |
| **Bug #3**: `get_health(trajectory)` recovery: `name 'normalize_whoop_sleep' is not defined` | `mcp/tools_health.py` | `normalize_whoop_sleep` only imported locally inside `tool_get_readiness_score`, not in scope for `tool_get_health_trajectory`. Fixed: moved to module-level import, removed redundant local import. |
| **Feature #4**: Weight loss rate safety warning | `mcp/tools_health.py` | Added Attia 1% body weight/week gate in `tool_get_health_trajectory`. At 287.7 lbs threshold = 2.88 lbs/week; current rate 5.23 lbs/week fires the warning. Wired into Board of Directors concerns. |
| **Feature #5**: Strength session frequency check | `mcp/tools_health.py` | Added check for <3 strength sessions/week during weight loss phase in fitness trajectory. Wired into Board concerns. |

All 5 verified live via MCP tool calls after deploy.

**Key live finding from board session:** Weight loss rate (5.23 lbs/week) is 1.82× the safe threshold (2.88 lbs/week). Platform now surfaces this warning in every trajectory call and Daily Brief Board section.

---

## Pending Items for Next Session

| Item | Priority | Notes |
|------|----------|-------|
| **GitHub Actions unblock** | Medium | Support ticket filed 2026-03-15. Once resolved: `gh workflow run ci-cd.yml --ref main` |
| **Monitor CI/CD first run** | Low | https://github.com/averagejoematt/life-platform/actions |
| R14-F04: MCP_TOOL_CATALOG.md | Low | Done this session ✅ |
| R13-F07: PITR drill | Low | Next ~2026-06-15 |
| SIMP-1 Phase 2 + ADR-025 cleanup | Deferred | ~2026-04-13 (EMF data gate) |
| Architecture Review #17 | Deferred | ~2026-04-08. Run `python3 deploy/generate_review_bundle.py` first. |
| IC-4/IC-5 activation | Deferred | ~2026-05-01. Data gate: 42 days habit_scores / computed_metrics. |
| **Character sheet data completeness** | Low | Many pillar components returning `null` — MacroFactor, Habitify, Hevy data not reaching character engine. Investigate compute Lambda data inputs before R17. |

---

## Key Learnings This Session

**Both boards as feature discovery:** Running both the Technical and Health boards on live data is a productive pattern — the health board spotted the weight loss rate issue (a real safety gap), and the tech board caught the production bugs. Worth doing at the start of any session where there's no clear backlog item.

**Character sheet data gap:** The character sheet compute shows most pillar components as `null` (nutrition, habits, movement all missing data). The compute Lambda likely isn't receiving MacroFactor/Habitify/Hevy data in its input bundle. This is a silent quality issue — the sheet renders but with low fidelity. Should be investigated before R17.

---

## Files Changed This Session

```
mcp/tools_character.py          # Bug #1: int(level) format fix
mcp/labs_helpers.py             # Bug #2: Key import added
mcp/tools_health.py             # Bug #3: normalize_whoop_sleep module-level; Features #4 + #5
docs/PROJECT_PLAN.md            # R16 findings closed, Key Metrics corrected
docs/MCP_TOOL_CATALOG.md        # ADR-030 retirement note (R14-F04)
docs/CHANGELOG.md               # v3.7.48 + v3.7.49 entries
deploy/sync_doc_metadata.py     # PLATFORM_FACTS secret_count 10→9
handovers/HANDOVER_v3.7.48_R16sweep.md
handovers/HANDOVER_v3.7.49.md   # this file
```
