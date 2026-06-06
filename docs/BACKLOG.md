# Life Platform — Open Backlog

**Last updated:** 2026-06-05 (v8.3.0)
**Source:** Synthesis of V1 audit (2026-05-17, ADR-057), V2 audit (2026-05-17, `docs/V2_AUDIT_PLAN.md`), V2 follow-up sessions (2026-05-18/19), the 2026-05-29 marathon (Bedrock cutover, budget guard, remediation agent, May-30 restart), the 2026-06-01/02 v4 website launch + QA sweep, and the 2026-06-03 operations/cost session (ADR-074/075). Data-blocked items D-01/D-03/D-04 + N-01/L-11 re-checked against live AWS on 2026-06-03.

> Single source of truth for everything **not done**. Items closed-with-rationale (ADR-057) and items shipped are not listed — see `docs/CHANGELOG.md` for what landed and `docs/DECISIONS.md` for what was formally closed.

### Recently shipped (2026-05-29 marathon — moved out of backlog)

- ✅ **Bedrock cutover** (ADR-062) — all Claude inference on AWS Bedrock + IAM auth.
- ✅ **$75 budget guardrails** (ADR-063) — `cost_governor_lambda` + `budget_guard.py` + tiered AI degradation (1=coaches, 2=website AI, 3=hard cutoff). Enforcement ENABLED.
- ✅ **Self-healing remediation agent** (ADR-064) — daily GitHub Actions workflow, Sonnet 4.6 via OIDC. Phase 1 shadow validated.
- ✅ **Auto-merge gate** (ADR-065) — `remediation/automerge.py` deterministic gate. Phase 2 ENABLED (mode=auto).
- ✅ **May-30 restart** — genesis re-anchored to 2026-05-30 via `restart_pipeline.py` (provisional baseline 304.62 lbs; re-run Saturday post-weigh-in to lock).
- ✅ **Ingestion alarm consolidation** — 12 redundant per-Lambda error alarms removed (~$1.20/mo saved).
- ✅ **Strava paused, freshness IAM fixed, coach seasonality crash fixed, CI verification holes closed, coach truncation fixed across siblings, secret pruning audit (none safely removable).**
- ✅ **PAT rotation** — `gho_` refreshed; classic `life-platform-development` PAT (god-mode, never-used) deleted.

### Recently shipped (2026-06-05 session — moved out of backlog)

