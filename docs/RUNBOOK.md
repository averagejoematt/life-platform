# Life Platform — Runbook

Last updated: 2026-06-21 (v8.6.0 — 135 MCP tools, 41-module package, 81 Lambdas, 20 data sources)

**Ground truth at last verification:**
- Lambda functions deployed: 73 (5 power-tuning Lambdas deleted in V2 P4)
- Shared layer `life-platform-shared-utils`: v76 (verify: `aws lambda list-layer-versions --layer-name life-platform-shared-utils --max-items 1`)
- Account concurrency limit: **10** (AWS Support case 177921309700709 filed 2026-05-19; awaiting raise to 100; CDK reservations pre-staged but commented out — see `docs/RESERVED_CONCURRENCY.md`)
- Active alarms in ALARM (2026-05-19): `life-platform-garmin-data-ingestion-errors`, `life-platform-weather-data-ingestion-errors`, `life-platform-compute-pipeline-stale`, `life-platform-dlq-depth-warning`, `life-platform-ingestion-dlq-messages`, `ai-tokens-daily-brief-daily`, `slo-source-freshness` — Garmin-related expected to clear within 24h post-OAuth refresh
- DLQ: `life-platform-ingestion-dlq`, retention 14d, currently 66 messages (normally near-empty — investigate via `dlq-consumer` Lambda logs)
- SES configuration set: `life-platform-emails` — wired to 4 email Lambdas, CloudWatch event destination tracks open/click/bounce/complaint/delivery
- CloudTrail: `life-platform-trail` now has data events on `s3://matthew-life-platform/raw/*` and `uploads/*`

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

**S3 deploy-artifact CMK pitfall (V2 P5 incident, 2026-05-17):** Scheduling the S3 CMK for deletion broke the deploy artifact upload step because 19 historical objects in `deploys/` were encrypted with that key and CDK couldn't read them during the next deploy. **Procedure for retiring an S3-targeting CMK:** (1) inventory objects encrypted with that key, (2) re-encrypt to AES256 (`aws s3 cp s3://bucket/key s3://bucket/key --metadata-directive REPLACE --sse AES256`) before scheduling deletion, (3) wait for stable deploys, (4) then schedule deletion. The S3 CMK is currently re-scheduled for deletion 2026-06-16.

---

## Common Mistakes (see also `docs/QUICKSTART.md`)

| Mistake | Result | Fix |
|---------|--------|-----|
| Edit shared layer module, skip `build_layer.sh` | Dependent Lambdas run stale code silently | Run `bash deploy/build_layer.sh` first |
| `deploy_lambda.sh life-platform-mcp` | MCP breaks — strips `mcp/` directory (ADR-031) | Use full zip build (see QUICKSTART) |
| `aws s3 sync --delete s3://matthew-life-platform/` | Deletes 35K+ objects (ADR-032) | Always use `sync_site_to_s3.sh` |
| Change Lambda env var in AWS Console | Next `cdk deploy` reverts it silently | Edit CDK stack code instead |
| Add Lambda to CDK, forget `role_policies.py` | `AccessDenied` on first run | Add IAM policy to role_policies.py |
| Use DST-aware cron in EventBridge | Schedule drifts 1 hour twice yearly | All crons must be fixed UTC |
| Change pipeline schedule ordering | Compute reads yesterday's data; brief reads stale compute | Ingestion → Compute → Brief ordering is strict |
| Secret scheduled for deletion goes unnoticed | Data pipeline silently breaks when 7-day recovery window expires | `pipeline-health-check` Lambda probes all secrets daily. Check status page. |

---

## Shared Lambda Layer

**Current version:** v76 (2026-06-08). Rebuild with `bash deploy/build_layer.sh`. The layer is consumed by the majority of Lambdas (verify count via `aws lambda list-functions --query 'Functions[?Layers[?contains(Arn, \`life-platform-shared-utils\`)]].FunctionName' --output text | wc -w`).

Source of truth for the expected version is `cdk/stacks/constants.py:SHARED_LAYER_VERSION`. A CI guard (`tests/test_layer_version_consistency.py`) blocks PRs that mismatch.

Modules included (33+ as of v76): `ai_calls.py` (+ its split modules `ai_context.py`/`ai_summaries.py`), `auth_breaker.py`, `bedrock_client.py`, `budget_guard.py`, `board_loader.py`, `character_engine.py`, `compute_metadata.py`, `digest_utils.py`, `html_builder.py`, `http_retry.py`, `ai_output_validator.py`, `ingestion_framework.py`, `ingestion_validator.py`, `insight_writer.py`, `intelligence_common.py`, `item_size_guard.py`, `numeric.py`, `output_writers.py`, `phase_filter.py`, `platform_logger.py`, `rate_limiter.py`, `request_validator.py`, `retry_utils.py`, `scoring_engine.py`, `secret_cache.py`, `site_writer.py`, plus shared helpers. (`email_framework.py` was removed in V2 — replaced inline.) See `ci/lambda_map.json` `skip_deploy` list for layer-resident modules that should NOT be deployed as standalone Lambda code.

**After rebuilding:** Update all dependent Lambdas to the new layer version via CDK deploy (`cd cdk && npx cdk deploy --all`). The version bump in `cdk/stacks/constants.py` propagates to every Lambda's `Layers=` arg.

**Verify a Lambda is on the current layer:**
```bash
aws lambda get-function-configuration --function-name <name> \
  --query 'Layers[0].Arn' --output text
# Expect: ...life-platform-shared-utils:51
```

---

## Secret Caching (COST-OPT-1)

Lambdas cache Secrets Manager reads for 15 minutes via `secret_cache.py` in the shared layer. This reduces Secrets Manager API calls by ~90% across 9 Lambdas. The cache is in-memory (per-Lambda instance), so a cold start always fetches fresh secrets.

---

## Gap-Fill Behavior

**Whoop:** Gap-fill checks for `recovery_score` presence. If a record exists but `recovery_score` is missing, the Lambda re-fetches from the Whoop API (recovery data is often delayed ~2 hours after sleep ends).

**Garmin:** Gap-fill checks for `steps` presence. If a record exists but `steps` is missing, the Lambda re-fetches from the Garmin API.

All ingestion Lambdas include today in gap-fill checks (`range(0, N)`, not `range(1, N)`).

---

## OAuth Token Refresh Behavior

Each OAuth-based ingestion Lambda refreshes its own tokens and writes them back to Secrets Manager. No dedicated rotation Lambda exists for OAuth tokens (only for the MCP API key via `key-rotator`).

| Lambda | Auth Type | When It Refreshes | Writes to Secrets Manager | Concurrent Invocation Risk |
|--------|-----------|-------------------|--------------------------|---------------------------|
| whoop | OAuth refresh_token | Every invocation (unconditional) | Yes | High — no concurrency limit yet |
| garmin | garth OAuth session | Every invocation (garth library) | Yes | High |
| withings | OAuth refresh_token | On 401 response | Yes | Medium |
| strava | OAuth expires_at | On expiration check (5-min buffer) | Yes | Medium |
| eightsleep | Password grant | On 401 response | Yes | Low |

**Note:** A concurrent invocation (manual invoke + cron overlap) could race on the token write. `ReservedConcurrentExecutions=1` is ready in CDK but commented out — requires account concurrency limit increase from 10 to 50+ (pending AWS Support request).

---

## Meal Grouping — Backfill & Regroup (ADR-090)

The derived `macrofactor_meals` projection is built by the deterministic `meal_grouper`
(shared layer). Raw `macrofactor` is never mutated.

