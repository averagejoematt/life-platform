# Life Platform — Session Handover
# Session: P2-P3 Engineering Hardening (MCP Split + Lambda Parameterization + DLQ)
# Date: 2026-02-28
# Version: v2.43.0

## What happened this session

### MCP Monolith Split (P2)
Split the 14,960-line `mcp_server.py` into a 21-module package:
- `mcp/handler.py` — request router (84 lines)
- `mcp/config.py` — shared constants, version string, USER_ID derivation
- `mcp/utils.py` — DynamoDB helpers, date parsing, cache layer
- 18 domain modules (`mcp/tools_sleep.py`, `mcp/tools_labs.py`, etc.)
- `mcp_server.py` remains as Lambda entry point (thin wrapper importing handler)
- 100% tool validation: all 94 tools registered, zero import errors
- Cold start 727ms (was ~750ms), warm calls 23-29ms
- Deployed via `deploy/deploy_mcp_split.sh`

### Lambda Parameterization (P2-P3)
Parameterized 19 Lambda source files (all except daily_brief and notion which were done in P0-P1):
- Replaced hardcoded `REGION`, `S3_BUCKET`, `DYNAMODB_TABLE` with `os.environ.get()` + backwards-compatible defaults
- Replaced all `USER#matthew` partition keys with `f"USER#{USER_ID}"` where `USER_ID = os.environ.get("USER_ID", "matthew")`
- Added `import os`, `import logging`, `logger = logging.getLogger()` to all 19 files
- Extracted `freshness_checker_lambda.py` from inline deploy script to proper source file
- Fixed `CACHE_PK` in `mcp/config.py` to use `USER_ID` variable (was hardcoded)
- Added `__version__ = "2.43.0"` to `mcp/config.py`, imported by handler for serverInfo

### DLQ Configuration (P3)
- Added `sqs:SendMessage` inline policy (`sqs-dlq-send`) to 3 IAM roles:
  - `lambda-weekly-digest-role` (used by monthly-digest, daily-brief, weekly-digest)
  - `lambda-anomaly-detector-role`
  - `lambda-freshness-checker-role`
- Configured DLQ (`life-platform-ingestion-dlq`) on all 5 previously-uncovered scheduled Lambdas:
  - monthly-digest, anomaly-detector, daily-brief, life-platform-freshness-checker, weekly-digest
- **Result: 20/22 Lambdas now have DLQ** (only MCP + HAE webhook excluded — request/response pattern)

### Bug Fix: Anomaly Detector ImportModuleError
- Pre-existing issue: anomaly-detector was broken (`No module named 'lambda_function'`)
- Root cause: previous deploy zipped with wrong entry filename
- Fixed by deploying parameterized code with correct `lambda_function.py` zip entry name

### Deploy Infrastructure Improvements
- `deploy/deploy_unified.sh` — updated freshness checker registry entry to `freshness_checker_lambda.py`
- `deploy/deploy_hardening_v2.sh` — simplified hardening deploy (used for successful deployment)
- Documented correct handler-to-filename mapping for all 22 Lambdas

## Validation results
- ✅ MCP Lambda: cold start 758ms, 94 tools, version string working
- ✅ Anomaly detector: fixed, running v2.1.0 with adaptive thresholds
- ✅ Freshness checker: querying all sources, sending alerts correctly
- ✅ Whoop ingestion: full cycle including 3 workouts
- ✅ Strava ingestion: 1 activity with HR recovery data
- ✅ Monthly digest: Haiku call + email sent successfully
- ✅ All 19 Lambdas deployed (timestamps 02:39-02:40 UTC)
- ✅ All 5 DLQs configured after IAM fix
- ✅ All Lambda source files pass Python syntax check

## Files modified

### Lambda source files (19 in lambdas/):
whoop_lambda.py, strava_lambda.py, garmin_lambda.py, eightsleep_lambda.py,
macrofactor_lambda.py, todoist_lambda.py, withings_lambda.py, habitify_lambda.py,
apple_health_lambda.py, health_auto_export_lambda.py, dropbox_poll_lambda.py,
weather_lambda.py, enrichment_lambda.py, journal_enrichment_lambda.py,
insight_email_parser_lambda.py, anomaly_detector_lambda.py, monthly_digest_lambda.py,
weekly_digest_v2_lambda.py, freshness_checker_lambda.py (new)

### MCP package (in mcp/):
config.py (CACHE_PK fix + __version__), handler.py (version import)

### Deploy scripts:
deploy/deploy_hardening_v2.sh, deploy/deploy_unified.sh (registry fix)

### IAM:
3 roles gained `sqs-dlq-send` inline policy

## Current state
- Version: v2.43.0
- 94 MCP tools across 21-module package
- 22 Lambdas: all parameterized, python3.12, standardized logging
- 20/22 Lambdas with DLQ coverage
- Anomaly detector: fixed and operational
- All 5 hardening items complete

## Handler-to-filename mapping (reference)
```
lambda_function.py:           whoop, apple-health, todoist, anomaly-detector,
                              monthly-digest, insight-email-parser, freshness-checker
strava_lambda.py:             strava-data-ingestion
garmin_lambda.py:             garmin-data-ingestion
eightsleep_lambda.py:         eightsleep-data-ingestion
macrofactor_lambda.py:        macrofactor-data-ingestion
withings_lambda.py:           withings-data-ingestion
habitify_lambda.py:           habitify-data-ingestion
weather_lambda.py:            weather-data-ingestion
dropbox_poll_lambda.py:       dropbox-poll
enrichment_lambda.py:         activity-enrichment
journal_enrichment_lambda.py: journal-enrichment
health_auto_export_lambda.py: health-auto-export-webhook
notion_lambda.py:             notion-journal-ingestion
daily_brief_lambda.py→lambda_function.py: daily-brief
weekly_digest_v2_lambda.py→digest_handler.py: weekly-digest
mcp_server.py:                life-platform-mcp
```

## Next steps
- Feature #1 (Monarch Money) or #2 (Google Calendar) — demand-side data gaps
- Feature #13 (Annual Health Report)
- Feature #15 (MCP API key auto-rotation)
- Feature #19 (Data export & portability)
