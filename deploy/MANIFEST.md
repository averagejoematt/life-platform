**DEPRECATED** -- This manifest is outdated. See docs/ARCHITECTURE.md for current Lambda inventory.

# Deploy Manifest — Life Platform

> Per PIR-2026-02-28 recommendation E. Documents handler, deps, IAM role, and deploy script for every Lambda.
> **Update this file every time a Lambda is deployed.**
> Last updated: 2026-02-28 (v2.47.1)

---

## Pre-Deploy Checklist

Before any multi-Lambda deploy session:

- [ ] Export current handlers: `aws lambda list-functions --query "Functions[].{N:FunctionName,H:Handler}" --output table --region us-west-2`
- [ ] Download current zips as backups (or verify backup exists in `lambdas/`)
- [ ] List IAM permissions per role for any role being modified
- [ ] After deploy: **smoke test every Lambda** (see `deploy/SMOKE_TEST_TEMPLATE.sh`)
- [ ] Verify gap-fill runs cleanly (proves read + write permissions)
- [ ] Check OAuth tokens still valid (Withings, Garmin, Eight Sleep)

---

## Lambda Inventory (22 Functions)

### Ingestion — API Polling (6)

| Lambda | Handler | Deps | IAM Role | Notes |
|--------|---------|------|----------|-------|
| `strava-data-ingestion` | `lambda_function.lambda_handler` | stdlib only | `lambda-strava-role` | Gap-fill LOOKBACK_DAYS=7. OAuth via Secrets Manager. |
| `whoop-data-ingestion` | `lambda_function.lambda_handler` | stdlib only | `lambda-whoop-role` | Gap-fill LOOKBACK_DAYS=7. OAuth via Secrets Manager. |
| `garmin-data-ingestion` | `garmin_lambda.lambda_handler` | `garth`, `garminconnect` ⚠️ NATIVE | `lambda-garmin-ingestion-role` | **NATIVE DEPS** — must build with `--platform manylinux2014_x86_64`. IAM requires `dynamodb:Query` for gap-fill. |
| `eightsleep-data-ingestion` | `lambda_function.lambda_handler` | stdlib only | `lambda-eightsleep-role` | Gap-fill LOOKBACK_DAYS=7. |
| `habitify-data-ingestion` | `lambda_function.lambda_handler` | stdlib only | `lambda-habitify-ingestion-role` | Gap-fill LOOKBACK_DAYS=7. |
| `withings-data-ingestion` | `lambda_function.lambda_handler` | stdlib only | `lambda-withings-role` | Gap-fill LOOKBACK_DAYS=7. OAuth rotating token — if Lambda is down >24h, token expires. Use `setup/fix_withings_oauth.py` to re-auth. |

### Ingestion — Other (7)

| Lambda | Handler | Deps | IAM Role | Notes |
|--------|---------|------|----------|-------|
| `todoist-data-ingestion` | `lambda_function.lambda_handler` | stdlib only | `lambda-todoist-role` | Simple API poll. |
| `notion-journal-ingestion` | `notion_lambda.lambda_handler` | stdlib only | `lambda-notion-ingestion-role` | Queries Notion DB for journal entries. |
| `macrofactor-data-ingestion` | `macrofactor_lambda.lambda_handler` | stdlib only | `lambda-macrofactor-role` | Parses S3 CSV exports dropped by Dropbox poll. |
| `apple-health-ingestion` | `lambda_function.lambda_handler` | stdlib only | `lambda-apple-health-role` | Processes S3 XML exports. |
| `health-auto-export-webhook` | `health_auto_export_lambda.lambda_handler` | stdlib only | `lambda-health-auto-export-role` | Webhook receiver (API Gateway). Handles health metrics, CGM, BP, State of Mind. |
| `dropbox-poll` | `dropbox_poll_lambda.lambda_handler` | stdlib only | `lambda-dropbox-poll-role` | Polls Dropbox for new MacroFactor exports → S3. |
| `weather-data-ingestion` | `weather_lambda.lambda_handler` | stdlib only | `lambda-weather-role` | Fetches Open-Meteo data. No auth needed. |

### Enrichment (2)

| Lambda | Handler | Deps | IAM Role | Notes |
|--------|---------|------|----------|-------|
| `activity-enrichment` | `enrichment_lambda.lambda_handler` | stdlib only | `lambda-enrichment-role` | Nightly Strava activity naming via Haiku. Uses Anthropic API key from Secrets Manager. |
| `journal-enrichment` | `journal_enrichment_lambda.lambda_handler` | stdlib only | `lambda-journal-enrichment-role` | Haiku enrichment of journal entries (mood, themes, cognitive patterns). Uses Anthropic API key. |

### Email / Digest (4)

