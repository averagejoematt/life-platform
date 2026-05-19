# Quickstart — First Day Commands

> Action sequence for a new engineer on day 1: auth, run tests, deploy a single Lambda, verify daily-brief output, roll back if needed.
> For mental model + concepts, see `docs/ONBOARDING.md`. For full operations, see `docs/RUNBOOK.md`.
> Last updated: 2026-05-19 (v8.0.0)

---

## System Requirements

| Tool | Version | Verify |
|------|---------|--------|
| Python | 3.12 (not 3.13 — Lambda runtime is 3.12) | `python3 --version` |
| Node.js | 18+ (CDK requirement) | `node --version` |
| AWS CLI | 2.x | `aws --version` |
| npm | Bundled with Node | `npm --version` |

CDK is installed via `cdk/requirements.txt` (Python package), not as a global npm package.

---

## 1. Authenticate to AWS

The platform runs in AWS account `205930651321`, region `us-west-2` (Oregon).

```bash
# Configure credentials (ask Matthew for access key + secret key)
aws configure
# AWS Access Key ID: <from Matthew>
# AWS Secret Access Key: <from Matthew>
# Default region: us-west-2
# Default output format: json

# Verify
aws sts get-caller-identity
# Should show: Account: 205930651321, Arn: ...matthew-admin...
```

The IAM user is `matthew-admin`. CI/CD uses OIDC federation (no long-lived keys in GitHub).

### Clone + install Python deps

```bash
cd ~/Documents/Claude/life-platform
python3 -m venv .venv
source .venv/bin/activate
pip install -r cdk/requirements.txt
pip install -r requirements-dev.txt   # pytest, flake8, etc.
pip install boto3 anthropic
```

### CDK setup (first time only)

```bash
cd cdk
npm install -g aws-cdk
pip install -r requirements.txt
cdk bootstrap aws://205930651321/us-west-2   # one-time per account
```

---

## 2. Run Tests

```bash
# Full suite
python3 -m pytest tests/ -v

# Single file
python3 -m pytest tests/test_shared_modules.py -v

# Lint
flake8 lambdas/ mcp/

# Syntax check all Python
find lambdas/ mcp/ -name '*.py' -exec python3 -m py_compile {} \;
```

CI runs the same commands on every push (`.github/workflows/ci-cd.yml`).

---

## 3. Deploy Decision Tree

**"I changed a file. What do I run?"**

| I edited... | Run this | Why |
|-------------|----------|-----|
| A single Lambda file (e.g., `daily_brief_lambda.py`) | `bash deploy/deploy_lambda.sh daily-brief` | Fast (~10s), no CDK synth |
| A Lambda + want smoke test | `bash deploy/deploy_and_verify.sh daily-brief` | Deploys + invokes + checks for errors |
| A shared layer module (see list below) | `bash deploy/build_layer.sh` FIRST, then redeploy dependents | Layer must propagate before Lambda code runs |
| Any file in `mcp/` | See MCP Deploy below | `deploy_lambda.sh` strips the `mcp/` directory (ADR-031) |
| CDK stack code (IAM, schedules, new Lambda) | `cd cdk && npx cdk deploy <StackName>` | Infra changes require CloudFormation |
| Site HTML/CSS/JS | `bash deploy/sync_site_to_s3.sh` | Content-hashes assets + invalidates CloudFront |

### `cdk deploy` vs `deploy_lambda.sh`

- **`deploy_lambda.sh`** — zips a single Lambda source, uploads via `aws lambda update-function-code`. Fast (~10s). Use for code-only changes.
- **`cdk deploy`** — synthesizes CloudFormation, diffs against AWS, deploys all resources in a stack. Slower (~60–120s). Use when IAM, env vars, schedules, or new resources change.

### Deploy a single Lambda — worked example

```bash
# 1. Edit the Lambda source
vim lambdas/daily_brief_lambda.py

# 2. Deploy + smoke test
bash deploy/deploy_and_verify.sh daily-brief
# → packages → updates function code → invokes → checks CloudWatch for errors
```

### MCP Lambda deploy (ADR-031)

