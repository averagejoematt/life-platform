# Handover — v6.8.4: PR 2 — Todoist daily cron + PR template + parity-debt label (TD-12/14/17)

**Date:** 2026-05-03
**Scope:** Three small housekeeping items from `docs/specs/TD_QUICK_DECISIONS.md`. Two land as code (TD-12, TD-14); the third (TD-17) is a Matthew action item.

## What deployed

| Item | Mechanism | Status |
|---|---|---|
| TD-12 — Todoist EventBridge schedule 2x → 1x daily | `cdk deploy LifePlatformIngestion` | ✅ live |
| TD-14 — `.github/PULL_REQUEST_TEMPLATE.md` | git commit | ✅ in repo |
| TD-14 — `parity-debt` GitHub label | `gh label create` | ✅ created |
| TD-17 — disable HAE Tier-2 feeds in iOS app | (Matthew action) | ⏳ pending |

## TD detail

### TD-12 — Todoist EventBridge schedule (LOW)

Spec said the Todoist Lambda was running every 4 hours; reality (from CDK) was every 12 hours (2x daily). Either way, the no-op gate meant most invocations did nothing. Dropped to 1x daily at 14:00 UTC = 6 AM PST / 7 AM PDT (CLAUDE.md mandates UTC-fixed crons — no DST adjustment).

CDK diff was a pure ScheduleExpression change (`cron(15 14,2 * * ? *)` → `cron(0 14 * * ? *)`); no other resources touched.

### TD-14 — PR template + parity-debt label (MED)

Process change. Drift between backfill scripts and live Lambdas (TD-15 was the most recent expensive example) is now caught at PR-review time via a checklist.

PR template at `.github/PULL_REQUEST_TEMPLATE.md` requires checking parity for any PR that touches a `backfill/` script or a Lambda with a corresponding backfill counterpart. The naming convention recommended in the spec (shared prefix between `lambdas/foo_lambda.py` and `backfill/backfill_foo_*.py`) wasn't enforced this PR — we already follow it informally for HAE (`health_auto_export_lambda.py` ↔ `backfill_apple_health_export_v16.py`).

GitHub label `parity-debt` (color `#FBCA04` amber) — for tracking deferred port work.

The quarterly audit suggested in the spec ("grep `backfill/*.py` for unique parsing/normalization functions, then grep the corresponding Lambdas") is not yet automated. Future TD if drift recurs.

### TD-17 — HAE Tier-2 feeds (LOW, Matthew action)

Heart Rate / Resting Heart Rate / SpO2 / respiratory data is sent by the iOS Health Auto Export app but immediately filtered by the live HAE Lambda (Whoop is source of truth). Cosmetic — wastes Lambda invocations, doesn't corrupt data.

**Matthew action:** Open Health Auto Export iOS app → Settings → Automations → find the active automation feeding the webhook → in metric list, untoggle Heart Rate, Resting Heart Rate, SpO2, Respiratory Rate (and any other Whoop-canonical metric). Save. Watch CloudWatch invocation count for ~24h to confirm the drop.

No code change in this PR per the spec's recommendation. Filed in CHANGELOG as a known action item.

## Commits

```
TBD — PR 2: TD-12 (cron) + TD-14 (PR template + label) + archive spec
TBD — docs: v6.8.4 handover + CHANGELOG
```

## What's next

- **PR 3** — SECRETS_MAP verification (doc-only). Already-known findings: 15 actual AWS secrets vs 13+wildcard in `KNOWN_SECRETS`; `anthropic-api-key` and `eightsleep-client` not registered; `webhook-key` deleted but still in test list.
- **PR 4** — write merged FH v3 spec → approval → 4a/4b/4c.
- **PR 5** — TD-19 Phase 1 audit only.
- **PR 6** — TD-11 Step 1 audit only.

## State snapshot

| Metric | Value |
|--------|-------|
| Version | v6.8.4 |
| Lambda Layer | v42 (unchanged) |
| Lambdas | 66 (unchanged) |
| MCP Tools | 123 (unchanged) |
| Todoist invocations/day | 1 (was 2) |
| GitHub labels | +1 (`parity-debt`) |
| Spec moved to archive | docs/specs/TD_QUICK_DECISIONS.md → docs/archive/TD_QUICK_DECISIONS_2026-05-02.md |
