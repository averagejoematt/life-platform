# Quickstart — Your First Day

> Read this before touching anything. It covers the things the other docs assume you already know.

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

## AWS Credential Setup

The platform runs in AWS account `205930651321`, region `us-west-2` (Oregon).

```bash
# Configure credentials (ask Matthew for access key + secret key)
aws configure
# AWS Access Key ID: <from Matthew>
# AWS Secret Access Key: <from Matthew>
# Default region: us-west-2
# Default output format: json

# Verify it worked
aws sts get-caller-identity
# Should show: Account: 205930651321, Arn: ...matthew-admin...
```

The IAM user is `matthew-admin`. CI/CD uses OIDC federation (no long-lived keys in GitHub).

---

## Deploy Decision Tree

**"I changed a file. What do I run?"**

| I edited... | Run this | Why |
|-------------|----------|-----|
| A Lambda file only (e.g., `daily_brief_lambda.py`) | `bash deploy/deploy_lambda.sh daily-brief` | Fast (~10s), no CDK synth needed |
| A Lambda + want smoke test | `bash deploy/deploy_and_verify.sh daily-brief` | Deploys + invokes + checks for errors |
| A shared layer module (see list below) | `bash deploy/build_layer.sh` FIRST, then deploy dependents | Layer must propagate before Lambda code runs |
| Any file in `mcp/` | See MCP Deploy below | `deploy_lambda.sh` strips the `mcp/` directory (ADR-031) |
| CDK stack code (IAM, schedules, new Lambda) | `cd cdk && npx cdk deploy <StackName>` | Infrastructure changes require CloudFormation |
| Site HTML/CSS/JS | `bash deploy/sync_site_to_s3.sh` | Content-hashes assets + invalidates CloudFront |
| Need to undo a Lambda deploy | `bash deploy/rollback_lambda.sh <function-name>` | Reverts to previous.zip (one level only) |

### `cdk deploy` vs `deploy_lambda.sh`

- **`deploy_lambda.sh`** — zips a single Lambda source file, uploads via `aws lambda update-function-code`. Fast (~10s). Use for code-only changes.
- **`cdk deploy`** — synthesizes CloudFormation, diffs against AWS, deploys all resources in a stack. Slower (~60-120s). Use when IAM policies, environment variables, schedules, or new resources change.
- Both work for Lambda code changes, but `cdk deploy` re-bundles ALL Lambdas in the stack from `lambdas/` directory.

---

## MCP Lambda Deploy (ADR-031)

The MCP Lambda is a multi-module package (`mcp_server.py` + `mcp_bridge.py` + the entire `mcp/` directory). `deploy_lambda.sh` packages only a single file — it would strip the `mcp/` directory and silently break all MCP endpoints.

**Always use the full zip build:**
```bash
cd /Users/matthewwalker/Documents/Claude/life-platform
ZIP=/tmp/mcp_deploy.zip && rm -f $ZIP
zip -j $ZIP mcp_server.py mcp_bridge.py
zip -r $ZIP mcp/ -x 'mcp/__pycache__/*' 'mcp/*.pyc'
aws lambda update-function-code --function-name life-platform-mcp --zip-file fileb://$ZIP --region us-west-2
```

`deploy_lambda.sh` hard-rejects `life-platform-mcp` with a clear error message and prints these commands.

---

## Shared Layer Modules

These 16 modules are deployed as a Lambda Layer (`life-platform-shared-utils`). All ingestion, compute, and email Lambdas reference this layer.

**If you edit ANY of these files, run `bash deploy/build_layer.sh` before deploying dependent Lambdas:**

```
ai_calls.py              board_loader.py          character_engine.py
digest_utils.py          html_builder.py          ingestion_framework.py
ingestion_validator.py   insight_writer.py        item_size_guard.py
output_writers.py        platform_logger.py       retry_utils.py
scoring_engine.py        sick_day_checker.py       site_writer.py
ai_output_validator.py
```

If you skip the layer rebuild and deploy a Lambda, it runs with the OLD version of the shared module. No error — just silently stale behavior.

---

## Things That Will Break If You Do X

| If you... | What breaks | How to fix |
|-----------|------------|-----------|
| Edit a shared module + skip `build_layer.sh` | Dependent Lambdas run stale code silently | Run `build_layer.sh`, redeploy |
| Run `aws s3 sync --delete` to bucket root | Deletes 35K+ objects across all prefixes (happened 2026-03-16, ADR-032) | S3 versioning recovers it, but it takes hours |
| Change a Lambda env var in AWS Console | Next `cdk deploy` reverts it silently | Edit the CDK stack instead |
| Add a Lambda to CDK without a `role_policies.py` entry | Lambda gets `AccessDenied` on first run | Add the IAM policy, redeploy the stack |
| Use `deploy_lambda.sh` for MCP | All MCP endpoints return 401 or route incorrectly (ADR-031) | Use the full zip build above |
| Use DST-aware cron in EventBridge | Schedule drifts by 1 hour twice yearly | All crons must be fixed UTC — see RUNBOOK |

---

## Pipeline Ordering

The daily pipeline has **strict ordering**. Changing schedules without maintaining this order produces stale data.

```
06:45–09:00 AM PT   INGESTION    Whoop, Withings, Strava, Garmin, etc.
09:05 AM PT         ANOMALY      Anomaly detector runs on ingested data
10:20–10:35 AM PT   COMPUTE      Insights, metrics, adaptive mode, character sheet
11:00 AM PT         DAILY BRIEF  Reads computed results, sends email, writes public_stats.json
11:30 AM PT         OG IMAGES    Generates social share images from public_stats.json
```

If compute runs before ingestion completes, it uses yesterday's data. If the brief runs before compute, it reads stale computed results.

---

## Budget

- **Target**: $15/month
- **AWS Budget alert**: $20/month cap (alerts at 25%/50%/100%)
- **Current actual**: ~$13/month
- **Cost Explorer**: `aws ce get-cost-and-usage --time-period Start=2026-03-01,End=2026-03-31 --granularity MONTHLY --metrics BlendedCost --no-cli-pager`

---

## What Next

- **Architecture overview**: `docs/ARCHITECTURE.md`
- **How the data model works**: `docs/SCHEMA.md`
- **Why decisions were made**: `docs/DECISIONS.md` (44 ADRs)
- **Daily operations**: `docs/RUNBOOK.md`
- **MCP tool catalog**: `docs/MCP_TOOL_CATALOG.md` (112 tools)
