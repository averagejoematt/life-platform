# HANDOVER — Stolen-laptop resilience audit → 1 epic + 5 stories filed (#1024–#1029), zero code shipped by design — 2026-07-11

> Instruction: "if my laptop got stolen do we have everything we need for the platform
> between what is in AWS and what is in git? If not, what is a plan that we no longer rely
> on anything local" → (via /plan) → then "can you put these all into epics and stories in
> open issues rather than executing now" → "continue with putting the plan into the issues
> plan in git".

## What ran

A read-only disaster-recovery audit, then the plan filed as backlog — **nothing executed,
no tracked file touched.** One Explore agent swept the DR/continuity surface (docs/DR,
CONTINUITY, AWS_ACCESS, ACCOUNTS, .gitignore, launchd plists, datadrops, memory-export
path, font provenance); the driver verified the git in-flight state directly (worktrees,
stashes, dangling tips). Findings went to GitHub Issues per ADR-099 (I filed them directly
with `gh` after the issue-filer subagent hit a credit error mid-run; deduped against the
open backlog — no overlap).

## The verdict (audited)

**~90% recoverable from AWS + git today.** Code (git + deploy zips in S3), all health data
(DDB PITR — restore drill passed #755), infra (CDK), secrets (Secrets Manager), the
platform-memory DDB partition, and site + fonts (fonts ARE committed under
`site/assets/fonts/v4/`, not S3-only) all survive a laptop loss. `docs/CONTINUITY.md` +
`docs/DISASTER_RECOVERY.md` already map most of it.

**Six gaps found → the epic:**
1. Claude Code file-memory dir — laptop-only; S3 backup runs only as a manual /wrap habit.
2. In-flight git — **mostly self-resolved**: the formerly-dirty ~35-file reset staging tree
   got committed + pushed as `1fe300f0` (cycle-5 reset) between plan-time and file-time.
   Residual = 3 low-value stashes + one dangling local-only branch tip
   (`docs/uplevel-handover` cf3c5586, remote deleted).
3. `datadrops/` originals (genome, physicals xlsx 2019–2024, Apple Health exports) —
   presence under the delete-protected `uploads/` S3 prefix unverified.
4. launchd manual-drop ingest runtime — code in git, running runtime dies with the laptop;
   no from-zero rebuild runbook.
5. **Re-entry risk (sharpest, owner-only):** Identity Center not enabled → break-glass keys
   are the only human AWS path and live on the device; ACCOUNTS.md estate/MFA-recovery rows
   still blank. Laptop + phone lost together could lock out AWS root + GitHub + registrar.
6. Live device secrets — recoverable but a theft = compromise; no consolidated rotation
   scenario in the DR doc.

Total remediation cost ≈ **$0.10–0.15/mo** (S3 storage only; no Bedrock/Lambda/alarms).

## What shipped (backlog only — no code, no deploy)

- **Epic #1024** — Stolen-laptop resilience (`type:epic`, area:infra+security); body carries
  the verdict, six gaps, success criterion, cost line, story checklist. Links #722, #936.
- **#1025** — git: rescue 3 stashes + dangling `docs/uplevel-handover` tip · Now · sonnet
- **#1026** — backup: scheduled launchd job, memory dir + `datadrops/` → S3 daily · Now · sonnet
- **#1027** — docs: DISASTER_RECOVERY stolen-laptop scenario + RPO · Next · sonnet
- **#1028** — docs: NEW_MACHINE_BOOTSTRAP.md rebuild runbook · Next · sonnet
- **#1029** — ops: re-entry hardening owner-gated checklist (Matthew) · Now · security

Plan file (session-local, not committed): `~/.claude/plans/lazy-hatching-squirrel.md`.

## Gotchas

- **Concurrent session live in the shared tree.** At wrap time the working tree held ~30
  modified `site/method/*` + `scripts/v4_build_evidence.py` + `tokens.css` files and
  `settings.local.json` screenshot-perm churn — NONE mine (my session touched zero tracked
  files). Wrap staged **only** `handovers/` + `CLAUDE.md`; left all concurrent work
  untouched. Confirmed via `git diff` before staging.
- **issue-filer subagent died on "out of usage credits"** mid-run; recovered by switching
  the session to Opus 4.8 and filing the 6 issues directly with `gh`. No partial/duplicate
  issues created (checked before re-filing).
- Plan-time git status ≠ file-time git status: the reset commit `1fe300f0` landed in
  between, erasing what the plan had called the biggest in-flight gap. Re-check live state
  at execute-time, don't trust the plan snapshot.

**Build beat:** none — read-only audit + backlog filing; no code merged or deployed this session (#736 skip).

**Docs:** none needed — session filed GitHub issues only; no repo doc pages invalidated. (The doc *work* itself is queued as #1027/#1028, to be done when those stories are picked up.)

## Residual — waiting on Matthew / next session

- **Owner-only (#1029, time-sensitive):** enable Identity Center → deactivate break-glass
  keys; fill ACCOUNTS.md estate + MFA-recovery rows; confirm FileVault; verify NameCheap
  login works off-device (**domain renews 2026-08-20, ~6 wks**); decide repo-private.
- **Now-milestone, AI-doable:** #1025 (git hygiene — quick) and #1026 (the launchd backup
  job — the highest-leverage automation; makes memory + datadrops ≤24h-durable).
- #1027/#1028 are the Next-milestone doc pair; #1026 should land first (they cite its RPO).
