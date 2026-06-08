# Contributing

This is a **solo-maintained, proprietary** project (see [`LICENSE`](LICENSE)). External contributions aren't accepted — but this file documents how change actually lands, for any reviewer or future maintainer.

## How changes land
- **One change → one branch → one PR.** `main` is branch-protected: PRs required, no direct pushes, no force-push/deletions, delete-on-merge enabled.
- **Conventional commits** (`feat` / `fix` / `refactor` / `chore` / `docs` / `style` / `test`); AI-authored changes carry a `Co-Authored-By` trailer.
- **Decisions become ADRs** in [`docs/DECISIONS.md`](docs/DECISIONS.md) (ADR-001…).
- **CI gates** (`.github/workflows/ci-cd.yml`): black + ruff (enforced) → tests → plan → deploy (production-approval) → smoke → auto-rollback.
- **Deploy only via the playbook** — see [`.claude/commands/deploy.md`](.claude/commands/deploy.md) (the site-api multi-module + layer-rebuild caveats matter).

## Start here
| To understand… | Read |
|---|---|
| The project | [`README.md`](README.md) |
| The agent + human workflow | [`CLAUDE.md`](CLAUDE.md) · [`.claude/README.md`](.claude/README.md) |
| First-day mental model | [`docs/ONBOARDING.md`](docs/ONBOARDING.md) |
| Everything in docs/ | [`docs/README.md`](docs/README.md) |
| Security posture | [`docs/SECURITY.md`](docs/SECURITY.md) |
| Testing | [`docs/TESTING.md`](docs/TESTING.md) |

## Local checks before a PR
```bash
make check        # flake8 + syntax + tests
make format       # ruff (lint+import-sort) + black
python3 -m pytest tests/ -q
```
