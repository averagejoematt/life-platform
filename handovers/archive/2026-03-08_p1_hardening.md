# Life Platform — Handover: P1 Security & Reliability Hardening
**Date:** 2026-03-08  
**Version:** v2.93.0  
**Session:** P1 items P1.4–P1.10 (all complete)

---

## What Was Done

### P1.8 + P1.9 — Exponential Backoff + Token Metrics (`ai_calls.py` + `retry_utils.py`)

**New file:** `lambdas/retry_utils.py` — single source of truth for Anthropic API calls across all Lambdas.

- **P1.8:** 4-attempt exponential backoff (delays: 5s / 15s / 45s) replacing fixed 2-attempt/5s retry
- **P1.9:** Token usage emitted to CloudWatch namespace `LifePlatform/AI`, dimension `LambdaFunction`
  - Metrics: `AnthropicInputTokens`, `AnthropicOutputTokens`, `AnthropicAPIFailure`
- All 7 AI Lambdas updated to delegate to `retry_utils`:
  - `ai_calls.py` → `call_anthropic()` now uses `retry_utils`
  - `weekly_digest_lambda.py`, `monthly_digest_lambda.py` → `call_anthropic_with_retry()` delegates to `retry_utils.call_anthropic_raw()`
  - `monday_compass_lambda.py`, `nutrition_review_lambda.py`, `wednesday_chronicle_lambda.py`, `weekly_plate_lambda.py` → `call_anthropic()` delegates to `retry_utils.call_anthropic_api()`
- All hardcoded `"claude-sonnet-4-5-20250929"` model strings replaced with `os.environ.get("AI_MODEL", ...)`
- CloudWatch IAM permission added to all 3 scoped roles (namespace-scoped to `LifePlatform/AI`)
- `retry_utils.py` bundled into all 7 Lambda zips

**Deploy scripts:**
- `deploy/p1_add_cloudwatch_metrics_permission.sh`
- `deploy/p1_deploy_ai_calls.sh`

**Verify:** CloudWatch > Metrics > LifePlatform/AI > LambdaFunction (appears after next Daily Brief at 10 AM)

---

### P1.7 — Invocation-Count Alarms (Silent Failure Detection)

8 CloudWatch alarms created — fire when a Lambda has 0 invocations in its expected window:

| Alarm | Lambda | Window |
|-------|--------|--------|
| `life-platform-daily-brief-invocations` | daily-brief | 26h |
| `life-platform-anomaly-detector-invocations` | anomaly-detector | 26h |
| `life-platform-character-sheet-compute-invocations` | character-sheet-compute | 26h |
| `life-platform-daily-metrics-compute-invocations` | daily-metrics-compute | 26h |
| `life-platform-daily-insight-compute-invocations` | daily-insight-compute | 26h |
| `life-platform-life-platform-freshness-checker-invocations` | freshness-checker | 26h |
| `life-platform-weekly-digest-invocations` | weekly-digest | 7d |
| `life-platform-hypothesis-engine-invocations` | hypothesis-engine | 7d |

All route to `life-platform-alerts` SNS. `TreatMissingData=breaching` — silence = alarm.  
Note: Will show `INSUFFICIENT_DATA` until the first invocation window passes.

**Deploy script:** `deploy/p1_invocation_alarms.sh`

---

### P1.10 — DynamoDB Item Size Alerting (Strava + MacroFactor)

Both ingestion Lambdas already had log-only size checks. Now they also emit CloudWatch metrics:

- Namespace: `LifePlatform/Ingestion`, metric: `DynamoDBItemSizeKB`, dimension: `Source` (strava / macrofactor)
- Alarm: `life-platform-ddb-item-size-warning` — fires when any item ≥ 300KB (DDB limit is 400KB)
- IAM: `cloudwatch:PutMetricData` added to `lambda-strava-role` + macrofactor role (auto-discovered)

**Deploy script:** `deploy/p1_deploy_item_size_alerting.sh`

---

### P1.4 — MCP Function URL Auth (DEFERRED — already adequate)

MCP URL is called by Claude.ai (external, no AWS IAM credentials). `AWS_IAM` AuthType would break all MCP tool calls. HMAC Bearer token with 90-day auto-rotation is the correct auth mechanism. **No action needed.**

---

### P1.5 — KMS CMK for DynamoDB Encryption

- Created KMS Customer Managed Key: `alias/life-platform-dynamodb`
- Annual automatic key rotation enabled
- Key policy: root admin + all Lambda execution roles + DynamoDB service principal
- `life-platform` DynamoDB table SSE updated from AWS-owned key → CMK
- Zero downtime — transparent to all application code
- Every Decrypt/GenerateDataKey call now logged in CloudTrail

