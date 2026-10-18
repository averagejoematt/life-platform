# Life Platform — Service Level Objectives (SLOs)

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-10-17

> OBS-3: Formal SLO definitions for critical platform paths.
> Last updated: 2026-10-18 (v8.6.0)

---

## Overview

Four SLOs define the platform's reliability contract (a fifth alarm, `slo-warmer-completeness`, is described after SLO-4). Each SLO has a measurable Service Level Indicator (SLI), a target, and a CloudWatch alarm that fires on breach.

**Alarm routing differs per SLO** (ADR-050): only `slo-daily-brief-delivery` publishes to the urgent `life-platform-alerts` topic. The others (freshness, AI coaching, MCP availability and the warmer alarm below) publish to the digest topic, being degradation signals rather than pages. Read the routing from the alarm declarations, not from this page. The `life-platform-ops` dashboard has **no dedicated SLO section** (see *CloudWatch Dashboard Widgets*).

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
| **Alarm** | `slo-source-freshness` — fires if `StaleSourceCount` Maximum ≥ 1 in a 24-hour period (one evaluation period) |
| **Metric** | `LifePlatform/Freshness::StaleSourceCount`, custom metric emitted by `lambdas/emails/freshness_checker_lambda.py` |
| **Recovery** | Identify stale source → check ingestion Lambda logs → fix auth/API issue → manually invoke |

