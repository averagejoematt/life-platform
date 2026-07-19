# The Life Platform Engineering Wiki

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-10
> **Sources of truth:** this directory's files; counts auto-synced by `deploy/sync_doc_metadata.py`

This is the home page of the platform's documentation. Everything lives **in this repo**
(docs-as-code): every page is PR-reviewed, CI-gated against drift, and versioned with the
code it describes. If you're reading this on GitHub, you're reading the wiki.

The standard the wiki holds itself to: **if all AI assistants were powered down tomorrow, a
competent human engineer could operate and extend this platform from these pages alone.**

Canonical pages stay **flat in `docs/`** (many are referenced by path from
`deploy/sync_doc_metadata.py`, the restart pipeline, and `CLAUDE.md`) — this index, not a
folder hierarchy, is how you navigate. Every page carries a status header
(`canonical` / `generated` / `log` / `superseded`); anything dated or shipped lives in
`archive/` or `specs/`.

---

## Start here, by role

**"I'm a new engineer, day one"** — read in this order:
1. [ONBOARDING.md](ONBOARDING.md) — the mental model (what this system is, in one page)
2. [REPO_STRUCTURE.md](REPO_STRUCTURE.md) — the repo map + "where does X go" rules
3. [AWS_ACCESS.md](AWS_ACCESS.md) — get AWS access (SSO — the one true auth procedure)
4. [QUICKSTART.md](QUICKSTART.md) — fresh laptop → first deploy (already have the toolchain + AWS access)
5. [NEW_MACHINE_BOOTSTRAP.md](NEW_MACHINE_BOOTSTRAP.md) — the layer below QUICKSTART: bare metal → operational (rebuild a lost/replacement Mac from zero)
6. [ARCHITECTURE.md](ARCHITECTURE.md) — the full system design
7. [CONVENTIONS.md](CONVENTIONS.md) — the load-bearing reflexes (read before your first deploy)

**"I'm operating the system today"** (on-call view):
[RUNBOOK.md](RUNBOOK.md) — daily ops + troubleshooting · [MONITORING.md](MONITORING.md) — what fires and why · [SLOs.md](SLOs.md) · [OPERATOR_GUIDE.md](OPERATOR_GUIDE.md) — the daily health check · [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md) — backups + drilled restore procedures

**"I'm taking this platform over from the AI"** (successor view):
[CONTINUITY.md](CONTINUITY.md) — the map of every state surface outside `docs/` (session handovers, platform memory, skills), the memory-export tooling, and the day-1 reading order · [NEW_MACHINE_BOOTSTRAP.md](NEW_MACHINE_BOOTSTRAP.md) — the from-zero rebuild runbook if the laptop is gone.

**"I'm changing the public website"**:
[PLATFORM_NORTH_STAR.md](PLATFORM_NORTH_STAR.md) — the durable why · [SITE_MAP_AND_INTENT.md](SITE_MAP_AND_INTENT.md) — what each page is for · [DESIGN_SYSTEM_V5.md](DESIGN_SYSTEM_V5.md) — the standards · [SITE_UPLEVEL_PLAYBOOK.md](SITE_UPLEVEL_PLAYBOOK.md) — how to change it well · [SITE_AUTHORING.md](SITE_AUTHORING.md) — add/change a page end-to-end

---

## Reference (look things up)

