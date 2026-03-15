# Deploy Scripts — Reference Guide

> Scripts in this directory are **run locally in Terminal**, never via Claude MCP tools.
> Last updated: 2026-03-15 (v3.7.30)

---

## The Golden Rule

**Run scripts from the project root**, not from inside `deploy/`:

```bash
# Correct
cd ~/Documents/Claude/life-platform
bash deploy/deploy_lambda.sh daily-brief

# Wrong — relative paths will break
cd deploy
bash deploy_lambda.sh daily-brief
```

---

## Active Scripts (20)

### Core deployment

| Script | Purpose | When to use |
|--------|---------|-------------|
| `deploy_lambda.sh <name>` | Zip + upload a single Lambda | Any code change to a Lambda |
| `deploy_and_verify.sh <name>` | Deploy + smoke test + auto-rollback | Preferred for production deploys |
| `rollback_lambda.sh <name>` | Restore previous Lambda version | After a bad deploy |
| `build_layer.sh` | Build the shared-utils Lambda layer | After adding a new shared module |
| `build_mcp_stable_layer.sh` | Build the MCP stable-core layer (ADR-027) | Apr 13 — SIMP-1 Phase 2 |

### Testing & verification

| Script | Purpose | When to use |
|--------|---------|-------------|
| `SMOKE_TEST_TEMPLATE.sh` | Template for Lambda smoke tests | Copy and adapt per Lambda |
| `post_cdk_smoke.sh` | Full smoke test after CDK deploy | After `cdk deploy --all` |
| `post_cdk_reconcile_smoke.sh` | Reconcile CDK state vs live AWS | After large CDK changes |
| `smoke_test_cloudfront.sh` | Verify CloudFront distributions | After web stack changes |

### Infrastructure setup (run once)

| Script | Purpose | When to use |
|--------|---------|-------------|
| `create_withings_oauth_alarm.sh` | Withings 2-day consecutive error alarm | Run once — alarm persists |
| `create_compute_staleness_alarm.sh` | Daily compute pipeline staleness alarm | Run once — alarm persists |
| `create_lambda_edge_alarm.sh` | Lambda@Edge error alarm (us-east-1) | Run once — alarm persists |
| `create_operational_dashboard.sh` | CloudWatch ops dashboard | Run once — dashboard persists |
| `apply_s3_lifecycle.sh` | S3 lifecycle rules (raw data expiry) | Run once or after bucket changes |

### Operations

| Script | Purpose | When to use |
|--------|---------|-------------|
| `maintenance_mode.sh enable\|disable\|status` | Pause non-essential Lambdas | Vacation / extended absence |
| `pitr_restore_drill.sh` | DynamoDB PITR restore test | Quarterly disaster recovery drill |
| `archive_onetime_scripts.sh` | Move completed one-time scripts to archive/ | Post-session hygiene |

### Documentation & review

| Script | Purpose | When to use |
|--------|---------|-------------|
| `generate_review_bundle.py` | Generate files for architecture review | Before each review session |
| `sync_doc_metadata.py` | Sync ARCHITECTURE.md resource counts | After adding Lambdas/alarms/tools |

---

## Deploying a Lambda (step by step)

The standard flow for any code change:

```bash
# 1. Edit the source file in lambdas/ or mcp/
# 2. Deploy
bash deploy/deploy_and_verify.sh <function-name>

# If deploy_and_verify isn't suitable (e.g. MCP Lambda which needs special zip):
bash deploy/deploy_lambda.sh life-platform-mcp

# 3. Check logs
# AWS Console → Lambda → <function> → Monitor → View CloudWatch Logs
```

### MCP Lambda — special zip procedure

The MCP Lambda requires bundling the entire `mcp/` package:

```bash
# From project root:
cd ..
zip -r life-platform/mcp_server.zip \
  life-platform/mcp_server.py \
  life-platform/mcp/ \
  -x "*.pyc" -x "*/__pycache__/*"
cd life-platform
bash deploy/deploy_lambda.sh life-platform-mcp
```

### Garmin Lambda — native deps

Garmin requires platform-specific dependencies. Always build on Linux-compatible targets:

```bash
pip install \
  --platform manylinux2014_x86_64 \
  --only-binary=:all: \
  --python-version 3.12 \
  --implementation cp \
  --target ./garmin_pkg \
  garth garminconnect
```

Never install Garmin deps on macOS and zip — they'll silently fail in Lambda.

---

## CDK Deploys

CDK manages all infrastructure. Run from the `cdk/` directory:

```bash
cd ~/Documents/Claude/life-platform/cdk

# Preview what will change
npx cdk diff LifePlatformEmail

# Deploy one stack
npx cdk deploy LifePlatformEmail

# Deploy all stacks (takes 5–10 min)
npx cdk deploy --all

# After CDK deploy — run smoke tests
cd ..
bash deploy/post_cdk_smoke.sh
```

**Stack names and what they own:**

| Stack | Lambdas / Resources |
|-------|-------------------|
| `LifePlatformCore` | DLQ, SNS alerts topic, shared layer |
| `LifePlatformIngestion` | 13 ingestion Lambdas + EventBridge rules |
| `LifePlatformCompute` | 5 compute Lambdas + EventBridge rules |
| `LifePlatformEmail` | 8 email/digest Lambdas + EventBridge rules |
| `LifePlatformOperational` | 8 operational Lambdas + EventBridge rules |
| `LifePlatformMcp` | MCP Lambda + Function URL + warmer rule |
| `LifePlatformMonitoring` | All CloudWatch alarms |
| `LifePlatformWeb` | CloudFront distributions + S3 policies |

IAM policies live in `cdk/stacks/role_policies.py` — one function per Lambda.

---

## Alarm Scripts

These create-once scripts are idempotent — safe to re-run. Running them twice just updates the alarm in place:

```bash
bash deploy/create_withings_oauth_alarm.sh     # R18/R55
bash deploy/create_compute_staleness_alarm.sh  # Risk-7
bash deploy/create_lambda_edge_alarm.sh        # Lambda@Edge (us-east-1)
```

The operational dashboard:
```bash
bash deploy/create_operational_dashboard.sh
# Creates 'life-platform-ops' dashboard in CloudWatch
# https://us-west-2.console.aws.amazon.com/cloudwatch/home#dashboards
```

---

## Maintenance Mode

Pause non-essential Lambdas for vacations or extended absences:

```bash
bash deploy/maintenance_mode.sh enable   # disable non-essential rules
bash deploy/maintenance_mode.sh status   # show which rules are enabled/disabled
bash deploy/maintenance_mode.sh disable  # re-enable everything
```

Essential Lambdas (always stay on): ingestion (data keeps flowing), freshness checker, canary.
Paused: daily brief, weekly/monthly digests, chronicle, anomaly detector.

---

## Archive Policy

The `archive/` directory holds one-time scripts that have been run and are no longer needed. Do not delete them — they serve as a record of what was done and when.

To move completed one-time scripts to archive:
```bash
bash deploy/archive_onetime_scripts.sh
```

---

## MANIFEST.md

`deploy/MANIFEST.md` is the Lambda inventory — handler names, IAM roles, deps, and critical deploy notes. **Update it every time a Lambda is added or its handler changes.** It's the source of truth for "what handler does this Lambda use?" and "which zipping procedure does it need?"
