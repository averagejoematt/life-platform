# SIMP-2: Ingestion Framework Design & Migration Plan

> Framework code: `lambdas/ingestion_framework.py`
> Generated: 2026-03-09 v3.2.1

---

## Framework Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  ingestion_framework.py                                     │
│                                                             │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ IngestionConfig │  run_ingestion() │ Shared utilities  │  │
│  │ - source_name │  │  1. Load secret  │ - floats_to_decimal│
│  │ - secret_id   │  │  2. Authenticate │ - init_logger     │
│  │ - gap_detect  │  │  3. Find dates   │ - init_aws        │
│  │ - s3_prefix   │  │  4. For each:    │ - find_missing    │
│  │ - item_guard  │  │     fetch()      │ - store_item      │
│  │ - writeback   │  │     transform()  │ - archive_raw     │
│  └───────────────┘  │     validate()   │                   │
│                     │     store()      │                   │
│                     │     post_store() │                   │
│                     │  5. Return summary│                  │
│                     └──────────────────┘                   │
└─────────────────────────────────────────────────────────────┘
         ▲                    ▲                    ▲
         │                    │                    │
    Source-specific      Source-specific      Source-specific
    config               callbacks            callbacks
         │                    │                    │
   weather_handler.py    whoop_handler.py    strava_handler.py
   (40 lines)            (200 lines)         (300 lines)
```

## What the Framework Handles (the 80%)

| Concern | How |
|---------|-----|
| AWS client init | `_init_aws()` — DynamoDB, S3, Secrets Manager |
| Secret loading | Reads from Secrets Manager, passes to `authenticate_fn` |
| OAuth writeback | If `enable_secret_writeback=True`, saves updated creds after auth |
| Gap detection | `_find_missing_dates()` — queries DDB for last N days, returns missing dates |
| Date override | EventBridge `date_override` payload support (single date or "today") |
| DATA-2 validation | `_store_item()` calls `ingestion_validator.validate_item()` |
| REL-3 size guard | `_store_item()` calls `item_size_guard.safe_put_item()` if enabled |
| DDB key construction | `pk=USER#{user_id}#SOURCE#{source}`, `sk=DATE#{date_str}` |
| Schema versioning | Auto-adds `schema_version` and `ingested_at` to every record |
| S3 raw archival | `_archive_raw()` writes to `{s3_prefix}/{year}/{month}/{date}.json` |
| Structured logging | OBS-1 `platform_logger` with fallback |
| Decimal conversion | `_floats_to_decimal()` for DynamoDB |
| Rate limiting | Configurable delay between gap-fill days |

## What Sources Provide (the 20%)

| Callback | Purpose | Example |
|----------|---------|---------|
| `authenticate_fn(secret_data)` | Source-specific auth | OAuth token refresh, JWT login, API key extraction |
| `fetch_day_fn(creds, date_str)` | Fetch one day's data | API GET, CSV parse, file read |
| `transform_fn(raw, date_str)` | Map to platform schema | Normalize field names, compute derived values |
| `post_store_fn(items, date_str)` | Optional post-write hook | Supplement bridge (habitify), workout dedup |

---

## Example Migration: Weather (simplest)

**Before:** 143 lines in `weather_lambda.py`
**After:** ~40 lines in `weather_handler.py` + framework

```python
# lambdas/weather_handler.py — Weather ingestion via framework
from ingestion_framework import IngestionConfig, run_ingestion
import urllib.request, json

config = IngestionConfig(
    source_name="weather",
    secret_id=None,           # No auth needed
    s3_archive_prefix="raw/weather",
    enable_gap_detection=False,
)

LAT, LON = 47.6062, -122.3321  # Seattle

def authenticate(secret_data):
    return {}  # No auth

def fetch_day(creds, date_str):
    url = (f"https://api.open-meteo.com/v1/forecast?"
           f"latitude={LAT}&longitude={LON}&daily=temperature_2m_max,"
           f"temperature_2m_min,...&start_date={date_str}&end_date={date_str}")
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read())

def transform(raw, date_str):
    d = raw.get("daily", {})
    return [{
        "source": "weather",
        "date": date_str,
        "temp_high_f": d["temperature_2m_max"][0],
        "temp_low_f": d["temperature_2m_min"][0],
        # ... rest of field mapping
    }]

def lambda_handler(event, context):
    return run_ingestion(config, authenticate, fetch_day, transform, event, context)
```

## Example Migration: Whoop (OAuth + gap detection)

**Before:** 708 lines in `whoop_lambda.py`
**After:** ~200 lines in `whoop_handler.py` (all API interaction + transform) + framework

