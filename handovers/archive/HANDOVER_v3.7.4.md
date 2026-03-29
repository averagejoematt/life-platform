# Life Platform Handover — v3.7.4
**Date:** 2026-03-12
**Session type:** P0 incident response — alarm flood root cause fix

---

## What Happened

Woke up to alarm flood despite resetting 5 alarms to OK in yesterday's v3.7.2 session.
Root cause: CDK reconcile (v3.7.2) overwrote live Lambda configs to CDK's desired state,
which didn't match the actual code. The alarms weren't stale — they were real failures
that would have kept firing every day until fixed.

---

## Bugs Fixed

### 1. Todoist IAM — S3 path mismatch (AccessDenied)
- **Symptom:** `AccessDenied` on `s3:PutObject` to `raw/todoist/2026/03/11.json`
- **Root cause:** CDK reconcile set IAM policy S3 resource to `raw/matthew/todoist/*`
  but Lambda writes to `raw/todoist/*` (no `matthew/` prefix)
- **Fix:** `aws iam put-role-policy` correcting resource ARN — `fix_p0_alarm_bugs.sh`

### 2. Freshness checker — wrong handler (Runtime.ImportModuleError)
- **Symptom:** `Unable to import module 'lambda_function': No module named 'lambda_function'`
- **Root cause:** CDK reconcile set handler to `lambda_function.lambda_handler`;
  actual file is `freshness_checker_lambda.py`
- **Fix:** `aws lambda update-function-configuration --handler freshness_checker_lambda.lambda_handler`

### 3. Daily insight compute — PlatformLogger multi-arg TypeError
- **Symptom:** `TypeError: PlatformLogger.info() takes 2 positional arguments but 5 were given`
- **Root cause:** Lambda used `logger.info("msg %s %d", arg1, arg2)` printf-style formatting;
  PlatformLogger only accepts a single message string
- **Fix:** Converted all `%`-format multi-arg logger calls to f-strings throughout
  `lambdas/daily_insight_compute_lambda.py`. Redeployed + smoke tested (200, insights written).

### 4. Monday compass — stale alarm from deleted secret
- **Symptom:** `InvalidRequestException: secret was marked for deletion`
- **Root cause:** Old code was hitting `life-platform/api-keys` (scheduled for deletion 2026-03-17).
  Code was already updated to use `life-platform/ai-keys` (live) but alarm wasn't reset.
- **Fix:** Alarm reset only. Will self-heal on Monday 2026-03-16 when it next runs.

### 5 & 6. failure-pattern-compute + slo-source-freshness
- Stale alarms from 2026-03-09 single errors. Both reset to OK.

---

## All Alarms → OK
All 6 alarms cleared. Platform should wake up clean tomorrow.

---

## Lesson Learned — CDK Reconcile Regression Risk

**CDK reconcile can silently overwrite live handler configs and IAM policies.**
The Todoist IAM path and freshness-checker handler had both been manually set to
non-CDK values and CDK "corrected" them back to its desired state.

**Action required:** Before next CDK reconcile, audit the CDK templates for:
1. IAM S3 resource paths — ensure they match actual Lambda write paths
2. Handler configs — ensure CDK template handler names match actual Python filenames

Then fix the CDK source (not the live config) so CDK's desired state matches reality.
Otherwise every CDK deploy will re-break these.

---

## Files Changed This Session

| File | Change |
|------|--------|
| `lambdas/daily_insight_compute_lambda.py` | All logger calls converted to f-strings |
| `deploy/fix_p0_alarm_bugs.sh` | New: handler + IAM + alarm fixes |
| `deploy/fix_p0_daily_insight_deploy.sh` | New: deploy + smoke test script |
| `docs/CHANGELOG.md` | v3.7.4 entry |
| `handovers/HANDOVER_v3.7.4.md` | This file |
| `handovers/HANDOVER_LATEST.md` | Updated |

---

## Pending Actions (Carry Forward)

1. **⚠️ TB7-4 — api-keys grep sweep (DEADLINE 2026-03-17)**
   ```bash
   grep -rn "api-keys" lambdas/ mcp/ deploy/ --include="*.py" --include="*.sh" --include="*.json"
   ```
   Confirm clean, then permanently delete `life-platform/api-keys`.

2. **CDK source fix (new — HIGH priority before next reconcile)**
   Fix CDK templates so `desired state = reality` for:
   - `LifePlatformIngestion` stack: Todoist IAM S3 resource path
   - `LifePlatformOperational` stack: freshness-checker handler config
   Otherwise next CDK deploy re-breaks both.

3. **TB7-1** — Verify GitHub Settings → Environments → `production` has required reviewers.

4. **TB7-2 / Brittany email** — Set `BRITTANY_EMAIL` env var to her real address.

5. **Google Calendar integration** — Next major feature (6–8h).

---

## Next Development Priorities
1. CDK source fix (before any further reconcile)
2. TB7-4 api-keys grep sweep (deadline 2026-03-17)
3. Google Calendar integration
