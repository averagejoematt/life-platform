→ See handovers/HANDOVER_v3.8.1.md

This session (2026-03-22):
- Reconciled gap between last chat session (Mar 21) and Claude Code sessions
- Diagnosed D1 root cause: sick day Lambda path skipped write_public_stats
- Fixed public_stats.json: weight=287.7, lost=14.3lbs, progress=12.2%, days_in=28
- Removed all hardcoded platform stats from daily_brief_lambda + scripts
- HTML fixes: D3 (streak null→0), D5 (homepage data_sources prose), D6 (story page)
- Committed v3.8.1, deployed to S3 + CloudFront, pushed to GitHub

Next session entry point:
1. Phase 0 remaining: D10 (Day 1 baseline hardcoded in compare card HTML)
2. Phase 1: 5-section nav restructure, page merges, /journal/ → /chronicle/ rename
3. Check if Withings has resumed syncing (last weigh-in was 2026-03-07 pre-illness)
4. WEBSITE_STRATEGY.md Phase 1 tasks 13-21 are next after D10

Key context:
- public_stats.json now fully dynamic — no hardcoded values
- daily_brief_lambda D1-FIX: sick day path now calls write_public_stats
- platform_meta field added to DynamoDB PROFILE#v1
- fix_public_stats.py: run with --write anytime to force-refresh S3 stats
- Withings data gap: Mar 7 → present (sick period, no weigh-ins)
- Lambda function name: "daily-brief" (not CDK-generated name)
- site-api Lambda is in us-east-1, all others in us-west-2
