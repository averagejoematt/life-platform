# Handover v3.9.34 — Signal Doctrine Design Brief Implementation

**Date**: 2026-03-26
**Session focus**: Product Board design brief + CSS/visual foundation for April 1st launch

---

## What Shipped

### Deployed to Production (3 deploys)
1. **Foundation CSS** — `tokens.css` complete rewrite + `base.css` with 15 new component blocks. Affects every page via cascade.
2. **Inter font** — Self-hosted 400/500/600 weights, `@font-face` declarations added.
3. **noise.svg** — Tileable SVG noise texture overlay (dark mode: 1.8% opacity overlay blend, light mode: 2.5% multiply).
4. **animations.js** — Shared scroll reveal observer, number count-up, signal bar fills, back-to-top. Vanilla JS, respects `prefers-reduced-motion`.
5. **8 page-level updates** — Homepage (coral CTA + reading path), Story (body-story + reading path), About (body-story + reading path), Chronicle (body-story), Live (reading path), Character (reading path), Discoveries (reading path), Subscribe (coral CTA).

### Design Brief
Full Product Board brief at `docs/briefs/BRIEF_2026-03-26_design_brief.md` — 8 parts covering diagnosis, visual direction ("Signal Doctrine"), typography, color, dark/light mode, motion, navigation, page-specific upgrades, CSS checklist, board member statements, priority matrix.

---

## What's Queued (Remaining Design Brief Items)

### Tier 1 — Ship by April 1st
- [ ] `body-signal` class (Inter 15px) on data pages: `/sleep/`, `/glucose/`, `/supplements/`, `/habits/`, `/benchmarks/`, `/protocols/`, `/platform/`, `/intelligence/`, `/challenges/`, `/experiments/`, `/explorer/`
- [ ] Reading paths on remaining ~15 pages (page sequence: Story → About → Live → Character → Habits → Protocols → Experiments → Discoveries → Sleep → Glucose → Platform → Subscribe)
- [ ] `animations.js` script tag on remaining pages
- [ ] Character page pillar ring chart (SVG — 7-segment ring in pillar colors, animated fill on load)
- [ ] Pillar border colors on character page cards (`.pillar-border--*` classes ready in base.css)
- [ ] Bottom nav label updates (Home → Story → Data → Science → Build) across all pages
- [ ] Breadcrumbs on all sub-pages (`.breadcrumb` component ready in base.css)

### Tier 2 — Ship by April 7th
- [ ] Full nav restructure (5 sections: The Story / The Data / The Science / The Build / Follow)
- [ ] Sparkline mini-charts on live page vitals
- [ ] Number count-up animations (data-count-up attributes on vital values)
- [ ] Pillar accent colors per observatory page (`--obs-accent` wired to pillar tokens)
- [ ] Sleep + Glucose narrative intro sections (story mode above signal dashboard)

### Tier 3 — Post-launch polish
- [ ] Section landing pages
- [ ] Data Explorer interactive charts
- [ ] Particle hero background (Canvas)
- [ ] Animated theme switch crossfade

---

## Also Still Pending from v3.9.33

- [ ] Deploy lifecycle gaps: `python3 -m pytest tests/test_mcp_registry.py -v && bash deploy/deploy_lifecycle_gaps.sh`
- [ ] Challenge voting (backend + frontend) — spec'd in `docs/briefs/BRIEF_2026-03-26_arena_lab_v2.md`
- [ ] 6 new experiments → `experiment_library.json`
- [ ] Podcast intelligence schema extension
- [ ] SIMP-1 Phase 2 + ADR-025 cleanup (~April 13)

---

## Key Design Decisions

1. **Two typography modes**: `.body-signal` (Inter 15px, tight) for data pages, `.body-story` (Lora 17px, generous) for narrative pages. Space Mono stays for labels, nav, data values.
2. **Coral CTA**: `--c-coral-500: #ff6b6b` (dark), `--c-coral-500: #cc4444` (light). Used for subscribe/follow/conversion buttons. Green = data, coral = action.
3. **Light mode warm-up**: Background shifted from cool green `#f4f7f5` to warm `#fafaf8`. Cards get soft shadows. Accent brightened to `#008f5f`.
4. **Noise texture**: SVG-based (resolution-independent), not PNG. `mix-blend-mode: overlay` in dark, `multiply` in light. Disabled on `prefers-reduced-motion`.
5. **Reading path**: `.reading-path-v2` component creates linear book-like flow through the site. Prev/next links with Bebas Neue titles.
6. **Board tension resolved**: Typography split limited to story + chronicle pages for April 1st (Ava's compromise). Full Inter rollout for signal pages in April 7th sprint. Nav restructure deferred to April 7th (Mara's call). Coral CTA ships as experiment via `--c-cta` variable.

---

## Files Modified This Session

| File | Change |
|------|--------|
| `site/assets/css/tokens.css` | Complete rewrite — DEPLOYED |
| `site/assets/css/base.css` | Inter @font-face + 15 DB components — DEPLOYED |
| `site/assets/images/noise.svg` | NEW — DEPLOYED |
| `site/assets/js/animations.js` | NEW — DEPLOYED |
| `site/assets/fonts/inter-{400,500,600}.woff2` | NEW — DEPLOYED |
| `site/index.html` | Coral CTA, reading path — DEPLOYED |
| `site/story/index.html` | body-story, reading path — DEPLOYED |
| `site/about/index.html` | body-story, reading path — DEPLOYED |
| `site/chronicle/index.html` | body-story, animations.js — DEPLOYED |
| `site/live/index.html` | Reading path, animations.js — DEPLOYED |
| `site/character/index.html` | Reading path, animations.js — DEPLOYED |
| `site/discoveries/index.html` | Reading path, animations.js — DEPLOYED |
| `site/subscribe/index.html` | Coral CTA button — DEPLOYED |
| `deploy/download_inter_fonts.sh` | NEW — font download script |
| `deploy/sync_doc_metadata.py` | Version bump v3.9.33 → v3.9.34 |
| `docs/briefs/BRIEF_2026-03-26_design_brief.md` | NEW — full Product Board design brief |
| `docs/CHANGELOG.md` | v3.9.34 entry |

---

## Immediate Next Steps

1. **Git commit**: `git add -A && git commit -m "v3.9.34: Signal Doctrine — design brief implementation" && git push`
2. **Continue Tier 1**: Add `body-signal` + reading paths + animations.js to remaining ~15 pages
3. **Character ring chart**: SVG pillar visualization (pillar colors ready in tokens)
4. **Deploy lifecycle gaps from v3.9.33**: `bash deploy/deploy_lifecycle_gaps.sh`
