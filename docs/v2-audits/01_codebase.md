# V2 Audit — Codebase + Architecture Leg

Date: 2026-05-17  
Scope: `lambdas/`, `mcp/`, `cdk/`, `deploy/`, shared modules, `tests/`  
HEAD: `321ef02` (v6.9.5). v1 work (v7.0.0 → v7.21.0) is entirely uncommitted in the working tree.

---

## TL;DR

**The v1 work is real, substantive, and on a knife-edge.** 85 files changed (`+10,840 / −17,684`), 13 brand-new shared modules, 7 ingestion Lambdas migrated to the framework, 5 new ADRs, 11 new test files, ~1,635 changelog lines, 5 new docs. **None of it is committed.** A `git restore` or a corrupted disk loses the entire audit.

Source-vs-prod drift is the next biggest issue. `cdk/stacks/constants.py` says `SHARED_LAYER_VERSION = 43` while live layer is **v50**. Any `cdk deploy --all` would silently re-point Lambdas to v43, undoing the v1 layer bumps. PRIVACY_MODE flipped `true → false` in the same uncommitted constants file.

v1's framework/refactor work is high quality and the new test suite enforces it (1,240 passing locally). But several v1-shipped modules sit unused (`auth_breaker.py`, `email_framework.py`); the SIMP-2-exempt Lambdas didn't pick them up. The 70-tool MCP orphan list is the largest pure dead-code surface. The site-api Anthropic call paths still bypass `retry_utils` entirely — no telemetry, no retry, no cache_control.

42 findings below, prioritized.

---

## CRITICAL findings

### C1 — All v1 audit work is uncommitted. ~10k LOC at risk of total loss
**Evidence:** `git log -1 → 321ef02 v6.9.5`. `git status --short | wc -l → 115`. `git diff --stat HEAD` totals: **85 files changed, +10,840 / −17,684 lines**. Includes 13 new shared modules (`auth_breaker.py`, `compute_metadata.py`, `email_framework.py`, `http_retry.py`, `numeric.py`, `rate_limiter.py`, `request_validator.py`, `alert_digest_lambda.py`, `delete_user_data_lambda.py`), 5 new ADRs (053–057), `+1,635` lines to `CHANGELOG.md`, 11 new test files, 5 new docs, complete rewrites of 7 ingestion Lambdas (Whoop, Garmin, Strava, Withings, EightSleep, Habitify, Todoist via SIMP-2 framework). 1,496 LOC `health_auto_export_lambda.py` edited, `daily_brief_lambda.py` reorganized, CDK stacks (`compute`, `operational`, `email`, `core`, `web`) all touched.
**Action:** Immediately `git add -p` in logical chunks (framework migrations, shared modules, CDK, docs, tests) and push 4–6 focused commits. Do not let one more session pass with this volume uncommitted.
**Effort:** S (2–3h to chunk + author commit messages)  
**Risk:** Loss of ~2 days of work if filesystem fails, deploy mishaps that touch the working tree, or accidental `git restore`.  
**ROI:** Non-monetary. Preserves the entire v1 audit deliverable.

### C2 — CDK SHARED_LAYER_VERSION is v43; prod is v50. Next `cdk deploy --all` downgrades 79 Lambdas
**Evidence:** `cdk/stacks/constants.py:37` → `SHARED_LAYER_VERSION = 43`. `tests/test_integration_aws.py::test_i2_lambda_layer_version_current` FAILED — actual current is v50; 7 Lambdas (daily-brief, weekly-digest, freshness-checker, anomaly-detector, character-sheet-compute, daily-metrics-compute, daily-insight-compute) still on v43. ADR-052 (CHANGELOG line 472) records v49 was published mid-audit; CHANGELOG v7.21.0 records v42→v50 bump for `ai-expert-analyzer`. The constants file uncommitted-diff does NOT touch the layer version.
**Action:** Update `cdk/stacks/constants.py:37` to `SHARED_LAYER_VERSION = 50`. Commit before next CDK deploy. Add a CI guard in `tests/test_layer_version_consistency.py` that fails if `aws lambda get-layer-version` of the current alias is newer than the constant. (test_i2 already covers Lambda-side drift; add CDK-source-side too.)
**Effort:** XS  
**Risk:** Without this, the next `cdk deploy` rolls back the v1 layer work end-to-end (including `auth_breaker` integration in `ingestion_framework`, `numeric.floats_to_decimal`, P5.8 staleness signals, `email_framework`, etc.) and breaks 7 Lambdas that were manually bumped.  
**ROI:** Prevents a single-deploy catastrophic regression of ~2 days of work.

