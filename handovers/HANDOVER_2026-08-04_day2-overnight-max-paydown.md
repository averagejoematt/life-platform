# HANDOVER — Overnight max paydown, Day 2: 9 PRs merged / 9 issues closed, 4 PRs staged, the Aug-5 send pre-flight — 2026-08-04 overnight → morning

> Instruction thread: *"overnight maximum paydown until ~05:30 PT … Fable drives only (preflight,
> briefs, serial merge queue, rebases, deploy-per-merge approvals, verification, wrap); every
> implementer a worktree-implementer on its issue's own model:* label; waves of ≤5 … I am asleep —
> batch every owner-only action into ONE numbered list."* Priorities: #2104 first, #2090 self-implemented,
> then down the stored rank; Aug-5 send pre-flighted dry-run-only; hard limits honored (no CDK deploys,
> no repo-settings mutations, no OAuth re-auths, no real sends).

**Main:** green (`d95bc763` — latest completed CI/CD run succeeded; four newer runs in flight at
wrap, two already gate-approved, watcher pattern documented below). One run (a9148f87) shows
`cancelled` — concurrency supersession by the next push, its content deployed by the d95bc763 run;
no rollback fired all session.
**Docs:** COACH_STANCE.md re-verified + #1973 gate documented (in-PR); RUNBOOK/TESTING via PRs;
alarm_citations.json unchanged (the #2104 citation stays until two green nights per its contract).
**Decisions:** none needed — all work was implementation of already-decided shapes (ADR-104/105/108/133 patterns).
**Incidents:** none — main never red (the three mid-flight PR-check failures were pre-merge), no
auto-rollback, no budget event (tier 0 all night).
**Build beat:** 2026-08-04-a-pre-genesis-weigh-in-is-not-todays-weight.
**Closures:** #423 #1950 #2104 #1970 #2090 #1243 #1961 #1973 #1962 all commented (ADR-099 two-line
verdicts; honest partials wherever a stored artifact, backfill, or owner step remains).
**Backlog:** Now holds 4 actionable (#2112, #2113 — both with open PRs staged; #1383, #1114 await
Matthew's interactive input); Later sweep clean (hygiene OK, 84 open, zero violations); 7 issues
filed tonight (#2109 #2111 #2112 #2113 #2116 #2119 + the two fixed-audience edits), all contract-clean.
**Alarms:** all reds >72h cited (gate exits 0); `qa-smoke-failures` stays honestly red until the
coach-card regen below.
**Stash/hooks:** clean — stash empty, hook freshness 🟢.

---

## What shipped (9 PRs merged; 8 more filed-and-staged artifacts)

**The genesis-honesty spine (#2104 → #2113, the session's story):**
- **#2104 → PR #2108** (opus): measure-first killed BOTH stated causes — the coach card was
  generated *post*-genesis (17:38Z), and Home's "seven days of life" was an LLM misquote of the
  cockpit. Real defects: `weight_recency`'s age-only staleness (a 2-day-old pre-genesis weigh-in
  passed as current) and the cockpit's static no-JS copy. Fix is structural per ADR-104: a
  pre-genesis weigh-in emits NO current-weight fact at any age, so `grounded_generation`'s
  allow-list treats a citation as fabrication; cockpit captions span-neutral; restart_verify
  check 16. Fleet + site deploys verified green.
- **#2113 → PR #2123 (OPEN, staged)** (opus): the SAME pilot `computed_metrics` row also fed
  recovery 59%/HRV 42ms into the sleep/training cards (and was where #2104's 317.0 came from —
  the second leak path). Fix: `phase_taxonomy.cycle_read_floor` (key-floor, never a
  FilterExpression — the Limit-before-filter trap), withhold-from-facts, cross-surface gate
  widened weight→4 vitals, restart_verify check 19. Full suite green, 31/36 new tests fail
  pre-fix. **Needs merge + deploy + the two regen invokes.**
- **#2090 → PR #2110** (self, fable): the ratchet now resolves module-level `#SOURCE#` constants
  (AST keyword verdicts, worst-call-wins — substring matching had let a *docstring* grade a site).
  Derived set 21→52; every new site read and classified (17 sanctioned, 7 debt → **#2109**, 5
  per-source); the #2089 pair derives as per-source exactly as acceptance required.

**Reset-window alarm pair:** #1961 → PR #2114 (dispatcher-side suppression window, ADR-133
dated-window pattern; human-email half is CDK-gated → **#2116**) · #1962 → PR #2118 (compute-stale
suppression marker + emitter reports 0.0 in-window; reader banner untouched; premise live-verified
against cycle-11's two false-red mornings). Both renumbered into restart_verify as checks 17/18.

**Data-integrity smalls:** #1950 → PR #2106 (NARRATIVE#arc keeps its semantic closing state across
future wipes; cycle-4's row recoverable via owner backfill) · #1970 → PR #2117 (seeder stamps +
qa-smoke WARN guard + dry-run backfill script; remaining unstamped writer → **#2119**) · #423 →
PR #2105 (parked-register pointers) · #1243 → PR #2107 (chronicle-podcast regen in the reset
pipeline + nightly parity check; the stale episode needs one regen invoke post-deploy).

**Staged OPEN PRs (implemented, tested, wrap deadline hit before their merge turn):**
- **PR #2120** (#2112, sonnet) — per-installment `delivered_at` marker closes the Wednesday
  double-send; "Week 0.0" → int. **Merge+deploy before Wed 15:10 UTC** (see owner list #1).
- **PR #2121** (#1976, sonnet) — CSS sanction grammar requires an issue ref on deferral-style
  sanctions; live `hex-ok` count measured at zero, so no backfill needed.
- **PR #2122** (#1982, sonnet) — ADR-105 target provenance rendered on /data/character/
  (`PERSONAL · P75 · 365D · N=341` chips); site-only, Playwright before/after in PR.
- **PR #2123** (#2113, opus) — above. Rebase note: restart_verify check renumbering (19) already
  applied at the driver rebase; expect only doc-sync literal conflicts at merge time.

## The Aug-5 first-Wednesday-send pre-flight (owner review material)

**No invoke was made and none is safe:** `chronicle-email-sender` has **no dry_run gate** — any
invoke, including `{"dry_run":true}`, is a REAL send (it reads no event flags). Filed **#2111**.
Read-only verification instead: EXTERNAL_EMAILS_ENABLED=true (lifted 08-03), **1 confirmed
subscriber**, sender cron Wed 15:10 UTC (10 min after the generator DRAFTS — approval comes later).
Measured consequence: at 15:10 the sender's ≤7-day published-installment lookup finds the KEPT
Aug-2 prologue (`phase=experiment`, week 0) → sends it with subject **"Week 0.0"**; a later
approval of Week 1 fires the sender AGAIN via chronicle-approve's async-invoke → double-send day.
Filed **#2112** (P2, Now); **PR #2120 closes the double-send + the subject formatting and is staged.**
Rendered subscriber email saved for review:
`/private/tmp/claude-501/-Users-matthewwalker-Documents-Claude-life-platform/19c33740-39b8-4669-b94c-68701629b110/scratchpad/aug5_send_render.html`
(subject: `The Measured Life — Week 0.0: "The Plan, On the Record"`, 3.1 KB).

## Verifications run

- Preflight: main green at 51b8af30, no wedge, stash empty, rank trusted (never re-scored).
- #2108's fleet deploy (run 30921231401) + site-deploy both completed success — the genesis-week
  weight fix is LIVE; d95bc763 run success covers #2110/#2117.
- **#2079 box 4: still open** — zero coach-state-updater invocations after 08-03 18:00Z (checked
  CloudWatch); the first genuinely post-genesis run is today ~17:01Z, minutes after this wrap.
- Budget tier 0 all session (AI CI gates alive); the #2104 work itself incurred zero Bedrock spend
  (regens deferred until post-deploy by design).

## Gotchas hit (carry these)

- **black 25.9.0 vs the 26.3.1 pin**: local PATH black lies in both directions — it MISSED the one
  real violation on #2107 (CI caught it) and false-flags ~30 clean files. The pre-commit hook
  resolves black from PATH. Fix used: a scratch venv with the pinned 26.3.1; all queue branches
  pre-checked with it after the first CI red.
- **Touching `ai_calls.py` (or any engine-doc source) trips the strict wiki gate** — the engine
  doc's `Verified:` date must be bumped WITH the change (COACH_STANCE.md re-verified for #2115;
  implementer briefs should name this).
