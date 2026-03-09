# Post-Incident Review: Feb 28, 2026 Ingestion Outage

**Date:** 2026-02-28
**Severity:** P0 — 5 of 6 API ingestion Lambdas down for ~12 hours
**Duration:** ~6:00 AM PT Feb 28 → ~10:00 AM PT Feb 28 (detected + fixed)
**Data lost:** None (gap-fill self-healed all sources once Lambdas restored)
**Author:** Claude + Matthew

---

## What happened

On Feb 27, a large engineering hardening session restructured the Lambda deployment model: parameterizing hardcoded values, adding DLQ coverage, standardizing environment variables, and splitting monolithic components. Deploy scripts were generated and executed.

On the morning of Feb 28, all 5 API-based ingestion Lambdas failed at their scheduled invocation times (6:00–7:00 AM PT). The freshness checker fired at 8:15 AM PT and emailed an alert, but the alert included a false positive (Hevy) that diluted the signal.

## Root causes

### 1. Handler/filename mismatch (4 Lambdas: strava, withings, habitify, eightsleep)

The hardening deploy standardized zip contents to `lambda_function.py`, but 4 Lambdas had handlers pointing to `X_lambda.lambda_handler` (e.g., `strava_lambda.lambda_handler`). The deploy scripts updated the code but not the handler configuration, or updated one without the other.

**Why this wasn't caught:** The deploy scripts tested that the `update-function-code` call succeeded (HTTP 200), but didn't invoke the Lambda to verify it could actually start. A 200 from `update-function-code` only means "the zip was uploaded" — it says nothing about whether the code can import.

### 2. Dependency stripping (1 Lambda: garmin)