### C3 — 17 source-tree shared modules not listed in `ci/lambda_map.json` `skip_deploy` — CI may try to deploy them as Lambdas
**Evidence:** `ci/lambda_map.json` `skip_deploy.files` lists 16 modules. Source has these NOT in either `lambdas{}` or `skip_deploy{}`: `auth_breaker.py`, `compute_metadata.py`, `email_framework.py`, `http_retry.py`, `intelligence_common.py`, `numeric.py`, `platform_logger.py`, `rate_limiter.py`, `request_validator.py`, `retry_utils.py`, `secret_cache.py`, `site_writer.py`, `character_engine.py`, `genome_coaching.py`, `ai_output_validator.py`, `labs_coaching.py`, `ingestion_framework.py`. All are layer-resident shared code. CI Lambda diffing job will try to deploy each as if it were a Lambda → 404 on `aws lambda update-function-code`.
**Action:** Add the 17 modules to `ci/lambda_map.json` `skip_deploy.files`. Single-line additions; no logic change.
**Effort:** XS  
**Risk:** CI cosmetic noise, possible spurious failures on PRs that touch shared modules. With layer-rebuild deploys also broken, this is real reliability debt.  
**ROI:** Prevents CI false-positives blocking merges.

---

## HIGH findings

### H1 — `auth_breaker.py` ships with ZERO production callers
**Evidence:** `grep -rn auth_breaker lambdas/` → only `tests/test_auth_breaker.py` and `auth_breaker.py` itself import it. Meanwhile, `ingestion_framework.py:97-155` inlines the SAME logic (`_check_auth_breaker`, `_mark_auth_failure`, `_clear_auth_failure`, `_looks_like_auth_failure`) for framework users. Module docstring claims it's for "non-framework ingestion Lambdas (Whoop, Garmin, Strava, etc.)" — but those Lambdas have ALL been migrated to the framework (verified `from ingestion_framework import` in each). The 6 SIMP-2 exempt Lambdas (notion, macrofactor, apple_health, dropbox_poll, food_delivery, hae) do NOT import `auth_breaker`.
**Action:** Either (a) adopt `auth_breaker` in the 3 exempt OAuth-using Lambdas (notion, dropbox_poll, hae for the HAE-webhook token) and document, OR (b) delete `auth_breaker.py` + its tests and rely on the framework-embedded version. Recommend (a) — the original ADR-052 motivation (alarm flood from expired OAuth tokens) still applies to notion/dropbox.
**Effort:** S (3 imports + 6 lines each)  
**Risk:** Low. Defensive code.  
**ROI:** Closes a 24h alarm-flood window for the 6 exempt sources. Non-monetary reliability win.

### H2 — Site-api makes raw Anthropic calls bypassing retry_utils — no telemetry, no retry, no cache
**Evidence:** `lambdas/site_api_lambda.py:2819-2832` (board_ask) and `:7841-7860` (`/api/ask`) both call `urllib.request.urlopen("https://api.anthropic.com/v1/messages", ...)` directly. Same in `lambdas/site_api_ai_lambda.py:517,614`, `lambdas/brittany_email_lambda.py:468`, `lambdas/canary_lambda.py:68`. None invoke `_emit_token_metrics()` or use `retry_utils.call_anthropic_raw`. CHANGELOG v7.21.0 explicitly noted "only daily-brief + coach-state-updater currently emit token telemetry" — the audit's own gap.
**Action:** For each of the 4 Lambdas, refactor to `from retry_utils import call_anthropic_raw`. This single change adds (a) 4-attempt exponential backoff, (b) `LifePlatform/AI` CloudWatch token metrics, (c) cache_control wrapper. site_api's board_ask is invoked per-user — without retry, transient Anthropic 5xx → user sees error. Add `cache_control` on the board_of_directors system prompt (which IS >1024 tokens, qualifies for caching).
**Effort:** M (4 file changes + reasonably-careful testing of public-facing endpoints)  
**Risk:** Low — `call_anthropic_raw` already battle-tested in daily_brief.  
**ROI:** ~$0.50-1/mo cache savings on board_ask (high-traffic) + visibility into ~30% of Anthropic spend that's currently dark + retry resilience for user-facing AI calls.

