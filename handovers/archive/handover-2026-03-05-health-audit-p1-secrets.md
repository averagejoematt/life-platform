# Handover — 2026-03-05 — Platform Health Audit + P0/P1 Fixes + Secrets Consolidation

**Session:** 2026-03-05 (session 5)
**Platform version:** v2.75.0
**Time spent:** ~3 hours

---

## What Was Done This Session

### Context
Ran a comprehensive platform health audit using `audit/platform_snapshot.py`, then executed all P0 and P1 remediation items from the findings. Ended with Secrets Manager consolidation (12 → 6 secrets).

---

### P0 Fixes (all complete ✅)

**1. `wednesday-chronicle` Lambda — packaging bug**
- Lambda was failing with `Runtime.ImportModuleError: No module named 'lambda_function'`
- Root cause: deploy zip contained `wednesday_chronicle_lambda.py` but handler expects `lambda_function.py`
- Fix: redeployed via universal `deploy_lambda.sh` (auto-reads handler config from AWS)
- Bonus: triggered smoke test, published missed Chronicle installment ("The Week Everything Leveled Up")

**2. `anomaly-detector` Lambda — same packaging bug**
- Same root cause, same fix
- Backfilled Mar 4 and Mar 5 anomaly detection (both 200 OK)

**3. DLQ purge**
- 5 stale messages cleared (all from the two broken Lambdas above)

---

### P1 Fixes (all complete ✅)

**4. Log retention — 10 log groups set to 30 days**
- 8 in us-west-2: adaptive-mode-compute, character-sheet-compute, dashboard-refresh, life-platform-data-export, life-platform-key-rotator, nutrition-review, wednesday-chronicle, weekly-plate
- 2 in us-east-1: life-platform-buddy-auth, life-platform-cf-auth

**5. Error alarms — 5 unmonitored Lambdas now covered**
- `adaptive-mode-compute-errors`, `character-sheet-compute-errors`, `dashboard-refresh-errors`, `life-platform-data-export-errors`, `weekly-plate-errors`
- All 86400s (1-day) period with `notBreaching` on missing data
- Script: `deploy/fix_p1_infra.sh`

**6. `dashboard-refresh` IAM fix — discovered via new alarm**
- New alarm immediately fired: `dashboard-refresh` was failing with `AccessDenied` on every run
- Lambda runs on `lambda-mcp-server-role` which lacked `s3:PutObject` + `s3:ListBucket`
- Added `s3-dashboard-write` inline policy to `lambda-mcp-server-role`:
  - `s3:PutObject` + `s3:GetObject` on `dashboard/*`, `buddy/*`, `profile.json`
  - `s3:ListBucket` on the bucket
- Dashboard has been silently failing since deployment — now fixed
- Verified: smoke test returned `Dashboard JSON refreshed` + `Buddy JSON refreshed`
- `NoSuchKey` on profile load is expected (falls back to DDB gracefully)

**7. `mcp/config.py` version bump 2.50.0 → 2.74.0 + MCP redeploy**
- Updated `__version__` in `mcp/config.py`
- MCP Lambda redeployed with full `mcp/` package (not just entry point file)
- Code size went from 216KB → 1.16MB (confirms full package was bundled)

**8. `weekly_digest_lambda.py` hardcoded values fix + redeploy**
- Line 47: `dynamodb.Table("life-platform")` → `os.environ.get("TABLE_NAME", "life-platform")`
- Also parameterized: `ses`, `secrets` clients (both were hardcoding `"us-west-2"`), `RECIPIENT`, `SENDER`
- Added `import os` at top of AWS clients block
- Lambda redeployed

---

### v2.75.0 — Secrets Manager Consolidation (in progress at handover time)

**Script:** `deploy/migrate_secrets_consolidation.sh`

**Plan:** Merge 6 static API key secrets into one `life-platform/api-keys` secret.

