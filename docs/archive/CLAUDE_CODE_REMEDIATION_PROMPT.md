# Claude Code Prompt — R19 Architecture Remediation (All Dimensions to A)

Paste everything below the line into Claude Code.

---

## Prompt Start

You are executing the Life Platform R19 Architecture Review remediation plan. Your goal is to bring all 10 architecture review dimensions from the current composite B+ to a straight A.

**Before doing anything else**, read these two plan documents from the project:

1. `docs/A_GRADE_REMEDIATION_PLAN.md` — Phases 1-5 (B+ → A-)
2. `docs/A_GRADE_PHASE6_SUPPLEMENT.md` — Phase 6 (A- → A)

Also read the R19 review for context:
3. `docs/reviews/REVIEW_2026-03-30_v19.md`

These documents contain the full technical specification for every task. Follow them precisely.

---

### Critical Rules

**COST RULE:** If any single change would increase monthly AWS spend by more than $1, STOP and ask me before implementing. Specifically:
- CloudWatch custom metrics ($0.30/metric/month) — DO NOT USE. Use structured logging to CloudWatch Logs instead ($0).
- CloudWatch dashboards ($3/month if NEW) — check if `life-platform-ops` already exists first. If updating an existing dashboard, it's $0. If creating new, ask me.
- New CloudWatch alarms (~$0.10 each) — if you need to create more than 5 new alarms, ask me first.
- PITR drill creates a temporary DynamoDB table — delete it immediately after verification. Cost is <$0.01.

**COMMIT RULE (Viktor directive):** Commit after EACH phase. Do not attempt all 6 phases in one pass. Each phase is a clean commit point:
```
Phase 1: git commit -m "v4.5.1-phase1: documentation sprint"
Phase 2: git commit -m "v4.5.1-phase2: architecture audit + SIMP-1 ADR"
Phase 3: git commit -m "v4.5.1-phase3: reliability + security audits"
Phase 4: git commit -m "v4.5.1-phase4: observability + route logging"
Phase 5: git commit -m "v4.5.1-phase5: operability polish"
Phase 6: git commit -m "v4.5.2: phase 6 — all dimensions to A"
```

**CDK RULE:** In Phase 6 Task 6.1, you will adopt unmanaged Lambdas into CDK. Run `npx cdk diff` for each affected stack and show me the diff BEFORE running `cdk deploy`. I must approve each stack deploy individually.

**SIMP-1 RULE:** In Phase 2 Task 2.2, you will analyze MCP tool counts and recommend either consolidation or acceptance. Present your analysis and recommendation to me — I will decide which ADR to write.

**MCP DEPLOY RULE:** NEVER use `deploy_lambda.sh` for `life-platform-mcp`. The MCP Lambda requires a full zip build. See `docs/RUNBOOK.md` for the correct procedure.

**S3 SAFETY RULE:** NEVER use `aws s3 sync --delete` against the bucket root or `site/` prefix. Use `aws s3 cp` for single files or the canonical `deploy/deploy_site.sh`.

---

### Phase-by-Phase Instructions

#### PHASE 1: Documentation Sprint
Read the plan for Tasks 1.1–1.6, then execute each one. Key files to edit:
- `docs/INFRASTRUCTURE.md` — full update (remove google-calendar, add 15 missing Lambdas, fix all counts)
- `docs/ARCHITECTURE.md` — body-section reconciliation (sync all numeric references with header)
- `docs/INCIDENT_LOG.md` — add 5 missing incidents from v4.4.0
- `deploy/generate_review_bundle.py` — add R17 + R18 findings to Section 13b
- `docs/SLOs.md` — remove google-calendar, update monitored sources
- `docs/RUNBOOK.md` — verification pass

**After completing Phase 1:** Run `bash deploy/audit_system_state.sh` and confirm zero discrepancies. This is the proof that documentation matches reality. If there are discrepancies, fix them before proceeding.

Then: `git add -A && git commit -m "v4.5.1-phase1: documentation sprint" && git push`

#### PHASE 2: Architecture Integrity
- Task 2.1: CDK adoption audit. Run `aws lambda list-functions --region us-west-2` and cross-reference against CDK stack definitions in `cdk/stacks/`. Also check EventBridge rules. Write findings to `docs/audits/AUDIT_cdk_adoption.md`. DO NOT modify CDK stacks — audit only.
- Task 2.2: SIMP-1 analysis. Count tools (`grep -c "def tool_" mcp/tools_*.py`), analyze consolidation feasibility, present recommendation to me. I will decide.

Then: `git add -A && git commit -m "v4.5.1-phase2: architecture audit + SIMP-1 ADR" && git push`

