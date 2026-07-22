# HANDOVER — Engineering-excellence craft grade: /craft-review skill + standards + epic — 2026-07-21

> Instruction thread: "Pretend I gave my repo to a hiring panel (Eng I → CIO) — plan to get it
> graded an A, then keep it there; 2026→2028 lens, core engineering + AI; group the issues under
> a CI/CD/DevOps grouping AND make it a repeatable skill (Fable-runnable). Uplevel the prompt."
> → plan approved → "yes do it, mind the parallel session" → "yes" (wrap).

## What this session was
A **planning + skill-build** session, not a shipping session. Produced a graded remediation +
forward-standards program and built the repeatable grader. **Nothing merged or deployed** —
the deliverable is an OPEN PR + a filed backlog.

## What shipped (all OPEN / filed — not merged, not deployed)
- **PR #1647** (branch `eng-excellence-craft-review`, OPEN) — two new files + one index line:
  - `.claude/commands/craft-review.md` — the **3rd grading ritual**. `/fullreview`=product,
    `/sdlc-review`=process, **`/craft-review`=codebase-as-craft-artifact** (would a panel from
    Eng I→CIO grade the git an A on cleanliness/structure/naming/aesthetics/gates/standards).
    Model-agnostic → **Fable runs it unchanged**; Workflow fan-out (seniority-ladder lenses,
    10 craft dimensions) → finding-verifier → `docs/reviews/craft_grades_<date>.json` (trend)
    → issue-filer under the epic; schedulable.
  - `docs/ENGINEERING_STANDARDS.md` — the durable **"definition of an A"**: the 10-dimension
    rubric the skill grades against AND the standard new code meets (one source). ~800-line
    module ceiling, real-mypy/no-blanket-waiver rules, CI-as-composition, 2026→2028 AI-era
    standards, and the CI ratchet-guards. (Carries the required `> **Status:**` header.)
  - `docs/README.md` — index line for the new standards doc.
- **Backlog** — `[EPIC] Engineering excellence: repo craft, cleanliness & standards` = **#1648**
  (`area:infra`), **18 stories #1649–#1666**, label `review:eng-excellence-2026-07-21`,
  milestones Now/Next/Later. `gate:owner` on **#1662** (branch protection) + **#1666**
  (proportionality ADR).

## The audit that drove it (grounded, 3 parallel reviewers)
Repo grades **B+/A−**. Excellent bones (OIDC least-privilege roles, prod-approval + auto-rollback,
the `reconcile` drift auto-fixer, grounded-generation gates, fail-open cost governor, honest ADRs,
clean commits). Gap to A is **craft, not correctness**: hygiene (`archive/` 315 dead files +
**111 git-ignored on-disk-only** incl. a real-code downloads backup; `handovers/` 477 transcripts),
structure (104-file flat `lambdas/` root, 2–3k-line god-modules, 1,490-line `ci-cd.yml`),
config-trust (mypy disables ~14 codes, blanket `mcp/` waivers, 40% coverage), team/supply-chain
(no branch protection, no secret-scan/CodeQL, non-blocking CVE gate, example-only tests).

## Decisions locked (encoded in the stories — don't relitigate)
- Config gates = **big-bang to full standard** (mypy strict/empty disable list #1656, zero
  blanket waivers #1657, coverage **70%** #1658).
- Branch protection = **Option C** (fast-lane required checks + auto-merge + scoping ADR, #1662).
- Proportionality = **cut nothing; make the keep/retire ledger legible** (#1666); CI→composition (#1655).
- Hygiene = **zip-to-local + tag `pre-hygiene-<date>` + git rm** — loss risk resolved live (full
  history 2,168 commits; handovers/patches/backfill 100% tracked). The ONE risk = the 111 ignored
  `archive/` files → the zip step in #1649 captures them **before any `git rm`**.

## Verified
- PR #1647 CI: **wiki-drift ✅** (fixed a missing `> **Status:**` header on the new doc — the only
  red, cleared by `43ffef51`), deploy-critical+format ✅ (passed), validate=skipping. Pre-commit
  doc-sync was a clean no-op both pushes.
- All 19 issues verified via `gh issue view` — labels/milestones/`gate:owner` correct; sanity grep
  found no story missing type/area/model.
- Worked entirely in an **isolated worktree** (`eng-excellence-craft-review`) — shared `main` tree
  never touched (only the harness's `settings.local.json`).

## Gotchas
- **zsh `read -ra` is bash-only** — the first 4 `gh issue create` calls silently dropped all but
  the review label (loop split failed). Fixed by `gh issue edit --add-label` and switching to a
  single comma-separated `--label` (gh splits it). Verify labels after batch-filing on zsh.
- **New docs need a `> **Status:** canonical · **Owner:** … · **Verified:** …` header** or
  `check_doc_index.py --strict` (the "Wiki drift gates" job) reds the PR.
- The 3 engine-doc drift warnings from a full-history local run of `check_doc_index.py --strict`
  are **pre-existing on main** (config committed 2026-07-21 vs doc verified dates) and don't fire
  on CI's shallow checkout — not this PR's concern.
- Agent self-reports on their own numbers are ~50% wrong — the hygiene agent's initial premises
  (`.DS_Store`/`.coverage` tracked) were FALSE; grep before trusting.

## Residual / next picks
- Merge PR #1647 to make `/craft-review` usable. `not-work — owner merge decision on PR #1647`.
- Drain the eng-excellence backlog via `/uplevel` — starts with the Now tranche (#1649/#1651/#1652
  hygiene, #1657 waivers, #1659 gitleaks, #1660 CodeQL). See **#1648**.
- Confirm **#1650** handovers disposition before executing (touches the wrap workflow /
  `HANDOVER_LATEST.md` dependency) — see **#1650** (`gate:owner`-adjacent).
- Schedule the periodic `/craft-review` run. `not-work — scheduling decision, do after #1647 merges`.
- **Standing (carried from prior session): cycle-10 reset to 2026-07-22 (Wed)** —
  `restart_pipeline.py --apply` (runs `cdk deploy --all` = OWNER); no 07-22 weigh-in yet, fallback
  `--override-weight-lbs 321.38`; plan in scratchpad `NEXT_SESSION_PLAN.md`.
  `not-work — owner-run experiment reset`.

**Build beat:** none — this session's work landed as OPEN PR #1647 + a filed backlog; nothing merged/deployed (merged-work-only gate #736).
**Docs:** none needed on main — the session's docs (`ENGINEERING_STANDARDS.md`, `craft-review.md`, README index) live on unmerged PR #1647; no `main` wiki page was invalidated.
**Decisions:** none needed — no governance decision landed on main this session; the proportionality ADR is filed as story #1666 (`gate:owner`), authored when that story is drained.
**Main:** red — latest completed non-cancelled CI/CD run is `953566a2`, failed/parked at the manual production Deploy gate (pre-cdk-deploy, per prior session's decode); newer main commits' runs auto-cancelled as superseded — no test breakage, a human-approval park.
**Incidents:** none
**Stash/hooks:** clean
