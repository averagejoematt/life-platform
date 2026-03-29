# Handover — 2026-03-07 (v2.84.2): Secret Sweep + QA Infrastructure Health Check

## Platform State
- **Version:** v2.84.2
- **MCP tools:** 135 | **Lambdas:** 32 | **Modules:** 27

---

## Session Work

### 1. Root Cause: HAE + Notion Silent Failures — FIXED

**Symptom:** Hydration blank on daily brief. Water data missing from DynamoDB for Mar 6.

**Discovery path:**
- HAE app showed "sync successful Mar 7 at 10:35 AM" but DDB had no apple_health records for Mar 6 or Mar 7
- Webhook CloudWatch log: `ERROR: Could not validate API key: You can't perform this operation on the secret because it was marked for deletion.`
- `health-auto-export-webhook` env var: `SECRET_NAME=life-platform/health-auto-export` — this secret was deleted during v2.75.0 consolidation
- Every HAE sync since v2.75.0 silently rejected at auth layer before writing anything

**Full Lambda secret audit results:**

| Lambda | SECRET_NAME was | Status |
|--------|-----------------|--------|
| `health-auto-export-webhook` | `life-platform/health-auto-export` | ❌ Fixed → `api-keys` |
| `notion-journal-ingestion` | `life-platform/notion` | ❌ Fixed → `api-keys` |
| `whoop-data-ingestion` | `life-platform/whoop` | ✅ Secret still exists |
| `strava-data-ingestion` | `life-platform/strava` | ✅ Secret still exists |
| `garmin-data-ingestion` | `life-platform/garmin` | ✅ Secret still exists |
| `eightsleep-data-ingestion` | `life-platform/eightsleep` | ✅ Secret still exists |
| `withings-data-ingestion` | `life-platform/withings` | ✅ Secret still exists |
| `todoist-data-ingestion` | `life-platform/todoist` | ❌ Fixed earlier this session |

Existing secrets (live): `life-platform/whoop`, `life-platform/withings`, `life-platform/strava`, `life-platform/mcp-api-key`, `life-platform/eightsleep`, `life-platform/garmin`, `life-platform/api-keys`

**Fix applied:** `aws lambda update-function-configuration` for HAE + Notion to point to `life-platform/api-keys`.

**Next action for Matthew:** Trigger manual HAE sync from the app → Mar 6 + Mar 7 water data should populate → re-invoke daily-brief to get hydration showing.

---

### 2. New: `tests/validate_lambda_secrets.py` — DONE

Reusable sweep script. Checks every Lambda's `SECRET_NAME` against live Secrets Manager inventory.

```bash
python3 tests/validate_lambda_secrets.py          # audit only
python3 tests/validate_lambda_secrets.py --fix    # auto-fix stale → life-platform/api-keys
```

**When to run:** After any secret rename, delete, or consolidation. Should have been run during v2.75.0 — would have caught this immediately.

---

### 3. QA Smoke: `check_lambda_secrets()` — DONE

New CHECK 5 added to `lambdas/qa_smoke_lambda.py`. Runs daily at 10:30 AM PT alongside other checks. Sweeps all Lambda functions and flags any `SECRET_NAME` not found in live Secrets Manager inventory.

IAM inline policy `qa-smoke-infra-read` added to `lambda-weekly-digest-role`:
- `lambda:ListFunctions` — to sweep all functions
- `secretsmanager:ListSecrets` — to build live inventory

**Deploy:** `bash deploy/deploy_lambda.sh life-platform-qa-smoke lambdas/qa_smoke_lambda.py`

---

### 4. Daily Brief Multi-Module Deploy Issue — IDENTIFIED (not fully fixed)

`deploy_lambda.sh` only bundles the single source file passed to it. `daily-brief` imports three local modules (`html_builder`, `ai_calls`, `output_writers`) plus `board_loader`. Every deploy via `deploy_lambda.sh` will silently drop these unless manually bundled.

**Immediate workaround used:**
```bash
WORK_DIR=$(mktemp -d)
cp lambdas/daily_brief_lambda.py "$WORK_DIR/lambda_function.py"
cp lambdas/html_builder.py "$WORK_DIR/html_builder.py"
cp lambdas/ai_calls.py "$WORK_DIR/ai_calls.py"
cp lambdas/output_writers.py "$WORK_DIR/output_writers.py"
cp lambdas/board_loader.py "$WORK_DIR/board_loader.py"
(cd "$WORK_DIR" && zip -q deploy.zip lambda_function.py html_builder.py ai_calls.py output_writers.py board_loader.py)
aws lambda update-function-code --function-name daily-brief --zip-file "fileb://$WORK_DIR/deploy.zip" --region us-west-2 --no-cli-pager
rm -rf "$WORK_DIR"
```

**Pending fix:** `deploy_lambda.sh` needs an `--extra-files` option or a per-Lambda manifest so multi-module Lambdas bundle correctly. This is a latent redeploy risk every time daily-brief is touched.

---

### 5. QA Improvements — DONE

- **Green suppression:** Email not sent when all checks pass
- **Warnings-only subject:** Fixed from `✅ All clear` to `⚠️ N warning(s)` 
- **Deploy:** `bash deploy/deploy_lambda.sh life-platform-qa-smoke lambdas/qa_smoke_lambda.py`

---

## Post-Mortem Summary

**What failed:** v2.75.0 consolidated 12 per-service secrets into `life-platform/api-keys` but didn't sweep Lambda env vars for stale references. Two Lambdas (`health-auto-export-webhook`, `notion-journal-ingestion`) were missed, silently failing at auth since then.

**Why it wasn't caught:** QA smoke only validated data outputs (DDB freshness, S3 files, score sanity) — not infrastructure state. HAE reported "sync successful" from the app side; Lambda was rejecting silently with no alarm.

**What now prevents recurrence:**
1. `tests/validate_lambda_secrets.py` — run at any secret migration
2. `check_lambda_secrets()` in QA smoke — catches within 24h of any future break

---

## Pending Items

- **[CRITICAL - TODAY]** Trigger HAE manual sync → confirm Mar 6+7 water in DDB → re-invoke daily-brief
- **[SOON]** Fix `deploy_lambda.sh` for multi-module Lambdas (--extra-files or manifest approach)
- **[ASSESS]** Extent of Apple Health data gap since v2.75.0 — steps, gait, glucose also affected; may want to backfill if HAE exports historical data
- **[ASSESS]** Notion journal gap since v2.75.0 — journal entries may be missing; journal ingestion Lambda should be manually triggered to backfill
- **[NEXT]** Google Calendar integration — Board rank #2
- **[PENDING]** Brittany weekly accountability email — prerequisite: reward seeding
- **[PENDING]** Reward seeding → Character Sheet Phase 4
- **[PENDING]** `deploy_todoist_integration.sh` bundling fix (caused today's html_builder outage)

---

## Files Changed (v2.84.1 + v2.84.2)
- `lambdas/qa_smoke_lambda.py` — green suppression, warnings subject fix, `check_lambda_secrets()` + IAM policy
- `tests/validate_lambda_secrets.py` — new sweep utility
- `docs/CHANGELOG.md` — v2.84.1 + v2.84.2 entries
- `docs/PROJECT_PLAN.md` — version bumped to v2.84.2
- Lambda env vars updated (no code changes): `health-auto-export-webhook`, `notion-journal-ingestion`
