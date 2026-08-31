# Handover — 2026-08-31 (FABLE 5): Session N — 11 closed, the fence under the belt, and the lease I stranded

**Session:** Claude Fable 5, owner co-working from mobile, Fable orchestrating Opus/Sonnet lanes
capped at 3–4 per wave (4 lanes total this session: two Sonnet, two Opus). Started 2026-08-31
06:37Z, worked to ~15:xxZ (a multi-hour idle gap mid-session — see Incidents). The day's through-line, named by the peer
and true four times over (the #2899 wrap line, the pillow waiver, my global cdk, their LaunchAgent):
**a stale local copy of a thing the repo thinks it owns, failing in the direction that looks like success.** Each instance
kept reporting success from a copy of a fact the repo had moved past, because nothing asked the authoritative
side — and each fix was the same move at a different layer: **make it derive rather than remember** (the peer's
formulation, worth keeping).

## The ask and the honest count

Owner: "same brief as the last two — close as many as possible without risking quality." Then, on
"what if I want more resolved": *do the recommendation for all five, if (1) it would be endorsed by
technical experts and (2) no material cost increase.* Applied literally: #2363 (BotFather) is the
owner's Telegram account, not doable by me; #2883 fails filter 1 today (n=2 post-fix cycles — no bar
re-derivation); #2578 option (a), #3340, and the evidence-based half of the Roadmap prune passed both.

**Closed 11** (open 37 → 27 at the last count, Roadmap 25 → 21):
#3354 (PR #3355) · #3353 (PRs #3356 + #3361) · #3352 (PR #3358, live-proved) · #3340 (PR #3360,
applied + probed live) · #1631 (PR #3357, the ADR-063 do-not-build amendment) · epics **#2578**
(Outcome amended per the owner's #3329 option B, then closed on it) and **#2799** (on its Outcome,
after #3352's live proof) · **#1080** (on its own closure rule — every child had shipped by 08-16) ·
#723 and #1414 (not-planned, executing the 2026-08-09 triage recommendations nobody had acted on) ·
#3363 (the auto-filed wedge alert, closed by hand with the honest disposition). #3362 was auto-filed
and auto-closed by the #3352 machinery itself (net 0). **Filed 1** (#3365 — the six standing `Pending owner cdk deploy` warnings' home, evidence-backed, → Now: the sanctioned refill lever). 9 PRs merged, every one on a
`wait_pr_green` verdict read in its own command; every closure carries `**Shipped:**` +
`**Outcome:**` with live evidence; closure sweep clean except the two benign Session-L hits.

## What shipped (merged AND deployed/verified by content)

- **#3352 / PR #3358** — the site auto-rollback scope check: `tests/visual_qa_verdict.py` classifies
  each failed page (`deploy-script` / `hashed-asset` / `api` / `site-shell`), the rollback job declines
  what a `site/**` revert cannot reach, files via #1447, alerts `SITE ROLLBACK DECLINED`; recovery job
  auto-closes. **Live proof:** dispatch 33372295160 (`qa_inject_failure=api`) → declined, 0
  `rollback_site.sh` invocations, `/version.json` unchanged, #3362 filed; recovery 33373714550 closed
  it. `/api/ai_analysis` `_meta.content_as_of` live. Census 587 → 588 (`ci::site-deploy.yml::visual-qa::6`, entered unproven, named).
- **#3340 / PR #3360** — the derived permissions boundary on the three CDK cfn-exec roles (16 Denies,
  5,612/6,144 chars, one registry with the additive-IAM gate). Driver-review narrowing before merge:
  `dynamodb:UpdateTimeToLive`/`UpdateContinuousBackups` dropped (the only CFN path for TTL/PITR).
  **Applied 14:24Z** as matthew-admin from the checked-in JSON; `verify_oidc_iam --strict` CLEAN (15);
  `cdk_deploy.sh LifePlatformCore` no changes; **probe (a)** denied by name (`explicit deny in a
  permissions boundary: …/cdk-cfn-exec-boundary`), **probe (b)** `CREATE_COMPLETE`. The first probe
  attempt was VACUOUS (an em dash in a role Description → IAM 400 before the boundary was evaluated;
  both controls failed identically) — fixed + charset-guarded in PR #3364.