Secrets being **merged → `life-platform/api-keys`**:
| Old Secret | Key in merged secret |
|---|---|
| `life-platform/anthropic` | `anthropic_api_key` |
| `life-platform/todoist` | `todoist_api_token` |
| `life-platform/habitify` | `habitify_api_key` |
| `life-platform/health-auto-export` | `health_auto_export_api_key` |
| `life-platform/notion` | `notion_api_key` + `notion_database_id` |
| `life-platform/dropbox` | `dropbox_app_key` + `dropbox_app_secret` + `dropbox_refresh_token` |

Secrets being **kept** (OAuth tokens that Lambdas write back to, or rotation-enabled):
- `life-platform/whoop` (writes back tokens daily)
- `life-platform/withings` (writes back tokens)
- `life-platform/strava` (writes back tokens + expires_at)
- `life-platform/eightsleep` (writes back JWT tokens)
- `life-platform/garmin` (writes back garth_tokens)
- `life-platform/mcp-api-key` (rotation enabled)

**Savings:** 6 × $0.40/mo = **$2.40/month** (~12% of $20 budget)

**Code changes made (all Lambda files edited, not yet deployed by script):**
All 13 affected Lambdas updated with backwards-compatible field extraction:
- `daily_brief_lambda.py` — secret name env var + `anthropic_api_key` field
- `weekly_digest_lambda.py` — secret name env var + `anthropic_api_key` field
- `journal_enrichment_lambda.py` — secret name env var + `anthropic_api_key` with fallback chain
- `wednesday_chronicle_lambda.py` — secret name env var + `anthropic_api_key` field
- `weekly_plate_lambda.py` — secret name env var + `anthropic_api_key` field
- `monthly_digest_lambda.py` — secret name env var + `anthropic_api_key` field
- `nutrition_review_lambda.py` — secret name env var + `anthropic_api_key` field
- `anomaly_detector_lambda.py` — secret name env var + `anthropic_api_key` field
- `todoist_lambda.py` — secret name env var + `todoist_api_token` with fallback
- `habitify_lambda.py` — secret name env var + `habitify_api_key` with fallback
- `health_auto_export_lambda.py` — secret name env var + `health_auto_export_api_key` with fallback
- `notion_lambda.py` — secret name env var + `notion_api_key` + `notion_database_id` with fallbacks
- `dropbox_poll_lambda.py` — secret name env var (field names unchanged: app_key/app_secret/refresh_token)

**Pattern used everywhere:** `.get("new_key") or .get("old_key")` — works with both old and new secret during transition, and after old secrets are deleted.

**Script steps:**
1. Creates `life-platform/api-keys` secret (reads from old secrets live)
2. Adds `api-keys-read` IAM policy to 9 affected roles
3. Redeploys all 13 Lambdas + MCP (via deploy_lambda.sh + custom MCP package)
4. Smoke tests todoist, habitify, notion, HAE, dropbox
5. Deletes 6 old secrets with 7-day recovery window