**Deploy script:** `deploy/p1_kms_dynamodb.sh`

---

### P1.6 — EventBridge Rules → EventBridge Scheduler (DST-safe)

**The big one.** All 27 Lambda schedules migrated from UTC-fixed EventBridge Rules to EventBridge Scheduler with `America/Los_Angeles` timezone. DST transitions now handled automatically — no more `deploy_dst_spring/fall.sh` scripts.

**New infrastructure:**
- IAM role: `life-platform-scheduler-role` (trust: `scheduler.amazonaws.com` with `aws:SourceAccount` condition)
- Scheduler group: `life-platform`
- 27 schedules created, all `ENABLED`

**Old EventBridge rules:** disabled (not deleted). Rollback:
```bash
aws events enable-rule --name <rule-name> --region us-west-2
# Then delete the corresponding scheduler schedule
aws scheduler delete-schedule --group-name life-platform --name <name>
```

**monthly-digest guard:** Lambda now checks `today.weekday() == 0` (Monday) at handler entry — fires on 1st of month but skips if not Monday, preserving "1st Monday" semantics.

**Deploy scripts:**
- `deploy/p1_migrate_eventbridge_scheduler.py` (Python — JSON-safe)
- `deploy/p1_fix_scheduler_role_and_migrate.sh`

---

## Files Changed

| File | Change |
|------|--------|
| `lambdas/retry_utils.py` | **NEW** — shared Anthropic retry + CloudWatch metrics |
| `lambdas/ai_calls.py` | `call_anthropic()` delegates to retry_utils; `boto3` import added |
| `lambdas/weekly_digest_lambda.py` | `call_anthropic_with_retry()` → retry_utils; model → env var |
| `lambdas/monthly_digest_lambda.py` | Same + Monday guard in handler + model → env var |
| `lambdas/nutrition_review_lambda.py` | `call_anthropic()` → retry_utils |
| `lambdas/wednesday_chronicle_lambda.py` | `call_anthropic()` → retry_utils |
| `lambdas/weekly_plate_lambda.py` | `call_anthropic()` → retry_utils |
| `lambdas/monday_compass_lambda.py` | `call_anthropic()` → retry_utils |
| `lambdas/strava_lambda.py` | CloudWatch metric emit on item size check |
| `lambdas/macrofactor_lambda.py` | CloudWatch metric emit on item size check |
| `deploy/p1_add_cloudwatch_metrics_permission.sh` | IAM: PutMetricData on AI roles |
| `deploy/p1_deploy_ai_calls.sh` | Deploy all AI Lambdas with retry_utils bundled |
| `deploy/p1_invocation_alarms.sh` | 8 CW alarms for silent Lambda failure |
| `deploy/p1_deploy_item_size_alerting.sh` | Deploy strava + macrofactor + CW alarm |
| `deploy/p1_kms_dynamodb.sh` | KMS CMK creation + DDB SSE update |
| `deploy/p1_migrate_eventbridge_scheduler.py` | EventBridge → Scheduler migration (Python) |
| `deploy/p1_migrate_eventbridge_scheduler.sh` | Shell version (superseded by .py) |

---

## Platform State After This Session

- **Version:** v2.93.0
- **Security posture:** P0 complete (prior session) + P1 complete (this session)
- **Alarms:** 35 existing + 8 invocation + 1 item size = **44 total**
- **Scheduling:** All 27 Lambdas on EventBridge Scheduler (America/Los_Angeles, DST-safe)
- **Token tracking:** Live in CloudWatch after next Daily Brief

---

## Pending — 48h Cleanup (from P0 session, still outstanding)

Run Monday after confirming clean sends:
```bash
# Strip anthropic_api_key from bundle secret
aws secretsmanager get-secret-value --secret-id life-platform/api-keys \
  --query SecretString --output text | \
  python3 -c "import sys,json; d=json.load(sys.stdin); d.pop('anthropic_api_key',None); print(json.dumps(d))" | \
  xargs -I{} aws secretsmanager put-secret-value \
  --secret-id life-platform/api-keys --secret-string {}

# Delete old shared role
aws iam delete-role-policy --role-name lambda-weekly-digest-role --policy-name weekly-digest-access
aws iam detach-role-policy --role-name lambda-weekly-digest-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam delete-role --role-name lambda-weekly-digest-role
```

---

## Next Up

1. **Monday Compass first real run** — Mon 2026-03-09 8:00 AM PT. Check `/aws/lambda/monday-compass` CloudWatch logs.
2. **Token metrics verification** — After Daily Brief today (10 AM): CloudWatch > Metrics > LifePlatform/AI
3. **P2 items** or **next feature build** (Google Calendar is North Star #2)