- **#3353 / PRs #3356 + #3361** — WebKit tiled screenshots past the 32767px cap; first-ever green of
  the weekly WebKit lane (66/66, run 33371151988) — then the wire gap: the job never installed Pillow,
  so the tiling had printed `fallback unavailable`; pinned, the stale #3315 waiver deleted, re-run
  33402608192 green with 16 tiled captures executing.
- **#3354 / PR #3355** — `diff_shape()` union-with-optionality for heterogeneous arrays; 120 baselines
  recaptured; `--check-drift` 0/0; the #3324 mutation proof still ARMS.
- **#1631 / PR #3357** — ADR-063 amendment: off-AWS per-post spend is outside the metered ceiling; X
  syndication is a recorded do-not-build until a metering amendment exists.
- **PR #3359** — the CLAUDE.md `$200` line that redded every PR (Incident 2).
- **PR #3364** — README simulator count 28 → 35; `qa-smoke-failures` citation pruned per its dated note
  (OK since 08-28 14:05Z); the ASCII-only probe templates + guard test.
- **Roadmap prune (evidence-based half):** #1080 closed on its rule, #723/#1414 not-planned; the
  taste half (tick-list of 8 groups) is in the terminal for the owner; #1389 re-homed off the closed epic.

## Incidents (both rows in `docs/INCIDENT_LOG.md`)

1. **P3 — the lease I stranded (4.9h):** my lease loop EXITED after approving the tip `7edaa94cf`;
   #3360's run then sat at the gate from ~09:05Z until `deploy-wedge-watch` fired at 13:53Z and
   dispatched the remediation agent (`stranded-approval`, the "12 need you" email). Rejected with
   decode at 14:2xZ; a persistent steward (reject ancestors / approve the tip, `Monitor persistent`)
   replaced the loop. `watch_deploy_gate.sh` would have approved an ancestor — not the answer.
2. **P4 — docs-only red-in-waiting:** Session M's wrap block (`CLAUDE.md:213: $200`) tripped the
   as-of-2026-09-02 doc gate on every PR while main's badge stayed green (path-filter skip). Fixed by
   PR #3359 + `gh pr update-branch` ×4.

## Verification state
- Every lease disposed (tip `7edaa94cf` approved; `f0f5526`, `2a22aae`, `cfd7c4d`, `785ef27`,
  `dfed9ab`, `9507d01`, `c85dfd6` rejected by name); the steward holds the rest.
- Live: site `7edaa94` (site-deploy self-run + two dispatches green), fleet bundle from
  `7edaa94cf` (Deploy + I1/I2/I5 + smoke + visual QA green), boundary attached ×3,
  `verify_oidc_iam --strict` CLEAN, census 588.
- Governor: 08:00Z cycle mtd $180.03 / projected $182.05, tier 2 against the $200 window, drift
  **1.21x unchanged** (datum posted on #2883; no re-derivation on n=2).
- Worktrees 18 → 8 at boot (11 reaped); lanes released after each merge.

## Gotchas (durable → memory)
- **A lease steward must outlive the tip** (memory) — one persistent watch per session.
- **A docs-only commit can red every PR while main reads green** (memory) — run the doc-facts gate
  on the FINAL wrap tree.
- **A dark-flag waiver's reason rots when the reach grows** (memory) — grep the waivers for any dist
  a lane makes newly reachable; the sweep's "N stale waiver(s)" line is a finding.
- **A probe can be vacuous for a reason unrelated to what it probes** — read the CREATE_FAILED reason
  before calling a negative control a pass (guard test added).
- `gh --jq` still takes no `--arg` (killed one waiter); quoting inside `$( )` killed another —
  write waiters as files, not inline.
- **A bare `npx cdk diff` is not evidence** — my stale global toolchain rendered a phantom LogRetention
  runtime DOWNGRADE + dashboard Tags deltas; the chooser is aws-cdk-lib's regionalFact (Python, pinned in
  `cdk/.venv`), already decoded in ci-cd.yml's #2468 comment and in memory. Synth through `cdk_deploy.sh`, always.
