# Handover v3.8.7 — 2026-03-22

## Session Summary
Full session: Phase 2 website depth (5 pages), then CI/CD pipeline activation prep.

## What Was Done

### CI/CD Pipeline — Already Built, Just Needs Activation
R13 flagged "no CI/CD pipeline" as F01 but the pipeline was actually built as a direct
response to R13 (setup_github_oidc.sh comment: "v1.0.0 — 2026-03-15 R13-F01").

The pipeline in .github/workflows/ci-cd.yml already covers everything R13 asked for:
- Lint (flake8 + py_compile)
- pytest (83+ tests including test_secret_references.py = F04, test_layer_version_consistency.py = F08)
- CDK diff with IAM/destruction gates
- Stateful resource assertions
- Live layer version consistency check
- Manual approval gate (GitHub 'production' environment)
- Deploy (lambda_map.json change detection)
- Smoke test + canary
- Auto-rollback on smoke failure (TB7-25)
- SNS notify on any failure

The only gap: **never activated**. OIDC role not created, GitHub environment not created.

### lambda_map.json fix
`lambdas/site_api_lambda.py` was in `skip_deploy` but is a real deployed Lambda
(life-platform-site-api, us-west-2). Moved to `lambdas` section. `_updated` bumped.

## Activation Steps (Matthew runs these)

```bash
# Step 1: Create OIDC provider + IAM role in AWS (idempotent, safe to re-run)
bash deploy/setup_github_oidc.sh

# Step 2: Create 'production' GitHub Environment (one-time, in browser)
# https://github.com/averagejoematt/life-platform/settings/environments
# Name it exactly: production
# Add yourself as required reviewer

# Step 3: Commit + push to trigger first pipeline run
git add -A && git commit -m "v3.8.7: activate CI/CD pipeline" && git push

# Step 4: Watch Actions tab
# https://github.com/averagejoematt/life-platform/actions
# The deploy job will pause for manual approval — approve if changes look right
```

## What to Expect on First Run

The pipeline triggers on push to main when `lambdas/`, `mcp/`, or `mcp_server.py` change.
This commit touches `ci/lambda_map.json` only — so lint + test + plan will run, but the
deploy job will show `has_deploys=false` and skip. Clean green run expected.

## Files Changed This Session

| File | Change |
|------|--------|
| `site/discoveries/index.html` | Empty state + last-updated note (v3.8.5) |
| `site/live/index.html` | Glucose snapshot panel (v3.8.6) |
| `site/character/index.html` | Live state banner + dynamic tier (v3.8.6) |
| `ci/lambda_map.json` | site_api moved from skip_deploy → lambdas |
| `docs/CHANGELOG.md` | v3.8.5, v3.8.6, v3.8.7 entries |
| `handovers/HANDOVER_LATEST.md` | Updated |

## Pending Site Deploy

```bash
aws s3 cp site/live/index.html s3://matthew-life-platform/site/live/index.html
aws s3 cp site/character/index.html s3://matthew-life-platform/site/character/index.html
aws s3 cp site/discoveries/index.html s3://matthew-life-platform/site/discoveries/index.html
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/live/*" "/character/*" "/discoveries/*"
```

## Next Session

1. Verify first CI/CD run passed (check Actions tab)
2. **F02**: 3-5 integration tests against live AWS (post-deploy checks I3/I10 not yet covered)
3. **F05**: OAuth fail-open fix — `mcp/handler.py`, `if expected is None: return True` → reject
4. **SIMP-1 Phase 2** remains ~April 13

## Platform State
- Version: v3.8.7
- Architecture grade: A- (R13 F01 now closed pending first pipeline run)
- Phase 2: ✅ COMPLETE
- CI/CD: Built ✅ | Activated ⏳ (pending setup_github_oidc.sh + environment creation)
