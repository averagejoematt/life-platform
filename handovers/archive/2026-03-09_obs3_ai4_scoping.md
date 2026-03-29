# Life Platform Handover — v3.2.0
**Date:** 2026-03-09
**Version:** v3.2.0
**Status:** Code ready, deploy scripts written. ⚠️ hypothesis_engine_lambda.py needs manual copy (see below).

---

## What Was Done This Session

### OBS-3: SLO Definitions ✅ (ready to deploy)
- **docs/SLOs.md** — Formal SLO definitions for 4 critical paths:
  - SLO-1: Daily Brief Delivery (99%, 24h error alarm)
  - SLO-2: Source Freshness (99%, custom CloudWatch metric from freshness checker)
  - SLO-3: MCP Availability (99.5%, hourly error rate alarm)
  - SLO-4: AI Coaching Success (99%, daily failure count alarm)
- **freshness_checker_lambda.py** — Updated to emit `StaleSourceCount` + `FreshSourceCount` to CloudWatch `LifePlatform/Freshness` namespace
- **deploy/obs3_slo_definitions.sh** — Creates 4 SLO alarms, adds IAM for freshness checker CloudWatch, deploys Lambda, updates ops dashboard with SLO section
- Error budgets defined (30-day and yearly windows)

### AI-4: Hypothesis Engine Output Validation ✅ (ready to deploy)
- **hypothesis_engine_lambda.py** v1.1.0 — Major validation upgrade:
  - `check_data_completeness()`: Requires 10+ days with 5+ metrics each before generating
  - `validate_hypothesis()`: Validates required fields, 2+ domains, numeric thresholds in criteria, 7-30d window, confidence level, dedup check
  - `enforce_hard_expiry()`: Archives any hypothesis >30 days old regardless of status
  - `validate_check_verdict()`: Validates Haiku check responses before acting
  - Min sample days for checking raised from 3 → 7
  - Confirming checks needed for promotion raised from 2 → 3
  - Updated prompt requires effect sizes, specific numeric thresholds, confidence reasons
- **deploy/ai4_hypothesis_validation.sh** — Deploy + smoke test script

### Large Opus Scoping ✅
- **docs/SCOPING_LARGE_OPUS.md** — Design specs for:
  - **MAINT-4** (CI/CD): GitHub Actions workflow design, OIDC auth, change detection, approval gates. 2 sessions.
  - **SIMP-2** (Ingestion consolidation): Shared framework architecture, migration strategy, 3-phase approach. 3 sessions.
  - **PROD-1** (IaC/CDK): 8-stack CDK design, import strategy for existing resources. 6 sessions.
  - **PROD-2** (Multi-user): Hardcoding audit, parameterization plan, synthetic user test. 4 sessions.

---

## ⚠️ IMPORTANT: Manual Step Required

The `hypothesis_engine_lambda.py` file on the local filesystem was accidentally emptied during the edit process. **Before running the AI-4 deploy script:**

1. Download `hypothesis_engine_lambda.py` from Claude's output (presented in chat)
2. Copy it to `lambdas/hypothesis_engine_lambda.py`
3. Verify: `grep -c "AI-4" lambdas/hypothesis_engine_lambda.py` should return 15+

The deploy script checks for AI-4 markers and will abort if the file is wrong.

---

## Deploy Order

```bash
# 1. Fix the hypothesis engine file first (manual copy from Claude output)
cp ~/Downloads/hypothesis_engine_lambda.py lambdas/hypothesis_engine_lambda.py

# 2. OBS-3: SLO definitions
bash deploy/obs3_slo_definitions.sh

# 3. AI-4: Hypothesis validation (wait 10s between deploys)
bash deploy/ai4_hypothesis_validation.sh
```

---

## Hardening Status (post v3.2.0)

| Status | Count | Items |
|--------|-------|-------|
| ✅ Done | 28 | SEC-1,2,3,4,5; IAM-1,2; REL-1,2,3,4; OBS-1,2,3; COST-1,3; MAINT-1,2,3; DATA-1,2,3; AI-1,2,3,4 |
| 🔴 Open | 7 | COST-2, MAINT-4, SIMP-1, SIMP-2, PROD-1, PROD-2 |

OBS-3 and AI-4 move from 🔴 → ✅.

---

## Next Session Options

### Quick Wins (Sonnet, 1 session)
- **COST-2:** MCP tool usage audit — add CW metric per tool, archive 0-invocation tools after 30d
- **SIMP-1:** Audit low-usage MCP tools — target <100 active tools (overlaps with COST-2)

### Medium Efforts (Opus, 1-2 sessions)
- **Brittany weekly email** — the long-queued major feature, fully unblocked

### Large Efforts (Opus, multi-session — scoped in SCOPING_LARGE_OPUS.md)
- **MAINT-4:** CI/CD with GitHub Actions (2 sessions)
- **SIMP-2:** Consolidate ingestion Lambdas (3 sessions)
- **PROD-1:** IaC with CDK (6 sessions)
- **PROD-2:** Multi-user parameterization (4 sessions, ideally after PROD-1)

---

## Platform Stats (v3.2.0)
- **Lambdas:** 39 | **MCP Tools:** 144 | **Modules:** 30
- **Data Sources:** 19 | **Secrets:** 8 | **Alarms:** ~51 (4 new SLO alarms)
- **Hardening:** 28/35 complete (80%)
