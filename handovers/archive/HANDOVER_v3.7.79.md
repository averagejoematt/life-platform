# Life Platform Handover — v3.7.79
**Date:** 2026-03-19

---

## Platform State

| Metric | Value |
|--------|-------|
| Version | v3.7.79 |
| MCP tools | 95 |
| Data sources | 19 active |
| Lambdas | 49 (CDK) + 1 Lambda@Edge + 1 us-west-2 manual (email-subscriber) |
| Tests | 0 failing / 853 passing / 22 skipped / 11 xfailed |
| Architecture grade | A (R16) |
| Website | **11 pages** at averagejoematt.com |
| CI | ✅ GREEN |

---

## What Was Done This Session

### WR-17: OG Image Function URL 403 — FIXED ✅
- **Symptom**: `curl https://averagejoematt.com/og` returned 403 Forbidden
- **Root cause**: Manually-created Function URL had stale/broken permission policy that persisted across delete/recreate cycles. Direct Lambda invoke worked; Function URL didn't.
- **Fix**: Moved OG image Lambda from manual creation (`from_function_arn` import) to fully CDK-managed Lambda + Function URL
  - Added `og_image()` policy to `cdk/stacks/role_policies.py`
  - Updated `cdk/stacks/web_stack.py` to create Lambda with `_lambda.Function()` and `add_function_url()`
  - CDK handles both the Function URL AND the permission policy together correctly
- **Deployed**: `cdk deploy LifePlatformWeb` — working at `https://averagejoematt.com/og`

### Stale Layers (I2) — Verified ✅
- All 3 Lambdas already on `life-platform-shared-utils:10`
- No action needed

### Site Deploy ✅
- Ran `bash deploy/deploy_site_all.sh`
- OG image regenerated, RSS feed updated, S3 synced, CloudFront invalidated

---

## Open Issues

| Issue | Priority | Notes |
|-------|----------|-------|
| /story prose | **CRITICAL** | Distribution gate — Matthew writes 5 chapters |
| DIST-1 | HIGH | HN post / Twitter thread — needs /story first |

---

## Key Files Changed This Session

```
cdk/stacks/role_policies.py   — Added og_image() policy
cdk/stacks/web_stack.py       — CDK-managed OG Lambda + Function URL
```

---

## Sprint Roadmap

```
Sprint 1  COMPLETE (v3.7.55)
Sprint 2  COMPLETE (v3.7.63)
Sprint 3  COMPLETE (v3.7.67)
Sprint 4  COMPLETE (v3.7.68)
Sprint 5  COMPLETE — buildable (v3.7.72) | /story + DIST-1 remaining
v3.7.73   Maintenance — CI fixed, Habitify restored, inbox cleared
v3.7.74   Maintenance — 44 test failures → 0, CI Node 24 bump (⚠ used @v6 by mistake)
v3.7.75   Website — Strategy review + 14 enhancements deployed
v3.7.76   Backend — /api/ask live, daily-brief deployed, WR items
v3.7.77   Polish — reveal.js all pages, platform.html stats, WR-17 debug
v3.7.78   Bugfix — CI @v6 → @v4/v5, daily-brief streak_data NameError
v3.7.79   Fix — WR-17 OG Function URL 403 (CDK-managed Lambda)
NEXT      /story prose → DIST-1
SIMP-1 Ph2 (~Apr 13)   95 → 80 tools
```
