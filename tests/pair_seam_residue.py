"""tests/pair_seam_residue.py — the #2847 must-agree-seam ledger (box 4, epic #2842).

The dated, shrink-only companion to ``tests/pair_seam_guard_lib.py``, in the shape
``tests/conformance_residue.py`` (#2844) and ``tests/lambda_enrollment_ledger.py``
(#2846) established: **an entry may only ever come OUT.** A row the sweep no longer
finds is a red, so the ratchet is forced to count down; a new seam is a red, never a
new baseline row you add to make the red go away.

Two dicts, and the difference between them is the whole point:

``PAIR_SEAM_RESIDUE`` — the must-agree seam census as it stood on the seed date.
    Reasonless by construction and honestly so: nobody can retroactively argue 286
    seams, and PR #3169 was right to refuse "299 rows of ceremony written by a model
    that cannot ground a single one of them". This is a PIN, not a debt claim —
    contracting all of these is neither the goal nor proportionate (ADR-103/144).
    Frozen: every value is the seed date, and the guard asserts that, so a new seam
    cannot be smuggled in here with a later date. Rows leave when the seam
    disappears or when a ``PairContract`` covers it.

``PAIR_SEAM_DECISIONS`` — seams born AFTER the seed date that are deliberately
    not contracted. ``(date, reason)``, and the reason has to be an argument, not a
    label: the guard enforces a 40-character floor, the same bar #2846 puts on its
    own dated exemptions. This dict starts EMPTY on purpose — the first row someone
    writes is the first time this instrument has actually cost anything, and that
    cost is the point of standing rule 3.

Seeded 2026-08-25 by ``python3 tests/pair_seam_guard_lib.py`` (286 seams over 39
partitions), the sweep's own output — no hand-typed list. Three seams the six
enrolled #2847 contracts already cover are absent by construction:
``computed_metrics`` <- daily_metrics_compute (write), ``adaptive_mode`` <-
adaptive_mode_lambda (write), ``engagement_state`` -> site_api_freshness (read).

THE NAMES ARE LOAD-BEARING (measured in CI, 2026-08-25)
--------------------------------------------------------
The first draft called these ``PAIR_SEAM_BASELINE`` / ``PAIR_SEAM_EXEMPTIONS``, and
the #3000 doc literal moved 557 -> 844 declared gates. ``scripts/gate_census.py``'s
``_REGISTRY_NAME`` matches ``.*_BASELINE`` and ``.*_EXEMPT.*``, so it enumerated all
286 rows as 286 SEPARATE gates and, because its exemption-data branch tests
``(root / entry).exists()``, flagged every one of them ``stale-exemption`` — the
keys are composite seam identities that merely CONTAIN a path, not paths. One gate
with 286 dated rows was being reported as 286 gates and 286 false leads.

Renamed to sit where its two siblings already sit: ``CONFORMANCE_RESIDUE`` (#2844)
and ``RAW_CONSTRUCTIONS``/``DEPLOY_REGISTRATION`` (#2846) do not match that regex
either, and they are the same kind of object. This is consistency, not evasion —
the census's composite-key blind spot is real and worth its own look, but silently
inflating the platform's gate count by 51% to make the point would be the wrong way
to raise it. Do not rename these back without re-measuring the census.
"""

SEED_DATE = "2026-08-25"

