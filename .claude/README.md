# How this platform is built with Claude

This repository is built and operated with **Claude Code** as the primary engineer, working against a deliberately **AI-legible** knowledge base. This file documents that human + AI workflow — the part a reviewer asking *"how do you actually use AI here?"* wants to see. Nothing below is aspirational; every piece is in the repo.

## The layers

**1. The agent brief — [`/CLAUDE.md`](../CLAUDE.md)**
The single source of project instructions loaded into every session: architecture, hard conventions (stdlib-only HTTP, Decimal-for-DynamoDB, single-table/no-GSI, Secrets-Manager-only, S3 safety), deploy discipline, and the cost/AI guardrails. It's kept current; its counts are auto-synced (below).

**2. The knowledge base — [`/docs/`](../docs/)**
Designed so an agent can answer "why" without guessing:
- **ADRs** — every non-trivial decision is recorded in [`docs/DECISIONS.md`](../docs/DECISIONS.md) (ADR-001…135). Reversible, dated, with context + consequences.
- **Reference** — `ARCHITECTURE.md`, `SCHEMA.md` (authoritative data model), `RUNBOOK.md`, `INFRASTRUCTURE.md`, `MONITORING.md`, `SECURITY.md`, `COST_TRACKER.md`.
- **[`docs/TAG_CODES.md`](../docs/TAG_CODES.md)** — decodes the internal tag alphabet (ADR/PG/SIMP/IC/SEC/…) so commits and comments are traceable to the decision that motivated them.
- **`handovers/`** — end-of-session state hand-offs so the next session resumes with full context.

**3. Slash commands — [`.claude/commands/`](commands/)**
Repeatable playbooks the agent invokes by name:
- [`deploy.md`](commands/deploy.md) — the deploy procedure (per-Lambda function-name map, the site-api multi-module caveat, layer-rebuild rules).
- [`qa.md`](commands/qa.md) — QA modes (smoke / API freshness / visual / AI-vision).

**3b. Subagent library — [`.claude/agents/`](agents/)**
Reusable subagent definitions for the standing multi-agent fan-out pattern:
[`worktree-implementer`](agents/worktree-implementer.md) (one issue → one worktree → one
open PR, with the worktree-discipline incident classes baked in),
[`finding-verifier`](agents/finding-verifier.md) (adversarial second pass on review
findings — historical first-pass false-positive rate ~50%), and
[`render-qa`](agents/render-qa.md) (Playwright render QA with the route-mock /
service-worker gotchas encoded). Each prompt carries the recurring lessons so sessions
stop re-improvising briefs from memory prose (#796).

**4. Automation the agent relies on**
- **Doc-sync pre-commit hook** (`scripts/install_hooks.sh` → `deploy/sync_doc_metadata.py`) — auto-updates doc headers (tool/Lambda/secret/alarm counts, version) on every commit, so docs can't silently drift from code.
- **Self-healing remediation agent** (`.github/workflows/remediation-agent.yml`, ADR-064/065) — Claude on a schedule via GitHub Actions + Bedrock: triages alarms/CI/DLQ, auto-fixes the provably-safe class behind a deterministic merge gate, opens PRs for the rest. Read-only AWS role; the gate (not the model) holds merge authority.
- **MCP server** (`mcp/`, `mcp_bridge.py`, `.mcp.json`) — 64 tools that let Claude query the live platform data directly during a session.

**5. Verification — Claude checks its own work**
- `tests/visual_qa.py` — a Playwright browser sweep after deploys.
- `tests/visual_ai_qa.py` (ADR-076) — a Claude/Bedrock **vision** pass that reads each screenshot for regressions a pixel-diff would miss or false-alarm on.

## Working norms (how changes land)

- **One change → one branch → one PR.** `main` is branch-protected (PR required, no direct pushes). Conventional-commit subjects; `Co-Authored-By` trailers credit the model.
- **Decisions become ADRs.** Architectural or irreversible choices get an ADR before/with the code.
- **Cost is a first-class constraint.** Everything runs under a $75/mo *enforced* budget (ADR-063); features justify their spend.
- **Honesty over optimism.** Failing tests are reported with output; skipped steps are stated; "done" means verified.

## Onboarding a fresh agent (or human)

1. Read [`/CLAUDE.md`](../CLAUDE.md), then [`docs/ONBOARDING.md`](../docs/ONBOARDING.md).
2. Skim the latest `handovers/HANDOVER_LATEST.md` for in-flight state.
3. Use `docs/TAG_CODES.md` + `docs/DECISIONS.md` to decode any tag or "why".
4. `make check` (lint + syntax + tests) before proposing changes; deploy only via the [`deploy`](commands/deploy.md) playbook.

> The thesis: a well-structured, decision-logged, self-verifying codebase lets an AI engineer move fast *without* losing rigor. The docs aren't overhead — they're the interface.
