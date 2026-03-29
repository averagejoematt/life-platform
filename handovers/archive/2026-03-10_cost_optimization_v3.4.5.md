# Life Platform Handover — v3.4.5 (2026-03-10)

## Session Summary

COST-A: CloudWatch alarm audit and cleanup. CDK changes deployed across 3 stacks.
Audit + delete scripts written. ~$4.60/month savings once orphan deletion runs.

---

## What Was Completed This Session

### COST-A: CloudWatch Alarm Consolidation

**Root cause:** 87 alarms existed vs ~55 CDK-managed. Alarm count grew via:
1. Pre-CDK orphans (~32) never cleaned up after v3.4.0 CDK migration
2. CDK duplicate alarms (14) added across stacks without dedup review

**CDK changes made:**

| File | Change |
|------|--------|
| `monitoring_stack.py` | Removed `life-platform-daily-brief-invocations` (dup of `daily-brief-no-invocations-24h`) |
| `monitoring_stack.py` | Removed 11 per-Lambda AI token alarms; kept `ai-tokens-daily-brief-daily` + `ai-tokens-platform-daily-total` |
| `email_stack.py` | daily-brief now passes `alerts_topic=None` — MonitoringStack owns its alarms (removes `ingestion-error-daily-brief`) |
| `operational_stack.py` | Removed `life-platform-canary-any-failure` (bug: watched `CanaryDDBFail`, identical to `canary-ddb-failure`) |

**Scripts written:**
- `deploy/audit_alarms.sh` — lists all 87 alarms, flags CDK-expected vs orphans
- `deploy/delete_orphan_alarms.sh` — deletes AI token orphans + CDK dupes + pre-CDK orphans (populate PRECDK_ORPHANS array from audit output before running)

**Savings:**
| Category | Alarms | Monthly |
|----------|--------|---------|
| CDK duplicates removed | 14 | $1.40 |
| Pre-CDK orphans (pending audit) | ~32 | ~$3.20 |
| **Total** | **~46** | **~$4.60** |
| CloudWatch before | 87 alarms | $7.70/mo |
| CloudWatch after | ~41 alarms | ~$3.10/mo |

### Docs Updated
- `docs/COST_TRACKER.md` — CloudWatch row corrected, monthly actuals updated, decision logged

---

## Platform State

- **Version:** v3.4.5
- **Alarm count:** 87 (live) → ~41 (after CDK deploy + orphan deletion)
- **CDK changes:** 3 stacks modified, NOT YET DEPLOYED

---

## Next Steps (in order)

### Immediate — complete this cost work
1. **Run audit:** `bash deploy/audit_alarms.sh` — review the [ORPHAN] list
2. **Populate delete script:** Add confirmed orphan names to `PRECDK_ORPHANS` array in `deploy/delete_orphan_alarms.sh`
3. **Delete AI token + CDK dupes:** `bash deploy/delete_orphan_alarms.sh` (partial run works before populating PRECDK_ORPHANS — it will delete the AI token + CDK duplicate entries immediately)
4. **Deploy CDK changes:** `cd cdk && cdk deploy LifePlatformMonitoring LifePlatformEmail LifePlatformOperational`
5. **Run audit again** to confirm alarm count is ~41

### Then
6. **Brittany weekly email** — next major feature
7. **SIMP-1** — MCP tool usage audit ~2026-04-08
8. **Delete api-keys secret** — ~2026-04-07 (saves $0.40/mo)
