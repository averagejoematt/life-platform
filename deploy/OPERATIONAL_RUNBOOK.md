# Operational Runbook — `deploy/`

Symptom-keyed index of what to run when. **If the symptom isn't listed here, escalate to `docs/RUNBOOK.md` first — that's the architectural runbook. This one is the deploy-script index.**

Per ADR-059, multi-step state-mutating operations go through `restart_pipeline.py` — not via direct sub-script invocation.

---

## Daily / scheduled — leave alone

These run on EventBridge / launchd / cron. **You don't manually invoke these.**

| Lambda / job | Cadence | What it does | When to worry |
|---|---|---|---|
| `daily-brief` | 11:00 AM PT daily | Generates Day-N email | If you didn't receive yesterday's brief by 11:30 AM |
| `wednesday-chronicle` | Wed 8:00 AM PT | Elena's weekly chronicle | If subscriber complaints arrive Wed afternoon |
| Daily ingestion (whoop/withings/garmin/…) | Hourly | Pulls source data | If `find_days` returns 0 records for today after 11 AM |
| `life-platform-canary` | Every 15 min | Probes MCP, DDB, S3, Anthropic, subscribe flow | CloudWatch alarms fire if any check fails twice in a row |
| `freshness-checker` | 9:45 AM PT daily | Alerts on stale sources | Daily summary email |
| `qa-smoke` | 10:30 AM PT daily | End-to-end smoke check | Daily summary email shows N failures |

---

## "Something looks wrong on the public site"

### Symptom: Site shows stale dates / weight / level / character / etc.

**Likely cause:** CloudFront cache OR a Lambda still has a warm container with stale profile.

```bash
# 1. First, verify backend state is correct
python3 deploy/restart_verify.py            # 12-check backend probe
python3 deploy/restart_verify_rendered.py   # 27-page rendered probe

# 2. If verify_rendered fails: the public surface is stale.
#    Force CloudFront full invalidation:
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths '/*'

# 3. If verify still fails after invalidation, the JSON behind site-api is stale.
#    Re-invoke the regen Lambdas:
aws lambda invoke --function-name daily-brief --invocation-type RequestResponse \
    --payload '{}' --cli-binary-format raw-in-base64-out --region us-west-2 /tmp/db.json
aws lambda invoke --function-name character-sheet-compute --invocation-type RequestResponse \
    --payload '{"force":true}' --cli-binary-format raw-in-base64-out --region us-west-2 /tmp/cs.json

# 4. If site-api itself has stale in-memory profile cache, force a cold start:
aws lambda update-function-configuration --function-name life-platform-site-api \
    --environment 'Variables={USER_ID=matthew,TABLE_NAME=life-platform,...,RESTART_CACHE_BUST='"$(date +%s)"'}' \
    --region us-west-2
```

### Symptom: 27/27 pages clean but `/api/journey` returns wrong start_date or weight

**Likely cause:** DDB `USER#matthew PROFILE#v1` record is stale.

```bash
# Inspect:
aws dynamodb get-item --table-name life-platform --region us-west-2 \
    --key '{"pk":{"S":"USER#matthew"},"sk":{"S":"PROFILE#v1"}}' \
    --query 'Item.[journey_start_date,journey_start_weight_lbs]' --output text

# Fix (only if you understand WHY it's wrong — usually means re-running the pipeline):
python3 deploy/restart_pipeline.py --genesis YYYY-MM-DD --apply
```

---

## "I want to re-anchor the experiment to a new date"

**Use `restart_pipeline.py` — never call sub-scripts directly.**

```bash
# Dry-run first (every sub-script defaults to dry-run anyway):
python3 deploy/restart_pipeline.py --genesis 2026-06-XX --dry-run

# Review the report at docs/restart/_pipeline_report.txt
# Then commit:
python3 deploy/restart_pipeline.py --genesis 2026-06-XX --apply
```

The pipeline runs (in order, each idempotent):

1. Fetch Withings reading for the target date (fails clearly if absent)
2. `sync_constants_from_config.py` — regenerate `lambdas/constants.py`
3. `update_ddb_profile()` — sync `USER#matthew PROFILE#v1`
4. Bump `SHARED_LAYER_VERSION`, `bash deploy/build_layer.sh`, `cdk deploy --all`
5. `restart_phase_tag.py --apply`
6. `restart_intelligence_wipe.py --apply`
7. `restart_character_rebuild.py --apply`
8. `restart_chronicle_handler.py --apply`
9. `restart_site_copy_sync.py --apply` — JS sweep + orphan tombstones + regen Lambdas
10. `restart_docs_update.py --apply`
11. `bust_lambda_warm_cache()` — force cold starts on read-path Lambdas
12. `restart_verify_rendered.py` — hard gate

ETA: ~10-15 min. Idempotent — safe to re-run if interrupted.

### Emergency rollback

```bash
python3 deploy/restart_rollback.py --to-genesis YYYY-MM-DD --apply   # back to previous date
# OR
python3 deploy/restart_rollback.py --full-unwind --apply             # nuke ALL phase tags + tombstones
```

---

## "A single Lambda needs to be redeployed (not full CDK)"

