# Life Platform Handover — v3.7.77
**Date:** 2026-03-19

---

## Platform State

| Metric | Value |
|--------|-------|
| Version | v3.7.77 |
| MCP tools | 95 |
| Data sources | 19 active |
| Lambdas | 48 (CDK) + 1 Lambda@Edge + 1 us-east-1 (site-api) + 1 us-east-1 (og-image) + 1 us-west-2 manual (email-subscriber) |
| Tests | **0 failing / 853 passing / 22 skipped / 11 xfailed** |
| Architecture grade | A (R16) |
| Website | **11 pages** at averagejoematt.com |
| CI | ✅ GREEN |

---

## What Was Done This Session

### WR-17: OG Function URL 403 — Exhaustive Debug (Parked)
- Lambda direct invoke: **200 OK, 4837-byte SVG** — Lambda is correct
- Resource policy: textbook correct (FunctionURLPublicAccess, AuthType NONE)
- Eliminated: VPC (none), concurrency (unset), trust policy (ok), org SCP (not in org), permissions boundary (none), inline policies (clean S3 read only)
- Function URL CORS config deleted and recreated without CORS — still 403 pre-dispatch
- 403 fires before Lambda (no CloudWatch entry), even with signed requests
- **Root cause: unknown after all standard causes eliminated**
- **Status: PARKED** — static og-image.png fallback is live, CloudFront /og wired and ready
- New Function URL (after recreate): `https://vatekozraszerm4hm5lxse6x3i0peokq.lambda-url.us-east-1.on.aws/`

### WR-22: Reveal.js Extended to All Pages ✅
Added `reveal` class + `reveal.js` script to all pages that were missing it:
- `/platform/` — arch, stack, AI tools, reviews, email CTA
- `/experiments/` — explainer, experiment list, methodology, email CTA
- `/journal/` — header, list, email CTA
- `/character/` — character card, radar, pillars, timeline, email CTA
- `/ask/` — header, data strip, email CTA

### platform/index.html Stats Corrected ✅
All stale counts updated:
- MCP tools: 87 → **95**
- Lambdas: 42 → **48**
- Tests: 83 → **853**
- Version badge: v3.7.49 → **v3.7.76**
- Lambda memory chip: 768MB → **1024MB**

### Deploy Scripts Written ✅
- `deploy/fix_og_url_403.sh` — re-applies Function URL public access (for future attempts)
- `deploy/fix_stale_layers.sh` — updates anomaly-detector, character-sheet-compute, daily-metrics-compute from layer v9 → v10

---

## Open Issues

| Issue | Priority | Notes |
|-------|----------|-------|
| /story prose | **CRITICAL** | Distribution gate — Matthew writes 5 chapters |
| WR-17 OG Function URL 403 | MEDIUM | All standard causes eliminated. Try: delete Lambda entirely + recreate with fresh name `life-platform-og-image-v2`. New URL is `vatekozraszerm4hm5lxse6x3i0peokq`. |
| Stale layers (I2) | LOW | Script written: `bash deploy/fix_stale_layers.sh` — run if not done this session |
| DIST-1 | HIGH | HN post / Twitter thread — needs /story first |
| Site deploy | — | Run `bash deploy/deploy_site_all.sh` to push all HTML changes live |

---

## Key Reminders for Next Session

**WR-17 next attempt — try fresh Lambda name:**
```bash
# If 403 persists, nuke and recreate with a new function name
aws lambda delete-function \
  --function-name life-platform-og-image \
  --region us-east-1

# Recreate with new name, same code
# Then update CloudFront origin to new Function URL
```

**Stale layers fix (if not run):**
```bash
bash deploy/fix_stale_layers.sh
```

**Site deploy (push all HTML changes):**
```bash
bash deploy/deploy_site_all.sh
```

**OG Lambda details (updated):**
- Function: `life-platform-og-image` (us-east-1)
- Function URL: `https://vatekozraszerm4hm5lxse6x3i0peokq.lambda-url.us-east-1.on.aws/` ← **UPDATED**
- CloudFront behavior `/og` → `OgImageOrigin` (wired in CDK)
- Source: `lambdas/og_image_lambda.mjs`

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
v3.7.76   Backend — /api/ask live, daily-brief deployed, WR-16/19/21/22/23/17 live
v3.7.77   Polish — reveal.js all pages, platform.html stats, WR-17 exhaustive debug
NEXT      /story prose → DIST-1 → site deploy → stale layers
SIMP-1 Ph2 (~Apr 13)   95 → 80 tools
```
