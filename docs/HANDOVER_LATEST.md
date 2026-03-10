# Life Platform — Handover v3.3.13
**Date:** 2026-03-10
**Session:** Task 10 — digest_utils consolidation

---

## Platform State

| Dimension | Value |
|---|---|
| Version | v3.3.13 |
| MCP Tools | 144 across 30 modules |
| Lambdas | 39 |
| Secrets | 8 |
| Alarms | ~47 |
| CDK Stacks | 7 |
| Cost | ~$25/month |
| AWS | Account 205930651321, us-west-2 |

---

## What Was Done This Session

### Task 10: Digest utility consolidation — COMPLETE (pending deploy)

**New file:** `lambdas/digest_utils.py` — shared pure-Python module (~270 lines).

**Contents:**
- Pure scalar helpers: `d2f`, `avg`, `fmt`, `fmt_num`, `safe_float`
- `dedup_activities` — Garmin→Strava duplicate removal (15-min window, richness-based)
- `_normalize_whoop_sleep` — canonical Whoop field alias mapping (v2.55.0 SOT)
- List-based extractors: `ex_whoop_from_list`, `ex_whoop_sleep_from_list`, `ex_withings_from_list`
- Banister: `compute_banister_from_list`, `compute_banister_from_dict`, `_banister_core`

**weekly_digest_lambda.py** — pure refactor, ~80 lines removed, behaviour unchanged.

**monthly_digest_lambda.py — v1.2.0 — 5 bug fixes:**

| Bug | Was | Fixed To |
|---|---|---|
| `ex_macrofactor` field names | `calories`, `protein_g` (wrong — zero data silently) | `total_calories_kcal`, `total_protein_g` |
| `ex_macrofactor` targets | Hardcoded constants | Profile-driven from PROFILE#v1 |
| Profile SK | `PROFILE` (wrong — silent fallback to defaults) | `PROFILE#v1` |
| `ex_strava` dedup | Not called (Garmin→Strava dupes counted) | `dedup_activities()` per day |
| Banister | Local `compute_banister()` without dedup | `compute_banister_from_list()` with dedup |

---

## Deploy Status

All v3.3.12 + v3.3.13 deploys confirmed live as of 2026-03-10:
- ✅ `life-platform-mcp` — auth-failure EMF metric (v3.3.12)
- ✅ `daily-insight-compute` — platform_memory 90-day TTL (v3.3.12)
- ✅ `weekly-digest` — digest_utils refactor (v3.3.13)
- ✅ `monthly-digest` — digest_utils + 5 bug fixes (v3.3.13)

---

## Hardening Status

34/35 complete. SIMP-1 (MCP tool usage audit) deferred ~2026-04-08.
SIMP-2 (digest consolidation) ✅ DONE this session.

---

## Next Steps

1. Deploy v3.3.12 hardening (if not done): `bash deploy/deploy_hardening_v3312.sh`
2. Deploy Task 10: `bash deploy/deploy_task10_digest_utils.sh`
3. **Next feature: Brittany weekly email** (Lambda slot + source file exist, feature deferred)
4. Architecture Review #4: ~2026-04-08

---

## Key Paths

- `lambdas/digest_utils.py` — NEW shared module
- `lambdas/weekly_digest_lambda.py` — refactored
- `lambdas/monthly_digest_lambda.py` — v1.2.0 + 5 bug fixes
- `deploy/deploy_task10_digest_utils.sh` — deploy script
- Profile SK: `pk=USER#matthew`, `sk=PROFILE#v1`
