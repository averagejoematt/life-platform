# Lambda Requirements

Pinned dependency files per Lambda group (MAINT-1, v2.99.0).

## Structure

| File | Lambda(s) | Notes |
|------|-----------|-------|
| `garmin.txt` | garmin-data-ingestion | Built via `fix_garmin_deps.sh` — cross-platform wheels |
| `withings.txt` | withings-data-ingestion | withings-api SDK |
| `strava.txt` | strava-data-ingestion | stdlib urllib only |
| `whoop.txt` | whoop-data-ingestion | stdlib urllib only |
| `eightsleep.txt` | eightsleep-data-ingestion | stdlib urllib only |
| `habitify.txt` | habitify-data-ingestion | stdlib urllib only |
| `macrofactor.txt` | macrofactor-data-ingestion | stdlib csv + urllib |
| `notion.txt` | notion-journal-ingestion | stdlib urllib only |
| `todoist.txt` | todoist-data-ingestion | stdlib urllib only |
| `weather.txt` | weather-data-ingestion | stdlib urllib only |
| `apple_health.txt` | apple-health-ingestion | stdlib xml only |
| `hae_webhook.txt` | health-auto-export-webhook | stdlib only |
| `enrichment.txt` | activity-enrichment, journal-enrichment | stdlib + boto3 |
| `email_digest.txt` | daily-brief, weekly-digest, monthly-digest, nutrition-review, chronicle, weekly-plate, monday-compass, anomaly-detector, character-sheet-compute, adaptive-mode-compute, daily-metrics-compute, daily-insight-compute, hypothesis-engine | stdlib + boto3 (AI via raw urllib) |
| `mcp.txt` | life-platform-mcp | stdlib + boto3 |
| `dashboard_refresh.txt` | dashboard-refresh | stdlib + boto3 |
| `infra.txt` | freshness-checker, key-rotator, data-export, qa-smoke, dlq-consumer, insight-email-parser, dropbox-poll | stdlib + boto3 |
| `layer.txt` | Lambda Layer (shared modules) | stdlib + boto3 |

## Key findings

**Most Lambdas have zero third-party dependencies** beyond what the Lambda runtime provides
(boto3, botocore). All Anthropic API calls use raw `urllib.request` — no `anthropic` SDK
is needed, which keeps zip sizes minimal and eliminates a major dependency surface.

**Only two Lambdas have third-party deps:**
- `garmin-data-ingestion` → `garminconnect` + `garth` (deployed via `fix_garmin_deps.sh`)
- `withings-data-ingestion` → `withings-api` + transitive deps

## Vulnerability scanning

```bash
# Install pip-audit
pip3 install pip-audit --break-system-packages

# Scan Garmin deps (the only ones with real third-party packages)
pip-audit -r lambdas/requirements/garmin.txt

# Scan Withings deps
pip-audit -r lambdas/requirements/withings.txt
```

## Adding new dependencies

1. Add pinned version to the appropriate `.txt` file
2. Update `deploy_lambda.sh` invocation to install from requirements
3. Run `pip-audit` on the updated file before deploying
