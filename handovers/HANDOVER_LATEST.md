# HANDOVER — 2026-06-09 (ER-01 infra-liveness + PG-14 data figure; PG-07 gate-blocked)

> A multi-item session. Three things landed and one was correctly deferred:
> **ER-02** (upstream contract tests — earlier this session), **ER-01** (infra-liveness
> heartbeat), and **PG-14 Tier-A** (the "data figure" on `/evidence/results/`). **PG-07
> was NOT built** — its gate isn't met.
>
> **✅ ER-01 + PG-14 are DEPLOYED + verified live** (layer v77 published, ingestion/
> operational/monitoring stacks deployed, site synced). **ER-02 is tests-only (no deploy).**
> All changes are still **uncommitted** in the working tree — commit/push is Matthew's.
> `main` was clean at session start.

**Earlier-same-session handover:** `handovers/HANDOVER_2026-06-09_ER02_Contracts.md` (ER-02 contract tests — full detail). **Prior:** `handovers/HANDOVER_2026-06-09_BlindSpotSweep.md`.

---

## 1. ER-01 — Infra-liveness heartbeat ✅ (ADR-085) — DEPLOYED + verified live

Closes the headline external-review finding: a source died silently for 44 days and nothing screamed. Behavioral freshness ("is the newest `DATE#` recent?") can't tell "user didn't log" from "ingestion erroring for weeks." ER-01 adds the **separate** infra-liveness signal.

- **New layer module `lambdas/ingest_health.py`** — pure, offline-tested decision core: `classify_error` (auth/throttle/transport/parse), `update_outcome` (streak math), `evaluate_source_health` (failure-streak arm ≥3 + attempt-staleness arm ~26h), `emf_metric_line`.
- **`ingestion_framework.py`** records a `USER#system / INGEST_HEALTH#{source}` sentinel + EMF at every terminal path (best-effort, never breaks ingestion). The auth-breaker-suppressed path records a continued failure → a source erroring every run alerts **with zero new data**.
- **`pipeline_health_check` `check_ingest_liveness` mode** (extension, not a new Lambda) — daily 17:10 UTC rule; emits `LifePlatform/IngestLiveness UnhealthySourceCount` + a distinct-subject digest alert.
- **`ingest-liveness-unhealthy` alarm** in `monitoring_stack` (separate from `slo-source-freshness`; 16 → 17). `freshness_checker` left behavioral-only by design.
- **`tests/test_ingest_health.py`** — 31 offline tests (4 error classes, streak buffer, both alert arms, both acceptance scenarios). All green.
- **Layer bumped 76 → 77**; `ingest_health.py` added to `build_layer.sh` + `ci/lambda_map.json`. No IAM change (pipeline-health-check role + ingestion roles already cover it).

**Deployed 2026-06-09** (the sequence — see "Deploy gotchas" below): `build_layer.sh` (builds the dir only) → `cd cdk && npx cdk deploy LifePlatformCore` (**this publishes layer v77**) → `npx cdk deploy LifePlatformIngestion LifePlatformOperational LifePlatformMonitoring`. **Live smoke passed:** `pipeline-health-check {"check_ingest_liveness": true}` → `unhealthy_count: 0`; sentinels populating; **garmin showed 2 consecutive `throttle` failures and stayed `ok` (under the 3-streak buffer) — the noise-suppression working in production.** No false alarms.

## 2. PG-14 — the "data figure" (Tier-A) ✅ — DEPLOYED live on /evidence/results/

The "AI me dropping weight" idea, built as its honest form (ADR-078 Wedge-B, productionized from `spikes/pg14_ai_me/`). A faceless, monochrome SVG silhouette whose girth is a **direct function of the real `/api/journey` weight** — no photo, no face, nothing generated/guessed.