- **The blind-add-mid-conflict trap fired once** (compound rebase command on #2118 staged a
  conflicted file): caught immediately, `git rebase --abort`, redone one-file-at-a-time. Compound
  resolution commands must never chain `add -u` after a possibly-failed `rebase --continue`.
- **Concurrent restart_verify checks collide on numbering** — assigned 16/17/18/19 in merge order
  at driver rebase; each later PR re-conflicts and renumbers mechanically.
- **Monitor UNSTABLE ≠ failure** on a just-force-pushed PR — transient recompute; filter on rollup
  conclusions, not mergeStateStatus alone.

## Residual / next picks

- **Merge the 4 staged PRs** (#2120 → #2121 → #2122 → #2123, deploy-per-merge; #2120 first for the
  Wednesday deadline) — closing open issues #2112, #1976, #1982, #2113 respectively; every branch
  is rebased-or-one-rebase-away, all pre-checked with pinned black.
- **Post-deploy regens (one-liners, session-runnable):** `ai-expert-analyzer` `{"expert":"physical"}`
  + `{"expert":"sleep"}` + `{"expert":"training"}` after #2123 deploys (clears `cross_surface`
  red + the #2104 stored card); `chronicle-podcast` bare regen for the stale episode (#1243's PR
  body records it; it emails nothing). not-work — recorded ops steps from merged PR bodies.
