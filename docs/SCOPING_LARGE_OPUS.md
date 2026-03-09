# Large Opus Items — Scoping & Design Notes

> Design decisions and scope for MAINT-4, SIMP-2, PROD-1, PROD-2.
> Created: 2026-03-09. These are planning documents, not implementation specs.

---

## MAINT-4: GitHub Actions CI/CD (6-8 hr, 2 sessions)

### Goal
On push to `main`: lint → package → deploy → smoke test. Manual approval gate before production deploy.

### Architecture

```
push to main
  └─ GitHub Actions workflow
       ├─ Job 1: Lint (flake8, ~30s)
       │    └─ All Python files in lambdas/ and mcp/
       ├─ Job 2: Package (build zips, ~2 min)
       │    ├─ Detect which Lambdas changed (git diff)
       │    ├─ Build zip per changed Lambda (handler config from AWS)
       │    └─ Upload zips as artifacts
       ├─ Job 3: Deploy (needs: package + manual approval)
       │    ├─ Manual approval gate (environment protection rule)
       │    ├─ Deploy each changed Lambda
       │    ├─ 10s delay between deploys (ResourceConflictException avoidance)
       │    └─ Update Lambda Layer if shared modules changed
       └─ Job 4: Smoke test (needs: deploy)
            ├─ Invoke qa-smoke Lambda
            └─ Verify no errors in response
```

### Key Decisions
- **Change detection:** `git diff --name-only HEAD~1 HEAD -- lambdas/` determines which Lambdas to rebuild. Shared modules (board_loader, ai_calls, etc.) trigger all consumers.
- **Handler mapping:** Read from AWS at deploy time (same as `deploy_lambda.sh`), not maintained in repo.
- **Secrets:** AWS credentials via OIDC federation (no long-lived keys in GitHub). Role: `github-actions-deploy-role` with Lambda update + S3 + Secrets read.
- **MCP server:** Special case — requires full `mcp/` package + `mcp_server.py`. Trigger on any file in `mcp/`.
- **Layer rebuild:** Trigger when any file in `lambdas/` that's a shared module changes (board_loader, ai_calls, etc.). Use `deploy/deploy_shared_layer.sh` (already exists? check).
- **Approval gate:** GitHub Environment `production` with required reviewer (Matthew). Lint + package run automatically; deploy waits.

### Flake8 Config
```ini
# .flake8
[flake8]
max-line-length = 140
exclude = .git,__pycache__,deploy,backfill,patches,seeds,setup,handovers,datadrops
ignore = E501,W503,E402
```

### Prerequisites
- Create IAM OIDC provider for GitHub Actions
- Create `github-actions-deploy-role` with scoped permissions
- Add GitHub Environment `production` with protection rules
- Verify `deploy_lambda.sh` works non-interactively (no tty prompts)

### Session Breakdown
- **Session 1 (3-4 hr):** OIDC setup, IAM role, workflow file (lint + package + deploy), manual approval gate
- **Session 2 (3-4 hr):** Change detection logic, shared module handling, smoke test integration, Layer rebuild, docs

---

## SIMP-2: Consolidate Ingestion Lambdas (8-12 hr, 3 sessions)

### Goal
Extract common patterns across 13 ingestion Lambdas into a shared framework. Source-specific code becomes configuration + handler function.

### Current State
13 ingestion Lambdas share ~80% identical code:
- DynamoDB write pattern (put_item with pk/sk)
- S3 raw data archival
- Gap detection (7-day lookback)
- Error handling → DLQ
- Secrets Manager read
- Ingestion validation (DATA-2)
- Schema version tagging (DATA-1)

### Proposed Architecture

