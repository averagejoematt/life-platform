# HANDOVER — 2026-06-13 (Stabilization: CI-green restore · ingestion-triage deploy · future-genesis 500 sweep · build_html split · Whoop re-auth · DLQ drain)

> A long multi-item stabilization session. **Nine PRs (#90–#98) merged to `main`**
> (tip `c256750`), and the full CI/CD pipeline is **verified green end-to-end**
> (run `27481953668` = `success` — Lint, Tests, Deploy, I1–I9, Smoke, Visual+AI QA).
> Several fixes were **deployed + verified live**; two layer-resident changes are
> **merged but intentionally NOT deployed** (see Deploy Ledger).
>
> **The headline:** `main` CI was RED at session start (an F821 + the lint gate),
> and the inbox was full of "Run failed: CI/CD - main" emails. Root-caused to a
> mix of (a) my own F821, (b) a **future-genesis 500 class** (cycle-4 genesis is
> `2026-06-14`, staged in the future → `DATE#genesis > DATE#today` ValidationExceptions),
> and (c) a 55-message DLQ backlog from the Whoop token outage. All three resolved.

**Prior:** `handovers/HANDOVER_2026-06-09_ER02_Contracts.md`.

---

## 0. Deploy Ledger — what is LIVE vs merged-only

| Change | PR | Deployed? |
|--------|----|-----------|
| Ingestion triage F3/F4 (MCP tools) | #91 | ✅ `life-platform-mcp` — live-invoke verified (`pre_genesis`, no 500) |
| Ingestion triage F1 (food-delivery freshness 90→14d) | #91 | ✅ `life-platform-freshness-checker` — `deploy_and_verify` passed |
| `/api/habits` future-genesis 500 fix (`_experiment_date` clamp) | #97 | ✅ `life-platform-site-api` (full `web/` pkg) — `/api/habits` 200 via CloudFront |
| `/api/journey_timeline` 500 fix (`_clamp_today`) | #98 | ✅ `life-platform-site-api` — 200 verified |
| Whoop refresh token | — | ✅ re-authorized live; gap-backfill ran (data through today) |
| DLQ drain (55 stale Whoop msgs) | — | ✅ purged → depth 0 (I9 green) |
| `build_html` section split | #94 / #18 | ❌ merged only — `html_builder.py` is a **layer** module; no behavior change; rides next governed layer deploy |
| `/api/vacation_fund` guard | #98 | ❌ merged only — `vacation_fund.py` is a **layer** module; **self-heals at genesis (00:00 → 2026-06-14)**; needs a governed layer deploy |
| Whoop re-auth redirect default `:3000` | #96 | n/a (dev helper script, no deploy) |

**No drift:** deployed layer = `v83`, `cdk/stacks/constants.py SHARED_LAYER_VERSION = 83`. I2 green.

---

## 1. CI-red recovery (#92, then #90/#91 brought current)
`main` was red on an **F821 `_error` undefined** in `site_api_vitals.py` (my own time-scrubber bug) + the **now-enforced black/ruff lint gate** shadowing it. #92 fixed the import + reformatted 10 black-dirty files + 3 ruff I001 + 2 justified `noqa` (S105/S602 false-positives in `deploy/`). #90 and #91 were branched pre-gate, so they'd have re-reddened main — both rebased onto green main and re-verified before merge.

## 2. Ingestion triage F1–F4 (#91) — DEPLOYED + verified
- **F3** `get_weight_loss_progress`: honor explicit `start_date`; future-window guard → `pre_genesis` instead of `ValidationException`.
- **F4** `get_body_composition_trend`: honest "DEXA-only, needs ≥2 scans" message + window guard.
- **F1** `food_delivery`: staleness guard in dashboard view + `freshness_checker` threshold 90→14d (was masking a dead feed for months).
- **F2** macrofactor: common-cause check — verdict was **independent manual-CSV-feed abandonment, NOT systemic** → **Monarch build gate CLEARED** (still deferred on token + board).
- RCA: `docs/rca/RCA_2026-06-13_ingestion_triage.md`. Regression tests: `tests/test_health_window_guards.py`.

## 3. Whoop restored (#90 helper, #96 default) — LIVE
Refresh-token rotation had broken ingestion (400s every run). `deploy/setup_whoop_auth.py` (#90) walks the OAuth re-auth; ran it live → secret updated, `/recovery` verified, gap-backfill triggered (data flowing through today). The app's registered redirect is **`http://localhost:3000/callback`** (port 3000, not 8080) — #96 fixed the script default so the next re-auth works flag-free. See `memory/project_whoop_reauth.md`.

## 4. Email golden nets (#93, #95) — tests only
- #93: golden render harnesses for `weekly_digest` + `monthly_digest` (fed via the real `ex_*` extractors on a frozen dataset, so the pinned shape can't drift).
- #95: a second **"everything-on"** daily-brief golden + a **`"section unavailable" not in html`** invariant (no section may silently fall back to its error placeholder). Closes the gap that the single quiet-day golden left uncovered.

## 5. `build_html` decomposition (#18 / #94) — merged, NOT deployed
`html_builder.build_html` (~1,534 lines) → a **72-line orchestrator** + 7 `_brief_*` section helpers. Behavior-preserving by construction (verbatim section moves; write-only `html` accumulator → local `out`); verified byte-identical via the golden **plus a 10-scenario equivalence harness**. **Layer module → not live until the next layer deploy** (no behavior change, no urgency).

## 6. Future-genesis 500 sweep (#97 + #98) — web side DEPLOYED
Cycle-4 genesis `2026-06-14` is in the future, so any `Key('sk').between(DATE#genesis, DATE#today)` query 500s (`lower > upper`).
- #97: clamp `_experiment_date` to today (fixes `/api/habits` + every `_experiment_date`-derived caller). Helper-based, no-op once genesis ≤ today.
- #98: audited **every** direct `.between()` in `web/`. Two used genesis directly: `handle_journey_timeline` (clamped via new `_clamp_today`) and `vacation_fund._query_range` (added the `start>end → []` guard `_query_source` already had). Everything else is `today-N` (safe), `_query_source` (guarded), or `_experiment_date` (fixed).
- Tests: `tests/test_experiment_date_window.py`.
- **All self-heal at genesis tonight regardless** — these are the durable guards for every future reset.

## 7. DLQ drain — purged
`test_i9_dlq_empty` was failing on **55 messages** = stale Whoop scheduled-event failures from the token-outage window (confirmed by peeking bodies: `aws.events` / `WhoopIngestionSchedule`). Superseded by the re-auth + backfill → `aws sqs purge-queue` → depth 0. I9 + the `dlq-depth-warning` / `ingestion-dlq-messages` alarms clear.

---

## Pending / next session
1. **Governed layer deploy** (ships #94 `build_html` + #98 `vacation_fund` guard). `/api/vacation_fund` **self-heals at midnight** so there's no urgency. ⚠️ A `cdk deploy --all` is a **full 8-stack / 79-function reconcile** (see Gotcha #1) — do it deliberately, through the production-approval gate, not as a casual one-off.
2. **Cycle-4 genesis = 2026-06-14** — the experiment routine starts; expect the future-genesis stragglers to self-heal and Day-1 data to begin accruing.
3. **#16 ghost counterfactuals** — held until ~2026-06-28 (needs ~2 weeks of cycle-4 correlation history; honest within-sample-contrast only, never a projected ghost line — ADR-086).
4. **Monarch financial integration** — gate cleared (triage proved failures were independent), still blocked on the Monarch API token + board sign-off.

## Gotchas learned this session
1. **CI ships CODE only, never the layer.** `update-function-code` per function; the shared layer is CDK-managed. So a layer change needs a manual `cdk deploy` — and because CI's code-deploys drift every function's asset hash vs CDK, a `cdk deploy --all` redeploys **all 79 functions across 8 stacks** (verified via `cdk diff --all`), effectively a full reconcile. Plan layer deploys accordingly.
2. **Check the OVERALL run conclusion, not just Lint+Tests.** The "Run failed" emails came from post-deploy jobs (I9 DLQ, Visual+AI QA) that only run on **code-deploying** merges; test-only merges skip Deploy and look green. Lint+Test green ≠ run green.
3. **`gh pr merge` does NOT fast-forward local `main`.** Branch from `origin/main` (or `git merge --ff-only origin/main` after fetch), else you re-introduce already-fixed bugs (this cost a CI cycle on #93).
4. **`cdk diff`/`cdk synth` write to STDERR** — capture with `2>&1`, not `2>/dev/null`.
5. **Whoop redirect URI = `http://localhost:3000/callback`** (registered on the dev app, client `0902cf1d…`). The redirect page 404s/refuses — that's expected; copy the `?code=` URL from the address bar. Codes expire ~30–60s.
