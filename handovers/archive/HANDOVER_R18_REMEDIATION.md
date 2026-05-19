# Handover — R18 Remediation (v4.3.1, 2026-03-28)

## Summary
Executed all 7 phases of R18 architecture review remediation. 9 findings addressed, 3 R17 findings verified resolved.

## Phases Completed

| Phase | Finding | Status |
|-------|---------|--------|
| 1 | R18-F01/F08: Doc reconciliation | Done — all headers updated, INTELLIGENCE_LAYER frozen, audit script created |
| 2 | R18-F03: lambda_map.json | Done — 2 entries added, CI orphan lint step added |
| 3 | R18-F04: New resource monitoring | Done — alarm script + freshness checker per-source override |
| 4 | R18-F06: WAF endpoint rules | Done — script created for /api/ask and /api/board_ask |
| 5 | R18-F05: Site deploy script | Done — deploy/deploy_site.sh with link validation |
| 6 | R17-F07/F08/F10 | Already resolved — CORS, google_calendar, model strings |
| 7 | Final sweep | Done — changelog + handover |

## Scripts Created (Matthew to run)
- `bash deploy/setup_r18_alarms.sh` — creates CloudWatch error alarms
- `bash deploy/setup_waf_endpoint_rules.sh` — adds WAF rate rules

## Deferred (per remediation prompt)
- R18-F02: CDK adoption of CLI Lambdas (dedicated CDK session)
- R18-F07: SIMP-1 Phase 2 (110→80 tools, post-launch)
- R18-F09: Cross-region migration (post-launch)
- R17-F12: PITR restore drill (manual verification)
