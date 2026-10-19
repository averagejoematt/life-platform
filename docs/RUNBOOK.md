# Life Platform — Runbook

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-10-17

Last updated: 2026-10-19 (v8.6.0 — 88 MCP tools, 77-module package, 108 Lambdas, 20 data sources)

**Ground truth (point-in-time values are drift — run the command instead):**
- Lambda functions defined (CDK): 108 — re-derive via `python3 deploy/sync_doc_metadata.py` (AST discoverers)
- Shared layer: **RETIRED** (#781/ADR-131) — shared modules ship in every bundle. Invariant check: `aws lambda list-functions --region us-west-2 --query "Functions[?Layers[?contains(Arn, 'life-platform-shared-utils')]].FunctionName"` → must be empty
- Account concurrency limit: **100** (raised from 10 via Support case 177921309700709 — verified live 2026-07-10 via `aws lambda get-account-settings`; see `docs/RESERVED_CONCURRENCY.md` for the reservation strategy)
- Alarms currently firing: point-in-time — check `aws cloudwatch describe-alarms --state-value ALARM --query 'MetricAlarms[].AlarmName' --output table --region us-west-2`
- DLQ: `life-platform-ingestion-dlq`, retention 14d, normally near-empty — check depth via `aws sqs get-queue-attributes --queue-url $(aws sqs get-queue-url --queue-name life-platform-ingestion-dlq --query QueueUrl --output text) --attribute-names ApproximateNumberOfMessages`; investigate via `dlq-consumer` Lambda logs
- SES configuration set: `life-platform-emails` — wired to the email Lambdas that name it (`grep -rl life-platform-emails lambdas/`; see "SES Email Pipeline"), CloudWatch event destination tracks open/click/bounce/complaint/delivery
- CloudTrail: `life-platform-trail` now has data events on `s3://matthew-life-platform/raw/*` and `uploads/*`

---

## S3 Safety Rules (ADR-032, ADR-033)

**Never run `aws s3 sync --delete` to the bucket root.** On 2026-03-16, this deleted 35,188 objects. Three protection layers are now in place:

1. **Bucket policy:** `matthew-admin` cannot `DeleteObject` on `raw/*`, `config/*`, `uploads/*`, `dashboard/*`, `exports/*`, `deploys/*`, `cloudtrail/*`, `imports/*`. Lambda roles are unaffected.
2. **safe_sync wrapper:** `source deploy/lib/safe_sync.sh` then call `safe_sync "$SRC" "$DST"` instead of raw `aws s3 sync --delete`. Blocks bucket-root targets and aborts if dryrun shows >100 deletions.
3. **S3 versioning:** Enabled. Even if objects are deleted, they can be recovered by removing delete markers.

**For site deploys:** merging to main deploys the site through CI (`site-deploy.yml`, #750 — gates + auto-rollback). The manual path (`bash deploy/sync_site_to_s3.sh`) is the fallback for attended fixes; it targets `s3://matthew-life-platform/site/` with correct cache-control headers.

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
| Edit a shared module (`lambdas/` root), deploy only one function | Every other function still runs the old copy | Fleet deploy: merge to main (CI auto-fleet-deploys unmapped `lambdas/` changes) or `bash deploy/deploy_fleet.sh` |
| Hand-rolled MCP zip (only `mcp_server.py` + `mcp/`) | MCP boots but imports fail (`No module named 'reading'`) | `bash deploy/deploy_lambda.sh life-platform-mcp mcp_server.py` — since #781 it stages the mcp-shaped full bundle |
| `aws s3 sync --delete s3://matthew-life-platform/` | Deletes 35K+ objects (ADR-032) | Always use `sync_site_to_s3.sh` |
| Change Lambda env var in AWS Console | Next `cdk deploy` reverts it silently | Edit CDK stack code instead |
| Add Lambda to CDK, forget its IAM policy | `AccessDenied` on first run | Add a policy function to the right `cdk/stacks/role_policies_<domain>.py` sibling + one re-export line in the `role_policies.py` facade (#2604) |
| Use DST-aware cron in EventBridge | Schedule drifts 1 hour twice yearly | All crons must be fixed UTC |
| Change pipeline schedule ordering | Compute reads yesterday's data; brief reads stale compute | Ingestion → Compute → Brief ordering is strict |
| Secret scheduled for deletion goes unnoticed | Data pipeline silently breaks when 7-day recovery window expires | `pipeline-health-check` Lambda probes all secrets daily. Check status page. |

---

## Shared Modules — ONE bundle, no layer (#781/ADR-131)

Canonical in `docs/CONVENTIONS.md` §1 (retirement date, `build_bundle.py`, which deploy paths stage through it, the invariant + how to verify it by hand). Don't restate it here.

---

## Secret Caching (COST-OPT-1)

Lambdas cache Secrets Manager reads for 15 minutes via `secret_cache.py` (a bundled shared module). This reduces Secrets Manager API calls by ~90% across 9 Lambdas. The cache is in-memory (per-Lambda instance), so a cold start always fetches fresh secrets.

---

## GitHub Actions quota glance (#1334, #1453)

GitHub is a metered production dependency (the repo is PUBLIC — `gh repo view --json visibility`, verified 2026-10-17): CI, site-deploy, and the remediation agent all run on Actions minutes. The **automated** path is `deploy/drift_sentinel.py`'s `check_github_quota()`, which runs inside the existing `remediation-agent.yml` schedule (Mon/Wed/Fri — `deploy/sentinel_cadence.py` derives the expected weekdays from the workflow's own cron) — no dedicated cron. It lands in the remediation agent's one curated email (`remediation/drift_report.quota_html()`) with: real minutes-used-vs-allowance + a 70% warn line when the billing API is reachable, top wall-clock-consuming workflows over the trailing 7 days always. See `docs/COST_TRACKER.md` §"GitHub Actions / Repo Hosting" for the full fact table and the confirmed reason the billing figures read as "unavailable" today (the workflow's built-in `GITHUB_TOKEN` lacks the `user` scope).

**Manual monthly-close fallback** (run locally, needs a `gh` session with the `user` scope — `gh auth refresh -h github.com -s user` once, interactively, as the account owner):

```bash
gh api users/averagejoematt/settings/billing/actions        # minutes used vs. included
gh api users/averagejoematt/settings/billing/shared-storage  # artifact/Packages storage used
python3 deploy/drift_sentinel.py --no-write                  # print the same weekly-sentinel view locally
```

Assert both quota figures stay under 80% before the month rolls over; if either is close, either wait for the natural reset or reduce run-rate (path-filtered/concurrency-capped workflows — see COST_TRACKER — are the first lever, then trimming schedule frequency).

---

## Gap-Fill Behavior

**Whoop:** Gap-fill checks for `recovery_score` presence. If a record exists but `recovery_score` is missing, the Lambda re-fetches from the Whoop API (recovery data is often delayed ~2 hours after sleep ends).

All ingestion Lambdas include today in gap-fill checks (`range(0, N)`, not `range(1, N)`).

---

## OAuth Token Refresh Behavior

Each OAuth-based ingestion Lambda refreshes its own tokens and writes them back to Secrets Manager. No dedicated rotation Lambda exists for OAuth tokens (only for the MCP API key via `key-rotator`).

| Lambda | Auth Type | When It Refreshes | Writes to Secrets Manager | Concurrent Invocation Risk |
|--------|-----------|-------------------|--------------------------|---------------------------|
| whoop | OAuth refresh_token | Every invocation (unconditional) | Yes | Low — reserved concurrency 1 |
| withings | OAuth refresh_token | On 401 response | Yes | Low — reserved concurrency 1 |
| strava | OAuth expires_at | On expiration check (5-min buffer) | Yes | Medium |
| eightsleep | Password grant | On 401 response | Yes | Low |

**Note:** A concurrent invocation (manual invoke + cron overlap) could race on the token write. `ReservedConcurrentExecutions=1` is live in CDK for whoop and withings (`cdk/stacks/ingestion_stack.py`; the account limit is 100, `docs/RESERVED_CONCURRENCY.md`), so a manual invoke that overlaps the cron is throttled rather than racing the token write.

---

## Meal Grouping — Backfill & Regroup (ADR-090)

The derived `macrofactor_meals` projection is built by the deterministic `meal_grouper`
(a bundled shared module). Raw `macrofactor` is never mutated.

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

**Bundle dependency (#781):** the grouper, seed templates, projection writer, and
`food_vocabulary.json` ship inside every function's code bundle (`deploy/build_bundle.py`).
Changing any of them = fleet deploy (merge to main — CI auto-fleet-deploys — or
`bash deploy/deploy_fleet.sh`), which includes the MCP lambda. Verify:
`manage_meals list_templates` returns 10 templates (not an import error).

**Format-drift:** if `get_freshness_status.macrofactor_format_drift.drifted` is true (or the
`MacroFactorFormatDrift` alarm fires), the MacroFactor diary export reverted to daily-summary
(empty `food_log`) and the grouper is starved — re-export the diary format.

---

## Pipeline Ordering Constraint (ADR-052)

**All EventBridge cron expressions are fixed UTC — except `daily-brief` (EventBridge Scheduler, `America/Los_Angeles`, #4284).** The PT times below are for reference only — they shift by 1 hour when DST begins (March) and ends (November). The UTC times never change.

The pipeline has strict ordering. Changing schedules without maintaining this sequence produces stale data:

```
hourly (INGEST_HOURLY)  INGESTION   API pulls from Whoop, Withings, Strava, etc. (per-source cadence: source_registry.py)
15:05 UTC           anomaly-detector        (08:05 PDT)
16:30 UTC           character-sheet-compute (09:30 PDT)
16:35 UTC           adaptive-mode-compute   (09:35 PDT)
16:40 UTC           daily-metrics-compute   (09:40 PDT)
16:45 UTC           daily-insight-compute   (09:45 PDT)
17:00 UTC (18:00 after 2026-11-01)  daily-brief  (10:00 Pacific — zoned schedule, #4284; 10:00 PDT — reads computed results → email → public_stats.json)
19:30 UTC           og-image-generator      (12:30 PDT — reads public_stats.json → generates share images)
```

**Verify the schedule chain** (the EventBridge rule names are CDK-generated, so match on the target Lambda, not a rule name — the committed answer is `model/platform_model.json`'s `schedules`):
```bash
python3 - <<'PY'
import json
m = json.load(open("model/platform_model.json"))
keep = {"anomaly-detector", "character-sheet-compute", "adaptive-mode-compute", "daily-metrics-compute", "daily-insight-compute", "daily-brief", "og-image-generator"}
for s in sorted(m["schedules"], key=lambda s: s["utc"] or ""):
    if s["lambda"] in keep:
        print(f'{s["lambda"]:28s} {s["expr"]}')
PY
```
Expected: the order above (15:05, 16:30, 16:35, 16:40, 16:45, 17:00, 19:30 UTC). Live cross-check: `aws events list-rules --region us-west-2 --query "Rules[?contains(Name,'CharacterSheet')].[Name,ScheduleExpression]"`.

---

## Daily Operations

### Scheduled times — read them, never restate them

The full per-Lambda cron list used to live in a table here and drifted: ingestion moved from per-source morning times to hourly (`INGEST_HOURLY` / `HABITIFY_HOURLY`, with sparse crons for the sub-daily sources, #4641), and Garmin retired (#4640, 2026-10-11 — no function, no rule; its data arrives through Strava). The sources of truth, all derived from the CDK stacks:

- `python3 scripts/boot_brief.py` — next runs and the fleet/alarm counts
- `python3 scripts/blast_radius.py --lambda <function>` — one function's schedule(s), alarm, reads and writes
- `model/platform_model.json` → `schedules` (every cron, UTC, with its stack) and `lambdas/ingestion/source_registry.py` (per-source cadence, paused state, `stale_hours`)
- `cdk/stacks/*.py` — each function's `schedule=`

All EventBridge crons are fixed UTC; PT = UTC-7 in PDT, UTC-8 in PST. The strict compute chain is the "Pipeline Ordering Constraint" block above. Weekly rhythm (which day each email lands): `docs/OPERATOR_GUIDE.md` → "Weekly Operational Rhythm".

**MacroFactor** uses an automated Dropbox pipeline: phone export → Dropbox `/life-platform/` → `dropbox-poll` Lambda (sparse cron — see the registry) → S3 → `macrofactor-data-ingestion`. Auto-detects nutrition vs workout CSVs. Manual S3 upload (`s3://matthew-life-platform/imports/macrofactor/`) still works as fallback.

**Apple Health** primary path is the Health Auto Export webhook (hourly push from iOS): Stelo/Apple Watch → HealthKit → Health Auto Export app → API Gateway → `health-auto-export-webhook`. The `apple-health-ingestion` export.xml import Lambda was RETIRED 2026-07-04 (#474, ADR-103) — it was a full-replace clobber of the webhook's merged records and its S3 trigger never existed — so there is no manual XML upload path; the HAE webhook is the sole `apple_health` writer (the old XML backfill script is no longer in the tree).

**⚠️ Health Auto Export gotcha:** The app must be configured for hourly (not "since last run") sync to reliably include all metric types. With infrequent syncs, payload size grows and the app may silently drop metrics like Dietary Water and Dietary Caffeine, sending only activity data. If water/caffeine stop appearing in webhook logs, check the app's sync interval.

### State of Mind (How We Feel) — restarting the automation (ADR-121, #507)

State of Mind is a **kept** subsystem (ADR-121) whose only blocker is the manual daily-logging habit, not the pipeline. The engine is wired and correct: check-ins flow **How We Feel (or Apple Health "State of Mind") → HealthKit → Health Auto Export → `health-auto-export-webhook` → `raw/matthew/state_of_mind/…` in S3 + `som_*` daily aggregates on the `apple_health` DynamoDB partition** (there is deliberately no separate `state_of_mind` partition — every HAE sub-datatype lands on `apple_health`). All five-plus consumer surfaces (Mind pillar / character sheet, daily brief + coach narrative, Wednesday chronicle, cockpit/observatory mood, MCP `get_mood view=state_of_mind`) read that partition and honestly show "no recent State of Mind data" when it's empty.

**To restart (the one manual step the owner must do):**
1. **Log moods** in the How We Feel app (or Apple Health → Browse → State of Mind). This is the habit — "just start doing it." Momentary emotions and daily mood both flow.
2. **Confirm the HAE automation exists and is enabled** (it is a *separate* automation from the metrics one — State of Mind is its own HAE Data Type, not a Health Metric). In Health Auto Export → Automations, there must be a REST API automation with:
   - **Data Type:** `State of Mind` (create a new automation if only the Health Metrics one exists)
   - **URL:** the same Lambda Function URL / API Gateway endpoint as the existing metrics automation
   - **Headers:** the same `Authorization: Bearer …` token
   - **Export Format:** JSON, Version 2 · **Date Range:** "Since Last Sync" · **hourly** cadence
3. **Verify a reading landed** (within ~an hour of logging): `aws s3 ls s3://matthew-life-platform/raw/matthew/state_of_mind/ --recursive` should show a file for today, and `get_mood view=state_of_mind` should return a valence trend rather than the "no data" restart message.

The webhook path is **live** (not parked) — it is the same `health-auto-export-webhook` that ingests CGM/BP/water/steps daily, so no infra needs enabling; only the phone-side State-of-Mind automation and the logging habit.

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
Per-source `ingestion-error-*` alarms were consolidated 2026-05-29 (`error_alarm=False`
in `ingestion_stack.py`); detection moved downstream — freshness-checker, DLQ depth, canary; there is deliberately NO aggregate alarm (CloudWatch metric-math cap; see MONITORING.md). Do NOT
query the old names (`describe-alarms --alarm-names` silently omits nonexistent alarms,
so an empty result reads as false "all-OK"). Query by state instead:
```bash
aws cloudwatch describe-alarms --state-value ALARM \
  --query 'MetricAlarms[?contains(AlarmName, `ingestion`) || contains(AlarmName, `dlq`)].{Name:AlarmName,State:StateValue}' \
  --region us-west-2
```
Empty output = nothing ingestion-related is firing. Freshness is the better signal
anyway: `slo-source-freshness` + the /status/ page.

### Via DLQ (failed messages land here)
```bash
aws sqs get-queue-attributes \
  --queue-url https://sqs.us-west-2.amazonaws.com/205930651321/life-platform-ingestion-dlq \
  --attribute-names ApproximateNumberOfMessages
```
Should be `0`. If non-zero, use the console to inspect messages.

**Redrive options:** the `dlq-consumer` Lambda auto-drains every 6h (redrives where
possible). To force reprocessing NOW instead of waiting:
```bash
# invoke the consumer directly
aws lambda invoke --function-name life-platform-dlq-consumer --region us-west-2 /tmp/dlq_out.json
# or use SQS's native redrive (moves messages back to the source queue):
aws sqs start-message-move-task \
  --source-arn arn:aws:sqs:us-west-2:205930651321:life-platform-ingestion-dlq --region us-west-2
```
Fix the root cause FIRST — redriving into a still-broken Lambda just round-trips the messages.

---

## S3 bucket notifications (ingestion triggers outside CDK)

Four functions start from an S3 event notification on `matthew-life-platform`. The notifications are ONE bucket-level document that CDK does not own; `cdk/stacks/` only grants `s3.amazonaws.com` permission to invoke the functions. A dropped notification shows up nowhere except as eventual staleness of the source (#4643).

| Notification Id | Function | Filter |
|---|---|---|
| `MacroFactorCSVIngest` | `macrofactor-data-ingestion` | prefix `uploads/macrofactor/`, suffix `.csv` |
| `InboundEmailInsightParser` | `insight-email-parser` | prefix `raw/inbound_email/` |
| `FoodDeliveryCSVIngest` | `food-delivery-ingestion` | prefix `imports/food_delivery/`, suffix `.csv` |
| `MeasurementsCSVIngest` | `measurements-ingestion` | prefix `imports/measurements/` |

All four fire on `s3:ObjectCreated:*`. The authoritative list is `EXPECTED_NOTIFICATIONS` in `deploy/check_bucket_notification_drift.py`; this table restates it.

**Check (read-only, run any time):**

```bash
python3 deploy/check_bucket_notification_drift.py --strict   # exit 1 on drift or a read error
```

It makes one `s3:GetBucketNotification` call and reports `missing`, `unexpected`, `changed` and any non-Lambda configuration. It also runs nightly, blocking, in `.github/workflows/config-drift.yml` (the ownership/bucket-policy drift step) under `github-actions-deploy-role`, whose `S3BucketNotificationRead` grant was applied 2026-10-11 (`infra/iam/README.md`).

**Repair (owner, attended — this is an AWS write):** `put-bucket-notification-configuration` REPLACES the whole document, so never put a single entry. Read the full live document, edit it, and put the whole thing back:

```bash
aws s3api get-bucket-notification-configuration --bucket matthew-life-platform > /tmp/notif.json
# edit /tmp/notif.json so it matches EXPECTED_NOTIFICATIONS — keep the other entries
aws s3api put-bucket-notification-configuration --bucket matthew-life-platform \
  --notification-configuration file:///tmp/notif.json
python3 deploy/check_bucket_notification_drift.py --strict   # must print `clean`
```

S3 validates each destination when the document is put: a function whose resource policy has no `s3.amazonaws.com` invoke grant fails the whole call. Three of the grants are CDK-owned (`S3InvokeMacrofactor`, `S3InvokeFoodDelivery`, `S3InvokeMeasurements` in `cdk/stacks/ingestion_stack.py`). The `insight-email-parser` grant (`AllowS3InvokeRefresh`, read 2026-10-10) is also outside CDK: its stack declares only the SES grant.

To add or remove a trigger, change `EXPECTED_NOTIFICATIONS` and this table in the same PR, then apply the document change above after the merge.

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

### Long-running / AI-generating Lambdas — never a bare sync invoke (#2860)

A default `aws lambda invoke` is SYNCHRONOUS over the AWS SDK's own client-side
read timeout (~60s) — far shorter than a multi-minute AI generation like
daily-brief's (~7.5min, 4 AI calls) or wednesday-chronicle's. The CLI/SDK's
standard retry mode treats that client timeout as transient and retries the
**same invocation**, `attempts=3`, ~60s apart — three separate Lambda
executions, three separate paid AI generations, and a real risk of tripping
the AI token-usage alarms. This happened live: daily-brief, 2026-08-17
15:54–15:56Z (#2860).

**`dry_run:true` does NOT protect you here.** Per #2255, DRY_RUN suppresses
writes only (SES, S3, DynamoDB) — never AI spend, which is the expensive half.
Before invoking any AI-generating email Lambda by hand, use ONE of:

```bash
# Preferred when you don't need to block on the response: async invoke has no
# client-side timeout/retry loop at all.
aws lambda invoke \
  --function-name daily-brief \
  --invocation-type Event \
  --payload '{"dry_run": true}' \
  --cli-binary-format raw-in-base64-out \
  --region us-west-2 \
  /tmp/response.json
# Event invokes return 202 immediately with no response body — check
# completion via CloudWatch Logs (see "Daily-Brief Log Inspection" below).

# If you need the sync response body, disable the client read-timeout instead
# of racing it — do not just re-run the command if it "hangs":
aws lambda invoke \
  --function-name daily-brief \
  --cli-read-timeout 0 \
  --payload '{"dry_run": true}' \
  --cli-binary-format raw-in-base64-out \
  --region us-west-2 \
  /tmp/response.json && cat /tmp/response.json
```

daily-brief additionally carries an in-flight guard as a backstop
(`lambdas/emails/daily_brief_lambda.py::_acquire_daily_brief_lock` — a
DynamoDB conditional-put LEASE keyed on `date + dry_run`, TTL comfortably
longer than the function's own 900s configured timeout) that short-circuits a
concurrent duplicate invocation BEFORE any AI call runs. That guard is a
backstop for the retry-storm case, not a substitute for avoiding the retry
storm in the first place — it still means a wasted invocation, just not a paid
one. wednesday-chronicle addresses the same duplicate-generation risk with a
generation cache instead (#2669, `chronicle_store.py`) — same symptom class,
different mechanism; don't conflate the two when troubleshooting either.

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
git checkout <good-sha> -- <source-file>   # the function's source path under lambdas/<domain>/ (ci/lambda_map.json)
bash deploy/deploy_lambda.sh <name> <source-file>
git checkout HEAD -- <source-file>   # restore working tree
# or use the rollback script: bash deploy/rollback_lambda.sh <name>
```

**B) Deployed via CDK (`cd cdk && npx cdk deploy`):**
```bash
git revert <bad-commit-sha>
cd cdk && npx cdk diff && npx cdk deploy --all
```

Always smoke-test after rollback (`aws lambda invoke ... /tmp/x.json && cat /tmp/x.json | grep -i error`).

## Cache Warmer

The dedicated warmer Lambda `life-platform-mcp-warmer` (schedule: its `schedule=` in `cdk/stacks/mcp_stack.py`; same `mcp_server.py` bundle as the MCP server) pre-computes the steps listed in `mcp/warmer.py` (4 after the #395 prune: three `get_training` views and the CGM dashboard) into the `CACHE#matthew` partition. Cached tools return in <100ms. Custom date ranges bypass cache and compute fresh.

Manually trigger warmer:
```bash
aws lambda invoke \
  --function-name life-platform-mcp-warmer \
  --payload '{"source": "aws.events"}' \
  --cli-binary-format raw-in-base64-out \
  /tmp/warmer.json && cat /tmp/warmer.json
```

Verify cache items exist:
```bash
aws dynamodb query \
  --table-name life-platform \
  --key-condition-expression "pk = :pk" \
  --expression-attribute-values '{":pk":{"S":"CACHE#matthew"}}' \
  --query 'Count'
```
Expected: one item per `mcp/warmer.py` step (4), plus any not-yet-expired older cache keys (live read 2026-10-17: 5, one a stale `TOOL#personal_records_…` key awaiting its 26 h TTL).

---

## Secrets Management

All secrets are stored in AWS Secrets Manager under `life-platform/` prefix. See `docs/SECRETS_MAP.md` for the authoritative inventory; `docs/SECRETS_ROTATION.md` for rotation procedures.

**Inventory:** `docs/SECRETS_MAP.md` is the reconciled list; the live count is `aws secretsmanager list-secrets --region us-west-2 --query 'length(SecretList[*])'` (28 on 2026-10-17). The 2026-05 deletion-window era is over: `dropbox` and `anthropic-api-key` completed deletion, `notion` was restored and sits live-but-idle (retire-candidate), and `garmin` is dormant after the source's retirement (#4640).

| Secret | Function(s) | Notes |
|--------|-------------|-------|
| `life-platform/whoop` | whoop-data-ingestion | OAuth2; auto-refresh on each run |
| `life-platform/withings` | withings-data-ingestion | OAuth2; auto-refresh on 401 |
| `life-platform/strava` | strava-data-ingestion | OAuth2; auto-refresh on expires_at |
| `life-platform/garmin` | (none — retired #4640) | dormant; owner-attended delete |
| `life-platform/eightsleep` + `/eightsleep-client` | eightsleep-data-ingestion | User creds + client ID |
| `life-platform/ai-keys` | the few direct-API readers (`grep -rl life-platform/ai-keys lambdas/`) — most inference is Bedrock/IAM (ADR-062) | Anthropic API key, fallback path |
| `life-platform/site-api-ai-key` | life-platform-site-api, life-platform-site-api-ai | Isolated Anthropic key for public site |
| `life-platform/mcp-api-key` | life-platform-mcp, canary, qa-smoke, key-rotator | HMAC bearer; 90-day auto-rotation |
| `life-platform/todoist` | life-platform-mcp (write tools) | Dedicated; bundle still used by ingestion |
| `life-platform/habitify` | habitify-data-ingestion | API key |
| `life-platform/ingestion-keys` | todoist-data-ingestion, notion-journal-ingestion, dropbox-poll, health-auto-export-webhook | Bundle: Notion + Dropbox + Todoist + Habitify + HAE webhook key |
| `life-platform/notion` (live, idle) | none read by ingestion — the bundle is authoritative | Retire-candidate; owner decision (`docs/SECRETS_MAP.md`) |
| `life-platform/dropbox`, `life-platform/anthropic-api-key` | — | Deleted (windows closed 2026-05) |

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

Each Lambda has its own dedicated, CDK-managed IAM role scoped to what it needs. The hand-kept role table that used to sit here drifted completely (it named `lambda-<fn>-role` roles that no longer exist — live IAM roles are CDK-generated — and secrets `life-platform/anthropic` and `life-platform/health-auto-export` that never existed). Read the roles from the code instead:

- Policies: `cdk/stacks/role_policies_*.py` (`role_policies.py` is the re-export facade); each stack gives every function its own role (`create_platform_lambda`).
- Per-function grants and reads/writes: `python3 scripts/blast_radius.py --lambda <function>`.
- Live: `aws iam list-roles --query "Roles[?contains(RoleName,'LifePlatform')].RoleName"`.

Worked example (pinned by `tests/test_docstring_secret_ids_2653.py`): the `dropbox-poll` role (historically `lambda-dropbox-poll-role`, live `LifePlatformIngestion-DropboxPollRole…`) is granted only `life-platform/ingestion-keys` (`ingestion_dropbox` in `role_policies_ingestion.py`); the dedicated `life-platform/dropbox` was deleted 2026-05-17 (#2653).

*All Lambdas have dedicated roles (SEC-1, v3.4.0); no shared roles remain.*

---

## DynamoDB

Table: `life-platform` (us-west-2)  
Design: Single-table with composite keys  
- Partition key: `pk` (e.g., `USER#matthew#SOURCE#whoop`)  
- Sort key: `sk` (e.g., `DATE#2026-02-22`) — the attribute names are lowercase (verified `describe-table` 2026-10-17); an uppercase `PK`/`SK` expression fails

### Check item count
```bash
aws dynamodb describe-table --table-name life-platform \
  --query 'Table.ItemCount'
```

### Query a specific source
```bash
aws dynamodb query \
  --table-name life-platform \
  --key-condition-expression "pk = :pk AND begins_with(sk, :sk)" \
  --expression-attribute-values '{":pk":{"S":"USER#matthew#SOURCE#whoop"},":sk":{"S":"DATE#2026-02"}}' \
  --query 'Items[*].sk.S'
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
#    TABLE_NAME env var on every Lambda — easiest via CDK redeploy
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

## Rate-Limiter Live Probe (#1439)

`lambdas/common/rate_limiter.py` (the DynamoDB-backed per-IP rate limiter) has deterministic
unit coverage in `tests/test_rate_limiter.py` (429 threshold, TTL/window reset,
fail-open/fail-closed). A separate **live probe**, `deploy/probe_rate_limiter.py`,
verifies the real deployed path end-to-end (Lambda → DynamoDB → CloudFront → response)
against `POST /api/board_ask` — chosen because its rate-limit check runs before body
validation, so probe requests never reach a Bedrock call (zero model cost) and never
touch `/api/subscribe` (no real emails).

**Posture re-decided 2026-08-23 (#2828):** a scheduled observation now exists — the
nightly qa-smoke check `ratelimit:edge_429` (`lambdas/operational/qa_check_edge_429.py`)
reuses the trip429 mechanism nightly, because the 2026-08-14 P2 incident (rate limiting
silently unenforced ~40 min, all CI gates green, caught only by a manual run) postdates
and overrides #1439's manual-only call. The script below remains the ATTENDED tool;
never wire it into per-deploy paths (`deploy/smoke_test_site.sh` / CI):
```bash
python3 deploy/probe_rate_limiter.py                 # --mode shape (default, safest): 2 requests, shape-only
python3 deploy/probe_rate_limiter.py --mode trip429   # up to 6 requests, deliberately observes one real 429
```
Cadence: at most once every few weeks, and only after touching `rate_limiter.py`,
the `_handle_board_ask` rate-limit wiring in `lambdas/web/site_api_ai_lambda.py`, or
the site-api-ai IAM policy. It always runs from the operator's/agent's own IP, never a
real reader's — the per-IP counter it may exhaust only affects that one IP for the rest
of the hour.

**PASS:** every response is well-formed JSON with the expected shape (400 `{"error":
...}` before the limit, 429 with a `Retry-After` header and `{"error": ...}` once
tripped). **FAIL:** any other status code, or (trip429 mode) never observing a 429
within `BOARD_RATE_LIMIT + 1` requests — investigate the rate limiter, the DDB table,
or the site-api-ai Lambda's IAM policy. Full reasoning + design tradeoffs are in the
script's module docstring.

---

## Common Issues

### Whoop/Withings/Strava: "Token expired" error
These functions auto-refresh tokens and write back to Secrets Manager. If they fail with auth errors, the refresh token itself may have expired (rare but possible if the function didn't run for weeks). Resolution: re-authenticate via the source app and manually update the secret.

### ingest-auth-unhealthy-24h: red on a verified-healthy fleet (#2004, re-cut by #2976)

**Symptom:** the `ingest-auth-unhealthy-24h` alarm (SNS urgent topic) is in ALARM,
but every source looks fine — recent ingestion Lambda logs are clean and no
credential actually needs rotating.

**Since #2976 this self-resolves instead of latching 24h, but #4641 widened the window to 15 h**: the sub-daily sources were cut to sparse crons (dropbox every 2 h, notion 14,21,3 UTC, withings 14,17,21,0 UTC, a 14 h sparsest gap), and a shorter window alternates ALARM/OK between their runs and re-pages a dead credential 2-3x a day. The alarm
reads `LifePlatform/OAuth IngestAuthHealthy` (dimensionless, fleet-wide) with
`Minimum` over a `period=54000s` / `evaluation_periods=1` window
(`cdk/stacks/monitoring_stack.py`, alarm id `IngestAuthUnhealthy`; the name's
`-24h` suffix is historical). The old fixed 86400s window latched a fully
recovered fleet red for up to 24h after the last unhealthy emission — the
2026-08-21→22 dropbox incident held two alarms red for a day after a transient
403. The shorten is safe *only because* #2976 also made every
authenticated-successful run emit a 1 (framework `errors == 0`, dropbox after
`list_folder`, notion after `query_database`); a tripped breaker keeps landing 0s
on every scheduled run, so Min<1 over 15h reads "some held source emitted unhealthy
within the window". **Honest clear delay: up to ~15 h after real recovery** (the last
0 has to age out), not the ~1 h of #2976. Cadence caveat: Eight Sleep (one 4-run
burst, 18 h gap) and DAILY-cron sources are not held by this window — their
breakage pins the aggregate only around their cron hours; the per-source
`ingest-auth-unhealthy-{source}` alarm (window matched to its own cadence,
86400s for daily sources) is the durable per-source truth. A red older than ~15h
therefore means some held source is emitting 0s *right now*.

**Triage — confirm real state, don't trust alarm state:**

1. Check for any *currently active* auth-breaker markers (the actual "is a
   credential dead right now" signal) across sources — read-only:
   ```bash
   aws dynamodb query --table-name life-platform \
     --key-condition-expression "pk = :pk AND sk = :sk" \
     --expression-attribute-values '{":pk":{"S":"USER#matthew#SOURCE#<source>"},":sk":{"S":"AUTH_FAILURE"}}'
   # repeat per credentialed source (see lambdas/ingestion/source_registry.py
   # oauth_source_ids()) or scan for sk = AUTH_FAILURE if checking the whole fleet
   ```
   No item (or an item whose `marked_at` is >24h old) means the breaker is not
   tripped for that source — `lambdas/common/auth_breaker.check_breaker()` treats
   it the same way and lets the next run through.
2. Check the metric's recent datapoints directly — if the last few hourly points
   are all `1`, the fleet has recovered and the alarm is coasting out its window:
   ```bash
   aws cloudwatch get-metric-statistics \
     --namespace LifePlatform/OAuth --metric-name IngestAuthHealthy \
     --start-time "$(date -u -v-6H +%Y-%m-%dT%H:%M:%S)" --end-time "$(date -u +%Y-%m-%dT%H:%M:%S)" \
     --period 3600 --statistics Minimum --region us-west-2
   ```
3. If either check shows a genuinely dead credential, triage by source using the
   relevant entry below (Garmin, Whoop/Withings/Strava, Eight Sleep, etc.) — the
   per-source `ingest-auth-unhealthy-{source}` alarms (#1960) name the culprit
   directly, so check those first if this aggregate alarm is the only one red.
4. If both checks are clean, no action is needed — the alarm self-clears once the
   unhealthy datapoint ages out of the trailing 15 h window (#2976, widened by #4641). A clean fleet
   with the alarm still red after ~16h is a real defect — investigate the metric
   stream, don't silence the alarm.

(The pre-#2976 "reshape into 4×6h evaluation periods" operator option is
obsolete — the #2976 re-cut delivered a strictly better clear latency by fixing
the emitters instead of the window arithmetic.)

### Garmin: 429 Too Many Requests / OAuth1 expired (auth_breaker tripped) — RETIRED (#4640)

> **Historical.** The `garmin-data-ingestion` function, its alarm and its role were removed on 2026-10-11 (ADR-074 amendment). Garmin-watch activities arrive through Strava. Reviving the direct API is a new ADR plus re-adding the function to `cdk/stacks/ingestion_stack.py`; the steps below are kept only as the revival reference.

Garmin OAuth1 has a ~30-day lifetime; after the gap or rate-limit storm, the Lambda trips `auth_breaker` and stops attempting calls until cleared.

**Step 1 — Re-auth via browser flow (Playwright):**
```bash
cd ~/dev/life-platform
python3 setup/setup_garmin_browser_auth.py
# Walks through Garmin login + MFA in headed Chromium
# Writes fresh garth tokens to life-platform/garmin
```

**Step 2 — Clear the auth_breaker marker so the Lambda will retry:**
```python
# Run via aws-vault or python3 with appropriate AWS creds
python3 -c "
import boto3
from common.auth_breaker import clear_failure
import logging
logging.basicConfig(level=logging.INFO)
ddb = boto3.resource('dynamodb', region_name='us-west-2')
table = ddb.Table('life-platform')
clear_failure(table, 'garmin', 'matthew', logging.getLogger())
"
```

Or directly via CLI (key pattern: `USER#matthew#SOURCE#garmin`, sk `AUTH_FAILURE` — `lambdas/common/auth_breaker.py`; the same shape clears any source):
```bash
aws dynamodb delete-item --table-name life-platform --region us-west-2 \
  --key '{"pk":{"S":"USER#matthew#SOURCE#garmin"},"sk":{"S":"AUTH_FAILURE"}}'
```

**Step 3 — Smoke test:**
```bash
aws lambda invoke --function-name garmin-data-ingestion --payload '{}' \
  --cli-binary-format raw-in-base64-out /tmp/garmin.json && cat /tmp/garmin.json
```

Then watch the alarm `life-platform-garmin-data-ingestion-errors` return to OK within 24h.

### Eight Sleep: JWT auth failure
Eight Sleep uses username/password → JWT (no OAuth). If the JWT refresh fails, the function will write to the DLQ. Check logs for the specific error. Resolution may require re-entering credentials in Secrets Manager if the account password changed.

### Notion journal: no full re-sync yet, and how the reconcile decides (#4631)

**No full re-sync of the journal (`{"full_sync": true}`, or a wide `start`/`end` backfill) until the #4631 fixes are merged, deployed and proven** — proven means the first production run that re-fetches an old-dated page has logged its reconcile decision with the row count unchanged. The legacy-key migration runs only after that, with the journal row count and the enriched-row count recorded before and after (counts only). Before the fix, a re-sync would have stripped the enrichment from every entry it re-keyed and could have deleted same-day entries outright; DynamoDB holds the only processed copy of most of them.

How `notion-journal-ingestion` treats the multi-per-day templates (`MULTI_PER_DAY` in `lambdas/ingestion/notion_lambda.py`):

- A run that reaches a date with one page in hand (an old page edited today, a page created today and dated back) writes that page and **leaves the date's other rows alone**. Holding one page of a date is not a view of the whole date.
- A stored row is removed in two cases only: the same Notion page was just written under its stable key and its `enriched_*`/`defense_*` fields were read and carried across first; or a whole-date re-query of Notion no longer returns the row's page. A failed or inconsistent re-query, an unreadable row, or a row with no `notion_page_id` removes nothing.
- Each `(date, template)` the run touches logs one line, counts only — no key, page id or text:
  `[E-6] reconcile decision date=… template=… outcome=done rows_before=N written=W rekeyed_removed=R vendor_absent_removed=A kept_unwritten=K requery=… rows_after=M`.
  `rows_after = rows_before + (new pages) − A`; a re-key leaves the count unchanged. Find them with `filter @message like /reconcile decision/` on `/aws/lambda/notion-journal-ingestion`.

### MacroFactor: Function not triggered
Ensure your export CSV is dropped into the correct S3 path: `s3://matthew-life-platform/uploads/macrofactor/`. The filename does not matter but the prefix does. The primary path is Dropbox poll → S3 → `macrofactor-data-ingestion` (S3 trigger).

### Apple Health: webhook payload too large / timing out
The only Apple Health writer is `health-auto-export-webhook` (256 MB, 300 s timeout — `cdk/stacks/ingestion_stack.py`). If a sync times out, the payload is too large: lower the Health Auto Export automation's date range or sync more often (hourly, not "since last run" — see the HAE gotcha above). There is no XML-export path any more.

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

**First, isolate which transport is broken — there are two, with independent auth.** They fail
separately, and the symptom is easy to misread:

| Transport | Client | Auth | Reads |
|---|---|---|---|
| **Function URL** (remote) | claude.ai connector, mobile | OAuth 2.1 Bearer | — |
| **Bridge** (stdio) | Claude Code, Claude Desktop | `x-api-key` header | `.config.json` |

Tools working in claude.ai while Claude Code reports **"Could not attach to MCP server
life-platform"** means the bridge is broken, *not* the URL. Don't go looking for a bad endpoint.

1. Check Lambda logs:
```bash
aws logs tail /aws/lambda/life-platform-mcp --since 1h
```

2. Verify the Function URL is up. Discover it rather than pasting a literal — it changes when the
   Function URL is recreated, and stale URLs in old docs are dead, not merely unauthorized:
```bash
MCP_URL=$(aws lambda list-function-url-configs --function-name life-platform-mcp \
  --region us-west-2 --query 'FunctionUrlConfigs[0].FunctionUrl' --output text)

# Health probe: OAuth discovery is unauthenticated and must return 200.
curl -s -o /dev/null -w "%{http_code}\n" "${MCP_URL}.well-known/oauth-authorization-server"
```
   A `401 {"error": "Unauthorized: invalid Bearer token"}` on `GET /` is **correct** — that is the
   handshake trigger, not a fault. A connection error or DNS failure means a dead URL.

3. Confirm the bridge's API key matches Secrets Manager. **The key lives in gitignored
   `.config.json`, not in `mcp_bridge.py`.** Compare hashes so the secret never hits your scrollback
   or shell history:
```bash
python3 -c "import json,hashlib;print(hashlib.sha256(json.load(open('.config.json'))['api_key'].encode()).hexdigest()[:12])"
aws secretsmanager get-secret-value --secret-id life-platform/mcp-api-key --region us-west-2 \
  --query SecretString --output text | shasum -a 256 | cut -c1-12
```

4. **If the hashes differ, the 90-day rotation is the cause.** `life-platform/mcp-api-key` rotates
   automatically (`life-platform-key-rotator`, `AutomaticallyAfterDays: 90`), and nothing updates
   your local `.config.json` when it does. The bridge then writes `{"error": "Unauthorized"}` to
   stdout instead of a JSON-RPC frame, so the handshake never completes and the client reports
   "Could not attach." Meanwhile the claude.ai connector keeps working — different auth path.
   Rewrite the key, then **restart the client** (the bridge is a subprocess spawned at attach time,
   so an in-place fix does nothing until relaunch):
```bash
python3 - <<'PY'
import json, boto3
cfg = json.load(open(".config.json"))
cfg["api_key"] = boto3.client("secretsmanager", region_name=cfg.get("region", "us-west-2")) \
    .get_secret_value(SecretId="life-platform/mcp-api-key")["SecretString"].strip()
json.dump(cfg, open(".config.json", "w"), indent=2)
PY
```
   Check when it next fires, and expect this failure within a day of it:
```bash
aws secretsmanager describe-secret --secret-id life-platform/mcp-api-key --region us-west-2 \
  --query '{LastChanged:LastChangedDate,NextRotation:NextRotationDate}'
```

5. Verify the bridge end-to-end before blaming the client — this exercises config, IAM, and the
   Lambda in one shot:
```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python3 mcp_bridge.py
```
   Expect a JSON-RPC frame listing the full tool set. `{"error": "Unauthorized"}` sends you to
   step 3.

6. If the Lambda itself is broken, check for a recent deploy that may have introduced a syntax error — redeploy the last known-good version from the local `.py` file.
7. Check Lambda memory is **768 MB** — the power-tuned, cost-optimal value (R5, AWS Lambda Power
   Tuning v4.4.0), declared in `cdk/stacks/mcp_stack.py`. It is deliberately *not* higher; don't
   raise it to "fix" slowness without re-running the power tuner:
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

Monthly ceiling: **$215 all-in, enforced** (ADR-063 + ADR-133 amendment; $252 in reader-traffic surge mode; cost-governor degrades AI by tier). See `docs/COST_TRACKER.md` for the full breakdown.

Real run-rate: read it from `docs/COST_TRACKER.md` (Cost Explorer re-verified there — September 2026 closed at $137.15; the old "~$25-40/mo" figure went stale ~3x, see `docs/OPERATOR_GUIDE.md`). Bedrock is the swing factor (priced from CloudWatch token metrics); WAF deleted (~−$8/mo).

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

### Per-feature AI spend attribution (#808 · R22-COST-02)

When Bedrock is the swing factor, `bedrock_client._emit_usage_metrics()` already meters
every Claude call per-feature to `LifePlatform/AI` (`EstimatedCostUSD` + token counts,
dimensioned by `LambdaFunction`). `scripts/ai_spend_attribution.py` is the read-only
reporting surface over those metrics — it ranks features by $, back-solves each feature's
model from the emitted cost, and reconciles against the authoritative per-model totals
(`AWS/Bedrock` token metrics — the same source `cost_governor` trusts).

```bash
python3 scripts/ai_spend_attribution.py                 # current month-to-date
python3 scripts/ai_spend_attribution.py --month 2026-06 # a specific calendar month
python3 scripts/ai_spend_attribution.py --days 14       # trailing-window run-rate
python3 scripts/ai_spend_attribution.py --json          # machine-readable
```

Run it as the **drift-check** whenever an `ai-tokens-*` alarm fires or before targeting a
cost-reduction (e.g. #409 batch pricing): if a "cheap tier" (Haiku) feature has crept to
the top of the ranking, that's the batch / prompt-diet target.

Two known interpretation notes:
- **`mixed` rows** — a Lambda that called >1 model in the window (daily-brief and the coach
  pipeline blend a Sonnet narrative pass with Haiku extraction passes) can't be split by the
  per-feature EMF (it carries a `LambdaFunction` dimension but no model), so its Haiku portion
  is folded into that one row. Use the authoritative per-model footer for the true split, or a
  short `--days` window (recent Haiku-only activity back-solves cleanly). Exact per-feature
  **and** per-model $ would need a `Model` dimension on the emit — a recurring CloudWatch
  metric cost, so it's a deliberate costed follow-up, not on by default.
- **Coverage < 100%** — the self-reported per-feature total under-counts vs the authoritative
  AWS/Bedrock total (calls that don't reach the EMF chokepoint); the footer prints the ratio.
  The **ranking** (relative shares) is the deliverable, not the absolute self-reported total.

## MCP Tool Usage Telemetry

MCP tool invocations emit to CloudWatch namespace **`LifePlatform/MCP`** with metrics `ToolInvocations`, `ToolErrors`, `ToolDuration`, `AuthFailures` (`ToolName` dimension; `AuthFailures` is dimensioned `EventType=AuthFailure`).

```bash
# List which tools are emitting
aws cloudwatch list-metrics --namespace LifePlatform/MCP \
  --metric-name ToolInvocations \
  --query 'Metrics[*].Dimensions[?Name==`ToolName`].Value' --output text

# Top tools by invocation count over the last 7 days
for tool in get_daily_snapshot get_date_range find_days get_sources; do
  count=$(aws cloudwatch get-metric-statistics --namespace LifePlatform/MCP \
    --metric-name ToolInvocations --dimensions Name=ToolName,Value=$tool \
    --start-time $(date -u -v-7d +%Y-%m-%dT00:00:00Z) \
    --end-time $(date -u +%Y-%m-%dT23:59:59Z) \
    --period 604800 --statistics Sum --query 'Datapoints[0].Sum' --output text)
  echo "$tool: $count"
done
```

V2 P4.1 finding (2026-05, registry then at ~133 tools): only ~11 were invoked in 30 days. Executed as the #395 prune (143→60, 2026-07-08) — the audited removal ledger is `docs/MCP_TOOL_AUDIT.md`.

## SES Email Pipeline

The `life-platform-emails` SES configuration set tracks bounce/click/complaint/delivery/open events to CloudWatch (dimension `SesEventType`). Verify:

```bash
aws ses describe-configuration-set --configuration-set-name life-platform-emails \
  --configuration-set-attribute-names eventDestinations
```

The Lambdas that send through this config set are the ones that name it — `grep -rl life-platform-emails lambdas/` (as of 2026-10-17: `daily_brief`, `weekly_digest`, `monthly_digest`, `partner_email`, and `content/recap_deliver`). Other email Lambdas (chronicle, weekly-plate, monday-compass, nutrition-review, evening-nudge) send without the config set — V2 P3 follow-up tracks wiring them.

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

**Model assignments** — which feature runs on which model is the registry `lambdas/ai/model_routing.py` (tiers → model in `TIER_MODELS`, per-call-site `ROUTES`; strategy in `docs/AI_MODEL_STRATEGY.md`). The hand-kept Lambda→model table that used to sit here predated that registry (#4770) and is retired; read the registry, not a copy.

**Rollback a model change** (no code deploy needed): a route's historical env var (the `env` field on its `ROUTES` row — e.g. `AI_MODEL_HAIKU`) still wins over the registry default, so set it on the one function:
```bash
# Read the function's CURRENT environment first, then put back ALL of it plus the override
aws lambda get-function-configuration --function-name <function> --region us-west-2 --query Environment.Variables
aws lambda update-function-configuration --function-name <function> \
  --environment "Variables={...existing vars...,<ROUTE_ENV_VAR>=<model-id>}" --region us-west-2
```
(CDK owns the environment — the next `cdk deploy` reverts this, so it is a stopgap; the durable change is one edit in `model_routing.py`.)

**Anthropic credit balance** — check at [console.anthropic.com/settings/billing](https://console.anthropic.com/settings/billing). This only matters for the few direct-API readers of `life-platform/ai-keys` (see `docs/SECRETS_ROTATION.md`); Bedrock inference bills through AWS. A direct-API caller returns `[AI_UNAVAILABLE]` when credits are exhausted — site API now filters this to show "Check back soon" instead of raw sentinel.

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
5. **Deploy manifest:** `deploy/MANIFEST.md` is deprecated (archived #4258); see `docs/ARCHITECTURE.md` + `ci/lambda_map.json` for Lambda → handler → zip mappings
6. **Smoke test template:** Source `deploy/SMOKE_TEST_TEMPLATE.sh` for reusable test functions
7. **Wait 10 seconds** between sequential Lambda deploys

---

## Withings OAuth Re-Authorization

If the Withings refresh token expires (cascading failure from extended Lambda downtime):

```bash
cd ~/dev/life-platform
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

> **The ordered checklist is `docs/NEW_SIGNAL_PLAYBOOK.md` (ADR-154); the per-source facets are the `source_registry.py` entry.** The list below is the short operator version, re-checked against the code 2026-10-17.

### Code & Infrastructure
- [ ] **Lambda**: Write `lambdas/ingestion/<source>_lambda.py`. Use `ingestion_framework.py` base if possible (new sources should always use the framework — see ADR-019). Add graceful handling for missing secrets (return 200, not 500, before OAuth is set up).
- [ ] **CDK IAM**: Add `ingestion_<source>()` policy function in `cdk/stacks/role_policies_ingestion.py` (#2604 — `role_policies.py` is a re-export facade over per-domain siblings) with least-privilege DDB/S3/secret permissions, then add it to the facade's `from stacks.role_policies_ingestion import …` re-export
- [ ] **CDK Stack**: Wire Lambda in `cdk/stacks/ingestion_stack.py` with correct handler, schedule, and IAM
- [ ] **Secret**: Create `life-platform/<source>` in Secrets Manager (platform CMK `alias/life-platform-dynamodb` is for DynamoDB; Secrets Manager uses the AWS-managed key). Add the row to `docs/SECRETS_MAP.md`.
- [ ] **Deploy CDK**: `bash deploy/cdk_deploy.sh LifePlatformIngestion` (drift-guarded; owner-attended)
- [ ] **Deploy Lambda code**: `bash deploy/deploy_fleet.sh` (the one path, #4255 — or merge and let CI run it)

### Platform Wiring (the steps most often missed)
- [ ] **Source registry**: add the source to `lambdas/ingestion/source_registry.py` — `SOURCES` in `mcp/config.py` is DERIVED from it (`mcp_source_ids()`), not a hand list
- [ ] **Freshness checker**: `lambdas/emails/freshness_checker_lambda.py` (derives its monitored sources from the registry; its `OAUTH_SECRETS` / `MANUAL_ROTATION_SECRETS` lists are secret names — add a credentialed source there, and mirror in `remediation/agent.py`)
- [ ] **Ingestion validator**: Add source schema to `_SCHEMAS` dict in `lambdas/ingestion/ingestion_validator.py`. Update docstring count.
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
- [ ] `bash deploy/deploy_fleet.sh` (ships both MCP functions with the fleet, #4255)

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
| **New Lambda added** | ARCHITECTURE (ingest/email/compute/operational table), INFRASTRUCTURE (Lambda list), lambda_map.json, CHANGELOG (the schedule itself is read from CDK/`platform_model.json`; RUNBOOK keeps no schedule table) |
| **Lambda deleted** | Same as above — remove the row |
| **Schedule time changed** | ARCHITECTURE (EventBridge table) — times must match; RUNBOOK keeps no schedule table, only the compute-chain ordering block |
| **New secret added** | ARCHITECTURE (Secrets table + cost profile), INFRASTRUCTURE (Secrets table), DECISIONS ADR-014, COST_TRACKER — then update PLATFORM_FACTS in sync_doc_metadata.py |
| **Secret deleted** | Same docs — then update PLATFORM_FACTS |
| **New MCP tools added** | MCP_TOOL_CATALOG (new rows), ARCHITECTURE (serve layer description) — then update PLATFORM_FACTS |
| **MCP tools removed** | MCP_TOOL_CATALOG (remove rows) — then update PLATFORM_FACTS |
| **New CDK stack** | ARCHITECTURE (CDK section), INFRASTRUCTURE, cdk/app.py |
| **DynamoDB schema change** | SCHEMA.md, DATA_DICTIONARY.md |
| **New data source** | ARCHITECTURE (ingest layer), DATA_DICTIONARY (SOT table), SCHEMA.md, FEATURES.md |
| **IAM role changed** | ARCHITECTURE (IAM section), `cdk/stacks/role_policies_*.py` (RUNBOOK keeps no IAM table) |
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

The prediction evaluator is a daily scheduled Lambda (`coach-prediction-evaluator`; its cron is in `model/platform_model.json` / `cdk/stacks/compute_stack.py`).

1. Check EventBridge rule status:
```bash
aws events list-rules --name-prefix LifePlatformCompute-CoachPredictionEvaluatorSchedul --region us-west-2   # CDK-generated rule name
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

### 6. Stale shared-module code

If coach Lambdas behave as if they run old shared-module code (e.g. an `AttributeError`
on a recently-added function), some functions missed the last fleet deploy:

1. Check the layer-retirement invariant + bundle freshness:
```bash
python3 -m pytest tests/test_integration_aws.py -k i2 -v
```

2. Fleet-redeploy the one bundle:
```bash
bash deploy/deploy_fleet.sh   # or: cd cdk && npx cdk deploy --all --require-approval never
```

---

**GitHub repo:** `git@github.com:averagejoematt/life-platform.git` (SSH; the repo has been PUBLIC since 2026-07-20 — `gh repo view --json visibility`)
**Never commit:** `datadrops/`, `lambdas/dashboard/data.json`, `lambdas/dashboard/clinical.json`, `*.env`, `.config.json`

---

**Verified:** 2026-10-17 (full re-check against the code and live read-only AWS; prior stamp 2026-05-19 V2 audit operational sweep)


## Restart Pipeline

To re-anchor the experiment to a new genesis date:

```bash
# 1. Verify the Withings reading exists for the target date in DDB
#    (or pass --override-weight-lbs <w> when the genesis date has no weigh-in yet).
# 2. Run the orchestrator:
python3 deploy/restart_pipeline.py --genesis YYYY-MM-DD --dry-run
# 3. Review the report, then commit:
python3 deploy/restart_pipeline.py --genesis YYYY-MM-DD --apply
```

The pipeline runs (in order, each idempotent; **fail-fast since #918** — any sub-step exiting
nonzero aborts the run and prints what already ran; `--continue-on-error` is the escape hatch):
1. Fetch the Withings reading for the target date (or fail / use the override)
2. Write `config/user_goals.json` + `config/character_sheet.json`; with `--close-cycle`
   (default ON) append the new genesis to `CYCLE_GENESES` in `lambdas/web/site_api_data.py`
3. `sync_constants_from_config.py` — regenerates `lambdas/common/constants.py`
4. `cdk deploy --all` (#781: constants + `CYCLE_GENESES` ship in every bundle — no layer step; `--skip-deploy` if you just deployed)
5. `restart_phase_tag.py --apply` — flips DDB phase tags relative to the new genesis
6. `restart_intelligence_wipe.py --apply` — tombstones newly pre-genesis records, stamping the
   CLOSING cycle number; `--close-cycle` then bumps SSM `/life-platform/experiment-cycle` to N+1
7. `restart_ledger_reset.py --apply` — rolls the accountability ledger into `LIFETIME#`/`CYCLE_TOTALS#`, zeroes `TOTALS#current`
8. `restart_chronicle_handler.py --apply` — archives newly pre-genesis chronicle HTML; resurrects
   the `PRELAUNCH_CALENDAR` lead-ins (or explicit `--keep-chronicle` overrides)
9. `restart_media_reset.py --apply` — archives + blanks the panelcast/debrief audio feeds, resurrects the calendar's podcast prequel
10. `restart_leadin_pages.py --apply` — rebuilds the public lead-in article pages + `/journal/posts.json`
    from the resurrected chronicle records (wired into the pipeline; S3-only writes; idempotent)
11. `restart_character_rebuild.py --apply` — recomputes character sheets from new genesis
12. `restart_site_copy_sync.py --apply --old-genesis <outgoing>` — JS/JSON/HTML genesis-literal sweep + CloudFront invalidate;
    its regen-lambda step also invokes `chronicle-podcast` (#1243) so any kept prologue's read-aloud episode re-anchors to
    its new date — the article-only re-anchor in step 8/10 previously left the audio narrating the OLD genesis date, since
    neither this step nor step 9's media reset ever regenerated `generated/podcast/episodes.json` (a third podcast surface,
    distinct from panelcast/debrief). Idempotent by date-key; only renders episodes missing for the current manifest.
13. `restart_docs_update.py --apply` — doc date/copy sync
14. With `--sync-site` (opt-in, #1092): `bash deploy/sync_site_to_s3.sh` — the full-site
    content-hashed sync + rss.xml regen (deliberately NOT default: heavy + interactive;
    without the flag it stays a printed next command)
15. `restart_verify_rendered.py --old-genesis <outgoing>` — hard gate over the 98-URL v4 surface (apply mode only)
16. `restart_verify_semantic.py` — **the #1093 semantic hard gate** (apply mode only): deterministic
    assertions on what the live site SAYS pre-start (`pre_start` flags on snapshot/journey, zeroed
    character, no current-cycle findings on /api/discoveries, coach_team dispute null-or-current-cycle,
    prologue-only `/journal/posts.json`) **plus zero pre-genesis `phase=experiment` rows across every
    raw-timeseries source** — catches the ingestion-poisoning class (a warm ingestion Lambda with
    stale constants re-stamping a pre-genesis row after the tagger pass, found 2026-07-12).
    Standalone: `python3 deploy/restart_verify_semantic.py [--offline]` (`--offline` skips the
    live-site checks honestly and still runs the read-only DDB check)
17. Post-verify hooks (#1092 — the former manual Sunday-queue steps, now inside the one command;
    skipped loudly if a verify gate failed — they run on the next successful re-run):
    - `fix_prologue_cycle_and_subscribe_ttl.py` — **default ON** (reads the SSM cycle, so it must
      follow the step-6 bump; `--skip-prologue-fix` to skip)
    - `seed_genesis_preregistration.py` — opt-in `--with-preregistration` (re-lands the frozen #976
      pre-registration after the wipe; #1378 — a fresh freeze is SHA-256-stamped at freeze time
      (`deploy/generated/genesis_preregistration.sha256.json`) and any re-land of an existing freeze
      is verified against its stamp first — a hash mismatch aborts before any DDB write)
    - `dedup_source_records.py --source <name>` — one pass per `--dedup-source <name>` (repeatable):
      deletes raw-timeseries duplicate `DATE#` rows (the eightsleep UTC-rollover class — same
      session written under two dates; keeps the earlier date, requires a session-timestamp anchor
      so gap-filled `no_data` rows can never group)
18. `--close-cycle`: appends one line to `docs/restart/RESET_LOG.md` (the human-readable reset ledger)

**Two reset reflexes the steps above do not spell out.** (1) **Check the archive before
regenerating anything.** A tombstoned record carries an `archived_to` pointer
(`deploy/restart_chronicle_handler.py`, `deploy/restart_media_reset.py` and
`deploy/curate_prelaunch_leadins.py` all write it); the original asset is usually still there,
and resurrecting it is cheaper and more honest than regenerating a new one under an old date.
(2) **When only the rendered gate (step 15) fails on a small-gap reset, the semantic gate
(step 16) is authoritative.** The rendered gate scans public surfaces for the *outgoing*
genesis literal; move genesis by only a few days and that literal collides with dates that
are legitimately correct in the new cycle (a last-complete-data `as_of_date`, a genesis−2
prequel episode). Read the rendered-gate report it writes under `docs/restart/`, `curl` each
flagged URL, and if the literal is a real new-cycle date, record the false positive in the
reset log and proceed — do **not** run `deploy/restart_rollback.py`. The apply still exits
nonzero, which also skips the post-verify hooks; run
`deploy/fix_prologue_cycle_and_subscribe_ttl.py` standalone afterward (idempotent).

**The one-command contract (#1092):** everything above is one `restart_pipeline.py --apply`
invocation. The ONLY steps that deliberately stay outside it (each a verified exclusion, not
an omission):
- `publish_genesis_preregistration.py` — a permanent PUBLIC AI artifact; stays **attended**
  under the prereg/frozen-artifact dry-run-review posture (review the dry-run output, then
  `--apply`). The pipeline prints it as a labeled next step. The published page prints the
  freeze's SHA-256 seal (#1378), so it requires a valid stamp and aborts on a hash mismatch.
- `genesis_prereg_stamp.py --apply` (#1378) — uploads the frozen pre-registration **verbatim** +
  its stamp to the public `/experiments/prereg/genesis-{genesis}.json` route (#728 CloudFront
  behavior, no infra change). Readers verify with
  `curl -s https://averagejoematt.com/experiments/prereg/genesis-<genesis>.json | shasum -a 256`.
  Immutable post-publish: it refuses to overwrite a published artifact with different bytes, and
  `tests/test_prereg_hash_stamp.py` reds CI if the committed frozen file ever stops matching its
  committed stamp. Stamps are never backdated — when a stamp postdates its freeze, both moments
  are recorded and the public seal states both.
- Genesis-eve engagement: `send_prereg_lock_email.py --apply` stays **attended** (the one
  "predictions lock tonight" subscriber email — refuses to send on any Pacific date but genesis eve).
  `build_genesis_predict_week.py --apply` is **no longer attended** — since #2612 it runs as
  post-verify hook (d) of `restart_pipeline.py` (`--skip-predict-week-seed` to opt out). Step 2d of
  the same pipeline deletes `site/config/current_challenge.json` on every `--apply` and nothing else
  ever rewrites it, so leaving the re-seed to an operator left the cockpit's predict-the-week widget
  dark for the whole genesis week of cycle 11 (#1952, wrong `week_id`) and again of cycle 13 (#2612,
  never seeded). Subjects derive from the frozen hypotheses' own test_specs and are hash-stamped for
  provenance; `week_id` is the **genesis** ISO week, derived from the genesis date and never the
  wall clock (#1952). It is safe to run before or during that week — the #1198 guard serves it only
  while it is the current Pacific ISO week.
  - **Weekly re-seeds are no longer a step at all** (#2622). The artifact is read as a per-CYCLE
    one: `site_api_social._predict_subject_state` stamps the CURRENT Pacific ISO week onto the
    stored subjects, so the week rolls over on the reader's Monday with nothing running. There is
    deliberately **no EventBridge seeder** — a cron must be UTC-fixed while the boundary is Pacific
    midnight (07:00Z in PDT, 08:00Z in PST), and picking either hour reproduces cycle 11's
    wrong-week failure for half the year. The #1198 guard is unweakened: the served `week_id` is
    the current week by construction, a challenge stamped **before the live genesis week** (what a
    reset leaves behind) is refused rather than rolled, and a measured `result` is never carried
    into a week it does not describe. Seed once per cycle — which hook (d) already does.
  - When there is genuinely no subject, `/api/predict_week` returns `active:false` **plus a named
    `state` and reader-facing `note`**, and the cockpit prints it. A dark week is a statement now,
    not a blank — the nightly qa-smoke `predict_week:freshness` check still escalates it.
- `deploy/restart_verify.py` — the **post-genesis Monday** health check (asserts `day_n >= 1`,
  a genesis weigh-in, a post-genesis character sheet); folding it would structurally fail at
  reset time. Run it Monday morning. Check 16 (#2104) covers the **slow-regen narrative
  class**: the coaching door regenerates on its own weekly-ish cadence, so on cycle 12's
  genesis the physical coach ran at 17:38Z — before the Day-1 weigh-in ingested at 04:05Z the
  next morning — and published the previous cycle's figure as the current weight while the
  cockpit served the new baseline. If it fails, the repair is a targeted regen once the Day-1
  weigh-in is in DynamoDB: `aws lambda invoke --function-name ai-expert-analyzer --payload
  '{"expert":"physical"}' /dev/stdout` (any coach domain; `"all"` re-runs the board). The data
  seam that makes the *next* card honest is `intelligence/weight_recency.py`, which now filters
  weigh-ins to the current cycle — a pre-genesis reading is withheld from the fact set entirely
  rather than dated, so the grounded-generation allow-list catches a coach that cites it.
  Check 20 (#3511) is the **pre-registration provenance** leg: check 15 proves a seal was
  PUBLISHED, check 20 proves the live `PREDICTION#` ledger AGREES with it — no unsealed row
  presenting as pre-genesis (written at/before PT-midnight of genesis, or dated before it),
  and from genesis onward no sealed id missing from the season. The same pure predicate
  (`deploy/prereg_provenance_gate.py`) also gates `genesis_prereg_stamp.py --apply`, so a
  seal cannot publish over a ledger it contradicts. Repair: `deploy/reconcile_prereg_season_3511.py`
  (dry-run default) re-stamps sealed rows an evening-before seed left on the closing cycle.
- `deploy/restart_integration_check.py` (#1559) — the **behavioral** leg: where
  `restart_verify.py` proves STATE, this proves the pipelines still FLOW. Four legs: ingestion
  (every `source_registry.py` source really invokes — the same bounded gap-aware runs the crons
  make; paused/event-driven sources SKIP with the registry-derived reason), compute (healthchecks
  + honest Day-0 shapes: Level-1 character baseline, replay-verified-or-honestly-absent receipts,
  fulfillment `insufficient_signal` semantics), serving (the full qa_manifest smoke surface + the
  daily-brief real dry-run + the static present-None gate over `lambdas/emails/`), ops (DLQ 0,
  alarms vs a stated allowlist, EventBridge crons armed, SSM cycle). Run it right after `--apply`
  (`--expect-cycle <N>` `--brief-full`), and again post-genesis with `--deep --synthetic` (force-recompute shape
  asserts + the tagged 2099-dated HAE webhook round-trip with verified DDB cleanup — the
  delete-protected `raw/` residue it leaves is printed honestly). Dry-running it with no flags
  against the LIVE current cycle proves the harness itself — drill step 4 below. The genesis-week
  present-None class (`reference_genesis_week_present_none`) is enforced between resets by its
  standing CI gate in `tests/test_restart_integration_check.py`.
- The git commit of regenerated files (constants, configs, `CYCLE_GENESES`, `RESET_LOG.md`) — from MAIN.

**Resume gotcha (`--old-genesis`):** the orchestrator snapshots the outgoing genesis from
`lambdas/common/constants.py` BEFORE regenerating it — but a **resumed** run (e.g. re-running with
`--skip-deploy` after an abort) snapshots AFTER constants were already regenerated, so
old = new and the literal sweep + verifier silently no-op. When resuming, pass the prior
genesis explicitly: `python3 deploy/restart_site_copy_sync.py --apply --old-genesis <prior genesis>`
(and the same flag to `restart_verify_rendered.py`).

**Pre-start countdown window (#931/#939):** a reset may stage a FUTURE genesis (the cycle-5
pattern: reset Friday, genesis Sunday). While `EXPERIMENT_START_DATE` > today (PT), the
journey/snapshot/pulse API payloads carry `pre_start: true`, `days_until_start`, and
`start_date`, baseline-dependent claims are nulled, and the site renders its countdown state —
`deploy/smoke_test_site.sh` and the site-deploy gates accept this window. **Expected alarm:**
the coherence sentinel's `check_experiment_continuity` treats genesis > today as week-underflow
and ALARMs for the entire pre-start window — this is expected, not an incident (the remediation
agent should classify it as such); bounded pre-start grace is tracked as issue #942. Everything
is inert again (`pre_start: false`, no payload change) once genesis ≤ today.

**Pre-reset drill (REQUIRED before any future re-anchor — #1094, first run 2026-07-12):**
prove the machinery green end-to-end BEFORE the real run. Four commands, all safe against prod:

```bash
# 1. Dry-run the full folded pipeline against the intended (or a synthetic) genesis —
#    every step previews, nothing mutates; reports land in docs/restart/_*.txt
python3 deploy/restart_pipeline.py --genesis YYYY-MM-DD --override-weight-lbs <current>

# 2. The deterministic truth gate, standalone (7 assertion groups; #1093)
python3 deploy/restart_verify_semantic.py

# 3. The AI reader-truth gate, standalone (#1097; skips loudly at budget tier 3 —
#    for a full run: tier-0 override, run, restore the honest tier)
python3 deploy/restart_verify_truth.py

# 4. The behavioral harness against the LIVE current cycle (#1559) — probe-mode invokes are
#    the same ones the crons make hourly; a true-positive FAIL here (e.g. a dark device past
#    its own staleness line) is the harness working, not the drill failing
python3 deploy/restart_integration_check.py
```

Drill record 2026-07-12 (genesis day, synthetic genesis 2026-08-02): dry-run previewed all
steps + folded hooks clean; semantic verify **7/7 PASS** (0 poisoned rows across 29 sources);
reader-truth gate ran full and **correctly FAILED with a real HIGH** — the home waveform's
static "every day, including the ones that dipped" claim over a 1-dot chart — fixed as
PR #1156/#1159, plus the cockpit week/month scope caps (same class, PR #1160); re-run
confirmed the home finding cleared. Known benign residue the gate reports on Day 1:
static-extraction placeholders ("··" pre-JS shells) read as med-severity — the rendered
page binds real values; judge against the live rendered page before treating as real.
Outputs captured in `docs/restart/_verify_semantic_report.txt` + `_verify_truth_report.txt`.

All steps preserve original data (interpretation B for DDB, archive-not-delete for S3).
Roll back via `deploy/restart_rollback.py` — removes tombstone flags (DDB) or copies back from `*/archive/pilot/` (S3).

See ADR-058/077 in `docs/DECISIONS.md` for the design rationale.

## Budget Guardrails (ADR-063)

The monthly AWS budget — **$215 base** (ADR-133 amendment 2026-08-28, #2801; was $75, then $85, then $150), floating to **$252 in reader-traffic surge mode** (ADR-133) — is enforced by a two-component system. For August 2026 only, a dated `_TEMP_CEILING_WINDOW` raised that pair to $200/$235; it auto-reverts 2026-09-01 with no deploy or manual step.

- **`life-platform-cost-governor`** Lambda (every 8h — `cron(0 0/8 * * ? *)`, `cdk/stacks/operational_stack.py`) — projects month-end spend, writes tier 0–3 to SSM `/life-platform/budget-tier`.
- **`lambdas/ai/budget_guard.py`** (bundled module, #781) — calling code uses `allow(feature)` to gate AI by tier.

**Tier behavior** (priority: protect daily brief longest):

| Tier | Projected (vs effective ceiling) | What pauses (audience-ordered, ADR-125) |
|---|---|---|
| 0 | <73% of ceiling ($157.67 at the $215 base) | nothing — all AI runs normally |
| 1 | 73–87% | internal/dev AI — ensemble, chronicle editor, coherence-semantic |
| 2 | 87–97% | + reader narratives — coach commentary, State of Matthew, chronicle |
| 3 | ≥97% ($209.27 at the $215 base) | hard cutoff — website AI returns "paused" JSON; `bedrock_client.invoke()` raises `BudgetExceeded`; daily brief skips AI |

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

Triage agent runs ~10:35 PT on Mon/Wed/Fri (cron `35 17 * * 1,3,5` — after the 16:20Z AI canary, #3499) via `.github/workflows/remediation-agent.yml`, plus on-demand urgent dispatch. Proposes the safe class and the rest as PRs a human merges, emails what needs the operator. Replaces the raw `[LP digest]` noise. **Shadow permanently** (#2833, ADR-129 amendment 2026-08-30) — it merges nothing.

**Mode kill-switch (SSM `/life-platform/remediation-mode`):**

| Value | Behavior |
|---|---|
| `off` | workflow no-ops immediately |
| `shadow` | diagnoses + opens PRs + emails; a human merges every PR (the only live running mode) |
| `auto` | **retired 2026-08-30 (#2833)** — not honoured: `agent.py::gate()` runs as `shadow` and adds a needs-human line telling you to reset the parameter |

**Check mode:**
```bash
aws ssm get-parameter --name /life-platform/remediation-mode --region us-west-2 \
  --query Parameter.Value --output text
```

**Switch mode (panic-off, or back to shadow):**
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
- `remediation-log/automerge/` — the retired auto-merge gate's decision prefix (ADR-065; 0 objects ever written). Kept as history; nothing writes it since #2833.

**Budget Tier-3 pauses remediation automatically** — the agent's `gate()` reads `/life-platform/budget-tier` and skips the run if ≥ 3.

**Classifier rubric:** `docs/REMEDIATION_TAXONOMY.md` (A=auto-fix-safe, B=fix-via-pr, C=needs-human, D=stale).

**Nothing merges.** The agent opens PRs labeled `auto-fix-safe` (template-shaped, low-risk) or `needs-review`; a human merges both. The deterministic auto-merge gate (`remediation/automerge.py`, a separate workflow step that merged only in `auto`) was retired 2026-08-30 with the mode (#2833) — `gh pr merge` stays in the agent's `disallowed_tools` and the workflow has no merge step. `ci-cd.yml`'s production approval gate is untouched; a PR touching `cdk/` still needs an operator `cdk deploy` after merge.

## QA Depth Dial (#1452)

One knob — SSM `/life-platform/qa-level` — trades QA depth against spend/Actions
minutes without editing workflows under pressure (the `/life-platform/remediation-mode`
kill-switch shape).

| Value | Standalone daily visual-qa.yml | Weekly WebKit run | Cost posture |
|---|---|---|---|
| `full` | full-surface AI-vision on EVERY fire (+ reader-truth) | runs | max depth — watching something closely |
| `standard` (default) | deterministic + reader-truth daily; full AI-vision Sunday/manual (#1428) | runs | today's normal |
| `lean` | deterministic sweep only — AI-vision + reader-truth stripped ($0 Bedrock). **Since #3251 (2026-08-30, C1) this strips the platform's ONLY CI prose truth-check** — the deploy copies no longer carry `--reader-truth`; measured saving ~$8.3/mo (6 × $0.195 daily fires + $0.74 Sunday) | skipped | cost pressure |
| `off` | sweep + accuracy gate skipped entirely | skipped | standalone QA dark — emergency only |

**Structural exemption:** the deploy-gating QA copies (`ci-cd.yml` / `site-deploy.yml`
visual-qa jobs, the PR gates `v4-gate.yml` / `surface-drift.yml`) NEVER read the dial —
the deploy gate cannot be disabled by it (`tests/test_qa_level_dial.py` enforces).

**Fail-open:** an unreadable/unset/invalid param is `standard` — each workflow states
the fail-open in its run log; it is never a silent default. The dial state also rides
the Monday weekly green report (E3, `traffic_digest_lambda`) — `lean` renders warn,
`off` renders loud/bad. The `/qa` skill reports the dial at the start of every mode,
and `python3 scripts/qa_audit.py --live` (#1450) reads it too.

**Check / set:**
```bash
aws ssm get-parameter --name /life-platform/qa-level --region us-west-2 \
  --query Parameter.Value --output text
aws ssm put-parameter --name /life-platform/qa-level --value standard \
  --type String --overwrite --region us-west-2   # full | standard | lean | off
```

**IAM:** the traffic-digest Lambda's read is CDK-owned (`role_policies.py`,
`OpsDialParamRead`). The workflows read via `github-actions-diagnosis-role` (manual,
non-IaC — DEVOPS-02 deferred); until that role carries `ssm:GetParameter` on the
param, workflow reads fail open to `standard` (logged).

## Urgent-Alarm Dispatcher (fast path, ADR-064)

`life-platform-remediation-dispatcher` Lambda is subscribed to the `life-platform-alerts` SNS topic. On each fire it:
1. Filters to urgent alarms (substring match on `_DEFAULT_PATTERNS` in `lambdas/operational/remediation_dispatcher_lambda.py` — currently `slo-`, `budget-tier`, `ai-daily-spend`, `ai-tokens-platform`, `ingest-consecutive-failures`, `ingest-auth-unhealthy`, `ddb-throttled`, `dlq`, `alert-digest`, `daily-brief-errors`, `daily-brief-no-invocations`; read the file, it changes). Routine ingestion-source errors stay non-urgent — the Mon/Wed/Fri ~10:35 PT sweep handles them.
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

The fine-grained PAT in `life-platform/github-dispatch-token` (GitHub name `life-platform-dispatcher`) has two consumers: the remediation dispatcher (urgent alarm → `repository_dispatch`) and qa-smoke's closure-probe leg (#4022, closes `closure:live-proof` issues on observed proof).

**Current token: regenerated 2026-09-23, expires 2027-09-23** (owner's 1-year choice). **Incident, 2026-09-23:** the previous token had expired unnoticed. The closure-probe leg's first armed run got `HTTP 401`, and the urgent-alarm fast path had been dark for the same window. A 401 means expired or bad credentials; a missing scope returns 403. Before the expiry, regenerate it (GitHub → the token → **Regenerate token**) and store it with the silent-read recipe below.

**Setup or rotation:**
1. Open https://github.com/settings/personal-access-tokens → **Generate new token (fine-grained)**.
2. Settings: name `life-platform-dispatcher`, repository access **Only `averagejoematt/life-platform`**, permissions **Contents: Read and write** (the dispatcher) and **Issues: Read and write** (the #4022 closure probe). Metadata: Read-only is granted automatically.
3. Generate, copy. Then:
   ```bash
   # First time:
   aws secretsmanager create-secret \
     --name life-platform/github-dispatch-token \
     --secret-string 'PASTE_TOKEN_HERE' \
     --region us-west-2

   # Rotation (subsequent times) — silent read, so the token never lands in shell history or a
   # chat transcript. Two one-line steps; check the length (~93) before writing:
   read -rs "T?Paste token: "; echo; echo "length: ${#T}"
   aws secretsmanager put-secret-value --secret-id life-platform/github-dispatch-token --region us-west-2 --secret-string "$T" --query VersionId --output text; unset T
   ```
   Verify without printing it: a GET of `/repos/averagejoematt/life-platform/issues` with the secret returns 200. The response's `github-authentication-token-expiration` header names the new expiry.
4. No Lambda redeploy needed — the dispatcher re-reads the secret on each cold start.
5. Old PAT can be left to expire naturally OR deleted at github.com/settings/personal-access-tokens.

**If the PAT is missing or expired**, urgent alarms still email you via the existing SNS subscriptions (no degradation); the dispatcher logs `SecretNotFound` or `GitHub HTTP 401` and the Mon/Wed/Fri ~10:35 PT sweep still covers the signal — just without the urgent fast path.

### Vendor transient in the canary gate: the standing watch (#3830)

#3830 (closed 2026-09-24 on its 26 seam tests plus the mutation proof, by owner ruling) made a Bedrock `ServiceUnavailableException` / `ThrottlingException` / timeout in the canary's gating lane NON-gating. It is still alarmed and named in the CI log. An `AccessDeniedException` still gates. Its one unobserved property is a REAL vendor transient passing through a deploy. When one happens, check that:
- the Smoke job's log shows `::warning::Canary: 1 external-transient failure(s) — NOT gating this deploy`;
- the Smoke job concluded `success`, with no auto-rollback.

Grep: `aws logs filter-log-events --log-group-name /aws/lambda/life-platform-canary --filter-pattern '"failed_external_transient"'`. If instead it gated or rolled back, reopen #3830 with that run.

---

## Advisory Scheduled Workflows — auto-filed failure issues (#1447)

The three advisory scheduled workflows — **Visual QA (standalone)** (`visual-qa.yml`, daily),
**Golden-brief eval** (`golden-brief-eval.yml`, weekly Mon), **Fresh-Eyes Discovery**
(`fresh-eyes.yml`, weekly Sun) — gate nothing, so before #1447 a red run just sat in the
Actions history (the silent-failure class from the 2026-07-11 ~26h-unnoticed incident,
`docs/INCIDENT_LOG.md`). Each now ends with the shared composite action
`.github/actions/advisory-failure-issue` (`if: always()`), backed by
`scripts/advisory_failure_issue.py` (stdlib-only; dedup logic offline-tested in
`tests/test_advisory_failure_issue.py`):

- **On failure** it files a GitHub issue labeled `auto-filed` + `area:infra` with an
  ADR-099-shaped body (what failed, run link, first-failure timestamp) — **one open issue
  per workflow**: a repeat failure comments the new run link on the existing open issue
  instead of filing a duplicate. Dedup key = an HTML-comment marker
  (`<!-- advisory-failure: <slug> -->`) in the issue body, stable across title edits.
- **On recovery (close policy):** the next green run of the *same* workflow — scheduled or
  `workflow_dispatch` — comments the recovery run link and **auto-closes** the issue. You
  can also close it by hand after fixing (e.g. to tidy up before the next cron fire), but
  closing without fixing just means the next failure files a fresh issue.
- A filing failure in file mode reds the (already-red) step visibly; in recover mode it
  only warns — a filing hiccup never reds a green advisory run.

Adding a new advisory scheduled workflow? Append the same composite-action step with a new
stable `workflow-slug` (never rename a slug once issues exist) and grant `issues: write`
in that workflow's `permissions` block.

---

## Hevy Routine Write-Loop Operations (ADR-066)

The Hevy routine write-loop ships with two layers of safety gates. Operator actions documented here are configuration-only; no code redeploy is required to flip any gate.

### Pre-deploy provisioning (one-time, blocks first deploy)

Before the first `cdk deploy` of OperationalStack / McpStack for the Hevy write loop (one-time; both secrets and all three SSM gates already exist live as of 2026-10-17):

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

# 4. Sync static configs to S3. The repo copy of all four is the authority, so pushing
#    it is a publish: three are hand-owned, and movement_catalog.json is repo-generated by
#    deploy/build_movement_catalog.py (#4108 — rebuild it there, never hand-grow it). A merge
#    that touches config/** also publishes them through site-deploy's config-twin step.
aws s3 cp config/training_landmarks.json s3://matthew-life-platform/config/
aws s3 cp config/movement_catalog.json   s3://matthew-life-platform/config/
aws s3 cp config/training_week.json      s3://matthew-life-platform/config/
aws s3 cp config/board_of_directors.json s3://matthew-life-platform/config/
```

> **NEVER run `aws s3 cp` on a GENERATED `config/` object** (#3785). For those the repo
> copy is a stale ARTIFACT, not the authority, and pushing it is a silent revert. On
> 2026-09-14 one such push replaced the live `config/hevy_template_index.json` (820
> templates, rebuilt at 13:40Z) with a June-1 copy of 789 — `draft_custom` lost 39
> templates and the daily **Config twin drift** workflow stayed green for nine runs,
> because while the clobber was active both sides read 789 and agreed.
>
> **The push was not a hand command.** Measured 2026-09-17 against the run log: all three
> clobbers (09-14 16:43Z, 09-14 18:13Z, 09-15 17:47Z) landed ~1m35s after a `site-deploy`
> run started, and run `35003307196`'s own log reads `🔴 DRIFT
> config/hevy_template_index.json` / `uploaded: 2` at 17:47:57.9Z against an S3 version
> written at 17:47:58Z. The writer was the sanctioned deploy path — site-deploy's
> `config_twin_sync.py --apply --strict` step — which had the generated index in its
> derived twin set. The stale repo twin is deleted and the ownership registry now holds
> every generated key out of that set, so the same command cannot repeat it.
>
> **Which files may NOT be pushed is a ruling, not a memory** — ask the registry, because
> a list written into this runbook would drift silently:
>
> ```bash
> python3 deploy/config_ownership_audit.py           # every config/ subject: class + upload=yes/NO
> python3 deploy/config_ownership_audit.py --strict  # …and exit 1 on a stale twin or an unruled file
> ```
>
> Today it prints `runtime_generated` / upload=**NO** for `config/hevy_template_index.json`
> and `config/hevy_template_cache.json`, and `hand_owned` or `repo_generated` /
> upload=yes for everything else — including the four files in the block above. A subject
> nobody has ruled is **not** uploadable: the registry fails closed.
>
> A generated object is repaired by **re-running its producer**, never by uploading the
> repo copy. `deploy/config_provenance_audit.py` is the standing check: it grades the live
> object's own `_built_at` against the clock, so it sees the revert within a day even
> though a comparison against the committed twin cannot.

### Post-deploy verification

```bash
# Shared layer retired (#781) — the invariant is that no Layer is attached:
aws lambda get-function-configuration --function-name hevy-routine-cron \
  --query 'Layers[*].Arn' --output text   # → empty

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

### Nightly pre-draft plan source — the v0.4 revert (#5080)

The nightly pre-draft (`mcp/nightly_predraft.py`, 02:00Z on `life-platform-mcp-warmer`) persists ONE plan per night. Which one is SSM `/life-platform/training-plan-source` (`v04 | charter`), read with a 60-s cache. **The parameter's absence means `charter`** (`mcp/predraft_shadow.py` `DEFAULT_SOURCE`), and so does a missing `ssm:GetParameter` grant or any read error — the run names the reason under `plan_source`.

```bash
# Revert to the frozen v0.4 plan (training/program_v04.build_session) from the next nightly run:
aws ssm put-parameter --name /life-platform/training-plan-source --value v04 --type String --overwrite
# Back to the charter engine:
aws ssm put-parameter --name /life-platform/training-plan-source --value charter --type String --overwrite
# What it reads now:
aws ssm get-parameter --name /life-platform/training-plan-source --query Parameter.Value --output text --cli-read-timeout 60
```

The parameter is deliberately NOT CDK-owned — a stack deploy would re-assert a synth value and undo a revert. The flip takes effect on the next run (a warm container may hold the previous answer for up to 60 s). It changes only the nightly pre-draft; a draft built in chat is unaffected, and nothing is committed to Hevy either way. For the first five nights the run also builds the other plan and writes an owner-only side-by-side at `USER#matthew#SOURCE#training_constraints / SHADOW#<date>` (`docs/SCHEMA.md`); the run's log line carries the one-line `shadow.summary`.

What a revert does and does not change (read before flipping to `v04`):

- **The days are still the charter's.** The run asks the charter's schedule (`scheduled_session`) whether tomorrow is a lifting day and returns `no_session` when it is not, so under `v04` the v0.4 sessions are drafted on the charter's five lifting days, not v0.4's four-day `program_v04.NOMINAL_WEEK`. The v0.4 ROLE is v0.4's own order (`v04_role` over the loaded sessions since the block start), and the draft's marker carries that role (`seam: program_v04.build_session`). The owner-routine skip and the partition check still compare against the charter's served session; a v0.4 draft that would version over a routine he authored is refused by `_mark_draft`'s backstop, by name.
- **No scheduled deload, under a revert too.** v0.4's calendar deload (from 2026-11-04, −40 % sets) is never applied — owner ruling 2 of 2026-10-18 (#5070) outranks v0.4. The plan reports it as `deload.would_have_deloaded` (and the shadow summary says "v0.4 would have deloaded — not applied"); sets are cut only when his recorded DELOAD# word (`get_exercise_notes action='deload'`) covers the day, exactly as on the charter path.

### Public-site copy reminder

Never describe this feature as "autoregulated" on averagejoematt.com or in the chronicle while the readiness signal is unvalidated. Correct phrasing: **deterministic volume-landmark programming with red-day deload guard.**

---

## Per-Exercise Notes — Current Operations (ADR-068)

> The one-time ADR-067/068/088 deploy records that used to sit here (pre-#781 layer
> commands) are archived at `archive/RUNBOOK_DEPLOY_RECORDS_2026-06.md`. What follows
> is the CURRENT config-only operations guidance.

### Flipping the notes mode

```bash
# Edit config/training_week.json:exercise_notes_mode (one_best_line | show_both | off)
aws s3 cp config/training_week.json s3://matthew-life-platform/config/ --region us-west-2
# Force MCP cold start as above.
```

### Disabling per-exercise notes entirely

Set `exercise_notes_mode = "off"`. The generator skips the DDB exercise-history load (verified by `test_exercise_notes_off_mode_yields_empty_notes`); per-exercise notes ship as empty strings. No code redeploy needed.
