# Handover — v6.8.2: PR 0 — MCP unbreak batch (TD-21/22/23)

**Date:** 2026-05-03
**Scope:** Three independent MCP bugs discovered in the 2026-05-02 evening session that left ~40 write tools broken in production. All fixes shipped in one batch per `docs/CLAUDE_CODE_PATCH_SPEC_2026_05_03.md`.
**Type:** Production hotfix.

## What deployed

| Item | Layer | Lambda(s) | Status |
|---|---|---|---|
| TD-21 — `mcp/tools_lifestyle.py` `, timezone` import | code | `life-platform-mcp`, `life-platform-mcp-warmer` | ✅ live |
| TD-22 — `get_todoist_projects(args=None)` signature | code | `life-platform-mcp`, `life-platform-mcp-warmer` | ✅ live |
| TD-23 — `life-platform/todoist` added to MCP IAM Secrets | IAM | both MCP roles via CDK | ✅ live |

CDK deploy: `LifePlatformMcp` stack — 36s. New code SHA on McpServer: `Pd6GnTqT5/tKHr2IVgTSKMs1FCvXKf209Y1ZiY5Nl+M=`.

## Pre-PR housekeeping (also in this version)

The session opened on a dirty tree with 19 modified files spanning two prior unfinished sessions. Clearing those was a precondition for PR 0:

1. **`852be19` v6.8.0-retroactive: COST-OPT-2 prompt caching + model tiering.** The COST-OPT-2 sprint (v6.7.1 → v6.8.0, 2026-04-09) was implemented in source and the shared layer (v41) was deployed to AWS, but the source diff was never committed before v6.8.1 source-restoration landed on top. This commit makes source match prod again. 13 Lambdas, ADR-049, RUNBOOK cost monitoring section.
2. **`1c2a9f5` docs: capture prior 2026-05-02/03 session design artifacts.** 6 untracked design docs from the prior cowork session: TECH_DEBT_INDEX, CLAUDE_CODE_PATCH_SPEC, alternate FUNCTION_HEALTH_V2_HANDOFF (18KB Technical Board version), PERSONAL_BOARD_FH_2026_DELIBERATION, WR_35_36_ARCHITECTURE_SPEC, cowork_handoff.
3. **`d8a63a0` fix: restore `deploy/sync_doc_metadata.py` from archive.** Script was archived to `deploy/archive/onetime/` in v4.9.0-docs but is still actively referenced by `scripts/update_architecture_header.sh` (the wrapper invoked by `.git/hooks/pre-commit`). Restoring silences the `[WARN] sync_doc_metadata.py not found` that fires on every commit.
4. **`dc0ac14` docs: sync platform metadata across 7 docs.** Side effect of restoring sync_doc_metadata.py — the pre-commit hook auto-applied 14 changes across 7 docs to bring counter values current (66 Lambdas, 123 MCP tools, 36 modules, 9 secrets, 49 alarms). Plus a manual fix to `docs/HANDOVER_LATEST.md` to point at v6.8.1 instead of stale v6.8.0.

## Conflicts surfaced for Matthew (and resolved)

The opening brief said the codebase was "post-source-restoration v6.8.1 (clean)". It wasn't. Two prior sessions left work on the floor: COST-OPT-2 (v6.8.0) and the 2026-05-02 evening MCP-debugging + FH-design session. Surfacing those before touching code added one round-trip but prevented committing on top of an inconsistent base.

The 2026-05-02 evening session also produced an alternate FH v2 handoff with a Technical Board consult prescribing a 5-section labs page restructure that Matthew's tonight-spec doesn't reflect. Decision: write a merged spec (`FUNCTION_HEALTH_V2_HANDOFF_v3.md`) before any PR 4 code; deferred to that PR.

## Sequencing change vs original brief

The original PR plan started with PR 1 (TD-15/16/18/20). Inserted TD-21/22/23 as PR 0 because they're production-broken-right-now (NameError, AccessDenied) while TD-15 is a slow-corrupting correctness bug. Per `docs/CLAUDE_CODE_PATCH_SPEC_2026_05_03.md`, that's the recommended order.

## What's next

- **PR 1 — TD-15/16/18/20.** HAE Lambda + platform_logger fixes. Source already in working tree (`lambdas/health_auto_export_lambda.py` v1.7.0, `lambdas/platform_logger.py` v1.0.2) from a prior session. Needs: review, tests, layer rebuild, deploy, post-deploy v16.1 interim backfill.
- **PR 2 — TD-12 EventBridge + TD-14 PR template.**
- **PR 3 — SECRETS_MAP verification.** Already revealed: AWS has 15 `life-platform/*` secrets, KNOWN_SECRETS in test had 13 + wildcard, 3 secrets in AWS not yet in KNOWN_SECRETS (`anthropic-api-key`, `eightsleep-client`, plus the now-added `todoist`), 1 stale entry in KNOWN_SECRETS (`webhook-key` deleted 2026-03-14). Reconciliation work.
- **PR 4 — FH v2.** Blocked on writing the merged v3 spec first.
- **PR 5 — TD-19 Phase 1 audit.** Audit-only.
- **PR 6 — TD-11 Step 1 audit.** Audit-only.

## Smoke test verification (Matthew)

```text
life-platform:create_experiment name="MCP smoke test — delete me" hypothesis="Tool no longer NameErrors"
life-platform:create_todoist_task content="MCP smoke test — delete me" priority=4
life-platform:get_todoist_projects
```

All three should return `{"created": true, ...}` / `{"projects": [...]}`. If any return `NameError` / `AccessDeniedException` / `TypeError`, deploy didn't take.

## Files changed (PR 0 source commit `b0306b0`)

- `cdk/stacks/role_policies.py` — `life-platform/todoist` in `mcp_server()` Secrets resources
- `mcp/tools_lifestyle.py` — `, timezone` to module import; removed 3 redundant local imports
- `mcp/tools_todoist.py` — `get_todoist_projects(args=None)` signature
- `tests/test_iam_secrets_consistency.py` — KNOWN_SECRETS gains todoist; EXPECTED_COUNT 14 → 15
- `docs/ARCHITECTURE.md` — Secrets table gains a todoist row

## State snapshot

| Metric | Value |
|--------|-------|
| Version | v6.8.2 |
| Lambda Layer | v41 (unchanged — TD-20 still pending in PR 1) |
| Lambdas | 66 (auto-discovered; ARCHITECTURE.md heading was 71, sync_doc_metadata corrected) |
| MCP Tools | 123 (unchanged) |
| Secrets in AWS (`life-platform/*`) | 15 (newly visible: `todoist`, `anthropic-api-key`, `eightsleep-client`) |
| Secrets in KNOWN_SECRETS test | 14 + wildcard (todoist added; `webhook-key` still stale) |