#: The grandfathered census. FROZEN at SEED_DATE — see the module docstring.
PAIR_SEAM_RESIDUE: dict[str, str] = {
    "adaptive_mode::mcp/tools_coach_checkin.py::read": SEED_DATE,
    "adaptive_mode::mcp/tools_reading.py::read": SEED_DATE,
    "ai_analysis::lambdas/compute/state_of_matthew_lambda.py::read": SEED_DATE,
    "ai_analysis::lambdas/emails/chronicle_data.py::read": SEED_DATE,
    "ai_analysis::lambdas/operational/coherence_sentinel_lambda.py::read": SEED_DATE,
    "ai_analysis::lambdas/web/site_api_coach_narrative.py::read": SEED_DATE,
    "ai_analysis::lambdas/web/site_api_coach_stance.py::read": SEED_DATE,
    "anomalies::lambdas/emails/anomaly_detector_lambda.py::write": SEED_DATE,
    "anomalies::lambdas/emails/daily_brief_lambda.py::read": SEED_DATE,
    "apple_health::lambdas/emails/evening_nudge_lambda.py::read": SEED_DATE,
    "apple_health::lambdas/emails/freshness_checker_lambda.py::read": SEED_DATE,
    "apple_health::lambdas/emails/freshness_checker_lambda.py::write": SEED_DATE,
    "apple_health::lambdas/ingestion/health_auto_export_lambda.py::read": SEED_DATE,
    "apple_health::lambdas/ingestion/health_auto_export_lambda.py::write": SEED_DATE,
    "apple_health::lambdas/intelligence/ai_expert_analyzer_lambda.py::read": SEED_DATE,
    "apple_health::lambdas/operational/qa_smoke_lambda.py::read": SEED_DATE,
    "apple_health::lambdas/web/site_api_biomarkers.py::read": SEED_DATE,
    "apple_health::lambdas/web/site_api_body.py::read": SEED_DATE,
    "apple_health::lambdas/web/site_api_fingerprint.py::read": SEED_DATE,
    "apple_health::lambdas/web/site_api_freshness.py::read": SEED_DATE,
    "apple_health::lambdas/web/site_api_journey.py::read": SEED_DATE,
    "apple_health::lambdas/web/site_api_meals.py::read": SEED_DATE,
    "apple_health::lambdas/web/site_api_mind.py::read": SEED_DATE,
    "apple_health::lambdas/web/site_api_physical.py::read": SEED_DATE,
    "apple_health::lambdas/web/site_api_pulse.py::read": SEED_DATE,
    "apple_health::lambdas/web/site_api_rollups.py::read": SEED_DATE,
    "apple_health::lambdas/web/site_api_sleep.py::read": SEED_DATE,
    "apple_health::lambdas/web/site_api_training.py::read": SEED_DATE,
    "apple_health::lambdas/web/site_stats_refresh_lambda.py::read": SEED_DATE,
    "apple_health::mcp/tools_cgm.py::read": SEED_DATE,
    "apple_health::mcp/tools_health.py::read": SEED_DATE,
    "apple_health::mcp/tools_lifestyle.py::read": SEED_DATE,
    "challenges::lambdas/compute/character_sheet_lambda.py::write": SEED_DATE,
    "challenges::lambdas/intelligence/challenge_generator_lambda.py::read": SEED_DATE,
    "challenges::lambdas/intelligence/challenge_generator_lambda.py::write": SEED_DATE,
    "challenges::lambdas/web/site_api_social_challenges.py::read": SEED_DATE,
    "challenges::lambdas/web/site_api_social_challenges.py::write": SEED_DATE,
    "chronicle::lambdas/content/site_writer.py::read": SEED_DATE,
    "chronicle::lambdas/emails/chronicle_approve_lambda.py::read": SEED_DATE,
    "chronicle::lambdas/emails/chronicle_approve_lambda.py::write": SEED_DATE,
    "chronicle::lambdas/emails/chronicle_data.py::read": SEED_DATE,
    "chronicle::lambdas/emails/chronicle_email_sender_lambda.py::read": SEED_DATE,
    "chronicle::lambdas/emails/chronicle_email_sender_lambda.py::write": SEED_DATE,
    "chronicle::lambdas/emails/chronicle_podcast_lambda.py::read": SEED_DATE,
    "chronicle::lambdas/emails/chronicle_store.py::read": SEED_DATE,
    "chronicle::lambdas/emails/chronicle_store.py::write": SEED_DATE,
    "chronicle::lambdas/emails/coach_panel_podcast_lambda.py::read": SEED_DATE,
    "chronicle::lambdas/web/ask_retrieval.py::read": SEED_DATE,
    "chronicle::lambdas/web/site_api_coach_narrative.py::read": SEED_DATE,
    "coach_actions::lambdas/intelligence/intelligence_common.py::write": SEED_DATE,
    "coach_actions::lambdas/web/site_api_lambda.py::read": SEED_DATE,
    "coach_thread::lambdas/training/training_notes.py::write": SEED_DATE,
    "coach_thread::mcp/tools_coach_intelligence.py::read": SEED_DATE,
    "computed_insights::lambdas/compute/daily_insight_compute_lambda.py::read": SEED_DATE,
    "computed_insights::lambdas/compute/daily_insight_compute_lambda.py::write": SEED_DATE,
    "computed_insights::lambdas/compute/weekly_signal_lambda.py::read": SEED_DATE,
    "computed_insights::lambdas/emails/daily_brief_lambda.py::write": SEED_DATE,
    "computed_metrics::lambdas/ai/ai_calls.py::read": SEED_DATE,
    "computed_metrics::lambdas/ai/ai_output_validator.py::read": SEED_DATE,
    "computed_metrics::lambdas/compute/acwr_compute_lambda.py::write": SEED_DATE,
    "computed_metrics::lambdas/emails/anomaly_detector_lambda.py::read": SEED_DATE,
    "computed_metrics::lambdas/emails/coach_nudge_lambda.py::read": SEED_DATE,
    "computed_metrics::lambdas/emails/daily_debrief_lambda.py::read": SEED_DATE,
    "computed_metrics::lambdas/emails/monday_compass_lambda.py::read": SEED_DATE,
    "computed_metrics::lambdas/emails/weekly_digest_lambda.py::read": SEED_DATE,
    "computed_metrics::lambdas/intelligence/ai_expert_analyzer_lambda.py::read": SEED_DATE,
    "computed_metrics::lambdas/intelligence/field_notes_lambda.py::read": SEED_DATE,
    "computed_metrics::lambdas/operational/coherence_sentinel_lambda.py::read": SEED_DATE,
    "computed_metrics::lambdas/web/site_api_discovery.py::read": SEED_DATE,
    "computed_metrics::lambdas/web/site_api_habits.py::read": SEED_DATE,
    "computed_metrics::mcp/tools_health.py::read": SEED_DATE,
    "computed_metrics::mcp/tools_training.py::read": SEED_DATE,
    "day_grade::lambdas/compute/adaptive_mode_lambda.py::read": SEED_DATE,
    "day_grade::lambdas/compute/daily_metrics_compute_lambda.py::write": SEED_DATE,
    "day_grade::lambdas/compute/failure_pattern_compute_lambda.py::read": SEED_DATE,
    "day_grade::lambdas/emails/daily_brief_lambda.py::write": SEED_DATE,
    "day_grade::lambdas/emails/monday_compass_lambda.py::read": SEED_DATE,
    "day_grade::lambdas/operational/coherence_sentinel_lambda.py::read": SEED_DATE,
    "diary_claims::lambdas/web/site_api_diary.py::read": SEED_DATE,
    "diary_claims::mcp/tools_coach_intelligence.py::read": SEED_DATE,
    "diary_claims::mcp/tools_journal.py::write": SEED_DATE,
    "diary_reactions::lambdas/coach/coach_diary_reaction.py::write": SEED_DATE,
    "diary_reactions::lambdas/web/site_api_thirdwall.py::read": SEED_DATE,
    "email_log::lambdas/common/send_ledger.py::read": SEED_DATE,
    "email_log::lambdas/compute/weekly_signal_lambda.py::read": SEED_DATE,
    "email_log::lambdas/compute/weekly_signal_lambda.py::write": SEED_DATE,
    "email_log::lambdas/emails/ai_review_pack_lambda.py::read": SEED_DATE,
    "email_log::lambdas/emails/ai_review_pack_lambda.py::write": SEED_DATE,
    "email_log::lambdas/emails/anomaly_detector_lambda.py::read": SEED_DATE,
    "email_log::lambdas/emails/anomaly_detector_lambda.py::write": SEED_DATE,
    "email_log::lambdas/emails/between_chronicle_lambda.py::read": SEED_DATE,
    "email_log::lambdas/emails/between_chronicle_lambda.py::write": SEED_DATE,
    "email_log::lambdas/emails/chronicle_email_sender_lambda.py::write": SEED_DATE,
    "email_log::lambdas/emails/chronicle_store.py::write": SEED_DATE,
    "email_log::lambdas/emails/daily_brief_lambda.py::read": SEED_DATE,
    "email_log::lambdas/emails/daily_brief_lambda.py::write": SEED_DATE,
    "email_log::lambdas/emails/evening_nudge_lambda.py::read": SEED_DATE,
    "email_log::lambdas/emails/evening_nudge_lambda.py::write": SEED_DATE,
    "email_log::lambdas/emails/insight_email_parser_lambda.py::read": SEED_DATE,
    "email_log::lambdas/emails/insight_email_parser_lambda.py::write": SEED_DATE,
    "email_log::lambdas/emails/milestone_digest_lambda.py::read": SEED_DATE,
    "email_log::lambdas/emails/milestone_digest_lambda.py::write": SEED_DATE,
    "email_log::lambdas/emails/monday_compass_lambda.py::read": SEED_DATE,
    "email_log::lambdas/emails/monday_compass_lambda.py::write": SEED_DATE,
    "email_log::lambdas/emails/nutrition_review_lambda.py::read": SEED_DATE,
    "email_log::lambdas/emails/nutrition_review_lambda.py::write": SEED_DATE,
    "email_log::lambdas/emails/partner_email_lambda.py::read": SEED_DATE,
    "email_log::lambdas/emails/partner_email_lambda.py::write": SEED_DATE,
    "email_log::lambdas/emails/weekly_digest_lambda.py::read": SEED_DATE,
    "email_log::lambdas/emails/weekly_digest_lambda.py::write": SEED_DATE,
    "email_log::lambdas/emails/weekly_plate_lambda.py::read": SEED_DATE,
    "email_log::lambdas/emails/weekly_plate_lambda.py::write": SEED_DATE,
    "engagement_state::lambdas/coach/coach_chat_grounding.py::read": SEED_DATE,
    "engagement_state::lambdas/compute/adaptive_mode_lambda.py::write": SEED_DATE,
    "engagement_state::lambdas/compute/character_sheet_lambda.py::read": SEED_DATE,
    "engagement_state::lambdas/compute/state_of_matthew_lambda.py::read": SEED_DATE,
    "engagement_state::lambdas/emails/coach_panel_podcast_lambda.py::read": SEED_DATE,
    "engagement_state::lambdas/emails/daily_brief_lambda.py::read": SEED_DATE,
    "engagement_state::lambdas/emails/daily_debrief_lambda.py::read": SEED_DATE,
    "engagement_state::lambdas/emails/monday_compass_lambda.py::read": SEED_DATE,
    "engagement_state::lambdas/emails/monthly_digest_lambda.py::read": SEED_DATE,
    "engagement_state::lambdas/emails/weekly_digest_lambda.py::read": SEED_DATE,
    "engagement_state::lambdas/intelligence/ai_expert_analyzer_lambda.py::read": SEED_DATE,
    "engagement_state::lambdas/web/site_api_ai_context.py::read": SEED_DATE,
    "engagement_state::mcp/tools_coach_checkin.py::read": SEED_DATE,
    "experiments::lambdas/compute/daily_insight_compute_lambda.py::read": SEED_DATE,
    "experiments::lambdas/emails/chronicle_data.py::read": SEED_DATE,
    "experiments::lambdas/emails/coach_nudge_lambda.py::read": SEED_DATE,
    "experiments::lambdas/intelligence/ai_expert_analyzer_lambda.py::read": SEED_DATE,
    "experiments::lambdas/web/site_api_discovery.py::read": SEED_DATE,
    "experiments::lambdas/web/site_api_journey.py::read": SEED_DATE,
    "experiments::lambdas/web/site_api_protocols.py::read": SEED_DATE,
    "experiments::lambdas/web/site_api_rollups.py::read": SEED_DATE,
    "experiments::mcp/tools_lifestyle.py::write": SEED_DATE,
    "field_notes::lambdas/emails/chronicle_data.py::read": SEED_DATE,
    "field_notes::lambdas/intelligence/ai_expert_analyzer_lambda.py::read": SEED_DATE,
    "field_notes::lambdas/intelligence/field_notes_lambda.py::read": SEED_DATE,
    "field_notes::lambdas/intelligence/field_notes_lambda.py::write": SEED_DATE,
    "field_notes::lambdas/web/site_api_thirdwall.py::read": SEED_DATE,
    "field_notes::mcp/tools_lifestyle.py::read": SEED_DATE,
    "field_notes::mcp/tools_lifestyle.py::write": SEED_DATE,
    "flourishing::lambdas/content/theme_river.py::read": SEED_DATE,
    "flourishing::lambdas/health/flourishing.py::write": SEED_DATE,
    "flourishing::lambdas/web/site_api_fulfillment.py::read": SEED_DATE,
    "flourishing::mcp/tools_journal.py::read": SEED_DATE,
    "food_delivery::lambdas/common/digest_utils.py::read": SEED_DATE,
    "food_delivery::lambdas/ingestion/food_delivery_lambda.py::write": SEED_DATE,
    "food_delivery::lambdas/web/site_api_meals.py::read": SEED_DATE,
    "food_delivery::lambdas/web/site_api_nutrition.py::read": SEED_DATE,
    "forecast::lambdas/ai/ai_calls.py::read": SEED_DATE,
    "forecast::lambdas/compute/forecast_engine_lambda.py::write": SEED_DATE,
    "forecast::lambdas/compute/state_of_matthew_lambda.py::read": SEED_DATE,
    "forecast::lambdas/web/site_api_foresight.py::read": SEED_DATE,
    "habit_scores::lambdas/coach/coach_prediction_evaluator.py::read": SEED_DATE,
    "habit_scores::lambdas/compute/adaptive_mode_lambda.py::read": SEED_DATE,
    "habit_scores::lambdas/compute/daily_metrics_compute_lambda.py::write": SEED_DATE,
    "habit_scores::lambdas/compute/failure_pattern_compute_lambda.py::read": SEED_DATE,
    "habit_scores::lambdas/emails/daily_brief_lambda.py::write": SEED_DATE,
    "habit_scores::lambdas/emails/monday_compass_lambda.py::read": SEED_DATE,
    "habit_scores::lambdas/web/site_api_ai_context.py::read": SEED_DATE,
    "habit_scores::lambdas/web/site_api_habits.py::read": SEED_DATE,
    "habit_scores::lambdas/web/site_api_mind.py::read": SEED_DATE,
    "health_check::lambdas/operational/pipeline_health_check_lambda.py::write": SEED_DATE,
    "health_check::lambdas/web/site_api_status.py::read": SEED_DATE,
    "hevy::lambdas/compute/daily_metrics_compute_lambda.py::read": SEED_DATE,
    "hevy::lambdas/content/vacation_fund.py::read": SEED_DATE,
    "hevy::lambdas/intelligence/ai_expert_analyzer_lambda.py::read": SEED_DATE,
    "hevy::lambdas/training/hevy_common.py::write": SEED_DATE,
    "hevy::lambdas/training/training_notes.py::read": SEED_DATE,
    "hevy::lambdas/web/site_api_pulse.py::read": SEED_DATE,
    "hevy::lambdas/web/site_api_training.py::read": SEED_DATE,
    "hevy::mcp/tools_hevy_routine.py::read": SEED_DATE,
    "hevy::mcp/tools_strength.py::read": SEED_DATE,
    "hevy::mcp/tools_training_notes.py::read": SEED_DATE,
    "hypotheses::lambdas/compute/hypothesis_engine_lambda.py::write": SEED_DATE,
    "hypotheses::lambdas/compute/state_of_matthew_lambda.py::read": SEED_DATE,
    "hypotheses::lambdas/intelligence/challenge_generator_lambda.py::read": SEED_DATE,
    "hypotheses::mcp/tools_lifestyle.py::read": SEED_DATE,
    "insights::lambdas/emails/insight_email_parser_lambda.py::write": SEED_DATE,
    "insights::lambdas/web/site_api_ledger.py::read": SEED_DATE,
    "insights::mcp/tools_lifestyle.py::read": SEED_DATE,
    "insights::mcp/tools_lifestyle.py::write": SEED_DATE,
    "journal_quotes::lambdas/web/site_api_diary.py::read": SEED_DATE,
    "journal_quotes::lambdas/web/site_api_thirdwall.py::read": SEED_DATE,
    "journal_quotes::mcp/tools_journal.py::write": SEED_DATE,
    "measurements::lambdas/ingestion/measurements_ingestion_lambda.py::write": SEED_DATE,
    "measurements::lambdas/intelligence/ai_expert_analyzer_lambda.py::read": SEED_DATE,
    "measurements::lambdas/web/site_api_physical.py::read": SEED_DATE,
    "notion::lambdas/compute/adaptive_mode_lambda.py::read": SEED_DATE,
    "notion::lambdas/compute/circadian_compliance_lambda.py::read": SEED_DATE,
    "notion::lambdas/compute/daily_insight_compute_lambda.py::read": SEED_DATE,
    "notion::lambdas/compute/daily_metrics_compute_lambda.py::read": SEED_DATE,
    "notion::lambdas/emails/evening_nudge_lambda.py::read": SEED_DATE,
    "notion::lambdas/emails/freshness_checker_lambda.py::read": SEED_DATE,
    "notion::lambdas/emails/freshness_checker_lambda.py::write": SEED_DATE,
    "notion::lambdas/ingestion/notion_lambda.py::read": SEED_DATE,
    "notion::lambdas/ingestion/notion_lambda.py::write": SEED_DATE,
    "notion::lambdas/intelligence/field_notes_lambda.py::read": SEED_DATE,
    "notion::lambdas/intelligence/intelligence_common.py::read": SEED_DATE,
    "notion::lambdas/web/site_api_fulfillment.py::read": SEED_DATE,
    "notion::lambdas/web/site_api_mind.py::read": SEED_DATE,
    "notion::lambdas/web/site_api_pulse.py::read": SEED_DATE,
    "notion::mcp/tools_journal.py::read": SEED_DATE,
    "notion::mcp/tools_social_connection.py::read": SEED_DATE,
    "panelcast::lambdas/emails/coach_panel_podcast_lambda.py::read": SEED_DATE,
    "panelcast::lambdas/emails/coach_panel_podcast_lambda.py::write": SEED_DATE,
    "panelcast::lambdas/emails/podcast_script_v2.py::read": SEED_DATE,
    "panelcast::lambdas/emails/podcast_script_v2.py::write": SEED_DATE,
    "panelcast::lambdas/web/site_api_coach_ledger.py::read": SEED_DATE,
    "platform_memory::lambdas/compute/daily_insight_compute_lambda.py::read": SEED_DATE,
    "platform_memory::lambdas/compute/daily_insight_compute_lambda.py::write": SEED_DATE,
    "platform_memory::lambdas/compute/failure_pattern_compute_lambda.py::write": SEED_DATE,
    "platform_memory::lambdas/compute/hypothesis_engine_lambda.py::write": SEED_DATE,
    "platform_memory::lambdas/emails/weekly_plate_lambda.py::read": SEED_DATE,
    "platform_memory::lambdas/emails/weekly_plate_lambda.py::write": SEED_DATE,
    "routine_index::lambdas/training/routine_repo.py::write": SEED_DATE,
    "routine_index::lambdas/training/routine_title.py::read": SEED_DATE,
    "routine_index::lambdas/web/site_api_protocols.py::read": SEED_DATE,
    "sick_days::lambdas/health/sick_day_checker.py::read": SEED_DATE,
    "sick_days::lambdas/health/sick_day_checker.py::write": SEED_DATE,
    "sick_days::mcp/tools_sick_days.py::read": SEED_DATE,
    "sick_days::mcp/tools_sick_days.py::write": SEED_DATE,
    "strava::lambdas/content/vacation_fund.py::read": SEED_DATE,
    "strava::lambdas/emails/monthly_digest_lambda.py::read": SEED_DATE,
    "strava::lambdas/ingestion/enrichment_lambda.py::write": SEED_DATE,
    "strava::lambdas/intelligence/ai_expert_analyzer_lambda.py::read": SEED_DATE,
    "strava::lambdas/intelligence/intelligence_common.py::read": SEED_DATE,
    "strava::lambdas/web/site_api_autonomic.py::read": SEED_DATE,
    "strava::lambdas/web/site_api_nutrition.py::read": SEED_DATE,
    "strava::lambdas/web/site_api_physical.py::read": SEED_DATE,
    "strava::lambdas/web/site_api_pulse.py::read": SEED_DATE,
    "strava::lambdas/web/site_api_training.py::read": SEED_DATE,
    "strava::lambdas/web/site_api_vitals_depth.py::read": SEED_DATE,
    "strava::lambdas/web/site_stats_refresh_lambda.py::read": SEED_DATE,
    "strava::mcp/tools_benchmark.py::read": SEED_DATE,
    "strava::mcp/tools_correlation.py::read": SEED_DATE,
    "strava::mcp/tools_health.py::read": SEED_DATE,
    "strava::mcp/tools_nutrition.py::read": SEED_DATE,
    "strava::mcp/tools_training.py::read": SEED_DATE,
    "subscribers::lambdas/emails/weekly_digest_lambda.py::read": SEED_DATE,
    "subscribers::lambdas/operational/canary_lambda.py::read": SEED_DATE,
    "subscribers::lambdas/operational/canary_lambda.py::write": SEED_DATE,
    "subscribers::lambdas/operational/delete_user_data_lambda.py::read": SEED_DATE,
    "subscribers::lambdas/operational/delete_user_data_lambda.py::write": SEED_DATE,
    "subscribers::lambdas/web/email_subscriber_lambda.py::read": SEED_DATE,
    "subscribers::lambdas/web/email_subscriber_lambda.py::write": SEED_DATE,
    "subscribers::lambdas/web/site_api_social.py::read": SEED_DATE,
    "subscribers::lambdas/web/site_api_social_engage.py::read": SEED_DATE,
    "subscribers::lambdas/web/site_api_social_ladder.py::read": SEED_DATE,
    "subscribers::lambdas/web/subscriber_onboarding_lambda.py::read": SEED_DATE,
    "supplements::lambdas/ingestion/habitify_lambda.py::write": SEED_DATE,
    "supplements::lambdas/web/site_api_protocols.py::read": SEED_DATE,
    "training_notes::lambdas/training/training_notes_llm.py::write": SEED_DATE,
    "training_notes::mcp/tools_training_notes.py::read": SEED_DATE,
    "weekly_correlations::lambdas/compute/daily_insight_compute_lambda.py::read": SEED_DATE,
    "weekly_correlations::lambdas/compute/weekly_correlation_compute_lambda.py::write": SEED_DATE,
    "weekly_correlations::lambdas/intelligence/ai_expert_analyzer_lambda.py::read": SEED_DATE,
    "weekly_correlations::lambdas/web/site_api_ai_context.py::read": SEED_DATE,
    "weekly_correlations::lambdas/web/site_api_discovery.py::read": SEED_DATE,
    "weekly_correlations::lambdas/web/site_api_journey.py::read": SEED_DATE,
    "weekly_correlations::lambdas/web/site_api_ledger.py::read": SEED_DATE,
    "what_changed::lambdas/compute/weekly_correlation_compute_lambda.py::write": SEED_DATE,
    "what_changed::lambdas/emails/between_chronicle_lambda.py::read": SEED_DATE,
    "what_changed::lambdas/web/site_api_ai_context.py::read": SEED_DATE,
    "what_changed::lambdas/web/site_api_ledger.py::read": SEED_DATE,
    "whoop::lambdas/coach/intake_response.py::read": SEED_DATE,
    "whoop::lambdas/compute/failure_pattern_compute_lambda.py::read": SEED_DATE,
    "whoop::lambdas/emails/monday_compass_lambda.py::read": SEED_DATE,
    "whoop::lambdas/ingestion/enrichment_lambda.py::read": SEED_DATE,
    "whoop::lambdas/ingestion/whoop_lambda.py::write": SEED_DATE,
    "whoop::lambdas/intelligence/ai_expert_analyzer_lambda.py::read": SEED_DATE,
    "whoop::lambdas/operational/hevy_restamp_lambda.py::read": SEED_DATE,
    "whoop::lambdas/web/site_api_autonomic.py::read": SEED_DATE,
    "whoop::lambdas/web/site_api_body.py::read": SEED_DATE,
    "whoop::lambdas/web/site_api_fingerprint.py::read": SEED_DATE,
    "whoop::lambdas/web/site_api_freshness.py::read": SEED_DATE,
    "whoop::lambdas/web/site_api_lambda.py::read": SEED_DATE,
    "whoop::lambdas/web/site_api_nutrition.py::read": SEED_DATE,
    "whoop::lambdas/web/site_api_pulse.py::read": SEED_DATE,
    "whoop::lambdas/web/site_api_rollups.py::read": SEED_DATE,
    "whoop::lambdas/web/site_api_sleep.py::read": SEED_DATE,
    "whoop::lambdas/web/site_api_training.py::read": SEED_DATE,
    "whoop::mcp/tools_health.py::read": SEED_DATE,
    "whoop::mcp/tools_hevy_routine.py::read": SEED_DATE,
    "whoop::mcp/tools_training.py::read": SEED_DATE,
}

