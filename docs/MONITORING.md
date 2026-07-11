# Life Platform — Monitoring & Observability

> **Status:** canonical · **Owner:** Matthew · **Verified:** 2026-07-10

**Last updated:** 2026-05-19 (v8.0.0)

What's monitored, what fires alarms, where to look when something's wrong.

---

## The 3-second answer: "Is anything broken right now?"

```bash
# Quick health check
aws cloudwatch describe-alarms --state-value ALARM --region us-west-2 \
  --query 'MetricAlarms[].AlarmName' --output table

# Or check the platform status endpoint
curl https://averagejoematt.com/api/status/summary
```

Empty list / `green` = nothing's currently firing.

---

## Alarm tiers (ADR-052)

**Two-tier alerting:** urgent vs digest. Goal: page loudly only for real emergencies.

| Tier | SNS Topic | Action | When |
|---|---|---|---|
| **Urgent** | `life-platform-alerts` | Email immediately | Lambda outright failing, data loss risk, security incident |
| **Digest** | `life-platform-alerts-digest` | Batched daily via `alert-digest` Lambda | Warnings, slow trends, single-eval failures |

In code (CDK), alarm constructor chooses the topic via `digest=True/False` flag in `lambda_helpers.create_platform_lambda()`.

---

## Active alarms (~50 total as of 2026-06-08)

### Critical (urgent tier — page immediately if firing)

| Alarm | Threshold | Trigger |
|---|---|---|
| `life-platform-daily-brief-errors` | ≥1 error in 5min window | Daily-brief Lambda failed |
| `slo-daily-brief-delivery` | ≥1 Lambda error in 24h (error-count, not absence-detection) | Brief errored today |
| `daily-brief-no-invocations-24h` | <1 invocation in 24h | Brief never ran (the absence signal) |
| `mcp-warmer-error` | Failure | MCP warming broken |
| `life-platform-canary-mcp-failure` | Failure | MCP Lambda unreachable |
| `life-platform-canary-anthropic-failure` | Failure | Anthropic API access lost (key disabled or billing) |
| ⚠️ NO fleet-wide ingestion-error ALARM exists (by design) | — | Per-Lambda alarms removed 2026-05-29; CloudWatch's ~10-metric math cap prevents an aggregate (19 ingestion fns). Detection is downstream: `slo-source-freshness`, DLQ depth alarms, the canary, the remediation agent. The `LifePlatformMonitoring` metric-math is a DASHBOARD widget only — it does not page |
| `life-platform-dlq-depth-warning` | ≥10 messages | Real failures accumulating |
| AWS Budget `life-platform-monthly-75` ($85 ceiling, ADR-133) + cost-governor SSM tiers | 50/70/85/100% alerts | Budget breach (an AWS Budget + SSM mechanism, not a CloudWatch alarm) |

### Warning (digest tier — review daily)

| Alarm | Threshold | Trigger |
|---|---|---|
| `*-duration-p95` (most Lambdas) | p95 > 80% of timeout | Lambda getting slow |
| `slo-source-freshness` | Any source > 48h stale | Data flow degraded |
| `ai-tokens-daily-brief-daily` | Token spend above calibrated threshold | AI spend spike |
| `cf-4xx-rate-elevated` | >50% over 5min | CloudFront errors |
| `ses-bounce-rate` | >5% in 24h | Email deliverability issue |

---

## CloudWatch namespaces

The platform emits custom metrics across these namespaces:

| Namespace | Source | What it measures |
|---|---|---|
| `AWS/Lambda` | AWS auto | Invocations, errors, duration, throttles |
| `AWS/DynamoDB` | AWS auto | Capacity consumption, throttles |
| `AWS/CloudFront` | AWS auto | Hits, error rates, cache hit ratio |
| `AWS/SES` | AWS auto | Send, Delivery, Open, Click, Bounce, Complaint |
| `AWS/SQS` | AWS auto | Queue depth, message age |
| `LifePlatform/AI` | retry_utils + site_api_ai | AnthropicInputTokens, AnthropicOutputTokens, AnthropicCacheReadTokens, AnthropicCacheWriteTokens, AnthropicAPIFailure |
| `LifePlatform/MCP` | mcp/handler.py | ToolInvocations (by tool name), ToolDuration, ToolError |
| `LifePlatform/SiteApi` | site_api_lambda emit_route_log | RouteHits, RouteDuration, RouteErrors |
| `LifePlatform/Freshness` | freshness_checker | StaleSourceCount, WarningSourceCount, PartialCompletenessCount |
| `LifePlatform/DailyBrief` | daily_brief EMF blobs | DataPresent (by source), PassFail (by component) |
| `LifePlatform/Pipeline` | pipeline_health_check | ComputeOutputsMissing, PipelineLatency |
| `LifePlatform/Compute` | compute_metadata.tag_record | RecordWritten (per compute Lambda) |
| `LifePlatform/Canary` | canary_lambda | CanaryMCPFail, CanaryAnthropicFail |

---

## Logs

### Log groups
Every Lambda has its own log group at `/aws/lambda/<function-name>`. CloudWatch Logs Insights queries:

```
filter @message like /ERROR/
| sort @timestamp desc
| limit 50
```

