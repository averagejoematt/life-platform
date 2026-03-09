# Handover — v3.3.2 — 2026-03-09

## What was done this session

### PROD-1 CDK — LifePlatformIngestion imported ✅

After Compute + Email deployed (v3.3.1), ran `cdk import LifePlatformIngestion --force`.

#### Problems hit and fixed during import

**1. Handler mismatches (7 Lambdas)**
7 ingestion Lambdas have `lambda_function.lambda_handler` in AWS (old zip convention). Updated `ingestion_stack.py` to match AWS reality. These are marked with `# AWS actual` comments — on next `cdk deploy` nothing changes, but the zips should eventually be renamed to module-based handlers.

Lambdas with `lambda_function.lambda_handler` in AWS:
- whoop-data-ingestion, withings-data-ingestion, habitify-data-ingestion, strava-data-ingestion, todoist-data-ingestion, eightsleep-data-ingestion, apple-health-ingestion

**2. EventBridge schedule drift (all 15)**
All ingestion rules fire 1 hour earlier than CDK had. All schedules corrected to match AWS.

**3. Garth layer doesn't exist**
`garth` is bundled in the garmin Lambda zip, not a separate layer. Removed `GARTH_LAYER_ARN` and `additional_layers=[garth_layer]` from ingestion_stack.py.

**4. Alarm names use short form (not full function name)**
AWS alarms use `ingestion-error-<short>` not `ingestion-error-<function-name>`. Added `alarm_name` override param to `lambda_helpers.py`. 8 alarms imported with correct short names.

**5. 7 alarms don't exist in AWS at all**
garmin, notion, habitify, journal-enrichment, weather, dropbox-poll, hae-webhook alarms are absent. Set `alerts_topic=None` for those Lambdas — CDK will create alarms on first `cdk deploy`.

**6. HAE webhook alarm doesn't exist**
Removed the inline HAE alarm block entirely for import. Will be created on first deploy.

#### Import result
- 8 CloudWatch alarms imported ✅
- All Lambda::Permission resources skipped (CDK recreates on deploy) ✅
- All EventBridge rules skipped by --force (already exist, no change needed) ✅

---

## CDK stack status

| Stack | Status | Notes |
|-------|--------|-------|
| LifePlatformCore | Not in CFn | DDB + S3 + SQS + SNS — import deferred |
| LifePlatformIngestion | ✅ Imported | Needs first `cdk deploy` to create missing alarms + Lambda permissions |
| LifePlatformCompute | ✅ Deployed | |
| LifePlatformEmail | ✅ Deployed | |
| LifePlatformOperational | 🔴 Not built | Next session |
| LifePlatformMcp | 🔴 Not built | |
| LifePlatformMonitoring | 🔴 Not built | |
| LifePlatformWeb | 🔴 Not built | |

---

## Immediate next steps

### Option A — First deploy of LifePlatformIngestion (quick win)
Run deploy to bring the stack fully up-to-date — creates the 7 missing alarms, Lambda permissions, and locks in all the handler/schedule fixes:
```bash
cd ~/Documents/Claude/life-platform/cdk && source .venv/bin/activate
npx cdk deploy LifePlatformIngestion --require-approval never
```
⚠️ This will change handler strings on 7 Lambdas in AWS — confirm that's acceptable (the module names still exist in the zips, so it'll break those 7 unless the zips are updated too). Consider skipping for now and leaving as drift.

### Option B — Build LifePlatformOperational stack (next PROD-1 stack)
Lambdas to model:
- freshness-checker, dlq-consumer, canary, pip-audit, qa-smoke, key-rotator, data-export, data-reconciliation

Start by running:
```bash
for fn in freshness-checker dlq-consumer canary pip-audit qa-smoke \
    life-platform-key-rotator data-export data-reconciliation; do
  role=$(aws lambda get-function-configuration --function-name $fn \
    --query Role --output text 2>/dev/null | awk -F'/' '{print $NF}')
  echo "$fn → $role"
done
```

### Option C — Brittany weekly email (fully unblocked, separate from CDK work)

---

## Key lessons learned this session

**Alarm name convention drift:** Pre-SEC-1 alarms used short names (`ingestion-error-whoop`); newer alarms use full function names. When building operational/mcp stacks, check actual alarm names first.

**Handler drift:** Older Lambdas deployed before the module-naming convention use `lambda_function.lambda_handler`. Changing the handler in CDK without updating the zip will break the Lambda. Leave as-is in CDK or update both simultaneously.

**`alerts_topic=None` pattern for missing alarms:** When an alarm doesn't exist in AWS, set `alerts_topic=None` in the Lambda call and let CDK create it on first deploy. Don't try to import a non-existent alarm.

**`alarm_name` override param:** Added to `lambda_helpers.py` — use whenever AWS alarm name doesn't match the default `ingestion-error-{function_name}` pattern.

---

## Platform state

**Version:** v3.3.2

| Epic | Status |
|------|--------|
| SEC-1,2,3,5; IAM-1,2; REL-1,2,3,4; OBS-1,2,3; COST-1,2,3; MAINT-1,2,3,4; DATA-1,2,3; AI-1,2,3,4 | ✅ |
| PROD-1 | ⚠️ Compute ✅ Email ✅ Ingestion ✅; 4 stacks remaining |
| PROD-2 | ✅ |
| SIMP-1 | 🔴 Revisit ~2026-04-08 |
