# Life Platform Handover — v3.7.47 (R16)
**Date:** 2026-03-15
**Pointer:** `handovers/HANDOVER_LATEST.md` → this file

---

## Platform State

| Metric | Value |
|--------|-------|
| Version | v3.7.47 |
| MCP tools | 87 |
| Data sources | 19 active |
| Lambdas | 42 CDK + 2 Lambda@Edge |
| CloudWatch alarms | ~49 |
| Tests | 83/83 passing |
| MCP connector | ✅ Connected in claude.ai |
| Latest review | R16 — Grade: A (all dimensions hold) |

---

## What Was Done This Session

### v3.7.44 — R15 doc fixes
- F01: `tests/test_business_logic.py` ImportError guard + `sleep_quality` key fix (83 tests now collected)
- F02–F06: INFRASTRUCTURE secrets table, Lambda@Edge count, IC skeleton callout, MCP memory, warmer step count

### v3.7.45 — R13 CI/CD activation
- OIDC role provisioned (`arn:aws:iam::205930651321:role/github-actions-deploy-role`)
- I4/I6/I7/I8/I9 wired into CI post-deploy-checks
- `ci/lambda_map.json` fixed: 3 missing Lambdas added, 2 skeleton Lambdas flagged `not_deployed`
- GitHub `production` Environment confirmed (1 protection rule)

### v3.7.46 — ADR-030 Google Calendar retired
- `mcp/registry.py`: `get_calendar_events` + `get_schedule_load` removed (89→87 tools)
- `lambdas/freshness_checker_lambda.py`: `google_calendar` removed from SOURCES
- `docs/DECISIONS.md`: ADR-030 added (full options-and-blockers table)
- MCP deployed live — 87 tools confirmed

### v3.7.47 — CDK cleanup + MCP deploy guard + incident fix
- `cdk/stacks/ingestion_stack.py`: block 16 retired
- `deploy/deploy_lambda.sh`: MCP guard added (ADR-031)
- **MCP outage resolved**: `deploy_lambda.sh` stripped `mcp/` from zip. Fixed with full zip rebuild.

### Architecture Review #16
- Full 12-member Technical Board review conducted
- **Grade: A** — all dimensions hold from R15
- 6 new findings (1 Medium, 5 Low) + 4 carried forward
- All 6 R15 findings confirmed resolved
- Report: `docs/reviews/REVIEW_2026-03-15_v16.md`

---

## Pending Items for Next Session (prioritized from R16)

| Item | Priority | Notes |
|------|----------|-------|
| **R16-F04: CI/CD activation** | ⚠️ High (Medium finding) | `bash deploy/setup_github_oidc.sh` → create GitHub `production` Environment → trigger first pipeline run. Closes TB7-1. Highest-leverage item. |
| **R16-F03: CDK deploy** | Medium | `cd cdk && source .venv/bin/activate && npx cdk deploy LifePlatformIngestion --require-approval never` then `bash deploy/post_cdk_reconcile_smoke.sh`. Removes `google-calendar-ingestion` from AWS. |
| **R16-F02: Delete google-calendar secret** | Medium | `aws secretsmanager delete-secret --secret-id life-platform/google-calendar --recovery-window-in-days 7 --region us-west-2` |
| **R16-F06: Verify webhook-key deletion** | Low | `aws secretsmanager describe-secret --secret-id life-platform/webhook-key --region us-west-2` |
| **R16-F01: Fix ARCHITECTURE inline tool count** | Low | Search for "89" in ARCHITECTURE.md, update to 87 |
| **R16-F05: Canary threshold** | Low | Update `lambdas/canary_lambda.py` tool count threshold `< 50` → `< 80` |
| **R14-F02: INTELLIGENCE_LAYER.md** | Low | Persisting 3 reviews. Add IC-4/IC-5 descriptions. |
| **R13-F07: PITR drill** | Low | Target ~April 2026. Script ready. |
| SIMP-1 Phase 2 + ADR-025 cleanup | Deferred | ~2026-04-13 (data-gated) |
| Architecture Review #7 | Deferred | ~2026-04-08. Run `python3 deploy/generate_review_bundle.py` first. |

---

## Key Learnings This Session

**MCP deploy pattern (ADR-031):** Never use `deploy_lambda.sh` for `life-platform-mcp`. Always:
```bash
ZIP=/tmp/mcp_deploy.zip && rm -f $ZIP
zip -j $ZIP mcp_server.py mcp_bridge.py
zip -r $ZIP mcp/ -x 'mcp/__pycache__/*' 'mcp/*.pyc'
aws lambda update-function-code --function-name life-platform-mcp --zip-file fileb://$ZIP --region us-west-2
```

**MCP connection reset:** After any MCP Lambda redeploy, the claude.ai connector must be disconnected and reconnected to re-run the OAuth handshake.

**Feature retirement generates doc drift:** The Google Calendar retirement touched 3+ docs but only headers were auto-updated by `sync_doc_metadata.py`. Inline body references (tool counts, Lambda lists, secret tables) required manual fixes — and still have residual items (R16-F01/F02/F03).

---

## Files Changed This Session

```
docs/reviews/REVIEW_2026-03-15_v16.md   # NEW: Architecture Review #16
docs/PROJECT_PLAN.md                     # R16 findings added, review history updated
docs/CHANGELOG.md                        # R16 review note added to v3.7.47
handovers/HANDOVER_v3.7.47_R16.md        # this file (replaces HANDOVER_v3.7.47.md as latest)
```