### Retention
- **Default:** 30 days (set via CDK `log_retention=ONE_MONTH`, V2 P2.3)
- **Critical Lambdas** (canary, key-rotator, dlq-consumer): consider 90d retention manually

### Structured logging
All Lambdas use `platform_logger.get_logger()` which emits JSON like:

```json
{
  "timestamp": "2026-05-19T15:00:00Z",
  "level": "INFO",
  "source": "daily-brief",
  "lambda": "daily-brief",
  "lambda_version": "$LATEST",
  "correlation_id": "daily-brief#2026-05-18",
  "message": "Date: 2026-05-18 | sources: whoop, sleep, ..."
}
```

This lets Logs Insights filter by source, correlation_id, etc.

---

## CloudWatch Logs Insights — useful queries

### Last 20 errors across all Lambdas (last 1h)
```
fields @timestamp, @log, @message
| filter @message like /ERROR/ or @message like /Traceback/
| sort @timestamp desc
| limit 20
```

(Run in CloudWatch Logs Insights with "All log groups" selected.)

### Daily-brief output verification
```
fields @timestamp, @message
| filter @log like /daily-brief/
| filter @message like /Filed:/ or @message like /Sent:/
| sort @timestamp desc
| limit 10
```

### Slowest MCP tool calls last 24h
```
fields @timestamp, @message
| filter @log like /mcp/
| filter @message like /tool_*/ and @message like /duration_ms/
| parse @message /duration_ms=(?<duration>\d+)/
| sort duration desc
| limit 20
```

### Token telemetry — daily AI cost estimation
```
fields @timestamp, @log
| filter @message like /Token usage/
| parse @message /input: (?<in>\d+), output: (?<out>\d+)/
| stats sum(in) as total_in, sum(out) as total_out by bin(1h)
```

Apply: total_in × $0.25/M (Haiku input) or $3/M (Sonnet input) + total_out × $1.25/M or $15/M.

---

## Dashboards (CloudWatch)

Suggested dashboards (manual creation recommended):

1. **Platform Health** — alarm states, error counts, recent invocations
2. **Daily Pipeline** — character_sheet → adaptive_mode → daily_metrics → daily_insight → daily_brief timing
3. **AI Spend** — per-Lambda token usage, cache hit rate, Anthropic 429 count
4. **Public Site** — CloudFront hit rate, 4xx/5xx, top paths, response time
5. **Subscriber Engagement** — SES Send/Delivery/Open/Click/Bounce
6. **Ingestion Sources** — per-source: invocations, last-success, gap count, DLQ contribution

None of these are committed to source (CDK custom dashboards). Build them in the CloudWatch console; pin to your bookmarks.

---

## On-call procedure

If you're paged (or notice red alarms during a routine check):

1. **Identify** — look at the alarm name + check `aws cloudwatch describe-alarms --alarm-names <name>` for details
2. **Triage** — is it real (user-impacting) or noisy (single-eval false positive)? Most alarms wait for 2+ evaluation periods before firing.
3. **Investigate** — pull the Lambda's logs from the time of failure
   ```bash
   aws logs filter-log-events --log-group-name /aws/lambda/<fn> \
     --region us-west-2 --start-time $(($(date +%s) - 3600))000 \
     --filter-pattern ERROR --max-items 10
   ```
4. **Mitigate** — common patterns:
   - Lambda erroring on every invoke → rollback (`bash deploy/rollback_lambda.sh <fn>`)
   - OAuth failure → check secret, re-auth source (e.g., `python3 setup/setup_garmin_browser_auth.py`)
   - Rate limit → wait or raise the rate limiter cap
   - Cost spike → identify spending Lambda; consider throttling
5. **Document** — add entry to `docs/INCIDENT_LOG.md` if user-impacting

---

## Metrics gaps + open items

See `docs/BACKLOG.md` for the full backlog. Monitoring-relevant gaps:

- **No synthetic monitoring** for public site beyond CloudWatch canary on MCP + Anthropic
- Positive daily-brief absence detection exists: `daily-brief-no-invocations-24h` (<1 invocation in 24h). (`life-platform-daily-brief-invocations` was REMOVED 2026-03-10 — don't cite it.) The old "infer from absence of errors" gap is closed
- **Token telemetry rolling out** — 9 of 22 AI-calling Lambdas now emit (V2 follow-up); remaining 13 still dark
- **Cost anomaly detector** is on (Default-Services-Subscription, daily email)
- **Dashboard-as-code** not used — CDK could define dashboards; currently console-managed

---

## Cost of monitoring

| Item | Cost / month |
|---|---|
| CloudWatch alarms (~50 × $0.10, first 10 free) | ~$4-5 |
| CloudWatch metrics (custom, ~50 metrics) | included in alarms |
| Logs storage (~1 GB across all Lambdas) | $0.50 |
| Logs ingestion (~5 GB/mo) | $2.50 |
| CloudTrail data events (raw/* + uploads/*) | ~$0.50 |
| SES tracking events | $0 |
| **TOTAL** | **~$14/month** |

Roughly half the platform's monthly cost. Worth it — most issues surface here before users notice.

---

**Verified:** 2026-05-19
