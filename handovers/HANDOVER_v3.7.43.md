# Life Platform Handover — v3.7.43
**Date:** 2026-03-15
**Session type:** Big batch — R14-F07, R13-F07/F10, IC-4/IC-5 skeletons, ADR-029, warmer, docs

## Platform Status
- **Version:** v3.7.43
- **MCP tools:** 89
- **Lambdas:** 43 (CDK) + 1 Lambda@Edge + 2 new skeleton files (IC-4/IC-5, not yet deployed)
- **CloudWatch alarms:** 49 (+ 2 new in us-east-1 pending script run)
- **Tests:** 16/16 passing

## What Was Done This Session

| Item | Status | Notes |
|------|--------|-------|
| R14-F07 | ✅ Script written | `bash deploy/create_cloudfront_5xx_alarm.sh` — run once, confirm email |
| R13-F07 | ✅ Script written | `bash deploy/pitr_restore_drill.sh` — run quarterly, first drill ~Apr |
| R13-F10 | ✅ Done | `weekly_correlation_compute_lambda.py` → `from digest_utils import d2f`; added to layer consumers in `ci/lambda_map.json` |
| R13-F01 | ✅ Confirmed existing | `ci-cd.yml` is a full 7-job pipeline |
| R13-F08 | ✅ Confirmed existing | `test_layer_version_consistency.py` in CI + plan job live check |
| Centenarian benchmarks | ✅ Done | `mcp/warmer.py` step 13 — `get_centenarian_benchmarks` cached nightly |
| IC-4 skeleton | ✅ Written | `lambdas/failure_pattern_compute_lambda.py` — data-gated, activate ~2026-05-01 |
| IC-5 skeleton | ✅ Written | `lambdas/momentum_warning_compute_lambda.py` — data-gated, activate ~2026-05-01 |
| ADR-029 | ✅ Done | MCP monolith retain decision documented; split trigger checklist |
| INCIDENT_LOG.md | ✅ Done | Header updated to v3.7.43 |
| PROJECT_PLAN.md | ✅ Done | Header updated to v3.7.43 |

## Pending One-Time Actions (Matthew to run)

```bash
# R14-F07: Create CloudFront 5xx alarms (run once)
bash deploy/create_cloudfront_5xx_alarm.sh
# Then confirm the SNS subscription email at awsdev@mattsusername.com

# R13-F10: Deploy weekly-correlation-compute with layer attachment
bash deploy/deploy_lambda.sh weekly-correlation-compute lambdas/weekly_correlation_compute_lambda.py

# Warmer step 13: Redeploy MCP server (warmer.py changed)
bash deploy/deploy_lambda.sh life-platform-mcp lambdas/mcp_server.py
```

## IC-4 / IC-5 Activation Checklist (~2026-05-01)
Both skeletons are deployed-ready but data-gated. When activating:
1. Check data gate: `days_available >= 42` in `habit_scores` (IC-4) and `computed_metrics` (IC-5)
2. Implement the TODO detector bodies in each Lambda
3. Create EventBridge rules:
   - IC-4: `cron(45 18 ? * SUN *)` → `failure-pattern-compute`
   - IC-5: `cron(50 17 * * ? *)` → `momentum-warning-compute`
4. Add to CDK Compute stack and lambda_map.json
5. Wire platform_memory reader in `daily_insight_compute_lambda.py` to pull `failure_patterns` + `momentum_warning` records as context

## Remaining Work

| ID | Item | Effort | Notes |
|----|------|--------|-------|
| **CLEANUP-3** | Google Calendar OAuth | S (20min) | `python3 setup/setup_google_calendar_auth.py` |
| R13-F07 | Run PITR drill | S (20min runtime) | Script ready, ~5-20 min wait |
| R14-F07 | Run CloudFront alarm script | XS (2min) | Script ready |
| SIMP-1 Phase 2 | MCP tool cuts to ≤80 | L | Data-gated ~Apr 13 |
| AR #15 | Architecture Review #15 | L | After R14 fully paid down |

## Next Session Recommendations
1. Run the three pending one-time commands above (5 min total)
2. **CLEANUP-3** — Google Calendar OAuth (last remaining data source gap)
3. **AR #15** — run `python3 deploy/generate_review_bundle.py` first
