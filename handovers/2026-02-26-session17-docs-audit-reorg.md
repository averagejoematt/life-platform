# Life Platform — Session Handover
## 2026-02-26 Session 17: Documentation Audit + Folder Reorganization

**Version:** v2.33.0 (no code changes this session — docs + housekeeping only)
**MCP tools:** 72 | **Cached:** 12 | **Lambda:** 1024 MB

---

## What Was Done

### 1. Tool Count Fix (61 → 72)
- Discovered actual TOOLS dict in mcp_server.py has 72 tools, not 61
- Swept all docs: ARCHITECTURE, PROJECT_PLAN, RUNBOOK, USER_GUIDE, SCHEMA, HANDOVER_LATEST
- Updated memory edit #1

### 2. Five New Reference Documents Created
- **docs/FEATURES.md** — Two-part feature showcase (non-technical by life domain + technical for engineers)
- **docs/MCP_TOOL_CATALOG.md** — All 72 tools with params, cache status, data source dependencies
- **docs/DATA_DICTIONARY.md** — SOT domain mapping, metric overlap resolution, webhook filtering tiers, known gaps
- **docs/INCIDENT_LOG.md** — 13 incidents tracked (P1-P4) with root cause, TTD/TTR, data loss
- **docs/COST_TRACKER.md** — ~$6/mo breakdown, budget guardrails, 8 cost decisions logged

### 3. Folder Reorganization (complete)
**Before:** ~170 files flat at life-platform root + drop folders scattered in ~/Documents/Claude/

**After:**
```
~/Documents/Claude/
  life-platform/                  ← Everything lives here now
    mcp_server.py                 ← MCP server (72 tools)
    mcp_bridge.py                 ← Local MCP adapter
    docs/                         ← All 14 .md files + archive/ + rca/
    lambdas/                      ← 36 files (Lambda source + zips)
    deploy/                       ← 65 deploy scripts
    backfill/                     ← 25 backfill + migration scripts
    patches/                      ← 31 historical patches
    seeds/                        ← 7 data seed scripts
    setup/                        ← 13 auth + infrastructure scripts
    tests/                        ← 5 test scripts
    scripts/                      ← 6 .command shortcuts
    handovers/                    ← 53+ session notes
    datadrops/                    ← 11 data drop folders (moved from parent)
    ingest/                       ← launchd automation (paths updated)
    archive/legacy-scripts/       ← Old p40 scripts
```

### 4. Automation Paths Updated
- `ingest/process_all_drops.sh` — $BASE now points to `datadrops/`, backfill refs point to `backfill/`
- `ingest/com.matthewwalker.life-platform-ingest.plist` — WatchPaths updated to `datadrops/` paths
- Matthew has reloaded the launchd agent ✅

### 5. 25-Item Feature Roadmap
- Expanded from 7 items to 25 across 4 tiers
- Cost flags on 2 items: WAF (+$5/mo, 25%) and Web dashboard (+$2-5/mo, 10-25%)
- North Star updated with 3 new remaining gaps
- All 23 other features ~$0 incremental cost

### 6. Docs Updated This Session
- ARCHITECTURE.md — tool count 61→72 (5 locations), Local Project Structure rewritten for new layout
- PROJECT_PLAN.md — tool count, 25-item roadmap, North Star gaps
- RUNBOOK.md — tool count
- USER_GUIDE.md — tool count (3 locations)
- SCHEMA.md — tool count
- HANDOVER_LATEST.md — tool count + pointer

### 7. Memory Updated
- #1: 72 tools (was 61)
- #2: New folder layout
- #3: Deploy scripts now in deploy/
- #5: All docs now in docs/

---

## Outstanding Ops Tasks

| Task | When | Command |
|------|------|---------|
| DST Spring Forward | March 7 evening | `bash deploy/deploy_dst_spring_2026.sh` |

---

## Next Session Suggestions

Pick from Tier 1 of the 25-item roadmap:

1. **Monarch Money (#1)** — Financial pillar. `setup/setup_monarch_auth.py` exists. 4-6 hr.
2. **Google Calendar (#2)** — Demand-side cognitive load data. Biggest remaining North Star gap. 6-8 hr.
3. **Strava ingestion dedup (#4)** — Quick win, fixes known issue. 2-3 hr.
4. **Health trajectory (#3)** — Forward-looking intelligence. 4-6 hr.
5. **N=1 experiment framework (#5)** — "Did this actually work?" tool. 6-8 hr.

---

## Key File Locations (post-reorg)

| What | Path |
|------|------|
| MCP server source | `mcp_server.py` (root) |
| MCP bridge | `mcp_bridge.py` (root) |
| All documentation | `docs/` |
| Project plan | `docs/PROJECT_PLAN.md` |
| Handover pointer | `docs/HANDOVER_LATEST.md` |
| Lambda source | `lambdas/` |
| Deploy scripts | `deploy/` |
| Data drop folders | `datadrops/` |
| Ingest automation | `ingest/` |
