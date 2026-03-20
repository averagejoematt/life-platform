# Life Platform — Runbook

Last updated: 2026-03-20 (v3.7.78 — 95 MCP tools, 31-module package, 49 Lambdas, 19 data sources)

---

## S3 Safety Rules (ADR-032, ADR-033)

**Never run `aws s3 sync --delete` to the bucket root.** On 2026-03-16, this deleted 35,188 objects. Three protection layers are now in place:

1. **Bucket policy:** `matthew-admin` cannot `DeleteObject` on `raw/*`, `config/*`, `uploads/*`, `dashboard/*`, `exports/*`, `deploys/*`, `cloudtrail/*`, `imports/*`. Lambda roles are unaffected.
2. **safe_sync wrapper:** `source deploy/lib/safe_sync.sh` then call `safe_sync "$SRC" "$DST"` instead of raw `aws s3 sync --delete`. Blocks bucket-root targets and aborts if dryrun shows >100 deletions.
3. **S3 versioning:** Enabled. Even if objects are deleted, they can be recovered by removing delete markers.

**For site deploys:** Always use `bash deploy/sync_site_to_s3.sh`. It targets `s3://matthew-life-platform/site/` with correct cache-control headers.

**To recover from accidental S3 deletion:**
```bash
# Check if versioning saved the objects
aws s3api list-object-versions --bucket matthew-life-platform --prefix raw/strava/ --max-keys 5

# Batch restore (removes delete markers)
cat > /tmp/restore_s3.py << 'SCRIPT'
import boto3, sys
bucket = "matthew-life-platform"
prefix = sys.argv[1] if len(sys.argv) > 1 else ""
s3 = boto3.client("s3", region_name="us-west-2")
total = 0
for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket, Prefix=prefix):
    batch = [{"Key": dm["Key"], "VersionId": dm["VersionId"]} for dm in page.get("DeleteMarkers", []) if dm["IsLatest"]]
    if batch:
        s3.delete_objects(Bucket=bucket, Delete={"Objects": batch[:1000], "Quiet": True})
        total += len(batch)
        print(f"  Restored {total}...", flush=True)
print(f"Done. Restored {total} objects.")
SCRIPT
python3 /tmp/restore_s3.py raw/
```

**To temporarily bypass the bucket policy (for legitimate bulk deletes):**
```bash
aws s3api delete-bucket-policy --bucket matthew-life-platform
# Do the work...
# Re-apply: aws s3api put-bucket-policy --bucket matthew-life-platform --policy file:///tmp/bucket_policy.json
```

**No one-off deploy scripts.** Two P1/P2 incidents (Mar 11, Mar 16) traced to one-off scripts bypassing canonical tooling. Use canonical scripts with flags, or modify them temporarily.

---

## Daily Operations

### Scheduled ingestion times (Pacific Time)