The Garmin Lambda requires `garth` and `garminconnect` as bundled dependencies (they're not in the Lambda runtime). The hardening deploy rebuilt the zip from the `.py` source file alone, without including the dependency tree.

**Why this wasn't caught:** Same as above — the deploy "succeeded" because the zip uploaded. The import error only surfaces at invocation time.

### 3. IAM permission gap (1 Lambda: garmin)

The gap-aware backfill feature (added in a prior session) uses `dynamodb:Query` to check which dates are missing. The Garmin IAM role had `PutItem` and `GetItem` but not `Query`. This worked before gap-fill was added because the old code only wrote, never queried.

**Why this wasn't caught:** The gap-fill code was added to the Lambda source but the IAM policy was written in a different session and never updated for the new operation.

### 4. Platform mismatch (1 Lambda: garmin, first fix attempt)

The first attempt to rebuild the Garmin zip used `pip3 install` on macOS, which downloaded ARM/macOS native `.so` files for `pydantic_core`. Lambda runs Amazon Linux x86_64, so the binary was incompatible.

**Why this happened:** The build script didn't specify `--platform manylinux2014_x86_64 --only-binary=:all:`.

### 5. OAuth token expiry (1 Lambda: withings)

With the Lambda unable to run for ~12 hours, the Withings OAuth refresh token (which is single-use and rotating) expired. Even after fixing the handler, the token was dead and required browser re-authorization.

**Why this happened:** Cascading failure — the handler mismatch prevented the daily run that would have kept the token alive.

---

## What went right

1. **Gap-fill self-healed data.** LOOKBACK_DAYS=7 meant that once Lambdas were restored, all missing days were automatically backfilled. Zero permanent data loss.
2. **Freshness checker alerted.** The 8:15 AM email flagged stale sources, which is how Matthew noticed the issue.
3. **Handler fix was trivial.** `update-function-configuration --handler lambda_function.lambda_handler` was a one-command fix per Lambda.

## What went wrong

1. **No post-deploy invocation test.** Deploy scripts verified `update-function-code` returned 200 but never called `lambda invoke` to confirm the function actually works.
2. **No handler consistency check.** The deploy scripts didn't verify that the handler config matches the filename inside the zip.
3. **Garmin deps not version-pinned or cached.** No record of which dependency versions were in the last working zip, and no cached copy of a known-good zip.
4. **Cross-session IAM drift.** Lambda code changes (gap-fill) were made in one session, but the IAM policy lived in a different session's scope and wasn't updated.
5. **No pre-deploy backup verification.** Backup zips were created but the rollback path wasn't tested.
6. **Hevy false positive in alert.** The freshness checker flagged Hevy (a one-time backfill, not an active source), which diluted alert credibility.

---

## Process improvements

### A. Mandatory post-deploy smoke test (CRITICAL)

Every deploy script MUST end with a test invocation and log check:

```bash
# After every deploy:
echo "Smoke testing..."
aws lambda invoke \
    --function-name "$FUNCTION_NAME" \
    --region us-west-2 \
    --log-type Tail \
    /tmp/${FUNCTION_NAME}_test.json \
    --query 'LogResult' \
    --output text | base64 -d | tail -20

# Check for errors
if grep -q "ERROR\|Error\|ImportModule" /tmp/${FUNCTION_NAME}_test.json 2>/dev/null; then
    echo "❌ SMOKE TEST FAILED — rolling back"
    aws lambda update-function-code \
        --function-name "$FUNCTION_NAME" \
        --zip-file "fileb://${BACKUP_ZIP}" \
        --region us-west-2
    exit 1
fi
echo "✅ Smoke test passed"
```

### B. Handler consistency guard

Deploy scripts should verify handler matches zip contents:

```bash
HANDLER=$(aws lambda get-function-configuration \
    --function-name "$FUNCTION_NAME" \
    --query 'Handler' --output text)
EXPECTED_FILE="${HANDLER%%.*}.py"
if ! zipinfo -1 "$ZIP_FILE" | grep -q "$EXPECTED_FILE"; then
    echo "❌ Handler expects $EXPECTED_FILE but zip doesn't contain it!"
    echo "   Fix: update handler or rename file in zip"
    exit 1
fi
```

### C. Cross-platform build enforcement

Any Lambda with native dependencies (garmin, anything with C extensions) MUST use:

```bash
pip3 install <packages> -t "$BUILD_DIR" \
    --platform manylinux2014_x86_64 \
    --only-binary=:all: \
    --python-version 3.12 \
    --implementation cp
```

Add a comment in the deploy script header: `# NATIVE DEPS: requires --platform manylinux2014_x86_64`

### D. IAM policy co-location

When adding a new DynamoDB operation to Lambda code (e.g., adding `Query` for gap-fill), the IAM policy update MUST happen in the same session. Add a checklist comment in the code:

```python
# IAM REQUIRED: dynamodb:Query on life-platform table
# If you add new AWS API calls here, update the IAM policy too.
```

### E. Deploy manifest

Maintain a `deploy/MANIFEST.md` that records for each Lambda:

| Lambda | Handler | Deps | IAM Role | Last Deploy | Deploy Script |
|--------|---------|------|----------|-------------|---------------|
| strava-data-ingestion | lambda_function.lambda_handler | none (stdlib only) | lambda-strava-role | 2026-02-28 | deploy/fix_garmin_deps.sh |
| garmin-data-ingestion | garmin_lambda.lambda_handler | garth, garminconnect (linux x86_64) | lambda-garmin-ingestion-role | 2026-02-28 | deploy/fix_garmin_deps.sh |
| ... | ... | ... | ... | ... | ... |

### F. Freshness checker accuracy

Only monitor actively-ingesting sources. Remove one-time backfill sources (Hevy, Chronicling). Add per-source stale thresholds (Strava can be 72h since rest days have no activities; Withings 96h since you don't weigh daily).

### G. Pre-deploy checklist (for future hardening-scale changes)

Before any session that touches 3+ Lambdas:

- [ ] Export current handler configs: `aws lambda list-functions --query "Functions[].{N:FunctionName,H:Handler}"`
- [ ] Download current deployed zips as backups
- [ ] List IAM permissions per role
- [ ] After deploy: invoke each Lambda and grep logs for ERROR
- [ ] Verify gap-fill runs cleanly (proves both read + write permissions work)
- [ ] Check OAuth tokens still valid (Withings, Garmin, Eight Sleep)

---

## Item 3: Apple Health "request entity too large"

The Health Auto Export app sends data to API Gateway (`health-auto-export-api`), which has a **10MB payload limit**. The TEXT export format likely exceeds this when it includes multiple days or high-frequency metrics (heart rate samples every few seconds, for example).

**Fix options:**
1. **In the app:** Change export frequency to more often (hourly instead of daily) so each payload is smaller. Or reduce which metrics are exported (skip high-frequency ones like heart rate samples).
2. **In AWS:** Switch from API Gateway to a Lambda Function URL (6MB limit — worse) or use S3 pre-signed URL uploads (unlimited size). The cleanest fix is reducing payload size in the app settings.

**Recommended:** In Health Auto Export, go to Settings and check if you're exporting "All Health Data" — switch to only the metrics we actually use (steps, active calories, resting HR, HRV, sleep analysis, walking speed, blood pressure, CGM glucose, mindful minutes). This should dramatically reduce payload size.

---

## Summary of actions

| # | Action | Status |
|---|--------|--------|
| 1 | Handler fix (strava, withings, habitify, eightsleep) | ✅ Done |
| 2 | Garmin deps rebuild (linux x86_64) | ✅ Done |
| 3 | Garmin IAM policy (add Query) | ✅ Done |
| 4 | Withings OAuth re-auth | ✅ Done |
| 5 | Remove Hevy from freshness checker | ✅ Patched, needs deploy |
| 6 | Add garmin+habitify to freshness checker | ✅ Patched, needs deploy |
| 7 | Apple Health payload size | 📋 Adjust app export settings |
| 8 | Deploy manifest | 📋 Create deploy/MANIFEST.md |
| 9 | Smoke test template | 📋 Add to all deploy scripts |
