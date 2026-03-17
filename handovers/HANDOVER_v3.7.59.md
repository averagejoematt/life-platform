# Life Platform Handover — v3.7.59
**Date:** 2026-03-17 (end of session)

---

## Platform State

| Metric | Value |
|--------|-------|
| Version | v3.7.59 |
| MCP tools | 89 |
| Data sources | 19 active |
| Lambdas | 45 (CDK) + 1 Lambda@Edge + email-subscriber (manual) |
| Tests | 83/83 passing |
| Architecture grade | A (R16) |
| Website | **LIVE** — averagejoematt.com (Signal teal, unified) |
| IC features | 14 live / 31 total |

---

## What Was Done This Session

### 1. Full v3.7.55 Deploy
- setup_email_subscriber.sh + deploy_v3755_session.sh — 10/10 smoke ✅
- ACWR backfill 2026-03-15: 1.056, safe zone ✅

### 2. TB7-4 + CDK Web
- `life-platform/api-keys` permanently deleted (grep sweep clean) ✅
- `cdk deploy LifePlatformWeb` — distribution E3S424OXQZ8NBE, `/api/subscribe` live ✅

### 3. Site Unification (Signal teal)
- `site/index.html` + `site/subscribe.html` rebuilt on `tokens.css` + `base.css`
- Two-column hero, data ticker, live vitals grid, journey progress bars, inline subscribe
- All S3 pages now in git: character, journal, platform, assets
- S3 public read bucket policy restored (was wiped in P1 incident, not noticed until today)
- `deploy/bucket_policy.json` committed; `post_cdk_reconcile_smoke.sh` now checks S3 public read
- `.git` leak removed from S3

### 4. Homepage Data Fixes
- `site/index.html` JS: fixed fetch path (`/public_stats.json`), nested field paths (`v.weight_lbs`, `j.lost_lbs` etc.), weekly_rate sanity guard
- `daily_brief_lambda.py` site_writer: fixed weight_delta_30d direction, weekly_rate_lbs null guard, hrv/rhr/recovery None guards, tier0_streak + days_in in platform block, ACWR from computed_metrics

### 5. BS-05 Chronicle Badge
- `wednesday_chronicle_lambda.py`: `compute_confidence(days_of_data=7)` → LOW CONFIDENCE badge on stats line in email

### 6. Weekly Digest — ACWR + Essential Seven
- `weekly_digest_lambda.py`: `acwr_data` fetched from `computed_metrics` in `gather_all()`
- ACWR row added to Banister section (green/amber/red, alert row if firing)
- Essential Seven perfect-days row added at top of Habits section (progress bar, day count)

---

## Pending Next Session

### P0 — None

### High
| Item | Notes |
|------|-------|
| Homepage data population | Will auto-populate tomorrow at 10am PT when daily-brief runs. No action needed. |
| TB7-26 | CloudFront + WAF rate rule on MCP Function URL |
| TB7-25 | CI/CD rollback mechanism (alias-based atomic deploys) |
| TB7-27 | MCP tool tiering system design doc |
| BS-05 chronicle badge on journal posts | `publish_to_journal()` — add badge to post header |
| Test `/api/subscribe` end-to-end | POST to https://averagejoematt.com/api/subscribe |

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
| `site/index.html` | Signal teal rebuild + JS data fix |
| `site/subscribe.html` | Signal teal rebuild |
| `site/character/index.html` | Pulled from S3 into repo (no change) |
| `site/journal/*` | Pulled from S3 into repo (no change) |
| `site/platform/index.html` | Pulled from S3 into repo (no change) |
| `site/assets/` | Pulled from S3 into repo (tokens.css, base.css, icons) |
| `deploy/bucket_policy.json` | **NEW** — canonical bucket policy |
| `deploy/setup_email_subscriber.sh` | **NEW** — first-time IAM + Lambda setup |
| `deploy/post_cdk_reconcile_smoke.sh` | S3 public read check added |
| `lambdas/daily_brief_lambda.py` | site_writer data bugs fixed + ACWR |
| `lambdas/wednesday_chronicle_lambda.py` | BS-05 confidence badge |
| `lambdas/weekly_digest_lambda.py` | ACWR + Essential Seven in build_html |
| `docs/CHANGELOG.md` | v3.7.59 entry |

---

## Website State
- `averagejoematt.com` — Signal teal, live ✅
- `/subscribe` — Signal teal, live ✅ (subscribe form → `/api/subscribe` untested end-to-end)
- `/journal/` — amber serif, live ✅
- `/character/` — Signal teal, live ✅
- `/platform/` — Signal teal, live ✅
- Data: vitals show dashes until 10am PT tomorrow (daily-brief populates public_stats.json)

## TB7 Status
- TB7-1: ✅ GitHub production gate confirmed
- TB7-4: ✅ api-keys deleted
- TB7-18: ✅ Retired (Google Calendar ADR-030)
- TB7-24: ⏳ Lambda handler integration tests
- TB7-25: ⏳ CI/CD rollback mechanism
- TB7-26: ⏳ WAF rate rule on MCP Function URL
- TB7-27: ⏳ MCP tool tiering design
