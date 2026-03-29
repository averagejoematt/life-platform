# Handover — v3.4.7 — 2026-03-10: IAM Health Check Complete

## Session Summary
Full platform health check following the COST-A/COST-B CDK migration. Found and fixed a systemic IAM bug affecting all ingestion Lambdas (S3 path mismatch), plus Strava OAuth and Dropbox path issues. Platform is now fully operational.

---

## Bugs Found and Fixed This Session

### v3.4.6 — Email Lambdas (3 bugs)
1. `EMAIL_RECIPIENT`/`EMAIL_SENDER` missing from CDK base env → added to `lambda_helpers.py` + `cdk.json`
2. `kms:Decrypt` missing from all 8 email Lambda roles (`_email_base()`) → added
3. `timezone` UnboundLocalError in `daily_brief_lambda.py` → removed inner re-import

### v3.4.7 — Ingestion Lambdas (IAM health check)
4. **S3 path mismatch (systemic):** All Lambdas write to `raw/matthew/<source>/...` but CDK policies granted `raw/<source>/*`. Fixed `_ingestion_base()` default prefix + all hardcoded prefixes.
5. **Strava OAuth:** Missing `secretsmanager:PutSecretValue` — token refresh on every API call was silently failing.
6. **HAE webhook:** S3 write path broadened to `raw/matthew/*` (writes to cgm_readings, blood_pressure, state_of_mind, workouts sub-paths).
7. **Dropbox:** S3 path corrected `imports/*` → `uploads/macrofactor/*`.
8. **KMS (5 inline functions):** `journal_enrichment`, `activity_enrichment`, `apple_health`, `hae`, `weather` were all missing `kms:Decrypt`.

---

## Platform Status — All Green ✅

| System | Status |
|--------|--------|
| `daily-brief` | ✅ Sending (confirmed 200) |
| `whoop-data-ingestion` | ✅ 200 post-deploy |
| `strava-data-ingestion` | ✅ 200 post-deploy |
| `journal-enrichment` | ✅ 200 post-deploy |
| `daily-metrics-compute` | ✅ Healthy |
| `character-sheet-compute` | ✅ Healthy |
| `dashboard-refresh` | ✅ Healthy |
| DLQ | ✅ Purged (67 stale messages from broken period) |
| CloudWatch alarms | ⏳ 14 in ALARM — all stale (Mar 7-9), will self-clear tonight |

---

## Key Files Changed
- `cdk/stacks/role_policies.py` — systemic S3 path fix + KMS additions + Strava PutSecretValue + Dropbox path
- `cdk/stacks/lambda_helpers.py` — EMAIL_RECIPIENT + EMAIL_SENDER base env
- `cdk/cdk.json` — email context keys
- `lambdas/daily_brief_lambda.py` — timezone UnboundLocalError fix

## Deployed
- `LifePlatformEmail` (2x)
- `LifePlatformIngestion` (1x)
- `daily-brief` Lambda

---

## Outstanding Items
| Item | Priority | Notes |
|------|----------|-------|
| CloudWatch alarms (14) | Low | All stale Mar 7-9, self-clear tonight with clean runs |
| `life-platform/api-keys` deletion | ~2026-04-07 | Auto, saves $0.40/mo |
| `life-platform/habitify` secret creation | Before 2026-04-07 | Before api-keys expires |
| SIMP-1 MCP tool usage audit | ~2026-04-08 | 30 days data needed |
| Brittany weekly email | Next major feature | |
| Character Sheet Phase 4 | Backlog | |
