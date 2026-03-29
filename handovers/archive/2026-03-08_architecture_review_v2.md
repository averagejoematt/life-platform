# Life Platform — Handover v3.1.4

_Generated: 2026-03-08 (end of architecture review cycle)_

## Platform State
- **Version:** v3.1.3 → v3.1.4 (review + docs only)
- **Lambdas:** 39 | **MCP Tools:** 144 | **Modules:** 30 | **Data Sources:** 19
- **CloudWatch Alarms:** ~47 | **Secrets:** 8 active (+1 pending deletion) | **KMS principals:** 37

---

## This Session: Architecture Review Cycle

Two full architecture reviews conducted back-to-back:
- **Review #1** (v2.91.0): Identified 35 hardening tasks across 10 epics
- Hardening sprint: 20 tasks fully completed, 3 built-not-wired, 1 partial
- **Review #2** (v3.1.3): Re-graded system, identified remaining gaps

### Grade Movement

| Dimension | Before | After |
|-----------|--------|-------|
| Security | C+ | **B+** |
| Reliability | B- | **B+** |
| Operability | C+ | **B-** |
| Data Quality | B | **B+** |
| AI Rigor | C+ | **B-** |
| Maintainability | C | **B-** |
| Production Readiness | D+ | **C** |

### Review artifacts
- `docs/REVIEW_2026-03-08.md` — Review #1 (full)
- `docs/REVIEW_2026-03-08_v2.md` — Review #2 (delta + re-grade)
- `docs/REVIEW_METHODOLOGY.md` — Repeatable review process
- `deploy/generate_review_bundle.sh` — AWS state snapshot script

---

## NEXT SESSION — 7 Immediate Items (Sonnet, ~6 hours)

> **Context for Sonnet:** Three critical safety modules were built during the hardening sprint but never integrated into their consuming Lambdas. Four core docs are stale. These 7 items close the gap before the Brittany email feature.

### Item 1: Wire `ai_output_validator.py` into `ai_calls.py` (1-2 hr)

**What:** The AI output validator (`lambdas/ai_output_validator.py`) validates coaching text for dangerous recommendations, empty output, and truncation. It's fully built but `ai_calls.py` doesn't call it.

**How:**
1. Read `lambdas/ai_output_validator.py` to understand the API (especially `validate_ai_output()`, `validate_daily_brief_outputs()`, `AIOutputType` enum)
2. Read `lambdas/ai_calls.py` to find the 4 AI call return points: `call_board_of_directors`, `call_training_nutrition_coach`, `call_journal_coach`, `call_tldr_and_guidance`
3. After each `call_anthropic()` return, add validation:
   ```python
   try:
       from ai_output_validator import validate_ai_output, AIOutputType
       result = validate_ai_output(text, AIOutputType.BOD_COACHING, health_context={"recovery_score": data.get("recovery_score")})
       if result.blocked:
           logger.warning(f"AI output blocked: {result.block_reason}")
           text = result.safe_fallback
       text = result.sanitized_text
   except ImportError:
       pass  # validator not bundled — proceed without validation
   ```
4. OR use the convenience wrapper `validate_daily_brief_outputs()` in the orchestrator (`daily_brief_lambda.py`) after all 4 calls return
5. Bundle `ai_output_validator.py` in the Lambda Layer (add to `deploy/p3_build_shared_utils_layer.sh` module list, rebuild + attach)
6. Deploy daily-brief and verify via CloudWatch logs that `[AI-3]` validation entries appear
7. Smoke test: invoke daily-brief with `{}` payload, check email renders correctly

**Acceptance criteria:** AI output passes through validator before email delivery. Blocked outputs use safe fallback. Warnings logged as structured JSON.

---

### Item 2: Wire `ingestion_validator.py` into 3 high-risk Lambdas (2 hr)

**What:** The ingestion validator (`lambdas/ingestion_validator.py`) has per-source validation schemas for all 19 sources. It's fully built but no Lambda calls it.

**How:**
1. Read `lambdas/ingestion_validator.py` — understand `validate_item(source, item, date_str)` API and `ValidationSeverity`
2. Start with 3 highest-volume Lambdas: `whoop_lambda.py`, `strava_lambda.py`, `macrofactor_lambda.py`
3. For each Lambda, find the `table.put_item()` or `safe_put_item()` call and add validation before it:
   ```python
   try:
       from ingestion_validator import validate_item
       vr = validate_item("whoop", item, date_str)
       if vr.should_skip_ddb:
           logger.error("Validation CRITICAL — skipping DDB write", errors=vr.errors)
           vr.archive_to_s3(s3, S3_BUCKET)
           return  # or continue to next date
       if vr.warnings:
           logger.warning("Validation warnings", warnings=vr.warnings)
   except ImportError:
       pass  # validator not bundled
   ```
4. Bundle `ingestion_validator.py` alongside each Lambda (add to deploy script extra_files or Lambda Layer)
5. Deploy all 3 Lambdas
6. Smoke test each: invoke manually, check CloudWatch for validation log lines
7. **Important:** Run with real data first, don't assume the validation rules are correct. If valid data gets rejected, loosen the rule in the validator — don't remove the validator.

