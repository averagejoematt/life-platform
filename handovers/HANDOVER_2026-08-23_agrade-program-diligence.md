# Handover — 2026-08-23 (daytime, Fable 5, interactive→autonomous): the backlog campaign became the A-Grade Program — an external diligence report, fact-checked and turned into a plan

**Session:** Fable 5. Drove: `/plan` to "maximize fable use paying down the open-issues
list … the real north star is a stabilized, mature, production-grade platform a CTO/CPO/CIO
panel would accept." Executed Session 1 (triage) + Session 2 (drain) of the approved
backlog campaign, then the owner supplied an **external acquisition-diligence PDF** and the
campaign was re-planned to **absorb** it as the A-Grade Program. Plan:
`~/.claude/plans/lively-juggling-candle.md`. Previous handover archived as
`HANDOVER_2026-08-22_fable-week-session2.md` on `session-archive`.

## What this session was

Three arcs, in order:
1. **Campaign plan + Session 1 triage (interactive).** Built the campaign: get the debt
   corpus (49) to ≤20 while fixing the *inflow* (measured: 312 filed / 311 closed in 14
   days — the board churns, it doesn't drain). Triaged 49→43 (folds #2958→#2957,
   #2962+#2963→#2961, #2891→#2837, #2838→#2986; #1677→Roadmap), landed the filing-discipline
   rule (**CONVENTIONS §10** + issue-filer agent), committed clean.
2. **Session 2 drain (autonomous, merge+deploy authority).** Five worktree implementers +
   driver work. **6 issues closed via 8 merged PRs.**
3. **The diligence pivot (interactive→plan).** Read the 44-page report (52 findings, 5 P0,
   4.47/10, "conditional no-go"), fact-checked every claim live with 3 agents, and
   re-planned the campaign as the A-Grade Program. Filed the tracking epic + register.

## Shipped (merged + deployed unless noted)

- **#3005** (PR #3032) — tool-attribution-trailer ban: 4 instruction files fixed + guard test + §9 row.
- **#2993** (PR #3033) — Plan-job config-drift classifier (`classify_cdk_diff.py`); agent
  found the issue's hypothesis wrong (real trigger = CDK LogRetention runtime skew).
- **#3021** (PR #3034) — superseded-lease janitor (owner needs `DEPLOY_GATE_JANITOR_TOKEN`
  to fully arm — batch item).
- **#2944** (PR #3035) — journal-coach absence declared not laundered; **deployed daily-brief**
  (root cause: designed absence since the cycle-14 reset).
- **#3006 + #3007** (PR #3036) — wrap gates asserted (11 lines) + batched (12 runs → 2).
  *This wrap ran through the new battery.*
- **#2959** (PR #3038) — oracle ground-truth feed: cycle number + 5 rulings + 2 structural
  drops; ledger 38→8; **deployed qa-smoke** (sha-verified). See the honest residual below.
- **#2978** (PR #3039, "Part of", stays open) — confirm-before-fail primitive on both QA
  surfaces + the incident-classifier sub-shape split.
- **#3040** — extracted `daily_brief_signals.py` to fix a size-guard main-red I caused by
  merging #3035 past its (not-yet-required) full-suite lane.
- **#3041** — `docs/reviews/DILIGENCE_2026-08-23_RESPONSE.md`, the diligence response register.
- **Campaign scaffolding:** CONVENTIONS §10 filing discipline (commit a86415136).

## The diligence fact-check (the session's highest-value output)

