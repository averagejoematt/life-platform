# Handover — 2026-06-24 (inbox-noise triage → CI-health excavation + Strava/alarm fixes + continuation)

Started as "reduce platform inbox noise — bugs vs one-offs?" Turned into peeling a **chain of masked CI gates**, then a data-integrity + privacy continuation. `main` @ `9fc9a996+`. **Everything CI-green and deployed except the low-urgency #215 email deploy (staged).**

## Continuation after the CI-health work (same session, all merged)
- **Dependabot cleared:** #200 (dev-tooling patches) + #198 (checkout v7) merged; #199 closed (superseded by #200). 0 open PRs.
- **#214 — Whoop late-sync hardening — DEPLOYED + live.** Same class as the Strava bug: Whoop stores per-workout sub-records (`DATE#..#WORKOUT#id`), so a workout syncing after the day's recovery record was stored would drop. `refresh_trailing_days=2`. `test_trailing_refresh_policy_per_source` pins the policy and documents why Garmin (429-fragile; activities→Strava; same-day wellness) + eightsleep/withings/habitify (same-day finalized) are deliberately excluded. Deployed `LifePlatformIngestion`; verified.
- **#215 — chronicle fallback privacy leak — MERGED, deploy STAGED.** `_FALLBACK_ELENA_PROMPT` (fires only on S3 config-load failure) still named real public figures (Attia/Huberman/Norton/Walker) → fictional roster (Reyes/Nakamura/Webb/Park). `test_no_real_names_in_chronicle.py` guards it. **Needs `cdk deploy LifePlatformEmail` (low urgency).**
- **Verified-already-done (no work):** `get_freshness_status` MCP interior-gap parity — the CLAUDE.md "still high-water-mark only" follow-up was **stale**; B3 (2026-06-21) already wired `find_interior_gaps` → returns `interior_gaps` + `interior_gap_count`, test green. Don't re-chase it.

**Session total: 8 PRs merged.** The only open action is the staged #215 email deploy (low urgency).

---

## Original CI-health writeup
Started as "reduce platform inbox noise — bugs vs one-offs?" Turned into peeling a **chain of masked CI gates**. `main` @ `317aa865`. **Lint + Unit Tests are green; one deploy is PENDING Matthew (the only thing left).**

## TL;DR
- The "Run failed: CI/CD" email stream was **one red gate masking three more**. CI's Lint job runs gates *sequentially* (flake8 → black → ruff → mypy → py_compile) and the `Unit Tests` job `needs` Lint — so a single unformatted file stopped everything before ruff/mypy/tests ever ran. Fixing each layer exposed the next.
- **6 PRs merged** (4 CI-health + 2 real platform fixes). **CI Lint + Unit Tests both green**, verified live.
- **⚠️ One deploy left (yours):** merging the Strava fix surfaced a *pre-existing* layer-v89 rollout that stalled Jun 22. `cdk deploy --all` finishes everything. Diff verified safe (no IAM changes).

## Merged this session
| PR | What | Layer of the mask |
|---|---|---|
| **#208** | Removed 2 dead one-off scripts (`deploy/_publish_week1.py`, `_prologue_rewrite.py`) that failed **black** — accidental commits in #186, the entire "Run failed" email source | 1 (black) |
| **#211** | 9 latent **test** failures unmasked once Unit Tests could run: cost_governor (7 — test not aware of the June-2026 tier headroom #169, auto-reverts Jul 1 → autouse fixture pins normal thresholds), coach_panel_podcast sensitivity (1 — refit #166-182 made the gate AI-adjudicate; test expected pre-refit auto-hold AND called live Bedrock → rewrote to new contract, mocked), hevy_common (1 — `BUCKET` binds `$S3_BUCKET` at import time; other modules set `test-bucket` → order-dependent → pinned) | 2 (Unit Tests) |
| **#212** | 14 **ruff** violations: 12 I001 import-sort (`ruff --fix`, sys.path/`# noqa: E402` guards preserved), F841 dead var, S324 sha1 → `usedforsecurity=False` (grouping signature, not security) | 3 (ruff) |
| **#213** | 2 hevy `dry_run` tests hit `routine_title.build_title_context` → DynamoDB → **`NoCredentialsError` in CI** (passed locally on ambient creds). Stubbed `build_title_context`. Found by running the suite with creds blanked | 4 (full suite) |
| **#209** | **Strava late-sync drop** (real data bug). `refresh_trailing_days=3` on the ingestion config | — |
| **#210** | **ai-tokens alarm** recalibrated 33333 → 150000 (steady-state ~59k/day; not a cost issue) | — |

**Verification:** full suite with **credentials blanked** (true CI condition): `2045 passed, 0 failed`. Live CI on `main`: Lint **success** + Unit Tests **success** (run 28125725760). black/ruff/mypy(11-module set)/py_compile all clean locally.

