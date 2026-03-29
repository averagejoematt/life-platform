# Handover — v3.9.29

## Session: Phase D + E — Challenge XP Wiring, Auto-Verification, Nav Update

### What shipped this session (v3.9.28 → v3.9.29)

**v3.9.29**: Challenge XP → Character Sheet wiring, metric auto-verification engine, nav integration.

#### Nav Update ✅ WRITTEN (needs S3 sync + CloudFront invalidation)
- `site/assets/js/components.js` — Added `/challenges/` ("The Arena") to:
  - SECTIONS → Method → "What I Tested" dropdown
  - Footer → Method column
  - HIER_ITEMS hierarchy nav bar
  - HIER_CONTEXT blurb

#### Phase D — Challenge XP → Character Sheet ✅ WRITTEN (needs Lambda deploy)
- `lambdas/character_sheet_lambda.py` v1.2.0:
  - Post-compute step queries `SOURCE#challenges` for challenges completed yesterday
  - Domain → pillar mapping (sleep→sleep, movement→movement, nutrition→nutrition, supplements→nutrition, mental→mind, social→relationships, discipline→consistency, metabolic→metabolic, general→consistency)
  - Bonus XP added to pillar `xp_total`, `xp_consumed_at` set to prevent double-counting
  - `challenge_bonus_xp` dict added to character record + site writer output
  - Fully non-fatal (try/except wrapped)

#### Phase E — Metric Auto-Verification ✅ WRITTEN (needs MCP deploy)
- `mcp/tools_challenges.py`:
  - `AUTO_METRIC_MAP` — 8 metrics: daily_steps, weight_lbs, eating_window_hours, zone2_minutes, sleep_hours, hrv, calories, protein_g
  - `_check_metric_targets()` — queries DDB source partitions, supports min/max/exact targets
  - Wired into `checkin_challenge`: `metric_auto` overrides manual; `hybrid` auto-checks but respects manual flag
  - Auto-verification results in each checkin and response
- Science scan already in generator prompt — activates when data flows

### Files Modified
- `site/assets/js/components.js` — Nav, footer, hierarchy nav, hierarchy context
- `lambdas/character_sheet_lambda.py` — Phase D challenge XP wiring (v1.2.0)
- `mcp/tools_challenges.py` — Phase E auto-verification + checkin integration
- `deploy/sync_doc_metadata.py` — Version bump v3.9.28 → v3.9.29
- `docs/CHANGELOG.md` — v3.9.29 entry
- `handovers/HANDOVER_LATEST.md` — Pointer updated

### Deploy Checklist
1. `bash deploy/deploy_lambda.sh life-platform-mcp-server mcp_server.py` (MCP — auto-verification)
2. `bash deploy/deploy_lambda.sh life-platform-character-sheet-compute lambdas/character_sheet_lambda.py` (Phase D XP wiring)
3. `aws s3 sync site/ s3://matthew-life-platform/site/ --delete --region us-west-2` (nav update)
4. `aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/*"` (CloudFront)
5. `python3 deploy/sync_doc_metadata.py --apply` (propagate version)

### Pending Items
- Create first manual challenge via MCP to test full XP flow end-to-end
- Day 1 checklist (April 1): run `capture_baseline`, verify homepage shows "DAY 1"
- SIMP-1 Phase 2 + ADR-025 cleanup targeted ~April 13
- Phase E stretch: add more auto-metrics (resting_heart_rate, body_fat_pct, sleep_latency)
- Consider auto-completion trigger when checkin_days == duration_days and success_rate > threshold
