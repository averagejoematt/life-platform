# Life Platform — Handover v3.0.0
_Generated: 2026-03-08_

## Platform State
- **Version:** v3.0.0
- **Lambdas:** 37 (35 prior + `life-platform-data-reconciliation` + `life-platform-pip-audit`)
- **MCP Tools:** 144 | **Modules:** 30 | **Data Sources:** 19
- **AWS:** Account 205930651321, us-west-2, DynamoDB `life-platform`, S3 `matthew-life-platform`

---

## This Session: P3 Hardening — ALL 6 TASKS COMPLETE ✅

### Files created / modified
| File | Status | Description |
|------|--------|-------------|
| `lambdas/platform_logger.py` | ✅ New | OBS-1: Structured JSON logging module |
| `lambdas/ingestion_validator.py` | ✅ New | DATA-2: Per-source ingestion validation |
| `lambdas/ai_output_validator.py` | ✅ New | AI-3: AI output safety validation |
| `lambdas/data_reconciliation_lambda.py` | ✅ New | DATA-3: Weekly coverage reconciliation |
| `lambdas/pip_audit_lambda.py` | ✅ New | SEC-5: Monthly dependency vulnerability scan |
| `lambdas/strava_lambda.py` | ✅ Modified | REL-3: replaced inline size-check with `safe_put_item` |
| `lambdas/macrofactor_lambda.py` | ✅ Modified | REL-3: replaced inline size-check with `safe_put_item` |
| `deploy/deploy_p3_lambdas.sh` | ✅ New | Builds + deploys all 4 affected Lambdas |
| `deploy/setup_p3_schedules.sh` | ✅ New | Creates EventBridge rules for 2 new Lambdas |

---

## IMMEDIATE NEXT STEPS (in order)

### 1. Deploy P3 Lambdas (run these in terminal)
```bash
cd ~/Documents/Claude/life-platform
bash deploy/deploy_p3_lambdas.sh
```
This deploys: `life-platform-data-reconciliation`, `life-platform-pip-audit`, and redeploys strava + macrofactor with REL-3 fix.

### 2. Set up EventBridge schedules
```bash
bash deploy/setup_p3_schedules.sh
```

### 3. Upload requirements files to S3 (needed by pip-audit Lambda)
```bash
aws s3 sync lambdas/requirements/ s3://matthew-life-platform/config/requirements/ --region us-west-2
```

### 4. Test new Lambdas manually
```bash
# Data reconciliation
aws lambda invoke --function-name life-platform-data-reconciliation \
  --payload '{}' /tmp/recon_out.json --region us-west-2 && cat /tmp/recon_out.json

# pip-audit (force flag bypasses first-Monday guard)
aws lambda invoke --function-name life-platform-pip-audit \
  --payload '{"force": true}' /tmp/audit_out.json --region us-west-2 && cat /tmp/audit_out.json
```

### 5. Git commit
```bash
cd ~/Documents/Claude/life-platform
git add -A && git commit -m "v3.0.0: P3 hardening — OBS-1, DATA-2, AI-3, DATA-3, SEC-5, REL-3 complete" && git push
```

---

## Pending (wiring not yet done — P3 created the modules, these wire them in)
These are optional follow-on tasks — platform runs fine without them, they just improve signal quality:

| Task | Effort | Notes |
|------|--------|-------|
| Migrate existing Lambdas to `platform_logger` | M | Start with `daily_brief_lambda.py` + `whoop_lambda.py` as pilot |
| Wire `ingestion_validator` into ingestion Lambdas | M | Start with `whoop_lambda.py` as pilot — call `validate_and_write()` |
| Wire `ai_output_validator` into `ai_calls.py` | S | Add to `call_board_of_directors()` + `call_tldr_and_guidance()` |

---

## Next Feature Work (post-P3)
Board top-ranked unbuilt features:
1. **Brittany weekly email** — accountability partner email (post reward seeding)
2. **Character Sheet Phase 4** — user-defined rewards, protocol recs, Weekly Digest integration
3. **Light exposure tracking** (~2hr) — Habitify habit + MCP correlation tool
4. **Grip strength tracking** (~2hr) — monthly Notion log, $15 dynamometer
5. **Google Calendar** (6-8hr) — demand-side cognitive load data
6. **Monarch Money** (4-6hr) — financial stress pillar

---

## Hardening Status (all P1/P2/P3 complete)

| Task | Status |
|------|--------|
| AI-1: Health disclaimers | ✅ P1 (prior session) |
| MAINT-1: requirements.txt | ✅ P2 |
| DATA-1: schema_version | ✅ P2 |
| MAINT-2: Lambda Layer | ✅ P2 |
| OBS-2: CW dashboard | ✅ P2 |
| REL-2: DLQ consumer | ✅ P2 |
| COST-3: Token alarms | ✅ P2 |
| REL-4: Synthetic canary | ✅ P2 |
| REL-3: DDB size monitoring | ✅ P2 (module) + P3 (wired) |
| OBS-1: Structured logging | ✅ P3 (module created) |
| DATA-2: Ingestion validation | ✅ P3 (module created) |
| AI-3: AI output validation | ✅ P3 (module created) |
| DATA-3: Weekly reconciliation | ✅ P3 (Lambda created) |
| SEC-5: pip-audit | ✅ P3 (Lambda created) |

Remaining hardening items (P3 deferred / lower priority):
OBS-3, COST-1, COST-2, SEC-1, SEC-2, SEC-3, SEC-4, IAM-1, IAM-2, REL-1, MAINT-3, MAINT-4, AI-2, AI-4, SIMP-1, SIMP-2

---

## Key Notes
- `deploy_p3_lambdas.sh` builds zips fresh each run — safe to re-run
- pip-audit Lambda fires every Monday but self-guards to first-Monday-of-month (day ≤ 7); bypass with `{"force": true}`
- data-reconciliation fires Sunday 11:30 PM PT (Monday 07:30 UTC), after weekly digest completes
- Both new Lambdas send email via SES — ensure `EMAIL_RECIPIENT` env var is set after Lambda creation
