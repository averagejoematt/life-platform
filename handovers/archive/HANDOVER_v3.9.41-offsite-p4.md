# Handover v3.9.41-offsite-p4 — Pre-Launch Offsite Part 4 Complete

**Date**: 2026-03-27
**Session focus**: Final offsite board meeting session (Part 4 of 4). Reviewed remaining 10 pages, completed all meta-discussions, produced final implementation roadmap.

---

## What Happened

### Pre-Launch Offsite Part 4 — All Pages Reviewed
- **Pages reviewed this session (Decisions 25–34):** Story, Platform, Intelligence, Cost, Methodology, Board, Tools, About, Home (re-review), Builders
- **Meta-discussions resolved:** Build Section Consolidation, Board Persona Compromise, Mobile Audit, Visual Design, AI Slop/Differentiation, General Feedback, Pre-Launch Questions
- **Total offsite output:** 34 decisions, 9 meta-discussions, ~548 recommendations across 30+ pages

### Critical Findings
1. **Board page has wrong personas** — 6 interactive chatbot personas don't match the 14-member BoD. Real public figures (James Clear, David Goggins) as interactive chatbots is a legal/ethical risk. APPROVED FIX: fictional BoD characters with "inspired by" attribution.
2. **Cost numbers inconsistent** — Platform says $3 Claude/$10 AWS/$13 total; Cost page says $8.50 Claude/~$3 AWS/~$11.50. Must reconcile from actual AWS bill.
3. **Stat counts vary across pages** — Lambdas: 48-52, MCP tools: 95-103. All must pull from `site_constants.js`.
4. **"365+ Days Tracked"** on Methodology is wrong at launch (~55 days). Must bind to `data-const`.
5. **Tools Matthew badges hidden on mobile** — `display: none` removes the differentiating feature for 70%+ of visitors.
6. **Dark mode body text fails WCAG AA** — `#7a9080` on `#080c0a` = 4.1:1 (needs 4.5:1).
7. **Site visual aesthetic is identifiably "Claude-built"** — neon green + monospace + `//` labels. APPROVED: change accent color + retire `//` labels with rollback capability.
8. **Builders page CIO audit** — 4 of 8 lessons need reframing to pass CTO/CIO professional review. "Senior Director" title survives in builder's note (removed from About in v3.9.41).

### Deliverables Produced
- `docs/OFFSITE_BUILD_PLAN_PART4.md` — Full build plan with all 10 decisions + 7 meta-discussions
- `docs/OFFSITE_FEATURE_LIST_PART4.md` — Detailed feature list with checkbox tasks for Claude Code

### No Code Shipped
This was a planning/review session. Platform remains at v3.9.41. All changes are captured in the feature list for implementation.

---

## What's Next (Priority Order)

### Critical Path for April 1 (12 items)
1. **28a** — Reconcile cost numbers across all pages (from actual AWS bill)
2. **29a** — Fix "365+ Days Tracked" → `data-const="journey.days_in"`
3. **30a/30b** — Board page persona replacement (highest effort)
4. **31b** — Fix Tools Matthew badges on mobile
5. **34b** — Reconcile all hardcoded stats sitewide → `site_constants.js`
6. **SLOP-1** — Change accent color (with rollback via token swap)
7. **SLOP-2** — Retire `//` comment labels from section headers
8. **PRE-5** — Fix dark mode text contrast (#7a9080 → ~#8aaa90)
9. **PRE-1** — Graceful degradation audit (all pages with public_stats.json 404)
10. **M-1** — Real-device mobile QA (iPhone + Android)
11. **PRE-9/PRE-10** — Verify sitemap.xml and robots.txt exist
12. **PRE-13** — Conscious data publication review (genome/lab sensitivity)

### Cross-Cutting (applies to many pages)
- **BRAND-1** — "The Measured Life" subscribe branding on ALL pages
- **BRAND-2** — `data-const` audit for all referenceable stats
- **VIS-1** — Subscribe buttons: coral CTA token, not amber
- **34-CIO-1 through 34-CIO-5** — Builders page lesson rewrites for CIO readiness

### Then Page-by-Page Must-Haves
- See `OFFSITE_FEATURE_LIST_PART4.md` for the full itemized list (~85 must-have items)

---

## Key Files
- Offsite Part 4 build plan: `docs/OFFSITE_BUILD_PLAN_PART4.md`
- Offsite Part 4 feature list: `docs/OFFSITE_FEATURE_LIST_PART4.md`
- Offsite Parts 1-2 feature list: `docs/OFFSITE_FEATURE_LIST.md`
- Offsite Part 3 build plan: `docs/OFFSITE_BUILD_PLAN_PART3.md`
- Offsite Part 3 feature list: `docs/OFFSITE_FEATURE_LIST_PART3.md`
- Board config (source of truth for personas): `config/board_of_directors.json` (S3)
- Design tokens (accent color changes): `site/assets/css/tokens.css`
- Site constants (stat bindings): `site/assets/js/site_constants.js`

---

## Guardrails (Never Violate)
1. No "Considering" section on Supplements (16q)
2. No downvotes on Experiments (19t)
3. One subscription at launch — "The Measured Life" (22-S1)
4. No reader streaks/habits at launch (22-S4)
5. Real-expert personas in editorial contexts only, never interactive Q&A (30c)