**Backfill history** (local script, runs with your admin creds — reads raw directly,
bypassing the phase filter so it sees full cross-phase history):
```bash
# DRY-RUN by default — prints grouped days, writes nothing. Eyeball first.
S3_BUCKET=matthew-life-platform USER_ID=matthew python3 deploy/backfill_meals.py --limit 14   # sample
S3_BUCKET=matthew-life-platform USER_ID=matthew python3 deploy/backfill_meals.py               # full dry-run
S3_BUCKET=matthew-life-platform USER_ID=matthew python3 deploy/backfill_meals.py --apply        # WRITE
# Resumable: --apply skips already-projected days unless --force. Conservation is checked
# per day; the job HALTS on any day that fails to reconcile to the cent (no partial write).
```

**Regroup a single day** (via the MCP tool — re-runs the grouper on raw + upserts):
`manage_meals regroup_day {date: YYYY-MM-DD}` (add `dry_run:true` to preview). Pruning of
stale ordinals uses the MCP role's **partition-scoped** `DeleteItem` (LeadingKeys =
`macrofactor_meals` only — see ADR-090).

**Layer dependency:** the grouper, seed templates, projection writer, and
`food_vocabulary.json` ship in the shared layer. Changing any of them = rebuild the layer
(`bash deploy/build_layer.sh`), bump `SHARED_LAYER_VERSION` in `cdk/stacks/constants.py`,
`cdk deploy LifePlatformCore`, **then** `cdk deploy LifePlatformMcp` (the MCP lambda must
re-attach the new layer — a code-only push leaves it on the old one; the tell is `cdk diff`
showing no Layers change). Verify: `aws lambda get-function-configuration
--function-name life-platform-mcp --query 'Layers[].Arn'` ends in the new version, and
`manage_meals list_templates` returns 10 templates (not an import error).

**Format-drift:** if `get_freshness_status.macrofactor_format_drift.drifted` is true (or the
`MacroFactorFormatDrift` alarm fires), the MacroFactor diary export reverted to daily-summary
(empty `food_log`) and the grouper is starved — re-export the diary format.

---

## Pipeline Ordering Constraint (ADR-052)

**All EventBridge cron expressions are fixed UTC.** The PT times below are for reference only — they shift by 1 hour when DST begins (March) and ends (November). The UTC times never change.

The pipeline has strict ordering. Changing schedules without maintaining this sequence produces stale data:

```
06:45–09:00 AM PT   INGESTION              API pulls from Whoop, Withings, Strava, etc.
09:05 AM PT         ANOMALY                Runs on freshly ingested data
16:30 UTC           character-sheet-compute (09:30 PDT)
16:35 UTC           adaptive-mode-compute  (09:35 PDT)
16:40 UTC           daily-metrics-compute  (09:40 PDT)
16:45 UTC           daily-insight-compute  (09:45 PDT)
17:00 UTC           daily-brief            (10:00 PDT — reads computed results → email → public_stats.json)
11:30 AM PT         OG IMAGES              Reads public_stats.json → generates share images
```

**Verify the schedule chain (2026-05-19 verified):**
```bash
aws events list-rules --query 'Rules[?Schedule] && Rules[].{Name:Name,Schedule:ScheduleExpression}' --output json \
  | python3 -c 'import json,sys;
data=json.load(sys.stdin);
keep=["character-sheet-compute","adaptive-mode-compute","daily-metrics-compute","daily-insight-compute","daily-brief-schedule"];
[print(f"{r[\"Name\"]:35s} {r[\"Schedule\"]}") for r in data if r["Name"] in keep]'
```

Expected:
```
character-sheet-compute             cron(30 16 * * ? *)
adaptive-mode-compute               cron(35 16 * * ? *)
daily-metrics-compute               cron(40 16 * * ? *)
daily-insight-compute               cron(45 16 * * ? *)
daily-brief-schedule                cron(0 17 * * ? *)
```

---

## Daily Operations

### Scheduled ingestion times (Pacific Time)

**⚠️ All EventBridge crons use fixed UTC. Times below reflect PDT (UTC-7, from March 8 2026). During PST (UTC-8, Nov–Mar) all times shift 1 hour earlier.**
| Source | Schedule | Lambda |
|--------|----------|--------|
| Whoop | 07:00 AM | whoop-data-ingestion |
| Garmin | 4x daily (cron 0 0,6,14,22 UTC) | garmin-data-ingestion |
| Notion Journal | 07:00 AM | notion-journal-ingestion |
| Withings | 07:15 AM | withings-data-ingestion |
| Habitify | 07:15 AM | habitify-data-ingestion |
| Strava | 07:30 AM | strava-data-ingestion |
| Journal Enrichment | 07:30 AM | journal-enrichment |
| Todoist | 2x daily | todoist-data-ingestion |
| Eight Sleep | 08:00 AM | eightsleep-data-ingestion |
| Activity Enrichment | 08:30 AM | activity-enrichment |
| MacroFactor | 09:00 AM | macrofactor-data-ingestion (EventBridge + S3 trigger) |
| MCP Cache Warmer | 10:00 AM | life-platform-mcp (EventBridge payload) |
| Whoop Recovery Refresh | 10:30 AM | whoop-data-ingestion (date_override: today) |
| Character Sheet Compute | 09:30 AM (16:30 UTC) | character-sheet-compute — ADR-052 ordering |
| Adaptive Mode Compute | 09:35 AM (16:35 UTC) | adaptive-mode-compute — ADR-052 ordering |
| Daily Metrics Compute | 09:40 AM (16:40 UTC) | daily-metrics-compute (day grade, readiness, streaks, TSB, HRV, weight → `computed_metrics` partition) |
| Daily Insight Compute | 09:45 AM (16:45 UTC) | daily-insight-compute (IC-8: 7-day habit×outcome correlations, leading indicators, platform_memory pull, structured JSON for Daily Brief AI calls) |
| Freshness Check | 10:45 AM | life-platform-freshness-checker |
| Daily Brief | 10:00 AM (17:00 UTC) | daily-brief (v2.62, 18 sections, 4 AI calls; reads char_sheet+adaptive+metrics+insight; async-invokes `coach-quality-gate` per coach generation) |
| **DST note** | — | All crons fixed UTC. Times above are PDT (UTC-7). DST is now active (PDT = UTC-7). |
| Anomaly Detector | 09:05 AM | anomaly-detector |
| Nutrition Review | 09:00 AM (Saturday only) | nutrition-review (v1.1, Sonnet, 3-expert panel) |
| Weekly Digest | 08:00 AM (Sunday only) | weekly-digest (v4.3) |
| Monthly Digest | 08:00 AM (1st Monday only) | monthly-digest (v1.1) |
| Wednesday Chronicle (compute + email) | Wed 08:00 AM (15:00 UTC) + Wed 08:10 AM (15:10 UTC) | wednesday-chronicle + chronicle-email-sender (V2 P3: re-enabled 2026-05-17) |
| Monday Compass | 08:00 AM (Monday only) | monday-compass (v1.0, Sonnet, weekly planning email — tasks by pillar, Board Pro Tips, Keystone) |
| The Weekly Plate | 07:00 PM (Friday only) | weekly-plate (v1.0, Sonnet, food magazine email, ~63s) |
| Dashboard Refresh | 02:00 PM | dashboard-refresh (lightweight, no AI — updates weight/glucose/zone2/TSB/buddy) |
| Dashboard Refresh | 06:00 PM | dashboard-refresh (same as above, second daily run) |
| Weather | 2x daily | weather-data-ingestion |
| Dropbox Poll | Every 30 min | dropbox-poll |

