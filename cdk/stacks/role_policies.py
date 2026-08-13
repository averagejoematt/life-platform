"""
role_policies.py — the public face of the Life Platform's per-Lambda IAM policies.

Each `role_policies.<name>()` returns the list of `iam.PolicyStatement` objects for
exactly one Lambda's least-privilege role. No shared roles.

**This module is now a facade.** The statements themselves live in cohesive per-domain
siblings and are re-exported here unchanged, so every existing call site
(`from stacks import role_policies as rp` → `rp.site_api()`) and every IAM linter that
walks this module keeps resolving the full set:

    role_policies_base.py         ARN constants + `_s3` / `_secret_arn` / `_bedrock_statement`
    role_policies_ingestion.py    `_ingestion_base` + every `ingestion_<source>()`
    role_policies_compute.py      `_compute_base` + `compute_*` + `intelligence_*`
    role_policies_email.py        `_email_base` + `email_*`
    role_policies_operational.py  `_operational_base` + `operational_*`
    role_policies_serve.py        `site_api`, `site_api_ai`, `mcp_server`, `og_image`,
                                  the Hevy jobs, the R19 adopted Lambdas, `telegram_*`
    role_policies_permanence.py   `operational_permanence()` (#1400 — imported directly
                                  by operational_stack.py, and by the linters via glob)

Why (#2604): this file sat at **exactly** its recorded ceiling in
`tests/test_module_size_guard.py` — 3,291 of 3,291 lines — so the next Lambda that
needed a role could not get one without an unrelated refactor first. #1400 had already
established the answer (a cohesive sibling, never a raised baseline); #2604 applied it
to the whole file rather than one more special case.

Adding a policy: put it in the domain sibling, then add one re-export line here. The
IAM linters (`tests/test_role_policies.py`, `tests/test_raw_archive_role_parity.py`,
`tests/test_iam_secrets_consistency.py`, `tests/test_cdk_s3_paths.py`) all derive the
family by glob, so a sibling is covered the day it lands even before it is re-exported.

Policy principle: least-privilege per Lambda. Audit source: `aws iam get-role-policy`
on all 37 console-created `lambda-*` roles (2026-03-09).
"""

from stacks.role_policies_base import (  # noqa: F401  (re-export)
    ACCT,
    BUCKET,
    BUCKET_ARN,
    CF_DIST_ARN,
    CF_DIST_ID,
    DLQ_ARN,
    KMS_KEY_ARN,
    KMS_KEY_ID,
    REGION,
    S3_BUCKET,
    SES_CONFIG_SET_ARN,
    SES_DOMAIN,
    SES_IDENTITY,
    TABLE_ARN,
    TABLE_NAME,
    _bedrock_statement,
    _s3,
    _secret_arn,
)
from stacks.role_policies_compute import (  # noqa: F401  (re-export)
    compute_acwr,
    compute_adaptive_mode,
    compute_anomaly_detector,
    compute_challenge_generator,
    compute_character_sheet,
    compute_circadian_compliance,
    compute_coach_computation,
    compute_coach_daily_reflection,
    compute_coach_memoir,
    compute_coach_orchestrator,
    compute_coach_prediction_evaluator,
    compute_coach_state_updater,
    compute_daily_insight,
    compute_daily_metrics,
    compute_dashboard_refresh,
    compute_episode_detect,
    compute_failure_pattern,
    compute_forecast_engine,
    compute_hypothesis_engine,
    compute_personal_baselines,
    compute_scenario_explorer,
    compute_state_of_matthew,
    compute_voice_fidelity_harness,
    compute_weekly_correlations,
    intelligence_ai_expert,
    intelligence_field_notes,
    intelligence_journal_analyzer,
)
from stacks.role_policies_email import (  # noqa: F401  (re-export)
    email_ai_review_pack,
    email_between_chronicle,
    email_chronicle_approve,
    email_chronicle_podcast,
    email_chronicle_sender,
    email_coach_nudge,
    email_coach_panel_podcast,
    email_daily_brief,
    email_daily_debrief,
    email_elena_state_updater,
    email_evening_nudge,
    email_milestone_digest,
    email_monday_compass,
    email_monthly_digest,
    email_nutrition_review,
    email_partner,
    email_wednesday_chronicle,
    email_weekly_digest,
    email_weekly_plate,
    email_weekly_signal,
)
from stacks.role_policies_ingestion import (  # noqa: F401  (re-export)
    ingestion_activity_enrichment,
    ingestion_bluesky,
    ingestion_dropbox,
    ingestion_eightsleep,
    ingestion_garmin,
    ingestion_habitify,
    ingestion_hae,
    ingestion_hevy_backfill,
    ingestion_journal_enrichment,
    ingestion_macrofactor,
    ingestion_mastodon,
    ingestion_notion,
    ingestion_social_enrichment,
    ingestion_strava,
    ingestion_todoist,
    ingestion_weather,
    ingestion_whoop,
    ingestion_withings,
    ingestion_youtube,
)
from stacks.role_policies_operational import (  # noqa: F401  (re-export)
    operational_ai_quality_canary,
    operational_alert_digest,
    operational_canary,
    operational_coherence_sentinel,
    operational_cost_governor,
    operational_data_export,
    operational_data_reconciliation,
    operational_delete_user_data,
    operational_dlq_consumer,
    operational_email_subscriber,
    operational_freshness_checker,
    operational_insight_email_parser,
    operational_key_rotator,
    operational_og_image_generator,
    operational_pip_audit,
    operational_qa_smoke,
    operational_reading_cover_pipeline,
    operational_reading_recall_sweep,
    operational_remediation_dispatcher,
    operational_site_stats_refresh,
    operational_traffic_digest,
)
from stacks.role_policies_serve import (  # noqa: F401  (re-export)
    food_delivery_ingestion,
    hevy_restamp,
    hevy_routine_cron,
    mcp_server,
    measurements_ingestion,
    og_image,
    pipeline_health_check,
    site_api,
    site_api_ai,
    subscriber_onboarding,
    telegram_webhook,
    telegram_worker,
)