## The two real platform bugs (the inbox signal worth keeping)
- **#209 — Strava afternoon walks dropped.** The ADR-092 reconciler caught it (`ingest-reconciliation-strava`, grew 0→2→5 Jun 21-24): 5 afternoon walks in the Strava API never reached DDB; every *stored* activity those days was a morning workout. **Root cause:** gap detection (`ingestion_framework._find_missing_dates`) is **presence-based** — once a date has any record it's never re-fetched (`refresh_today` only re-pulls today). Walks that **sync late** (after their local day rolled) land on an already-present date and are stranded. Distinct from the #180 tz-window fix. **Fix:** `refresh_trailing_days=N` re-fetches the last N days regardless of presence; `transform()` rebuilds the day from all API activities, so a re-fetch merges late arrivals — and **auto-heals the existing 5 gaps on the next run.** Strava set to 3.
- **#210 — ai-tokens-platform-daily-total fires daily.** Threshold 33333 sits below real autonomous baseline (~59k output tokens/day: brief + 8 coaches + panelcast loop + compute). Not a cost problem — $75 budget guard + `ai-daily-spend-high` $ alarm intact. Bumped to 150000 (clears the ~121k content-heavy peaks).

## ✅ DEPLOY DONE — Matthew authorized "you run it this time" (2026-06-24)
`cdk deploy` of the 5 changed stacks (Ingestion/Compute/Email/Operational/Monitoring, `--require-approval never`; diff had confirmed no IAM changes) — all ✅, no rollbacks. **Live-verified:** all 15 consumers + strava on **v89** (0 behind → `Plan` gate now passes), `ai-tokens-platform-daily-total` → **OK**, and a manual Strava ingestion **auto-healed the 5 walks** (Jun 23 record 2→5 activities; reconcile `missing_count 0`). `ingest-reconciliation-strava` self-clears within ~24h (its daily-`Maximum` window still holds the pre-fix datapoint; the data is already fixed). The next push shows CI fully green end-to-end. Original blocker write-up below for the record.

## (resolved) The blocker that required the deploy
Merging #209 triggered a CI run that went green on Lint+Test then **failed at `Plan deployments`** on a *pre-existing* check: **`15 consumer(s) not on layer v89`**.

**Root cause:** layer **v89 was published Jun 22** (hevy-commit-hardening: `hevy_compiler` set-type map + note sanitize) and `constants.py` bumped to 89, but the **15 consumer Lambdas (email + compute) were never redeployed to attach it** — they're on v87/v88. The `Plan` layer-consistency gate (also masked behind the red Lint until now) catches it. Two consequences: it **blocks #209's auto-deploy**, and it's now **the new "Run failed: CI/CD" email source** (every lambdas/ push: Lint+Test green → Plan red).

**The fix (one command, his to run):**
```bash
cd cdk && JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1 npx cdk deploy --all
```
`cdk diff` verified the blast radius (all 5 changed stacks):
- **Monitoring:** one property — `Threshold 33333 → 150000` (#210).
- **Ingestion:** Strava code (#209) + layer →v89.
- **Compute / Email / Operational:** the 15 consumers, layer **v87/v88 → v89**, no code change.
- **NO IAM / policy / role / security changes anywhere.** Clean, low-risk.

Ignore the CI hint to run `build_layer.sh` — **v89 already exists in AWS**; consumers just need re-attaching, which `cdk deploy` does (rebuilding would needlessly create v90). Targeted alternative: `cdk deploy LifePlatformIngestion LifePlatformCompute LifePlatformEmail LifePlatformOperational LifePlatformMonitoring`.

**After the deploy, verify:** (1) the 15 consumers on v89 → `Plan` gate passes → CI/CD fully green (email stream stops for good); (2) `ingest-reconciliation-strava` clears + the 5 walks backfill on the next Strava run (hourly 12-23 UTC, reconcile cron 17:20 UTC); (3) `ai-tokens-platform-daily-total` clears.

## Inbox verdict (the original ask)
- CI failures (×7+) → real, fixed. ✅ (and the *new* Plan-failure email clears on deploy)
- `ingest-reconciliation-strava` → **real data bug** (#209) — don't suppress, it was working; clears on deploy.
- `ai-tokens` alarm → mis-tuned (#210); clears on deploy.
- AWS Budget / Dependabot / Remediation 0-0-0 / newsletters / Venmo / court filing → expected or non-platform; ignore.

## New memory
`reference_ci_masking_and_creds.md` — the Lint gates are sequential (a red one masks the rest + skips Unit Tests); verify CI-green by running the suite with **creds blanked** (catches the boto3-without-mock tests that pass locally, fail in CI on `NoCredentialsError`). Indexed in MEMORY.md.

## State
`main` @ `317aa865`, tree clean. PRs #208/#209/#210/#211/#212/#213 merged. Layer v89 published; **fleet rollout pending the deploy above.** CLAUDE.md layer ref updated v85→v89.
