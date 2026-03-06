# Phase 4: Costing Review
**Date:** 2026-02-28 | **Version:** v2.47.1 | **Reviewer:** Claude (Expert Panel)

---

## 4.1 February 2026 Actual Cost (MTD)

| Service | Feb Cost | Notes |
|---------|----------|-------|
| AWS Secrets Manager | $0.83 | 12 secrets (prorated — many created mid-Feb) |
| Route 53 | $0.50 | Hosted zone ($0.50/mo) — fixed cost |
| S3 | $0.12 | ~2.3 GB stored + requests |
| DynamoDB | $0.05 | 15K items, on-demand reads/writes |
| Cost Explorer | $0.04 | API calls (including this review!) |
| CloudWatch | $0.00 | Within free tier |
| Lambda | $0.00 | Within free tier |
| API Gateway | $0.00 | Within free tier |
| CloudFront | $0.00 | Within free tier |
| SES | $0.00 | Within free tier |
| Tax | $0.14 | WA state |
| **TOTAL** | **$1.68** | |

**January 2026:** $0.00 (platform built primarily in Feb)

---

## 4.2 Projected Steady-State Monthly Cost

The Feb number is artificially low because most resources were created mid-month. Here's the projected full-month steady state:

| Service | Projected Monthly | Calculation |
|---------|-------------------|-------------|
| **Secrets Manager** | **$4.80** | 12 secrets × $0.40/mo |
| Route 53 | $0.50 | 1 hosted zone |
| S3 | $0.15 | Storage + requests (growing slowly) |
| DynamoDB | $0.10 | On-demand, ~900 writes/day + reads |
| CloudWatch | $0.00–0.50 | Depends on log retention (see F4.2) |
| Lambda | $0.00–0.10 | Free tier covers ~1M invocations |
| Cost Explorer | $0.04 | $0.01 per API call |
| CloudTrail | $0.00 | First trail is free |
| CloudFront | $0.00 | Free tier covers 1TB/mo |
| API Gateway | $0.00 | Free tier covers 1M calls |
| SES | $0.00 | Free tier for Lambda-originated email |
| SQS (DLQ) | $0.00 | Free tier |
| SNS | $0.00 | Free tier |
| Tax (~10%) | $0.60 | WA state sales tax |
| **TOTAL** | **$6.19–$6.69** | |

**Grade: A+** — This is an extraordinarily cost-efficient platform. 22 Lambdas, 19 data sources, 97 MCP tools, daily/weekly/monthly emails, a web dashboard, and a remote MCP server — all for ~$6/month. The $20/month budget has massive headroom.

---

## 4.3 Cost Driver Analysis

### #1: Secrets Manager ($4.80/mo = 72% of projected cost)
This is the dominant cost line. At $0.40/secret/month, each secret costs more than all of Lambda, DynamoDB, S3, and API Gateway combined.

#### F4.1 — Secrets Manager cost optimization opportunity (MEDIUM)
**Options:**
1. **Consolidate secrets** — Combine static API keys (Todoist, Habitify, Notion, Health Auto Export, MCP API key) into a single secret as a JSON blob. This could reduce from 12 → 7 secrets, saving $2.00/mo.
   - Keep separate: OAuth secrets (Whoop, Withings, Strava, Garmin, Dropbox, Eight Sleep) — these need per-Lambda write-back
   - Consolidate: `life-platform/static-api-keys` → `{"todoist": "...", "habitify": "...", "notion": "...", "health_auto_export": "...", "mcp_api_key": "..."}`
   - Savings: 5 fewer secrets = $2.00/mo
   - Effort: Medium — update 5 Lambdas to parse JSON
   
