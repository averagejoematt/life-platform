# HANDOVER — the silent-failure batch: #466/#467/#469/#471/#472 + #511 shipped end-to-end — 2026-07-04 (session 5)

**Epic #459's Now-milestone slice is merged, deployed on layer v99, and live-verified —
no scheduled data source can fail silently anymore.** The three pattern-exempt ingesters
(hevy, notion, dropbox) write the ER-01 sentinel, the two known instrument misfires
(Todoist false-stale, Strava reconciler edge) are fixed at the root, and the MacroFactor
format-change trap raises instead of 200-skipping. PRs **#515** (#511 fix), **#516**
(the batch), **#517** (v99 pin). Issues #466/#467/#469/#471/#472/#511 auto-closed;
**#518 filed** (pre-existing pipeline-health-check probes a nonexistent
`life-platform/dropbox` secret — found during live verification).

---

## What shipped

**#515 — #511:** both `tools_training` `_linear_regression` call sites passed `(xs, ys)`
instead of a points list → TypeError the moment sessions existed
(`get_lactate_threshold_estimate` + `get_exercise_efficiency_trend`). Fixed + 2 tests.
Also salvaged an uncommitted 2026-07-03 handover from the stale `accuracy-phase3`
worktree (worktree removed, `main` reclaimed by the primary tree).

**#516 — the batch (21 new offline tests):**
- **#466** — `hevy_backfill` writes the sentinel at every terminal path via a new
  **public** `ingestion_framework.record_ingest_health()` (private `_record_…` now
  delegates); fatal `HevyAPIError` **raises** (sentinel first) instead of a swallowed
  500; `hevy_get` converges on `http_retry`. `hevy` added to `ACTIVE_API_SOURCES`.
- **#467** — notion + dropbox record the sentinel (success / auth-suppressed skip /
  failure). **X-13 root fix:** the framework's breaker was a metric-less private copy of
  `auth_breaker` — it now delegates, so SIMP-2 sources emit `IngestAuthHealthy` and the
  monitoring-stack comment is finally true.
- **#469** — unknown-format MacroFactor CSV archives to `raw/…/unknown/` then **raises**
  (dropbox_poll has already hash-marked + moved the file by then — the 22-day May
  incident class); the dead daily `cron(0 16)` deleted (365 no-op invokes/yr).
- **#471** — todoist `stale_hours` 48→72 (day-dated records + 1x-daily ingestion → max
  healthy age ~62h; 48h false-staled request-time surfaces ~14h/day); CLAUDE.md cadence
  corrected to 1x daily.
- **#472** — strava reconciler brackets the stored-side fetch **±1 day** (store keyed by
  local PT date, API window in UTC epochs → the evening-PT-walk edge false-positived).

## Deploy (all live 2026-07-04 ~15:15 UTC, explicit in-session merge+deploy approval)

Layer dance per CONVENTIONS §1: build → Core published **v99** → pin merged (PR #517) →
Ingestion (the MacroFactor schedule-rule destroy read + confirmed in `cdk diff`),
Operational, Mcp, Compute, Email from detached origin/main → site-api via
`deploy_site_api.sh`. Monitoring had **zero** template diff (comment-only). Asset check:
deployed zips grep'd for all five fix markers + layer v99 zip for
`record_ingest_health`/`_ab_clear_failure`/`"stale_hours": 72` — all present.

## Live verification (all ACs)

- **#466 drill:** normal run → sentinel `streak=0/none`; **wrong-API-key drill** (secret
  temporarily swapped, cold start forced via env-var touch) → Lambda **raised**
  `HevyAPIError`, sentinel `streak=1/auth`, metric `ConsecutiveFailures{Source=hevy}`
  now EXISTS in CloudWatch; secret restored, re-run reset to `0/none`; alarm stayed OK
  (drill deliberately kept below the 3-streak page threshold — chain proven without a
  6h synthetic URGENT page, since the alarm is 6h-Maximum).
- **#467:** notion + dropbox invoked → sentinels live; `check_ingest_liveness` mode →
  **notion/dropbox/hevy all `ok`** (no more permanent 'unknown'), unhealthy_count=0
  (garmin `failing` correctly excluded as best-effort).
- **#472:** live reconcile → 16 API / 18 stored / **missing_count 0** on the exact
  window that was alarming.
- **Alarms pending their evaluation cycles:** `ingest-reconciliation-strava` (1-day
  Maximum) clears within 24h as yesterday's datapoint ages out; `slo-source-freshness`
  (red since 06-27) should clear after the checker's 16:45 UTC run — **the #471 AC's
  7-consecutive-day OK observation starts 2026-07-04.**

## Gotchas for the next session

- **The pre-commit hook rewrites `site_api_common.py` test_count AFTER `git add`** — the
  bump chases you one commit behind. Check `git status` after every commit; both PRs
  needed a trailing sync commit, and #515 vs #516 conflicted on exactly that line
  (resolve = take either side, re-run `deploy/sync_doc_metadata.py --apply`).
- **PR-level CI is Dependabot-validate only** — the real lint/test gates run on push to
  main. Local black + ruff + flake8-E9 + full pytest + `cdk synth` is the pre-merge bar.
- **Warm containers cache secrets forever** (`hevy_common._secret_cache` module global)
  — a live failure drill needs a cold start; touching an env var
  (`update-function-configuration`) is the clean way to force one.
- `aws lambda invoke` with a JSON payload needs `--cli-binary-format raw-in-base64-out`
  (bare `'{}'` happens to pass, anything with a space does not).

## Open / next

- **#518** — pipeline-health-check's expected-secrets list probes `life-platform/dropbox`
  which has never existed (creds live in `ingestion-keys`) → daily `failed: 1` misfire.
- Watch: `slo-source-freshness` 7-day OK window (from 07-04); `ingest-reconciliation-strava`
  should be OK by 07-05 — if either stays red, the diagnosis in the review doc §E-3/§C-1
  is incomplete.
- **13 area:data Now stories remain** — `gh issue list --label area:data --milestone Now
  --state open`. Journal remainder (J-2/J-6/X-7/E-6) in epic #464; #474 (apple_health
  XML decision) is the one opus-effort story.
- 6 pre-existing local test failures on main (coaches_api ×4, hevy_compiler_isolation,
  integration_aws) — env/live-data dependent, green in CI; untouched.
