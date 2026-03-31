# Claude Code Prompt — Character Engine v1.1.0 Implementation

Read `docs/specs/SPEC_CHARACTER_ENGINE_v1.1.0.md` and `docs/reviews/REVIEW_CHARACTER_LEVELING_2026-03-30.md` in full before starting.

## Context

Our Technical Board's statistician (Dr. Henning Brandt) led a full review of the character leveling system with 8 experts across our Technical, Personal, and Product boards. They found 15 issues (F-01 through F-15) — the engine is structurally sound but mathematically incomplete. The spec contains every code change, config update, test, page content fix, and deploy step needed to ship v1.1.0.

## What to implement

The spec has 10 parts. Implement them in this order:

### Phase 1: Engine changes (`lambdas/character_engine.py`)

Implement all changes from Part 1 (sections 1A through 1K):

- **1A (F-01):** Replace `_weighted_pillar_score()` with confidence-weighted version. When data is sparse, blend score toward 50 (neutral) instead of pretending missing data doesn't exist. Return confidence and data_coverage in the details dict.
- **1B (F-02):** XP now decays daily and acts as a level stability buffer. Change `_compute_xp()` to accept previous_xp, apply daily decay, return (earned, delta, new_xp). Update the call site in `compute_character_sheet()`.
- **1C (F-03):** Per-pillar EMA lambda. `compute_ema_level_score()` accepts `pillar_name` kwarg, looks up per-pillar lambda from config, falls back to global.
- **1D (F-04):** Two-phase body composition scoring. New `_body_comp_score()` function with sigmoid curve during loss phase, maintenance band scoring after goal reached. Replace the inline body comp block in `compute_nutrition_raw()`.
- **1E (F-05):** Cross-pillar effects now support explicit `{"type": "multiplicative", "value": -0.08}` format in config. Backward-compatible with raw numbers. Remove the `abs(mod) < 1` branching — all modifiers are multiplicative: `score * (1 + total_mod)`.
- **1F (F-07):** Lab biomarker decay extends to zero at 180 days instead of flooring at 0.5.
- **1G (F-12):** Vice control uses logarithmic curve: `100 * log(1 + streak) / log(31)` instead of linear.
- **1H (F-15):** Progressive difficulty. `evaluate_level_changes()` reads `tier_streak_overrides` from config to get per-tier streak requirements. Foundation needs 3 days to level up, Elite needs 14. Also implements XP buffer gate (F-02), variable step size +2 when delta >10 (F-10), and streak hold on equal days (F-11).
- **1I (F-14):** Use `math.floor()` instead of `round()` for character level calculation.
- **1J (F-13):** Fix `_in_range_score()` buffer calculation to use `(high - low) * buffer` as divisor.
- **1K (F-09):** Change all "no data" fallback defaults from 40.0 to 50.0.

Update `ENGINE_VERSION = "1.1.0"`.

The spec contains the exact replacement code for each function. Follow it closely but adapt as needed if the existing code has drifted from what the spec expects.

### Phase 2: Config update (`config/character_sheet.json`)

Replace the config with the v1.1.0 version from Part 2 of the spec. Key additions:
- `baseline.weight_phase`, `baseline.maintenance_band_lbs`
- Per-pillar `ema_lambda` values
- `leveling.tier_streak_overrides` with all 5 tiers
- `leveling.xp_per_level`, `leveling.daily_xp_decay`, `leveling.xp_buffer_threshold`, `leveling.level_step_threshold`
- Cross-pillar effects using `{"type": "multiplicative", "value": N}` format
- `_meta.version = "1.1.0"`

### Phase 3: Unit tests (`tests/test_character_engine.py`)

Add the tests from Part 6 of the spec. They cover:
- Confidence scoring (full data, sparse data, no data)
- XP decay mechanics
- Body comp sigmoid + maintenance
- Lab decay expiry at 180 days
- Vice log curve
- Progressive streaks (Foundation 3-day, Mastery 10-day)
- Equal day streak hold

Run tests to confirm they pass: `python3 -m pytest tests/test_character_engine.py -v`

### Phase 4: Character page content (`site/character/index.html`)

The current methodology section and "The Math" expandable are **factually wrong** — they claim equal weights and a logarithmic XP curve that never existed. Update them with the corrected content from Parts 5A through 5E of the spec:

- **5A:** Replace the methodology section with correct pillar weights and accurate description
- **5B:** Replace "The Math" expandable with the two-tier explanation (30-second version + deeper version) including the progressive difficulty table
- **5C:** Update tier framework descriptions to mention streak requirements
- **5D:** Update the intro paragraph below the pillar grid
- Remove all references to "equal weights (14.3% each)" and "logarithmic XP curve"

### Phase 5: Deploy

Follow the deploy sequence from Part 8:
1. Upload config to S3: `aws s3 cp config/character_sheet.json s3://matthew-life-platform/config/matthew/character_sheet.json`
2. Rebuild shared layer (character_engine.py lives there): `bash deploy/p3_build_shared_utils_layer.sh` then `bash deploy/p3_attach_shared_utils_layer.sh`
3. Sync character page: `aws s3 cp site/character/index.html s3://matthew-life-platform/site/character/index.html --content-type "text/html"`
4. CloudFront invalidation: `aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/character/*"`

Do NOT run retrocompute yet — I'll do that manually after verifying the deploy.

## Important rules

- `character_engine.py` lives in `lambdas/` AND in the shared Lambda layer. Edit `lambdas/character_engine.py` — the layer build script copies it.
- Run `python3 -m pytest tests/test_mcp_registry.py -v` before any deploy to verify MCP registry consistency.
- Do NOT use `--delete` flag on any S3 sync.
- Write deploy scripts to `deploy/` — I run them in terminal.
- After all changes, update CHANGELOG.md with a v1.1.0 entry summarizing the 15 findings implemented.
- Update the handover: write `handovers/HANDOVER_v1.1.0.md` and update `handovers/HANDOVER_LATEST.md` to point to it.
- Git commit and push when done.

## Acceptance criteria

From Part 9 of the spec — all 10 items must be true before marking complete.
