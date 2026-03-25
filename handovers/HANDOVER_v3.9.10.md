# Handover — v3.9.10 (2026-03-24)

> Prior: handovers/HANDOVER_v3.9.9.md

## SESSION SUMMARY
Joint Product Board × Personal Board navigation architecture review (4 rounds, 22 participants, 20-0-1 vote). Restructured the website from 5 nav sections to 6, with multiple page renames and a new grouped dropdown pattern. Two files changed — `components.js` (rewritten) and `base.css` (3 CSS additions + footer grid fix). All 54 pages pick up changes automatically via the component injection system.

## WHAT CHANGED

### Navigation restructure (components.js v2.0.0):

**Before (5 sections):**
```
The Story | The Data | The Science | The Build | Follow
```

**After (6 sections):**
```
Story | Pulse | Evidence | Method | Build | Follow   [Subscribe →]
```

| Section | Children |
|---------|----------|
| **Story** | Home, My Story, The Mission |
| **Pulse** | Today, Character, Habits, Accountability, Milestones |
| **Evidence** | Sleep, Glucose, Benchmarks, Data Explorer |
| **Method** | *What I Do:* Protocols, Supplements · *What I Tested:* Active Tests, Discoveries |
| **Build** | Platform, The AI, AI Board, Cost, Methodology, Tools |
| **Follow** | Chronicle, Weekly Snapshots, Subscribe, Ask the Data |

### Renames applied:
- Live → Today
- Character Sheet → Character
- Explorer → Data Explorer
- Intelligence → The AI
- Experiments → Active Tests
- Weekly Journal → Chronicle
- "The" prefix dropped from all section labels

### Key moves:
- Supplements: Science → Method (intervention, not measurement)
- Milestones: Data → Pulse (journey progress, not evidence)
- Sleep/Glucose/Benchmarks: Data → Evidence (case studies)

### CSS additions (base.css):
- `.nav__dropdown-heading` — sub-header in desktop dropdown
- `.nav__dropdown-divider` — divider between dropdown groups
- `.nav-overlay__subheading` — sub-header in mobile overlay
- Footer grid: 4 columns → 6 columns

## NOT DEPLOYED
Files are committed but NOT synced to S3/CloudFront. To deploy:
```bash
aws s3 sync site/ s3://matthew-life-platform/site/ --delete
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/assets/js/components.js" "/assets/css/base.css"
```

## BOARD RATIONALE (for future reference)
- **6 sections, not 7**: Cognitive load research (Attia), nav bar width (Tyrell), mobile hamburger depth (Sofia)
- **"Pulse" for status pages**: Heartbeat metaphor, health-coded, 1 syllable
- **"Evidence" for deep-dives**: Answers trust question "is it working?", gives case studies gravitas (Attia's trust framework)
- **"Method" for protocols/tests**: Avoids "Experiment within The Experiment" echo (Huberman), captures full scientific method cycle
- **Supplements with Protocols**: Supplements are deliberate interventions, not passive measurements (Rhonda Patrick)
- **30-day time-box**: Ship now, watch visitor behavior, rename if data shows confusion (Conti)

## PENDING / CARRY FORWARD
- **ADR-034 page migration**: Foundation committed in v3.9.9, pages NOT yet migrated. See HANDOVER_v3.9.9.md for batch plan.
- **Nav reading paths in nav.js**: `READING_PATHS` object still uses old page names ("Weekly Journal", etc.). Cosmetic only — these are link labels in the "Read Next" CTA, not URLs. Should be updated when convenient.
- **WEBSITE_STRATEGY.md + WEBSITE_REDESIGN_SPEC.md**: Still reference old 5-section nav. Should be updated to reflect the new 6-section structure when next editing these docs.
- **CHRON-3/4**: Chronicle generation fix + approval workflow
- **G-8**: Privacy page email confirmation (Matthew)
- **SIMP-1 Phase 2 + ADR-025 cleanup**: ~Apr 13
- **Withings OAuth**: No weight data since Mar 7
