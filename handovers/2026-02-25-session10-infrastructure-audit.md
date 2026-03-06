# Handover — Session 10: Full Infrastructure Audit

**Date:** 2026-02-25  
**Version:** v2.28.0 (no version bump — audit only, no code changes)

---

## What happened this session

Conducted a comprehensive 6-part infrastructure audit of the entire Life Platform AWS account, checking every resource against ARCHITECTURE.md and RUNBOOK.md. No code was deployed — this was purely a discovery and documentation exercise.

**Audit reports generated (all in claude.ai outputs):**
1. Part 1: Storage & Data Layer (S3, DynamoDB)
2. Part 2: IAM & Security (18 roles, 20 Lambdas, permissions)
3. Part 3: Scheduling & Automation (18 EventBridge rules)
4. Part 4: Lambda Functions (configs, errors, alarms, logs)
5. Part 5: API Gateway & Networking (Function URL, SES, SNS, Secrets, Budget)
6. Part 6: Final Report (all 31 findings prioritized with fix scripts)

---

## Key findings

### Critical (fix immediately)
1. **Anomaly detector has NO EventBridge trigger** — Lambda exists but is never invoked. Daily brief anomaly section reads empty data. 3 CLI commands to fix.
2. **Enrichment alarm watches nonexistent function** — `ingestion-error-enrichment` alarm monitors `activity-enrichment-nightly` (the EventBridge rule name) instead of `activity-enrichment` (the Lambda). Will never fire.

### Medium (fix soon)
- MCP server role has `dynamodb:Scan` despite docs saying "no Scan"
- SES `Resource: "*"` on weekly-digest and anomaly-detector roles
- 6 Lambdas missing DLQ (garmin, habitify, notion, dropbox-poll, both enrichments)
- ARCHITECTURE.md says "API Gateway" for MCP — actually a Lambda Function URL with AuthType NONE
- Habitify alarm currently in ALARM state (active error)
- Apple Health S3 trigger missing (webhook is primary path now)
- 5 schedule discrepancies between ARCHITECTURE.md and reality
- Composite alarm documented but doesn't exist

### Systemic pattern
ARCHITECTURE.md has drifted to ~70% accuracy. RUNBOOK.md is ~93% accurate. The original 7 ingestion Lambdas were built with full rigor; later additions missed steps (DLQs, alarms, docs).

---

## What needs to happen next

### Immediate: Phase 1-2 fixes from audit report (~1 hour)
The Part 6 final report contains copy-paste CLI commands for all fixes in 5 phases. Phases 1-2 (critical + security) are highest priority.

### Then: ARCHITECTURE.md overhaul
12 specific doc updates identified in Phase 5 of the fix plan. The doc needs a significant refresh to match reality.

### Then: Resume roadmap
After fixes, resume from wherever the PROJECT_PLAN.md priorities are. The audit didn't change the roadmap — it just identified infrastructure debt to clear first.

---

## What did NOT change
- No code deployed
- No Lambda configs modified  
- No ARCHITECTURE.md or SCHEMA.md changes (audit was read-only)
- Version remains v2.28.0

---

## Important context for next session
- DST starts March 8 (12 days away) — all EventBridge crons use fixed UTC and will shift 1 hour in PT
- MCP server duration trending up (1.2s → 2.8s avg over 3 days) — worth monitoring
- Bucket grew from 34MB → 2.3GB in one day — likely `raw/` directory, investigate
- Budget: $0.63 MTD, running ~$5/month total — excellent cost discipline
- 12 secrets at $0.40/month each = $4.80 is the biggest cost driver
