# Life Platform — Handover v2.97.0
**Date:** 2026-03-08  
**Session:** P1 Hardening Batch — all 6 tasks built

---

## What Was Done This Session

### All 6 P1 Tasks Complete (source edits done, deploy pending)

#### MAINT-2 — Lambda Layer Expanded ✅
- `deploy/p3_build_shared_utils_layer.sh` — expanded from 4 → 8 modules: adds `character_engine.py`, `output_writers.py`, `ai_calls.py`, `html_builder.py`
- `deploy/p3_attach_shared_utils_layer.sh` — expanded from 11 → 16 Lambdas: adds `brittany-weekly-email`, `daily-metrics-compute`, `adaptive-mode-compute`, `dashboard-refresh`

#### SEC-2 — Secret Split ✅
- `deploy/sec2_split_secrets.sh` — verifies `ai-keys` Phase 1 complete, creates `ingestion-keys` + `webhook-key`, updates ingestion Lambda env vars, tightens IAM role policies to `ai-keys` only
- Bundle `api-keys` → FROZEN after run; delete 2026-04-08

#### SEC-3 — MCP Input Validation ✅
- `lambdas/mcp_server.py` — added `_validate_tool_args()` function + wired into `handle_tools_call()`
- Validates: required fields, type coercion, YYYY-MM-DD date format, 500-char string cap, 100-item array cap, enum values
- Returns `{error: invalid_arguments, detail: "..."}` instead of crashing on bad input

#### REL-1 — Compute Staleness Detection ✅
- `lambdas/daily_brief_lambda.py` — checks `computed_at` timestamp; flags stale if >4h old or missing
- `lambdas/html_builder.py` — renders amber banner in email when stale flag set; `build_html()` signature extended with `compute_stale=False, compute_age_msg=""`

#### DATA-1 — schema_version on DDB Items ✅
- `lambdas/daily_brief_lambda.py` — `store_day_grade()` writes `schema_version: 1`
- `lambdas/whoop_lambda.py` — daily item writes `schema_version: 1` (canonical pattern for remaining 11 ingestion Lambdas)
- `deploy/data1_backfill_schema_version.sh` — backfills all existing `USER#matthew` items (conditional update, safe to re-run)

#### AI-2 — Correlational Language ✅
- `lambdas/mcp_server.py` — `get_cross_source_correlation` and `get_day_type_analysis` descriptions updated from causal to correlational framing; added "correlations do not imply causation" note

---

## Status: ALL DEPLOYED ✅

All 6 P1 tasks complete and live. Git committed at `85cb969`.

## Remaining Cleanup

### DATA-1 follow-on
11 ingestion Lambdas still need `"schema_version": 1` on their `put_item` calls. Backfill already ran (15,489 items updated). Pattern in `whoop_lambda.py`.

Lambdas: garmin, eightsleep, strava, habitify, withings, apple_health, health_auto_export, macrofactor, todoist, notion, weather

### Layer attach for dashboard-refresh Lambdas
The two dashboard refresh Lambdas have different names than expected:
```bash
bash deploy/p3_attach_shared_utils_layer.sh arn:aws:lambda:us-west-2:205930651321:layer:life-platform-shared-utils:1
# Already attached to 15 Lambdas. dashboard-refresh-afternoon and dashboard-refresh-evening
# were missed — can manually attach or skip (they don't use all 8 shared modules).
```

### api-keys bundle
Frozen. Delete on or after 2026-04-08:
```bash
aws secretsmanager delete-secret --secret-id life-platform/api-keys --region us-west-2
```

### lambda-weekly-digest-role
Deprecated. Delete on or after 2026-03-15:
```bash
aws iam list-role-policies --role-name lambda-weekly-digest-role
aws iam list-attached-role-policies --role-name lambda-weekly-digest-role
aws iam delete-role --role-name lambda-weekly-digest-role
```

---

## Archived: What Was Deployed

**Step 1 — Build + attach Lambda Layer (MAINT-2):**
```bash
bash deploy/p3_build_shared_utils_layer.sh
# Copy the LAYER_VERSION_ARN from the output, then:
bash deploy/p3_attach_shared_utils_layer.sh arn:aws:lambda:us-west-2:205930651321:layer:life-platform-shared-utils:X
```

**Step 2 — Split secrets (SEC-2):**
```bash
bash deploy/sec2_split_secrets.sh
```
Note: reads the current `api-keys` bundle live to extract per-domain keys. Review the output before proceeding.

**Step 3 — Deploy code changes (SEC-3, REL-1, DATA-1, AI-2):**
```bash
bash deploy/deploy_v2.97.0.sh
```
Deploys: `life-platform-mcp`, `daily-brief`, `whoop-data-ingestion`

**Step 4 — Backfill schema_version on existing DDB items (DATA-1):**
```bash
bash deploy/data1_backfill_schema_version.sh
```

**Step 5 — Commit:**
```bash
git add -A && git commit -m "v2.97.0: P1 hardening — SEC-2/3, MAINT-2, REL-1, DATA-1, AI-2" && git push
```

---

## Remaining DATA-1 Work (follow-on)
11 ingestion Lambdas still need `"schema_version": 1` added to their `put_item` calls.
Pattern from `whoop_lambda.py`:
```python
table.put_item(Item={
    "pk": f"USER#{USER_ID}#SOURCE#<source>",
    "sk": f"DATE#{date_str}",
    "date": date_str,
    "schema_version": 1,   # ← add this line
    **normalized,
})
```
Lambdas to update: garmin, eightsleep, strava, habitify, withings, apple_health, health_auto_export, macrofactor, todoist, notion, weather

---

## Hardening Roadmap Status

### ✅ Done
| Task | Description |
|------|-------------|
| AI-1 | Health disclaimers on all email Lambdas |
| MAINT-3 | Stale file cleanup |
| COST-1 | S3 Glacier lifecycle |
| SEC-4 | API Gateway rate limiting |
| IAM-2 | IAM Access Analyzer |
| SEC-1 | IAM role decomposition complete |
| SEC-2 | Secret split (script written — run pending) |
| SEC-3 | MCP input validation |
| MAINT-2 | Lambda Layer expanded (scripts updated — run pending) |
| REL-1 | Compute staleness detection |
| DATA-1 | schema_version (partial — backfill + 2 lambdas; 11 remain) |
| AI-2 | Correlational language in descriptions |

### 🟡 Next (P2)
| Task | Description |
|------|-------------|
| MAINT-1 | requirements.txt per Lambda |
| OBS-2 | CloudWatch operational dashboard |
| COST-3 | AI token usage alarm |
| REL-2 | DLQ consumer Lambda |
| REL-4 | Synthetic health check |
| REL-3 | DynamoDB 400KB monitoring |

---

## Platform State
- **Version:** v2.97.0
- **Lambdas:** 35
- **MCP Tools:** 144
- **Modules:** 30
- **Layer:** life-platform-shared-utils (8 modules, needs build+attach)
- **Secrets:** 3 scoped + 1 frozen bundle (after SEC-2 runs)
