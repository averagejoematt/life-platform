→ See handovers/HANDOVER_v3.8.7.md

This session (2026-03-22):
- Phase 2 complete: /discoveries/ empty state + /live/ glucose panel + /character/ live banner
- CI/CD: pipeline was already built post-R13 — just needed activation
- ci/lambda_map.json: site_api_lambda.py moved from skip_deploy → lambdas (life-platform-site-api)

PENDING DEPLOY (do these in order):
1. Deploy Phase 2 site files:
   aws s3 cp site/live/index.html s3://matthew-life-platform/site/live/index.html
   aws s3 cp site/character/index.html s3://matthew-life-platform/site/character/index.html
   aws s3 cp site/discoveries/index.html s3://matthew-life-platform/site/discoveries/index.html
   aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/live/*" "/character/*" "/discoveries/*"

2. Activate CI/CD pipeline:
   bash deploy/setup_github_oidc.sh
   → Then: create 'production' Environment at github.com/averagejoematt/life-platform/settings/environments
   → Then: git add -A && git commit -m "v3.8.7: activate CI/CD pipeline" && git push
   → Then: watch Actions tab — approve deploy job if Lambda changes detected

Next session entry point:
- After CI/CD activated and first run passes: F02 integration tests (3-5 tests against live AWS)
- F05 OAuth fail-open fix (30 min, mcp/handler.py)
- SIMP-1 Phase 2 remains on ~April 13 schedule

Key context:
- Pipeline already handles: lint → pytest → cdk diff → layer check → deploy → smoke → rollback → SNS notify
- Manual approval gate via GitHub 'production' Environment (required before deploy job runs)
- email_subscriber_lambda.py stays in skip_deploy (us-east-1, needs region override)
- acwr/circadian/sleep_reconciler stay in skip_deploy (skeleton/not-yet-deployed)
