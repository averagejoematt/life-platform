# Handover — v3.9.23

## Session: DISC-7 Annotations + 3 Observatory Pages + Product Board Strategy

### What shipped this session (v3.9.22 → v3.9.23)

**v3.9.23**: DISC-7 behavioral response annotations (full stack). Three new Observatory pages: Nutrition, Training, Inner Life. Three new API endpoints. Nav/footer updated. Product Board strategy sessions defined the 5-observatory Evidence architecture.

### DISC-7: Discovery Annotations

Full 4-layer implementation:
1. **DynamoDB**: New partition `USER#matthew#SOURCE#discovery_annotations` with SK `EVENT#{sha256(date|type|title)[:16]}`
2. **MCP**: `tool_annotate_discovery` (write) + `tool_get_discovery_annotations` (read) in `tools_social.py`
3. **Site API**: Section 6 in `handle_journey_timeline()` loads all annotations, builds lookup by event_key, merges into matching events
4. **Frontend**: CSS `.tl-event__annotation*` + JS renders "What I did" section with action tag, outcome, chat bubble icon

Config constant added: `ANNOTATIONS_PK` in `mcp/config.py`

### Observatory Pages — Functional V1

| Page | URL | Accent | API Endpoint | Data Sources |
|------|-----|--------|-------------|-------------|
| Nutrition | `/nutrition/` | Amber #f59e0b | `/api/nutrition_overview` | MacroFactor |
| Training | `/training/` | Crimson #ef4444 | `/api/training_overview` | Strava, Hevy, Whoop |
| Inner Life | `/mind/` | Violet #a78bfa | `/api/mind_overview` | state_of_mind, habit_scores, interactions, temptations, notion |

**Nutrition features**: Donut ring SVG (macro proportions), protein adherence gradient meter, area-fill 30d trend chart, N=1 rules with oversized watermark numbers, protocol sidebar, methodology footer.

**Training features**: Zone 2 animated ring gauge, activity type mosaic chips, 12-week stacked bar chart (total volume + Z2 overlay), centenarian decathlon framing.

**Inner Life features**: 3 signal cards (mind pillar, resist rate, journal entries), vice streak cards with bottom-fill animation, connection depth bars, willpower bars, mood valence chart with pos/neg zone gradient, "Building This" honest gap section for sparse journal data.

**Nav update**: `components.js` Evidence dropdown now has 7 items: Sleep, Glucose, Nutrition, Training, Inner Life, Benchmarks, Data Explorer. Footer updated to match.

### Product Board Sessions (3 rounds)

**Round 1**: Reviewed glucose + sleep pages. Board endorsed Training Observatory, dismissed Mind/Nutrition.
**Round 2**: Matthew challenged on Nutrition — board reversed, agreed MacroFactor + CGM crossover is as data-rich as Sleep/Glucose.
**Round 3**: Matthew challenged on Inner Life — board reversed again. Acknowledged 8 data streams (mood, journal sentiment, vice streaks, temptations, social connections, CBT patterns, PERMA). Agreed emotional health is the most differentiated content on the site.

**Final consensus**: 5 observatories. Mind, Relationships, Consistency stay as Character pillar drill-downs only. Hydration is a section within Nutrition. Body comp lives on Journey page.

### ⚠️ Critical Next-Session Priority: Visual Design Overhaul

**Matthew's feedback**: Pages are functional but visually don't match the quality he wants. The earlier homepage mockup session produced elite visual concepts. These pages feel like "stat-card walls" — too dense, too many numbers, not enough visual storytelling. 

**Next session approach**: Pick ONE page at a time. Use Visualizer to mock up 2-3 visual concepts for that specific domain. Get Matthew's approval on direction. Then build. This is how the homepage mockups were done and they were well-received.

**Design direction from Matthew**: "Elite visual artists, graphic designers. Not gimmicky, but not all dense numbers and text. More visuals, infographic, icons, organization. Each page should be an ode to its domain. Amazing web designers and graphic designers collaborating."

### Files Modified
- `mcp/config.py` — ANNOTATIONS_PK
- `mcp/tools_social.py` — annotate_discovery + get_discovery_annotations
- `mcp/registry.py` — 2 new tool registrations
- `lambdas/site_api_lambda.py` — DISC-7 annotation merge + 3 observatory handlers + 3 routes
- `site/discoveries/index.html` — annotation CSS + JS rendering
- `site/nutrition/index.html` — NEW (complete page)
- `site/training/index.html` — NEW (complete page)
- `site/mind/index.html` — NEW (complete page)
- `site/assets/js/components.js` — nav + footer Evidence section updated
- `site/assets/css/observatory.css` — EXISTS (pre-built shared styles, not currently used by new pages which are self-contained)
- `docs/CHANGELOG.md` — v3.9.23 entry

### Deploy Log
- `life-platform-mcp`: Deployed via manual zip (mcp_server.py + mcp_bridge.py + mcp/)
- `life-platform-site-api`: Deployed 2x via deploy_lambda.sh
- S3: 5 files synced (discoveries, nutrition, training, mind HTML + components.js)
- CloudFront: 3 invalidations covering all new paths + APIs

### Critical Reminders
- MCP Lambda is `life-platform-mcp` (NOT `life-platform-mcp-server`). Requires manual zip with full `mcp/` directory — `deploy_lambda.sh` can't handle it.
- The `observatory.css` shared stylesheet exists and is comprehensive but the 3 new pages use self-contained `<style>` blocks instead. Future consolidation opportunity.
- DISC-7 annotation key = `sha256(date|type|title)[:16]` — the MCP tool and site API must compute the same hash to match. Both use the same algorithm.
- `get_nutrition` MCP tool has a bug (`query_source_range() takes 3 positional args but 4 given`) — the site API `/api/nutrition_overview` works fine because it uses `_query_source()` directly, not the MCP tool.

### Next Steps
1. **Visual design overhaul** — one page at a time, Visualizer mockups first, then build. Nutrition or Inner Life recommended as first candidate.
2. **Test DISC-7** — add a real annotation to a timeline event to verify end-to-end
3. **Seed annotations** — annotate 3-5 key timeline events with behavioral responses
4. SIMP-1 Phase 2 + ADR-025 cleanup still targeted ~April 13
