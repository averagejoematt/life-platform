# Life Platform Handover — v3.7.45
**Date:** 2026-03-15
**Session type:** R13 findings batch — CI/CD activation + lambda_map fixes

## Platform Status
- **Version:** v3.7.45
- **MCP tools:** 89
- **Lambdas:** 43 CDK + 2 Lambda@Edge
- **CloudWatch alarms:** ~49
- **Tests:** 83/83 passing

## What Was Done This Session

| Item | Status | Notes |
|------|--------|-------|
| R13-F01 (CI/CD pipeline) | ✅ Complete | `deploy/setup_github_oidc.sh` created and executed. OIDC provider existed; trust policy + `life-platform-cicd-permissions` inline policy applied. Role ARN: `arn:aws:iam::205930651321:role/github-actions-deploy-role` |
| R13-F02 (integration tests in CI) | ✅ Complete | I4/I6/I7/I8/I9 added to post-deploy-checks job in ci-cd.yml. I1/I2/I5 already existed. |
| lambda_map.json fixes | ✅ Complete | Added google_calendar, evening_nudge, weekly_correlation. failure_pattern + momentum_warning flagged `not_deployed` (skeleton — not yet in AWS). |
| R13-F07 (PITR drill) | ✅ Confirmed done | Marked done v3.7.43 in PROJECT_PLAN. |
| R13-F08 (layer CI test) | ✅ Confirmed done | Marked done v3.7.38 in PROJECT_PLAN. |
| R13-F10 (d2f consolidation) | ✅ Confirmed done | Marked done v3.7.43 in PROJECT_PLAN. |
| R13-F15 (BH FDR correction) | ✅ Confirmed done | Marked done v3.7.37 in PROJECT_PLAN. |
| PROJECT_PLAN | ✅ Updated | R13 open findings: 12 → 2 (only F03 monolith split, deferred per ADR-029). |

## One Remaining CI/CD Step

The OIDC role is live. One manual step remains before the pipeline will actually gate deploys:

**Create the GitHub `production` Environment:**
https://github.com/averagejoematt/life-platform/settings/environments

This is the manual approval gate on the `deploy` job. Without it, the deploy job runs unguarded on every push. Takes 2 minutes in the GitHub UI.

After that, the first push to main touching `lambdas/**` or `mcp/**` will trigger the full 7-job pipeline.

## Note on Existing IAM Policies

The `github-actions-deploy-role` had pre-existing inline policies (`cloudwatch-read`, `lambda-deploy`, `s3-read`) from prior manual setup. The script added `life-platform-cicd-permissions` alongside them. These older policies are now redundant (the new one is a superset) but harmless. Can clean up later with:
```bash
aws iam delete-role-policy --role-name github-actions-deploy-role --policy-name cloudwatch-read
aws iam delete-role-policy --role-name github-actions-deploy-role --policy-name lambda-deploy
aws iam delete-role-policy --role-name github-actions-deploy-role --policy-name s3-read
```

## Remaining Work

| ID | Item | Effort | Notes |
|----|------|--------|-------|
| **TB7-1** | GitHub `production` Environment gate | S (2min) | See above — https://github.com/averagejoematt/life-platform/settings/environments |
| **CLEANUP-3** | Google Calendar OAuth | S (20min) | `python3 setup/setup_google_calendar_auth.py` — last missing data source |
| **AR #15** | Architecture Review #15 | L (full session) | Bundle at `docs/reviews/REVIEW_BUNDLE_2026-03-15.md`. Use Opus. All R13 findings closed — clean baseline. |
| SIMP-1 Phase 2 | MCP tool cuts to ≤80 | L | Data-gated ~Apr 13 |
| IC-4/IC-5 activation | Implement detector bodies | L | Data-gated ~May 2026 |

## Next Session Recommendations
1. **TB7-1** — 2-minute GitHub UI task, unblocks CI/CD deploy gating
2. **CLEANUP-3** — Google Calendar OAuth (20 min, unblocks last data source)
3. **AR #15** — Full Opus review session; platform is at its cleanest baseline yet
