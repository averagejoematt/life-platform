# Life Platform — Session Handover
**Date:** 2026-03-08  
**Version:** v2.94.0  
**Session:** P3 Infrastructure Cleanup + Documentation Pass

---

## What Was Done This Session

### 1. KMS Key ID → INFRASTRUCTURE.md ✅
- **Key ID:** `444438d1-a5e0-43b8-9391-3cd2d70dde4d`
- **Key ARN:** `arn:aws:kms:us-west-2:205930651321:key/444438d1-a5e0-43b8-9391-3cd2d70dde4d`
- Added new **KMS section** to INFRASTRUCTURE.md with full details
- Also updated: Secrets Manager count (6→8 incl. ai-keys), CloudWatch alarms (35→44), EventBridge section → Scheduler section, version stamp

### 2. Stale SECRET_NAME Audit ✅
Audited all 35 Lambdas for `SECRET_NAME` env vars pointing to nonexistent secrets.

**Result:**
| Lambda | SECRET_NAME value | Status |
|--------|------------------|--------|
| `habitify-data-ingestion` | `life-platform/habitify` | ⚠️ Secret doesn't exist — harmless (Lambda uses `HABITIFY_SECRET_NAME` not `SECRET_NAME`) |
| `health-auto-export-webhook` | `life-platform/api-keys` | ✅ Exists |
| `monday-compass` | `life-platform/api-keys` | ✅ Exists |
| `notion-journal-ingestion` | `life-platform/api-keys` | ✅ Exists |
| `dropbox-poll` | `life-platform/api-keys` | ✅ Exists |
| `todoist-data-ingestion` | `life-platform/api-keys` | ✅ Exists |
| `whoop/eightsleep/garmin/withings/strava` | individual secrets | ✅ All exist |

**Script:** `deploy/p3_secret_name_audit_fix.sh` removes the stale `SECRET_NAME` from habitify.

**Run:** `./deploy/p3_secret_name_audit_fix.sh`

### 3. deploy_unified.sh v2.0 ✅
Rewrote `deploy/deploy_unified.sh` to cover all 35 current Lambdas. Old version only had ~22.
- Delegates to `deploy_lambda.sh` (auto-reads AWS handler config, no hardcoded zip names)
- Garmin special-cased to `fix_garmin_deps.sh` (needs garminconnect/garth bundle)
- All AI Lambdas list their extra modules explicitly (retry_utils, board_loader, etc.)
- `all` target deploys everything with 10s pauses between

### 4. Lambda Layer Scripts ✅ (scripts only — not run yet)

**Garmin deps layer:**
- `deploy/p3_build_garmin_layer.sh` — builds `life-platform-garmin-deps` layer (garminconnect + garth, ~15MB, linux/x86_64, Python 3.12)
- Eliminates the need to pip-install deps on every garmin deploy

**Shared utils layer:**
- `deploy/p3_build_shared_utils_layer.sh` — builds `life-platform-shared-utils` layer (retry_utils.py, board_loader.py, insight_writer.py, scoring_engine.py)
- `deploy/p3_attach_shared_utils_layer.sh <LAYER_ARN>` — attaches to all 11 consumer Lambdas (daily-brief, weekly-digest, monthly-digest, nutrition-review, chronicle, weekly-plate, monday-compass, anomaly-detector, character-sheet-compute, daily-insight-compute, hypothesis-engine)

**When to run:** When you want to simplify deploys. Run build → attach → redeploy each consumer without extra-files. Not urgent.

### 5. project_pillar_map.json Verified & Corrected ✅
- Queried DynamoDB `completions_by_project` field across all 2025+ Todoist records
- **Real project names in use:** `To Do`, `Inbox`, `Long Term`, `Re-Occuring`, `Watch and Listen`, `Growth & Relationships`
- Old config had generic placeholders (`Health & Body`, `Fitness`, etc.) — none of which match Matthew's actual Todoist
- Rewrote `config/project_pillar_map.json` v2.0.0 with verified mappings as primary entries
- `deploy/p3_deploy_pillar_map.sh` uploads to S3

**Run to make live:** `./deploy/p3_deploy_pillar_map.sh`  
(Monday Compass will immediately use correct project→pillar mappings)

---

## Scripts Run ✅

```bash
# ✅ DONE 2026-03-08
bash deploy/p3_secret_name_audit_fix.sh   # SECRET_NAME removed from habitify
bash deploy/p3_deploy_pillar_map.sh        # project_pillar_map.json uploaded to S3
```

## Scripts Remaining

```bash
# (Optional, when ready) Build + attach Lambda Layers
bash deploy/p3_build_garmin_layer.sh        # capture ARN in output
bash deploy/p3_build_shared_utils_layer.sh  # capture ARN in output
bash deploy/p3_attach_shared_utils_layer.sh <SHARED_UTILS_ARN>

# Git commit
git add -A && git commit -m "v2.94.0: P3 infra cleanup, KMS docs, SECRET_NAME audit, Lambda Layer scripts, pillar map fix" && git push
```

---

## Platform State

**Version:** v2.94.0 | **35 Lambdas** | **44 CloudWatch alarms**  
**MCP:** 144 tools, 30 modules  

**Open items (after today):**
1. Monday cleanup (2026-03-09): strip `anthropic_api_key` from bundle secret + delete `lambda-weekly-digest-role`
2. Verify Monday Compass first real run 8 AM PT Mon — check `/aws/lambda/monday-compass` CloudWatch
3. Lambda Layers (scripts ready, run when convenient)
4. **Next feature:** Google Calendar integration (North Star #2) or IC-4/5/8 (data gating ~mid-April)

---

## Key Reminders

- **deploy_unified.sh** is now the canonical deploy tool — use it
- **project_pillar_map.json** update needs `p3_deploy_pillar_map.sh` to go live on S3
- **Garmin** still deploys via `fix_garmin_deps.sh` until Garmin Layer is built + attached
- **SCHEMA.md** / **DATA_DICTIONARY.md** still at v2.64.0 — minor drift, not blocking
