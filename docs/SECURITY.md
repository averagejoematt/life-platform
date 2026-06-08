# Security Posture

**Last updated:** 2026-05-19 (v8.0.0)

> What we protect against, what we accept as risk, and the layered defenses in place. Reviewed quarterly.

---

## Threat model (top-3 realistic threats)

1. **API key / OAuth token leak** — anthropic-api-key, garmin tokens, etc. exposed via accidental git commit, screenshot, or external service compromise.
2. **Public AI endpoint abuse** — `/api/ask` and `/api/board_ask` hit by a bot, racking up Anthropic charges.
3. **Account compromise** — AWS root or matthew-admin credentials leaked or phished.

Lower-probability but mentioned in ADR-053/055/057:
- Inbound webhook spoofing (Health Auto Export from random sources)
- Outbound SES abuse (impersonation if account compromised)
- Subscriber data leak (~50 subscriber records in DDB)

---

## Defense in depth

### Layer 1 — Identity & access (IAM)

- ✅ **Per-Lambda execution roles** (one role per function, scoped least-privilege)
- ✅ **OIDC federation for GitHub Actions** — no long-lived AWS access keys committed
- ✅ **AWS root account locked down** with MFA — used only for billing
- ✅ **Inline policies preferred** over managed policies (smaller blast radius)
- ✅ **Resource ARNs scoped** — e.g. `secretsmanager:GetSecretValue` restricted to `life-platform/*`
- ❌ **No IAM Access Analyzer findings remediation** — manual sweep monthly

**Rotation cadence:**
- AWS access keys: 90 days (calendar reminder)
- Lambda execution role permissions: reviewed each ADR
- 5 orphan roles deleted 2026-05-19 (life-platform-digest-role, og-image-role, measurements-ingestion-role, pipeline-health-check-role, subscriber-onboarding-role)

### Layer 2 — Secrets management

