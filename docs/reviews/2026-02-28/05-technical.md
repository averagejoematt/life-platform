# Phase 5: Technical Review — Bugs, Changes, Opportunities
**Date:** 2026-02-28 | **Version:** v2.47.1 | **Reviewer:** Claude (Expert Panel)

---

## 5.1 Code Quality

**Grade: A-** — The codebase is well-structured, consistently formatted, and appropriately parameterized. The MCP modular split into 21 files is clean. The main area for improvement is the daily brief Lambda's size.

---

## 5.2 Bugs & Issues Found

#### F5.1 — MCP config.py version is stale: "2.45.0" vs actual "2.47.1" (BUG)
`mcp/config.py` has `__version__ = "2.45.0"` but the platform is at v2.47.1. This version string is returned in the MCP `initialize` response and visible to Claude clients.

**Fix:** Update to `"2.47.1"`. Add to the deploy checklist: "bump __version__ in mcp/config.py."

#### F5.2 — SOURCES list in config.py is incomplete (BUG)
`mcp/config.py` defines `SOURCES` as a list of 15 sources, but the platform has 19+ active sources. Missing: `supplements`, `weather`, `travel`, `state_of_mind`, `macrofactor_workouts`. Also missing derived partitions: `day_grade`, `habit_scores`, `anomalies`, `insights`, `experiments`.

**Impact:** Any tool that iterates `SOURCES` for cross-source queries won't include newer sources. The `get_daily_summary` and `get_aggregated_summary` tools likely use this list.

**Fix:** Update `SOURCES` to include all active sources. Consider splitting into `DATA_SOURCES` (ingested) and `DERIVED_SOURCES` (computed) for clarity.

#### F5.3 — _DEFAULT_SOURCE_OF_TRUTH missing domains (BUG)
The config lists 15 SOT domains but the profile has 20 (missing: `caffeine`, `supplements`, `weather`, `state_of_mind`, `water`). The config falls back to profile-stored values, so this works at runtime, but the code doesn't match the documentation.

**Fix:** Sync `_DEFAULT_SOURCE_OF_TRUTH` in config.py with the profile's full 20-domain list.

---

## 5.3 Lambda Configuration Issues

#### F5.4 — Timeout over-provisioning on 5 Lambdas (LOW)
Based on the Lambda list-functions data:

| Lambda | Current Timeout | Recommended | Rationale |
|--------|-----------------|-------------|-----------|
| `todoist-data-ingestion` | 300s | 30s | Simple API call |
| `strava-data-ingestion` | 300s | 120s | Gap-fill may need 7 API calls |
| `activity-enrichment` | 300s | 180s | Multiple Haiku calls |
| `journal-enrichment` | 300s | 120s | Haiku calls, multiple entries |
| `macrofactor-data-ingestion` | 300s | 60s | CSV parse, no external calls |

No cost impact (Lambda bills per ms, not per timeout), but right-sizing prevents hung-invocation masking.

#### F5.5 — Memory under-provisioning on journal-enrichment (LOW)
Journal enrichment Lambda is at 128 MB. It makes Haiku API calls and processes multiple journal entries. If a day has many entries, the Lambda could hit memory limits. All other Haiku-calling Lambdas are at 256 MB.

**Recommendation:** Bump to 256 MB for consistency: 
```bash
aws lambda update-function-configuration --function-name journal-enrichment --memory-size 256 --region us-west-2
```

#### F5.6 — Daily brief timeout is tight at 210s (INFO)
The daily brief makes 4 Haiku API calls, reads from 15+ DynamoDB partitions, and writes to 3 DynamoDB partitions + S3. If Haiku has high latency (>15s per call), the brief could approach the 210s limit.

**Recommendation:** Increase to 300s for safety margin. The brief is the most critical Lambda — a timeout means no daily email.

---

## 5.4 Technical Opportunities

#### F5.7 — Powertools for AWS Lambda (OPPORTUNITY)
AWS Lambda Powertools for Python provides structured logging, metrics, tracing, and error handling out of the box. Adding it to the daily brief and MCP Lambdas would give you:
- Structured JSON logs (easier to query in CloudWatch Insights)
- Automatic X-Ray tracing (see which DynamoDB calls are slow)
- Built-in correlation IDs

**Effort:** Medium. Would need to be added as a Lambda layer. The MCP Lambda's 1024 MB allocation has room.

**Recommendation:** Nice-to-have, not urgent. If you ever debug a slow MCP tool call, the tracing would be invaluable.

#### F5.8 — Daily brief should catch and continue on section failures (MEDIUM)
If section 5 (Nutrition) throws an exception, the entire brief fails. Each section should be wrapped in try/except with graceful degradation:

```python
try:
    html += render_nutrition_section(data)
except Exception as e:
    logger.error(f"Nutrition section failed: {e}")
    html += '<div class="section-error">Nutrition data unavailable today</div>'
```

This is the single highest-ROI code change. A brief with 17/18 sections is better than no brief at all.

#### F5.9 — MCP tool error responses are inconsistent (LOW)
Some tools return `{"error": "message"}` on failure, others raise exceptions that get caught by the handler and returned as JSON-RPC errors. A consistent pattern would improve the Claude experience.

**Recommendation:** Standardize on returning `{"error": "...", "error_code": "...", "suggestions": [...]}` from tools, so Claude can offer helpful recovery suggestions.

#### F5.10 — No structured error logging across Lambdas (LOW)
Errors are logged as unstructured text (`logger.error(f"...")`). CloudWatch Logs Insights queries would be more powerful with structured JSON logging:
```python
logger.error(json.dumps({"event": "ingestion_failed", "source": "whoop", "error": str(e)}))
```

This would enable queries like: "show me all ingestion failures in the last 7 days grouped by source."

#### F5.11 — Garmin Lambda code size is 5.4 MB (INFO)
The Garmin Lambda has a 5.4 MB code package (vs <35 KB for all others) due to bundled `garth` and `garminconnect` dependencies with native binaries. This is fine but means longer cold starts.

**No action needed** — just noting this as the outlier in the fleet.

---

## 5.5 Runtime & Dependency Health

**Grade: A** — All 22 Lambdas run Python 3.12. No deprecated runtimes. No external dependencies except Garmin (garth + garminconnect). The stdlib-only approach is excellent for security and maintainability.

---

## 5.6 Summary

| Area | Grade | Critical Findings | Action Items |
|------|-------|-------------------|-------------|
| Code Quality | A- | Daily brief monolith | Section-level try/except |
| Bugs | B+ | Version stale, SOURCES incomplete, SOT missing | **Fix config.py (15 min)** |
| Lambda Config | B+ | Timeout/memory mismatches | Right-size 5 Lambdas |
| Opportunities | — | Powertools, structured logging | Nice-to-have |

**Top 3 recommendations (priority order):**
1. **Fix mcp/config.py** — update `__version__`, `SOURCES`, and `_DEFAULT_SOURCE_OF_TRUTH` (15 min, fixes 3 bugs)
2. **Add section-level try/except to daily brief** (30 min, prevents total brief failures)
3. **Increase daily-brief timeout to 300s** (1 min CLI command, safety margin)
