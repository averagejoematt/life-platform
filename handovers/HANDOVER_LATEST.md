# Life Platform — Handover v3.3.7
**Date:** 2026-03-09  
**Session:** IC-4 + IC-5 + PROD-2 audit  
**Version bump:** v3.3.6 → v3.3.7

---

## What Was Done This Session

### IC-4: Failure Pattern Compute Lambda ✅ (written + on disk, NOT YET DEPLOYED)
**File:** `lambdas/failure_pattern_compute_lambda.py`

New Lambda — weekly Sunday 9:50 AM PT (EventBridge cron `50 17 ? * SUN *`).

Logic:
1. Loads 7 days of `computed_metrics`
2. Identifies "failure days" (any component score < 50)
3. Enriches each failure day with contextual data: Whoop recovery/HRV, Todoist task count, journal stress, MacroFactor calories
4. Haiku synthesis pass → identifies recurring patterns (min 2 occurrences)
5. Stores to `platform_memory` as `MEMORY#failure_pattern#<date>#<index>`
6. Idempotent — skips if already ran today unless `force=true`

Consumed by: `daily_insight_compute` → `build_memory_context()` → injected into Daily Brief AI calls.

### IC-5: Early Warning Detection ✅ (written + on disk, NOT YET DEPLOYED)
**File:** `lambdas/daily_insight_compute_lambda.py` (v1.0.0 → v1.2.0)

New function `detect_early_warning(computed_records_7d, habit_7d, declining)`:
- 4 markers: `journal_sparse`, `nutrition_gap`, `habit_declining`, `recovery_sliding`
- Warning fires when **2+ markers** active simultaneously
- Injects `⚠️ EARLY WARNING` block into AI context before final INSTRUCTION

Handler return includes `ic5_warning` (bool) and `ic5_markers` (list) for CloudWatch visibility.

### PROD-2 Audit ✅
- **Phase 1 (env var defaults):** Already complete since v3.2.1. All 39 Lambdas use `os.environ["USER_ID"]` fail-fast. No `"matthew"` defaults remain.
- **Phase 2 (email → profile):** Already done. All email Lambdas use `os.environ["EMAIL_RECIPIENT"]` / `os.environ["EMAIL_SENDER"]`. No profile migration needed to unblock multi-user.
- **Phase 3 (S3 path prefix):** Deferred — touches CloudFront/web infra. Own session.

---

## Deploy Needed

**Single script covers everything:**
```bash
bash deploy/deploy_ic4_ic5.sh
```

This script:
1. Creates/updates `failure-pattern-compute` Lambda with correct env vars
2. Creates EventBridge rule `failure-pattern-compute-weekly` (cron `50 17 ? * SUN *`) — only on first deploy
3. Deploys `daily-insight-compute` v1.2.0 via `deploy_lambda.sh`

**Verify after deploy:**
```bash
# IC-4 test (force=true bypasses idempotency check)
aws lambda invoke --function-name failure-pattern-compute \
  --payload '{"force":true}' /tmp/ic4_out.json --region us-west-2
cat /tmp/ic4_out.json

# IC-5: already fires as part of daily-insight-compute — check CloudWatch logs
aws logs describe-log-streams \
  --log-group-name /aws/lambda/daily-insight-compute \
  --order-by LastEventTime --descending --limit 1 --region us-west-2
```

---

## File State

| File | Status |
|------|--------|
| `lambdas/failure_pattern_compute_lambda.py` | ✅ New — IC-4 v1.0.0 |
| `lambdas/daily_insight_compute_lambda.py` | ✅ Updated — IC-2 v1.2.0 with IC-5 |
| `deploy/deploy_ic4_ic5.sh` | ✅ Ready to run |
| `docs/CHANGELOG.md` | ✅ v3.3.7 entry added |

---

## Architecture Notes (IC-4/5)

**DDB keys:**
- IC-4 writes: `pk=USER#matthew#SOURCE#platform_memory`, `sk=MEMORY#failure_pattern#<YYYY-MM-DD>#<i>`
- IC-5 reads: `declining` list from `detect_metric_trends()` (already computed in step 3 of insight compute)

**Schedule ordering on Sundays:**
```
9:40 AM  daily-metrics-compute
9:42 AM  daily-insight-compute  (IC-5 fires here)
9:50 AM  failure-pattern-compute  (IC-4 — new)
10:00 AM daily-brief  (reads everything)
```

**IC-5 marker thresholds:**
- `journal_sparse`: journal component < 50 for 2+ of last 3 days
- `nutrition_gap`: nutrition component < 40 for 2+ of last 3 days
- `habit_declining`: T0 completion rate dropped ≥15pp (last 3d avg vs prior 4d avg)
- `recovery_sliding`: recovery or readiness_score in `declining` list from `detect_metric_trends`

---

## Open Items (Carried Forward)

| Item | Priority | Status |
|------|----------|--------|
| **Deploy IC-4 + IC-5** | 🔴 High | Written, script ready → `bash deploy/deploy_ic4_ic5.sh` |
| Brittany email | 🔴 High | Env var `BRITTANY_EMAIL` not set; Board sections not rendering |
| Character Sheet Phase 4 (rewards) | 🟡 Medium | Deferred post Brittany |
| PROD-2 Phase 3 (S3 path prefix) | 🟡 Medium | Deferred — CloudFront impact |
| SEC-4 (API GW rate limiting) | 🟡 Medium | WAF rule on health-auto-export webhook |
| Google Calendar integration | 🟢 Tier 1 | North Star gap #2 |
| Monarch Money integration | 🟢 Tier 1 | `setup/setup_monarch_auth.py` exists |
| DLQ depth monitoring | 🟡 Medium | EventBridge trigger or dashboard widget |

---

## Session Start Protocol
Read `handovers/HANDOVER_LATEST.md` + `docs/PROJECT_PLAN.md` → brief state + suggest next steps.