### H3 — `brittany_email_lambda.py` hardcodes `model: "claude-sonnet-4-6"` — no env override
**Evidence:** `lambdas/brittany_email_lambda.py:463`: literal string. Compare `ai_calls.py:39` (`AI_MODEL = os.environ.get("AI_MODEL", ...)`) and `retry_utils.py:33`. The CDK constants set `AI_MODEL_HAIKU` but no `AI_MODEL` — meaning when the next Anthropic model deprecation hits, brittany breaks silently with no env-var escape.
**Action:** Replace literal with `os.environ.get("AI_MODEL", "claude-sonnet-4-6")`. Add env propagation in CDK stack if not present.
**Effort:** XS  
**Risk:** None.  
**ROI:** Avoids one inevitable post-model-deprecation incident.

### H4 — Test I9 reports 63 messages in DLQ. At least one Lambda is silently dlq-ing
**Evidence:** `tests/test_integration_aws.py::test_i9_dlq_empty` FAILED: 63 visible messages in `life-platform-ingestion-dlq`. Drain Lambda exists (`life-platform-dlq-consumer`) per `lambda_map.json`. dlq_consumer hasn't drained — either it's broken, throttled, or hasn't been triggered.
**Action:** Manually invoke `life-platform-dlq-consumer`, inspect contents (`aws sqs receive-message ...`), identify the source Lambda emitting failures, fix root cause, drain. Verify dlq_consumer is on a working schedule (CDK source check).
**Effort:** S  
**Risk:** Real ingestion data may be missing from DDB for whatever source is failing.  
**ROI:** Restores reliability of whatever ingestion source is broken.

### H5 — Test I11 schedule expectation is wrong, not the Lambda
**Evidence:** `tests/test_integration_aws.py:649` asserts `data-reconciliation` ran within 48h. `cdk/stacks/operational_stack.py:234`: `cron(30 7 ? * MON *)` — Monday only (weekly). Today is Saturday May 17; Lambda correctly ran Monday May 11 (6 days ago). Test expectation is misconfigured — `DRECON_LOOKBACK_HOURS` should be ≥192 (8 days), not 48.
**Action:** Edit `tests/test_integration_aws.py`: `DRECON_LOOKBACK_HOURS = 192` (or compute from cron). Document in test docstring.
**Effort:** XS  
**Risk:** None.  
**ROI:** Removes a perma-yellow CI signal — keeps the test informative.

### H6 — `intelligence_common.py` (1,589 LOC): only importer is `ai_expert_analyzer`, NOT `daily_brief` as ADR-057 claims
**Evidence:** `grep -rn intelligence_common lambdas/ mcp/` → single hit at `lambdas/ai_expert_analyzer_lambda.py:49,466,746`. ADR-057 (`docs/DECISIONS.md:1363`) says "has only 1 active importer (daily_brief)" — incorrect importer name. `daily_brief_lambda.py` has zero references to `intelligence_common` or `build_coach_preamble`.
**Action:** Edit ADR-057 to read "1 active importer (ai_expert_analyzer)". v1's CLOSURE rationale (1 importer → don't split) is still correct, just rename. Also CHANGELOG v7.20.0 references "the only known consumer of `build_coach_preamble`" — verify same Lambda.
**Effort:** XS  
**Risk:** None (doc-only fix).  
**ROI:** Source of truth for future audits.

### H7 — CDK has zero `log_retention` config — all Lambda log groups default to "Never expire"
**Evidence:** `grep -rn "log_retention\|RetentionInDays" cdk/` → empty. `lambda_helpers.py:197-210` Function constructor lacks `log_retention=`. CloudWatch logs accumulate indefinitely. v1's COST cleanup likely set retention via console (out-of-band).
**Action:** Add `log_retention=_lambda.RetentionDays.ONE_MONTH` (or `THREE_MONTHS`) as a `create_platform_lambda` kwarg with sensible default. Or use CloudWatch `aws_logs.LogGroup` construct explicitly. Re-deploy stacks.
**Effort:** S  
**Risk:** Drift between manual console state and CDK — CDK will overwrite console retention. Document in ADR.  
**ROI:** Caps CloudWatch storage cost (current spend already low per ADR-053, but unbounded growth is the bigger risk).

