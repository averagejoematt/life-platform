# Phase 3: Security / IAM Review
**Date:** 2026-02-28 | **Version:** v2.47.1 | **Reviewer:** Claude (Expert Panel)

---

## 3.1 IAM Role Architecture

**Grade: A-** — Strong least-privilege design with per-Lambda roles. One shared role is documented and justified.

### Strengths
- 20 dedicated IAM roles for 22 Lambdas — excellent isolation
- No role has `dynamodb:Scan` — prevents accidental full-table reads
- No cross-account permissions — single-account, single-region design
- Secrets Manager access scoped to specific secret ARNs per role
- SES SendEmail scoped to `mattsusername.com` domain identity
- DLQ send permissions added via inline policies

### Findings

#### F3.1 — Shared digest role is a broad permission surface (MEDIUM)
`lambda-weekly-digest-role` is shared by `daily-brief`, `weekly-digest`, and `monthly-digest`. This role has: DynamoDB read/write, Secrets Manager (Anthropic key), SES SendEmail, S3 PutObject on `dashboard/*`. The daily brief writes day_grade, habit_scores, and dashboard JSON — the weekly and monthly digests don't need write access to most of these.

**Risk:** A bug in the monthly digest could theoretically write bad data to day_grade or habit_scores partitions.

**Recommendation:** Consider splitting into `lambda-daily-brief-role` (full write access) and `lambda-digest-read-role` (read-only DDB + SES + S3 write to clinical.json only). Medium effort, modest security improvement. Not urgent.

#### F3.2 — MCP Lambda PutItem permission is necessary but broad (LOW)
The MCP role has `PutItem` because it doubles as cache warmer and manages supplements/travel/insights/experiments. This is justified but means any tool could theoretically write to any partition.

**Mitigation:** The MCP code only writes to CACHE, supplements, travel, insights, experiments, and state_of_mind partitions. The risk is code bugs, not external attacks. Acceptable.

#### F3.3 — No IAM policy version pinning (INFO)
IAM policies use inline policies rather than managed policies. This is fine for a personal platform (easier to manage), but there's no change tracking. The deploy MANIFEST helps but doesn't capture IAM state.

**Recommendation:** Consider periodically exporting IAM policies to a `security/` directory for documentation. Low priority.

---

## 3.2 Network / Endpoint Security

#### F3.4 — MCP Function URL: AuthType NONE with CORS AllowOrigins: ["*"] (MEDIUM)
The Function URL has `AuthType: NONE` and allows all origins. Authentication is handled in the Lambda code via `x-api-key` header (checked against Secrets Manager). This is necessary for claude.ai's MCP connector to work (it can't send IAM signatures).

**Risk:** The endpoint is publicly accessible. Anyone who discovers the URL can send requests — they'll be rejected without the API key, but they can still probe the endpoint and cause Lambda invocations (billing).

**Mitigations in place:**
- API key validation in Lambda code (returns 401 without valid key)
- HMAC Bearer token validation (mentioned in PROJECT_PLAN)
- Lambda concurrency is uncapped (could be a cost risk under abuse)

**Recommendations:**
1. **Set reserved concurrency on MCP Lambda** (e.g., 10). This caps max concurrent invocations and prevents a DDoS from running up your bill. Simple, effective, free. **HIGH PRIORITY.**
2. The roadmap mentions WAF rate limiting (#14 at $5/mo) — the reserved concurrency approach achieves 80% of the protection for $0.
3. Consider adding a `User-Agent` or custom header check as a lightweight additional barrier.

#### F3.5 — API Gateway webhook has no rate limiting (LOW)
`health-auto-export-api` accepts POST requests with bearer token auth. No rate limiting configured. Since the token is a simple bearer token (not rotating), if it leaked, anyone could push data.

**Recommendation:** Add a usage plan with a daily quota (e.g., 100 requests/day — you only need ~6 at 4-hour intervals). This prevents abuse if the token is compromised. Free to configure.

#### F3.6 — S3 bucket policy is correctly scoped (POSITIVE)
- Public read only on `dashboard/*` — all other objects remain private
- BlockPublicAcls=true, IgnorePublicAcls=true — prevents accidental ACL-based exposure
- BlockPublicPolicy=false (required for static site hosting) — documented and expected
- SES PutObject scoped to source account condition — good

No action needed.

---

## 3.3 Secrets Management

**Grade: A-**

- 12 secrets in Secrets Manager — proper credential storage
- OAuth tokens self-heal on each Lambda invocation
- MCP API key stored in Secrets Manager, not in code or env vars

#### F3.7 — No automatic secret rotation (LOW)
Secrets Manager supports automatic rotation with a Lambda rotator. None of the 12 secrets have rotation enabled. For OAuth secrets this doesn't matter (they self-rotate on use). For static API keys (Todoist, Habitify, Notion, MCP), rotation would be a nice-to-have.

**Recommendation:** The PROJECT_PLAN has item #15 (MCP API key rotation, 30 min effort). This is the most impactful — it's the only secret that protects a public-facing endpoint. Schedule it.

#### F3.8 — Withings OAuth fragility documented but not mitigated (LOW)
If the Withings Lambda is down for >24h, the rotating refresh token expires and requires browser re-authorization. This happened during the Feb 28 outage and is documented in the PIR.

**Recommendation:** The `fix_withings_oauth.py` script exists for recovery. Consider adding a monitoring check: if the Withings Lambda fails 2 consecutive days, send a specific "OAuth may expire soon" alert rather than the generic freshness alert.

---

## 3.4 Data Security

#### F3.9 — Dashboard data.json is publicly accessible (INFO)
`data.json` (written by daily brief) and `clinical.json` (written by weekly digest) are publicly readable via CloudFront. These contain health metrics including weight, sleep scores, HRV, etc.

**Current state:** The URLs are not indexed by search engines, and the CloudFront distribution doesn't have a robots.txt. Security through obscurity.

**Recommendation:** If you're comfortable with the current approach, no action needed. If you want to restrict access, consider CloudFront Functions with a simple cookie/token check, or move to a signed URL approach. This would be a larger change.

#### F3.10 — No encryption at rest for S3 (LOW)
S3 default encryption applies (SSE-S3), which is fine. DynamoDB encryption at rest is enabled by default (AWS managed key). No action needed.

---

## 3.5 Summary

| Area | Grade | Critical Findings | Action Items |
|------|-------|-------------------|-------------|
| IAM Roles | A- | Shared digest role is broad | Consider splitting (low priority) |
| Network Security | B+ | MCP Function URL uncapped concurrency | **Set reserved concurrency (HIGH)** |
| Secrets | A- | No rotation on MCP API key | Implement rotation (#15) |
| Data Security | B+ | Dashboard JSON publicly accessible | Acceptable risk for now |

**Top 3 recommendations (priority order):**
1. **Set reserved concurrency on life-platform-mcp Lambda** (5 min, $0, prevents cost abuse) — `aws lambda put-function-concurrency --function-name life-platform-mcp --reserved-concurrent-executions 10 --region us-west-2`
2. **Add API Gateway usage plan** with daily quota on health-auto-export-api (15 min, $0)
3. **Implement MCP API key rotation** (roadmap item #15, 30 min)