2. **SSM Parameter Store** — Move static API keys to SSM SecureString parameters ($0/mo for standard, $0.05/10K API calls for advanced). OAuth secrets stay in Secrets Manager (they need the built-in rotation support even if you don't use auto-rotation).
   - Savings: Up to $2.00/mo
   - Effort: Medium — change from `secretsmanager.get_secret_value()` to `ssm.get_parameter(WithDecryption=True)`

3. **Do nothing** — $4.80/mo is still trivial. The simplicity of one-secret-per-Lambda is worth the cost.

**Recommendation:** Option 3 (do nothing) is fine. If you want to optimize, Option 1 (consolidation) is the cleanest.

### #2: Route 53 ($0.50/mo = 8%)
Fixed cost for the hosted zone. No optimization possible unless you move DNS elsewhere.

### #3: S3 ($0.15/mo = 2%)
Raw data archives are the main storage. At ~2.3 GB and growing by maybe 50 MB/month, this stays trivial.

### #4: Everything else (~$0.20/mo combined)
Lambda, DynamoDB, CloudWatch, API Gateway, SES — all within or near free tier. Extraordinary efficiency.

---

## 4.4 Cost Risk Factors

#### F4.2 — CloudWatch log retention may cause cost growth (MEDIUM)
The architecture doc mentions "30-day retention" but the previous review attempt (from your screenshot) noted that "several log groups don't have retention set (null = infinite)." Infinite retention means logs accumulate forever. At 22 Lambdas generating logs daily, this could grow to several GB within a year.

**CloudWatch Logs pricing:** $0.50/GB ingested, $0.03/GB/month stored. Current impact is minimal but will grow linearly.

**Recommendation:** Set 30-day retention on ALL log groups:
```bash
for lg in $(aws logs describe-log-groups --query "logGroups[?retentionInDays==null].logGroupName" --output text --region us-west-2); do
    aws logs put-retention-policy --log-group-name "$lg" --retention-in-days 30 --region us-west-2
    echo "Set 30d retention on $lg"
done
```
This is a quick win — prevents cost growth with zero downside. **Do this.**

#### F4.3 — MCP Lambda concurrency cost risk (LOW with F3.4 mitigation)
Without reserved concurrency, a bot or accidental retry loop hitting the Function URL could cause thousands of Lambda invocations. At 1024 MB and 300s max timeout, a worst case is ~$0.005 per invocation × 10,000 = $50. Setting reserved concurrency to 10 (recommended in Phase 3) caps this.

#### F4.4 — Dropbox poll invocation volume (INFO)
Dropbox poll runs every 30 minutes = ~1,440 invocations/month. This is the highest-volume Lambda but at 128 MB and <1s execution, it costs approximately $0.00 within free tier. If free tier expires (after 12 months), this would add ~$0.03/month. Negligible.

---

## 4.5 Budget Forecast

| Timeframe | Projected Cost | vs $20 Budget |
|-----------|---------------|---------------|
| Mar 2026 (first full month) | $6.50 | 33% utilized |
| Jun 2026 (steady state) | $7.00 | 35% utilized |
| Dec 2026 (12-month) | $7.50 | 38% utilized |
| With Google Calendar + Monarch Money | +$0.50 | ~$8.00 (40%) |
| With WAF (if added) | +$5.00 | ~$13.00 (65%) |

**Verdict:** The $20/month budget is generous. You can add 2-3 more data sources, double the MCP tool count, and add new email digests without meaningfully impacting cost. The only feature that would significantly move the needle is WAF ($5/mo), which is why reserved concurrency is the recommended alternative.

---

## 4.6 Summary

| Area | Grade | Finding | Action |
|------|-------|---------|--------|
| Overall Cost | A+ | $6.50/mo projected | Well under $20 budget |
| Cost Optimization | B+ | Secrets Manager is 72% of cost | Consolidate if desired |
| Cost Risk | B+ | Log retention, concurrency | **Set log retention (quick win)** |
| Budget Headroom | A+ | 65% headroom remaining | Room for many more features |

**Top 3 recommendations (priority order):**
1. **Set 30-day retention on all CloudWatch log groups** (5 min, prevents cost growth)
2. **Set reserved concurrency on MCP Lambda** (also in Phase 3 — dual benefit: security + cost)
3. Consider Secrets Manager consolidation if you want to save $2/mo (optional, low priority)
