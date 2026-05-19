# Handover — Character Engine v1.1.0

**Date:** 2026-03-30
**Scope:** Statistical review implementation (15 findings)

## What Changed

The character leveling engine was mathematically incomplete per Dr. Henning Brandt's 8-panelist review. This release fixes all 15 findings:

### Critical (P0)
- **F-01**: Missing data no longer inflates scores. Confidence-weighted scoring blends toward 50 when data is sparse.
- **F-04**: Body composition uses sigmoid (loss) + maintenance band instead of broken linear interpolation.
- **F-05**: Cross-pillar modifiers are all multiplicative with explicit typed format.

### High (P1)
- **F-02**: XP decays daily and acts as a level stability buffer.
- **F-03**: Per-pillar EMA lambda (Sleep 4-day, Metabolic 14-day half-life).
- **F-07**: Lab decay extends to zero at 180 days.
- **F-12**: Vice control uses log curve.

### Medium/Low (P2-P3)
- **F-09**: Neutral default 50, **F-10**: Variable step +2, **F-11**: Equal-day hold, **F-13**: Buffer fix, **F-14**: Floor rounding.
- **F-15**: Progressive difficulty — tier-specific streak requirements.

## Files Modified
- `lambdas/character_engine.py` — ENGINE_VERSION 1.0.0 → 1.1.0
- `config/character_sheet.json` — v1.1.0 with all new config fields
- `site/character/index.html` — corrected methodology, math, tier descriptions
- `tests/test_character_engine.py` — 29 tests (new file)
- `docs/CHANGELOG.md` — v1.1.0 entry

## Deploy Status
- Config uploaded to S3
- Shared layer rebuilt and deployed (v17)
- All CDK stacks updated (Core, Compute, Ingestion, Email, Web, Operational)
- Character page synced to both S3 prefixes
- CloudFront invalidated

## Not Done
- **Retrocompute**: Spec recommends `python3 backfill/retrocompute_character_sheet.py --write --force` to recompute all history with v1.1.0 rules. User will run manually.
- **F-08**: Relationships 14-day rolling window (approved, deferred)
- **F-06**: Consistency circular dependency (documented, acceptable at 10% weight)
- **Pillar weight rationale doc**: Lena's requirement, separate task

## Risks
- First character_sheet compute after this deploy will use v1.1.0 rules while historical data uses v1.0.0. The `engine_version` field distinguishes them. Run retrocompute to clean up.
- XP decay means existing XP totals will start eroding immediately. This is by design.
