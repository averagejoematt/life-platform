# Handover — v3.9.16 (2026-03-25)

## Session Summary
**Data-Driven Architecture Pivot** — Joint Product Board + Technical Board session. Identified hardcoded website content as architectural debt. Built complete data-driven foundation: 3 S3 config files (protocols, challenges, domains), 4 new API endpoints, and wired all 4 affected pages to consume APIs instead of hardcoded HTML/JS.

## What Changed

### New Files
- `site/config/protocols.json` — Source of truth for 6 health protocols (S3)
- `site/config/challenges.json` — Source of truth for 5 visitor challenges (S3)
- `site/config/domains.json` — Source of truth for 5 domain groupings (S3)
- `site/stack/index.html` — New "The Stack" page (domain map, live experiments, vice streaks)

### Modified Files
- `lambdas/site_api_lambda.py` — 4 new endpoints: `/api/protocols`, `/api/challenges`, `/api/domains`, `/api/habit_registry`
  - Bug fix: initial deploy used `ttl=3600` instead of `cache_seconds=3600` — fixed and redeployed
  - Added `_load_s3_json()` helper with module-level caching
  - `handle_habit_registry()` reads from DynamoDB PROFILE#v1, sorts by tier
- `site/protocols/index.html` — **Fully data-driven**: 6 hardcoded protocol cards replaced with dynamic render from `/api/protocols`. Adherence + experiment badges load after cards render.
- `site/experiments/index.html` — Challenges zone: 3 hardcoded cards replaced with dynamic render from `/api/challenges` (now shows all 5 challenges)
- `site/habits/index.html` — **Fully data-driven**: `T0_HABITS`, `PURPOSE_GROUPS`, `T2_HABITS` hardcoded JS arrays replaced with `transformRegistry()` that fetches from `/api/habit_registry` and transforms DynamoDB data into the same shapes the render functions expect.
- `site/stack/index.html` — **Fully data-driven**: domain cards rendered from `/api/domains` + `/api/protocols` + `/api/experiments` + `/api/vice_streaks`
- `site/assets/js/components.js` — "The Stack" added to Method dropdown, hierarchy nav `buildHierarchyNav()` function added, footer updated
- `site/achievements/index.html` — Hierarchy nav added
- `deploy/sync_doc_metadata.py` — Version bumped to v3.9.16

### Board Decisions
- **Product Board**: "The Stack" page (unanimous), hierarchy nav replaces pipeline nav, challenges concept (amber treatment), keep all deep pages
- **Technical Board**: Tiered source-of-truth architecture:
  - Habit registry → DynamoDB (already exists, wired via `/api/habit_registry`)
  - Protocols → S3 config (change rarely, 6 records)
  - Challenges → S3 config (5 records)
  - Domains → S3 config (5 records)
  - Viktor pushback accepted: S3 JSON is right for entities that change quarterly; promote to DynamoDB only if versioning/history needed

### New API Endpoints (all live, all tested)
| Endpoint | Source | Cache |
|----------|--------|-------|
| `GET /api/protocols` | S3 `site/config/protocols.json` | 3600s |
| `GET /api/challenges` | S3 `site/config/challenges.json` | 3600s |
| `GET /api/domains` | S3 `site/config/domains.json` | 3600s |
| `GET /api/habit_registry` | DynamoDB `PROFILE#v1.habit_registry` | 3600s |

### Architecture Pattern
**Config drift eliminated.** Before: website HTML and DynamoDB told two different stories. Now: every page reads from a single source of truth via API. Changes to a protocol or habit tier automatically propagate to every page that references them.

## What's Next
- **End-of-session**: Run `python3 deploy/sync_doc_metadata.py --apply`, git commit
- **Stack page wiring verified** — all 4 pages data-driven
- **SIMP-1 Phase 2 + ADR-025 cleanup** — targeted ~April 13, 2026
- **Architecture Review #14** — next review cycle
- **Website Review #4** — visual QA pass on all data-driven pages

## Deploy Commands Used
```bash
# S3 configs
aws s3 cp site/config/protocols.json s3://matthew-life-platform/site/config/protocols.json --content-type "application/json"
aws s3 cp site/config/challenges.json s3://matthew-life-platform/site/config/challenges.json --content-type "application/json"
aws s3 cp site/config/domains.json s3://matthew-life-platform/site/config/domains.json --content-type "application/json"

# Lambda
bash deploy/deploy_lambda.sh life-platform-site-api lambdas/site_api_lambda.py

# Pages
aws s3 cp site/protocols/index.html s3://matthew-life-platform/site/protocols/index.html --content-type "text/html"
aws s3 cp site/experiments/index.html s3://matthew-life-platform/site/experiments/index.html --content-type "text/html"
aws s3 cp site/habits/index.html s3://matthew-life-platform/site/habits/index.html --content-type "text/html"
aws s3 cp site/stack/index.html s3://matthew-life-platform/site/stack/index.html --content-type "text/html"
aws s3 cp site/assets/js/components.js s3://matthew-life-platform/site/assets/js/components.js --content-type "application/javascript"
aws s3 cp site/achievements/index.html s3://matthew-life-platform/site/achievements/index.html --content-type "text/html"
```
