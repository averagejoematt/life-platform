# Handover — 2026-08-22 ~20:50 → 2026-08-23 ~02:45 PT: fable week, session 2 — the council plan, executed; the oracle blocked its own publish path three times and each block became structure

**Session:** Fable 5, autonomous (boot prompt: *"Execute the approved council plan at
`~/.claude/plans/stateful-squishing-dongarra.md`, end-to-end, with merge+deploy authority
for its scope"*). Previous wrap archived as `HANDOVER_2026-08-22_fable-week-lane-a.md` on
`session-archive`.

## The scoreboard

**Closed 5 / filed 3** (net −2): closed #2832 (flagship), #2692 (folded), #3025, #2921,
#3030; filed #3021 (lease janitor, file-not-fix per plan), #3025, #3030. **8 PRs merged +
deployed** (#3022 #3023 #3024 #3026 #3028 #3029 #3031, + probe #3027 closed-unmerged by
design). 3 deploy-gate leases approved, 2 rejected-as-superseded with recorded reasons.
Every closure carries its ADR-099 verdict comment. Main GREEN (18dfa1e4c) verified by
`check_main_green.py` at wrap.

## Shipped, by plan step

- **Step 0/1 (boot + verification):** wrap commit had already landed; fixed its Docs CI
  red (stale INCIDENT_LOG Patterns — the #2975 lane-gap class, regenerated + pushed).
  Alarm board reconciled clean: all 4 ALARM-state alarms live-cited (#2989, #2883, #2977,
  genesis window), 3 flaps = the known #2976 recovery episodes. #2889 + #2972 tails are
  time-gated to the 08-23 daily runs — still owned by the next boot (see residuals).
- **Step 2 flagship — #2832 Platform Operating Calendar (PR #3024):** registry
  (`scripts/operating_calendar.py`, 7 rituals with artifact-dated probes + 3 dated
  exemptions closing the review-skill set both directions) + daily dead-man workflow
  (`operating-calendar.yml`, first live run green: 32619558490) + generated
  `docs/OPERATING_CALENDAR.md` (#2986 DERIVED row, docs-ci lane). #1451/#1338 obligations
  re-homed onto the sdlc entry; REVIEW_METHODOLOGY's competing cadence retired; PT
  adoption anchor prevents born-red. Two premerge guards (PUSH_TRIGGER_GLOBS mirror, §9
  pointer-length) caught the first push — fixed in-PR.
- **Step 3 — #3025 pre-merge full suite (PR #3026), #2692 folded:** measured first from
  CI's own `--durations` (green run 32613992699): ONE unmocked-network test cost 180.85s
  (13% of the 1394s suite; 0.99s locally). Landed: `full-suite` job in pr-checks (exact
  post-merge selection, no coverage, unpiped; **13:44 for 20,560 tests** post-fix),
  parity/dep/unpiped contract tests, the 181s test made hermetic, a per-test 90s
  `::warning` warner (e11-triaged), budget 1200→1500s in its three synced literals with
  the measurement as rationale, PROPORTIONALITY row + two §9 rows. **Mutation-proved on
  the wire** (probe PR #3027: old lane green with a failing deselected test aboard; new
  lane red on exactly it) — and the lane caught **two real deselected-test breaks the
  same night**: its own maiden run (the doc-literal treadmill lives INSIDE the suite →
  in-workspace `sync --apply` step, never committed) and #3031's stub break. Required-ness
  promotion (github_posture/ADR-148) deliberately deferred past the ≥2-merge observation
  window — which is now satisfied (merges #3023, #3029, #3031 all landed green with the
  lane active); the promotion itself is next-session work (#3025 closure comment notes it).
- **Step 5 (promoted mid-session) — #2959 down-payment (PRs #3028, #3029):** the oracle
  blocked the site publish path 3× in ~90 min (runs 32616299944, 32618360726,
  32620189500). Root cause found in the rubric's own text — its final DO-NOT-FLAG bullet
  *instructed* "Flag a window only when it is LONGER than the days elapsed", which
  manufactured the 7-day-HRV-average-on-Day-6 highs. Fixed generation (cross-phase
  trailing-window clause) + enforcement (two deterministic suppressors in the #2780/#3003
  family: `is_day_counter_bound_inference` → demote, `is_self_refuted` → drop; phrase set
  widened after the third block's surviving high ended "within phase bounds and
  internally consistent"). 6 baselines recorded via the sanctioned writer + triaged
  (#2959). **Site deploy #4 green; suppressors observed firing 9× then 5× on later
  sweeps; the wrap's build dispatch finally published.** #2959 stays open — the
  per-page API ground-truth feed is the remaining rubric work.
- **Step 4 fan-out (sonnet worktrees):** **#2921 realized (PR #3023)** — `/api/sleep_detail`
  per-device namespacing (additive `eightsleep`/`whoop` blocks), verified live post-deploy
  (self-consistent per device, explicit `night_of`/`as_of_date`); evidence_sleep.js stage
  bar fixed. **#2883 stays open honestly (PR #3022, "Part of")** — drift re-measured
  WORSE (1.4177 vs the 1.15 bar), residual $20.64 unattributed with out-of-repo
  candidates (remediation agent + concurrent Claude worktree sessions' own Bedrock
  calls); the shipped fix (state-of-matthew's write-only 1h cache, 24,159 write/0 read
  tokens over 30d) is correct and ~$0.006/mo. **#3021 filed** (lease janitor, Next).
- **Unplanned class, found + fixed live — #3030 one-clock (PR #3031):** the QA harness
  computed phase truth at assess time; a sweep straddling midnight PT judged Day-6
  screenshots (PT-correct chrome per #2941) against a Day-7 phase — 2 red QA jobs on
  green deploys (runs 32622594057, 32623497239's QA). Fixed: `pacific_today()` pinned
  once at sweep start, threaded through `assess_prose(today_iso=…)`, spy-test proved,
  stored in report.json. The new full-suite lane caught this PR's own deselected stub
  break pre-merge.

## The night's honest pattern

Five sweeps produced five DISTINCT novel oracle highs (build-log chrome, 7-day average
×2 pages, a self-refuting note, a second self-refuting phrasing, an editorial
cross-cycle-label nit graded high) — each on a page that had passed the previous sweep.
That non-stationarity is #2959's remaining case, now with tonight's runs as the measured
series; the suppressors + 6 baselines ended the bleeding, the rubric ground-truth feed is
the cure. Also: I burned one empty-commit nudge diagnosing zero-run pushes before
checking `mergeable` — the exact first move the existing memory prescribes (CONFLICTING
PR after #3024's conftest twin-add; resolved by merging main, runs minted in a minute).

## Gate lines

**Build beat:** 2026-08-23-the-suite-that-catches-what-the-fast-lane-cannot
**Docs:** OPERATING_CALENDAR.md (new, generated) + README index + REVIEW_METHODOLOGY
cadence retirement + PROPORTIONALITY (2 rows + Re-read log) + CONVENTIONS §9 (3 rows) +
frontier-plan artifact path — all inside the feature PRs; SCHEMA.md sleep SoT ruling in
#3023; wiki checkers green at commit.
**Decisions:** none needed — no new ADR; #2832 executes ADR-099/103/144 machinery,
required-ness change deferred (will need the ADR-148 posture edit when taken).
**Main:** green (18dfa1e4c) — `check_main_green.py` exit 0; the intervening QA-job reds
(32626430842, 32623497239) were the #3030 clock race + the fifth oracle novel high, both
structurally answered same-session.
**Incidents:** 2 rows added — (1) the 3× oracle-blocked site publish path
04:07–06:36Z (2 auto-rollbacks, no reader impact, recovered by #3028/#3029+baselines);
(2) the #3030 midnight-clock QA reds on green deploys (no rollback, no reader impact).
**Closures:** #2832, #2692, #3025, #2921, #3030 commented (4 realized, 1 fold-realized);
#2883 + #1629 got dated status comments without closure.
**Backlog:** hygiene OK over 77 open; Now refilled per (e9) by stored rank — promoted
#2989, #3005, #2813 (score lines updated to `→ Now` with dated notes; the liveness rule
counts type:story only, which took three promotions to satisfy); no stale Later issues
printed. The cycle's one Roadmap promotion allowance DECLINED on measurement (#1629 gate
reads 0/30 vs ≥15/30 — owner decision point ~09-01 per its own close-unbuilt banner).
**Alarms:** 4 red, all cited (#2989, #2883 — deliberately red, #2977, genesis window
self-clearing 08-24); 2 flaps flagged and decoded: `ingest-liveness-unhealthy`
(08-21 10:11 → 08-22 10:11 PT — the previous wrap's already-named #2976-cluster
organic clear, still inside this wrap's 72h window) and `site-api-invocation-spike`
(08-22 23:43→23:45 PT, 2-min dwell — self-inflicted by this session's own five
full-surface QA sweeps in ~3h during the publish-path recovery; no reader-facing
symptom, load source known). Gate closed with `--decoded`.
**CI warnings:** 2 — both `cdk deploy` config-change advisories (Operational + Email)
on the wrap-tip green run: the already-filed #2993 class (the Plan classifier calls an
asset-hash-only `Code.S3Key` diff a config change; tonight's fleet deploys moved every
bundle hash). Owned by #2993 (Next, 2.00 — top of its milestone's rank); no local cdk
deploy warranted on a hash-only diff. Gate closed with `--decoded`.
**Stash/hooks:** clean.
**Ledger:** 2 rows added — operating calendar + pre-merge full suite (posture, rent,
demote triggers in `docs/PROPORTIONALITY.md`).

## Residuals / next picks

- **#2889** first live `GenerationSkippedUnchanged` reading at the 08-23 17:00 UTC brief —
  not-work — scheduled observation, issue open.
- **#2972 tail**: `public_summary` first rows after the 08-23 coach daily run; then 2
  clean oracle runs → delete the `/method/board/` baseline entry — not-work — dated
  observation owned by the next boot (tracked in #3018's body).
- **#3025 follow-through**: promote `Full unit suite (pre-merge, #3025)` to a REQUIRED
  check via `deploy/github_posture.json` + `apply_branch_protection.py` (ADR-148 path) —
  the ≥2-merge green window is satisfied; noted in #3025's closure comment.
- **#2883**: measure the out-of-repo candidates (Cost Explorer usage-type granularity vs
  the callers' windows) — the issue's own next step, recorded in its status comment.
- **#2959**: the rubric ground-truth feed (per-page API cycle metadata) — the plan's
  stated success metric: zero NEW over-read highs on baselined pages next session.
- **#1629**: owner decision ~09-01 — 0/30 usage at the gate reads as close-unbuilt per
  the issue's banner — not-work — gate:owner decision, measurement recorded on the issue.
- One-off flake observed once, not filed: `test_singleton_tombstone_guards` order-
  dependence candidate (probe run only; passed on identical base 20 min earlier) —
  not-work — single observation recorded in #3025's evidence comment; file on recurrence.
