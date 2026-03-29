# Handover — v3.9.17 (2026-03-25)

## Session Summary
**Pulse Redesign — Sprint 1 + Sprint 2** — Product Board reviewed `/live/` page and identified the fundamental problem: it conflates "am I having a good day?" with "how much weight have I lost total?" Built the complete Pulse data pipeline (Sprint 1) and redesigned glyph page (Sprint 2) in a single session. 8 symbolic SVG glyph icons, 3-layer progressive disclosure architecture, Elena Voss narrative voice, single `/api/pulse` composite endpoint replacing 8 separate API calls.

## What Changed

### New Files
- `docs/PULSE_REDESIGN_SPEC.md` — Full implementation spec (3-layer architecture, 8 glyph definitions, JSON schema, narrative rules, 22 tasks across 4 phases)
- `deploy/deploy_pulse_a.sh` — Sprint 1 patch script (not used — edits applied directly via Filesystem tools instead)

### Modified Files
- `lambdas/site_writer.py` — Added `PULSE_KEY`, `_glyph_state()`, `_compute_pulse()`, `write_pulse_json()` (+210 lines). Shared Lambda Layer v12 published.
- `lambdas/site_api_lambda.py` — Added `handle_pulse()` + `/api/pulse` route (+38 lines)
- `lambdas/daily_brief_lambda.py` — Added `write_pulse_json()` call in site_writer block (+44 lines)
- `site/live/index.html` — Complete rewrite: 3-layer Pulse page with 8 symbolic SVG glyphs, sparklines, detail cards, journey section below fold
- `deploy/p3_build_shared_utils_layer.sh` — Fixed layer description >256 char error (hardcoded short description)
- `deploy/sync_doc_metadata.py` — Version bumped to v3.9.17
- `docs/CHANGELOG.md` — v3.9.17 entry added

### Infrastructure
- Shared Lambda Layer v12 published + attached to all 15 consumers
- `/api/pulse` endpoint live (300s cache via CloudFront)
- DynamoDB: new `PK=PULSE` partition for historical pulse records
- S3: `site/pulse.json` written daily by daily brief

## Key Decisions
- **Split live page into Pulse (NOW) vs Journey (retrospective)** — Product Board unanimous
- **8 glyphs: Scale, Water, Movement, Lift, Recovery, Sleep, Journal, Mind** — mental health signals (Journal, Mind) sit alongside physical metrics as equals
- **Color-only glyph strip** — no numbers on Layer 2; numbers are in Layer 3 detail cards (progressive disclosure)
- **Elena Voss voice** for all narratives — journalist-narrator, not coach
- **site_writer.py lives in shared Layer** — any changes require `p3_build_shared_utils_layer.sh` + `p3_attach_shared_utils_layer.sh` (learned again this session)

## Deployment Sequence (for reference)
```bash
# 1. Edit site_writer.py, site_api_lambda.py, daily_brief_lambda.py
# 2. Build + publish shared layer
bash deploy/p3_build_shared_utils_layer.sh
# 3. Attach layer to all consumers
bash deploy/p3_attach_shared_utils_layer.sh "arn:aws:lambda:us-west-2:205930651321:layer:life-platform-shared-utils:12"
# 4. Deploy site-api (reads pulse.json from S3)
bash deploy/deploy_lambda.sh life-platform-site-api lambdas/site_api_lambda.py
# 5. Deploy daily brief (writes pulse.json)
bash deploy/deploy_lambda.sh daily-brief lambdas/daily_brief_lambda.py
# 6. Sync site HTML
bash deploy/sync_site_to_s3.sh
# 7. Invoke daily brief to generate first pulse.json
aws lambda invoke --function-name daily-brief --payload '{}' /tmp/brief_out.json --no-cli-pager
```

## Task Status

### Sprint 1 (Phase A) — API + Data Pipeline ✅
| Task | Description | Status |
|------|-------------|--------|
| PULSE-A1 | Pulse computation in daily brief | ✅ |
| PULSE-A2 | pulse.json to S3 | ✅ |
| PULSE-A3 | DynamoDB historical record (PK=PULSE) | ✅ |
| PULSE-A4 | /api/pulse route in site-api | ✅ |
| PULSE-A5 | CloudFront cache (inherits /api/*) | ✅ |

### Sprint 2 (Phase B) — Glyph Page ✅
| Task | Description | Status |
|------|-------------|--------|
| PULSE-B1 | 8 SVG glyph icons (symbolic) | ✅ |
| PULSE-B2 | Layer 1: Pulse headline | ✅ |
| PULSE-B3 | Layer 2: Glyph strip | ✅ |
| PULSE-B4 | Layer 3: Detail cards with sparklines | ✅ |
| PULSE-B5 | Wire to /api/pulse | ✅ |
| PULSE-C1 | Journey section below fold | ✅ |

### Remaining (Phase B6 + D) — Future Sessions
| Task | Description | Status |
|------|-------------|--------|
| PULSE-B6 | Historical navigation (← → arrows wired to DynamoDB) | ❌ Not started |
| PULSE-C2 | Weight timeline chart in Journey section | ❌ Not started |
| PULSE-D1 | Share card generation | ❌ Not started |
| PULSE-D2 | Pre-render narrative for SEO | ❌ Not started |
| PULSE-D3 | Glyph state variants (open/closed book, flame intensity) | ❌ Not started |

## Pre-Existing Test Failures (not introduced this session)
10 integration test failures — all pre-existing:
- I2: stale layers on MCP + freshness-checker (no layer attached)
- I5: todoist + notion secrets marked for deletion
- I6: 3 missing EventBridge rules
- I8: missing config/profile.json in S3
- I9: DLQ has 25 messages
- I11: data-reconciliation last ran 48h+ ago
- I12: MCP tool `get_data_freshness` unknown (renamed/removed)
- I13: freshness-checker response shape mismatch
- I14: canary MCP API key unavailable
- test_i5_no_orphaned_lambda_files: site_stats_refresh_lambda.py not in lambda_map.json

## What's Next
- **PULSE-B6**: Historical day navigation (← → arrows query DynamoDB `PK=PULSE` partition)
- **PULSE-C2**: Weight timeline chart in Journey section (port from old cockpit)
- **PULSE-D1-D3**: Share cards, SEO pre-render, glyph state variants
- **Visual QA**: Review on mobile, test light mode, check all 8 glyph states
- **SIMP-1 Phase 2 + ADR-025 cleanup** — targeted ~April 13, 2026

## Critical Reminders
- `site_writer.py` is in the **shared Lambda Layer** — edits require layer republish + attach
- Daily brief Lambda name is `daily-brief` (NOT `life-platform-daily-brief`)
- Layer description has 256 char limit (fixed in `p3_build_shared_utils_layer.sh`)
- `deploy_lambda.sh` only zips the single source file, not layer modules