- ✅ **Secrets Manager only** — never `.env` files, never hardcoded
- ✅ **`life-platform/*` namespace** — 12 active secrets + 3 in deletion window
- ✅ **15-min in-Lambda caching** via `secret_cache.py` — reduces SM API calls ~90%
- ✅ **mcp-api-key auto-rotates** every 90 days via `key_rotator_lambda`
- ⚠️ **anthropic-api-key NO programmatic rotation** — manual at console.anthropic.com (Anthropic doesn't expose a rotation API)
- ⚠️ **OAuth tokens (Whoop, Garmin, Strava, Withings)** — auto-refreshed on use; manual fallback ~180 days
- ✅ **No tokens in CloudWatch logs** — confirmed via grep of recent log streams

See `docs/SECRETS_MAP.md` for full secret inventory + rotation cadence.
See `docs/SECRETS_ROTATION.md` for rotation procedures.

### Layer 3 — Public endpoints (CloudFront → site-api/site-api-ai)

- ⚠️ **WAF removed** — `life-platform-amj-waf` was **deleted** (2026-06, ~−$8/mo). Rate limiting is now entirely **in-Lambda (DDB-backed)**, which is durable across warm containers and was hardened in PG-10. (NB: `cdk/stacks/web_stack.py` may still reference the dead WAF ARN — flagged for cleanup before the next `cdk deploy LifePlatformWeb`.)
- ✅ **In-app rate limiting** (DDB-backed, PG-10 hardened):
  - `/api/ask`: 5/hr anon, 20/hr subscriber
  - `/api/board_ask`: 5/IP/hour
  - `/api/subscribe`: 60 req / 5 min / IP (DDB atomic counter)
- ✅ **AI cost caps** — per-request `max_tokens` (300–600) + 500-char input cap + reserved concurrency=2; Bedrock spend visible per-endpoint via `LifePlatform/AI`; the $75 cost-governor pauses public AI at tier 2.
- ✅ **CORS pinned** to `https://averagejoematt.com` only
- ✅ **CSP headers** on all responses (no `unsafe-eval`, `script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net`)
- ✅ **HSTS** max-age 1 year, includeSubDomains
- ⚠️ **`'unsafe-inline'` still in script-src** (V2 P6.2 deferred — inline JS extraction is risky for cosmetic benefit)

### Layer 4 — Data at rest

- ✅ **DynamoDB:** customer-managed KMS key (CMK) `life-platform-dynamodb` — rotation enabled, audit via CloudTrail
- ✅ **S3:** AES256 (managed) — explicitly chosen after V2 P5.1 rolled back CMK
  - Rationale: S3 website endpoint cannot serve KMS-encrypted objects to anonymous CloudFront (ADR-053)
  - S3 CMK retained but disabled, scheduled for deletion 2026-06-16
- ✅ **Secrets Manager:** AWS-managed encryption (every secret)
- ✅ **CloudWatch Logs:** AES256 (managed); 30-day retention default on new groups (V2 P2.3)
- ❌ **PII tagging:** in `docs/DATA_GOVERNANCE.md` only; not enforced at storage layer

### Layer 5 — Data in transit

- ✅ **TLS 1.2+** enforced everywhere (CloudFront, API Gateway, Lambda HTTPS endpoints)
- ✅ **Anthropic API** over HTTPS (urllib stdlib)
- ✅ **Garmin / Whoop / etc. OAuth** over HTTPS to their endpoints
- ✅ **SES outbound** encrypted at AWS edge

### Layer 6 — Audit & forensics

- ✅ **CloudTrail management events** — all AWS API calls logged
- ✅ **CloudTrail data events** (V2 P1.7) — S3 GetObject/PutObject on `matthew-life-platform/raw/*` and `uploads/*`
- ✅ **90-day CloudTrail retention** in dedicated bucket
- ⚠️ **No SIEM integration** — manual investigation only (`aws cloudtrail lookup-events`)
- ✅ **CloudWatch Logs Insights** queries for behavioral anomalies (e.g. failed auth bursts)

### Layer 7 — Backups & recovery

See `docs/DISASTER_RECOVERY.md`. Summary:
- DDB PITR 35 days
- S3 versioning enabled
- Lambda deploy artifacts (`previous.zip`) for rollback
- Cross-region replication NOT enabled (accepted risk)

### Layer 8 — Endpoint hardening

- ✅ **HAE webhook signature check** — HMAC verifies request body (ADR ≈ P2.7)
- ✅ **MCP Bearer token auth** — HMAC-derived bearer required on all MCP tool calls
- ✅ **No public Function URLs without auth** — `chronicle-approve` was flagged as `authType=NONE` but resides behind the dormant chronicle workflow; re-evaluate if reactivated
- ✅ **Public Function URLs (mcp, site-api, site-api-ai)**: app-layer Bearer/API-key required in code

---

## Active mitigations for known abuse vectors

| Vector | Mitigation |
|---|---|
| Bot scans of WordPress admin paths | CloudFront returns 404 (no backend hit) |
| Bedrock spend runaway via `/api/ask` | DDB rate limit 5/hr per IP + `max_tokens` cap + reserved concurrency=2 + cost-governor tier-2 pause + token telemetry per-endpoint |
| Subscriber email scraping | DDB partitioned by `USER#matthew` — no public list endpoint |
| HAE webhook spoofing | HMAC signature required (ADR-052 follow-up) |
| OAuth token theft | 15-min secret cache + 24h auth_breaker — first failed auth marks DDB record; subsequent attempts short-circuit |

---

## Open security gaps (accepted as documented risk)

| Gap | Documented in | Reopen if |
|---|---|---|
| `'unsafe-inline'` in CSP | ADR-057 W-08 | XSS becomes a real threat |
| No cross-region DR | ADR-057 W-03 | Regulated data or SLA |
| Anthropic API key has no rotation API | docs/SECRETS_ROTATION.md | Anthropic ships one |
| Per-user secrets isolation | ADR-057 W-02 | Second user onboards |
| IAM Access Analyzer findings not remediated | This doc | Annual security review |
| No SIEM integration | This doc | Compliance requirement |

---

## Quarterly security checklist

Every 3 months (next: 2026-08-19):

```bash
# 1. Verify all secrets rotated within their cadence
aws secretsmanager list-secrets --region us-west-2 \
    --query 'SecretList[].[Name,LastChangedDate,LastRotatedDate]' --output table

# 2. Check for orphan IAM roles
aws iam list-roles --query 'Roles[?contains(RoleName, `life-platform`)].[RoleName,RoleLastUsed.LastUsedDate]' --output table
# Any unused > 60 days → consider deleting

# 3. Check public S3 buckets (should be none allowing public READ)
aws s3api list-buckets --query 'Buckets[].Name' --output text | tr '\t' '\n' \
    | xargs -I{} aws s3api get-bucket-policy-status --bucket {} 2>/dev/null \
    | grep -B1 'IsPublic.*true'

# 4. Review in-Lambda rate-limit hits (WAF removed; rate limiting is DDB-backed)
aws cloudwatch get-metric-statistics --namespace LifePlatform/SiteApiAi \
    --metric-name RateLimitHit --start-time $(date -u -v-7d '+%Y-%m-%dT%H:%M:%S') \
    --end-time $(date -u '+%Y-%m-%dT%H:%M:%S') --period 86400 --statistics Sum --region us-west-2

# 5. Audit CloudTrail for unusual API calls
aws cloudtrail lookup-events --region us-west-2 \
    --lookup-attributes AttributeKey=EventName,AttributeValue=DeleteBucket \
    --start-time $(date -u -v-90d '+%Y-%m-%dT%H:%M:%S')

# 6. Confirm CSP / security headers active
curl -I https://averagejoematt.com/ | grep -E 'Strict-Transport|Content-Security|X-Frame|X-Content'
```

Document findings in `docs/INCIDENT_LOG.md` as "Security review YYYY-MM-DD" entry.

---

## Incident response — see also

- `docs/DISASTER_RECOVERY.md` Scenario 5 — Account compromise sequence
- `docs/INCIDENT_LOG.md` — historical incidents

---

**Verified:** 2026-05-19
