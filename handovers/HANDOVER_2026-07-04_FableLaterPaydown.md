# HANDOVER — the fable Later pay-down: all 7 model:fable stories — 2026-07-04 (session 11)

Matthew asked to "pay down our issues list based on open items tagged with fable mode"
and authorized merges + deploys in-session. **All seven `model:fable` Later stories are
MERGED + DEPLOYED + LIVE-VERIFIED**: #541 → #539 → #506 → #498 → #550 → #540 → #547
(PRs #572–#574, #596–#604). Layer went **v105 → v109** across the session. Every issue
auto-closed. The fable Later shelf is empty.

---

## What shipped (in ship order)

### #541 Forecast engine (PRs #572, #573)
- `stats_core.ewma_fit/ewma_forecast` — deterministic grid-fit alpha, SES residual
  intervals that widen with horizon; **0.80 joined the supported confidence set**
  (the "did the 80% interval cover 80%?" question is answerable in weeks).
- New `forecast-engine` lambda (16:50 UTC, pre-brief lane): h=1/h=7 expectations for
  recovery/sleep/weight, FROZEN at issue (`SOURCE#forecast`, EXPERIMENT_SCOPED, model
  `ewma-v1`); matured forecasts auto-grade into the **CROSS_PHASE `SOURCE#calibration`
  ledger** (`record_type=forecast_resolution`, `covered`/`abs_error`); running
  interval-coverage stat is `null` until something grades — never invented.
- Coaches: a MODEL EXPECTATIONS block rides the authoritative-facts block in
  `_run_coach_v2_pipeline` — forecast numbers are in the prompt, so ADR-104-allowed
  **by construction**; framing "the model expects", never causal.
- `/api/forecast` + cockpit "the model expects" panel (expected-vs-actual + coverage).
- #573 followed the first live run: intervals now **clamp to physical bounds**
  (a 106.1% recovery ceiling is an artifact, not an expectation).
- Live: 6 forecasts/day issuing; first resolutions land 2026-07-05.

### #539 N-of-1 experiment engine (PR #574, layer v107)
- New shared-layer `experiment_design.py`: design validation (baseline 7–56d, washout
  0–14d, criterion over a 17-metric registry), window derivation, paired analysis
  (`stats_core.bootstrap_mean_diff_ci` + Cohen's d), verdict = supported only when the
  CI excludes zero in the predicted direction AND clears the frozen `min_effect`.
- `create_experiment` accepts `design`, validates at creation (**invalid
  pre-registration is rejected outright**), freezes it with `pre_registered_at`; no
  writer mutates it. `end_experiment` runs the analysis automatically (fail-soft —
  honest state is `analysis=None`, never a guess).
- `/api/experiments` serves design/stamp/analysis; the experiments page renders
  "pre-registered DATE · criterion · effect [95% CI, n/n] → verdict".
- Live drill (read-only, real data): honest inconclusive on a whoop-sparse window —
  n_baseline=1 correctly refused analysis.

### #506 Journal Phase 2 (PRs #596, #597)
- `journal_analyzer` rebuilt: **the per-entry Haiku call is DELETED** — per-day rows
  derive deterministically from pass-1 enrichment (`model=deterministic-v2`);
  `one_line_summary` dropped at the writer (J-8 resolved at the source).
- New registries in `SOURCE#journal_analysis`: `ENTITY_REGISTRY#current`,
  `BEHAVIOR_REGISTRY#current` (with the habitify name-join, #422's free-text side),
  `HYPO_CANDIDATE#{slug}` (verbatim quotes as provenance; cause/effect mapped into
  SPEC_METRICS; unmappable = honest `needs_instrumentation`).
- Hypothesis engine seeds generation from testable candidates (quote provenance in
  the prompt). Coach preamble gains a one-line journal-signals block (honest-when-
  sparse). `/data/mind` + `/api/*` stay aggregate-only — quotes never leave DDB.
- #597: **the live enrichment lists are plain strings** (`["Britt"]`), not the v2 dict
  sketch — builders accept both vintages. Live: 100 entities, 100 behaviors, 50
  candidates (2 testable / 48 needs-instrumentation) from 36 entries.

### #498 Registry-derived enumerations (PRs #598, part of #599; layer v109)
- `source_registry` gains the facets: `active_api`, `best_effort`, `expected_days`,
  `qa_tier`, `method`/`metrics`/`posture` (the review's verdicts), `raw_layout`
  (X-9's three-generation raw-S3 reality documented per source — **no mass-move**),
  `partition`, `freshness`. Weather/supplements/dropbox join as **facet-only** entries
  (`freshness: False` keeps every existing freshness surface byte-identical — pinned).
- Derivations: pipeline_health_check (ACTIVE_API/BEST_EFFORT), qa_smoke tiers (the
  phantom `journal` partition check became `notion`), data_reconciliation source rows,
  `mcp/config.SOURCES` (gains hevy/measurements/food_delivery → MCP get_sources now 23).
- `data_export.ALL_SOURCES` derives from **phase_taxonomy** (the partition census):
  exports gained 14 silently-missing partitions (forecast, calibration,
  engagement_state, travel, mood, …); journal_analysis (cache) + composite_scores
  (removed) correctly dropped; platform_memory + google_calendar kept via extras.
- `site/data/data_sources.json` is **GENERATED** (`scripts/v4_build_data_sources.py`,
  wired into sync_site_to_s3.sh) — hevy finally listed, posture field ships.
- `tests/test_source_enumeration_drift.py` is the linter: consumer lists must be
  registry projections; the CDK alarm tuple pinned by extraction; the JSON by regen.
- CLAUDE.md's raw-path claim corrected.

### #550 Scenario explorer (PRs #599, #600, #601)
- New `scenario-explorer` lambda (12:10 UTC nightly): for 8 curated levers, the
  distribution of **what FOLLOWED** similar days (next-day recovery/sleep/HRV/mood/
  energy) vs other days — block-bootstrap diff CIs, **AR(1) effective-n gate hides
  thin cells at the source**. Day-rows reuse the hypothesis engine's
  `build_data_narrative` (one assembly, ADR-105). Zero AI.
- `/api/scenarios` + `/method/scenarios/` page: lever chips, inline-SVG distribution
  bands, n + n_eff on every cell, anti-causal framing in payload AND copy.
- Live and honest: 32 usable days this cycle → 2 cells shown, 38 hidden as thin.
- Also in #599: **the ops-layer fix** (see gotcha 2).

### #540 Real inter-coach dialogue (PR #602)
- New `inter-coach-dialogue` lambda (Sun 18:00 UTC): **deterministic selector** over
  the ensemble's ACTIVE# topics (cycle_count + strongest influence-graph edge, 4-week
  airing cooldown, stable tie-breaks); two gated in-voice Haiku turns (coach B answers
  coach A's SPECIFIC recorded claim; A gets one rejoinder to what B actually said);
  ADR-104 grounding gate per turn; **≤4 Haiku calls/week hard**; tier≥1 self-pauses;
  ≤1 dispute/ISO-week enforced in-lambda.
- Threads persist at `ENSEMBLE#dispute / THREAD#{week}#{slug}` (EXPERIMENT_SCOPED);
  the ACTIVE# topic gets `last_aired_week` + `dispute_ref`; both coaches'
  state-updaters record it (`output_type=inter_coach_dispute`).
- `/api/coach_team` gains `dispute`; the coaching page renders "the dispute" as turns.
- **Live**: first dispute aired 2026-W27 — Dr. Webb (nutrition) vs Dr. Reyes
  (physical) on caloric adequacy; the rejoinder genuinely concedes a point.

### #547 Podcast v2 (PRs #603, #604)
- Two-pass engine (`lambdas/emails/podcast_script_v2.py`, split for the size gate,
  deps-injected): **Elena writes her half first** (voice + host state + show memory),
  then the guest coach answers Elena's ACTUAL lines in their own voice spec. Exactly
  2 writer calls; output contract identical to v1 → **every downstream gate (per-line
  ER-03, safety, QA + revisions, HOLD, human-in-loop) untouched**; any v2 failure
  falls back to v1.
- `SHOW#memory` ledger (panelcast partition): callbacks + guest history from real
  records; ≥1 callback prompted when material exists. Dispute segments cite the real
  record (#540 threads + live ACTIVE# topics) — invented banter has no fuel path.
- Live dry-run: week-3 episode → **would PUBLISH, 17 clean turns** through the whole
  v2 chain.

---

## Gotchas learned (the expensive ones)

1. **Single-file hot deploys strip sibling modules.** `deploy_lambda.sh` (and CI's
   deploy stage) package ONLY the handler file. Three classes bit us in one session:
   (a) qa-smoke/data-reconciliation/data-export had NO shared layer, so the #498
   `source_registry`/`phase_taxonomy` imports died after CI's hot deploy → all three
   now carry the shared layer, and **phase_taxonomy joined the layer (v109)**;
   (b) scenario-explorer imports its compute sibling → flagged `cdk_only` in
   lambda_map; (c) coach-panel-podcast imports podcast_script_v2 → flagged `cdk_only`.
   Reflex: **a lambda that imports a non-layer sibling must be `cdk_only`.**
2. **Package-aware sibling imports** — twice in one session: a handler that runs as
   `compute.x_lambda` / `emails.x_lambda` cannot `import sibling` flat; use
   `try: from <pkg> import sibling / except ImportError: import sibling` (the flat
   branch keeps the test harness working).
3. **The CDK asset-staging glitch struck the MCP stack**: the S3 asset object under
   the content hash was an incomplete zip (46 files, no `reading/`), while the local
   staged dir was complete — so `cdk deploy` forever said "no changes" and never
   re-uploaded. Fix: **delete the S3 asset object**
   (`cdk-hnb659fds-assets…/<hash>.zip`), redeploy (re-uploads), then
   `aws lambda update-function-code --s3-bucket … --s3-key <same key>` because CFN
   sees no template change and won't refresh the function itself. Verify by
   downloading `Code.Location` and listing the zip.
4. **CI's layer-consistency Plan check races a manual fleet deploy** — publish the
   layer + re-attach consumers promptly after merge; the next CI run goes green.
5. **`gh pr merge` right after a force-push returns "not mergeable"** — GitHub is
   still computing mergeability; re-check `mergeStateStatus` and retry.
6. **DLQ during fleet redeploys**: a scheduled event can land while its function is
   updating → 1 message in the ingestion DLQ → I9 red. Transient class; drain it
   (receive+delete) once the fleet settles.

## Pre-existing local failures (NOT this session's)
- `tests/test_coaches_api.py` (4) + `tests/test_integration_aws.py` (subset) fail on
  a clean HEAD locally (env-dependent); green in CI.
- `tests/test_hevy_compiler_isolation.py` fails locally because **stale worktrees
  live under `.claude/worktrees/`** (ds-health-review, honesty-pair,
  v5-coherence-redesign) and the scan walks into them. They look finished — Matthew
  should confirm + `git worktree remove` them.

## Watch
- **Sun 07-06**: first scheduled runs — hypothesis engine v2 now seeded with journal
  candidates; inter-coach-dialogue will SKIP (2026-W27 already aired via the drill);
  weekly panelcast uses the v2 two-pass engine (human-in-loop HOLD flow unchanged).
- **Mon 07-07 07:00 UTC**: data-reconciliation first run on derived source rows.
- **From 07-05**: forecast resolutions start writing `forecast_resolution` rows into
  the calibration ledger; the cockpit coverage line switches on once n≥1.
- `/api/journal_analysis` shows an honest empty (no journal entries since 05-25) —
  expected, not a regression.
- Build dispatch (#380) for this batch NOT yet distilled — one public beat covering
  the forecast engine + scenario explorer + the dispute would be the natural pick.

## Next
- #535 uncertainty-everywhere (tools_correlation's n=5 HARMFUL labels deliberately
  left for it), #538 calibration scoreboard (ledger rows now accruing from TWO
  engines — hypotheses AND forecasts), #543 personal thresholds, #545 voice-fidelity
  harness. The uplevel roadmap (#575–#595, filed by the concurrent session) is
  untouched.
