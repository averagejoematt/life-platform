# HANDOVER — the data-truth batch: #486/#488/#491/#492/#495/#496 shipped end-to-end — 2026-07-04 (session 6)

**Six Now stories merged, deployed on layer v100, and live-verified — surfaces and
engines tell the truth about the data they actually have.** PRs **#520** (the batch)
and **#521** (v100 pin). Issues #486/#488/#491/#492/#495/#496 auto-closed;
**7 `area:data` Now stories remain.**

---

## What shipped (PR #520, 23 new tests in `test_data_truth_batch.py`)

- **#491 (M-5/M-6)** — ONE shared `weight_trend.latest_weight()` (withings backscan
  + 7-day apple_health window; kg→lbs conversion folded in) replaces the three
  divergent resolutions in vitals / journey / character-sheet. The old apple
  fallback inspected only the single latest item (usually a steps record) — dead
  except same-day. `/api/last_sync` now includes withings; `evidence.js`
  date-conditions the labels (`todayPT()` helper): /data/results says
  "latest · Jun 26" when stale, /data/physical only says "yesterday" when the
  previous reading truly is yesterday's.
- **#492 (M-4/M-7)** — `compute_readiness` returns its inputs; stored as
  `readiness_components` in computed_metrics; `_latest_readiness` serves them and
  serves NONE for pre-#492 records (never the day-grade set). Cockpit zero-caption
  reworded (a 0 is a reading now, not a "quiet day"). `device_agreement` always
  explains an absent cross-check (`{status: unavailable, reason: garmin paused
  (ADR-074)…}`) in both the readiness tool and the standalone tool; registry
  description weights corrected 35/10 → 40/5.
- **#495 (M-9)** — sleep_detail substitutes ONLY the recovery trio (was: the whole
  whoop record — night-A hours + night-B stages under one header) and carries
  `recovery_night_of`; evidence.js captions the splice in all three sections that
  render the trio.
- **#486 (B-3/D-2)** — character engine reads `blood_glucose_time_in_range_pct`
  (the written name); `body_fat_trajectory` REMOVED from engine + config (scale is
  weight-only — 0/1198 records ever had the fields; weights redistributed
  cgm .3 / labs .4 / bp .15 / rhr .15); dead `_compute_body_comp_deltas` deleted
  from withings_lambda; nutrition_review's `extract_cgm` was dead END-TO-END (all
  five reads) — repointed to `blood_glucose_*`.
- **#488 (A-5/A-6)** — hypothesis_engine reads `sleep_duration_hours` + `bed_temp_f`;
  whoop `_compute_sleep_consistency` now key-bounds the real 7-day window and skips
  `#WORKOUT#` sub-records (verifier had found 5 of 6 returned items were workouts).
- **#496 (C-3)** — `DECLARED_PAUSED_SOURCES = set()` (strava live since 06-20);
  qa_smoke: strava moved PAUSED→OPTIONAL. test_di1 posture tests now assert the
  new posture; the paused *mechanism* tests pin a synthetic entry via monkeypatch.

## Deploy (all live 2026-07-04, in-session merge+deploy approval carried over)

CONVENTIONS §1: build → Core published **v100** → pin merged (#521) → Ingestion,
Compute, Email, Mcp, Operational from main (clean diffs: layer 99→100 + code zips)
→ site-api via `deploy_site_api.sh` → site synced. **S3 config updated**:
`config/matthew/character_sheet.json` — diffed live vs repo FIRST (only our change
differed; backup in session scratchpad), then uploaded. Asset check: all deployed
zips + the v100 layer zip grep-verified for the fix markers (note: zip entries are
`compute/…`, `ingestion/…`, `mcp/…` — not root-level).

## Live verification

- `/api/vitals` + `/api/journey`: weight 301 · as_of **2026-06-26** (the exact M-5
  scenario, now honest); `/data/physical/` renders **"LATEST · JUN 26"**, no
  "yesterday" figure.
- `/api/last_sync`: withings present (last write 06-26) beside whoop/8sleep/HAE.
- daily-metrics-compute invoked → `readiness_components` stored (recovery .4 /
  sleep .25 / hrv_trend .2 / tsb .1); cockpit renders the four real inputs + new
  caption.
- character-sheet-compute invoked → pillar_metabolic has the 4-component set, no
  body_fat_trajectory; live coverage 0.15 (real absence: no CGM/BP/fresh labs —
  the honest number, not the structural cap; 1.0 full-data case pinned in tests).
- `/api/sleep_detail`: `recovery_night_of` served (null today — nights matched).
- pipeline-health-check invoked → **paused: 0** (strava counted again); the 1
  failure is pre-existing #518 (dropbox secret). `/api/source_freshness`: strava
  = `behavioral-stale` (honest — no workouts logged, not "paused").
- Visual QA: /now/, /data/sleep/, /data/physical/ all pass.

## Gotchas for the next session

- **Deployed-zip verification paths**: lambda zips nest by package dir
  (`compute/`, `ingestion/`, `emails/`, `mcp/`, `operational/`) — grepping the
  root filename silently returns 0 matches (looked exactly like the CDK
  asset-staging glitch; it wasn't).
- `config/matthew/character_sheet.json` in S3 is runtime-mutable
  (update_character_config MCP tool) — ALWAYS diff live vs repo before upload.
- test_last_sync pinned the sync-source set; test_di1 pinned the paused posture —
  posture pins live in tests, so a posture change is also a test change (good).
- Known env-dependent local failures unchanged: coaches_api ×4,
  hevy_compiler_isolation, integration_aws (fails on clean main too).

## Open / next

- **7 `area:data` Now stories remain**: #473 (measurements re-arm), #474
  (apple_health XML decision — the opus one), #477 (habitify finalize), #480
  (supplement merge + validator truth), #481 (eightsleep token persist), #482
  (phase-tag standalone writers), #497 (garmin cron coherence).
- **#518** still open (dropbox secret misfire — red daily in pipeline-health-check).
- Watch (from session 5): `slo-source-freshness` 7-day OK window counting from
  07-04; `ingest-reconciliation-strava` should be OK by 07-05.
- Cockpit "training balance 0" is real TSB output — C-5 (kJ-vs-TSS scale) is the
  open story behind it, not a #492 regression.
