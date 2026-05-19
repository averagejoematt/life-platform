# Deployment Guide

**Last updated:** 2026-05-19 (v8.0.0)

> How to safely change anything in production. If you're new, also read `docs/QUICKSTART.md` first.

---

## Deployment surfaces

There are 4 categories of change. Each has its own deploy procedure.

| What you changed | Deploy path | Risk |
|---|---|---|
| Single Lambda source code (e.g. `lambdas/daily_brief_lambda.py`) | `bash deploy/deploy_lambda.sh <function-name> <source-file>` | Low |
| Shared layer module (e.g. `lambdas/ai_calls.py`) | Layer rebuild + bump CDK constant + redeploy consumers | Medium |
| Infrastructure (CDK — new Lambda, schedule, IAM, alarm) | `cd cdk && npx cdk deploy <StackName>` | Medium-High |
| Static site (`site/**.html`, CSS, etc.) | `aws s3 sync site/ s3://matthew-life-platform/site/ --delete` + CF invalidate | Low |

---

## Single Lambda deploy

```bash
# Simple case — single source file
bash deploy/deploy_lambda.sh daily-brief lambdas/daily_brief_lambda.py

# Multi-module case — bundle extra files
bash deploy/deploy_lambda.sh daily-brief lambdas/daily_brief_lambda.py \
    --extra-files lambdas/ai_calls.py lambdas/html_builder.py

# MCP is special — must use full mcp/ package, NOT deploy_lambda.sh
ZIP=/tmp/mcp_deploy.zip; rm -f $ZIP
zip -j $ZIP mcp_server.py mcp_bridge.py
zip -r $ZIP mcp/ -x 'mcp/__pycache__/*'
aws lambda update-function-code --function-name life-platform-mcp --zip-file fileb://$ZIP --region us-west-2
```

**What `deploy_lambda.sh` does:**
1. Queries the live Handler config from AWS (e.g. `daily_brief_lambda.lambda_handler`)
2. Packages the source file with the EXACT module name AWS expects (catches filename mismatch bugs)
3. Saves the prior `latest.zip` → `previous.zip` in S3 (`s3://matthew-life-platform/deploys/<fn>/`) for rollback
4. Uploads new code via `aws lambda update-function-code`
5. Prints success + new `LastModified` timestamp

**Verify a deploy worked:**
```bash
aws lambda get-function-configuration --function-name daily-brief \
    --region us-west-2 --query '[LastModified,CodeSize]' --output text
```

---

## Rollback a single Lambda

```bash
bash deploy/rollback_lambda.sh <function-name>
```

This copies `s3://.../deploys/<fn>/previous.zip` → `latest.zip` and re-uploads to Lambda. Fast (~5s).

If you need an older version, the S3 versioned bucket may have older zips:
```bash
aws s3api list-object-versions --bucket matthew-life-platform \
    --prefix deploys/<fn>/latest.zip --region us-west-2
```

---

## Shared layer deploy

Triggered when you edit any file in `cdk/stacks/constants.py` MODULES list:
`ai_calls.py, retry_utils.py, board_loader.py, output_writers.py, scoring_engine.py, secret_cache.py, site_writer.py, character_engine.py, intelligence_common.py, auth_breaker.py, compute_metadata.py, http_retry.py, numeric.py, platform_logger.py, rate_limiter.py, request_validator.py, ingestion_framework.py, ingestion_validator.py, item_size_guard.py, digest_utils.py, sick_day_checker.py, ai_output_validator.py, html_builder.py, insight_writer.py`.

**Procedure:**
```bash
# 1. Rebuild the layer dir
bash deploy/build_layer.sh

# 2. Publish a new layer version to AWS
cd cdk/layer-build && zip -r /tmp/shared_layer.zip python/
NEW=$(aws lambda publish-layer-version \
    --layer-name life-platform-shared-utils \
    --zip-file fileb:///tmp/shared_layer.zip \
    --compatible-runtimes python3.12 \
    --description "what you changed" \
    --region us-west-2 \
    --query 'Version' --output text)
echo "Published v$NEW"

# 3. Bump CDK constant (one-line change)
sed -i '' "s/SHARED_LAYER_VERSION = [0-9]*/SHARED_LAYER_VERSION = $NEW/" \
    cdk/stacks/constants.py

# 4. Verify LV6 test passes (guards against this drift)
python3 -m pytest tests/test_layer_version_consistency.py -v

# 5. Two paths to update consumers:
#    Path A (safest, per-Lambda): bump only the affected consumer
aws lambda update-function-configuration --function-name daily-brief \
    --layers arn:aws:lambda:us-west-2:205930651321:layer:life-platform-shared-utils:$NEW \
    --region us-west-2

#    Path B (all consumers, requires deploy): CDK deploy
cd cdk && npx cdk deploy LifePlatformCore
```

**The trap:** Bumping the layer in AWS without bumping `SHARED_LAYER_VERSION` constant means the next `cdk deploy` regresses consumers. The LV6 test catches this.

