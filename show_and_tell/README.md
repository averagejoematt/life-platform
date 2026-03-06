# Show & Tell PDF Pipeline

Generates the Life Platform Show & Tell PDF with automated screenshot capture, redaction, and data-driven content.

## First-Time Setup (once only)

```bash
cd /Users/matthewwalker/Documents/Claude/life-platform/show_and_tell
bash setup.sh
```

Then add your dashboard cookie (see setup.sh output for instructions).

---

## Quick Start (every time you need a PDF)

```bash
cd show_and_tell/
./run.sh --open
```

That's it. The script activates the venv, updates stats from live docs, runs automated screenshots, pauses for manual ones, redacts, and builds the PDF.

---

## File Map

```
show_and_tell/
├── manifest.json          ← UPDATE THIS: version, stats, roadmap items
├── update_manifest.py     ← Auto-reads manifest values from live docs
├── capture_screenshots.py ← Playwright automation for dashboard/buddy page
├── redact_screenshots.py  ← Applies all redaction rules (documented inside)
├── build_pdf.py           ← Orchestrates manifest → PDF build
├── build_v4.py            ← Core ReportLab PDF engine (copy from root)
├── run.sh                 ← Full pipeline in one command
├── screenshots/           ← Raw, unredacted screenshots go here
├── processed/             ← Redacted screenshots (used by build)
└── output/                ← Final PDFs land here
```

---

## What Changes Each Time

### Always auto-updated by `update_manifest.py`:
- Version number (from HANDOVER_LATEST.md)
- Incident count (from INCIDENT_LOG.md row count)
- Handover file count (from handovers/ directory)
- Changelog entry count (from CHANGELOG.md)
- MCP tool count (from MCP_TOOL_CATALOG.md)
- Git object count (from `git count-objects`)

### Manual updates in `manifest.json`:
- New roadmap items
- New board personas
- Cost per month (if changed)
- Lambda count (if changed)

### Screenshots — automated (Playwright):
- Dashboard main view
- Dashboard clinical tab
- Dashboard + character sheet
- Character radar chart
- Buddy page views

### Screenshots — manual (CleanShot X, @2x, 880px wide):
- Daily Brief email (Mail.app)
- Brittany email (Mail.app)
- Weekly Plate email (Mail.app)
- Elena Voss blog (browser)
- CloudWatch alarm (AWS Console)

---

## Redaction Rules

All rules are documented in `redact_screenshots.py` with:
- Which screenshot they apply to
- What region (as image fractions, so resolution-independent)
- **Why** the rule exists (what sensitive info it covers)
- `enabled: True/False` toggle

Rules currently active:
| Screenshot | What's redacted | Why |
|---|---|---|
| shot02_daily_brief | Habit streak line | "No marijuana / No alcohol" visible |
| shot05_habits | No alcohol, No marijuana, No porn rows + body skincare weight mention | Private habits |
| shot06_cgm_board | Weight Phase Tracker tile | Exact body weight in lbs |
| shot16_dashboard | Weight tile | Exact body weight in lbs |
| shot18_dashboard_character | Weight tile | Same as shot16 |
| shot07_brittany1 | Coach Rodriguez paragraph from "What's driving it" onward | Emotionally vulnerable content |

---

## First Time Setup

```bash
# Just run the setup script — it handles everything
bash setup.sh
```

The setup script creates a `.venv` in the show_and_tell folder, installs playwright/pillow/reportlab into it, installs Chromium, and walks you through the cookie step. You never touch pip3 directly.

---

## Updating the PDF Content

The build script (`build_v4.py`) contains all the section content. Most stats flow from `manifest.json`. For content changes:

- **Stats / numbers**: edit `manifest.json`
- **New feature descriptions**: edit the relevant section function in `build_v4.py`
- **New section**: add a `def new_section(s):` function + wire into the `story +=` list at the bottom
- **New redaction rule**: add a rule dict to `RULES` in `redact_screenshots.py`

---

## Estimated Time Per Run (after first setup)

| Step | Time |
|------|------|
| `update_manifest.py` | ~5 seconds |
| `capture_screenshots.py` (automated) | ~2 minutes |
| Manual screenshots (email + blog) | ~15 minutes |
| `redact_screenshots.py` | ~10 seconds |
| `build_pdf.py` | ~20 seconds |
| **Total** | **~20 minutes** |
