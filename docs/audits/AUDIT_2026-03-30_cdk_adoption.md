# CDK Adoption Audit — 2026-03-30

**Total Lambdas in us-west-2:** 65 (59 platform + 6 serverlessrepo/power-tuning)
**CDK-managed:** 55
**Unmanaged:** 4
**Lambda@Edge (us-east-1):** 4 (2 platform: cf-auth, buddy-auth + 2 serverlessrepo)
**Serverlessrepo (exclude from count):** 6 (Lambda Power Tuning — not platform code)

---

## Unmanaged Lambdas

| Function | Created | Should Belong To | EventBridge? | Status |
|----------|---------|------------------|-------------|--------|
| `food-delivery-ingestion` | v4.2.x | LifePlatformIngestion | Yes (S3 trigger) | NEEDS ADOPTION |
| `measurements-ingestion` | v4.2.x | LifePlatformIngestion | No (manual trigger) | NEEDS ADOPTION |
| `pipeline-health-check` | v4.4.0 | LifePlatformOperational | Yes (daily 6 AM PT) | NEEDS ADOPTION |
| `subscriber-onboarding` | v4.3.x | LifePlatformEmail | Yes (daily 10 AM PT) | NEEDS ADOPTION |

---

## Adoption Plan

### `food-delivery-ingestion`
- **Stack:** LifePlatformIngestion
- **IAM:** DynamoDB read/write on `food_delivery` partition, S3 read on uploads/
- **Trigger:** S3 event on `uploads/food_delivery/`
- **Alarm:** Error alarm → life-platform-alerts

### `measurements-ingestion`
- **Stack:** LifePlatformIngestion
- **IAM:** DynamoDB read/write on `measurements` partition
- **Trigger:** None (manual/MCP-triggered)
- **Alarm:** Error alarm → life-platform-alerts

### `pipeline-health-check`
- **Stack:** LifePlatformOperational
- **IAM:** Lambda invoke (all ingestion Lambdas), Secrets Manager read, DynamoDB write on `health_check` partition
- **Trigger:** EventBridge cron(0 13 * * ? *) = 6 AM PT daily
- **Alarm:** Error alarm → life-platform-alerts

### `subscriber-onboarding`
- **Stack:** LifePlatformEmail
- **IAM:** DynamoDB read on subscribers, SES send, Secrets Manager read (ai-keys)
- **Trigger:** EventBridge cron (daily)
- **Alarm:** Error alarm → life-platform-alerts

---

## Notes
- 6 `serverlessrepo-lambda-power-tuning-*` Lambdas are from AWS SAR deployment — not platform code, excluded from count
- 2 Lambda@Edge functions (`life-platform-cf-auth`, `life-platform-buddy-auth`) are manually managed in us-east-1 — cannot be CDK-managed (CDK limitation for Lambda@Edge attached to existing distributions)
- Platform Lambda count for documentation: 59 us-west-2 platform Lambdas + 2 Lambda@Edge = 61 total (docs say 60 — update to 61 after adoption)
