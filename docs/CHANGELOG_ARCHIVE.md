# Life Platform — Changelog Archive

> Versions older than v2.11.0. Moved here to reduce session startup token cost.
> For recent changes, see CHANGELOG.md.

---

## v2.10.0 — 2026-02-24 — GP Physicals + DEXA + Genome Data Seed

### GP Blood Draws — 5 Annual Physicals (2019–2024)
- Seeded 5 One Medical / LabCorp blood draws to `USER#matthew#SOURCE#labs`
- 2019-05-01: 35 biomarkers, 0 out of range
- 2020-10-20: 35 biomarkers, 0 out of range
- 2021-10-20: 34 biomarkers, 2 out of range (total cholesterol 212↑, LDL 126↑)
- 2022-06-01: 33 biomarkers, 2 out of range (total cholesterol 201↑, LDL 135↑)
- 2024-06-01: 45 biomarkers + WBC differential, 2 out of range (total cholesterol 206↑, LDL 124↑)
- All use identical biomarker key names as Function Health draws for seamless cross-provider trending
- Labs partition now: 8 items total (5 GP + 2 Function Health + 1 metadata)
- Full labs timeline: 7 blood draws spanning 6 years (2019–2025)

### DEXA Body Composition Scan (2025-05-10)
- New `dexa` source added: `USER#matthew#SOURCE#dexa`
- DexaFit Seattle scan: weight 190.2 lb, body fat 15.6%, lean mass 150.3 lb
- Android/Gynoid ratio 1.13, visceral fat 230g (elite category)
- BMD T-score 1.4 (excellent bone density)
- Posture assessment (Kinetisense 3D): forward shoulder 2.2–2.4 in, forward hip 2.6–2.8 in, left-side rotation pattern
- Interpretations: leaner than 85% of men same age, exceptional lean mass retention post-120lb loss
- 6-month goals: 12-13% body fat, 5-7 lb fat loss, A/G ratio ≤1.0

### Genome SNP Report — 110 Clinical Interpretations
- New `genome` source: `USER#matthew#SOURCE#genome` — 111 items (110 SNPs + 1 summary)
- Parsed 49-page comprehensive SNP interpretation report (consumer genomics, dated 2020-06-19)
- Risk distribution: 35 unfavorable, 17 mixed, 47 neutral, 11 favorable
- 14 categories: metabolism (20), longevity (20), nutrient_metabolism (19), lipids (10), immune (9), taste (7), exercise (6), sleep (6), miscellaneous (5), statin_response (3), antioxidant (2), cardiovascular (1), caffeine (1), cancer_risk (1)
- Key actionable themes: 6 FTO obesity variants, triple vitamin D deficiency risk, MTHFR compound heterozygous, FADS2 poor ALA→EPA conversion, SLCO1B1 statin sensitivity, ABCG8 elevated LDL, CYP1A2 fast caffeine metabolizer
- Stores ONLY clinical interpretations — no raw genome data (privacy by design)

---

## v2.9.0 — 2026-02-23 — Blood Work / Labs Integration (Phase 1: Seed + Schema)

- New `labs` source (#12) added. Parsed 6 Function Health PDF lab reports.
- Extracted 107 unique biomarkers across 2 blood draws (2025-04-08: 33 biomarkers; 2025-04-17: 74 biomarkers)
- DynamoDB schema: draw records at `DATE#YYYY-MM-DD`, provider metadata at `PROVIDER#<provider>#<period>`
- 22 biomarker categories defined
- `seed_labs.py` ready for deployment

---

## v2.8.0 — 2026-02-23 — Caffeine-Sleep Correlation Tool

- `get_caffeine_sleep_correlation`: personal caffeine cutoff finder — MacroFactor food_log timing + Eight Sleep
- Bucket analysis (no caffeine / before noon / noon-2pm / 2pm-4pm / after 4pm) + Pearson correlations + personal cutoff recommendation
- Unified OneDrive data pipeline for MacroFactor + Apple Health zero-touch ingestion
- MCP server v2.8.0 (45 tools)

---

## v2.7.0 — 2026-02-23 — Habitify Integration (Replaces Chronicling)

- **habitify_lambda.py** — daily ingestion Lambda; replaces Chronicling as P40 habit tracking source
- 65 habits across 9 P40 groups (added Supplements group with 19 items)
- Mood tracking (1-5 scale), dynamic area-to-group mapping via Habitify API
- MCP server: `habitify` added to SOURCES, default SOT `habits` → `habitify`, all 8 habit tools auto-switch
- Exist.io removed from roadmap — Habitify covers habits + mood; Notion journal for energy/stress

---

## v2.6.0 — 2026-02-23 — Garmin Epix Integration

- **garmin_lambda.py** — ingestion Lambda via garminconnect + garth OAuth
- Fields: RHR, HRV, stress, Body Battery, respiration, steps + Garmin-exclusive biometrics
- New MCP tools: `get_garmin_summary`, `get_device_agreement` (Whoop vs Garmin cross-validation)
- `get_readiness_score` updated: 4→5 components (Body Battery added)
- Backfill: 2022-04-25 → 2026-01-18 (1,356 records)

---

## v2.5.2 — 2026-02-23 — Infrastructure Hardening

- CloudTrail audit logging (`life-platform-trail`)
- CloudWatch alarms for email Lambdas (daily-brief, weekly-digest, monthly-digest, anomaly-detector)
- 30-day log retention on all 12 Lambda log groups
- Haiku API retry logic (`call_anthropic_with_retry()`) in all 4 email Lambdas

---

## v2.5.1 — 2026-02-23 — DynamoDB TTL Field Name Fix
- Bug fix: `ttl_epoch` → `ttl` in cache read/write

---

## v3.6.0 — 2026-02-23 — QA Pass: Bug Fixes + Audit
- Weight projection sign fix, delta guard, MacroFactor hit rate denominator fix
- Flagged: trend threshold tuning, batch_get_item optimization, digest code split

---

## v3.5.0 — 2026-02-23 — Weekly Digest Open Insights + MacroFactor Real Data
- `fetch_stale_insights()` + Open Insights HTML section in weekly digest
- First real MacroFactor CSV processed (6 days)

---

## v3.4.0 — 2026-02-23 — Insights Coaching Log
- 3 new tools: `save_insight`, `get_insights`, `update_insight_outcome` (tool count 41→44)

---

## v3.3.0 — 2026-02-23 — Anomaly Detection + DKIM
- `anomaly-detector` Lambda (9 metrics, 6 sources, Z-threshold 1.5 SD)
- DKIM verified on mattsusername.com

---

## v3.2.0 — 2026-02-23 — Daily Brief + Monthly Coach's Letter
- `daily-brief` Lambda (8:15am PT), `monthly-digest` Lambda (first Sunday 8am PT)

---

## v2.4.0 — 2026-02-23 — Unified readiness score
- `get_readiness_score` — 0-100 (GREEN/YELLOW/RED), 4 components

---

## v2.3.3 — 2026-02-22 — Ingestion schedule alignment
- All sources 6am–7am PT; enrichment 7:30am; cache 8:00am; freshness 8:15am; digest 8:30am Sun

---

## v2.3.2 and earlier — 2026-02-22
- Source-of-truth domain architecture, security hardening, activity enrichment, weekly digest, Eight Sleep integration, MacroFactor tools, PITR, IAM hardening, CloudWatch, documentation