Three agents verified all 52 findings against **live** repo/GitHub/site. The verdict is
materially better than 4.47/10 — and the gap is instructive:
- **3 of 5 P0s genuinely live** → Phase D0: DIL-001 (5 PRIVATE-marked coaching docs are
  world-readable), DIL-003 (/privacy/ "deleted immediately" vs 548-day retention + tokenless
  unsubscribe), DIL-007 (56% of the prediction corpus is `eval_type: qualitative` =
  structurally ungradeable — the report missed this, fixating on "0 graded" which is
  *correct*: nothing's due before 08-24).
- **2 of 5 P0s WRONG/STALE against current state** — DIL-002 fixed 08-21; DIL-004
  ("approval absent") is live+blocking now. **Root cause: the platform's own 7-week-stale
  `MANAGED_WHERE_LEDGER.md` manufactured the report's false positives.** Documentation truth
  is the external-assessment attack surface — D0.5 + D2 close it.
- **7 findings sharper than the report** (main has zero required checks; CodeQL regrew 7
  alerts; budget-guard hard-stop shares a fail-open path; etc.) — all in the register.

**Filed:** epic **#3042** [A-Grade Program] + stories **#3043–3050** + 7 folds
(#2824/#2828/#2890/#2578/#2986/#2834/#2799). Owner decisions: repo stays public+sanitized ·
commercial domains priced + a clinical-lite build subset · program absorbs the campaign.

## The honest residual — #2959's deploy rolled back

#3038's deploy auto-rolled-back the site (incident row added). The fix WORKED — every
documented oracle class dropped/demoted correctly on the live sweep — but the
non-stationary tail (#2959's own tracked remaining work) raised ONE novel high (a
correctly-dated 'WEEK 1 · 2026-08-18' chronicle piece on /story/), and a NEW finding
surfaced: **the visual-qa CI role lacks `ssm:GetParameter` on the experiment-cycle param**,
so the cycle ground-truth sentence is dark in exactly the gating path. Deploy content (the
receipts UTC-caption) was orthogonal — a rollback casualty. Site healthy on the prior build
(3ad9572, all 200s). Re-deploy + both residuals carry into #3042's oracle lane; re-deploying
now without baselining the new shape would just block again (the documented "3 blocks in one
night" anti-pattern).

## Gate lines

**Build beat:** none — the session's public-worthy work (the #2959 oracle rulings, the
receipts-caption fix) auto-rolled-back on deploy; nothing net-new is live on the reader
surface. Merged infra/QA (#3005/#2993/#3021/#3006/#3007) is not reader-facing dispatch material.
**Docs:** CONVENTIONS §10 (filing discipline, committed mid-session a86415136) +
`docs/reviews/DILIGENCE_2026-08-23_RESPONSE.md` (new, PR #3041) + INCIDENT_LOG (+1 row) +
this wrap's doc-sync literals. Register links the 10 filed diligence issues.
**Decisions:** none needed — the A-Grade Program's ADR-worthy calls (Tier-2 publication
consent, repo-posture) are staged as D0/D3 work (#3045 carries `gate:owner`), not landed
this session.
**Main:** green — the recent CI/CD "failures" (`4b89eba2`, `3862eb55`, `5557b0a2`,
`f4ef58f4`) are all deliberately-**rejected superseded/hand-deployed leases** (#2467/#1901
class, actioned this session), not test reds; HEAD's Docs CI is green and the live site is
healthy. Verified via `check_main_green.py --decoded`.
**Incidents:** 1 row added — the #3038 site auto-rollback (#2959 non-stationary tail;
deploy content orthogonal; + the visual-qa role's missing SSM grant; both fold to #3042).
**Stash/hooks:** clean.
**Closures:** #3005, #2993, #3021, #2944, #3006, #3007, #2959 commented (7 ADR-099 verdicts —
6 realized, #2959 partial-realized with residuals to #3042); the Session-1 folds
(#2958/#2962/#2963/#2891/#2838) carry their fold-closure comments.
**Backlog:** Now 12 actionable (the A-Grade Program filed #3042–3050 into Now/Next — the
plan's expected transient rise from 39→46 debt, drains class-wise as D0–D5 close them); no
stale Later issues; #1677 score-line corrected to Roadmap.
**Alarms:** 3 flapped in the 72h window, all decoded — `ingest-auth-unhealthy-dropbox` +
`ingest-liveness-unhealthy` (the known #2976 recovery-episode cluster) and
`site-api-invocation-spike` (self-inflicted by this session's own full-surface QA sweeps
during the #2959 deploy verification; no reader symptom). No standing red >72h. Closed
with `--decoded`.
**CI warnings:** none — the newest completed main run isn't green (it's a rejected lease),
so `check_ci_warnings` has nothing to triage (that's the main-green gate's job).
**Ledger:** none — no NEW standing subsystem shipped this session; #2978's confirm-before-fail
and #2959's rulings extend existing machinery (reader-truth gate, smoke harness) already
in `docs/PROPORTIONALITY.md`, and #3036's wrap-gate batcher is session tooling, not a
production subsystem.

## Residuals / next picks

- **The A-Grade Program (#3042) is the spine** — next session boots Phase D0 (P0 truth:
  coaching-docs containment #3043, subscriber trust #3044, Tier-2 ADR #3045, prediction
  gradeability #3046, doc-truth kills, `apply_branch_protection.py --apply` for required
  checks, CodeQL #3047). Plan: `~/.claude/plans/lively-juggling-candle.md`.
- **#2959 oracle lane (fold into #3042):** re-deploy the receipts caption AFTER baselining
  the /story/ WEEK-1 finding; grant the visual-qa CI role `ssm:GetParameter` on the
  experiment-cycle param (the ground-truth feed is dark in CI without it) — not-work until
  D0, both recorded on #2959.
- **#3037 (recall indexer) — OPEN, blocked:** its fix breaches `monitoring_stack.py`'s size
  ceiling; carried into #3042's alarm lane where the cdk Email+Monitoring deploy chain gets
  proper attention (diagnosis on the PR). #2977 stays the tracker.
- **#2978 30-day re-measure** (~2026-09-22): the confirm-before-fail transient counters in
  both summaries are the data source — not-work, scheduled.
- **#2944 live verify** at the 08-23 17:00 UTC brief (declared-absent path) — not-work,
  scheduled.
- **Owner batch (staged for Session 5 / D1):** `DEPLOY_GATE_JANITOR_TOKEN` secret (#3021) ·
  billing-alarm dupes (#2961) · #2834 IAM posture · WAF decision (#2828) · notion-secret
  retire (#2890).
- **One lease may still present** on the #3038 CI/CD run if it re-queues — the deploy-wedge
  janitor (#3021, just merged) + next boot's `check_main_green` cover it — not-work.
