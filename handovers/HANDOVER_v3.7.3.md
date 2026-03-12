# Handover — v3.7.3 (2026-03-11)

## Session Summary
Completed TB7-11 through TB7-17 (all 7 tasks from the CI hardening batch).
Also fixed a silent duplicate sick-day check block in `daily_metrics_compute_lambda.py`.

---

## What Was Done

### TB7-11 — Layer version consistency CI check
Added "Verify layer version consistency" step to `.github/workflows/ci-cd.yml` Plan job.
Fetches latest `life-platform-shared-utils` layer ARN, iterates all consumers in
`ci/lambda_map.json`, fails CI if any Lambda is on a stale version.

### TB7-12 — Stateful resource assertion
Added "Assert stateful resources exist" step to CI Plan job. Verifies DynamoDB table
`life-platform`, S3 bucket `matthew-life-platform`, SNS topic
`arn:aws:sns:us-west-2:205930651321:life-platform-alerts`, and KMS key
`alias/life-platform-dynamodb` all exist before any CDK deploy proceeds.

### TB7-13 — digest_utils.py in lambda_map.json
Added `lambdas/digest_utils.py` to `shared_layer.modules` and `skip_deploy.files` in
`ci/lambda_map.json`. It's a shared layer module, not a standalone Lambda — previously
missing from the layer manifest.

### TB7-14 — TTL policy in SCHEMA.md
Added `## TTL Policy` section to `docs/SCHEMA.md`. Documents: only `CACHE#matthew`
partition has TTL (26h, field `ttl`, value `int(time.time()) + 93600`). All other
partitions retain indefinitely. Explains background deletion timing and how to add TTL
to new partitions.

### TB7-15 — AI cost soft alarm
Created `deploy/create_ai_cost_alarm.sh`. Creates CloudWatch `EstimatedCharges` alarm
in `us-east-1` (billing metrics region only), threshold $5/month (period 86400s),
SNS to `life-platform-alerts`. Requires "Receive Billing Alerts" enabled in AWS Console
→ Billing → Preferences (one-time manual step — script includes reminder note).

**To run:**
```bash
bash deploy/create_ai_cost_alarm.sh
```

### TB7-16 — Fingerprint idempotency docstrings
Added detailed docstrings to `get_source_fingerprints()` and `fingerprints_changed()`
in `lambdas/daily_metrics_compute_lambda.py` explaining the data-aware idempotency
pattern and ISO string comparison safety.

### TB7-17 — DLQ alarm period verifier
Created `deploy/verify_dlq_alarm_periods.sh`. Scans all CloudWatch alarms for
DLQ-related metrics (`ApproximateNumberOfMessagesNotVisible` or names containing
"dlq"/"dead"), fails if any alarm has `Period > 3600` seconds (1 hour). Outputs
per-alarm table with period, evaluation count, total window, and current state.

**To run:**
```bash
bash deploy/verify_dlq_alarm_periods.sh
```

### Bug fix — Duplicate sick-day block in daily_metrics_compute_lambda.py
The Lambda handler had the entire sick-day try/except/if block duplicated verbatim
(first copy used f-string logger, second used %-format). The duplicate was silent —
both blocks ran, second one overwrote nothing harmful but was ~2600 bytes of dead code.
Fixed: second occurrence removed. File is now 863 lines, syntax verified clean.

---

## Current State

- **Version:** v3.7.3
- **TB7 board:** All tasks complete (TB7-1 through TB7-17, noting TB7-10 N/A)
- **api-keys secret:** Permanent delete scheduled 2026-03-17 (grep sweep TB7-4 still needed to confirm no references remain)
- **Brittany email:** Live at awsdev@mattsusername.com; `BRITTANY_EMAIL` env var still needs to be set to her real address
- **GitHub `production` Environment:** TB7-1 — still needs verification in GitHub Settings

---

## Immediate Next Priorities

1. **TB7-4 — api-keys grep sweep** (⚠️ delete deadline 2026-03-17)
   ```bash
   grep -rn "api-keys" lambdas/ mcp/ deploy/ --include="*.py" --include="*.sh" --include="*.json"
   ```
   Confirm no code still reads from `life-platform/api-keys`. Then permanently delete.

2. **TB7-1 — GitHub `production` Environment approval gate**
   Verify GitHub Settings → Environments → `production` is configured with required reviewers.

3. **TB7-2 — Brittany email** (already marked complete but env var still needed)
   Set `BRITTANY_EMAIL` env var on the Brittany email Lambda to her real address.

4. **Google Calendar integration** — highest-priority remaining data gap (6–8h estimated)

5. **OBS-1 completion** — structured logger rollout to remaining Lambdas

---

## Pending Deploy Actions

- `deploy/create_ai_cost_alarm.sh` — run once to create the $5/month AI cost alarm (TB7-15)
- `deploy/verify_dlq_alarm_periods.sh` — run to verify DLQ alarm periods ≤ 1h (TB7-17)
- No Lambda deploys needed for this session (only CI config, docs, and code quality changes)

---

## Key Files Changed This Session
- `.github/workflows/ci-cd.yml` — TB7-11 + TB7-12 CI steps added
- `ci/lambda_map.json` — TB7-13 digest_utils.py in shared layer
- `docs/SCHEMA.md` — TB7-14 TTL policy section
- `deploy/create_ai_cost_alarm.sh` — new (TB7-15)
- `deploy/verify_dlq_alarm_periods.sh` — new (TB7-17)
- `lambdas/daily_metrics_compute_lambda.py` — TB7-16 docstrings + bug fix
- `docs/CHANGELOG.md` — v3.7.3 entry
- `docs/PROJECT_PLAN.md` — version bumped to v3.7.3
