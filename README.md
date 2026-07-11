# Life Platform

[![CI](https://github.com/averagejoematt/life-platform/actions/workflows/ci-cd.yml/badge.svg)](https://github.com/averagejoematt/life-platform/actions/workflows/ci-cd.yml)
![AWS](https://img.shields.io/badge/cloud-AWS_serverless-232F3E?logo=amazonaws)
![Python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)
![IaC](https://img.shields.io/badge/IaC-AWS_CDK-FF9900)
![License](https://img.shields.io/badge/license-proprietary-lightgrey)

A personal **health-intelligence platform** — it ingests data from ~20 wearables/apps/labs, stores it in a single-table data model, runs a deterministic computation pipeline plus an 8-agent AI coaching layer, and publishes the results (privately and at **[averagejoematt.com](https://averagejoematt.com)**) — all on a hard **$85/month enforced budget** (floats to $100 in reader-traffic surge mode — ADR-133).

> **N=1, in public, kept honest.** Everything is correlative (never causal), confidence-labelled, and the down weeks are shown, not hidden.

---

## At a glance

| | |
|---|---|
| **~94 Lambdas** | Ingest → Store → Serve, all serverless (us-west-2 + us-east-1 edge) |
| **64 MCP tools** | Claude reads the data back via a Model Context Protocol server |
| **Single-table DynamoDB** | `USER#…#SOURCE#…` / `DATE#…`, on-demand, 2 sanctioned GSIs (ADR-097; PITR + KMS) |
| **AWS Bedrock** | Claude Sonnet 4.6 (narrative) + Haiku 4.5 (structured), prompt-cached |
| **9 CDK stacks** | 100% infrastructure-as-code; OIDC CI/CD with a production-approval gate + auto-rollback |
| **$85/mo, enforced** | A cost-governor degrades AI by budget tier; an independent AWS Budget backstops it |
| **v4 site** | Three doors — Cockpit (`/now/`), Story (`/story/`), Evidence (`/evidence/`) |

## Architecture (one line)

**Ingest** (scheduled EventBridge Lambdas + HAE webhooks) → **Store** (raw JSON in S3, normalized metrics in DynamoDB) → **Serve** (compute Lambdas, daily-brief emails, the MCP server, and a read-only Site API behind CloudFront).

## Start here

**The engineering wiki lives at [`docs/README.md`](docs/README.md)** — role-based entry
paths, the full page registry, and the drift-prevention contract that keeps it accurate.

| You want to… | Read |
|---|---|
| Build the mental model | [`docs/ONBOARDING.md`](docs/ONBOARDING.md) |
| Find your way around the repo | [`docs/REPO_STRUCTURE.md`](docs/REPO_STRUCTURE.md) |
| Run first-day commands | [`docs/QUICKSTART.md`](docs/QUICKSTART.md) |
| Understand the system | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) |
| Operate / troubleshoot | [`docs/RUNBOOK.md`](docs/RUNBOOK.md) |
| Know *why* (ADRs) | [`docs/DECISIONS.md`](docs/DECISIONS.md) · [`docs/TAG_CODES.md`](docs/TAG_CODES.md) |
| The data model | [`docs/SCHEMA.md`](docs/SCHEMA.md) |
| See what shipped | [`docs/CHANGELOG.md`](docs/CHANGELOG.md) |
| How the AI agent builds this | [`CLAUDE.md`](CLAUDE.md) |

## Tech stack

Python 3.12 (stdlib-only HTTP — no `requests`/`httpx`) · AWS Lambda · DynamoDB · S3 · CloudFront · EventBridge · Secrets Manager · SES · **Bedrock** · **AWS CDK** (TypeScript app, Python stacks) · GitHub Actions (OIDC, no long-lived keys) · pytest + Playwright + AI-vision QA.

## Conventions (the short version)

- **IaC only** — change AWS via `cdk/`, never the console (see [`CLAUDE.md`](CLAUDE.md)).
- **Secrets** live in AWS Secrets Manager under `life-platform/`; never in the repo.
- **Decimal**, not float, for DynamoDB. **Single table**, no GSIs without an ADR.
- Every non-trivial decision is an **ADR** in `docs/DECISIONS.md`; internal tag-codes are decoded in [`docs/TAG_CODES.md`](docs/TAG_CODES.md).

## License

**Proprietary — © 2026 Matthew. All rights reserved.** See [`LICENSE`](LICENSE). Solo-maintained; not open for external contribution.
