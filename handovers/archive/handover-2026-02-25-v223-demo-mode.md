# Handover — 2026-02-25 Session 7 (cont): Demo Mode (v2.22.3)

## What Happened

### v2.22.3 — Demo Mode for Sharing (READY TO DEPLOY)
Built profile-driven HTML sanitization so the daily brief can be shared with coworkers and friends without exposing sensitive data.

**Architecture:**
- `demo_mode_rules` stored in DynamoDB profile — updatable anytime without deploy
- `sanitize_for_demo()` function reads rules and applies to final HTML
- Handler checks `event["demo_mode"]` flag
- 13 section markers (`<!-- S:name -->`) added to build_html for section-level stripping
- Demo banner ("DEMO VERSION") injected at top of sanitized email
- Day grade storage skipped in demo mode to protect real data

**Default rules seeded:**
- `redact_patterns`: marijuana, thc, cannabis, weed, edible, alcohol, bourbon, whiskey, wine, beer, drinks, drunk, hungover, hangover
- `replace_values`: weight→"•••", calories→"•,•••", protein→"•••"
- `hide_sections`: journal_pulse, journal_coach, weight_phase
- `subject_prefix`: "[DEMO]"

**Invocation:**
```bash
# Normal brief
aws lambda invoke --function-name daily-brief --payload '{}' ...

# Demo brief (sanitized)
aws lambda invoke --function-name daily-brief --payload '{"demo_mode": true}' ...
```

### Deploy Chain
The deploy script (`deploy_daily_brief_v223.sh`) chains all pending patches:
1. `seed_demo_mode_rules.py` — Profile rules to DynamoDB
2. `patch_activity_dedup.py` — v2.2.2 dedup fix
3. `patch_demo_mode.py` — v2.2.3 demo mode
4. Package + deploy + test both normal and demo invocations

## Files Created
- `patch_demo_mode.py` — v2.2.3 patcher (section markers + sanitizer + handler changes)
- `seed_demo_mode_rules.py` — DynamoDB profile rules seeder
- `deploy_daily_brief_v223.sh` — Chained deploy (v2.2.2 + v2.2.3 + test both modes)

## Files Modified
- `CHANGELOG.md` — v2.22.3 entry
- `PROJECT_PLAN.md` — Version bumped, completed table updated
- `HANDOVER_LATEST.md` — Pointer updated

## Current State
- **Production**: v2.2.1 running (day grade fix deployed)
- **Pending**: v2.2.2 (dedup) + v2.2.3 (demo mode) — single deploy via `bash deploy_daily_brief_v223.sh`

## Section Markers Available for hide_sections
scorecard, readiness, training, nutrition, habits, cgm, weight_phase, guidance, journal_pulse, journal_coach, bod

## What's Next
1. **Deploy v2.2.3** — `bash deploy_daily_brief_v223.sh`
2. **Day grade retrocompute** (2-3 hr) — Backfill historical grades
3. **Weekly Digest v2** (3-4 hr) — Needs retrocompute for grade trending
4. **API gap closure deploy** (30 min) — 3 patches ready since v2.14.3
