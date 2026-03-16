# Life Platform Handover — v3.7.51 (CDK Web Stack + Deploy Scripts)
**Date:** 2026-03-16
**Pointer:** `handovers/HANDOVER_LATEST.md` → this file

---

## Platform State

| Metric | Value |
|--------|-------|
| Version | v3.7.51 |
| MCP tools | 87 |
| Data sources | 19 active |
| Lambdas | 43 (CDK count — includes site-api) |
| CloudWatch alarms | ~50 (site-api alarm added) |
| Tests | 83/83 passing |
| Architecture grade | A (R16) |

---

## Website Status — IN PROGRESS

### What's done
- Full site scaffold built and on S3: `s3://matthew-life-platform/site/`
- `life-platform-site-api` Lambda + Function URL defined in CDK
- `averagejoematt.com` CloudFront distribution defined in CDK
- ACM certificate requested: `arn:aws:acm:us-east-1:205930651321:certificate/e85e4b63-e7d0-4403-a64c-c235bc57084c`
- DNS validation CNAME added to Route 53 (confirmed resolving via `dig`)

### What's PENDING — site not yet live

**averagejoematt.com is LIVE** ✅

- CloudFront distribution: `E3S424OXQZ8NBE` (domain: `d2qlzq81ggequb.cloudfront.net`)
- Homepage returning 200
- Route 53 A+AAAA alias records pointing to CloudFront
- S3 bucket policy updated to allow `site/*` public read
- All static pages on S3 with correct cache-control headers
- Real-time API Lambda deployed (`life-platform-site-api`) — serving `/api/*`

---

## What Was Done This Session

### v3.7.51 — CDK LifePlatformWeb stack fully wired

**`cdk/stacks/web_stack.py`** — major update:
- Added `site_api_fn` Lambda (`life-platform-site-api`)
  - Read-only: DDB GetItem/Query + KMS Decrypt only
  - Reserved concurrency = 20 (viral defence hard cap)
  - Timeout = 15s (fast DDB reads only)
  - CloudWatch error alarm wired
- Added Lambda Function URL (CORS scoped to averagejoematt.com)
- Added `AmjDistribution` CloudFront distribution:
  - Two origins: S3 `/site` (default) + Lambda Function URL (`/api/*`)
  - Static: TTL 3600s default, 86400s max
  - API: TTL 300s default, 3600s max (Lambda sets Cache-Control per endpoint)
  - Custom error 404 → `/index.html` (SPA fallback)
  - Aliases: `averagejoematt.com` + `www.averagejoematt.com`
  - Cert: `e85e4b63` (us-east-1)
- CDK outputs: `AmjDistributionId`, `AmjDistributionDomain`, `SiteApiFunctionUrl`

**`cdk/stacks/role_policies.py`** — `site_api()` function added:
- DynamoDB: `GetItem`, `Query` on `life-platform` table only
- KMS: `Decrypt` on CMK only
- NO write, NO secrets, NO S3 — minimal by design (Yael directive)

**`ci/lambda_map.json`** — `site_api_lambda` added; `site_writer.py` in skip_deploy

**New deploy scripts (all `chmod +x`):**
| Script | Purpose |
|--------|---------|
| `deploy/request_amj_cert.sh` | Request ACM cert (already run ✅) |
| `deploy/validate_amj_cert.sh` | Add DNS CNAME to Route 53 (already run ✅) |
| `deploy/deploy_web_stack.sh` | CDK deploy with PLACEHOLDER guard |
| `deploy/point_route53_to_cloudfront.sh` | A+AAAA alias records, fetches CF domain from CDK outputs |
| `deploy/sync_site_to_s3.sh` | Tiered cache-control sync + CloudFront invalidation |
| `deploy/smoke_test_site.sh` | End-to-end: 5 pages + 4 API endpoints + response quality |

### v3.7.50 — Website Phase 1 scaffold (previous session)
- Full 5-page site: homepage, platform, character, journal, post template
- Design token system (`tokens.css`) + shared components (`base.css`)
- 5-breakpoint responsive CSS (`responsive.css`): 320px → 1280px
- Mobile nav drawer, Jony Ive one-vital-on-small-phone pattern
- Real-time API engine: parallel fetch `/api/vitals`, `/api/journey`, `/api/character`
- `lambdas/site_writer.py` — writes JSON for website from existing Lambdas
- `lambdas/site_api_lambda.py` — read-only API with viral defence
- Board sessions: Web board (12 members) + both Tech+Health boards on roadmap
- 5-phase website roadmap produced

---

## Key Numbers

| Item | Value |
|------|-------|
| Cert ARN | `arn:aws:acm:us-east-1:205930651321:certificate/e85e4b63-e7d0-4403-a64c-c235bc57084c` |
| Route 53 Zone ID | `Z063312432BPXQH9PVXAI` |
| ACM validation CNAME | `_612ee4c4692d048eb69001effeb11729.averagejoematt.com` |
| CNAME value | `_f78034378e595352da12cf2cc6c0ed40.jkddzztszm.acm-validations.aws.` |
| S3 site prefix | `s3://matthew-life-platform/site/` |
| CDK stack | `LifePlatformWeb` |

---

## Cost Profile (website)

| Component | Cost at 50k hits |
|-----------|-----------------|
| CloudFront (static) | ~$0.21 |
| Lambda API (TTL-cached) | ~$0.05 |
| DynamoDB reads | ~$0.01 |
| API GW | ~$0.02 |
| **Total** | **~$0.33** |
| WAF (when added) | $5/month flat |

Viral defence: Lambda reserved concurrency = 20. At cap → 429 error, not unbounded bill.

---

## Pending Beyond Go-Live

| Item | Priority | Notes |
|------|----------|-------|
| Wire `site_writer.py` into `daily_brief_lambda.py` | Medium | Follow DEPLOY.md Step 3 |
| Wire `site_writer.py` into `character_sheet_compute_lambda.py` | Medium | Follow DEPLOY.md Step 4 |
| IAM: add S3 site/* write to both Lambda roles | Medium | Or update CDK role_policies.py |
| WAF rate limit rule ($5/mo) | Medium | 100 req/min per IP |
| Character pillar radar chart | Phase 1 | ~3h, highest WOW/hour |
| Email capture → ConvertKit | Phase 1 | Build audience before content |
| GitHub Actions for averagejoematt-site repo | Low | Auto-deploy on push |
| TB7-4 (HARD DEADLINE 2026-03-17) | ⚠️ Critical | api-keys grep sweep before permanent deletion |
| R17 Architecture Review | Deferred | ~2026-04-08 |

---

## TB7-4 Reminder ⚠️

**DEADLINE: 2026-03-17** — Must confirm no code reads from `life-platform/api-keys` secret before permanent deletion. Run:

```bash
grep -r "api-keys" lambdas/ mcp/ --include="*.py" | grep -v ".pyc"
```

If nothing found → safe to delete. If found → update those references first.
