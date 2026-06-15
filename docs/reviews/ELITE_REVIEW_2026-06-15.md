# Elite Platform Review — 2026-06-15

> **Deep multi-agent external-lens review.** 7 dimensions · large finder pools + loop-until-dry on the high-value dims · every finding put through a **3-vote diverse-lens adversarial refutation** (correctness / reproducibility / impact). Run cost: **558 agents, ~25M tokens, ~5h**. The orchestration crashed on the final synthesis step (session token ceiling); this report was **reconstructed from the verified transcripts** — the findings + verdicts are intact.

**89 findings survived verification** ({'P1': 47, 'P2': 41, 'quickwin': 1}). Candidates: 172, refuted/dropped: 83 (~48% — the adversarial pass doing its job). **Zero P0** — nothing on fire.

## Executive summary

The platform's craft holds up — the real risks cluster into a few clear themes, and they **strongly validate the manual findings from earlier today**:

1. **Silent-failure is systemic (the headline).** The biggest cluster (reliability + parts of bug/quality) is *exactly* the class that hid the Garmin/Strava deaths: compute Lambdas **return HTTP 500 instead of raising** (so EventBridge sees success), EventBridge targets have **no DLQ / max-event-age** (silent event loss after 2 retries), OAuth token-writeback **swallows errors**, the SIMP-2 auth circuit-breaker **clears on any success** (masking intermittent auth), and Notion can **silently brick all future runs**. Today's Garmin alarm was one instance of a platform-wide pattern.
2. **The public write surface is under-defended.** Multiple POST endpoints (`challenge_checkin`, `challenge_vote`, `experiment_suggest`, `submit_finding`, `nudge`) have **in-memory rate limits that reset on cold start**, **no idempotency** (double-submit on retry), **no `catalog_id` validation**, and weak origin auth — abuse/spam/data-pollution risk now that the WAF is gone. Plus **prompt-injection via history replay** in `/api/ask`.
3. **A real money leak.** Prompt caching appears **disabled on the daily-brief AI calls** — sacrificing the ~90% cache discount — and retry logic can **re-bill** Bedrock on transient errors. Direct hits on the $75/mo ceiling.
4. **IAM over-grants.** The DLQ consumer has broad `lambda:invoke`, and pipeline-health reads **all** `life-platform/*` secrets.
5. **Computed-but-not-surfaced features.** Circadian-compliance and unified sleep-reconciliation are computed daily but never exposed — high-leverage, low-effort wins.

**Caveat (honesty):** these survived a 3-vote refutation, but per the standing rule I have **not yet independently re-verified each one** against full code — several P1s look near-duplicate or may soften on inspection (e.g. the public-write-abuse items are lower-impact on a personal N=1 site). Treat P1 as "credible, verify-before-fixing," not "confirmed bug." I'll re-verify the top cluster before any fix lands.

## Findings by dimension
**security** 20 · **reliability** 19 · **bug** 15 · **features** 14 · **cost** 8 · **quality** 7 · **architecture** 6

## P1 (47)

