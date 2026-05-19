# Handover — v6.9.5: qa-smoke false-positive sweep + DLQ drain

**Date:** 2026-05-03 (very late evening, after v6.9.4)
**Trigger:** Inbox at 9pm PT showed CI failure (DLQ 90 messages) + "🔴 QA: 8 FAILURES" email. User asked "are we sure we are good?" — no.
**Scope:** Triage. 3 of 8 QA failures were real bugs in qa-smoke itself; remaining 5 are known Matthew-action or deferred items.

See [HANDOVER_v6.9.5.md](HANDOVER_v6.9.5.md) for full details.

## Headlines

1. **qa-smoke path mismatch** — was checking `dashboard/data.json` (old path); canonical writer moved to `dashboard/matthew/data.json` 2026-03-08. False S3-stale failures for ~56 days. Fixed.
2. **MCP auth scheme mismatch** — qa-smoke sent `x-api-key` but Function URL needs `Authorization: Bearer lp_<hmac>`. Two MCP checks 401-ing every run. Fixed via deterministic Bearer derivation.
3. **`tool_get_sources` KeyError** — `oldest["Items"][0]["date"]` raised when one source had a record without `date` field. Fixed via `.get()`.
4. **DLQ drained** — 90 stale messages from silence period (April 20+). Purged. Test `test_i9_dlq_empty` now passes.

## Verification

Manual qa-smoke invoke post-deploy: **8 failures → 5 failures**. Remaining are Matthew-action stale sources (Strava, MacroFactor) + DDB:withings false-positive timing edge case + blog:links (separate bundle).

## State as of 9:15pm PT

✅ Alarms in ALARM: 0
✅ DLQ messages: 0
✅ qa-smoke failures: 5 (all real Matthew-action or deferred low-priority)
✅ MCP `get_sources` and `get_todoist_snapshot` working

---

**Previous:** [HANDOVER_v6.9.4.md](HANDOVER_v6.9.4.md) — visual_qa v3.1 + character_stats 503→200
