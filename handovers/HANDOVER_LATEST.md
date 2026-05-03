# Handover — v6.8.5: PR 3 — SECRETS_MAP verification + KNOWN_SECRETS reconciliation (TD-13)

**Date:** 2026-05-03
**Scope:** Doc-only PR. Reconciles SECRETS_MAP, test KNOWN_SECRETS, and ARCHITECTURE.md against AWS reality (15 secrets).

See [HANDOVER_v6.8.5.md](HANDOVER_v6.8.5.md) for full details.

## Summary

- 15 `life-platform/*` secrets verified in AWS, all rows in `docs/SECRETS_MAP.md` flipped from ⚠ to ✅, consumer Lambdas populated.
- `KNOWN_SECRETS` test list: +eightsleep-client, +anthropic-api-key, −webhook-key. EXPECTED_COUNT 15 → 16.
- `docs/ARCHITECTURE.md` Secrets section: 9 → 15 active secrets, cost line updated, missing rows added.
- Stale `webhook-key` comment removed from `cdk/stacks/role_policies.py`.

## Action items for Matthew

1. **Orphan `life-platform/anthropic-api-key`** — no consumer in source. Delete it, or wire up a consumer. Decision pending.
2. **Todoist secret consolidation** — ingestion path still reads from `ingestion-keys` bundle; MCP path uses dedicated `life-platform/todoist`. Migrate ingestion later when convenient.

## Current State

| Metric | Value |
|--------|-------|
| Version | v6.8.5 |
| Lambdas | 66 |
| MCP Tools | 123 |
| Secrets in AWS | 15 |