**Acceptance criteria:** Whoop, Strava, MacroFactor items pass through validation before DDB write. CRITICAL items archived to S3 instead of written. Warnings logged.

---

### Item 3: Wire `platform_logger.py` into `daily_brief_lambda.py` (1 hr)

**What:** The structured logger (`lambdas/platform_logger.py`) outputs single-line JSON for CloudWatch Logs Insights. It's fully built but no Lambda uses it.

**How:**
1. Read `lambdas/platform_logger.py` — understand `get_logger(source)`, `.set_date()`, convenience methods
2. In `daily_brief_lambda.py`, replace the existing logger setup (likely `import logging; logger = logging.getLogger()`) with:
   ```python
   from platform_logger import get_logger
   logger = get_logger("daily-brief")
   ```
3. In `lambda_handler()`, add `logger.set_date(target_date)` early to set the correlation ID
4. Existing `logger.info(msg)` calls continue to work unchanged (backward compatible)
5. Optionally upgrade a few key log lines to use kwargs: `logger.info("Sending email", grade=grade, subject=subject)`
6. Bundle `platform_logger.py` in the Lambda zip (should already be in the Layer, but verify)
7. Deploy and verify: CloudWatch logs should now be JSON lines with `correlation_id` field

**Acceptance criteria:** Daily Brief logs emit structured JSON. `correlation_id` field present on all log lines. CWL Insights query `filter correlation_id like "2026-03-09"` returns results.

---

### Item 4: Update `ARCHITECTURE.md` + `INFRASTRUCTURE.md` (1-2 hr)

**What:** Both docs are stale after the hardening sprint. ARCHITECTURE.md still references the shared role. INFRASTRUCTURE.md is at v2.93.0.

**ARCHITECTURE.md changes needed:**
1. Update header version: v2.91.0 → v3.1.3, 35 → 39 Lambdas, 6 → 8 secrets
2. **IAM Security Model section:** Remove mention of `lambda-weekly-digest-role` shared by 10 Lambdas. Replace with description of 13 dedicated per-function roles (daily-brief, weekly-digest, monthly-digest, nutrition-review, wednesday-chronicle, weekly-plate, monday-compass, adaptive-mode-compute, daily-metrics-compute, daily-insight-compute, hypothesis-engine, qa-smoke, data-export) + note that graduated restrictiveness is applied (most restrictive: DDB+KMS only)
3. **Operational Lambdas table:** Update IAM Role column — replace all `lambda-weekly-digest-role` entries with the correct per-function role names
4. **Secrets Manager section:** Update from 6 to 8 secrets. Add `life-platform/todoist`, `life-platform/notion`, `life-platform/dropbox`, `life-platform/ai-keys`. Note `api-keys` is pending deletion (~2026-04-07)
5. **Failure handling section:** Add DLQ consumer Lambda, canary Lambda, item_size_guard
6. **New Lambdas to add:** `life-platform-dlq-consumer`, `life-platform-canary`, `life-platform-data-reconciliation`, `life-platform-pip-audit`

**INFRASTRUCTURE.md changes needed:**
1. Update header: v2.93.0 → v3.1.3
2. Secrets Manager table: Add todoist, notion, dropbox, ai-keys secrets. Mark api-keys as "pending deletion"
3. Lambdas section: Update count from 35 to 39. Add Infrastructure Lambdas: dlq-consumer, canary, data-reconciliation, pip-audit
4. CloudWatch alarms: Update count from 44 to ~47
5. EventBridge section: Note new schedules for data-reconciliation (Mon 07:30 UTC), pip-audit (Mon 17:00 UTC), canary (rate 4h), dlq-consumer (rate 6h)

**Acceptance criteria:** Both docs accurately reflect v3.1.3 state. No references to shared `lambda-weekly-digest-role`. Lambda count, secret count, and alarm count correct.

---

### Item 5: Update `PROJECT_PLAN.md` Tier 8 statuses (30 min)

**What:** The Tier 8 section still shows 🔴 for all items, even the 20 that are complete.

**How:**
1. Update header version: v3.0.0 → v3.1.3, 37 → 39 Lambdas, 6 → 8 secrets
2. Flip these to ✅: SEC-1, SEC-2, SEC-3, SEC-5, IAM-1, IAM-2, REL-1, REL-2, REL-3, REL-4, OBS-2, COST-1, COST-3, MAINT-1, MAINT-2, DATA-1, DATA-3, AI-1
3. Mark these as ⚠️ (built, not wired): OBS-1, DATA-2, AI-3
4. Mark MAINT-3 as ⚠️ (partial — lambdas/ cleaned, deploy/ not)
5. Keep 🔴 for: SEC-4, OBS-3, COST-2, MAINT-4, AI-2, AI-4, SIMP-1, SIMP-2, PROD-1, PROD-2
6. Update the Completed section with v2.95 through v3.1.3 entries

