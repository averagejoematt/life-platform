# Life Platform — Handover: GP Physicals + DEXA + Genome Seed
**Date:** 2026-02-24  
**Version:** v2.10.0  
**Session:** Health data ingestion — physicals, DEXA, genome SNP report  
**Status:** All data seeded and verified in DynamoDB

---

## What Was Done

### 1. GP Blood Draws — 5 Annual Physicals (2019–2024)
Manually transcribed from Excel file covering One Medical / LabCorp annual physicals.

| Draw Date | Provider | Biomarkers | Out of Range |
|-----------|----------|------------|--------------|
| 2019-05-01 | One Medical / LabCorp | 35 | 0 |
| 2020-10-20 | One Medical / LabCorp | 35 | 0 |
| 2021-10-20 | One Medical / LabCorp | 34 | 2 (total chol 212↑, LDL 126↑) |
| 2022-06-01 | One Medical / LabCorp | 33 | 2 (total chol 201↑, LDL 135↑) |
| 2024-06-01 | One Medical / LabCorp | 45 | 2 (total chol 206↑, LDL 124↑) |

- All biomarker keys match Function Health naming for cross-provider trending
- 2024 draw includes WBC differential (7 subtypes)
- Labs partition now: 8 items (5 GP + 2 Function Health + 1 metadata)
- Script: `seed_physicals_dexa.py`

### 2. DEXA Body Composition Scan (2025-05-10)
New `dexa` source created. DexaFit Seattle scan data:

- Weight: 190.2 lb, Body Fat: 15.6%, Lean Mass: 150.3 lb
- Android/Gynoid Ratio: 1.13, Visceral Fat: 230g (elite)
- BMD T-score: 1.4 (excellent)
- Posture: Forward shoulder 2.2–2.4 in, forward hip 2.6–2.8 in, left rotation
- Interpretations: Leaner than 85% of men same age, exceptional lean mass post-120lb loss
- 6-month goals: 12-13% body fat, A/G ratio ≤1.0
- Script: `seed_physicals_dexa.py` (same script as GP draws)

### 3. Genome SNP Report — 110 Clinical Interpretations
Parsed 49-page comprehensive SNP interpretation PDF (report.pdf, dated 2020-06-19).

**DynamoDB:** `USER#matthew#SOURCE#genome` — 111 items (110 SNPs + 1 summary)

**Risk distribution:** 35 unfavorable, 17 mixed, 47 neutral, 11 favorable

**Top actionable findings:**
- 6 FTO obesity variants → exercise + high protein + PUFA + low saturated fat
- Triple vitamin D deficiency risk (3 separate SNPs)
- MTHFR compound heterozygous + MTRR → 5-methylfolate, methylcobalamin, monitor homocysteine
- FADS2 poor ALA→EPA conversion → direct EPA/DHA, not plant omega-3
- PPAR-alpha → high-sat-fat keto detrimental; favor PUFA
- SLCO1B1 x2 statin sensitivity → rosuvastatin/pravastatin preferred, add CoQ10
- ABCG8 T;T elevated LDL → explains LDL trend in GP draws
- CYP1A2 fast caffeine metabolizer → coffee cardioprotective at 1-3 cups
- 5+ choline-related variants → prioritize choline intake
- 6 telomere-shortening variants → stress reduction, omega-3, exercise, sleep

**Privacy:** Stores only clinical interpretations — no raw genome data. ~50-200 targeted variants pose minimal re-identification risk vs 600K+ raw SNP arrays.

- Script: `seed_genome.py`
- Data size: 62.3 KB total, 0.6 KB avg/item

### 4. Garmin Export Evaluation
Evaluated `/Users/matthewwalker/Documents/Claude/GarminExport/`:
- weight.csv: 586 entries (2012–2020) — complete duplicate of Withings (1,138 entries)
- activities.csv: only 7 months walking data
- **Decision: No ingestion needed**

### 5. Documentation Updated
- CHANGELOG.md — v2.10.0 entry
- SCHEMA.md — `dexa` and `genome` source sections added, valid sources updated to 14
- PROJECT_PLAN.md — labs/DEXA/genome marked done, North Star gap #2 marked substantially closed
- ARCHITECTURE.md — source count updated to 14, manual seed sources added to diagram

---

## DynamoDB Inventory After This Session

| Source | Partition | Items | Span |
|--------|-----------|-------|------|
| genome | `USER#matthew#SOURCE#genome` | 111 | Genotyped ~2020 |
| labs | `USER#matthew#SOURCE#labs` | 8 | 2019–2025 (7 draws + 1 meta) |
| dexa | `USER#matthew#SOURCE#dexa` | 1 | 2025-05-10 |
| whoop | `USER#matthew#SOURCE#whoop` | ~730+ | 2024–present |
| withings | `USER#matthew#SOURCE#withings` | 1,138 | 2012–2026 |
| strava | `USER#matthew#SOURCE#strava` | 2,636+ | 2018–present |
| eightsleep | `USER#matthew#SOURCE#eightsleep` | 868+ | 2023–present |
| garmin | `USER#matthew#SOURCE#garmin` | 1,356 | 2022–2026 |
| macrofactor | `USER#matthew#SOURCE#macrofactor` | growing | 2026-02-22+ |
| apple_health | `USER#matthew#SOURCE#apple_health` | ~700+ | 2024–present |
| todoist | `USER#matthew#SOURCE#todoist` | ~365+ | 2025–present |
| hevy | `USER#matthew#SOURCE#hevy` | varies | 2024–present |
| habitify | `USER#matthew#SOURCE#habitify` | growing | 2026-02-23+ |
| chronicling | `USER#matthew#SOURCE#chronicling` | ~300 | 2025 (archived) |

---

## What's Next

### Labs Phase 2 — MCP Tools (queued)
New tools to build for the MCP server:
1. `get_lab_results` — biomarkers for a specific draw, with category filter
2. `get_lab_trends` — compare biomarker values across 7 draws (2019–2025)
3. `get_out_of_range_summary` — all flagged biomarkers across all draws
4. `get_lab_summary` — provider metadata, clinician notes, action plans
5. `search_biomarker` — find a biomarker by name across all draws
6. `get_genome_insights` — query genome SNPs by category/risk level, cross-reference with labs

### Genome-Labs Cross-Reference (high value)
The genome data enables personalized interpretation of lab results:
- ABCG8 T;T → explains persistent LDL elevation across 5 years of GP draws
- MTHFR/MTRR → homocysteine monitoring should be added to next draw
- Triple vitamin D risk → confirms need for aggressive D3 supplementation
- FADS2 → omega-3 index testing would be valuable
- SLCO1B1 → if statins ever prescribed, rosuvastatin only

---

## Key Files

| File | Location | Purpose |
|------|----------|---------|
| seed_physicals_dexa.py | ~/Documents/Claude/life-platform/ | GP draws + DEXA seed |
| seed_genome.py | ~/Documents/Claude/life-platform/ | Genome SNP seed |
| report.pdf | ~/Documents/Claude/genome/ | Source genome report |
| CHANGELOG.md | ~/Documents/Claude/life-platform/ | v2.10.0 entry |
| SCHEMA.md | ~/Documents/Claude/life-platform/ | dexa + genome sections added |
| PROJECT_PLAN.md | ~/Documents/Claude/life-platform/ | Updated gaps + future sources |
| ARCHITECTURE.md | ~/Documents/Claude/life-platform/ | 14 sources, diagram updated |
