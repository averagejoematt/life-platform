# Life Platform Handover — v3.2.1
**Date:** 2026-03-09
**Version:** v3.2.1
**Status:** CI/CD pipeline written. OIDC setup + GitHub Environment config required before first use.

---

## What Was Done This Session

### OBS-3: SLO Definitions ✅ (deployed)
- 4 SLO alarms created and verified
- Freshness checker emitting CloudWatch metrics
- Ops dashboard updated with SLO Health section

### AI-4: Hypothesis Engine Validation ✅ (deployed)
- v1.1.0 with data completeness, hypothesis validation, 30-day hard expiry
- 13 complete data days confirmed, Lambda executing cleanly

### MAINT-4: GitHub Actions CI/CD ✅ (code ready, setup required)
- `.github/workflows/ci-cd.yml` — 4-job pipeline:
  - **Lint:** flake8 (fatal on syntax errors, warnings pass)
  - **Plan:** git diff change detection → Lambda mapping via `ci/lambda_map.json`
  - **Deploy:** GitHub Environment `production` approval gate, 10s between deploys, shared layer auto-rebuild, MCP server handled separately, garmin native deps auto-skipped
  - **Smoke test:** qa-smoke + canary post-deploy verification
- `ci/lambda_map.json` — 38 Lambda mappings + shared layer + MCP config
- `.flake8` — project-wide lint config
- `deploy/setup_github_oidc.sh` — OIDC provider + IAM role creation
- `workflow_dispatch` support for manual deploy-all

### Large Opus Scoping ✅
- SIMP-2, PROD-1, PROD-2 design specs in `docs/SCOPING_LARGE_OPUS.md`

---

## ⚠️ Setup Steps for MAINT-4

The CI/CD pipeline code is in the repo but won't work until these one-time setup steps are done:

```bash
# 1. Create OIDC provider + IAM role
bash deploy/setup_github_oidc.sh

# 2. Go to GitHub → repo Settings → Environments
#    Create environment: "production"
#    Add protection rule: Required reviewers → add yourself
#    Add deployment branch rule: main only
```

After that, any push to `main` that touches `lambdas/` or `mcp/` files will trigger the pipeline. The deploy step waits for your approval in the GitHub UI.

---

## Hardening Status (v3.2.1)

| Status | Count | Items |
|--------|-------|-------|
| ✅ Done | 29 | SEC-1,2,3,4,5; IAM-1,2; REL-1,2,3,4; OBS-1,2,3; COST-1,3; MAINT-1,2,3,4; DATA-1,2,3; AI-1,2,3,4 |
| 🔴 Open | 6 | COST-2, SIMP-1, SIMP-2, PROD-1, PROD-2 |

**83% complete.** Remaining open items are all Sonnet (COST-2, SIMP-1) or multi-session Opus (SIMP-2, PROD-1, PROD-2).

---

## Platform Stats (v3.2.1)
- **Lambdas:** 39 | **MCP Tools:** 144 | **Modules:** 30
- **Data Sources:** 19 | **Secrets:** 8 | **Alarms:** ~51
- **Hardening:** 29/35 complete (83%)