**Acceptance criteria:** Tier 8 status column reflects actual state. Version header correct.

---

### Item 6: Update `INCIDENT_LOG.md` (30 min)

**What:** Last updated v2.76.1. Missing the todoist SECRET_NAME incident and reconciliation first-run finding.

**Add these entries:**

| Date | Severity | Summary | Root Cause | TTD | TTR | Data Loss? |
|------|----------|---------|------------|-----|-----|------------|
| 2026-03-08 | P3 | todoist-data-ingestion failing since 2026-03-06 | Stale `SECRET_NAME` env var pointing to `life-platform/api-keys` (marked for deletion during secrets consolidation). DLQ consumer caught it on first run. | ~2 days (DLQ consumer) | 15 min (env var fix) | No — gap-aware backfill self-healed 2-day gap |
| 2026-03-08 | Info | data-reconciliation first run: RED (17 gaps / 6 sources) | All gaps are bootstrap noise (platform started Feb 22) or expected absence (DEXA, genome, labs = manual/periodic). Zero real ingestion failures detected. | N/A | N/A | No — informational |

Also update the "Resolved gaps" section: DLQ now has a consumer, end-to-end canary exists, item size monitoring deployed.

**Acceptance criteria:** Incident log current through v3.1.3. Pattern analysis updated.

---

### Item 7: Clean stale `.zip` files from `lambdas/` (10 min)

**What:** 6 stale deployment artifact zips sitting next to source files.

**How:**
```bash
cd ~/Documents/Claude/life-platform
mkdir -p deploy/zips
mv lambdas/garmin_lambda.zip deploy/zips/
mv lambdas/habitify_lambda.zip deploy/zips/
mv lambdas/health_auto_export_lambda.zip deploy/zips/
mv lambdas/key_rotator.zip deploy/zips/
mv lambdas/nutrition_review_lambda.zip deploy/zips/
mv lambdas/wednesday_chronicle.zip deploy/zips/
```

**Acceptance criteria:** No .zip files in `lambdas/` (except maybe `mcp_server.zip` if used by deploy). All moved to `deploy/zips/`.

---

## After These 7 Items

### Next hardening session (Sonnet, ~8 hr)
- Wire `ingestion_validator.py` into remaining 10+ Lambdas
- Wire `platform_logger.py` into 5-10 more Lambdas
- MAINT-3 completion: purge deploy/ of one-time scripts → `deploy/archive/`
- AI-2: Fix causal language in prompts
- Verify hardening stuck: invoke each Lambda, check role + secret + Layer

### Still open from Tier 8 (longer-term)
- MAINT-4: CI/CD with GitHub Actions (**Opus**)
- OBS-3: SLOs for critical paths (**Opus**)
- AI-4: Hypothesis engine validation (**Opus**)
- SEC-4: API Gateway rate limiting (Sonnet)
- COST-2: MCP tool usage audit (Sonnet)
- SIMP-1: Archive low-usage tools (Sonnet)

### Then: Brittany weekly email
First feature after hardening gate passes.

---

## Files Changed This Session

| File | Change |
|------|--------|
| `docs/REVIEW_2026-03-08.md` | **NEW** — Architecture Review #1 |
| `docs/REVIEW_2026-03-08_v2.md` | **NEW** — Architecture Review #2 (delta) |
| `docs/REVIEW_METHODOLOGY.md` | **NEW** — Repeatable review process |
| `deploy/generate_review_bundle.sh` | **NEW** — AWS state snapshot |
| `docs/PROJECT_PLAN.md` | **UPDATED** — Tier 8 hardening roadmap added |
| `docs/CHANGELOG.md` | **UPDATED** — v2.94.1 entry |
| `handovers/2026-03-08_architecture_review_v2.md` | **NEW** — This file |
| `docs/HANDOVER_LATEST.md` | **UPDATED** — Points here |

---

## Resume Prompt (for Sonnet)

```
Life Platform — post-architecture-review wiring session.

Read these files first:
- handovers/2026-03-08_architecture_review_v2.md (this handover — has all 7 tasks with exact instructions)
- docs/PROJECT_PLAN.md (Tier 8 section for status context)

This session's goal: complete the 7 immediate items listed in the handover.
Work sequentially — Item 1 through Item 7. Each has specific files to read,
changes to make, and acceptance criteria.

Key context:
- Three safety modules exist as files in lambdas/ but aren't imported by any Lambda yet:
  1. ai_output_validator.py → needs wiring into ai_calls.py
  2. ingestion_validator.py → needs wiring into whoop, strava, macrofactor Lambdas
  3. platform_logger.py → needs wiring into daily_brief_lambda.py
- Four docs are stale: ARCHITECTURE.md, INFRASTRUCTURE.md, PROJECT_PLAN.md, INCIDENT_LOG.md
- Six .zip files in lambdas/ need moving to deploy/zips/

Start with Item 1 (ai_output_validator wiring).
```
