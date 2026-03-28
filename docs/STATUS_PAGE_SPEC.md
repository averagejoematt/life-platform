# Status Page Spec — `averagejoematt.com/status`

> Authored by: Technical Board of Directors + Product Board of Directors, Life Platform
> Date: 2026-03-28
> For: Claude Code — read this single file to implement everything end to end
> Estimated effort: 4–6 hours

---

## Overview

Build a status page at `averagejoematt.com/status` giving Matthew a single-pane-of-glass view
of all 19 data sources, key Lambdas, email delivery, web layer, and infrastructure health.
The page is semi-public (no auth required), auto-refreshes every 60 seconds, and is the
ambient confidence instrument for a solo developer running a complex personal health platform.

**URL decision (both boards unanimous):** `/status` path on the existing domain — not a
separate subdomain. Simpler DNS, no new CloudFront alternate domain needed, same TLS cert.
The page is accessible at `https://averagejoematt.com/status/`.

**Navigation placement (14-0 unanimous joint vote):** Footer only — never in the primary nav.
Status pages belong in footers (Stripe, GitHub, Atlassian all do this). A new "Internal"
footer column will be added to `components.js` containing Status + future private links
(Clinician View, Buddy Dashboard). See Part 5 for the exact `components.js` changes.

**Design references:** Atlassian StatusPage (90-day uptime bars), Stripe (component grouping +
overall banner), GitHub (timestamp format), Cloudflare (immediate all-clear message).

---

## Files to create or modify

| File | Action |
|---|---|
| `lambdas/site_api_lambda.py` | Add `/api/status` and `/api/status/summary` routes |
| `site/status/index.html` | Create — the status page HTML |
| `site/assets/js/components.js` | Modify — add "Internal" footer column with live status dot |
| Email Lambdas (see Part 4) | Possibly add DynamoDB completion record on success |

No new CDK stacks. No new Lambda. No new CloudFront distribution. No new DNS record.

---

## Part 1: Backend — `/api/status` and `/api/status/summary` endpoints

### File to modify
`lambdas/site_api_lambda.py`

### Routes to add
```
GET /api/status          — full status payload (used by status page)
GET /api/status/summary  — lightweight {overall: green|yellow|red} (used by footer dot)
```

### Response format for `/api/status`
```json
{
  "generated_at": "2026-03-28T18:47:00Z",
  "overall": "green",
  "groups": [
    {
      "id": "data_sources",
      "label": "Data sources",
      "subtitle": "13 scheduled · 3 file · 1 webhook",
      "components": [
        {
          "id": "whoop",
          "name": "Whoop",
          "description": "Recovery · HRV · sleep staging",
          "status": "green",
          "last_sync_relative": "2h ago",
          "uptime_90d": [1,1,1,1,1],
          "comment": null
        }
      ]
    }
  ]
}
```

### Response format for `/api/status/summary`
```json
{ "overall": "green", "generated_at": "2026-03-28T18:47:00Z" }
```

This lightweight endpoint is called by the footer on every page load to animate the status dot.
Cache it for 5 minutes alongside the full response (same cache object, just return `overall`).

### Status enum
- `"green"` — operational, last sync within expected window
- `"yellow"` — stale, last sync beyond yellow threshold but within red threshold
- `"red"` — critical, last sync beyond red threshold OR Lambda errored
- `"gray"` — expected to not run today (e.g. weekly digest on a Tuesday)

### DynamoDB query strategy

For each data source, query the partition for the latest DATE# record:

```python
response = table.query(
    KeyConditionExpression="PK = :pk AND begins_with(SK, :prefix)",
    ExpressionAttributeValues={
        ":pk": f"USER#matthew#SOURCE#{source_id}",
        ":prefix": "DATE#"
    },
    ScanIndexForward=False,
    Limit=1
)
```

**IMPORTANT:** The `site_api_lambda.py` runs in **us-east-1** but queries **us-west-2** DynamoDB.
The existing Lambda already does this. Confirm `boto3.resource("dynamodb", region_name="us-west-2")`
is used — not the Lambda's own region.

**Verify partition IDs before deploying** — the source IDs below must match the exact PK prefixes
written by ingestion Lambdas. Spot-check with:
```bash
aws dynamodb query --table-name life-platform \
  --key-condition-expression "PK = :pk" \
  --expression-attribute-values '{":pk":{"S":"USER#matthew#SOURCE#whoop"}}' \
  --limit 1 --scan-index-forward false
```

### Stale thresholds per component