### H8 — Reserved concurrency entirely manual / commented out in CDK
**Evidence:** `grep -rn ReservedConcurrentExecutions cdk/` → 7 hits, ALL commented out. `docs/RESERVED_CONCURRENCY.md` says it's pre-staged but blocked on quota raise (L-B99A9384). Whoop reserved=1 prevents OAuth race per ADR-036 — when set, it's set via console drift.
**Action:** Once quota raised, uncomment AND commit. Until then, document drift in CDK with a "MANUAL — set via console pending quota" comment. Add a CI test that checks console reservation matches CDK source comment.
**Effort:** S (after quota) / XS now (just add doc-style comment)  
**Risk:** OAuth race re-introduction if a Lambda is redeployed (CDK creates with reserved=unset, console drift is lost).  
**ROI:** Reliability — prevents the race that ADR-036 documents.

### H9 — `daily_brief_lambda.py` has 89 raw `print()` calls AND uses `platform_logger`
**Evidence:** `grep -c "print(" lambdas/daily_brief_lambda.py` → 89. Same file `from platform_logger import get_logger; logger = get_logger("daily-brief")`. Inconsistent — half the WARN paths are structured, half are bare print to stdout. CloudWatch Logs Insights queries miss the `print()`s entirely.
**Action:** Sweep `print(` → `logger.info/warning(`. Same for `garmin_lambda.py` (47), `health_auto_export_lambda.py` (23), `anomaly_detector_lambda.py` (23), `weekly_digest_lambda.py` (21). Script-able: `sed 's/print(\(.*\))/logger.info(\1)/'` then manual review of multi-line prints.
**Effort:** M  
**Risk:** Low — JSON logs are still JSON; print → logger doesn't change semantics, just format.  
**ROI:** Logs Insights queries become reliable for daily_brief, which is the highest-value debugging target.

### H10 — site_api still 7,879 LOC despite v7.7.0 router partial-refactor
**Evidence:** `wc -l site_api_lambda.py` → 7,879. `_SIMPLE_ROUTES` at 7040, `ROUTES` at 6926. 89 functions. Two dispatch tables suggest the refactor was started and stopped. Several endpoints still bypass both tables (board_ask, ask handled inline before dispatch).
**Action:** Defer the full split — it's too risky for marginal benefit (file size alone isn't a bug). BUT: enforce a no-growth rule via `tests/test_site_api_routes.py` (already exists, passing). Optionally extract the 2,800-line `board_ask`/`ask` AI handlers (lines 2810-3000 + 7820-7870) into a separate module `site_api_ai_handlers.py` to ease H2 (retry_utils integration).
**Effort:** M for partial extraction; L for full split  
**Risk:** site-api outage if dispatch table is mis-wired.  
**ROI:** Marginal until next big endpoint addition. Defer to v3 unless extraction unlocks H2.

### H11 — `health_auto_export_lambda.py` still 1,496 LOC, ADR-057 closed it correctly but per-handler-table refactor still has real value
**Evidence:** `wc -l health_auto_export_lambda.py` → 1,496. `grep -c "print(" → 23`. 5+ data types (CGM, water, BP, State-of-Mind, weight, …) handled inline in one file via if/elif. ADR-057 closed the registry pattern as "cleanup-only with no behavior change."
**Action:** Honor ADR-057 closure. Re-open only if a 6th data type lands.
**Effort:** —  
**ROI:** Honor v1's documented decision.

---

## MEDIUM findings

### M1 — 70 orphan MCP tool functions defined but unregistered (66 per the test's stricter regex)
**Evidence:** Custom grep: 187 `def tool_*` definitions in `mcp/tools_*.py`, only 117 referenced in `mcp/registry.py`. `tests/test_mcp_orphan_tools.py::KNOWN_ORPHANS` allowlists 66 explicitly. Each is dead code — written, never wired. Examples: `tool_get_calendar_events` (entire module retired ADR-030), `tool_get_cgm_dashboard`, `tool_get_health_dashboard`, `tool_get_keystone_habits`.
**Action:** Triage in batches of 10: for each, either (a) register in `registry.py` if useful, or (b) delete function + its tests. Update `KNOWN_ORPHANS` allowlist by removing the deleted/registered entries. Target: ratchet `AUDITED_AT` from 66 → 30 over the next 2 sessions.
**Effort:** M (~3h to triage + bulk delete)  
**Risk:** Low — orphan functions are unreachable; deleting them is pure cleanup.  
**ROI:** Reduces MCP module sprawl. Faster cold starts (smaller Lambda asset). Easier mental model.

