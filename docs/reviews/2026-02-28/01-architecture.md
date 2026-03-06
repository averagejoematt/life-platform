# Phase 1: Architecture Review
**Date:** 2026-02-28 | **Version:** v2.47.1 | **Reviewer:** Claude (Expert Panel)

---

## 1.1 Overall Architecture Assessment

**Grade: A-** — Exceptionally well-designed for a personal platform. The three-layer architecture (Ingest → Store → Serve) is clean, the single-table DynamoDB design is appropriate for the access patterns, and the separation of concerns across 22 Lambdas is solid. The areas below are refinements, not structural problems.

### Strengths
- **Single-table DynamoDB** with composite keys is the right pattern. No GSI needed because all access is user+source+date. This keeps costs minimal and queries predictable.
- **Source-of-truth domain architecture** prevents double-counting — this is a design decision most personal health platforms get wrong.
- **Gap-aware backfill (LOOKBACK_DAYS=7)** is elegant self-healing. No sync markers, no state to manage, just idempotent checks against what exists.
- **EventBridge scheduling with staggered cron** prevents thundering herd and respects upstream API rate limits.
- **MCP server as both API server and cache warmer** is efficient — avoids a separate Lambda for warming.

### Findings

#### F1.1 — Daily Brief is a 3,011-line monolith (MEDIUM)
The daily brief Lambda at 3,011 lines with 4 AI calls, 18 sections, and DynamoDB writes for day_grade + habit_scores + dashboard JSON is the single biggest risk surface. Any bug in one section can break the entire brief. The 210s timeout is already generous.

**Recommendation:** Consider extracting the day_grade computation and habit_scores computation into a separate "daily-compute" Lambda that runs at 9:50 AM. The brief Lambda then reads the pre-computed results. This decouples compute from email rendering and makes each piece independently testable. Not urgent — the current design works — but this is the most fragile Lambda in the fleet.

#### F1.2 — Todoist timeout is excessive (LOW)
Todoist Lambda has a 300s timeout but it's a simple API call that should complete in <5s. Similarly, Strava and Activity Enrichment are at 300s. These won't cost money (Lambda bills per 1ms), but inflated timeouts mask hung invocations.

**Recommendation:** Right-size timeouts based on observed p99 durations. Suggested: Todoist 30s, Strava 60s (gap-fill may need multiple API calls), Activity Enrichment 120s (Haiku calls). Check CloudWatch duration metrics before changing.

#### F1.3 — No circuit breaker for upstream API failures (LOW)
If an upstream API (e.g., Whoop) is down for maintenance, the Lambda will fail, retry (DLQ after 2 retries), and alarm. Gap-fill will recover the data next day. This is actually fine for a personal platform — the gap-fill pattern IS the circuit breaker. No action needed, just documenting that this is by design.

#### F1.4 — CloudFront → S3 static site architecture is clean (POSITIVE)
The dashboard architecture (CloudFront + S3 OriginPath + ACM cert + custom domain) is well-implemented. The daily brief writing `data.json` as a side effect is a good pattern — no separate Lambda needed.

#### F1.5 — Webhook Lambda handles too many concerns (LOW)
`health-auto-export-webhook` handles health metrics, CGM readings, blood pressure, AND State of Mind — four distinct data types with different storage paths (DynamoDB aggregates + S3 individual readings). It works because the payload detection is clean, but a bug in State of Mind processing could theoretically block health metric ingestion.

**Recommendation:** No action needed at current scale. If you add more Health Auto Export data types, consider splitting into separate handlers behind API Gateway routes.

#### F1.6 — DST cron drift risk (INFO)
All EventBridge crons use fixed UTC. The architecture doc notes PT times shift by 1 hour when DST changes. The 9:30 AM Whoop recovery refresh is the most sensitive — it needs to run AFTER waking up. Spring forward (Mar 8, 2026) means this fires at 10:30 AM PT instead of 9:30 AM.

**Recommendation:** You have `deploy/deploy_dst_spring_2026.sh` already. Ensure it's in your calendar for Mar 8. Consider a recurring calendar event for both DST transitions.

---

## 1.2 Data Flow Architecture

**Grade: A** — The ingest pipelines are well-separated, idempotent, and self-healing.

- ✅ Each source has its own Lambda and IAM role — blast radius is contained
- ✅ S3 raw backup on every ingestion — audit trail + replay capability  
- ✅ DynamoDB `update_item` for webhook data — merges without overwrites
- ✅ Dropbox poll + S3 trigger + scheduled Lambda for MacroFactor — triple redundancy
- ✅ OAuth token self-healing on each invocation — no separate token refresh job needed

No findings in this section.

---

## 1.3 Serve Layer Architecture

**Grade: A-**

- ✅ MCP server modularized into 21 modules — good for cold start and maintainability
- ✅ 12-tool cache warmer reduces latency for common queries
- ✅ Function URL for remote MCP access — enables claude.ai and mobile
- ✅ RAW_DAY_LIMIT=90 auto-aggregation prevents payload bloat

#### F1.7 — MCP Lambda memory may be over-provisioned (LOW)
1024 MB was set in v2.33.0 for "2x CPU allocation." This is valid for compute-heavy tools, but most tools are simple DynamoDB queries. The cache warmer is the heaviest workload at ~7s.

**Recommendation:** Run AWS Lambda Power Tuning (open-source tool) to find the optimal memory/cost tradeoff. The 1024 MB may be correct, but 512 MB with slightly longer durations could save ~$0.50/month on the ~1440 Dropbox poll invocations that hit this Lambda. Low priority.

#### F1.8 — No request-level timeout on MCP tools (INFO)
Individual MCP tool executions don't have internal timeouts. A slow DynamoDB query on a 365-day range could consume the full 300s Lambda timeout. The RAW_DAY_LIMIT=90 mitigates this for date-range tools, but correlation tools that scan 180 days of data from multiple sources could be slow.

**Recommendation:** Consider adding a per-tool soft timeout (e.g., 30s) that returns a "query too broad, narrow your date range" message rather than timing out the entire Lambda.

---

## 1.4 Summary

| Area | Grade | Critical Findings | Action Items |
|------|-------|-------------------|-------------|
| Overall Architecture | A- | Daily brief monolith risk | Monitor, consider splitting compute in future |
| Data Flow | A | None | None |
| Serve Layer | A- | Memory sizing, no per-tool timeout | Power Tuning, soft timeouts |
| Infrastructure | A | DST cron management | Calendar reminders |

**Top 3 recommendations:**
1. Right-size Lambda timeouts based on observed durations (quick win, no cost)
2. Consider splitting daily brief compute from email rendering (medium effort, reduces blast radius)
3. Add per-tool soft timeout in MCP server (low effort, improves reliability)
