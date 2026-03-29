# Handover — v3.9.13 (2026-03-25)

> Prior: handovers/HANDOVER_v3.9.12.md

## SESSION SUMMARY
Benchmarks page completely redesigned from a pure Centenarian Decathlon lift tracker into "The Standards" — a 6-domain, 27-benchmark research reference library covering Physical, Sleep, Cognitive, Emotional, Social Connection, and Behavioral Discipline. Product Board convened ground-up to define purpose, domain structure, and visual identity. Three iterations shipped: base page, letter grades, and trend indicators.

## WHAT CHANGED

### site/benchmarks/index.html (COMPLETE REWRITE — "The Standards")

**Structural overhaul:**
- Renamed page from "Centenarian Decathlon" → "The Standards"
- Expanded from 1 domain (physical lifts) to 6 domains, 27 benchmarks
- Each benchmark has: research target, evidence rating (●●●/●●/●), letter grade (A-F), trend arrow (▲/▶/▼), progress bar, "why it matters" explainer, source citation
- Domains: Physical Capacity (6), Sleep & Recovery (5), Cognitive & Intellectual (4), Emotional & Psychological (4), Social Connection (4), Behavioral Discipline (4)
- Interactive "Check Yourself Against the Research" self-assessment at bottom (6 questions, client-side only)
- Evidence legend + grade scale + trend arrow legend in header

**Unique visual per domain:**
- Physical: SVG mini arc gauges for deadlift/squat/VO2
- Sleep: Architecture bars (deep/REM/light) with research target markers
- Cognitive: Animated bookshelf visualization (read vs unread spines)
- Emotional: Sentiment waveform SVG (trending upward)
- Social: Dunbar concentric rings with scattered dots per layer
- Discipline: GitHub-style consistency heatmap (7×26 grid)

**Data integration:**
- Fetches from `/api/vitals` (sleep hrs, HRV, RHR, weight)
- Fetches from `/api/habits` (T0 completion rate from last 7 days)
- Fetches from `/api/vice_streaks` (shortest current streak)
- Grade badges auto-compute from bar fill percentage
- Trend arrows ready for `/api/benchmark_trends` endpoint (graceful degradation — hidden when endpoint doesn't exist yet)

**Research citations included:**
- Mandsager et al. (JAMA 2018), Leong et al. (Lancet 2015), Zhang et al. (CMAJ 2016)
- Cappuccio et al. (Sleep 2010), Xie et al. (Science 2013), Boyce et al. (Science 2016)
- Bavishi et al. (Social Science & Medicine 2016), Pennebaker (1986+)
- Holt-Lunstad et al. (PLOS Medicine 2010), Dunbar (2010)
- Lally et al. (European J Social Psych 2010), Volkow et al. (2004)
- Emmons & McCullough (JPSP 2003), Epel et al. (PNAS 2004), WHO-5 Index

**No new API endpoints** — uses existing vitals, habits, vice_streaks. Trend endpoint designed but not yet built.

### Bug fixes across 3 iterations
1. JS was reading fields from `/api/character` that don't exist (character only returns pillar scores, not raw metrics) — remapped to `/api/vitals` field names
2. Double `.json()` call on character response would have consumed the stream twice
3. `overflow: hidden` on bench-card was clipping grade badges

## DEPLOYED
```bash
# 4 deploys this session (base → grades → trends → data fix)
aws s3 cp site/benchmarks/index.html s3://matthew-life-platform/site/benchmarks/index.html --content-type "text/html"
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/benchmarks/*"
```

## PRODUCT BOARD RATIONALE (for future reference)

### Key decisions:
- **Raj**: "This page answers 'what should a human be measuring?' — it's educational first, Matthew's data second"
- **Lena**: Evidence gradient (●●● to ●) prevents pretending social connection has the same evidence base as VO2 max
- **Sofia**: Renamed to "The Standards" — "Benchmarks" is a gym word, this is about the full human
- **Tyrell**: Each domain needs unique visual treatment (not 27 identical card types)
- **Jordan**: Self-assessment is the shareability play — visitors check their own numbers against research
- **Mara**: Distinct from Character Sheet — Character = gamification/RPG, Standards = research library

### Distinction from Character page:
- Character = levels, XP, pillar scores, badges, gamification language
- Standards = research targets, citations, evidence ratings, no scores — just "where does science say good is?"
- Character *consumes* these benchmarks as inputs; Standards stands alone as reference

## LEARNINGS
- `Filesystem:write_file` requires `content` parameter (not `contents`) — tool_search needed first
- str_replace tool requires file to be on Claude's container — use copy_file_user_to_claude first for Mac files
- Site API field mapping must be verified against actual endpoint responses, not assumed

## PENDING / CARRY FORWARD
- **`/api/benchmark_trends` endpoint**: Frontend is ready; needs backend handler in site_api_lambda.py that compares 7-day avg now vs 30 days ago for each metric
- **Sleep staging data**: Deep sleep %, REM %, sleep consistency not in `/api/vitals` — Whoop has this data, needs endpoint expansion
- **Strength tracking**: No lift data in any public endpoint (deadlift, squat, grip, dead hang, VO2 max current values)
- **Social metrics**: Social dashboard is MCP-only — needs site API exposure
- **Cognitive/Emotional metrics**: Books, learning hours, gratitude, wellbeing — not tracked yet
- **Nav label**: components.js still says "Benchmarks" in Evidence dropdown — consider renaming to "The Standards"
- **CHANGELOG update**: v3.9.13 entry prepended (done this session)
- **sync_doc_metadata.py**: Run `--apply` after changelog update
- **WEBSITE_REDESIGN_SPEC.md**: Note benchmarks overhaul
- **Git commit**: `git add -A && git commit -m "v3.9.13: Benchmarks → The Standards — 6-domain redesign" && git push`
- **Supplements page**: Was deployed successfully (confirmed from v3.9.12 carry-forward)
- **CHRON-3/4**: Chronicle generation fix + approval workflow
- **G-8**: Privacy page email confirmation
- **Withings OAuth**: No weight data since Mar 7
- **SIMP-1 Phase 2 + ADR-025 cleanup**: ~Apr 13
