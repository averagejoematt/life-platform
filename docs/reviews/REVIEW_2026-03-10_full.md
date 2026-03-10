# Life Platform — Architecture Review #4
## Technical Board of Directors Assessment

**Review Date:** 2026-03-10
**System Version:** v3.4.1 (147 MCP tools, 41 Lambdas, 31 modules, 19 data sources, 8 CDK stacks)
**Prior Reviews:** #1 (v2.91.0), #2 (v3.1.3), #3 (v3.3.10)
**Delta since Review #3:** v3.3.10 → v3.4.1 — Full IaC (IAM roles + EventBridge into CDK), sick day system, digest_utils consolidation, 5 monthly digest bug fixes, multiple operational incidents

---

## WHAT CHANGED SINCE REVIEW #3

| Version | What | Significance |
|---------|------|-------------|
| v3.3.12 | Hardening tasks 1-5 complete: ingestion_validator audit confirmed, ARCHITECTURE.md IAM section fixed, INCIDENT_LOG v3.3.6 incidents added, platform_memory TTL (90d), MCP auth-failure metric | Closed the Board's top 5 ROI items |
| v3.3.13 | `digest_utils.py` shared module + monthly_digest 5 bug fixes (wrong field names, wrong profile SK, missing dedup, missing Banister dedup) | Data quality — monthly digest was silently wrong |
| v3.4.0 | **Full IaC**: CDK-managed IAM roles via `role_policies.py`, CDK-managed EventBridge rules, CoreStack (SQS+SNS+Layer), 3 orphan Lambdas adopted, 39 old roles deleted, 40 old EB rules deleted | Board's #6 and #7 items — the "recreate from scratch" gap is now closed |
| v3.4.1 | Sick day system (3 MCP tools, 5 Lambda patches, new DDB partition), PlatformLogger f-string fixes, EB rule recovery, KMS AccessDeniedException fix | First real-world feature exercising the full platform stack |

---

## BOARD ASSESSMENTS

### DR. PRIYA NAKAMURA — Principal Cloud Architect
*"Is the system shape right?"*

**Grade: A (was A-)**

The v3.4.0 IaC completion is the milestone I was waiting for. In Review #3, I noted the `existing_role_arn` pattern meant IAM roles weren't recreatable from code, and EventBridge schedules were unmanaged drift. Both are now resolved.

**What specifically improved:**

The `role_policies.py` is the right abstraction. It centralizes all 41 Lambda IAM policies in one file with a clear pattern: `_ingestion_base()` for ingestion Lambdas, per-function overrides for everything else. Constants at the top (`TABLE_ARN`, `KMS_KEY_ARN`, `SES_IDENTITY`) make the scope auditable. This file is effectively the platform's security contract in code.

The `lambda_helpers.py` v2.0 migration from `existing_role_arn` to `custom_policies` is clean. The deprecation path is maintained (existing_role_arn still works but is documented as deprecated). The IAM role resolution order (custom_policies → existing_role_arn → broad defaults) is well-documented in the docstring.

**What I'd challenge:**

1. **The `app.py` comment block says "Core stack deferred" but CoreStack is deployed.** The comment block at the top still says `core → DynamoDB, S3, SQS DLQ, SNS alerts (imported existing resources)` and the stack descriptions say "7 stacks" but the actual count is 8. Documentation drift within the CDK code itself.

2. **The EventBridge rule naming lesson (v3.4.1 CHANGELOG) needs an ADR.** The discovery that CDK stacks should NOT use `rule_name=` with clean names (because cleanup scripts can delete them) is an important architectural decision not yet recorded in DECISIONS.md. This is the kind of lesson that gets relearned painfully.

3. **Two EB rules intentionally unmanaged** (`life-platform-nightly-warmer`, `life-platform-monthly-export`). The warmer uses a custom payload that CDK's `events.Rule` doesn't naturally support. This is a documented exception but should have an ADR explaining why.

