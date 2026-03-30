# Alarm Coverage Audit — 2026-03-30

**Pre-audit coverage:** 42 of 59 platform Lambdas (71%)
**Post-audit coverage:** 59 of 59 platform Lambdas (100%)
**New alarms created:** 17

## Missing Alarms (Fixed)

All 17 created with pattern: daily evaluation, Sum > 0, SNS → life-platform-alerts, treat-missing-data notBreaching.

| Lambda | Alarm Created |
|--------|--------------|
| dropbox-poll | life-platform-dropbox-poll-errors |
| garmin-data-ingestion | life-platform-garmin-data-ingestion-errors |
| habitify-data-ingestion | life-platform-habitify-data-ingestion-errors |
| insight-email-parser | life-platform-insight-email-parser-errors |
| journal-enrichment | life-platform-journal-enrichment-errors |
| life-platform-canary | life-platform-life-platform-canary-errors |
| life-platform-data-reconciliation | life-platform-life-platform-data-reconciliation-errors |
| life-platform-dlq-consumer | life-platform-life-platform-dlq-consumer-errors |
| life-platform-pip-audit | life-platform-life-platform-pip-audit-errors |
| life-platform-qa-smoke | life-platform-life-platform-qa-smoke-errors |
| life-platform-site-api-ai | life-platform-life-platform-site-api-ai-errors |
| measurements-ingestion | life-platform-measurements-ingestion-errors |
| notion-journal-ingestion | life-platform-notion-journal-ingestion-errors |
| pipeline-health-check | life-platform-pipeline-health-check-errors |
| site-stats-refresh | life-platform-site-stats-refresh-errors |
| subscriber-onboarding | life-platform-subscriber-onboarding-errors |
| weather-data-ingestion | life-platform-weather-data-ingestion-errors |

## Cost Impact
17 alarms × ~$0.10/month = ~$1.70/month incremental.

## Alarm Action Verification
All alarms action to: `arn:aws:sns:us-west-2:205930651321:life-platform-alerts`
