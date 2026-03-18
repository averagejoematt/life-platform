# Life Platform Handover — v3.7.75
**Date:** 2026-03-18 (end of session)

---

## Platform State

| Metric | Value |
|--------|-------|
| Version | v3.7.75 |
| MCP tools | 95 |
| Data sources | 19 active |
| Lambdas | 48 (CDK) + 1 Lambda@Edge + 1 us-east-1 (site-api) + 1 us-west-2 manual (email-subscriber) |
| Tests | **0 failing / 853 passing / 22 skipped / 11 xfailed** |
| Architecture grade | A (R16) |
| Website | **11 pages** at averagejoematt.com (added /ask/) |
| CI | ✅ GREEN |

---

## What Was Done This Session

### Website Strategy Review + 14 Enhancements

Comprehensive expert panel review (30 personas across design, product, growth, health, AI, commercialization, technical board, personal board) produced a 10-section analysis with 30/60/90 day roadmap. Then executed 14 of the recommended enhancements in-session.

**Deployed to S3/CloudFront (live now):**
1. Stats inlining — `deploy/inline_stats.py` bakes public_stats.json into HTML at deploy time (fixes "dashes" problem)
2. OG social preview image — `deploy/generate_og_image.py` with live stats
3. OG/Twitter meta tags on all 11 pages
4. sitemap.xml + robots.txt (SEO foundation)
5. 404.html branded error page + CloudFront custom error response
6. N=1 disclaimers on character, explorer, experiments, biology
7. Newsletter CTA copy improved
8. Homepage "Live Signals" sparkline section (weight chart from /api/weight_progress, HRV/recovery from vitals)
9. Homepage "What Claude Sees" AI brief widget (placeholder until daily-brief deploys with brief_excerpt)
10. /ask/ page frontend (Ask the Platform — suggestion chips, conversation UI, session rate limit)
11. RSS feed at /rss.xml (4 journal posts) + autodiscovery links
12. Story page writing prompts (5 chapters with specific "Start with:" prompts)

**Code ready, needs Lambda deploy:**
13. `site_writer.py` v1.2.0 — trends + brief_excerpt params
14. `daily_brief_lambda.py` — builds trend arrays (weight_daily, hrv_daily, sleep_daily, recovery_daily) + extracts brief excerpt
15. `site_api_lambda.py` — /api/ask POST endpoint (Claude Haiku 4.5, rate limited, data sanitized)

---

## Open Issues

| Issue | Priority | Notes |
|-------|----------|-------|
| /story prose | **CRITICAL** | Distribution gate — Matthew writes 5 chapters (prompts now in place) |
| /api/ask backend | HIGH | Code in site_api_lambda.py ready. Needs: (1) `aws secretsmanager create-secret --name life-platform/anthropic-api-key`, (2) IAM role policy for GetSecretValue, (3) DynamoDB TTL enabled, (4) site-api Lambda deploy |
| daily-brief Lambda deploy | HIGH | Updated code adds trends + brief_excerpt to public_stats.json. Enables sparklines + AI brief widget |
| site-api Lambda deploy | HIGH | Updated code has /api/ask endpoint |
| DIST-1 | HIGH | HN post or Twitter thread — needs /story first |
| chronicle_email_sender scope | LOW | F821 suppressed with noqa |
| Stale layers (I2) | LOW | anomaly-detector, character-sheet-compute, daily-metrics-compute on v9 vs v10 |

---

## Key Reminders for Next Session

**Site deploy command (standard):**
```bash
bash ~/Documents/Claude/life-platform/deploy/deploy_site_all.sh
```

**Wire /api/ask backend (3 steps):**
```bash
aws secretsmanager create-secret --name life-platform/anthropic-api-key \
  --secret-string 'sk-ant-...' --region us-west-2

aws iam put-role-policy --role-name life-platform-site-api-role \
  --policy-name ask-secrets --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"secretsmanager:GetSecretValue","Resource":"arn:aws:secretsmanager:us-west-2:205930651321:secret:life-platform/anthropic-api-key-*"}]}'

aws dynamodb update-time-to-live --table-name life-platform \
  --time-to-live-specification 'Enabled=true,AttributeName=ttl' --region us-west-2
```

**New deploy scripts created this session:**
- `deploy/inline_stats.py` — bake stats into HTML
- `deploy/generate_og_image.py` — OG preview image
- `deploy/generate_rss.py` — RSS feed from journal posts
- `deploy/fix_site_meta.py` — batch OG/nav/footer fixer
- `deploy/deploy_site_all.sh` — full site deploy (6 steps)

**Website review document:** Available at `/mnt/user-data/outputs/website_review.md` (also in session context)

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
NEXT      /story prose → DIST-1 → /api/ask backend → daily-brief deploy
SIMP-1 Ph2 (~Apr 13)   95 → 80 tools
```
