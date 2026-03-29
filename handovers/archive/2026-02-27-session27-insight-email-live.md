# Session 27 — Insight Email Pipeline Live + S3 Investigation Started

**Date:** 2026-02-27
**Version:** v2.39.0 (no version bump — deployment/config of v2.37.0 feature)
**Previous session:** Session 26 (insight email deploy scripts created)

---

## What Was Done

### 1. Insight Email Pipeline — Fully Deployed & Tested ✅

Completed the end-to-end deployment of Feature #21 (Insight Email Parser) that was built in v2.37.0 and scripted in Session 26.

**Deployment steps executed:**
- `deploy_insight_email_v1.1.sh` — deployed insight-email-parser v1.1.0 Lambda code
  - Race condition on `UpdateFunctionConfiguration` (code upload in progress) — manually ran env var update after 10s wait
  - `ALLOWED_SENDERS` set to `awsdev@mattsusername.com` + `mattsthrowaway@protonmail.com` (added during testing)
- `deploy_insight_email_pipeline.sh` — created SES receipt rule set, S3 bucket policy, receipt rule, S3→Lambda notification
  - Receipt rule set: `life-platform-inbound` (active)
  - Receipt rule: `insight-capture` → S3 `raw/inbound_email/` → Lambda trigger
  - S3 notifications: `InboundEmailInsightParser` on `raw/inbound_email/` prefix

**DNS setup in Cloudflare:**
- MX record: `aws` → `inbound-smtp.us-west-2.amazonaws.com` (priority 10, DNS only)
- TXT record: `_amazonses.aws` → SES verification token
- SES domain verification: `aws.mattsusername.com` → **Success**

**End-to-end test results:**
- ✅ Email received by SES at `insight@aws.mattsusername.com`
- ✅ Stored in S3 `raw/inbound_email/`
- ✅ Lambda triggered, parsed email
- ✅ Sender whitelist working (rejected unauthorized sender, then accepted after adding to allowed list)
- ✅ Insight saved to DynamoDB (`USER#matthew#SOURCE#insights`)
- ⚠️ Confirmation reply email failed (SES sandbox mode — can only send to verified addresses; Proton Mail not verified). Not a problem for production use case (replying to Daily Brief from `awsdev@mattsusername.com`)

### 2. S3 Growth Investigation — In Progress

Investigating S3 bucket growth from 34MB baseline to 2.3GB.

**Prefixes checked so far (~8.8 MiB accounted for):**
- `cloudtrail/`: 2.3 MiB (755 objects)
- `raw/apple_health/`: 1.9 MiB (3,864 files)
- `raw/health_auto_export/`: 587.5 KiB (9 files)
- `raw/strava/`: 4.0 MiB (1,165 files)
- `deployments/`: 9.2 KiB (3 files)
- `imports/`: 1.3 KiB (4 files)
- `uploads/`: 59.4 KiB (8 files)

**Remaining to check (~2.29 GB unaccounted):**
- `raw/cgm_readings/` ← likely culprit (continuous 5-min glucose data)
- `raw/whoop/` ← possible (continuous data)
- `raw/eightsleep/`, `raw/garmin/`, `raw/macrofactor/`, `raw/todoist/`, `raw/weather/`, `raw/withings/`
- `dashboard/`, `tmp/`

---

## What Needs Follow-Up

1. **Complete S3 investigation** — check remaining raw/ subdirectories to find the 2.29 GB
2. **SES sandbox lift** — if confirmation emails are desired for non-SimpleLogin addresses, request SES production access. Low priority since primary use case (Daily Brief reply) uses verified domain
3. **Test Daily Brief reply flow** — next Daily Brief should include `Reply-To: insight@aws.mattsusername.com`. Reply to it from `awsdev@mattsusername.com` to verify the real workflow
4. **Dashboard verification** — confirm `https://dash.averagejoematt.com/` loads (DNS propagation from Session 25)

---

## Context for Next Session

- **Platform:** v2.39.0, 88 MCP tools, 22 Lambdas, 18 data sources
- **Insight email pipeline:** LIVE and tested end-to-end
- **S3 investigation:** ~8.8 MiB accounted for, ~2.29 GB remaining
- **Remaining roadmap:** Monarch Money (#1), Google Calendar (#2), Annual Health Report (#13), infrastructure items (#14-20, #23-24)
