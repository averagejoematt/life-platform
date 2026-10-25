# Cheapest AWS wins — log retention, custom metrics, secrets, crons (#5142)

> Measured read-only on 2026-10-24 (us-west-2 unless stated). No AWS write was made. Prices are
> us-west-2 list prices: custom metric $0.30/metric-month (first 10k), standard alarm $0.10/month,
> secret $0.40/secret-month, log storage $0.03/GB-month, dashboards $3 each beyond 3 free.

## 1. CloudWatch log groups — nothing to fix

- 125 groups in us-west-2, 65 MB stored in total (about $0.002/month of storage).
- Every group has a retention policy: 113 at 30 d, 5 at 90 d (security tier), 6 at 1 d (the CDK
  `LogRetention` helper functions), 1 at 14 d (a serverlessrepo power-tuning group). None is
  NEVER_EXPIRE; the other regions checked (us-east-1/2, us-west-1, eu-west-1, eu-central-1) also have none.
- The convention is `LOG_RETENTION_DEFAULT_DAYS = 30` / security 90 in `cdk/stacks/constants.py`, already
  derived per function and swept weekly by `deploy/sentinel_log_retention.py`. No CDK change is needed.
- Lowering retention would save nothing measurable. The CloudWatch cost lines are metrics and alarms.

## 2. Custom metrics and alarms

- 538 custom `LifePlatform*` series live (list-metrics, last two weeks); 136 alarms (about $13.60/month
  at $0.10); 3 dashboards (inside the free three).
- A crude reader check (alarm MetricStat + dashboard widget metrics, matching namespace + metric name)
  finds 374 series with no alarm or dashboard reader. Code readers (`get_metric_data` callers,
  composite/metric-math alarms) are not seen by this check, so these are CANDIDATES, not removals.
- Largest unread clusters: `LifePlatform/MCP` 124 series (ToolName dimension), `LifePlatform/AI` 114,
  AICanary 17, IngestLiveness 16, Canary 14, Coherence 12, DailyBrief 10, Traffic 9, Freshness 9.
- Upper bound at list price: 374 x $0.30 = $112/month. The real CloudWatch bill is about $13 in total,
  so realised savings are bounded by that; the first, safest cut is dropping the per-tool dimension on
  `LifePlatform/MCP` (124 series, up to $37 at list price).

## 3. Secrets Manager (28 secrets, about $11.20 at list; the bill reads about $7)

| Candidate | Evidence | Saving | Recommendation |
|---|---|---|---|
| `life-platform/progress-token-secret` | never accessed; no reader in the tree (SECRETS_MAP.md already lists it as an orphan) | $0.40 | delete, owner-attended |
| `life-platform/notion` | last accessed 2026-07-25 | $0.40 | confirm the notion ingestion is retired, then delete |
| `life-platform/github-billing` | never accessed by a Lambda; read only by `deploy/sentinel_quota.py` | $0 | keep (live tooling) |
| `hevy` + `hevy-write`, `eightsleep` + `eightsleep-client` | same vendor, two secrets | $0.80 | merge into one JSON secret each; touches IAM and runtime code |
| `ai-keys` + `site-api-ai-key` | both AI keys | $0.40 | merge; touches IAM and runtime code |
| HMAC/salt group: `ritual-token-secret`, `subscriber-token-secret`, `ip-hash-salt`, `progress-photos-signing` | all small signing secrets | $1.20 | merge only with a key-rotation plan; invalidates live tokens if done carelessly |

Maximum realistic saving about $3.60/month. Not worth the IAM churn except the two deletions ($0.80).

## 4. Cron consolidation (100 schedules, 81 distinct expressions)

EventBridge schedule rules cost $0; the only cost is Lambda invocations (negligible). Merging crons
therefore saves about $0/month directly and adds coupling; the value is fewer moving parts. Same-expression
sets (rows for #4287): daily-brief + journal-analyzer (0 10); alert-digest + site-stats-refresh 8am (0 15);
pip-audit + monday-compass (Mon 0 15); coach-prediction-evaluator + reading-recall-sweep + telegram outbound
(0 16); between-chronicle + coach-history-summarizer + episode-detect (Sun 0 17); ai-review-pack +
field-notes-generate + inter-coach-dialogue (Sun 0 18); coach-daily-reflection + daily-debrief + site-stats
12pm (0 19); evening-nudge + site-stats 8pm + telegram evening check-in (0 3); og-image-generator +
recap-card-generator (30 19); daily-insight-compute + freshness-checker (45 16); mcp-warmer + pipeline-health
(10 17); circadian-compliance + mcp-warmer predraft (0 2); chronicle-approve + hevy-restamp (0 18);
traffic-digest + story-questions (Mon 0 16).

## Savings summary

| Item | $/month | Basis |
|---|---|---|
| Log retention change | 0.00 | 65 MB stored, all groups already 30/90 d |
| Drop unread custom metrics (upper bound) | up to 112 (bill-capped, about $13 total) | 374 x $0.30 |
| First cut: MCP per-tool dimension | up to 37 | 124 x $0.30 |
| Delete 2 orphan/retired secrets | 0.80 | 2 x $0.40 |
| Merge vendor/key secrets | up to 2.80 | IAM + code change |
| Cron consolidation | about 0 | schedule rules are free |
