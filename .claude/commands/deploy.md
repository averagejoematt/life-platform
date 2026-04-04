Deploy a Lambda function, the site, or the shared layer.

## Arguments: $ARGUMENTS

## Instructions

Parse `$ARGUMENTS` to determine what to deploy. Support these modes:

### Mode 1: `site`
Run: `bash deploy/deploy_site.sh`
This syncs the site/ directory to S3 with content-hashed assets and invalidates CloudFront.

### Mode 2: `layer`
Run: `bash deploy/build_layer.sh`
Then report the module count and remind the user to run `cd cdk && npx cdk deploy --all` to publish the new layer version.

### Mode 3: Lambda function (anything else)
Match the argument against the function-name mapping below using fuzzy matching (e.g., "whoop" matches "whoop-data-ingestion", "site-api" matches "life-platform-site-api"). If ambiguous, list the matches and ask which one.

**Before deploying any Lambda**, check if any shared layer module was modified more recently than `cdk/layer-build/python/`. The layer modules are: retry_utils.py, board_loader.py, insight_writer.py, scoring_engine.py, character_engine.py, output_writers.py, ai_calls.py, html_builder.py, ai_output_validator.py, platform_logger.py, ingestion_framework.py, ingestion_validator.py, item_size_guard.py, digest_utils.py, sick_day_checker.py, site_writer.py. Check with:
```bash
# Find newest layer module modification time vs last layer build
NEWEST_MOD=$(stat -f %m lambdas/ai_calls.py lambdas/output_writers.py lambdas/scoring_engine.py lambdas/board_loader.py lambdas/html_builder.py lambdas/retry_utils.py lambdas/insight_writer.py lambdas/character_engine.py lambdas/ai_output_validator.py lambdas/platform_logger.py lambdas/ingestion_framework.py lambdas/ingestion_validator.py lambdas/item_size_guard.py lambdas/digest_utils.py lambdas/sick_day_checker.py lambdas/site_writer.py 2>/dev/null | sort -rn | head -1)
LAYER_BUILD=$(stat -f %m cdk/layer-build/python/ai_calls.py 2>/dev/null || echo 0)
```
If `NEWEST_MOD > LAYER_BUILD`, warn: "Shared layer modules have changed since last build. Run `/deploy layer` first, then `cd cdk && npx cdk deploy --all` to publish the new layer version."

**Deploy command:**
```bash
bash deploy/deploy_and_verify.sh <function-name> lambdas/<source-file>
```

**Special case — `life-platform-mcp`:**
Do NOT use deploy_lambda.sh. Instead:
```bash
ZIP=/tmp/mcp_deploy.zip
rm -f $ZIP
zip -j $ZIP mcp_server.py mcp_bridge.py
zip -r $ZIP mcp/ -x 'mcp/__pycache__/*' 'mcp/*.pyc'
aws lambda update-function-code --function-name life-platform-mcp --zip-file fileb://$ZIP --region us-west-2
```

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
- sleep-reconciler → sleep_reconciler_lambda.py
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
- brittany-weekly-email → brittany_email_lambda.py
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
- life-platform-site-api → site_api_lambda.py
- life-platform-site-api-ai → site_api_ai_lambda.py
- site-stats-refresh → site_stats_refresh_lambda.py
- pipeline-health-check → pipeline_health_check_lambda.py
- email-subscriber → email_subscriber_lambda.py
- og-image-generator → og_image_lambda.py

**Special:**
- life-platform-mcp → SPECIAL BUILD (see above)