```python
# lambdas/whoop_handler.py — Whoop ingestion via framework
from ingestion_framework import IngestionConfig, run_ingestion

config = IngestionConfig(
    source_name="whoop",
    secret_id="life-platform/whoop",
    s3_archive_prefix="raw/whoop",
    enable_gap_detection=True,
    enable_secret_writeback=True,  # OAuth token refresh
    enable_item_size_guard=False,
)

def authenticate(secret_data):
    # Refresh OAuth token, return updated credentials
    access_token, new_refresh = refresh_access_token(
        secret_data["client_id"], secret_data["client_secret"],
        secret_data["refresh_token"],
    )
    return {**secret_data, "access_token": access_token, "refresh_token": new_refresh}

def fetch_day(creds, date_str):
    # Whoop API calls for recovery + sleep + workouts
    return {
        "recovery": api_get("/v1/recovery", date_str, creds["access_token"]),
        "sleep": api_get("/v1/sleep", date_str, creds["access_token"]),
        "workouts": api_get("/v1/workout", date_str, creds["access_token"]),
    }

def transform(raw, date_str):
    items = []
    # Main recovery record
    if raw["recovery"]:
        items.append({"source": "whoop", "hrv": ..., "recovery_score": ..., ...})
    # Workout sub-records
    for i, w in enumerate(raw.get("workouts", [])):
        items.append({"source": "whoop", "sk_suffix": f"#WORKOUT#{w['id']}", ...})
    return items

def lambda_handler(event, context):
    return run_ingestion(config, authenticate, fetch_day, transform, event, context)
```

## Example Migration: Habitify (supplement bridge post-hook)

```python
# lambdas/habitify_handler.py
config = IngestionConfig(
    source_name="habitify",
    secret_id="life-platform/habitify",  # via Secrets Manager
    enable_gap_detection=True,
)

def post_store(items, date_str):
    # Bridge supplements from habit completion data
    bridge_supplements(items[0])  # Existing logic, unchanged

def lambda_handler(event, context):
    return run_ingestion(config, authenticate, fetch_day, transform,
                         event, context, post_store_fn=post_store)
```

---

## Migration Plan

| Phase | Lambdas | Effort | Notes |
|-------|---------|--------|-------|
| 0 | Framework only | Done | `ingestion_framework.py` written |
| 1 | weather | 1 hr | Simplest — no auth, no gap detection. Proof of concept. |
| 2 | whoop, strava, garmin | 3-4 hr | OAuth + gap detection. Tests token writeback. Garmin has native deps (keep separate zip). |
| 3 | withings, eightsleep, habitify | 3-4 hr | Withings fragile OAuth. Habitify supplement bridge. Eight Sleep JWT auth. |
| 4 | todoist, notion, macrofactor, apple_health, dropbox_poll, health_auto_export | 3-4 hr | Mixed: API key auth, CSV parsing, webhooks. HAE is webhook (different pattern — may not fit framework). |

### Migration Per-Lambda Checklist

- [ ] Create `{source}_handler.py` with config + 3 callbacks
- [ ] Verify `lambda_handler` signature matches AWS handler config
- [ ] Run smoke test: `aws lambda invoke --function-name {name} --payload '{}' /tmp/test.json`
- [ ] Verify DDB record written for today
- [ ] Verify S3 raw archive written
- [ ] Verify gap detection (if enabled): delete one day's record, re-run, verify backfill
- [ ] Keep old `{source}_lambda.py` as `.py.archived` for 2 weeks
- [ ] Update `ci/lambda_map.json` with new source file

### Lambdas That May NOT Fit the Framework

| Lambda | Issue | Recommendation |
|--------|-------|----------------|
| `health-auto-export-webhook` | Webhook receiver, not poll-based. Processes arbitrary payloads. | Keep separate. Framework is for poll-based ingestion. |
| `dropbox-poll` | Polls Dropbox (not a health API), triggers `macrofactor-data-ingestion`. | Keep separate — it's a trigger, not an ingester. |
| `apple-health-ingestion` | S3 XML trigger, parses large XML exports. | Keep separate — file-trigger pattern is fundamentally different. |

**Target:** 10 of 13 Lambdas on framework. 3 keep custom handlers.

---

## Risk Mitigation

1. **Parallel deploy:** Keep old Lambda code during migration. New handler deployed as separate Lambda for testing before cutover.
2. **Framework in Layer:** Add `ingestion_framework.py` to shared Lambda Layer. Single update point.
3. **Feature flags:** Add `USE_FRAMEWORK=true` env var. Handler checks and delegates to old or new path.
4. **Rollback:** Old `.py.archived` files restore in <1 minute via deploy_lambda.sh.
