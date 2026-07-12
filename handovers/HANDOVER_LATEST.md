# HANDOVER — Epic close-out: 6 issues cleared by live-evidence verification, drift sentinel unblocked, SSO provisioned, the podcast gate held 15/15 — 2026-07-12 (late evening)

> Instruction: "get the most issues cleared efficiently from open issues, start with
> highest complexity ones … i also approve all merges and deploys."

## What ran

The open backlog was 21 issues: 7 stories (mostly Matthew- or data-gated) + 13 epics +
the parked register. The leverage was epics whose child stories were ALL closed: six of
them (#348, #342, #1001, #719, #717, #722). Pattern: **6 parallel verification agents,
one per epic, each checking the epic's own DoD against LIVE evidence** (site endpoints,
workflow run history, AWS state, IAM policies) — closure only on evidence, never on
child-state alone. In parallel: a worktree-implementer took #1017 (the one actionable
deferred story), and two prep agents ran the machine halves of Matthew-gated #1123
(podcast regen) and #1114 (portrait art direction v2 options).

## Shipped (all merged + deployed + live-verified)

- **PR #1166** — drift-sentinel IAM starvation fix. The #342 verifier found the sentinel
  had NEVER run clean: its only Monday run (07-06) was DEGRADED (AccessDenied on 4 checks
  + the `drift-log/` persist — the prefix was empty, ever), because PR #438's DriftSentinel
  statements were never applied live AND #401's canonical `infra/iam/*.permissions.json`
  **codified the broken live state**, so `verify_oidc_iam.py` reported CLEAN while the
  sentinel starved. Fix landed in BOTH sources of truth; live role updated via
  `put-role-policy`; parity CLEAN (9/9); IAM simulation verified (reads allowed,
  `drift-log/*` write allowed, `raw/*` write still denied). Also fixed the ledger's stale
  assertions row + DESIGN_SYSTEM §10.7 `/now/`→`/cockpit/`.
- **PR #1167** — #1017 constellation labels: svg text now derives from live render scale
  with an 11px effective floor + ≥44px tap targets; measured 8.86→11.0px @390px,
  8.15→11.0px @360px. site-deploy run 29209436766 green (smoke + visual-QA); live at
  build `80c1763` with `sizeConstellation` confirmed in the served bundle.
- **PRs #1168 + #1169** — two prompt iterations teaching the wk0 intro writer the #1122
  gate rules (130-word cap via `_QA_MAX_WORDS_PER_TURN`, no-dangling-threads mirroring
  `_CHALLENGE_RE`, Eli-owns-the-risk, strict speaker alternation, substantive answers,
  other-speaker-voiced topic shifts). `coach-panel-podcast` lambda deployed after each.

## Issues closed (6) + keep-opens with recorded close paths (2)

- **Closed with live-evidence comments:** epics #348 (honest-empty verified per ADR-104 on
  Day-1 data), #719 (ADR-125/126/132/133 all verified in deployed code), #722 (every
  perimeter item decided or closed; #916 dispositioned decided-deferred), #1001 (wk0.mp3
  3.3MB, skeletons live, SW island decision recorded + build-hash VERSION), #1000 (closed
  after #1017 went live), story #1017 (auto via PR #1167).
- **#342 keep-open:** closes on Monday 07-13 ~14:45 UTC when the now-unblocked sentinel
  writes its first clean `drift-log/` record. Close-path comment on the issue.
- **#717 keep-open:** criterion honesty — green-streak is 1 current / 7 best vs 30
  required (remaining red class = cross-PR generated-artifact drift on merge-queue days,
  NOT the old lint mask), and the reconciliation leg (drift sentinel) had zero executions.
  Path to close on the issue: verify Monday's sentinel run + either accumulate the streak
  or explicitly amend the criterion.

## #1029 / stolen-laptop progress (Matthew active in-session)

- IAM Identity Center **enabled by Matthew** (instance ACTIVE 07-12 11:52 PT); I
  provisioned user `awsdev` (awsdev@mattsusername.com), permission set
  **AdministratorAccess** (PT8H sessions — Matthew explicitly named the grant after the
  permission classifier twice refused agent-chosen elevation), account assignment done;
  Matthew completed the password reset. FileVault verified ON. Memory-backup S3 leg
  verified fresh (same-day).
