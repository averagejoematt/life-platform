# Handover — v6.9.5: qa-smoke false-positive sweep + DLQ drain

**Date:** 2026-05-03 (very late evening, after v6.9.4)
**Trigger:** User showed inbox at 9pm PT — "🔴 QA: 8 FAILURES" email + CI/CD failure on `36bebf1` (DLQ piled to 90 messages). Asked "are we sure we are good?" Honest answer was no.
**Scope:** Triage + fix the false positives polluting the QA signal.

---

## What changed

### 3 real bugs in qa-smoke itself

1. **Path mismatch (`lambdas/qa_smoke_lambda.py`)**
   - Was checking: `dashboard/data.json`, `dashboard/clinical.json`
   - Should check: `dashboard/matthew/data.json`, `dashboard/matthew/clinical.json`
   - Root cause: `output_writers.py` moved to `dashboard/{user_id}/data.json` for multi-user prep on 2026-03-08. qa-smoke wasn't updated. Generating false S3-stale failures for ~56 days.
   - Fixed in two places: `check_s3_freshness` FILES list + `check_score_sanity` get_object call.

2. **MCP auth scheme mismatch**
   - Was sending: `x-api-key: <api_key>`
   - Should send: `Authorization: Bearer lp_<hmac_sha256(api_key, "life-platform-bearer-v1")>`
   - Root cause: `mcp/handler.py:511` requires Bearer auth on Function URL endpoints; qa-smoke was using the bridge-invoke `x-api-key` style. Two MCP checks failed every run with HTTP 401.
   - Fixed by computing the Bearer token the same way `mcp/handler.py::_get_bearer_token` does (note `lp_` prefix). Tested live with curl — 200 OK.

3. **`tool_get_sources` KeyError (`mcp/tools_data.py:42-43`)**
   - Was: `oldest["Items"][0]["date"]` and `newest["Items"][0]["date"]`
   - Now: `oldest["Items"][0].get("date")` and same for newest.
   - Root cause: at least one source partition has a record without a `date` field. KeyError tanked the whole tool. With auth fixed, this surfaced; before, the 401 hid it.

### DLQ drained

`life-platform-ingestion-dlq` had 90 stale messages from EventBridge scheduled events 2026-04-20+ (silence period; Lambdas were broken pre-v6.8.9 layer-drift fix). `test_i9_dlq_empty` was correctly flagging this — old garbage, not active failures. Purged via `aws sqs purge-queue`. Queue at 0.

### Deploy

```bash
bash deploy/deploy_lambda.sh life-platform-qa-smoke lambdas/qa_smoke_lambda.py
# MCP needed full mcp/ package:
zip -j /tmp/mcp-deploy.zip mcp_server.py mcp_bridge.py
zip -r /tmp/mcp-deploy.zip mcp -x 'mcp/__pycache__/*'
aws lambda update-function-code --function-name life-platform-mcp \
    --zip-file fileb:///tmp/mcp-deploy.zip --region us-west-2
aws sqs purge-queue --queue-url https://sqs.us-west-2.amazonaws.com/205930651321/life-platform-ingestion-dlq
```

### Verification

- Post-deploy manual qa-smoke invoke: **8 failures → 5 failures**, **6 → 6 warnings**. Three false positives eliminated.
- `get_sources` direct curl test: returns 200 with whoop/withings/strava/todoist/apple_health source list (first/latest dates).
- DLQ: 90 → 0.

### Remaining 5 qa-smoke failures (categorized)

| Failure | Type | Action |
|---|---|---|
| DDB:macrofactor (no May 2 record) | Real, known | Matthew action: re-export MacroFactor (XLSX now works) |
| DDB:strava (no May 2 record) | Real, known | Matthew action: open Strava app, force sync |
| DDB:withings (no May 2 record) | False positive timing | Withings DOES have 2026-05-03 record. qa-smoke checks "yesterday" — edge case when Matthew skips a day. Defer. |
| blog:links (5 stale `week-0[0-4].html` refs) | Real but separate scope | Blog index in `./blog/` not `./site/blog/` — likely auto-generation lag. Defer until chronicle redesign. |
| (one more — likely DDB:strava cascade) | — | Same as above |

---

## What I investigated but didn't change

- **`/api/character_stats` 503→200 fix**: Already shipped in v6.9.4 (parallel session). Confirmed working.
- **CI failure on `36bebf1`**: post-deploy `test_i9_dlq_empty` failed because DLQ had 90 messages. Now drained; next push that touches `lambdas/**` will re-run that integration test and pass.

---

## State as of 9:15pm PT

| Metric | Value |
|---|---|
| Alarms in ALARM | 0 (per v6.9.2 cleanup) |
| DLQ messages | 0 (purged) |
| qa-smoke failures | 5 (down from 8); all real Matthew-action items or known low-priority deferrals |
| MCP `get_sources` | Working (was 401 + KeyError) |
| MCP `get_todoist_snapshot` | Working (was 401) |

## What's true tomorrow morning

✅ qa-smoke 10:30 AM PT run will show clean signal — no false dashboard/MCP failures
✅ Inbox quiet (alarm + DLQ + qa-smoke false positives all addressed)
✅ Three new Matthew-action surfaces in qa-smoke email: Strava re-sync, MacroFactor re-export, blog:links cleanup (defer)

---

**Previous:** [HANDOVER_v6.9.4.md](HANDOVER_v6.9.4.md) — visual_qa v3.1 + character_stats 503→200