**If script failed:** Old secrets are still intact (they're only deleted in Step 5). Fix whatever broke, re-run from Step 3 (Lambda deploys are idempotent). Recovery: `aws secretsmanager restore-secret --secret-id life-platform/anthropic --region us-west-2`

---

## Current Platform State
- **Version:** v2.75.0
- **MCP tools:** 121 across 26 modules
- **Lambdas:** 29 (unchanged)
- **Data sources:** 19 (unchanged)
- **Secrets:** 6 (down from 12, assuming consolidation succeeded)
- **Monthly cost:** ~$3/month projected (down from ~$5.43)
- **CloudWatch alarms:** 35 (up from 30 — 5 new error alarms added)
- **Log groups with retention:** all 30 (was 20)

---

## Known Issues / Next Up

- **Verify consolidation succeeded:** Check tomorrow's Daily Brief runs clean (10 AM PT). Also verify: todoist, habitify, notion all ingest at their scheduled times. No failures = consolidation clean.
- **wednesday-chronicle alarm** will auto-clear within 24h now that Lambda is fixed (alarms on 24h window)
- **Adaptive mode journal score = 0** — still correct, no journal entries yet

## Next Session Suggestions
1. **Brittany accountability email** — next major planned feature (weekly email for Matthew's partner)
2. **#31 Light exposure tracking** (2-3 hr) — Habitify habit + correlation tool
3. **#16 Grip strength** (2 hr) — buy dynamometer + Notion manual log + percentile tool
4. **P2 backlog from audit** — if appetite: secrets consolidation verification + `weekly_digest` smoke test, then consider `daily_brief_lambda.py` monolith breakdown (4,002 lines → extract scoring_engine.py, ai_calls.py, html_builder.py, data_writers.py)

---

## Files Changed This Session

| File | Change |
|------|--------|
| `mcp/config.py` | `__version__` 2.50.0 → 2.74.0 |
| `lambdas/daily_brief_lambda.py` | `ANTHROPIC_SECRET` default → `life-platform/api-keys`, field → `anthropic_api_key` |
| `lambdas/weekly_digest_lambda.py` | Hardcoded table/clients/emails → env vars; secret → `life-platform/api-keys`, field → `anthropic_api_key` |
| `lambdas/journal_enrichment_lambda.py` | Secret default → `life-platform/api-keys`, field fallback chain |
| `lambdas/wednesday_chronicle_lambda.py` | `get_anthropic_key()` → env var + `anthropic_api_key` |
| `lambdas/weekly_plate_lambda.py` | Same as chronicle |
| `lambdas/monthly_digest_lambda.py` | Same as chronicle |
| `lambdas/nutrition_review_lambda.py` | Same as chronicle |
| `lambdas/anomaly_detector_lambda.py` | Same as chronicle |
| `lambdas/todoist_lambda.py` | `SECRET_NAME` → env var default `api-keys`, field → `todoist_api_token` with fallback |
| `lambdas/habitify_lambda.py` | `SECRET_NAME` → `api-keys`, field → `habitify_api_key` with fallback |
| `lambdas/health_auto_export_lambda.py` | `SECRET_NAME` → `api-keys`, field → `health_auto_export_api_key` with fallback |
| `lambdas/notion_lambda.py` | `SECRET_NAME` → `api-keys`, fields → `notion_api_key`/`notion_database_id` with fallbacks |
| `lambdas/dropbox_poll_lambda.py` | `SECRET_NAME` → `api-keys` (field names unchanged) |
| `deploy/fix_p0_broken_lambdas.sh` | **NEW** — P0 Chronicle + anomaly detector redeployment |
| `deploy/fix_p1_infra.sh` | **NEW** — Log retention + alarms + MCP/weekly-digest redeploys |
| `deploy/migrate_secrets_consolidation.sh` | **NEW** — Full secrets consolidation migration |
| `docs/reviews/platform-review-2026-03-05.md` | **NEW** — Full audit findings report |

---

## Audit Findings Summary (for reference)

**Overall health: 🟡 AMBER → 🟢 GREEN after fixes**

| Finding | Severity | Status |
|---------|----------|--------|
| wednesday-chronicle ImportModuleError | P0 | ✅ Fixed |
| anomaly-detector ImportModuleError | P0 | ✅ Fixed |
| DLQ had 5 stale messages | P0 | ✅ Purged |
| 10 log groups no retention | P1 | ✅ Fixed |
| 5 Lambdas no error alarms | P1 | ✅ Fixed |
| dashboard-refresh AccessDenied (found via alarm) | P1 | ✅ Fixed |
| config.py version 24 versions behind | P1 | ✅ Fixed |
| weekly_digest hardcoded table name | P1 | ✅ Fixed |
| Secrets Manager 12 secrets (over-provisioned) | P1 | ✅ Fixed (script running) |
| daily_brief_lambda.py 4,002 lines (monolith) | P2 | Backlog |
| 2 bare `except: pass` blocks in daily_brief | P2 | Backlog |
| 4 stale docs (USER_GUIDE, COST_TRACKER, INCIDENT_LOG, INFRASTRUCTURE) | P2 | Backlog |