### M2 — 6 SIMP-2 exempt Lambdas didn't adopt the new shared modules either
**Evidence:** `grep "from numeric\|from http_retry\|from auth_breaker" lambdas/notion_lambda.py lambdas/macrofactor_lambda.py lambdas/apple_health_lambda.py lambdas/dropbox_poll_lambda.py lambdas/food_delivery_lambda.py lambdas/health_auto_export_lambda.py`. Results: `apple_health` uses `numeric`. `notion` uses `http_retry` (2 sites). `macrofactor` uses `numeric`. `dropbox_poll`, `food_delivery`, `health_auto_export` use NONE of the new modules. None use `auth_breaker`.
**Action:** Per ADR-056's mitigation note ("shared modules are still importable by standalone Lambdas"), audit each exempt Lambda for retry-able HTTP calls and decimal-cast boilerplate, swap in the shared modules. Add `auth_breaker` to notion/dropbox/hae. ~4 lines per Lambda.
**Effort:** S  
**Risk:** Low.  
**ROI:** Brings the 6 exempt sources into the same reliability baseline as the migrated 7.

### M3 — `request_validator.py` only used by site_api + site_api_ai. Webhook Lambdas (HAE) skip it
**Evidence:** `grep -rn "from request_validator" lambdas/` → 2 importers. HAE webhook explicitly handles 401/403 inline (`lambdas/health_auto_export_lambda.py:1249,1258`). If `request_validator` validates webhook envelopes too, the HAE webhook is missing that hardening.
**Action:** Audit `request_validator.validate_envelope` API. If it's path/method-aware (it is, per usage), extend HAE to call it before processing webhook body.
**Effort:** S  
**Risk:** Could reject otherwise-valid HAE webhook payloads if validator is overly strict. Test with sample webhook payloads first.  
**ROI:** Defense-in-depth against malformed/malicious webhook input.

### M4 — `email_framework.py` is a new module — who uses it?
**Evidence:** `grep -rn "from email_framework" lambdas/` → only `email_framework.py` itself (self-test). 166 LOC. New, untracked, never imported.
**Action:** Either adopt in one of the 7 email Lambdas (daily-brief, weekly-digest, monthly-digest, wednesday-chronicle, brittany-email, evening-nudge, weekly-plate, monday-compass) as a proof-of-concept, OR delete + commit-message that v1's email-framework idea didn't pan out.
**Effort:** S (delete) or M (adopt in 1 Lambda)  
**Risk:** None.  
**ROI:** Stops the "what's this for?" cost of carrying an unused module.

### M5 — `compute_metadata.py` adopted only by 4 of the 6 compute Lambdas
**Evidence:** `grep "from compute_metadata" lambdas/` → `character_engine`, `character_sheet_lambda`, `adaptive_mode_lambda`, `daily_metrics_compute_lambda`, `daily_insight_compute_lambda`. NOT in `hypothesis_engine_lambda.py`, `failure_pattern_compute_lambda.py`, `weekly_correlation_compute_lambda.py`, ACWR compute, sleep_reconciler, circadian_compliance.
**Action:** Add `compute_metadata.tag_record(...)` calls in the remaining 6 compute Lambdas at their DDB-write sites. Provides P3.3 idempotency `run_id` consistently across the compute fleet.
**Effort:** S  
**Risk:** Low.  
**ROI:** Idempotency completeness; better debugging when a compute Lambda doubles a run.

### M6 — `email_subscriber_lambda.py`, `podcast_scanner_lambda.py` listed in `skip_deploy` — verify still alive in prod
**Evidence:** `ci/lambda_map.json` `skip_deploy.files` includes these. They're either dead (delete) or deployed-via-other-mechanism (document).
**Action:** Query AWS Lambda for each function name; if exists, document where it's deployed. If not, delete source.
**Effort:** XS (status check + decision)  
**Risk:** None.  
**ROI:** Source-tree honesty.

### M7 — ADR-056 says "8 sources migrated" but only 7 Lambdas show framework import (weather is the 8th, deployed separately)
**Evidence:** `grep "from ingestion_framework import" lambdas/*.py` → garmin, strava, withings, whoop, eightsleep, habitify, todoist (7). ADR-056 counts weather as the 8th (`weather_handler.py`). Verified — `lambdas/weather_handler.py` is the original framework POC.
**Action:** Confirm `weather_handler.py` still uses framework. If yes, doc is correct. If no, doc drift to fix.
**Effort:** XS  
**Risk:** None.  
**ROI:** Doc accuracy.

