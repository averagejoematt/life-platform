# HANDOVER — Genesis-night close: #1023 + #1066 closed, #741's measurement leg live, inherited CI red root-caused — 2026-07-12 (early UTC)

> Instruction: "do as many as you can this session to close status if you see them adding
> good value, things like best practice (DRs etc.) can be skipped this time" — following
> "read handover and memory so we can start a session". Matthew answered the two gating
> decisions in-session (#741 publish: yes; #1023: option b).

## What ran

Genesis-night session (02:30–04:30 UTC, cycle-5 Day 1 begins this morning PT). Two
`worktree-implementer` agents in parallel (#1066, #741 mechanics); the driver did #1023
inline, the serial reconcile-merge queue, all deploys, and an unplanned ops/CI
investigation when the first merge surfaced a red ci-cd pipeline and a DLQ message.

## What shipped (4 PRs #1071–#1074, ALL merged + deployed + verified)

- **#1071** (#1023 CLOSED): **Matthew's call = option (b)** — /privacy/ softened from the
  absolute "no affiliate arrangements" to scoping any affiliate arrangements to the
  disclosed product links on /gear/; "Last updated" bumped to July 2026. Sweep confirmed
  /subscribe/ + chronicle-sample "no affiliate links" claims describe the *email* (still
  true, untouched); /legacy/ verbatim-preserved. Decision recorded on the issue; verified
  live.
- **#1073** (#1066 CLOSED): **the training-block lever** — new read-only `GET /api/routine`
  (newest prescription on/before today via `routine_index`, block name from
  `config/training_phases.json`; fail-closed field projection: counts only, no exercise
  names/loads/notes/Hevy ids — leak test asserts it) + third lever row in
  `cockpit.js renderLevers` linking /protocols/. 10 new tests, render gate 12/12 with
  /now/ now requiring 3 lever rows, 7 Playwright states verified. Deployed
  API-before-frontend; live `/api/routine` returns shaped pre-start data.
- **#1072** (#741 ADVANCED, stays open): **travel watch in the traffic digest** —
  per-page views + external referrer domains for the career essay URL (env-overridable
  `WATCHED_PAGES`), URI variants normalized, zero-view weeks explicit. 3 new tests.
  `life-platform-traffic-digest` deployed; first section appears in Monday's 16:00 UTC
  digest. **Key finding:** the essay was ALREADY live at
  `/journal/essays/org-chart-of-one/` since PR #899 (07-08) — story-hub tab, rss.xml,
  /method/build/ cross-link all shipped then; only measurement was missing.
- **#1074** (no issue): **inherited CI red root-caused + fixed** — PR #1049 (07-11
  char-math session) archived `deploy/void_legacy_predictions_726.py` to
  `deploy/archive/onetime/` but `tests/test_predictions_one_store_726.py` still
  sys.path-imported from `deploy/` → **every ci-cd run since had a red Unit Tests job
  (~26h, unnoticed)**. One-line path fix; post-merge ci-cd run GREEN.

**Ops (driver-attended):** tonight's 03:05 UTC Withings ingestion failed
("invalid refresh_token", status 503) and landed 1 message in `life-platform-ingestion-dlq`.
Diagnosed **transient Withings-side glitch** — identical signature to a 07-04 burst that
self-recovered; a manual invoke at ~03:40 UTC refreshed the token fine and gap-filled 8
dates (all `no_data`, consistent with no weigh-ins since 07-04). **Genesis weigh-in path
is safe; no re-auth needed.**

## Verification

Serial merge queue with doc-sync `--apply` per test-adding PR (`test_count`
3306→3309→3319; #1073 reconciled via merge-main + `--theirs` + re-sync +
`reset --soft` linearize for squash). Deploys: site auto-deploy ×2 GREEN (smoke +
visual-AI QA), `deploy_site_api.sh` (403-boot healthy), `deploy_lambda.sh` traffic-digest.
Live checks: /privacy/ new copy + July stamp, `/api/routine` shaped 200,
`/version.json` == main HEAD, essay 200. Final ci-cd run (post-#1074) GREEN. 0 open PRs,
worktrees/branches removed, stash stack untouched.

## Gotchas / new reflexes

- **Archiving a one-time script can break tests that import it** — #1049's archive move
  redded ci-cd for a full day. When moving anything under `deploy/`, grep `tests/` for
  its module name first.
- **ci-cd red does NOT block site deploys** (separate workflows) — the prior session
  wrapped "all green" while ci-cd was red on every run. Wrap reflex: check
  `gh run list --workflow=ci-cd.yml` conclusions, not just site-deploy/canary.
- **Withings "invalid refresh_token" (status 503) can be transient** — same burst
  signature 07-04 and 07-12, both self-recovered; manually invoke the lambda to test
  before assuming the token is dead and re-authing.
- **The permission classifier blocks SQS DLQ deletes even with verbal in-session
  approval** — needs a scoped settings rule or Matthew's `!`-prefix command.

## Next picks / residual

- **DLQ: 1 diagnosed message still in `life-platform-ingestion-dlq`** (delete was
  classifier-blocked; Matthew's `!` command not yet run) — **it will red the I9
  post-deploy check on the next full ci-cd run** until cleared. One paste fixes it; the
  remediation agent (07:45 PT) may also pick it up.
- **The career essay page carries a live draft artifact** — `[CONFIRM: self-reported
  figure …]` in the throughput paragraph. Matthew says the page was a casual one-time
  share, but it IS publicly listed (story-hub tab, RSS, /method/build/ cross-link) and is
  now the travel-watch URL. One-line honest-parenthetical fix is drafted and pending his
  word — resolve before any HN submission (#741).
- **#741 remains:** HN submission (Matthew) + travel in the Monday digests.
- **Post-genesis watch (today):** first character-sheet v1.6.0 run ~17:35 UTC,
  /api/board_ask p95 under the #1068 gate, levers/inputs stations on real Day-1 data;
  the training lever populates once the first cycle-5 routine draft is pushed
  (`manage_hevy_routine draft`).
- **Matthew queue (unchanged):** Sunday pipeline + prereg scripts, panelcast wk0
  spot-listen, `/bin/bash` FDA grant, locate the genome original, #1029.
- **Open backlog:** #1029 (owner-gated), #936 (attended DR drill), #916 + #1017 + #748
  (wait-conditioned), #741 (Matthew leg), Later epics #1000/#1001 + standing epics.

**Build beat:** 2026-07-12-training-lever (see `site/story/build/beats.json`).

**Docs:** `docs/API.md` gained the `/api/routine` entry (+ an honest drift note: its
endpoint list was last fully verified 2026-05-19 and lacks newer endpoints like
`/api/presence` — a re-verify pass is doc-debt for a docs session). Everything else is
inside existing documented surfaces; doc-sync literals reconciled per PR, machinery
green at wrap.
