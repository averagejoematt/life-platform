# Life Platform — Changelog

## v3.7.61 — 2026-03-16: Board Summit gap-fill + full sprint plan

### Summary
Documentation-only session. Read and processed the 27-page Joint Board Summit Record (March 15, 2026). Gap analysis against PROJECT_PLAN confirmed 8 items missing from previous integration. All gaps filled, IC-27–31 explicitly defined, and a complete 4-sprint implementation roadmap created with full board review and alignment (22 board members, Health + Technical).

### Changes
- `docs/PROJECT_PLAN.md`: Updated to v3.7.61. Added 8 missing Board Summit items (BS-T2-7, BS-T3-5, BS-T3-6, WEB-CE, WEB-NET, WEB-WCT, EMAIL-P2, EMAIL-P3). IC-27–31 defined explicitly with descriptions, models, gates. Sprint assignments added to all BS-* items. Email phases given concrete target dates (June 16 / Sep 16, 2026). Model assignments updated per board (BS-NU1, BS-MP1 → Opus; BS-09 → None/pure compute). Architecture review target updated to R17 ~June 2026.
- `docs/SPRINT_PLAN.md`: **NEW** — complete implementation roadmap. 4 sprints + SIMP-1 Phase 2 mini-sprint. 48 features inventoried: 26 in sprints 1-4, 22 in backlog. Effort estimates (XS–XL), model assignments (None/Sonnet/Opus), deliverables, champions, definitions of done, and prerequisite tasks per sprint.
- `docs/reviews/BOARD_SPRINT_REVIEW_2026-03-16.md`: **NEW** — full joint board review record. All 22 board members (Health Board: Attia, Huberman, Patrick, Clear, Goggins, Hormozi, Norton, Moreau, Kim; Technical Board: Nakamura, Webb, Cohen, Park, Reyes, Khalil, Patel, Brandt, Chen, Srinivasan, Sorokin, Torres) reviewed and aligned on sprint plan. Key adjustments: BS-05 moved to Sprint 1 (Yael), BS-SL2 moved to Sprint 2 (Huberman), BS-12 moved to Sprint 3 (data maturity), BS-NU1/BS-MP1 → Opus (Patrick/Norton/Anika), WEB-NET/IC-30 → backlog (Viktor), Sprint 4 scoped down to 4 items.

### No Deployments
Docs-only session. No Lambdas deployed, no CDK changes, no AWS infrastructure touched.

### Sprint Plan Summary
- **Sprint 1** (~Mar 30, ~19h): BS-01 Essential Seven, BS-02 Website Hero, BS-03 Chronicle Email, BS-05 AI Confidence Scoring, BS-09 ACWR Load Model
- **Sprint 2** (~Apr 13, ~27h): BS-07 Website API, BS-08 Unified Sleep Record, BS-SL2 Circadian Score, BS-BH1 Vice Streaks, BS-MP3 Decision Fatigue, BS-TR1/TR2/NU1
- **SIMP-1 Ph2** (~Apr 13, ~5h): 89→≤80 tools via EMF telemetry
- **Sprint 3** (~May 11, ~38h): BS-12 Deficit Tracker, BS-SL1 Sleep Optimizer, BS-MP1 Autonomic Balance, BS-MP2 Journal Sentiment, BS-13 Experiments, BS-T2-5 Newsletter, WEB-WCT, IC-28/29
- **Sprint 4** (~Jun 8, ~27h): BS-11 Transformation Timeline, WEB-CE Correlation Explorer, BS-BM2 Genome Dashboard, BS-14 Multi-User Design

---

## v3.7.60 — 2026-03-17: TB7-26 WAF + subscribe end-to-end fix

### Summary
WAF WebACL live on averagejoematt.com CloudFront. Subscribe flow fixed (email-subscriber was writing DDB to us-east-1 instead of us-west-2). Subscribe test 5/5 passing.

