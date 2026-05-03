# Handover — v6.8.3: PR 1 — HAE source-priority + platform_logger (TD-15/16/18/20) + MCP outage hotfix

**Date:** 2026-05-03
**Scope:** TD_BATCH_HAE_FIXES spec end-to-end. Plus a 9.5-hour MCP outage hotfix that fired during the PR 0 deploy window.

See [HANDOVER_v6.8.3.md](HANDOVER_v6.8.3.md) for full details.

## Summary

- **TD-15/16/18** [HIGH/MED/LOW]: HAE Lambda v1.7.0 with SOURCE_PRIORITY dict + pick_source_or_all() helper, ported from v16.1 backfill. Fixes iPhone+Garmin step double-count and My-Water+MacroFactor water double-count. weight_body_mass alias added.
- **TD-20** [LOW]: platform_logger.py v1.0.2 normalizes exc_info=True/BaseException to tuple before makeRecord. No more secondary TypeError on error log lines.
- **Layer v42** published via `cdk deploy LifePlatformCore`. Re-attached to all 65 layer-dependent Lambdas via stack-by-stack cdk deploys.
- **HAE Lambda** redeployed via `deploy/deploy_lambda.sh` (then re-bundled by CDK to match the kitchen-sink pattern). TD-15/16/18 + TD-20 (via inline platform_logger bundle).
- **MCP outage hotfix**: latent typo `_decimal_to_float` → `decimal_to_float` in `mcp/tools_data.py` and `mcp/tools_coach_intelligence.py` (from de57c67, v6.6.0, 3 weeks ago). Surfaced when PR 0's CDK deploy re-uploaded the MCP code asset for the first time since the bad commit. ~9.5h outage, caught by canary, recovered in 3 minutes.

## Tests added

- `tests/test_health_auto_export.py` — 16 tests (priority resolver + e2e dedup + weight alias + Tier-2 fallthrough)
- `tests/test_platform_logger.py` — 5 tests (exc_info forms; no secondary TypeError leak)

## Matthew action item

**Re-run v16.1 backfill** for the interim window (May 2 18:32 PT → May 3 15:53 UTC). Requires fresh Apple Health export from iPhone. ~5 min once exported. See HANDOVER_v6.8.3.md for the exact commands.

## Behavioral change

Step counts will drop ~50% on iPhone+Garmin overlap days going forward — this is the bug fix making things correct, not a regression.

## Current State

| Metric | Value |
|--------|-------|
| Version | v6.8.3 |
| Lambda Layer | v42 (was v41) |
| Lambdas | 66 |
| MCP Tools | 123 |
| Stacks deployed | Core + Mcp + Ingestion + Compute + Email + Operational + Web |