**MacroFactor** uses an automated Dropbox pipeline: phone export → Dropbox `/life-platform/` → `dropbox-poll` Lambda (every 30 min) → S3 → `macrofactor-data-ingestion`. Auto-detects nutrition vs workout CSVs. Manual S3 upload (`s3://matthew-life-platform/imports/macrofactor/`) still works as fallback.

**Apple Health** primary path is the Health Auto Export webhook (hourly push from iOS): Stelo/Apple Watch → HealthKit → Health Auto Export app → API Gateway → `health-auto-export-webhook`. Manual S3 XML upload (`s3://matthew-life-platform/imports/apple_health/`) still works for backfills.

**⚠️ Health Auto Export gotcha:** The app must be configured for hourly (not "since last run") sync to reliably include all metric types. With infrequent syncs, payload size grows and the app may silently drop metrics like Dietary Water and Dietary Caffeine, sending only activity data. If water/caffeine stop appearing in webhook logs, check the app's sync interval.

---

## Logs-Insights Triage Queries (2026-06-09)

Paste these into **CloudWatch → Logs Insights** (pick the matching log groups) for fast incident triage instead of re-typing filters. The `life-platform-ops` dashboard is the at-a-glance view; these are the drill-down.

**Ingestion errors** — log groups: every `/aws/lambda/*-ingestion`:
```
fields @timestamp, @logStream, @message
| filter @message like /(?i)(error|exception|failed|traceback)/
| sort @timestamp desc
| limit 100
```
**Compute-pipeline errors** — log groups: `character-sheet-compute`, `adaptive-mode-compute`, `daily-metrics-compute`, `daily-insight-compute`, `daily-brief`: same filter as above.

**AI / Bedrock failures** — log groups: the compute set above:
```
fields @timestamp, @logStream, @message
| filter @message like /(?i)(bedrock|anthropic|budgetexceeded|throttl|AI call failed|inference)/
| sort @timestamp desc
| limit 100
```

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
  --cli-binary-format raw-in-base64-out \
  --region us-west-2 \
  /tmp/response.json && cat /tmp/response.json
```

The `--cli-binary-format raw-in-base64-out` flag is required on AWS CLI v2. Without it, the CLI base64-encodes the literal `{}` string and the Lambda receives invalid JSON.

## Daily-Brief Log Inspection (most common ops task)

```bash
# Tail the most recent daily-brief run (live stream)
aws logs tail /aws/lambda/daily-brief --since 2h --follow

# Find the most recent invocation and read the full log
aws logs describe-log-streams --log-group-name /aws/lambda/daily-brief \
  --order-by LastEventTime --descending --max-items 1 \
  --query 'logStreams[0].logStreamName' --output text \
  | xargs -I {} aws logs get-log-events --log-group-name /aws/lambda/daily-brief \
    --log-stream-name {} --start-from-head --output text --query 'events[].message'
```

Daily-brief log group retention is 30 days (default added to `lambda_helpers.py` in V2 P1 — applies to new groups; existing groups patched individually).

## Rolling Back a Failed Lambda

Two paths depending on how it was deployed:

**A) Deployed via `deploy_lambda.sh` (single-Lambda code update):**
```bash
# List the last 5 Lambda versions (AWS retains numbered immutable versions)
aws lambda list-versions-by-function --function-name <name> \
  --query 'Versions[-5:].[Version,LastModified,Description]' --output table

# Re-point $LATEST to a known-good version by re-uploading that code:
# Easiest: redeploy from a known-good git commit
git checkout <good-sha> -- lambdas/<name>_lambda.py
bash deploy/deploy_lambda.sh <name>
git checkout HEAD -- lambdas/<name>_lambda.py   # restore working tree
```

**B) Deployed via CDK (`cd cdk && npx cdk deploy`):**
```bash
git revert <bad-commit-sha>
cd cdk && npx cdk diff && npx cdk deploy --all
```

Always smoke-test after rollback (`aws lambda invoke ... /tmp/x.json && cat /tmp/x.json | grep -i error`).

## Cache Warmer

14 tools are pre-computed nightly at 9:00 AM PT via EventBridge → MCP Lambda. Tools with cached results return in <100ms. Custom date ranges bypass cache and compute fresh.

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
Expected: 14 items.

---

## Secrets Management

All secrets are stored in AWS Secrets Manager under `life-platform/` prefix. See `docs/SECRETS_MAP.md` for the authoritative inventory; `docs/SECRETS_ROTATION.md` for rotation procedures.

**Inventory snapshot (2026-05-19):** 12 active secrets + 3 in deletion window. Two are tracked for deletion 2026-05-24 (`life-platform/notion`, `life-platform/dropbox`) — both have been replaced by fields inside `life-platform/ingestion-keys`. `life-platform/anthropic-api-key` (orphan, never adopted by any Lambda) scheduled for deletion 2026-05-23.

| Secret | Function(s) | Notes |
|--------|-------------|-------|
| `life-platform/whoop` | whoop-data-ingestion | OAuth2; auto-refresh on each run |
| `life-platform/withings` | withings-data-ingestion | OAuth2; auto-refresh on 401 |
| `life-platform/strava` | strava-data-ingestion | OAuth2; auto-refresh on expires_at |
| `life-platform/garmin` | garmin-data-ingestion | garth OAuth1+OAuth2; refreshed via Playwright browser flow |
| `life-platform/eightsleep` + `/eightsleep-client` | eightsleep-data-ingestion | User creds + client ID |
| `life-platform/ai-keys` | 24+ Lambdas (daily-brief, weekly digests, coaches, etc.) | Anthropic API key |
| `life-platform/site-api-ai-key` | life-platform-site-api, life-platform-site-api-ai | Isolated Anthropic key for public site |
| `life-platform/mcp-api-key` | life-platform-mcp, canary, qa-smoke, key-rotator | HMAC bearer; 90-day auto-rotation |
| `life-platform/todoist` | life-platform-mcp (write tools) | Dedicated; bundle still used by ingestion |
| `life-platform/habitify` | habitify-data-ingestion | API key |
| `life-platform/ingestion-keys` | todoist-data-ingestion, notion-journal-ingestion, dropbox-poll, health-auto-export-webhook | Bundle: Notion + Dropbox + Todoist + Habitify + HAE webhook key |
| `life-platform/notion` (deletion window) | none — migrated to bundle | Pending delete 2026-05-24 |
| `life-platform/dropbox` (deletion window) | none — migrated to bundle | Pending delete 2026-05-24 |
| `life-platform/anthropic-api-key` (deletion window) | none (orphan) | Pending delete 2026-05-23 |

To view a secret value (for debugging):
```bash
aws secretsmanager get-secret-value --secret-id life-platform/whoop --query SecretString --output text
```

To list all secrets including those scheduled for deletion:
```bash
aws secretsmanager list-secrets --include-planned-deletion \
  --query 'SecretList[].{Name:Name,DeletedDate:DeletedDate}' --output table
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

### Garmin: 429 Too Many Requests / OAuth1 expired (auth_breaker tripped)

Garmin OAuth1 has a ~30-day lifetime; after the gap or rate-limit storm, the Lambda trips `auth_breaker` and stops attempting calls until cleared.

**Step 1 — Re-auth via browser flow (Playwright):**
```bash
cd ~/Documents/Claude/life-platform
python3 setup/setup_garmin_browser_auth.py
# Walks through Garmin login + MFA in headed Chromium
# Writes fresh garth tokens to life-platform/garmin
```

