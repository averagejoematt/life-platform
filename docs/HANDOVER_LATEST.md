# Handover — v3.3.0 — 2026-03-09

## What was done this session

### PROD-1 CDK — Handler bug fix + garth layer + import prep tooling

#### Context: current CDK stack states (verified from CHANGELOG)

| Stack | Status |
|-------|--------|
| `LifePlatformCore` | Not imported (exists outside CDK) |
| `LifePlatformIngestion` | Synth ✅ — **import PENDING** |
| `LifePlatformCompute` | **Already imported** (v3.2.10) — handler bug now FIXED |
| `LifePlatformEmail` | **Already imported** (v3.2.10) — handler bug now FIXED |

#### 1. Critical handler bug fixed in compute_stack.py and email_stack.py

All 15 Lambda definitions in ComputeStack and EmailStack had `handler="lambda_function.lambda_handler"` — a placeholder that was **already present in CloudFormation** after the v3.2.10 import. Without this fix, the next `cdk deploy` on either stack would have changed every Lambda's handler string in AWS to `lambda_function.lambda_handler`, breaking all 14 Lambdas.

Fixed all handlers to use the correct `{module_name}.lambda_handler` convention:

**compute_stack.py (7 Lambdas fixed):**
| Lambda | Corrected Handler |
|--------|---------|
| anomaly-detector | `anomaly_detector_lambda.lambda_handler` |
| character-sheet-compute | `character_sheet_lambda.lambda_handler` |
| daily-metrics-compute | `daily_metrics_compute_lambda.lambda_handler` |
| daily-insight-compute | `daily_insight_compute_lambda.lambda_handler` |
| adaptive-mode-compute | `adaptive_mode_lambda.lambda_handler` |
| hypothesis-engine | `hypothesis_engine_lambda.lambda_handler` |
| dashboard-refresh | `dashboard_refresh_lambda.lambda_handler` |

**email_stack.py (7 Lambdas fixed, weekly-digest unchanged):**
| Lambda | Corrected Handler |
|--------|---------|
| daily-brief | `daily_brief_lambda.lambda_handler` |
| monthly-digest | `monthly_digest_lambda.lambda_handler` |
| nutrition-review | `nutrition_review_lambda.lambda_handler` |
| wednesday-chronicle | `wednesday_chronicle_lambda.lambda_handler` |
| weekly-plate | `weekly_plate_lambda.lambda_handler` |
| monday-compass | `monday_compass_lambda.lambda_handler` |
| brittany-weekly-email | `brittany_email_lambda.lambda_handler` |
| weekly-digest | `digest_handler.lambda_handler` ← already correct, preserved |

#### 2. Garth layer support added (ingestion_stack.py + lambda_helpers.py)

- Added `GARTH_LAYER_ARN` constant to `ingestion_stack.py` (placeholder ARN with UPDATE comment)
- Wired `garth_layer` as `additional_layers=[garth_layer]` on the GarminIngestion Lambda
- Added `additional_layers: list = None` parameter to `create_platform_lambda()` in `lambda_helpers.py`
- `layers=` now merges `shared_layer` + `additional_layers` cleanly

#### 3. New script: deploy/prepare_cdk_import.sh

Comprehensive pre-flight script for `cdk import LifePlatformIngestion`:
```bash
bash deploy/prepare_cdk_import.sh
```

Script does:
1. **Garth layer lookup** — queries AWS, patches `GARTH_LAYER_ARN` in ingestion_stack.py automatically
2. **Handler verification** — compares all 30 Lambda handlers in AWS vs CDK expected; flags mismatches
3. **IAM role spot-check** — verifies pre-SEC-1 Lambdas against CDK ROLE_ARNS dicts
4. **EventBridge rule names** — queries and prints for use during cdk import prompts
5. **cdk synth** — runs synth on all 3 stacks as final validation
6. **Import sequence reminder**

---

## Immediate next steps

### Step 1 — Deploy compute + email to reconcile handler fix (URGENT)

ComputeStack and EmailStack are already imported — the handler fix needs to be pushed:

```bash
cd ~/Documents/Claude/life-platform/cdk
source .venv/bin/activate

# First verify synth passes with new handlers
npx cdk synth LifePlatformCompute LifePlatformEmail

# Then deploy to push corrected handlers to CloudFormation
# (This changes CloudFormation metadata only — handler string reconciliation.
#  No code is redeployed; existing Lambda code packages are not touched.)
npx cdk deploy LifePlatformCompute LifePlatformEmail --require-approval never
```

⚠️ **After deploy, verify actual Lambda handlers in AWS are unchanged:**
```bash
for fn in anomaly-detector character-sheet-compute daily-metrics-compute \
    daily-insight-compute adaptive-mode-compute hypothesis-engine dashboard-refresh \
    daily-brief weekly-digest monthly-digest nutrition-review wednesday-chronicle \
    weekly-plate monday-compass; do
  echo "$fn: $(aws lambda get-function-configuration --function-name $fn --query Handler --output text)"
done
```

If any handler changed to `lambda_function.lambda_handler` → immediate hotfix: set it back via the AWS console or `aws lambda update-function-configuration --handler <correct_handler>`.

### Step 2 — Ingestion stack import prep

```bash
cd ~/Documents/Claude/life-platform
bash deploy/prepare_cdk_import.sh
```

Fixes GARTH_LAYER_ARN automatically. Review any handler/role mismatches it reports.

### Step 3 — Import LifePlatformIngestion

```bash
cd ~/Documents/Claude/life-platform/cdk
source .venv/bin/activate
npx cdk import LifePlatformIngestion
```

CDK will prompt for physical IDs — use rule names from step 2 output.

### Step 4 — Drift detection

```bash
for stack in LifePlatformIngestion LifePlatformCompute LifePlatformEmail; do
  echo "Triggering drift detection for $stack..."
  aws cloudformation detect-stack-drift --stack-name $stack
done
```

### Step 5 — Remaining PROD-1 stacks (sessions 4–6)

- `operational_stack.py` (freshness-checker, dlq-consumer, canary, pip-audit, qa-smoke, key-rotator, data-export, data-reconciliation)
- `mcp_stack.py` (life-platform-mcp + Function URL)
- `monitoring_stack.py` (35 alarms)
- `web_stack.py` (3 CloudFront distributions)

### Alternative: Brittany weekly email (fully unblocked)

---

## Files changed this session

| File | Change |
|------|--------|
| `cdk/stacks/compute_stack.py` | Rewrote — fixed all 7 handler names |
| `cdk/stacks/email_stack.py` | Rewrote — fixed all 7 handler names (digest_handler preserved) |
| `cdk/stacks/ingestion_stack.py` | Added GARTH_LAYER_ARN constant + garth_layer + additional_layers wiring |
| `cdk/stacks/lambda_helpers.py` | Added `additional_layers` parameter to `create_platform_lambda()` |
| `deploy/prepare_cdk_import.sh` | New — pre-flight import prep script |

---

## Platform state

**Version:** v3.3.0

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
| PROD-1 | ⚠️ Compute + Email imported; handler bug fixed (deploy needed); Ingestion import pending; 4 stacks remaining |
| PROD-2 | ✅ |
| SIMP-1 | 🔴 Revisit ~2026-04-08 |
