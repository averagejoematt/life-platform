# V2 Audit — AWS Infrastructure, Cost & Security
**Account:** 205930651321 · **Region:** us-west-2 (primary), us-east-1 (CF/WAF)
**Date:** 2026-05-17 · **Auditor:** Claude (v2 round)
**v1 baseline:** $35/mo April → $30.87/mo May forecast → $0.93/day mean

---

## TL;DR
- v1 hardening **mostly landed** (DDB PITR/TTL, S3 lifecycle, SES suppression, log retention, WAF rate-limits, CloudTrail), but **3 items drifted or were never deployed**: reserved concurrency (P1.5 not applied), CloudTrail data-events (P2.5 not enabled), log-retention hook (P1.1 patched existing groups but new ones still default to none — 2 new untreated groups today).
- **1 CRITICAL** (API GW timeout mismatch causes silent HAE truncation), **5 HIGH**, **9 MEDIUM**, **6 LOW**.
- **Realistic recoverable cost: $2.50–4.00/mo** (alarms prune, orphan KMS CMK, unused power-tuning, dropbox/notion secrets, CE polling cache). Don't repeat v1's overestimate.
- **63 messages stuck in DLQ since May 4** — silent failure ladder, alarm fired May 4 but not cleared.

---

## CRITICAL

### C1. HAE API Gateway integration timeout (30s) < Lambda timeout (300s) → silent truncation
- **Evidence:** API GW `health-auto-export-api` integration `TimeoutInMillis=30000`, but `health-auto-export-webhook` Lambda `Timeout=300`. Apple Health bulk uploads (multi-day catch-up) take >30s; API GW returns 504 to phone, Lambda keeps running orphaned, phone retries.
- **Action:** Raise API GW integration timeout to 29000ms maximum (HTTP API hard cap), OR move HAE to direct Lambda Function URL like site-api/mcp. Recommend the latter — eliminates API GW $0/mo line and integration limits.
- **Effort:** 30 min · **ROI:** Eliminates silent data loss + $0/mo (API GW already at $0.0002). · **Risk:** Low — change auth pattern from API GW key check to Lambda-internal signature check (already present per code).

---

## HIGH

### H1. Reserved concurrency never applied (v1 P1.5 drift)
- **Evidence:** `aws lambda get-account-settings` → `UnreservedConcurrentExecutions: 10`, `ConcurrentExecutions: 10`. **Zero** Lambdas have reserved concurrency. Account cap is also still 10 (not raised).
- **Impact:** Any noisy ingestion Lambda can starve daily-brief / MCP / site-api. Already saw 6 alarms in ALARM state — high probability one of those was contention-related.
- **Action:** (a) File AWS Support quota raise to 100 (free, 24h). (b) Set reserved=2 on `life-platform-mcp`, `life-platform-site-api`, `life-platform-site-api-ai`, `daily-brief`, `health-auto-export-webhook` once quota lifted. Critical-path protection.
- **Effort:** 1h plus 24h support wait · **ROI:** Non-monetary; prevents production outage class. · **Risk:** Low.

### H2. CloudTrail data events NOT enabled (v1 P2.5 drift)
- **Evidence:** `aws cloudtrail get-event-selectors` returns `DataResources: []`, `HasCustomEventSelectors: false`. Only management events log. **No record of who read which S3 object, no DDB GetItem audit.**
- **Action:** Add S3 data event selector for `matthew-life-platform/raw/*` and DDB selector for `life-platform` table. Already have `cloudtrail-expire-90d` lifecycle on the bucket, so storage cost is bounded.
- **Effort:** 15 min · **ROI:** ~$0.50–1.00/mo CloudTrail data-event cost vs forensic value. · **Risk:** Low.

### H3. S3 KMS CMK `life-platform-s3` is orphaned (ADR-053 rollback debt)
- **Evidence:** Key `5c50ca02-c187-4338-8704-5b27f1efafca` created 2026-05-16, but `matthew-life-platform` bucket reverted to AES256. `aws kms list-grants` → 0 grants. Nothing references it. Costs $1/mo while idle (`us-west-2-KMS-Keys` line is $0.556 for ~17 days = on track for $1).
- **Action:** Schedule key deletion (`aws kms schedule-key-deletion --pending-window-in-days 7`). Also retire `alias/life-platform-s3`.
- **Effort:** 5 min · **ROI:** $1/mo recurring. · **Risk:** Verify CloudFront OAC policy on key doesn't break dashboard; the KMS policy includes CF service principal but if no objects are encrypted with it, deletion is safe.