---

## CDK deploy

For infra changes — new Lambdas, schedules, IAM, alarms, etc.

```bash
cd cdk

# Preview what will change
npx cdk diff <StackName>

# Deploy single stack (preferred — smaller blast radius)
npx cdk deploy LifePlatformIngestion
npx cdk deploy LifePlatformCore
npx cdk deploy LifePlatformEmail
npx cdk deploy LifePlatformCompute
npx cdk deploy LifePlatformMcp
npx cdk deploy LifePlatformOperational
npx cdk deploy LifePlatformWeb
npx cdk deploy LifePlatformMonitoring

# Deploy all (rare — full sync)
npx cdk deploy --all
```

**Before any `cdk deploy`:**
1. `bash deploy/build_layer.sh` if layer code changed
2. `python3 -m pytest tests/test_layer_version_consistency.py` — confirms LV6 passes (no drift)
3. `npx cdk diff` — read the change preview carefully

**After:**
1. Check Lambda functions transitioned to `Active`: `aws lambda get-function-configuration --function-name <fn> --query LastUpdateStatus`
2. Smoke-test any affected Lambda
3. Watch CloudWatch alarms for the next 30 min

---

## Static site deploy

For `site/**.html`, CSS, JS, images:

```bash
# Sync site/ (HTML + CSS) to S3, deleting orphans
aws s3 sync site/ s3://matthew-life-platform/site/ --delete --region us-west-2

# Invalidate CloudFront cache (any changed paths)
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE \
    --paths "/*" --region us-west-2
```

**Safety (ADR-046):**
- Never run `aws s3 sync` against the bucket root — only against `site/` prefix
- Generated files (public_stats.json, OG images, journal posts) live in `generated/` prefix; CloudFront routes them to S3GeneratedOrigin
- Bucket policy blocks `DeleteObject` on `raw/*`, `config/*`, `uploads/*`, `generated/*` for the `matthew-admin` role

---

## GitHub Actions CI/CD

Defined in `.github/workflows/ci-cd.yml`.

**Triggered on:** push to `main` touching `lambdas/**`, `mcp/**`, or `mcp_server.py`.

**Stages:**
1. **Lint + syntax** (flake8 strict `--select=E9,F63,F7,F82` + `python -m py_compile`)
2. **Tests** (`python -m pytest tests/ -v`)
3. **Plan** (validates `ci/lambda_map.json`; computes diff vs deployed)
4. **Deploy** (manual approval gate via GitHub Environment: `production`)
5. **Smoke test** (invokes `qa-smoke` Lambda)
6. **Auto-rollback** if smoke test fails

**Auth:** OIDC federation (no long-lived AWS keys).

**Concurrency:** `concurrency: group: main, cancel-in-progress: false` — prevents racing deploys; in-flight deploy completes.

---

## Emergency rollback procedures

### Just deployed a bad Lambda, daily-brief is failing

```bash
bash deploy/rollback_lambda.sh daily-brief
# Verify
aws logs tail /aws/lambda/daily-brief --since 5m --region us-west-2
```

### Deployed bad CDK infra, multiple things broke

```bash
cd cdk
# Get the last good commit
git log --oneline -10
git checkout <last-good-sha>
npx cdk deploy --all
# When healthy:
git checkout main  # don't lose your in-progress code
```

### Pushed bad commit but haven't deployed yet (CI hasn't finished)

GitHub Environments approval gate is your friend — just don't approve the deploy. Then push a fix and approve THAT.

### S3 site/ broken

```bash
# Restore from versioned bucket (S3 versioning enabled on matthew-life-platform)
aws s3api list-object-versions --bucket matthew-life-platform \
    --prefix site/<broken-path>.html --region us-west-2

# Copy specific version back
aws s3api copy-object \
    --copy-source "matthew-life-platform/site/<path>?versionId=<id>" \
    --bucket matthew-life-platform --key "site/<path>" --region us-west-2

# Invalidate
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE \
    --paths "/<path>" --region us-west-2
```

---

## Pre-deploy checklist

Before pushing/merging:
- [ ] `python3 -m pytest tests/ -m 'not integration' -v` — unit tests pass
- [ ] `flake8 lambdas/ mcp/ --select=E9,F63,F7,F82` — no syntax/name errors
- [ ] If touching a shared layer module: did you bump the constant?
- [ ] If touching IAM: did you read the policy carefully?
- [ ] If touching an EventBridge schedule: is the new cron correct UTC (no DST drift)?
- [ ] If deleting code: search for callers first (`grep -rln <name> lambdas/ mcp/ cdk/`)
- [ ] If renaming a Lambda file: update `ci/lambda_map.json` AND CDK source AND the AWS Handler config

---

## Disaster scenarios

See `docs/DISASTER_RECOVERY.md` for:
- Full-region outage response
- Account compromise response
- Mass data loss (DDB / S3) recovery
- Anthropic API outage degradation

---

**Verified:** 2026-05-19