`life-platform-mcp` is multi-module — `deploy_lambda.sh` hard-rejects it with the correct commands printed. Use the full zip:

```bash
cd /Users/matthewwalker/Documents/Claude/life-platform
ZIP=/tmp/mcp_deploy.zip && rm -f $ZIP
zip -j $ZIP mcp_server.py mcp_bridge.py
zip -r $ZIP mcp/ -x 'mcp/__pycache__/*' 'mcp/*.pyc'
aws lambda update-function-code --function-name life-platform-mcp --zip-file fileb://$ZIP --region us-west-2
```

### Stack names (use with `cdk deploy <name>`)

`LifePlatformCore` · `LifePlatformIngestion` · `LifePlatformCompute` · `LifePlatformEmail` · `LifePlatformOperational` · `LifePlatformMcp` · `LifePlatformMonitoring` · `LifePlatformWeb`

---

## 4. Check Daily-Brief Output

The daily-brief Lambda runs at 11 AM PT and is the platform heartbeat. To verify it ran successfully today:

```bash
# Latest invocation logs (last 10 minutes)
aws logs tail /aws/lambda/daily-brief --since 10m --region us-west-2

# Latest invocation status
aws logs filter-log-events \
  --log-group-name /aws/lambda/daily-brief \
  --start-time $(date -v-1d +%s)000 \
  --filter-pattern '"END RequestId"' \
  --region us-west-2 \
  --query 'events[-1].message'

# Verify public_stats.json was refreshed today
aws s3api head-object \
  --bucket matthew-life-platform \
  --key generated/public_stats.json \
  --query 'LastModified'

# Spot-check the contents
aws s3 cp s3://matthew-life-platform/generated/public_stats.json - | python3 -m json.tool | head -40
```

Quick health checks via MCP (in Claude Desktop or claude.ai):

> "get_freshness_status" — which sources are stale?
> "get_daily_metrics today" — confirm today's day grade is populated.

CloudWatch alarms to watch: `life-platform-daily-brief-errors`, `slo-daily-brief-delivery`, `daily-brief-no-invocations-24h`. These all publish to the urgent SNS topic (ADR-052).

---

## 5. Roll Back

### Roll back a single Lambda

```bash
# Reverts to the previously-deployed zip (one level only)
bash deploy/rollback_lambda.sh <function-name>

# e.g.
bash deploy/rollback_lambda.sh daily-brief
```

### Roll back a CDK stack

```bash
# CloudFormation knows the previous template — roll forward via CDK:
cd cdk
git revert <bad-commit>
npx cdk deploy <StackName>
```

If a CDK deploy fails mid-stream, CloudFormation auto-rolls-back. No manual action usually needed; check the events tab in the AWS Console.

### Roll back the shared layer

```bash
# Pin dependent Lambdas to the prior layer version. Edit cdk/stacks/constants.py:
#   SHARED_LAYER_VERSION = 50   # was 51
cd cdk
npx cdk deploy LifePlatformIngestion LifePlatformCompute LifePlatformEmail LifePlatformMcp LifePlatformOperational LifePlatformMonitoring
```

Don't delete the new layer version — it lets you roll forward later.

### Halt all crons (maintenance mode)

```bash
bash deploy/maintenance_mode.sh enable    # disables all EventBridge rules
# … fix the issue …
bash deploy/maintenance_mode.sh disable   # re-enables
```

---

## Shared Layer Modules

These modules are deployed as Lambda Layer `life-platform-shared-utils` (currently **v51**, mirrored in `cdk/stacks/constants.py:SHARED_LAYER_VERSION`). All ingestion, compute, email, and MCP Lambdas reference this layer.

**If you edit any of these files, run `bash deploy/build_layer.sh` before deploying dependent Lambdas:**

```
ai_calls.py              ai_output_validator.py    auth_breaker.py
board_loader.py          character_engine.py       compute_metadata.py
digest_utils.py          html_builder.py           http_retry.py
ingestion_framework.py   ingestion_validator.py    insight_writer.py
intelligence_common.py   item_size_guard.py        numeric.py
output_writers.py        platform_logger.py        rate_limiter.py
request_validator.py     retry_utils.py            scoring_engine.py
secret_cache.py          sick_day_checker.py       site_writer.py
```

