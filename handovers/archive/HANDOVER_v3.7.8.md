# Life Platform Handover — v3.7.8
**Date:** 2026-03-13
**Session type:** TB7 close-out + DLQ cleared + smoke test fixes

---

## What Was Done

### TB7 Board — Fully Closed

**TB7-11/12/13** — Confirmed already implemented in prior sessions:
- TB7-11: Layer version consistency CI check already in `ci-cd.yml` Plan job
- TB7-12: Stateful resource assertions already in `ci-cd.yml` Plan job
- TB7-13: `digest_utils.py` already in `lambda_map.json` `shared_layer.modules`

**TB7-14** — `SCHEMA.md` TTL section rewritten. Replaced single-row "all others
indefinite" with a per-partition table distinguishing DDB TTL, app-level expiry,
and policy-only retention. Partitions documented: cache (26h DDB TTL), hypotheses
(30d app-level via expiry_date), platform_memory (~90d policy), insights (~180d
policy), decisions/anomalies/raw ingestion (indefinite by design).

**TB7-16** — Comment added to `get_source_fingerprints()` in
`daily_metrics_compute_lambda.py`: new data sources (e.g. Google Calendar) must be
added to the sources list or late-arriving data won't trigger recompute.

### DLQ Investigation and Clear
- Queue: `life-platform-ingestion-dlq` — 5 messages in ALARM since 2026-03-12
- Root cause: Habitify ingestion Lambda failed pre-layer-v9. Same EventBridge event
  (id: d9f45a87) retried 5 times before hitting DLQ. All messages stale.
- Action: Purged queue + reset `life-platform-dlq-depth-warning` alarm to OK
- Habitify confirmed healthy on layer v9.

### Smoke Test Fixes
- Removed `--cli-binary-format raw-in-base64-out` from `post_cdk_reconcile_smoke.sh`
  (AWS CLI v2 was failing on this flag, causing all invocations to return status 0)
- Fixed todoist invocation check (was passing `'{"dry_run": true}'` which also
  failed without the binary format flag — simplified to `'{}'`)

### Handler Regressions Fixed (CDK reconcile overwrote)
- `life-platform-key-rotator` → `key_rotator_lambda.lambda_handler`
- `insight-email-parser` → `insight_email_parser_lambda.lambda_handler`

---

## TB7 Board Final Status

All 30 TB7 items resolved:
- TB7-1 through TB7-10: ✅ v3.7.0–v3.7.2 (TB7-10 N/A)
- TB7-11/12/13: ✅ Already in ci-cd.yml / lambda_map.json
- TB7-14/16: ✅ v3.7.8
- TB7-15/17: ✅ v3.7.6
- TB7-18: 🔴 Google Calendar (next major feature)
- TB7-19 through TB7-23: ✅ v3.7.7
- TB7-24 through TB7-30: 🔴 Larger efforts / data-gated (see PROJECT_PLAN.md)

---

## Open Items / Next Up

1. **Google Calendar integration** — Next major feature (~6-8h). Board rank #2.
   TB7-18. Rodriguez/Sarah sponsors. Demand-side intelligence: meeting load,
   deep work blocks, cognitive load correlations.

2. **TB7-24** — Lambda handler integration tests (larger effort, future session)

3. **TB7-25** — CI/CD rollback mechanism (alias-based atomic deploys)

4. **TB7-26** — CloudFront + WAF rate rule on MCP Function URL

5. **TB7-27** — MCP tool tiering system design (before SIMP-1 data arrives)

6. **TB7-28/29** — SIMP-1 + Architecture Review #8 (~2026-04-08)

7. **Billing SNS confirmation** — Check awsdev@mattsusername.com for SNS
   subscription confirmation (from TB7-15). Alarm won't notify until confirmed.

---

## Key Architecture Notes
- Platform: v3.7.8, 42 Lambdas, 19 data sources, 8 CDK stacks
- Shared layer: v9 (life-platform-shared-utils)
- DLQ: life-platform-ingestion-dlq — CLEAR (0 messages)
- All CloudWatch alarms: OK state
- Smoke test: 10/10 passing
- Post-deploy rule: run `bash deploy/post_cdk_reconcile_smoke.sh` after every `cdk deploy`