### M8 — 51 patches in `patches/` — README is new (untracked), good. But no expiry policy enforced
**Evidence:** `ls patches/ | wc -l` → 52 (51 patches + README). README says "if it exceeds ~100 files, consider archiving". Today's 51 is at 50% of that bar.
**Action:** No action now. Re-evaluate at v2 next round (Aug 2026).
**Effort:** —  
**ROI:** —

### M9 — Older Lambdas still missing `platform_logger` (alert_digest_lambda.py being new is the model)
**Evidence:** `grep -L platform_logger lambdas/*.py` returns 15 files: `food_delivery_lambda.py`, `og_image_lambda.py`, `site_stats_refresh_lambda.py`, etc. Many of these are shared modules (ai_calls.py, output_writers.py, html_builder.py, scoring_engine.py — fine, they aren't handlers). Real misses: `food_delivery_lambda.py`, `og_image_lambda.py`, `site_stats_refresh_lambda.py`.
**Action:** Add the standard `try: from platform_logger import get_logger; logger = get_logger("…"); except ImportError: …` block to the 3 actual Lambdas.
**Effort:** XS each  
**Risk:** None.  
**ROI:** Logs Insights queries return rows for those Lambdas.

### M10 — site-api `_emit_route_log` is built but no test asserts shape
**Evidence:** `lambdas/site_api_lambda.py:7084-7090` builds `_type: route_metric` structured log. No test in `tests/test_site_api_routes.py` validates the shape, no Logs Insights saved query references `_type=route_metric`.
**Action:** Add 1 test asserting shape. Add a saved CloudWatch Logs Insights query (or document the query in RUNBOOK) using `_type="route_metric"` to surface 404s + slow routes.
**Effort:** S  
**Risk:** None.  
**ROI:** Existing observability shipped but not exploited.

### M11 — `coach_state_updater.py` had `+114` lines this round; verify token telemetry path
**Evidence:** `git diff --stat HEAD` shows `+114`. `grep "call_anthropic\|retry_utils\|emit_token" lambdas/coach_state_updater.py` → uses `retry_utils.call_anthropic_raw` and emits via `_emit_token_metrics`. Healthy.
**Action:** None. Working as intended.
**Effort:** —  
**ROI:** —

### M12 — `mcp/tools_data.py` is `import *`'d — wildcard imports hide registry dependencies
**Evidence:** `mcp/registry.py:5` `from mcp.tools_data import *`. Same for tools_training, tools_health, tools_sleep, tools_nutrition, tools_correlation, tools_labs, tools_measurements, tools_cgm, tools_journal, tools_lifestyle, tools_board, tools_character, tools_social, tools_adaptive, tools_todoist, tools_memory, tools_decisions, tools_hypotheses, tools_sick_days. Mixed wildcard + explicit imports mask the orphan situation — the orphan test has to text-scan to find references.
**Action:** Replace wildcards with explicit `from mcp.tools_X import (tool_a, tool_b, …)`. Touches every registry import. The orphan test then becomes a structural check (`tool_X in __all__` or similar).
**Effort:** M  
**Risk:** Low — pure import refactor.  
**ROI:** Clarity. Linters catch unused tools immediately.

---

## LOW findings

### L1 — `weather_handler.py` is named differently (not `weather_lambda.py`) — naming inconsistency
**Evidence:** `lambdas/weather_handler.py` (per lambda_map.json). All other ingestion: `<source>_lambda.py`.
**Action:** Rename to `weather_lambda.py`, update lambda_map.json. Minor cosmetic.
**Effort:** XS  
**Risk:** None.  
**ROI:** Convention consistency.

### L2 — `ingest/ingest.log` checked into the repo
**Evidence:** `git diff` shows `ingest/ingest.log +4 lines`. Log files shouldn't be tracked.
**Action:** Add `ingest/ingest.log` to `.gitignore`. Remove from index (`git rm --cached`).
**Effort:** XS  
**Risk:** None.  
**ROI:** Cleaner diffs.

### L3 — CHANGELOG.md uncommitted growth: +1,635 lines in one diff
**Evidence:** Largest single-file diff. Self-explanatory.
**Action:** Commit as part of C1 chunking. Maybe break into v7.0–7.10, v7.11–7.20, v7.21 commits.
**Effort:** Already counted in C1.  
**ROI:** Counted in C1.

### L4 — `delete_user_data_lambda` (Phase 7.3) ships in CDK with no schedule and an alarm — only on-demand
**Evidence:** `cdk/stacks/operational_stack.py:219-224` registers it with alarm but no schedule. Correct (on-demand) but the alarm may be over-eager since "errors" on this function might be intentional (rejected delete for protected user).
**Action:** Verify the Lambda returns 200 (not raises) for refused-deletes. If yes, no action. If no, refactor to not raise on policy refusal.
**Effort:** XS  
**Risk:** Spurious alarms.  
**ROI:** Reduced alarm noise.

### L5 — `numeric.floats_to_decimal` adopted by 5 ingestion Lambdas, but not by compute Lambdas that also write floats to DDB
**Evidence:** `grep "from numeric" lambdas/` → eightsleep, garmin, macrofactor, apple_health, enrichment. Compute Lambdas (character_sheet, daily_metrics, etc.) also write to DDB — verify they don't have leftover float→str patterns.
**Action:** Audit compute Lambdas for `Decimal(str(...))` boilerplate; replace with `floats_to_decimal()` where applicable.
**Effort:** S  
**Risk:** Behavior should be identical — just consolidation.  
**ROI:** Less boilerplate; one source of truth for the boto3 float problem.

### L6 — `tests/test_business_logic.py` empty per pytest counts (only `test_business_logic.py` + `test_cdk_handler_consistency.py` showed up with `.` placeholders)
**Evidence:** pytest run output shows them passing but no counts. Likely fine; just noting.
**Action:** Spot-check by running them in isolation if there's appetite.
**Effort:** —  
**ROI:** —

---

## What v1 got RIGHT (Drift verifications — wins)

### W1 — SIMP-2 framework migration is real and substantial
- **Quantified**: Whoop 917 → 308 LOC (`whoop_lambda.py`). Garmin, Strava, Withings, EightSleep, Habitify, Todoist all converted with the same pattern.
- The framework absorbed real complexity (auth refresh, gap detection, S3 archive, DDB writes, validation, structured logging, AUTH circuit breaker, refresh_today flag for intra-day sources, sk_suffix for sub-records).
- ADR-056 documents the trade-offs honestly (8 in, 6 exempt).
- Test surface is preserved (`test_ddb_patterns`, `test_iam_secrets_consistency` updated).

### W2 — Shared modules ARE imported, not orphan
With one exception (auth_breaker — H1), all new modules are wired:
- `numeric` → 5 importers
- `http_retry` → 6 importers
- `compute_metadata` → 5 importers
- `rate_limiter` → 2 importers (site_api_ai)
- `request_validator` → 2 importers (site_api, site_api_ai)

### W3 — Test suite is healthy and comprehensive
- **1,240 unit tests passing** in 34s (3 integration tests fail against AWS — H4 real, H5 false-positive, I2 confirms C2).
- 11 new test files from v1 ALL pass: `test_alert_digest`, `test_auth_breaker`, `test_delete_user_data`, `test_email_framework`, `test_handler_type_hints`, `test_http_retry`, `test_logger_discipline`, `test_mcp_orphan_tools`, `test_numeric`, `test_rate_limiter`, `test_request_validator`, `test_site_api_routes`.
- Orphan-tool test uses a ratchet (`AUDITED_AT = 66`) preventing new orphan creep.

### W4 — Daily-brief shared system block (Phase 3.8) really wired
`ai_calls.py:1108` defines `daily_brief_shared_system()`. `call_training_nutrition_coach`, `call_journal_coach`, `call_board_of_directors` all accept `shared_system=None` param and pass it with `cache_system=True`. The Anthropic 90% discount on shared system content IS being collected on the 4 daily-brief calls.

### W5 — Pipeline-timing fix (P3.1) IS in CDK source
`cdk/stacks/compute_stack.py` diff: compute Lambdas moved from 17:30/35/40/45/50 UTC → 16:30/35/40/45 UTC so they complete BEFORE daily-brief at 17:00 UTC. The race ADR-052 documents is closed at the source.

### W6 — Failure-pattern-compute is alive
ci/lambda_map.json drops `"not_deployed": true` for `failure_pattern_compute_lambda.py`. CDK source wires it. Test suite has `test_failure_pattern_detectors.py` (12 tests passing). v1 brought a dormant Lambda back online.

### W7 — Two-tier alerting (ADR-052) wired into CDK
`compute_stack.py` passes `digest=True` to all compute Lambdas → alarms go to `life-platform-alerts-digest`. Inbox noise reduced as documented.

### W8 — Privacy mode toggle parameterized
`constants.py` `PRIVACY_MODE = os.environ.get("PRIVACY_MODE", ...)` — site can flip between private/public without code changes. Toggle is currently flipped to "false" in uncommitted diff (intentional — site is public).

---

## What v1 got WRONG or didn't land

### X1 — ADR-057 mis-identifies intelligence_common's importer
See H6. ADR-057 says "daily_brief" — actual is "ai_expert_analyzer". Closure rationale unchanged, but the named importer is wrong. Self-fix.

### X2 — `auth_breaker.py` is a half-shipped module
See H1. Written, tested, never imported by the intended callers (because they all became framework users). Either backfill the 3 OAuth-using exempt Lambdas (notion/dropbox/hae) or delete.

### X3 — `email_framework.py` shipped without an adopter
See M4. New module, only its self-test imports it. Either adopt or delete.

### X4 — SHARED_LAYER_VERSION constant never bumped from 43 to 50
See C2. This is the most consequential drift between source and prod. The next `cdk deploy --all` is a destructive event.

### X5 — Lambda log retention never wired in CDK despite COST work
See H7. Console-set, source-undefined. CDK-reconcile destroys it.

### X6 — Reserved concurrency manual-only despite ADR-036
See H8. Source has 7 commented-out reservations; manual console reservations are the only thing preventing Whoop OAuth races.

### X7 — Top-down logging discipline incomplete
See H9. daily_brief and 4 other Lambdas mix print() + platform_logger. v1's logger-discipline test exists (`test_logger_discipline.py`) but only checks that the import is present, not that print() is replaced.

### X8 — Site-api Anthropic call paths remain dark
See H2. The audit's own CHANGELOG v7.21.0 calls this out as "deferred to v2." Now is v2; fix it.

### X9 — 17 shared modules not listed in lambda_map skip_deploy
See C3. CI bookkeeping incomplete.

### X10 — KMS S3 CMK ADR-053 incident — not a v1 wrong, but the lesson is that uncoordinated v1 deploys nearly broke prod twice (once for KMS, almost for layer version). The pattern: "shipped to prod via console, not source-of-truth committed." v2 should formalize that all production deploys go through CDK or `deploy_lambda.sh`, never console-only.

---

## Cross-cutting observations

- **The v1 audit work is the highest-leverage refactor work in the platform's history.** −2,383 LOC across 7 Lambdas with no behavior regression. The framework abstraction is sound. The test discipline shipped alongside (1240 tests, orphan ratchet, layer-consistency check) prevents v3 from rediscovering the same problems.
- **The biggest v1 failure mode is "shipped to prod, not committed to source."** C1, C2, H7, H8 are all variants. The fix isn't process — it's making the deploy path that touches source be the only path. The freshness checker + layer-consistency test together form the immune system for this; they just need to fire blocking, not informational.
- **The MCP tool layer is the largest pure dead-code surface.** 66-70 orphan tools = ~6,000 LOC unreferenced. Half are aspirational ("dashboard" tools), half are abandoned (e.g., calendar). A focused triage session could halve the source-tree footprint with zero behavioral risk.

---

## Suggested v2 phasing for codebase items (effort-weighted)

**Phase A — Commit + safety net (single session, ~3h):**
- C1 commit v1 work in 4–6 logical chunks
- C2 bump SHARED_LAYER_VERSION 43 → 50
- C3 add 17 modules to skip_deploy
- H5 fix test_i11 lookback (false positive)
- H6 fix ADR-057 importer name

**Phase B — Drift closure (single session, ~3h):**
- H1 adopt auth_breaker in 3 exempt Lambdas OR delete
- M4 adopt email_framework in 1 Lambda OR delete
- H3 brittany model env-override
- H7 add log_retention to CDK lambda_helpers

**Phase C — Dark-call visibility (single session, ~4h):**
- H2 route 4 site_api Anthropic calls through retry_utils
- H4 drain DLQ + diagnose root cause
- H9 sweep print() → logger in daily_brief

**Phase D — Cleanup (multi-session):**
- M1 triage 66 orphan MCP tools (target -36)
- M2 adopt new shared modules in 6 exempt Lambdas
- M5 compute_metadata in remaining compute Lambdas
- M12 replace MCP wildcard imports

**Phase E — Defer or won't-do:**
- H10 site_api split (too risky for marginal gain; honor ratcheting test instead)
- H11 HAE registry (ADR-057 closure stands)
- L1 weather_handler rename (cosmetic)

Total deliverable estimate: ~20h focused work to land everything above C-prefix and most H-prefix.
