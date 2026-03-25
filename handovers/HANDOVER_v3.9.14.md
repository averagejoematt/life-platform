# Handover — v3.9.14 (2026-03-25)

> Prior: handovers/HANDOVER_v3.9.13.md

## SESSION SUMMARY
Product Board convened to reimagine the Experiments page from a static lab notebook into a living experiment library. Built: 52-experiment evidence-based library config (S3), 4 new API endpoints (library, vote, follow, detail), complete 3-zone page rewrite (Mission Control + Library + Record), CloudFront `/api/*` fix (POST methods + query string forwarding were blocked). Full implementation spec written and approved by all 8 Product Board members.

## WHAT CHANGED

### config/experiment_library.json (NEW — EL-1)
- 52 evidence-based experiment ideas across 7 pillars (Sleep, Movement, Nutrition, Supplements, Mental, Social, Discipline)
- Each experiment: id, name, description, pillar, evidence_tier, evidence_citation, suggested_duration, difficulty, metrics, hypothesis_template, protocol_template, why_it_matters
- 4 experiments pre-linked to active DynamoDB records (Tongkat Ali, NMN, Creatine, Berberine)
- Deployed to: `s3://matthew-life-platform/site/config/experiment_library.json`

### lambdas/site_api_lambda.py (EL-2/3/4 + EL-F1/F2)
- `handle_experiment_library()` — GET `/api/experiment_library`: S3 config + DynamoDB vote merge + experiment status merge, grouped by pillar
- `_handle_experiment_vote()` — POST `/api/experiment_vote`: atomic DynamoDB counter + 24hr IP-based TTL rate limit
- `_handle_experiment_follow()` — POST `/api/experiment_follow`: email interest storage for per-experiment notifications, 10/hr rate limit
- `_handle_experiment_detail()` — GET `/api/experiment_detail?id=slug`: full library entry + vote count + follower count + all past DynamoDB runs
- **NOTE**: File contains a dead `_REMOVED_handle_experiment_detail` duplicate function — clean up next session
- S3 key path: `site/config/experiment_library.json` (within site-api IAM `site/config/*` read scope)

### cdk/stacks/web_stack.py (CloudFront fix — CRITICAL)
- `/api/*` catch-all cache behavior updated:
  - `query_string: False` → `True` (experiment_detail needs `?id=` param)
  - `allowed_methods: GET/HEAD/OPTIONS` → `+ POST/PUT/PATCH/DELETE` (vote, follow, nudge, submit_finding were silently blocked)
  - Added `Content-Type` header forwarding (POST body parsing)
- CDK deployed: `npx cdk deploy LifePlatformWeb`
- This fixed voting, nudging, submit_finding, and follow — ALL of which were silently failing through CloudFront before this fix

### site/experiments/index.html (EL-6 through EL-15 — COMPLETE REWRITE)
- Zone 1 (Mission Control): SVG progress rings, progress bars, tier badges, evidence chips
- Zone 2 (The Library): 7 pillar sections, collapsible headers, 3-col grid, voting with optimistic UI + localStorage dedup, pillar filters, sort controls
- Zone 3 (The Record): grade badges, full card design retained
- Retained: H/P/D explainer, methodology section, pipeline nav, N=1 disclaimer

### docs/EXPERIMENTS_EVOLUTION_SPEC.md (NEW)
- 12 sections, 26 tasks across 6 phases, full Product Board sign-off

### docs/CHANGELOG.md — v3.9.14 entry prepended
### docs/PROJECT_PLAN.md — Experiments Evolution section added, v3.9.14 in completed items

## DEPLOYED
```bash
# S3 config (initially to config/, then copied to site/config/ for IAM)
aws s3 cp config/experiment_library.json s3://matthew-life-platform/site/config/experiment_library.json

# Lambda (4 deploys: initial + S3 key fix + F1/F2 endpoints + dedup cleanup)
bash deploy/deploy_lambda.sh life-platform-site-api lambdas/site_api_lambda.py

# CDK (CloudFront /api/* POST + query string fix)
npx cdk deploy LifePlatformWeb

# Experiments page
aws s3 cp site/experiments/index.html s3://matthew-life-platform/site/experiments/index.html
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/experiments/*"
```

## DynamoDB SCHEMA ADDITIONS
- `VOTES#experiment_library / LIB#{library_id}` — vote counts (atomic counter)
- `VOTES#rate_limit / IP#{hash}#LIB#{library_id}` — vote rate limit (24hr TTL)
- `VOTES#rate_limit / FOLLOW#{ip_hash}#{hour}` — follow rate limit (2hr TTL)
- `EXPERIMENT_FOLLOWS / EMAIL#{hash}#EXP#{library_id}` — follow interest records

## PENDING / CARRY FORWARD

### Experiments Evolution — remaining frontend work
- **F1 frontend**: Follow buttons on library tiles (backend live, UI not wired)
- **F2 frontend**: Build `/experiments/detail/index.html` page consuming `/api/experiment_detail`
- **F3**: og:meta shareable cards on detail pages
- **F4**: "Try It With Me" CTAs on active experiment cards
- **F5**: MCP tool updates — `create_experiment` (library_id, duration_tier, iteration auto-detect) and `end_experiment` (grade, compliance_pct, reflection). Changes were built on Claude's container but NOT applied to `mcp/tools_lifestyle.py`

### Code cleanup
- Remove `_REMOVED_handle_experiment_detail` dead function from site_api_lambda.py

### EL-16–23 (Record zone polish)
- Grade badges on completed cards, compliance % bars, reflection field
- 5 new experiment achievement badges in handle_achievements
- Achievement badge inline display on completed experiment cards

### Other carry-forward
- Withings OAuth: No weight data since Mar 7
- CHRON-3/4: Chronicle generation fix + approval workflow
- G-8: Privacy page email confirmation
- SIMP-1 Phase 2 + ADR-025 cleanup: ~Apr 13
- Nav label: "Benchmarks" → "The Standards" in components.js
- `/api/benchmark_trends` endpoint: frontend ready, backend not built

## LEARNINGS
- **S3 IAM scope**: Site API Lambda only has read access to `site/config/*`, not root `config/*`. All site-api S3 configs must use `site/config/` prefix.
- **CloudFront `/api/*` was blocking POST**: The catch-all behavior only allowed GET/HEAD/OPTIONS. Voting, nudging, follow, and submit_finding were all silently failing (200 from CloudFront cache, never reaching Lambda). Fixed by updating to allow all methods + forward query strings + Content-Type header.
- **DynamoDB conditional puts for rate limiting**: `ConditionExpression="attribute_not_exists(pk)"` with TTL records is cleaner than in-memory counters — survives cold starts.
- **Product Board value**: Mara (simplify) vs Raj (add features) tension produced the right balance — library collapses on mobile, but voting shipped in Phase 1.
