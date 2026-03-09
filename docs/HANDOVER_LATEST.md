# Life Platform — Handover v3.2.6
Date: 2026-03-09
Session: PROD-2 Phase 2 — S3 path prefixing (raw/ + config/)

---

## What Was Done This Session

### OBS-1 Resume (carried over from previous session)
- `bash deploy/deploy_obs1_resume.sh` — 9/9 remaining live Lambdas deployed ✅
- OBS-1 complete for all existing infrastructure (3 un-deployed Lambdas pre-patched)

### PROD-2 Phase 2: S3 path prefixing
**Scope:** raw/ and config/ paths only. dashboard/buddy excluded (no CloudFront risk, zero multi-user value now).

**What changed:**
- `deploy/patch_prod2_phase2.py` — patched 13 files (8 ingestion Lambdas + tools_cgm + board_loader + character_engine + tools_board + tools_character)
- `deploy/migrate_s3_prod2_phase2.sh` — copied 16,022 raw/ objects → raw/matthew/, 3 config files → config/matthew/
- `deploy/deploy_prod2_phase2.sh` — deployed 10 Lambdas (8 ingestion + character-sheet-compute + life-platform-mcp)

**All raw/ writes now:** `raw/{USER_ID}/source/...`
**All config/ reads now:** `config/{USER_ID}/file.json`
**Old paths preserved** — safe to delete after 7+ days of verified operation

**⚠️ Manual follow-up still pending (2 items):**
1. SES receipt rule: update S3 prefix from `raw/inbound_email/` → `raw/matthew/inbound_email/`
2. Apple Health S3 event notification: update trigger prefix from `imports/apple_health/` (unchanged) — actually the apple-health Lambda trigger hasn't changed; but `insight-email-parser` S3 trigger needs updating from `raw/inbound_email/` → `raw/matthew/inbound_email/`

---

## Hardening Status

| Epic | Status |
|------|--------|
| SEC-1,2,3,5 | ✅ |
| IAM-1,2 | ✅ |
| REL-1,2,3,4 | ✅ |
| OBS-1 | ✅ All live Lambdas |
| OBS-2,3 | ✅ |
| COST-1,2,3 | ✅ |
| MAINT-1,2,3,4 | ✅ |
| DATA-1,2,3 | ✅ |
| AI-1,2,3,4 | ✅ |
| PROD-1 | ⚠️ Scaffolding done, CDK sessions 2-6 remain |
| PROD-2 | ✅ Phase 1 (env var defaults) + Phase 2 (S3 paths) done. dashboard/buddy deferred. |
| SIMP-1 | 🔴 Revisit ~2026-04-08 |

Overall: ~97-98% hardening complete. PROD-1 CDK is the only substantial open item.

---

## Next Steps (Priority Order)

| Priority | Item | Notes |
|----------|------|-------|
| 1 | **PROD-1 CDK IngestionStack** | Write IngestionStack + run cdk synth. Import later. |
| 2 | **Brittany weekly email** | Fully unblocked |
| 3 | **PROD-2 manual follow-up** | SES + insight-email-parser S3 trigger prefix update |
| 4 | **Old S3 path cleanup** | After ~2026-03-16: delete raw/ (non-prefixed) + old config/*.json |
| 5 | **Prompt Intelligence fixes (P1-P5)** | 2-3 sessions |
| 6 | **Google Calendar integration** | 2 sessions |

---

## PROD-1 CDK — Where We Left Off

- `cdk/app.py` — 8-stack architecture defined, CoreStack wired, others commented out
- `cdk/stacks/core_stack.py` — DynamoDB, S3, SQS DLQ, SNS (ready to `cdk import`)
- `cdk/stacks/lambda_helpers.py` — `create_platform_lambda()` helper written
- **Next session:** write `cdk/stacks/ingestion_stack.py` (13 Lambdas + IAM + EventBridge + alarms), run `cdk synth`, review CloudFormation diff. Do NOT run `cdk import` in the same session.

## Key Files Changed This Session

- `deploy/patch_prod2_phase2.py`
- `deploy/migrate_s3_prod2_phase2.sh`
- `deploy/deploy_prod2_phase2.sh`
- `lambdas/health_auto_export_lambda.py` — 5 raw/ paths prefixed
- `lambdas/whoop_lambda.py` — 4 raw/ paths prefixed
- `lambdas/strava_lambda.py` — 1 raw/ path prefixed
- `lambdas/garmin_lambda.py` — 1 raw/ path prefixed
- `lambdas/macrofactor_lambda.py` — 1 raw/ path prefixed
- `lambdas/apple_health_lambda.py` — 1 raw/ path prefixed
- `lambdas/withings_lambda.py` — 1 raw/ path prefixed
- `lambdas/eightsleep_lambda.py` — 1 raw/ path prefixed
- `lambdas/board_loader.py` — user_id param added to load_board()
- `lambdas/character_engine.py` — user_id param added to load_character_config()
- `mcp/tools_cgm.py` — 3 raw/ read paths prefixed
- `mcp/tools_board.py` — BOARD_S3_KEY dynamic
- `mcp/tools_character.py` — S3_BUCKET + CS_CONFIG_KEY dynamic
