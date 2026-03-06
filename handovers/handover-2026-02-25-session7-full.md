# Handover — 2026-02-25 Session 7: Day Grade Fix + Water Investigation + Dedup + Demo Mode

## What Happened

### v2.22.1 — Day Grade Zero-Score Fix (DEPLOYED ✅)
- **Root cause**: `score_journal()` returned `0` (not `None`) when no entries; `score_hydration()` scored Apple Health trace water (11.83ml) as 0/100.
- **Fix**: Journal returns `None` when no entries. Hydration treats <118ml (4oz) as "not tracked". Algorithm version bumped 1.0→1.1.
- **Verified**: Feb 24 grade **69 C+ → 77 B** (later adjusted to 73 B- after dedup corrected movement score).

### Water Data Investigation
- **Symptom**: DynamoDB had 11.83ml for Feb 24; user saw 3,632ml in Apple Health app.
- **Root cause (pipeline timing)**: The 11.83 was actually 11.83 fl_oz (350ml after correct unit conversion) from a single tiny webhook sync. The full day's water was in a 289KB payload that hit the Lambda before `dietary_water` was enabled (deployment timing issue from the Feb 24 RCA incident). Remaining water never left the phone.
- **Replay**: `replay_feb24_water.py` v2 scanned all 4 archived payloads. Only 1 water reading for Feb 24 found. DynamoDB updated: 11.83ml → 350ml (unit conversion fix).
- **Status**: 350ml is correct for what was captured, but incomplete vs 3,632ml actual. Tracked as known issue — depends on HAE sync cadence going forward.

### v2.22.2 — Strava Activity Deduplication (DEPLOYED ✅)
- **Root cause**: WHOOP and Garmin both record the same walk → both sync to Strava independently. Feb 24: "Afternoon Walk" appeared twice.
- **Fix**: `dedup_activities()` detects overlapping activities (same sport_type, start within 15 min), keeps richer record (prefers GPS/distance, then longer duration). Recomputes `activity_count` and `total_moving_time_seconds`.
- **Verified in logs**: `Dedup: walk overlap — kept Garmin Epix Gen2, dropped WHOOP` + `3 → 2 activities`.
- **Scope**: Daily brief only. Strava ingestion-level dedup tracked as known issue.

### v2.22.3 — Demo Mode for Sharing (DEPLOYED ✅)
- **Feature**: Invoke with `{"demo_mode": true}` for a sanitized version safe to share.
- **Profile-driven rules** (`demo_mode_rules` in DynamoDB) — updatable without deploy:
  - `redact_patterns`: 15 words (marijuana, thc, alcohol, bourbon, etc.) → "[redacted]"
  - `replace_values`: weight→"•••", calories→"•,•••", protein→"•••"
  - `hide_sections`: journal_pulse, journal_coach, weight_phase
  - `subject_prefix`: "[DEMO]"
- **13 section markers** (`<!-- S:name -->`) in build_html for section-level stripping.
- **Safety**: Demo mode skips `store_day_grade()` to protect real data.
- **Verified in logs**: `[DEMO MODE]`, `Demo mode: sanitization applied`, `Sent: [DEMO] Morning Brief...`

## Final Production State
- **Version**: v2.2.3 (Daily Brief Lambda — Day Grade Fix + Activity Dedup + Demo Mode)
- **Platform version**: v2.22.3
- **Day grade (Feb 24)**: 73 B- (accurate — no phantom zeros, no inflated exercise)
- **Code size**: 21,955 bytes (up from 19,299 at v2.2.1)

## Files Created This Session
- `patch_day_grade_zero_score.py` — v2.22.1 patcher
- `deploy_daily_brief_v221.sh` — v2.22.1 deploy
- `replay_feb24_water.py` — Water data replay (v2, multi-payload scan)
- `patch_activity_dedup.py` — v2.22.2 patcher
- `deploy_daily_brief_v222.sh` — v2.22.2 deploy (superseded by v223)
- `patch_demo_mode.py` — v2.22.3 patcher
- `seed_demo_mode_rules.py` — DynamoDB profile rules seeder
- `deploy_daily_brief_v223.sh` — Chained deploy (v2.22.2 + v2.22.3)

## Files Modified This Session
- `daily_brief_lambda.py` — v2.2.1 → v2.2.3 (all three patches applied)
- `CHANGELOG.md` — v2.22.1, v2.22.2, v2.22.3 entries
- `PROJECT_PLAN.md` — Version bumped to v2.22.3, known issues added, completed table updated, Tier 1 items renumbered
- `SCHEMA.md` — Profile fields (day_grade_weights, mvp_habits, weight_loss_phases, demo_mode_rules), Demo Mode Rules section
- `ARCHITECTURE.md` — Header bumped to v2.22.3
- `HANDOVER_LATEST.md` — Pointer updated

## Known Issues Added
- **Strava multi-device duplicates (ingestion)**: Dedup in daily brief only. Raw records still store duplicates. Fix at ingestion level would benefit MCP tools too.
- **Water data incomplete (HAE sync)**: Feb 24 water only 350ml vs 3,632ml actual. HAE sync cadence/timing means some days' water never reaches webhook. Verify with upcoming syncs.

## What's Next (per updated PROJECT_PLAN)
1. **Day grade retrocompute** (2-3 hr) — Backfill historical grades with algo v1.1. No dependency blocker.
2. **Weekly Digest v2** (3-4 hr) — W-o-W deltas, grade trend, Zone 2, macro adherence.
3. **API gap closure deploy** (30 min) — 3 patches ready since v2.14.3.

## Demo Mode Quick Reference
```bash
# Normal brief
aws lambda invoke --function-name daily-brief --payload '{}' \
  --cli-binary-format raw-in-base64-out --region us-west-2 /tmp/brief.json

# Demo brief (sanitized for sharing)
aws lambda invoke --function-name daily-brief --payload '{"demo_mode": true}' \
  --cli-binary-format raw-in-base64-out --region us-west-2 /tmp/demo.json

# Available sections for hide_sections:
# scorecard, readiness, training, nutrition, habits, cgm,
# weight_phase, guidance, journal_pulse, journal_coach, bod
```
