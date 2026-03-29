# Life Platform Handover — v3.7.47
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

---

## What Was Done This Session (full day)

### v3.7.44 — R15 doc fixes
- F01: `tests/test_business_logic.py` ImportError guard + sleep key fix
- F02–F06: INFRASTRUCTURE secrets table, Lambda@Edge count, IC skeleton callout, MCP memory, warmer step count

### v3.7.45 — R13 CI/CD activation
- OIDC role provisioned (`arn:aws:iam::205930651321:role/github-actions-deploy-role`)
- I4/I6/I7/I8/I9 wired into CI post-deploy-checks
- `ci/lambda_map.json` fixed: 3 missing Lambdas added, 2 skeleton Lambdas flagged `not_deployed`
- 3 redundant IAM policies deleted from OIDC role
- GitHub `production` Environment confirmed (1 protection rule)

### v3.7.46 — ADR-030 Google Calendar retired
Exhausted all 7 integration paths. All blocked by Smartsheet IT or macOS restrictions.
- `mcp/registry.py`: `get_calendar_events` + `get_schedule_load` removed (89→87 tools)
- `lambdas/freshness_checker_lambda.py`: `google_calendar` removed from SOURCES + field checks
- `ci/lambda_map.json`: `google_calendar_lambda.py` marked `not_deployed`
- `docs/DECISIONS.md`: ADR-030 added (full options-and-blockers table)
- MCP deployed live — 87 tools confirmed

### v3.7.47 — CDK cleanup + MCP deploy guard + incident fix
- `cdk/stacks/ingestion_stack.py`: block 16 retired (CDK deploy will remove Lambda + EventBridge rule)
- `cdk/stacks/role_policies.py`: `ingestion_google_calendar()` removed
- `deploy/deploy_lambda.sh`: MCP guard added — hard-rejects `life-platform-mcp` with correct build instructions
- `assets/life-platform-icon.svg`: constellation logo created + uploaded to S3
- `docs/DECISIONS.md`: ADR-031 added (MCP deploy pattern)
- `docs/INCIDENT_LOG.md`: MCP deploy watch-out documented
- **MCP outage resolved**: `deploy_lambda.sh` had stripped `mcp/` from zip causing 401 on all OAuth endpoints. Fixed with full zip rebuild.

---

## Pending Items for Next Session

| Item | Priority | Notes |
|------|----------|-------|
| CDK deploy (remove google-calendar-ingestion) | Medium | `cd cdk && source .venv/bin/activate && npx cdk deploy LifePlatformIngestion --require-approval never` then `bash deploy/post_cdk_reconcile_smoke.sh` |
| AR #15 | High | Platform at cleanest baseline — good time for full Opus review. Run `python3 deploy/generate_review_bundle.py` first. |
| TB7-4 (OVERDUE) | ⚠️ Critical | `api-keys` grep sweep — deadline was 2026-03-17 |
| TB7-1 | Low | Verify GitHub `production` Environment gate (likely already done this session) |

---

## Key Learnings This Session

**MCP deploy pattern (ADR-031):** Never use `deploy_lambda.sh` for `life-platform-mcp`. Always:
```bash
ZIP=/tmp/mcp_deploy.zip && rm -f $ZIP
zip -j $ZIP mcp_server.py mcp_bridge.py
zip -r $ZIP mcp/ -x 'mcp/__pycache__/*' 'mcp/*.pyc'
aws lambda update-function-code --function-name life-platform-mcp --zip-file fileb://$ZIP --region us-west-2
```
Symptom of wrong deploy: `{"error": "Unauthorized"}` on OAuth endpoints + clean Lambda logs (misleading).

**MCP connection reset:** After any MCP Lambda redeploy, the claude.ai connector must be disconnected and reconnected to re-run the OAuth handshake.

---

## Files Changed This Session

```
cdk/stacks/ingestion_stack.py      # block 16 retired
cdk/stacks/role_policies.py        # ingestion_google_calendar() removed
deploy/deploy_lambda.sh            # MCP guard added
deploy/sync_doc_metadata.py        # data_sources 20→19
assets/life-platform-icon.svg      # new: constellation logo
docs/CHANGELOG.md                  # v3.7.47 entry
docs/DECISIONS.md                  # ADR-030 full body, ADR-031, index updated
docs/INCIDENT_LOG.md               # MCP deploy watch-out added
docs/RUNBOOK.md                    # (updated by pre-commit sync)
handovers/HANDOVER_v3.7.47.md      # this file
```
