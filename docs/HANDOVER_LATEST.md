# Life Platform — Handover v2.95.0
**Date:** 2026-03-08  
**Session:** Architecture Review Hardening — Batch 1 (5 Quick-Win Tasks)

---

## What Was Done This Session

### AI-1: Health Disclaimers ✅
Added "⚕️ Personal health tracking only — not medical advice" footer to all 8 email Lambdas.

Files edited (source files on disk, not yet deployed):
- `lambdas/html_builder.py` — Daily Brief footer
- `lambdas/weekly_digest_lambda.py` — Weekly Digest footer
- `lambdas/monday_compass_lambda.py` — Monday Compass footer
- `lambdas/nutrition_review_lambda.py` — Saturday Nutrition Review footer
- `lambdas/wednesday_chronicle_lambda.py` — Wednesday Chronicle email footer
- `lambdas/weekly_plate_lambda.py` — The Weekly Plate footer
- `lambdas/anomaly_detector_lambda.py` — Anomaly Detector footer
- `lambdas/monthly_digest_lambda.py` — **already had disclaimer**, no change needed

### MAINT-3: Stale File Cleanup ✅
`deploy/maint3_cleanup.sh` written. Moves to `archive/YYYYMMDD/`:
- `.backup` / `.broken` files in `lambdas/`
- Old `.zip` files in `lambdas/` and `deploy/`
- Superseded versioned deploy scripts (`deploy_daily_brief_v21.sh` etc.)
- Orphaned copies (`scoring_engine.py`, `patch_*.py` in `deploy/`)
- `generate_habit_registry.py` → moves to `seeds/`
- Old `backup_2026*/` directories
- **Review the script before running** — nothing deleted, only moved.

### COST-1: S3 Glacier Lifecycle ✅
`deploy/cost1_s3_lifecycle.sh` — applies `raw/` → Glacier Instant Retrieval after 90 days.

### SEC-4: API Gateway Rate Limiting ✅
`deploy/sec4_api_gateway_throttle.sh` — 1.67 req/s + burst 10 on Health Auto Export HTTP API.

### IAM-2: IAM Access Analyzer ✅
`deploy/iam2_access_analyzer.sh` — creates `life-platform-analyzer` (free, ACCOUNT type).

---

## What Still Needs to Run

**Step 1 — Deploy email Lambdas (AI-1):**
```bash
bash deploy/deploy_v2.95.0.sh
```
Deploys: daily-brief, weekly-digest, monday-compass, nutrition-review, wednesday-chronicle, weekly-plate-schedule, anomaly-detector

**Step 2 — Infra one-shots (idempotent):**
```bash
bash deploy/cost1_s3_lifecycle.sh
bash deploy/sec4_api_gateway_throttle.sh
bash deploy/iam2_access_analyzer.sh
```

**Step 3 — Cleanup (review first):**
```bash
# Read through maint3_cleanup.sh, then:
bash deploy/maint3_cleanup.sh
```

**Step 4 — Git commit:**
```bash
git add -A && git commit -m "v2.95.0: Hardening batch 1 — AI-1 disclaimers, MAINT-3 cleanup, COST-1 lifecycle, SEC-4 throttle, IAM-2 analyzer" && git push
```

---

## Hardening Roadmap Status

### ✅ Done (Quick Wins)
| Task | Description |
|------|-------------|
| AI-1 | Health disclaimer on all 8 email Lambdas |
| MAINT-3 | Stale file cleanup scripts written |
| COST-1 | S3 Glacier lifecycle script written |
| SEC-4 | API Gateway throttle script written |
| IAM-2 | IAM Access Analyzer script written |

### 🔴 Next Up (P0/P1 — Next 2 Weeks)
| Task | Priority | Description |
|------|----------|-------------|
| SEC-1 | P0 | Decompose `lambda-weekly-digest-role` (used by 10+ Lambdas) into per-function roles |
| SEC-2 | P1 | Split `life-platform/api-keys` into domain-specific secrets |
| SEC-3 | P1 | Input validation on MCP tool arguments |
| MAINT-1 | P1 | `requirements.txt` per Lambda with pinned versions |
| MAINT-2 | P1 | Lambda Layer for shared modules |
| DATA-1 | P1 | Add `schema_version` to all DynamoDB items |
| REL-1 | P1 | Graceful degradation when compute Lambdas fail |

---

## Key Files
- `docs/REVIEW_2026-03-08.md` — Full 35-finding review
- `docs/PROJECT_PLAN.md` — Full hardening roadmap with all 35 tasks
- `docs/CHANGELOG.md` — v2.95.0 entry added

## Platform State
- **Version:** v2.95.0
- **Lambdas:** 35
- **MCP Tools:** 144
- **Modules:** 30