Note: `email_framework.py` was deleted in V2 (replaced inline). `tools_calendar.py` and `podcast_scanner_lambda.py` were also deleted as dead code.

If you skip the layer rebuild and deploy a Lambda, it runs with the OLD version of the shared module silently. CI guard: `tests/test_layer_version_consistency.py`.

---

## Source-of-truth checks

```bash
# Authoritative MCP tool count
grep -c '"name":' mcp/registry.py

# Authoritative layer version
aws lambda list-layer-versions --layer-name life-platform-shared-utils --region us-west-2 \
  --query 'LayerVersions[0].Version'

# Lambda count in us-west-2
aws lambda list-functions --region us-west-2 \
  --query 'Functions[].FunctionName' --output text | tr '\t' '\n' | wc -l
```

---

## Things That Will Break If You Do X

| If you... | What breaks | How to fix |
|-----------|------------|-----------|
| Edit a shared module + skip `build_layer.sh` | Dependent Lambdas run stale code silently | Run `build_layer.sh`, redeploy |
| Run `aws s3 sync --delete` to bucket root | Tries to delete 35k+ objects (blocked by bucket policy + ADR-032 deny statement, but DON'T test it) | S3 versioning recovers; takes hours |
| Change a Lambda env var in AWS Console | Next `cdk deploy` reverts it silently | Edit the CDK stack instead |
| Add a Lambda to CDK without a `role_policies.py` entry | `AccessDenied` on first run | Add the IAM policy, redeploy the stack |
| Use `deploy_lambda.sh` for MCP | All MCP endpoints break (ADR-031) | Use the full zip build above |
| Use DST-aware cron in EventBridge | Schedule drifts twice yearly | All crons fixed UTC — see RUNBOOK |
| Default-encrypt the S3 bucket with KMS | CloudFront → 400 on website endpoints (ADR-053) | Revert to AES256 bucket default; use explicit `--sse aws:kms` for sensitive uploads |
| Re-enable the deleted Lambdas (`email_framework`, `tools_calendar`, `podcast_scanner`) | V2 dead-code closure regression | They were deliberately deleted — check the V2 PR before resurrecting |

---

## Pipeline Ordering

```
06:45–09:00 AM PT   INGESTION    14 Lambdas (8 SIMP-2 + 6 exempt — ADR-056)
09:05 AM PT         ANOMALY      Anomaly detector runs on ingested data
10:20–10:35 AM PT   COMPUTE      character-sheet, daily-metrics, daily-insight,
                                 adaptive-mode, hypothesis-engine + coach pipeline
11:00 AM PT         DAILY BRIEF  Reads computed results, sends email, writes
                                 public_stats.json + character_stats.json
11:30 AM PT         OG IMAGES    6 PNG share cards from public_stats.json
```

If compute runs before ingestion completes, it uses yesterday's data. If the brief runs before compute, it reads stale computed results.

---

## Budget

- **Target**: $15/month
- **AWS Budget alert**: $20/month cap (25%/50%/100% thresholds)
- **Current actual**: ~$13/month (post V2 Phase 5 — saved ~$3.65/mo via prompt caching + model tiering + log retention)
- **Anthropic spend**: ~$8–12/month (down from $17–20 pre-ADR-049)
- **Cost Explorer**:
  ```bash
  aws ce get-cost-and-usage \
    --time-period Start=2026-05-01,End=2026-05-31 \
    --granularity MONTHLY --metrics BlendedCost --no-cli-pager
  ```

---

## What Next

- **Mental model**: `docs/ONBOARDING.md`
- **Architecture catalog**: `docs/ARCHITECTURE.md`
- **Data model**: `docs/SCHEMA.md`
- **Decision history**: `docs/DECISIONS.md` (57 ADRs)
- **Daily operations**: `docs/RUNBOOK.md`
- **MCP tool catalog**: `docs/MCP_TOOL_CATALOG.md` (127 tools)
- **V2 audit findings**: `docs/V2_AUDIT_PLAN.md` (76 findings, ~33 shipped, formally closed in ADR-057)

---

**Verified:** 2026-05-19