**Step 2 — Clear the auth_breaker marker so the Lambda will retry:**
```python
# Run via aws-vault or python3 with appropriate AWS creds
python3 -c "
import boto3
from lambdas.auth_breaker import clear_failure
import logging
logging.basicConfig(level=logging.INFO)
ddb = boto3.resource('dynamodb', region_name='us-west-2')
table = ddb.Table('life-platform')
clear_failure(table, 'garmin', 'matthew', logging.getLogger())
"
```

Or directly via CLI (PK pattern: `AUTH_BREAKER#matthew#garmin`, SK `STATE`):
```bash
aws dynamodb delete-item --table-name life-platform \
  --key '{"pk":{"S":"AUTH_BREAKER#matthew#garmin"},"sk":{"S":"STATE"}}'
```

**Step 3 — Smoke test:**
```bash
aws lambda invoke --function-name garmin-data-ingestion --payload '{}' \
  --cli-binary-format raw-in-base64-out /tmp/garmin.json && cat /tmp/garmin.json
```

Then watch the alarm `life-platform-garmin-data-ingestion-errors` return to OK within 24h.

### Eight Sleep: JWT auth failure
Eight Sleep uses username/password → JWT (no OAuth). If the JWT refresh fails, the function will write to the DLQ. Check logs for the specific error. Resolution may require re-entering credentials in Secrets Manager if the account password changed.

### MacroFactor: Function not triggered
Ensure your export CSV is dropped into the correct S3 path: `s3://matthew-life-platform/uploads/macrofactor/`. The filename does not matter but the prefix does. The primary path is Dropbox poll → S3 → `macrofactor-data-ingestion` (S3 trigger).

### Apple Health: Large export timeout
Apple Health exports can be large. The function has 1024 MB memory and a 5-minute timeout. If it times out on a very large export, consider exporting a shorter date range.

### Compute Lambda failed (character-sheet / adaptive-mode / daily-metrics / daily-insight)

Failure of any compute Lambda upstream of daily-brief degrades the brief (sections fall back to legacy paths but final brief still ships). Diagnose:

```bash
# 1. Find which compute Lambda failed
for fn in character-sheet-compute adaptive-mode-compute daily-metrics-compute daily-insight-compute; do
  echo "== $fn =="
  aws logs tail /aws/lambda/$fn --since 4h | tail -20
done

# 2. Check error rate from CloudWatch
aws cloudwatch get-metric-statistics --namespace AWS/Lambda \
  --metric-name Errors --dimensions Name=FunctionName,Value=character-sheet-compute \
  --start-time $(date -u -v-1d +%Y-%m-%dT00:00:00Z) \
  --end-time $(date -u +%Y-%m-%dT23:59:59Z) \
  --period 86400 --statistics Sum

# 3. Manually re-invoke (after fixing the root cause)
aws lambda invoke --function-name <name> --payload '{}' \
  --cli-binary-format raw-in-base64-out /tmp/x.json && cat /tmp/x.json
```

---

## DynamoDB TTL Policy (R17-17)

TTL is enabled on the `life-platform` table (attribute: `ttl`, Unix epoch). The table is imported by CDK — TTL cannot be enabled via CDK, only via CLI (run once).

**Partitions that write `ttl`:**
| Partition | TTL | Purpose |
|-----------|-----|---------|
| `CACHE#matthew` | 26 hours | MCP cache warmer pre-computed results |
| `USER#matthew#SOURCE#anomalies` | 90 days | Anomaly detector records (investigative data only) |

**Enable TTL (run once, idempotent):**
```bash
aws dynamodb update-time-to-live \
  --table-name life-platform \
  --time-to-live-specification "Enabled=true,AttributeName=ttl" \
  --region us-west-2
```

**To add TTL to other partitions:** update the Lambda that writes to that partition to include a `"ttl": int(timestamp)` field. DynamoDB will auto-expire items within ~48h of the TTL passing.

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

## AWS CLI Setup (OE-05)

Disable the pager to prevent `aws` commands from blocking in non-interactive shells (CI, scripts):

```bash
aws configure set cli_pager ""
```

This sets `cli_pager=` in `~/.aws/config`. Run once per machine/CI environment. Without it, commands like `aws logs tail` open `less` and block scripts.

---

## Setting CloudWatch Log Retention

Default of `RetentionDays.ONE_MONTH` (30d) is now applied by `cdk/stacks/lambda_helpers.py` for any new Lambda log group it creates (V2 P1). Two pre-existing untreated groups were patched manually.

AWS has no account-level log-retention default API (verified V2). To find any remaining log groups with no retention:

```bash
aws logs describe-log-groups \
  --query 'logGroups[?retentionInDays==`null`].logGroupName' --output text
```

To patch a one-off group manually (only if a new group appears without retention):
```bash
aws logs put-retention-policy \
  --log-group-name /aws/lambda/<name> \
  --retention-in-days 30 \
  --region us-west-2
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

Monthly ceiling: **$75 all-in, enforced** (ADR-063; cost-governor degrades AI by tier). See `docs/COST_TRACKER.md` for the full breakdown.

Real run-rate (CE, 2026-06-08 sweep): Mar $20.04 → Apr $35.01 → May $48.19 (peak, Bedrock $14.29) → steady-state **~$25-40/mo**. Bedrock is the swing factor (priced from CloudWatch token metrics); WAF deleted (~−$8/mo).

Check current MTD AWS spend:
```bash
aws ce get-cost-and-usage \
  --time-period Start=$(date -u +%Y-%m-01),End=$(date -u +%Y-%m-%d) \
  --granularity MONTHLY \
  --metrics UnblendedCost \
  --region us-east-1
```

Break down by service:
```bash
aws ce get-cost-and-usage \
  --time-period Start=$(date -u +%Y-%m-01),End=$(date -u +%Y-%m-%d) \
  --granularity MONTHLY \
  --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  --region us-east-1 \
  --query 'ResultsByTime[0].Groups[].{Service:Keys[0],Cost:Metrics.UnblendedCost.Amount}' --output table
```

## MCP Tool Usage Telemetry

MCP tool invocations emit to CloudWatch namespace **`LifePlatform/MCP`** with metrics `ToolInvocations`, `ToolErrors`, `ToolDuration`, `AuthFailures` (dimensioned by `ToolName`).

```bash
# List which tools are emitting
aws cloudwatch list-metrics --namespace LifePlatform/MCP \
  --metric-name ToolInvocations \
  --query 'Metrics[*].Dimensions[?Name==`ToolName`].Value' --output text

# Top tools by invocation count over the last 7 days
for tool in get_daily_snapshot get_health get_habits get_journal_entries; do
  count=$(aws cloudwatch get-metric-statistics --namespace LifePlatform/MCP \
    --metric-name ToolInvocations --dimensions Name=ToolName,Value=$tool \
    --start-time $(date -u -v-7d +%Y-%m-%dT00:00:00Z) \
    --end-time $(date -u +%Y-%m-%dT23:59:59Z) \
    --period 604800 --statistics Sum --query 'Datapoints[0].Sum' --output text)
  echo "$tool: $count"
done
```

V2 P4.1 finding: only ~11 of the 133 MCP tools were invoked in the last 30 days. Bulk pruning planned post-V2.

## SES Email Pipeline

The `life-platform-emails` SES configuration set tracks bounce/click/complaint/delivery/open events to CloudWatch (dimension `SesEventType`). Verify:

```bash
aws ses describe-configuration-set --configuration-set-name life-platform-emails \
  --configuration-set-attribute-names eventDestinations
