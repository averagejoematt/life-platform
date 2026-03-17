## v3.7.70 — 2026-03-17: Sprint 5 execution — website, email CTAs, deficit ceiling, MCP fix

### Summary
Sprint 5 execution session. Sprint 4 deployed (BS-11 /live, WEB-CE /explorer, BS-BM2 /biology, 3 API endpoints). Two new website pages built (/about, /story). Email subscribe CTA injected into all 8 site pages. Adaptive deficit ceiling (S2-T1-9) implemented in daily-insight-compute. MCP Key import bug fixed and redeployed.

### Changes
- **Sprint 4 deploy complete**: /live, /explorer, /biology pages + /api/timeline, /api/correlations, /api/genome_risks live at averagejoematt.com
- **`site/about/index.html`** (new): Bio page — professional context, live weight, sidebar stats, full tech stack table, amber subscribe CTA
- **`site/story/index.html`** (new): 5-chapter story template — platform stats pre-filled, placeholder blocks for Matthew's prose in Chapters 1/2/4/5
- **`deploy/add_email_cta.py`**: Script that injects amber email CTA section before footer on all pages — ran successfully on 8/8 pages (index, platform, journal, character, experiments, biology, live, explorer)
- **`deploy/patch_deficit_ceiling.py`**: Surgical patch for `daily_insight_compute_lambda.py` — adds `_compute_deficit_ceiling_alert()`, updates priority queue, handler call site, return dict
- **Adaptive deficit ceiling (S2-T1-9)** in `daily_insight_compute_lambda.py`:
  - Tier A (RATE, P2): weight loss >2.5 lbs/wk over 14 days → specific +200 kcal prescription
  - Tier B (MULTI, P1): HRV ↓>15% AND sleep eff <80% (3+ days) AND ≥2 T0 habits failing → same prescription, max priority
  - Configurable via env vars: DEFICIT_RATE_THRESHOLD, DEFICIT_HRV_DROP_PCT, DEFICIT_KCAL_INCREASE, DEFICIT_REASSESS_DAYS
- **MCP Key bug fixed**: `from boto3.dynamodb.conditions import Key` was already on disk — MCP Lambda redeployed to pick it up
- All site changes synced to S3 + CloudFront invalidated

### Deploys this session
- `life-platform-site-api` (us-east-1): Sprint 4 endpoints
- `life-platform-mcp` (us-west-2): Key import fix
- `daily-insight-compute` (us-west-2): S2-T1-9 deficit ceiling [PENDING — run bash deploy/deploy_lambda.sh daily-insight-compute lambdas/daily_insight_compute_lambda.py]

### Open
- `/story` page placeholder content — Matthew must write Chapters 1, 2, 4, 5
- Weekly habit review (S2-T1-10) — not started
- First distribution event (DIST-1) — not started
- Privacy policy on /subscribe (Yael requirement)

---

## v3.7.69 — 2026-03-17: Board Summit #2 — post-sprint review + Sprint 5 plan

### Summary
Board Summit #2 conducted (16 members, Health + Technical boards). Post-sprint review: all 4 Summit #1 sprints complete (30 items shipped). Summit identified distribution as unanimous #1 priority (zero subscribers despite working infrastructure). Rate-of-loss medical concern flagged (>2.5 lbs/wk). Sprint 5 planned: 8 items focused on website (story page, about page, email CTAs, design enforcement) + behavior change (adaptive deficit ceiling, weekly habit review) + distribution (first HN/Twitter event). Full summit record: `docs/reviews/BOARD_SUMMIT_2_2026-03-17.md`.
