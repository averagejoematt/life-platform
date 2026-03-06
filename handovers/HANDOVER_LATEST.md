# Handover — 2026-03-06 — Show & Tell PDF + Pipeline

## Current Version
v2.80.1 (no code changes this session — PDF/pipeline work only)

## What Was Done This Session

### 1. Show & Tell PDF (v5 — iterative build)
Built a full multi-section PDF presentation for an internal show-and-tell with boss/peers/delegates. The PDF is at:
`show_and_tell/output/LifePlatform_ShowAndTell_LATEST.pdf`

**Content changes from previous versions:**
- Cover hook rewritten: removed "felt terrible each morning" framing → "19 apps, none talking to each other"
- The Story page: removed 120lb personal weight loss narrative → reframed as data aggregation problem
- Stats strip: removed "120 lbs lost" → replaced with neutral platform stats
- Elena Voss section: removed blog URL → added voice section mention
- Met Market → "local supermarket" everywhere
- Accountability section: expanded with friends dashboard (green/yellow/red signals)
- Reward examples added: weekend away, spa day, new gear, dinner out, concert tickets
- Roadmap: added LLM Failover Router (Anthropic down → OpenAI fallback)
- New Section 12 — Documentation System (changelog, handovers, incident log, RCA)
- Source-of-truth callout added to Data Model section
- Board of Directors box rebuilt from canvas drawString → Paragraph Table (wraps properly)
- Tier progression diagram regenerated with consistent pixel art avatars (brown hair, dark suit)
- Removed "As the person responsible for rolling out Claude..." personal paragraph

**Privacy redactions applied to screenshots:**
- shot02_daily_brief: habit streaks line (No marijuana, No alcohol) → "✓ Habit streaks tracked"
- shot05_habits: No alcohol, No marijuana, No porn rows; body skincare weight mention; walk 5k weight subtext
- shot06_cgm_board: Weight Phase Tracker tile (290.3 lbs, 302 start, 185 goal, target 250)
- shot16_dashboard + shot18_dashboard_character: weight tile numbers
- shot07_brittany1: Coach Rodriguez "What's driving it" paragraph (emotionally vulnerable content)

### 2. Show & Tell Pipeline (`show_and_tell/`)
Built a full automated pipeline so future PDFs take ~20 min instead of a full day.

**Files created:**
```
show_and_tell/
├── README.md               ← full documentation
├── setup.sh                ← one-time venv setup (handles macOS/Homebrew correctly)
├── run.sh                  ← main pipeline: ./run.sh --open
├── manifest.json           ← all version-specific stats (edit before each run)
├── update_manifest.py      ← auto-reads version/incidents/handovers from live docs
├── capture_screenshots.py  ← Playwright automation for dashboard + buddy page
├── redact_screenshots.py   ← documented redaction rules (fractional coords, resolution-independent)
├── build_pdf.py            ← patches manifest values into build script, runs build
├── build_v4.py             ← core ReportLab PDF engine (copy here from root)
├── tier_progression.png    ← generated tier diagram (keep here)
├── arch_diagram.png        ← generated architecture diagram (keep here)
├── screenshots/            ← raw unredacted screenshots go here
├── processed/              ← redacted screenshots (used by build)
└── output/                 ← final PDFs land here
```

**Pipeline flags:**
- `./run.sh --open`                              — full pipeline
- `./run.sh --skip-shots --open`                 — skip screenshot capture, still redact
- `./run.sh --skip-shots --skip-redact --open`   — use existing processed/ screenshots directly

**What auto-updates each run (update_manifest.py reads live docs):**
- Version (from HANDOVER_LATEST.md)
- Incident count (from INCIDENT_LOG.md row count)
- Handover count (from handovers/ directory)
- Changelog entry count (from CHANGELOG.md)
- MCP tool count (from MCP_TOOL_CATALOG.md)
- Git object count (from `git count-objects`)

**What needs manual update in manifest.json before each run:**
- roadmap_near_term array (items will have shipped)
- Lambda count if changed
- Cost per month if changed

## Next Major Features (unchanged from last session)
1. Reward seeding (prerequisite for Brittany email fixes)
2. Brittany weekly email debugging (deployed but Board sections not rendering)
3. Google Calendar integration
4. Character Sheet Phase 4

## Open Items
- BRITTANY_EMAIL env var: not yet set on brittany-weekly-email Lambda
- Brittany email Board sections not rendering — CloudWatch logs needed to diagnose

## Key Files
- Build script: `show_and_tell/build_v4.py`
- Pipeline entry: `show_and_tell/run.sh`
- Manifest: `show_and_tell/manifest.json`
- Latest PDF: `show_and_tell/output/LifePlatform_ShowAndTell_LATEST.pdf`
