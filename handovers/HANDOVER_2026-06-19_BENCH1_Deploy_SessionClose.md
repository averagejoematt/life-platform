# HANDOVER — 2026-06-19 (EOD) · BENCH-1 built+deployed · Hevy folders · coaching calibration · session close

> Long multi-stream session. **Everything below is MERGED to `main`**; BENCH-1 is also
> **deployed live**. Earlier parts of the day have their own dated handovers:
> `HANDOVER_2026-06-19_ReadinessDateIntegrity.md` (AM) and
> `HANDOVER_2026-06-19_InboxTriage_NoiseReduction.md` (midday). This one covers the rest +
> closes the session.

---

## PRs merged this session (#152 → #158)
| PR | What | Deployed? |
|---|---|---|
| #152 | Readiness date-integrity + recurring-email-noise reduction (+ first coaching commit) | ✅ live (incl. precompute sleep 30→25, see ⚠️) |
| #153 | **BENCH-1** cut benchmarking & regain firewall (ADR-089) | ✅ deployed (see below) |
| #154 | Hevy: file committed routines into per-type folders (Push/Pull/Legs/Engine) | merged; MCP redeploy carried it live |
| #155 | doc-header reconciliation (INFRASTRUCTURE/RUNBOOK/SLOs → 81/134) | docs only |
| #156 | coaching calibration: data/continuity sessions, night-before planning, all-source pull + ruck | docs only |
| #157 | fix(benchmark): pace label at curve edge + robust regression rate | ✅ via MCP redeploy |
| #158 | fix(benchmark): pace rate reads withings cross-phase | ✅ via MCP redeploy |

No open PRs. Working tree clean except 3 untracked `docs/*MEAL_GROUPING*` files (Matt's, untouched).

## BENCH-1 — cut benchmarking & regain firewall (ADR-089), DEPLOYED
Operationalizes `PROVEN_BLUEPRINT.md` (16 loss episodes, 0 ever held; regain ≈ 0.79× loss; walking collapses post-trough). PRIVATE — never surfaces to Elena Voss / any public surface.

**What shipped + deployed:**
- **`episode-detect` Lambda** (`lambdas/compute/episode_detect_lambda.py`) — weekly Sun 17:00 UTC (rule **ENABLED**) + manual. Pure-Python turning-point/episode/outcome/covariate pass over **full** withings/strava/hevy history (reads pre-genesis — bypasses the ADR-058 phase filter). Writes two cross-phase computed sources: `weight_episodes` + `training_reference` (keyed like `computed_metrics`, no `phase` attr → survive resets). Live timeout 120s, Active.
- **Backfill done** — invoked once: **29 episodes (15 loss / 14 regain / 0 held)** in DDB. (CSV test gave 16/15; DDB has slightly less history — `0 held` holds either way.)
- **`get_benchmark` MCP tool** (`mcp/tools_benchmark.py`, view-dispatched: `pace`/`episodes`/`maintenance`) — MCP package redeployed (full `mcp/` zip; `deploy_lambda.sh` rejects `life-platform-mcp`).
- **Smoke (live, final):** `get_benchmark(view="pace")` → `pace_vs_proven: behind`, `current_rate -1.21 lb/wk` (n=16, real cross-phase regression), `proven_rate@weight 2.2`, `walk_gap 11.59` (0.5 vs 12.09/wk), `run_gate_ok False`. Matches the work order's acceptance smoke exactly.

**Algorithm note (carried in ADR-089):** the work order's pasted `turning_points` ZigZag had a `direction=0` bug (records 0 pivots — verified). Replaced with the standard ZigZag; reproduces the validated values exactly (16/15, 2.96/2.41 lb/wk, reference cut 116.4 lb / 33.6 wk). A datadrops-gated test pins this locally; `datadrops/` is gitignored so it skips in CI.

**Two pace fixes after the first live smoke (#157, #158):**
1. `_proven_rate_at` clamps the lookup into the curve's weight range — a current weight just above the curve's rounded max (305.44 > 305.4) was returning None → "unknown".
2. `_current_weight_and_rate` uses a least-squares regression over a 28d window AND reads withings **cross-phase** (`include_pilot=True`) — the phase filter had left only ~5 post-genesis days of water-weight normalization (the bogus 12.75 lb/wk); weight-rate is physiological, not experiment-scoped.

**Board guardrails (enforced + tested):** no predictor (`n_held=0`, descriptive only, `confidence`+`n` everywhere); forward-framing (a test asserts the `maintenance` signal has no failure-count string; `pace` asserts `run_gate_ok=False` above 240); weekly-not-nightly (Viktor); PRIVATE.

## ⚠️ Deploy side effect to know
`cdk deploy LifePlatformCompute` (to create `episode-detect`) reconciled the **whole compute stack** — a merged-but-undeployed backlog: the **precompute sleep 30→25** readiness change (we'd parked it "until after QA"), ai-expert-analyzer 120→600s, AICostMetrics IAM (#142), etc. All merged/CI'd code, no deletions. Net: the **readiness colour shift is now LIVE**. The page-by-page website QA we never got to is still worth doing.

## Hevy per-type folders (#154)
`commit()` now files a committed routine into its per-type Hevy folder (Push/Pull/Legs/Engine) via a find-or-create helper (`folder_id` is create-only in Hevy); `dry_run` previews `target_folder`. Fixes home-page routine bloat. Live via the MCP redeploy.

## Coaching calibration (#156, docs only — PRIVATE)
§4a additions to `TRAINING_CALIBRATION.md` + `TRAINING_PROGRAM.md`: continuity-over-calendar (resume PPL/cardio sequence from what was actually trained, not the weekday); night-before-at-5am is the normal path (plan confidently without a live recovery gate; never label a session with a non-live recovery tier); mandatory all-source pre-flight (Hevy + Strava + Whoop, never Hevy alone); ruck edge case (a Strava `Walk` may be a weighted ruck → offer/honor the `log_ruck` overlay). Program grid reframed as a default rhythm, not a Mon–Fri schedule.

## Docs / state
- `sync_doc_metadata.py` reports **all docs in sync** (Tools **134**, Lambdas **81**, layer **v85**).
- ADR-089 in `DECISIONS.md`; `weight_episodes` + `training_reference` documented in `SCHEMA.md`; `get_benchmark` in `MCP_TOOL_CATALOG.md`; CHANGELOG + COST_TRACKER updated; CLAUDE.md verified line + tool count refreshed.

## Open follow-ups (next session)
- **Page-by-page website QA** (the original plan we got pulled off — now extra-relevant since the precompute readiness shift is live).
- **Garmin/Strava liveness:** Garmin alarms deleted earlier (known-dead); `ingest-liveness-unhealthy` now red on **Strava** alone (its 402-paywall path doesn't record a liveness attempt). Decide: mark Strava best-effort, or fix the 402 path to record the attempt.
- Matt's untracked `docs/*MEAL_GROUPING*` spec/review/prompt — his to commit when ready.

**Verified:** 2026-06-19 EOD. All BENCH/benchmark/registry tests green; black clean; live smokes pass. No open PRs; main clean.
