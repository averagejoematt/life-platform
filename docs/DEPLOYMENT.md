# Deployment Guide — SUPERSEDED POINTER

**Status:** superseded · **Verified:** 2026-07-10

> This page used to restate deploy procedure and drifted badly (it still taught the
> shared-layer dance a month after the layer was retired by #781/ADR-131, and a raw
> `aws s3 sync --delete` for the site). Per the CONVENTIONS meta-rule, procedure lives
> in ONE canonical home each — this page is now just the map.

## Where the real procedures live

| You want to… | Canonical home |
|---|---|
| **Pick the right deploy path for a change** ("I edited X, what do I run?") | [`QUICKSTART.md`](QUICKSTART.md) — the decision-tree table |
| **Understand the ONE-bundle model** (shared code, no layer — #781) | [`CONVENTIONS.md` §1](CONVENTIONS.md) |
| **Deploy from the right checkout** (main, not a worktree; squash-drift; `cdk diff` discipline) | [`CONVENTIONS.md` §2–§3, §6](CONVENTIONS.md) |
| **Per-script reference** (what each `deploy/*.sh` does, flags, the run-from-repo-root rule) | [`deploy/README.md`](../deploy/README.md) |
| **Deploy a single Lambda / fleet / MCP / site-api** | `deploy/deploy_lambda.sh` · `deploy/deploy_fleet.sh` · (MCP is just `deploy_lambda.sh life-platform-mcp` since #781) · `deploy/deploy_site_api.sh` — all documented in [`deploy/README.md`](../deploy/README.md) |
| **Deploy the static site** | Merge to main — `site-deploy.yml` deploys automatically (#750). Attended fallback: `bash deploy/sync_site_to_s3.sh`. Details: [`SITE_UPLEVEL_PLAYBOOK.md`](SITE_UPLEVEL_PLAYBOOK.md) |
| **CDK / infra changes** | `bash deploy/cdk_deploy.sh <StackName>` (the guarded path — [`CONVENTIONS.md` §6](CONVENTIONS.md)); site-api ownership split rules in `.claude/commands/deploy.md` (#793/#794) |
| **Roll back** (Lambda, site, CDK) | [`QUICKSTART.md`](QUICKSTART.md) rollback section + `deploy/rollback_lambda.sh` / `deploy/rollback_site.sh` |
| **CI/CD pipeline shape** (gates, approval, smoke, auto-rollback) | [`CONVENTIONS.md` §4](CONVENTIONS.md) + `.github/workflows/ci-cd.yml` |
| **Emergency / disaster scenarios** | [`RUNBOOK.md`](RUNBOOK.md) + [`DISASTER_RECOVERY.md`](DISASTER_RECOVERY.md) |

## The three rules that outlive any procedure

1. **One bundle** — shared code ships inside every function (`deploy/build_bundle.py`); a shared-module change is a fleet deploy, and CI does it automatically on merge (#781).
2. **Deploy from `main`**, never a worktree branch; `cdk diff` before every `cdk deploy`; an unexplained `[-]` means main is behind live.
3. **Never `aws s3 sync --delete` to the bucket root** — `deploy/lib/safe_sync.sh` or the CI path only (ADR-032/033/046).
