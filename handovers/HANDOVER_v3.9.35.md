# Handover v3.9.35 — Signal Doctrine Tier 1 Rollout + Arena Voting + Experiments

**Date**: 2026-03-26
**Session focus**: Apply design brief to remaining pages, character ring chart, lifecycle gaps, new experiments, podcast schema

---

## What Shipped

### Deploy Scripts (run `bash deploy/deploy_v3.9.35.sh` to execute all)
1. **`deploy/apply_design_brief.py`** — Applies `body-signal`, breadcrumbs, `reading-path-v2`, `animations.js` to 11 data pages
2. **`deploy/patch_character_ring.py`** — Adds 7-segment pillar ring chart (SVG, animated, pillar-colored) to character page
3. **`deploy/add_experiments.py`** — Appends 6 new experiments from Product Board brainstorm to `experiment_library.json`
4. **`deploy/bump_version.py`** — Version bump v3.9.34 → v3.9.35
5. **`deploy/prepend_changelog.py`** — Prepend CHANGELOG entry
6. **`deploy/deploy_lifecycle_gaps.sh`** — Deploy MCP + site-api + achievements (from v3.9.33)

### New Config
- **`config/podcast_watchlist.json`** — 7 podcasts (Huberman, Attia, Patrick, Norton, Wolf, Chatterjee, Hill) with extraction prompt for future automated scanner Lambda

### Already In Production (confirmed this session)
- Challenge voting backend (`/api/challenge_vote`, `/api/challenge_follow`) — routes wired, rate-limited, DDB-backed
- Challenge voting frontend — vote buttons + follow overlay on `/challenges/` page
- Challenge catalog endpoint with merged vote counts

---

## Deploy Sequence

```bash
cd ~/Documents/Claude/life-platform

# Option A: Run everything at once
bash deploy/deploy_v3.9.35.sh

# Option B: Step by step
python3 deploy/bump_version.py
python3 deploy/prepend_changelog.py
python3 deploy/apply_design_brief.py --dry-run   # preview first
python3 deploy/apply_design_brief.py              # apply
python3 deploy/patch_character_ring.py
python3 deploy/add_experiments.py
python3 -m pytest tests/test_mcp_registry.py -v
bash deploy/deploy_lifecycle_gaps.sh
aws s3 cp config/experiment_library.json s3://matthew-life-platform/config/experiment_library.json --region us-west-2
aws s3 cp config/experiment_library.json s3://matthew-life-platform/site/config/experiment_library.json --region us-west-2
aws s3 cp config/podcast_watchlist.json s3://matthew-life-platform/config/podcast_watchlist.json --region us-west-2
aws s3 sync site/ s3://matthew-life-platform/site/ --region us-west-2 --exclude '.DS_Store'
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths '/*' --region us-east-1
python3 deploy/sync_doc_metadata.py --apply
git add -A && git commit -m "v3.9.35: Signal Doctrine Tier 1 rollout + arena voting + 6 experiments" && git push
```

---

## What's Queued

### Tier 2 — Ship by April 7th (Design Brief)
- [ ] Full nav restructure (5 sections: The Story / The Data / The Science / The Build / Follow)
- [ ] Sparkline mini-charts on live page vitals
- [ ] Number count-up animations (`data-count-up` attributes on vital values)
- [ ] Pillar accent colors per observatory page (`--obs-accent` wired to pillar tokens)
- [ ] Sleep + Glucose narrative intro sections (story mode above signal dashboard)
- [ ] Bottom nav label updates (Home → Story → Data → Science → Build)

### Tier 3 — Post-launch polish
- [ ] Section landing pages
- [ ] Data Explorer interactive charts
- [ ] Particle hero background (Canvas)
- [ ] Animated theme switch crossfade

### From v3.9.33 (still pending)
- [ ] SIMP-1 Phase 2 + ADR-025 cleanup (~April 13)

### Podcast Intelligence
- Phase 1 (conversational creation) works NOW — tell Claude podcast details, it creates catalog entries with metadata
- Phase 2 (automated scanner Lambda) — future sprint, config ready at `config/podcast_watchlist.json`

---

## Key Design Decisions

1. **`apply_design_brief.py` is idempotent** — checks for existing elements before adding. Safe to re-run.
2. **Reading order is linear**: Home → Story → About → Live → Character → Habits → Sleep → Glucose → Benchmarks → Explorer → Protocols → Supplements → Experiments → Challenges → Discoveries → Platform → Intelligence → Subscribe
3. **Pillar ring chart replaces static score number** in the trading card hero on character page. Shows all 7 pillar scores as colored ring segments with animated fill.
4. **Challenge voting was already fully implemented** (backend + frontend) in v3.9.33 but lifecycle gaps deploy hadn't been run.
5. **6 new experiments are all "backlog" status** — available in the library for activation but not auto-started.
6. **Podcast watchlist config is prep** — scanner Lambda is future work (~$0.40/month estimated).

---

## Files Created This Session

| File | Purpose |
|------|---------|
| `deploy/apply_design_brief.py` | Bulk-apply design brief to 11 pages |
| `deploy/patch_character_ring.py` | Character page pillar ring chart |
| `deploy/add_experiments.py` | Append 6 experiments to library |
| `deploy/deploy_v3.9.35.sh` | Master deploy orchestrator |
| `deploy/bump_version.py` | Version bump utility |
| `deploy/prepend_changelog.py` | Changelog prepend utility |
| `config/podcast_watchlist.json` | 7 podcasts for future scanner |
