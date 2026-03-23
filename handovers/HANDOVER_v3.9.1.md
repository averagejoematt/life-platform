# Handover v3.9.1 — SUPP-1+2: Data-Driven Supplements Page
**Date:** 2026-03-22
**Session type:** Phase 1 redesigns (continuing from v3.9.0)

---

## What Was Done

### SUPP-1: Remove Hardcoded Supplement Cards — COMPLETE

Rewrote `site/supplements/index.html` body to be fully dynamic:
- Removed all 10 hardcoded supplement cards (was static HTML, 500+ lines)
- Added skeleton loading state (`#supp-skeleton`)
- Added dynamic groups container (`#supp-groups`, rendered by JS)
- Added error state (`#supp-error`)
- Added dynamic genome explainer section (`#supp-genome`) populated from API data
- Stats row now uses `id="stat-total"`, `id="stat-strong"`, `id="stat-emerging"`, `id="stat-exp"` (updated dynamically from API)

### SUPP-2: Evidence Tier Badges — COMPLETE

New evidence tier system from `supplement_metadata.json`:
- `strong` → green badge (`.badge--strong`) — peer-reviewed / genome-justified
- `emerging` → amber badge (`.badge--emerging`) — promising RCT data
- `general` → gray badge (`.badge--general`) — foundational health
- `experimental` → purple badge (`.badge--experimental`) — N=1 hypothesis

Genome SNP tag (`.badge--snp`) rendered if supplement has `genome_snp` field.

Supplements are now **grouped by `purpose_group`** (not timing):
- Foundation
- Sleep Stack
- Recovery+Performance
- Longevity+Metabolic
- Nutrition+Glucose
- Experimental

### New S3 Config: supplement_metadata.json — COMPLETE

Created `config/supplement_metadata.json` (17KB, 18 supplements):
- Uploaded to both `config/` and `site/config/` paths
- Lambda reads from `site/config/supplement_metadata.json` (IAM allows `site/config/*`)
- Fields: `display_name`, `purpose_group`, `evidence_tier`, `genome_snp`, `rationale`, `science_points[]`, `watching`, `signal`, `linked_experiment_id`

**Current DynamoDB supplement stack (9 active):**
| Key | Display Name | Group | Tier |
|---|---|---|---|
| collagen | Collagen Peptides | Foundation | emerging |
| probiotics | Probiotics | Foundation | emerging |
| creatine | Creatine Monohydrate | Recovery+Performance | strong |
| electrolytes | Electrolytes | Foundation | general |
| l_glutamine | L-Glutamine | Recovery+Performance | emerging |
| protein_supplement | Protein Supplement | Foundation | strong |
| l_threonate | Magnesium L-Threonate | Sleep Stack | emerging |
| apigenin | Apigenin | Sleep Stack | experimental |
| theanine | L-Theanine | Sleep Stack | strong |

**Metadata also covers original 10 supplements** (vitamin_d3, omega3, tongkat_ali, nmn, coq10, berberine, magnesium_glycinate, zinc, ashwagandha) for future use.

### Lambda Enhancement: handle_supplements() — COMPLETE

`lambdas/site_api_lambda.py`:
- Added `_supp_metadata_cache: dict = None` module-level cache
- Added `_load_supp_metadata()` — loads from `site/config/supplement_metadata.json`, caches in warm container
- `handle_supplements()` now merges S3 metadata into each DynamoDB supplement record
- New response fields: `key`, `purpose_group`, `evidence_tier`, `genome_snp`, `rationale`, `science_points`, `watching`, `signal`, `linked_experiment_id`

**IAM note:** Lambda role only permits `s3:GetObject` on `matthew-life-platform/site/config/*`. This is why `_load_content_filter()` (uses `config/content_filter.json`) also silently fails — it falls back to hardcoded defaults. If you want to fix content filter too, either grant `config/*` access in CDK or move the file to `site/config/`.

---

## Deployment

```bash
# Lambda deployed ✓
bash deploy/deploy_lambda.sh life-platform-site-api lambdas/site_api_lambda.py

# Site deployed ✓
aws s3 cp site/supplements/index.html s3://matthew-life-platform/site/supplements/index.html

# CloudFront invalidated ✓
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/supplements/*" "/api/supplements"
```

---

## Known Remaining Issues (Phase 0 carryover)

1. `public_stats.json.vitals.weight_lbs = null` — daily-brief Lambda bug
2. `public_stats.json.journey.progress_pct = 0` — daily-brief Lambda bug
3. `public_stats.json.platform.tier0_streak` missing — daily-brief Lambda needs this field
4. `test_count` and `monthly_cost` not in public_stats.json — for STORY-1 full wiring
5. G-8: Privacy page email pending Matthew confirmation
6. G-7: SES verification for lifeplatform@mattsusername.com

## Next Up (Phase 1 Remaining)

- **HAB-1**: Vice streak portfolio section on /habits/
- **STORY-3**: Journey timeline component + new API endpoint
- G-8 once email confirmed
- G-7 once SES verified
- Fix daily-brief Lambda (weight_lbs, progress_pct bugs)
