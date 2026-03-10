# Handover: COST-A + COST-B + Habitify Secret — v3.4.8
**Date:** 2026-03-10  
**Session goal:** Complete three pending items: habitify secret, COST-A alarm consolidation, COST-B secrets consolidation

---

## What Was Discovered

### Key Finding: CDK Already Did Most of the Work
v3.4.7 deployed `LifePlatformIngestion` which already pushed updated Lambda env vars:
- `todoist-data-ingestion`: `SECRET_NAME=life-platform/ingestion-keys`
- `notion-journal-ingestion`: `NOTION_SECRET_NAME=life-platform/ingestion-keys`
- `dropbox-poll`: `SECRET_NAME=life-platform/ingestion-keys`
- `habitify-data-ingestion`: `HABITIFY_SECRET_NAME=life-platform/ingestion-keys`

But the `ingestion-keys` secret doesn't have those API keys in it yet — these 4 Lambdas are currently broken.

### CHANGELOG v3.4.4 Warning is Superseded
The note "life-platform/habitify secret needs creating before 2026-04-07" is wrong. The `role_policies.py` was subsequently updated (COST-B work) to route habitify through `ingestion-keys` instead. No separate `life-platform/habitify` secret should be created.

---

## What Was Built

### Script 1: `deploy/setup_ingestion_keys.sh` (URGENT — run first)
Merges todoist/notion/dropbox/habitify API keys into `life-platform/ingestion-keys`:
- Reads current `ingestion-keys` content
- Reads keys from `life-platform/api-keys` bundle + individual `todoist`/`notion`/`dropbox` secrets (if they exist)
- Merges all keys into `ingestion-keys`
- Schedules `life-platform/todoist`, `life-platform/notion`, `life-platform/dropbox` for deletion (~2026-04-10)
- Verifies Lambda env vars point correctly

### Script 2: `deploy/finish_cost_a.sh`
Finalizes COST-A alarm consolidation:
- Runs `delete_orphan_alarms.sh` (48 orphans, already populated)
- Deploys `LifePlatformMonitoring` (removes AI token per-Lambda alarms, daily-brief invocations dup)
- Deploys `LifePlatformOperational` (removes canary-any-failure dup)

---

## Run Order

```bash
# 1. Fix broken Lambdas + consolidate secrets (URGENT)
bash deploy/setup_ingestion_keys.sh

# 2. Finalize alarm consolidation
bash deploy/finish_cost_a.sh
```

---

## Expected Outcomes

| Item | Savings |
|------|---------|
| COST-B secrets consolidation | $1.20/mo (3 secrets × $0.40) |
| COST-A alarm consolidation | $4.60/mo (~87 → ~41 alarms) |
| **Total** | **$5.80/mo** |

---

## Remaining Pending Items

| Item | When | Notes |
|------|------|-------|
| `life-platform/api-keys` permanent deletion | ~2026-04-07 | Auto-deletes from recovery window set earlier |
| `life-platform/todoist`/`notion`/`dropbox` permanent deletion | ~2026-04-10 | From this session's recovery window |
| SIMP-1 MCP tool usage audit | ~2026-04-08 | 30 days usage data needed |
| OBS-1 structured logging rollout | Ongoing | daily-brief only; remaining Lambdas pending |
| AI-3 output validation rollout | Ongoing | daily-brief only; remaining Lambdas pending |
| COST-2 MCP tool usage audit | Backlog | CloudWatch metric per tool, archive 0-invocation |
| **Brittany weekly email** | Next major feature | Priority after this session |

---

## Next Session
Start with: Brittany weekly email feature build.
