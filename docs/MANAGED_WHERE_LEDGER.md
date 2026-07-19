# Managed-Where Ledger

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-09

> Every production resource that lives **outside infrastructure-as-code**, with how
> each is verified. A wrong answer to "is this managed in code?" caused the 2026-06
> traffic-logging incident; this ledger makes the right answer scannable.

Last verified: 2026-07-04

---

## The out-of-IaC ring

| Resource | What it is | Why out-of-IaC | Where defined | How drift is detected |
|----------|------------|----------------|---------------|-----------------------|
| **DynamoDB table `life-platform`** | Single-table store; billing PAY_PER_REQUEST | Imported via `Table.from_table_name()` — CDK would need ownership to manage it, risking accidental deletion on `cdk destroy` | AWS Console / initial setup | I4 (`test_i4_dynamodb_table_healthy`) — ACTIVE + deletion_protection + PITR checked post-deploy; GSI1/GSI2 asserted by same test |
| **DynamoDB GSI1** (reading due-date sparse index) | `sk_due_date` GSI for reading domain | ADR-097 sparse index; CDK can't add GSIs to an imported table | AWS Console | I4 GSI assertion |
| **DynamoDB GSI2** (reading overview index) | `sk_overview` GSI for book overview queries | Same as GSI1 | AWS Console | I4 GSI assertion |
| **S3 bucket policy `matthew-life-platform`** | Denies `s3:DeleteObject` on `raw/*`, `config/*`, `uploads/*`, `generated/*` for `matthew-admin` role | Protects raw data; CDK would need to own the bucket to manage the policy | AWS Console / `deploy/bucket_policy.json` | `ProtectDataFromDeployScripts` statement; weekly drift sentinel checks critical bucket settings |
| **S3 lifecycle configuration `matthew-life-platform`** | Per-prefix retention/expiration rules (deploys/, raw/, uploads/, generated/, config/, cloudtrail/, remediation-log/dispatch-dedupe/, mcp-audit/) | Bucket is imported via `Bucket.from_bucket_name()` — CDK cannot attach lifecycle rules to an imported bucket | `deploy/apply_s3_lifecycle.sh` (declarative FULL config — a put replaces every rule; #886) | Retention table in `docs/DATA_GOVERNANCE.md` mirrors the script; no automated drift assertion yet |
| **SES email identity `lifeplatform@mattsusername.com`** | Verified sender for daily brief and digest emails | SES identities are verified at the address level; CDK manages configuration sets but not DKIM/SPF outside Route 53 | AWS Console | Manual quarterly check; SES bounce/complaint metrics in CloudWatch |
| **Route 53 / DNS** | `averagejoematt.com` → CloudFront; MX records for SES | DNS is the root of trust — CDK would need to import the hosted zone; deliberate choice to keep DNS outside automated teardown | AWS Console (Route 53 hosted zone) | Monthly manual check; CloudFront availability alarm fires if DNS is broken |
| **CloudFront function version pins** | `v4-redirects` function version pinned in CloudFront distribution | CloudFront function versions are immutable; the CDK stack references the distribution by ID (`E3S424OXQZ8NBE`) but doesn't manage function associations in the current config | AWS Console | `cdk diff` flags function-version drift; visual QA catches broken redirects |
| **SSM control parameters** | `/life-platform/{budget-tier,experiment-cycle,pause-mode,remediation-mode,partner-email}` | Operational state that must survive a CDK re-deploy; SSM is the runtime config store | Set by Lambdas or operator commands | `deploy/session_postflight.py` reads budget-tier; remediation agent reads remediation-mode; no automated assertion for all 5 |
| **EventBridge Lambda-schedule rules** | Every `cron(...)`/`rate(...)` rule that triggers a life-platform Lambda | **None today — fully CDK-owned.** The only historical exceptions were two hand-created rules, `pipeline-health-check-daily` and `subscriber-onboarding-daily`, created by the pre-CDK setup scripts `deploy/setup_pipeline_health_check.sh` / `deploy/setup_subscriber_onboarding.sh` (now tombstoned — see `docs/_lint/tombstones.txt`) — each duplicated a schedule CDK already owned. Deleted 2026-07-18 (#1257); this row + I24 exist so the class doesn't quietly recur | `cdk/stacks/*.py` — either `create_platform_lambda(..., schedule=...)` (the shortcut, auto-creates + attaches the Rule) or a manual `events.Rule(...)` + `.add_target(targets.LambdaFunction(...))` (the documented "manual events.Rule escape hatch" in `operational_stack.py`, used when the shortcut's auto-enable isn't wanted, or for a second schedule on an already-scheduled Lambda) | I24 (`test_i24_eventbridge_rule_lambda_targets_are_cdk_managed`) — every ENABLED rule targeting a life-platform Lambda must resolve to a CDK declaration or an explicit entry in `EVENTBRIDGE_RULE_EXEMPTIONS` |

---

## Automated assertions (wired to CI)

| Check | What | Where |
|-------|------|-------|
| I4 `test_i4_dynamodb_table_healthy` | DynamoDB ACTIVE + deletion_protection + PITR + GSI1/GSI2 | `tests/test_integration_aws.py` — runs in `post-deploy-checks` CI job |
| I8 `test_i8_s3_bucket_and_config_files` | S3 bucket accessible + critical config files present | Same job |
| I24 `test_i24_eventbridge_rule_lambda_targets_are_cdk_managed` | Every ENABLED EventBridge rule targeting a life-platform Lambda resolves to a CDK-declared schedule (or an explicit `EVENTBRIDGE_RULE_EXEMPTIONS` entry) — catches the #1257 hand-created-rule class | Same job |
| Weekly drift sentinel | Compares live infra config vs CDK code for Lambda timeout/memory/env drift | `deploy/drift_sentinel.py` — Monday-gated step in `.github/workflows/remediation-agent.yml` (cron `45 14 * * 1,3,5`; self-skips unless Monday UTC or manual dispatch) |

---

## Recovery runbook

### DynamoDB deletion protection accidentally disabled
```bash
aws dynamodb update-table \
  --table-name life-platform \
  --deletion-protection-enabled \
  --region us-west-2
```

### DynamoDB PITR disabled
```bash
aws dynamodb update-continuous-backups \
  --table-name life-platform \
  --point-in-time-recovery-specification PointInTimeRecoveryEnabled=true \
  --region us-west-2
```

### S3 bucket policy lost
```bash
aws s3api put-bucket-policy \
  --bucket matthew-life-platform \
  --policy file://deploy/bucket_policy.json
```

### SES identity verification lost
Re-verify via AWS Console → SES → Verified Identities. Check DNS MX + DKIM records in Route 53 still point to SES endpoints.

---

## Maintenance convention

Update this ledger when a resource moves in or out of IaC, or when a new out-of-band resource is deliberately created. Link this file in the PR body. If an automated assertion is added, add a row to the "Automated assertions" table.