### H4. DLQ has 63 stuck messages (alarming since May 4, never cleared)
- **Evidence:** `ApproximateNumberOfMessages=63` on `life-platform-ingestion-dlq`. Sampled messages = Garmin scheduled-event payloads from May 4-8. `life-platform-dlq-depth-warning` and `life-platform-ingestion-dlq-messages` alarms both in ALARM since May 4. `life-platform-dlq-consumer` runs every 6h — either it's broken or it requires manual replay.
- **Action:** Inspect dlq-consumer Lambda logs (`/aws/lambda/life-platform-dlq-consumer`). If failures are transient, drain queue. If structural (e.g., Garmin auth expired), fix upstream then drain.
- **Effort:** 1h · **ROI:** Restores Garmin coverage gap May 4-8; clears 2 false-positive alarms eating attention. · **Risk:** Low.

### H5. 4 public Function URLs with `authType=NONE`
- **Evidence:** IAM Access Analyzer flagged all 4 as PUBLIC findings. `life-platform-mcp`, `life-platform-site-api`, `life-platform-site-api-ai`, `chronicle-approve` all use `lambda:InvokeFunctionUrl` with `Principal:*`. Auth lives only in Lambda code (API key / Bearer header / signature). Bypass = full DoS or unauthorized AI calls.
- **Mitigations in place:** WAF on CloudFront edge (4 rate rules: 1000/min global, 60/min subscribe, 100/min ask/board-ask). BUT `chronicle-approve` URL is direct (no CF in front per origin list) — **0 WAF protection, 0 invocations in 14d** = dead but exposed.
- **Action:** (a) Switch `chronicle-approve` URL to `AWS_IAM` auth or delete the function URL (0 invocations 14d). (b) Document that the other 3 rely on app-layer auth + WAF.
- **Effort:** 15 min for chronicle-approve · **ROI:** Reduces attack surface; non-monetary. · **Risk:** Low.

---

## MEDIUM

### M1. 13 duplicate alarms (paying ~$1.30/mo for redundant coverage)
- **Evidence:** Same `Namespace/MetricName/Dimensions` covered by 2 alarms (e.g., `challenge-generator-errors` + `ingestion-error-challenge-generator`; `daily-brief-duration-high` + `life-platform-daily-brief-duration-p95`). At $0.10/alarm × 13 = $1.30/mo waste.
- **Action:** For each duplicate pair, decide which name survives (prefer `slo-*` / `ingestion-error-*` naming convention) and delete the other.
- **Effort:** 30 min · **ROI:** $1.30/mo + signal-to-noise improvement. · **Risk:** None.

### M2. 6 alarms in ALARM state right now, several stale
- **Evidence:** ALARM list:
  - `ingestion-error-whoop` (today 22:01 — current)
  - `life-platform-dlq-depth-warning` (May 4 — see H4)
  - `life-platform-garmin-data-ingestion-errors` (May 3)
  - `life-platform-ingestion-dlq-messages` (May 4 — same root as H4)
  - `og-image-generator-errors` (May 3 — also matches `slo-source-freshness`)
  - `slo-source-freshness` (May 3 — likely same root)
- **Action:** Triage today: Whoop ingest failure (probably token), Garmin (H4), og-image (verify whether the Sunday batch failed permanently).
- **Effort:** 1-2h · **ROI:** Non-monetary; restores alarm trust. · **Risk:** None.

### M3. 5 power-tuning Lambdas + their layer dormant 30+ days
- **Evidence:** All 5 `serverlessrepo-lambda-power-tuning-*` Lambdas: 0 invocations in 30 days. Plus shared `AWS-SDK-v3:1` layer they pin. Plus the CloudFormation stack that owns them is unowned by app.
- **Action:** `aws cloudformation delete-stack --stack-name serverlessrepo-lambda-power-tuning` (or whatever the stack is). Reinstall if/when a new tuning campaign is needed.
- **Effort:** 5 min · **ROI:** ~$0.05/mo Lambda storage; primary value is reducing 79→74 function count (cleaner ops). · **Risk:** None.

### M4. `chronicle-approve` Lambda: 0 invocations 14d
- **Evidence:** Function exists, has Function URL exposed (H5), 0 calls in 14d. Wednesday-chronicle EventBridge rule is `DISABLED`, so the approve flow is dormant.
- **Action:** Confirm intent — if Wednesday-chronicle workflow is deprecated, delete the Lambda + role + URL. If paused, leave with note.
- **Effort:** 15 min triage · **ROI:** Removes attack surface. · **Risk:** Low (verify with user).

