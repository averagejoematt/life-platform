# Handover v3.8.8 — Phase 0 Website Data Fixes
**Date:** 2026-03-22
**Session type:** Phase 0 surgical fixes per WEBSITE_REDESIGN_SPEC.md

---

## What Was Done

### G-3: Weight showing blank in marquee — FIXED

**Root cause:** `handle_vitals()` used `float(withings.get("weight_lbs", 0))` which returns 0 when the
field is missing, then `if current_weight` evaluated 0.0 as falsy → returned `null`.
Additionally, `public_stats.json` has `vitals.weight_lbs = null` (separate daily-brief Lambda bug).

**Fix in site_api_lambda.py:**
- Changed `_latest_item("withings")` weight extraction to use `wv is not None` guard
- Added `weight_as_of` date field to the `/api/vitals` response
- `weight_lbs` now uses `if current_weight is not None` (not truthy check)

**Fix in site/index.html:**
- Ticker now falls back to `/api/vitals` when `public_stats.json` has null weight
- Displays "287.7 LBS (MAR 7)" format when `weight_as_of` is >3 days ago

### G-4: Journey progress showing 0.00% — FIXED

**Root cause:** `handle_journey()` returned `_error(503, ...)` when no Withings data found in the
120-day window. If weight_series is empty, progress_pct defaults to 0.

**Fix in site_api_lambda.py:**
- Removed `return _error(503, ...)` fallback
- Falls back to `_latest_item("withings")` (any date) for last known weight
- If truly no weight data at all, seeds with journey start (302 lbs, 0% progress)

Note: `public_stats.json.journey.progress_pct = 0` is a separate daily-brief Lambda bug;
this fix ensures `/api/journey` endpoint always returns correct data.

### G-5: Streak showing "—" instead of "0" — ALREADY FIXED ✓

Line 1354 of site/index.html already has `p.tier0_streak != null ? p.tier0_streak : 0`.
The `!= null` comparison covers both `null` and `undefined` in JS. No change needed.

### STORY-1: Hardcoded stats in story data-moment — FIXED

Added IDs to three of five spans in `site/story/index.html` lines 449-453:
- `story-lambda-count` → wired to `platform.lambdas`
- `story-data-sources-stat` → wired to `platform.data_sources`
- `story-tools-count` → wired to `platform.mcp_tools`

**Left static:** "853/853 tests passing" and "~$13/mo" — not in public_stats.json yet.
Add `test_count` and `monthly_cost` to daily-brief Lambda output when counts change.

### PLAT-1: Hardcoded stats on platform page — FIXED

Added IDs to `site/platform/index.html` header stat cards:
- `plat-mcp-tools` (was hardcoded 95 → now dynamic)
- `plat-data-sources` (was hardcoded 19 → now dynamic)
- `plat-lambdas` (was hardcoded 48 → now dynamic)

Added a new JS loader block that fetches public_stats.json on page load.

Current live values in public_stats.json: mcp_tools=87, data_sources=19, lambdas=42.

### PROTO-1: Hardcoded fallback adherence — FIXED

Removed the `var fallback = {zone2: '78%', ...}` dict from `site/protocols/index.html`.
`applyFallback()` now sets "—" (em dash) for all adherence values when API is unavailable.
This is honest: we don't have data, so we show nothing rather than stale estimates.

### CHRON-1: Individual post pages using old nav — ALREADY DONE ✓

Checked all four posts: week-00, week-01, week-02, week-03.
All have the current 5-section nav (Story / Data / Science / Build / Follow).

### CHRON-2: Week 1 gap investigation — NOTED, NO CHANGE

`site/journal/posts/week-01/index.html` exists but its body is a placeholder:
`"See S3: blog/week-00.html"` — no actual prose content.

Title is "Before the Numbers" (same as week-00 which is the prologue).
**Action needed:** Generate Elena Voss Week 1 content in a separate content session.
Do NOT add to `posts.json` until content is real.

### G-7: Subscribe confirmation not working — INVESTIGATED, NO CODE CHANGE

The subscribe infrastructure is correctly built:
- `email_subscriber_lambda.py` handles POST /api/subscribe
- CDK web_stack.py routes `/api/subscribe*` → SubscriberLambdaOrigin via CloudFront behavior
- Lambda code looks correct; sender = `lifeplatform@mattsusername.com`

**Likely issue:** `lifeplatform@mattsusername.com` may not be verified in SES (us-west-2).

**To diagnose:** Run:
```
aws sesv2 list-email-identities --region us-west-2
aws logs tail /aws/lambda/email-subscriber --since 7d
```

If `lifeplatform@mattsusername.com` is not in the list, verify it:
```
aws sesv2 create-email-identity --email-address lifeplatform@mattsusername.com --region us-west-2
```
Then click the confirmation link sent to that inbox.

### G-8: Privacy page email — PENDING MATTHEW CONFIRMATION

Current email in `site/privacy/index.html`: `matt@averagejoematt.com`
Spec suggests updating to `awsdev@mattsusername.com` or another address.

**Matthew: please confirm the correct contact email** and then run:
```
# Replace in privacy page
# Edit site/privacy/index.html — 3 occurrences of matt@averagejoematt.com
aws s3 cp site/privacy/index.html s3://matthew-life-platform/site/privacy/index.html
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/privacy/*"
```

---

## Deployment Commands

Run these in order after reviewing changes:

```bash
# 1. Deploy Lambda
bash deploy/deploy_lambda.sh life-platform-site-api lambdas/site_api_lambda.py

# 2. Wait 10s for Lambda propagation
sleep 10

# 3. Deploy site files
aws s3 cp site/index.html s3://matthew-life-platform/site/index.html
aws s3 cp site/story/index.html s3://matthew-life-platform/site/story/index.html
aws s3 cp site/platform/index.html s3://matthew-life-platform/site/platform/index.html
aws s3 cp site/protocols/index.html s3://matthew-life-platform/site/protocols/index.html

# 4. Invalidate CloudFront
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE \
  --paths "/" "/story/*" "/platform/*" "/protocols/*"
```

---

## Known Remaining Issues (Not Phase 0)

1. `public_stats.json.vitals.weight_lbs = null` — generated by daily-brief Lambda with the same
   weight-lookup bug. Now that `/api/vitals` is fixed, the daily-brief Lambda needs the same fix
   (use `_latest_item` instead of date-windowed query). Fix in a dedicated daily-brief session.

2. `public_stats.json.journey.progress_pct = 0` — same cause as above. Fix daily-brief Lambda.

3. `public_stats.json.platform` missing `tier0_streak` — the streak in the ticker comes from
   `platform.tier0_streak` but this field isn't in public_stats.json. Currently defaults to 0.
   Need daily-brief Lambda to add this field.

4. `test_count` and `monthly_cost` not in public_stats.json — needed for STORY-1 full wiring.
