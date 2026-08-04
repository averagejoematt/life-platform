# Lambda Requirements

Pinned dependency files per Lambda group (MAINT-1, v2.99.0).

## Structure

| File | Lambda(s) | Notes |
|------|-----------|-------|
| `garmin.txt` | garmin-data-ingestion | **Binary layer** `garth-layer` (`GARTH_LAYER_ARN`). 🤖 GENERATED (#2099) — build spec `LAYERS['garth']`. Lists all 14 packages in the live layer, not just the 2 top-level pins |
| `pillow.txt` | og-image-generator, reading-cover-pipeline | **Binary layer** `pillow-layer` (`PILLOW_LAYER_ARN`). 🤖 GENERATED (#2099) — build spec `LAYERS['pillow']` |
| `lameenc.txt` | coach-panel-podcast | **Binary layer** `lameenc-layer` (`LAMEENC_LAYER_ARN`). 🤖 GENERATED (#2099) — build spec `LAYERS['lameenc']`. The #1336 "UNVERIFIED" flag is cleared: measured 2026-08-04 against the live layer, `lameenc==1.8.4` was already correct |
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

## The three layer manifests are GENERATED (#2099)

`garmin.txt`, `pillow.txt` and `lameenc.txt` are **derived artifacts** — do not hand-edit
them. They are rendered by `deploy/build_lambda_layer.py::render_manifest()` from two
inputs, and `tests/test_layer_build_manifest.py` fails if the file and the render disagree:

| Input | Meaning | Who edits it |
|---|---|---|
| `LAYERS[key].requirements` in `deploy/build_lambda_layer.py` | the **target** pins the next build installs | a human taking an upgrade |
| `deploy/layers/<key>.deployed.json` | the **measured** contents of the live layer version | `--promote`, after an owner deploy |

Why this matters more than it looks: **editing a pin in these files deploys nothing.** No
deploy path pip-installs from `lambdas/requirements/`; third-party code reaches a running
Lambda only inside the pre-built layer zip. Dependabot #1778 (Pillow) and #1780
(garminconnect) were both closed for exactly this reason. A real upgrade is
build → `publish-layer-version` → bump `*_LAYER_VERSION` → `cdk deploy` → `--promote`.

The uncommented pins are therefore the **deployed** versions — that is what pip-audit
should alarm on. The next build's targets appear as `# layer-build-target:` comments in
the same file, so both states are visible side by side.

Manifests list the **whole transitive closure**. `garmin.txt` used to pin 2 of the 14
packages inside `garth-layer:2`, which hid three fixable advisories (`idna` PYSEC-2026-215,
`urllib3` PYSEC-2026-142/141) from every scan.

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

**For a binary layer** (`garmin.txt` / `pillow.txt` / `lameenc.txt` — generated):

1. Edit the target pins in `deploy/build_lambda_layer.py::LAYERS[<key>].requirements`
2. `python3 deploy/build_lambda_layer.py build <key>` — prints every packaged distribution
3. `pip-audit -r <(...)` the build record's packages, then owner-publish + `cdk deploy`
4. `--promote <key> --from-build <build.json> --layer-version <N>` to re-derive this manifest

**For every other manifest** (stdlib/boto3 groups, hand-maintained):

1. Add pinned version to the appropriate `.txt` file
2. Update `deploy_lambda.sh` invocation to install from requirements
3. Run `pip-audit` on the updated file before deploying
