# Life Platform — Incident Log

Last updated: 2026-03-10 (v3.4.9)

> Tracks operational incidents, outages, and bugs that affected data flow or system behavior.
> For full details on any incident, check the corresponding CHANGELOG entry or handover file.

---

## Severity Levels

| Level | Definition |
|-------|------------|
| **P1 — Critical** | System broken, no data flowing or MCP completely down |
| **P2 — High** | Major feature broken, data loss risk, or multi-day data gap |
| **P3 — Medium** | Single source affected, degraded but functional |
| **P4 — Low** | Cosmetic, minor data quality, or transient error |

---

## Incident History

| Date | Severity | Summary | Root Cause | TTD* | TTR* | Data Loss? |
|------|----------|---------|------------|------|------|------------|
| 2026-02-28 | **P1** | 5 of 6 API ingestion Lambdas failing after engineering hardening (v2.43.0) | Handler mismatches (4 Lambdas had `lambda_function.py` but handlers pointed to `X_lambda.lambda_handler`), Garmin missing deps + IAM, Withings cascading OAuth expiry | ~hours (next scheduled run) | ~2 hr (sequential fixes) | No — gap-aware backfill self-healed all missing data. Full PIR: `docs/PIR-2026-02-28-ingestion-outage.md` |
| 2026-02-26 | **P1** | MCP server broken since v2.31.0 — every invocation failing with NameError | 3 tool functions defined AFTER TOOLS dict that references them at module load | ~hours | 30 min | No (server returned errors, no silent corruption) |
| 2026-02-26 | P3 | 5 MCP tools failing with `get_table()` NameError | Functions referenced undefined `get_table()` instead of module-level `table` | Found during P1 fix | 15 min | No |
| 2026-02-25 | P3 | Anomaly detector never running on schedule | EventBridge rule `anomaly-detector-daily` never created despite Lambda existing | ~days | 10 min | No (Lambda existed, just never invoked) |
| 2026-02-25 | P4 | Enrichment alarm watching wrong function name | Alarm dimension: `activity-enrichment-nightly` (rule) instead of `activity-enrichment` (Lambda) | Found in audit | 5 min | No |
| 2026-03-03 | **P2** | Hydration data missing/near-zero for 7+ days (Feb 24–Mar 2) | Health Auto Export app not including Dietary Water/Caffeine in automatic webhook pushes — only sending activity metrics. Caused by infrequent sync schedule producing too-large payloads that silently drop nutrition metrics. | ~8 days | 1 hr | Recovered — user forced 7-day water push from app, day grades regraded via new `regrade_dates` mode |
| 2026-03-03 | P3 | Buddy page showing 12-13 exercise sessions (actual: ~2) | Two bugs: (1) rolling 7-day window instead of Monday–Sunday weekly count, (2) WHOOP+Garmin both push to Strava creating duplicate activities | ~2 days | 30 min | No (display only, raw data correct) |
| 2026-03-03 | P3 | Buddy page "No food logged in 99 days" | MacroFactor field name mismatch: code checked `calories`/`energy_kcal`, data uses `total_calories_kcal` | ~2 days | 15 min | No (display only, raw data correct) |
| 2026-03-05 | **P2** | dashboard-refresh Lambda silently failing on every run since deployment | IAM role missing `s3:PutObject` on `dashboard/` path. Lambda invoked successfully but AccessDenied on write. New alarm detected it within hours of being added | Since initial deploy | 30 min | Dashboard never updated by this Lambda (Daily Brief still wrote dashboard data correctly — no user-visible impact) |
| 2026-03-04 | **P2** | wednesday-chronicle + anomaly-detector failing with ImportModuleError since last deploy | Wrong filenames in zip packages — deploy script used hardcoded filenames rather than reading handler config from AWS. Both Lambdas silently broken. Chronicle missed one installment; anomaly detector not running; 5 DLQ messages accumulated | ~2 days | 1 hr | Chronicle: 1 missed installment (backfilled). Anomaly: backfilled Mar 4-5. Root fix: deploy_lambda.sh now auto-reads handler config |
| 2026-03-04 | P3 | State of Mind Lambda deploy not updating | deploy_lambda.sh zipped wrong filename for state-of-mind handler; fixed in v2.70.1 with universal deploy script that reads handler config from AWS | ~1 session | 20 min | No |
| 2026-03-05 | **P2** | dropbox-poll failing with InvalidRequestException on every run since secrets consolidation | Secrets consolidation (v2.75.0) deleted `life-platform/dropbox` secret but Lambda had `SECRET_NAME=life-platform/dropbox` hardcoded as env var, overriding the correct code default. Additionally key names in `api-keys` bundle use `dropbox_` prefix (`dropbox_app_key` etc.) vs old secret's unprefixed names (`app_key`) | Hours (new alarm, alarming proves its worth) | 30 min | No Dropbox polling since secrets consolidation; MacroFactor CSV auto-import non-functional. Fixed: env var updated to `life-platform/api-keys`, key lookups patched in code (v2.76.1) |
| 2026-03-05 | P3 | dashboard-refresh + life-platform-data-export alarms firing from earlier IAM failures | Both Lambdas had IAM fixed during tech debt session (v2.75.0) but earlier failed runs had already triggered alarms. Both resolved on next successful run. | Hours (alarm) | Self-resolved after IAM fix | No — dashboard was still being written by daily-brief; export recovered on subsequent run |
| 2026-03-04 | P3 | character-sheet-compute failing with AccessDenied on S3 + DynamoDB | IAM role missing s3:GetObject on config bucket and dynamodb:PutItem permission. Lambda silently failing since deployment | ~1 day | 30 min | No (compute re-run via backfill) |
| 2026-02-25 | P4 | Day grade zero-score — journal and hydration dragging grades down | `score_journal` returned 0 instead of None when no entries; hydration noise <118ml scored | 1 day | 20 min | No (grades recalculated) |
| 2026-02-25 | P3 | Strava multi-device duplicate activities inflating movement score | WHOOP + Garmin recording same walk → duplicate in Strava | ~days | 30 min | No (dedup applied in brief; raw data retained) |
| 2026-03-10 | **P2** | All three web URLs (dash/blog/buddy) showing TLS cert error — `ERR_CERT_COMMON_NAME_INVALID` | `web_stack.py` had `CERT_ARN_* = None` placeholders — CDK deployed distributions without `viewer_certificate`, causing CloudFront to serve default `*.cloudfront.net` cert. Introduced during PROD-1 (v3.3.5). | Hours (noticed by user) | 15 min (v3.4.9) | No (data unaffected; all URLs inaccessible via HTTPS) |
| 2026-03-08 | **P3** | `todoist-data-ingestion` failing since 2026-03-06 | Stale `SECRET_NAME` env var (`life-platform/api-keys`) set on the Lambda — when api-keys was soft-deleted as part of secrets decomposition, the env var override started producing `ResourceNotFoundException`. Code default was correct but env var took precedence. DLQ consumer caught accumulated failures at 9:15 AM on 2026-03-08. | ~2 days | 15 min (env var removed + Lambda redeployed) | No — Todoist ingestion gap 2026-03-06 to 2026-03-08. Gap-aware backfill (7-day lookback) self-healed all missing task records on next run. |
| 2026-03-08 | **Info** | `data-reconciliation` first run reported RED: 17 gaps across 6 sources | Bootstrap noise, not real failures. First run has no prior reference point — all "gaps" were expected coldstart artifacts (MacroFactor real data only from 2026-02-22, habit gap 2025-11-10→2026-02-22, etc.). | First run | No action needed — monitor next 3 runs for convergence to GREEN | No |
| 2026-03-09 | **P2** | All 23 CDK-managed Lambdas broken after first CDK deploy (PROD-1, v3.3.5) | `Code.from_asset("..")` bundles files at `lambdas/X.py` inside a subdirectory, but Lambda expects `X.py` at zip root — causing `ImportModuleError` on every invocation. Affected: 7 Compute + 8 Email + 1 MCP + 7 Operational Lambdas. | Next scheduled run post-deploy | ~1 hr (`deploy/redeploy_all_cdk_lambdas.sh` redeployed all 23 via `deploy_lambda.sh`) | No — gap-aware backfill + DLQ drained. Permanent fix: update `lambda_helpers.py` to `Code.from_asset("../lambdas")` (tracked as TODO) |
| 2026-03-10 | **P1** | CDK IAM bulk migration — Lambda execution role gap during v3.4.0 deploy | CDK deleted 39 old IAM roles before confirming CDK-managed replacement roles were fully propagated and attached. Two email Lambdas (`wednesday-chronicle`, `nutrition-review`) had no execution role for ~5 min during the migration window, causing invocation failures on any warmup or invocation in that window. Root fix: `cdk deploy` sequencing — always verify role attachment before deleting old roles. *Identified retroactively during Architecture Review #4.* | Deploy logs (real-time) | ~15 min (CDK re-apply with `--force`) | No — no scheduled runs in migration window |
| 2026-03-10 | **P2** | CoreStack SQS DLQ ARN changed on CDK-managed recreation — DLQ send failures across all async Lambdas | CoreStack created a new CDK-managed DLQ (`life-platform-ingestion-dlq`) with a different ARN than the manually-created original. CDK-deployed Lambda env vars referenced the new ARN, but 3 Lambdas that had the old ARN cached in env var overrides (`SECRET_NAME`-style pattern) continued sending to the deleted queue. Result: DLQ send failures and silent dead-letter drop for ~30 min. *Identified retroactively during Architecture Review #4.* | CloudWatch errors (~30 min lag) | CDK update pushed correct ARN to all Lambda configs | Possible: some DLQ messages lost during gap window |
| 2026-03-10 | **P3** | EB rule recreation gap: 2 ingestion Lambdas missed scheduled morning runs during v3.4.0 migration | Old EventBridge rules deleted first; CDK replacements deployed after. 2 ingestion Lambdas (`withings-data-ingestion`, `eightsleep-data-ingestion`) missed their 7:15 AM / 8:00 AM PT windows during ~10 min gap between deletion and CDK rule creation. *Identified retroactively during Architecture Review #4.* | Freshness checker alert (10:45 AM) | Gap-aware backfill self-healed on next scheduled run | No — backfill recovered all missing data |
| 2026-03-10 | **P3** | Orphan Lambda adoption: `failure-pattern-compute` Sunday EB rule not included in CDK Compute stack definition | When 3 orphan Lambdas were adopted into CDK (v3.4.0), the `failure-pattern-compute` Sunday 9:50 AM EventBridge rule was omitted from the Compute stack definition. Lambda did not execute for ~1 week (one missed Sunday run). *Identified retroactively during Architecture Review #4.* | Architecture Review #4 inspection | EB rule added to CDK Compute stack | No — failure pattern memory records simply not generated for that week |
| 2026-03-10 | **P4** | Duplicate CloudWatch alarms after CDK Monitoring stack adoption of orphan Lambdas | CDK Monitoring stack created new alarms for 3 newly-adopted Lambdas (`failure-pattern-compute`, `brittany-email`, `sick-day-checker`) that already had manually-created alarms — resulting in 9 duplicate alarms with overlapping SNS notifications and alert fatigue. *Identified retroactively during Architecture Review #4.* | Architecture Review #4 alarm audit | Manual alarms deleted; CDK alarms authoritative | No |
| 2026-03-09 | **P2** | All 13 ingestion Lambdas failing with `AttributeError: 'Logger' object has no attribute 'set_date'` | After `platform_logger.py` added `set_date()` to support OBS-1 structured logging, ingestion Lambdas had stale bundled copies of `platform_logger.py` missing the new method. 14 DLQ messages accumulated. Affected: whoop, eightsleep, withings, strava, todoist, macrofactor, garmin, habitify, notion, journal-enrichment, dropbox-poll, weather, activity-enrichment. | DLQ depth alarm + CloudWatch errors | ~30 min (`deploy/redeploy_ingestion_with_logger.sh` redeployed all 13 with `--extra-files lambdas/platform_logger.py`). DLQ purged in v3.3.8. | No — gap-aware backfill recovered all ingestion gaps. |
| 2026-02-25 | P4 | Daily brief IAM — day grade PutItem AccessDeniedException | `lambda-weekly-digest-role` missing `dynamodb:PutItem` | Since v2.20.0 | 10 min | Grades not persisted until fixed |
| 2026-02-24 | P2 | Apple Health data not flowing — 2+ day gap | Investigated wrong Lambda (`apple-health-ingestion` vs `health-auto-export-webhook`) + deployment timing | ~2 days | 4 hr investigation, 15 min actual fix | No (S3 archives preserved, backfill recovered) |
| 2026-02-24 | P3 | Garmin Lambda pydantic_core binary mismatch | Wrong platform binary in deployment package | 1 day | 30 min | No |
| 2026-02-24 | P3 | Garmin data gap (Jan 19 – Feb 23) | Garmin app sync issue (Battery Saver mode suspected) | ~5 weeks | Backfill script | Partial (gap backfilled from Feb 23 forward) |
| 2026-02-23 | P4 | Habitify alarm in ALARM state | Transient Lambda networking error ("Cannot assign requested address") | Hours | Manual alarm reset | No (re-invoked successfully) |
| 2026-02-23 | P4 | DynamoDB TTL field name mismatch | Cache using `ttl_epoch` but TTL configured on `ttl` attribute | ~1 day | 5 min | No (cache items never expired, just accumulated) |
| 2026-02-23 | P4 | Weight projection sign error in weekly digest | Delta calculation reversed (showing gain as loss) | 1 day | 5 min | No |
| 2026-02-23 | P4 | MacroFactor hit rate denominator off | Division denominator using wrong field | 1 day | 5 min | No |

