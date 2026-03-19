# Life Platform Handover — v3.7.76
**Date:** 2026-03-18 (end of session)

---

## Platform State

| Metric | Value |
|--------|-------|
| Version | v3.7.76 |
| MCP tools | 95 |
| Data sources | 19 active |
| Lambdas | 48 (CDK) + 1 Lambda@Edge + 1 us-east-1 (site-api) + 1 us-east-1 (og-image NEW) + 1 us-west-2 manual (email-subscriber) |
| Tests | **0 failing / 853 passing / 22 skipped / 11 xfailed** |
| Architecture grade | A (R16) |
| Website | **11 pages** at averagejoematt.com |
| CI | ✅ GREEN |

---

## What Was Done This Session

### Phase 1: /api/ask backend wired end-to-end ✅

- Secret `life-platform/anthropic-api-key` created in Secrets Manager (us-west-2)
- IAM policy `ask-secrets` added to `LifePlatformWeb-SiteApiLambdaRoleD76A39BB-fjAOtBxD1q5a`
- DynamoDB TTL already enabled — confirmed
- `site-api` Lambda deployed (us-east-1) — single-file
- CloudFront CORS on site-api Function URL: added POST + Content-Type
- CloudFront `/api/ask` behavior added: POST allowed, no cache, Content-Type forwarded
- CDK deployed `LifePlatformWeb` to wire the new behavior
- **Smoke test passed:** `/api/ask` returns live weight + recovery data via Haiku 4.5

### Phase 2: daily-brief + site_writer v1.2.0 deployed ✅

- `daily_brief_lambda.py` deployed with 9 extra modules including `site_writer.py` v1.2.0
- Next 10am PT run will write `trends.weight_daily/hrv_daily/sleep_daily/recovery_daily` and `brief_excerpt` to `public_stats.json`
- Enables homepage sparklines and "What Claude Sees" AI brief widget

### Phase 3: Website enhancements (WR-16/19/21/22/23/17)

| Item | Status |
|------|--------|
| WR-23 `/biology` noindex | ✅ Live |
| WR-16 Dual-path CTAs (homepage) | ✅ Live — "Follow the Journey" / "See the Platform" |
| WR-19 Press section (/about) | ✅ Live — 3-sentence pitch + angles + contact |
| WR-22 Scroll animations | ✅ Live — `reveal.js` + base.css IntersectionObserver |
| WR-21 Self-host fonts | ✅ Live — 9 woff2 files on S3, Google Fonts import removed |
| WR-17 Dynamic OG cards | ⚠️ Partial — Lambda created, CDK wired, Function URL 403 (see below) |

---

## Open Issues

| Issue | Priority | Notes |
|-------|----------|-------|
| /story prose | **CRITICAL** | Distribution gate — Matthew writes 5 chapters (prompts in place) |
| WR-17 OG Function URL 403 | MEDIUM | `life-platform-og-image` Lambda works via direct invoke, 403 on Function URL. Direct invoke confirmed 200/SVG. Resource policy correct. Not blocking — static OG image still works. Investigate: check if resource policy needs a re-apply after Function URL CORS update |
| DIST-1 | HIGH | HN post or Twitter thread — needs /story first |
| chronicle_email_sender scope | LOW | F821 suppressed with noqa |
| Stale layers (I2) | LOW | anomaly-detector, character-sheet-compute, daily-metrics-compute on v9 vs v10 |

---

## Key Reminders for Next Session

**Site deploy command (standard):**
```bash
bash ~/Documents/Claude/life-platform/deploy/deploy_site_all.sh
```

**To fix WR-17 OG Function URL 403:**
```bash
# Check if re-adding permission fixes it
aws lambda remove-permission \
  --function-name life-platform-og-image \
  --statement-id FunctionURLPublicAccess \
  --region us-east-1

aws lambda add-permission \
  --function-name life-platform-og-image \
  --statement-id FunctionURLPublicAccess \
  --action lambda:InvokeFunctionUrl \
  --principal "*" \
  --function-url-auth-type NONE \
  --region us-east-1

curl -sv "https://fj5u62xcm2bk2fwuiyvf3wzqqm0mwcmk.lambda-url.us-east-1.on.aws/" 2>&1 | grep -E "< HTTP|< content"
```

**OG Lambda details:**
- Function: `life-platform-og-image` (us-east-1)
- Function URL: `https://fj5u62xcm2bk2fwuiyvf3wzqqm0mwcmk.lambda-url.us-east-1.on.aws/`
- CloudFront behavior `/og` → `OgImageOrigin` wired in CDK (deployed this session)
- Source: `lambdas/og_image_lambda.mjs`
- Role: `life-platform-og-image-role`
- Update code: `bash deploy/deploy_og_image.sh --update-code`

**Fonts deployed:**
- 9 woff2 files on S3: `s3://matthew-life-platform/site/assets/fonts/`
- base.css now uses `@font-face` with `/assets/fonts/*.woff2`
- No more Google Fonts external request on page load
- Script preserved: `deploy/download_and_upload_fonts.sh` (run if fonts need re-download)

**New deploy scripts created this session:**
- `deploy/download_and_upload_fonts.sh` — downloads Google Fonts woff2 with correct UA + uploads to S3
- `deploy/deploy_og_image.sh` — creates og-image Lambda + Function URL (fixed: `create-function-url-config`)
- `site/assets/js/reveal.js` — scroll reveal IntersectionObserver

---

## Sprint Roadmap (Updated)

```
Sprint 1  COMPLETE (v3.7.55)
Sprint 2  COMPLETE (v3.7.63)
Sprint 3  COMPLETE (v3.7.67)
Sprint 4  COMPLETE (v3.7.68)
Sprint 5  COMPLETE — buildable (v3.7.72) | /story + DIST-1 remaining
v3.7.73   Maintenance — CI fixed, Habitify restored, inbox cleared
v3.7.74   Maintenance — 44 test failures → 0, CI Node 24 bump
v3.7.75   Website — Strategy review + 14 enhancements deployed
v3.7.76   Backend — /api/ask live, daily-brief deployed, WR-16/19/21/22/23 live, WR-17 partial
NEXT      /story prose → DIST-1 → WR-17 OG URL debug
SIMP-1 Ph2 (~Apr 13)   95 → 80 tools
```
