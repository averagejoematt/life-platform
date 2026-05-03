# Handover — v6.8.1: Phase 1 Source Restoration + FH 2026 Ingest

**Date:** 2026-05-02 (session ran into early hours of 2026-05-03 UTC)
**Scope:** Restore platform pulse after 4-week silence (April 2 → May 2). Ingest Function Health 2026 lab draw (8th draw, 153 biomarkers). Re-auth Garmin. Backfill 27-day Apple Health gap. Document accumulated tech debt.
**Type:** Operational restoration, not feature work. No new product capabilities; system returned to baseline + one major lab draw added.

## TL;DR

Platform was silent April 2 to May 2 during Matthew's mid-March move. Tonight: walked through 11 ingestion sources, 10 verified working end-to-end, 1 dormant (MacroFactor — no logs to ingest, not a pipeline failure). Function Health 2026 draw committed to DDB at `DATE#2026-04-03` with 153 biomarkers across three source PDFs (standard panel, Cardio IQ + NfL, Galleri). 26 biomarkers out-of-range. Headline finding: **Cardio IQ Insulin Resistance Score 75 — definitively insulin resistant** (>66 cutoff). Garmin OAuth was rate-limited (429 at SSO exchange) after the silence — fixed via `setup/setup_garmin_browser_auth.py`, gap-fill backfilled 7 missing dates. Apple Health backfill ran cleanly via `backfill_apple_health_export_v16.py` (32 days, 0 errors).

Platform is ready for Monday May 4 soft re-launch. Site rebuild work for FH v2 deferred to a fresh-context handoff doc (see "Deferred work" section).

---

## What Changed

### 1. Function Health 2026 lab draw ingested

**New artifacts in repo:**
- `backfill/draw_2026_04_03.py` — structured biomarker dictionary, 153 biomarkers, 1015 lines
- `backfill/ingest_function_health_2026_04_03.py` — one-off ingest script with validation gate, dry-run mode, interactive commit prompt

**Architecture decision:** Hybrid extraction. Claude (this session) read all three PDFs and emitted structured Python dicts directly into `draw_2026_04_03.py`. The ingest script is a thin wrapper that does deterministic DDB write + S3 archive. This was preferred over building a regex parser because:

1. The Quest layout has multi-line biomarker names (allergy panel), inline footnote ranges, and multi-page panels with re-printed page headers. Regex was estimated at 90-120 min and high error risk.
2. This is a **one-off ingestion**, not a recurring pipeline. The August 2026 retest will have its own ingestion. By then the schema is settled and a parser can be written if recurring ingestion is desired.
3. Validation gate against `Supplement_Protocol_2026-05_v2.md` reference values catches any extraction errors before write.

**Schema:** Single DDB item under `pk = USER#matthew#SOURCE#labs`, `sk = DATE#2026-04-03`. Item size 38 KB serialized (well under 400 KB limit). Three separately-collected panels merged: standard panel collected 04/03, Cardio IQ + NfL collected 04/01, Galleri collected 04/02 — each biomarker carries `panel_collected` for traceability.

**Headline findings:**
- `insulin_resistance_score: 75` (Cardio IQ; cutoff >66 = insulin resistant). Combines fasting insulin 14.3 (5.7x rise from 2.5 last year) and elevated C-peptide 2.26.
- `apob: 116` standard, `apob_cardio_iq: 111` (different assays). Both flagged high (target <90).
- `lp_pla2_activity: 137` (>123 cutoff) — vascular-specific inflammation alongside hs-CRP 1.4.
- `omega_3_index: 3.3%` — failed repletion despite supplementation (was 7.8% last year).
- `vitamin_d_25oh: 28` — dropped from 117 to 28 ng/mL into deficient range.
- `testosterone_total: 361` — fell from 577 ng/dL.
- `nfl: 0.81 pg/mL` — neurodegeneration baseline normal.
- `galleri_signal: NO CANCER SIGNAL DETECTED`.

**Out-of-range count: 26 biomarkers.** Full list available via `life-platform:get_labs view=results`.

