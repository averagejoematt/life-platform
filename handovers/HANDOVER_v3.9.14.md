# Handover — v3.9.14 (2026-03-25)

> Prior: handovers/HANDOVER_v3.9.13.md

## SESSION SUMMARY
Product Board convened to reimagine the Experiments page. Designed and partially built a 52-experiment evidence-based library with community voting, 3-zone page architecture, and full implementation spec. Backend complete (2 new API endpoints, S3 config, DynamoDB voting with TTL rate limiting). Frontend complete (3-zone page rewrite with progress rings, pillar grid, voting UI). Experiments page HTML not yet deployed to S3.

## WHAT CHANGED

### config/experiment_library.json (NEW — EL-1)
- 52 evidence-based experiment ideas across 7 pillars
- Each experiment: id, name, description, pillar, evidence_tier, evidence_citation, suggested_duration_days, duration_tier, difficulty, metrics_measurable/behavioral, experiment_type, hypothesis_template, protocol_template, why_it_matters, tags, related_protocols, status, votes
- 4 experiments pre-linked to active DynamoDB records (Tongkat Ali, NMN, Creatine, Berberine)
- Pillar metadata with icons and colors
- Deployed to: `s3://matthew-life-platform/site/config/experiment_library.json`

### lambdas/site_api_lambda.py (EL-2/3/4)
- `handle_experiment_library()` — GET `/api/experiment_library`
  - Reads S3 config, merges DynamoDB vote counts (pk=VOTES#experiment_library), merges active experiment status (matches by library_id or name slug)
  - Groups by pillar, computes stats (total/active/completed/backlog per pillar)
  - Sorts: active experiments first, then by vote count descending
  - Cache: 900s
- `_handle_experiment_vote()` — POST `/api/experiment_vote`
  - Body: `{"library_id": "post-dinner-walk"}`
  - IP-based rate limiting: conditional put to `VOTES#rate_limit / IP#{hash}#LIB#{id}` with 24hr TTL
  - Atomic increment on `VOTES#experiment_library / LIB#{id}` using `ADD vote_count :one`
  - Returns 429 if already voted within 24hrs
- Deployed: 2 deploys (initial had wrong S3 key `config/` → fixed to `site/config/`)

### site/experiments/index.html (EL-6 through EL-15 — COMPLETE REWRITE)
- 3-zone architecture:
  - Zone 1 (Mission Control): SVG progress rings, progress bars, tier badges, evidence chips
  - Zone 2 (The Library): pillar-grouped collapsible grid, voting with optimistic UI + localStorage, pillar filters, sort controls
  - Zone 3 (The Record): grade badges, full card design retained
- Retained: H/P/D explainer, methodology section, pipeline nav, N=1 disclaimer
- **NOT YET DEPLOYED TO S3** — needs: `aws s3 cp site/experiments/index.html s3://matthew-life-platform/site/experiments/index.html --content-type "text/html" && aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/experiments/*" --no-cli-pager`

### docs/EXPERIMENTS_EVOLUTION_SPEC.md (NEW)
- Full implementation spec: 12 sections, 26 tasks across 6 phases
- Product Board sign-off from all 8 members
- Covers: data model, API design, visual design, community features, achievement integration, future phases

### docs/CHANGELOG.md
- v3.9.14 entry prepended

### docs/PROJECT_PLAN.md
- Experiments Evolution section added (EL-1 through EL-F5)
- v3.9.14 added to completed items
- Last update timestamp bumped

## DEPLOYED
```bash
# S3 config
aws s3 cp config/experiment_library.json s3://matthew-life-platform/site/config/experiment_library.json --content-type "application/json"

# Lambda (2 deploys)
bash deploy/deploy_lambda.sh life-platform-site-api lambdas/site_api_lambda.py

# DynamoDB TTL already enabled (confirmed)
```

## NOT YET DEPLOYED
```bash
# Experiments page HTML (written to filesystem, NOT yet on S3)
aws s3 cp site/experiments/index.html s3://matthew-life-platform/site/experiments/index.html --content-type "text/html"
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/experiments/*" --no-cli-pager

# sync_doc_metadata not yet run
python3 deploy/sync_doc_metadata.py --apply

# Git commit
git add -A && git commit -m "v3.9.14: Experiments page evolution — 52-experiment library, voting, 3-zone redesign" && git push
```

## PENDING / CARRY FORWARD

### Experiments Evolution — remaining tasks
- **EL-16–20**: Record zone enhancements (grade badges on completed cards, compliance % bars, "what I'd do differently" reflection field, achievement badge inline display)
- **EL-21**: Add 5 new experiment achievement badges to handle_achievements in site_api_lambda.py (Lab Rat, Research Fellow, Principal Investigator, Hot Streak, Renaissance Man)
- **EL-22–23**: Update MCP create_experiment/end_experiment with library_id, duration_tier, grade, compliance_pct fields
- **EL-F1**: Per-experiment email subscribe (UI hook designed, wiring deferred)
- **EL-F2**: Individual experiment pages (`/experiments/{slug}/`) for SEO
- **EL-F3**: Shareable og:image auto-generation per experiment
- **EL-F4**: "Try It With Me" co-experiment announcements
- **EL-F5**: Experiment repeat/iteration tracking

### Other carry-forward
- **Withings OAuth**: No weight data since Mar 7 — needs re-auth
- **CHRON-3/4**: Chronicle generation fix + approval workflow
- **G-8**: Privacy page email confirmation
- **SIMP-1 Phase 2 + ADR-025 cleanup**: ~Apr 13
- **Nav label**: components.js still says "Benchmarks" in Evidence dropdown — consider renaming to "The Standards"
- **Benchmarks trend endpoint**: `/api/benchmark_trends` — frontend ready, backend not built

## LEARNINGS
- Site API Lambda IAM role only has S3 read access to `site/config/*` prefix, not root `config/*`. All site-api S3 configs must use the `site/config/` prefix.
- DynamoDB conditional puts (`ConditionExpression="attribute_not_exists(pk)"`) work well for rate limiting — cleaner than in-memory counters since they survive cold starts.
- Product Board dynamics: Mara (simplify) vs Raj (add features) tension produced the right balance — library collapses by default on mobile, but voting system shipped in Phase 1 rather than being deferred.
