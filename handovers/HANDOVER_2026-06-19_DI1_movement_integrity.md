# HANDOVER — 2026-06-19 · DI-1 Movement Data Integrity (DI-1.2 / 1.3 / 1.1 / 1.4)

> Branch **`di1-movement-integrity`** (off `main`, **not pushed**). Four sub-items built +
> tested, **nothing deployed** — Matthew runs all deploys. Spec:
> `docs/coaching/WORKORDER_DI1_movement_integrity.md`. Tests: `tests/test_di1_movement_integrity.py` (15, all green).

---

## The bug (one line)
The platform stamped Matthew's hardest training days as **sedentary / under-training** because the movement/sedentary read and the TSB signal were **Strava-only**, and Strava is paused (402) + Garmin rate-limited — so with no Hevy join the platform had no training signal and the training coach wrote six days of "you're under-training."

## Commits (each sub-item independent)
| Commit | Sub-item | What |
|---|---|---|
| `eea20c64` | **DI-1.2** | `tool_get_movement_score` joins Hevy (`has_workout`=any source, Hevy-first; Hevy day never sedentary); `compute_tsb` Hevy-aware fallback + `tsb_load_basis`; Hevy added to recompute fingerprints. |
| `d4eec4ce` | **DI-1.3** | Coach `gather_data_for_expert("training")` Hevy-first pull; `movement_assessability()`+`apply_movement_honesty_guard()` (prompt constraint + write-time backstop) withhold under-training verdicts when Strava isn't live. |
| `65ba76af` | **DI-1.1 source-state** | New `source_state.py` layer module (`live/paused/rate_limited/stale`, freshness-wins-for-live); `get_freshness_status` surfaces it; coach guard reads it; **liveness-pinger masking killed** in `pipeline_health_check`. |
| `2dfb711e` | **DI-1.4** | Phantom-298 traced + fixed (state-aware step precedence); step-completeness flag in movement tool; step SOT in `SCHEMA.md`. |

## Key diagnoses (verified, read-only)
- **Strava** = deliberately **paused** in CDK (`ingestion_stack.py:182 schedule=None`) at the 402 paywall; the `strava-daily-ingestion` EventBridge rule was deleted; the 4-hourly 2 ms invokes are `pipeline_health_check`'s healthcheck pings masking the dead cron. **Re-auth fixes nothing** — Matthew subscribed → re-enable.
- **Phantom 298** = Garmin's `2026-06-15` step reading (`298`), surfaced because the coach preferred Garmin steps while Garmin is rate-limited. Apple ~3,415 was truer.
- **⚠️ Work-order fixture correction:** "Apple steps blank 6/5–6/13" is **wrong vs live DDB** — steps are present every day (low, 254–2487); the *entirely* blank field recently is **`active_calories`** (None on every day 6/3–6/19). Worth a follow-up: active-calories ingestion gap (HAE `active_energy`).

## Deploy sequence (Matthew — all four sub-items ship together)
1. **Layer rebuild + bump** (DI-1.1 `source_state.py` is a new layer module; DI-1.3 touched `intelligence_common.py`): `bash deploy/build_layer.sh` → `cd cdk && npx cdk deploy LifePlatformCore` (publishes → **v87**) → set `SHARED_LAYER_VERSION = 87` in `cdk/stacks/constants.py`.
2. **`daily-metrics-compute`** (DI-1.2): `bash deploy/deploy_lambda.sh daily-metrics-compute lambdas/compute/daily_metrics_compute_lambda.py` → recompute 6/15→today: `aws lambda invoke --function-name daily-metrics-compute --payload '{"date":"2026-06-1X","force":true}' /dev/stdout` for each date.
3. **`ai-expert-analyzer`** (DI-1.3/1.4 coach) — redeploy on the new layer; regenerate today's training thread so the corrected logic writes a clean entry.
4. **`pipeline-health-check`** (DI-1.1) — redeploy on the new layer (the paused-aware probe + liveness exclusion).
5. **MCP package** (DI-1.2 `tools_lifestyle` + DI-1.1 `tools_labs`) — full `mcp/` deploy per its printed build sequence; `pytest tests/test_mcp_registry.py` green first (it is).
6. **Smoke:** `get_daily_metrics(view="movement")` 6/16–6/19 → 0 sedentary, `step_coverage_pct` present; `get_freshness_status` → Strava `source_state: paused` (not stale); `get_benchmark`/coach thread names no "under-training" with Hevy present.

## Strava re-enable (DI-1.1 remaining — Matthew)
Un-pause `ingestion_stack.py:182` (restore `schedule=`), `cdk deploy LifePlatformIngestion` to **recreate the `strava-daily-ingestion` rule** + reconcile the stale Lambda permission, invoke once to backfill 6/15→present, confirm the 402 is gone. **Then remove `"strava"` from `DECLARED_PAUSED_SOURCES` in `lambdas/source_state.py`** — freshness already flips it to `live`, but removing it relabels a *future* real outage as `stale` (not `paused`) and resumes the health-check probe. (Garmin GARM-1 deferred.)

## Remaining DI-1 work
- **DI-1.5 (governance)** — out-of-band Dr. Chen thread correction (Matthew, via insight/decision log — *not* Claude Code); an **ADR** promoting the staleness/paused honesty-guard to a cross-coach standard; RUNBOOK `paused≠stale` note. Not started.
- **DI-1.6 (HAE activity failsafe)** — **blocked on Matthew verifying two config preconditions** before coding: (a) Garmin Connect → Apple Health **workout** sync on (not just steps); (b) HAE exports **workouts/activities** (distance/duration/HR), not only the gapped step field. Depends on DI-1.4. Then: ingest HAE activity records + Strava-primary/HAE-fallback precedence (gated by the DI-1.1 source-state) + dedupe.

**Verified:** 2026-06-19. 15 DI-1 tests green; `test_business_logic`/`test_mcp_registry`/`test_wiring_coverage`/`test_coach_intelligence`/`test_persona_registry`/`test_ingest_health` all green; black + flake8 clean (zero new issues). Not deployed.