**S3 archive paths** (all written to `s3://matthew-life-platform/raw/matthew/labs/2026-04-03/`):
- `standard_panel.pdf`
- `cardio_iq_nfl_panel.pdf`
- `galleri_corrected.pdf` (canonical Quest-mediated corrected version)
- `galleri_grail_original.pdf` (patient-facing GRAIL original)
- `clinician_notes.pdf` (qualitative — not yet ingested as structured data)
- `function_data_trends.pdf` (Function platform's own trends export — qualitative)
- `supplement_protocol_v2.md`

**Critical context for the Cardio IQ panel:** The PDF labeled `Lab Results of Record (4).pdf` was originally tagged as "NfL panel only" in earlier session notes, but it is actually a **10-panel Cardio IQ comprehensive cardiometabolic suite** with NfL embedded as one panel. Missed during prior triage; caught and ingested fully tonight. The 15 Cardio IQ biomarkers (Insulin Resistance Score, Lp-PLA2, ApoE evaluation, HDL Function, Fibrinogen, Adiponectin, MPO, TMAO, etc.) are the most diagnostically meaningful additions in the v2 panel — they convert the "rising insulin trend" into a clinical IR diagnosis.

### 2. Garmin pipeline restored

**Failure mode:** OAuth1 token expired during the 27-day silence. Lambda's auto-refresh attempts hit 429 at `connectapi.garmin.com/oauth-service/oauth/exchange/user/2.0` because the refresh endpoint itself was rate-limited from repeated cron-driven retries.

**Fix:** Ran `setup/setup_garmin_browser_auth.py` (Playwright-based browser auth — Garmin actively blocks non-browser clients via Cloudflare TLS fingerprinting since March 2026). Manual login + MFA in spawned Chromium → fresh OAuth1 + OAuth2 tokens written to `life-platform/garmin` Secrets Manager.

**Verification:**
1. Single-date test invoke: `{"date": "2026-03-30"}` → `{"fields_written": 21}` ✅
2. Default gap-fill invoke: `{}` → `{"mode": "gap_fill", "gaps_found": 8, "gaps_filled": 7}` ✅
3. Backfilled dates: 2026-04-26 (37 fields), 04-27 (37), 04-28 (37), 04-29 (37), 04-30 (11), 05-01 (4), 05-02 (16). 05-03 returned 0 fields (watch hadn't synced today yet at time of run).

**Token lifetimes:** OAuth2 access ~83,722s (23 hrs, auto-refreshes); OAuth1 refresh ~30 days. The Lambda will auto-refresh OAuth2 on every cron run as long as OAuth1 remains valid. Re-auth will be needed approximately every 30 days of continuous data flow, OR any time the platform is silent long enough that the refresh endpoint rate-limits us.

### 3. Apple Health backfill — 27 day gap closed

**New artifact:** `backfill/backfill_apple_health_export_v16.py` (v16.1 source-aware)

**Discovery during dev:** iOS Health export.xml has source-duplication. Multiple devices write the same metric type:
- iPhone + Garmin both write `HKQuantityTypeIdentifierStepCount`
- "My Water" + MacroFactor both write `HKQuantityTypeIdentifierDietaryWater`
- Water units are mL in export.xml, not fl_oz as METRIC_MAP assumed

**Fix:** `SOURCE_PRIORITY` dict in v16.1 picks canonical source per metric. Run command: `python3 backfill/backfill_apple_health_export_v16.py --since 2026-04-01`. Result: 32 days backfilled, 0 errors.

**HAE webhook independently verified working** post-recovery via `/aws/lambda/health-auto-export-webhook` logs — successful 200s for all 8 feeds.

### 4. Other source verifications (all passed)

- **Whoop** ✅ — latest record 2026-05-02, full sleep/recovery/HRV
- **Eight Sleep** ✅ — latest record 2026-05-02
- **Withings** ✅ — re-auth via `setup/fix_withings_oauth.py` had been done in pre-session prep
- **Strava** ✅
- **Habitify** ✅ — "Weigh In" canary habit confirmed
- **Todoist** ✅ — 200 active tasks, 278 overdue (expected after silence)
- **Notion** ✅ — verified end-to-end with a test journal entry titled "Failure Test", body text/template/properties all captured cleanly
- **Weather** ✅ — daily ingestion running

### 5. MacroFactor — dormant, not failed

No food or workouts were logged during the 4-week silence, so the Dropbox-sync pipeline has nothing to ingest. Validating the empty case wasn't worth the round-trip — the pipeline is the same architectural pattern as Notion (file-watcher → DDB write), and Notion was just verified working with the test entry. **First real CSV export after Matthew resumes logging will be the implicit smoke test.** If that doesn't appear in DDB within 24 hours, then we investigate.

---

## Critical Architectural Finding — TD-19

**Severity: HIGH** (architectural, not yet causing visible damage but will silently miscount as more sources come online)

**The bug:** Different sources use different date partition conventions when writing to DDB. Specifically:

- HAE Lambda (Apple Health webhook) uses **local-PT-midnight partitions**. Today's data lands at `DATE#<PT-local-date>`.
- Withings uses **UTC-midnight partitions**. Today's data lands at `DATE#<UTC-date>`.

The two can disagree on which calendar date a given event belongs to. Same wall-clock day → two different DDB partitions → daily intelligence aggregation will silently undercount whichever source is on the "wrong" partition for the question being asked.

**How it was discovered:** While verifying the HAE webhook was working, the today's `apple_health` row at `DATE#2026-05-03` was missing from MCP queries, but the Lambda logs showed it had successfully written. Direct DDB query revealed the row existed at `DATE#2026-05-02` (PT-local midnight) — the other sources had already advanced to `DATE#2026-05-03`.

**Why this matters more later than now:** With one or two sources misaligned, daily aggregation just shows partial data. As more sources come online and the platform leans on cross-source correlation (e.g. correlating Apple Health step count with Whoop strain on the same day), the bug will produce systematically wrong correlations rather than visible missing-data warnings.

**Not fixed in this session.** Documented as TD-19 below for prioritization.

---

## Tech Debt Accumulated This Session

Carry-forward list. Numbering continues from the existing TD-* sequence. Severity: HIGH = ship blocker for v2 site, MED = correctness risk, LOW = annoyance.

### TD-11 [MED] — Habitify writes 65 phantom-failed habits per day
The full habit registry of 65 is written daily as `0.0` even when the user hasn't completed any. Distinguishing "not done yet" from "actively skipped" matters for streak calculation. **Strategic — not a quick fix.** Touches Habitify Lambda + scoring engine + Habitify completion-API contract.

### TD-12 [LOW] — Todoist Lambda phantom no-op invocations every 4hr
Cron fires every 4 hours; Lambda has no-op gate that returns early if no changes since last run. This means we burn 6 invocations/day with no work. Either reduce schedule to daily, OR add EventBridge throttle, OR use Todoist webhooks (preferred long-term).

### TD-13 [LOW] — No central secret-name reference
Discovered Todoist's API key actually lives at `life-platform/ingestion-keys` not `life-platform/todoist`, requiring code archaeology to find. Need a single config doc mapping every source → secret name.

### TD-14 [MED] — Backfill scripts drift from live Lambdas
`backfill_apple_health_export_v16.py` has the source-priority fix; the live HAE Lambda does NOT. If we have to backfill again from the same export.xml, results are correct. If new HAE webhooks fire today, they have the bug. **Same root cause as TD-15.**

### TD-15 [HIGH] — Live HAE Lambda has source-duplication bug fixed in backfill
The live `health-auto-export-webhook` Lambda doesn't have the `SOURCE_PRIORITY` dict from v16.1. Today's webhook traffic is silently inflating step counts (iPhone + Garmin double-count) and miscalculating water (mL vs fl_oz). Fix: port the SOURCE_PRIORITY logic into the live Lambda. Should be a one-file change.

### TD-16 [MED] — Apple Health "Connect" (Garmin-via-AppleHealth) inflates activity ~2x
Garmin syncs to Apple Health, which then writes to its export.xml under a non-iPhone source name. Without the source filter, we'd be counting Garmin steps in both the apple_health and garmin partitions. The backfill script fixes this; the live Lambda does not (TD-15).

### TD-17 [LOW] — HAE Tier 2 feeds (HR/RHR/SpO2) drop 100% of payloads
Whoop is the source of truth for these; HAE Lambda correctly filters them out. But the upstream Health Auto Export iOS app keeps sending them, wasting Lambda invocations. Either disable those feeds in the iOS app config, OR add a fast-reject path in the Lambda. **Cosmetic, not correctness.**

### TD-18 [LOW] — HAE weight feed name mismatch
Live Lambda's METRIC_MAP expects `body_mass`; iOS export sends `weight_body_mass`. Weight is currently captured fine because it's the only feed where `weight_lbs_apple` is also written, but the field-mapping is fragile.

### TD-19 [HIGH] — Cross-source date partition convention mismatch (UTC vs local-PT)
**See "Critical Architectural Finding" above.** This is the highest-priority architectural issue from tonight. Recommended approach: pick one convention (UTC seems cleanest) and audit/fix every Lambda's date-keying logic. Will require a one-time backfill rewrite for any source currently on the wrong convention.

### TD-20 [LOW] — `platform_logger.py` TypeError on exception formatting
Surfaced by Garmin OAuth failures: every error log line spawns a secondary traceback `TypeError: 'bool' object is not subscriptable` at `platform_logger.py:103` in `formatException()`. The original `logger.error("...", exc_info=True)` is passing `True` where `sys.exc_info()` tuple is expected. Cosmetic but pollutes log streams and makes real errors harder to read.

---

## Out-of-range biomarkers from FH 2026 (full list)

For reference. All accessible via `life-platform:get_labs view=results` after MCP refresh.

**Allergies (9):**
- `allergy_dust_mite_d_pteronyssinus`: 4.85 kU/L (Class 3 high)
- `allergy_dust_mite_d_farinae`: 3.06 kU/L (Class 2 mod)
- `allergy_alder`: 5.08 kU/L (Class 3 high)
- `allergy_birch`: 5.07 kU/L (Class 3 high)
- `allergy_oak`: 1.64 kU/L (Class 2 mod)
- `allergy_timothy_grass`: 0.68 kU/L (Class 1 low)
- `allergy_cat_dander`: 0.63 kU/L (Class 1 low)
- `allergy_dog_dander`: 0.60 kU/L (Class 1 low)
- `allergy_total_ige`: 339 kU/L (3x upper limit)

**Lipids (8):**
- `cholesterol_total`: 243 mg/dL
- `ldl_c`: 163 mg/dL
- `non_hdl_c`: 185 mg/dL
- `apob`: 116 mg/dL (standard panel)
- `apob_cardio_iq`: 111 mg/dL (Cardio IQ assay)
- `ldl_particle_number`: 2128 nmol/L
- `ldl_small`: 352 nmol/L
- `ldl_medium`: 611 nmol/L
- `hdl_large`: 6504 nmol/L (low)
- `ldl_peak_size`: 221.0 Angstrom (low)

**Metabolic / inflammation (6):**
- `insulin_resistance_score`: 75 (HEADLINE FINDING)
- `c_peptide`: 2.26 ng/mL
- `crp_hs`: 1.4 mg/L
- `lp_pla2_activity`: 137 nmol/min/mL
- `omega_3_index`: 3.3% (low)
- `vitamin_d_25oh`: 28 ng/mL (low)

**Other:**
- `amylase`: 18 U/L (low — has been low historically, not new)

---

## Deferred Work — for fresh-context handoff

These items were flagged in Matthew's original 7-step scope for the FH v2 work but were scoped out of tonight's session because the priority was "platform pulse before Monday." A separate handoff doc — `docs/specs/FUNCTION_HEALTH_V2_HANDOFF.md` — should be written next session to scope these for Claude Code execution.

### Site updates (`site/labs/index.html`)
The labs page has 7 historical draws rendered. Adding the 8th (2026-04-03) needs:
- Conditional rendering for the new biomarker categories: allergies, NfL, Galleri, Cardio IQ panels
- Chart series for the high-trend biomarkers (insulin, T, omega-3 index, ApoB, GGT, vitamin D)
- New panel-of-panels visualizer for the Cardio IQ insulin resistance score with the <33 / 33-66 / >66 threshold bands

### Supplements page rendering
`Supplement_Protocol_2026-05_v2.md` is in S3 but not yet rendered as a page on averagejoematt.com. Need to decide on:
- Public vs private (likely private given it discusses specific dosages and clinical context)
- Whether to render as static page or build a "supplement tracker" widget that ties to Habitify completion data

### Free-text clinician notes ingestion
`clinician_notes.pdf` is in S3 but not parsed. Options:
- LLM-based structured extraction (Claude Haiku in a small Lambda) → "recommendations" structured JSON
- Manual one-time extraction now, automated for future draws
- Skip structured extraction, just surface as a downloadable artifact

Recommend deferring decision until v2 site is built — surface the PDF as a download first, and only build extraction if the surface needs it.

### Board consult on the FH 2026 findings
Two boards:
- **Personal Board of Directors** (Attia, Lustig, etc.) on the IR diagnosis and atherogenic lipid pattern. Specifically whether to escalate to statin/PCSK9 conversation or buy more time with metformin + lifestyle.
- **Technical Board of Directors** on the observatory rendering for the new test categories. Particularly whether to surface allergy results at all (they're real but not actionable in the Life Platform's optimization loop).

### MCP tool additions for cross-draw delta queries
The existing `get_labs` shows latest values + per-biomarker trends, but there's no tool that says "show me everything that moved more than 1.5x year-over-year." With 8 draws, this becomes a useful surface. Spec:
- `life-platform:get_lab_deltas year_over_year=True threshold=1.5` → list of biomarkers with % change exceeding threshold
- Optional allergy-specific surface `life-platform:get_allergies` (since allergy panel has different semantics — IgE class is ordinal, not continuous)
- NfL trending cadence — should it be quarterly? annually? — needs board input
- Galleri tracking — annual cadence assumed; should we surface "days since last Galleri" anywhere?

### Sleep / Glucose Observatory V2 visual overhaul (independent of FH work)
Pre-existing work item. Apply editorial pattern from Nutrition/Training/Mind observatories. Gated until after SIMP-1 Phase 2 (MCP tool consolidation to ≤80 tools, ~April 13 window) to avoid merge conflicts.

### Coach Intelligence Architecture Phase 1-2 build (also pre-existing)
- Coach State Store in DynamoDB
- Narrative Orchestration Layer
- Cross-Coach Ensemble
- See R19 review notes for full scope

### Bedrock migration
Tech Board voted 5-1-3 in favor long-term; defer until 30 days of cost data collected. Currently using Anthropic API direct (hit credit exhaustion in v6.8.0 era).

---

## Operational Notes for Future Self

### Garmin re-auth: ~30 day cadence

The OAuth1 refresh token has a ~30 day lifetime. As long as the Lambda is running daily and successfully refreshing OAuth2 (which it does on every invocation), this stays fresh indefinitely. **The danger zone is any silence longer than 30 days** — at that point, the OAuth1 refresh token expires AND the Lambda's repeated retry attempts trigger the Garmin SSO endpoint's rate limit, leading to the 429 chicken-and-egg observed tonight.

**Mitigation pattern:** If the platform will be silent for >2 weeks, manually disable the Garmin EventBridge rule before the silence begins. This prevents the rate-limit accumulation. Re-enable + run the browser auth on return.

### Withings has the same re-auth pattern

Withings re-auth was done in pre-session prep via `setup/fix_withings_oauth.py`. Same architectural shape as Garmin: long silence → token expires → manual re-auth → resume.

### Strava also has the same pattern

Already verified working tonight, but follows the same pattern. Watch for it on extended silences.

### Apple Health backfill is the safety net

If anything in the Apple Health pipeline goes sideways, the iOS export.xml file regenerates whenever Matthew exports it from the Health app. The v16.1 backfill script can re-run from any historical export. This is the platform's most resilient ingestion path because it's idempotent and doesn't depend on a 3rd-party token.

### The Cardio IQ panel was almost missed

Earlier session triage labeled `(4).pdf` as "NfL panel" only, missing 9 of its 10 panels. **Lesson:** when a Function Health PDF has more pages than expected (this one was 27 pages), don't trust file-name-derived assumptions about content. Run `pdftotext -layout` and grep for `Collected:` to find all panel headers before extraction.

### MCP tool count in this session

123 tools (no change — no new tools added or retired). SIMP-1 Phase 2 consolidation work targeting ≤80 still pending.

---

## Verification Commands for Next Session

If returning to this work cold, these commands confirm everything still healthy:

```bash
# Source freshness (should show recent ingested_at for each)
# Run via MCP:
# life-platform:get_daily_snapshot view=latest

# FH 2026 draw still in DDB
# life-platform:get_labs view=results
# → expect total_draws=8, latest=2026-04-03, total_biomarkers=153

# Garmin pipeline alive
aws logs tail /aws/lambda/garmin-data-ingestion --since 1h --region us-west-2

# HAE webhook alive
aws logs tail /aws/lambda/health-auto-export-webhook --since 1h --region us-west-2

# DDB row count for labs
aws dynamodb query --table-name life-platform --region us-west-2 \
  --key-condition-expression "pk = :pk" \
  --expression-attribute-values '{":pk":{"S":"USER#matthew#SOURCE#labs"}}' \
  --select COUNT
# → expect 8
```

---

## Files Touched This Session

### New files
- `backfill/draw_2026_04_03.py` (1015 lines) — structured biomarker data
- `backfill/ingest_function_health_2026_04_03.py` (293 lines) — FH 2026 ingest script
- `backfill/backfill_apple_health_export_v16.py` (v16.1 source-aware)
- `backfill/survey_apple_health_gap.py` — diagnostic helper

### Modified files (DDB only — no code changes)
- `life-platform` table: 1 new item at `pk = USER#matthew#SOURCE#labs / sk = DATE#2026-04-03`
- `life-platform/garmin` Secrets Manager secret rotated
- 32 days of `apple_health` records backfilled
- 7 days of `garmin` records backfilled (gap-fill)

### S3 uploads
- `s3://matthew-life-platform/raw/matthew/labs/2026-04-03/` — 7 artifacts (3 lab PDFs + 2 qualitative PDFs + supplement protocol .md + GRAIL original PDF)

### No code shipped to Lambdas this session
- All Lambda code unchanged
- No CDK deploy
- No CI/CD pipeline runs

---

## Phase 1 Source Restoration Tally

| # | Source | Status | Note |
|---|---|---|---|
| 1 | Whoop | ✅ | Latest 2026-05-02 |
| 2 | Eight Sleep | ✅ | Latest 2026-05-02 |
| 3 | Withings | ✅ | Re-auth done pre-session |
| 4 | Strava | ✅ | |
| 5 | MacroFactor | 🟡 dormant | No logs to ingest. Will smoke-test on first real export. |
| 6 | Garmin | ✅ | Re-auth + 7-day gap-fill tonight |
| 7 | Habitify | ✅ | "Weigh In" canary verified |
| 8 | Todoist | ✅ | 200 active / 278 overdue |
| 9 | Apple Health / HAE | ✅ | 32-day backfill + webhook live |
| 10 | Notion | ✅ | "Failure Test" journal entry verified |
| 11 | Function Health 2026 | ✅ | 8th draw, 153 biomarkers, 26 OOR |

**Phase 1 verdict: 10 of 11 verified, 1 dormant-but-not-broken. Platform has a pulse.**

---

## Next Session Triggers

When Matthew next types "Life Platform" the trigger handover ritual should:
1. Read this file (`HANDOVER_LATEST.md` → this content)
2. Brief on: TD-19 (cross-source partition mismatch) is highest-priority pending item; FUNCTION_HEALTH_V2_HANDOFF spec is the next big writing task; MacroFactor smoke test pending Matthew's first food log
3. Confirm Garmin pipeline still healthy (single MCP query)
4. Confirm Function Health 2026 draw still queryable

If Matthew says "let's do the FH v2 site work," start by writing `docs/specs/FUNCTION_HEALTH_V2_HANDOFF.md` per the "Deferred Work" section above. Don't try to do the work in-session unless explicitly requested — it's larger than a single session.

If Matthew says "let's tackle tech debt," prioritize TD-19 (architectural risk) over TD-15 (correctness risk in HAE Lambda) over the rest.
