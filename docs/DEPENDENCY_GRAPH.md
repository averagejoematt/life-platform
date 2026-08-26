# Life Platform — Dependency Graph

> **Status:** canonical · **Owner:** Matthew · **GENERATED — do not hand-edit.**
> This document is a rendering of `model/platform_model.json` (#2845), produced by
> `scripts/generate_platform_model.py` and drift-gated by `tests/test_platform_model_drift.py`:
> CI regenerates and diffs both artifacts on every run, so a hand-edit or a stale commit
> fails the build. Blast-radius queries: `python3 scripts/blast_radius.py --touches <partition>`
> / `--feeds <module>`. Scope cuts are stated in the model's `meta.scope_cuts` and §6 below.

## 1. Scheduled Lambdas (CDK ground truth)

Crons are the CDK `schedule=` strings (fixed UTC, no DST drift); `resolved` = an
f-string schedule resolved through module constants; `constructed` = built from a
`Schedule.cron(...)` keyword form. Multi-schedule lambdas show every schedule.

| Lambda | Stack | Schedule (UTC) | Resolution |
|--------|-------|----------------|------------|
| `activity-enrichment` | ingestion_stack | `cron(30 15 * * ? *)` | constant |
| `acwr-compute` | compute_stack | `cron(55 16 * * ? *)` | constant |
| `adaptive-mode-compute` | compute_stack | `cron(35 16 * * ? *)` | constant |
| `ai-expert-analyzer` | compute_stack | `cron(0 14 * * ? *)` | constant |
| `ai-review-pack` | email_stack | `cron(0 18 ? * SUN *)` | constant |
| `anomaly-detector` | compute_stack | `cron(5 15 * * ? *)` | constant |
| `between-chronicle` | email_stack | `cron(0 17 ? * SUN *)` | constant |
| `bluesky-social-ingestion` | ingestion_stack | `cron(0 0,1,2,3,4,5,12,13,14,15,16,17,18,19,20,21,22,23 * * ? *)` | resolved |
| `challenge-generator` | compute_stack | `cron(0 22 ? * SUN *)` | constant |
| `character-sheet-compute` | compute_stack | `cron(30 16 * * ? *)` | constant |
| `chronicle-approve` | email_stack | `cron(0 18 * * ? *)` | constant |
| `chronicle-email-sender` | email_stack | `cron(10 15 ? * WED *)` | constant |
| `circadian-compliance` | compute_stack | `cron(0 2 * * ? *)` | constant |
| `coach-daily-reflection` | compute_stack | `cron(0 19 * * ? *)` | constant |
| `coach-history-summarizer` | compute_stack | `cron(0 17 ? * SUN *)` | constant |
| `coach-memoir` | compute_stack | `cron(0 15 1 1,4,7,10 ? *)` | constant |
| `coach-nudge` | email_stack | `cron(10 0-5,15-23 * * ? *)` | constant |
| `coach-panel-podcast` | email_stack | `cron(0 18 * * MON,WED *)` | constructed |
| `coach-prediction-evaluator` | compute_stack | `cron(0 16 * * ? *)` | constant |
| `daily-brief` | email_stack | `cron(0 17 * * ? *)` | constant |
| `daily-debrief` | email_stack | `cron(0 19 * * ? *)` | constant |
| `daily-insight-compute` | compute_stack | `cron(45 16 * * ? *)` | constant |
| `daily-metrics-compute` | compute_stack | `cron(40 16 * * ? *)` | constant |
| `dashboard-refresh` | compute_stack | `cron(0 1 * * ? *)` + `cron(0 21 * * ? *)` | constant, constant |
| `dropbox-poll` | ingestion_stack | `rate(30 minutes)` | constant |
| `eightsleep-data-ingestion` | ingestion_stack | `cron(15 0,1,2,3,4,5,12,13,14,15,16,17,18,19,20,21,22,23 * * ? *)` | resolved |
| `episode-detect` | compute_stack | `cron(0 17 ? * SUN *)` | constant |
| `evening-nudge` | email_stack | `cron(0 3 * * ? *)` | constant |
| `failure-pattern-compute` | compute_stack | `cron(50 17 ? * SUN *)` | constant |
| `field-notes-generate` | compute_stack | `cron(0 18 ? * SUN *)` | constant |
| `forecast-engine` | compute_stack | `cron(50 16 * * ? *)` | constant |
| `habitify-data-ingestion` | ingestion_stack | `cron(5 0,1,2,3,4,5,12,13,14,15,16,17,18,19,20,21,22,23 * * ? *)` | resolved |
| `hevy-backfill` | ingestion_stack | `cron(0 12-23 * * ? *)` | constant |
| `hevy-restamp` | operational_stack | `cron(0 18 * * ? *)` | constant |
| `hevy-routine-cron` | operational_stack | `cron(30 13 ? * SUN *)` | constant |
| `hypothesis-engine` | compute_stack | `cron(0 19 ? * SUN *)` | constant |
| `inter-coach-dialogue` | compute_stack | `cron(0 18 ? * SUN *)` | constant |
| `journal-analyzer` | compute_stack | `cron(0 10 * * ? *)` | constant |
| `journal-enrichment` | ingestion_stack | `cron(30 14 * * ? *)` | constant |
| `life-platform-ai-quality-canary` | operational_stack | `cron(20 16 ? * MON,WED,FRI *)` | constant |
| `life-platform-alert-digest` | operational_stack | `cron(0 15 * * ? *)` | constant |
| `life-platform-canary` | operational_stack | `rate(4 hours)` | constant |
| `life-platform-coherence-sentinel` | operational_stack | `cron(45 18 ? * * *)` | constant |
| `life-platform-cost-governor` | operational_stack | `cron(0 0/8 * * ? *)` | constant |
| `life-platform-data-reconciliation` | operational_stack | `cron(30 7 ? * MON *)` | constant |
| `life-platform-delete-user-data` | operational_stack | `cron(0 8 ? * MON *)` | constant |
| `life-platform-dlq-consumer` | operational_stack | `rate(6 hours)` | constant |
| `life-platform-freshness-checker` | operational_stack | `cron(45 16 * * ? *)` | constant |
| `life-platform-permanence` | operational_stack | `cron(0 6 * * ? *)` | constant |
| `life-platform-pip-audit` | operational_stack | `cron(0 17 ? * MON *)` | constant |
| `life-platform-qa-smoke` | operational_stack | `cron(30 18 ? * * *)` | constant |
| `life-platform-traffic-digest` | operational_stack | `cron(0 16 ? * MON *)` | constant |
| `mastodon-social-ingestion` | ingestion_stack | `cron(0 0,1,2,3,4,5,12,13,14,15,16,17,18,19,20,21,22,23 * * ? *)` | resolved |
| `milestone-digest` | email_stack | `cron(15 17 * * ? *)` | constant |
| `monday-compass` | email_stack | `cron(0 15 ? * MON *)` | constant |
| `monthly-digest` | email_stack | `cron(0 16 ? * 1#1 *)` | constant |
| `notion-journal-ingestion` | ingestion_stack | `cron(0 0,1,2,3,4,5,12,13,14,15,16,17,18,19,20,21,22,23 * * ? *)` | resolved |
| `nutrition-review` | email_stack | `cron(0 17 ? * SAT *)` | constant |
| `og-image-generator` | operational_stack | `cron(30 19 * * ? *)` | constant |
| `partner-weekly-email` | email_stack | `cron(30 17 ? * 1 *)` | constant |
| `personal-baselines-compute` | compute_stack | `cron(0 8 1 * ? *)` | constant |
| `pipeline-health-check` | operational_stack | `cron(10 17 * * ? *)` + `cron(30 2,6,14,18,22 * * ? *)` + `cron(58 16 * * ? *)` | constructed, constant, constructed |
| `reading-recall-sweep` | operational_stack | `cron(0 16 * * ? *)` | constant |
| `scenario-explorer` | compute_stack | `cron(10 12 * * ? *)` | constant |
| `site-stats-refresh` | operational_stack | `cron(0 * * * ? *)` | constructed |
| `social-enrichment` | ingestion_stack | `cron(45 14 * * ? *)` | constant |
| `state-of-matthew` | compute_stack | `cron(30 19 ? * SUN *)` | constant |
| `strava-data-ingestion` | ingestion_stack | `cron(10 0,1,2,3,4,5,12,13,14,15,16,17,18,19,20,21,22,23 * * ? *)` + `cron(20 17 * * ? *)` | resolved, constructed |
| `subscriber-onboarding` | email_stack | `cron(5 17 * * ? *)` | constant |
| `telegram-coach-worker` | serve_stack | `cron(0 16 * * ? *)` + `cron(15 17 ? * MON-FRI *)` | constant, constant |
| `todoist-data-ingestion` | ingestion_stack | `cron(0 14 * * ? *)` | constant |
| `voice-fidelity-harness` | compute_stack | `cron(0 15 1 * ? *)` | constant |
| `weather-data-ingestion` | ingestion_stack | `cron(0 14,2 * * ? *)` | constant |
| `wednesday-chronicle` | email_stack | `cron(0 15 ? * WED *)` | constant |
| `weekly-correlation-compute` | compute_stack | `cron(30 18 ? * SUN *)` | constant |
| `weekly-digest` | email_stack | `cron(0 16 ? * SUN *)` | constant |
| `weekly-plate` | email_stack | `cron(0 2 ? * SAT *)` | constant |
| `weekly-signal` | email_stack | `cron(30 16 ? * SUN *)` | constant |
| `whoop-data-ingestion` | ingestion_stack | `cron(0 0,4,12,16,20 * * ? *)` + `cron(20 18 * * ? *)` + `cron(30 17 * * ? *)` | resolved, constructed, constant |
| `withings-data-ingestion` | ingestion_stack | `cron(5 0,1,2,3,4,5,12,13,14,15,16,17,18,19,20,21,22,23 * * ? *)` | resolved |
| `youtube-social-ingestion` | ingestion_stack | `cron(0 0,1,2,3,4,5,12,13,14,15,16,17,18,19,20,21,22,23 * * ? *)` | resolved |

**Unscheduled lambdas (23)** — webhook/S3-trigger/invoked-on-demand: `chronicle-podcast`, `coach-computation-engine`, `coach-ensemble-digest`, `coach-narrative-orchestrator`, `coach-observatory-renderer`, `coach-quality-gate`, `coach-state-updater`, `elena-state-updater`, `email-subscriber`, `food-delivery-ingestion`, `garmin-data-ingestion`, `health-auto-export-webhook`, `insight-email-parser`, `life-platform-data-export`, `life-platform-key-rotator`, `life-platform-og-image`, `life-platform-remediation-dispatcher`, `life-platform-site-api`, `life-platform-site-api-ai`, `macrofactor-data-ingestion`, `measurements-ingestion`, `reading-cover-pipeline`, `telegram-webhook`

## 2. DynamoDB Partitions (ADR-077 census)

### cross_phase (15)

`benchmarks`, `calibration`, `chronicling`, `coach_corrections`, `dexa`, `effect_fits`, `eyeball_estimate`, `genome`, `labs`, `milestones`, `recall_embeddings`, `subscribers`, `supplements`, `training_reference`, `weight_episodes`

### experiment_scoped (33)

`achievements`, `adaptive_mode`, `ai_analysis`, `anomalies`, `centenarian_progress`, `challenges`, `character_receipt`, `character_sheet`, `chronicle`, `circadian`, `coach_actions`, `computed_insights`, `computed_metrics`, `decisions`, `diary_claims`, `diary_reactions`, `discovery_annotations`, `engagement_state`, `experiments`, `field_notes`, `forecast`, `habit_scores`, `hypotheses`, `insights`, `ledger`, `nutrition_review`, `panelcast`, `protocols`, `rewards`, `scenarios`, `state_of_matthew`, `weekly_correlations`, `what_changed`

### raw_timeseries (41)

`apple_health`, `bluesky`, `day_grade`, `eightsleep`, `evening_ritual`, `exposures`, `felt_probe`, `flourishing`, `food_delivery`, `food_responses`, `garmin`, `habit_causality`, `habitify`, `hevy`, `instagram`, `interactions`, `journal_quotes`, `life_events`, `macrofactor`, `macrofactor_meals`, `macrofactor_workouts`, `mastodon`, `measurements`, `mood`, `notion`, `private_intake`, `ruck_log`, `sick_days`, `state_of_mind`, `strava`, `temptations`, `tiktok`, `time_affluence`, `todoist`, `training_notes`, `travel`, `weather`, `whoop`, `withings`, `x`, `youtube`

### system_state (16)

`coach_gen_cache`, `composite_scores`, `deletion_log`, `dropbox_tracker`, `email_digest`, `email_log`, `experiment_suggestions`, `google_calendar`, `health_check`, `hevy_id_map`, `ingest_liveness`, `journal_analysis`, `personal_baselines`, `qa_predict_dark`, `routine_index`, `sleep_unified`

## 3. Consumer Edges (module → partition)

666 edges from the two-pass AST sweep (#2805 mechanism). Directions:
`read` (query/get/seam call), `write` (put/update/delete), `unknown` (partition
reference outside a recognized call). Site resolution is counted in §6 — a partition
built from a runtime variable is tagged dynamic in the model, never guessed.

### Writers and readers per partition

| Partition | Writers | Readers |
|-----------|---------|---------|
| `achievements` | — | — |
| `adaptive_mode` | adaptive_mode_lambda.py | tools_coach_checkin.py, tools_reading.py |
| `ai_analysis` | ai_expert_analyzer_lambda.py | ai_expert_analyzer_lambda.py, chronicle_data.py, coherence_sentinel_lambda.py, site_api_coach_narrative.py, site_api_coach_stance.py, state_of_matthew_lambda.py |
| `anomalies` | anomaly_detector_lambda.py | anomaly_detector_lambda.py, daily_brief_lambda.py |
| `apple_health` | freshness_checker_lambda.py, health_auto_export_lambda.py | ai_expert_analyzer_lambda.py, evening_nudge_lambda.py, freshness_checker_lambda.py, health_auto_export_lambda.py, qa_smoke_lambda.py, site_api_biomarkers.py, site_api_body.py, site_api_fingerprint.py, site_api_freshness.py, site_api_journey.py, site_api_meals.py, site_api_mind.py, site_api_physical.py, site_api_pulse.py, site_api_rollups.py, site_api_sleep.py, site_api_training.py, site_stats_refresh_lambda.py, tools_cgm.py, tools_health.py, tools_lifestyle.py |
| `benchmarks` | — | site_api_training.py |
| `calibration` | — | state_of_matthew_lambda.py |
| `centenarian_progress` | weekly_correlation_compute_lambda.py | — |
| `challenges` | challenge_generator_lambda.py, character_sheet_lambda.py, site_api_social_challenges.py | challenge_generator_lambda.py, site_api_social_challenges.py |
| `character_receipt` | — | qa_smoke_lambda.py, site_api_character.py |
| `character_sheet` | — | challenge_generator_lambda.py, coherence_sentinel_lambda.py, field_notes_lambda.py, monday_compass_lambda.py, monthly_digest_lambda.py, site_api_ai_context.py, site_api_character.py, site_api_discovery.py, site_api_fulfillment.py, site_api_habits.py, site_api_journey.py, site_api_mind.py, site_api_rollups.py, site_stats_refresh_lambda.py, spiral_breaker.py |
| `chronicle` | chronicle_approve_lambda.py, chronicle_email_sender_lambda.py, chronicle_store.py | ask_retrieval.py, chronicle_approve_lambda.py, chronicle_data.py, chronicle_email_sender_lambda.py, chronicle_podcast_lambda.py, chronicle_store.py, coach_panel_podcast_lambda.py, site_api_coach_narrative.py, site_writer.py |
| `circadian` | circadian_compliance_lambda.py | — |
| `coach_actions` | intelligence_common.py | intelligence_common.py, site_api_lambda.py |
| `coach_corrections` | coach_corrections.py | coach_corrections.py |
| `coach_credibility` | — | intelligence_common.py |
| `coach_gen_cache` | generation_cache.py | generation_cache.py |
| `coach_thread` | training_notes.py | tools_coach_intelligence.py |
| `computed_insights` | daily_brief_lambda.py, daily_insight_compute_lambda.py | daily_insight_compute_lambda.py, weekly_signal_lambda.py |
| `computed_metrics` | acwr_compute_lambda.py, daily_metrics_compute_lambda.py | ai_calls.py, ai_expert_analyzer_lambda.py, ai_output_validator.py, anomaly_detector_lambda.py, coach_nudge_lambda.py, coherence_sentinel_lambda.py, daily_debrief_lambda.py, field_notes_lambda.py, monday_compass_lambda.py, site_api_discovery.py, site_api_habits.py, site_stats_refresh_lambda.py, tools_health.py, tools_training.py, weekly_digest_lambda.py |
| `day_grade` | daily_brief_lambda.py, daily_metrics_compute_lambda.py | adaptive_mode_lambda.py, coherence_sentinel_lambda.py, failure_pattern_compute_lambda.py, monday_compass_lambda.py |
| `decisions` | — | site_api_thirdwall.py |
| `deletion_log` | delete_user_data_lambda.py | — |
| `dexa` | — | ai_expert_analyzer_lambda.py, nutrition_review_lambda.py, site_api_physical.py |
| `diary_claims` | tools_journal.py | site_api_diary.py, tools_coach_intelligence.py |
| `diary_reactions` | coach_diary_reaction.py | coach_diary_reaction.py, site_api_thirdwall.py |
| `discovery_annotations` | — | site_api_journey.py |
| `dropbox_tracker` | dropbox_poll_lambda.py | dropbox_poll_lambda.py |
| `effect_fits` | — | — |
| `eightsleep` | — | ai_expert_analyzer_lambda.py, site_api_sleep.py, tools_nutrition.py, tools_training.py |
| `email_digest` | between_chronicle_lambda.py | between_chronicle_lambda.py |
| `email_log` | ai_review_pack_lambda.py, anomaly_detector_lambda.py, between_chronicle_lambda.py, chronicle_email_sender_lambda.py, chronicle_store.py, daily_brief_lambda.py, evening_nudge_lambda.py, insight_email_parser_lambda.py, milestone_digest_lambda.py, monday_compass_lambda.py, nutrition_review_lambda.py, partner_email_lambda.py, weekly_digest_lambda.py, weekly_plate_lambda.py, weekly_signal_lambda.py | ai_review_pack_lambda.py, anomaly_detector_lambda.py, between_chronicle_lambda.py, daily_brief_lambda.py, evening_nudge_lambda.py, insight_email_parser_lambda.py, milestone_digest_lambda.py, monday_compass_lambda.py, nutrition_review_lambda.py, partner_email_lambda.py, send_ledger.py, weekly_digest_lambda.py, weekly_plate_lambda.py, weekly_signal_lambda.py |
| `engagement_state` | adaptive_mode_lambda.py | ai_expert_analyzer_lambda.py, character_sheet_lambda.py, coach_chat_grounding.py, coach_panel_podcast_lambda.py, daily_brief_lambda.py, daily_debrief_lambda.py, monday_compass_lambda.py, monthly_digest_lambda.py, site_api_ai_context.py, site_api_freshness.py, state_of_matthew_lambda.py, tools_coach_checkin.py, weekly_digest_lambda.py |
| `evening_ritual` | — | site_api_fulfillment.py |
| `experiment_suggestions` | site_api_social_experiments.py | — |
| `experiments` | tools_lifestyle.py | ai_expert_analyzer_lambda.py, chronicle_data.py, coach_nudge_lambda.py, daily_insight_compute_lambda.py, site_api_discovery.py, site_api_journey.py, site_api_protocols.py, site_api_rollups.py, tools_lifestyle.py |
| `exposures` | — | — |
| `eyeball_estimate` | — | — |
| `felt_probe` | — | site_api_fulfillment.py |
| `field_notes` | field_notes_lambda.py, tools_lifestyle.py | ai_expert_analyzer_lambda.py, chronicle_data.py, field_notes_lambda.py, site_api_thirdwall.py, tools_lifestyle.py |
| `flourishing` | flourishing.py | site_api_fulfillment.py, theme_river.py, tools_journal.py |
| `food_delivery` | food_delivery_lambda.py | digest_utils.py, site_api_meals.py, site_api_nutrition.py |
| `food_responses` | — | — |
| `forecast` | forecast_engine_lambda.py | ai_calls.py, site_api_foresight.py, state_of_matthew_lambda.py |
| `garmin` | — | ai_expert_analyzer_lambda.py, intelligence_common.py, site_api_fingerprint.py, site_api_freshness.py, site_api_physical.py, site_api_pulse.py, site_api_training.py, site_api_vitals_depth.py, tools_health.py, tools_training.py |
| `genome` | — | nutrition_review_lambda.py, site_api_biomarkers.py |
| `habit_causality` | — | site_api_habits.py |
| `habit_scores` | daily_brief_lambda.py, daily_metrics_compute_lambda.py | adaptive_mode_lambda.py, coach_prediction_evaluator.py, failure_pattern_compute_lambda.py, monday_compass_lambda.py, site_api_ai_context.py, site_api_habits.py, site_api_mind.py |
| `habitify` | — | ai_expert_analyzer_lambda.py, intelligence_common.py, journal_analyzer_lambda.py, site_api_data.py, site_api_habits.py |
| `health_check` | pipeline_health_check_lambda.py | site_api_status.py |
| `hevy` | hevy_common.py | ai_expert_analyzer_lambda.py, daily_metrics_compute_lambda.py, site_api_pulse.py, site_api_training.py, tools_hevy_routine.py, tools_strength.py, tools_training_notes.py, training_notes.py, vacation_fund.py |
| `hevy_id_map` | routine_repo.py | routine_repo.py |
| `hypotheses` | hypothesis_engine_lambda.py | challenge_generator_lambda.py, hypothesis_engine_lambda.py, state_of_matthew_lambda.py, tools_lifestyle.py |
| `ingest_liveness` | pipeline_health_check_lambda.py | — |
| `insights` | insight_email_parser_lambda.py, tools_lifestyle.py | site_api_ledger.py, tools_lifestyle.py |
| `intelligence_quality` | — | site_api_foresight.py, tools_data.py |
| `interactions` | — | site_api_fulfillment.py, site_api_mind.py, tools_social.py |
| `journal` | — | site_api_rollups.py |
| `journal_analysis` | — | ai_expert_analyzer_lambda.py, hypothesis_engine_lambda.py, site_api_mind.py |
| `journal_quotes` | tools_journal.py | site_api_diary.py, site_api_thirdwall.py |
| `labs` | — | ai_expert_analyzer_lambda.py, nutrition_review_lambda.py |
| `ledger` | — | site_api_ledger.py |
| `life_events` | — | site_api_journey.py |
| `macrofactor` | — | ai_expert_analyzer_lambda.py, freshness_checker_lambda.py, site_api_body.py, site_api_meals.py, site_api_nutrition.py, site_api_pulse.py, site_api_rollups.py, site_api_sleep.py, site_stats_refresh_lambda.py, tools_labs.py, tools_nutrition.py, weekly_digest_extractors.py |
| `macrofactor_meals` | — | — |
| `macrofactor_workouts` | — | tools_training.py |
| `measurements` | measurements_ingestion_lambda.py | ai_expert_analyzer_lambda.py, site_api_physical.py |
| `milestones` | — | — |
| `notion` | freshness_checker_lambda.py, notion_lambda.py | adaptive_mode_lambda.py, circadian_compliance_lambda.py, daily_insight_compute_lambda.py, daily_metrics_compute_lambda.py, evening_nudge_lambda.py, field_notes_lambda.py, freshness_checker_lambda.py, intelligence_common.py, notion_lambda.py, site_api_fulfillment.py, site_api_mind.py, site_api_pulse.py, tools_journal.py, tools_social_connection.py |
| `nutrition_review` | nutrition_review_lambda.py | nutrition_review_lambda.py |
| `panelcast` | coach_panel_podcast_lambda.py, podcast_script_v2.py | coach_panel_podcast_lambda.py, podcast_script_v2.py, site_api_coach_ledger.py |
| `platform_memory` | daily_insight_compute_lambda.py, failure_pattern_compute_lambda.py, hypothesis_engine_lambda.py, weekly_plate_lambda.py | daily_insight_compute_lambda.py, weekly_plate_lambda.py |
| `private_intake` | — | intake_response.py |
| `protocols` | — | site_api_protocols.py |
| `qa_predict_dark` | qa_smoke_lambda.py | qa_smoke_lambda.py |
| `recall_embeddings` | — | — |
| `rewards` | — | — |
| `routine_index` | routine_repo.py | routine_repo.py, routine_title.py, site_api_protocols.py |
| `ruck_log` | — | — |
| `scenarios` | — | site_api_foresight.py |
| `sick_days` | sick_day_checker.py, tools_sick_days.py | sick_day_checker.py, tools_sick_days.py |
| `state_of_matthew` | — | site_api_foresight.py |
| `state_of_mind` | — | site_api_mind.py, site_api_pulse.py |
| `strava` | enrichment_lambda.py | ai_expert_analyzer_lambda.py, enrichment_lambda.py, intelligence_common.py, monthly_digest_lambda.py, site_api_autonomic.py, site_api_nutrition.py, site_api_physical.py, site_api_pulse.py, site_api_training.py, site_api_vitals_depth.py, site_stats_refresh_lambda.py, tools_benchmark.py, tools_correlation.py, tools_health.py, tools_nutrition.py, tools_training.py, vacation_fund.py |
| `subscribers` | canary_lambda.py, delete_user_data_lambda.py, email_subscriber_lambda.py | canary_lambda.py, delete_user_data_lambda.py, email_subscriber_lambda.py, site_api_social.py, site_api_social_engage.py, site_api_social_ladder.py, subscriber_onboarding_lambda.py, weekly_digest_lambda.py |
| `supplements` | habitify_lambda.py | habitify_lambda.py, site_api_protocols.py |
| `temptations` | — | site_api_mind.py |
| `time_affluence` | — | — |
| `todoist` | — | daily_insight_compute_lambda.py, intelligence_common.py, site_api_fulfillment.py, site_api_sleep.py, tools_todoist.py |
| `training_notes` | training_notes_llm.py | tools_training_notes.py, training_notes_llm.py |
| `training_reference` | — | site_api_nutrition.py, site_api_training.py |
| `travel` | — | adaptive_mode_lambda.py, anomaly_detector_lambda.py, tools_lifestyle.py |
| `weather` | tools_lifestyle.py | tools_lifestyle.py |
| `weekly_correlations` | weekly_correlation_compute_lambda.py | ai_expert_analyzer_lambda.py, daily_insight_compute_lambda.py, site_api_ai_context.py, site_api_discovery.py, site_api_journey.py, site_api_ledger.py, weekly_correlation_compute_lambda.py |
| `weight_episodes` | — | — |
| `what_changed` | weekly_correlation_compute_lambda.py | between_chronicle_lambda.py, site_api_ai_context.py, site_api_ledger.py, weekly_correlation_compute_lambda.py |
| `whoop` | whoop_lambda.py | ai_expert_analyzer_lambda.py, enrichment_lambda.py, failure_pattern_compute_lambda.py, hevy_restamp_lambda.py, intake_response.py, monday_compass_lambda.py, site_api_autonomic.py, site_api_body.py, site_api_fingerprint.py, site_api_freshness.py, site_api_lambda.py, site_api_nutrition.py, site_api_pulse.py, site_api_rollups.py, site_api_sleep.py, site_api_training.py, tools_health.py, tools_hevy_routine.py, tools_training.py, whoop_lambda.py |
| `withings` | — | adaptive_mode_lambda.py, ai_expert_analyzer_lambda.py, site_api_body.py, site_api_coach_profile.py, site_api_journey.py, site_api_nutrition.py, site_api_pulse.py, site_api_rollups.py, site_api_sleep.py, site_stats_refresh_lambda.py, tools_benchmark.py, tools_health.py, tools_nutrition.py |
| `zone2_efficiency` | weekly_correlation_compute_lambda.py | — |

## 4. MCP Layer

**76 tools across 26 modules** (AST-counted from `mcp/registry.py`;
the same counter `deploy/sync_doc_metadata.py` uses). MCP modules appear in §3 as
readers under the `life-platform-mcp` lambda.

## 4b. Producer/Consumer Contracts (#2847)

Pairs enrolled in the contract sweep: the real producer's output is round-tripped
through the real consumer, then a disagreement is injected into BOTH sides
(`tests/test_pair_contract_sweep_2847.py`). Enrolling a pair is one registry entry in
`tests/pair_contract_registry.py`. This lists what IS contracted — see `meta.scope_cuts`
for why it is not a census of every must-agree pair.

| Pair | Producer | Consumer | Partition | Mutations |
|------|----------|----------|-----------|-----------|
| adaptive_mode -> /api/ask grounding reads | `compute.adaptive_mode_lambda::store_adaptive_mode` | `web.site_api_ai_context::_ask_fetch_computed_reads` | `adaptive_mode` | 3 |
| ai_analysis EXPERT# -> observatory card journaling prompt | `intelligence.ai_expert_analyzer_lambda::generate_and_cache` | `coach.coach_observatory_renderer::journaling_prompt_for_domain` | `ai_analysis` | 3 |
| computed_metrics -> canonical facts | `compute.daily_metrics_compute_lambda::store_computed_metrics` | `experiment.canonical_facts::build_canonical_facts` | `computed_metrics` | 4 |
| computed_metrics -> site-stats-refresh tier0_streak | `compute.daily_metrics_compute_lambda::store_computed_metrics` | `web.site_stats_refresh_lambda::resolve_tier0_streak` | `computed_metrics` | 3 |
| engagement_state -> /api/presence | `content.engagement_core::compute_presence` | `web.site_api_freshness::presence` | `engagement_state` | 4 |
| input_manifest -> character page projection | `common.input_manifest::build_input_manifest` | `web.site_api_character::_public_input_manifest` | `computed_metrics` | 4 |
| public_stats.json -> fingerprint broadcast projection | `content.site_writer::write_public_stats` | `content.fingerprint_broadcast::project_public` | — | 4 |
| send_ledger row -> replay guard + status page | `common.send_ledger::record_sent` | `common.send_ledger::already_sent` | — | 3 |

## 5. Alarms + Routing

| Alarm | Stack | Routing |
|-------|-------|---------|
| `ai-tokens-platform-daily-total` | monitoring_stack | unresolved |
| `between-chronicle-scrub-failed-closed` | monitoring_silence_alarms | digest |
| `budget-tier-unreadable` | monitoring_budget_alarms | digest |
| `chronicle-delivery-heartbeat` | email_stack | urgent |
| `cost-metric-drift-sustained` | operational_stack | digest |
| `email-subscriber-errors` | web_stack | unresolved |
| `expert-gate-infra-hold` | monitoring_silence_alarms | digest |
| `freshness-checker-errors` | operational_stack | digest |
| `grading-stalled` | monitoring_prediction_alarms | digest |
| `hae-webhook-errors` | ingestion_stack | digest |
| `hae-webhook-no-invocations-24h` | monitoring_stack | digest |
| `hevy-restamp-errors` | operational_stack | digest |
| `hevy-routine-cron-errors` | operational_stack | digest |
| `ingest-auth-unhealthy-24h` | monitoring_stack | urgent |
| `key-rotator-errors` | operational_stack | digest |
| `life-platform-daily-brief-memory-high` | monitoring_stack | digest |
| `life-platform-data-export-errors` | operational_stack | digest |
| `life-platform-delete-user-data-errors` | operational_stack | digest |
| `life-platform-dlq-depth-warning` | operational_stack | digest |
| `life-platform-freshness-checker-not-emitting` | operational_stack | digest |
| `life-platform-insight-email-parser-parse-failure` | operational_stack | digest |
| `life-platform-og-image-errors` | web_stack | unresolved |
| `life-platform-recursive-loop` | mcp_stack | digest |
| `mcp-server-duration-high` | mcp_stack | digest |
| `mcp-warmer-error` | mcp_stack | digest |
| `mcp-warmer-no-invocations-24h` | mcp_stack | digest |
| `paging-budget-tier-3` | monitoring_stack | paging |
| `paging-pipeline-dead` | monitoring_stack | paging |
| `permanence-errors` | operational_stack | digest |
| `permanence-heartbeat` | operational_stack | digest |
| `prediction-gradable-share-low` | monitoring_prediction_alarms | digest |
| `recall-index-failed-chronicle-approve` | monitoring_silence_alarms | digest |
| `recall-index-failed-wednesday-chronicle` | monitoring_silence_alarms | digest |
| `site-api-ai-errors` | serve_stack | digest |
| `site-api-ai-throttles` | serve_stack | digest |
| `site-api-content-filter-fallback` | serve_stack | digest |
| `site-api-errors` | serve_stack | digest |
| `site-api-handled-5xx` | serve_stack | digest |
| `site-api-invocation-spike` | serve_stack | digest |
| `site-api-p95-latency-high` | serve_stack | digest |
| `site-api-throttles` | serve_stack | digest |
| `slo-mcp-availability` | mcp_stack | digest |
| `slo-warmer-completeness` | mcp_stack | digest |
| `telegram-coach-hold` | monitoring_silence_alarms | digest |
| `telegram-event-sweep-heartbeat` | serve_stack | digest |
| `telegram-webhook-throttles` | serve_stack | digest |
| `telegram-worker-errors` | serve_stack | digest |
| `telegram-worker-throttles` | serve_stack | digest |
| `token-alarm-genesis-window-active` | monitoring_stack | unresolved |
| `weekly-signal-delivery-heartbeat` | email_stack | urgent |

## 6. Coverage (honest numbers, ADR-104)

- Edge sites: 1142 total · 826 resolved · 316 dynamic (unresolvable at AST time, tagged — never guessed)
- Schedules: 81 resolved · 0 dynamic of 81 scheduled lambdas (104 lambdas total)
- Alarms: 50 explicit declarations (helper-default `ingestion-error-*` alarms are a stated scope cut)
- Record families referenced in code but outside the SOURCE_CLASS census (6): `coach_credibility`, `coach_thread`, `intelligence_quality`, `journal`, `platform_memory`, `zone2_efficiency` — special-cased in `phase_taxonomy` (category-split `platform_memory`, predicate-classified sk-families) or not yet live; `classify()` raises loudly for a genuinely unknown source by design
- Scope cuts: field-level edges wait on the #2797 per-field wiring registry · privacy tiers have no executable registry (docs/DATA_GOVERNANCE.md is prose) — not modeled