| Lambda | Handler | Deps | IAM Role | Notes |
|--------|---------|------|----------|-------|
| `daily-brief` | `lambda_function.lambda_handler` | stdlib only | `lambda-weekly-digest-role` | ⚠️ Zip MUST contain `lambda_function.py` (not `daily_brief_lambda.py`). 3011 lines. 4 Haiku AI calls. Writes day_grade + habit_scores + dashboard JSON. |
| `weekly-digest` | `digest_handler.lambda_handler` | stdlib only | `lambda-weekly-digest-role` | Sunday 8:30 AM PT. Writes clinical.json to S3. |
| `monthly-digest` | `lambda_function.lambda_handler` | stdlib only | `lambda-weekly-digest-role` | 1st Sunday 8:00 AM PT. |
| `anomaly-detector` | `lambda_function.lambda_handler` | stdlib only | `lambda-anomaly-detector-role` | 8:05 AM PT. Travel-aware suppression (v2.1.0). Personalized thresholds (v2.0). |

### Monitoring (1)

| Lambda | Handler | Deps | IAM Role | Notes |
|--------|---------|------|----------|-------|
| `life-platform-freshness-checker` | `lambda_function.lambda_handler` | stdlib only | `lambda-freshness-checker-role` | 9:45 AM PT. Per-source stale thresholds. |

### MCP Server (1)

| Lambda | Handler | Deps | IAM Role | Notes |
|--------|---------|------|----------|-------|
| `life-platform-mcp` | `mcp_server.lambda_handler` | 21-module `mcp/` package | `lambda-mcp-server-role` | 1024 MB. Function URL for remote MCP. Cache warmer at 9 AM PT (EventBridge). Tool functions MUST go BEFORE `TOOLS={}` dict. |

### Utility (1)

| Lambda | Handler | Deps | IAM Role | Notes |
|--------|---------|------|----------|-------|
| `insight-email-parser` | `lambda_function.lambda_handler` | stdlib only | `lambda-insight-email-parser-role` | SES inbound email → insight DDB partition. |

---

## Critical Deploy Rules

1. **Smoke test every deploy** — invoke + grep ERROR + auto-rollback. See `deploy/SMOKE_TEST_TEMPLATE.sh`.
2. **Handler must match filename** — if zip contains `lambda_function.py`, handler must be `lambda_function.lambda_handler`. Mismatch = silent failure.
3. **Daily Brief zip** — must contain `lambda_function.py`, NOT `daily_brief_lambda.py`. Copy/rename before zipping.
4. **Garmin native deps** — always build with `pip3 install --platform manylinux2014_x86_64 --only-binary=:all: --python-version 3.12 --implementation cp`. Never install on macOS directly.
5. **IAM changes with code changes** — if adding a new DynamoDB operation (e.g. `Query` for gap-fill), update the IAM role in the same session.
6. **MCP tool ordering** — tool functions must be defined BEFORE the `TOOLS = {}` dictionary in `mcp_server.py` and all `mcp/*.py` modules.
7. **Wait 10s between sequential Lambda deploys** — prevents API throttling.
8. **Withings OAuth fragility** — if the Lambda is down for >24h, the rotating refresh token expires. Re-auth with `setup/fix_withings_oauth.py`.

---

## DLQ Coverage

20 of 22 Lambdas have Dead Letter Queues. Exceptions:
- `life-platform-mcp` — synchronous Function URL, no async invocation
- `health-auto-export-webhook` — API Gateway integration, errors return HTTP 500

---

## Shared IAM Roles

`lambda-weekly-digest-role` is shared by: `daily-brief`, `weekly-digest`, `monthly-digest`. Changes to this role affect all three.

---

## Handler Quick-Reference

```
strava-data-ingestion        → lambda_function.lambda_handler
whoop-data-ingestion         → lambda_function.lambda_handler
garmin-data-ingestion        → garmin_lambda.lambda_handler         ⚠️ NATIVE DEPS
eightsleep-data-ingestion    → lambda_function.lambda_handler
habitify-data-ingestion      → lambda_function.lambda_handler
withings-data-ingestion      → lambda_function.lambda_handler       ⚠️ OAUTH FRAGILE
todoist-data-ingestion       → lambda_function.lambda_handler
notion-journal-ingestion     → notion_lambda.lambda_handler
macrofactor-data-ingestion   → macrofactor_lambda.lambda_handler
apple-health-ingestion       → lambda_function.lambda_handler
health-auto-export-webhook   → health_auto_export_lambda.lambda_handler
dropbox-poll                 → dropbox_poll_lambda.lambda_handler
weather-data-ingestion       → weather_lambda.lambda_handler
activity-enrichment          → enrichment_lambda.lambda_handler
journal-enrichment           → journal_enrichment_lambda.lambda_handler
daily-brief                  → lambda_function.lambda_handler       ⚠️ ZIP = lambda_function.py
weekly-digest                → digest_handler.lambda_handler
monthly-digest               → lambda_function.lambda_handler
anomaly-detector             → lambda_function.lambda_handler
life-platform-freshness-checker → lambda_function.lambda_handler
life-platform-mcp            → mcp_server.lambda_handler            ⚠️ 21-MODULE PACKAGE
insight-email-parser         → lambda_function.lambda_handler
```
