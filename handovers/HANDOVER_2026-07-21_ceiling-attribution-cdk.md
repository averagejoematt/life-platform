# HANDOVER — July ceiling window, achievements ledger, attribution + the CDK drift clear — 2026-07-21

> Instruction thread: "Pay down as much of the NON-FABLE backlog as possible" → owner
> approvals given live for push / the $110→$115 ceiling bump / cdk deploy / TikTok handle →
> "go" (1-2-3 for #1637) → "you go ahead and merge and do the cdk deploy and everything i
> approve" (#1642 + the full CDK drift clear) → "wrap and then give me back the plan."
>
> Third session of 2026-07-21 (after Glass-Engine, then brand-mark). Picked up the residual
> owner-queue from the first two and drained it.

## What shipped (all merged to main AND deployed/verified)

**#1635 — July-only ceiling raise ($115 base / $135 surge), self-reverting 2026-08-01** (PR #1635, `8b412d4a`).
- The projection was $96.09 vs the $85 base (113%), guard parked at **tier 2** — reader narratives paused. Matthew's call: raise for one month only.
- **$115 not the $110 first approved.** The tier bands are fixed FRACTIONS of the ceiling (≈73/87/97%), so $110 leaves the projection at 87.4% — *still tier 2*. $110 would have paid the full cost of raising the ceiling and bought nothing (missed by $0.87). $115 → 83.6% → tier 1. Verified live: `_decide_tier(96.09, 63.26, 21.0, ceiling=115) == 1`.
- **Fixed a latent surge inversion found in the process.** `_effective_ceiling` returned `SURGE_CEILING_USD` unconditionally, so any base >$100 made reader arrival LOWER the ceiling ($115→$100) and tighten the guard exactly when surge exists to loosen it — the success-punishes-you failure ADR-133 was written to prevent. Now floored with `max()`; pinned by `test_surge_never_lowers_the_ceiling`. Latent at any base over $100; predates this PR.
- Dated window (`_TEMP_CEILING_WINDOW`, half-open `[2026-07-01, 2026-08-01)`), auto-reverts with no deploy — tested across six injected dates incl. 2027-07-15 (must not recur annually). Removed the dead `_JUNE_2026_THRESHOLDS`. AWS Budgets backstop deliberately LEFT at $85 so the overrun still signals. **Deployed via `cdk deploy LifePlatformOperational`; governor invoked → tier 2→1 live.** ADR-133 amended.

**#1637 — achievements durable first-earn ledger** (PR #1637, `953566a2`, closes #1624).
- `handle_achievements()` set `earned_date=today if <cond> else None` for all 40 badges → a nightly snapshot dressed as an earned record; badges un-earned on a 2-lb water swing. Fixed as a writer/reader split: `lambdas/achievement_rules.py` (new, single source of catalog + comparators + ledger I/O), writer = `daily-metrics-compute`, reader = `site_api_vitals` (no serving-path writes, `git grep`-verified). Ledger is **EXPERIMENT_SCOPED** (registered in `phase_taxonomy.py`) — tomorrow's cycle-10 reset wipes + rebuilds it, by design.
- **Deployed: `deploy_site_api.sh` + `deploy_lambda.sh daily-metrics-compute`; writer proven to boot via a live invoke** (`first_earns_written: 0`, no crash — correct, cycle is 1 day old). `/api/achievements` serving 40 badges.

**#1642 — site-wide UTM capture + separate attribution signals** (PR #1642, `0809cc03`, closes #1621).
- The issue's diagnosis was factually wrong (corrected on-issue): the `source` field *was* sent and `referrer` *was* captured — the real defect was the referrer fallback being dead code on every real signup, plus zero UTM capture. Built: `site/assets/js/attribution.js` (site-wide landing capture, sessionStorage first-write-wins, read at submit), `lambdas/utm.py` (canonical tagger + host-only referrer), three SEPARATE signals stored, canary hard short-circuit, operator count-by-source in the weekly digest.
- **Deployed: `email-subscriber` + `weekly-digest` lambdas, then merged (site auto-deploy green); `attribution.js` live + hash-wired in the shared footer; canary short-circuit verified on the live endpoint.**

**CDK drift clear — all 9 stacks** (`npx cdk deploy --all`).
- The "pending cdk deploy" the brand-mark session flagged as "2 lambdas + a LogRetention runtime bump" was actually that **plus a brand-new scheduled email-sender**: `AiReviewPack` (merged PR #1594, weekly QA review email, defined in CDK but never deployed). Diffed before deploying: **zero deletions, zero replacements**, one new scoped IAM role, schedule `cron(0 18 ? * SUN *)` (no send on deploy). Deployed under explicit broad owner approval. **All 9 stacks UPDATE_COMPLETE; `cdk diff --all` = 0 differences; Plan gate re-run = success.**

## Also done (no code)
- **#1620** TikTok handle corrected to `averagejoematt`, `gate:owner` cleared (flagged X keeps a trailing underscore, TikTok doesn't).
- **#1589** closed with simulated-IAM + live-canary evidence (the canary un-blinded after the origin-secret grant landed in the first cdk deploy).
- **#1625** Reddit playbook shipped (`be6b519b`) — a separate wrap earlier today.
- **#1634** filed — the canary's advisory judge false-positives on sanctioned coach personas (found while verifying #1589; its own rule says *vendor*, Dr. Sarah Chen is a coach).

## Gotchas hit
- **The $110 fractional-band trap.** Tier bands are fractions of the ceiling, not dollars — the "obvious" round number was the one value in the neighborhood that changed nothing. Always check the ratio, not the number.
- **The surge inversion was invisible at $85.** A bug with no way to fire until the base crossed $100 — raising the ceiling is what would have activated it. Moving the surge value in the same change (not just `max()`) kept the pair coherent.
- **Agent self-reports are ~50% wrong on their own numbers.** The #1637 agent misreported its badge counts by ~2.3× (said 17 never-dated/23 wrong-date; actual 30/10). The #1621 issue body was factually wrong in two places. `git grep` the claim on the branch and run the suite before relaying — done for both.
- **`node --test tests/js/` (with a dir arg) fails; CI runs bare `node --test`.** A directory arg makes node try to resolve it as a module. The "JS test failure" was my invocation, not the tests (104 pass).
- **A hashed asset filename hides from a literal grep.** `attribution.js` looked un-wired until I grepped the live page and found `attribution.6d69289b.js` — the module graph hashes it. Grep the hashed form or the `import` edge, not the bare name.
- **CDK re-staged the same main tree over my manual lambda deploys** (email-subscriber, daily-metrics-compute) — harmless because both stage from main → identical SHA, not the older-code-overwrite class.

## Gate outcomes
- **Build beat:** `2026-07-21-badges-that-stay-earned` (the achievements ledger — reader-facing correctness fix; ceiling + attribution mentioned in a clause).
- **Docs:** DECISIONS.md (ADR-133 amendment), CLAUDE.md (ceiling line + status block); auto-synced literals. No new ADR needed beyond the 133 amendment.
- **Decisions:** none needed — the ceiling change is an amendment to the existing ADR-133 (filed in #1635), not a new governance decision.
- **Main:** red — `check_main_green` keys on the latest COMPLETED CI/CD run (`953566a2`, a pre-cdk-deploy Plan-gate failure). HEAD `0809cc03`'s every automated gate is green (Plan/Lint/Reconcile/Deploy-critical/Unit all success); the run only "waiting" at the manual production-approval Deploy gate. The Plan drift that reded `953566a2` was cleared this session (`cdk diff --all` = 0 differences, Plan re-run = success).
- **Incidents:** none — the standing Plan-gate red (R8-ST6 class, pre-existing across sessions) was RESOLVED this session by the CDK drift clear, not a new firing. No auto-rollbacks; both site deploys green.
- **Stash/hooks:** clean — `git stash list` empty, hook freshness 🟢.
- **Labels:** OK — all 71 open type:story issues carry a model:* label.
- **Memory:** compacted MEMORY.md 20.3KB→15.6KB (Edit-hook read-limit warning); added `reference_budget_ceiling_fractional_bands`; orphan gate + body-fact drift clean; S3-backed up.

## Residual / next picks
- **cycle-10 reset to 2026-07-22 (Wed)** — the headline of the next session. Full plan + paste prompt in the scratchpad `NEXT_SESSION_PLAN.md` (sent to Matthew). Preflight: NO Withings weigh-in exists for 2026-07-22 yet (latest = 2026-07-20 = 321.38 lbs) → re-check, else `--override-weight-lbs 321.38`. `restart_pipeline.py --apply` runs `cdk deploy --all` = OWNER-ONLY. `not-work — owner-run reset, tracked in NEXT_SESSION_PLAN.md`.
- **#1618** receipts projection curve — now more interesting: the ceiling moved mid-month, so a curve-vs-ceiling shows the tier crossing. (#1618)
- **#1634** canary judge false-positive fix. (#1634)
- **#1639 / #1640** head-chrome drift + OG-image brand marks (coordinate with the shipped #1638). (#1639, #1640)
- **#1620** outbound social links — unblocked now (TikTok confirmed); runs `v4_apply_chrome` HTML sweep → AFTER any reset. (#1620)
- **AiReviewPack (#1594) first fires Sunday 18:00 UTC** — a new weekly email to Matthew's inbox, went live in this session's cdk deploy. Matthew may want to review/disable before then. `not-work — owner review of a just-activated schedule`.
- **The nodejs22→24 LogRetention runtime bump is now deployed** (part of the drift clear). `not-work — resolved this session, no longer outstanding`.
- **Standing alarms:** none newly outstanding; budget tier 1 (July window working as designed, not an alarm). `not-work — standing-alarms checklist, nothing to action`.