```bash
# Auto-detects handler name, packages from local lambdas/, uploads.
# Source-of-truth for individual Lambda code redeploys.
bash deploy/deploy_lambda.sh <function-name> lambdas/<source>.py

# Multi-module Lambdas (e.g., daily-brief depends on ai_calls + html_builder + …):
bash deploy/deploy_lambda.sh daily-brief lambdas/daily_brief_lambda.py \
    --extra-files lambdas/ai_calls.py lambdas/html_builder.py lambdas/output_writers.py lambdas/board_loader.py

# Rollback to previous zip:
bash deploy/rollback_lambda.sh <function-name>
```

For the MCP Lambda (`life-platform-mcp`), `deploy_lambda.sh` will refuse — it requires the full `mcp/` package. Use the MCP-specific bash sequence printed by the refusal message.

---

## "The shared Lambda layer needs to be updated"

```bash
# 1. Bump SHARED_LAYER_VERSION in cdk/stacks/constants.py
# 2. Rebuild the layer:
bash deploy/build_layer.sh
# 3. Deploy:
cd cdk && npx cdk deploy --all --require-approval never
```

Test `tests/test_layer_version_consistency.py` enforces consistency between the constant and the AWS-published version.

---

## "The DLQ has messages — what do I do?"

```bash
# 1. Inspect (one message, no remove):
aws sqs receive-message --queue-url https://sqs.us-west-2.amazonaws.com/205930651321/life-platform-ingestion-dlq \
    --region us-west-2 --max-number-of-messages 1 --visibility-timeout 1 \
    --query 'Messages[0].Body' --output text

# 2. If they're stale scheduled-event records (Lambda failed to process its cron),
#    investigate the Lambda's logs to fix the root cause. Then purge:
aws sqs purge-queue --queue-url https://sqs.us-west-2.amazonaws.com/205930651321/life-platform-ingestion-dlq \
    --region us-west-2

# 3. Force the DLQ alarm OK:
aws cloudwatch set-alarm-state --alarm-name life-platform-dlq-depth-warning --region us-west-2 \
    --state-value OK --state-reason "drained <YYYY-MM-DD>"
```

---

## "Subscriber emails aren't going out"

```bash
# 1. Check that the subscriber canary is passing:
aws lambda invoke --function-name life-platform-canary --invocation-type RequestResponse \
    --payload '{}' --cli-binary-format raw-in-base64-out --region us-west-2 /tmp/c.json
cat /tmp/c.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(json.loads(d['body']) if isinstance(d['body'],str) else d['body'], indent=2))"

# 2. Look for "subscribe flow OK" or specific error in the canary output

# 3. If the canary subscribe check fails: read the canary CloudWatch log,
#    then read /aws/lambda/life-platform-subscribe and /aws/lambda/email-subscriber

# 4. Verify SES is healthy:
aws sesv2 get-account --region us-west-2 --query 'SendingEnabled'
aws sesv2 get-account --region us-west-2 --query 'EnforcementStatus'
```

---

## "Inbox is too noisy — alarm spam"

See `docs/RUNBOOK.md` section "Inbox noise mitigations". Briefly:
- `dash-total-errors`: threshold 25%, requires 3×5min sustained. Should fire ≤1/day.
- `canary-anthropic-failure`: requires 2 consecutive failures (10 min). OK action removed.
- DLQ alarms: only fire when queue > 0. Purge + state OK.

---

## "Pre-launch sanity check before re-anchoring genesis"

```bash
# Order matters
python3 -m pytest tests/ -q --tb=no                          # all unit + integration
python3 deploy/restart_verify.py                             # 12-check backend probe
python3 deploy/restart_verify_rendered.py                    # 27-page public probe
# Expect: 1232+ tests passing, 12/12, 27/27
```

---

## What lives in `deploy/`

- **`restart_pipeline.py`** — THE orchestrator. Use this for any multi-step state change.
- **`restart_*.py`** (8 of them) — sub-scripts called by the pipeline. Each supports `--dry-run` and `--apply`. Direct invocation only for surgical fixes.
- **`restart_verify.py`** — 12-check backend health probe.
- **`restart_verify_rendered.py`** — 27-page public-surface token-grep gate.
- **`restart_rollback.py`** — Insurance. Two modes: `--to-genesis YYYY-MM-DD` (back to previous date) or `--full-unwind` (drop all phase tags + tombstones).
- **`restart_pivot_when_ready.py`** — Watchdog. Polls DDB for the genesis-day Withings reading, runs the pipeline when it lands. Used by launchd.
- **`sync_constants_from_config.py`** — Regenerates `lambdas/constants.py` from `config/user_goals.json`.
- **`deploy_lambda.sh`** — Single-Lambda surgical redeploy. Source-of-truth for hot fixes.
- **`rollback_lambda.sh`** — Inverse of above.
- **`build_layer.sh`** — Rebuilds the shared Lambda layer directory.
- **`deploy_and_verify.sh`** — `deploy_lambda.sh` + smoke test combo.
- **`safe_sync.sh`** — S3 sync wrapper that's guaranteed not to `--delete` bucket root (ADR-032/033).
- **`sync_doc_metadata.py`** — Updates PLATFORM_FACTS dict in docs from CDK source-of-truth.
- **`archive/`** — One-off scripts older than 30 days.

Everything else in `deploy/` is either a helper for the above or an in-flight script that should be archived once its purpose is complete.
