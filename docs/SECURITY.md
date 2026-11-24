# Security Posture

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-10-17

**Last updated:** 2026-05-19 (v8.0.0)

> What we protect against, what we accept as risk, and the layered defenses in place. Reviewed quarterly.

---

## Threat model (top-3 realistic threats)

1. **API key / OAuth token leak** — `ai-keys` / `site-api-ai-key`, Whoop/Strava/Withings tokens, etc. exposed via accidental git commit, screenshot, or external service compromise.
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
- ✅ **Human access = IAM Identity Center SSO** (short-lived sessions); long-lived `matthew-admin` keys are break-glass only — the single authoritative procedure is `docs/AWS_ACCESS.md`
- ✅ **AWS root account locked down** with MFA — used only for billing
- ✅ **Inline policies preferred** over managed policies (smaller blast radius)
- ✅ **Resource ARNs scoped** — e.g. `secretsmanager:GetSecretValue` restricted to `life-platform/*`
- ❌ **No IAM Access Analyzer findings remediation** — manual sweep monthly

**Rotation cadence:**
- AWS access keys (break-glass `matthew-admin` only — see `docs/AWS_ACCESS.md` §3): 90 days (calendar reminder)
- Lambda execution role permissions: reviewed each ADR
- 5 orphan roles deleted 2026-05-19 (life-platform-digest-role, og-image-role, measurements-ingestion-role, pipeline-health-check-role, subscriber-onboarding-role)

### Layer 2 — Secrets management