```python
# (yellow_hours, red_hours)
# yellow = show amber warning; red = show red critical

DATA_SOURCES = [
    # (source_id, display_name, description, yellow_h, red_h)
    ("whoop",              "Whoop",              "Recovery · HRV · sleep staging",        25,  49),
    ("withings",           "Withings",           "Weight · body comp · blood pressure",   25,  49),
    ("garmin",             "Garmin",             "Steps · GPS · zone training",           25,  49),
    ("strava",             "Strava",             "Activity · segments · effort",          25,  49),
    ("habitify",           "Habitify",           "P40 habit tracking · day grades",       25,  49),
    ("eightsleep",         "Eight Sleep",        "Sleep staging · bed temperature",       25,  49),
    ("macrofactor",        "MacroFactor",        "Nutrition · calories · macros",         25,  49),
    ("notion_journal",     "Notion journal",     "Daily journal · mood · reflections",    25,  49),
    ("todoist",            "Todoist",            "Tasks · projects · completion rate",    25,  49),
    ("weather",            "Weather",            "Daily conditions · temperature",        25,  49),
    ("dropbox_poll",       "Dropbox",            "File drop trigger · 30-min polling",    1,    2),  # tight: every 30m
    ("health_auto_export", "Health Auto Export", "CGM · blood pressure · state of mind",  4,   12),  # webhook
    ("apple_health",       "Apple Health",       "Manual import · HKR XML",              168, 336),  # weekly is normal
]

COMPUTE_SOURCES = [
    ("character_sheet",  "Character sheet",  "Pillar scores · level · XP",             25, 49),
    ("computed_metrics", "Daily metrics",    "Cross-domain computed signals",          25, 49),
    ("insights",         "Daily insights",   "IC-8 intent vs execution",               25, 49),
    ("adaptive_mode",    "Adaptive mode",    "Engagement scoring · brief mode",        25, 49),
]

# Email Lambdas: (lambda_id, name, description, expected_dow, yellow_h, red_h)
# expected_dow: 0=Mon, 6=Sun, -1=daily
EMAIL_LAMBDAS = [
    ("daily_brief",         "Daily brief",         "11:00 AM daily · 18 sections",     -1, 25,  49),
    ("weekly_digest",       "Weekly digest",       "Sunday 9:00 AM",                    6, 200, 400),
    ("monday_compass",      "Monday compass",      "Monday 8:00 AM · forward planning", 0, 200, 400),
    ("wednesday_chronicle", "Wednesday chronicle", "Wednesday 8:00 AM · Elena Voss",    2, 200, 400),
    ("weekly_plate",        "Weekly plate",        "Friday 7:00 PM · nutrition",        4, 200, 400),
    ("nutrition_review",    "Nutrition review",    "Saturday 10:00 AM",                 5, 200, 400),
    ("anomaly_detector",    "Anomaly detector",    "9:05 AM daily · 15 metrics",       -1, 25,  49),
]
```

### Schedule-aware status for digest Lambdas

For weekly digests, `gray` is correct on non-send days. Logic:

```python
def schedule_aware_status(status, rel, expected_dow, today_dow):
    """If expected_dow >= 0 and today is not that day, convert yellow -> gray."""
    if expected_dow < 0:
        return status, rel  # daily — no adjustment
    if today_dow == expected_dow:
        return status, rel  # send day — keep real status
    if status == "yellow":
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        return "gray", f"next: {day_names[expected_dow]}"
    return status, rel
```

### 90-day uptime array

