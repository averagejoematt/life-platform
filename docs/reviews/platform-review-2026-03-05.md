# Platform Health Review — 2026-03-05

**Snapshot:** audit/2026-03-05.json (first snapshot)  
**Platform version:** v2.74.0  
**Review type:** Full health check — infrastructure, security, code quality, cost, monolith assessment

---

## Overall Health: 🟡 AMBER

Platform is fundamentally sound and cost-efficient. Two active issues (Chronicle alarm + DLQ backlog) need same-day attention. The bigger story is accumulated technical debt across five areas: a 4,000-line monolith, a stale MCP config version, a hardcoded table name in weekly digest, incomplete snapshot coverage, and 10 log groups without retention. None are fires, but several will become problems at scale.

---

## Summary

| Category | Status | Finding count |
|---|---|---|
| Active incidents | 🔴 | 2 (alarm in ALARM, DLQ messages) |
| Infrastructure | 🟡 | 5 missing alarms, 10 missing log retention |
| Security | 🟢 | Clean — all values parameterised except one |
| Code quality | 🟡 | 1 serious monolith, 1 hardcoded value |
| Configuration drift | 🔴 | MCP config version 24 minor versions behind |
| Cost | 🟢 | $8.57 projected — well under $20 budget |
| Docs freshness | 🟡 | 4 docs stale (7–13 versions behind) |
| Snapshot tooling | 🟡 | DDB source discovery incomplete, EventBridge coverage incomplete |

---

## P0 — Fix Today

### 1. `wednesday-chronicle` alarm is firing 🚨
The `wednesday-chronicle-errors` CloudWatch alarm is in ALARM state. This means the Wednesday Chronicle Lambda has thrown errors. With it scheduled Wednesday 7:00 AM PT, check whether today's (or last Wednesday's) Chronicle ran successfully.

**Action:** Check CloudWatch logs for `wednesday-chronicle`, identify the error, fix it.
```bash
aws logs describe-log-streams \
  --log-group-name /aws/lambda/wednesday-chronicle \
  --order-by LastEventTime --descending \
  --region us-west-2 --query 'logStreams[0].logStreamName' --output text
```

### 2. DLQ has 5 unprocessed messages
The `life-platform-ingestion-dlq` has 5 messages sitting unprocessed. These are failed Lambda invocations that were never retried successfully — meaning some data was silently not ingested.

**Action:** Inspect DLQ messages to identify which Lambda(s) failed and on which dates:
```bash
aws sqs receive-message \
  --queue-url https://sqs.us-west-2.amazonaws.com/205930651321/life-platform-ingestion-dlq \
  --max-number-of-messages 10 \
  --region us-west-2
```
Once identified, manually re-invoke the failed Lambda(s) with a backfill payload.

---

## P1 — This Week

### 3. MCP `config.py` version is 24 minor versions behind
`config.py` declares `__version__ = "2.50.0"` but the platform is at v2.74.0. This version is used in the MCP server's `initialize` response (`serverInfo.version`). Not a runtime bug, but misleading for debugging and violates the documentation hygiene principle.

**Action:** Update `__version__` in `mcp/config.py` to `"2.74.0"` and redeploy MCP Lambda.

### 4. `weekly_digest_lambda.py` has a hardcoded table name
Line 47: `table = dynamodb.Table("life-platform")` — not reading from `os.environ`. Every other Lambda correctly uses `os.environ.get("TABLE_NAME", "life-platform")`. This is inconsistent and will break silently if the table name ever changes.

**Action:**
```python
# Replace line 47:
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
table = dynamodb.Table(TABLE_NAME)
```

### 5. 5 Lambdas missing CloudWatch error alarms
These Lambdas run critical paths but have no error alarm:

| Lambda | What it does | Risk if it fails silently |
|---|---|---|
| `adaptive-mode-compute` | Sets Daily Brief tone mode | Brief falls back to standard — no alert |
| `character-sheet-compute` | Computes Character Sheet | Brief shows stale/no character data |
| `dashboard-refresh` | Updates S3 dashboard 2x/day | Dashboard goes stale |
| `life-platform-data-export` | Monthly data backup | Loss of backup with no notification |
| `weekly-plate` | Friday food email | Email silently skipped |

**Action:** Add a standard error alarm for each (same pattern as existing alarms — threshold=1, period=86400s, SNS action to `life-platform-alerts`).

### 6. 10 log groups missing retention policy
Logs accumulate indefinitely at no immediate cost (Lambda free tier) but will eventually grow and could complicate debugging (too much noise). The 10 affected groups include all recently-deployed Lambdas:

`adaptive-mode-compute`, `character-sheet-compute`, `dashboard-refresh`, `life-platform-data-export`, `life-platform-key-rotator`, `nutrition-review`, `wednesday-chronicle`, `weekly-plate`, `us-east-1.life-platform-buddy-auth`, `us-east-1.life-platform-cf-auth`