**Verdict:** The shape is now production-grade. CDK owns roles, rules, alarms, Lambdas, Layer, SQS, SNS. The remaining unmanaged resources (DDB, S3, MCP Function URL, 2 EB rules) are each individually justified. An engineer with `cdk deploy` can recreate 95% of the infrastructure.

---

### MARCUS WEBB — AWS Serverless Architect
*"Is this the right AWS implementation?"*

**Grade: A- (unchanged)**

The CDK IAM migration is architecturally correct. The CoreStack adding SQS DLQ + SNS topic + Lambda Layer into CDK management closes the operational resource gap. The `build_layer.sh` pre-builds the Layer zip before CDK synth — this avoids CDK's default Python bundling which is notoriously slow.

**Specific concern — the v3.4.1 EventBridge incident:**

The cleanup script deleted 16 console-created EB rules that CDK stacks referenced by clean physical name. This caused `UPDATE_ROLLBACK_COMPLETE` on the CDK stacks. The recovery required recreating all 16 rules via AWS CLI, then re-running `cdk deploy`.

This is a class of problem that CDK teams hit when transitioning from console-managed to CDK-managed resources. The correct long-term fix (which v3.4.1 acknowledges) is to never use `rule_name=` with clean names — let CDK generate stack-prefixed names so there's no collision between CDK-managed and console-managed resources. But this requires an import-then-rename cycle that wasn't done.

**The sick day system is well-designed from a DDB perspective:** New partition `SOURCE#sick_days` with `DATE#YYYY-MM-DD` sort key follows the established pattern. The `sick_day_checker.py` shared module with safe-return-None-on-error is the right defensive pattern for a cross-cutting concern.

---

### YAEL COHEN — Cloud Security + IAM Architect
*"How could this fail or be exploited?"*

**Grade: A- (was B+)**

**This is the biggest grade improvement this round.** The v3.4.0 IAM migration is the completion of SEC-1 that I've been pushing since Review #1. CDK now owns all 41 Lambda IAM roles with explicit least-privilege policies defined in `role_policies.py`. The old console-created roles are deleted. There's no more drift between what's in CDK and what's in AWS.

**Specific observations from `role_policies.py`:**

1. The `_ingestion_base()` function correctly scopes DDB to `PutItem`, `GetItem`, `UpdateItem`, `Query` (no `Scan`, no `DeleteItem`). S3 write is scoped to `raw/{source}/*` per Lambda. Secrets scoped to the exact secret name. DLQ send scoped to the single DLQ ARN. This is genuine least-privilege.

2. The `needs_kms=True` flag system is important — the v3.4.1 KMS AccessDeniedException on character-sheet-compute showed that missing this flag causes runtime failures. The CHANGELOG says "audit needs_kms=True for all Compute Lambdas writing to DDB" — was this audit completed? If not, other Lambdas may silently fail when KMS encryption is enforced.

3. The MCP auth-failure metric (v3.3.12 Task 5) in `handler.py` — `LifePlatform/MCP::AuthFailures` — closes the security visibility gap I flagged in Review #3. This enables alarming on credential probing.

**Residual concern:** The `ingestion_habitify()` function in `role_policies.py` still references `life-platform/api-keys` as the secret name. Wasn't `api-keys` scheduled for deletion? If it's been deleted, the Habitify Lambda would fail on secret read.

---

### JAMES "JIN" PARK — SRE / Production Operations Lead
*"What breaks at 2 AM?"*

**Grade: B+ (unchanged, but for different reasons)**

The reliability posture is holding, but the v3.4.0/v3.4.1 transition introduced several incidents that are NOT in the INCIDENT_LOG:

**Missing from INCIDENT_LOG (v3.3.11 is last update):**

