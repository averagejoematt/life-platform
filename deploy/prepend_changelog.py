#!/usr/bin/env python3
"""Prepend v3.9.35 changelog entry"""
import os

CHANGELOG = os.path.expanduser("~/Documents/Claude/life-platform/docs/CHANGELOG.md")

ENTRY = """## v3.9.35 — 2026-03-26: Signal Doctrine Tier 1 Rollout + Arena Voting + Experiments

### Summary
Rolled out Signal Doctrine design language to all 11 remaining data pages (body-signal typography, breadcrumbs, reading-path-v2 navigation, animations.js). Added 7-segment pillar ring chart to Character page. Deployed lifecycle gaps (overdue detection, catalog_id, challenge badges). Added 6 new experiments from Product Board brainstorm. Created podcast intelligence pipeline config. Challenge voting + follow infrastructure confirmed deployed.

### What Shipped
- **Design Brief Tier 1 rollout**: `body-signal` class, breadcrumbs, reading-path-v2, animations.js applied to: sleep, glucose, supplements, habits, benchmarks, protocols, platform, intelligence, challenges, experiments, explorer (11 pages)
- **Character pillar ring chart**: 7-segment SVG ring in pillar colors with animated fill on load, replacing the static composite score number
- **Lifecycle gaps deployed**: overdue detection in `list_challenges`, `catalog_id` param in `create_challenge`, 5 new challenge achievement badges (Arena Debut/Regular/Veteran/Legend/Flawless)
- **6 new experiments**: sauna-2x-week, cold-plunge-3x, zone2-150min, morning-sunlight-blue-blockers, TRF-12pm-8pm, eliminate-alcohol-30d
- **Podcast intelligence config**: `config/podcast_watchlist.json` with 7 podcasts (Huberman, Attia, Patrick, Norton, Wolf, Chatterjee, Hill) + extraction prompt for future automated scanner
- **Challenge voting confirmed**: Backend (`/api/challenge_vote`, `/api/challenge_follow`) + frontend vote buttons already in production from v3.9.33

### Deploy Scripts Created
| Script | Purpose |
|--------|---------|
| `deploy/apply_design_brief.py` | Apply body-signal + breadcrumbs + reading paths + animations.js to 11 pages |
| `deploy/patch_character_ring.py` | Add 7-segment pillar ring chart to character page |
| `deploy/add_experiments.py` | Append 6 new experiments to library |
| `deploy/deploy_v3.9.35.sh` | Master deploy orchestrator (all steps in order) |
| `deploy/bump_version.py` | Version bump in sync_doc_metadata.py |

### Files Modified
| File | Change |
|------|--------|
| `site/{sleep,glucose,supplements,habits,benchmarks,protocols,platform,intelligence,challenges,experiments,explorer}/index.html` | body-signal + breadcrumb + reading-path-v2 + animations.js |
| `site/character/index.html` | 7-segment pillar ring chart (CSS + JS + mount point) |
| `config/experiment_library.json` | +6 experiments (58 total) |
| `config/podcast_watchlist.json` | NEW — 7 podcasts for future scanner |
| `deploy/sync_doc_metadata.py` | Version bump v3.9.34 → v3.9.35 |

---

"""

with open(CHANGELOG) as f:
    existing = f.read()

with open(CHANGELOG, "w") as f:
    f.write(ENTRY + existing)

print("✓ Changelog entry prepended for v3.9.35")