#### PHASE 3: Reliability & Security
- Task 3.1: PITR restore drill. Restore to `life-platform-pitr-drill` table, verify item counts match production, spot-check records, document results, DELETE the test table immediately.
- Task 3.2: Alarm coverage audit. Cross-reference all 60 Lambdas against CloudWatch alarms. Verify alarm actions point to `arn:aws:sns:us-west-2:205930651321:life-platform-alerts`. Check DLQ depth is zero. Verify pipeline-health-check has run daily for last 7 days.
- Task 3.3: Security verification. Check security.txt, security headers, WAF attachment to CloudFront E3S424OXQZ8NBE, site-api IAM role is read-only (no PutItem/Scan).

Document all findings in `docs/audits/`.

Then: `git add -A && git commit -m "v4.5.1-phase3: reliability + security audits" && git push`

#### PHASE 4: Observability
- Task 4.1+4.3: Add structured JSON route logging to `lambdas/site_api_lambda.py` (NOT CloudWatch custom metrics — those cost $9/month). Log `{"_type": "route_metric", "route": ..., "duration_ms": ..., "status": ...}` at the end of each request. Create a saved Logs Insights query at `deploy/queries/site_api_route_metrics.txt`.
- Task 4.2: Verify `life-platform-ops` dashboard exists and has SLO widgets. If it doesn't exist, ask me about the $3/month cost before creating.
- Deploy the updated site-api: `bash deploy/deploy_lambda.sh life-platform-site-api`

Then: `git add -A && git commit -m "v4.5.1-phase4: observability + route logging" && git push`

#### PHASE 5: Operability Polish
- Task 5.1: Update `deploy/audit_system_state.sh` expected values for v4.5.1
- Task 5.2: Verify RUNBOOK.md covers all operational procedures
- Task 5.3: Update CHANGELOG.md with v4.5.1 entry covering Phases 1-5

Then: `git add -A && git commit -m "v4.5.1-phase5: operability polish" && git push`

#### PHASE 6: A- to A (from the supplement document)
- Task 6.1: CDK adoption of unmanaged Lambdas found in Phase 2 audit. For each: add to CDK stack, add IAM role, add EventBridge rule if scheduled, add alarm. Run `npx cdk diff` and SHOW ME before deploying.
- Task 6.2: Add `pip-audit` step to `.github/workflows/ci-cd.yml` (advisory/non-blocking). Audit all site-api input validation — verify all query params and POST bodies are validated and bounded.
- Task 6.3a: Update or create ops dashboard with SLO widgets, Lambda health, data freshness, DLQ depth, API latency.
- Task 6.3b: Add `/api/healthz` endpoint to site-api — lightweight DDB read latency check + source freshness summary + Lambda warm/cold status. No auth required, no PII in response.
- Task 6.4: Full refresh of `docs/INTELLIGENCE_LAYER.md` — remove freeze label, update all IC feature statuses, add signal doctrine, challenge system, food delivery integration, reader engagement signals, update architecture diagram, update data maturity roadmap.
- Task 6.5: Create `docs/OPERATOR_GUIDE.md` — narrative Day-1 onboarding document covering: system overview, daily health check procedure, weekly operational rhythm, failure response playbooks, deployment procedures, key URLs, secrets management.

Then: `git add -A && git commit -m "v4.5.2: phase 6 complete — all dimensions to A" && git push`

---

### Key Platform Facts (for reference)

- **Project root:** `~/Documents/Claude/life-platform/`
- **AWS region:** us-west-2 (all resources except Lambda@Edge in us-east-1)
- **DynamoDB table:** `life-platform` (us-west-2)
- **S3 bucket:** `matthew-life-platform`
- **CloudFront:** `E3S424OXQZ8NBE` (averagejoematt.com)
- **SNS topic:** `life-platform-alerts`
- **Site-api Lambda:** `life-platform-site-api` (us-west-2, confirmed)
- **MCP Lambda:** `life-platform-mcp` (us-west-2, manual zip deploy only)
- **Current version:** v4.5.0 → will become v4.5.1 (Phases 1-5) then v4.5.2 (Phase 6)
- **Current counts:** 60 Lambdas, 118 MCP tools, 68 pages, 26 data sources, 10 secrets, 8 CDK stacks
- **Lambda deploy:** `bash deploy/deploy_lambda.sh <function-name>`
- **Site deploy:** `bash deploy/deploy_site.sh`
- **Shared layer rebuild:** `bash deploy/p3_build_shared_utils_layer.sh` then `bash deploy/p3_attach_shared_utils_layer.sh`

### What Success Looks Like

When all 6 phases are complete:
- Every doc header matches reality (zero discrepancies from audit_system_state.sh)
- PITR drill documented and test table deleted
- 100% alarm coverage with correct SNS actions
- Per-route structured logging deployed on site-api
- `/api/healthz` endpoint returning health status
- INTELLIGENCE_LAYER.md current (not frozen)
- OPERATOR_GUIDE.md exists and covers Day-1 onboarding
- All Lambdas CDK-managed (or CDK diff approved and pending deploy)
- CI pipeline has dependency scanning
- All API inputs validated
- SIMP-1 has an explicit ADR decision (consolidate or accept)
- 6 clean git commits, one per phase
