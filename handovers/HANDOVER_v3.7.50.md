# Life Platform Handover — v3.7.50 (Website Phase 1)
**Date:** 2026-03-16
**Pointer:** `handovers/HANDOVER_LATEST.md` → this file

---

## Platform State

| Metric | Value |
|--------|-------|
| Version | v3.7.50 |
| MCP tools | 87 |
| Data sources | 19 active |
| Lambdas | 42 CDK + 2 Lambda@Edge (+ 1 pending: site-api) |
| CloudWatch alarms | ~49 |
| Tests | 83/83 passing |
| Website | averagejoematt-site/ committed to S3 at s3://matthew-life-platform/site/ |

---

## What Was Done This Session

### Website Phase 1 — full scaffold built and deployed to S3

**Files created in `/Users/matthewwalker/Documents/Claude/averagejoematt-site/`:**

| File | Purpose |
|------|---------|
| `index.html` | Homepage — Signal aesthetic, real-time API fetch, responsive |
| `platform/index.html` | Architecture deep-dive — tech stack, layers, review history |
| `character/index.html` | Character progress — pillar scores, tier map, event log |
| `journal/index.html` | Journal listing — amber skin, serif body type |
| `journal/posts/TEMPLATE.html` | Post template — drop cap, data callout blocks, reading progress bar |
| `assets/css/tokens.css` | Design token system — single source of truth for all colours/fonts |
| `assets/css/base.css` | Reset + all shared components (nav, vitals, ticker, buttons) |
| `assets/css/responsive.css` | 5-breakpoint responsive system (320px → 1280px) |
| `data/public_stats.json` | Schema for daily Lambda write |
| `data/character_stats.json` | Schema for nightly character compute write |
| `DEPLOY.md` | Step-by-step deployment guide |

**Files created in life-platform repo:**

| File | Purpose |
|------|---------|
| `lambdas/site_writer.py` | Writes public_stats.json + character_stats.json from existing Lambdas |
| `lambdas/site_api_lambda.py` | Read-only real-time API (4 endpoints) with viral defence built in |

**All committed to S3:** `s3://matthew-life-platform/site/` ✅

**Site repo initialised:** `/Users/matthewwalker/Documents/Claude/averagejoematt-site/` — v1.0.0 committed locally.

### Cost + viral defence analysis
- 50k hits cost: ~$0.33 (CloudFront TTL caching + Lambda concurrency cap)
- Defence stack: WAF managed rules ($5/mo) + Lambda reserved concurrency = 20 + $5 budget alert
- Architecture: real-time API Gateway → Lambda → DynamoDB, fronted by CloudFront with TTL tiers

### Board sessions
- Web board convened (Jony Ive, Bret Victor, Karpathy, Jason Fried, Patrick Collison, Rasmus Andersson, Frank Chimero, Tobias van Schneider, Frank Chimero, John Maeda, Des Traynor, Julie Zhuo, Chris Do)
- Both boards (Tech + Health) convened on website roadmap
- Full 5-phase roadmap produced (Signal Launch → Dashboard → AI Showcase → Living Document → The Product)

---

## ⚠️ One Fix Needed Before Site Goes Live

`responsive.css` was created AFTER the S3 sync. Re-sync needed:

```bash
aws s3 cp /Users/matthewwalker/Documents/Claude/averagejoematt-site/assets/css/responsive.css \
  s3://matthew-life-platform/site/assets/css/responsive.css \
  --region us-west-2
```

---

## Pending Items for Next Session

| Item | Priority | Notes |
|------|----------|-------|
| **Deploy site_api_lambda via CDK** | High | Add to `cdk/stacks/web_stack.py`. Set reserved concurrency = 20. Lambda name: `life-platform-site-api`. |
| **Create API Gateway HTTP API** | High | Route `/api/*` → `life-platform-site-api`. See DEPLOY.md Step 2. |
| **CloudFront behaviour for `/api/*`** | High | Add behaviour to new (or existing) CloudFront distribution: `/api/*` → API GW origin. TTL tiers: vitals=300s, journey=3600s, character=900s. |
| **Route 53 — point averagejoematt.com** | High | Add A record (Alias) → new CloudFront distribution. Get ACM cert in us-east-1 first. |
| **WAF rate limit rule** | Medium | `aws wafv2 create-web-acl` with rate limit 100/min per IP. Attach to CloudFront. |
| **Wire site_writer.py into daily-brief-lambda** | Medium | Follow DEPLOY.md Step 3. Add ~15 lines at end of lambda_handler. |
| **Wire site_writer.py into character-sheet-compute** | Medium | Follow DEPLOY.md Step 4. |
| **IAM: add S3 site/* write to both Lambda roles** | Medium | Follow DEPLOY.md Step 5. Or update CDK role_policies.py. |
| **Re-sync responsive.css to S3** | Low | See fix above — created after initial sync. |
| **GitHub Actions for averagejoematt-site repo** | Low | Set up auto-deploy on push to main. Simple: `aws s3 sync` + CloudFront invalidation. |
| **Character pillar radar chart** | Phase 1 | Sarah Chen + Maeda top pick. Animated SVG radar of 7 pillars. ~3h. |
| **GitHub Actions unblock** | Pending | Support ticket filed 2026-03-15. Once resolved: `gh workflow run ci-cd.yml --ref main` |
| R17 Architecture Review | Deferred | ~2026-04-08. Run `python3 deploy/generate_review_bundle.py` first. |

---

## Key Learnings This Session

**S3 sync + later file additions:** When you add files after the initial `aws s3 sync`, they don't get automatically uploaded. Always run the sync again or use `aws s3 cp` for individual files.

**Site repo is separate from life-platform repo:** `averagejoematt-site/` has its own git repo (currently local only). Consider pushing to GitHub as `averagejoematt/averagejoematt-site` for CI/CD.

**Real-time vs static JSON:** Real-time API engine (site_api_lambda) is the right architecture — CloudFront TTL caching means it costs the same as static JSON at scale, but data is always live.

**The most impactful next feature (board consensus):** Character pillar radar chart. It's the one element that makes the character page emotionally resonant. ~3 hours of work, highest visual WOW per hour.

---

## Website Roadmap Summary (board-approved)

| Phase | Timeline | Key feature |
|-------|----------|-------------|
| 1 — Signal Launch | Now → May 5 | Responsive, real-time, character radar, email capture |
| 2 — Dashboard | May–Jul | Timeline scrubber, milestone cards, PWA |
| 3 — AI Showcase | Aug–Oct | "Ask the Platform", correlation heatmap, centenarian benchmarks |
| 4 — Living Document | Nov–Feb | WebSocket streaming, visitor mirror mode, video digest |
| 5 — The Product | 2027 | White-label, clinician dashboard, enterprise |

---

## Files Changed This Session

```
lambdas/site_writer.py              # NEW: writes JSON to S3 for website
lambdas/site_api_lambda.py          # NEW: real-time public API Lambda
docs/CHANGELOG.md                   # v3.7.50 entry (write this)
handovers/HANDOVER_v3.7.50.md       # this file
handovers/HANDOVER_LATEST.md        # pointer updated

averagejoematt-site/ (separate repo)
  index.html, platform/, character/, journal/
  assets/css/tokens.css, base.css, responsive.css
  data/public_stats.json, character_stats.json
  DEPLOY.md
```
