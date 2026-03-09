# PROD-2: Multi-User Hardcoding Audit

> Full audit of hardcoded single-user assumptions across the platform.
> Generated: 2026-03-09 from codebase analysis at v3.2.1.
> **Purpose:** Identifies every change needed before a second user can be added.

---

## Executive Summary

The codebase is **~90% parameterized already.** Every Lambda reads `USER_ID` and `S3_BUCKET` from environment variables. DynamoDB keys use f-strings with `{USER_ID}`. The remaining 10% is:

1. **Default fallback values** — `os.environ.get("USER_ID", "matthew")` in every Lambda
2. **S3 bucket name** — contains "matthew" in the name itself (can't rename)
3. **SES email addresses** — hardcoded sender/recipient in email Lambdas
4. **S3 path structure** — dashboard/buddy/config paths don't include user prefix
5. **Board of Directors config** — single shared config, not per-user
6. **Docstrings/comments** — cosmetic references to "matthew" (no runtime impact)

**Estimated effort to fix all:** 4 sessions (12-16 hours), as scoped in SCOPING_LARGE_OPUS.md.

---

## Category 1: Environment Variable Defaults (39 Lambdas)

**Pattern:** Every Lambda has this boilerplate:
```python
USER_ID    = os.environ.get("USER_ID", "matthew")
S3_BUCKET  = os.environ.get("S3_BUCKET", "matthew-life-platform")
```

**Risk:** LOW — all Lambdas have `USER_ID` and `S3_BUCKET` set as env vars in AWS. The default is only used in local testing. But it means a new user deployment must set these env vars or silently write to Matthew's data.

**Fix:** Change default to `None` and fail fast:
```python
USER_ID = os.environ["USER_ID"]  # No default — must be set
```

**Files affected (all 39 Lambdas + MCP config):**

| File | USER_ID | S3_BUCKET |
|------|---------|-----------|
| `mcp/config.py` | ✅ line 20 | ✅ line 19 |
| `whoop_lambda.py` | ✅ line 24 | ✅ line 22 |
| `strava_lambda.py` | ✅ line 35 | ✅ line 33 |
| `garmin_lambda.py` | ✅ line 86 | ✅ line 84 |
| `eightsleep_lambda.py` | ✅ line 102 | ✅ line 100 |
| `habitify_lambda.py` | ✅ line 58 | — (uses TABLE_NAME) |
| `withings_lambda.py` | ✅ line 32 | ✅ line 30 |
| `todoist_lambda.py` | ✅ line 23 | ✅ line 21 |
| `macrofactor_lambda.py` | ✅ line 38 | ✅ line 36 |
| `weather_lambda.py` | ✅ line 26 | ✅ line 25 |
| `hypothesis_engine_lambda.py` | ✅ line 47 | ✅ line 48 |
| All other Lambdas | Same pattern | Same pattern |

**Migration:** Find-and-replace across all files. 10 minutes.

---

## Category 2: S3 Bucket Name (cannot rename)

**Issue:** The bucket is named `matthew-life-platform`. S3 bucket names are globally unique and immutable.

**Fix options:**
- **A) Keep the bucket name** — it's just a string; a second user's data goes in the same bucket, prefixed by user. No cost, no risk. The bucket name is cosmetic.
- **B) Create a new bucket** per user — cleaner isolation but adds infra complexity.

**Recommendation:** Option A. Set `S3_BUCKET` env var per-user deployment. The bucket name doesn't leak to the user.

---

## Category 3: SES Email Addresses (7 email Lambdas)

**Hardcoded locations (need to verify in email Lambda source):**
- Sender: `life-platform@mattsusername.com` or similar
- Recipient: Matthew's personal email
- SES domain: `mattsusername.com`

**Fix:** Move sender/recipient to user profile record (`pk=USER#{user_id}, sk=PROFILE#v1`). Email Lambdas already read profile for targets — add `email` and `sender_address` fields.