**Action:** Set 30-day retention on all 10 (matches existing pattern):
```bash
for lg in \
  /aws/lambda/adaptive-mode-compute \
  /aws/lambda/character-sheet-compute \
  /aws/lambda/dashboard-refresh \
  /aws/lambda/life-platform-data-export \
  /aws/lambda/life-platform-key-rotator \
  /aws/lambda/nutrition-review \
  /aws/lambda/wednesday-chronicle \
  /aws/lambda/weekly-plate; do
  aws logs put-retention-policy \
    --log-group-name "$lg" \
    --retention-in-days 30 \
    --region us-west-2
done
# CloudFront auth functions are in us-east-1
for lg in \
  "/aws/lambda/us-east-1.life-platform-buddy-auth" \
  "/aws/lambda/us-east-1.life-platform-cf-auth"; do
  aws logs put-retention-policy \
    --log-group-name "$lg" \
    --retention-in-days 30 \
    --region us-east-1
done
```

### 7. Secrets Manager: 12 secrets at ~$4.80/mo base cost
At $0.40/secret/month, 12 secrets cost $4.80/month in base fees alone — 24% of the $20 budget, before API call charges. The MCP server reads the API key on a 5-minute TTL cache, meaning ~8,700 Secrets Manager API calls/month (another ~$0.04/month, negligible).

**Consolidation opportunity:** Several per-service API secrets (withings, todoist, strava, etc.) could be combined into a single `life-platform/api-keys` JSON secret containing all non-rotating values. Rotating secrets (whoop, the MCP key) stay separate. Could reduce from 12 to ~5–6 secrets, saving ~$2.40/month.

**Action:** Decide on consolidation. If yes, create merged secret + update affected Lambdas in one session.

---

## P2 — Backlog

### 8. `daily_brief_lambda.py` is a 4,002-line monolith
61 functions in one file covering 8 distinct concerns. This is the single biggest code quality risk — hard to test, easy to introduce regressions, and slow to reason about during debugging.

**Breakdown analysis:**

| Logical module | Key functions | ~Lines |
|---|---|---|
| `scoring_engine.py` | `score_sleep`, `score_recovery`, `score_nutrition`, `score_movement`, `score_habits_registry`, `score_hydration`, `score_journal`, `score_glucose`, `compute_day_grade`, `letter_grade` | ~400 |
| `ai_calls.py` | `call_anthropic`, `call_board_of_directors`, `call_training_nutrition_coach`, `call_journal_coach`, `call_tldr_and_guidance` | ~350 |
| `html_builder.py` | `build_html` (single ~900 line function) | ~1,000 |
| `data_writers.py` | `write_dashboard_json`, `write_buddy_json`, `write_clinical_json` | ~800 |
| `data_fetchers.py` | `gather_daily_data`, `fetch_date`, `fetch_range`, `fetch_journal_entries`, `fetch_anomaly_record` | ~250 |
| `character_hooks.py` | `_evaluate_rewards_brief`, `_get_protocol_recs_brief`, `_build_avatar_data` | ~200 |
| `lambda_handler.py` | `lambda_handler`, `_regrade_handler` | ~200 |

The `build_html` function alone is estimated at ~900 lines. `write_buddy_json` and `write_dashboard_json` partially duplicate data assembly logic already in MCP tools — a violation of the compute→store→read principle.

**Recommended extraction order:**
1. `scoring_engine.py` — most testable, already referenced by character sheet Lambda
2. `ai_calls.py` — clean interface, would benefit from shared retry logic
3. `data_writers.py` — dashboard/buddy JSON writers are good candidates for their own Lambda

### 9. `build_html` single-function design
Estimated ~900 lines in a single function with no sub-functions. Should be broken into section-building helpers (`_section_readiness()`, `_section_nutrition()`, etc.) that `build_html` calls sequentially. Low operational risk but a debugging hazard.

### 10. `apple-health-ingestion` timeout is 600s
All other Lambdas are ≤300s. The 600s timeout is technically fine (max is 900s) but doubles worst-case wait during debugging and indicates the function may be doing too much per invocation.

### 11. Stale documentation
Four docs are meaningfully behind the current version:

| Doc | Version detected | Platform version | Gap |
|---|---|---|---|
| `USER_GUIDE.md` | v2.66.1 | v2.74.0 | 8 versions |
| `COST_TRACKER.md` | v2.63.0 | v2.74.0 | 11 versions |
| `INCIDENT_LOG.md` | v2.61.0 | v2.74.0 | 13 versions |
| `INFRASTRUCTURE.md` | v2.67.0 | v2.74.0 | 7 versions |

### 12. Snapshot tooling gaps