- **#2079 box 4** — read coach-state-updater logs after today's ~17:01Z run (expect gradability
  >0%); record on the closed issue. not-work — verification step on a closed issue.
- #2109 (compute-layer genesis-blind batch, Next) · #2116 (token-page human-email half, Later) ·
  #2119 (_cache_brief stamp, Next) · #2111 (sender dry_run gate, Next) — filed tonight, ranked.
- Frontier: #1383 / #1114 stay Now for a daytime interactive session (channel credentials,
  portrait approval). not-work — needs Matthew live.

## OWNER ACTIONS — the one numbered list (Matthew, morning of Tue 2026-08-04)

1. **Before Wed 08:10 PT (15:10 UTC): decide the first-send shape.** Options: (a) merge+deploy
   staged **PR #2120** (delivered-marker; safest, additive) and let Wednesday deliver the Aug-2
   prologue ONCE then Week 1 on approval; (b) also/instead flip `EXTERNAL_EMAILS_ENABLED=false`
   for one more week; (c) accept the double-send. Review the saved render (path above) + #2112.
2. **Branch protection one-liner (carried):** `python3 scripts/apply_branch_protection.py --apply
   && python3 scripts/apply_branch_protection.py --check` with a repo-admin token (#1662's closure
   comment has the runbook).
3. **Layer rebuild deploy (carried):** PR #2100's runbook (build → pip-audit → publish → env bumps
   → `cdk_deploy.sh LifePlatformOperational LifePlatformIngestion` → promote manifests) — closes
   #2099's boxes 2/4.
4. **Owner-approved data backfills (both dry-run-first, scripts merged tonight):**
   `python3 deploy/backfill_coach_ensemble_phase_stamps.py` (then `--apply`) for #1970's legacy
   rows; optionally the cycle-4 NARRATIVE#arc restoration (#1950's closure comment).
5. **Carried from 08-03:** 3 CodeQL dismissals (#2046's alerts 131–133), PR #2012's revision purge.
6. **#1905 decision (new to the list):** /legacy publicly serves four real clinicians as
   coach-voice attributions — leave-as-is / CloudFront-block / scrub. Filed as a Later story but
   the CALL is yours (real-people privacy); overnight session deliberately did not decide it.

Full narrative of the prior session: `git show
origin/session-archive:handovers/HANDOVER_2026-08-03_day1-max-paydown-stale-pr-flush.md`.
