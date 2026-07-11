Deploy a Lambda function, the site, or the fleet (one full-tree bundle, #781).

## Arguments: $ARGUMENTS

## Instructions

Parse `$ARGUMENTS` to determine what to deploy. Support these modes:

### Mode 1: `site`
**Primary path (since #393): merge to `main` — CI deploys the site.** A push to `main`
touching `site/` runs the gated CI pipeline (`.github/workflows/ci-cd.yml`): lint → test →
plan → **manual `production` approval** → site deploy (`deploy_site.sh`) → visual/AI-QA +
accuracy gates. CI deploys the merged `main` tree only, so a stale local checkout can never
clobber live, and the reader-facing QA gate fires on every site change. Prefer this.

**Local fallback (documented, not the default):** `bash deploy/deploy_site.sh` — run this
only for an out-of-band hotfix or when CI is unavailable. It syncs `site/` to S3 with
content-hashed assets and invalidates CloudFront; the clobber guard blocks a sync from a
checkout behind `origin/main` (override `ALLOW_STALE_SITE=1` for an intentional rollback).

### Mode 2: `layer` / `fleet`
The shared layer is RETIRED (#781): shared modules ship inside every function's
code bundle (`deploy/build_bundle.py` — the one staging implementation used by
CDK, `deploy_lambda.sh`, `deploy_fleet.sh`, and `deploy_site_api.sh`). To push a
shared-module change to every function:
```bash
bash deploy/deploy_fleet.sh          # one bundle → S3 → every function
```
(or `cd cdk && npx cdk deploy --all`, which ships the same staged bundle).

### Mode 3: Lambda function (anything else)
Match the argument against the function-name mapping below using fuzzy matching (e.g., "whoop" matches "whoop-data-ingestion", "site-api" matches "life-platform-site-api"). If ambiguous, list the matches and ask which one.

**Deploy command:**
```bash
bash deploy/deploy_and_verify.sh <function-name> lambdas/<source-file>
```

**Special case — `life-platform-mcp`:**
`deploy_lambda.sh life-platform-mcp mcp_server.py` now builds the correct
mcp-shaped bundle automatically (full tree + `mcp_server.py` + `mcp/` via
`build_bundle.py --mcp` — `reading/`, the hevy modules, and every shared module
are inside; there is no layer). Verify it BOOTS after deploy (statusCode 401 =
auth gate = healthy import):
```bash
sleep 7
aws lambda invoke --function-name life-platform-mcp --region us-west-2 --cli-binary-format raw-in-base64-out \
  --payload '{"method":"tools/list","params":{}}' /tmp/mcp.json >/dev/null
python3 -c "import json; d=json.load(open('/tmp/mcp.json')); assert 'errorType' not in d, d; print('mcp OK', d.get('statusCode'))"
```

**Special case — `life-platform-site-api`:**
```bash
bash deploy/deploy_site_api.sh        # full bundle + invoke-verify a real route
```
(#781: the script ships the same full-tree bundle as CDK — web/ siblings,
reading/, methods_registry, and every shared module included. The old
single-file / partial-zip import breaks are structurally dead. #794 ownership:
CDK — LifePlatformOperational — owns the function's infra (role, env, alarms);
this script is the sanctioned fast code path. `tests/test_deploy_bundle_paths.py`
enforces both channels stay on `deploy/build_bundle.py`.)

## Function Name → Source File Mapping

**Ingestion:**
- whoop-data-ingestion → whoop_lambda.py
- garmin-data-ingestion → garmin_lambda.py
- notion-journal-ingestion → notion_lambda.py
- withings-data-ingestion → withings_lambda.py
- habitify-data-ingestion → habitify_lambda.py
- strava-data-ingestion → strava_lambda.py
- journal-enrichment → journal_enrichment_lambda.py
- todoist-data-ingestion → todoist_lambda.py
- eightsleep-data-ingestion → eightsleep_lambda.py
- activity-enrichment → enrichment_lambda.py
- macrofactor-data-ingestion → macrofactor_lambda.py
- weather-data-ingestion → weather_handler.py
- dropbox-poll → dropbox_poll_lambda.py
- apple-health-ingestion → apple_health_lambda.py
- food-delivery-ingestion → food_delivery_lambda.py
- measurements-ingestion → measurements_ingestion_lambda.py
- health-auto-export-webhook → health_auto_export_lambda.py

**Compute:**
- anomaly-detector → anomaly_detector_lambda.py
- character-sheet-compute → character_sheet_lambda.py
- daily-metrics-compute → daily_metrics_compute_lambda.py
- daily-insight-compute → daily_insight_compute_lambda.py
- adaptive-mode-compute → adaptive_mode_lambda.py
- hypothesis-engine → hypothesis_engine_lambda.py
- weekly-correlation-compute → weekly_correlation_compute_lambda.py
- dashboard-refresh → dashboard_refresh_lambda.py
- acwr-compute → acwr_compute_lambda.py
- circadian-compliance → circadian_compliance_lambda.py
- failure-pattern-compute → failure_pattern_compute_lambda.py
- challenge-generator → challenge_generator_lambda.py

**Email:**
- daily-brief → daily_brief_lambda.py
- weekly-digest → weekly_digest_lambda.py
- monthly-digest → monthly_digest_lambda.py
- nutrition-review → nutrition_review_lambda.py
- wednesday-chronicle → wednesday_chronicle_lambda.py
- weekly-plate → weekly_plate_lambda.py
- monday-compass → monday_compass_lambda.py
- partner-weekly-email → partner_email_lambda.py
- evening-nudge → evening_nudge_lambda.py
- chronicle-email-sender → chronicle_email_sender_lambda.py
- chronicle-approve → chronicle_approve_lambda.py
- subscriber-onboarding → subscriber_onboarding_lambda.py

**Operational:**
- life-platform-freshness-checker → freshness_checker_lambda.py
- life-platform-dlq-consumer → dlq_consumer_lambda.py
- life-platform-canary → canary_lambda.py
- life-platform-pip-audit → pip_audit_lambda.py
- life-platform-qa-smoke → qa_smoke_lambda.py
- life-platform-key-rotator → key_rotator_lambda.py
- life-platform-data-export → data_export_lambda.py
- life-platform-data-reconciliation → data_reconciliation_lambda.py
- insight-email-parser → insight_email_parser_lambda.py
- life-platform-site-api → SPECIAL BUILD — full-tree bundle via `deploy_site_api.sh` (see Special case above; NOT single-file)
- life-platform-site-api-ai → site_api_ai_lambda.py
- site-stats-refresh → site_stats_refresh_lambda.py
- pipeline-health-check → pipeline_health_check_lambda.py
- email-subscriber → email_subscriber_lambda.py
- og-image-generator → og_image_lambda.py

**Special:**
- life-platform-mcp → SPECIAL BUILD (see above)

## Doc impact (wiki contract — CONVENTIONS §8)

A deploy that changes behavior usually invalidates a wiki page. Before closing the loop:
name the affected canonical docs and update them (or state "docs: none needed — <reason>"
in the session log). If the deploy RETIRED something, add a tombstone rule to
`docs/_lint/tombstones.txt`. The wrap skill's step (e) enforces this at session end —
doing it at deploy time is cheaper.