#: Seams born after SEED_DATE that are deliberately not contracted: (date, reason).
#: The reason must be an argument (40-char floor, enforced by the guard).
# The first rows this dict has ever carried (#3741). See the reason itself for why these
# five are a decision rather than five contracts.
_RECAP_READ_REASON = "#3741 recap card: a READ-ONLY consumer that cannot make a false claim from a shape change. Verified on the module, not assumed: recap_data does no [] indexing on any source row (every field goes through .get()), DayFacts declares 21 Optional fields and the non-Optional ones default to empty list/dict, and web/recap_templates raises RecapNullFact on any None at RENDER rather than formatting it — fmt(None) == '-' is forbidden on this surface. So a renamed or dropped field makes the beat that needs it DECLINE; it can never become a wrong number on a public card. Residual risk stated plainly rather than waved: the card would then degrade to a fallback beat silently, and the only record is `absent_sources` on the SOURCE#recap_cards row per run, which is queryable but not alarmed. Contracting five read seams whose worst case is 'draws less' is disproportionate (ADR-103/144) while that holds; if a card ever derives a number from two partitions that must agree, that seam gets a PairContract instead of this row."

_HEVY_WORKED_SET_REASON = (
    "#3931 routed all three TDEE surfaces through ONE shared hevy reader (health.tdee.worked_set_seconds), whose "
    "dependence on the exercises[].sets[] wire shape is pinned against hevy_compiler._set_to_wire; a shape drift "
    "collapses sets to 0 and flips the PUBLISHED basis string to lifting_duration_x0.25_no_set_log, so the two "
    "sides cannot disagree silently."
)

