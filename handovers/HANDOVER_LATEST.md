→ See handovers/HANDOVER_v3.8.3.md

This session (2026-03-22):
- Bug fix: deploy_d10_phase1.sh step 3 — Lambda deploy command missing source file + extra files
- Phase 2 /habits/ page: Keystone Spotlight + Day-of-Week Pattern sections
- site_api_lambda.py handle_habits() extended: day_of_week_avgs, best_day, worst_day, group_90d_avgs, keystone_group
- Confirmed: life-platform-site-api is in us-west-2 (not us-east-1)
- All deployed: Lambda (us-west-2) + S3 sync + CloudFront invalidation

Next session entry point:
1. Verify: curl -s 'https://averagejoematt.com/api/habits' | python3 -m json.tool | grep -E '"keystone|best_day|day_of_week'
2. Check /habits/ live — Keystone + DOW sections (may not show if group_* fields absent from habit_scores DynamoDB)
3. Withings check: still no weigh-ins since Mar 7
4. Phase 2 next: /experiments/ page depth OR investigate habit_scores group_* field presence

Key context:
- Phase 0: COMPLETE | Phase 1: COMPLETE | Phase 2: IN PROGRESS (habits done)
- Keystone/DOW sections hidden by default — only appear when API returns group data
- If sections aren't showing: check if habit_scores DynamoDB records have group_* fields
  (habitify ingestion Lambda may not be writing them)
- site-api deploy command: zip -j /tmp/site_api_deploy.zip lambdas/site_api_lambda.py &&
  aws lambda update-function-code --function-name life-platform-site-api
  --zip-file fileb:///tmp/site_api_deploy.zip --region us-west-2 --no-cli-pager
