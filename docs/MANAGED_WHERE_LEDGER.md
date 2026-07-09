# Managed-Where Ledger

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
| **S3 bucket policy `matthew-life-platform`** | Denies `s3:DeleteObject` on `raw/*`, `config/*`, `uploads/*`, `generated/*` for `matthew-admin` role | Protects raw data; CDK would need to own the bucket to manage the policy | AWS Console / `seeds/seed_bucket_policy.json` | `ProtectDataFromDeployScripts` statement; weekly drift sentinel checks critical bucket settings |
| **S3 lifecycle configuration `matthew-life-platform`** | Per-prefix retention/expiration rules (deploys/, raw/, uploads/, generated/, config/, cloudtrail/, remediation-log/dispatch-dedupe/, mcp-audit/) | Bucket is imported via `Bucket.from_bucket_name()` — CDK cannot attach lifecycle rules to an imported bucket | `deploy/apply_s3_lifecycle.sh` (declarative FULL config — a put replaces every rule; #886) | Retention table in `docs/DATA_GOVERNANCE.md` mirrors the script; no automated drift assertion yet |
| **SES email identity `lifeplatform@mattsusername.com`** | Verified sender for daily brief and digest emails | SES identities are verified at the address level; CDK manages configuration sets but not DKIM/SPF outside Route 53 | AWS Console | Manual quarterly check; SES bounce/complaint metrics in CloudWatch |
| **Route 53 / DNS** | `averagejoematt.com` → CloudFront; MX records for SES | DNS is the root of trust — CDK would need to import the hosted zone; deliberate choice to keep DNS outside automated teardown | AWS Console (Route 53 hosted zone) | Monthly manual check; CloudFront availability alarm fires if DNS is broken |
| **CloudFront function version pins** | `v4-redirects` function version pinned in CloudFront distribution | CloudFront function versions are immutable; the CDK stack references the distribution by ID (`E3S424OXQZ8NBE`) but doesn't manage function associations in the current config | AWS Console | `cdk diff` flags function-version drift; visual QA catches broken redirects |
| **SSM control parameters** | `/life-platform/{budget-tier,experiment-cycle,pause-mode,remediation-mode,partner-email}` | Operational state that must survive a CDK re-deploy; SSM is the runtime config store | Set by Lambdas or operator commands | `deploy/session_postflight.py` reads budget-tier; remediation agent reads remediation-mode; no automated assertion for all 5 |

---

## Automated assertions (wired to CI)

| Check | What | Where |
|-------|------|-------|
| I4 `test_i4_dynamodb_table_healthy` | DynamoDB ACTIVE + deletion_protection + PITR + GSI1/GSI2 | `tests/test_integration_aws.py` — runs in `post-deploy-checks` CI job |
| I8 `test_i8_s3_bucket_and_config_files` | S3 bucket accessible + critical config files present | Same job |
| Weekly drift sentinel | Compares live infra config vs CDK code for Lambda timeout/memory/env drift | `.github/workflows/ci-cd.yml` weekly cron |

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
  --policy file://seeds/seed_bucket_policy.json
```

### SES identity verification lost
Re-verify via AWS Console → SES → Verified Identities. Check DNS MX + DKIM records in Route 53 still point to SES endpoints.

---

## Maintenance convention

Update this ledger when a resource moves in or out of IaC, or when a new out-of-band resource is deliberately created. Link this file in the PR body. If an automated assertion is added, add a row to the "Automated assertions" table.