- **Parked for a separate discussion at Matthew's request — do not re-raise unprompted:**
  FDA grant for `/bin/bash` (ingest watcher still exit 126; `datadrops-archive/` still
  empty), ACCOUNTS.md estate rows (both ⚠️ rows), repo-private call, genome original
  (datadrops/genome/ still empty).

## #1123 podcast — machine half CONCLUDED, fork recorded on the issue

**0/15 generations clean across 4 runs; the fail-closed #1122 gate held every time. No
candidate exists; live wk0 untouched (byte-verified); zero audio synthesized (~$1.50
Bedrock total).** Prompt iterations verifiably killed the word-cap and friction/Eli-owns-
risk failure modes, but the model wrote consecutive same-speaker turns even when the
prompt strictly forbade them — **prompt instructions cannot guarantee structural output
properties** (diagnostics confirmed the holes were model-written, not gate-deleted).
Decision fork recorded on #1123: (a) deterministic same-speaker-merge repair pre-gate
(wrinkle: naive merge busts the 130 cap → merge-then-split means the gate authors a
bridging line); (b) restructure to turn-by-turn alternating generation (defect
unrepresentable at source); (c) hold as-is. Staging playbook (candidate keys
`generated/panelcast/wk0-candidate.*`, listenable at `/panelcast/wk0-candidate.mp3`, +
one-command swap block) is in the #1123 comment. **Matthew decides the route.**

## #1114 portraits — options delivered, awaiting Matthew's ADR-106 pick

3 rendered v2 directions delivered in-chat (A "Medallion" ring-evolution, B "Cameo plate"
frameless tinted arch — recommended, C "Horizon line" editorial; B+C hybrid viable), each
on the same 3 coaches at 96/56/40px both themes, after 3 solo review rounds. Sketch
renderer + option sheet archived at
`s3://matthew-life-platform/design-sketches/portrait-v2-2026-07-12/` (scratchpad is
session-ephemeral). Root causes documented: no signed recipe has a `frame` layer (all get
`seededFrame()`'s dial-like ticked circle that never intersects the figure); fixed ~1.7
screen-px `non-scaling-stroke` reads ~2× heavy at 96px.

## Gotchas hit (durable ones → memory topics)

- **A parity check can codify a broken live state**: #401 snapshotted the live role
  without the never-applied #438 statements — repo==live said CLEAN while the capability
  was dead. Verify the *capability* (simulate/exercise), not just source parity.
- Permission classifier requires the USER to literally name an IAM grant level
  ("assign the admin access permission set") — "appropriate for what we need" from the
  user, or a doc-derived choice by the agent, both get refused.
- `deploy/deploy_lambda.sh` needs `<function> <source-file>` (two args).
- SSO users created via CLI get no invite email — console → Reset password → send email.
- Verification-sweep pattern paid off: 4 of 6 epics closed, 2 honestly refused — the
  refusals (with concrete close paths) are what make the closures trustworthy.

## Next picks

1. **Monday 07-13 ~14:45 UTC:** check the drift sentinel's first unblocked run → close
   #342 (and it satisfies #717's reconciliation leg; #717 still needs the streak call).
2. **Matthew queue:** #1123 route decision (a/b/c above) + eventual attended listen;
   #1114 portrait pick (then a shipping story); parked #1029 items (separate discussion);
   #741 career artifact; supplement hypotheses (#1148) + coach trait scores review still
   outstanding from the prior session.
3. Structural-fix candidate if #1123 route (a)/(b) chosen: implement + one staging run
   (~$0.25/attempt; SKIP_TIER=2 band allows at tier ≤1).
4. Budget watch: tier 1, projected $82 vs $85 ceiling — month-end headroom is thin;
   internal AI stays paused by the governor.

**Build beat:** 2026-07-12-the-gate-that-said-no
**Docs:** docs/AWS_ACCESS.md (Identity Center now LIVE — §1 table + §2 callout updated); MANAGED_WHERE_LEDGER.md + DESIGN_SYSTEM_V5.md §10.7 shipped inside PR #1166; no other pages invalidated (site fix + prompt changes live within already-documented systems)
