# Handover — 2026-09-01 (Opus 5): Session Q — Day 1, the launch-day P1

**Session:** Claude Opus 5, plan-mode entry. The owner's ask was open — *"what do you think
we should work on today — either open issues, something else, skills, health check, bug bash,
whats a logical plan together — i have a day off and working from home"*. Two clarifications
answered by the owner up front: **subject first, then I build** (the September posture — the
owner USES the platform, sessions are bug-fix-only), and a **standing deploy grant for the
day** on bug fixes, still stopping before data/IAM/experiment-anchor changes.

The plan that came out of orientation was not a backlog sweep. Day 1 of cycle 15 had exactly
one thing wrong with it that a reader could see, and it was found by measuring rather than by
reading the backlog: `/api/board_ask` was returning 504s.

---

## What shipped (all merged AND deployed AND verified live)

| PR | Issue | What |
|---|---|---|
| **#3415** | **#3413** (P1) | The ADR-108 quality gate removed from the `/api/board_ask` reader path — both call sites + `enforce()`; `board_quality_gate.py` reduced to the pure #1973 rule; structural anti-reintroduction guard; ADR-108 scope narrowed in `docs/DECISIONS.md` |
| **#3416** | **#3412** | `check_alarm_citations.py` — one grammar-based `issue_refs()` replacing two bare `re.findall(r"#(\d+)")` sites, so a citation can quote `DATE#2026-08-24` without inventing issue #2026 |