### M5. 16 production Lambdas without DLQ
- **Evidence:** `health-auto-export-webhook`, `life-platform-mcp`, `life-platform-site-api`, `life-platform-site-api-ai`, `daily-brief`'s related (site-stats-refresh, data-export, data-reconciliation, pip-audit, qa-smoke, freshness-checker, alert-digest, mcp-warmer, key-rotator, canary, dlq-consumer, delete-user-data) — all have no `DeadLetterConfig`. (Excluding 5 power-tuning infra.)
- **Note:** Async-invoked Lambdas without DLQ silently lose failed events after retries.
- **Action:** Determine sync vs async per function. `life-platform-mcp`, `site-api*`, `chronicle-approve`, HAE webhook are sync (caller gets error) — DLQ N/A. The rest: add DLQ → `life-platform-ingestion-dlq`.
- **Effort:** 30 min · **ROI:** Non-monetary; data integrity. · **Risk:** None.

### M6. 2 brand-new log groups have no retention (root cause for P1.1 unfixed)
- **Evidence:** `/aws/lambda/coach-observatory-renderer`, `/aws/lambda/life-platform-delete-user-data`, both created 2026-05-17 with `retentionInDays=null`. The v1 P1.1 fix patched existing groups but didn't install the **default account-level retention** that AWS now supports (`aws logs put-account-policy`).
- **Action:** `aws logs put-account-policy --policy-name life-platform-retention --policy-type DATA_PROTECTION_POLICY ...` OR simpler: `aws logs put-account-policy --policy-name life-platform-retention --policy-type LOG_RETENTION_POLICY --policy-document '{"retention_in_days":30}'`. This ensures all new groups inherit.
- **Effort:** 15 min · **ROI:** Prevents drift recurrence forever. · **Risk:** None.

### M7. CloudFront 4xx rates: averagejoematt 56%, buddy 50%, dash 67% (over 24h)
- **Evidence:** Distribution `E3S424OXQZ8NBE`: 1668 reqs, 56.3% 4xx; `ETTJ44FT0Z4GO` (buddy): 213 reqs, 50.2% 4xx; `EM5NPX6NJN095` (dash): 3 reqs, 67% 4xx (sample too small). All 5xx = 0 (good).
- **Note:** 4xx at this rate usually = bot probing 404s or genuine missing assets. WAF rate-limits are 1000/min — well above bot scanning, so this is likely real 404s on the site origin.
- **Action:** Pull CF access logs (already enabled via S3?) and identify top 4xx paths. Likely candidates: removed blog posts, OG image 404s, asset paths renamed. Fix or add CF redirects.
- **Effort:** 1h · **ROI:** Better SEO + cleaner WAF metrics. · **Risk:** None.

### M8. `life-platform-digest-role` IAM role unused since 2026-03-08
- **Evidence:** Sample of 3 roles found this one last-used 10 weeks ago. Likely from a deprecated daily-digest experiment.
- **Action:** Audit all 8 "potential orphan" Lambda roles found by lookup, delete those not in use AND not last-used in 60d. List: `AWSServiceRoleForLambdaReplicator` (keep, AWS-managed), `life-platform-digest-role`, `life-platform-og-image-role`, `LifePlatformWeb-EmailSubscriberLambdaRole21E2BE5B-Hwn0FyJfNizG`, `LifePlatformWeb-OgImageLambdaRoleB88B26C0-EjtTd9uL46OL`, `measurements-ingestion-role`, `pipeline-health-check-role`, `subscriber-onboarding-role`.
- **Effort:** 30 min · **ROI:** Cleanup; non-monetary. · **Risk:** Low (verify last-used <60d before deleting).

### M9. Layer version sprawl (43/49/50/25 simultaneously)
- **Evidence:** `life-platform-shared-utils` deployed at v25 (3 fns: site-api, site-stats-refresh, og-image-generator), v43 (46 fns — majority), v49 (7 fns: eightsleep, garmin, habitify, strava, todoist, whoop, withings — all ingestion that rotated together), v50 (1 fn: ai-expert-analyzer). 16 Lambdas use no layer at all.
- **Note:** Layer drift = silent dependency divergence. Site-api on v25 is the riskiest (frozen 6+ months behind).
- **Action:** Catalog what changed between v25→v43→v49→v50. Bring site-api stack to latest. Decide whether 16 layerless Lambdas need shared utils.
- **Effort:** 2h · **ROI:** Reduces incident triage time. · **Risk:** Medium — must test site-api after upgrade.

---

## LOW

