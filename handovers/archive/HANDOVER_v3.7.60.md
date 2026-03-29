# Life Platform Handover — v3.7.60
**Date:** 2026-03-17 (end of session)

---

## Platform State

| Metric | Value |
|--------|-------|
| Version | v3.7.60 |
| MCP tools | 89 |
| Data sources | 19 active |
| Lambdas | 45 (CDK) + 1 Lambda@Edge + email-subscriber (us-east-1, manual) |
| Tests | 83/83 passing |
| Architecture grade | A (R16) |
| Website | **LIVE** — averagejoematt.com (Signal teal, WAF-protected) |
| WAF | `life-platform-amj-waf` on E3S424OXQZ8NBE — 2 rules active |

---

## What Was Done This Session

### 1. Subscribe flow fixed + tested (5/5)
- Root cause: `email-subscriber` Lambda in us-east-1, DDB in us-west-2. Lambda was writing DDB to wrong region.
- Fix: `DYNAMODB_REGION=us-west-2` env var; DDB client uses it, SES client uses `REGION` (us-east-1).
- `deploy/test_subscribe.sh` written and passing: HTTP 200, pending_confirmation body, 400 on invalid/empty, DDB record verified.
- Note: SES confirmation email test fails (unverified test address in sandbox) — expected. Core flow is working.

### 2. TB7-26 WAF — complete
- WAF WebACL `life-platform-amj-waf` (us-east-1) created with 2 rules:
  - `SubscribeRateLimit`: `/api/subscribe*` — block >60 req/5min per IP
  - `GlobalRateLimit`: all paths — block >1000 req/5min per IP
- Attached to CloudFront `E3S424OXQZ8NBE` via `update-distribution`
- Verified: WebACLId confirmed in distribution config
- `deploy/setup_waf.sh` committed (idempotent, safe to re-run)
- MCP endpoint protected by API key auth — WAF cannot attach to Lambda Function URLs directly. TB7-26 satisfied.
- Cost: ~$6/month

---

## Pending Next Session

### P0 — None

### High
| Item | Notes |
|------|--------|
| `cdk deploy LifePlatformWeb` | Should sync `DYNAMODB_REGION` env var into CDK-managed Lambda. Low priority — env var is set live. |
| TB7-25 | CI/CD rollback mechanism — `rollback_lambda.sh` already exists for individual Lambdas. Verify scope. |
| TB7-27 | MCP tool tiering design doc (pre-SIMP-1 Phase 2) |
| SES sandbox exit | Request production SES access so confirmation emails deliver to real subscribers |
| Homepage data | Auto-populates at 10am PT daily brief — no action needed |

### Deferred (unchanged)
| Item | Target |
|------|--------|
| BS-08: Unified Sleep Record | Design doc first |
| IC-4/IC-5 activation | ~2026-05-01 data gate |
| SIMP-1 Phase 2 (≤80 tools) | ~2026-04-13 EMF gate |
| R17 Architecture Review | ~2026-04-08 |

---

## Key Files Changed This Session

| File | Change |
|------|--------|
| `lambdas/email_subscriber_lambda.py` | `DYNAMODB_REGION` fix — cross-region DDB access |
| `cdk/stacks/web_stack.py` | `DYNAMODB_REGION=us-west-2` in EmailSubscriberLambda env |
| `deploy/setup_waf.sh` | **NEW** — WAF WebACL setup + CloudFront attachment |
| `deploy/test_subscribe.sh` | **NEW** — subscribe end-to-end test (5 assertions) |
| `docs/CHANGELOG.md` | v3.7.60 entry |

---

## Infrastructure State
- WAF WebACL: `arn:aws:wafv2:us-east-1:205930651321:global/webacl/life-platform-amj-waf/3d75472e-e18b-4d1c-b76b-8bbe63cb05e8`
- CloudFront AMJ: `E3S424OXQZ8NBE` (WAF attached)
- email-subscriber: us-east-1, DYNAMODB_REGION=us-west-2 ✅
- Subscribe flow: working end-to-end (DDB write confirmed)