```

Four email Lambdas explicitly send through this config set: `daily-brief`, `weekly-digest`, `monthly-digest`, `partner-weekly-email`. Other email Lambdas (chronicle, weekly-plate, monday-compass, nutrition-review, evening-nudge) currently send without the config set — V2 P3 follow-up tracks wiring them.

**SES IAM regression watch-out (V2 P2):** SES requires `ses:SendEmail` on BOTH the identity ARN AND the configuration-set ARN. A 2026-05-17 regression dropped the config-set permission and silently failed deliveries with `AccessDenied`. Fixed via `role_policies.py` — both ARNs in the `Resource` list.

### Anthropic API Cost Monitoring (ADR-049)

**Prompt caching metrics** — verify caching is working:
```bash
# Cache hit tokens (should be >> cache write tokens after expert analyzer runs)
aws cloudwatch get-metric-statistics --namespace "LifePlatform/AI" \
  --metric-name "AnthropicCacheReadTokens" \
  --dimensions Name=LambdaFunction,Value=ai-expert-analyzer \
  --start-time "$(date -u -v-1d +%Y-%m-%dT00:00:00Z)" \
  --end-time "$(date -u +%Y-%m-%dT23:59:59Z)" \
  --period 86400 --statistics Sum --region us-west-2
```

**Model assignments** — which Lambdas use Sonnet vs Haiku:

| Lambda | Model | Reason |
|--------|-------|--------|
| daily-brief (4 calls) | Sonnet | Core daily coaching voice |
| wednesday-chronicle | Sonnet | Literary narrative |
| weekly-plate, nutrition-review | Sonnet | Long-form meal/nutrition analysis |
| monday-compass, weekly-digest | Sonnet | Weekly intelligence narrative |
| partner-email | Sonnet | Partner update |
| ai-expert-analyzer | **Haiku** | Templated observatory content |
| hypothesis-engine | **Haiku** | Structured JSON output |
| challenge-generator | **Haiku** | Structured JSON output |
| field-notes-generate | **Haiku** | Weekly lab notes |
| _run_analysis_pass (daily-brief) | **Haiku** | 200-token JSON extraction |
| Coach pipeline (5 Lambdas) | Haiku | Orchestration/extraction |
| journal-enrichment | Haiku | Per-entry enrichment |
| anomaly-detector | Haiku | Daily anomaly narrative |

**Rollback a model downgrade** (no code deploy needed):
```bash
# Example: revert expert analyzer to Sonnet
aws lambda update-function-configuration \
  --function-name ai-expert-analyzer \
  --environment "Variables={TABLE_NAME=life-platform,AI_SECRET_NAME=life-platform/ai-keys,AI_MODEL=claude-sonnet-4-6}" \
  --region us-west-2
```

**Anthropic credit balance** — check at [console.anthropic.com/settings/billing](https://console.anthropic.com/settings/billing). API key in Secrets Manager (`life-platform/ai-keys`) ends in `cQAA`. All Lambdas return `[AI_UNAVAILABLE]` when credits are exhausted — site API now filters this to show "Check back soon" instead of raw sentinel.

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

## Coach Intelligence Troubleshooting

### 1. Failed coach generation

If a coach output is missing from the daily brief:

1. Check CloudWatch logs for the orchestrator and state updater:
```bash
aws logs tail /aws/lambda/coach-narrative-orchestrator --since 4h --region us-west-2
aws logs tail /aws/lambda/coach-state-updater --since 4h --region us-west-2
```

2. The coach pipeline is: **computation engine** → **orchestrator** → **generation** (8 parallel coaches) → **state updater** (async). If the orchestrator fails, the affected coach falls back to legacy generation (no crash).

3. Manual re-run of the computation engine:
```bash
aws lambda invoke --function-name coach-computation-engine --payload '{}' --region us-west-2 /tmp/coach_compute.json && cat /tmp/coach_compute.json
```

### 2. Stale observatory coach cards

If the website shows old coach analysis on the observatory:

- `/api/coach_analysis` reads from `COACH#` `OUTPUT#` records in DynamoDB.
- Falls back to legacy `/api/ai_analysis` if no `COACH#` data exists.

Check the latest output for a coach:
```bash
aws dynamodb query --table-name life-platform \
  --key-condition-expression "pk = :pk" \
  --expression-attribute-values '{":pk":{"S":"COACH#sleep_coach"}}' \
  --region us-west-2 \
  --query 'Items[?begins_with(sk, `OUTPUT#`)].{sk:sk,created_at:created_at}' \
  --scan-index-forward false --limit 1
```

Fix: Re-run the daily brief pipeline or manually trigger coach generation.

### 3. Prediction evaluator not running

The prediction evaluator is scheduled daily at 9 AM PT (`cron(0 16 * * ? *)` UTC).

1. Check EventBridge rule status:
```bash
aws events describe-rule --name coach-prediction-evaluator-schedule --region us-west-2
```

2. Manual invocation:
```bash
aws lambda invoke --function-name coach-prediction-evaluator --payload '{}' --region us-west-2 /tmp/pred_eval.json && cat /tmp/pred_eval.json
```

### 4. Voice pattern repetition

If a coach sounds repetitive across multiple days:

1. Check the voice state record:
```bash
aws dynamodb get-item --table-name life-platform \
  --key '{"pk":{"S":"COACH#sleep_coach"},"sk":{"S":"VOICE#state"}}' \
  --region us-west-2
```

2. The `overused_patterns` field flags detected repetition. The `recent_openings` field stores recent opening lines.

3. Reset: update `VOICE#state` to clear `recent_openings` and `overused_patterns` arrays. The next generation will produce fresh phrasing.

### 5. Missing USER_ID env var

All coach Lambdas use `os.environ.get("USER_ID", "matthew")` with a safe default. If a Lambda crashes with `KeyError: USER_ID`, it is running old code — redeploy via CDK:
```bash
cd cdk && npx cdk deploy --all --require-approval never
```

### 6. Layer version mismatch

If coach Lambdas use stale shared layer modules:

1. Check layer version consistency:
```bash
python3 -m pytest tests/test_integration_aws.py::test_i2_lambda_layer_version_current -v
```

2. Rebuild and deploy:
```bash
bash deploy/build_layer.sh && cd cdk && npx cdk deploy --all --require-approval never
```

---

**GitHub repo:** `git@github.com:averagejoematt/life-platform.git` (SSH, private)
**Never commit:** `datadrops/`, `lambdas/dashboard/data.json`, `lambdas/dashboard/clinical.json`, `*.env`, `.config.json`

---

**Verified:** 2026-05-19 (V2 audit operational sweep)


## Restart Pipeline

To re-anchor the experiment to a new genesis date:

```bash
# 1. Verify the Withings reading exists for the target date in DDB.
# 2. Run the orchestrator:
python3 deploy/restart_pipeline.py --genesis YYYY-MM-DD --dry-run
# 3. Review the report, then commit:
python3 deploy/restart_pipeline.py --genesis YYYY-MM-DD --apply
```

The pipeline runs (in order, each idempotent):
1. `sync_constants_from_config.py` — regenerates `lambdas/constants.py`
2. `bash deploy/build_layer.sh` + layer version bump + `cdk deploy LifePlatformCore LifePlatformCompute LifePlatformEmail`
3. `restart_phase_tag.py --apply` — flips DDB phase tags relative to the new genesis
4. `restart_intelligence_wipe.py --apply` — tombstones any newly pre-genesis records
5. `restart_character_rebuild.py --apply` — recomputes character sheets from new genesis
6. `restart_chronicle_handler.py --apply` — archives any newly pre-genesis chronicle HTML
7. `restart_site_copy_sync.py --apply` — regenerates JS/JSON/HTML site copy + CloudFront invalidate

