# Documentation Index

The map for `docs/`. Files stay flat (many are referenced by path from
`deploy/sync_doc_metadata.py`, the restart pipeline, and `CLAUDE.md`), so this
index — not a folder hierarchy — is the way to navigate. New here? Start at the
top and stop when you have what you need.

## Start here
| Doc | What it gives you |
|---|---|
| [ONBOARDING.md](ONBOARDING.md) | First-day mental model, key concepts |
| [REPO_STRUCTURE.md](REPO_STRUCTURE.md) | Canonical top-level layout + "where does X go" rules |
| [QUICKSTART.md](QUICKSTART.md) | First-day commands (AWS auth, deploy, rollback) |
| [../README.md](../README.md) · [../CLAUDE.md](../CLAUDE.md) | Repo overview · the AI-agent brief |

## Architecture & data
| Doc | |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Full system design (the 8 stacks, ingest→store→serve) |
| [SCHEMA.md](SCHEMA.md) | **Authoritative** DynamoDB field reference |
| [INFRASTRUCTURE.md](INFRASTRUCTURE.md) | The AWS account by the numbers |
| [DEPENDENCY_GRAPH.md](DEPENDENCY_GRAPH.md) | What calls what; SPOFs |
| [MCP_TOOL_CATALOG.md](MCP_TOOL_CATALOG.md) | All 133 MCP tools by domain |
| [API.md](API.md) | The Site-API endpoints |
| [DATA_GOVERNANCE.md](DATA_GOVERNANCE.md) | PII classification + retention |

## Operations
| Doc | |
|---|---|
| [RUNBOOK.md](RUNBOOK.md) | Daily ops + troubleshooting |
| [RUNBOOK_REENTRY.md](RUNBOOK_REENTRY.md) | OAuth re-auth / source re-entry |
| [MONITORING.md](MONITORING.md) · [SLOs.md](SLOs.md) | Alarms / what fires · service levels |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Deploy mechanics |
| [CONVENTIONS.md](CONVENTIONS.md) | **The load-bearing reflexes** (layer sequence, deploy-from-main, squash-drift, CI ordering, asset-staging trap) + the drift-discovery commands |
| [MANAGED_WHERE_LEDGER.md](MANAGED_WHERE_LEDGER.md) | **Out-of-IaC resources** (DynamoDB table+GSIs, S3 bucket policy, SES, DNS, SSM) — what's managed where + automated assertions |
| [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md) | Backups + recovery |
| [OPERATOR_GUIDE.md](OPERATOR_GUIDE.md) | Operator onboarding + daily checks |
| [RESERVED_CONCURRENCY.md](RESERVED_CONCURRENCY.md) | Concurrency strategy |

## Security & secrets
| [SECURITY.md](SECURITY.md) | Threat model + defense layers + accepted risks |
|---|---|
| [SECRETS_MAP.md](SECRETS_MAP.md) · [SECRETS_ROTATION.md](SECRETS_ROTATION.md) | Inventory · rotation |

## Decisions, taxonomy & cost
| [DECISIONS.md](DECISIONS.md) | **ADRs (001–105)** — why things are the way they are; ADR-103 = complexity-posture ledger, ADR-104 = honest numbers, ADR-105 = the rigor bar |
|---|---|
| [TAG_CODES.md](TAG_CODES.md) | Decode the internal tag alphabet (PG/SIMP/IC/SEC/…) |
| [PHASE_TAXONOMY.md](PHASE_TAXONOMY.md) | What resets vs. persists at experiment restart (ADR-077) |
| [REMEDIATION_TAXONOMY.md](REMEDIATION_TAXONOMY.md) | Self-healing agent's classifier rubric |
| [COST_TRACKER.md](COST_TRACKER.md) | The $75 budget + real run-rate |

## Development & process
| [TESTING.md](TESTING.md) · [REVIEW_METHODOLOGY.md](REVIEW_METHODOLOGY.md) | Test layers · how audits run |
|---|---|
| [A11Y_BASELINE.md](A11Y_BASELINE.md) | Accessibility baseline (pre-v4) |
| [BOARDS.md](BOARDS.md) | The three AI persona boards |
| [design/PORTRAIT_RUNBOOK.md](design/PORTRAIT_RUNBOOK.md) | Coach-portrait style bible + commissioning gate (ADR-106) |

## History & append-only logs
| [CHANGELOG.md](CHANGELOG.md) | What shipped, version by version |
|---|---|
| [INCIDENT_LOG.md](INCIDENT_LOG.md) | Incident records |
| [V2_AUDIT_PLAN.md](V2_AUDIT_PLAN.md) · [V2_AUDIT_PROMPT.md](V2_AUDIT_PROMPT.md) | **Historical** — the 2026-05 V2 audit |

## v4 design (launch artifacts — shipped)
[V4_DESIGN_CONSTITUTION](V4_DESIGN_CONSTITUTION_2026_06_01.md) · [DESIGN_SYSTEM](DESIGN_SYSTEM_V4_THE_MEASURED_LIFE.md) · [CLAUDE_DESIGN_BRIEF](CLAUDE_DESIGN_BRIEF_V4_2026_06_01.md) · [CLAUDE_CODE_PROMPT](CLAUDE_CODE_PROMPT_V4_PASTE_READY.md) · [MIGRATION_MAP](MIGRATION_MAP_V4_2026_06_01.md) · [LAUNCH_DAY_CHECKLIST](LAUNCH_DAY_CHECKLIST.md) (historical)

## Feature specs
[SPEC_HEVY_ROUTINE_WRITELOOP](SPEC_HEVY_ROUTINE_WRITELOOP_2026_05_31.md) (+ [prereqs](SPEC_HEVY_ROUTINE_WRITELOOP_2026_05_31_PREREQS.md))

## Subdirectories
`archive/` (superseded specs/designs) · `reviews/` (board reviews + the 2026-06-07 product summit + the [R21 definitive review](reviews/R21_BACKLOG.md), 2026-07-06) · `rca/` (post-mortems) · `restart/` (reset run reports) · `audits/` · `specs/` · `briefs/` · `content/` · `design/`
