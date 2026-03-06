# Phase 6 — Observability & Telemetry Review

**Date:** 2026-02-28  
**Platform:** v2.47.1 (97 MCP tools, 22 Lambdas)  
**Reviewer:** Claude (Expert Review)

---

## 6.1 CloudWatch Alarms

**Coverage: 20 of 22 Lambdas have error alarms.** Plus 1 SQS DLQ alarm and 1 recursive-loop guard. This is excellent for a personal project.

**2 Lambdas missing alarms:**
- `weather-data-ingestion` — low risk (weather is non-critical, Open-Meteo has no auth), but should still be monitored
- `life-platform-freshness-checker` — moderate risk. If the freshness checker itself fails, you lose your "watchdog" — who watches the watchman?

**2 alarms currently in ALARM state:**
- `garmin-data-ingestion-errors` — likely residual from the Feb 28 P0 outage. These alarms use a 24-hour evaluation period, so they should auto-clear tomorrow if Garmin runs clean tonight/tomorrow.
- `habitify-ingestion-errors` — same root cause. Should auto-resolve.

**Action:** If these are still in ALARM after 48 hours, investigate. Otherwise they should self-heal.

**Alarm design observations:**
- All alarms route to `life-platform-alerts` SNS topic → email to `awsdev@mattsusername.com`. Good single pane.
- The `health-auto-export-no-invocations-24h` alarm is smart — it detects when the webhook stops receiving data (missing invocations rather than errors). This pattern should be replicated for other critical sources.
- No duration/throttle alarms exist. If a Lambda starts timing out consistently (but not erroring), you'd miss it.

**Recommendations:**
1. **P1:** Add alarm for `weather-data-ingestion` (consistency, 5 min)
2. **P1:** Add alarm for `life-platform-freshness-checker` — this is your meta-monitor (5 min)
3. **P2:** Add duration alarms for `daily-brief` and `life-platform-mcp` — these are the most likely to hit timeout limits as they grow
4. **P3:** Consider a "no invocations" alarm for `daily-brief` — if EventBridge stops firing, you'd want to know

---

## 6.2 CloudWatch Log Retention

**9 of 22 log groups have NO retention policy (never expire):**

| Log Group | Retention | Stored Bytes |
|-----------|-----------|-------------|
| `/aws/lambda/dropbox-poll` | ♾️ Never | 122 KB |
| `/aws/lambda/eightsleep-data-ingestion` | ♾️ Never | 5 KB |
| `/aws/lambda/garmin-data-ingestion` | ♾️ Never | 27 KB |
| `/aws/lambda/habitify-data-ingestion` | ♾️ Never | 7 KB |
| `/aws/lambda/health-auto-export-webhook` | ♾️ Never | 15 KB |
| `/aws/lambda/insight-email-parser` | ♾️ Never | 2 KB |
| `/aws/lambda/journal-enrichment` | ♾️ Never | 4 KB |
| `/aws/lambda/macrofactor-data-ingestion` | ♾️ Never | 14 KB |
| `/aws/lambda/notion-journal-ingestion` | ♾️ Never | 8 KB |
| `/aws/lambda/weather-data-ingestion` | ♾️ Never | 1 KB |

**13 of 22 have 30-day retention** — correctly set.

At current volumes (~205 KB total for the 9 unset groups), cost impact is negligible. But this is a hygiene issue — over months/years, unbounded log retention grows silently. The Phase 4 cost review also flagged this.

**Recommendation:**
- **P1:** Set 30-day retention on all 9 missing log groups. One-liner per group:

```bash
for lg in dropbox-poll eightsleep-data-ingestion garmin-data-ingestion habitify-data-ingestion health-auto-export-webhook insight-email-parser journal-enrichment macrofactor-data-ingestion notion-journal-ingestion weather-data-ingestion; do
  aws logs put-retention-policy --log-group-name "/aws/lambda/$lg" --retention-in-days 30 --region us-west-2
  echo "Set 30-day retention on /aws/lambda/$lg"
done
```

---

## 6.3 Dead Letter Queue (DLQ)

**Single shared DLQ:** `life-platform-ingestion-dlq` — currently has **5 messages sitting unprocessed.**

These are almost certainly from the Feb 28 P0 ingestion outage. Failed invocations from the 5 broken Lambdas would have been routed here.

**Concerns:**
- **No DLQ alarm for message age.** The existing alarm (`life-platform-ingestion-failures`) monitors `NumberOfMessagesSent`, which fires when new messages arrive. But there's no alarm for messages sitting unprocessed for extended periods.
- **No DLQ processing/drain mechanism.** Messages sit in the queue indefinitely. There's no Lambda or manual process to review and clear them.
- **5 stale messages create noise** — they'll sit there forever unless purged.

**Recommendations:**
1. **P1:** Purge the current 5 messages (they're from the resolved P0 outage):
   ```bash
   aws sqs purge-queue --queue-url https://sqs.us-west-2.amazonaws.com/205930651321/life-platform-ingestion-dlq --region us-west-2
   ```
2. **P2:** Add a message retention policy on the DLQ (14 days is standard) so stale messages auto-expire
3. **P3:** Consider a weekly DLQ drain check as part of the weekly digest or a manual weekly habit

---

## 6.4 SNS Alert Routing

**Single topic:** `life-platform-alerts` → email to `awsdev@mattsusername.com`.

This is fine for a single-operator platform. No findings.

**Optional enhancement:** If you ever want faster alerting, adding an SMS subscription to the SNS topic is trivial (~$0.01/alert). Not needed now.

---

## 6.5 Missing Observability Layers

Things that don't exist but could add value:

1. **No Lambda Insights or X-Ray tracing.** Not needed at current scale, but Lambda Insights ($0.30/Lambda/month) would give memory utilization and cold start metrics for the MCP server. Only worth considering for `life-platform-mcp` since it's the most complex function.

2. **No structured logging standard.** Some Lambdas use `print()`, some use `logging`. A consistent JSON log format would make CloudWatch Insights queries easier. Low priority but good hygiene for when you need to debug.

3. **No CloudWatch dashboard.** You have the S3 web dashboard for health data, but no AWS operations dashboard showing Lambda invocation counts, error rates, duration trends, and DDB consumed capacity at a glance. CloudWatch dashboards are free for up to 3 custom dashboards.

4. **No DynamoDB consumed capacity monitoring.** You're on on-demand (pay-per-request) pricing, so capacity isn't a concern — but monitoring consumed WCU/RCU would help forecast costs and detect anomalous query patterns (e.g., a runaway MCP tool doing full table scans).

---

## 6.6 Overall Observability Grade: B+

**Strengths:**
- Excellent alarm coverage (20/22 Lambdas)
- Consistent SNS routing
- Freshness checker provides application-level monitoring beyond just Lambda errors
- Anomaly detector adds a health-data-layer watchdog
- DLQ coverage on 20/22 Lambdas

**Gaps:**
- 9 log groups with no retention (hygiene)
- 2 Lambdas missing alarms
- 5 stale DLQ messages
- No duration or throttle alarms
- No meta-monitoring (freshness checker itself unmonitored)

**Top 3 recommendations (priority order):**
1. **Set 30-day retention on 9 log groups** (2 min script, prevents unbounded cost growth)
2. **Purge 5 stale DLQ messages + add alarms for freshness-checker and weather** (5 min total)
3. **Add duration alarm for daily-brief** (5 min, catches timeout issues before they cause missed briefs)