All steps preserve original data (interpretation B for DDB, archive-not-delete for S3).
Roll back by removing tombstone flags (DDB) or copying from `*/archive/pilot/` (S3).

See ADR-058 in `docs/DECISIONS.md` for the design rationale.

## Budget Guardrails (ADR-063)

The $75/month AWS budget is enforced by a two-component system:

- **`life-platform-cost-governor`** Lambda (hourly) — projects month-end spend, writes tier 0–3 to SSM `/life-platform/budget-tier`.
- **`lambdas/budget_guard.py`** (shared-layer module) — calling code uses `allow(feature)` to gate AI by tier.

**Tier behavior** (priority: protect daily brief longest):

| Tier | Projected | What pauses |
|---|---|---|
| 0 | <70% of $75 | nothing — all AI runs normally |
| 1 | 70–85% | coach narratives + ensemble + chronicle |
| 2 | 85–95% | + website AI (`/api/ask`, `/api/board_ask`) — returns "paused" JSON |
| 3 | ≥95% | hard cutoff — `bedrock_client.invoke()` raises `BudgetExceeded`; daily brief skips AI |

**Check current tier:**
```bash
aws ssm get-parameter --name /life-platform/budget-tier --region us-west-2 \
  --query Parameter.Value --output text
```

**Reset tier (testing, or after a cost-anomaly fix):**
```bash
aws ssm put-parameter --name /life-platform/budget-tier --value 0 \
  --type String --overwrite --region us-west-2
```

**Disable enforcement temporarily (emergency debugging):**
```bash
aws lambda update-function-configuration --function-name life-platform-cost-governor \
  --environment 'Variables={OBSERVE_MODE=true}' --region us-west-2
# Re-enable: --environment 'Variables={OBSERVE_MODE=false}'
```

**Email alerts:** budget `life-platform-monthly-75` notifies at 50/70/85/100% to `awsdev@mattsusername.com` via SNS.

## Remediation Agent (ADR-064/065)

Self-healing triage agent runs daily ~07:45 PT via `.github/workflows/remediation-agent.yml`. Auto-fixes the safe class via PR, opens PRs for the rest, emails what needs the operator. Replaces the raw `[LP digest]` noise.

**Mode kill-switch (SSM `/life-platform/remediation-mode`):**

| Value | Behavior |
|---|---|
| `off` | workflow no-ops immediately |
| `shadow` | diagnoses + opens PRs, never auto-merges (validation mode) |
| `auto` | `automerge.py` gate merges `auto-fix-safe` PRs that pass all guards (see ADR-065) |

**Check mode:**
```bash
aws ssm get-parameter --name /life-platform/remediation-mode --region us-west-2 \
  --query Parameter.Value --output text
```

**Switch mode (panic-off, or back to shadow for validation):**
```bash
aws ssm put-parameter --name /life-platform/remediation-mode --value shadow \
  --type String --overwrite --region us-west-2
```

**Manual trigger (force a run now, useful after pushing a fix):**
```bash
gh workflow run remediation-agent.yml
```

**Audit logs:**
- Agent decisions: `s3://matthew-life-platform/remediation-log/YYYY/MM/DD/HHMMSS.json`
- Auto-merge gate decisions: `s3://matthew-life-platform/remediation-log/automerge/YYYY/MM/DD/pr{N}-{HHMMSS}.{merged|held}.json`

**Budget Tier-3 pauses remediation automatically** — the agent's `gate()` reads `/life-platform/budget-tier` and skips the run if ≥ 3.

**Classifier rubric:** `docs/REMEDIATION_TAXONOMY.md` (A=auto-fix-safe, B=fix-via-pr, C=needs-human, D=stale).

**The merge gate is deterministic, not the agent.** The agent opens PRs labeled `auto-fix-safe`; `remediation/automerge.py` (separate workflow step) verifies allowlist/denylist/diff-bound/lint/unit-tests and merges if all green. The gate does NOT bypass `ci-cd.yml`'s production approval gate — even merged code needs manual deploy approval. Infra (`cdk/`) merges are flagged "needs cdk deploy."

## Urgent-Alarm Dispatcher (fast path, ADR-064)

`life-platform-remediation-dispatcher` Lambda is subscribed to the `life-platform-alerts` SNS topic. On each fire it:
1. Filters to urgent alarms (substrings: `canary`, `dlq-depth`, `site-api-error`, `budget-tier`, `bedrock-throttle`, `slo-`). Routine ingestion-source errors stay non-urgent — the daily 07:45 PT sweep handles them.
2. Dedupes per 30-min window via S3 marker (`s3://matthew-life-platform/remediation-log/dispatch-dedupe/{alarm}-{stamp}.marker`; markers expire after 1 day via lifecycle rule).
3. Calls GitHub `POST /repos/averagejoematt/life-platform/dispatches` with `event_type: urgent_alarm`, authenticated via a fine-grained PAT in Secrets Manager (`life-platform/github-dispatch-token`).
4. The workflow's `repository_dispatch: [urgent_alarm]` trigger fires the agent immediately.

**Inspect the dispatcher logs:**
```bash
aws logs tail /aws/lambda/life-platform-remediation-dispatcher --follow --region us-west-2
```

**Test the path end-to-end (synthetic alarm):**
```bash
cat > /tmp/test-alarm.json <<'JSON'
{"Records":[{"Sns":{"Message":"{\"AlarmName\":\"canary-manual-test\",\"NewStateValue\":\"ALARM\",\"NewStateReason\":\"Manual test\"}"}}]}
JSON
aws lambda invoke --function-name life-platform-remediation-dispatcher --region us-west-2 \
  --cli-binary-format raw-in-base64-out --payload file:///tmp/test-alarm.json /tmp/out.json
cat /tmp/out.json   # expect dispatched:1, errors:0
```
A successful test triggers a real workflow run (~$0.05 of Bedrock, ~10 min). Then check `gh run list --workflow=remediation-agent.yml --limit 1` for `event=repository_dispatch`.

### PAT rotation (every 90 days)

The fine-grained PAT in `life-platform/github-dispatch-token` expires every 90 days by design.