**DDB source discovery is incomplete.** Found only 8 of the expected ~25 sources. The scan uses `Limit=500` against 15,420 items — sees only the first page. Fix: paginate using `LastEvaluatedKey`.

**EventBridge capture is incomplete.** The keyword list for target-based discovery misses: `wednesday-chronicle`, `weekly-plate`, `adaptive-mode-compute`, `character-sheet-compute`, `nutrition-review`, `dashboard-refresh`. These rules exist but aren't captured. Fix: expand the keyword list in `audit/platform_snapshot.py`.

### 13. Two bare `except: pass` blocks in daily_brief
Lines 339 and 2878. Confirm these are intentional silent failures, not accidentally swallowed errors.

### 14. Duplicate `dedup_activities` function in daily_brief
`dedup_activities` (line 792) and `_dedup_activities` (line 3460) appear to be the same function. Should be consolidated.

---

## Infrastructure Metrics

| Metric | Value | Assessment |
|---|---|---|
| Lambdas | 30 | ✅ All python3.12 |
| Alarms | 30 | 🟡 5 Lambdas unmonitored |
| Alarms in ALARM | 1 | 🔴 wednesday-chronicle |
| Log groups missing retention | 10 | 🟡 |
| DLQ messages | 5 | 🔴 Unprocessed failures |
| DDB items | 15,420 | ✅ |
| DDB sources discovered (snapshot) | 8 / ~25 | 🟡 Snapshot tooling gap |
| EventBridge rules captured | 21 / ~29 | 🟡 Snapshot tooling gap |
| All captured rules ENABLED | ✅ | All 21 enabled |

---

## Cost

| Service | MTD | Projected full month | Notes |
|---|---|---|---|
| Secrets Manager | $0.72 | ~$4.47 | 12 secrets × $0.40/mo base |
| Route 53 | $0.50 | ~$0.50 | Flat monthly hosted zone fee |
| DynamoDB | $0.01 | ~$0.07 | On-demand, very low |
| S3 | $0.01 | ~$0.06 | Dropped from $0.13 last month |
| CloudFront | $0.01 | ~$0.04 | Free tier mostly |
| Tax | $0.13 | ~$0.29 | |
| **Total** | **$1.38** | **~$5.43** | **27% of $20 budget** |

Last month actual: $1.92. **Budget status: healthy.**

Note: Route 53 and Secrets Manager are billed at month start, so the $8.57 simple linear extrapolation overstates — realistic full-month projection is ~$5.43.

Secrets Manager is 52% of MTD cost. Consolidating from 12 to 6 secrets saves ~$2.40/month and is the highest-ROI infrastructure improvement currently available.

---

## Security Assessment

| Check | Status |
|---|---|
| No hardcoded account IDs | ✅ |
| No hardcoded ARNs | ✅ |
| All credentials from Secrets Manager | ✅ (except weekly_digest table name) |
| All env vars use `os.environ.get()` | ✅ (except weekly_digest) |
| MCP Bearer token + HMAC validation | ✅ |
| Dashboard + buddy Lambda@Edge auth | ✅ |
| DynamoDB PITR enabled | ✅ |
| All Lambdas on python3.12 | ✅ |

---

## Prioritised Action List

| Priority | Action | Effort |
|---|---|---|
| P0 | Investigate + fix wednesday-chronicle Lambda error | 30 min |
| P0 | Inspect DLQ, identify failed ingestions, re-invoke | 30 min |
| P1 | Fix `config.py` version string → `2.74.0`, redeploy MCP | 10 min |
| P1 | Fix hardcoded table name in `weekly_digest_lambda.py` line 47 | 10 min |
| P1 | Set 30-day retention on 10 log groups (bash loop above) | 15 min |
| P1 | Add error alarms for 5 unmonitored Lambdas | 30 min |
| P1 | Evaluate + implement Secrets Manager consolidation | 1 hr |
| P2 | Fix snapshot script: paginate DDB + expand EB keyword list | 1 hr |
| P2 | Update stale docs (USER_GUIDE, COST_TRACKER, INCIDENT_LOG, INFRASTRUCTURE) | 1 hr |
| P2 | Audit 2 bare `except: pass` blocks in daily_brief (lines 339, 2878) | 15 min |
| P2 | Deduplicate `dedup_activities`/`_dedup_activities` in daily_brief | 15 min |
| Future | Plan + execute daily_brief monolith breakdown (scoring_engine first) | Multi-session |

---

## Board Notes

The platform is healthy and cheap. Two patterns worth watching: Secrets Manager is now the dominant cost driver — secret consolidation is the single highest-ROI infrastructure improvement available, saving ~$2.40/month and reducing the 52% cost concentration. And the daily brief Lambda has crossed 4,000 lines; the next time a scoring bug appears will be the right moment to extract `scoring_engine.py` rather than debug inside the monolith.