- **`site/assets/js/evidence.js`** — `dataFigure(j)` + `dfBody`/`dfSmooth` (ported morph); `renderResults` prepends it; interactivity bound via the `WIRE.results` post-render hook (scrub, milestone buttons, play). `prefers-reduced-motion` respected.
- **`site/assets/css/evidence.css`** — `.df-*` styles; fill = `var(--ink)` so it adapts to light/dark; accent `var(--ember)`.
- **One contained instance** on `/evidence/results/` (the spec's first-choice home; results already used `/api/journey`). Disclaimer "representative figure, not a photo" baked in. Tier B (photoreal) + Tier C (video) remain deferred.
- **Verified:** `node --check` clean; morph path-gen tested 185→311.62 (valid closed paths, no `NaN`).

**Deployed 2026-06-09:** `bash deploy/sync_site_to_s3.sh` → `evidence.679d90c4.js`/`evidence.2cab809c.css` live; CloudFront `E3S424OXQZ8NBE` invalidated. **Remaining:** final browser visual QA (`python3 tests/visual_qa.py --screenshot --ai-qa` or `/qa`) once the invalidation propagates — eyeball the figure on `/evidence/results/`.

## 3. PG-07 — predict-the-week loop ❌ NOT built (gate not met)

PG-07's gate is **"D-05 prediction loop producing real verdicts (~2026-06-17)."** D-05 currently produces **100% inconclusive (theatrical)** verdicts pre-maturity — so PG-07's "reveal" would have only theatrical output to reveal against, which violates the platform's correlative-honesty standard. **Correctly deferred** until ~2026-06-17, when D-05 should yield real confirmed/refuted verdicts. Building it now would ship dishonest output. Revisit after the D-05 check passes.

---

## Deploy gotchas (learned the hard way this session — bake into the runbook)
- **`build_layer.sh` only BUILDS `cdk/layer-build/python/` — it does NOT publish to AWS.** The layer version is published by **`cdk deploy LifePlatformCore`** (the `LayerVersion` construct in `core_stack.py`). Deploying the layer-*consuming* stacks (Ingestion/Operational) before Core fails with "Layer version …:77 does not exist."
- **Run `cdk` from inside `cdk/`** — `core_stack` uses `Code.from_asset("layer-build")`, a path relative to the cwd. From the repo root it looks for `<root>/layer-build` and errors `CannotFindAsset`.
- **Correct sequence:** `bash deploy/build_layer.sh` → `cd cdk` → `npx cdk deploy LifePlatformCore` (publishes the layer) → verify `aws lambda list-layer-versions … → 77` → `npx cdk deploy LifePlatformIngestion LifePlatformOperational LifePlatformMonitoring`.

## Operator follow-ups (in order)
1. **Commit** — the working tree has three logically-separable changesets (ER-02, ER-01, PG-14) + the deployed-status doc updates. Suggest three commits/PRs, or one if you prefer. **The deploys are already live; committing now makes git match prod.**
2. **PG-14 final QA:** run visual QA on `/evidence/results/` once the CloudFront invalidation propagates (~30s) — confirm the figure renders, scrubs, and morphs, light + dark.
3. **ER-02 (optional, your terminal):** `python3 deploy/refresh_upstream_fixtures.py --date <recent-day>` to replace bootstrapped fixtures with real scrubbed captures.

## Verify quickly
- `python3 -m pytest tests/test_ingest_health.py tests/test_upstream_contracts.py -q` → 50 passed.
- `python3 -m pytest tests/ -q --ignore=tests/test_integration_aws.py` → all green (lv6 now passes — layer v77 is published).
- `node --check site/assets/js/evidence.js` → clean.
- Live: `aws lambda invoke --function-name pipeline-health-check --payload '{"check_ingest_liveness": true}' …` → `unhealthy_count` shape with per-source verdicts.

## Notes
- **No `PROJECT_PLAN.md`** exists; `docs/BACKLOG.md` is the active roadmap and was updated (ER 8→6 done, PG-14 done, PG-07 flagged gate-blocked, totals adjusted).
- **`sync_doc_metadata.py` not applied** — its only diffs were date-stamp bumps to 2026-06-10 (no count changed); skipped to avoid stamping tomorrow's date.
- Next ER item per the spec sequencing: **ER-03 Layer 1** (deterministic AI-output faithfulness guards, offline/gating).