| Doc | What it answers |
|---|---|
| [SCHEMA.md](SCHEMA.md) | **Authoritative** DynamoDB reference — key-family catalog + per-source fields |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Full system design (the 9 stacks, ingest→store→serve; counts auto-synced) |
| [INFRASTRUCTURE.md](INFRASTRUCTURE.md) | The AWS account by the numbers |
| [DEPENDENCY_GRAPH.md](DEPENDENCY_GRAPH.md) | What calls what; single points of failure |
| [MCP_TOOL_CATALOG.md](MCP_TOOL_CATALOG.md) | All 67 MCP tools by domain (generated — never hand-edit) |
| [MCP_TOOL_AUDIT.md](MCP_TOOL_AUDIT.md) | The tool-removal ledger (#395 prune ratchet) |
| [API.md](API.md) | Site-API endpoints |
| [engines/](engines/) | The algorithm pages: [SCORING](engines/SCORING.md) · [CHARACTER](engines/CHARACTER.md) · [READINESS](engines/READINESS.md) · [HYPOTHESIS](engines/HYPOTHESIS.md) · [COACH_STANCE](engines/COACH_STANCE.md) |
| [ACCOUNTS.md](ACCOUNTS.md) | Every external account a successor needs, and how to recover each |
| [SECRETS_MAP.md](SECRETS_MAP.md) · [SECRETS_ROTATION.md](SECRETS_ROTATION.md) | Credential inventory · rotation procedures |
| [TAG_CODES.md](TAG_CODES.md) | Decode the internal tag alphabet (PG/SIMP/IC/SEC/…) |
| [BOARDS.md](BOARDS.md) | The AI persona boards |
| [REPO_STRUCTURE.md](REPO_STRUCTURE.md) | Top-level layout + "where does X go" |

## How-to (get things done)

| Doc | |
|---|---|
| [NEW_MACHINE_BOOTSTRAP.md](NEW_MACHINE_BOOTSTRAP.md) | Bare metal → operational: rebuild a lost/replacement Mac from zero (the layer below QUICKSTART) |
| [QUICKSTART.md](QUICKSTART.md) | Cold start + "I edited X, what do I run?" decision tree |
| [AWS_ACCESS.md](AWS_ACCESS.md) | Get/verify AWS access (SSO primary, break-glass keys, CI's OIDC roles) |
| [RUNBOOK.md](RUNBOOK.md) | Operate + troubleshoot everything |
| [RUNBOOK_REENTRY.md](RUNBOOK_REENTRY.md) | OAuth re-auth / data-source re-entry |
| [SITE_AUTHORING.md](SITE_AUTHORING.md) | Add/change a public-site page end-to-end |
| [ADD_A_COACH.md](ADD_A_COACH.md) | The paved path for extending the coach roster (persona registry → engine ids → portrait/quality gates → deploy) |
| [TESTING.md](TESTING.md) | Test layers, run commands, golden harnesses, visual QA |
| [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md) | Restore procedures (PITR + S3 — exercised 2026-07-10) |
| [REVIEW_METHODOLOGY.md](REVIEW_METHODOLOGY.md) · [SITE_REVIEW_METHODOLOGY.md](SITE_REVIEW_METHODOLOGY.md) | Run an architecture / site audit |

## Explanation (understand why)

| Doc | |
|---|---|
| [PLATFORM_NORTH_STAR.md](PLATFORM_NORTH_STAR.md) | The durable why — purpose, thesis, audiences, success bar |
| [DECISIONS.md](DECISIONS.md) | **ADRs (001–135)** — every significant decision with rationale; index auto-generated |
| [CONVENTIONS.md](CONVENTIONS.md) | **The load-bearing reflexes** (one-bundle rule #781, deploy-from-main, squash-drift, CI gate ordering, asset-staging trap) + drift-discovery commands |
| [CONTINUITY.md](CONTINUITY.md) | What lives outside `docs/` and how a human reads/exports it |
| [PHASE_TAXONOMY.md](PHASE_TAXONOMY.md) | What resets vs. persists at experiment restart (ADR-077) |
| [DATA_GOVERNANCE.md](DATA_GOVERNANCE.md) | PII classification + retention |
| [SECURITY.md](SECURITY.md) | Threat model, defense layers, accepted risks |
| [REMEDIATION_TAXONOMY.md](REMEDIATION_TAXONOMY.md) | The self-healing agent's classifier rubric |
| [MANAGED_WHERE_LEDGER.md](MANAGED_WHERE_LEDGER.md) | Out-of-IaC resources — what's managed where |
| [SITE_MAP_AND_INTENT.md](SITE_MAP_AND_INTENT.md) · [DESIGN_SYSTEM_V5.md](DESIGN_SYSTEM_V5.md) · [SITE_UPLEVEL_PLAYBOOK.md](SITE_UPLEVEL_PLAYBOOK.md) | The v5 site brief (intent · standards · change discipline) |
| [design/PORTRAIT_RUNBOOK.md](design/PORTRAIT_RUNBOOK.md) | Coach-portrait style bible + commissioning gate (ADR-106) |
| [COST_TRACKER.md](COST_TRACKER.md) | The $85 budget (surge $100 — ADR-133) + real run-rate |
| [RESERVED_CONCURRENCY.md](RESERVED_CONCURRENCY.md) | Concurrency strategy |
| [A11Y_BASELINE.md](A11Y_BASELINE.md) | Accessibility baseline (pre-v4 audit) |

## Logs (append-only history)

| Doc | |
|---|---|
| [CHANGELOG.md](CHANGELOG.md) | What shipped, version by version |
| [INCIDENT_LOG.md](INCIDENT_LOG.md) | Incidents + inline RCAs (the current post-mortem home; `rca/` is the older standalone format) |
| [BACKLOG.md](BACKLOG.md) | **Frozen archive** (ADR-099 — the live backlog is GitHub Issues) |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Superseded pointer shell → CONVENTIONS + QUICKSTART + deploy/README |

## Subdirectories

| Dir | What's in it |
|---|---|
| `specs/` | Dated feature specs (shipped — historical record; includes the 2026-06-21 page-redesign series) |
| `archive/` | Superseded designs, plans, and launch artifacts (incl. the v4 design quartet, V2 audit) |
| `reviews/` | Dated board/consultancy reviews (see [R21](reviews/R21_BACKLOG.md), the 2026-07-06 definitive review; [FRONTIER_REVIEW_2026-07-18](reviews/FRONTIER_REVIEW_2026-07-18.md), the quantified-life strategy review → label `review:frontier-2026-07-18`) |
| `design/` | Current design assets + the portrait runbook |
| `design-review/` | The paste-ready design-review prompt kit (current tooling) |
| `coaching/` | Coaching program docs (PRIVATE-flagged content — never surface publicly) |
| `content/` | Content-production checklists (build dispatches etc.) |
| `briefs/` | Dated feature briefs (historical) |
| `audits/` · `v2-audits/` · `rca/` | Dated audit + post-mortem records |
| `restart/` | **Machine-written** reset-pipeline run reports (the restart scripts write here — do not relocate) |
| `site-reviews/` | Dated site reviews |

---

## How this wiki maintains itself

Four layers keep these pages true (full contract: [CONVENTIONS.md](CONVENTIONS.md) §7):

1. **Generated facts** — counts/versions are never hand-typed in canonical pages; `deploy/sync_doc_metadata.py` discovers them from source (AST) and `--check` fails CI when a literal drifts — including when a sync rule itself stops matching. `MCP_TOOL_CATALOG.md` and the ADR index are fully generated (`scripts/generate_mcp_tool_catalog.py`, `scripts/generate_adr_index.py`).
2. **Mechanical CI lint** — dead-link check, retired-concept (tombstone) scan, and index-coverage check run on every docs push (`docs-ci.yml`) and inside the main pipeline's lint job.
3. **Process gates** — the session-wrap skill has a **doc-impact sweep gate**: every shipped change either updates the affected pages or records an explicit "docs: none needed — <reason>"; silent omission is not an outcome. New pages follow the checklist in CONVENTIONS §7 (status header, index entry here, checkers green).
4. **Periodic verification** — each canonical page carries a `Verified:` date in its status header; the index checker reports pages unverified for >90 days.

**Adding a page?** Flat in `docs/` if canonical, `specs/` if a dated spec, `archive/` if superseded. Give it the status header, add it to this index, run the three checkers. That's the whole process.
