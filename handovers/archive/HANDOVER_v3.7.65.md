# Life Platform Handover — v3.7.65
**Date:** 2026-03-17 (end of session)

---

## Platform State

| Metric | Value |
|--------|-------|
| Version | v3.7.65 |
| MCP tools | 90 |
| Data sources | 19 active |
| Lambdas | 48 (CDK) + 1 Lambda@Edge + 1 us-east-1 manual (email-subscriber) |
| Tests | 83/83 passing |
| Architecture grade | A (R16) |
| Website | LIVE — averagejoematt.com |
| Sprint 3 | 3/9 complete (IC-28, WEB-WCT, BS-13) |

---

## What Was Done This Session

### IC-28: Training Load Intelligence
- `_build_acwr_signal()` in `daily_insight_compute_lambda.py` — reads ACWR from computed_7d, priority-4 signal for danger/caution/detraining, priority-8 for safe
- `_build_acwr_coaching_context()` in `ai_calls.py` — zone-specific coaching rules injected into `call_training_nutrition_coach` prompt
- Both deployed. Timing confirmed correct (no CDK change needed).

### WEB-WCT: Weekly Challenge Ticker
- `.challenge-bar` CSS added to `base.css` (fixed bottom, 36px, all pages)
- `/api/current_challenge` route in `site_api_lambda.py` — reads S3 `site/config/current_challenge.json` via boto3
- IAM `S3SiteConfigRead` policy added live + to `role_policies.py`
- Challenge bar HTML+JS added to all 4 existing pages + new experiments page
- S3 config seeded: Week 4 challenge live
- Smoke tested via CloudFront ✅

### BS-13: N=1 Experiment Archive
- `site/experiments/index.html` created and deployed
- Filter buttons, experiment cards (status badge, hypothesis, days counter, data grid, outcome)
- Active experiment amber accent, empty state, H/P/D methodology strip
- Reads from existing `/api/experiments` endpoint (no Lambda changes)

### BS-T2-5: Assessment only
- Pipeline is ~90% complete already (chronicle → DDB → email sender → subscribers works)
- Two gaps remaining: SEND_RATE_PER_SEC=1.0 (needs 14.0), unsubscribe URL uses raw email (needs token)

---

## Immediate Next Actions

| Item | Notes |
|------|-------|
| **MCP Key bug** | `NameError: name 'Key' is not defined` on list_experiments + others. Check CloudWatch: `aws logs tail /aws/lambda/life-platform-mcp --since 30m --region us-west-2` |
| **BS-T2-5 finish** | Bump `SEND_RATE_PER_SEC` to 14.0 in CDK email_stack.py + update unsubscribe to use token |
| **HERO_WHY_PARAGRAPH** | Edit in `lambdas/site_writer.py`, set `paragraph_is_placeholder: False`, redeploy daily-brief |
| **Continue Sprint 3** | Remaining: BS-12, BS-SL1, BS-MP1, BS-MP2, IC-29 (all Opus) |

---

## Sprint 3 Status

| ID | Feature | Status |
|----|---------|--------|
| IC-28 | Training Load Intelligence | ✅ DEPLOYED |
| WEB-WCT | Weekly Challenge Ticker | ✅ DEPLOYED |
| BS-13 | N=1 Experiment Archive | ✅ DEPLOYED |
| BS-T2-5 | Chronicle Newsletter Full Delivery | ⚠️ 90% — rate bump + token unsub remain |
| BS-12 | Deficit Sustainability Tracker | Not started |
| BS-SL1 | Sleep Environment Optimizer | Not started |
| BS-MP1 | Autonomic Balance Score | Not started |
| BS-MP2 | Journal Sentiment Trajectory | Not started |
| IC-29 | Metabolic Adaptation Intelligence | Not started |

---

## deploy/deploy_lambda.sh Note
Script hardcodes `REGION="us-west-2"`. For us-east-1 Lambdas (site-api, email-subscriber), deploy directly:
```bash
zip -j /tmp/site_api_deploy.zip lambdas/site_api_lambda.py
aws lambda update-function-code --function-name life-platform-site-api \
  --zip-file fileb:///tmp/site_api_deploy.zip --region us-east-1
```

---

## Key Files Changed This Session

| File | Change |
|------|--------|
| `lambdas/daily_insight_compute_lambda.py` | IC-28: `_build_acwr_signal()` + wired in handler |
| `lambdas/ai_calls.py` | IC-28: `_build_acwr_coaching_context()` + injected in training coach |
| `lambdas/site_api_lambda.py` | WEB-WCT: `/api/current_challenge` route + boto3 S3 read |
| `cdk/stacks/role_policies.py` | WEB-WCT: `S3SiteConfigRead` in `site_api()` |
| `site/assets/css/base.css` | WEB-WCT: `.challenge-bar` component CSS |
| `site/index.html` | WEB-WCT: challenge bar added |
| `site/journal/index.html` | WEB-WCT: challenge bar added |
| `site/character/index.html` | WEB-WCT: challenge bar added |
| `site/platform/index.html` | WEB-WCT: challenge bar added |
| `site/experiments/index.html` | BS-13: new file |
| `docs/CHANGELOG.md` | v3.7.65 entry |

---

## Infrastructure State
- `life-platform-site-api` (us-east-1): DEPLOYED with `/api/current_challenge`
- `daily-insight-compute`: DEPLOYED (IC-28)
- `daily-brief`: DEPLOYED (IC-28 via ai_calls.py)
- All other infrastructure: unchanged from v3.7.64

---

## Open Issues
1. **MCP `Key` NameError** — `list_experiments`, likely others. Check CloudWatch logs. May be a missing import in a module that uses `boto3.dynamodb.conditions.Key` directly without importing it.
2. **BS-T2-5 rate bump** — `SEND_RATE_PER_SEC=1.0` in CDK email_stack.py needs to be `14.0` (SES production confirmed). Requires CDK deploy of LifePlatformEmail.
3. **HERO_WHY_PARAGRAPH** — still placeholder in site_writer.py. Carry from v3.7.63.

---

## Sprint Roadmap

```
Sprint 1  COMPLETE          BS-01 BS-02 BS-03 BS-05 BS-09
Sprint 2  COMPLETE          BS-07 BS-08 BS-SL2 BS-BH1 BS-MP3 BS-TR1 BS-TR2
SIMP-1 Ph2 (~Apr 13)        90 to 80 tools (EMF telemetry gate)
Sprint 3  IN PROGRESS       IC-28 ✅ WEB-WCT ✅ BS-13 ✅
          Remaining:        BS-12 BS-SL1 BS-MP1 BS-MP2 BS-T2-5(finish) IC-29
Sprint 4  (~Jun 8)          BS-11 WEB-CE BS-BM2 BS-14
```
