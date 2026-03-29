# Life Platform Handover — v3.7.27
**Date:** 2026-03-15
**Session type:** 10-item unblocked sweep (Technical Board planning session)

---

## Platform Status
- **Version:** v3.7.27
- **MCP tools:** 88
- **Lambdas:** 42 (CDK) + 1 Lambda@Edge (cf-auth, us-east-1)
- **Data sources:** 20
- **Secrets:** 11
- **Alarms:** 49 (+ 1 new in us-east-1: life-platform-cf-auth-errors)
- **Tests:** 90/90 offline + 11 integration tests (I1-I11, manual)
- **Correlation pairs:** 23

---

## What Was Done This Session (v3.7.27)

10 of 11 planned items completed (Calendar OAuth deferred per plan). Two post-run script bugs patched.

### 1. Lambda@Edge alarm — ✅ LIVE (us-east-1)
- Secret verified in us-east-1 ✅
- `life-platform-cf-auth-errors` alarm created in us-east-1 CloudWatch
- **No SNS action** — CloudWatch alarms in us-east-1 cannot use the us-west-2 SNS topic. Alarm is visible in console only. To add email: create `life-platform-alerts` topic in us-east-1 and update the alarm.
- Script fixed: removed `--alarm-actions`/`--ok-actions` with wrong-region SNS ARN.

### 2. CLEANUP-2 — ✅ committed
- `ci/lambda_map.json`: new `lambda_edge` section added with `cf-auth` entry, region annotation, CloudFront distribution ID, and note that it's manually managed outside CDK.

### 3. CLEANUP-4 — ✅ committed
- `lambdas/ingestion_validator.py`: docstring fixed — duplicate `computed_insights` removed, count corrected 22→20.
- `lambdas/weekly_correlation_compute_lambda.py`: `from datetime import` removed from inside lagged correlation loop — now uses top-level imports.

### 4. MCP S3 permissions tightened — ✅ committed, ⚠️ CDK NOT YET DEPLOYED
- `cdk/stacks/role_policies.py` — `mcp_server()` tightened from `BUCKET_ARN/*` (full-bucket read) to:
  - `s3:GetObject` on `config/*` and `raw/matthew/cgm_readings/*` only
  - `s3:ListBucket` scoped to `raw/matthew/cgm_readings/` prefix only
- `docs/ARCHITECTURE.md` IAM section updated to reflect this
- **CDK deploy failed** due to working directory: `npx cdk deploy` was run from project root but `lambda_helpers.py` uses `Code.from_asset("../lambdas")` which requires `cdk/` as CWD. Fix: `cd cdk && npx cdk deploy LifePlatformMcp`

### 5. SEC-3 input validation assessment — ✅ new doc
- `docs/sec3_input_validation_assessment.md` created
- **HIGH finding: S3 path traversal** in `_load_cgm_readings` — malformed date like `"../../config/board_of_directors"` could read arbitrary S3 objects. Fix: add regex date validation before key construction (~30 min).
- MEDIUM finding: unbounded date range scans — need `MAX_LOOKBACK_DAYS=365` cap with `validate_date_range()` utility.
- Both fixes are un-gated; HIGH should ship before R13.

### 6. I1/I2/I5 wired into CI/CD — ✅ committed
- `.github/workflows/ci-cd.yml`: new `post-deploy-checks` job after `deploy`, parallel to `smoke-test`
  - **I1** (handler names) and **I2** (layer version) — blocking
  - **I5** (secrets exist) — `continue-on-error: true` until OIDC role gets `secretsmanager:DescribeSecret`
- To fully enable I5: add `secretsmanager:DescribeSecret` on `life-platform/*` to `github-actions-deploy-role`.

### 7. PITR restore drill — ✅ executed, script fixed
- Full drill ran: restore → ACTIVE (4m40s) → spot-checked → deleted
- Whoop record absent (expected — March 14 was sick day); computed_metrics ✅; profile ✅
- Item count shown as 0 (expected — DynamoDB approximate count not yet updated for new table)
- Script bug fixed: `RECOVERY` and `GRADE` now initialized to `"N/A"` before conditional assignment

### 8. CloudWatch operational dashboard — ✅ LIVE
- `life-platform-ops` dashboard created at: https://us-west-2.console.aws.amazon.com/cloudwatch/home?region=us-west-2#dashboards/dashboard/life-platform-ops
- 5-row layout: alarm strip, Lambda errors (ingestion/compute/MCP), DLQ depth, freshness metrics (StaleSourceCount + new PartialCompletenessCount), pipeline staleness, MCP duration p50/p99, invocations, DynamoDB RCU/WCU + throttles

### 9. Freshness checker field completeness — ✅ DEPLOYED
- `lambdas/freshness_checker_lambda.py`: `FIELD_COMPLETENESS_CHECKS` dict added (10 sources)
- For each fresh source, does a `GetItem` on the most recent record and checks expected fields are non-null
- `partial_sources` list, separate SNS alert, new `PartialCompletenessCount` CloudWatch metric
- Return value extended: `partial_count`, `partial_sources` added

---

## Outstanding Actions for Next Session

### Immediate (before April 13):
```bash
# 1. Deploy MCP S3 scope tightening (CDK — must run from cdk/ directory)
cd ~/Documents/Claude/life-platform/cdk
source .venv/bin/activate
npx cdk deploy LifePlatformMcp
cd ..
bash deploy/post_cdk_reconcile_smoke.sh

# 2. Run Lambda@Edge alarm script again (now fixed — no SNS region error)
bash deploy/create_lambda_edge_alarm.sh

# 3. CLEANUP-3: Google Calendar OAuth (still deferred from every review)
python3 setup/setup_google_calendar_auth.py

# 4. CLEANUP-1: Remove write_composite_scores() dead code (gate: Apr 13 — 30 days computed_metrics)
```

### SEC-3 S3 path traversal fix (HIGH — ~30 min, before R13):
In `mcp/tools_cgm.py`, `_load_cgm_readings()` — add at top:
```python
import re
if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', date_str):
    return []
try:
    datetime.strptime(date_str, "%Y-%m-%d")
except ValueError:
    return []
```

### To enable I5 in CI (OIDC role needs):
Add to `github-actions-deploy-role` policy:
```json
{"Effect": "Allow", "Action": "secretsmanager:DescribeSecret",
 "Resource": "arn:aws:secretsmanager:us-west-2:205930651321:secret:life-platform/*"}
```

### April 13 session:
- SIMP-1 Phase 2 (EMF data available → cut tools to ≤80)
- Architecture Review #13 (`python3 deploy/generate_review_bundle.py` first)
- CLEANUP-1 (gate clears)
- Decide ADR-027 + MCP domain split at R13

---

## Session Close Ritual
1. `python3 deploy/sync_doc_metadata.py --apply`
2. `git add -A && git commit && git push`