*TTD = Time to Detect, TTR = Time to Resolve

---

## Patterns & Observations

**Most common root causes:**
1. **Deployment errors** (wrong function ordering, missing IAM, wrong binary, CDK packaging) — 7 incidents
2. **Stale config / env var overrides** (SECRET_NAME env var pointing at deleted secret) — 3 incidents
3. **Wrong component investigated** (two Apple Health Lambdas, alarm dimension mismatch) — 3 incidents
4. **Missing infrastructure** (EventBridge rule never created, IAM missing permission) — 2 incidents
5. **Data quality / scoring logic** (zero-score defaults, dedup, sign errors) — 4 incidents

**CDK packaging watch-out:** `Code.from_asset("..")` bundles source files one directory deep in the zip — Lambda can't find the handler. Always use `Code.from_asset("../lambdas")` (points at the lambdas directory directly). When CDK-managing Lambdas for the first time, verify a sample function works before assuming all 23 are healthy. `deploy_lambda.sh` is immune to this bug.

**Stale lambda module caches:** When a shared module (like `platform_logger.py`) adds new methods, all Lambdas that bundle their own copy of that file need to be redeployed. CDK packaging re-bundles from source automatically; `deploy_lambda.sh --extra-files` is the manual equivalent for Lambdas not yet on CDK.

