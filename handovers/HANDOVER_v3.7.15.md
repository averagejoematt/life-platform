# Life Platform Handover — v3.7.15
**Date:** 2026-03-13
**Session type:** Architecture Review #8 + P0 execution

---

## What Was Done

### Architecture Review #8 — Full System Review
Grade: A-. Full report at `docs/reviews/architecture_review_8_full.md`. 12 findings (3 HIGH).

### P0 Verification Results (r8_p0_verify.sh)
Ran the P0 verification script. Key discoveries:

**Actual secrets in AWS = 10 (not 9):**
- 7 documented correctly: whoop, withings, strava, garmin, eightsleep, ai-keys, habitify
- 3 undocumented: `ingestion-keys` (COST-B bundle), `webhook-key`, `mcp-api-key`
- 2 documented but DON'T EXIST: `todoist`, `notion` — these use `ingestion-keys` bundle

**Webhook auth (FINDING-2 resolved):** Returns 500 "Auth error" — failing closed (safe but broken). Lambda tries to read `ingestion-keys` secret but IAM has no Secrets Manager access. Fixed in `role_policies.py` — added `secretsmanager:GetSecretValue` for `ingestion-keys`. Needs CDK deploy.

**MCP reserved concurrency:** Not set. ADR-010 says 10.

### Fixes Applied
1. **role_policies.py:** Added Secrets Manager access to `ingestion_hae()` for `life-platform/ingestion-keys` (restores webhook auth after CDK deploy)
2. **test_iam_secrets_consistency.py:** Updated KNOWN_SECRETS to 10 actual secrets (removed nonexistent todoist/notion, added ingestion-keys/webhook-key/mcp-api-key)
3. **sync_doc_metadata.py:** Secret count 9→10, cost $3.60→$4.00
4. **anomaly_detector_lambda.py:** Fixed stale CV_THRESHOLDS comments
5. **ci-cd.yml:** Added IAM lint to Job 2
6. **CHANGELOG.md:** v3.7.15 entry

---

## Platform Status
- Version: v3.7.15
- ⚠️ Webhook auth BROKEN until CDK deploy (failing closed — safe but no data flowing)
- MCP reserved concurrency: NOT SET (ADR-010 says 10)
- SIMP-1 data window: accumulating

## Next Session — Critical Path

### 1. Sync docs
```bash
python3 deploy/sync_doc_metadata.py --apply
```

### 2. Commit current fixes
```bash
git add -A && git commit -m "v3.7.15: Architecture Review #8 — P0 fixes" && git push
```

### 3. Deploy CDK to restore webhook auth
```bash
cd cdk
source .venv/bin/activate
npx cdk deploy LifePlatformIngestion --require-approval never
```
Then verify:
```bash
curl -X POST -H "Authorization: Bearer INVALID_TOKEN" https://a76xwxt2wa.execute-api.us-west-2.amazonaws.com/ingest -d '{"data":{"metrics":[]}}'
# Should return 401 (not 500)
```

### 4. Set MCP reserved concurrency (ADR-010)
```bash
aws lambda put-function-concurrency \
  --function-name life-platform-mcp \
  --reserved-concurrent-executions 10 \
  --region us-west-2
```

### 5. Update ARCHITECTURE.md secrets table (manual — sync script handles counts only)
Replace the 9-secret table with the actual 10-secret list.

### 6. Future
- SIMP-1 tool consolidation (60-day target, ≤80 tools)
- Google Calendar integration
- DDB restore test

---

## Files Changed
- `cdk/stacks/role_policies.py` — webhook IAM fix
- `tests/test_iam_secrets_consistency.py` — updated KNOWN_SECRETS to reality
- `deploy/sync_doc_metadata.py` — secret count 10, SCHEMA.md rule
- `lambdas/anomaly_detector_lambda.py` — CV_THRESHOLDS comments
- `.github/workflows/ci-cd.yml` — IAM lint
- `deploy/r8_p0_verify.sh` — NEW
- `docs/CHANGELOG.md` — v3.7.15
- `handovers/HANDOVER_v3.7.15.md` — this file