| Dim | Finding | File | Effort | Votes |
|---|---|---|---|---|
| architecture | Multiple ingestion lambdas have unfiltered DDB reads that may contaminate output with pilot-phase data (P1) | `lambdas/ingestion/whoop_lambda.py:fetch_date (details line estimate); enrichment_lambda.py; journal_enrichment_lambda.py; withings_lambda.py` | M | 2/3 |
| architecture | Bedrock cost overflow risk if budget_guard SSM parameter is missing or stale (P1) | `lambdas/bedrock_client.py:107-117 and budget_guard.py:57-77` | M | 3/3 |
| architecture | phase_filter does not validate that attribute_not_exists(phase) is the right default for untagged records (P1) | `lambdas/phase_filter.py:20` | M | 2/3 |
| architecture | restart_intelligence_wipe.py partition list is hand-maintained and may diverge from phase_taxonomy (P1) | `deploy/restart_intelligence_wipe.py:75-122` | M | 2/3 |
| bug | Handle_confirm DDB query missing pagination for token search | `lambdas/web/email_subscriber_lambda.py:324-332` | M | 3/3 |
| bug | Circadian compliance uses hardcoded PT offset instead of dynamic timezone | `lambdas/compute/circadian_compliance_lambda.py:157-158` | M | 3/3 |
| bug | Mismatched HRV window comment claims 7d/14d but implements 8d/14d | `lambdas/compute/daily_insight_compute_lambda.py:1508-1513` | S | 2/3 |
| bug | Unsafe string parsing of ACWR zone from content field with potential empty result | `lambdas/compute/daily_insight_compute_lambda.py:1967` | S | 2/3 |
| bug | Unsafe timezone mixing — PT vs UTC in active experiment days calculation | `lambdas/web/site_api_social.py:481` | S | 2/3 |
| bug | Large exception catch-all swallowing DynamoDB errors without logging | `lambdas/web/site_api_lambda.py:786-787` | S | 3/3 |
| bug | Large exception catch-all wrapping entire endpoint — unlogged failures degrade gracefully | `lambdas/web/site_api_lambda.py:807-809` | M | 2/3 |
| bug | Strava OAuth refresh missing response field validation | `lambdas/ingestion/strava_lambda.py:50-69` | S | 2/3 |
| bug | site_api_lambda POST endpoints missing strong origin authentication | `lambdas/web/site_api_lambda.py:563-570` | M | 2/3 |
| bug | ingestion_framework.py SECRET_WRITEBACK may fail silently after OAuth refresh | `lambdas/ingestion_framework.py:522-531` | M | 3/3 |
| cost | Prompt caching disabled on all 4 daily-brief AI calls — sacrificing 90% cost savings | `lambdas/ai_calls.py:479,550,801,1014` | M | 2/3 |
| cost | Retry logic may re-bill on ephemeral errors without accounting for budget overshoot | `lambdas/retry_utils.py:27-28,156-194` | M | 2/3 |
| cost | Retry logic invokes bedrock_client.invoke() up to 4 times on transient errors; success response may not occur but tokens may be billed | `lambdas/retry_utils.py:155-193` | L | 3/3 |
| features | Habitify's 'pending' state (in-progress habits) not yet reflected in scoring consumers | `lambdas/ingestion/habitify_lambda.py:32-33` | M | 3/3 |
| features | Garmin OAuth refresh 429-breaker suppresses alerts for 3 hours, masking data gaps | `lambdas/ingestion/garmin_lambda.py:180-190` | M | 3/3 |
| features | Circadian compliance score computed daily but not exposed via public site API | `lambdas/compute/circadian_compliance_lambda.py:1` | S | 3/3 |
| features | Sleep unified reconciliation (merged Whoop/Eight Sleep/Apple data) computed but not exposed | `lambdas/compute/sleep_reconciler_lambda.py:1` | S | 3/3 |
| quality | experiment_suggest POST handler accepts unbounded idea field — potential DynamoDB write amplification | `lambdas/web/site_api_social.py:1228-1249` | S | 3/3 |
| quality | Silent exception swallowing in MCP tools_food_delivery.py without logging | `mcp/tools_food_delivery.py:31-32,51-52` | S | 3/3 |
| quality | Garmin ingestion silent token writeback failure with incomplete metric emission | `lambdas/ingestion/garmin_lambda.py:140-149` | M | 2/3 |
| reliability | EventBridge targets lack DLQ and max_event_age, causing silent event loss after 2 retries | `cdk/stacks/lambda_helpers.py:290` | M | 2/3 |
| reliability | Compute Lambdas return HTTP status codes instead of raising, hiding failures from EventBridge | `lambdas/compute/daily_metrics_compute_lambda.py:926` | S | 3/3 |
| reliability | daily_metrics_compute missing profile generates silent 500 response without raising | `lambdas/compute/daily_metrics_compute_lambda.py:923-926` | S | 3/3 |
| reliability | POST /api/challenge_checkin appends to list without idempotent dedup, allowing double-submission via network retries | `lambdas/web/site_api_social.py:1196-1205` | M | 3/3 |
| reliability | Garmin OAuth token writeback suppresses errors silently—refresh failure means next run uses stale token | `lambdas/ingestion/garmin_lambda.py:330-372` | S | 2/3 |
| reliability | Garmin token writeback failure suppresses error without fallback persistence | `lambdas/ingestion/garmin_lambda.py:130-149` | M | 2/3 |
| reliability | Notion ingestion silent auth failure blocks all future runs due to API circuit breaker | `lambdas/ingestion/notion_lambda.py:585-693` | S | 3/3 |
| reliability | SIMP-2 framework auth-failure circuit breaker clears on *any* successful run, masking intermittent auth issues | `lambdas/ingestion_framework.py:648-649` | S | 2/3 |
| reliability | daily_metrics_compute lambda silently returns 500 on missing profile without logging which profile is missing | `lambdas/compute/daily_metrics_compute_lambda.py:923-926` | S | 2/3 |
| reliability | Whoop Lambda concurrent invocation race on refresh_token rotation not fully covered | `lambdas/ingestion/whoop_lambda.py:307-343` | M | 3/3 |
| reliability | EventBridge targets lack DLQ and maximum event age configuration — potential silent event loss | `cdk/stacks/lambda_helpers.py:290` | S | 3/3 |
| reliability | POST /api/submit_finding uses timestamp-based dedup vulnerable to double-submission on network retries | `lambdas/web/site_api_social.py:488-520` | M | 3/3 |
| reliability | POST /api/challenge_checkin appends to list without idempotency — double-tap could create duplicate check-ins | `lambdas/web/site_api_social.py:551-580` | M | 3/3 |
| reliability | DLQ consumer (dlq_consumer_lambda.py) disabled for 6+ hours due to missing DLQ_URL env var — recent fix has no coverage | `cdk/stacks/operational_stack.py:123-130` | M | 3/3 |
| security | Over-broad Lambda invoke permission in DLQ consumer allows privilege escalation | `cdk/stacks/role_policies.py:1210-1214` | M | 3/3 |
| security | Pipeline health check reads all life-platform/* secrets, exposing OAuth keys | `cdk/stacks/role_policies.py:1925-1929` | S | 2/3 |
| security | Weak Rate Limiting on /api/nudge — In-Memory Store Resets on Cold Start | `lambdas/web/site_api_social.py:284-335` | M | 2/3 |
| security | No Rate Limiting on /api/experiment_suggest Endpoint | `lambdas/web/site_api_social.py:1228-1250` | S | 3/3 |
| security | Unauth Writes to Challenge Catalog Allow Arbitrary Challenge Checkins | `lambdas/web/site_api_social.py:1145-1226` | M | 3/3 |
| security | Submit Finding Rate Limit is In-Memory Only, Resets on Cold Start | `lambdas/web/site_api_social.py:338-424` | M | 3/3 |
| security | No validation of challenge catalog_id in /api/challenge_vote — arbitrary vote creation | `lambdas/web/site_api_social.py:861-929` | S | 3/3 |
| security | History replay in /api/ask allows attacker-controlled assistant responses to influence conversation | `lambdas/web/site_api_ai_lambda.py:589-596` | M | 3/3 |
| security | Prompt injection via untrusted history replay in /api/ask — attacker-controlled assistant responses | `lambdas/web/site_api_ai_lambda.py:589-596, 634-636` | M | 2/3 |

## P2 (41)

| Dim | Finding | File | Effort | Votes |
|---|---|---|---|---|
| architecture | Email subscriber Lambda created without shared layer attachment (potential version skew risk) | `cdk/stacks/web_stack.py:286-308` | S | 2/3 |
| bug | Silent exception swallowing with pass — overdue status never logged | `mcp/tools_challenges.py:508-509` | S | 2/3 |
| bug | Silent exception swallowing — per-item overdue computation (duplicate pattern) | `mcp/tools_challenges.py:536-537` | S | 2/3 |
| bug | Rate-limit TTL calculation does not account for clock skew or Lambda drift | `lambdas/web/site_api_social.py:701` | M | 2/3 |
| bug | Missing validation on email hash length — potential collision risk | `lambdas/web/site_api_social.py:687` | S | 2/3 |
| bug | email_subscriber_lambda handle_confirm doesn't check Query response 'LastEvaluatedKey' | `lambdas/web/email_subscriber_lambda.py:324-339` | S | 3/3 |
| cost | CloudWatch Metrics: 27 put_metric_data calls across Lambdas, mostly unsummarized | `lambdas/emails/daily_brief_lambda.py:1320` | M | 2/3 |
| cost | Google TTS (Chirp 3) rates include 1M chars/month free; no tracking of free-tier remaining budget | `lambdas/google_tts.py:1-8` | S | 2/3 |
| cost | Gemini TTS (multi-speaker) cost is 'free under 1M chars/mo' but no meter, no fallback if quota exceeded | `lambdas/gemini_tts.py:1-6,28` | M | 3/3 |
| cost | Chronicle Podcast Lambda timeout (900s) accounts for force=true re-rendering full back-catalogue, but no idempotent guard prevents accidental re-invocation | `lambdas/emails/chronicle_podcast_lambda.py:154-200` | M | 2/3 |
| cost | Site API AI Lambda (/api/ask, /api/board_ask) uses budget_guard.allow() gate but no per-tier rate limiting distinction | `lambdas/web/site_api_ai_lambda.py:164-186, 302-330` | M | 2/3 |
| features | Dropbox MacroFactor ingestion lacks monitoring for silent XLSX→CSV conversion failures | `lambdas/ingestion/dropbox_poll_lambda.py:550-559` | S | 3/3 |
| features | No MCP tool to query multi-day ingestion failure history (DLQ insights unavailable) | `lambdas/operational/dlq_consumer_lambda.py:1-30` | M | 3/3 |
| features | Site API public write endpoints lack request deduplication (nudge/finding clicks can double-count) | `lambdas/web/site_api_social.py:88-99` | M | 2/3 |
| features | No daily metric for 'data freshness trend'—can't detect slow decline of ingestion sources | `lambdas/web/site_api_data.py:165-232` | M | 2/3 |
| features | Todoist integration doesn't surface task list staleness or project structure in daily brief | `lambdas/ingestion/todoist_lambda.py` | M | 3/3 |
| features | ACWR (Acute:Chronic Workload Ratio) computed but not surfaced on public site API | `lambdas/compute/acwr_compute_lambda.py:1` | S | 2/3 |
| features | Decision fatigue signal (task load + habit compliance correlation) computed but not exposed | `lambdas/compute/daily_insight_compute_lambda.py:1359` | S | 2/3 |
| features | N+1 DynamoDB queries in /api/coaching-dashboard endpoint | `lambdas/web/site_api_lambda.py:743` | M | 2/3 |
| features | Computed insights and early warning markers stored but not exposed as public endpoint | `lambdas/compute/daily_insight_compute_lambda.py:1804` | S | 2/3 |
| features | Weekly correlation matrix computed but not exposed with statistical rigor | `lambdas/compute/weekly_correlation_compute_lambda.py:1` | S | 2/3 |
| quality | No test coverage for public write endpoints (experiment_suggest, challenge_checkin, experiment_vote, challenge_vote) | `tests/test_site_api_routes.py` | M | 3/3 |
| quality | experiment_suggest handler does not validate request_validator input because it's in write-handler catch-all | `lambdas/web/site_api_lambda.py:471-485` | M | 3/3 |
| quality | 19 copies of identical d2f() function across lambdas despite shared numeric.py module | `lambdas` | M | 3/3 |
| quality | intelligence_common.py credential preamble section silently drops errors (line 512) | `lambdas/intelligence_common.py:512-513` | S | 2/3 |
| reliability | Strava ingestion paused since 2026-05-28 (API HTTP 402) with no alarm or retry mechanism | `cdk/stacks/ingestion_stack.py:174-190` | S | 3/3 |
| reliability | daily_insight compute lambda swallows non-fatal exceptions without fallback content | `lambdas/compute/daily_insight_compute_lambda.py:1910-1979` | M | 2/3 |
| reliability | http_retry.py urlopen_with_retry retries 429s but does not emit metrics or track quota exhaustion | `lambdas/http_retry.py:76-84` | M | 3/3 |
| reliability | Apple Health Lambda silently drops individual dates with parse/write errors without tracking missing data | `lambdas/ingestion/apple_health_lambda.py:454-462` | M | 3/3 |
| reliability | Freshness checker suppresses alerts for food_delivery source with 14-day threshold — but no alert if data is consistently 10 days old (at-risk behavioral signal) | `lambdas/emails/freshness_checker_lambda.py:64-74` | M | 2/3 |
| security | QA smoke test has unrestricted secretsmanager:ListSecrets and lambda:ListFunctions | `cdk/stacks/role_policies.py:1382-1393` | M | 3/3 |
| security | Site API AI endpoint rate limiting via DynamoDB LeadingKeys is insufficient | `cdk/stacks/role_policies.py:1658-1667` | M | 2/3 |
| security | Weak Email Validation Allows Disposable Domain Bypasses in /api/experiment_follow and /api/challenge_follow | `lambdas/web/site_api_social.py:666-745 and 932-1009` | S | 3/3 |
| security | /api/board_ask personas not schema-enforced — open-ended persona list | `lambdas/web/site_api_ai_lambda.py:714-717` | S | 3/3 |
| security | Content filter bypass via whitespace reordering in _scrub_blocked_terms | `lambdas/web/site_api_ai_lambda.py:267-277` | S | 3/3 |
| security | Insufficient rate-limit enforcement for /api/ask via distributed attacks across multiple IPs | `lambdas/web/site_api_ai_lambda.py:302-327, 607-612` | M | 2/3 |
| security | PII denylist is gitignored and may be incomplete during public surface scans in CI | `deploy/pii_surface_guard.py:75-92` | S | 2/3 |
| security | Content filter bypass via whitespace padding and reordering in _scrub_blocked_terms | `lambdas/web/site_api_ai_lambda.py:267-277` | M | 3/3 |
| security | Rate limit bypass via distributed attack across multiple IP addresses hampered by DDB atomicity but not impossible | `lambdas/rate_limiter.py:74-94` | M | 2/3 |
| security | Hardcoded USER_ID in profile fetch bypasses environment configuration intent | `lambdas/web/site_api_ai_lambda.py:378` | S | 2/3 |
| security | No anti-CSRF token on /api/ask and /api/board_ask — state-changing rate limit updates vulnerable to cross-site attacks | `lambdas/web/site_api_ai_lambda.py:302-327, 675-683` | M | 3/3 |

## quickwin (1)

| Dim | Finding | File | Effort | Votes |
|---|---|---|---|---|
| architecture | Daily ingestion count queries miss phase_filter, risking double-counts in measurements Lambda (quickwin) | `lambdas/ingestion/measurements_ingestion_lambda.py:197-205` | S | 2/3 |

## Appendix — unverified / refuted-or-uncertain
83 candidate findings did NOT reach a majority-real verdict (refuted, uncertain, or verifier cut off by the session limit). Not included above; available in `/tmp/review_salvage.json` if worth a second look.

**Gap-fill round (6 findings, verification was cut off):**
- [P1] Cross-cycle S3 episode collision: week keys not namespaced by cycle (`lambdas/emails/coach_panel_podcast_lambda.py:876-883`)
- [P1] Race condition in bet_ledger state write: last-writer-wins, no CAS (`lambdas/emails/coach_panel_podcast_lambda.py:588-991`)
- [P1] No pre-synthesis cost meter: force=true re-renders entire back-catalogue via Gemini without char accounting (`lambdas/emails/coach_panel_podcast_lambda.py:862-945`)
- [P1] ER-03 numbers_in gate uses basic regex, vulnerable to unicode-digit and whitespace-padding bypasses (`lambdas/er03_gate.py:58-74`)
- [P1] GDPR deletion incomplete: podcast audio, holds, journal, findings left behind in non-namespaced prefixes (`lambdas/operational/delete_user_data_lambda.py:80-89`)
- [P1] Gemini personal API key is a single point of failure with slow detection (8+ days) and no fallback (`lambdas/gemini_tts.py:1-48`)