```python
# lambdas/ingestion_framework.py — shared framework

class IngestionConfig:
    """Per-source configuration."""
    source_name: str          # e.g., "whoop"
    secret_id: str            # Secrets Manager key
    api_base_url: str         # API endpoint
    lookback_days: int = 7
    needs_oauth: bool = True
    s3_archive_prefix: str    # e.g., "raw/whoop/"
    schema_version: str = "1.0"
    validation_schema: dict   # DATA-2 schema

def ingestion_handler(config: IngestionConfig, fetch_fn, transform_fn):
    """Generic handler. Source-specific logic in fetch_fn and transform_fn."""
    def lambda_handler(event, context):
        # 1. Load secrets
        creds = load_secret(config.secret_id)
        # 2. Determine dates (today + gap detection)
        dates = detect_gaps(config.source_name, config.lookback_days)
        # 3. For each date: fetch → transform → validate → store
        for date in dates:
            raw = fetch_fn(creds, date)         # Source-specific
            record = transform_fn(raw, date)     # Source-specific
            validate_and_store(config, record, date, raw)
    return lambda_handler
```

```python
# lambdas/whoop_handler.py — source-specific handler (tiny file)

from ingestion_framework import IngestionConfig, ingestion_handler

config = IngestionConfig(
    source_name="whoop",
    secret_id="life-platform/whoop",
    ...
)

def fetch(creds, date): ...    # Whoop API calls
def transform(raw, date): ...  # Normalize to platform schema

handler = ingestion_handler(config, fetch, transform)
```

### Migration Strategy
- **Phase 1:** Extract framework from one Lambda (whoop — most standard). Keep old code as fallback.
- **Phase 2:** Migrate 3 more (garmin, strava, withings) — all OAuth-based, similar patterns.
- **Phase 3:** Migrate remaining 9 (including webhook-based and file-triggered).
- **Phase 4:** Delete old Lambda code, update docs.

### Risks
- Each Lambda has subtle differences (OAuth refresh patterns, pagination, field mapping)
- Breaking changes risk data gaps during migration
- Framework must handle: OAuth auto-refresh, CSV parsing (MacroFactor), XML parsing (Apple Health), webhook (HAE)

### Session Breakdown
- **Session 1 (3-4 hr):** Extract framework from whoop. Deploy + verify. Shared module in Layer.
- **Session 2 (3-4 hr):** Migrate garmin, strava, withings. Verify gap detection still works.
- **Session 3 (2-4 hr):** Migrate remaining sources. Delete old code. Update docs.

---

## PROD-1: Infrastructure as Code — CDK (16-24 hr, 5-6 sessions)

### Goal
All AWS resources defined in CDK (Python). `cdk deploy` recreates the full environment. Bash deploy scripts retired for IaC equivalents.

### Scope
39 Lambdas, 1 DynamoDB table, 1 S3 bucket, 1 API Gateway, 3 CloudFront distributions, 1 SQS queue, 8 Secrets Manager secrets, ~47 CloudWatch alarms, ~30 EventBridge rules, 39 IAM roles, 1 SNS topic, 1 Lambda Layer, ACM certificates.

### Stack Design

```
cdk/
  app.py                    # CDK app entry point
  stacks/
    core_stack.py           # DynamoDB, S3, SQS, SNS, Secrets Manager
    ingestion_stack.py      # 13 ingestion Lambdas + EventBridge rules
    compute_stack.py        # 5 compute Lambdas + EventBridge rules
    email_stack.py          # 7 email Lambdas + EventBridge rules
    operational_stack.py    # Operational Lambdas (anomaly, freshness, canary, etc.)
    mcp_stack.py            # MCP Lambda + Function URLs (local + remote)
    web_stack.py            # CloudFront (3 distributions) + ACM
    monitoring_stack.py     # CloudWatch alarms + ops dashboard + SLOs
```

### Key Decisions
- **CDK over Terraform:** Python-native (matches existing codebase), fine-grained AWS resource support, no state file management
- **Stack splitting:** Separate stacks enable independent deployment and reduce blast radius
- **Import existing resources:** Use `cdk import` for DynamoDB table, S3 bucket, CloudFront (avoid recreation)
- **Secrets:** CDK creates the secret shells; values managed externally (never in code)
- **Lambda code:** CDK packages from `lambdas/` directory, same as current deploy scripts
- **Parameter store:** Environment-specific config (account ID, region, domain names) via CDK context

