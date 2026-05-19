# Handover — v4.4.0 (2026-03-29)

## Session Summary
24-hour launch readiness session. Status page rebuilt from scratch with 3-layer monitoring. Pipeline validation found and fixed 4 silent failures. Reader engagement (4 phases), subscriber email redesign, homepage rewrite, and dozens of fixes.

## Critical: Action Items for Matthew
1. **Garmin re-auth** — wait until tomorrow morning, try once: `python3 setup/setup_garmin_auth.py`. If 429 again, try from different network or wait 24h.
2. **Notion journal** — pipeline works. Entries no longer need Template or Date properties. Any entry in your journal database will be processed. Test by writing a new entry and running: `aws lambda invoke --function-name notion-journal-ingestion --region us-west-2 /tmp/notion.json`

## What Was Fixed (Silent Failures Caught)
| Issue | How Found | Root Cause | Fix |
|-------|-----------|------------|-----|
| Eight Sleep down 10 days | Manual check | `logger.set_date` crash | `hasattr` guard + re-auth |
| Dropbox secret deleted | Deep pipeline probe | Secret scheduled for deletion Mar 10 | Restored |
| Notion secret deleted | Deep pipeline probe | Secret scheduled for deletion | Restored |
| Health Auto Export crash | Pipeline health check | `logger.set_date` (deployed old code) | Redeployed |
| Garmin broken | Pipeline health check | Missing modules + expired tokens | Layer published, auth pending |

## New Infrastructure
- `pipeline-health-check` Lambda — daily at 6 AM PT, probes 17 Lambdas + 11 secrets
- `subscriber-onboarding` Lambda — Day 2 bridge email for new subscribers
- `og-image-generator` — now generates 12 images (was 6)
- `garth-layer:2` — garth + garminconnect for Garmin Lambda
- `pillow-layer:1` — Pillow for OG image generation
- CloudWatch alarm overlay on status page
- Cost Explorer integration on status page
- DLQ depth monitoring

## Known Issues (Not Blocking Launch)
- Garmin auth expired (Garmin SSO rate limiting — retry tomorrow)
- DLQ has 25 messages (accumulated from pre-fix failures)
- Some Apple Health sub-sources share same DDB partition (BP shows generic apple_health date)

## Post-Launch Roadmap
- CDK adoption of CLI-created Lambdas
- Cross-region migration (site-api us-east-1 → us-west-2)
- Site API monolith split
- Endpoint test suite
- Content-hashed CSS/JS filenames
- Hevy field mapping for strength benchmarks
- Turn pipeline health check into status page section with per-probe results

## Platform Stats
- 67 pages, 60+ API endpoints, 116 MCP tools, 59 Lambdas
- 26 data sources, 7 CDK stacks
- Health check: 16/17 pass
- Overall status: yellow (Garmin only red item)
