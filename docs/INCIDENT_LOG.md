# Life Platform — Incident Log

Last updated: 2026-03-05 (v2.76.1)

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
1. **Deployment errors** (wrong function ordering, missing IAM, wrong binary) — 5 incidents
2. **Wrong component investigated** (two Apple Health Lambdas, alarm dimension mismatch) — 3 incidents
3. **Missing infrastructure** (EventBridge rule never created, IAM missing permission) — 2 incidents
4. **Data quality / scoring logic** (zero-score defaults, dedup, sign errors) — 4 incidents

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
