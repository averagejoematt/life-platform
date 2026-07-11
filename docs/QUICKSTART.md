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

The CDK toolchain is pinned both directions (#814, R22-MOD-01) — CLI in
`ci-cd.yml`, `aws-cdk-lib`/`constructs` in `cdk/requirements.txt` +
`requirements-dev.txt`. Match CI's pinned CLI version rather than installing
whatever npm resolves as latest today (an unpinned install is exactly what
caused #814):

```bash
cd cdk
npm install -g aws-cdk@2.1129.0   # match the pin in .github/workflows/ci-cd.yml
pip install -r requirements.txt   # aws-cdk-lib/constructs pinned exactly — see comments in that file
cdk bootstrap aws://205930651321/us-west-2   # one-time per account
```

Bumping either pin is a deliberate PR (bump CLI + lib + constructs together,
verify `cdk synth`/`cdk diff` still work), never an incidental drift.

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
| A shared module at the `lambdas/` root (e.g. `ai_calls.py`) | Merge to main (CI fleet-deploys) or `bash deploy/deploy_fleet.sh` | ONE bundle per function (#781) — every function must receive the new copy |
| Any file in `mcp/` | `bash deploy/deploy_lambda.sh life-platform-mcp` | Since #781 the script stages the mcp-shaped full bundle (tree + `mcp_server.py` + `mcp/`) |
| CDK stack code (IAM, schedules, new Lambda) | `cd cdk && npx cdk deploy <StackName>` | Infra changes require CloudFormation |
| Site HTML/CSS/JS | **merge to main** — CI deploys it (`site-deploy.yml`, #750) | Manual fallback: `bash deploy/sync_site_to_s3.sh` |

### `cdk deploy` vs `deploy_lambda.sh`

- **`deploy_lambda.sh`** — zips a single Lambda source, uploads via `aws lambda update-function-code`. Fast (~10s). Use for code-only changes.
- **`cdk deploy`** — synthesizes CloudFormation, diffs against AWS, deploys all resources in a stack. Slower (~60–120s). Use when IAM, env vars, schedules, or new resources change.

**Prefer the guarded path over a bare `cdk deploy`:** `bash deploy/cdk_deploy.sh <StackName>` (see `docs/CONVENTIONS.md` §6) blocks a deploy from a stale checkout, and flags any function whose live code has drifted from the stack via a direct `deploy_lambda.sh` push since the last `cdk deploy` — either of which a blind `cdk deploy --all` would silently clobber (#382).

### Deploy a single Lambda — worked example

```bash
# 1. Edit the Lambda source
vim lambdas/daily_brief_lambda.py

# 2. Deploy + smoke test
bash deploy/deploy_and_verify.sh daily-brief
# → packages → updates function code → invokes → checks CloudWatch for errors
```

### MCP Lambda deploy

Since #781, `deploy_lambda.sh` handles MCP correctly — it stages the mcp-shaped full bundle
(the whole `lambdas/` tree + `mcp_server.py` + `mcp/`):

```bash
bash deploy/deploy_lambda.sh life-platform-mcp
```

⚠️ Do NOT hand-roll a zip of only `mcp_server.py` + `mcp/` — it boots but fails at import
time (`No module named 'reading'`) because the bundled `lambdas/` tree is missing. The
script is the only sanctioned path. Verify boot after any MCP deploy: an unauthenticated
curl to the Function URL should return **401** (healthy), not 5xx.

### Stack names (use with `cdk deploy <name>`)

`LifePlatformCore` · `LifePlatformIngestion` · `LifePlatformCompute` · `LifePlatformEmail` · `LifePlatformOperational` · `LifePlatformServe` · `LifePlatformMcp` · `LifePlatformMonitoring` · `LifePlatformWeb`

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

### Roll back a shared-module change

Shared modules ship inside every function's bundle (#781 — no layer to pin). Roll back the
commit and let the fleet converge:

```bash
git revert <bad-sha>              # on main
git push                          # CI fleet-deploys the reverted bundle
# Attended alternative: bash deploy/deploy_fleet.sh   (after the revert is checked out)
# Single function only: bash deploy/rollback_lambda.sh <function-name>
```

### Halt all crons (maintenance mode)

```bash
bash deploy/maintenance_mode.sh enable    # disables all EventBridge rules
# … fix the issue …
bash deploy/maintenance_mode.sh disable   # re-enables
```

---

## Shared Modules (bundled — #781/ADR-131)

Shared modules live at the `lambdas/` root and ship **inside every function's code bundle**,
staged by `deploy/build_bundle.py` (the shared layer `life-platform-shared-utils` was retired
2026-07-06). Editing any of them = fleet deploy (see the table above).

**Notable shared modules:**

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

If you edit a shared module and deploy only one function, every OTHER function still runs
the old copy until fleet-deployed — CI closes this automatically (an unmapped `lambdas/`
change on main triggers a fleet deploy). CI invariant: zero functions reference the retired
layer (plan job + integration test I2).

---

## Source-of-truth checks

```bash
# Authoritative counts (tools, Lambdas, alarms, ADRs) — AST discoverers, prints all of them
python3 deploy/sync_doc_metadata.py
# NB: do NOT `grep -c '"name":' mcp/registry.py` for the tool count — it over-counts by
# matching nested input-schema fields (docs/CONVENTIONS.md "Facts that drift").

# Layer-retirement invariant (#781) — must return []
aws lambda list-functions --region us-west-2 \
  --query "Functions[?Layers[?contains(Arn, 'life-platform-shared-utils')]].FunctionName"

# Live Lambda count in us-west-2 (live AWS view; CDK-defined count comes from the discoverer above)
aws lambda list-functions --region us-west-2 \
  --query 'Functions[].FunctionName' --output text | tr '\t' '\n' | wc -l
```

---

## Things That Will Break If You Do X

| If you... | What breaks | How to fix |
|-----------|------------|-----------|
| Edit a shared module + deploy only ONE function | Every other function runs the old copy | Fleet deploy: merge to main or `bash deploy/deploy_fleet.sh` |
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
- **Decision history**: `docs/DECISIONS.md` (119 ADRs)
- **Daily operations**: `docs/RUNBOOK.md`
- **MCP tool catalog**: `docs/MCP_TOOL_CATALOG.md` (64 tools)
- **V2 audit findings**: `docs/V2_AUDIT_PLAN.md` (76 findings, ~33 shipped, formally closed in ADR-057)

---

**Verified:** 2026-07-10 (layer-retirement #781 propagated; counts re-derived via sync_doc_metadata discoverers)
