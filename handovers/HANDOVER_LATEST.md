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

---

## Plan for Session R (written 2026-09-01, post-wrap — owner-approved in-session)

Owner context for the reader of this plan: Fable is back and set as the default model; the owner asked for "a good plan for the next session — either getting workable open items to zero, or skills/other ideas: improving SDLC, autonomous agents toward zero-touch, bug bashing, architecture/design review". The three shaping questions below were asked and answered by the owner before this plan was approved. An architecture review was deliberately NOT chosen: the 09-08 Architect-ritual run covers it days later and is itself a dead-man (#2849's reopen trigger).

## Context

Fable is back (owner set it as default this session), which lifts the September
"bug-fix-only on Opus" constraint for session work — the owner's posture (he USES the
platform; the platform doesn't demand his time) is unchanged and this plan records that
distinction. Session Q closed the launch-day P1 and wrapped clean; the backlog now holds
**~9 startable items**, one Now epic whose children are ALL closed (#3042), and a
top-of-queue P1 that was waiting for Fable (#1407 — deliberately NOT this session's
flagship; owner chose the A-Grade closeout instead, and #1407 remains the obvious next
flagship after it).

Owner's three shaping calls (asked and answered):
1. **Flagship: #3042 A-Grade closeout** — dispose the remaining DIL-IDs, run the re-assessment.
2. **Zero-touch: design-first, filed issues** — no building this session.
3. **Fan-out: full drain (~8-9 lanes).**

One discovery reframes the zero-touch phase: **the autonomy survey already happened.**
#2849 ("the resident operator") closed 2026-08-30 having delivered the substrate spike
(`docs/OPERATOR_SUBSTRATE_SPIKE.md`), a five-role operating staff (Engineering /
Production support / QA / Architect / Reader) with an ADR-129-style authority ladder,
and one leg live: the `architect-operator-2849` weekly routine, **first real run
2026-09-08** with a written reopen trigger if it produces no report PR. So Phase 3 files
the *next legs of that staff*, grounded in Session Q's measured pain — it does not
invent a parallel autonomy program.

## Phase 0 — Boot, leases, and loose ends from Session Q (~20 min)

- **Dispose the parked CI/CD leases.** The wrap push (`6a935ae8e`) and this plan's own
  docs-only commit each mint a gated CI/CD run that parks at the production approval gate.
  Reject ancestors, approve the tip; hold ONE persistent lease steward for the whole session (memory:
  `reference_lease_steward_must_outlive_the_tip`) — the full drain will mint one lease
  per merge and Session Q disposed 4 by hand.
- **Confirm the wrap sha settled green** (swallow-check with the FULL sha —
  `gh api "repos/$REPO/actions/runs?head_sha=$FULL"`; a short sha returns 0 silently).
- **#3394**: the visual-qa cron fires in practice ~22:30–23:45Z; it should have
  auto-closed overnight. If still open with a fresh failure, it becomes a drain lane.
- **The 7-persona probe** (#3413's stated-unmeasured worst case): the rate window is
  open. One `POST /api/board_ask` with all 7 coach ids, report the real wall time on
  closed #3413. If it breaches ~30s, file the fan-out issue (parallelize or
  deadline-aware persona cap) — that's the pre-agreed disposition, not a re-litigation.
- **Usage headroom check before the fan-out** (memory: `feedback_usage_headroom_before_fanout`).

## Phase 1 — The full drain (~8 lanes, worktree-implementer fan-out)

Standing sanctioned fan-out: one issue per lane, isolated worktrees, PRs behind full CI,
merged through the reconcile-branch / stacked-census discipline. Lanes by stored rank:

| Lane | Issue | Shape |
|---|---|---|
| 1 | **#3369** (Now·P3) | diff the two daily prose-truth judges' claim sets → merge or record complementarity (≤−$2-3/mo) |
| 2 | **#3374 R1+R3** (Now·P3) | cost-surface baseline ratchet into the #2845 model-drift gate + per-feature AI budget ledger, `unknown` down-only at $33.19 (R2 shipped) |
| 3 | **#3395** (Next·P2) | site rollback's SMOKE leg gets a reachability scope (the #3352 gap, smoke edition) |
| 4 | **#3399** (Next·P2) | reader-truth judge: `basis:"withdrawn"` emitted 0 times in 35 findings; a self-withdrawn finding gated as `impossibility` |
| 5 | **#3414** (Next·P3) | board voice verdict on an async channel — the gate already runs to completion and is billed; wire-contract change, brief path byte-unchanged |
| 6 | **#3417** (Next·P3·sonnet) | correct the "scale is weight-only" comments; record the body-comp-delta decision + lean-mass-floor instrument (absence semantics per NEW_SIGNAL_PLAYBOOK — sparse/behavioral, n=2 real scans) |
| 7 | **#3418** (Next·P3) | discriminate the three hypotheses on the recurring `Pending owner cdk deploy` warnings — compare DEPLOYED template vs CI synth vs local pinned synth for one Web `Comment` field; if CI synth diverges, they're unclearable by deploying |
| 8 | **#3376** (Later·P3) | per-door page-view instrumentation for the three most expensive features |

Parked, with reasons the lanes must not override: **#3403** (its own acceptance requires
a week of post-#3378 duration data — earliest ~09-08), **#2978** (`blocked:date`),
**#2883 + #3390** (`gate:owner` — surface both as numbered owner asks at wrap),
**#3373** (fable design work — folds into Phase 3's filing pass instead of a lane).

Merge-train discipline (all from memory, all bitten before): assert the expected check
set BY NAME before any merge; swallow-check every push by FULL sha; rebase census PRs
onto the previous PR's tip and re-rebase after EACH squash; lane-unique scratchpad
filenames; the steward rejects ancestors and approves only the tip.

## Phase 2 — Flagship: the #3042 A-Grade closeout (Fable)

All 16+ child stories are CLOSED; the epic's live gap is the register and the
re-assessment. (Memory: epic checklists are stale by construction — reconcile the boxes
from live child state first.)

1. **Dispose the remaining DIL-IDs** in `docs/reviews/DILIGENCE_2026-08-23_RESPONSE.md`
   (20 of 52 done as of 08-31). Dispositions come from evidence — the closed children
   (#3043-#3050, #3113-#3128, #3278, #3340) and `scripts/diligence_verify.py`'s live
   asserts — never from re-narration. Each row: CONFIRMED-fixed / STALE-corrected /
   WRONG-evidenced / PRICED-accepted-with-date.
2. **Run the re-assessment** against the original report's §12 acceptance matrix on the
   non-commercial domains, via the `/review` spine (the platform's graded-review ritual)
   with the diligence rubric as the anchor set; adversarial verification pass on every
   finding (finding-verifier — ~50% of first-pass findings are historically false).
3. **The honesty gate on closing:** the epic's outcome asks for an *external*
   re-assessment ≥9/10. A self-run review with fresh-context agents is the sanctioned
   equivalent of how the ORIGINAL diligence was produced, but that equivalence is the
   owner's call, not the session's. If any domain scores <9, or the owner hasn't blessed
   the equivalence, the epic stays OPEN with the register complete and a one-line ask —
   an epic can pass every box and fail its Outcome, and the Outcome sentence decides.
4. `diligence_verify.py` must exit clean after the register edits; the epic body's
   "Done when" boxes get reconciled to live state in the same pass.

## Phase 3 — Zero-touch: file the next legs of the #2849 operating staff (design-first)

No building. Each item lands as an ADR-099 issue citing `docs/OPERATOR_SUBSTRATE_SPIKE.md`,
with its staff role, authority tier (observe → propose-PR → act; never auto-promote),
substrate leg, and an ADR-103 rent line. Candidates, each grounded in measured evidence:

1. **Production-support leg: the reject-only lease steward.** Session Q disposed 4 leases
   by hand; the reject half is fully mechanical (a superseded ancestor is derivable from
   the run DAG) and `check_main_green.py` already reads rejection comments back as
   "not a red main". Authority: act, but REJECT-ONLY — approval stays human, consistent
   with the owner decision that retired the remediation agent's auto mode.
2. **Production-support leg: reader-facing canary escalation.** `ai-canary-overall` was
   red 31h across launch day with immediate detection and zero escalation — it sat under
   the 72h citation bar. Candidate: alarms whose Outcome audience is `reader` page or
   escalate on first red, not at 72h. (This is the incident row's own lesson.)
3. **Engineering leg pilot.** The spike's own acceptance names it: "the Engineering
   role's first week of PRs opened with zero owner terminal sessions" —
   `backlog_next.py` → worktree-implementer → PRs, propose-only, weekday-scheduled,
   budget-tier-gated. Phase 1 of this session is the manual dress rehearsal; file the
   pilot with Phase 1's measured cost/outcomes as the sizing evidence.
4. **Fold #3373** (feature/cost-toggle kill-switch registry) into the staff frame — it
   is the "act" tier's precondition for any Production-support automation (a kill switch
   per feature), so its issue gets that dependency stated and possibly a promotion.
5. **The unfiled 4%** — `coach-quality-gate` exceeding its own 30s ceiling on 8/211
   invocations (~4% of brief coach sections silently ungated): put the owner decision in
   the issue text rather than leaving it in a handover bullet.

Explicitly NOT in scope: reopening #2849 (that's the 09-08 architect run's dead-man),
any auto-merge or auto-approve authority, AgentCore (declined per ADR-103 with a dated
revisit trigger — respect it).

## Phase 4 — Wrap

Standard `/wrap`. Likely build beat: the A-Grade closeout (if it honestly closes) or the
drain count. Owner asks to surface, numbered: (1) #2883's gate:owner act, (2) #3390's
weigh-in — and per #3417, the full-scan handles, (3) the coach-quality-gate 4% decision,
(4) the external-equivalence call on #3042's re-assessment.

## Verification

- Every lane: full CI green by named check set; merged through the train; deploy leases
  disposed by the persistent steward; post-merge verify by shipped CONTENT where a lambda
  changed.
- #3042: `python3 scripts/diligence_verify.py` exits 0; register grep shows 52/52
  dispositions; the re-assessment scorecard is committed under `docs/reviews/` with per-
  domain scores and n/uncertainty per ADR-105.
- Phase 3: `python3 scripts/check_backlog_hygiene.py` green over the newly filed issues.
- Session end: `python3 scripts/wrap_gates.py` + `--verify` both green.
