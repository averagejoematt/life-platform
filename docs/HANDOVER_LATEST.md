# Life Platform — Handover v3.2.4
Date: 2026-03-09
Session: PROD-2 Phase 1 — Hardcoded default removal

---

## What Was Done This Session

### OBS-1 / AI-3 Audit (no code changes needed)
Checked `weekly_plate_lambda.py` and `monthly_digest_lambda.py` — both already had OBS-1
(`platform_logger`) and AI-3 (`ai_output_validator`) wired. The previous handover saying
"only daily-brief wired" was stale. All 7 email Lambdas are fully wired for both.

**OBS-1 remaining gap:** 34 ingestion Lambdas (no AI calls, so AI-3 not applicable).

### PROD-2 Phase 1 — Completed ✅
Ran `deploy/prod2_phase1_fix.py` — 96 replacements across 40 files:

1. `os.environ.get("USER_ID", "matthew")` → `os.environ["USER_ID"]` (all Lambdas + mcp/config.py)
2. `os.environ.get("S3_BUCKET", "matthew-life-platform")` → `os.environ["S3_BUCKET"]`
3. `os.environ.get("EMAIL_RECIPIENT/SENDER", "awsdev@...")` → `os.environ[...]`
4. `monthly_digest_lambda.py` bare string assignments → `os.environ[...]`
5. `weekly_digest_lambda.py` — injected `USER_ID = os.environ["USER_ID"]` (was missing entirely);
   fixed 4 hardcoded `"USER#matthew"` DDB key patterns → `f"USER#{USER_ID}"`
6. `insight_writer.init(table, "matthew")` → `insight_writer.init(table, USER_ID)` in 4 Lambdas

All 40 Lambdas redeployed 40/40 ✅ via `deploy/prod2_phase1_deploy_all.sh`.

---

## PROD-2 Status

| Category | Status | Notes |
|----------|--------|-------|
| 1. USER_ID / S3_BUCKET / email defaults | ✅ Done | This session |
| 2. S3 bucket name | ✅ Closed | Cosmetic, no action needed |
| 3. SES email addresses | ✅ Done | This session (env vars already existed) |
| 4. S3 path prefixing | 🔴 Pending | Biggest change — needs migration decision |
| 5. DDB keys | ✅ Done | Was already parameterized |
| 6. Board config | ✅ Closed | Shared config is correct for this use case |
| 7. CloudFront/web | 🔴 Deferred | Low priority for single-user |
| 8. Comments | 🔴 Low priority | Bulk find-and-replace, no urgency |

**PROD-2 Phase 2 (S3 path prefixing) decision needed:**
- Current: `dashboard/data.json`, `config/board_of_directors.json`, `raw/{source}/...`
- Target:  `dashboard/{user_id}/data.json`, `config/{user_id}/...`, `raw/{user_id}/{source}/...`
- Question: Migrate Matthew's existing S3 data to new paths, or keep old paths for Matthew
  and only use new user-prefixed paths for future users?
- Recommendation: Keep old paths for Matthew (migration risk not worth it for single user),
  new paths for new users. Implement conditional: if USER_ID == "matthew", use legacy paths;
  else use prefixed paths. But this adds complexity — simplest is full migration + S3 copy.

---

## Hardening Status

| Epic | Status |
|------|--------|
| SEC-1,2,3,5 | ✅ |
| IAM-1,2 | ✅ |
| REL-1,2,3,4 | ✅ |
| OBS-1 | ⚠️ Email Lambdas ✅, ingestion Lambdas pending |
| OBS-2,3 | ✅ |
| COST-1,2,3 | ✅ |
| MAINT-1,2,3,4 | ✅ |
| DATA-1,2,3 | ✅ |
| AI-1,2,3,4 | ✅ (AI-3 email Lambdas fully wired) |
| PROD-1 | ⚠️ Scaffolding done, CDK import sessions 2-6 remain |
| PROD-2 | ⚠️ Phase 1 done ✅, Phase 2 (S3 paths) pending |
| SIMP-1 | 🔴 Revisit ~2026-04-08 (need 30d MCP metric data) |
| SIMP-2 | ✅ Closed |

Overall: ~31/33 complete (~94%)

---

## Next Steps (Priority Order)

| Priority | Item | Effort |
|----------|------|--------|
| 1 | OBS-1 rollout to 34 ingestion Lambdas | 1 session |
| 2 | PROD-2 Phase 2: S3 path prefixing | 4-6 hr — needs migration decision first |
| 3 | Brittany weekly email | 2 sessions — fully unblocked |
| 4 | Prompt Intelligence fixes (P1-P5) | 2-3 sessions |
| 5 | Google Calendar integration (#2) | 2 sessions |
| 6 | PROD-1 CDK sessions 2-6 | 5 sessions |
| 7 | SIMP-1 | ~2026-04-08 |

### Prompt Intelligence Backlog (P1-P5)
- P1: Weekly Plate memory (store history, anti-repeat) — already done per weekly_plate_lambda.py
- P2: Journey context block (`_build_journey_context()` for all AI calls) — 2-3 hr
- P3: Training coach walk/early fitness rewrite — 1-2 hr
- P4: Habit→outcome connector (pre-process correlations before AI calls) — 3-4 hr
- P5: TDEE/deficit context in nutrition prompts — 1-2 hr

---

## Key Files Changed This Session

- `deploy/prod2_phase1_fix.py` — the fix script (keep for future audits)
- `deploy/prod2_phase1_deploy_all.sh` — bulk deploy script (reusable)
- All 39 Lambda `.py` files — `os.environ.get()` defaults removed
- `mcp/config.py` — same
- `docs/CHANGELOG.md` — v3.2.4 added

---

## Platform Stats
- Version: v3.2.4
- Lambdas: 40 | MCP Tools: 144 | Modules: 30
- Hardening: ~31/33 (~94%)