### Migration Strategy
- **Phase 1:** Core stack (DynamoDB, S3, SQS, SNS) — import existing resources
- **Phase 2:** One ingestion Lambda as proof of concept (whoop) — verify packaging, IAM, EventBridge
- **Phase 3:** Remaining ingestion Lambdas (bulk, from template pattern)
- **Phase 4:** Compute + email + operational Lambdas
- **Phase 5:** MCP + web + monitoring stacks
- **Phase 6:** Retire bash deploy scripts (keep as reference), update all docs

### Prerequisites
- Install CDK: `npm install -g aws-cdk`
- Bootstrap CDK: `cdk bootstrap aws://205930651321/us-west-2`
- Create `cdk.json` with context values

### Risks
- Importing existing resources is delicate — wrong resource ID = CDK tries to create duplicates
- CloudFront + ACM cross-region (us-east-1) adds complexity
- Lambda Layer versioning in CDK is auto-incrementing — may conflict with manual versions

### Session Breakdown
- **Session 1 (3-4 hr):** CDK init, core stack (DDB import, S3 import, SQS, SNS)
- **Session 2 (3-4 hr):** First Lambda (whoop) — full lifecycle: IAM, code, EventBridge, DLQ, alarm
- **Session 3 (3-4 hr):** Remaining ingestion Lambdas (template-based bulk creation)
- **Session 4 (3-4 hr):** Compute + email + operational Lambdas
- **Session 5 (3-4 hr):** MCP stack + web stack (CloudFront, ACM)
- **Session 6 (2-3 hr):** Monitoring stack + cleanup + retire bash scripts + docs

---

## PROD-2: Multi-User Parameterization (12-16 hr, 4 sessions)

### Goal
Remove hardcoded `matthew` assumptions end-to-end. USER_ID parameterized so a second user could be added without code changes.

### Current Hardcoding Audit
- `USER_ID = "matthew"` in 39 Lambdas + MCP server (env var, but default is hardcoded)
- `USER#matthew` in DynamoDB key construction
- `mattsusername.com` in SES sender/recipient
- `matthew-life-platform` S3 bucket name
- Profile at `pk=USER#matthew, sk=PROFILE#v1`
- Board of Directors config assumes single user
- Dashboard/buddy page JSON paths assume single user
- Weekly Plate grocery list assumes Met Market (user-specific)

### Architecture Changes

1. **Lambda env var:** `USER_ID` already exists as env var — just ensure all Lambdas read it and never fallback to hardcoded `matthew`
2. **DynamoDB:** Key pattern `USER#{user_id}#SOURCE#{source}` already parameterized in most places — audit for hardcoded `matthew`
3. **S3 paths:** Prefix with user_id: `dashboard/{user_id}/data.json`, `buddy/{user_id}/data.json`, `config/{user_id}/profile.json`
4. **SES:** Email recipient from profile record, not hardcoded
5. **MCP:** User ID from auth context (API key → user mapping)
6. **Profile:** Per-user profile record (targets, habits, grocery store, etc.)
7. **CloudFront:** User-scoped paths (or separate distributions per user)

### What Stays Single-User
- AWS account (shared)
- DynamoDB table (shared, partitioned by user)
- S3 bucket (shared, prefixed by user)
- Lambda functions (shared, parameterized by event/env)

### Migration Strategy
- **Phase 1:** Audit all 39 Lambdas + MCP for hardcoded user references
- **Phase 2:** Extract user-specific config to profile record (grocery store, email, targets)
- **Phase 3:** Parameterize all S3 paths
- **Phase 4:** Parameterize MCP (user from auth context)
- **Phase 5:** Parameterize email sender/recipient
- **Phase 6:** Test with synthetic second user (no real data, verify isolation)

### Dependency
PROD-1 (IaC) should ideally come first — CDK makes it trivial to parameterize resources. Doing PROD-2 on bash scripts means editing 39 Lambda configs manually.

### Session Breakdown
- **Session 1 (3-4 hr):** Full audit + catalog of all hardcoded references
- **Session 2 (3-4 hr):** Parameterize ingestion + compute Lambdas
- **Session 3 (3-4 hr):** Parameterize email + MCP + web
- **Session 4 (2-3 hr):** Synthetic second user test + docs
