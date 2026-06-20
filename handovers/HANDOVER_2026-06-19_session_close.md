# HANDOVER — 2026-06-19 session close · DI-1 movement integrity + HAE deep dive

> Branch **`di1-movement-integrity`** (off `main`, **not pushed**, **nothing deployed**). Matthew
> runs all deploys. Two threads this session: **DI-1** (movement data integrity, WORKORDER_DI1) and a
> **surgical HAE-path review** that found why step data isn't arriving. Picks up **2026-06-20**.
> Detail docs: `docs/coaching/WORKORDER_DI1_movement_integrity.md`, `docs/reviews/HAE_PATH_REVIEW_2026-06-19.md`,
> `handovers/HANDOVER_2026-06-19_DI1_movement_integrity.md` (the DI-1-only handover), ADR-091.

## Commits on the branch (7), all tested, none deployed
| Commit | What |
|---|---|
| `eea20c64` | **DI-1.2** movement/TSB join Hevy (has_workout=any source, Hevy-first; Hevy day never sedentary; Hevy-aware TSB + `tsb_load_basis`) |
| `d4eec4ce` | **DI-1.3** coach Hevy-first pull + honesty guard (withholds under-training when Strava not live; prompt + deterministic write-time backstop) |
| `65ba76af` | **DI-1.1 source-state** `source_state.py` (`live/paused/rate_limited/stale`, freshness-wins-for-live); `get_freshness_status` surfaces it; liveness-pinger masking killed |
| `2dfb711e` | **DI-1.4** step-completeness flag + state-aware step precedence (phantom-298 = Garmin stale reading) |
| `8efa6d13` | DI-1 consolidated handover |
| `ae9a1aae` | **DI-1.5** ADR-091 (cross-coach honesty-guard standard) + HAE step-undercount RCA |
| `9e98e093` | **HAE P0 fix** MAX-across-sources + GREATEST-on-write for additive activity metrics |

Tests green throughout (15 DI-1 + 16 HAE + business/registry/wiring/coach/persona/ingest_health). black + flake8 clean.

## HAE deep dive — the answer (why step data isn't arriving)
**HTTP 413.** HAE exports raw per-sample steps (`aggregateData=False`); the 7-day payload is **24.8 MB**,
the Lambda Function URL caps bodies at **~6 MB** → rejected at the edge, our Lambda never runs. HAE logs
the run `complete` right after the 413, so **the phone shows success while nothing lands**. Activity
(period=Today) also 413s at 14.2 MB. Historical 402/444 days = a separate older cause (Activity
`period=Today` + Watch→iPhone sync lag froze partial iPhone-only counts; period=Today never re-sends).
Full forensics + severity-ranked findings in `docs/reviews/HAE_PATH_REVIEW_2026-06-19.md`.

**P0 code fix shipped** (`9e98e093`): MAX-across-per-source-sums + GREATEST-on-write for
`steps/distance/active_calories/basal_calories/flights_climbed`. Makes the data correct *once it
arrives* — orthogonal to the 413 unblock.

## TOMORROW (2026-06-20) — Matthew's call: aggregate change OR one-time export
1. **Unblock the data — pick one:**
   - **(A)** Flip **`Aggregate Data` ON** for the HAE "Step counts" automation → daily totals, payload drops to KB, no 413, gives Apple's deduped daily number. (Remove `Step Count` from "Activity" too.)
   - **(B)** One-time **file export** from Apple Health (`datadrops/apple_health_export/export.xml` exists) → import path (no size limit) for the 7-day/full history.
2. **Add `Active Energy`** to an `includeHealthMetrics=True` automation (it's exported by none → `active_calories` is `None` every day, degrading NEAT + the sedentary clause).
3. Once data lands: verify `get_daily_metrics(view="movement")` 6/13–6/19 matches the app; the monotonic guard lets corrected higher totals overwrite the stored 402/444.
4. **Then the DI-1 deploys** (ready, pending — were going to do them this session before the HAE pivot):
   - **Layer rebuild + bump first** (new `source_state.py` + `intelligence_common.py` change): `bash deploy/build_layer.sh` → `cdk deploy LifePlatformCore` (→ v87) → set `SHARED_LAYER_VERSION=87` in `cdk/stacks/constants.py`.
   - Then `daily-metrics-compute` (DI-1.2, recompute 6/15→today) · `ai-expert-analyzer` (DI-1.3/1.4) · `pipeline-health-check` (DI-1.1) · MCP package (tools_lifestyle + tools_labs) · `health-auto-export-webhook` (HAE P0).
   - **Strava re-enable** (DI-1.1, separate): un-pause `ingestion_stack.py:182`, `cdk deploy LifePlatformIngestion` to recreate the rule, backfill, confirm 402 gone — then drop `"strava"` from `DECLARED_PAUSED_SOURCES`.

## Open / deferred (not blocking)
- **DI-1.6 HAE activity failsafe** — depends on the HAE config being clean (above) + DI-1.4.
- **Dr. Chen thread correction** — out-of-band, Matthew (per ADR-091/DI-1.5).
- HAE P1s (untouched): UTC-day vs local-day partitioning decision; our-side 413/low-steps anomaly guard (the 413 is invisible to us today — no alarm); ingestion completeness/plausibility gate.
- Historical undercount days are **unrecoverable from existing raw** (the Watch stream was never exported); only a fresh HAE re-send (A/B above) recovers them.

**Verified:** 2026-06-19 session close. Branch local-only (not pushed per the no-push norm — Matthew pushes + runs CI at deploy). Nothing deployed.