**Files affected:** `daily_brief_lambda.py`, `weekly_digest_lambda.py`, `monthly_digest_lambda.py`, `nutrition_review_lambda.py`, `wednesday_chronicle_lambda.py`, `weekly_plate_lambda.py`, `monday_compass_lambda.py`

---

## Category 4: S3 Path Structure

**Current paths (no user prefix):**
```
dashboard/data.json           → should be dashboard/{user_id}/data.json
dashboard/index.html          → shared (template) vs per-user data
buddy/data.json               → should be buddy/{user_id}/data.json
config/board_of_directors.json → should be config/{user_id}/board_of_directors.json
config/character_sheet.json    → should be config/{user_id}/character_sheet.json
config/profile.json            → should be config/{user_id}/profile.json
raw/{source}/...              → should be raw/{user_id}/{source}/...
```

**Producers:** `daily-brief` (writes data.json, buddy/data.json), `weekly-digest` (writes clinical.json), `dashboard-refresh`, all ingestion Lambdas (write to raw/)

**Fix:** Prefix all S3 keys with user_id. This is the biggest change — affects read/write paths in ~20 Lambdas.

---

## Category 5: DynamoDB Key Construction

**Status: ALREADY PARAMETERIZED.** All Lambdas construct keys using:
```python
pk = f"USER#{USER_ID}#SOURCE#{source}"
```

The MCP config.py centralizes this:
```python
USER_PREFIX     = f"USER#{USER_ID}#SOURCE#"
PROFILE_PK      = f"USER#{USER_ID}"
INSIGHTS_PK     = f"USER#{USER_ID}#SOURCE#insights"
# ... (10 more partition keys)
```

**No changes needed** — just ensure `USER_ID` env var is set correctly per deployment.

---

## Category 6: Board of Directors Config

**Current:** Single `config/board_of_directors.json` in S3, loaded by all email Lambdas via `board_loader.py`.

**Issue:** Board config is identical for all users today, but personalization (different coaching personas) would require per-user configs.

**Fix options:**
- **A) Keep shared** — Board is the same for everyone. Simplest.
- **B) Per-user path** — `config/{user_id}/board_of_directors.json`. board_loader.py already takes a bucket param.

**Recommendation:** Option A for now. Board personalization is a future feature.

---

## Category 7: CloudFront / Web Properties

**Current:**
- `dash.averagejoematt.com` → S3 `/dashboard` (Lambda@Edge auth)
- `buddy.averagejoematt.com` → S3 `/buddy` (separate auth)
- `blog.averagejoematt.com` → S3 `/blog` (public)

**Issue:** Domain names, CloudFront distributions, and Lambda@Edge auth functions are all single-user.

**Fix:** For multi-user, either:
- Path-based routing (`dash.domain.com/{user_id}/`) with auth checking user ownership
- Separate subdomains per user (complex, likely overkill)

**Recommendation:** Defer. Dashboard/buddy are low-priority for multi-user. The data layer is the important part.

---

## Category 8: Docstrings and Comments

**53 instances** of "matthew" in docstrings/comments across the codebase. No runtime impact.

**Fix:** Bulk find-and-replace `matthew` → `{user_id}` in comments. Low priority.

---

## Priority Order for Multi-User Migration

| Phase | What | Effort | Impact |
|-------|------|--------|--------|
| 1 | Remove default fallbacks (require env vars) | 30 min | Prevents silent cross-contamination |
| 2 | Move email addresses to profile record | 2 hr | Enables per-user email delivery |
| 3 | Prefix S3 paths with user_id | 4-6 hr | Isolates raw data + dashboard data |
| 4 | Parameterize CloudFront/web (optional) | 4-6 hr | Multi-user web access |

---

## Verdict

The platform was built with parameterization in mind from day one. The `USER_ID` env var pattern is consistent across all 39 Lambdas and the MCP server. The real work is:
1. **S3 path prefixing** (the biggest change, ~4-6 hours)
2. **Email address extraction** (2 hours)
3. **Removing default fallbacks** (30 minutes)

Everything else is already done or can be deferred.
