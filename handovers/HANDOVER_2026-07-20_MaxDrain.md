# HANDOVER — Max autonomous drain: 21 issues closed through a mid-session TCC outage — 2026-07-20 (afternoon/evening)

> Instruction thread: "ultracode +2M — MAXIMUM AUTONOMOUS DRAIN (~88 → as low as honesty
> allows), four tiers pre-verified to need zero input, gate:owner fenced, public-repo
> discipline in every brief, all merges/deploys/pushes authorized (IAM stays user-NAMED),
> three-kinds-of-close, triage table first, full suite no -x per merge." Mid-session
> Matthew re-confirmed the blanket merge/deploy/push authorization.

## Outcome — the board went 98 → 83; the platform grew a pre-merge lane, two signed
## posture ADRs, a transport-aware canary, and two new chat modes; and half the session
## ran from a /private/tmp clone because macOS revoked ~/Documents mid-flight

**Closed (19 stories + 2 epics):** #1451 #1590 #1472 #1474 #1442 #1439 #1586 #1448 #1430
#1346 #1337 #1324 #1349 #1353 #1578 #1566 #1575 #1576 #1338 #1344 + epics #1460 #342
(all-children-closed + DoD legs verified). **#1589 reopened deliberately** — see below.
17 PRs merged (#1591–#1609 minus the fenced ones), every one on a verified full suite
(no -x), the four doc-sync-literal-conflicted ones through the full reconcile ritual
(rebase → main's literal files → regen → collect-only → full suite → merge).

**The headline fixes:**
- **#1589 canary blind:** root cause = the synthetic direct-invoke events carried NO
  headers, so site-api-ai's R22-SEC-03 origin gate (correctly) 403'd all 5 probes. Fix
  is canary-side (reads the origin secret via secret_cache, presents x-amj-origin);
  gate untouched. NEW transport self-test: an all-None/401/403 run classifies **BLIND**
  — its own `Blind` gauge + `ai-canary-blind` digest alarm + "NOT an AI-quality verdict"
  in the digest head. **Proven live**: post-deploy invoke returned status=BLIND exactly
  as designed (the IAM grant isn't applied yet, which IS the blind condition). Code +
  Monitoring alarm deployed; the Operational-stack IAM grant is Matthew's (user-NAMED
  IAM rule — the auto-mode classifier held it, correctly). After his
  `cdk deploy LifePlatformOperational`: one canary invoke → expect OK/Blind=0 → close.
- **#1447's filer was broken on every fire:** the advisory-failure-issue composite
  action had `${{ job.status }}` / `${{ secrets.GITHUB_TOKEN }}` in its input
  DESCRIPTION strings — GitHub template-validates those even in prose, so the action
  failed to load exactly when needed (first real fire: the 21:17 UTC standalone
  visual-QA red). Fixed via the contents API mid-outage (e4a666b1); proven by a green
  dispatched rerun.
- **ADR-138 + ADR-139 (PR #1603):** the SDLC posture pair signed — prod-only release
  topology with its six compensating controls, and the testing topology with a NEW
  advisory pre-merge lane (`.github/workflows/pr-checks.yml`: collect-only +
  deploy_critical subset + black --check, ~1 min) whose required-ness is explicitly an
  owner toggle in github_posture.json (the #1319 lesson: durable controls live in git).
- **I4 hotfix (5ec629ff):** #1594's merged review-pack lambda had no handler
  try/except (its agent's six-red suite summary under-itemized this one) — caught in
  my reconcile suite, fixed forward on main same hour.

**Deploys executed (all from the clone, CodeSha256/behavior-verified):**
ai-quality-canary (code), LifePlatformMonitoring (the new alarm), qa-smoke (#1593's
weekly redirect spot-check), MCP (#1606's checkpoint triggers; boot-verified 401), site
×2 via auto site-deploy with green gates (live == 51ff229 content at verification time).

## THE INCIDENT — macOS TCC revoked ~/Documents mid-session
At ~12:45 PT every file read under ~/Documents went EPERM for the whole process tree
(Bash, Read/Edit — everything; directory listings still worked). Root-cause class is the
known TCC trap, new escalation: it hit a LIVE interactive session. **The workaround
that saved the session: `gh repo clone` into /private/tmp** — git, pytest, black, aws,
cdk, gh all work there (~/.aws, ~/.config/gh, ~/.claude are not TCC-protected). All
merges, reconciles, deploys, and this wrap ran from clones. **Owner fix (30s): System
Settings → Privacy & Security → Files & Folders (or Full Disk Access) → re-enable
Documents for the terminal/Claude app, or restart the app.** Memory updated.

## Gotchas hit (durable, all in memory)
- **Agent-concurrency contamination, two new vectors:** (1) an agent's Bash cwd
  silently reverted to the shared main checkout (case-twin path) and its `git stash -u`
  briefly captured MY uncommitted work (restored, confessed in its report); (2) three
  agents raced the shared scratchpad `repo/` clone — branch switched underfoot, edits
  clobbered; all recovered via fresh uniquely-named clones. RULE for every future
  brief: unique clone dir per agent (`repo-<issue>`), stash ban stated verbatim.
- **The composite-action description-string trap:** GitHub template-validates `${{ }}`
  inside input descriptions — never put expression syntax in action prose.
- **gh pr merge races mergeability recompute** after main moves: poll
  `mergeStateStatus` until non-UNKNOWN; a merge attempt during recompute 405s.
- The pre-commit doc-sync hook rewriting literals MID-full-suite-run produces phantom
  platform-stats reds — commit, then run the suite.

## Live state at wrap
- Cycle 9 Day 1; site healthy on latest content; brief went out 17:00 UTC (carried the
  315 override — tomorrow's carries 321.38; known, by design).
- **Main:** latest CI/CD conclusions: Unit/lint/deploy-critical green; the ONLY red is
  `Plan deployments` — the R8-ST6 IAM-review gate red BY DESIGN over the un-applied
  canary IAM grant; clears with Matthew's Operational deploy. CI Deploy stages are
  WAITING on the restored production approval gate (the gate working, not a failure).
- **Harness** (restart_integration_check --expect-cycle 9, run this session): 20 pass /
  4 fail, all four known (canary-blind pair → IAM deploy; qa-paused-by-budget = tier-1
  visibility by design; token alarms from the day's heavy Bedrock load; dark sources).
- felt_probe still n=0. Dark sources unchanged: hevy 6/25, notion 5/25, strava 7/14
  (gate:owner #1330).
- Board: **83 open** (98 at session start; #1589 deliberately reopened).

## Residual / next picks
- **Owner queue (the decision menu, also in the session close):** TCC re-grant;
  `cdk deploy LifePlatformOperational` (canary IAM → green canary → close #1589, also
  clears the Plan red); `cdk deploy LifePlatformEmail` (#1594's role+cron, before
  Sunday 18:00 UTC); approve the newest waiting CI Deploy run (fleet-syncs bundles);
  optional pr-checks required-ness toggle (ADR-139, not-work — owner call).
- **#1474 CLS skeletons: MERGED at wrap (PR #1609)** — data/method/protocols CLS
  0.46–0.67 → ~0.00 measured, per-page cls_budget locked in qa_manifest; its site
  auto-deploy was in flight at wrap (gates + auto-rollback own it). Next in lane: #1475.
- Tier-3 remainder, deliberately not rushed at session tail: #1481 (self-calibration),
  #1483 (semi-private references — its allude-tier PRODUCER lines already ship in
  /team-meeting + /interview), #1577 (conversational enrichment).
- Tomorrow (Tue): after the 16:30 UTC compute, `python3 deploy/restart_verify.py` →
  expect 12/12 (the Day-1 character sheet lands then; not-work — standing op).
- Dependabot black/garminconnect PRs: not yet filed by Dependabot at wrap; the black
  one is format-gate-coupled — bump CI pin + requirements-dev + full-tree reformat in
  ONE PR, solo (not-work — waits for Dependabot).
- #1329 rotation, #1350 sign-off, SNS confirm click: standing (gate:owner).
- ai-canary-heartbeat alarm: self-heals after Wednesday 16:20 UTC's run (not-work).

**Build beat:** `2026-07-20-canary-blind-self-test` (merged + deployed + proven live).
**Docs:** each merged PR carried its own (TESTING.md scorecard, CONVENTIONS §9 gate
registry, DECISIONS ADR-138/139 + ADR-057/129 addenda + ADR-099 template-retirement
note, CHAT_MODES two new modes, SECRETS_MAP consumer line, engine docs re-verified);
wrap adds INCIDENT_LOG rows only. **Decisions:** ADR-138 + ADR-139 filed (PR #1603).
**Incidents:** 2 rows added (TCC outage P3; agent-concurrency contamination P4).
**Main:** red — sole failing job is the by-design R8-ST6 Plan gate over the staged
canary IAM grant (clears on Matthew's Operational deploy); all test/lint/deploy-critical
jobs green on the latest completed run. **Stash/hooks:** clone stash empty; the main
checkout's stash/hook state UNVERIFIABLE this session (TCC) — next session re-checks
after the re-grant.

Prior session (same day): `HANDOVER_2026-07-20_Day3-cycle9-reset.md`.