**Secrets consolidation watch-out:** When consolidating Secrets Manager entries, Lambdas with `SECRET_NAME` (or similar) set as explicit env vars will override code defaults and continue pointing at the deleted secret. Always audit Lambda env vars — not just code — when retiring secrets. Also verify key naming conventions match between old and new secret schemas.

**Key lesson (from RCA):** When data isn't flowing, check YOUR pipeline first (CloudWatch logs for the receiving Lambda), not the external dependency. Document the full request path so you investigate the right component.

---

## Open Monitoring Gaps

| Gap | Risk | Mitigation |
|-----|------|------------|
| No end-to-end data flow dashboard | Slow detection of silent failures | Freshness checker provides daily coverage |
| DLQ coverage: MCP + webhook excluded | Request/response pattern — DLQ not applicable | CloudWatch error alarms cover both |
| No webhook health check endpoint | Can't externally monitor webhook availability | CloudWatch alarm on zero invocations/24h |
| No duration/throttle alarms | Timeouts without errors go undetected | Daily brief and MCP are most at risk |

**Resolved gaps (v2.75.0):** All 29 Lambdas now have CloudWatch error alarms. 10 log groups now have 30-day retention. Deployment zip filename bug eliminated by `deploy_lambda.sh` auto-reading handler config from AWS.

**Resolved gaps (v3.1.x):** DLQ consumer Lambda (`dlq-consumer`) now drains and logs failures from `life-platform-ingestion-dlq` on a schedule — silent DLQ accumulation is now caught proactively. Canary Lambda (`life-platform-canary`) runs synthetic DDB+S3+MCP round-trip every 30 min with 4 CloudWatch alarms — end-to-end health check is now automated. `item_size_guard.py` monitors 400KB DDB write limits before they cause failures.
