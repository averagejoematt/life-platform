# Handover — v6.8.5: PR 3 — SECRETS_MAP verification + KNOWN_SECRETS reconciliation (TD-13)

**Date:** 2026-05-03
**Scope:** Doc-only PR. Reconciles `docs/SECRETS_MAP.md`, `tests/test_iam_secrets_consistency.py KNOWN_SECRETS`, and `docs/ARCHITECTURE.md` Secrets table against AWS reality.

## What deployed

| Item | Mechanism | Status |
|---|---|---|
| `docs/SECRETS_MAP.md` rewrite | git commit | ✅ |
| `KNOWN_SECRETS` test list reconciliation | git commit | ✅ |
| `ARCHITECTURE.md` secrets table sync | git commit | ✅ |
| Stale `cdk/stacks/role_policies.py` `webhook-key` comment removed | git commit | ✅ |
| **No Lambda code touched** | | |

## What AWS actually has

15 `life-platform/*` secrets:

```
ai-keys             (24 consumers — main Anthropic pool)
anthropic-api-key   (orphan — no consumer in source)
dropbox             (dropbox-poll, pipeline-health-check)
eightsleep          (eightsleep-data-ingestion, pipeline-health-check)
eightsleep-client   (eightsleep-data-ingestion only)
garmin              (garmin-data-ingestion + freshness + pipeline-health)
habitify            (habitify-data-ingestion, pipeline-health-check)
ingestion-keys      (todoist, notion, dropbox-poll, hae-webhook, pipeline-health bundle)
mcp-api-key         (mcp Lambda config, canary, qa-smoke, mcp-key-rotator)
notion              (notion-journal-ingestion, pipeline-health-check)
site-api-ai-key     (site-api-ai-lambda, life-platform-site-api, pipeline-health-check)
strava              (strava-data-ingestion + freshness + pipeline-health)
todoist             (life-platform-mcp via mcp/tools_todoist.py)
whoop               (whoop-data-ingestion + freshness + pipeline-health)
withings            (withings-data-ingestion + freshness + pipeline-health)
```

## Drift findings (now fixed)

1. **`KNOWN_SECRETS` test list**:
   - Added: `eightsleep-client`, `anthropic-api-key` (existed in AWS but never registered)
   - Removed: `webhook-key` (deleted from AWS 2026-03-14, was stale entry)
   - `EXPECTED_COUNT` 15 → 16 (15 actual + 1 wildcard)
   - `DELETED_SECRETS` list now also catalogs `webhook-key` and `google-calendar` for future drift detection
2. **`ARCHITECTURE.md` Secrets section**:
   - Heading "9 active secrets" → "15 active secrets"
   - Cost line "$3.60/month" → "$6.00/month" (15 × $0.40)
   - Added rows for `eightsleep-client`, `anthropic-api-key`, `notion`, `dropbox`
3. **`cdk/stacks/role_policies.py:326`**:
   - Stale comment "Dedicated life-platform/webhook-key also exists — migration deferred" replaced with note that the secret was deleted 2026-03-14

## Carry-forward — Matthew action items

1. **Decide on the orphan `life-platform/anthropic-api-key`** (created 2026-03-18, no consumer in source, no IAM grant). Either:
   - Delete it from AWS (`aws secretsmanager delete-secret --secret-id life-platform/anthropic-api-key --recovery-window-in-days 7 --region us-west-2`), OR
   - Wire up a consumer (perhaps it was created for a project that didn't ship)
   - Note: `docs/SECRETS_MAP.md` has it flagged with the `⚠️` orphan marker.
2. **Decide on Todoist secret consolidation.** PR 0 added `life-platform/todoist` for the MCP write tools. The ingestion path still reads Todoist's API key from `ingestion-keys` (bundled). Eventually the ingestion Lambda should also migrate to `life-platform/todoist` for consistency, but that requires a Lambda code change in lock-step with the secret rename (or just update the Lambda's `SECRET_NAME` env var to point at the dedicated secret). Low priority — not blocking.

## Doc-only PR — no AWS state changes

This PR didn't touch any Lambda code, didn't run `cdk deploy`, didn't change any secret values. Pure documentation reconciliation.

## State snapshot

| Metric | Value |
|--------|-------|
| Version | v6.8.5 |
| Lambda Layer | v42 (unchanged) |
| Lambdas | 66 (unchanged) |
| MCP Tools | 123 (unchanged) |
| Secrets in AWS | 15 (unchanged — just visible to docs now) |
| KNOWN_SECRETS test entries | 16 (was 15; +eightsleep-client, +anthropic-api-key, -webhook-key) |
