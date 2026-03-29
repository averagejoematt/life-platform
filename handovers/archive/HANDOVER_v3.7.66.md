# Life Platform Handover — v3.7.66
**Date:** 2026-03-17 (end of session)

---

## Platform State

| Metric | Value |
|--------|-------|
| Version | v3.7.66 |
| MCP tools | 90 |
| Data sources | 19 active |
| Lambdas | 48 (CDK) + 1 Lambda@Edge + 1 us-east-1 manual (email-subscriber) |
| Tests | 83/83 passing |
| Architecture grade | A (R16) |
| Website | LIVE — averagejoematt.com |
| Sprint 3 | 5/9 complete |

---

## What Was Done This Session

### MCP `Key` NameError Fix
- `mcp/tools_lifestyle.py`: Added `from boto3.dynamodb.conditions import Key` at line 10.
- Was missing despite `Key()` being used at lines 285 and 2455 (insights + experiments queries).
- Affected tools: `list_experiments`, `create_experiment`, `end_experiment`, `get_experiment_results`, `log_insight`, and all other experiments-related functions in the file.
- MCP deployed via full package zip. **FIXED ✅**

### BS-T2-5: Chronicle Newsletter Full Delivery — COMPLETE
- CDK: `SEND_RATE_PER_SEC` 1.0 → 14.0 in `email_stack.py`. LifePlatformEmail deployed.
- `chronicle_email_sender_lambda.py`: Unsubscribe URL now uses `?h=<email_hash>` instead of raw email. Function signature updated to accept full subscriber dict.
- `email_subscriber_lambda.py`: `handle_unsubscribe_by_hash()` added. Router prefers `?h=` param. Welcome email unsub link also updated to hash-based URL.

---

## Sprint 3 Status

| ID | Feature | Status |
|----|---------|--------|
| IC-28 | Training Load Intelligence | ✅ DEPLOYED |
| WEB-WCT | Weekly Challenge Ticker | ✅ DEPLOYED |
| BS-13 | N=1 Experiment Archive | ✅ DEPLOYED |
| BS-T2-5 | Chronicle Newsletter Full Delivery | ✅ COMPLETE |
| BS-12 | Deficit Sustainability Tracker | Not started — Opus |
| BS-SL1 | Sleep Environment Optimizer | Not started — Opus |
| BS-MP1 | Autonomic Balance Score | Not started — Opus |
| BS-MP2 | Journal Sentiment Trajectory | Not started — Opus |
| IC-29 | Metabolic Adaptation Intelligence | Not started — Opus |

---

## Immediate Next Actions (for Opus session)

All remaining Sprint 3 features are **Opus-recommended** (complex intelligence/analysis work):

| Item | Notes |
|------|-------|
| **BS-12** | Deficit Sustainability Tracker — multi-signal early warning for unsustainable caloric deficit. Opus. |
| **BS-SL1** | Sleep Environment Optimizer — cross-reference Eight Sleep temp data with Whoop staging. Opus. |
| **BS-MP1** | Autonomic Balance Score — HRV + RHR + RR + sleep quality → 4-quadrant nervous system state. Opus. |
| **BS-MP2** | Journal Sentiment Trajectory — structured sentiment analysis with divergence detection. Opus. |
| **IC-29** | Metabolic Adaptation Intelligence — TDEE divergence tracking IC feature. Opus. |

**Also carry forward:**
- **HERO_WHY_PARAGRAPH** — still placeholder in `lambdas/site_writer.py`. Set `paragraph_is_placeholder: False` + write 50-word paragraph + redeploy daily-brief.

---

## Open Issues
1. **HERO_WHY_PARAGRAPH** — placeholder in site_writer.py. Carry from v3.7.63.

---

## Key Files Changed This Session

| File | Change |
|------|--------|
| `mcp/tools_lifestyle.py` | Added `from boto3.dynamodb.conditions import Key` import |
| `cdk/stacks/email_stack.py` | `SEND_RATE_PER_SEC` 1.0 → 14.0 |
| `lambdas/chronicle_email_sender_lambda.py` | Hash-based unsub URL + subscriber dict signature |
| `lambdas/email_subscriber_lambda.py` | `handle_unsubscribe_by_hash()` + router update + welcome email fix |
| `docs/CHANGELOG.md` | v3.7.66 entry |

---

## Infrastructure State
- `life-platform-mcp` (us-west-2): DEPLOYED — Key import fix
- `LifePlatformEmail` (CDK): DEPLOYED — rate bump
- `chronicle-email-sender` (us-west-2): DEPLOYED — hash unsub
- `email-subscriber` (us-west-2): DEPLOYED — hash unsub handler
- All other infrastructure: unchanged from v3.7.65

---

## Sprint Roadmap

```
Sprint 1  COMPLETE          BS-01 BS-02 BS-03 BS-05 BS-09
Sprint 2  COMPLETE          BS-07 BS-08 BS-SL2 BS-BH1 BS-MP3 BS-TR1 BS-TR2
SIMP-1 Ph2 (~Apr 13)        90 to 80 tools (EMF telemetry gate)
Sprint 3  IN PROGRESS (5/9) IC-28 ✅ WEB-WCT ✅ BS-13 ✅ BS-T2-5 ✅
          Remaining:        BS-12 BS-SL1 BS-MP1 BS-MP2 IC-29  (all Opus)
Sprint 4  (~Jun 8)          BS-11 WEB-CE BS-BM2 BS-14
```

---

## deploy/deploy_lambda.sh Note
Script hardcodes `REGION="us-west-2"`. For us-east-1 Lambdas (site-api), deploy directly:
```bash
zip -j /tmp/site_api_deploy.zip lambdas/site_api_lambda.py
aws lambda update-function-code --function-name life-platform-site-api \
  --zip-file fileb:///tmp/site_api_deploy.zip --region us-east-1
```
`email-subscriber` is in **us-west-2** (not us-east-1 as previously noted):
```bash
zip -j /tmp/subscriber_deploy.zip lambdas/email_subscriber_lambda.py
aws lambda update-function-code --function-name email-subscriber \
  --zip-file fileb:///tmp/subscriber_deploy.zip --region us-west-2
```
