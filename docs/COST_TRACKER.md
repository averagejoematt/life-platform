# Life Platform — Cost Tracker

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-08-31

Last updated: 2026-08-31 (v8.6.0)

> The Secrets rate-card row and the `Last updated` line above are **sync-owned literals**
> (`deploy/sync_doc_metadata.py` RULES): a hand-edit must keep the rule's exact phrasing or
> the Wiki-drift gate reds `main` — the pre-commit hook only WARNS, docs-ci FAILS.

> Budget ceiling: **$215/month all-in** base, floating to **$252 in surge mode** on real
> reader traffic (≥900 trailing-7d uniques — ADR-133). **August 2026 ONLY: a dated
> window raised that pair to $200 base / $235 surge** (ADR-133 amendments 2026-08-09 #2381 + 2026-08-16
> #2734, `_TEMP_CEILING_WINDOW`) that auto-reverts 2026-09-01 — note the window is
> now BELOW the base it reverts to, so 09-01 is a raise, not a cut. The AWS Budgets
> backstop moves WITH the permanent base (#2801, `core_stack.py` — the amount is
> resolved at CDK **synth** time by parsing `cost_governor_lambda.py`, so there is no
> `budget_limit=` literal to read; an earlier version of this line pointed at one that
> no longer exists): it was pinned low only while the raises were temporary, and a
> permanent base above the backstop would page every month by construction.
> The September base decision is **settled** — $215 base / $252 surge, permanent
> (#2801), derived from measured steady state (Cost Explorer unblended $5.74/day,
> sd $4.32, n=25 over 2026-08-01..08-25 → ~$172/mo, 95% CI $121–223) rather than a
> projection. $215 is the lowest base that never reaches tier 2 in any of three
> modelled September burn rates — see ADR-133's 2026-08-28 amendment for the table.
> History: $25 → $75 with the Bedrock migration + automated guardrails
> (2026-05-29), $75 → $85 on 2026-07-08 (ADR-133 amendment). Design constraint: every
> feature must justify its cost.
>
> **Freshness contract (#1354):** every number below was read from live Cost Explorer /
> SSM / CloudWatch on the Verified: date. `scripts/check_doc_facts.py` fails CI when the
> newest Verified: stamp in this doc is older than **45 days** — re-run the close ritual
> below and re-stamp.

---

## Live posture snapshot — 2026-08-18

From SSM `/life-platform/budget-tier` + `/life-platform/budget-breakdown` (the governor's
own output, computed 2026-08-19T00:00Z):

| Fact | Value |
|------|-------|
| Tier | **1** (Caution — internal/dev AI paused) |
| MTD estimated total | $110.81 (governor; carries the deliberate 1.15x AI buffer — CE actual MTD-18d is $100.98) |
| Projected month-end | $171.72 (governor, spike-contaminated) vs **measured spike-free run-rate $4.12/day (sd 0.66, n=6) ≈ $124/mo, 95% CI $108–139** |
| Effective ceiling | **raised to $200 — August window, reverts 2026-09-01** (surge inactive: 773 trailing-7d uniques < 900) |
| Burn (trailing 7d) | AI ~$2.97/day + non-AI ~$1.71/day |

## The real monthly bill (Cost Explorer, unblended)

Mar **$20.04** → Apr **$35.01** → May **$48.19** → Jun **$79.80** (94% of the $85 base)
→ Jul **$98.35 closed** (first month over the $85 base — the fact forcing the #2836
September decision) → Aug MTD-18d **$100.98** inside the $200 window.

**The bill is two things:**

- **A measured non-AI floor of ~$36–43/mo** (post-WAF). Jun actual non-AI: **$35.8**.
  Jul MTD non-AI: **$25.16 over 18 billed days** ≈ $42–43/mo pace (the governor's
  trailing-7d rate of $1.21/day reads a touch lower, ~$37/mo). Composition (Jul MTD, CE
  per-service): CloudWatch $11.53, Secrets Manager $5.48, Tax $4.63, Cost-Explorer API
  $1.32, S3 $0.79, KMS $0.63, Route 53 $0.50, DynamoDB $0.28.
  *The long-documented "fixed floor ~$15–17/mo all-in" was ~2.5x too low — it predated
  the alarm-estate growth (see the alarm count below) and undercounted CloudWatch/Tax.*
- **Variable Bedrock AI, development-driven:** May $14.29 → Jun **$43.98** (Haiku $26.91 +
  Sonnet $17.07 — the Coaching-door launch + QA marathons) → Jul MTD $24.43 (Haiku $14.34 +
  Sonnet $10.09). Spiky with dev sessions, not steady; hard-capped by the enforcing
  governor.

**Honest correction to the old "steady-state ~$25–40/mo" expectation:** in practice,
dev-heavy months run **$50–80** ($80 was reached in June and is projected again for
July). ~$40 of that is the structural floor; the rest is Bedrock proportional to how
much building happened. The ceiling holds — June peaked at 94% of the $85 base and
tier-2/3 degradation fired as designed (Jun 15–18).

## Budget guardrails (automated, ENFORCING)

Three layers — `lambdas/ai/budget_guard.py`, `lambdas/operational/cost_governor_lambda.py`:

1. **AWS Budget** (`life-platform-monthly-75`, CDK CoreStack — name historical): one $85
   budget, email notifications at **50/70/85/100% (actual + 100% forecast)** →
   `awsdev@mattsusername.com`. Lagged backstop (Cost Explorer trails Bedrock 24–48h).
2. **cost-governor** — runs **every 8h** (`cron(0 0/8 * * ? *)`).
   Cadence history: was hourly → 4h (2026-06-08) → 8h (2026-06-16), both CE-self-cost trims.
   Estimates near-real-time spend (Cost Explorer non-AI + Bedrock per-model token
   metrics × price, +15% buffer), projects month-end from trailing-7d burn, and writes a
   **tier** to SSM `/life-platform/budget-tier` + the full projection breakdown to
   `/life-platform/budget-breakdown`. Alerts on tier change. Emits
   `LifePlatform/Budget::BudgetTier` every run — the tier-residence history used below.

   The breakdown payload carries the ADR-133 **envelope**, not just the one number
   in effect (#1999): `base_ceiling` / `surge_ceiling` (the pair `_active_ceilings()`
   returns today, surge floored at the base) and `ceiling_window` — `null` normally,
   or `{start, end_exclusive, base_ceiling, surge_ceiling, reverts_to_base_ceiling,
   reverts_to_surge_ceiling, reason}` while a dated temp window is open. Consumers
   (`/api/receipts`, `/api/inference_receipt`) publish those instead of a hardcoded
   base literal, so a raised base explains itself on the public receipt instead of
   showing an unattributed gap. Their literal is a **fail-closed fallback only** —
   reached when the param is missing, unreadable, or predates this schema (an old
   payload persists until the governor's next 8h run rewrites it).
3. **budget_guard** (graceful degradation, audience-ordered per ADR-125 — the daily
   brief is protected longest). The bands are **fixed fractions of the effective
   ceiling** (≈73% / 87% / 97%), so they scale automatically between the $215 base and
   the $252 surge ceiling:

   | Tier | Band (of effective ceiling) | Trips at ($215 base) | Trips at ($252 surge) | Effect |
   |------|------------------------------|---------------------|-----------------------|--------|
   | 0 Normal | < 73% | < $157.67 | < $184.80 | everything runs |
   | 1 Caution | 73–87% | $157.67 | $184.80 | internal/dev AI paused (ensemble, chronicle editor, coherence-semantic) |
   | 2 Restrict | 87–97% | $186.33 | $218.40 | + reader narratives paused (coach commentary, State of Matthew, chronicle) |
   | 3 Hard stop | ≥ 97% | $209.27 | $245.28 | + website AI returns "paused", daily brief data-only; `bedrock_client` refuses |

   Trip amounts computed by executing `cost_governor_lambda._tier_for`'s own band
   scaling (thresholds `[(73,3),(65,2),(55,1)]` against the $75 reference ceiling),
   not hand-multiplied — the bands are 73.3% / 86.7% / 97.3% exactly.

   Auto-resumes at month rollover. **Status: ENFORCING** (`OBSERVE_MODE=false` since
   2026-05-29). Harsh tiers (2/3) additionally require ACTUAL month-to-date dollars, not
   just projection (the projection may escalate at most one tier above actual).

Budget email: `awsdev@mattsusername.com`

## Tier residence — a decided posture, not an invisible steady state

Measured from `LifePlatform/Budget::BudgetTier` (daily max ≥ 1; metric exists since the
governor launch 2026-05-29): **June sat at tier ≥1 on 19 of 30 days** (including a
tier-2/3 excursion Jun 15–18) and **July on 14 of its first 19 days** — a continuous
tier-1 run since 2026-07-06.

This is arithmetic, not anomaly: with a ~$40/mo non-AI floor, tier 1 at the $85 base
trips when projected AI spend exceeds ~$22/mo (~$0.75/day) — which any sustained dev
sprint does. **Decision (ADR-133 amendment, 2026-07-19): tier-1 residence is the
expected and accepted state in dev-heavy months.** Tier 1 pauses only internal/dev AI
(ensemble, chronicle editor, coherence-semantic) — the reader surfaces and the daily
brief stay on, which is the ladder doing exactly its ADR-125 job. The tier bands are
deliberately **not** re-derived upward from the measured floor: the 73% band exists to
degrade *before* the ceiling is threatened, and spending that margin to make tier-0 the
cosmetic norm would neuter the early warning. See `DECISIONS.md` (ADR-133) for the full
record.

## Monthly close ritual (#1354)

At each month rollover, append a row to Monthly Actuals with three facts:

1. **CE actual** — `aws ce get-cost-and-usage --time-period Start=<mo>-01,End=<next-mo>-01
   --granularity MONTHLY --metrics UnblendedCost` (grouped `--group-by
   Type=DIMENSION,Key=SERVICE` for the notes).
2. **Days at tier ≥1** — the degraded-tier residence line:

   ```bash
   aws cloudwatch get-metric-statistics --namespace LifePlatform/Budget \
     --metric-name BudgetTier --start-time <mo>-01T00:00:00Z --end-time <next-mo>-01T00:00:00Z \
     --period 86400 --statistics Maximum --region us-west-2 \
     --query 'Datapoints[?Maximum>=`1`] | length(@)'
   ```

   (CloudWatch retains this at 1-hour granularity for 15 months; the number recorded
   here is the durable ledger beyond that window.)
3. **Cost per reader-week** (derived) — monthly bill ÷ (trailing-7d uniques × weeks in
   month), uniques from `LifePlatform/Traffic::UniqueVisitors7d`. Jul 2026: $80.11
   projected ÷ (972 × 4.43) ≈ **$0.02 per unique-visitor-week**.
4. **Spike vs. steady** (#2892) — how much of the month's AI spend was the platform
   running itself versus a human working on it. `bedrock_client.invoke()` stamps a
   `CallerClass` dimension (`prod-cron` · `remediation` · `ci` · `dev-session`) on
   every metered call:

   ```bash
   for c in prod-cron remediation ci dev-session; do
     printf '%-12s ' "$c"
     aws cloudwatch get-metric-statistics --namespace LifePlatform/AI \
       --metric-name EstimatedCostUSD --dimensions Name=CallerClass,Value="$c" \
       --start-time <mo>-01T00:00:00Z --end-time <next-mo>-01T00:00:00Z \
       --period 2678400 --statistics Sum --region us-west-2 \
       --query 'Datapoints[0].Sum' --output text
   done
   ```

   Record the `dev-session + ci` share in the Notes column. This is the self-emitted
   metric, so the absolute dollars under-count (see the guardrails note on
   `CostMetricDriftRatio`) — the **share** is the fact worth recording, and it is what
   the governor's month-end projection now runs on: `prod-cron + remediation` recur and
   get extrapolated over the days remaining, `ci + dev-session` do not. Tier decisions
   are unchanged and still ride TOTAL spend — a dev-heavy month is still a real bill,
   it just stops reading as a permanent run-rate change.

Then update the two **Verified:** stamps in this doc — CI flags the doc at 45 days stale.

## Monthly Actuals

| Month | AWS Bill | Days at tier ≥1 | Notes |
|-------|---------|------------------|-------|
| Feb 2026 | $1.92 | — (no governor yet) | Platform built Feb 22, partial month. |
| Mar 2026 | **$20.04** (CE actual) | — | First full month. Fixed infra only (Secrets $5.12, CloudWatch $4.84, WAF $4.12, CE-API $2.50, Tax $1.88, KMS $0.75) — pre-Bedrock. |
| Apr 2026 | **$35.01** (CE actual) | — | Infra grew: CloudWatch $9.56, WAF $9.04, Secrets $6.90, CE-API $4.25. AI still negligible. |
| May 2026 | **$48.19** (CE actual) | 3 (metric began May 29) | + Bedrock $14.29 (Sonnet $9.31 + Haiku $4.98) — Bedrock-cutover marathon + v4 launch. WAF deleted at month end (~−$8/mo). |
| Jun 2026 | **$79.80** (CE actual, peak) | **19 / 30** | Bedrock $43.98 (Haiku $26.91 + Sonnet $17.07), CloudWatch $14.87, Secrets $7.98, Tax $7.56. Coaching-door launch + QA marathons; tier-2/3 excursion Jun 15–18; 94% of the $85 base — held. |
| Jul 2026 | **$98.35** (CE actual — first close over the $85 base) | **26 / 31** | Bedrock $49.51 (Haiku $28.47 + Sonnet $21.04), CloudWatch $24.50, Secrets $9.83, Tax $9.26. Continuous tier-1 from Jul 6; surge first activated 2026-07-19 (972 uniques). Cost per reader-week ≈ $98.35 ÷ (972 × 4.43) ≈ **$0.023**. |
| Aug 2026 | **$175.85** (CE actual read 08-31 16:00Z — may settle as CE finalizes; month the dated ADR-133 window applied) <!-- drift-ok: dated ledger row — names the August-only window ceiling as history, the current base is $215 --> | **26 / 31** (tier 2 from 08-26; 08-31 datapoint pending at close) | Bedrock $109.61 (Haiku $71.22 + Sonnet $38.39 — spikes 08-10 $18.33, 08-23 $9.55; median $2.22/day, mean $3.54), CloudWatch $31.45, Tax $16.47, Secrets $11.44, S3 $3.16 (deploy-version churn + DIL-027 backfill, one-time). CallerClass (#2892, dimension live only from 08-23 — partial-month): ci $14.38 + dev-session $0.20 = 63% of the $23.19 stamped window; prod-cron $8.45. Cost per reader-week ≈ $175.85 ÷ (897 × 4.43) ≈ **$0.044** (uniques mean 897, n=5 daily datapoints; peak 1,011 on 08-30 — first reading above the 900 surge bar). Uncached input was 57% of Bedrock ($62.20 vs $8.10 cache-read). Closed 2026-08-31 by the financial-diligence session. |

## Current cost structure (rate card, verified 2026-08-18)

| Service | Cost/Month | Notes |
|---------|-----------|-------|
| **Bedrock (AI)** | ~$44–61 (Jun–Aug observed range; steady state ~$1.9/day ≈ $58, spikes on top) | Haiku (structured) + Sonnet (narrative), prompt-cached; tracked near-real-time by the governor; CE lags 24–48h. Token shape Aug MTD: **uncached input $30.81** / output $18.53 / cache-read $6.33 / cache-write $5.67 — half the bill is input that never hits the cache (the #2801 input-diet story). |
| **CloudWatch** | ~$20–25 | The driver FLIPPED (#2837): **custom metrics now beat alarms** — MetricMonitorUsage $16.46 (Jul) from **741 live custom series** (SiteAPI 328, MCP 156; `aws cloudwatch list-metrics`, 2026-08-18) vs AlarmMonitorUsage ~$9–10 from **103 metric alarms live** (`describe-alarms`, 2026-08-18; 35 per-Lambda). Logs ingestion ≈ $0 at this volume. |
| **Secrets Manager** | $10.40 | 26 active secrets × $0.40/secret/month (us-west-2; live-listed 2026-08-18 — PLUS 3 us-east-1 secrets ≈ $1.20/mo the sync literal doesn't count, 29 total; inventory: docs/SECRETS_MAP.md). Jul billed 24.0 secret-months = $9.60 with proration. Consolidation story #2890. |
| **Tax** | ~$4.6–7.6 | Scales with the bill. |
| **Cost Explorer API** | ~$1.3–3.0 | The governor's own CE polling (1 DAILY query per 8h run) + ad-hoc queries. |
| **KMS** | ~$0.6–1.0 | DynamoDB CMK. |
| **Route 53** | $0.50 | 1 hosted zone — flat fee. |
| **Lambda / DynamoDB / S3 / CloudFront / SES** | ~$1.1–1.4 | On-demand DDB, 30-day log retention, S3 lifecycle — all well-managed. |
| **WAF** | $0 | Deleted 2026-06 (was ~$8–9/mo); rate limiting is in-Lambda (DynamoDB-backed). |
| **QA-depth dial (SSM `/life-platform/qa-level`, #1452)** | ~$9–11/mo **swing** — a lever, not a separate line item (its spend rides the Bedrock line above; added 2026-08-31, #3375 — the dial appeared nowhere on this card) | Per level (standalone-QA Bedrock spend, from the #3251 measurement): `full` ≈ $11 (full-surface AI-vision on every standalone fire + reader-truth) · `standard` (default) ≈ $8–9 (reader-truth daily + Sunday full AI-vision — the 6 × $0.195 daily fires + $0.74 Sunday ≈ $8.3/mo that `lean` strips) · `lean` ≈ $0 (deterministic sweep only — also strips the platform's only CI prose truth-check) · `off` ≈ $0 (standalone QA dark — emergency only). Deploy-gating QA copies are structurally exempt from the dial. Semantics: `docs/RUNBOOK.md` § QA Depth Dial. |

## GitHub Actions / Repo Hosting (#1334, #1453 — added 2026-07-18)

**The $215 AWS budget governor above covers AWS spend only.** GitHub became a
*metered production dependency* the moment the repo went private (2026-07-13,
`project_repo_visibility.md`): CI (`ci-cd.yml`), the standing site-deploy path
(`site-deploy.yml`), and the remediation agent (`remediation-agent.yml`) all now
run on GitHub Actions minutes billed against the account's plan allowance — a
private repo has no unlimited-minutes free tier the way a public repo does.

**Update 2026-08-18: the repo has been PUBLIC again since 2026-07-20**, so current
Actions cost is **$0** — but the exposure below is a live **contingent liability**:
at the observed ~11,790 min/mo, flipping private again ≈ **$53/mo** overage
((11,790 − 3,000) × $0.006). Any repo-privacy remediation plan must carry this line.

**Account-specific facts — RESOLVED 2026-07-26 (#1613): the owner's user-scoped
PAT is stored at Secrets Manager `life-platform/github-billing` and as the
`GH_BILLING_TOKEN` repo secret; `deploy/drift_sentinel.py::check_github_quota`
now reads the real figures weekly.**

| Fact | Value | How verified |
|------|-------|----------------|
| Actions minutes used this month | **live** — e.g. 11,790 min July 2026 (public repo, $0 net) | sentinel billing leg: `GET /users/averagejoematt/settings/billing/usage?year=&month=` |
| Paid overage this month | **live** — Σ `netAmount` over the month's actions usage items | same call; any value > $0 sets `warn` |
| Spending limit setting | **unverified** | GitHub → Settings → Billing and plans → Spending limit |

**Endpoint history:** the legacy `GET /users/{owner}/settings/billing/actions`
(and `.../shared-storage`) probed 2026-07-18 as needing the `user` scope is now
**410 Gone** (verified 2026-07-26) — replaced by the enhanced-billing usage API
above, which returns per-SKU `usageItems` (quantity/netAmount) instead of
`total_minutes_used`/`included_minutes`. The included-minutes figure is therefore
the `GITHUB_ACTIONS_INCLUDED_MINUTES` constant (3000, Pro assumption), and the
70% warn is **visibility-aware**: public-repo standard-runner minutes are free,
so the warn only arms while the repo is private (or visibility is unreadable).

**Public plan facts (NOT account-specific — from GitHub's published billing docs,
fetched 2026-07-18; use only as the warn-threshold basis, not as confirmation of
which plan this account is actually on):**

| Plan | Included Actions minutes/mo | Included artifact storage | Linux 2-core overage |
|------|------------------------------|----------------------------|------------------------|
| Free | 2,000 | 500 MB | n/a (private repos on Free get no paid overage — Actions just stops) |
| **Pro** | **3,000** | 1 GB | $0.006/min |
| Team | 3,000 | 2 GB | $0.006/min |

Source: [GitHub Actions billing docs](https://docs.github.com/en/billing/managing-billing-for-github-actions/about-billing-for-github-actions).

**The monthly glance (automated, #1334 AC2 + #1453):** `deploy/drift_sentinel.py`'s
`check_github_quota()` check runs as part of the existing weekly (Monday) drift
sentinel step in `remediation-agent.yml` — no new cron. It:
1. Attempts the real billing-usage API and warns at **70%** of the included allowance
   when it can read one (`GITHUB_ACTIONS_WARN_PCT` in `drift_sentinel.py`); today this
   always reports the fail-soft "billing API unavailable: …" line above for the
   reason just confirmed.
2. Always lists the **top wall-clock-consuming workflows over the trailing 7 days**
   (`gh run list`, needs only `actions: read`) — a same-direction proxy for billable
   minutes (not exact — Actions bills per-job, and parallel jobs move wall-clock the
   opposite direction from billable-minute totals) good enough to attribute a
   run-rate regression to a specific workflow.

Both land in the remediation agent's one curated weekly email
(`remediation/drift_report.quota_html()`, called from `remediation/agent.py`; the
retired `automerge.py` email path went with `auto` mode, #2833) alongside the existing
infra-drift status line — see
`docs/RUNBOOK.md` §"GitHub Actions quota glance" for the manual fallback command.

**CI-minutes run-rate levers already in place:** `concurrency: cancel-in-progress:
true` (scoped per-ref) on the PR-triggered gates that lacked it — `docs-ci.yml` and
`v4-gate.yml` — so a rapid string of pushes to one PR no longer burns minutes on
every superseded run to completion; `visual-qa.yml`/`site-deploy.yml`/`ci-cd.yml`
already had concurrency groups. `golden-brief-eval.yml` and `eval-harvest.yml`
(schedule-only) now queue rather than double-run if a manual `workflow_dispatch`
overlaps their cron.

---

## Cost Decisions Log

Decisions where cost was a factor in the design:

| Date | Decision | Cost Impact | Outcome |
|------|----------|-------------|---------|
| 2026-08-31 | **Brief shared day-context cache prefix (#3367) measured and REJECTED**: ~2,318 common tokens/call across the 7 Sonnet coach calls (clears the 1,024 floor) but worth only ~$1.5/mo at post-#2888 rates — the $4–6/mo premise rested on the 36/day mean (3 outlier days inflate it; steady median 25) and the stale pre-#2888 4.7% cache-hit baseline (actually ~18% since 08-24). The commons sit MID-prompt behind per-coach voice headers, so capture is an M-effort restructure of 7 templates + the byte-exact input-gate contracts | $0 (avoided ~M effort for ~$1.5/mo) | Do not re-propose above ~$2/mo without new measurement. |
| 2026-08-31 | **Cost-allocation tagging evaluated and REJECTED** (financial-diligence panel): a per-stack `Domain` tag can slice only ~$10–13/mo (~6–7%) — Bedrock carries no taggable resource, CW custom metrics are untaggable, DDB/S3 are `from_*_name` imports outside CDK tag reach | $0 (avoided a dead instrument) | Existing instruments (CE usage-type, EMF ledger, CallerClass #2892, `ai_spend_attribution.py`) are finer-grained at $0. Do not re-propose without a change in the taggability facts. |
| 2026-07-19 | **Tier-1 residence accepted as the dev-heavy-month norm** (ADR-133 amendment, #1354); tier bands NOT re-derived from the measured ~$40 floor | $0 | Degraded-tier residence became a recorded posture with a days-at-tier≥1 line in the monthly close, instead of an invisible steady state. |
| 2026-07-08 | Base ceiling $75 → $85 + surge mode to $100 on ≥900 trailing-7d uniques (ADR-133) | headroom, not spend | Reader traffic can never outage reader AI at the moment of success; dev spend can't trigger surge. |
| 2026-06-16 | cost-governor CE polling every 4h → **every 8h** (second CE-self-cost trim) | ~−$1/mo | AI estimate stays fresh from CloudWatch token metrics; only the slow non-AI half is polled. |
| 2026-06-08 | cost-governor CE polling hourly → every 4h (first trim) | ~−$2–3/mo | Same rationale. |
| 2026-06 | **WAF deleted** (~−$8/mo; June+ shows $0) | −$8/mo | Rate limiting moved fully in-Lambda (DynamoDB atomic counters). |
| 2026-05-29 | Bedrock migration + enforcing governor + budget guard (ADR-062/063) | AI spend became governable | Hard ceiling with graceful audience-ordered degradation; the ceiling was $85 at the time. <!-- drift-ok: dated ledger row, states the ceiling in force on 2026-05-29 --> |
| 2026-05-17 | V2 audit cost optimization (P5): 5-item sweep (power-tuning Lambdas, orphan IAM roles, duplicate alarms, orphan secrets) | −$3.65/mo | Full effect from June 2026 onward. |
| 2026-03-10 | CloudWatch alarm consolidation (COST-A): 87 → ~41 alarms (14 CDK duplicates + ~32 pre-CDK orphans) | −$4.60/mo at the time | The estate has since deliberately re-grown to 74 with platform scope (see rate card). |
| 2026-03-05 | Secrets Manager consolidation: 12 → 9 active secrets | −$1.20/mo | Later re-grew with new integrations to 21 — isolation per OAuth service is the accepted trade. |
| 2026-02-28 | Reserved concurrency (10) on MCP Lambda instead of WAF | −$5/mo | 80% of WAF protection for $0. |
| 2026-02-26 | Rejected provisioned concurrency for MCP Lambda | −$10.80/mo | Solved latency with memory bump (+$1/mo) + caching. |
| 2026-02-25 | DynamoDB on-demand (not provisioned) | −$10–15/mo vs provisioned | Workload is spiky. |
| 2026-02-25 | Single DynamoDB table (GSIs only by ADR — two exist per ADR-097) | ~$0 extra | Access patterns served by PK+SK. |
| 2026-02-24 | CloudWatch 30-day log retention | saves vs infinite | Older data in S3 raw archives. |
| 2026-02-23 | MCP via Lambda Function URL (not API Gateway) | $0 vs ~$3.50/mo | In-Lambda API key check = free. |

## Potential cost increases (planned features)

| Feature | Est. Monthly Cost | Status |
|---------|-------------------|--------|
| Additional Secrets Manager secrets | $0.40/each | OAuth sources stay separate; static API keys merge into `life-platform/ingestion-keys`. |
| Reader-traffic surge | up to +$15/mo (the $85→$100 float) | ADR-133 — engaged automatically, first activation 2026-07-19. |
| Provisioned concurrency (rejected) | $10.80/month | ❌ Rejected — caching solved it. |

---

**Verified:** 2026-08-31 (financial-diligence session — August close row (CE by-service, tier residence, CallerClass split, reader-week), ceiling-revert facts re-read via budget_ceilings.py; rate-card ranges NOT re-verified this run — several no longer contain the Aug actuals, tracked as a filed finding), Aug DAILY
by Bedrock model; SSM `/life-platform/budget-tier` + `budget-breakdown`;
`describe-alarms` (103) + `list-metrics` (741 custom series); `list-secrets` both
regions (29); `LifePlatform/Budget::BudgetTier` daily Jul 1 → Aug 18;
`LifePlatform/Traffic::UniqueVisitors7d` (773). Prior full rewrite: 2026-07-19, #1354.
The tier-residence and guardrail prose above the close ritual was NOT re-derived this
pass — its Verified date remains 2026-07-19 per the #2838 stamp-honesty rule.)

## What degrades when (the tier ladder)

The feature-by-tier degradation ladder (tier 0–3, bands ≈73/87/97% of the effective
ceiling, audience-ordered per ADR-125 — internal AI pauses first, the daily brief is
protected longest) is specified once in `CLAUDE.md` §"AI Inference (Bedrock + Budget
Guard)" and implemented in `lambdas/ai/budget_guard.py` (tests: `test_budget_guard_ladder.py`).
Check the live tier: `aws ssm get-parameter --name /life-platform/budget-tier --query Parameter.Value --output text`.
