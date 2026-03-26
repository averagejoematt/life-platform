# Handover — v3.9.26

## Session: April 1 Launch Reframe — Product Board Emergency Session

### What shipped this session (v3.9.25 → v3.9.26)

**v3.9.26**: Full April 1 launch reframe. Product Board convened and unanimously endorsed reframing all pre-April data as the "testing window" with April 1 as Day 1 of the public experiment.

#### 1. site_constants.js updates (Item 1 — done in prior cut-off session)
- `experiment_start: '2026-04-01'` added to journey block
- `phase` changed from `'Ignition'` to `'Launch'`
- `hero_tagline`, `hero_copy`, `cta_sub` rewritten for April 1 narrative
- Meta descriptions updated across all pages

#### 2. countdown.js — Global Day N counter (Item 2 — done in prior session)
- New `/assets/js/countdown.js` component
- Before April 1: shows "T-{N}" countdown in nav badge, "Experiment begins in N days" in counter elements
- After April 1: shows "DAY {N}" in nav badge, Day N in counter elements
- Exposes `window.AMJ_EXPERIMENT` global for other scripts
- Nav badge injected automatically via `.nav-day-badge` class
- Counter styles added to base.css (`.experiment-counter`, `.nav-day-badge`)

#### 3. Homepage hero rewrite (Item 3 — done in prior session)
- Central experiment counter added (`.experiment-counter` div)
- "Day 1. For real this time." headline
- Prequel context banner (auto-hides after April 1 via JS)
- Updated meta tags for April 1 launch messaging
- Subscribe label changed to "Follow from Day 1"
- "Days on Journey" chip now uses experiment counter

#### 4. Chronicle archive reframe (Item 4)
- All existing episodes relabeled as "Prequel" series
- Week numbering: Prologue, Week −5 through Week −1
- Phase divider added: "PREQUEL — The Testing Window · Feb – Mar 2026"
- "Coming soon" placeholder replaced with April 1 Week 1 teaser
- Both `chronicle/posts.json` and `journal/posts.json` rewritten with prequel framing and `phase: "prequel"` field
- countdown.js added to archive page scripts

#### 5. Week −1: "The Interview" chronicle (Item 5)
- New file: `site/journal/posts/week-minus-1/index.html`
- Elena Voss's first direct conversation with Matthew
- Q&A format with speaker-labeled dialogue blocks
- Covers: the relapse (weed, DoorDash, porn), the gap between sickness and return, the "testing window" reframe, what April 1 means, the accountability mechanism
- Key quote: "I have nineteen data sources measuring my body and a journalist documenting my behavior. Dishonesty isn't really an option at this point."
- Reading progress bar, prequel series label, post navigation

#### 6. Baseline snapshot MCP tool (Item 6)
- New function: `tool_capture_baseline()` in `mcp/tools_memory.py`
- `baseline_snapshot` added to `VALID_CATEGORIES`
- Captures 8 domains: weight/body comp, blood pressure, HRV/recovery, Character Sheet, habits, vices, glucose, nutrition
- Safety: won't overwrite existing snapshot unless `force=true`
- Registered in `mcp/registry.py` as `capture_baseline`
- Designed to run April 1 morning to create permanent Day 1 anchor

### Files Modified
- `site/assets/js/site_constants.js` — experiment_start, phase, copy (prior session)
- `site/assets/js/countdown.js` — New file (prior session)
- `site/assets/css/base.css` — Counter + badge styles (prior session)
- `site/index.html` — Hero rewrite (prior session)
- `site/chronicle/archive/index.html` — Prequel reframe + countdown.js
- `site/chronicle/posts.json` — Prequel episode manifest
- `site/journal/posts.json` — Prequel episode manifest (mirror)
- `site/journal/posts/week-minus-1/index.html` — New chronicle episode
- `mcp/tools_memory.py` — baseline_snapshot category + capture function
- `mcp/registry.py` — capture_baseline tool registration
- `deploy/sync_doc_metadata.py` — Version bump v3.9.25 → v3.9.26

### Deploy Required
```bash
# 1. Run MCP registry test first
python3 -m pytest tests/test_mcp_registry.py -v

# 2. Sync doc metadata
python3 deploy/sync_doc_metadata.py --apply

# 3. Deploy site files to S3
aws s3 sync site/ s3://matthew-life-platform/site/ --delete --exclude ".DS_Store"

# 4. Deploy MCP Lambda (has new tool)
bash deploy/deploy_lambda.sh life-platform-mcp-server mcp_server.py

# 5. CloudFront invalidation
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/*"
```

### Day 1 Checklist (April 1, 2026)
1. Verify all data sources are connected and flowing
2. Run `capture_baseline` MCP tool (no args needed — defaults to today, label "day_1")
3. Verify homepage shows "DAY 1" instead of countdown
4. Verify prequel banner auto-hides
5. First post-launch chronicle drops Wednesday April 8 as "Week 1"

### Pending Items
- `get_nutrition` MCP tool positional args bug (site API unaffected)
- `observatory.css` consolidation opportunity
- SIMP-1 Phase 2 + ADR-025 cleanup targeted ~April 13
- countdown.js not yet added to all observatory/non-homepage pages (only homepage + archive)