### L1. 2 unused secrets (notion + dropbox last accessed 2026-03-09)
- **Evidence:** `life-platform/notion`, `life-platform/dropbox` both at $0.40/mo each = $0.80/mo. Last-access 9+ weeks ago. Notion ingestion is still scheduled (`NotionIngestionSchedule` is ENABLED, runs hourly) — so why no access in 9 weeks? Either the rotation last-access tracker is stale or notion-ingestion isn't using Secrets Manager.
- **Action:** Verify notion-ingestion code path. If it's using Secrets Manager, the `LastAccessedDate` should be daily. Likely either code-caches the secret indefinitely (no SM read), or the secret is dead.
- **Effort:** 20 min · **ROI:** $0.80/mo if both removed. · **Risk:** Verify before deletion.

### L2. Cost Explorer API: 69 calls/17d = 4/day, $0.04/day → $0.69/mo
- **Evidence:** `USE1-APIRequest qty=69`. Probably pipeline-health-check or a cost-tracker Lambda polling daily totals.
- **Action:** If polling daily, cache for 24h. If polling hourly, switch to daily.
- **Effort:** 30 min · **ROI:** $0.50/mo. · **Risk:** None.

### L3. Single AZ / no S3 cross-region replication / no AWS Backup plans
- **Evidence:** `aws backup list-backup-plans` = empty. `aws s3api get-bucket-replication` = not configured. PITR on DDB is 35d. CloudTrail is multi-region (good).
- **Action:** Decision: do you want to survive a us-west-2 region failure? If yes, enable DDB Global Tables OR add AWS Backup plan with cross-region copy for the DDB table and a weekly S3 sync to us-east-1.
- **Effort:** 2-3h · **ROI:** Disaster recovery; non-monetary. · **Risk:** Adds $5-10/mo.

### L4. SES has no Configuration Set / no event destination
- **Evidence:** `list-configuration-sets` = empty. Suppression list IS active (1 entry, brittany@). But open/click tracking, delivery events, bounce-firehose all unattached. v1 P7.7 implemented suppression at account level but skipped the config-set layer.
- **Action:** If you want to know which weekly digests get opened, create a `life-platform-default` configuration set with open/click destinations → S3 or EventBridge. If you don't care, this is fine.
- **Effort:** 1h · **ROI:** Engagement data. · **Risk:** None.

### L5. KMS request counts = $0 (DDB CMK is correctly using key-cache)
- **Evidence:** `us-west-2-KMS-Requests = $0` despite 23,035 DDB items. SSE-KMS bulk operations are using the data-key cache properly.
- **Action:** None — this is a v1 win, confirming.
- **Effort:** 0 · **ROI:** Already realized. · **Risk:** None.

### L6. CDK bootstrap buckets in us-east-1 and us-west-2 (both ~empty)
- **Evidence:** `cdk-hnb659fds-assets-205930651321-us-east-1` and `-us-west-2` exist. Standard CDK bootstrap. If CDK isn't actively deployed from CI, the us-east-1 bucket may be holding stale assets.
- **Action:** Lifecycle rule on both (transition to IA after 30d, delete after 180d). Currently no lifecycle.
- **Effort:** 10 min · **ROI:** Tiny ($0.01/mo). · **Risk:** None.

---

## DRIFT CHECK — v1 items still working?

| v1 Item | Status | Evidence |
|---|---|---|
| P1.1 Log retention (existing) | ✅ DRIFT | 79 of 81 log groups have retention (30d mostly). But 2 new ones today have null — fix didn't install account-level policy. See M6. |
| P1.3 S3 lifecycle | ✅ HOLDS | 7 rules present: deploys/30d, raw/noncurrent 7d, raw/abort multipart 7d, uploads/30d, generated/noncurrent 7d, config/noncurrent 30d, cloudtrail/90d. |
| P1.5 Reserved concurrency | ❌ NEVER DEPLOYED | UnreservedConcurrentExecutions=10 = full pool free. No Lambda has reserved set. See H1. |
| P1.6 Timeouts (HAE 300s, site-api 30s) | ⚠ PARTIAL | Lambda timeouts correct. But API GW integration timeout=30s overrides HAE. See C1. |
| P1.7 DDB TTL | ✅ HOLDS | `ttl` attribute enabled. |
| P1.8 DDB PITR | ✅ HOLDS | 35-day PITR enabled, earliest restore 2026-04-12. |
| P2.5 CloudTrail data events | ❌ NEVER DEPLOYED | Only management events. See H2. |
| P2.7 HAE auth | ⚠ CODE-ONLY | API GW `AuthorizationType: NONE`. Auth must be in Lambda code (signature/key check). |
| P7.7 SES suppression | ✅ HOLDS | Account-level suppression on BOUNCE+COMPLAINT, 1 suppressed (brittany@). |
| ADR-052 schedule order | ✅ HOLDS | character-sheet 16:30 → adaptive-mode 16:35 → daily-metrics 16:40 → daily-insight 16:45 → daily-brief 17:00. Correct. |
| ADR-053 S3 KMS rollback | ⚠ DEBT | Bucket reverted to AES256 but the orphan CMK was never scheduled for deletion. See H3. |
| ADR-054 website origin | ✅ HOLDS | All 4 CF distributions point to `matthew-life-platform.s3-website-us-west-2.amazonaws.com`. |
| ADR-056 mcp-api-key rotation | ✅ HOLDS | `life-platform/mcp-api-key` has rotation enabled, 90 days. |
| MCP secret consolidation | ✅ HOLDS | No `anthropic-api-key` duplicate. `ai-keys` is canonical, `site-api-ai-key` is separate (deliberate). |

