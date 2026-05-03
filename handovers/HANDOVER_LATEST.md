# Handover — v6.8.1: Phase 1 Source Restoration + FH 2026 Ingest

**Date:** 2026-05-02
**Scope:** Restore platform pulse after 4-week silence. Ingest Function Health 2026 lab draw (8th draw, 153 biomarkers). Re-auth Garmin. Backfill Apple Health gap. Document accumulated tech debt.
**Type:** Operational restoration, not feature work.

See [HANDOVER_v6.8.1.md](HANDOVER_v6.8.1.md) for full details.

## Summary

- **10 of 11 ingestion sources verified end-to-end.** MacroFactor dormant (no logs during silence — not a pipeline failure).
- **Function Health 2026 ingested** at `DATE#2026-04-03`. 153 biomarkers across standard panel + Cardio IQ + NfL + Galleri. 26 out-of-range. Validated against `Supplement_Protocol_2026-05_v2.md` reference values (15/15 match). Total draws now: 8.
- **Headline finding: Cardio IQ Insulin Resistance Score 75** — definitively insulin resistant (>66 cutoff). Combines fasting insulin 14.3 (5.7x rise from 2.5 last year) and elevated C-peptide 2.26.
- **Garmin re-auth** via `setup/setup_garmin_browser_auth.py` (Playwright/Chromium MFA flow). 7 missing dates backfilled cleanly.
- **Apple Health 27-day gap closed** via new `backfill/backfill_apple_health_export_v16.py` (v16.1 source-aware — fixes iPhone+Garmin step duplication, mL→fl_oz water).
- **No Lambda code shipped.** All restoration was DDB writes, S3 uploads, and Secrets Manager rotations.

## Critical Finding — TD-19 [HIGH]

**Cross-source date partition convention mismatch.** HAE Lambda writes today's data at local-PT-midnight partition; Withings writes at UTC-midnight. Same wall-clock day → two different DDB partitions → daily intelligence aggregation will silently undercount. Highest-priority architectural fix from tonight.

## Headline Findings from FH 2026 Draw

- `insulin_resistance_score: 75` (Cardio IQ; >66 = resistant) — **the headline finding**
- `c_peptide: 2.26` (>2.16 cutoff) — confirms endogenous insulin overproduction
- `apob: 116` standard panel + `apob_cardio_iq: 111` (different assays, both flagged)
- `lp_pla2_activity: 137` (>123 cutoff) — vascular inflammation
- `omega_3_index: 3.3%` (was 7.8% last year) — failed repletion
- `vitamin_d_25oh: 28` (was 117 last year) — into deficient range
- `testosterone_total: 361` (was 577) — fell ~37%
- `nfl: 0.81 pg/mL` — neurodegeneration baseline normal
- `galleri_signal: NO CANCER SIGNAL DETECTED`
- Allergy panel: total IgE 339 (3x upper limit), sensitized to dust mites, alder/birch/oak trees, cat/dog dander, timothy grass

## Phase 1 Status

| Source | Status |
|---|---|
| Whoop, Eight Sleep, Withings, Strava | ✅ |
| Garmin | ✅ (re-auth + 7-day gap-fill tonight) |
| Habitify, Todoist | ✅ |
| Apple Health / HAE | ✅ (32-day backfill + webhook live) |
| Notion | ✅ ("Failure Test" journal entry verified) |
| Function Health 2026 | ✅ (8th draw committed) |
| MacroFactor | 🟡 dormant (no logs to ingest) |

## Tech Debt Carried Forward

10 items numbered TD-11 through TD-20. Highest-priority items:
- **TD-19 [HIGH]** — Cross-source date partition convention mismatch (architectural)
- **TD-15 [HIGH]** — Live HAE Lambda missing source-priority fix (correctness; iPhone+Garmin step double-count today)
- **TD-20 [LOW]** — `platform_logger.py:103` TypeError on every error log line (cosmetic but pollutes logs)

Full list in [HANDOVER_v6.8.1.md](HANDOVER_v6.8.1.md#tech-debt-accumulated-this-session).

## Deferred Work

For fresh-context handoff (write `docs/specs/FUNCTION_HEALTH_V2_HANDOFF.md` next session):

1. Site updates (`site/labs/index.html`) for v2 panels (allergies, NfL, Galleri, Cardio IQ)
2. Supplements page rendering from `Supplement_Protocol_2026-05_v2.md`
3. Free-text clinician notes ingestion strategy
4. Personal + Technical Board consults on FH 2026 findings
5. MCP tool additions: `get_lab_deltas`, `get_allergies`, NfL/Galleri trending cadence

Plus pre-existing:
- Sleep/Glucose Observatory V2 visual overhaul (gated until SIMP-1 Phase 2)
- Coach Intelligence Architecture Phase 1-2 build
- Bedrock migration (assess after 30 days cost data)

## Operational Note

**Garmin re-auth is a recurring ~30-day chore.** OAuth1 refresh token has ~30 day lifetime. As long as Lambda runs daily and refreshes OAuth2, this stays fresh indefinitely. Danger zone: any silence >2 weeks. **Mitigation pattern:** disable Garmin EventBridge rule before any planned silence to prevent rate-limit accumulation. Same pattern applies to Withings and Strava.

## Current System State

| Metric | Value |
|--------|-------|
| Version | v6.8.1 |
| Lambda Layer | v41 (unchanged) |
| Lambdas | 71 (unchanged) |
| MCP Tools | 123 (unchanged) |
| Lab Draws in DDB | **8** (was 7) |
| Total Biomarkers in latest draw | **153** (was 74) |
| Out-of-range biomarkers in latest draw | 26 |