**Setup or rotation:**
1. Open https://github.com/settings/personal-access-tokens → **Generate new token (fine-grained)**.
2. Settings: name `life-platform-dispatcher`, expiry 90 days, repository access **Only `averagejoematt/life-platform`**, permissions **Contents: Read and write** ONLY (Metadata: Read-only is granted automatically — that's fine, leave it).
3. Generate, copy. Then:
   ```bash
   # First time:
   aws secretsmanager create-secret \
     --name life-platform/github-dispatch-token \
     --secret-string 'PASTE_TOKEN_HERE' \
     --region us-west-2

   # Rotation (subsequent times):
   aws secretsmanager update-secret \
     --secret-id life-platform/github-dispatch-token \
     --secret-string 'PASTE_NEW_TOKEN_HERE' \
     --region us-west-2
   ```
4. No Lambda redeploy needed — the dispatcher re-reads the secret on each cold start.
5. Old PAT can be left to expire naturally OR deleted at github.com/settings/personal-access-tokens.

**If the PAT is missing or expired**, urgent alarms still email you via the existing SNS subscriptions (no degradation); the dispatcher logs `SecretNotFound` or `GitHub HTTP 401` and the daily 07:45 PT sweep still covers the signal — just without the urgent fast path.

---

## Hevy Routine Write-Loop Operations (ADR-066)

The Hevy routine write-loop ships with two layers of safety gates. Operator actions documented here are configuration-only; no code redeploy is required to flip any gate.

### Pre-deploy provisioning (one-time, blocks first deploy)

Before the first `cdk deploy` of layer v64+ / OperationalStack / McpStack:

```bash
# 1. Create the WRITE secret. Use a SEPARATE Hevy API key from the read one
#    (life-platform/hevy). Generate at hevy.com/settings?developer.
aws secretsmanager create-secret \
  --name life-platform/hevy-write \
  --description "ADR-066: write-capable Hevy API key (cron + MCP). Separate from read." \
  --secret-string '{"api_key":"<paste-write-key>"}' \
  --region us-west-2

# 2. Create the two SSM gates (both default false — the cron stays off).
aws ssm put-parameter --name /life-platform/hevy/cron_enabled \
  --value false --type String --region us-west-2 \
  --description "ADR-066: master cron switch. Flip true after Phase 1 use justifies it."
aws ssm put-parameter --name /life-platform/hevy/autoreg_add_load_enabled \
  --value false --type String --region us-west-2 \
  --description "ADR-066: add-load autoregulation. Flip true only after PREREQS §C N≥30 passes."

# 3. Verify /life-platform/pause-mode exists; create if not (WR-47 default).
aws ssm get-parameter --name /life-platform/pause-mode --region us-west-2 \
  || aws ssm put-parameter --name /life-platform/pause-mode \
       --value active --type String --region us-west-2

# 4. Sync static configs to S3.
aws s3 cp config/training_landmarks.json s3://matthew-life-platform/config/
aws s3 cp config/movement_catalog.json   s3://matthew-life-platform/config/
aws s3 cp config/training_week.json      s3://matthew-life-platform/config/
aws s3 cp config/board_of_directors.json s3://matthew-life-platform/config/
```

### Post-deploy verification

```bash
# Layer v64 attached?
aws lambda get-function-configuration --function-name hevy-routine-cron \
  --query 'Layers[*].Arn' --output text

# Cron rule is disabled?
aws events describe-rule --name hevy-routine-cron-weekly --query 'State' --output text   # → DISABLED

# Both SSM gates default false?
aws ssm get-parameter --name /life-platform/hevy/cron_enabled --query 'Parameter.Value' --output text   # → false
aws ssm get-parameter --name /life-platform/hevy/autoreg_add_load_enabled --query 'Parameter.Value' --output text   # → false
```

### Flip the cron ON (after ~3 weeks of chat-path usage)

```bash
aws ssm put-parameter --name /life-platform/hevy/cron_enabled --value true --overwrite
aws events enable-rule --name hevy-routine-cron-weekly
```

To turn it back off — flip either gate to false. The Lambda no-ops on the next fire.

### Flip "add load" ON (after PREREQS §C validation passes)

```bash
aws ssm put-parameter --name /life-platform/hevy/autoreg_add_load_enabled --value true --overwrite
```

NOTE: the generator code path is currently inert even with this flag on; enabling it future-proofs the SSM signal but the symmetric autoregulation logic still needs the §C decision-rule branch wired in.

### Retire the interim Iris Tanaka seat

When a named Sports Medicine voice fills the seat:

```bash
# Remove the entry from the live config.
python3 -c "import json; \
  c = json.load(open('config/board_of_directors.json')); \
  c['members'].pop('iris_tanaka_interim', None); \
  c['_meta']['member_count'] -= 1; \
  c['_meta']['last_updated'] = '$(date +%F)'; \
  json.dump(c, open('config/board_of_directors.json','w'), indent=2)"

aws s3 cp config/board_of_directors.json s3://matthew-life-platform/config/

# Remove the placeholder note in docs/BOARDS.md (manual edit).
```

### Conflict-guard playbook (HevyConflict on PUT)

The write client refuses to clobber a routine that was edited in-app since our last push. When the cron or chat tool reports `HevyConflict`:

1. Inspect the in-app edit (open Hevy on phone or hevy.com).
2. Decide whether to re-author from the in-app state or overwrite it.
3. To overwrite: `aws ssm get-parameter --name /life-platform/hevy/cron_enabled` first to confirm cron is off, then GET the current routine via the MCP `get_routine` (Phase 2 helper TBD) or directly via `aws lambda invoke` of a small one-off probe; update the IR's `hevy_updated_at` to the latest value and re-commit.

The cron emits a `RoutineConflict` CloudWatch metric and returns `pushed=false` for that routine but does **not** raise — DLQ does not poison-pill on conflicts.

### DLQ playbook (HevyRetryable flood)

`HevyRetryable` (Hevy 429 or 5xx after retries) propagates from the cron, triggering Lambda async retry → DLQ. If the DLQ depth alarm fires:

1. Check Hevy status (`https://status.hevyapp.com/`).
2. Inspect failed payloads in the DLQ (CloudWatch logs for `hevy-routine-cron` log the throw).
3. If transient: redrive via the existing DLQ consumer (`life-platform-dlq-consumer`, every 6h).
4. If persistent: disable the cron (`aws events disable-rule --name hevy-routine-cron-weekly`) until Hevy recovers.

### Public-site copy reminder

Never describe this feature as "autoregulated" on averagejoematt.com or in the chronicle while the readiness signal is unvalidated. Correct phrasing: **deterministic volume-landmark programming with red-day deload guard.**

---

## Hevy Routine Title Convention — Deploy Steps (ADR-067)

Code is on `main`; layer v69 not yet published. Run these in order from the repo root.

```bash
# 1. Sync the new phase config to S3 (read by Lambda at runtime).
aws s3 cp config/training_phases.json s3://matthew-life-platform/config/ --region us-west-2

# 2. Build the layer bundle locally (includes routine_title.py).
bash deploy/build_layer.sh
ls cdk/layer-build/python/routine_title.py   # sanity check

# 3. Publish the layer + propagate to all consumers. Core publishes v69;
#    the rest pick it up via SHARED_LAYER_VERSION=69 in cdk/stacks/constants.py.
cd cdk
npx cdk deploy LifePlatformCore --require-approval never
npx cdk deploy \
  LifePlatformMcp \
  LifePlatformOperational \
  LifePlatformIngestion \
  LifePlatformEmail \
  LifePlatformCompute \
  --require-approval never --concurrency 3
cd ..

# 4. Verify all 36 layer-using Lambdas are on v69.
aws lambda list-functions --output json --region us-west-2 --no-paginate | \
  python3 -c "import json,sys; d=json.load(sys.stdin); vs={}; \
    [vs.setdefault((l['Arn'].rsplit(':',1)[-1]), []).append(f['FunctionName']) \
     for f in d['Functions'] for l in (f.get('Layers') or []) if 'shared-utils' in l['Arn']]; \
    [print(f'v{v}: {len(fns)}') for v, fns in sorted(vs.items())]"

# 5. Smoke-test the new title via MCP. (Force a cold start so the in-memory
#    phase-config cache reloads from S3.)
CUR=$(aws lambda get-function-configuration --function-name life-platform-mcp \
        --query 'Environment.Variables' --output json --region us-west-2)
ENV_PAYLOAD=$(python3 -c "
import json
env = json.loads('''$CUR''')
env['DEPLOY_VERSION'] = '2.74.4'
print(json.dumps({'Variables': env}))")
aws lambda update-function-configuration --function-name life-platform-mcp \
  --environment "$ENV_PAYLOAD" --region us-west-2 --query LastModified --output text

# 6. Re-commit an existing routine to see the new title applied in Hevy.
# (Use any active routine_id from `manage_hevy_routine action=list` via claude.ai.)
```

### Advancing the phase later

```bash
# Edit config/training_phases.json — change `current` + `current_started`.
# Then push to S3:
aws s3 cp config/training_phases.json s3://matthew-life-platform/config/ --region us-west-2
# Force cold start so warm containers reload the config:
aws lambda update-function-configuration --function-name life-platform-mcp \
  --environment "$ENV_PAYLOAD_WITH_NEW_DEPLOY_VERSION" --region us-west-2
```

N resets to 1 for each archetype the first time it's committed in the new phase. Y keeps counting up.

### Rollback (if titles look wrong)

```bash
# Revert the caller edits — title_context=None falls back to ir.title.
git revert --no-commit <commit-sha-of-adr-067>
# Or just unset title_context in mcp/tools_hevy_routine.py + cron_lambda.py and
# redeploy the MCP Lambda. The layer itself stays — routine_title.py is dormant.
```

---

## Final Experiment Reset → 2026-06-01 (ADR-067 amendment)

Source code already reflects the new genesis date (`lambdas/constants.py:EXPERIMENT_START_DATE = "2026-06-01"`, `config/user_goals.json:timeline.start_date`, `config/training_phases.json:current_started`). Run the restart-pipeline to apply everything else (phase-tag DDB, wipe intelligence, rebuild character, sync site/docs, layer publish, cdk deploy chain):

```bash
python3 deploy/restart_pipeline.py \
  --genesis 2026-06-01 \
  --override-weight-lbs 304.3 \
  --apply
```

The `--override-weight-lbs` is needed because 2026-06-01 has no Withings weigh-in yet; 304.3 lbs is the locked baseline from 2026-05-30 we're preserving.

After it completes, verify:

```bash
aws lambda list-functions --output json --region us-west-2 --no-paginate | \
  python3 -c "import json,sys; d=json.load(sys.stdin); vs={}; \
    [vs.setdefault(l['Arn'].rsplit(':',1)[-1], []).append(f['FunctionName']) \
     for f in d['Functions'] for l in (f.get('Layers') or []) if 'shared-utils' in l['Arn']]; \
    [print(f'v{v}: {len(fns)}') for v,fns in sorted(vs.items())]"
# Expect: v70: 36
```

Then force MCP cold start so the new constants are picked up:

```bash
CUR=$(aws lambda get-function-configuration --function-name life-platform-mcp \
        --query 'Environment.Variables' --output json --region us-west-2)
ENV_PAYLOAD=$(python3 -c "
import json
env = json.loads('''$CUR''')
env['DEPLOY_VERSION'] = '2.74.5'
print(json.dumps({'Variables': env}))")
aws lambda update-function-configuration --function-name life-platform-mcp \
  --environment "$ENV_PAYLOAD" --region us-west-2 --query LastModified --output text
```

Then from claude.ai: `manage_hevy_routine action=draft target_date=2026-06-01` → `action=dry_run routine_id=<id>` to see the new title. Y will start at 1 (no performed workouts since experiment start yet); N starts at 1 for each archetype.

---

## Hevy Title Renderer — Deploy Steps (ADR-088)

Code is on `main`; **nothing is deployed by the author** (layer module + MCP tool + config). Run in order from the repo root. Changed artifacts: `lambdas/routine_title.py` + `lambdas/hevy_common.py` (shared layer), `mcp/registry.py` + `mcp/tools_hevy_routine.py` (MCP lambda), `config/training_phases.json` (S3).

```bash
# 1. Sync the phase/counter config to S3 (read by Lambda at runtime).
#    current_started + reset_epoch_date = 2026-06-16.
aws s3 cp config/training_phases.json s3://matthew-life-platform/config/ --region us-west-2

# 2. Rebuild the shared layer (routine_title.py + hevy_common.py).
bash deploy/build_layer.sh
grep -c "count_performed_of_type" cdk/layer-build/python/routine_title.py   # sanity → 1

# 3. Publish the layer (Core) + propagate to consumers. Bump SHARED_LAYER_VERSION
#    in cdk/stacks/constants.py to the new version first if the build incremented it.
cd cdk
npx cdk deploy LifePlatformCore --require-approval never
npx cdk deploy \
  LifePlatformMcp LifePlatformOperational LifePlatformIngestion LifePlatformEmail LifePlatformCompute \
  --require-approval never --concurrency 3
cd ..

# 4. Redeploy the MCP server (registry.py + tools_hevy_routine.py changed — these
#    live in the MCP package, NOT the layer). Special build (see .claude/commands/deploy.md):
ZIP=/tmp/mcp_deploy.zip; rm -f $ZIP
zip -j $ZIP mcp_server.py mcp_bridge.py
zip -r $ZIP mcp/ -x 'mcp/__pycache__/*' 'mcp/*.pyc'
aws lambda update-function-code --function-name life-platform-mcp --zip-file fileb://$ZIP --region us-west-2

# 5. Verify: draft a custom routine, then dry_run — the wire_body title must read
#    "Foundation - Push - 2 - 2" (or "... - Pull - 1 - 2"), NOT "Push — <date>".
#    A title passed without force_title must be ignored (warning in the response).
```

Phase advancement later is config-only: edit `config/training_phases.json` (flip `current`, bump `current_started`), re-run step 1. No code deploy.

## Per-Exercise Notes — Deploy Steps (ADR-068)

Bundled with the ADR-067-amendment reset; both ship under layer v70. After `restart_pipeline` lands the reset, propagate v70 to all consumers and force the MCP cold start so the new modules + configs are read fresh:

```bash
# (1) Configs (re-sync; harmless if already in S3 from prior steps)
aws s3 cp config/training_week.json s3://matthew-life-platform/config/ --region us-west-2

# (2) Layer + cdk are handled by restart_pipeline above. If you only want
#     to ship ADR-068 without re-running restart_pipeline:
bash deploy/build_layer.sh
cd cdk
npx cdk deploy LifePlatformCore --require-approval never
npx cdk deploy LifePlatformMcp LifePlatformOperational LifePlatformIngestion \
               LifePlatformEmail LifePlatformCompute \
               --require-approval never --concurrency 3
cd ..

# (3) MCP cold start (preserves env vars)
CUR=$(aws lambda get-function-configuration --function-name life-platform-mcp \
        --query 'Environment.Variables' --output json --region us-west-2)
ENV_PAYLOAD=$(python3 -c "
import json
env = json.loads('''$CUR''')
env['DEPLOY_VERSION'] = '2.74.6'
print(json.dumps({'Variables': env}))")
aws lambda update-function-configuration --function-name life-platform-mcp \
  --environment "$ENV_PAYLOAD" --region us-west-2 --query LastModified --output text

# (4) From claude.ai:
#       manage_hevy_routine action=draft target_date=2026-06-02
#       manage_hevy_routine action=dry_run routine_id=<id>
#     Inspect wire_body.routine.exercises[*].notes — populated lifts get
#     "Last: 60kg 8/8/7 (24 May)"-style cues; lifts with no SOURCE#hevy
#     history get empty notes.
```

### Flipping the notes mode

```bash
# Edit config/training_week.json:exercise_notes_mode (one_best_line | show_both | off)
aws s3 cp config/training_week.json s3://matthew-life-platform/config/ --region us-west-2
# Force MCP cold start as above.
```

### Disabling per-exercise notes entirely

Set `exercise_notes_mode = "off"`. The generator skips the DDB exercise-history load (verified by `test_exercise_notes_off_mode_yields_empty_notes`); per-exercise notes ship as empty strings. No code redeploy needed.