- ✅ **L-01/L-02/L-05/L-06/L-10/L-11, D-03, B-03** closed (a few long-tail remain — see below).
- ✅ **S-01** Tier-3 graceful-empty site-api — deployed. **S-06** freshness infra-vs-behavioral split (zero new metrics/alarms) — deployed.
- ✅ **Pipeline status** Evidence dashboard — `GET /api/source_freshness` + `/evidence/pipeline/`.
- ✅ **Cockpit `/api/character` 503 fix** (it 503'd ~16h/day — now reads the latest available record) + **Day-Grade Replay** (per-pillar `score_delta` chip).
- ✅ **a11y:** `--ink-faint` contrast fixed in both themes; constellation `<svg>` `role="img"`→`role="group"`.
- ✅ **`deploy/smoke_test_site.sh` rewritten for v4** (was 58 false failures → 65/0).
- ✅ **Visual + AI-vision UI test harness** (`tests/visual_qa.py` + `tests/visual_ai_qa.py` + CI `visual-qa` job, **ADR-076**) — Playwright deterministic + Claude/Bedrock semantic. Found & fixed the **`/api/coach_analysis` 400** for 4 of 7 cockpit pillars.
- ⚠️ **KMS "cleanup" was a false premise** — the remaining `KMS_KEY_ARN` grants are the LIVE DynamoDB key; do NOT remove (see the restart-followups note further down).

**Operator follow-ups from this session (not auto-done):** `git push` the 17 commits; apply the staged `bedrock:InvokeModel` grant in `deploy/setup_github_oidc.sh` to enable AI-QA in CI; flip the `visual-qa` job advisory→gate after a tuning week. See `handovers/HANDOVER_LATEST.md`.

### Recently shipped (2026-06-05 continued session — moved out of backlog)

- ✅ **D-01** daily-brief prompt-cache waste fixed — `cache_system=False` on the 4 daily-brief calls (root cause: Bedrock cross-region inference defeats region-local cache at once/day volume). Needs layer rebuild + daily-brief deploy.
- ✅ **N-01** `slo-source-freshness` structural false-positive **resolved/closed** — verified live: paused sources already excluded, S-06 deployed; alarm now tracks real infra freshness (flagging a genuine eightsleep/todoist ~2-day gap).
- ✅ **S-02** Evidence depth **done** (premise was stale — no /legacy links remain): bespoke renderers added for intelligence/predictions/benchmarks. Needs site deploy.
- ✅ **visual-qa CI job flipped advisory→gate** (deterministic layer verified green on live prod, 17 pages/0 fails). AI-vision layer self-skips under tier-3 budget so it can't false-block; tune after a budget reset.
- 🔴 **Surfaced N-08** — June budget at **tier 3** (all AI paused) on a projection overshoot ($15 MTD actual). Needs a decision (see N-08).

### Recently shipped (2026-06-06 session — moved out of backlog)

- ✅ **N-08 RESOLVED** — root cause was deeper than "early-month overshoot": after a pause the projection structurally can't decay (`ai_daily = ai/active_days` freezes), so tier 3 would have held until ~Jun 22. Fix (PR #12, deployed): `_decide_tier()` caps projection-driven escalation at **actual-MTD tier + 1**. Tier went 3→**1** (brief + website AI back; orchestrator stays paused — correct, its ~$2.4/day run-rate is real per D-03). 15 unit tests. **Follow-up lever (open):** reduce coach-narrative-orchestrator tokens (D-03) — at current run-rate June will duty-cycle tier 0/1.
- ✅ **D-01 deployed** — layer **v72** published (`SHARED_LAYER_VERSION=72`, PR #13), daily-brief repointed; brief code shipped via PR #11 CI. Other Lambdas catch up on next cdk deploy. Verify next 11 AM brief: CacheWrite=0.
- ✅ **S-02 deployed** — Evidence bespoke renderers + `/feed.xml` alias (L-06) live, verified 200.
- ✅ **Bedrock OIDC grant** — verified ALREADY applied on `github-actions-deploy-role` (matches staged scope); AI-vision QA active in CI now that tier <3. First gated `visual-qa` run green (PR #11).
- ✅ **DLQ 16→2** — all `[AI_UNAVAILABLE]` coach outputs from the tier-3 outage; cause fixed, remainder ages out. (CI `test_i9_dlq_empty` red until then.)
- ℹ️ **Remediation branch open:** `remediation/freshness-date-sk-filter` (no PR) — legit `begins_with(sk, "DATE#")` fix for sentinel-record false-stales in `freshness_checker_lambda.py`. Review + merge.

---

## 📋 By status

| Bucket | Count | Action mode |
|---|---|---|
| **🔴 User-action blocked** | 3 | Waiting on you / AWS Support |
| **⏰ Data-blocked / time-windowed** | 5 | D-03 ✅ closed, D-01/D-04 findings open, D-02/D-05 still windowed (checked 2026-06-03) |
| **🟡 Long-tail low-value** | 5 | L-01/L-02/L-05/L-06/L-10/L-11 ✅ closed 2026-06-03; remaining: L-03/L-04/L-07/L-08/L-09 |
| **🛑 Defer-with-rationale (won't do)** | 9 | Documented `won't-do` unless trigger fires |
| **📦 New work surfaced (post-V2)** | 7 | N-01 ✅ closed · N-08 ✅ resolved 2026-06-06 (tier 3→1) |
| **🌐 v4 website + ops follow-ups** | 5 | S-01 ✅ + S-02 ✅ + S-06 ✅ deployed · B-03 ✅ · S-03/S-04/S-05 open · S-07 deferred |
| **TOTAL OPEN** | **~25** | 2026-06-06 shipped: N-08 fix, D-01 deploy (layer v72), S-02 deploy, OIDC grant verified, DLQ drained |

---

## 🔴 User-action blocked

### B-01 — AWS Lambda concurrency quota raise
- **Filed:** AWS Support case 177921309700709 on 2026-05-19
- **Ask:** Account concurrent-execution limit 10 → 100
- **Cost:** Free
- **Unblocks:** Reserved concurrency rollout (pre-staged in CDK, commented out)
- **Action when approved:** Uncomment `reserved_concurrent_executions=` in `cdk/stacks/operational_stack.py` for 5 Lambdas (mcp, site-api, site-api-ai, daily-brief, hae-webhook); deploy via `cdk deploy LifePlatformOperational`.
- **ETA:** ~24h from filing

### B-02 — MCP tool bulk-delete decision window
- **V2 plan:** Recommended 60-day grace before bulk-pruning 124 unused MCP tools
- **Re-evaluate:** 2026-07-17 (60 days from V2 audit)
- **Data:** Per `LifePlatform/MCP ToolInvocations` metric, only 11 of 135 tools called in last 30d
- **First-pass candidates (already removable):** `tools_calendar.py` ✅ done, ~70 orphan `tool_*` functions in `mcp/tools_lifestyle.py` (3,400 LOC), `mcp/tools_correlation.py` (1,553 LOC), various `compare_*_periods` variants
- **Action:** When ready, run orphan-tool ratchet down from `AUDITED_AT=64` toward 0 in batches of 10-20

### B-03 — show_and_tell/screenshots/ local cleanup — ✅ DONE 2026-06-03
- The 169MB had already been cleared in a prior pass; only an empty `screenshots/` dir remained (0B, untracked). Removed it. Closed.

---

## ⏰ Data-blocked / time-windowed

### D-01 — Cache hit-rate quantification (V2 P1.5) — ✅ DONE 2026-06-05
- **daily-brief (14d):** CacheRead **0** vs CacheWrite 10K → cache delivered no savings and the writes were pure 25%-premium cost.
- **Deeper root cause (2026-06-05):** all 4 daily-brief Claude calls use the *same* model (`AI_MODEL`=sonnet-4-6) and the *same* `shared_system` preamble, so intra-invocation reuse *should* have hit — yet 0 reads. The cause is **Bedrock cross-region inference**: `us.anthropic.claude-sonnet-4-6` routes each call to whichever region has capacity, and prompt cache is region-local. A once/day, 4-call brief writes a fresh cache each call and never reads one back. Not fixable at the app layer for low-volume callers.
- **Fix shipped:** `cache_system=False` on all 4 daily-brief call sites in `lambdas/ai_calls.py` (`call_training_nutrition_coach`/`call_journal_coach`/`call_board_of_directors`/`call_tldr_and_guidance`) + corrected the stale "Phase 3.8" comment in `daily_brief_lambda.py`. `coach-narrative-orchestrator` caching left untouched — it's high-frequency, keeps a region warm, and hits (382K reads/14d).
- **Deploy + verify:** ✅ deployed 2026-06-06 — layer v72 published, daily-brief repointed. After the next 11 AM brief, `daily-brief` CacheWrite should drop to 0 with unchanged output.

### D-02 — Coach hit_rate threshold tuning (V2 P3.6)
- **Wait until:** ~2026-07-17 (60 days for confirmed/refuted verdicts to accumulate)
- **What changed:** V2 P1.1 (already-shipped) enforces `_normalize_metric_hint` whitelist; predictions with invalid hints become qualitative-only (correctly skipped by evaluator). New predictions from 2026-05-17+ should have measurable verdicts.
- **Action when data exists:** Read `coach_quality_gate.PASS_SCORE_THRESHOLD = 60`; tune based on actual hit_rate_pct distribution; promote advisory → blocking on score < 40

### D-03 — Per-Lambda AI spend ranking (V2 P1.4 followup) — ✅ checked 2026-06-03
- **Data now exists.** 7 Lambdas emit input/output tokens via `LifePlatform/AI` (`LambdaFunction` dim): coach-narrative-orchestrator, daily-brief, coach-history-summarizer, coach-ensemble-digest, coach-state-updater, coach-quality-gate, api_ask. (Fewer than the "9 of 22" BACKLOG estimated — site_api/site_api_ai/brittany dimensions not observed in the 14d window.)
- **Ranking (input tokens, 14d ending 2026-06-03):**
  1. **coach-narrative-orchestrator — 8.03M in / 539K out** ← dominant spender, ~8× the next. Sonnet narrative path. Caching already engaged (D-01).
  2. daily-brief — 1.02M in / 163K out (cache wasted — see D-01)
  3. coach-history-summarizer — 557K in / 27K out
  4. coach-ensemble-digest — 434K in / 83K out
  5. coach-state-updater — 416K in / 257K out
  6. coach-quality-gate — 275K in / 74K out
  7. api_ask — 0 in window (website AI quiet or budget-gated)
- **Reduction levers:** coach-narrative-orchestrator is the only real target — everything else is rounding error. Levers: tighten its system prompt / context window, confirm Haiku isn't viable for sub-sections, verify cache hit-rate stays high. Re-run this query monthly.

### D-04 — SES open-rate baseline (V2 P1.6 followup) — ⚠️ root cause found 2026-06-03
- **Checked:** Send=175, Delivery=110 over 14d, but **no `Open`/`Click` metric is published at all** (not zero — absent).
- **Root cause (not Apple-Mail masking):** `aws sesv2 get-configuration-set --configuration-set-name life-platform-emails` returns `TrackingOptions: null` and `VdmOptions: null`. Open-tracking is **not enabled**, so SES never injects the tracking pixel and never emits the Open metric. The V2 assumption that the config set auto-tracks opens was wrong.
- **Decision needed (not just "wait for data"):** To get open-rate you must `aws sesv2 put-configuration-set-tracking-options` with a CNAME-validated `CustomRedirectDomain` (open pixel + click redirect rewrite). That's a privacy tradeoff for a personal/low-volume list — may be a deliberate "won't do." Until configured, open-rate is permanently unobservable.

### D-05 — Coach prediction loop validation (V2 ADR-055)
- **Wait until:** ~2026-06-17 (30 days post-loop closure)
- **What it tests:** Daily coach predictions get auto-evaluated against measured outcomes. Pre-V2 = 100% inconclusive (theatrical). Post-V2 should produce real confirmed/refuted verdicts.
- **Action when data exists:** Run `aws dynamodb query --table-name life-platform --key-condition-expression "begins_with(sk, 'PREDICTION#')" ...` and count by `verdict` field. Expect mix of confirmed/refuted (not 100% inconclusive).

---

## 🟡 Long-tail low-value (chip away when bored)

### L-01 — multi-line prints in `anomaly_detector_lambda.py` — ✅ DONE 2026-06-03 (`0e41f11`)
- 5 `print()` → `logger.info()` (file at `lambdas/emails/anomaly_detector_lambda.py`; logger already present). Needs anomaly-detector deploy to take effect in logs.

### L-02 — redundant explicit imports in `mcp/registry.py` — ✅ DONE 2026-06-03 (`0e41f11`)
- Dropped 5 redundant single-name re-imports (`tool_get_autonomic_balance`, `tool_get_sleep_environment_analysis`, `tool_get_deficit_sustainability`, `tool_get_metabolic_adaptation`, `tool_get_journal_sentiment_trajectory`) — all already in the bulk imports above them. Registry flake8 violations 131→126; wiring-coverage test green. Needs MCP deploy to take effect.

### L-03 — Site_api partial extraction of `board_ask` + `/api/ask` handlers
- Source: V2 P6.6 — full router split deferred (too risky); partial extraction worth doing
- Move 2 large handlers (lines 2810-3000 + 7820-7870 of site_api_lambda.py) to new `lambdas/site_api_ai_handlers.py`
- Effort: 1-2h with regression test
- Value: smaller site_api_lambda.py file; easier follow-on AI work

### L-04 — Shared module adoption in exempt ingestion Lambdas (V2 P2.7)
- Notion/dropbox got `auth_breaker` ✅
- Still missing: `numeric` in dropbox_poll + food_delivery + hae; `http_retry` where applicable in macrofactor + food_delivery
- Effort: ~30 min per file
- Value: cleanup consistency

### L-05 — `print()` in `garmin_lambda.py` — ✅ DONE 2026-06-03 (`0e41f11`)
- Last `print()` → `logger.info()` at `lambdas/ingestion/garmin_lambda.py`. Moot in practice (Garmin retired, ADR-074) — done for consistency if ever revived.

### L-06 — RSS feed `/feed.xml` alt-path 404 — ✅ DONE 2026-06-03 (`0e41f11`)
- `scripts/v4_build_rss.py` now writes `site/feed.xml` as a byte-identical alias of `rss.xml` (duplicate-file approach — `redirects.map` is auto-generated by `v4_migration_inventory.py` so a manual 301 there would be overwritten). Live after next `bash deploy/sync_site_to_s3.sh`.

### L-07 — Refresh DEPENDENCY_GRAPH.md "Hottest Partitions" estimates
- Per V2 doc audit: estimates inherited from v4.5.0; need fresh DDB CloudWatch metrics
- Effort: 20 min query + edit

### L-08 — Verify SCHEMA.md per-source field tables exhaustively
- V2 doc audit flagged: per-source tables not line-by-line verified against current Lambda source
- Effort: 1h cross-reference

### L-09 — MCP_TOOL_CATALOG.md per-section tool tables
- V2 doc audit flagged: total count correct (127 cataloged vs 135 in registry), but per-section tables not line-by-line verified
- Effort: 1h

### L-10 — `webhook-key` reference in `cdk/stacks/role_policies.py` — ✅ NOT AN ISSUE (verified 2026-06-03)
- The only `webhook-key` mention (lines 405-406) is a deliberate *historical note* explaining the secret was deleted 2026-03-14 and `ingestion-keys` replaced it. There is **no stale IAM grant** — no resource ARN references a dead secret. The comment is useful context; leaving it. Closed, no change needed.

### L-11 — DLQ depth — ✅ DONE (verified 2026-06-03)
- `life-platform-ingestion-dlq` now holds **0 messages** (ApproximateNumberOfMessages=0, NotVisible=0). The 66 stuck pre-Garmin messages aged out at 14d retention. No action needed; ingestion gaps self-heal via gap-detection backfill regardless.

---

## 🛑 Defer-with-rationale (won't do unless trigger fires)

These items are documented in ADR-057 or surfaced in V2 plan as won't-do. Do not re-open without new evidence.

### W-01 — Split `intelligence_common.py` (1,556 LOC)
- **Why won't-do:** Only 1 importer (`ai_expert_analyzer`); splitting multiplies imports without benefit
- **Reopen if:** A second major importer emerges

### W-02 — Multi-user / Cognito (V1 Phase 6, ~4 FTE-weeks)
- **Why won't-do:** No second user on horizon
- **Reopen if:** Real subscriber begins onboarding to their own dashboard

### W-03 — Cross-region DR (V1 P8.13)
- **Why won't-do:** Overkill for personal platform
- **Reopen if:** SLA pressure or regulatory requirement

### W-04 — Site_api full router split (V2 P6.6, 7,879 LOC monolith)
- **Why won't-do:** Touches public surface, risk > benefit
- **Reopen if:** A new endpoint requires touching the file substantially

### W-05 — HAE handler registry refactor (V1 P4.6)
- **Why won't-do:** Cleanup-only; current per-data-type code works
- **Reopen if:** 6th+ data type added

### W-06 — Lambda Power Tuning campaign (V1 P8.6)
- **Why won't-do:** Most Lambdas already at 256MB minimum; daily-brief unsafe to tune (sends real emails per invoke); realistic savings $1-3/mo
- **Reopen if:** Memory-related throttling becomes an issue

### W-07 — Batch API (V1 P5.9)
- **Why deferred:** Original plan said reconsider July 2026
- **Reopen on:** 2026-07-15 with 3 months of post-caching AI cost data

### W-08 — Inline JS extraction from `site/index.html` (V2 P6.2)
- **Why won't-do:** 22 KB across 15 inline scripts; touches many DOM IDs; risk of breaking dashboard hydration; cosmetic benefit
- **Reopen if:** CSP hardening (drop `'unsafe-inline'`) becomes priority

### W-09 — DLQ on 16 "async" Lambdas (V2 P6.5)
- **Why won't-do:** Operations stack explicitly sets `dlq=None` for scheduled health-check Lambdas; self-healing on next cron tick
- **Reopen if:** A specific Lambda's failure mode would benefit from manual replay

---

## 📦 New work surfaced (post-V2)

Items that came up during V2 follow-up sessions and aren't yet scheduled.

### N-01 — long-standing alarms — ✅ 4 of 5 cleared (checked 2026-06-03), 1 structural remains
- **Cleared:** `life-platform-dlq-depth-warning` (OK since 2026-05-28), `life-platform-garmin-data-ingestion-errors` (OK since 2026-05-29), `life-platform-ingestion-dlq-messages` (OK since 2026-05-28). `ingestion-error-whoop` no longer exists (the `ingestion-error-*` alarm family is now per-compute/email-Lambda and all 34 are OK).
- **`slo-source-freshness` structural false-positive — ✅ RESOLVED (verified live 2026-06-05).** The "count=3 forever from paused sources" premise was already false: paused sources (Garmin/Strava/MacroFactor) are **commented out of `SOURCES` entirely** in `freshness_checker_lambda.py`, so they're never counted, and S-06 (`3bde46d`, deployed 2026-06-03 21:27 UTC) excludes behavioral sources (measurements/food_delivery) from `StaleSourceCount`. Live count has dropped from a permanent 3 to a fluctuating 1–2.
- **The alarm now behaves as designed** — it fires only when a genuine infra source exceeds its per-source threshold. At verification time it flagged `eightsleep` (51h) and `todoist` (51h), i.e. a real ~2-day gap — exactly the signal it's meant to surface (digest-routed, non-paging). No code change: lowering those thresholds would blunt a working signal.
- **Operational note (not a code item):** eightsleep + todoist showed a live ~2-day data gap on 2026-06-05/06 — worth a glance to confirm it's behavioral (didn't use device / no tasks closed) vs an ingestion issue.

### N-02 — Subscriber `confirm-token` lookup uses DDB scan
- Per V2 audit web/DX agent
- Currently fine (subscriber volume low)
- Re-evaluate when >2000 subscribers; switch to GSI-less pattern (item-per-token)
- Effort: 1h refactor + test
- Trigger: subscriber count

### N-03 — Email dark-mode CSS
- V2 plan: 30% of recipients use dark mode; emails currently assume light
- Add `@media (prefers-color-scheme: dark)` block in `html_builder.py`
- Effort: 3h design + test in real clients

### N-04 — Site `h1` semantic vs visual review
- V2 closed: hidden h1 is valid SEO pattern; left alone
- Possible follow-up: convert `.h-hero__title` from `div` to `h1` and remove the hidden one
- Skipped because of CSS cascade risk
- Effort: 2h careful refactor

### N-05 — V2 audit drift checks: re-verify all v1-shipped items are still working in 90 days
- Schedule a 2026-08-17 audit (per V2_AUDIT_PROMPT.md cadence)
- Use `docs/V2_AUDIT_PROMPT.md` for the v3 round
- Cost: ~1 session of focused agent work

### N-06 — Coach `quality_gate` threshold promotion
- Currently advisory (logs score, doesn't block); V2 wired it but kept it observational
- After 30 days of scores accumulating, decide: promote to retry-with-stricter-prompt on score <60? block on score <40?
- Re-evaluate: 2026-06-19

### N-07 — `compute_metadata` adoption gap-filling
- V2 P2.6 expanded to 5 more compute Lambdas; `acwr_compute` skipped (uses update_item)
- Future: if `acwr_compute` ever switches to put_item, add tag_record there
- No ETA — only if pattern changes

### N-08 — June budget tier 3 — ✅ RESOLVED 2026-06-06 (PR #12, deployed; tier now 1)

- **Resolution:** `_decide_tier()` in `cost_governor_lambda.py` caps projection-driven escalation at actual-MTD tier +1 (and ignores the projection entirely inside the early-month window). Found a second, worse failure mode while fixing: post-pause the projection structurally can't decay (`ai_daily = ai/active_days` freezes), so the old code would have held tier 3 until ~Jun 22 with AI off the whole time.
- **Decisions (a)/(b)/(c) answered:** (a) the ~$2.4/day AI run-rate is REAL (orchestrator-dominated, matches D-03) — not transient; (b) yes, projection was too trigger-happy — fixed via the actual-spend cap rather than a one-off floor; (c) no manual reset needed — redeployed governor re-computed tier 1 on invoke.
- **Open follow-up:** the real spend lever remains coach-narrative-orchestrator token reduction (see D-03). At current run-rate June will duty-cycle between tiers 0/1 — acceptable, but trimming the orchestrator unlocks full tier-0 months.
- Original report follows for context:
- **Observed:** SSM `/life-platform/budget-tier` = **3** (set 2026-06-05 17:00 PT). At tier 3 the budget guard hard-cuts ALL AI: daily brief skips AI, website `/api/ask`+`/api/board_ask` return "paused", and `bedrock_client.invoke()` raises `BudgetExceeded` (confirmed live — the AI-vision QA layer self-skipped with "monthly $75 ceiling reached").
- **But actual MTD spend is only $15.38** (Cost Explorer, Jun 1–5). The tier is **projection-driven**: ~$3/day run-rate × 30 ≈ ~$90/mo projected → ≥95% of $75 → tier 3. So it's an early-month linear-extrapolation overshoot, not a real $75 breach — yet it's currently degrading the product (no AI brief, no website AI).
- **Decisions needed:** (a) is the ~$3/day June run-rate real and worth reducing (prime suspect: `coach-narrative-orchestrator`, the dominant AI spender per D-03 — 8M in-tokens/14d), or a transient (restart aftermath)? (b) Is the cost_governor's linear projection too trigger-happy this early in the month — should it weight actual-vs-projected or add an absolute-spend floor before tiering to 3? (c) Short-term: manually reset to tier 0 for testing (`aws ssm put-parameter --name /life-platform/budget-tier --value 0 --type String --overwrite`) if the projection is judged a false alarm.
- **Relation to D-01:** the daily-brief cache fix trims waste but is rounding error vs this; the real lever is the projection logic + coach-narrative-orchestrator token budget.

---

## 🌐 v4 website + ops follow-ups (2026-06-01/02/03 sessions)

Surfaced during the v4 "The Measured Life" launch, QA sweep, and operations/cost session. Documented in `handovers/HANDOVER_LATEST.md`; folded here for single-source-of-truth.

### S-01 — Tier 3 graceful-empty site-api deploy (committed, NOT deployed)
- **Status:** Code committed (`ee88b6b`); awaiting CI/CD production approval or manual `/deploy site-api`.
- **What it does:** Converts 503s on `/api/nutrition_overview` + `/api/correlations` to shaped-empty 200s (restart-safe); 4 more endpoints audited to match. Files: `lambdas/web/site_api_observatory.py` (+ siblings).
- **Action:** Deploy full `web/` package (never single-file — ADR-046/deploy.md), then verify the two endpoints return shaped-empty 200 not 503.

### S-02 — Evidence depth — ✅ DONE 2026-06-05 (premise was stale)
- The "14 archive topics link to /legacy" framing was **obsolete**: v4 `site/assets/js/evidence.js:153` already zeroes all `/legacy` link-outs ("everything lives inline in v4 now"), and the registry has no `archive`-mode topics. The real remaining gap was *depth*: 3 data-mode topics still rendered via the generic auto-table fallback (`renderGeneric`).
- **Fixed:** added bespoke renderers `renderCorrelations` (intelligence), `renderPredictions` (predictions), `renderBenchmarks` (benchmarks) in `evidence.js` + registered them in `RENDERERS`; rebuilt via `scripts/v4_build_evidence.py`. All 3 endpoints are empty this genesis week (restart wiped intelligence) so they show honest bespoke empty-states now and rich readouts as data accrues.
- **Deploy:** ✅ synced 2026-06-06 — all 3 topics + `/feed.xml` verified 200 live.

### S-03 — Cockpit week/month/journey deeper time-series
- Scope buttons show basic metrics; add deeper time-series per scope. Time-permitting enhancement.

### S-04 — RSS real-time refresh (optional)
- Today `rss.xml` regenerates on site deploy (`scripts/v4_build_rss.py`). Optional: also write it from `lambdas/emails/chronicle_approve_lambda.py::_publish_to_s3` so the feed refreshes the instant a chronicle issue is approved. Effort: 30 min. Nice-to-have.

### S-05 — visual_qa legacy repointing
- `tests/visual_qa.py` has deep legacy-page entries on old URLs; repoint to `/legacy/<path>` or drop as each is rebuilt bespoke. Low-priority test maintenance.
- **Note (2026-06-05):** no Evidence topic links to `/legacy` anymore (S-02), so legacy repointing is now purely test-harness hygiene. Separately, the `visual_qa.py` page list does **not** include the 3 newly-bespoke pages (`/evidence/intelligence|predictions|benchmarks/`) — adding them would extend gate coverage. Both are optional follow-ups.

### S-06 — slo-source-freshness alarm still firing — ⚠️ needs a decision (re-diagnosed 2026-06-03)
- **Correction:** paused sources are ALREADY excluded — Garmin/Strava/MacroFactor are commented out of `SOURCES` in `freshness_checker_lambda.py`. So the alarm (StaleSourceCount=2-3) is firing on **genuinely stale ACTIVE behavioral sources** (e.g. `measurements` now >60d, others lapsing), not paused ones. The alarm is arguably working as designed.
- **The real question (your call):** the SLO alarm trips at `StaleSourceCount ≥ 1`, so ANY behavioral source lapsing pages it — structurally noisy for a personal platform where infrequent logging is normal. Options: (a) accept it (routed to digest, not paging) and just keep behavioral `SOURCE_STALE_HOURS` overrides current; (b) split the metric into infra-stale (OAuth broken — alarm) vs behavioral-stale (you haven't logged — informational, no alarm); (c) raise the threshold. Not a mechanical fix — needs a product decision before coding.

### S-07 — daily-brief cache-write waste — 🔬 DIAGNOSED 2026-06-03, deferred (not worth changing)
- **What was investigated:** daily-brief builds one `shared_system` preamble (`ai_calls.daily_brief_shared_system`) and passes it to 4 calls (`call_board_of_directors`, `call_training_nutrition_coach`, `call_journal_coach`, `call_tldr_and_guidance`) — all same model (Sonnet, no `model=` override), identical system block, `cache_system=True`, seconds apart. By design (Phase 3.8) calls 2-4 should hit the cache. They don't: CacheRead=0, CacheWrite≈740/day over 14d.
- **Why it's NOT a global Bedrock/cross-region issue:** `coach-narrative-orchestrator` caches fine (382K reads / 67K writes, same Bedrock path + cross-region profiles). So the 0-reads is **daily-brief-specific**.
- **Ruled out (from CloudWatch logs, 2026-06-02/03 runs):** TTL expiry (BoD→Training/Nutrition are ~12s apart, far inside the 5-min TTL), model mismatch (all 4 default to Sonnet), and the `shared_system=None` fallback (no "shared_system build failed" warning logged). The block is built once and shared — yet calls 2-4 still don't read it.
- **Root cause still unconfirmed:** needs per-call `cache_read_input_tokens`/`cache_creation_input_tokens` logging (only the aggregate metric exists today; the text logs don't break it down). Leading suspect: `shared_system` sits near/under the ~1024-token Sonnet cache-engagement floor, so Bedrock silently skips the read. Confirming requires instrumenting daily-brief — itself a deploy not worth 2¢.
- **Why deferred:** the *waste* is the 25% write premium on ~740 tokens/day = **~$0.02/month** (negligible). The 4 functions live in `ai_calls.py` (a SHARED LAYER module) and are daily-brief-only, but changing them still needs a layer rebuild + redeploy. Speculatively disabling caching (might be the wrong fix — the orchestrator proves it *can* work) on a shared module, via a ~20-Lambda layer deploy, to save 2¢/mo is upside-down. **Do NOT disable blindly.**
- **If ever picked up:** first pull daily-brief's per-call Bedrock cache token logs to confirm root cause; if the 4 calls genuinely share a cacheable ≥1024-token prefix, make caching *work* (recover the intended $1.50-2/mo); only if it's structurally impossible, set `cache_system=False` and bundle into the next layer rebuild. Not a standalone deploy.

---

## How to add to this backlog

When you discover a new tech debt item:

1. Pick a category (User-action, Data-blocked, Long-tail, Won't-do, New-work-surfaced)
2. Assign an ID (next number in sequence within category)
3. Add a section like the ones above with: title, source/why-found, action, trigger/timing, effort estimate
4. Commit with `docs(backlog): add B-NN ...`

If you do an item, move it to `docs/CHANGELOG.md` and remove from here. If you decide an item won't ever be done, move it to `docs/DECISIONS.md` as an ADR with rationale.

---

**Verified:** 2026-05-19 — synthesized from V1 audit + V2 audit + V2 follow-ups


### Restart 2026-05-18 follow-ups

- [x] **2026-05-27: Wrapped 20 of the original 21 clear-cut USER#-data sites** across 3 batches (commits 0bcb771 + 3796a5f + 5f4d969). Covers web (site-api family), MCP tools, ingestion (apple_health), and email Lambdas (chronicle, weekly_digest, monthly_digest, anomaly_detector). Skipped 1 intentionally (subscriber count — SUBSCRIBER records deliberately untagged per ADR-058).
- [ ] **Deferred — remaining ~46 phase-relevant sites + 145 truly-unclear sites.** Per-callsite domain judgment needed. Highest-volume buckets: `site_api_intelligence.py` (18 sites — /api/status path, 5-min cache so leakage half-life is short), `failure_pattern_compute_lambda.py` (4 sites — high blast radius into daily compute). Risk acceptable to defer because pre-genesis records are correctly phase-tagged at write, AND `compute_metadata.tag_record()` now auto-infers phase from sk on every future write (commit 462de75).
- [ ] Re-evaluate phase filter at 30/60/90 days post-restart (ADR-058 §13).
- [x] ~~Remove orphan IAM references to `S3_KMS_KEY_ARN` in `cdk/stacks/role_policies.py`~~ — **DONE 2026-05-24** (grants removed). Only `S3_KMS_KEY_ID` (`5c50ca02…`, PendingDeletion) remains as an unused constant in `constants.py:28` + two explanatory comments; keep until the key fully deletes 2026-06-16, then drop the constant.
  - ⚠️ **2026-06-05 — do NOT remove the remaining `KMS_KEY_ARN` grants.** Verified against live AWS: `KMS_KEY_ARN` references `444438d1…` (alias `life-platform-dynamodb`, **State: Enabled**), which is the **DynamoDB table's SSE-KMS key** (`life-platform` table `SSEType: KMS` → this ARN). The ~32 `kms:Decrypt`/`GenerateDataKey` grants are LOAD-BEARING — every Lambda needs them to read/write DDB. An audit/roadmap pass flagged these as "orphan grants" by conflating them with the deleted S3 CMK (`5c50ca02`); removing them would lock the platform out of all its data. The bucket itself is AES256 (no S3 CMK).
- [x] ~~DLQ has 62 stale messages — drain via `life-platform-dlq-consumer`.~~ — drained 2026-05-24 (down to 0).
- [x] ~~`life-platform/notion` secret is `MARKED FOR DELETION` — confirm intentional or re-create.~~ — verified 2026-05-24: secret is healthy (`DeletedDate: null`, last changed today), actively referenced by `notion_lambda.py`, `freshness_checker_lambda.py`, `pipeline_health_check_lambda.py`. Was likely restored before this BACKLOG note got written. No action needed.
- [ ] Decide whether to resurrect 1-2 specific chronicle entries via `restart_chronicle_handler.py --resurrect-sk`, or leave the chronicle blank until the next Wednesday cycle generates the first fresh entry.

### 2026-05-24 P3.4 site-api work follow-ups

- [x] ~~Site-api Lambda is missing the shared layer attachment.~~ — **Code staged 2026-05-24.** `shared_layer=shared_utils_layer` added to `SiteApiLambda`, `SiteApiAiLambda`, and `SiteStatsRefresh` in `cdk/stacks/operational_stack.py`. Awaits next `cdk deploy --all` (deferred to post-launch to avoid hot-fix-overwrite risk).
- [ ] CloudWatch dashboard for `LifePlatform/SiteAPI` EMF metrics. The Lambda now emits `DurationMs` + `ColdStart` per (Route, Method) but no dashboard renders them yet. Build a Logs Insights board: p50 / p95 latency per route + cold-start rate.
- [x] ~~Subscribe-page CLS 0.151 (over the 0.1 budget).~~ — **Fixed 2026-05-24.** Root cause: empty `#amj-nav` / `#amj-hierarchy-nav` / `#amj-subscribe` mount points shifted content when components.js populated them. Added `min-height` reservations in `site/assets/css/base.css`. CLS now 0.091 (under budget).

### 2026-05-24 post-launch CDK deploy follow-ups

- [ ] **Batched `cdk deploy --all` post-launch.** Pending changes staged in CDK code:
    1. Remove orphan S3 CMK grants from all IAM role policies (`cdk/stacks/role_policies.py` — `S3_KMS_KEY_ARN` deleted from 26 PolicyStatement resources). Bucket is AES256, key in PendingDeletion until 2026-06-16. Code-complete; deploy deferred to avoid the CDK reconcile hot-fix-overwrite risk on launch eve.
    2. Reattach shared layer to `site-api`, `site-api-ai`, `site-stats-refresh` (see above).
    3. Run after Monday's launch settles. Use `cdk deploy --all --hotswap-fallback` and verify against `restart_verify_rendered.py` (27/27) immediately after.

### 2026-05-25 launch-eve bug sweep — fixed + open follow-ups

**Fixed and deployed 2026-05-25 01:30–02:30 UTC:**
- [x] `site_writer.py` — `JOURNEY_START_WEIGHT` referenced at module-load before its import. Caused `(non-fatal)` warning on every daily-brief run. Moved the `from constants import ...` block above the `HERO_WHY_PARAGRAPH` f-string. Deployed via daily-brief bundle.
- [x] `coach-quality-gate` IAM gap — daily-brief role granted `lambda:InvokeFunction` on coach-computation-engine etc. but not coach-quality-gate. Every coach call logged `AccessDeniedException (non-blocking)`. Added the ARN to the `CoachIntelligenceInvoke` policy statement. Deployed via `cdk deploy LifePlatformEmail`.
- [x] Canary subscribe bouncing — `/api/subscribe` synthetic subscriber `canary+<ts>@mattsusername.com` resulted in SES sending a confirmation email that then bounced (MAILER-DAEMON spam). `email_subscriber_lambda.py` now reads `source` from POST body and skips the confirmation send when `source == "canary"`. Deployed to both us-west-2 and us-east-1.
- [x] Canary alert-on-any-failure — every transient blip emailed `🔴 canary: 1 failure(s)`. Added a 2-consecutive-fail buffer using DDB state at `USER#system / CANARY#last_state`. Only alerts when the SAME check has failed in both the previous AND current run. Deployed.
- [x] 43 CloudWatch alarms still publishing to immediate-email SNS topic `life-platform-alerts` — root cause of "AWS Notification Message" + alarm-flap spam. Batch-rerouted to digest topic via `aws cloudwatch put-metric-alarm` script. CDK source updated (mcp_stack + operational_stack `add_alarm_action`/`add_ok_action` lines now point at `local_digest_topic`).
- [x] `pipeline-health-check` Lambda had no `SNS_ARN` env var, falling back to hardcoded `life-platform-alerts` topic. Set env var to digest topic via CLI.

**Open follow-ups:**
- [x] ~~**Garmin OAuth rate-limited (HTTP 429)** — needs manual re-auth.~~ — **Superseded by ADR-074 (2026-06-03): Garmin direct-API ingestion RETIRED/paused.** Garmin's 2026 anti-automation crackdown 429-blocks server-side OAuth2 refresh from datacenter IPs (374 throttles vs 2 successes / 14 days — unwinnable headless). Garmin is commented out of `freshness_checker_lambda.py` SOURCES + OAUTH_SECRETS. **Revive options (open decision):** Terra wearable aggregator (free, official, webhook — 3rd-party privacy tradeoff) · official Garmin Health API (B2B, approval-gated) · residential proxy (paid, fragile). See ADR-074.
- [ ] **The 5 duplicate Morning Brief emails** were caused by `aws lambda invoke daily-brief` during my P3.4 / phase-filter test cycles. Lesson: never invoke an email-shipping Lambda unless explicitly intended. Future-Claude: if testing daily-brief logic, set `DRY_RUN=1` env var (add this gate to the Lambda) or invoke a dedicated test endpoint that returns the HTML without SES'ing.
- [ ] **`compute-pipeline-stale` alarm** will fire tomorrow (genesis = first day) because compute hasn't run yet. Now routes to digest, so it'll batch into one email. Once compute runs at 11 AM PT Monday, alarm self-clears.
- [ ] **JOURNAL_COACH validator BLOCKED empty output** in daily-brief logs (currently every run). Cause: pre-genesis there are no journal entries, so the coach returns empty, the validator blocks it as low-quality. **Expected pre-launch behavior** — once you start journaling (via Notion), the coach will produce output and the validator will accept it. Self-resolves; no code change needed.
- [ ] **Training coach prompt drift** — `[ai_validator] WARNING: Output starts with 'Matthew' — prompt instruction may have been ignored`. Quality issue, not blocking. The Sonnet prompt for the training coach tells the model not to start with "Matthew" — Sonnet is ignoring that instruction. Worth a prompt-engineering pass post-launch.
- [ ] **76 untagged DDB records discovered + retro-tagged** via `restart_phase_tag.py --apply` 2026-05-25 02:24 UTC. Root cause: per-Lambda write paths (`character_engine.store_character_sheet`, daily-brief insight writes, ingestion writes between phase-tag runs) didn't add phase tags. Fixed `store_character_sheet` to tag pre-genesis writes as `pilot`; **other write paths still don't tag**. Acceptable for now (untagged passes the filter as "experiment"), but a future hardening pass should add a `compute_metadata.tag_record(item, phase=...)` helper used by every writer.

**Source freshness inventory captured 2026-05-25 02:25 UTC** — 3 fresh (whoop, apple_health, habitify), 9 stale. Of the 9: only Garmin is a code bug (above). The rest are behavioral (macrofactor=44d, food_delivery=58d, measurements=57d, notion=23d, etc.) and resolve when you log data.

### 2026-05-25 MacroFactor Tier 1 — TORN DOWN (was blocked by Firebase App Check)

- [x] **MF unofficial-API path removed.** Closed same day it was deployed. Firebase App Check blocked the auth endpoint; 5 workarounds all failed. Code, Lambda, IAM role, EventBridge rule, secret, and DDB state record all removed. ADR-061 "Update 2026-05-25 (same day, later)" documents the attempt and tear-down rationale for institutional memory.
- [x] **Tier 2 (manual MacroFactor Dropbox export) is the only food-level + MF-workout path.** Unchanged.
- [x] WS-3 schema migration of historical MF Dropbox workout records — no longer needed since there's no Tier 1 to dedupe against. Existing `_expand_legacy_aggregate` bridge in `mcp/tools_hevy.py` continues to surface them via `source="macrofactor_export"`.

### 2026-05-24 phase-filter sweep — deferred-with-reason

- [ ] **~254 raw `table.query()` callsites still bypass the phase-filter chokepoint.** Audited per-Lambda counts; not the bounded mechanical sweep originally estimated — each callsite needs human judgment (USER#-prefixed user data needs the filter; SUBSCRIBER#/ADMIN#/system tables are exempt). Daily-brief / character-sheet / daily-insight-compute have the highest blast radius. Defer to launch+1 week with daylight to test; pre-genesis data is already correctly phase-tagged at the DDB level, so the practical risk of leakage into post-genesis compute outputs is low.
