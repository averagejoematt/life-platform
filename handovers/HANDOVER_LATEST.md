# HANDOVER — 2026-06-20 · DI-1 deploy + HAE 413 remediation + Strava re-enable

> Branch **`di1-movement-integrity`** — now **pushed**, **PR #160 open** to main, and
> **fully deployed to production** (we deployed locally off this branch; the PR brings
> `main` into agreement — it does NOT require a redeploy). Picks up at a **QA session**.
> Prior session: `handovers/HANDOVER_2026-06-19_session_close.md`.

## What shipped this session (all live)
1. **One-time native Apple Health import** (`backfill/onetime_apple_health_import_2026-06-20.py`) —
   streamed the 1.2 GB `export.xml` from disk (the 512 MB / 5-min Lambda OOMs), windowed to
   the experiment, **max-sum-across-sources dedup** (no iPhone+Garmin double-count), wrote via
   production `save_day`. Corrected **6/14–6/20**: undercounts fixed (6/15 402→1547, 6/18 444→2720)
   and **`active_calories` filled** (was `None` every day). Verified in DDB + S3 + the movement view.
2. **DI-1 fully deployed** — layer **v87** (`source_state.py` + `intelligence_common.py`) published
   via `cdk deploy LifePlatformCore`; `SHARED_LAYER_VERSION=87` in `constants.py`; redeployed
   Compute, Operational, MCP, Ingestion. DI-1.1 `is_paused` confirmed live (pipeline-health reports
   paused sources correctly). **Fixed layer drift:** `PipelineHealthCheck` was on an out-of-band v85
   (no `shared_layer=` arg) → `source_state` silently no-op'd; added the arg so CDK pins it to v87.
3. **DI-1.6 HAE silent-413 failsafe** (`freshness_checker_lambda.py`) — the 413 is rejected at the
   HTTP-API gateway before metering (**verified 4xx/5xx==0** on dropped-payload days → invisible to
   CloudWatch). Guard watches `steps` vs partition freshness + sustained-low; emits 3 metrics; respects
   sick-days. Fixed a latent `active_energy_kcal`→`active_calories` completeness-bug. Tests: `test_hae_activity_failsafe.py` (6).
4. **Capture-everything expansion** — promoted cycling/swimming/snow distance (+max-across-sources),
   VO₂ max, walking-HR, walking-steadiness, physical effort, cycling FTP to daily fields in the HAE
   webhook `METRIC_MAP` + batch `QUANTITY_RECORDS` + SCHEMA. Per-sample workout dynamics (power/cadence/
   ground-contact/stride/oscillation) stay archived in raw S3 (daily-avg is noise). `basal_calories`
   mapping confirmed already correct (HAE sends `basal_energy_burned`). Tests: `test_health_auto_export.py` (25).
5. **Strava re-enabled** — live test returned **200** (402 paywall cleared; Garmin→Strava auto-upload
   feeds it). Restored the hourly EventBridge schedule (`ingestion_stack.py`, was `schedule=None`) and
   re-added strava to `freshness_checker` (SOURCES + `activity_count` completeness + OAuth). Rule is
   **ENABLED**. NB: `strava` left in `DECLARED_PAUSED_SOURCES` — behaviorally inert (freshness-wins),
   drop on next layer rebuild for tidiness (only `pipeline_health_check.is_paused()` reads it directly).

## HAE — PARKED ✅
The config is remediated (Matt's changes: `Summarize=Yes` on Feeds 1/4/5/9/10, glucose Feed 6 kept raw,
de-duped Step Count to Feed 10). Live incremental path **confirmed flowing** — steps/active/gait/basal
landing, today's record self-updating via webhook GREATEST-on-write (6/20 steps 2,794→10,280).
- **Caveat:** payloads are still **raw per-sample** (Summarize doesn't appear to collapse them) — fine
  while hourly syncing keeps each window small; the death-spiral risk only returns on a multi-day stall,
  which the failsafe catches in ~2 days. Worth confirming the `Summarize=Yes` toggle actually saved.
- **Insurance:** drop a native `export.xml` into `datadrops/` ~quarterly and re-run the importer →
  guarantees full-resolution history regardless of feed settings.

## Commits on the branch (13; 10 prior + 3 this session)
`bc03bcc1` v87 deploy + capture-everything · `c3c6d2ee` DI-1.6 failsafe + one-time import · `e015ae1b` Strava re-enable
(+ the 10 DI-1.x/HAE-P0 commits from prior sessions). All tested, black + flake8 clean.

## NEXT
1. **Merge PR #160** → reconciles `main` with what's live (already CI-equivalent-checked locally).
2. **QA session** (the reason we stopped) — `/qa` sweep of averagejoematt.com + movement/HAE data spot-checks.
3. Spot-check the **6/21 record** — a full day with no import behind it = clean proof the HAE incremental path stands alone.
4. Minor/deferred: drop `strava` from `DECLARED_PAUSED_SOURCES` on the next layer rebuild; HAE UTC-day vs local-day partitioning decision (open design); Dr. Chen thread correction (out-of-band, Matthew, per ADR-091).

**Verified:** 2026-06-20. Branch pushed, PR #160 open, production live on this code. Stopping for QA.
