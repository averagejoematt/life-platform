# Life Platform Handover — v3.3.9 (2026-03-09)

## Session Summary

Two hardening items closed:

**MAINT-3 (deploy/ cleanup):**
- `deploy/maint3_archive_deploy.sh` written — archives all but 8 active files to `archive/YYYYMMDD/deploy/`
- Run: `bash deploy/maint3_archive_deploy.sh`
- **Pending your execution** — script is ready, nothing run yet

**SEC-4 (API Gateway rate limiting):**
- Verified already live — `health-auto-export-api` (HTTP API v2, `a76xwxt2wa`) has `ThrottlingRateLimit: 1.67 req/s`, `ThrottlingBurstLimit: 10`
- Applied in a prior session; just needed confirmation and documentation
- No deploy needed ✅

---

## MAINT-3 Details

Script: `deploy/maint3_archive_deploy.sh`

**Archives** (~247 files) → `archive/YYYYMMDD/deploy/`

**Keeps** (8 files):
| File | Why |
|------|-----|
| `deploy_lambda.sh` | Universal Lambda deploy helper — used every session |
| `MANIFEST.md` | Handler/role/deps reference |
| `SMOKE_TEST_TEMPLATE.sh` | Smoke test template |
| `generate_review_bundle.sh` | Future architecture reviews |
| `p3_build_shared_utils_layer.sh` | Rebuild shared Lambda layer |
| `p3_build_garmin_layer.sh` | Rebuild Garmin native deps layer |
| `p3_attach_shared_utils_layer.sh` | Attach layer to Lambdas |
| `sec4_apigw_rate_limit.sh` | SEC-4 reference (already applied) |
| `maint3_archive_deploy.sh` | This cleanup script |

**Zips:** Archives 9 stale from `deploy/zips/`; keeps `garmin_lambda.zip` (native deps — hard to rebuild).

To undo if needed: `mv archive/YYYYMMDD/deploy/* deploy/`

---

## Hardening Epic Final Status

| Status | Items |
|--------|-------|
| ✅ Done (34) | SEC-1,2,3,4,5; IAM-1,2; REL-1,2,3,4; OBS-1,2,3; COST-1,2,3; MAINT-1,2,3,4; DATA-1,2,3; AI-1,2,3,4; SIMP-2; PROD-1; PROD-2 |
| 🔴 Open (1) | SIMP-1 — MCP tool usage audit (revisit ~2026-04-08 after 30 days usage data) |

**Hardening epic is effectively complete.**

---

## Platform State — v3.3.9
- **Version:** v3.3.9
- **Lambdas:** 39 | **MCP Tools:** 144 | **Data Sources:** 19 | **Alarms:** ~47
- **Git:** pending commit after MAINT-3 script execution

## Next Steps (in priority order)

1. **Run the cleanup**: `bash deploy/maint3_archive_deploy.sh` (then `git add -A && git commit -m "v3.3.9: MAINT-3 deploy cleanup + SEC-4 confirmed"`)
2. **Brittany weekly email** — next major feature, fully unblocked
3. **SIMP-1** — ~2026-04-08 (MCP tool usage audit after 30 days data)