### Changes
- `lambdas/email_subscriber_lambda.py`: Added `DYNAMODB_REGION` env var (defaults `us-west-2`). DynamoDB client now uses `DYNAMODB_REGION`; SES client uses `REGION` (us-east-1). Fixes cross-region DDB access from us-east-1 Lambda.
- `cdk/stacks/web_stack.py`: `DYNAMODB_REGION=us-west-2` added to `EmailSubscriberLambda` environment.
- `deploy/setup_waf.sh`: **NEW** — creates WAF WebACL with 2 rate rules, attaches to CloudFront E3S424OXQZ8NBE via `update-distribution`.
- `deploy/test_subscribe.sh`: **NEW** — end-to-end subscribe flow test (5 assertions: HTTP 200, body, 400 invalid, 400 empty, DDB record).

### Deployed
- `email-subscriber` Lambda code (us-east-1) ✅
- `email-subscriber` env var `DYNAMODB_REGION=us-west-2` updated ✅
- WAF WebACL `life-platform-amj-waf` created + attached to E3S424OXQZ8NBE ✅

### WAF Rules
- `SubscribeRateLimit`: /api/subscribe* — block >60 req/5min per IP
- `GlobalRateLimit`: all paths — block >1000 req/5min per IP
- Cost: ~$6/month

---

## v3.7.59 — 2026-03-17: Site unification + data fixes + BS-05/BS-09 in Weekly/Chronicle

### Summary
Full session: Signal teal homepage + subscribe rebuilt on token system, S3 public read restored (P1 recovery gap), homepage JS fixed (nested data paths), daily-brief site_writer data bugs fixed (weight/rate calc), BS-05 badge in Chronicle email, ACWR + Essential Seven in Weekly Digest, TB7-4 complete, TB7-18 confirmed retired.

### Changes
- `site/index.html`: Rebuilt on Signal token system — dark teal, two-column hero, live vitals grid, data ticker, journey progress bars, inline subscribe form. Fetches `/public_stats.json` with correct nested field paths.
- `site/subscribe.html`: Rebuilt on token system — teal, two-column, what-you-get panel.
- `site/`: All S3 pages pulled into repo (character, journal, platform, assets) — fully version controlled.
- `deploy/bucket_policy.json`: Canonical bucket policy committed (PublicReadSite + PublicReadBlog + ProtectData). Restores public read wiped in P1 recovery.
- `deploy/post_cdk_reconcile_smoke.sh`: S3 public read check added — curls site/index.html after every CDK deploy.
- `lambdas/daily_brief_lambda.py`: site_writer data bugs fixed — weight_delta_30d direction, weekly_rate_lbs null guard, hrv/rhr/recovery None guards, tier0_streak + days_in added to platform block, ACWR wired from computed_metrics.
- `lambdas/wednesday_chronicle_lambda.py`: BS-05 confidence badge on Chronicle email stats line. `compute_confidence(days_of_data=7)` → LOW CONFIDENCE (correct per Henning n<14 rule).
- `lambdas/weekly_digest_lambda.py`: ACWR row in Banister section (from computed_metrics, with alert row). Essential Seven perfect-days row in Habits section. `acwr_data` fetched in `gather_all()`.
- `docs/CHANGELOG.md`: P1 recovery gap noted in v3.7.57 entry.

### Deployed
- `daily-brief` Lambda ✅
- `weekly-digest` Lambda ✅
- `wednesday-chronicle` Lambda ✅
- `site/index.html` + `site/subscribe.html` to S3 ✅
- CloudFront invalidations (2) ✅

### Also This Session
- `.git` leak deleted from `site/.git/` in S3
- TB7-4: `life-platform/api-keys` permanently deleted ✅
- TB7-18: Confirmed retired (Google Calendar, ADR-030) ✅
- CDK LifePlatformWeb deployed: E3S424OXQZ8NBE, `/api/subscribe` live ✅
- CDK LifePlatformCompute + v3.7.55 full deploy ✅
- ACWR backfill 2026-03-15: 1.056 safe zone ✅

---

## v3.7.58 — 2026-03-16: BS-09 ACWR in Daily Brief + BS-05 Confidence Badges + CDK Web + TB7-4
