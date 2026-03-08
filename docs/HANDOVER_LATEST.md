# Life Platform — Handover v2.96.0
**Date:** 2026-03-08  
**Session:** Architecture Review Hardening — Batch 1 complete + SEC-1 IAM decomposition

---

## What Was Done This Session

### Hardening Batch 1 — All 5 Quick Wins ✅
- **AI-1** — Health disclaimers on all 8 email Lambdas (deployed)
- **MAINT-3** — 39 stale files archived to `archive/20260308/`
- **COST-1** — S3 Glacier lifecycle on `raw/` prefix (90 days)
- **SEC-4** — API Gateway throttle: 1.67 req/s on `health-auto-export-api`
- **IAM-2** — `life-platform-analyzer` (IAM Access Analyzer) live

### SEC-1 — IAM Role Decomposition ✅ COMPLETE
Live audit showed the bulk of the work was already done by a prior session. Only 2 Lambdas remained on the shared `lambda-weekly-digest-role`:

| Lambda | Old Role | New Role |
|--------|----------|----------|
| `brittany-weekly-email` | `lambda-weekly-digest-role` | `life-platform-email-role` |
| `life-platform-qa-smoke` | `lambda-weekly-digest-role` | `life-platform-compute-role` |

**Result:** `lambda-weekly-digest-role` has zero Lambda users. Tagged `status=deprecated, deprecated-date=2026-03-08`.

**All 35 Lambdas are now on scoped roles:**
- `life-platform-compute-role` — 5 compute Lambdas (no SES, no blog S3)
- `life-platform-email-role` — 8 email Lambdas (daily-brief, monday-compass, nutrition-review, wednesday-chronicle, weekly-plate, anomaly-detector, brittany-weekly-email + freshness-checker)
- `life-platform-digest-role` — 2 digest Lambdas (weekly-digest, monthly-digest)
- 20 dedicated per-function roles — all ingestion, MCP, enrichment, utility Lambdas

---

## Pending Action: Delete Deprecated Role (7 days)

After confirming clean operation on 2026-03-15, delete `lambda-weekly-digest-role`:

```bash
# List its policies first
aws iam list-role-policies --role-name lambda-weekly-digest-role --no-cli-pager
aws iam list-attached-role-policies --role-name lambda-weekly-digest-role --no-cli-pager

# Then delete inline policies, detach managed policies, delete role
# (run manually — don't script a delete of a role until you've confirmed what's attached)
```

---

## Commit

```bash
git add -A && git commit -m "v2.96.0: SEC-1 complete — lambda-weekly-digest-role deprecated, all 35 Lambdas on scoped roles" && git push
```

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
| SEC-1 | IAM role decomposition — shared role deprecated |

### 🔴 Next Up (P1 — Next 2 Weeks)
| Task | Priority | Description |
|------|----------|-------------|
| SEC-2 | P1 | Split `life-platform/api-keys` into domain-specific secrets |
| SEC-3 | P1 | Input validation on MCP tool arguments |
| MAINT-1 | P1 | `requirements.txt` per Lambda with pinned versions |
| MAINT-2 | P1 | Lambda Layer for shared modules |
| DATA-1 | P1 | Add `schema_version` to all DynamoDB items |
| REL-1 | P1 | Graceful degradation when compute Lambdas fail |

### Note on SEC-2
`p0_split_secret.sh` already exists in `deploy/` — read it before running to understand what it does and whether it's current.

---

## Platform State
- **Version:** v2.96.0
- **Lambdas:** 35 (all on scoped IAM roles)
- **MCP Tools:** 144
- **Modules:** 30
- **IAM:** No shared roles. `lambda-weekly-digest-role` deprecated.
