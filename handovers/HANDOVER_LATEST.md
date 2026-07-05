# HANDOVER — the rigor trio ships: uncertainty, calibration, commitments + data-health + the parse gate — 2026-07-05 (session 15)

Session opened on "do all the highest value opus items in the issues list," with Matthew
authorizing **all merges and deploys** for the session up front, then extending to "do both
follow-ups and the next tier of opus items that don't have prereqs," then "do all of that so I
can exit this session." Everything below is **merged to main, deployed, and live-verified.**

The unblock that shaped the session: most flagship opus items are gated on sonnet prerequisites
(#377 parse gate, #544 methods registry) — but **stats_core (#529) was already shipped**, which
unblocked the three highest-value opus items in the intelligence roadmap. Those shipped first,
then the two follow-ups, then a self-contained data-health opus item, then the parse-gate prereq.

---

## What shipped (8 PRs: #624–#631)

1. **#532 — Coach commitments & follow-through** (opus, epic #526 rank 4 · PR #625). Every
   concrete recommendation a coach pushes becomes a tracked `COMMITMENT#` record (Haiku-extracted
   in `coach_state_updater`, like `PREDICTION#`) with a due window + a deterministic
   follow-through check. The daily `coach_prediction_evaluator` grades the metric-backed ones
   kept/broken by reusing the directional evaluator (zero new AI); the orchestrator injects due
   commitments so a coach must revisit its own advice + a kept/broken tally. `SCHEMA.md` documents
   `COMMITMENT#`.

2. **#535 — Uncertainty everywhere it's claimed** (opus, epic #525 rank 7 · PR #624 · layer v110).
   (a) `weight_trend` rate gets a moving-block-bootstrap CI and the goal date becomes an honest
   **range**; live on `/api/journey` (`weekly_rate_ci_low` verified populated once site-api hit
   v111 — see gotcha #1). (b) `_compute_slow_drift` recomputed as an SE-based z on the
   AR(1)-corrected effective n, gated on effect≥0.5 SD AND p<0.05. (c) the six correlation labeling
   copies collapsed into one `helpers.correlation_report` — r [CI], effective n, per-tool BH-FDR
   q-value, and HARMFUL/BENEFICIAL asserted only at `compute_confidence ≥ MEDIUM` (else
   INCONCLUSIVE). On the current thin post-reset data almost everything correctly reads
   INCONCLUSIVE — that's the point.

3. **#538 — The calibration scoreboard** (opus, epic #528 rank 10 · PR #626 · layer v111). New
   `stats_core.brier_score`/`brier_skill_score`/`reliability_bins`; new **`calibration_core`** layer
   module (the ONE scorer — pairs from resolved `PREDICTION#` + the hypothesis `CALIB#` ledger);
   `compute_credibility` rewired to consume it. Public page **`/method/calibration/`** + `/api/calibration`
   (per-coach Brier + platform aggregate + reliability curve); the coach track-record MCP tool and
   `/api/coach_team` huddle carry the same numbers. Empty today (`n:0`) — no forward call has
   resolved post-reset yet; the empty-state copy says so.

4. **Follow-up: `deploy_site_api.sh` durable layer sync** (PR #627). See gotcha #1.

5. **Follow-up: build-log beat** (PR #627) — "The platform grades its own predictions, in public,"
   leading with #538. Live on `/story/build/`. `content_policy_scan.py` PASS.

6. **#468 — HAE per-datatype liveness + alert dedup** (opus, Next · PRs #628/#629/#630). **D-4:**
   every HAE datatype (CGM/BP/SoM/workouts/water/steps) lands in the ONE `apple_health` partition,
   so a single "fresh" hid a months-dark sensor. The freshness-checker now derives per-datatype
   last-seen, stores a `DATATYPE_LIVENESS` sentinel, and `/api/source_freshness` surfaces it. **Live
   result: CGM dark 43 days, BP & State of Mind never seen, Water 14d** — all previously invisible.
   **D-8:** the DI-1.6 alert that fired **36×/72h** is episode-gated via an `ALERTSTATE#` sentinel
   (once + daily reminder, quiet on recovery) — verified holding live. Two follow-on fixes: a scoped
   `dynamodb:PutItem` IAM grant (the checker was read-only — the writes AccessDenied'd on the first
   run; PR #629, `cdk deploy LifePlatformOperational`) and a ConsistentRead on the dedup sentinel
   (PR #630).

7. **#377 — JS parse gate on site deploys** (Now, epic #341 · PR #631). `sync_site_to_s3.sh` now
   syntax-checks every site JS module before uploading and aborts naming the file. **Unblocks #581.**
   Ran live on the wrap deploy (`✓ all site JS modules parse clean`).

Layer went **v109 → v110 (#535) → v111 (#538)**; all consumers + site-api + MCP on v111. Platform
status green throughout; 43 new tests across 6 files, all passing.

## Gotchas learned (the load-bearing ones)

1. **site-api is script-managed (NOT in the Web CDK stack) and `deploy_site_api.sh` never set the
   layer** — so a `SHARED_LAYER_VERSION` bump silently left site-api on the OLD layer. This made
   #535's `/api/journey` rate CI read `None` (stale `weight_trend` on v109) and broke #538's
   `/api/calibration` import (`No module named calibration_core`). **Fix shipped:** `deploy_site_api.sh`
   now reads `SHARED_LAYER_VERSION` from `cdk/stacks/constants.py` and pins the layer after every
   code deploy (idempotent). Saved to memory: `reference_site_api_layer_manual_attach`.
2. **`node --check <file>` SILENTLY MISSES real syntax errors in ES-module files** (a dangling
   operator passed file-mode). The #377 gate MUST use `node --check --input-type=module` via stdin —
   that flag is load-bearing, pinned by `test_js_parse_gate_377`.
3. **CI/CD runs only on `push` to specific paths** (`lambdas/mcp/tests/cdk/ci/config/.github/…`) —
   **NOT `site/**` or `deploy/**`.** A site-only or deploy-script-only change triggers NO pipeline,
   so the site must be deployed manually (`deploy/deploy_site.sh`). Also: CI **deploys code only**
   (deploy_lambda.sh); cdk_only lambdas (site-api, MCP) and shared-LAYER changes need a manual
   `cdk deploy`. CI's Deploy auto-runs (no manual approval gate).
4. **The `test_count` doc-drift trap across stacked PRs:** `sync_doc_metadata.py --apply` sets
   `PLATFORM_STATS.test_count`, but a branch forked before a sibling merged doesn't see the sibling's
   tests — so after merge the count is short and `test_test_count_matches_suite` reds CI. Re-sync on
   main after each merge (done every time here).
5. **The freshness-checker role was read-only** — any new DDB write from it AccessDenies. Scope new
   writes with a `dynamodb:LeadingKeys` condition (least-privilege) and `cdk deploy LifePlatformOperational`.

## What's next (ranked, with the honest blockers)

- **#544 — Methods page / registry** (sonnet, Next, rank 16). The credibility artifact: a
  `methods_registry.py` single source → auto-generated `/method/methods/` page + a **CI drift gate**
  (code-fingerprint pattern of #389) + a "how was this computed?" popover on ≥4 surfaces. Sizeable
  (comparable to #538). **Unblocks #584** (provenance popovers, opus). Deliberately NOT started this
  session — too big to finish well at the tail; better clean than half-done.
- **#581 — Split evidence.js** (opus, Now). Now unblocked by #377. **Do this attended** — it's a
  byte-identical refactor of a 3,000-line SPOF; too risky to run unsupervised. Then #582 (chart
  contract) unblocks on top.
- **Self-contained data-health opus, no owner-decision fork:** #484 (resurrect the TDEE/deficit
  chain), #483 (HAE field validation). #494 depends on C-3 (strava un-pause). **#487/#507 need YOUR
  fix-or-retire decision** (ADR-103) before code — don't let an agent decide those unilaterally.
- **#551** is labelled `model:opus` but its body says `model:sonnet` (mismatch) — it's a dataviz
  design story that builds on #535's CI data; pairs naturally with #544.

## Watch / flags for Matthew

- **Calibration + weight-range are LIVE but empty** by design — they fill as post-reset predictions
  resolve and weigh-ins accrue (the goal-date range needs ≥5 weigh-ins; today there are ~4, so the
  rate CI shows but the projection stays suppressed). Not bugs.
- **The DI-1.6 "activity degraded" alert opened an episode** during this session (steps lagging +
  low-step days on the thin post-reset data). It sent once; dedup now holds it. If the underlying
  activity stream is genuinely fine, the thresholds (`AH_STEPS_LAG_ALERT_DAYS`, `AH_LOW_STEP_FLOOR`)
  may want tuning — but the spam is fixed regardless.
- **GitHub Pages** still enabled+public on the repo (carried from session 14, unactioned) — disable or bless.
- **Sun 07-06 / Mon 07-07 scheduled runs** (hypothesis engine, panelcast, data-recon) are the first
  to exercise the new commitment-grading + calibration + drift-z paths on real cron cadence.
