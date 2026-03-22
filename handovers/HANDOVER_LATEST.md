→ See handovers/HANDOVER_v3.8.8.md

This session (2026-03-22):
- Phase 0 website data fixes per WEBSITE_REDESIGN_SPEC.md
- G-3, G-4: site_api_lambda.py handle_vitals + handle_journey fixed
- G-3 ticker: weight fallback to /api/vitals with stale date display
- STORY-1, PLAT-1: public_stats.json wired to hardcoded stat spans
- PROTO-1: removed fake fallback adherence values
- CHRON-1/G-5: already done; CHRON-2: week-01 gap noted; G-7: investigated

PENDING DEPLOY (do these in order):
1. Deploy Lambda (site_api_lambda.py changed):
   bash deploy/deploy_lambda.sh life-platform-site-api lambdas/site_api_lambda.py
   (wait 10s)

2. Deploy site files to S3:
   aws s3 cp site/index.html s3://matthew-life-platform/site/index.html
   aws s3 cp site/story/index.html s3://matthew-life-platform/site/story/index.html
   aws s3 cp site/platform/index.html s3://matthew-life-platform/site/platform/index.html
   aws s3 cp site/protocols/index.html s3://matthew-life-platform/site/protocols/index.html

3. Invalidate CloudFront:
   aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/" "/story/*" "/platform/*" "/protocols/*"

4. Answer: what is the correct contact email for /privacy/ page?
   Current: matt@averagejoematt.com
   Confirm or replace → then run: aws s3 cp site/privacy/index.html s3://...

5. G-7 subscribe investigation:
   Check if lifeplatform@mattsusername.com is verified in SES (us-west-2):
   ! aws sesv2 list-email-identities --region us-west-2
   Check CloudWatch logs: /aws/lambda/email-subscriber for errors

Next session entry point:
- Phase 1 redesigns (LIVE-2 Cockpit is highest impact)
- G-8 once email confirmed
- G-7 once SES verified

Key context:
- public_stats.json vitals.weight_lbs is null (bug in daily-brief Lambda, separate fix needed)
- The ticker now falls back to /api/vitals when public_stats has null weight
- Journey progress_pct=0 in public_stats.json is also a daily-brief Lambda bug
- STORY-1 wires lambdas+data_sources+mcp_tools; test_count/monthly_cost not in public_stats yet