- ✅ **Secrets Manager only** — never `.env` files, never hardcoded
- ✅ **`life-platform/*` namespace** — 28 secrets live in us-west-2 (`aws secretsmanager list-secrets`, count re-read 2026-10-17; the reconciled inventory is `docs/SECRETS_MAP.md`)
- ✅ **15-min in-Lambda caching** via `secret_cache.py` — reduces SM API calls ~90%
- ✅ **mcp-api-key auto-rotates** every 90 days via `lambdas/operational/key_rotator_lambda.py` (`life-platform-key-rotator`; rotation enabled, 90-day rule, live-verified 2026-10-17)
- ⚠️ **Legacy Anthropic keys (`ai-keys`, `site-api-ai-key`) — NO programmatic rotation** — manual at console.anthropic.com (Anthropic doesn't expose a rotation API); runtime inference is Bedrock/IAM (ADR-062), so these are fallback paths
- ⚠️ **OAuth tokens (Whoop, Strava, Withings; Garmin retired 2026-10-11, #4640)** — auto-refreshed on use; manual fallback ~180 days
- ✅ **No tokens in CloudWatch logs** — confirmed via grep of recent log streams

See `docs/SECRETS_MAP.md` for full secret inventory + rotation cadence.
See `docs/SECRETS_ROTATION.md` for rotation procedures.

### Layer 3 — Public endpoints (CloudFront → site-api/site-api-ai)

- ✅ **Edge rate rule on the reader write doors** (#6114, owner decision 2026-11-16): ONE WebACL `life-platform-amj-reader-writes` on the main distribution only, default ALLOW, one rate-based rule (`ReaderWritePostRate`) — POSTs to the reader write doors, 100 per IP per 5 min, blocked with a JSON 429 marked `"limiter": "edge"`. Spec + measured limit: `cdk/stacks/web_edge_rate_rule.py`; scope guard: `tests/test_edge_rate_rule_6114.py`. A flood backstop only — WAF counts each IPv6 address separately, so the in-Lambda limiters below stay the per-route, per-network control. (History: the broad SEC-02 `life-platform-amj-waf` was deleted 2026-06; the new ACL is declared in the same stack as the distribution and associated by GetAtt, never a pasted ARN.)
- ✅ **In-app rate limiting** (DDB-backed, PG-10 hardened):
  - `/api/ask`: 5/hr anon, 20/hr subscriber
  - `/api/board_ask`: 7 Bedrock calls/IP/hour (`BOARD_RATE_LIMIT` in `lambdas/web/site_api_ai_lambda.py` — a fan-out budget, one token per persona, so one full board per IP per hour)
  - `/api/subscribe`: 60 req / 5 min / IP (DDB atomic counter)
- ✅ **AI cost caps** — per-request `max_tokens` (300–600) + 500-char input cap + reserved concurrency=2; Bedrock spend visible per-endpoint via `LifePlatform/AI`; the cost-governor ($215/month ceiling, $252 in reader-traffic surge mode — ADR-063/ADR-133) pauses public AI at the tier-3 hard stop (ADR-125).
- ✅ **CORS pinned** to `https://averagejoematt.com` and `https://www.averagejoematt.com` only (`allowed_origins` in `cdk/stacks/serve_stack.py`)
- ✅ **CSP headers** on all responses — live main-domain policy is `script-src 'self'` (no `unsafe-inline`, no `unsafe-eval`, no CDN; #3048 / DIL-015; built in `cdk/stacks/csp.py`, curl-verified 2026-10-17). `style-src` still carries `'unsafe-inline'`
- ✅ **HSTS** max-age 1 year, includeSubDomains
- ✅ **`'unsafe-inline'` is out of script-src** on the main domain (#3048 closed the old V2 P6.2 deferral); only the `style-src` inline allowance remains

### Layer 4 — Data at rest

- ✅ **DynamoDB:** customer-managed KMS key (CMK) `life-platform-dynamodb` — rotation enabled, audit via CloudTrail
- ✅ **S3:** AES256 (managed) — explicitly chosen after V2 P5.1 rolled back CMK
  - Rationale: S3 website endpoint cannot serve KMS-encrypted objects to anonymous CloudFront (ADR-053)
  - The S3 CMK is gone (no customer-managed key besides `life-platform-dynamodb` exists in us-west-2, 2026-10-17)
- ✅ **Secrets Manager:** AWS-managed encryption (every secret)
- ✅ **CloudWatch Logs:** AES256 (managed); 30-day retention default on new groups (V2 P2.3)
- ❌ **PII tagging:** in `docs/DATA_GOVERNANCE.md` only; not enforced at storage layer

### Layer 5 — Data in transit

- ✅ **TLS 1.2+** enforced everywhere (CloudFront, API Gateway, Lambda HTTPS endpoints)
- ✅ **Anthropic API** over HTTPS (urllib stdlib)
- ✅ **Whoop / Withings / Strava / etc. OAuth** over HTTPS to their endpoints
- ✅ **SES outbound** encrypted at AWS edge

### Layer 6 — Audit & forensics

- ✅ **CloudTrail management events** — all AWS API calls logged
- ✅ **CloudTrail data events** (V2 P1.7) — S3 GetObject/PutObject on `matthew-life-platform/raw/*` and `uploads/*`
- ✅ **90-day CloudTrail retention** — trail `life-platform-trail` writes under the `cloudtrail/` prefix of `matthew-life-platform`, with lifecycle rule `cloudtrail-expire-90d` (live-verified 2026-10-17; not a dedicated bucket)
- ⚠️ **No SIEM integration** — manual investigation only (`aws cloudtrail lookup-events`)
- ✅ **CloudWatch Logs Insights** queries for behavioral anomalies (e.g. failed auth bursts)

### Layer 7 — Backups & recovery

See `docs/DISASTER_RECOVERY.md`. Summary:
- DDB PITR 35 days
- S3 versioning enabled
- Lambda deploy artifacts (`previous.zip`) for rollback
- **Cross-region replication of `raw/*` → `matthew-life-platform-raw-backup` (us-east-2)** —
  DIL-027, #3042. The `raw/` zone (original wearable/API captures) is the platform's only
  unrecomputable data; everything else rebuilds from it plus git. The replica is versioned,
  public-access-blocked, `RETAIN`, carries its own delete-protection Deny, and does **not**
  replicate delete markers, so a delete on the source does not propagate. Asserted by the
  infra drift sentinel (`deploy/drift_sentinel.py` → `deploy/sentinel_replication.py`, on the remediation-agent's cron cadence).
- ⚠️ **Nothing outside `raw/` is replicated, and the backup is in the SAME ACCOUNT** — it
  survives a regional failure and the primary bucket's destruction, not an account-level
  compromise. `aws organizations list-accounts` shows one account, so cross-account has no
  destination today. Dated priced acceptance + revisit triggers:
  `docs/reviews/DILIGENCE_2026-08-23_RESPONSE.md` (DIL-027).
- ⚠️ **The restore has not been drilled** — the configuration is asserted, the recovery is not.
  Owner-present timed restore drill is a scheduled appointment.

### Layer 8 — Endpoint hardening

- ✅ **HAE webhook bearer check** — `Authorization: Bearer` token compared in constant time (`hmac.compare_digest`) in `lambdas/ingestion/health_auto_export_lambda.py` (Phase 2.7); the `?key=` query fallback was removed (#500). It is a shared-secret check, not a body HMAC
- ✅ **MCP auth, fully hardened 2026-07-10 (#893 A+B):** Desktop path keeps the static HMAC bearer (`life-platform/mcp-api-key`, auto-rotated 90d); the remote OAuth path now mints **short-lived, revocable SESSION bearers** at `/token` (#909) and `/authorize` is a **passcode consent gate** with a 30-day remembered-browser cookie (#912) — URL possession alone yields nothing. NB: the Function URL itself appears in historical `docs/reviews/` bundles from the repo's public era; the control is this auth model + repo visibility, not URL secrecy.
- ✅ **Function URLs with `AuthType=NONE` carry application-layer auth** — `chronicle-approve` is live (`AuthType NONE`, verified 2026-10-17) and gated by the per-draft 32-byte token validated against DynamoDB; the Telegram webhook gates on the echoed secret token
- ✅ **Public Function URLs (mcp, site-api, site-api-ai)**: app-layer Bearer/API-key required in code

---

## Active mitigations for known abuse vectors

| Vector | Mitigation |
|---|---|
| Bot scans of WordPress admin paths | CloudFront returns 404 (no backend hit) |
| Bedrock spend runaway via `/api/ask` | DDB rate limit 5/hr per IP + `max_tokens` cap + reserved concurrency=2 + cost-governor tier-2 pause + token telemetry per-endpoint |
| Subscriber email scraping | DDB partitioned by `USER#matthew` — no public list endpoint |
| HAE webhook spoofing | Bearer token, constant-time compare (ADR-052 follow-up) |
| OAuth token theft | 15-min secret cache + 24h auth_breaker — first failed auth marks DDB record; subsequent attempts short-circuit |

---

## Open security gaps (accepted as documented risk)

| Gap | Documented in | Reopen if |
|---|---|---|
| `'unsafe-inline'` in CSP `style-src` (script-src is clean since #3048) | ADR-057 W-08 | XSS becomes a real threat |
| No cross-region DR **for anything except `raw/`** (partially closed 2026-08-24, DIL-027 — `raw/*` now replicates to us-east-2; DDB, generated artifacts and the site remain single-region, all recomputable from `raw/` + git) | ADR-057 W-03 | Regulated data or SLA |
| **Backup is in the same AWS account** (DIL-027 residual — dated priced acceptance 2026-08-24) | `docs/reviews/DILIGENCE_2026-08-23_RESPONSE.md` | A second AWS account exists · the restore drill finds the replica unusable · commercialization / second user / regulated obligation · otherwise re-read 2027-02-24 |
| Anthropic API key has no rotation API | docs/SECRETS_ROTATION.md | Anthropic ships one |
| Per-user secrets isolation | ADR-057 W-02 | Second user onboards |
| IAM Access Analyzer findings not remediated | This doc | Annual security review |
| No SIEM integration | This doc | Compliance requirement |
| **GuardDuty + AWS Config not enabled** | **ADR-079** | Second/real user, commercial/compliance obligation, or budget headroom (cost ~$5–10/mo on a $215 ceiling; compensating controls: CloudTrail + cost-governor + least-priv IAM + MFA) |

---

## GitHub token inventory (#4257, measured 2026-10-01)

GitHub Actions reaches AWS through OIDC only (no stored AWS keys — `docs/AWS_ACCESS.md` §4).
The repo secrets below are the GitHub-side credentials. Measured with
`gh api repos/averagejoematt/life-platform/actions/secrets` (names + `updated_at` only — the
API never returns a value or an expiry) and `grep -rn 'secrets\.' .github/`.

| Secret | Set / last rotated | Read by | Least scope | Could `GITHUB_TOKEN` replace it? |
|---|---|---|---|---|
| `RECONCILE_PUSH_TOKEN` | 2026-11-23 (regenerated on GitHub's 7-day expiry notice; new PAT set to **no expiry**) | `ci-cd.yml` `reconcile` (checkout `token:`, falls back to `github.token`) | fine-grained, this repo only, Contents: read-and-write | **No.** The `main-required-fast-lane` ruleset's bypass actor is a `User` (#2198); `GITHUB_TOKEN` authenticates as `github-actions[bot]`, which that bypass does not match |
| `GH_BILLING_TOKEN` | 2026-07-26 | `remediation-agent.yml` → `deploy/sentinel_quota.py` (also mirrored in Secrets Manager `life-platform/github-billing`) | user-scoped, billing-usage read only | **No.** `GET /users/{owner}/settings/billing/usage` is a user-level endpoint |
| `GH_POSTURE_TOKEN` | **not set** (absent from the secrets list) | `remediation-agent.yml` → `deploy/sentinel_github.py` | fine-grained, this repo, Administration: read + Actions: read + Contents: read | **No.** `GITHUB_TOKEN` cannot carry Administration: read. While it is absent, the posture surfaces report `unavailable`, never green |
| `DEPLOY_GATE_JANITOR_TOKEN` | 2026-08-30 | **nothing** — its only reader, `deploy-gate-janitor.yml`, was deleted by #4497 | — | Not needed at all. **Owner act: delete the secret** and revoke the PAT |
| `CONTENT_FILTER_JSON` | 2026-08-12 | `ci-lint` content-filter channel | — (vocabulary, not a token) | n/a |

**Expiry is not recorded here** because no API this repo can call returns it; the owner reads
it from github.com/settings/personal-access-tokens and adds it to this table. That makes
this inventory's expiry column the one open item of issue 4257's PAT box.

## Quarterly security checklist

Every 3 months (last recorded due date 2026-08-19; no "Security review" row exists in `docs/INCIDENT_LOG.md`, so the next one is owed — owner call):

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

# 4. Review in-Lambda rate-limit hits (the per-route limiters are DDB-backed; the #6114 edge rule's
#    blocks are AWS/WAFV2 BlockedRequests, Rule=ReaderWritePostRate, WebACL=life-platform-amj-reader-writes, us-east-1)
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

**Verified:** 2026-10-17