**Filed (3):** **#3414** (the deferred async-verdict half of #3413), **#3417** (the Withings
"scale is weight-only" premise is false since 2026-08-16 — #486/B-3 deleted the body-comp
delta on it, and the lean-mass floor has no instrument), **#3418** (the six `Pending owner
cdk deploy` warnings returned one day after #3365 verified them cleared).

**Closed (2 by this session):** #3413, #3412 — both with ADR-099 outcome verdicts. Also added
the missing verdict to **#3410** (closed pre-session, but this session held the live proof its
fix worked).

---

## The finding grew twice under measurement

#3413 was filed as a tuning defect: a 10s client cap below a gate whose *max* was 11.5–17s.

**First correction — it was worse than the max.** `coach-quality-gate` Duration from CloudWatch
Logs REPORT lines: **7d n=211 p50=10434ms p90=20580ms**; 48h n=68 p50=16371ms. The cap sat below
the callee's **p50 in both windows**. Both windows are carried in the module docstring on purpose,
because they disagree and the weaker one still settles it.

**Second correction — it had never worked at all.** Seven days of live board traffic:
**8 gate attempts → 6 "skipped", 2 read timeouts, 0 verdicts**, and `BoardQualityGateFired` has
no datapoint in all of August. Not degraded; never functional on this surface. That flipped the
fix from "retune the cap" to "remove it, and say plainly that the board's voice-fidelity rate is
now *unknown* rather than fine."

**Deliberately not built:** the plan called for keeping the verdict via an async invoke. With 0
verdicts in 7 days that would be *new* capability, not preserved capability, and needs a
wire-contract change to the gate Lambda. Filed as #3414 rather than bolted onto a P1.

---

## Verified

- **Live probe:** `POST /api/board_ask` 3 personas — **33.9s (and 504s at the boundary) → 12.8s, http 200**, all three coaches answered. Origin `REPORT` durations: pre-deploy max **30,000ms** (the timeout), post-deploy max **9,559ms**.
- **By shipped CONTENT, not sha:** pulled the deployed zip — `site_api_ai_lambda.py` has zero live gate references; `board_quality_gate.py` exposes exactly `_day_n_today`, `cycle_boundary_violations`, `_pt_day_contract_extract_day_n`, no `enforce`, no boto3. `LastModified 2026-09-01T19:10:13Z`.
- **Canary named:** post-deploy invoke of `life-platform-ai-quality-canary` returned `status: OK`, `alarms: []`, `board_grounded:status: OK — 200` — the exact check that had been failing. `ai-canary-overall` **ALARM → OK at 12:20:36 PT**.
- **Guard mutation-proved both ways:** reintroducing `_bqg.enforce(` reds it; reintroducing a raw `invoke(..., "RequestResponse")` reds it; restored → 19 pass.
- **#3412 proved against the live board,** not a fixture: `check_alarm_citations.py` green against live CloudWatch; the two restored citations parse to `['3410']` and `[]`.
- Full suite **23,717 passed**; the 4 failures are `test_count`/doc-literal drift that **also fails on clean main** (verified by stash) — the reconcile-bot-owned class.
- Post-deploy gates: `Smoke test: success` · `Post-deploy integration checks (I1/I2/I5): success` · `Auto-rollback: skipped`.

---

## Gotchas hit

1. **My own guard was vacuous, and only the mutation proof caught it.** The first version rebuilt source by joining token strings, which separated `_bqg.enforce(` into `_bqg` `.` `enforce` `(` — so the needle could never match and the guard would have passed forever. Now it blanks comments **in place** (the #3413 record necessarily names the gate it removed, so a bare substring match reads the explanation as the offence) and carries a positive control asserting the multi-token needle is still findable. *A check you have never seen fail is not yet a check.*
2. **The swallow detector has a false-positive path, and the documented command is broken.** `gh run list --commit <SHORT_SHA>` returns **0** silently — byte-identical to a real dropped push — and the `gh api ... -f head_sha=` form written in memory forces a POST and 404s on every sha. Use `gh api "repos/$REPO/actions/runs?head_sha=$FULL"`. Dangerous because the documented response to a swallow is to dispatch a redundant deploy. Recorded in `reference_swallowed_push_no_runs_at_all`.
3. **"Approve the tip, reject ancestors" earned itself.** The reconcile bot's commit looked like a docs-only chore but changed `lambdas/web/platform_counts.py` — real lambda code the P1's own sha lacked. Approving the P1's sha would have shipped a stale counter module.
4. **`check_main_green.py` reads rejection comments back verbatim** to classify a rejected lease as "not a red main". Substantive rejection comments are load-bearing, not cosmetic.
5. **Don't touch the tree while a full suite runs in background.** Saw `999 Lambdas` appear in `docs/ARCHITECTURE.md` and discarded it as corruption — it was a running test's deliberate mutation.
6. **I pattern-counted instead of reading**: grepped the Day-1 brief for "hold", got 10 hits, and they were all `threshold=0.75`. The brief was clean.
7. **A waiter that polls a rate-limited endpoint writes to coach memory when it succeeds** — killed it before its first success; verified `sleep_coach` memory clean.

---

## Gate lines

**Build beat:** 2026-09-01-the-gate-that-never-once-answered
**Docs:** docs/DECISIONS.md (ADR-108 amendment + ADR-103 scope row narrowed), docs/CONVENTIONS.md (§4a2 closure-contract block re-rendered), docs/INCIDENT_LOG.md (+1 row + Patterns regenerated), docs/alarm_citations.json (2 citations restored to quote keys; qa-smoke-failures re-pointed), scripts/closure_contract.py (#3413 disposition)
**Decisions:** none needed — the ADR-108 scope narrowing is an amendment to an existing ADR, filed in `docs/DECISIONS.md` with its measurement; no new governance decision was made
**Main:** green (b1933150)
**Incidents:** 1 row added — the ~34h `/api/board_ask` 504 outage spanning launch day (P2; immediate canary detection, ~31h escalation because the alarm sat under the 72h citation bar)
**Stash/hooks:** clean
**Closures:** #3413, #3412 commented (plus the missing verdict added to #3410, closed pre-session but this session held its live proof) · DoD: scanned 8, hits 1 — #3401's post-close comment belongs to the prior session (not this session's closure, left for its owner); #3413's two post-close comments dispositioned in `scripts/closure_contract.py` as structural to `Fixes #N` + deploy-after-merge on any issue whose acceptance demands a live probe
**Backlog:** Now live at 3 actionable (opus lane) — `now_liveness` not firing, no promotions needed; Later sweep — no stale issues, 37 open satisfy the ADR-099 contract
**Alarms:** 4 red, all cited — `freshness-interior-gap` (permanently unclearable, cited in prose), `qa-smoke-failures` (re-pointed this session to derived prose with the two commands proving the cure), `qa-smoke-warnings`, `token-alarm-genesis-window-active` (dated, self-clears 09-08). `ai-canary-overall` cleared this session; `life-platform-s3-bucket-size-high` cleared on its own dated window
**CI warnings:** 7 — (1–6) the six `Pending owner cdk deploy` stack warnings, filed as **#3418** (they returned one day after #3365 verified them cleared, and only two `cdk/` commits landed in between, so the leading hypothesis is that CI synth re-mints them and they are unclearable by deploying); (7) the Unit Tests duration budget at 2200s/1950s — already filed as **#3403**, deliberate no-action this session because that issue's own acceptance requires a week of post-#3378 data before re-measuring. `--decoded` after naming all seven
**Ledger:** none — no standing machinery shipped; #3413 REMOVED a subsystem from the board reader path and its ADR-103 scope row in `docs/DECISIONS.md` was narrowed in the same PR

---

## Residuals / next picks

- **The 7-persona worst case on `/api/board_ask` is UNMEASURED** — #3413. The rate limiter charges one request per coach and the probes spent the budget; synthetic invokes were declined because `_write_board_interaction` would pollute Day-1 coach memory. Arithmetic says ~22s at origin, which is not a measurement. Stated as unmeasured on the closed issue.
- **#3414** — recover the board's voice verdict on an async channel; near-free, the gate already runs to completion and is billed.
- **#3417** — the Withings full-scan finding. Practical half for the owner: **hold the handles**. The basic weigh gives weight only; the full scan adds ~30 fields including segmental composition, and `lean_mass_floor_lbs: 155` is a documented hard stop with no instrument behind it otherwise.
- **#3418** — do the six CDK warnings clear by deploying at all, or does CI synth re-mint them?
- **#3390** — Day-1 verification sits at 23/24. The only open box is the supersede reflex, blocked on a real Day-1 weigh-in; the owner stepped on the scale but it did not register on withings.com either, so the reading does not exist upstream. Reflex is pre-staged: `PROFILE#v1.baseline_weight_lbs` + `user_goals.timeline.{start_weight_lbs,start_weight_kg,baseline_measurement_utc}` → `sync_constants_from_config.py` → rebake game/home → CHARACTER.md stamp.
- **#3403** — the Unit Tests duration budget; its own acceptance says wait a week for post-#3378 data.
- **`coach-quality-gate` exceeds its own 30s ceiling on 4% of invocations (8/211 over 7d)** — not-work — an owner decision, flagged in-session rather than filed to avoid inflating a deliberately small backlog: on the daily brief that fails open by design, so ~4% of coach sections ship silently ungated. Measured, intentional, currently invisible. Flagged to the owner in-session rather than filed, to avoid inflating a deliberately small backlog.
- **#3401's post-close comment** — not-work — belongs to the prior session's closure, left for its owner rather than dispositioned by this one.

**The through-line, for the next session:** three instruments that reported something other
than what they measured — a quality gate that returned nothing while looking healthy, a citation
gate that invented an owner out of a date and thereby masked a real dead citation, and a
swallow-detector that answers "0 runs" to a question it was never asked. In each case the green
came from the instrument not being able to fail.