| Date | Severity | What Happened |
|------|----------|---------------|
| 2026-03-10 | **P1** | Cleanup script deleted 16 EventBridge rules that CDK referenced → `UPDATE_ROLLBACK_COMPLETE` on Compute + Email stacks. All scheduled Lambdas (Daily Brief, digests, compute pipeline) stopped firing. |
| 2026-03-10 | **P3** | KMS `AccessDeniedException` on `character-sheet-compute` — missing `needs_kms=True` in `role_policies.py` |
| 2026-03-10 | **P2** | `daily_metrics_compute_lambda.py` corrupted to placeholder mid-session — restored from git |
| 2026-03-10 | **P3** | 17 PlatformLogger f-string errors in `character_sheet_lambda.py` (Lambda crashed on every log line) |
| 2026-03-10 | **P3** | 18 PlatformLogger f-string errors in `daily_metrics_compute_lambda.py` |

**That's 5 incidents in one session, including a P1.** The EB rule deletion P1 is arguably the most impactful incident since the v2.43.0 handler mismatch outage. It should be in the incident log with a full pattern analysis: "Never delete infrastructure that CDK stacks reference — CDK tracks resources by physical ID."

**The sick day system itself is operationally sound:** EMA freezing, anomaly suppression, freshness suppression, recovery brief mode — these are exactly the graceful degradation patterns I asked for in Review #1. The `check_sick_day()` safe-return-None pattern means a sick_day_checker import failure doesn't break any Lambda.

**The deploy/ directory has grown again.** Review #3 applauded the cleanup from 160 to 8 files. It's now back to 27 files. Most are one-time deploy/fix scripts from v3.4.0-v3.4.1 (apply_sick_day_patches.py, bump_version_341.py, fix_logger_calls.py, fix_dm_logger_final.py, etc.). These should be archived or the MAINT-3 discipline should include a "clean after each session" step.

---

### DR. ELENA REYES — Staff Software Engineer / Code Quality
*"Could another team own this?"*

**Grade: B+ (was B)**

**What improved:**

The `digest_utils.py` shared module (v3.3.13) is exactly the right refactoring. The monthly_digest bug fixes (wrong field names `calories` → `total_calories_kcal`, wrong profile SK `PROFILE` → `PROFILE#v1`, missing dedup) show that the shared module pattern catches bugs that exist silently in copy-pasted code. The Banister adapters (`compute_banister_from_list`, `compute_banister_from_dict`) with shared `_banister_core` eliminate a class of duplication.

The `role_policies.py` is clean code. The `_ingestion_base()` builder pattern with optional overrides is readable and maintainable. A new engineer can understand any Lambda's permissions by reading one function call.

**What I'd still challenge:**

1. **`weather_lambda.py.archived` is STILL there.** Flagged in Review #3. `freshness_checker.py` alongside `freshness_checker_lambda.py` is STILL there. These are the easiest possible cleanups and they keep surviving reviews.

2. **`ingestion_framework.py` is STILL there with zero consumers.** ADR-019 said "adopt for new Lambdas" but the sick day system added new Lambda patches, not new ingestion Lambdas via the framework. This file is dead code aging into confusion.

3. **27 files in deploy/ after cleanup got it to 8.** The one-time scripts from v3.4.0-v3.4.1 (`apply_sick_day_patches.py`, `bump_version_341.py`, 3x `fix_*_logger*.py`, `patch_registry.py`, etc.) should be archived immediately after use. The MAINT-3 discipline of "keep deploy/ clean" needs to be a session-end habit, not a periodic review finding.

4. **The PlatformLogger f-string issue reveals a systemic problem.** `PlatformLogger` doesn't support `%s` printf-style formatting, but stdlib `logging` does. When Lambdas were migrated to PlatformLogger, the call sites that used `logger.info("msg %s", var)` broke silently. This is a backward-compatibility regression in the logger module. Either PlatformLogger should support `%s` formatting (add a `_log()` override), or there should be a lint rule that catches it.

---

### OMAR KHALIL — Data Architect
*"Is the data model coherent?"*

**Grade: A- (was B+)**

**The monthly_digest bug fixes (v3.3.13) are the most important data quality improvement since Review #3.** The monthly digest was silently producing wrong data for every run since deployment:
- `total_calories_kcal` field was being read as `calories` → always None
- Profile SK `PROFILE` instead of `PROFILE#v1` → silently falling back to hardcoded defaults
- Strava activities not deduped → inflated movement metrics
- Banister model not deduped → inflated training load