_WHOOP_HISTORY_READ_REASON = (
    "#4025: a READ-ONLY, fail-soft consumer (resolve_vitals_history). It reads four named whoop daily fields "
    "(recovery_score, hrv, resting_heart_rate, sleep_duration_hours) through dict.get() only — never [] indexing "
    "— and wraps the whole DDB call in a bare except that returns None. VERIFIED, not assumed: a writer-side field "
    "rename or shape drift just makes that metric's per-day entry absent from the returned history dict, which "
    "routes assess_cross_surface_vitals's dated-citation exemption to 'no matching day' — the pre-#4025 STRICT "
    "compare, byte-identical to today's behaviour. So the two sides cannot disagree SILENTLY: the worst case a "
    "shape drift causes is the exemption going dark (a stale citation still correctly FAILs), never a coach's "
    "wrong number being wrongly forgiven. Pinned by "
    "tests/test_cross_surface_vitals_dated_citation_4025.py::test_resolve_vitals_history_parses_the_real_whoop_field_names "
    "and its fail-soft/mutation-control siblings in the same file."
)


PAIR_SEAM_DECISIONS: dict[str, tuple[str, str]] = {
    # #3900 (2026-09-20): the writer gained a write-time `phase`/`cycle` stamp via
    # experiment_stamp_for(); the reader (mcp/tools_coach_intelligence.py) never inspects
    # those keys — it selects rows through with_phase_filter, which IS the contract between
    # them (taxonomy-derived on both sides). The shape the reader depends on
    # (position_summary, predictions, surprises, …) did not change, so there is no field
    # the two sides could disagree about; a PairContract here would pin the filter, which
    # tests/test_tagger_blind_writers_stamp_3900.py already does from the writer's side.
    "coach_thread::lambdas/intelligence/intelligence_common.py::write": (
        "2026-09-20",
        "#3900 added the write-time phase/cycle stamp to write_coach_thread; the MCP reader selects through "
        "with_phase_filter and reads none of the stamped keys, so the stamp is the contract, not a shape to agree on.",
    ),
    "computed_metrics::lambdas/content/recap_data.py::read": (
        "2026-09-13",
        _RECAP_READ_REASON,
    ),
    "habit_scores::lambdas/content/recap_data.py::read": (
        "2026-09-13",
        _RECAP_READ_REASON,
    ),
    "hevy::lambdas/content/recap_data.py::read": (
        "2026-09-13",
        _RECAP_READ_REASON,
    ),
    "notion::lambdas/content/recap_data.py::read": (
        "2026-09-13",
        _RECAP_READ_REASON,
    ),
    "strava::lambdas/content/recap_data.py::read": (
        "2026-09-13",
        _RECAP_READ_REASON,
    ),
    # #3931 (2026-09-20): three TDEE surfaces began reading the `hevy` partition so the
    # lifting energy term can be charged on WORKED-SET time instead of the full logged
    # session duration (rest between sets included). All three read it through ONE shared
    # accessor — `health.tdee.worked_set_seconds` — never inline, and that accessor's
    # dependence on the wire shape (`exercises[].sets[].reps` / `.duration_seconds` /
    # `.type`) is asserted against the shape `lambdas/training/hevy_compiler._set_to_wire`
    # writes in tests/test_tdee_worked_set_3931_behavior.py.
    #
    # VERIFIED (not asserted): the two sides cannot disagree SILENTLY here. The accessor
    # treats every unmatched set row as contributing zero, so a shape drift collapses
    # `sets` to 0, which routes `lifting_energy` to its NAMED fallback branch — the
    # published `basis` string flips from "worked_set_time_from_hevy_set_log…" to
    # "lifting_duration_x0.25_no_set_log" on every calorie surface. That flip is pinned by
    # test_without_a_set_log_the_lifting_duration_is_charged_at_the_stated_work_fraction.
    # A drift changes a published label, not just a number.
    "hevy::lambdas/web/site_api_nutrition.py::read": (
        "2026-09-20",
        _HEVY_WORKED_SET_REASON,
    ),
    "hevy::mcp/tools_health.py::read": (
        "2026-09-20",
        _HEVY_WORKED_SET_REASON,
    ),
    "hevy::mcp/tools_nutrition.py::read": (
        "2026-09-20",
        _HEVY_WORKED_SET_REASON,
    ),
    # #4025 (2026-09-21): weight_truth_qa.checks() gained an optional `table=` param so
    # the nightly's already-instantiated DDB Table is reused to resolve trailing Whoop
    # history — the fix for a coach narrating a PAST reading BY DATE (e.g. "the 97%
    # recovery reading on September 18th") being judged as a claim about TODAY.
    "whoop::lambdas/operational/weight_truth_qa.py::read": (
        "2026-09-21",
        _WHOOP_HISTORY_READ_REASON,
    ),
    # #4051 (2026-09-22): stage-1 plan_next_session's pain-flag evidence set became the
    # movements PERFORMED in the trailing 28 days (it was a draft routine's exercise list,
    # which is empty before a draft exists — so a flagged, owner-dismissed site read
    # "clear"). That read is what joins tools_plan to the hevy partition.
    "hevy::mcp/tools_plan.py::read": (
        "2026-09-22",
        "#4051: tools_plan does NOT parse the hevy wire shape. `_performed_movements` reads through "
        "`tools_strength._read_hevy_all_phases` (itself already a residue seam, and the ONE sanctioned cross-phase "
        "Hevy read) and `strength_helpers.normalize_hevy_items`, the shared normaliser that gives every field an "
        "explicit default; it then touches only `date`, `exercises[].template_id` and `exercises[].name`. VERIFIED, "
        "not assumed: a writer-side shape drift makes the normaliser yield blocks with an empty template_id/name, "
        "which `_performed_movements` counts as `blocks_without_template_id` and drops — collapsing the evidence set "
        "to zero movements. That is the EMPTY-EVIDENCE path #4051 exists to make loud: the scope reports "
        "`status: none` and the `pain_flag_named_site` row reads `unknown` with `evidence: none — <reason>`, with "
        "the count of dropped blocks named in the payload. So the two sides cannot disagree SILENTLY — a drift turns "
        "the tripwire off BY NAME, it can never turn it green. Pinned by "
        "tests/test_stage1_pain_evidence_4051.py::TestTheEmptyPath::test_no_session_in_the_window_reads_unknown_with_evidence_none "
        "and by test_mutation_control_break_the_derivation_and_the_planted_flag_disappears.",
    ),
    # #4072 (2026-09-22): the readiness_floor tripwire had NO producer — nothing supplied
    # `readiness_low_streak_days`, so it read "no recovery series" with Whoop fresh. Its
    # input is now read from the whoop partition, which is what joins tools_plan to it.
    "whoop::mcp/tools_plan.py::read": (
        "2026-09-22",
        "#4072: `_readiness_low_streak` reads ONLY `sk` (to keep the DATE#<day> daily rows and drop the "
        "DATE#<day>#WORKOUT# rows) and `recovery_score`, through `query_source_cross_phase`. VERIFIED, not assumed: "
        "a writer-side rename of `recovery_score` leaves daily rows with no numeric score, which raises "
        "InputShapeError, and the plan block then reports the input `read_failed (InputShapeError: ...)` and the "
        "readiness_floor row `read_failed` BY NAME — it can never read clear, and it no longer reads a merely "
        "absent `unknown`. A change to the sk scheme empties the daily set and reads `absent` with the window "
        "named. Pinned by tests/test_plan_input_read_state_4072.py::TestReadinessFloorReadsWhoop::"
        "test_a_writer_shape_drift_is_read_failed_not_absent and test_an_empty_window_is_absent_not_failed.",
    ),
    # #4082 (2026-09-23): get_coach_session_packet's `last_session_by_type` shows the newest
    # performed session of each type — the read that joins tools_coach_packet to the hevy partition.
    "hevy::mcp/tools_coach_packet.py::read": (
        "2026-09-23",
        "#4082: `_last_sessions` reads through `tools_strength._read_hevy_all_phases` (the ONE sanctioned "
        "cross-phase Hevy read, itself a residue seam) and parses no set shape of its own: exercises go through "
        "`training.muscle_volume.normalize_hevy_items`, the type through `routine_title.resolve_archetype`, load "
        "through `training_streaks.is_loaded_session` — the shared readers every other consumer uses. Its own keys "
        "are `sk` (the DATE#<day>#WORKOUT#<id> filter) plus display pass-throughs (date, title, workout_uid, "
        "duration_sec, adherence, description), shown verbatim, None visible. VERIFIED, not assumed: a writer-side "
        "sk change leaves rows with no per-workout marker, which raises InputShapeError and the field reports "
        "`read_failed (InputShapeError: ...)` BY NAME — never `absent`. Pinned by "
        "tests/test_coach_session_packet_4082.py::test_a_hevy_key_scheme_drift_is_read_failed_not_absent.",
    ),
    # #4110 (2026-09-24): the three stage-1 Hevy window readers moved VERBATIM out of
    # mcp/tools_plan.py (module-size ceiling) into mcp/plan_hevy_windows.py, and one of them
    # (`_block_workouts`) is new: the v0.3 session sequence's record since the block start.
    "hevy::mcp/plan_hevy_windows.py::read": (
        "2026-09-24",
        "#4110: plan_hevy_windows does NOT parse the hevy wire shape — each reader turns a date into rows and hands "
        "them on untouched (`_rotation_window`/`_prescription_window` through `mcp.core.query_source_range`, the "
        "`hevy::mcp/tools_plan.py` reads they were before the move; `_block_workouts` through "
        "`tools_strength._read_hevy_all_phases`, the ONE sanctioned cross-phase Hevy read). The field-level consumers "
        "are the training modules: `_block_workouts`' rows reach `session_sequence.completed_sessions`, which reads "
        "only `date`, `tombstone`, `title`, `source_workout_id`/`workout_id`, `start_time` and — through "
        "`training_streaks.is_loaded_session`, the one loaded-session definition (#4105) — `exercises[].name` and "
        "`exercises[].sets[].{type|set_type, weight_kg|weight_lbs}`, accepting both the raw row and the normalised "
        "shape. VERIFIED, not assumed: a writer-side rename of the set weight makes every session unloaded, so the "
        "sequence stops ADVANCING and serves the same session with `advanced_by: null` and the note 'no loaded Hevy "
        "session since the block start' — it can postpone, never skip or double a session, and the stale position is "
        "named on every plan. A failed read is `sequence_unreadable` / week None, never session 1. Pinned by "
        "tests/test_session_sequence_4110.py::test_engine_days_warmup_only_logs_and_rest_days_never_advance, "
        "::test_an_unread_record_is_unknown_never_session_one and "
        "::test_mutation_control_a_walk_that_advances_the_position_reds_the_fixture.",
    ),
    # #4075 decision 4A (2026-09-23): get_training view=load stopped running its own
    # Hevy-blind day model and now reads the hevy partition — but only to hand the rows,
    # untouched, to training_load.daily_training_load, the SAME function daily-metrics-compute
    # feeds (whose hevy read is already in the residue above).
    "hevy::mcp/tools_training.py::read": (
        "2026-09-23",
        "#4075 4A: `_get_training_load` reads no hevy field itself; it passes the rows to "
        "training_load.daily_training_load, the one consumer daily-metrics-compute also feeds, so this seam adds no "
        "second shape to agree on. The shape that consumer depends on (`exercises[].sets[]` with `type`/`reps`/"
        "`duration_sec`/`distance_m`, `start_time`/`end_time`, `duration_sec`, `tombstone`) is pinned key-for-key "
        "from a live SOURCE#hevy read in tests/test_training_load_worked_set_4075.py, and a record with no set log "
        "degrades to the stated work fraction BY NAME (basis `no_set_log_work_fraction`), never to zero.",
    ),
}

__all__ = ["PAIR_SEAM_RESIDUE", "PAIR_SEAM_DECISIONS", "SEED_DATE"]