- **`cdk deploy` stages the working TREE** — with a peer's uncommitted Lambda edit in the shared checkout,
  a "cosmetic drift" deploy would have silently shipped it (grant not yet deployed). Clean-tree is a deploy
  precondition, now recorded in #3365's acceptance.

## Residual / next picks
- **Owner asks, unanswered this session:** #1407 Roadmap→Now pick; #2363 BotFather (10 min); #1738
  pick-by-ear (renders gone; re-render ≈ $0.62 on request); the Roadmap taste tick-list (8 groups);
  #2883 re-derivation waits for the September clean-month read.
- **#3042** carries the #3340 residuals: `drift_sentinel.check_oidc_iam` runs the verifier without
  `--strict` (the weekly sweep cannot red on any OIDC/boundary finding); the remediation role cannot
  read the exec roles (`BOUNDARY-UNREADABLE`); the propagated-boundary non-goal.
- **`deploy-wedge-watch` has no recovery leg** (not #1447-wired) — a cleared wedge never auto-closes
  its issue; named on #3363, file if it recurs.
- **09-01 00:00Z:** the $215 base goes live; read the governor log. **09-03 wrap:** `qa-smoke-warnings`
  citation expiry. **09-08 16:00Z:** the Architect ritual runs itself. (not-work — standing calendar, each item owned by its own dated machinery)
- **CI warnings (7 on `236f8d2bc`) triaged:** six `Pending owner cdk deploy` → filed #3365 (Now; clean-window
  preconditions in its acceptance — no in-flight fleet deploy, clean tree, pinned-venv synth, Web's CloudFront
  change READ before shipping); the Unit-Tests duration breach (2290s/1950s) → **no action, measured** — 11
  same-day datapoints span 1198–2298s (92% spread on near-identical trees; the #3265 queue-noise pattern).
- Monday 14:45Z remediation cron: GitHub-starved through wrap (~15:4xZ; last schedule-event run 08-28) — the CallerClass=remediation datapoint check moves to next boot (not-work — the cron is GitHub's scheduler, the waiter pattern is in this handover, and the #2883 soak record carries the datum when it lands).

## Peer-session interlude (life-platform-a7, owner-directed)
- Mid-session, local main diverged: two unpushed commits by the peer session (the #1026 memory-backup
  repair, owner-directed, in the SHARED checkout). Coordinated by SendMessage — no touch, no reset;
  the peer ran its full suite (23,619 passed), rebased onto the moving tip, resolved the
  `platform_counts.py` collisions by regeneration, and pushed (`8e8d05708` + `cfb1a7e3c`).
- **The checkout is now load-bearing for a scheduled job:** LaunchAgent
  `com.matthewwalker.claude-memory-backup` runs `setup/claude_memory_backup.sh` FROM THIS REPO
  (the ~/.local/bin staged copy is deleted). Moving or removing the checkout breaks the daily
  memory backup; and because its two path-contract tests read ~/Library/LaunchAgents and SKIP in CI,
  **a green CI run is not evidence the backup path is intact** — after any checkout move, a local
  `pytest tests/test_backup_agent_path_contract.py` is the only thing that will catch the break
  (peer proved it live: 3 kickstarts, latest 15:12:30Z, 380 memory files, rc=0).
- The peer's SECOND slice — the memory-backup dead-man (`output_artifact_registry.py` + the freshness-checker
  wire-in + an s3:GetObject grant) — is committed as `c446c4173`, UNPUSHED at wrap: an ordering decision sits
  with the owner (deploy `LifePlatformOperational` first = zero window; push first = correct-but-noisy daily
  alerts until the stack deploys). #3365 carries the ordering box; the commit closes the '#3042
  LaunchAgent-visibility' residual named on #3340.
- The peer independently re-verified my boot reap (all five reaped lanes' content on origin via
  #3339/#3323/#3321/#3320/#3319; the one 7-line delta was a waiver main deliberately removed in #3361).

## Gate lines
**Build beat:** 2026-08-31-the-rollback-learned-its-reach
**Docs:** docs/DECISIONS.md (ADR-063 amendment via PR #3357; ADR-065 amendment via PR #3360), docs/PROPORTIONALITY.md (cfn-exec boundary row PR #3360; deploy-guardrails row amended PR #3358), infra/iam/README.md + docs/alarm_citations.json (PR #3364), docs/INCIDENT_LOG.md (+2 rows, this commit), docs/OPERATING_KNOWLEDGE_LEDGER.md (+3 rows, this commit)
**Decisions:** none needed beyond the dated ADR amendments already landed in merged PRs — ADR-063 (off-AWS spend, #3357) and ADR-065 (boundary = braces, #3360); the #2578 Outcome amendment is recorded on-issue per the owner's #3329 option-B ruling
**Main:** green (236f8d2b) — the tip run `cfb1a7e3c` (the peer's backup commits) was in flight at wrap with its Deploy lease steward-approved at 15:24Z; every earlier lease disposed by name
**Incidents:** 2 rows added — the 4.9h stranded lease (caught by deploy-wedge-watch → remediation dispatch, P3) and the docs-only wrap line that redded every PR while main read green (P4)
**Stash/hooks:** clean
**Closures:** #3354, #3353, #3352, #3340, #1631, #2578, #2799, #1080, #723, #1414, #3363 commented (Shipped + Outcome with live evidence on each; #3362 given its marker over the machinery's auto-close) · DoD: re-ran `scripts/closure_sweep.py --session` after commenting — scanned=28 hits=2, both pre-existing benign (#3317 = Session L's own verdict +18m; #3318 = lexical quote of the sweep's output), #2848 dispositioned in the registry
**Backlog:** Now 1 actionable corpus-wide (#3365, sonnet, filed this session — the evidence-backed refill lever); fable-lane 0 — `backlog_next.py --refill-now --lane fable` verdict: the ONLY sanctioned pick is #1407 (ADR-099 ¶3 product pick, the owner's call — asked this session in the numbered asks, unanswered), then NO REMEDY IN THE CORPUS (9 Roadmap stories held by the one-per-cycle cap; unblock levers named on the plan); floor untouched. Later sweep — no stale Later issues printed
**Alarms:** all cited — 3 red >72h carry standing citations (ai-tokens-platform-daily-total, compute-pipeline-stale, cost-metric-drift-sustained #2883); qa-smoke-warnings rides its self-clearing Withings-gap citation (expiry the 09-03 wrap); qa-smoke-failures citation PRUNED per its own dated note (OK since 08-28 14:05Z; PR #3364)
**CI warnings:** 7 on 236f8d2b — six `Pending owner cdk deploy` (Web/Serve/Monitoring/Ingestion/Email/Compute) → filed #3365 with clean-window preconditions (plus the Operational ordering box from the peer's slice); Unit-Tests duration 2290s/1950s → deliberate no-action, measured: 11 same-day datapoints span 1198–2298s (92% wall-clock spread on near-identical trees, the #3265 queue-noise pattern) — acknowledged via `check_ci_warnings.py --decoded`
**Ledger:** rows landed via merged PRs — the cfn-exec permissions-boundary row (PR #3360) and the deploy-guardrails row amended for the rollback scope-check + resolve job (PR #3358); no unledgered standing machinery from this session
