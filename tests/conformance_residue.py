"""tests/conformance_residue.py — the #2844 conformance-guard exemption ledger.

THE dated, shrink-only record of every hand-typed enumeration of registry
vocabulary that predates the guard (charter standing rule 1, docs/CHARTER.md).
Each key is ``path::vocabulary::matched-members`` — content-keyed on purpose:
EDITING an exempted hand-list changes its key, surfaces as a NEW violation, and
the only green path is deriving the site from its registry. Re-dating an entry
is not a thing; entries only ever come OUT (the #1964 ratchet precedent).

Populated honestly by the initial sweep on 2026-08-17 (37 sites). Every entry
is real debt: convert the site to a registry projection, then delete its line.

2026-08-24 (#3049): -2. The two compute Lambdas that hand-typed their own ingest
set now derive it from the compute-input census
(`lambdas/common/input_manifest.py`, sanctioned in conformance_guard_lib) — one
declaration feeding both the recompute fingerprint and the input-freshness
manifest, instead of two copies of the same list feeding neither.
"""

CONFORMANCE_RESIDUE: dict[str, str] = {
    "cdk/stacks/monitoring_dashboards.py::lambdas::adaptive-mode-compute,character-sheet-compute,daily-brief,daily-insight-compute,daily-metrics-compute": "2026-08-17",
    "cdk/stacks/monitoring_stack.py::lambdas::between-chronicle,chronicle-email-sender,weekly-signal": "2026-08-17",
    "cdk/stacks/monitoring_stack.py::sources::dropbox,habitify,todoist,whoop": "2026-08-17",
    "cdk/stacks/monitoring_stack.py::sources::eightsleep,hevy,strava,whoop,withings": "2026-08-17",
    "cdk/stacks/monitoring_stack.py::sources::garmin,notion": "2026-08-17",
    "lambdas/content/engagement_core.py::sources::apple_health,eightsleep,whoop": "2026-08-17",
    "lambdas/content/html_builder.py::sources::habitify,macrofactor,strava,whoop": "2026-08-17",
    "lambdas/content/insight_writer.py::sources::garmin,strava,whoop": "2026-08-17",
    "lambdas/emails/anomaly_detector_lambda.py::sources::eightsleep,garmin,habitify,macrofactor,strava,todoist,whoop,withings": "2026-08-17",
    "lambdas/emails/chronicle_render.py::personas::andrew_huberman,elena_voss,layne_norton,margaret_calloway,maya_rodriguez,paul_conti,peter_attia,rhonda_patrick,the_chair,vivek_murthy": "2026-08-17",
    "lambdas/emails/freshness_checker_lambda.py::sources::apple_health,eightsleep,habitify,whoop": "2026-08-17",
    "lambdas/emails/monthly_digest_lambda.py::sources::hevy,macrofactor,strava,todoist,whoop,withings": "2026-08-17",
    "lambdas/emails/partner_email_lambda.py::sources::apple_health,habitify,macrofactor,strava,whoop,withings": "2026-08-17",
    "lambdas/emails/weekly_digest_lambda.py::sources::apple_health,eightsleep,garmin,habitify,macrofactor,strava,todoist,whoop,withings": "2026-08-17",
    "lambdas/health/character_engine.py::sources::habitify,macrofactor,strava": "2026-08-17",
    "lambdas/health/pillar_absence.py::sources::habitify,todoist": "2026-08-17",
    "lambdas/health/pillar_absence.py::sources::hevy,strava": "2026-08-17",
    "lambdas/intelligence/ai_expert_analyzer_lambda.py::sources::garmin,strava": "2026-08-17",
    "lambdas/intelligence/intelligence_common.py::sources::apple_health,eightsleep,garmin,habitify,macrofactor,measurements,notion,strava,supplements,whoop,withings": "2026-08-17",
    "lambdas/intelligence/intelligence_common.py::sources::eightsleep,whoop": "2026-08-17",
    "lambdas/intelligence/intelligence_common.py::sources::garmin,strava": "2026-08-17",
    "lambdas/operational/ai_quality_canary_lambda.py::personas::sleep_coach,training_coach": "2026-08-17",
    "lambdas/operational/qa_check_subscriber_promise.py::lambdas::between-chronicle,chronicle-email-sender,weekly-signal": "2026-08-17",
    "lambdas/web/site_api_ai_lambda.py::personas::nutrition_coach,sleep_coach,training_coach": "2026-08-17",
    "lambdas/web/site_api_nutrition.py::sources::habitify,strava,whoop": "2026-08-17",
    "lambdas/web/site_api_rollups.py::sources::macrofactor,notion,withings": "2026-08-17",
    "lambdas/web/site_api_status.py::sources::eightsleep,whoop": "2026-08-17",
    "lambdas/web/site_stats_refresh_lambda.py::lambdas::habitify-data-ingestion,whoop-data-ingestion,withings-data-ingestion": "2026-08-17",
    "lambdas/web/vitals_resolver.py::sources::apple_health,garmin": "2026-08-17",
    "mcp/tools_labs.py::sources::apple_health,eightsleep,habitify,whoop": "2026-08-17",
    "mcp/tools_lifestyle.py::sources::apple_health,hevy,strava": "2026-08-17",
    "mcp/tools_nutrition.py::sources::habitify,hevy,strava,whoop": "2026-08-17",
    "mcp/tools_nutrition.py::sources::macrofactor,withings": "2026-08-17",
}
