# Life Platform Handover — v3.7.43
**Date:** 2026-03-15
**Session type:** Big batch — R14-F07, R13-F07/F10, IC-4/IC-5 skeletons, ADR-029, warmer, docs + PITR drill

## Platform Status
- **Version:** v3.7.43
- **MCP tools:** 89
- **Lambdas:** 43 (CDK) + 1 Lambda@Edge + 2 new skeleton files (IC-4/IC-5, not yet wired to CDK/EventBridge)
- **CloudWatch alarms:** 49 (us-west-2) + 2 new in us-east-1 (life-platform-dash-5xx-rate, life-platform-dash-total-errors)
- **Tests:** 16/16 passing

## What Was Done This Session

| Item | Status | Notes |
|------|--------|-------|
| R14-F07 | ✅ Complete | CloudFront 5xx alarms live in us-east-1, SNS confirmed |
| R13-F07 | ✅ Complete | PITR drill run: 270s restore, 4/6 partitions verified (2 false failures — bash whitespace bug, data confirmed intact), drill table deleted. Script bug fixed + committed. Next drill ~2026-06-15 |
| R13-F10 | ✅ Complete | `weekly_correlation_compute_lambda.py` → `from digest_utils import d2f`; added to layer consumers; Lambda deployed |
| R13-F01 | ✅ Confirmed existing | `ci-cd.yml` is a full 7-job pipeline |
| R13-F08 | ✅ Confirmed existing | `test_layer_version_consistency.py` in CI + plan job live check |
| Centenarian benchmarks | ✅ Complete | Warmer step 13 deployed, `mcp/warmer.py` + `life-platform-mcp` redeployed |
| IC-4 skeleton | ✅ Written | `lambdas/failure_pattern_compute_lambda.py` — data-gated MIN_DAYS=42, activate ~2026-05-01 |
| IC-5 skeleton | ✅ Written | `lambdas/momentum_warning_compute_lambda.py` — data-gated MIN_DAYS=42, activate ~2026-05-01 |
| ADR-029 | ✅ Complete | MCP monolith retain decision + split trigger checklist in DECISIONS.md |
| INCIDENT_LOG.md | ✅ Complete | Header updated to v3.7.43 |
| PROJECT_PLAN.md | ✅ Complete | Header updated to v3.7.43 |
| INTELLIGENCE_LAYER.md | ✅ Complete | Updated v3.3.9 → v3.7.41 (hypothesis engine v1.2.0, weekly correlations, W3 validator, ADR-025) |

## PITR Drill Record
- **Date:** 2026-03-15
- **Result:** PASSED (with cosmetic script warnings)
- **Restore time:** 270s (~4.5 min)
- **Partitions verified:** computed_metrics ✅, insights ✅, platform_memory ✅, withings ✅, whoop ✅ (confirmed via 7-day query), strava ✅ (confirmed present, bash whitespace bug caused false 0)
- **Next drill:** ~2026-06-15

## IC-4 / IC-5 Activation Checklist (~2026-05-01)
Both skeletons written, not yet wired to CDK/EventBridge. When activating:
1. Check data gate: `days_available >= 42` in `habit_scores` (IC-4) and `computed_metrics` (IC-5)
2. Implement the TODO detector bodies in each Lambda
3. Create EventBridge rules:
   - IC-4: `cron(45 18 ? * SUN *)` → `failure-pattern-compute`
   - IC-5: `cron(50 17 * * ? *)` → `momentum-warning-compute`
4. Add to CDK Compute stack and `ci/lambda_map.json`
5. Wire platform_memory reader in `daily_insight_compute_lambda.py` to pull `failure_patterns` + `momentum_warning` records as context

## Remaining Work

| ID | Item | Effort | Notes |
|----|------|--------|-------|
| **CLEANUP-3** | Google Calendar OAuth | S (20min) | `python3 setup/setup_google_calendar_auth.py` — been deferred since v3.7.21 |
| **AR #15** | Architecture Review #15 | L (full session) | Bundle generated at v3.7.43. Use Opus. Read `docs/reviews/REVIEW_BUNDLE_2026-03-15.md` |
| SIMP-1 Phase 2 | MCP tool cuts to ≤80 | L | Data-gated ~Apr 13 |
| IC-4/IC-5 activation | Implement detector bodies | L | Data-gated ~May 2026 |

## Next Session Recommendations
1. **CLEANUP-3** — Google Calendar OAuth (20 min, unblocks last missing data source)
2. **AR #15** — full Opus review session
