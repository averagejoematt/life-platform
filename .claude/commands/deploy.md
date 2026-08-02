Deploy a Lambda function, the site, or the fleet (one full-tree bundle, #781).

## Arguments: $ARGUMENTS

## Instructions

Parse `$ARGUMENTS` to determine what to deploy. Support these modes:

### Mode 1: `site`
**The canonical site-deploy rule lives in `docs/CONVENTIONS.md` §2 — read that; this is a
pointer, not a restatement.** In short (#750, 2026-07-09): a push to `main` touching
`site/**` deploys the merged `main` tree automatically via
`.github/workflows/site-deploy.yml` — OIDC deploy role → `bash deploy/deploy_site.sh`
(wraps `sync_site_to_s3.sh` + the explicit fonts sync), then the `smoke_test_site.sh` +
visual/AI-QA gates, with `bash deploy/rollback_site.sh HEAD~1` auto-rollback on a red.

**This is a SEPARATE workflow from `ci-cd.yml` and deliberately has NO `production`
approval gate** — do NOT wait for an approval that never comes, and watch
`site-deploy.yml` (not `ci-cd.yml`'s deploy job) for the QA/rollback verdict. "Merged but
not deployed" was the drift class this kills, so the merge IS the deploy. Prefer this.

**Attended fallback (documented, not the default):** `bash deploy/sync_site_to_s3.sh` —
content-hashed assets + self-invalidation, for an out-of-band hotfix or when CI is
unavailable; its clobber guard blocks a sync from a checkout behind `origin/main`
(override `ALLOW_STALE_SITE=1` for an intentional rollback).

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
Match the argument against the function-name mapping below using fuzzy matching (e.g., "whoop" matches "whoop-data-ingestion", "site-api" matches "life-platform-site-api"). If ambiguous, list the matches and ask which one. The table is GENERATED from `ci/lambda_map.json` (the same map CI and `deploy_lambda.sh` resolve from) — if a function isn't listed, check the map directly; never hand-edit the block.

**Deploy command:**
```bash
bash deploy/deploy_and_verify.sh <function-name> <source-path from the table>
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
CDK — `LifePlatformServe` (`cdk/stacks/serve_stack.py`, split from Operational by
#793, 2026-07-08) — owns the function's infra (role, env, alarms); this script is
the sanctioned fast code path. `tests/test_deploy_bundle_paths.py` enforces both
channels stay on `deploy/build_bundle.py`.)

## Function Name → Source File Mapping

Generated from `ci/lambda_map.json` by `deploy/sync_deploy_doc_map.py` (#2005);
`tests/test_deploy_doc_map.py` reds CI if this block drifts from the map.

<!-- BEGIN GENERATED: deploy-doc-map -->
<!-- Regenerate: python3 deploy/sync_deploy_doc_map.py   (never hand-edit this block)
     Source of truth: ci/lambda_map.json — drift gate: tests/test_deploy_doc_map.py -->

**Ingestion** (`lambdas/ingestion/`):
- activity-enrichment → `lambdas/ingestion/enrichment_lambda.py`
- dropbox-poll → `lambdas/ingestion/dropbox_poll_lambda.py`
- eightsleep-data-ingestion → `lambdas/ingestion/eightsleep_lambda.py`
- food-delivery-ingestion → `lambdas/ingestion/food_delivery_lambda.py`
- garmin-data-ingestion → `lambdas/ingestion/garmin_lambda.py`
- habitify-data-ingestion → `lambdas/ingestion/habitify_lambda.py`
- health-auto-export-webhook → `lambdas/ingestion/health_auto_export_lambda.py` (cdk_only†)
- hevy-backfill → `lambdas/ingestion/hevy_backfill_lambda.py` (cdk_only†)
- journal-enrichment → `lambdas/ingestion/journal_enrichment_lambda.py`
- macrofactor-data-ingestion → `lambdas/ingestion/macrofactor_lambda.py`
- measurements-ingestion → `lambdas/ingestion/measurements_ingestion_lambda.py`
- notion-journal-ingestion → `lambdas/ingestion/notion_lambda.py`
- social-enrichment → `lambdas/ingestion/social_enrichment_lambda.py`
- strava-data-ingestion → `lambdas/ingestion/strava_lambda.py`
- todoist-data-ingestion → `lambdas/ingestion/todoist_lambda.py`
- weather-data-ingestion → `lambdas/ingestion/weather_lambda.py`
- whoop-data-ingestion → `lambdas/ingestion/whoop_lambda.py`
- withings-data-ingestion → `lambdas/ingestion/withings_lambda.py`
- youtube-social-ingestion → `lambdas/ingestion/youtube_lambda.py`

**Compute** (`lambdas/compute/`):
- acwr-compute → `lambdas/compute/acwr_compute_lambda.py`
- adaptive-mode-compute → `lambdas/compute/adaptive_mode_lambda.py`
- character-sheet-compute → `lambdas/compute/character_sheet_lambda.py`
- circadian-compliance → `lambdas/compute/circadian_compliance_lambda.py`
- coach-daily-reflection → `lambdas/compute/coach_daily_reflection_lambda.py`
- coach-memoir → `lambdas/compute/coach_memoir_lambda.py`
- daily-insight-compute → `lambdas/compute/daily_insight_compute_lambda.py`
- daily-metrics-compute → `lambdas/compute/daily_metrics_compute_lambda.py`
- dashboard-refresh → `lambdas/compute/dashboard_refresh_lambda.py`
- episode-detect → `lambdas/compute/episode_detect_lambda.py`
- failure-pattern-compute → `lambdas/compute/failure_pattern_compute_lambda.py`
- forecast-engine → `lambdas/compute/forecast_engine_lambda.py`
- hypothesis-engine → `lambdas/compute/hypothesis_engine_lambda.py`
- personal-baselines-compute → `lambdas/compute/personal_baselines_lambda.py`
- scenario-explorer → `lambdas/compute/scenario_explorer_lambda.py` (cdk_only†)
- state-of-matthew → `lambdas/compute/state_of_matthew_lambda.py`
- weekly-correlation-compute → `lambdas/compute/weekly_correlation_compute_lambda.py`
- weekly-signal → `lambdas/compute/weekly_signal_lambda.py`

**Coach** (`lambdas/coach/`):
- coach-computation-engine → `lambdas/coach/coach_computation_engine.py`
- coach-ensemble-digest → `lambdas/coach/coach_ensemble_digest.py`
- coach-history-summarizer → `lambdas/coach/coach_history_summarizer.py`
- coach-narrative-orchestrator → `lambdas/coach/coach_narrative_orchestrator.py`
- coach-observatory-renderer → `lambdas/coach/coach_observatory_renderer.py`
- coach-prediction-evaluator → `lambdas/coach/coach_prediction_evaluator.py`
- coach-quality-gate → `lambdas/coach/coach_quality_gate.py`
- coach-state-updater → `lambdas/coach/coach_state_updater.py`
- inter-coach-dialogue → `lambdas/coach/inter_coach_dialogue_lambda.py` (cdk_only†)
- voice-fidelity-harness → `lambdas/coach/voice_fidelity_harness.py` (cdk_only†)

**Emails** (`lambdas/emails/`):
- ai-review-pack → `lambdas/emails/ai_review_pack_lambda.py`
- anomaly-detector → `lambdas/emails/anomaly_detector_lambda.py`
- between-chronicle → `lambdas/emails/between_chronicle_lambda.py`
- chronicle-approve → `lambdas/emails/chronicle_approve_lambda.py`
- chronicle-email-sender → `lambdas/emails/chronicle_email_sender_lambda.py`
- chronicle-podcast → `lambdas/emails/chronicle_podcast_lambda.py`
- coach-nudge → `lambdas/emails/coach_nudge_lambda.py`
- coach-panel-podcast → `lambdas/emails/coach_panel_podcast_lambda.py` (cdk_only†)
- daily-brief → `lambdas/emails/daily_brief_lambda.py`
- daily-debrief → `lambdas/emails/daily_debrief_lambda.py`
- elena-state-updater → `lambdas/emails/elena_state_updater.py`
- evening-nudge → `lambdas/emails/evening_nudge_lambda.py`
- insight-email-parser → `lambdas/emails/insight_email_parser_lambda.py`
- life-platform-freshness-checker → `lambdas/emails/freshness_checker_lambda.py`
- milestone-digest → `lambdas/emails/milestone_digest_lambda.py`
- monday-compass → `lambdas/emails/monday_compass_lambda.py`
- monthly-digest → `lambdas/emails/monthly_digest_lambda.py`
- nutrition-review → `lambdas/emails/nutrition_review_lambda.py`
- partner-weekly-email → `lambdas/emails/partner_email_lambda.py`
- wednesday-chronicle → `lambdas/emails/wednesday_chronicle_lambda.py`
- weekly-digest → `lambdas/emails/weekly_digest_lambda.py`
- weekly-plate → `lambdas/emails/weekly_plate_lambda.py`

**Intelligence** (`lambdas/intelligence/`):
- ai-expert-analyzer → `lambdas/intelligence/ai_expert_analyzer_lambda.py`
- challenge-generator → `lambdas/intelligence/challenge_generator_lambda.py`
- field-notes-generate → `lambdas/intelligence/field_notes_lambda.py`
- journal-analyzer → `lambdas/intelligence/journal_analyzer_lambda.py`

**Operational** (`lambdas/operational/`):
- hevy-restamp → `lambdas/operational/hevy_restamp_lambda.py` (cdk_only†)
- hevy-routine-cron → `lambdas/operational/hevy_routine_cron_lambda.py` (cdk_only†)
- life-platform-ai-quality-canary → `lambdas/operational/ai_quality_canary_lambda.py`
- life-platform-alert-digest → `lambdas/operational/alert_digest_lambda.py`
- life-platform-canary → `lambdas/operational/canary_lambda.py`
- life-platform-coherence-sentinel → `lambdas/operational/coherence_sentinel_lambda.py`
- life-platform-cost-governor → `lambdas/operational/cost_governor_lambda.py`
- life-platform-data-export → `lambdas/operational/data_export_lambda.py`
- life-platform-data-reconciliation → `lambdas/operational/data_reconciliation_lambda.py`
- life-platform-delete-user-data → `lambdas/operational/delete_user_data_lambda.py`
- life-platform-dlq-consumer → `lambdas/operational/dlq_consumer_lambda.py`
- life-platform-key-rotator → `lambdas/operational/key_rotator_lambda.py`
- life-platform-pip-audit → `lambdas/operational/pip_audit_lambda.py`
- life-platform-qa-smoke → `lambdas/operational/qa_smoke_lambda.py`
- life-platform-remediation-dispatcher → `lambdas/operational/remediation_dispatcher_lambda.py`
- life-platform-traffic-digest → `lambdas/operational/traffic_digest_lambda.py`
- pipeline-health-check → `lambdas/operational/pipeline_health_check_lambda.py`

**Reading** (`lambdas/reading/`):
- reading-cover-pipeline → `lambdas/reading/cover_pipeline_lambda.py`
- reading-recall-sweep → `lambdas/reading/reading_recall_sweep_lambda.py`

**Web** (`lambdas/web/`):
- email-subscriber → `lambdas/web/email_subscriber_lambda.py` (region: us-east-1)
- life-platform-site-api → SPECIAL BUILD — `bash deploy/deploy_site_api.sh` (see Special case above)
- life-platform-site-api-ai → `lambdas/web/site_api_ai_lambda.py`
- og-image-generator → `lambdas/web/og_image_lambda.py`
- site-stats-refresh → `lambdas/web/site_stats_refresh_lambda.py`
- subscriber-onboarding → `lambdas/web/subscriber_onboarding_lambda.py`

**Special:**
- life-platform-mcp → `mcp_server.py` + `mcp/` — SPECIAL BUILD (see above)

**Lambda@Edge (manually deployed, NOT CI/CD — see the map's notes):**
- life-platform-cf-auth → `lambdas/cf-auth/index.mjs` (region: us-east-1)

† `cdk_only` is a historical annotation in the map: since #781 every sanctioned deploy path
ships the same full-tree bundle, so these deploy fine via `deploy_and_verify.sh` too.
<!-- END GENERATED: deploy-doc-map -->

## Doc impact (wiki contract — CONVENTIONS §8)

A deploy that changes behavior usually invalidates a wiki page. Before closing the loop:
name the affected canonical docs and update them (or state "docs: none needed — <reason>"
in the session log). If the deploy RETIRED something, add a tombstone rule to
`docs/_lint/tombstones.txt`. The wrap skill's step (e) enforces this at session end —
doing it at deploy time is cheaper.