**Monitored sources:** the behavioral, non-paused sources in `lambdas/ingestion/source_registry.py` (each source's `stale_hours` and `paused` facets are authoritative; the count and the per-source thresholds live there, not on this page). The 48h figure below is the checker's default (`STALE_HOURS`); sources with a longer cadence (e.g. Food Delivery, 90 days) carry their own `stale_hours`.
**Note:** Labs, DEXA, and Genome are periodic/manual — not subject to the 48h freshness SLO. Infrastructure liveness (a pipe erroring or not running) is a separate alarm, `ingest-liveness-unhealthy`, so a quiet behavioral source and a broken pipe are never conflated.

**Why 48h threshold:** Many sources only sync once daily. A 24h threshold would false-alarm on normal timezone drift. 48h catches genuine failures while tolerating expected gaps (e.g., no MacroFactor data on a day Matthew doesn't log food).

---

### SLO-3: MCP Availability

| Field | Value |
|-------|-------|
| **SLI** | MCP Lambda invocations that complete without error |
| **Target** | 99.5% |
| **Window** | Rolling 7-day |
| **Alarm** | `slo-mcp-availability` — fires if MCP Lambda `Errors` Sum ≥ 3 in a 1-hour period (an absolute count, not a rate; the 99.5% target is a review measure, not computed by the alarm — `cdk/stacks/mcp_stack.py`) |
| **Metric** | `AWS/Lambda::Errors` for `life-platform-mcp` (the SLI ratio would add `AWS/Lambda::Invocations`) |
| **Recovery** | Check CloudWatch logs → redeploy from last-known-good code |

**Why 99.5%:** MCP is the interactive query layer — errors directly block Claude from answering questions. Higher bar than batch email Lambdas.

**Cold start note:** Cold starts (~700-800ms) are not errors. The SLI measures availability (error-free completion), not latency. Latency is watched separately by the `mcp-server-duration-high` alarm (`Duration` p99 ≥ 240000 ms over 24h, digest-routed).

---

### SLO-4: AI Coaching Success

| Field | Value |
|-------|-------|
| **SLI** | Anthropic API calls that return a valid response |
| **Target** | 99% |
| **Window** | Rolling 7-day |
| **Alarm** | `slo-ai-coaching-success` — `Sum >= 3` over one 86400s period — it fires on the **3rd** failure in a 24-hour window (the threshold is inclusive) |
| **Metric** | the **dimensionless** `LifePlatform/AI::AnthropicAPIFailure` — a **fleet-wide** total across every emitter, not a per-Lambda count |
| **Emitters** | 7: `common/retry_utils.py`, `ai/ai_transport.py`, and the five coach Lambdas (`coach_ensemble_digest`, `coach_history_summarizer`, `coach_narrative_orchestrator`, `coach_quality_gate`, `coach_state_updater`) — each writes **two** datapoints per failure, one tagged `{LambdaFunction=…}` for attribution and one dimensionless for this alarm |
| **Recovery** | Check Anthropic status page → if upstream outage, wait. If code issue, fix prompt/parsing. Attribute with the `{LambdaFunction=…}` series |

**Why count-based not rate-based:** The platform makes ~15-20 AI calls/day across all Lambdas. A rate-based alarm with so few datapoints would be noisy. A count threshold of 3 failures/day (fleet-wide) means something is systematically wrong (not just a transient 429).

**Emitter roster is a floor, not a list:** `tests/test_alarm_emission_dimension_3260.py` pins `EMITTER_FLOOR` (7 for `AnthropicAPIFailure`); read that test, not this row, for the current minimum.

**The dimensionless series is load-bearing (#3260).** CloudWatch does not roll a custom metric up across dimension sets. Until 2026-08-27 every emitter attached `{LambdaFunction=…}` and the alarm had no dimensions, so it read a series nothing wrote: **0 datapoints in 180 days**, while `{LambdaFunction=daily-brief}` alone recorded 329 failures over 18 days and 2026-05-26 saw 191 failures across five Lambdas. The alarm's last state change was 2026-03-08 with `StateReason: "no datapoints were received"`. The fix is the emitters' dimensionless twin — the same shape `bedrock_client._emit_usage_metrics` uses for `AnthropicOutputTokens` and `auth_breaker.auth_health_metric_data` uses for `IngestAuthHealthy`. The alarm stays dimensionless **deliberately**: a per-function dimension would silently reinterpret `Sum >= 3` as a per-function threshold (five Lambdas failing twice each = 10 real failures and no page). Pinned by `tests/test_alarm_emission_dimension_3260.py`.

### SLO-5: MCP Warmer Completeness (alarm only)

`slo-warmer-completeness` (`cdk/stacks/mcp_stack.py`) fires if `life-platform-mcp-warmer` `Errors` Sum ≥ 1 in 24h (digest-routed): a failed warmer means the tools serve stale cached data all day. It is an Errors alarm and cannot see a warmer that stopped running; the absence case has its own alarm in the same file (#3161). It has no target or error budget below.

---

## CloudWatch Dashboard Widgets

**Drift found 2026-10-17:** earlier editions of this page described an "SLO Health" section on `life-platform-ops` (status panel, daily-brief success rate, MCP error rate, AI failure trend). `cdk/stacks/monitoring_dashboards.py` defines no such section. What `life-platform-ops` actually carries is: ingestion freshness counts (including `StaleSourceCount`), per-source ingestion Lambda errors and invocations, compute-pipeline duration and errors (which includes `daily-brief`), AI output tokens and projected spend, the budget tier, and ingestion DLQ depth. There is no widget for `AnthropicAPIFailure`, MCP errors or an SLO alarm-state panel; the SLO alarms are read from CloudWatch alarms directly.

---

## SLO Review Cadence

- **Weekly:** Glance at the SLO alarm states (CloudWatch alarms) and the ops dashboard during Weekly Digest review
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

---

## SLO Status Snapshot — HISTORICAL (2026-05-19 audit; statuses below are frozen, NOT current)

> Live status: run the describe-alarms command below + check /status/. The May incidents
> referenced here (Garmin staleness, SES IAM regression) were resolved in May–June.

| SLO | Status (2026-05-19) | Notes |
|-----|--------|-------|
| SLO-1 Daily Brief | Likely BREACHED in current window | Daily-brief was AccessDenied for 2026-05-17 (V2 SES IAM regression) — error budget consumed for May. Recovered same day. |
| SLO-2 Freshness | **BREACHED** | `slo-source-freshness` in ALARM — Garmin stale ~44 days (P2 incident, see INCIDENT_LOG.md). Expected to clear within 24h of OAuth refresh. |
| SLO-3 MCP | OK | No alarms firing |
| SLO-4 AI | At risk | `ai-tokens-daily-brief-runaway` in ALARM (one brief run burned >35k output tokens) — investigate prompt/retry-loop growth |

Point-in-time ALARM snapshots drift (the 2026-05-19 snapshot that used to sit here named alarms that no longer exist). Get the live picture: `aws cloudwatch describe-alarms --state-value ALARM --query 'MetricAlarms[].AlarmName' --region us-west-2`.

---

**Verified:** 2026-10-17 (re-verified against the alarm declarations; the May 2026 V2 audit sweep remains the origin of the historical snapshot above)
