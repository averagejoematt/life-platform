# Contributing

This is a **solo-maintained, proprietary** project (see [`LICENSE`](LICENSE)). External contributions aren't accepted — but this file is the working first-contribution path: everything a second maintainer (or future-me) needs to land a change the way the conventions expect, so the discipline survives without the one author remembering it.

## First-time setup

```bash
git clone <repo> && cd life-platform
pip install -r requirements-dev.txt   # black, ruff, flake8, pytest
bash scripts/install_hooks.sh         # installs pre-commit + commit-msg hooks (below)
```

`.git/hooks/` is local and untracked — **rerun `scripts/install_hooks.sh` after cloning and whenever it changes** (a stale hook drifts silently; `python3 deploy/session_postflight.py` reports hook freshness).

The hooks it installs:
- **pre-commit** — runs `black --check` + `ruff` on staged Python (matches CI's Lint job so an unformatted file can't red `main`) and auto-syncs the doc-metadata literals via `deploy/sync_doc_metadata.py`.
- **commit-msg** — rejects a subject that isn't a [Conventional Commit](#commit-messages), so the convention is mechanical, not cultural.

## Land a change (one change → one branch → one PR)

1. **Branch** off up-to-date `main` (it's branch-protected: PRs required, no direct pushes, no force-push/deletions, delete-on-merge enabled).
2. **Make the change.** One logical change per PR. Owners are routed per area in [`.github/CODEOWNERS`](.github/CODEOWNERS) and requested as reviewers automatically.
3. **Run the local checks** (below) — same gates as CI, so failures surface before the push.
4. **Commit** with a Conventional-Commits subject (the commit-msg hook enforces it). AI-authored changes carry a `Co-Authored-By` trailer.
5. **Open the PR.** The body is prefilled from [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md); include `Fixes #<issue>` and the post-merge deploy/ops steps.
6. **Merge ≠ deploy.** Lambda/infra code deploys from `main` via the playbook after merge; `site/**` auto-deploys on merge. See the PR template's deploy-notes section and [`.claude/commands/deploy.md`](.claude/commands/deploy.md).

## Commit messages

Conventional Commits: `<type>(<optional-scope>): <subject>`. The type set the commit-msg hook enforces:

`feat` · `fix` · `chore` · `docs` · `refactor` · `test` · `ci` · `build` · `perf` · `style` · `revert`

Examples: `feat(coaching): add streak card` · `fix: correct sleep-duration rounding` · `docs(readme): fix a broken link`. Merge/revert/`fixup!`/`squash!` subjects are exempt; bypass in a genuine emergency with `git commit --no-verify`.

## Local checks before a PR

```bash
make check        # flake8 + syntax + tests
make format       # ruff (lint+import-sort) + black  (never run black on .json)
python3 -m pytest tests/ -q
```

Run the **targeted** test for what you touched during iteration; run the full suite before opening the PR.

## Where things are decided

- **Backlog** — GitHub Issues (ADR-099): epics (`type:epic`) + ranked stories (`type:story`) on Now/Next/Later milestones. A shipping PR carries `Fixes #N`.
- **Decisions become ADRs** in [`docs/DECISIONS.md`](docs/DECISIONS.md) (ADR-001…).
- **CI gates** (`.github/workflows/ci-cd.yml`): black + ruff (enforced) → tests → plan → deploy (production-approval) → smoke → auto-rollback.

## Start here

| To understand… | Read |
|---|---|
| The project | [`README.md`](README.md) |
| The agent + human workflow | [`CLAUDE.md`](CLAUDE.md) · [`.claude/README.md`](.claude/README.md) |
| First-day mental model | [`docs/ONBOARDING.md`](docs/ONBOARDING.md) |
| Everything in docs/ | [`docs/README.md`](docs/README.md) |
| The load-bearing deploy/CI reflexes | [`docs/CONVENTIONS.md`](docs/CONVENTIONS.md) |
| Security posture | [`docs/SECURITY.md`](docs/SECURITY.md) |
| Testing | [`docs/TESTING.md`](docs/TESTING.md) |
