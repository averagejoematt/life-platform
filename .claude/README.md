# How this platform is built with Claude

This repository is built and operated with **Claude Code** as the primary engineer, working against a deliberately **AI-legible** knowledge base. This file documents that human + AI workflow — the part a reviewer asking *"how do you actually use AI here?"* wants to see. Nothing below is aspirational; every piece is in the repo.

## The layers

**1. The agent brief — [`/CLAUDE.md`](../CLAUDE.md)**
The single source of project instructions loaded into every session: architecture, hard conventions (stdlib-only HTTP, Decimal-for-DynamoDB, single-table/no-GSI, Secrets-Manager-only, S3 safety), deploy discipline, and the cost/AI guardrails. It's kept current; its counts are auto-synced (below).

**2. The knowledge base — [`/docs/`](../docs/)**
Designed so an agent can answer "why" without guessing:
- **ADRs** — every non-trivial decision is recorded in [`docs/DECISIONS.md`](../docs/DECISIONS.md) (ADR-001…155). Reversible, dated, with context + consequences.
- **Reference** — `ARCHITECTURE.md`, `SCHEMA.md` (authoritative data model), `RUNBOOK.md`, `INFRASTRUCTURE.md`, `MONITORING.md`, `SECURITY.md`, `COST_TRACKER.md`.
- **[`docs/TAG_CODES.md`](../docs/TAG_CODES.md)** — decodes the internal tag alphabet (ADR/PG/SIMP/IC/SEC/…) so commits and comments are traceable to the decision that motivated them.
- **`handovers/`** — the live end-of-session hand-off (`HANDOVER_LATEST.md`) so the next session resumes with full context. Prior sessions live on the **`session-archive`** branch (#1650) — `git show origin/session-archive:handovers/<name>.md`.

**3. Skills — [`.claude/skills/`](skills/)**
**28 skills** the agent invokes by name, each `‹name›/SKILL.md` with YAML frontmatter
(`description`, `argument-hint`, `allowed-tools`) so a session can pick the right one
without being told. The count is derived from the registry, never hand-listed — this
paragraph itself used to name two of them. A sample rather than an inventory:
- [`deploy`](skills/deploy/SKILL.md) — the deploy procedure (per-Lambda function-name map, the site-api multi-module caveat, one-bundle rules).
- [`qa`](skills/qa/SKILL.md) — QA modes (smoke / API freshness / visual / AI-vision).
- [`wrap`](skills/wrap/SKILL.md) — the session close: an 18-gate battery whose expectations are derived from the skill file itself.
- [`fullreview`](skills/fullreview/SKILL.md) — the 17-lens expert panel that grades every area A–F.

`python3 scripts/skill_registry.py` lists the live set; nothing here is hand-maintained.

**3b. Subagent library — [`.claude/agents/`](agents/)**
**4 subagent definitions** for the standing multi-agent fan-out pattern, each declaring its own least-privilege `tools:` list:
[`worktree-implementer`](agents/worktree-implementer.md) (one issue → one worktree → one
open PR, with the worktree-discipline incident classes baked in),
[`finding-verifier`](agents/finding-verifier.md) (adversarial second pass on review
findings — historical first-pass false-positive rate ~50%), and
[`render-qa`](agents/render-qa.md) (Playwright render QA with the route-mock /
service-worker gotchas encoded), and [`issue-filer`](agents/issue-filer.md) (files verified
findings against the ADR-099 contract — exact score-line grammar, class-not-symptom filing). Each prompt carries the recurring lessons so sessions
stop re-improvising briefs from memory prose (#796).

**4. Automation the agent relies on**
- **Session hooks** (`.claude/settings.json` → `scripts/hooks/`) — enforcement at
  *tool-use* time, which the git hooks below cannot reach because they run at commit time.
  A `SessionStart` pre-flight prints main's real state, any waiting deploy lease and
  worktree hygiene (three things sessions otherwise guess); a `PreToolUse` guard flags a
  merge with no named-check assertion, a deploy from a worktree, and a force-push to main;
  a `PostToolUse` check records each push and, once runs have had time to appear, reports
  a sha that minted **zero** — the swallowed-push class. All **advisory** by default:
  they warn and exit 0 until an operator sets `CLAUDE_HOOK_MODE=block`. Every one fails
  open on a bad payload, because a hook that can crash can halt a session.
- **Doc-sync pre-commit hook** (`scripts/install_hooks.sh` → `deploy/sync_doc_metadata.py`) — auto-updates doc headers (tool/Lambda/secret/alarm counts, version) on every commit, so docs can't silently drift from code.
- **Self-healing remediation agent** (`.github/workflows/remediation-agent.yml`, ADR-064/065) — Claude on a schedule via GitHub Actions + Bedrock: triages alarms/CI/DLQ, auto-fixes the provably-safe class behind a deterministic merge gate, opens PRs for the rest. Read-only AWS role; the gate (not the model) holds merge authority.
- **MCP server** (`mcp/`, `mcp_bridge.py`, `.mcp.json`) — 76 tools that let Claude query the live platform data directly during a session.

**5. Verification — Claude checks its own work**
- `tests/visual_qa.py` — a Playwright browser sweep after deploys.
- `tests/visual_ai_qa.py` (ADR-076) — a Claude/Bedrock **vision** pass that reads each screenshot for regressions a pixel-diff would miss or false-alarm on.

## Working norms (how changes land)

- **One change → one branch → one PR.** `main` is branch-protected (PR required, no direct pushes). Conventional-commit subjects; **no tool-attribution trailers** (owner decision 2026-08-12 — commits carry the work, not the tooling).
- **Decisions become ADRs.** Architectural or irreversible choices get an ADR before/with the code.
- **Cost is a first-class constraint.** Everything runs under an *enforced* monthly budget (ADR-063/133) with a tiered guard that degrades AI features rather than overspending; features justify their spend.
- **Honesty over optimism.** Failing tests are reported with output; skipped steps are stated; "done" means verified.

## Onboarding a fresh agent (or human)

1. Read [`/CLAUDE.md`](../CLAUDE.md), then [`docs/ONBOARDING.md`](../docs/ONBOARDING.md).
2. Skim `handovers/HANDOVER_LATEST.md` for in-flight state (earlier sessions: the `session-archive` branch).
3. Use `docs/TAG_CODES.md` + `docs/DECISIONS.md` to decode any tag or "why".
4. `make check` (lint + syntax + tests) before proposing changes; deploy only via the [`deploy`](commands/deploy.md) playbook.

> The thesis: a well-structured, decision-logged, self-verifying codebase lets an AI engineer move fast *without* losing rigor. The docs aren't overhead — they're the interface.