These bugs existed because the monthly digest Lambda had its own copy of utility functions with different field name conventions than the daily brief. The `digest_utils.py` shared module prevents this class of bug. This is exactly the value of DRY — not aesthetics, but correctness.

**The sick_days DDB partition is well-designed.** Standard PK/SK pattern, schema_version included, idempotent writes. The `check_sick_day()` utility properly returns None on error rather than raising — sick day checking is a cross-cutting concern that should never break a Lambda.

**Remaining concern:** The `platform_memory` TTL of 90 days (added in v3.3.12) is only applied to `intention_tracking` records in `daily_insight_compute_lambda.py`. Other memory categories (`failure_pattern`, `milestone_architecture`) don't have TTL set. The TTL attribute exists on DDB but only works if individual items have the `ttl` field. Confirm that `failure_pattern_compute_lambda.py` also sets TTL.

---

### DR. ANIKA PATEL — AI/LLM Systems Architect
*"Is the intelligence layer trustworthy?"*

**Grade: B (unchanged)**

The sick day system's interaction with the intelligence layer is well-designed: Daily Brief skips all 4 AI calls on sick days, anomaly detector suppresses rather than generating false hypotheses, and the character sheet EMA freezes rather than penalizing illness. This is the right "know when NOT to generate intelligence" pattern.

