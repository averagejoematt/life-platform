# Life Platform — Cost Tracker

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-19

Last updated: 2026-07-24 (v8.6.0)

> Budget ceiling: **$85/month all-in** base, floating to **$100 in surge mode** on real
> reader traffic (≥900 trailing-7d uniques — ADR-133). History: $25 → $75 with the
> Bedrock migration + automated guardrails (2026-05-29), $75 → $85 on 2026-07-08 (ADR-133
> amendment). Design constraint: every feature must justify its cost.
>
> **Freshness contract (#1354):** every number below was read from live Cost Explorer /
> SSM / CloudWatch on the Verified: date. `scripts/check_doc_facts.py` fails CI when the
> newest Verified: stamp in this doc is older than **45 days** — re-run the close ritual
> below and re-stamp.

---

## Live posture snapshot — 2026-07-19

From SSM `/life-platform/budget-tier` + `/life-platform/budget-breakdown` (the governor's
own output, computed 2026-07-19T16:00Z):

| Fact | Value |
|------|-------|
| Tier | **1** (Caution — internal/dev AI paused) |
| MTD estimated total | $50.40 |
| Projected month-end | $80.11 |
| Effective ceiling | **$100 — surge mode ACTIVE** (972 trailing-7d uniques ≥ the 900 threshold) |
| Burn (trailing 7d) | AI ~$1.20/day + non-AI ~$1.21/day |

## The real monthly bill (Cost Explorer, unblended)

Mar **$20.04** → Apr **$35.01** → May **$48.19** → Jun **$79.80** (the true peak — 94% of
the $85 base) → Jul MTD (through 2026-07-19) **$49.59**, governor-projected **$80.11**.

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

Three layers — `lambdas/budget_guard.py`, `lambdas/operational/cost_governor_lambda.py`:

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
3. **budget_guard** (graceful degradation, audience-ordered per ADR-125 — the daily
   brief is protected longest). The bands are **fixed fractions of the effective
   ceiling** (≈73% / 87% / 97%), so they scale automatically between the $85 base and
   the $100 surge ceiling:

   | Tier | Band (of effective ceiling) | Trips at ($85 base) | Trips at ($100 surge) | Effect |
   |------|------------------------------|---------------------|-----------------------|--------|
   | 0 Normal | < 73% | < $62.33 | < $73.33 | everything runs |
   | 1 Caution | 73–87% | $62.33 | $73.33 | internal/dev AI paused (ensemble, chronicle editor, coherence-semantic) |
   | 2 Restrict | 87–97% | $73.67 | $86.67 | + reader narratives paused (coach commentary, State of Matthew, chronicle) |
   | 3 Hard stop | ≥ 97% | $82.73 | $97.33 | + website AI returns "paused", daily brief data-only; `bedrock_client` refuses |

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

Then update the two **Verified:** stamps in this doc — CI flags the doc at 45 days stale.

## Monthly Actuals

| Month | AWS Bill | Days at tier ≥1 | Notes |
|-------|---------|------------------|-------|
| Feb 2026 | $1.92 | — (no governor yet) | Platform built Feb 22, partial month. |
| Mar 2026 | **$20.04** (CE actual) | — | First full month. Fixed infra only (Secrets $5.12, CloudWatch $4.84, WAF $4.12, CE-API $2.50, Tax $1.88, KMS $0.75) — pre-Bedrock. |
| Apr 2026 | **$35.01** (CE actual) | — | Infra grew: CloudWatch $9.56, WAF $9.04, Secrets $6.90, CE-API $4.25. AI still negligible. |
| May 2026 | **$48.19** (CE actual) | 3 (metric began May 29) | + Bedrock $14.29 (Sonnet $9.31 + Haiku $4.98) — Bedrock-cutover marathon + v4 launch. WAF deleted at month end (~−$8/mo). |
| Jun 2026 | **$79.80** (CE actual, peak) | **19 / 30** | Bedrock $43.98 (Haiku $26.91 + Sonnet $17.07), CloudWatch $14.87, Secrets $7.98, Tax $7.56. Coaching-door launch + QA marathons; tier-2/3 excursion Jun 15–18; 94% of the $85 base — held. |
| Jul 2026 (MTD 19d) | **$49.59** (CE actual) | **14 / 19** | Projected $80.11. Bedrock MTD $24.43; non-AI MTD $25.16. Continuous tier-1 since Jul 6; surge mode ACTIVE 2026-07-19 (972 uniques → $100 ceiling). |

## Current cost structure (rate card, verified 2026-07-19)

| Service | Cost/Month | Notes |
|---------|-----------|-------|
| **Bedrock (AI)** | ~$24–44 (dev-heavy months' observed range) | Haiku (structured) + Sonnet (narrative), prompt-cached; tracked near-real-time by the governor; CE lags 24–48h. |
| **CloudWatch** | ~$11.5–14.9 | Dominated by the alarm estate: **74 metric alarms live** (`aws cloudwatch describe-alarms`, 2026-07-19; the CDK stacks define 75 — one not yet deployed). ~$0.10/alarm ≈ $7.40, + logs/metrics/dashboard. The old claim "consolidated to ~25, no safe consolidation remains" was stale: the estate re-grew with the platform (per-Lambda error alarms are deliberate, ADR-scoped coverage). |
| **Secrets Manager** | $8.40 | 21 active secrets × $0.40/secret/month (live count: `aws secretsmanager list-secrets`; inventory: docs/SECRETS_MAP.md). Jul MTD shows $5.48 (partial month). Mostly irreducible per-service OAuth isolation. |
| **Tax** | ~$4.6–7.6 | Scales with the bill. |
| **Cost Explorer API** | ~$1.3–3.0 | The governor's own CE polling (1 DAILY query per 8h run) + ad-hoc queries. |
| **KMS** | ~$0.6–1.0 | DynamoDB CMK. |
| **Route 53** | $0.50 | 1 hosted zone — flat fee. |
| **Lambda / DynamoDB / S3 / CloudFront / SES** | ~$1.1–1.4 | On-demand DDB, 30-day log retention, S3 lifecycle — all well-managed. |
| **WAF** | $0 | Deleted 2026-06 (was ~$8–9/mo); rate limiting is in-Lambda (DynamoDB-backed). |

## GitHub Actions / Repo Hosting (#1334, #1453 — added 2026-07-18)

**The $85 AWS budget governor above covers AWS spend only.** GitHub became a
*metered production dependency* the moment the repo went private (2026-07-13,
`project_repo_visibility.md`): CI (`ci-cd.yml`), the standing site-deploy path
(`site-deploy.yml`), and the remediation agent (`remediation-agent.yml`) all now
run on GitHub Actions minutes billed against the account's plan allowance — a
private repo has no unlimited-minutes free tier the way a public repo does.

**Account-specific facts (unverified — needs an owner glance with a scoped PAT):**

| Fact | Value | How to verify |
|------|-------|----------------|
| GitHub plan tier (Free/Pro/Team) | **unverified** — assumed Pro per #1334's originating evidence, not confirmed | `gh auth refresh -h github.com -s user` then `gh api user` (look for the `plan` field), or the GitHub billing settings page |
| Actions minutes used this cycle | **unverified** — billing API 404s with the current token | `gh api users/averagejoematt/settings/billing/actions` (needs the `user` scope — see below) |
| Actions artifact/Packages storage used | **unverified** | `gh api users/averagejoematt/settings/billing/shared-storage` (same scope requirement) |
| Spending limit setting | **unverified** | GitHub → Settings → Billing and plans → Spending limit |

**Confirmed by direct probe (2026-07-18, `gh` CLI authenticated as `averagejoematt`,
scopes `gist, read:org, repo, workflow` — no `user` scope):**
```
$ gh api users/averagejoematt/settings/billing/actions
gh: This API operation needs the "user" scope. To request it, run:
  gh auth refresh -h github.com -s user
```
Same result for `.../settings/billing/shared-storage`, and `/user` returns no `plan`
field either. **This is the exact scope gap** — the fix is a one-time, human-run
`gh auth refresh -h github.com -s user` (adds the `user` scope to the *local*
`gh` credential; it does not by itself get the scope into GitHub Actions' built-in
`GITHUB_TOKEN`, which is minted per-run and can never carry a broadened scope — a
real billing-capable CI check would need a **classic PAT stored as a repo secret**,
owned by the account owner, with no extra named scope beyond being the account
owner). **Flagged as a follow-up for the decision menu, not done here** — deploy_
/auth changes are outside this PR's read-only scope.

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
(`remediation/drift_report.quota_html()`, called from both `remediation/agent.py`
and `remediation/automerge.py`) alongside the existing infra-drift status line — see
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
| 2026-07-19 | **Tier-1 residence accepted as the dev-heavy-month norm** (ADR-133 amendment, #1354); tier bands NOT re-derived from the measured ~$40 floor | $0 | Degraded-tier residence became a recorded posture with a days-at-tier≥1 line in the monthly close, instead of an invisible steady state. |
| 2026-07-08 | Base ceiling $75 → $85 + surge mode to $100 on ≥900 trailing-7d uniques (ADR-133) | headroom, not spend | Reader traffic can never outage reader AI at the moment of success; dev spend can't trigger surge. |
| 2026-06-16 | cost-governor CE polling every 4h → **every 8h** (second CE-self-cost trim) | ~−$1/mo | AI estimate stays fresh from CloudWatch token metrics; only the slow non-AI half is polled. |
| 2026-06-08 | cost-governor CE polling hourly → every 4h (first trim) | ~−$2–3/mo | Same rationale. |
| 2026-06 | **WAF deleted** (~−$8/mo; June+ shows $0) | −$8/mo | Rate limiting moved fully in-Lambda (DynamoDB atomic counters). |
| 2026-05-29 | Bedrock migration + enforcing governor + budget guard (ADR-062/063) | AI spend became governable | $85 hard ceiling with graceful audience-ordered degradation. |
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

**Verified:** 2026-07-19 (full rewrite from live Cost Explorer + SSM + CloudWatch — #1354.
Sources: `aws ce get-cost-and-usage` Mar–Jul grouped by SERVICE; SSM
`/life-platform/budget-tier` + `budget-breakdown`; `aws cloudwatch describe-alarms`;
`LifePlatform/Budget::BudgetTier` daily history 2026-05-29 → 2026-07-19.)

## What degrades when (the tier ladder)

The feature-by-tier degradation ladder (tier 0–3, bands ≈73/87/97% of the effective
ceiling, audience-ordered per ADR-125 — internal AI pauses first, the daily brief is
protected longest) is specified once in `CLAUDE.md` §"AI Inference (Bedrock + Budget
Guard)" and implemented in `lambdas/budget_guard.py` (tests: `test_budget_guard_ladder.py`).
Check the live tier: `aws ssm get-parameter --name /life-platform/budget-tier --query Parameter.Value --output text`.
