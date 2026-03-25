# Life Platform — Service Level Objectives (SLOs)

> OBS-3: Formal SLO definitions for critical platform paths.
> Last updated: 2026-03-25 (v3.9.21)

---

## Overview

Four SLOs define the platform's reliability contract. Each SLO has a measurable Service Level Indicator (SLI), a target, and a CloudWatch alarm that fires on breach.

All SLO alarms publish to `life-platform-alerts` SNS topic. The operational dashboard (`life-platform-ops`) includes an SLO tracking widget section.

---

## SLO Definitions

### SLO-1: Daily Brief Delivery

| Field | Value |
|-------|-------|
| **SLI** | Daily Brief Lambda completes without error |
| **Target** | 99% (≤3 missed days per year) |
| **Window** | Rolling 30-day |
| **Alarm** | `slo-daily-brief-delivery` — fires if Daily Brief Lambda errors ≥1 in a 24-hour period |
| **Metric** | `AWS/Lambda::Errors` for `daily-brief`, Sum, 24h period |
| **Recovery** | Check CloudWatch logs → fix code or data issue → re-invoke manually |

**Why 99% not 99.9%:** Single-user platform with no revenue SLA. 99% allows for the occasional bad deploy or upstream API outage without false-alarming. One missed day is annoying, not dangerous.

---

### SLO-2: Data Source Freshness

| Field | Value |
|-------|-------|
| **SLI** | Number of monitored data sources with data older than 48 hours |
| **Target** | 99% of checks show 0 stale sources |
| **Window** | Rolling 30-day |
| **Alarm** | `slo-source-freshness` — fires if `StaleSourceCount > 0` for 2 consecutive checks |
| **Metric** | `LifePlatform/Freshness::StaleSourceCount`, custom metric emitted by `freshness_checker_lambda.py` |
| **Recovery** | Identify stale source → check ingestion Lambda logs → fix auth/API issue → manually invoke |

**Monitored sources (10):** Whoop, Withings, Strava, Todoist, Apple Health, Eight Sleep, MacroFactor, Garmin, Habitify, Google Calendar.

**Why 48h threshold:** Many sources only sync once daily. A 24h threshold would false-alarm on normal timezone drift. 48h catches genuine failures while tolerating expected gaps (e.g., no MacroFactor data on a day Matthew doesn't log food).

---

### SLO-3: MCP Availability

| Field | Value |
|-------|-------|
| **SLI** | MCP Lambda invocations that complete without error |
| **Target** | 99.5% |
| **Window** | Rolling 7-day |
| **Alarm** | `slo-mcp-availability` — fires if MCP Lambda error rate exceeds 0.5% over 1 hour |
| **Metric** | `AWS/Lambda::Errors` / `AWS/Lambda::Invocations` for `life-platform-mcp` |
| **Recovery** | Check CloudWatch logs → redeploy from last-known-good code |

**Why 99.5%:** MCP is the interactive query layer — errors directly block Claude from answering questions. Higher bar than batch email Lambdas.

**Cold start note:** Cold starts (~700-800ms) are not errors. The SLI measures availability (error-free completion), not latency. A separate informational metric tracks p95 duration.

---

### SLO-4: AI Coaching Success

| Field | Value |
|-------|-------|
| **SLI** | Anthropic API calls that return a valid response |
| **Target** | 99% |
| **Window** | Rolling 7-day |
| **Alarm** | `slo-ai-coaching-success` — fires if `AnthropicAPIFailure` count exceeds 2 in a 24-hour period |
| **Metric** | `LifePlatform/AI::AnthropicAPIFailure` (already emitted by `ai_calls.py`) |
| **Recovery** | Check Anthropic status page → if upstream outage, wait. If code issue, fix prompt/parsing |

**Why count-based not rate-based:** The platform makes ~15-20 AI calls/day across all Lambdas. A rate-based alarm with so few datapoints would be noisy. A count threshold of 2 failures/day means something is systematically wrong (not just a transient 429).

---

## CloudWatch Dashboard Widgets

The `life-platform-ops` dashboard includes an "SLO Health" section with:

1. **SLO Status Panel** — 4 metric widgets showing current alarm states
2. **Daily Brief Success Rate** — 30-day graph of daily-brief errors
3. **Source Freshness Trend** — 30-day graph of stale source count
4. **MCP Error Rate** — 7-day graph of MCP error count
5. **AI Failure Trend** — 7-day graph of Anthropic API failures

---

## SLO Review Cadence

- **Weekly:** Glance at ops dashboard SLO section during Weekly Digest review
- **Monthly:** Review any SLO breaches in Monthly Digest (future integration)
- **Quarterly:** Review whether SLO targets need adjustment based on platform growth

---

## Error Budgets

| SLO | Target | Budget (30-day) | Budget (yearly) |
|-----|--------|-----------------|------------------|
| SLO-1 Daily Brief | 99% | 7.2 hours (~0.3 missed days) | 3.65 days |
| SLO-2 Freshness | 99% | 7.2 hours | 3.65 days |
| SLO-3 MCP | 99.5% | 3.6 hours | 1.83 days |
| SLO-4 AI | 99% | ~3 failed calls/day budget | ~1,095 failed calls/year |

**Error budget policy:** When budget is burned >50% in a rolling window, pause feature work and investigate. This is a personal guideline, not an automated gate.
