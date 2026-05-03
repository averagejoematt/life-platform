# Handover — v6.8.2: PR 0 — MCP unbreak batch (TD-21/22/23)

**Date:** 2026-05-03
**Scope:** Three independent MCP bugs discovered in the 2026-05-02 evening session that left ~40 write tools broken in production. All fixes shipped in one batch per `docs/CLAUDE_CODE_PATCH_SPEC_2026_05_03.md`.
**Type:** Production hotfix.

See [HANDOVER_v6.8.2.md](HANDOVER_v6.8.2.md) for full details.

## Summary

- **TD-21** (HIGH): `mcp/tools_lifestyle.py:9` missing `, timezone` import → ~40 functions raised `NameError` at runtime. Fixed; cleanup of 3 redundant local imports.
- **TD-22** (LOW): `get_todoist_projects` signature mismatch (0 args, dispatcher passes 1). Changed to `(args=None)`.
- **TD-23** (HIGH): MCP IAM role missing `secretsmanager:GetSecretValue` on `life-platform/todoist` → all MCP Todoist write tools `AccessDeniedException`. Added via CDK to both McpServerRole and McpWarmerRole.

## Pre-PR housekeeping

Cleared a dirty tree carrying two prior unfinished sessions:

- v6.8.0-retroactive (COST-OPT-2 prompt caching + model tiering — was deployed to AWS via shared layer v41 but never committed)
- 6 untracked design docs from the 2026-05-02 cowork session (TECH_DEBT_INDEX, alternate FH v2 handoff, Personal Board deliberation, WR-35/36 spec, etc.)
- Restored `deploy/sync_doc_metadata.py` from archive (silences pre-commit warning; auto-synced 7 docs)

## Sequencing change

Inserted TD-21/22/23 as PR 0 ahead of the original PR 1 (TD-15/16/18/20) because the MCP failures are production-broken-right-now while TD-15 is a slow-corrupting correctness bug. Per `docs/CLAUDE_CODE_PATCH_SPEC_2026_05_03.md`, this is the recommended order.

## What's next

- **PR 1 — TD-15/16/18/20.** HAE Lambda + `platform_logger`. Source already written by a prior session in working tree; needs review + tests + layer rebuild + deploy.
- PR 2 → PR 6 unchanged from original brief, except PR 4 will start by writing a merged v3 FH spec reconciling Matthew's tonight version with the alternate Technical Board version.

## Current State

| Metric | Value |
|--------|-------|
| Version | v6.8.2 |
| Lambda Layer | v41 (unchanged) |
| Lambdas | 66 |
| MCP Tools | 123 (unchanged) |
| Secrets in AWS | 15 (`life-platform/*`) |
