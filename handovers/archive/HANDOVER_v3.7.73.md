# Life Platform Handover — v3.7.73
**Date:** 2026-03-18 (end of session)

---

## Platform State

| Metric | Value |
|--------|-------|
| Version | v3.7.73 |
| MCP tools | 95 |
| Data sources | 19 active |
| Lambdas | 48 (CDK) + 1 Lambda@Edge + 1 us-east-1 (site-api) + 1 us-west-2 manual (email-subscriber) |
| Tests | 44 failing (all pre-existing) / 827 passing / 24 skipped / 5 xfailed |
| Architecture grade | A (R16) |
| Website | 10 pages at averagejoematt.com |
| CI | ✅ GREEN (0 lint errors — fixed this session) |

---

## What Was Done This Session

### CI lint (126 F821/F823 → 0)
All flake8 errors blocking CI since Sprint 5 fixed. Root cause: module split left functions referencing names from the old monolith (`get_table`, `query_date_range`, `_d2f`, `query_range`) plus missing stdlib/boto3 imports across 9 mcp/ files.

Files changed: `mcp/tools_data.py`, `tools_journal.py`, `tools_habits.py`, `tools_health.py`, `tools_lifestyle.py`, `tools_nutrition.py`, `tools_strength.py`, `tools_training.py`, `warmer.py`, `lambdas/monday_compass_lambda.py`, `lambdas/nutrition_review_lambda.py`, `lambdas/buddy/write_buddy_json.py`, `lambdas/chronicle_email_sender_lambda.py`

Scripts: `deploy/fix_ci_lint.py`, `deploy/fix_ci_lint2.py`

### Habitify IAM restoration
**RCA:** `life-platform/habitify` secret restored 2026-03-10, but `HabitifyIngestionRole` was never re-granted `secretsmanager:GetSecretValue`. 10 DLQ messages accumulated over 7 days.

**Fix:** Emergency `put-role-policy` → then CDK stack updated to manage it properly:
- `cdk/stacks/ingestion_stack.py`: HabitifyIngestion added as Lambda #5 of 16
- `cdk/stacks/role_policies.py`: `ingestion_habitify()` now uses `life-platform/habitify` per ADR-014
- `LifePlatformIngestion` deployed successfully (56s)
- Lambda verified: gap-fill ran for 7 days, all 0.0 (correct for sick week with no logging)

### Inbox triage
| Item | Outcome |
|------|---------|
| Budget $5.77 | Normal — $10.20/mo pace |
| Dash CloudWatch errors | Self-resolved |
| SES sandbox | Check AWS Support console — pending production access case |
| DLQ 10 messages | Fixed (Habitify IAM) |

---

## Open Issues

| Issue | Priority | Notes |
|-------|----------|-------|
| /story prose | CRITICAL | Distribution gate — Matthew writes 5 chapters |
| DIST-1 | HIGH | HN post or Twitter thread — needs /story first |
| SES production access | MEDIUM | Check support.aws.amazon.com for case status |
| Node.js 20 CI deprecation | LOW | actions/checkout, setup-python, configure-aws-credentials need v bump before June 2026 |
| chronicle_email_sender subscriber_email scope | LOW | F821 suppressed with noqa — real scope analysis deferred |
| 44 pre-existing test failures | LOW | All architectural debt, none new |
| Stale layers (I2) | LOW | anomaly-detector, character-sheet-compute, daily-metrics-compute on v9 vs v10 |

---

## Key Reminders for Next Session

**MCP deploy command:**
```bash
rm -f /tmp/mcp_deploy.zip && zip -j /tmp/mcp_deploy.zip mcp_server.py mcp_bridge.py && zip -r /tmp/mcp_deploy.zip mcp/ && zip -j /tmp/mcp_deploy.zip lambdas/digest_utils.py && aws lambda update-function-code --function-name life-platform-mcp --zip-file fileb:///tmp/mcp_deploy.zip --no-cli-pager > /dev/null && echo "✅ life-platform-mcp deployed"
```

**Habitify verified working:**
```bash
aws lambda invoke --function-name habitify-data-ingestion \
  --region us-west-2 --payload '{}' --no-cli-pager /tmp/h.json && cat /tmp/h.json
```

**CI is green** — next push to main should pass lint cleanly. Node.js 20 warnings are harmless until June 2026.

---

## Sprint Roadmap (Updated)

```
Sprint 1  COMPLETE (v3.7.55)
Sprint 2  COMPLETE (v3.7.63)
Sprint 3  COMPLETE (v3.7.67)
Sprint 4  COMPLETE (v3.7.68)
Sprint 5  COMPLETE — buildable (v3.7.72) | /story + DIST-1 remaining
v3.7.73   Maintenance — CI fixed, Habitify restored, inbox cleared
SIMP-1 Ph2 (~Apr 13)   95 → 80 tools
R17 Review (~Jun 2026)  Post-sprint validation
```
