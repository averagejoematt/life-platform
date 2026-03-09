# Handover — v3.2.7 — 2026-03-09

## What was done this session

### PROD-1 CDK IngestionStack — cdk synth PASSING ✅

Written and validated `cdk/stacks/ingestion_stack.py` covering all 15 ingestion Lambdas:

| # | Lambda | Trigger | Notes |
|---|--------|---------|-------|
| 1 | whoop-data-ingestion | cron(0 14) + cron(30 17) | 2 EventBridge rules |
| 2 | garmin-data-ingestion | cron(0 14) | garth layer attached |
| 3 | notion-journal-ingestion | cron(0 14) | |
| 4 | withings-data-ingestion | cron(15 14) | OAuth token refresh |
| 5 | habitify-data-ingestion | cron(15 14) | api-keys secret |
| 6 | strava-data-ingestion | cron(30 14) | OAuth token refresh |
| 7 | journal-enrichment | cron(30 14) | ai-keys secret |
| 8 | todoist-data-ingestion | cron(45 14) | |
| 9 | eightsleep-data-ingestion | cron(0 15) | |
| 10 | activity-enrichment | cron(30 15) | ai-keys secret |
| 11 | macrofactor-data-ingestion | cron(0 16) + S3* | S3 notification outside CDK |
| 12 | weather-data-ingestion | cron(45 13) | no S3 write |
| 13 | dropbox-poll | rate(30 minutes) | |
| 14 | apple-health-ingestion | S3* | S3 notification outside CDK, 512MB |
| 15 | health-auto-export-webhook | API GW* | no DLQ, 30s timeout, API GW outside CDK |

*S3 notifications and API Gateway not imported into CDK — kept external to avoid cyclic deps.

### Key bugs fixed during synth

1. **ENAMETOOLONG** — `Code.from_asset(".")` from cdk/ dir bundled `.venv` recursively.
   Fix: changed to `Code.from_asset("..")` (project root) with comprehensive excludes.

2. **Cyclic dependency** — `bucket.grant_read_write(role)` / `table.grant_*` mutate CoreStack
   resource policies with IngestionStack ARNs → `CoreStack → IngestionStack → CoreStack`.
   Fix: replaced all `grant_*` with explicit `role.add_to_policy(PolicyStatement(...))`.

3. **Deprecated API** — `pointInTimeRecovery=True` in core_stack.py.
   Fix: replaced with `point_in_time_recovery_specification=CfnTable.PointInTimeRecoverySpecificationProperty(...)`.

### New files
- `cdk/stacks/ingestion_stack.py`
- `cdk/cdk.json`

### Modified files
- `cdk/app.py` — IngestionStack wired in
- `cdk/stacks/lambda_helpers.py` — asset path, excludes, grant→policy fix
- `cdk/stacks/core_stack.py` — PITR deprecation fix

---

## Immediate next steps

### 1. cdk import LifePlatformIngestion (NEXT SESSION — don't rush)
Run in a fresh session after reviewing the synth output carefully:
```bash
cd ~/Documents/Claude/life-platform/cdk
source .venv/bin/activate
npx cdk import LifePlatformIngestion
```
CDK will prompt for each Lambda's physical resource name. Get them with:
```bash
aws lambda list-functions --query 'Functions[?starts_with(FunctionName, `whoop`) || starts_with(FunctionName, `garmin`) || starts_with(FunctionName, `strava`)].FunctionName'
# etc — or just type the names as prompted
```
Verify via CloudWatch after import — CDK import does NOT redeploy code.

⚠️ **Update GARTH_LAYER_ARN** in ingestion_stack.py before importing:
```bash
aws lambda list-layers --query 'Layers[?contains(LayerName, `garth`)].LatestMatchingVersion.LayerVersionArn'
```

### 2. Remaining PROD-1 CDK stacks (sessions 3–6)
- compute_stack.py (5 Lambdas: character-sheet-compute, dashboard-refresh x2, etc.)
- email_stack.py (7 Lambdas: daily-brief, weekly-digest, monthly-digest, etc.)
- operational_stack.py (anomaly, freshness, canary, dlq-consumer, key-rotator, etc.)
- mcp_stack.py (life-platform-mcp + Function URL)
- monitoring_stack.py (35 alarms)

### 3. Brittany weekly email (fully unblocked — no other dependencies)

### 4. PROD-2 manual follow-up (AWS console — not blocking)
- SES receipt rule: update prefix → `raw/matthew/inbound_email/`
- S3 event notification for insight-email-parser: update prefix → `raw/matthew/inbound_email/`

### 5. Old S3 path cleanup (~2026-03-16 when safe)
```bash
aws s3 rm s3://matthew-life-platform/raw/ --recursive --exclude 'raw/matthew/*'
# + delete config/board_of_directors.json, config/character_sheet.json, config/project_pillar_map.json
```

---

## Platform state

**Version:** v3.2.7
**Hardening:** ~98% complete

| Epic | Status |
|------|--------|
| SEC-1,2,3,5 | ✅ |
| IAM-1,2 | ✅ |
| REL-1,2,3,4 | ✅ |
| OBS-1,2,3 | ✅ |
| COST-1,2,3 | ✅ |
| MAINT-1,2,3,4 | ✅ |
| DATA-1,2,3 | ✅ |
| AI-1,2,3,4 | ✅ |
| PROD-1 | ⚠️ IngestionStack synth ✅; import + 5 more stacks remain |
| PROD-2 | ✅ Phase 1 + Phase 2 done |
| SIMP-1 | 🔴 Revisit ~2026-04-08 |

## CDK environment
- Location: `~/Documents/Claude/life-platform/cdk/`
- Activate venv: `source .venv/bin/activate`
- Synth: `npx cdk synth LifePlatformIngestion`
- Node v25 warning is harmless — CDK runs fine