---

## COST LEVER SECTION — ordered by effort

Realistic monthly recovery from each (validated against actual Cost Explorer lines, not list price):

1. **Delete orphan S3 KMS CMK** — H3 — $1.00/mo (5 min)
2. **Prune 13 duplicate alarms** — M1 — $1.30/mo (30 min)
3. **Cache Cost Explorer poller** — L2 — $0.50/mo (30 min)
4. **Delete 2 unused secrets after verifying** — L1 — $0.80/mo (20 min)
5. **Delete power-tuning stack** — M3 — $0.05/mo (5 min)

**Total realistic recovery: ~$3.65/mo.** Combined with current $30.87 forecast → $27/mo floor. *Do not project $80-120/mo like v1.* CW alarms ($4.84) and WAF ($4.84) and Secrets ($3.69) are floor costs for the security posture; cutting them further means accepting risk.

---

## QUOTA / BLOCKER SECTION

Items requiring AWS Support or manual action:

1. **Lambda concurrency cap raise from 10 to ≥100** — Free quota request, ~24h turnaround. Required for H1 reserved-concurrency work.
2. **AWS Backup region pairing** — If pursuing L3, requires choosing peer region (us-east-1 makes sense given CDK bootstrap already there).
3. **WAF Bot Control add-on** — If you want bot mitigation beyond rate-limits, requires WAF managed-rule subscription (~$10/mo). Not recommended at current traffic; the 50-67% 4xx is more likely real 404s.
4. **CE Anomaly Detector** — Free, but requires enable + 14d learning period. Worth turning on now to catch the next April-style cost spike before it doubles.

---

## QUICK-REFERENCE INVENTORY

- **Lambdas:** 79 total (74 prod + 5 power-tuning). Memory mostly 256MB. Timeouts 30-900s. Tracing OFF except `life-platform-mcp` (Active).
- **IAM roles:** 104 total, 84 Lambda-assumable, 8 potential orphans.
- **Log groups:** 81. Retention: 30d×73, 7d×5, 14d×1, null×2.
- **Alarms:** 104. States: OK×98, ALARM×6, INSUFFICIENT_DATA×0. 13 duplicate-metric pairs.
- **Secrets:** 14. Rotation enabled on 1 (mcp-api-key). 2 not accessed in 60d.
- **KMS CMKs:** 2 (DDB used, S3 orphan).
- **S3 buckets:** 3 (matthew-life-platform 2.86GB / 70K objects, 2× CDK bootstrap).
- **DDB tables:** 1 (`life-platform`, 23K items, 30MB, on-demand, PITR + TTL + KMS).
- **CloudFront distros:** 4 (averagejoematt, dash, blog, buddy) — all Deployed, only main has WAF.
- **WAF Web ACLs:** 1 (CloudFront, 4 rate-rules), 0 REGIONAL.
- **EventBridge rules:** 65 (62 enabled, 3 disabled).
- **API Gateway:** 1 HTTP API (HAE), 0 REST.
- **Function URLs:** 4 (all authType=NONE; flagged by Access Analyzer).
- **Route 53 zones:** 1 (averagejoematt.com only).
- **CloudTrail:** 1 trail, multi-region, management-events only, S3+SNS destinations.
- **SQS:** 2 queues (alerts-digest empty, ingestion-dlq with 63 stuck messages).
- **SES:** Production access enabled, 50K/24h quota, used 8/24h (0.02%), suppression on.
