# Life Platform Handover — v3.7.46
**Date:** 2026-03-15
**Session type:** Google Calendar retirement (ADR-030) + cleanup

## Platform Status
- **Version:** v3.7.46
- **MCP tools:** 87 (was 89 — retired get_calendar_events + get_schedule_load)
- **Data sources:** 19 active (was 20 — google_calendar retired)
- **Lambdas:** 43 CDK + 2 Lambda@Edge
- **CloudWatch alarms:** ~49
- **Tests:** 83/83 passing

## What Was Done This Session

| Item | Status | Notes |
|------|--------|-------|
| Google Calendar retirement | ✅ Complete | ADR-030 logged. All 7 integration paths evaluated and blocked. |
| registry.py | ✅ Complete | get_calendar_events + get_schedule_load removed. tools_calendar import removed. 89→87 tools. |
| freshness_checker_lambda.py | ✅ Complete | google_calendar removed from SOURCES + FIELD_COMPLETENESS_CHECKS. 10→9 sources. |
| lambda_map.json | ✅ Complete | google_calendar_lambda.py marked not_deployed. |
| DECISIONS.md | ✅ Complete | ADR-030 added with options-and-blockers table. ADR-029 added to index. |
| MCP Lambda deployed | ✅ Complete | Live tool count now 87. |
| google-calendar secret | ✅ N/A | Never created (OAuth was never completed). ResourceNotFoundException confirmed. |
| setup/calendar_sync.py | ⚠️ Kept | Marked RETIRED in file header. Not deleted — serves as reference for ADR-030. |

## Pending CDK Cleanup (next CDK deploy session)
Remove `google-calendar-ingestion` from `cdk/stacks/ingestion_stack.py`:
- Remove the Lambda definition
- Remove the EventBridge rule
- Remove the IAM role call
- Run `npx cdk deploy LifePlatformIngestion` + `post_cdk_reconcile_smoke.sh`

This is low-urgency — the Lambda exists in AWS but is harmless (returns `pending_oauth` on every run, no alerts fire). Clean it up before AR #15.

## Session Summary (full day)

This was a long session. What got done:
- R15-F01 through F06: doc accuracy + test guard (v3.7.44)
- R13-F01/F02/F07/F08/F10/F15: CI/CD activation + lambda_map fixes (v3.7.45)
- OIDC role provisioned, GitHub production Environment confirmed
- Redundant IAM policies cleaned up (3 old policies deleted)
- Google Calendar retirement after exhausting all integration paths (v3.7.46)

## Next Session Recommendations
1. **CDK cleanup** — remove google-calendar-ingestion from ingestion_stack.py (15 min)
2. **AR #15** — full Opus review session. Bundle at `docs/reviews/REVIEW_BUNDLE_2026-03-15.md`. Platform at its cleanest baseline: 87 tools, 19 sources, 0 open R13 findings, CI/CD live.
