→ See handovers/HANDOVER_v3.8.0.md

This session (2026-03-21, session 2 — Strategy):
- CEO manual audit of all 20+ live pages (63 findings)
- Comprehensive website strategy produced: docs/WEBSITE_STRATEGY.md
- Audit findings archived: docs/audits/AUDIT_2026-03-21_website.md
- 49-task backlog (P0 through P4), sequenced and sized
- WEBSITE_ROADMAP.md remains valid as technical reference (API specs, deploy patterns, file structure)
- WEBSITE_STRATEGY.md is the new master plan (what + why + order)

Next session entry point (Claude Code):
1. Read docs/WEBSITE_STRATEGY.md — this is the master plan
2. Read docs/WEBSITE_ROADMAP.md — this has API specs and deploy patterns
3. Start Phase 0: Tasks 1-12 + 42-46 (data fixes, parameterization, bug verification)
4. Sprint 6 Tier 0 remaining: R17-02 (privacy), R17-04 (API key), R17-07 (config cleanup)
5. Fix public_stats.json — weight_lbs is null (daily_brief_lambda.py issue)

Key context for Claude Code:
- WEBSITE_STRATEGY.md has 49 tasks in 5 phases (P0-P4)
- Phase 0 = fix broken data/bugs BEFORE any new features
- Phase 1 = restructure IA (5-section nav, page merges/renames)
- Phase 2 = content depth (expand /live/, build /habits/, rebuild deep-dives)
- Phase 3 = chronicle engine (rebrand journal, fix auto-publish, preview flow)
- Phase 4 = engagement (badges, return-visit hooks)
- WEBSITE_ROADMAP.md has technical details: API endpoints needed, file structure, deploy commands, content filter integration
- 30 HTML pages already patched with Sprint 8 nav (hamburger + bottom + footer)
- Content safety filter active (blocks porn/marijuana from public surfaces)