For each component, return a list of 90 integers:
- `1` = operational (DATE# record exists for that day)
- `0` = down/missing
- `-1` = not expected (gray, e.g. Apple Health on non-import days)
- `2` = degraded/stale

Query: fetch last 90 DATE# records per source with `ScanIndexForward=False, Limit=90`.
Build a set of present dates, then iterate 90 days back from today.

**Performance:** 19 + 4 + 7 = 30 sources × ~2ms/query warm ≈ 60ms total. Acceptable.
Cache full response for 5 minutes using module-level dict (same pattern as `_ask_rate_store`).

### Full handler code

Add the following to `lambdas/site_api_lambda.py`:

```python
import json
import time
import boto3
from datetime import datetime, timedelta, timezone

# Module-level cache (no DDB writes — role is read-only)
_status_cache = {}
_status_cache_ts = 0
STATUS_CACHE_TTL = 300  # 5 minutes

def _get_status_dynamodb():
    """Returns a DynamoDB Table resource pointing at us-west-2."""
    db = boto3.resource("dynamodb", region_name="us-west-2")
    return db.Table("life-platform")

def _get_last_sync_date(table, source_id):
    """Returns YYYY-MM-DD string of most recent DATE# record, or None."""
    try:
        resp = table.query(
            KeyConditionExpression=
                "PK = :pk AND begins_with(SK, :prefix)",
            ExpressionAttributeValues={
                ":pk": f"USER#matthew#SOURCE#{source_id}",
                ":prefix": "DATE#"
            },
            ScanIndexForward=False,
            Limit=1,
            ProjectionExpression="SK"
        )
        items = resp.get("Items", [])
        if not items:
            return None
        return items[0]["SK"].replace("DATE#", "").split("#")[0]  # handle DATE#date#LAMBDA#name
    except Exception:
        return None

def _compute_component_status(last_date_str, yellow_hours, red_hours):
    """Returns (status, relative_label, comment_or_None)."""
    if not last_date_str:
        return "red", "never", "No records found in DynamoDB — check Lambda logs"

    last_dt = datetime.strptime(last_date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    hours_ago = (now - last_dt).total_seconds() / 3600

    if hours_ago < 1:
        rel = "< 1h ago"
    elif hours_ago < 24:
        rel = f"{int(hours_ago)}h ago"
    elif hours_ago < 48:
        rel = "yesterday"
    else:
        rel = f"{int(hours_ago / 24)}d ago"

    if hours_ago <= yellow_hours:
        return "green", rel, None
    elif hours_ago <= red_hours:
        return "yellow", rel, f"Last sync {rel} — expected within {yellow_hours}h. May need attention."
    else:
        return "red", rel, f"STALE: last sync {rel}. Threshold exceeded ({red_hours}h)."

def _get_uptime_90d(table, source_id):
    """Returns list of 90 ints: 1=up, 0=missing, -1=n/a."""
    try:
        resp = table.query(
            KeyConditionExpression=
                "PK = :pk AND begins_with(SK, :prefix)",
            ExpressionAttributeValues={
                ":pk": f"USER#matthew#SOURCE#{source_id}",
                ":prefix": "DATE#"
            },
            ScanIndexForward=False,
            Limit=90,
            ProjectionExpression="SK"
        )
        present = set()
        for item in resp.get("Items", []):
            sk = item["SK"].replace("DATE#", "")
            present.add(sk[:10])  # just YYYY-MM-DD

        today = datetime.now(timezone.utc).date()
        return [1 if (today - timedelta(days=i)).isoformat() in present else 0
                for i in range(89, -1, -1)]
    except Exception:
        return [0] * 90

def _schedule_aware(status, rel, expected_dow, today_dow):
    if expected_dow < 0 or today_dow == expected_dow:
        return status, rel
    if status == "yellow":
        names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        return "gray", f"next: {names[expected_dow]}"
    return status, rel

def handle_status(event, context):
    global _status_cache, _status_cache_ts

    path = event.get("rawPath", event.get("path", ""))
    summary_only = path.endswith("/summary")

    now_ts = time.time()
    if now_ts - _status_cache_ts < STATUS_CACHE_TTL and _status_cache:
        if summary_only:
            body = json.dumps({"overall": _status_cache.get("overall", "green"),
                               "generated_at": _status_cache.get("generated_at", "")})
        else:
            body = json.dumps(_status_cache)
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json",
                        "Cache-Control": "public, max-age=60",
                        "Access-Control-Allow-Origin": "*"},
            "body": body
        }

    table = _get_status_dynamodb()
    today_dow = datetime.now(timezone.utc).weekday()

    DATA_SOURCES = [
        ("whoop",              "Whoop",              "Recovery · HRV · sleep staging",        25,  49),
        ("withings",           "Withings",           "Weight · body comp · blood pressure",   25,  49),
        ("garmin",             "Garmin",             "Steps · GPS · zone training",           25,  49),
        ("strava",             "Strava",             "Activity · segments · effort",          25,  49),
        ("habitify",           "Habitify",           "P40 habit tracking · day grades",       25,  49),
        ("eightsleep",         "Eight Sleep",        "Sleep staging · bed temperature",       25,  49),
        ("macrofactor",        "MacroFactor",        "Nutrition · calories · macros",         25,  49),
        ("notion_journal",     "Notion journal",     "Daily journal · mood · reflections",    25,  49),
        ("todoist",            "Todoist",            "Tasks · projects · completion rate",    25,  49),
        ("weather",            "Weather",            "Daily conditions · temperature",        25,  49),
        ("dropbox_poll",       "Dropbox",            "File drop trigger · 30-min polling",    1,    2),
        ("health_auto_export", "Health Auto Export", "CGM · blood pressure · state of mind",  4,   12),
        ("apple_health",       "Apple Health",       "Manual import · HKR XML",              168, 336),
    ]
    COMPUTE_SOURCES = [
        ("character_sheet",  "Character sheet",  "Pillar scores · level · XP",         25, 49),
        ("computed_metrics", "Daily metrics",    "Cross-domain computed signals",       25, 49),
        ("insights",         "Daily insights",   "IC-8 intent vs execution",            25, 49),
        ("adaptive_mode",    "Adaptive mode",    "Engagement scoring · brief mode",     25, 49),
    ]
    EMAIL_LAMBDAS = [
        ("daily_brief",         "Daily brief",         "11:00 AM daily · 18 sections",     -1, 25,  49),
        ("weekly_digest",       "Weekly digest",       "Sunday 9:00 AM",                    6, 200, 400),
        ("monday_compass",      "Monday compass",      "Monday 8:00 AM · forward planning", 0, 200, 400),
        ("wednesday_chronicle", "Wednesday chronicle", "Wednesday 8:00 AM · Elena Voss",    2, 200, 400),
        ("weekly_plate",        "Weekly plate",        "Friday 7:00 PM · nutrition",        4, 200, 400),
        ("nutrition_review",    "Nutrition review",    "Saturday 10:00 AM",                 5, 200, 400),
        ("anomaly_detector",    "Anomaly detector",    "9:05 AM daily · 15 metrics",       -1, 25,  49),
    ]

    def build_components(sources, id_fn=None):
        out = []
        for row in sources:
            sid = row[0]; name = row[1]; desc = row[2]; yellow = row[-2]; red = row[-1]
            lookup_id = id_fn(sid) if id_fn else sid
            last = _get_last_sync_date(table, lookup_id)
            status, rel, comment = _compute_component_status(last, yellow, red)
            uptime = _get_uptime_90d(table, lookup_id)
            out.append({"id": sid, "name": name, "description": desc,
                        "status": status, "last_sync_relative": rel,
                        "uptime_90d": uptime, "comment": comment})
        return out

    ds_components = build_components(DATA_SOURCES)

    compute_components = build_components(COMPUTE_SOURCES)

    email_components = []
    for row in EMAIL_LAMBDAS:
        lid = row[0]; name = row[1]; desc = row[2]; exp_dow = row[3]; yellow = row[4]; red = row[5]
        last = _get_last_sync_date(table, f"email_log#{lid}")
        status, rel, comment = _compute_component_status(last, yellow, red)
        status, rel = _schedule_aware(status, rel, exp_dow, today_dow)
        uptime = _get_uptime_90d(table, f"email_log#{lid}")
        email_components.append({"id": lid, "name": name, "description": desc,
                                  "status": status, "last_sync_relative": rel,
                                  "uptime_90d": uptime, "comment": comment})

    infra = [
        {"id": "cloudfront_main", "name": "averagejoematt.com",     "description": "CloudFront E3S424OXQZ8NBE · 12 pages",        "status": "green", "comment": None},
        {"id": "cloudfront_dash", "name": "dash.averagejoematt.com", "description": "CloudFront EM5NPX6NJN095 · Lambda@Edge auth", "status": "green", "comment": None},
        {"id": "cloudfront_blog", "name": "blog.averagejoematt.com", "description": "CloudFront E1JOC1V6E6DDYI · Chronicle",       "status": "green", "comment": None},
        {"id": "site_api",        "name": "Site API Lambda",         "description": "us-east-1 · public read-only API",            "status": "green", "comment": None},
        {"id": "mcp_server",      "name": "MCP server",              "description": "us-west-2 · 95 tools · Claude integration",  "status": "green", "comment": None},
        {"id": "dynamodb",        "name": "DynamoDB",                "description": "life-platform · on-demand · PITR enabled",   "status": "green", "comment": None},
        {"id": "ses",             "name": "SES email delivery",      "description": "Production mode · receipt rule active",       "status": "green", "comment": None},
        {"id": "dlq",             "name": "Dead-letter queue",       "description": "life-platform-ingestion-dlq",                 "status": "green", "comment": None},
    ]

    all_statuses = [c["status"] for g in [ds_components, compute_components, email_components] for c in g]
    if "red" in all_statuses:
        overall = "red"
    elif "yellow" in all_statuses:
        overall = "yellow"
    else:
        overall = "green"

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "groups": [
            {"id": "data_sources",  "label": "Data sources",  "subtitle": "13 scheduled · 3 file · 1 webhook",           "components": ds_components},
            {"id": "compute",       "label": "Compute layer", "subtitle": "character sheet · metrics · insights · adaptive mode", "components": compute_components},
            {"id": "email",         "label": "Email & digests","subtitle": "7 scheduled senders",                         "components": email_components},
            {"id": "infrastructure","label": "Infrastructure","subtitle": "CloudFront · DynamoDB · SES · DLQ",             "components": infra},
        ]
    }

    _status_cache = result
    _status_cache_ts = now_ts

    if summary_only:
        body = json.dumps({"overall": overall, "generated_at": result["generated_at"]})
    else:
        body = json.dumps(result)

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json",
                    "Cache-Control": "public, max-age=60",
                    "Access-Control-Allow-Origin": "*"},
        "body": body
    }
```

### Add routes to the main router in `site_api_lambda.py`

Find the existing `elif path == "/api/..."` block and add:

```python
elif path in ("/api/status", "/api/status/summary"):
    return handle_status(event, context)
```

---

## Part 2: Frontend — `site/status/index.html`

Create this file at `site/status/index.html`. It is a self-contained static page — no shared
components.js, no nav injection. The status page has its own minimal header and no subscribe CTA.

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>System Status — averagejoematt.com</title>
  <style>
    :root {
      --green: #639922; --green-bg: #EAF3DE; --green-text: #27500A;
      --yellow: #BA7517; --yellow-bg: #FAEEDA; --yellow-text: #633806;
      --red: #E24B4A;   --red-bg: #FCEBEB;   --red-text: #791F1F;
      --gray: #888780;  --gray-bg: #F1EFE8;  --gray-text: #444441;
      --bar-up: #97C459; --bar-warn: #EF9F27; --bar-down: #F09595; --bar-na: #e0dfd8;
      --border: #e0dfd8; --surface: #fff; --page-bg: #f8f8f6;
      --text: #2c2c2a; --text-muted: #888780; --text-subtle: #b4b2a9;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: var(--page-bg); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color: var(--text); }

    .header { background: var(--surface); border-bottom: 0.5px solid var(--border); padding: 0 1.5rem; }
    .header-inner { max-width: 860px; margin: 0 auto; display: flex; align-items: center; justify-content: space-between; height: 52px; }
    .logo { font-size: 13px; font-weight: 500; color: var(--text); text-decoration: none; }
    .logo span { color: var(--text-muted); }
    .logo:hover { color: var(--text); }
    .header-meta { font-size: 11px; color: var(--text-muted); display: flex; align-items: center; gap: 8px; }
    .refresh-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--green); animation: pulse 2s infinite; }
    @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }

    .main { max-width: 860px; margin: 0 auto; padding: 1.5rem; display: flex; flex-direction: column; gap: 12px; }

    .overall { border-radius: 10px; padding: 14px 18px; display: flex; align-items: center; gap: 12px; }
    .overall.green { background: var(--green-bg); border: 0.5px solid #97C459; }
    .overall.yellow { background: var(--yellow-bg); border: 0.5px solid #EF9F27; }
    .overall.red { background: var(--red-bg); border: 0.5px solid #F09595; }
    .overall.loading { background: var(--gray-bg); border: 0.5px solid var(--border); }
    .overall-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
    .overall.green .overall-dot { background: var(--green); }
    .overall.yellow .overall-dot { background: var(--yellow); }
    .overall.red .overall-dot { background: var(--red); }
    .overall.loading .overall-dot { background: var(--gray); }
    .overall-text { font-size: 14px; font-weight: 500; }
    .overall.green .overall-text { color: var(--green-text); }
    .overall.yellow .overall-text { color: var(--yellow-text); }
    .overall.red .overall-text { color: var(--red-text); }
    .overall.loading .overall-text { color: var(--gray-text); }
    .overall-sub { font-size: 12px; margin-left: auto; color: #3B6D11; }
    .overall.yellow .overall-sub { color: #854F0B; }
    .overall.red .overall-sub { color: #A32D2D; }
    .overall.loading .overall-sub { color: var(--text-subtle); }

    .section { background: var(--surface); border: 0.5px solid var(--border); border-radius: 10px; overflow: hidden; }
    .sec-header { padding: 10px 14px; border-bottom: 0.5px solid #f0efe8; display: flex; align-items: center; justify-content: space-between; }
    .sec-title { font-size: 11px; font-weight: 500; color: #444441; letter-spacing: .05em; text-transform: uppercase; }
    .sec-sub { font-size: 11px; color: var(--text-muted); }

    .component-row { display: grid; grid-template-columns: 200px 1fr 100px 110px; align-items: start; padding: 10px 14px; border-bottom: 0.5px solid #f8f7f5; }
    .component-row:last-child { border-bottom: none; }
    .component-row:hover { background: #fafaf8; }
    .comp-name { font-size: 13px; font-weight: 500; color: var(--text); }
    .comp-desc { font-size: 11px; color: var(--text-muted); margin-top: 2px; line-height: 1.4; }

    .uptime-wrap { padding: 2px 12px 0; }
    .uptime-bar { display: flex; gap: 1.5px; }
    .uptime-bar .bar { width: 6px; height: 18px; border-radius: 2px; flex-shrink: 0; }
    .bar.up { background: var(--bar-up); }
    .bar.warn { background: var(--bar-warn); }
    .bar.down { background: var(--bar-down); }
    .bar.na { background: var(--bar-na); }
    .uptime-label { font-size: 10px; color: var(--text-subtle); margin-top: 3px; }

    .sync-time { text-align: right; padding-right: 4px; }
    .sync-time strong { display: block; font-size: 12px; font-weight: 500; color: #444441; }

    .pill { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: 20px; font-size: 11px; font-weight: 500; white-space: nowrap; }
    .pill::before { content: ''; width: 5px; height: 5px; border-radius: 50%; flex-shrink: 0; }
    .pill.green { background: var(--green-bg); color: var(--green-text); }
    .pill.green::before { background: var(--green); }
    .pill.yellow { background: var(--yellow-bg); color: var(--yellow-text); }
    .pill.yellow::before { background: var(--yellow); }
    .pill.red { background: var(--red-bg); color: var(--red-text); }
    .pill.red::before { background: var(--red); }
    .pill.gray { background: var(--gray-bg); color: var(--gray-text); }
    .pill.gray::before { background: var(--gray); }

    .comment-strip { grid-column: 1 / -1; margin-top: 6px; font-size: 11px; background: var(--yellow-bg); color: #854F0B; border-radius: 4px; padding: 5px 8px; line-height: 1.4; }
    .comment-strip.red { background: var(--red-bg); color: #791F1F; }

    .infra-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; padding: 12px 14px; }
    .infra-card { background: #fafaf8; border: 0.5px solid #eceae3; border-radius: 8px; padding: 10px 12px; display: flex; align-items: center; gap: 10px; }
    .infra-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
    .infra-dot.green { background: var(--green); }
    .infra-dot.yellow { background: var(--yellow); }
    .infra-dot.red { background: var(--red); }
    .infra-dot.gray { background: var(--gray); }
    .infra-label { font-size: 12px; font-weight: 500; color: var(--text); }
    .infra-desc { font-size: 11px; color: var(--text-muted); margin-top: 1px; }

    .page-footer { text-align: center; font-size: 11px; color: var(--text-subtle); padding: 1.5rem 0 0.5rem; }
    .page-footer a { color: var(--text-muted); text-decoration: none; }
    .page-footer a:hover { color: var(--text); }

    @media (max-width: 600px) {
      .component-row { grid-template-columns: 1fr auto; }
      .uptime-wrap, .sync-time { display: none; }
      .sec-sub { display: none; }
      .infra-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>

<div class="header">
  <div class="header-inner">
    <a href="/" class="logo">averagejoematt <span>/ status</span></a>
    <div class="header-meta">
      <div class="refresh-dot" id="refreshDot"></div>
      <span id="lastUpdated">loading…</span>
    </div>
  </div>
</div>

<div class="main" id="main">
  <div class="overall loading" id="overallBanner">
    <div class="overall-dot"></div>
    <div class="overall-text">Checking systems…</div>
    <div class="overall-sub"></div>
  </div>
</div>

<script>
const API_URL = '/api/status';
const STATUS_LABELS = { green: 'Operational', yellow: 'Stale', red: 'Critical', gray: 'Scheduled' };
const OVERALL_MESSAGES = { green: 'All systems operational', yellow: 'Degraded performance', red: 'Service disruption' };

function buildUptimeBar(arr) {
  if (!arr || !arr.length) return '<div class="uptime-label">no data</div>';
  const bars = arr.slice(-30).map(v => {
    const cls = v === 1 ? 'up' : v === 2 ? 'warn' : v === 0 ? 'down' : 'na';
    return `<div class="bar ${cls}" title="${cls}"></div>`;
  }).join('');
  return `<div class="uptime-bar">${bars}</div><div class="uptime-label">30 days</div>`;
}

function buildComponentRow(c) {
  const comment = c.comment
    ? `<div class="comment-strip ${c.status === 'red' ? 'red' : ''}">&#9888; ${c.comment}</div>`
    : '';
  return `
    <div class="component-row">
      <div><div class="comp-name">${c.name}</div><div class="comp-desc">${c.description}</div></div>
      <div class="uptime-wrap">${buildUptimeBar(c.uptime_90d)}</div>
      <div class="sync-time"><strong>${c.last_sync_relative || '—'}</strong></div>
      <div><span class="pill ${c.status}">${STATUS_LABELS[c.status] || c.status}</span></div>
      ${comment}
    </div>`;
}

function buildInfraCard(c) {
  return `<div class="infra-card">
    <div class="infra-dot ${c.status}"></div>
    <div><div class="infra-label">${c.name}</div><div class="infra-desc">${c.description}</div></div>
  </div>`;
}

function renderStatus(data) {
  const main = document.getElementById('main');
  const banner = document.getElementById('overallBanner');
  const total = data.groups.reduce((s, g) => s + g.components.length, 0);

  banner.className = `overall ${data.overall}`;
  banner.innerHTML = `
    <div class="overall-dot"></div>
    <div class="overall-text">${OVERALL_MESSAGES[data.overall] || 'Status unknown'}</div>
    <div class="overall-sub">${total} components monitored</div>`;

  const genAt = new Date(data.generated_at);
  document.getElementById('lastUpdated').textContent =
    `updated ${genAt.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})}`;

  main.querySelectorAll('.section, .page-footer').forEach(el => el.remove());

  data.groups.forEach(group => {
    const sec = document.createElement('div');
    sec.className = 'section';
    if (group.id === 'infrastructure') {
      sec.innerHTML = `
        <div class="sec-header">
          <span class="sec-title">${group.label}</span>
          <span class="sec-sub">${group.subtitle}</span>
        </div>
        <div class="infra-grid">${group.components.map(buildInfraCard).join('')}</div>`;
    } else {
      sec.innerHTML = `
        <div class="sec-header">
          <span class="sec-title">${group.label}</span>
          <span class="sec-sub">${group.subtitle}</span>
        </div>
        ${group.components.map(buildComponentRow).join('')}`;
    }
    main.appendChild(sec);
  });

  const foot = document.createElement('div');
  foot.className = 'page-footer';
  foot.innerHTML = `life platform &middot; <a href="/">averagejoematt.com</a> &middot; auto-refreshes every 60s`;
  main.appendChild(foot);
}

async function fetchStatus() {
  const dot = document.getElementById('refreshDot');
  try {
    dot.style.background = '#EF9F27';
    const res = await fetch(API_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderStatus(data);
    dot.style.background = '#639922';
  } catch (err) {
    dot.style.background = '#E24B4A';
    document.getElementById('lastUpdated').textContent = 'update failed — retrying in 60s';
  }
}

fetchStatus();
setInterval(fetchStatus, 60000);
</script>
</body>
</html>
```

---

## Part 3: CloudFront — serve `/status/` path

The status page HTML lives at `site/status/index.html` in S3. The existing CloudFront
distribution `E3S424OXQZ8NBE` already serves `site/*` from S3. No new behavior is needed
if the default root object and path routing already handle `/status/index.html`.

**Verify the existing S3 origin behavior** covers `/status/*`:
```bash
aws cloudfront get-distribution-config --id E3S424OXQZ8NBE \
  --query 'DistributionConfig.Origins'
```

The path `averagejoematt.com/status/` should resolve to `site/status/index.html` in S3 —
this works if the S3 origin has `OriginPath: /site` and CloudFront is configured to forward
the request path. If not, add a CloudFront function or behavior for `/status/*` → S3.

**Add to deploy script** (safe — no `--delete` flag):
```bash
aws s3 cp site/status/index.html s3://matthew-life-platform/site/status/index.html
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/status/*" "/api/status*"
```

**CloudFront cache TTL for the status page:**
- `/status/index.html` → TTL 60s (matches auto-refresh; set via `Cache-Control: max-age=60` header or behavior)
- `/api/status` and `/api/status/summary` → TTL 60s (already set by Lambda response header)

---

## Part 4: DynamoDB — email completion tracking

The `/api/status` email section queries `USER#matthew#SOURCE#email_log#<lambda_id>` for
`DATE#` records to determine when each email Lambda last ran successfully.

**Before adding anything**, check whether this already exists:
```bash
grep -rn "email_log" lambdas/
grep -rn "SOURCE#email" lambdas/
```

If these partitions don't exist, add the following helper to each email Lambda
(daily-brief, weekly-digest, monday-compass, wednesday-chronicle, weekly-plate,
nutrition-review, anomaly-detector) — call it at the end of the handler on success only:

```python
def record_email_send(table, lambda_name: str) -> None:
    """Write a completion record so the status page can track last send."""
    from datetime import datetime, timezone
    import time
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        table.put_item(Item={
            "PK": f"USER#matthew#SOURCE#email_log#{lambda_name}",
            "SK": f"DATE#{today}",
            "sent_at": datetime.now(timezone.utc).isoformat(),
            "status": "success",
            "ttl": int(time.time()) + 86400 * 90  # 90-day TTL
        })
    except Exception as e:
        print(f"[status-tracking] Non-fatal write failure: {e}")
        # Do NOT re-raise — never fail the email over status tracking
```

The lambda_name values to use (must match the source IDs in Part 1):
- `daily_brief`
- `weekly_digest`
- `monday_compass`
- `wednesday_chronicle`
- `weekly_plate`
- `nutrition_review`
- `anomaly_detector`

These Lambdas already have DynamoDB write access in their IAM roles (they write digest
output and habit scores). No IAM changes needed.

---

## Part 5: Footer — "Internal" column in `components.js`

**File:** `site/assets/js/components.js`

**Board decision (14-0 unanimous):** Status is discoverable only from the footer, not the
primary nav. A new fifth column "Internal" will be added to the existing footer grid.
Key design details:
- Live green/yellow/red dot on the Status link — fetches `/api/status/summary` on page load
- Lock icons on Clinician View and Buddy Dashboard signal they are password-protected
- RSS and Privacy migrate into this column from wherever they currently live

### Exact change to `buildFooter()` in `components.js`

Find the `footerCols` array in `buildFooter()`. It currently has 4 columns. Add the 5th:

**Locate this line** (the closing of the last column before the grid is closed):
```javascript
      { href: '/subscribe/', text: 'Subscribe' },
    ]},
  ];
```

**Replace with** (adds the Internal column):
```javascript
      { href: '/subscribe/', text: 'Subscribe' },
    ]},
    { heading: 'Internal', links: [
      { href: '/status/', text: 'System Status', id: 'footer-status-link' },
      { href: 'https://dash.averagejoematt.com', text: 'Clinician View', locked: true },
      { href: 'https://buddy.averagejoematt.com', text: 'Buddy Dashboard', locked: true },
      { href: '/rss.xml', text: 'RSS Feed' },
      { href: '/privacy/', text: 'Privacy' },
    ]},
  ];
```

Then find where the footer column links are rendered in `buildFooter()`. The existing render
loop generates `<a href="...">text</a>` for each link. Modify the link renderer to handle
the two new properties: `id` and `locked`.

**Find the existing link render line** (something like):
```javascript
html += '<a href="' + link.href + '" class="footer-v2__link">' + link.text + '</a>';
```

**Replace the entire link-render section** with:
```javascript
// Build link — supports id (for JS targeting) and locked (shows lock icon)
var linkId = link.id ? ' id="' + link.id + '"' : '';
var lockIcon = link.locked
  ? ' <svg style="width:10px;height:10px;opacity:.45;vertical-align:middle;margin-left:2px" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="5" width="8" height="6" rx="1"/><path d="M4 5V3.5a2 2 0 0 1 4 0V5"/></svg>'
  : '';
html += '<a href="' + link.href + '" class="footer-v2__link"' + linkId + '>' + link.text + lockIcon + '</a>';
```

### Status dot script — add to the bottom of `components.js`

Add this block at the end of the IIFE, after all the `inject` logic:

```javascript
  // ── Status dot: fetch /api/status/summary and update footer link ──────
  (function() {
    var statusLink = document.getElementById('footer-status-link');
    if (!statusLink) return;

    // Insert the dot before the text
    var dot = document.createElement('span');
    dot.style.cssText = 'display:inline-block;width:6px;height:6px;border-radius:50%;background:#888780;margin-right:5px;vertical-align:middle;transition:background .3s';
    statusLink.insertBefore(dot, statusLink.firstChild);

    fetch('/api/status/summary')
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(data) {
        if (!data) return;
        var colors = { green: '#639922', yellow: '#BA7517', red: '#E24B4A' };
        dot.style.background = colors[data.overall] || '#888780';
        dot.title = data.overall === 'green' ? 'All systems operational'
                  : data.overall === 'yellow' ? 'Degraded performance'
                  : 'Service disruption';
      })
      .catch(function() {}); // silently ignore — never break page load for this
  })();
```

**Important:** The `fetch('/api/status/summary')` call fires on every page load across
the entire site. The endpoint is cached for 5 minutes server-side and has `max-age=60`
in the response. The browser will cache it accordingly. Cost: negligible — this is a
tiny JSON response with no DDB queries beyond the cache hit.

---

## Implementation checklist for Claude Code

Complete these in order. Each step is independent and testable.

```
PART 1 — BACKEND
[ ] 1.  Search lambdas/site_api_lambda.py for existing status-related code — avoid duplication
[ ] 2.  Add handle_status() function from Part 1 to site_api_lambda.py
[ ] 3.  Add /api/status and /api/status/summary to the main router
[ ] 4.  grep -rn "email_log" lambdas/ — check if completion records already exist
[ ] 5.  If not: add record_email_send() helper to each email Lambda (Part 4)
[ ] 6.  Deploy site-api Lambda: bash deploy/deploy_lambda.sh life-platform-site-api
        (us-east-1 — the script handles the correct region)

PART 2 — FRONTEND
[ ] 7.  Create site/status/index.html using the HTML in Part 2
[ ] 8.  Upload to S3: aws s3 cp site/status/index.html s3://matthew-life-platform/site/status/index.html

PART 3 — CLOUDFRONT
[ ] 9.  Verify /status/* is served correctly from CloudFront → S3
        curl -I https://averagejoematt.com/status/
[ ] 10. If 404: check CloudFront origin path and S3 key — may need /status/ behavior
[ ] 11. Invalidate: aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/status/*" "/api/status*"

PART 5 — FOOTER (components.js)
[ ] 12. Add Internal column to footerCols array in buildFooter() (Part 5)
[ ] 13. Update link renderer to support id and locked props (Part 5)
[ ] 14. Add status dot fetch script to end of components.js IIFE (Part 5)
[ ] 15. Upload: aws s3 cp site/assets/js/components.js s3://matthew-life-platform/site/assets/js/components.js
[ ] 16. Invalidate: aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/assets/js/components.js"

SMOKE TESTS
[ ] 17. curl https://averagejoematt.com/api/status — verify JSON, all 4 groups present
[ ] 18. curl https://averagejoematt.com/api/status/summary — verify {"overall":"green",...}
[ ] 19. Open https://averagejoematt.com/status/ — verify page loads, data populates
[ ] 20. Open https://averagejoematt.com/ — scroll to footer — verify Internal column + status dot
[ ] 21. Check all 13 data sources appear in /api/status with non-null last_sync_relative
[ ] 22. Verify email components show gray (not yellow) for non-send days
[ ] 23. git add -A && git commit -m "feat: status page + footer Internal column — v[next]"
[ ] 24. Add CHANGELOG entry
```

---

## Important notes for Claude Code

1. **DynamoDB region:** `site_api_lambda.py` runs in us-east-1 but must query us-west-2 DynamoDB.
   Confirm `boto3.resource("dynamodb", region_name="us-west-2")` — not the Lambda's own region.

2. **Source partition IDs:** The source IDs (e.g. `whoop`, `habitify`) must exactly match
   the PK suffixes the ingestion Lambdas use. Spot-check at least 3 before deploying.

3. **No auth on /api/status:** This endpoint is intentionally public — it exposes only
   timestamps and status enums, never health data values or AWS resource identifiers.

4. **Module-level caching pattern:** `_status_cache` uses the same pattern as `_ask_rate_store`
   already in site_api_lambda.py. This is safe and idiomatic. Do not use DynamoDB for caching
   — the IAM role is read-only by design.

5. **components.js is a single file serving 54+ pages:** Test the footer change on at least
   3 different page types (home, observatory page, chronicle) before declaring it done.

6. **The status dot fetch is non-blocking and non-fatal:** The `catch(function() {})` is
   intentional — never let a status API failure affect page load across the entire site.

7. **/status/ trailing slash:** Ensure S3 and CloudFront serve `index.html` for both
   `/status` and `/status/` — add a CloudFront function or default root object if needed.

---

## Optional future enhancements (post-launch)

- **DLQ depth:** Add `cloudwatch:GetMetricStatistics` to site-api IAM role → show actual message count
- **CI/CD last deploy:** Write last-deploy timestamp to DynamoDB from GitHub Actions → show in infra grid
- **Incident log:** Add `INCIDENT#` DynamoDB partition + admin write endpoint → show in red comment strips
- **Canary Lambda:** `life-platform-canary` runs every 30 min — its last DATE# record is a strong proxy for overall Lambda health