**⚠️ All EventBridge crons use fixed UTC. Times below reflect PDT (UTC-7, from March 8 2026). During PST (UTC-8, Nov–Mar) all times shift 1 hour earlier.**
| Source | Schedule | Lambda |
|--------|----------|--------|
| Whoop | 07:00 AM | whoop-data-ingestion |
| Garmin | 07:00 AM | garmin-data-ingestion |
| Notion Journal | 07:00 AM | notion-journal-ingestion |
| Withings | 07:15 AM | withings-data-ingestion |
| Habitify | 07:15 AM | habitify-data-ingestion |
| Strava | 07:30 AM | strava-data-ingestion |
| Journal Enrichment | 07:30 AM | journal-enrichment |
| Todoist | 07:45 AM | todoist-data-ingestion |
| Eight Sleep | 08:00 AM | eightsleep-data-ingestion |
| Activity Enrichment | 08:30 AM | activity-enrichment |
| MacroFactor | 09:00 AM | macrofactor-data-ingestion (EventBridge + S3 trigger) |
| MCP Cache Warmer | 10:00 AM | life-platform-mcp (EventBridge payload) |
| Whoop Recovery Refresh | 10:30 AM | whoop-data-ingestion (date_override: today) |
| Character Sheet Compute | 10:35 AM | character-sheet-compute (v1.0, reads yesterday's data, stores to DDB) |
| Daily Metrics Compute | 10:25 AM | daily-metrics-compute (day grade, readiness, streaks, TSB, HRV, weight → `computed_metrics` partition) |
| Daily Insight Compute | 10:20 AM | daily-insight-compute (IC-8: 7-day habit×outcome correlations, leading indicators, platform_memory pull, structured JSON for Daily Brief AI calls) |
| Freshness Check | 10:45 AM | life-platform-freshness-checker |
| Daily Brief | 11:00 AM | daily-brief (v2.62, 18 sections, 4 AI calls, reads character_sheet record, dedup, regrade mode, dynamic weight context, 7d training context) |
| **DST note** | — | All crons fixed UTC. Times above are PDT (UTC-7). DST is now active (PDT = UTC-7). |
| Anomaly Detector | 09:05 AM | anomaly-detector |
| Nutrition Review | 09:00 AM (Saturday only) | nutrition-review (v1.1, Sonnet, 3-expert panel) |
| Weekly Digest | 08:00 AM (Sunday only) | weekly-digest (v4.3) |
| Monthly Digest | 08:00 AM (1st Monday only) | monthly-digest (v1.1) |
| Wednesday Chronicle | 07:00 AM (Wednesday only) | wednesday-chronicle (v1.1, Sonnet, Elena Voss) |
| Monday Compass | 08:00 AM (Monday only) | monday-compass (v1.0, Sonnet, weekly planning email — tasks by pillar, Board Pro Tips, Keystone) |
| The Weekly Plate | 07:00 PM (Friday only) | weekly-plate (v1.0, Sonnet, food magazine email, ~63s) |
| Dashboard Refresh | 02:00 PM | dashboard-refresh (lightweight, no AI — updates weight/glucose/zone2/TSB/buddy) |
| Dashboard Refresh | 06:00 PM | dashboard-refresh (same as above, second daily run) |
| Dropbox Poll | Every 30 min | dropbox-poll |

**MacroFactor** uses an automated Dropbox pipeline: phone export → Dropbox `/life-platform/` → `dropbox-poll` Lambda (every 30 min) → S3 → `macrofactor-data-ingestion`. Auto-detects nutrition vs workout CSVs. Manual S3 upload (`s3://matthew-life-platform/imports/macrofactor/`) still works as fallback.

**Apple Health** primary path is the Health Auto Export webhook (hourly push from iOS): Stelo/Apple Watch → HealthKit → Health Auto Export app → API Gateway → `health-auto-export-webhook`. Manual S3 XML upload (`s3://matthew-life-platform/imports/apple_health/`) still works for backfills.

**⚠️ Health Auto Export gotcha:** The app must be configured for hourly (not "since last run") sync to reliably include all metric types. With infrequent syncs, payload size grows and the app may silently drop metrics like Dietary Water and Dietary Caffeine, sending only activity data. If water/caffeine stop appearing in webhook logs, check the app's sync interval.

---

## How to Check If Ingestion Ran

### Via CloudWatch Logs (quickest)
```bash
aws logs tail /aws/lambda/whoop-data-ingestion --since 24h
```
Replace `whoop-data-ingestion` with any function name.

### Via CloudWatch Alarms
```bash
aws cloudwatch describe-alarms --alarm-names \
  ingestion-error-whoop ingestion-error-withings ingestion-error-strava \
  ingestion-error-todoist ingestion-error-eightsleep ingestion-error-macrofactor \
  ingestion-error-apple-health garmin-ingestion-errors habitify-ingestion-errors \
  --query 'MetricAlarms[*].{Name:AlarmName,State:StateValue}'
```
All should be `OK`. If any show `ALARM`, check that function's logs.

### Via DLQ (failed messages land here)
```bash
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-west-2.amazonaws.com/205930651321/life-platform-ingestion-dlq \
  --attribute-names ApproximateNumberOfMessages
```
Should be `0`. If non-zero, use the console to inspect messages.

---

## How to Manually Trigger a Lambda

```bash
aws lambda invoke \
  --function-name whoop-data-ingestion \
  --payload '{}' \
  /tmp/response.json && cat /tmp/response.json
```

## Cache Warmer

12 tools are pre-computed nightly at 9:00 AM PT via EventBridge → MCP Lambda. Tools with cached results return in <100ms. Custom date ranges bypass cache and compute fresh.

Manually trigger warmer:
```bash
aws lambda invoke \
  --function-name life-platform-mcp \
  --payload '{"source": "aws.events"}' \
  /tmp/warmer.json && cat /tmp/warmer.json
```

Verify cache items exist:
```bash
aws dynamodb query \
  --table-name life-platform \
  --key-condition-expression "PK = :pk" \
  --expression-attribute-values '{":pk":{"S":"CACHE#matthew"}}' \
  --query 'Count'
```
Expected: 12 items.

---

## Secrets Management

All secrets are stored in AWS Secrets Manager under `life-platform/` prefix:

| Secret | Function | Notes |
|--------|----------|-------|
| `life-platform/whoop` | whoop-data-ingestion | OAuth2 access + refresh tokens; auto-updated on each run |
| `life-platform/withings` | withings-data-ingestion | OAuth2 tokens; auto-updated |
| `life-platform/strava` | strava-data-ingestion | OAuth2 tokens; auto-updated |
| `life-platform/garmin` | garmin-data-ingestion | garth OAuth tokens; auto-refreshed; falls back to password re-login |
| `life-platform/eightsleep` | eightsleep-data-ingestion | Username + password (JWT); auto-refreshed on each run |
| `life-platform/ai-keys` | All email/compute/MCP Lambdas | Anthropic API key + MCP API key (90-day auto-rotation) |
| `life-platform/todoist` | todoist-data-ingestion | Static API key; get from Todoist Settings → Integrations |
| `life-platform/notion` | notion-journal-ingestion | Notion integration key + database ID |
| `life-platform/habitify` | habitify-data-ingestion | Static API key; get from Habitify Settings → Account → API |

To view a secret value (for debugging):
```bash
aws secretsmanager get-secret-value --secret-id life-platform/whoop --query SecretString --output text
```

---

## IAM Roles (per-function, least privilege)

Each Lambda has its own dedicated IAM role scoped to exactly what it needs:

| Role | Function | Secrets Access |
|------|----------|---------------|
| lambda-whoop-role | whoop-data-ingestion | life-platform/whoop only |
| lambda-withings-role | withings-data-ingestion | life-platform/withings only |
| lambda-strava-role | strava-data-ingestion | life-platform/strava only |
| lambda-todoist-role | todoist-data-ingestion | life-platform/todoist only |
| lambda-eightsleep-role | eightsleep-data-ingestion | life-platform/eightsleep only |
| lambda-macrofactor-role | macrofactor-data-ingestion | None |
| lambda-apple-health-role | apple-health-ingestion | None |
| lambda-garmin-ingestion-role | garmin-data-ingestion | life-platform/garmin only |
| lambda-habitify-ingestion-role | habitify-data-ingestion | life-platform/habitify only |
| lambda-mcp-server-role | life-platform-mcp | DynamoDB GetItem + Query + PutItem (cache writes) |
| lambda-anomaly-detector-role | anomaly-detector | life-platform/anthropic (Haiku for hypothesis) |
| lambda-notion-ingestion-role | notion-journal-ingestion | life-platform/notion only |
| lambda-journal-enrichment-role | journal-enrichment | life-platform/anthropic only |
| lambda-dropbox-poll-role | dropbox-poll | life-platform/dropbox only |
| lambda-health-auto-export-role | health-auto-export-webhook | life-platform/health-auto-export only |
| lambda-freshness-checker-role | life-platform-freshness-checker | None |
| lambda-daily-brief-role | daily-brief | life-platform/ai-keys |
| lambda-weekly-digest-role-v2 | weekly-digest | life-platform/ai-keys |
| lambda-monthly-digest-role | monthly-digest | life-platform/ai-keys |
| lambda-nutrition-review-role | nutrition-review | life-platform/ai-keys |
| lambda-wednesday-chronicle-role | wednesday-chronicle | life-platform/ai-keys |
| lambda-weekly-plate-role | weekly-plate | life-platform/ai-keys |

*Note: As of SEC-1 (PROD-1, v3.4.0), all Lambdas have dedicated IAM roles. No shared roles remain. All roles CDK-managed via `role_policies.py`.*

---

## DynamoDB

Table: `life-platform` (us-west-2)  
Design: Single-table with composite keys  
- Partition key: `PK` (e.g., `USER#matthew#SOURCE#whoop`)  
- Sort key: `SK` (e.g., `DATE#2026-02-22`)

### Check item count
```bash
aws dynamodb describe-table --table-name life-platform \
  --query 'Table.ItemCount'
```

### Query a specific source
```bash
aws dynamodb query \
  --table-name life-platform \
  --key-condition-expression "PK = :pk AND begins_with(SK, :sk)" \
  --expression-attribute-values '{":pk":{"S":"USER#matthew#SOURCE#whoop"},":sk":{"S":"DATE#2026-02"}}' \
  --query 'Items[*].SK.S'
```

---

## DynamoDB PITR Restore (R8-ST2)

PITR (Point-In-Time Recovery) is enabled on `life-platform`. This gives a 35-day continuous backup window. PITR restores to a **new table** — the original table is never overwritten.

### Verify PITR is enabled
```bash
aws dynamodb describe-continuous-backups \
  --table-name life-platform \
  --region us-west-2 \
  --query 'ContinuousBackupsDescription.PointInTimeRecoveryDescription'
```
Expected: `PointInTimeRecoveryStatus: ENABLED` with `EarliestRestorableDateTime` and `LatestRestorableDateTime`.

### Restore to a test table (drill procedure)
Use this to verify integrity without touching production:
```bash
# Restore to a timestamped test table (use ISO 8601 UTC)
RESTORE_TIME="2026-03-14T10:00:00Z"   # adjust to desired point-in-time

aws dynamodb restore-table-to-point-in-time \
  --source-table-name life-platform \
  --target-table-name life-platform-restore-test \
  --restore-date-time "$RESTORE_TIME" \
  --region us-west-2
```

Monitor restore status (takes 5–20 minutes depending on table size):
```bash
aws dynamodb describe-table \
  --table-name life-platform-restore-test \
  --region us-west-2 \
  --query 'Table.TableStatus'
# ACTIVE = restore complete
```

Verify data integrity after restore:
```bash
# Check item count
aws dynamodb describe-table \
  --table-name life-platform-restore-test \
  --query 'Table.ItemCount' \
  --region us-west-2

# Spot-check a known record (e.g. yesterday's whoop data)
YESTERDAY=$(date -u -v-1d +%Y-%m-%d)
aws dynamodb get-item \
  --table-name life-platform-restore-test \
  --key "{\"pk\":{\"S\":\"USER#matthew#SOURCE#whoop\"},\"sk\":{\"S\":\"DATE#${YESTERDAY}\"}}" \
  --region us-west-2
```

Delete the test table when done:
```bash
aws dynamodb delete-table \
  --table-name life-platform-restore-test \
  --region us-west-2
```

### Emergency: restore to production (data loss recovery)
Only if the production table is corrupted or accidentally deleted:
```bash
# 1. Restore to a temporary table first
aws dynamodb restore-table-to-point-in-time \
  --source-table-name life-platform \
  --target-table-name life-platform-recovered \
  --restore-date-time "<last-known-good-timestamp>" \
  --region us-west-2

# 2. Verify integrity (see drill procedure above, substitute table name)

# 3. Update all Lambda env vars to point to life-platform-recovered:
#    TABLE_NAME env var on all 42 Lambdas — easiest via CDK redeploy
#    cdk deploy --all (will set TABLE_NAME across all stacks)

# 4. Enable PITR on the recovered table:
aws dynamodb update-continuous-backups \
  --table-name life-platform-recovered \
  --point-in-time-recovery-specification PointInTimeRecoveryEnabled=true \
  --region us-west-2
```

### Notes
- PITR has no additional restore cost beyond storage (~$0.10/mo for this table size).
- Restore is to a new table — original is never touched, so there's no risk in initiating a restore.
- KMS: the restored table uses the same CMK. No key rotation needed.
- Deletion protection is enabled on `life-platform` — accidental deletes require a 2-step process.

---

## Common Issues

### Whoop/Withings/Strava: "Token expired" error
These functions auto-refresh tokens and write back to Secrets Manager. If they fail with auth errors, the refresh token itself may have expired (rare but possible if the function didn't run for weeks). Resolution: re-authenticate via the source app and manually update the secret.

### Eight Sleep: JWT auth failure
Eight Sleep uses username/password → JWT (no OAuth). If the JWT refresh fails, the function will write to the DLQ. Check logs for the specific error. Resolution may require re-entering credentials in Secrets Manager if the account password changed.

### MacroFactor: Function not triggered
Ensure your export CSV is dropped into the correct S3 path: `s3://matthew-life-platform/uploads/macrofactor/`. The filename does not matter but the prefix does.

### Apple Health: Large export timeout
Apple Health exports can be large. The function has 1024 MB memory and a 5-minute timeout. If it times out on a very large export, consider exporting a shorter date range.

---

## Verifying DynamoDB TTL is Active

The cache partition uses a 26-hour TTL. Confirm it’s actually enabled:

```bash
aws dynamodb describe-time-to-live \
  --table-name life-platform \
  --region us-west-2
```

Expected output: `{"TimeToLiveDescription": {"AttributeName": "ttl", "TimeToLiveStatus": "ENABLED"}}`

If status is `DISABLED`, enable it:
```bash
aws dynamodb update-time-to-live \
  --table-name life-platform \
  --time-to-live-specification "Enabled=true,AttributeName=ttl" \
  --region us-west-2
```

---

## MCP Server Failure

If Claude tools are returning errors or the MCP server appears unresponsive:

1. Check Lambda logs:
```bash
aws logs tail /aws/lambda/life-platform-mcp --since 1h
```

2. Verify the Lambda Function URL is up:
```bash
curl -s -o /dev/null -w "%{http_code}" \
  -H "x-api-key: <your-key>" \
  https://votqefkra435xwrccmapxxbj6y0jawgn.lambda-url.us-west-2.on.aws/
```

3. Confirm the API key in `mcp_bridge.py` matches the value in Secrets Manager:
```bash
aws secretsmanager get-secret-value \
  --secret-id life-platform/mcp-api-key \
  --query SecretString --output text
```

4. If the Lambda itself is broken, check for a recent deploy that may have introduced a syntax error — redeploy the last known-good version from the local `.py` file.
5. Check Lambda memory is 1024 MB (doubled in v2.33.0). If reverted, heavy queries will be slow:
```bash
aws lambda get-function-configuration --function-name life-platform-mcp --query 'MemorySize'
```

---

## Setting CloudWatch Log Retention (run once, then done)

Prevents indefinite log accumulation. Run for each Lambda:

```bash
for fn in whoop-data-ingestion withings-data-ingestion strava-data-ingestion \
  todoist-data-ingestion eightsleep-data-ingestion macrofactor-data-ingestion \
  apple-health-ingestion health-auto-export-webhook activity-enrichment \
  notion-journal-ingestion journal-enrichment life-platform-mcp \
  anomaly-detector life-platform-freshness-checker dropbox-poll \
  daily-brief weekly-digest monthly-digest \
  garmin-data-ingestion habitify-data-ingestion; do
  aws logs put-retention-policy \
    --log-group-name /aws/lambda/$fn \
    --retention-in-days 30 \
    --region us-west-2
done
```

---

## Day Grade Regrade

If source data is backfilled or a scoring bug is fixed, recompute stored day grades without sending email:

```bash
aws lambda invoke \
  --function-name daily-brief \
  --payload '{"regrade_dates":["2026-02-24","2026-02-25","2026-02-26"]}' \
  --cli-binary-format raw-in-base64-out \
  --region us-west-2 /tmp/regrade.json && cat /tmp/regrade.json
```

This re-runs `gather_daily_data` + `compute_day_grade` + `store_day_grade` for each date. No email sent, no buddy/dashboard JSON regenerated. Check results in the output JSON or CloudWatch logs (`[REGRADE]` prefix).

---

## Activity Dedup (WHOOP + Garmin → Strava)

Both WHOOP and Garmin independently push activities to Strava, causing duplicates. The `_dedup_activities()` function handles this at read-time:
- Detects overlaps: activities starting within 15 min with durations within 40%
- Device priority: Garmin (3) > Apple (2) > WHOOP (1)
- Applied in: buddy JSON generation + daily brief exercise section
- **Not yet applied in:** MCP tools querying Strava directly, or at ingestion time

To check for duplicates on a specific date:
```bash
aws dynamodb get-item --table-name life-platform \
  --key '{"pk":{"S":"USER#matthew#SOURCE#strava"},"sk":{"S":"DATE#2026-03-01"}}' \
  --projection-expression "activities" --region us-west-2
```

---

## Cost Monitoring

Monthly budget target: under $20  
CloudWatch billing alarm fires at: $5  

Check current MTD spend:
```bash
aws ce get-cost-and-usage \
  --time-period Start=2026-02-01,End=2026-03-01 \
  --granularity MONTHLY \
  --metrics UnblendedCost \
  --region us-east-1
```

---

## Lambda Environment Variable Audit

Manually-set env vars (set via console or CLI outside of CDK) can override CDK's desired state and cause silent failures when secrets are renamed or deleted. Run this audit after any secret restructuring or CDK migration.

```bash
# List all Lambda functions and their environment variables
aws lambda list-functions --region us-west-2 \
  --query 'Functions[*].{Name:FunctionName,Env:Environment.Variables}' \
  --output json | python3 -c "
import json, sys
data = json.load(sys.stdin)
for fn in sorted(data, key=lambda x: x['Name']):
    env = fn.get('Env') or {}
    if env:
        print(fn['Name'])
        for k, v in env.items():
            # Redact secret values
            print(f'  {k} = {v[:4]}...' if len(v) > 8 else f'  {k} = {v}')
"
```

**What to look for:**
- `SECRET_NAME` pointing at a deleted secret (e.g., `life-platform/api-keys`)
- `TABLE_NAME` values different from `life-platform`
- Any env var not set by CDK in `cdk/stacks/lambda_helpers.py` or `role_policies.py`

**How to remove a rogue env var:**
```bash
aws lambda update-function-configuration \
  --function-name <function-name> \
  --environment '{"Variables":{}}' \
  --region us-west-2
# Or remove a specific variable while keeping others:
# Get current vars, remove the bad one, then put the remainder back
```

**ADR-014 principle:** Env vars should only exist in CDK. If it's not in a stack file, it shouldn't exist on the Lambda.

---

## Deployment Best Practices (from PIR-2026-02-28)

1. **Always smoke test after deploy:** Invoke Lambda and check for errors:
   ```bash
   aws lambda invoke --function-name <name> --payload '{}' /tmp/test.json --region us-west-2 && grep -i error /tmp/test.json
   ```
2. **Check handler consistency:** Ensure zip filename matches handler config:
   ```bash
   aws lambda get-function-configuration --function-name <name> --query 'Handler' --region us-west-2
   ```
3. **Cross-platform builds:** Python deps must use `--platform manylinux2014_x86_64 --only-binary=:all:` (not macOS `.so` files)
4. **IAM co-location:** If a code change adds new AWS operations (e.g., `dynamodb:Query` for gap-fill), update IAM in the same deploy
5. **Deploy manifest:** See `deploy/MANIFEST.md` for Lambda → handler → zip mappings
6. **Smoke test template:** Source `deploy/SMOKE_TEST_TEMPLATE.sh` for reusable test functions
7. **Wait 10 seconds** between sequential Lambda deploys

---

## Withings OAuth Re-Authorization

If the Withings refresh token expires (cascading failure from extended Lambda downtime):

```bash
cd ~/Documents/Claude/life-platform
python3 setup/fix_withings_oauth.py
```

This launches a local callback server, opens the browser for Withings OAuth consent, captures the new tokens, and writes them to Secrets Manager. Verify with:
```bash
aws lambda invoke --function-name withings-data-ingestion --payload '{}' /tmp/test.json --region us-west-2 && cat /tmp/test.json
```

---

## Adding a New Data Source — Complete Checklist

> **Use this checklist for every new ingestion source.** Missing any of these steps creates
> technical debt that the next architecture review will find. Complete all steps in the same
> session as the feature work — don't defer.

### Code & Infrastructure
- [ ] **Lambda**: Write `lambdas/<source>_lambda.py`. Use `ingestion_framework.py` base if possible (new sources should always use the framework — see ADR-019). Add graceful handling for missing secrets (return 200, not 500, before OAuth is set up).
- [ ] **CDK IAM**: Add `ingestion_<source>()` policy function in `cdk/stacks/role_policies.py` with least-privilege DDB/S3/secret permissions
- [ ] **CDK Stack**: Wire Lambda in `cdk/stacks/ingestion_stack.py` with correct handler, schedule, and IAM
- [ ] **Secret**: Create `life-platform/<source>` in Secrets Manager (use platform CMK: `alias/life-platform-dynamodb`). Add row to INFRASTRUCTURE.md Secrets table.
- [ ] **Deploy CDK**: `source cdk/.venv/bin/activate && npx cdk deploy LifePlatformIngestion`
- [ ] **Deploy Lambda code**: `bash deploy/deploy_and_verify.sh <function-name> lambdas/<source>_lambda.py`

### Platform Wiring (the steps most often missed)
- [ ] **SOURCES list**: Add source name to `SOURCES` list in `mcp/config.py`
- [ ] **Freshness checker**: Add source to monitored list in `lambdas/freshness_checker_lambda.py`
- [ ] **Ingestion validator**: Add source schema to `_SCHEMAS` dict in `lambdas/ingestion_validator.py`. Update docstring count.
- [ ] **MCP tools**: Add `mcp/tools_<source>.py` with at least one tool. Register in `mcp/registry.py`. Run `python3 -m pytest tests/test_mcp_registry.py -v` before deploying MCP.
- [ ] **Cache warmer** (if new tools are expensive >1s): Add warm step to `mcp/warmer.py`
- [ ] **SLO-2**: Update monitored source count in `docs/SLOs.md`

### CI & Tests
- [ ] **CI Lambda map**: Update `ci/lambda_map.json` with new function name and handler
- [ ] **Registry test**: Verify `python3 -m pytest tests/test_mcp_registry.py -v` still passes (all R1-R7 green)

### Documentation (all in one pass — don't skip any)
- [ ] **SCHEMA.md**: Add DynamoDB key patterns and fields
- [ ] **ARCHITECTURE.md**: Add Lambda to ingest schedule table + update source count in overview
- [ ] **INFRASTRUCTURE.md**: Add Lambda to Lambdas section (correct category)
- [ ] **DECISIONS.md**: Add ADR if any non-obvious design decision was made
- [ ] **CHANGELOG.md**: Add version entry
- [ ] **sync_doc_metadata.py**: Run `python3 deploy/sync_doc_metadata.py --apply` to auto-update counters in all docs

### Final verification
- [ ] Manually invoke Lambda: `aws lambda invoke --function-name <name> --payload '{}' /tmp/test.json && cat /tmp/test.json`
- [ ] Check DynamoDB: `aws dynamodb get-item --table-name life-platform --key '{"pk":{"S":"USER#matthew#SOURCE#<source>"},"sk":{"S":"DATE#<yesterday>"}}'`
- [ ] Git commit + push: `git add -A && git commit -m "vX.X.X: add <source> ingestion" && git push`

---

## Adding a New MCP Tool — Complete Checklist

> **Use this checklist every time you add a tool.** Done right, a new tool takes <30 minutes.
> Done wrong, it creates import errors and registry drift caught in the next review.

### Code
- [ ] **Implement function**: Add `tool_<name>(params)` function to the appropriate `mcp/tools_<domain>.py` module. Function MUST be defined **before** the TOOLS dict (NameError otherwise — see ADR-020).
- [ ] **Register in TOOLS dict**: Add entry to `mcp/registry.py` with `fn`, `schema.name`, `schema.description`, `schema.inputSchema`. Tool name in schema must match the TOOLS dict key exactly.
- [ ] **Warm if expensive**: If the tool takes >1s (DDB range scan, multi-source), add a warm step to `mcp/warmer.py` calling the dispatcher, not the raw function.

### Validation (before any deploy)
- [ ] **Registry linter**: `python3 -m pytest tests/test_mcp_registry.py -v` — all R1-R7 must pass
  - R1: import resolves to a real file
  - R2: `fn` reference points to a real function
  - R3: schema has name + description + inputSchema
  - R4: no duplicate tool names
  - R5: tool count within expected range (update `EXPECTED_MIN_TOOLS`/`EXPECTED_MAX_TOOLS` if intentional)
- [ ] **Update R5 range**: If adding tools intentionally, update `EXPECTED_MIN_TOOLS`/`EXPECTED_MAX_TOOLS` in `tests/test_mcp_registry.py`

### Deploy
- [ ] `bash deploy/deploy_and_verify.sh life-platform-mcp lambdas/mcp_server.py`

### Documentation
- [ ] **MCP_TOOL_CATALOG.md**: Add new tool row
- [ ] **ARCHITECTURE.md**: Update tool count in serve layer description (auto-updated by sync_doc_metadata.py)
- [ ] **CHANGELOG.md**: Add version entry
- [ ] `python3 deploy/sync_doc_metadata.py --apply`
- [ ] `git add -A && git commit -m "vX.X.X: add <tool_name> MCP tool" && git push`

---

## Session Close Checklist

At the end of every working session — in this order:

```bash
# Step 1: Sync all doc metadata (auto-discovers tool + Lambda counts from source)
python3 deploy/sync_doc_metadata.py          # dry run — review changes
python3 deploy/sync_doc_metadata.py --apply  # apply if changes look right

# Step 2: Commit and push
git add -A && git commit -m "vX.XX.X: <what changed>" && git push
```

**If CDK was deployed this session** — also run integration tests:
```bash
python3 -m pytest tests/test_integration_aws.py -v --tb=short
# I1-I11: handler names, Layer version, invocability, DDB, secrets, EB rules,
#         alarms, S3, DLQ, MCP, data-reconciliation freshness
```

**Integration tests are MANUAL-ONLY** (R12, ADR-028 note): not wired into GitHub Actions.
Require live AWS credentials. Run after CDK deploys, or when investigating an incident.
Do NOT add to CI/CD without setting up a dedicated OIDC role with CloudWatch Logs read access.

**That's it for standard sessions.** The sync script auto-discovers tool and Lambda counts from source files — no manual PLATFORM_FACTS updates needed for those.

For sessions where more than counters changed, use the trigger matrix below.

---

## Doc Update Trigger Matrix

Consult this when deciding which docs need human edits beyond what sync_doc_metadata.py handles.

| What changed | Docs to update manually |
|---|---|
| **New Lambda added** | ARCHITECTURE (ingest/email/compute/operational table), INFRASTRUCTURE (Lambda list), lambda_map.json, RUNBOOK (schedule table if scheduled), CHANGELOG |
| **Lambda deleted** | Same as above — remove the row |
| **Schedule time changed** | ARCHITECTURE (EventBridge table), RUNBOOK (schedule table) — times must match |
| **New secret added** | ARCHITECTURE (Secrets table + cost profile), INFRASTRUCTURE (Secrets table), DECISIONS ADR-014, COST_TRACKER — then update PLATFORM_FACTS in sync_doc_metadata.py |
| **Secret deleted** | Same docs — then update PLATFORM_FACTS |
| **New MCP tools added** | MCP_TOOL_CATALOG (new rows), ARCHITECTURE (serve layer description) — then update PLATFORM_FACTS |
| **MCP tools removed** | MCP_TOOL_CATALOG (remove rows) — then update PLATFORM_FACTS |
| **New CDK stack** | ARCHITECTURE (CDK section), INFRASTRUCTURE, cdk/app.py |
| **DynamoDB schema change** | SCHEMA.md, DATA_DICTIONARY.md |
| **New data source** | ARCHITECTURE (ingest layer), DATA_DICTIONARY (SOT table), SCHEMA.md, RUNBOOK (schedule table), FEATURES.md |
| **IAM role changed** | ARCHITECTURE (IAM section), RUNBOOK (IAM table), role_policies.py |
| **New IC feature** | ARCHITECTURE (IC features list), INTELLIGENCE_LAYER.md, CHANGELOG |
| **Cost change** | COST_TRACKER (breakdown + decisions log) — then update PLATFORM_FACTS |
| **New ADR** | DECISIONS.md (ADR Index + full entry) |
| **Incident** | INCIDENT_LOG.md |
| **New CI rule / test** | ARCHITECTURE (CI section if applicable), CHANGELOG |
| **Any of the above** | CHANGELOG always |

**Key principle:** `sync_doc_metadata.py` owns the numbers. Humans own the prose. Never manually update tool counts, Lambda counts, version headers, or date stamps — just update PLATFORM_FACTS in the script and run it.

---

**GitHub repo:** `git@github.com:averagejoematt/life-platform.git` (SSH, private)
**Never commit:** `datadrops/`, `lambdas/dashboard/data.json`, `lambdas/dashboard/clinical.json`, `*.env`, `.config.json`