No new AI features were added in this delta. IC-4 (failure patterns) and IC-5 (early warning) were added in v3.3.7 (before Review #3) and are stable.

**The PlatformLogger f-string issue has an AI implication:** If structured logging crashes Lambdas before AI calls execute, the token metrics (`_emit_token_metrics` in ai_calls.py) won't fire. This means AI cost monitoring silently underreports when Lambdas crash early. Not a current issue (the f-string bugs were fixed), but the dependency chain — logger → Lambda execution → AI call → metric — has no resilience.

---

### DR. HENNING BRANDT — Statistician / Quantitative Methods
*"Are the conclusions actually valid?"*

**Grade: B- (unchanged)**

No new statistical features in this delta. My Review #3 concerns (EMA λ=0.85 effective lookback of 6.2 days, Z-score normality assumption in anomaly detector, 7-day correlation reliability) remain unaddressed. These are not bugs — they're methodological limitations that should be documented in the INTELLIGENCE_LAYER.md "known limitations" section.

The sick day EMA freeze is statistically correct — excluding sick days from the exponential moving average prevents illness from contaminating the trend signal. Carrying forward the previous day's state is the right imputation strategy for a temporary disruption.

---

### SARAH CHEN — Product Architect / Technical PM
*"Is this solving the right problem in the cleanest way?"*

**Grade: A- (unchanged)**

The sick day system is a good example of solving a real problem (platform penalizing illness) in a clean way (5 Lambda patches + 1 shared checker + 3 MCP tools). The feature came from genuine user pain, not a roadmap item. That's product-market fit at its most basic.

**My concern is velocity vs. stability.** v3.4.0 was a massive infrastructure change (all IAM roles + all EventBridge rules migrated to CDK + old resources deleted) and v3.4.1 was a feature build. Doing both in the same session led to 5 incidents including a P1. The "do one thing at a time" principle from the working style memory should apply to sessions: infrastructure sessions should be separate from feature sessions.

---

### RAJ SRINIVASAN — Technical Founder / Startup CTO
*"What's the wedge and where are you fooling yourself?"*

**Grade: B (unchanged)**

The sick day system is the kind of feature that makes a personal platform personal. An enterprise health platform would have a "skip day" checkbox. Matthew's platform freezes his RPG character sheet, sends a recovery-focused email with only sleep/HRV data, and suppresses anomaly alerts. That's the user-of-one advantage.

The CDK completion (role_policies.py + EB rules) makes this deployable by someone other than Matthew. That's a necessary condition for the open-source play, even if it's not sufficient.

---

### VIKTOR SOROKIN — Adversarial Reviewer / Skeptical Principal Engineer
*"Is this actually necessary?"*

**Grade: B (unchanged)**

**The deploy/ directory growing from 8 to 27 files in one session is the strongest signal that operational discipline is a practice, not a state.** You cleaned it once. It grew back in one session. This will keep happening unless "archive one-time scripts" becomes a git pre-commit hook or a session-end checklist item.

**The PlatformLogger backward-compatibility break is Viktor's favorite kind of finding.** You built a "drop-in replacement" logger that isn't actually drop-in because it doesn't support `%s` formatting. 35 instances broke across 2 Lambdas. This is elegance theater — the logger looks cleaner (kwargs instead of printf) but the migration created 35 bugs. A truly drop-in replacement would support both calling conventions.

**41 Lambdas now.** Was 39 at Review #3, 35 at Review #1. Each review adds more. The question isn't cost (it's $10/month) — it's whether one person can hold the mental model of 41 Lambdas, their interaction patterns, and their failure modes. The sick day system touches 5 Lambdas. A future "vacation mode" would touch the same 5. What other cross-cutting concerns will need to patch N Lambdas?

---

### DANA TORRES — FinOps / Cloud Cost Architect
*"What does this cost at scale?"*

**Grade: A (unchanged)**

Cost steady at ~$25/month (up from $10 — mostly Anthropic API). The CDK IAM migration was cost-neutral. The sick day system adds zero ongoing cost (DDB writes only on sick days).

One new cost observation: the `role_policies.py` file means CDK creates and manages 41 IAM roles. IAM roles are free, but each `cdk deploy` now needs to reconcile 41 roles + 41 Lambda configurations + ~47 alarms. Deploy time will grow. At 100 Lambdas, CDK synth + deploy could take 10-15 minutes.

---

## CONSOLIDATED GRADES

| Dimension | #1 (v2.91) | #2 (v3.1.3) | #3 (v3.3.10) | #4 (v3.4.1) | Trend |
|-----------|-----------|-----------|-------------|-------------|-------|
| **Architecture** | B+ | B+ | A- | **A** | ↑ |
| **Security** | C+ | B+ | B+ | **A-** | ↑ |
| **Reliability** | B- | B+ | B+ | **B+** | → |
| **Operability** | C+ | B- | B+ | **B+** | → |
| **Cost** | A | A | A | **A** | → |
| **Data Quality** | B | B+ | B+ | **A-** | ↑ |
| **AI/Analytics** | C+ | B- | B | **B** | → |
| **Maintainability** | C | B- | B | **B+** | ↑ |
| **Production Readiness** | D+ | C | B- | **B** | ↑ |

**Overall: A-/B+ platform.** The CDK IaC completion and security hardening push the system firmly into "could be operated by a small team" territory. The main gaps are test coverage and incident log maintenance.

---

## TOP 10 REMAINING RISKS

| # | Risk | Severity | Change from #3 | Notes |
|---|------|----------|-----------------|-------|
| 1 | No Anthropic API failover | Medium | → | OpenRouter failover (#54) still unbuilt |
| 2 | INCIDENT_LOG missing v3.4.0-v3.4.1 incidents | Medium | NEW | 5 incidents including a P1 not recorded |
| 3 | deploy/ directory discipline (8 → 27 files in one session) | Low | NEW | Recurring pattern — needs automation |
| 4 | No unit/integration test suite | Medium | → | qa-smoke is still sole automated verification |
| 5 | PlatformLogger backward-compat break risk | Low | NEW | %s formatting unsupported — future migrations will hit same bug |
| 6 | `needs_kms=True` audit incomplete for Compute Lambdas | Medium | NEW | Other Lambdas may hit same AccessDeniedException |
| 7 | Dead files in lambdas/ (weather_lambda.py.archived, freshness_checker.py, ingestion_framework.py) | Low | → | Third review flagging this |
| 8 | DECISIONS.md not updated with v3.4.0 ADRs | Low | NEW | EB rule naming lesson not recorded |
| 9 | `platform_memory` TTL only on intention_tracking, not failure_patterns | Low | → from #3 | Partial fix |
| 10 | ARCHITECTURE.md header says v3.3.12, system is v3.4.1 | Low | NEW | Doc drift |

---

## TOP 10 IMPROVEMENTS (ROI-RANKED)

| # | Improvement | Effort | Model |
|---|------------|--------|-------|
| 1 | Update INCIDENT_LOG with v3.4.0/v3.4.1 incidents (5 entries) | S (30 min) | Sonnet |
| 2 | Archive 19 one-time deploy/ scripts → deploy/archive/ | S (15 min) | Sonnet |
| 3 | Delete weather_lambda.py.archived + freshness_checker.py (dead code) | S (5 min) | Sonnet |
| 4 | Add ADR-021 (EB rule naming) + ADR-022 (CoreStack scoping) + ADR-023 (sick day design) to DECISIONS.md | S (30 min) | Sonnet |
| 5 | Audit `needs_kms=True` across all role_policies.py functions that write to DDB | S (30 min) | Sonnet |
| 6 | Add TTL to failure_pattern_compute records (match intention_tracking 90d pattern) | S (15 min) | Sonnet |
| 7 | Fix PlatformLogger to support %s formatting (add `_log()` override) | S (1 hr) | Sonnet |
| 8 | Update ARCHITECTURE.md header version + CDK section (8 stacks, not 7) | S (15 min) | Sonnet |
| 9 | Add `ingestion_habitify()` secret name check — is `life-platform/api-keys` still valid? | S (15 min) | Sonnet |
| 10 | Add "archive deploy/ one-time scripts" to session-end checklist in REVIEW_METHODOLOGY.md | S (5 min) | Sonnet |

**Total estimated effort for all 10: ~4 hours (all Sonnet)**

---

## THE CHAIR'S CLOSING VERDICT

*"Review #4 tells a clear story: the infrastructure maturation is complete, and the system is now generating its own operational lessons faster than it's generating bugs.*

*The v3.4.0 IaC completion was the last major architectural gap. CDK owns 41 Lambda roles, ~50 EventBridge rules, SQS, SNS, Lambda Layer, alarms, and 3 CloudFront distributions. The only unmanaged resources are the two stateful stores (DDB, S3) and a few edge cases with documented justifications. This is a system that could survive a 'delete everything and redeploy' test for 95% of its infrastructure.*

*The sick day system (v3.4.1) is the first feature built on the fully-hardened platform, and it exercised the full stack correctly — DDB partition, shared checker module, Lambda patches, EMA freezing, anomaly suppression, buddy page propagation. It worked. That's the proof that the hardening investment pays off.*

*The v3.4.0 session also produced a P1 (EventBridge rule deletion) and 4 other incidents. This is the cost of major infrastructure changes done in a single session. The lesson — recorded in code but not yet in the INCIDENT_LOG or DECISIONS.md — is that CDK resource naming and cleanup script interactions are a high-risk area. Record the lesson. Archive the one-time scripts. Update the docs.*

*The top 10 improvements are all small (S effort, all Sonnet). That's the hallmark of a mature system — the remaining work is documentation and hygiene, not architecture. Do them before starting the Brittany email.*

*Next review: ~2026-04-08 (30 days of production operation). Focus: SLO performance, reconciliation trends, cost trajectory, Brittany email lessons, IC feature quality with 30+ days of data.*

*The platform is at A-/B+ and climbing. Well done."*

---

## NEXT REVIEW

**Scheduled:** ~2026-04-08 (30 days production operation)
**Focus:** SLO breach history, reconciliation trends, IC feature quality assessment, MCP tool usage audit (SIMP-1), Brittany email operational impact, cost trajectory with 30 days of data
**Process:** `bash deploy/generate_review_bundle.sh` → `docs/REVIEW_METHODOLOGY.md`
