# Lambda Requirements

Pinned dependency files per Lambda group (MAINT-1, v2.99.0).

## Structure

| File | Lambda(s) | Notes |
|------|-----------|-------|
| `garmin.txt` | garmin-data-ingestion | Built via `fix_garmin_deps.sh` — cross-platform wheels; **also pins `garth` (the `garth-layer` binary layer)** |
| `pillow.txt` | og-image-generator (+ web/operational PIL users) | **Binary layer** `pillow-layer` (`PILLOW_LAYER_ARN`). ⚠️ Version UNVERIFIED vs live layer — confirm + correct (#1336) |
| `lameenc.txt` | coach-panel-podcast | **Binary layer** `lameenc-layer` (`LAMEENC_LAYER_ARN`). ⚠️ Version UNVERIFIED vs live layer — confirm + correct (#1336) |
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

## Key findings

**Most Lambdas have zero third-party dependencies** beyond what the Lambda runtime provides
(boto3, botocore). All Anthropic API calls use raw `urllib.request` — no `anthropic` SDK
is needed, which keeps zip sizes minimal and eliminates a major dependency surface.

**Lambda *source* is stdlib-only, but three binary *layers* ship third-party code**
into running Lambdas — these are the real SCA surface and each has a pinned manifest here:
- `garth-layer` → `garth` (pinned in `garmin.txt` alongside `garminconnect`)
- `pillow-layer` → `Pillow` (`pillow.txt`)
- `lameenc-layer` → `lameenc` (`lameenc.txt`)

The layer ARNs live in `cdk/stacks/constants.py` (`*_LAYER_ARN`). **`pip_audit_lambda`
enforces coverage**: `check_layer_manifest_coverage()` enumerates those ARNs and fails the
scan RED if any referenced layer has no matching manifest here — so a future layer added
without a pinned manifest can't slip back into the unscanned state that #1336 fixed.

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
