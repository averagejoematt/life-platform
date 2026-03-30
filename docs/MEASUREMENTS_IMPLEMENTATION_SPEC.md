# Body Measurements — Implementation Spec
**Version:** 1.0  
**Date:** 2026-03-29  
**Platform version at time of writing:** v4.3.1  
**Prepared by:** All-Boards convening (Personal + Technical + Product)

---

## Overview

Add `measurements` as a new periodic data source to the Life Platform. This is tape-measure body measurements captured every 4–8 weeks by Brittany. The import mechanism is a CSV (or Excel) file drop to S3, mirroring the MacroFactor import pattern. No API, no OAuth, no secrets needed.

**Key decisions:**
- Source key: `measurements`
- Unit: inches (locked — never cm)
- Cadence: every 4–8 weeks (not daily, not scheduled)
- Import: CSV/Excel → S3 → Lambda trigger
- `height_inches` is already in the profile (`USER#matthew` / `PROFILE#v1` = **69**) — read from there at import time
- Raw measurements never go public — only the derived waist-to-height ratio trend
- Photos: not part of this implementation (manual folder system by Brittany is sufficient)

---

## 1. DynamoDB Schema

**PK:** `USER#matthew#SOURCE#measurements`  
**SK:** `DATE#YYYY-MM-DD` (one item per measurement session)

```python
{
    # Identity
    "pk": "USER#matthew#SOURCE#measurements",
    "sk": "DATE#2026-03-29",          # session date
    "unit": "in",                      # inches — always
    "session_number": 1,               # sequential, computed at import
    "measured_by": "brittany",

    # TRUNK
    "neck_in": Decimal("17.0"),
    "chest_in": Decimal("49.0"),
    "waist_narrowest_in": Decimal("49.5"),   # ★ Attia priority
    "waist_navel_in": Decimal("52.0"),       # ★ Attia priority — visceral fat proxy
    "hips_in": Decimal("55.5"),

    # ARMS
    "bicep_relaxed_left_in": Decimal("16.0"),
    "bicep_relaxed_right_in": Decimal("17.0"),
    "bicep_flexed_left_in": Decimal("17.5"),
    "bicep_flexed_right_in": Decimal("18.0"),

    # LEGS
    "calf_left_in": Decimal("19.0"),
    "calf_right_in": Decimal("19.0"),
    "thigh_left_in": Decimal("30.5"),        # ★ Sarah Chen priority — mid-thigh
    "thigh_right_in": Decimal("30.0"),

    # DERIVED — computed at import time, stored on item
    "waist_height_ratio": Decimal("0.7536"),  # waist_navel_in / 69 — target <0.5
    "bilateral_symmetry_bicep_in": Decimal("1.0"),   # abs(right - left relaxed)
    "bilateral_symmetry_thigh_in": Decimal("0.5"),   # abs(right - left)
    "limb_avg_in": Decimal("23.375"),         # avg(bicep_relaxed L/R, thigh L/R)
    "trunk_sum_in": Decimal("101.5"),         # waist_navel + waist_narrowest

    # Metadata
    "ingested_at": "2026-03-29T19:00:00Z",
    "source_file": "s3://matthew-life-platform/imports/measurements/2026-03-29.csv",
}
```

**Derived field computation:**
```python
height_in = 69  # from profile PROFILE#v1 height_inches
waist_height_ratio = round(waist_navel_in / height_in, 4)
bilateral_symmetry_bicep_in = abs(bicep_relaxed_right_in - bicep_relaxed_left_in)
bilateral_symmetry_thigh_in = abs(thigh_right_in - thigh_left_in)
limb_avg_in = (bicep_relaxed_left_in + bicep_relaxed_right_in + thigh_left_in + thigh_right_in) / 4
trunk_sum_in = waist_navel_in + waist_narrowest_in
```

---

## 2. CSV Import Format

The file Brittany sends each session. Claude Code should accept both `.csv` and `.xlsx` (auto-detect by extension, use openpyxl for xlsx).

**S3 path:** `s3://matthew-life-platform/imports/measurements/YYYY-MM-DD.csv`  
The filename date becomes the session date / SK.

**CSV column layout** (header row + one data row):

```csv
date,neck_in,chest_in,waist_narrowest_in,waist_navel_in,hips_in,bicep_relaxed_left_in,bicep_relaxed_right_in,bicep_flexed_left_in,bicep_flexed_right_in,calf_left_in,calf_right_in,thigh_left_in,thigh_right_in,notes
2026-03-29,17.0,49.0,49.5,52.0,55.5,16.0,17.0,17.5,18.0,19.0,19.0,30.5,30.0,Day 1 baseline
```

**Notes on the CSV:**
- All values in inches (decimal, e.g. `17.5` not fractions)
- The `date` column overrides the filename date if present (filename is fallback)
- `notes` is optional free text
- For `.xlsx` input, the Lambda reads the first sheet, first data row after header

---

## 3. Lambda — `measurements-ingestion`

**File:** `lambdas/measurements_ingestion_lambda.py`  
**Trigger:** S3 ObjectCreated on `matthew-life-platform` bucket, prefix `imports/measurements/`  
**Memory:** 256 MB (no ML, no heavy deps — can be lower than default)  
**Timeout:** 30s  
**Region:** us-west-2

### Logic:

```python
def lambda_handler(event, context):
    # 1. Parse S3 event — get bucket + key
    # 2. Infer session date from filename (e.g. "imports/measurements/2026-03-29.csv" → "2026-03-29")
    # 3. Read file from S3 (csv or xlsx, detect by extension)
    # 4. Parse measurement values → validate all required fields present
    # 5. Fetch height_inches from profile:
    #       table.get_item(Key={"pk": "USER#matthew", "sk": "PROFILE#v1"})["Item"]["height_inches"]
    # 6. Compute session_number (query existing measurements records, count + 1)
    # 7. Compute all derived fields
    # 8. Write item to DynamoDB
    # 9. Log success with derived fields for verification
```

### Required fields (Lambda should error if missing):
`waist_narrowest_in`, `waist_navel_in` — the two Attia-priority fields. All others are logged as warnings if missing but don't block the write.

### Dependencies:
- `boto3` (already in Lambda runtime)
- `csv` (stdlib)
- `openpyxl` — for xlsx support. Include in Lambda zip or Lambda layer.

---

## 4. Freshness Checker Update

**File:** `lambdas/freshness_checker_lambda.py`

### Changes:

**1. Add to `SOURCES` dict:**
```python
SOURCES = {
    # ... existing sources ...
    "measurements": "Tape measure check-ins",
}
```

**2. Add to `SOURCE_STALE_HOURS`:**
```python
SOURCE_STALE_HOURS = {
    "food_delivery": 90 * 24,   # existing
    "measurements": 60 * 24,    # 60 days — one missed session before alert
}
```

**3. Add to `FIELD_COMPLETENESS_CHECKS`:**
```python
FIELD_COMPLETENESS_CHECKS = {
    # ... existing ...
    "measurements": ["waist_navel_in", "waist_narrowest_in", "thigh_left_in"],
}
```

---

## 5. MCP Tools

**Module:** Create `mcp/tools_measurements.py` (new file)  
Register both tools in the `TOOLS` dict in `mcp_server.py` or `mcp/registry.py`.  
**Run before MCP deploy:** `python3 -m pytest tests/test_mcp_registry.py -v`

---

### Tool 1: `get_measurements`

**Purpose:** Returns all measurement sessions in a date range, with all raw and derived fields.

**Parameters:**
```python
{
    "latest_only": bool,        # default False — if True, returns only most recent session
    "start_date": str,          # YYYY-MM-DD, default 12 months ago
    "end_date": str,            # YYYY-MM-DD, default today
}
```

**Returns:**
```python
{
    "sessions": [
        {
            "date": "2026-03-29",
            "session_number": 1,
            "measurements": { ...all raw fields... },
            "derived": {
                "waist_height_ratio": 0.7536,
                "waist_height_ratio_target": 0.5,
                "bilateral_symmetry_bicep_in": 1.0,
                "bilateral_symmetry_thigh_in": 0.5,
                "trunk_sum_in": 101.5,
                "limb_avg_in": 23.375,
            }
        }
    ],
    "session_count": 1,
    "date_range": { "start": "...", "end": "..." },
    "board_note": "Dr. Peter Attia: Current waist-to-height ratio is 0.754 — target is <0.50 ..."
}
```

**Board note logic:** If `waist_height_ratio > 0.6` → Attia note about visceral risk. If `bilateral_symmetry_bicep_in > 1.0` → Norton note about asymmetric loading. Always include Attia's target (<0.5) and current ratio.

---

### Tool 2: `get_measurement_trends`

**Purpose:** Cross-session analysis — deltas from baseline, rate of change, recomposition score, projection.

**Parameters:**
```python
{
    "include_projection": bool,   # default True — project W/H ratio goal date
}
```

**Requires:** ≥2 sessions for deltas and trends. With only 1 session, return baseline snapshot and note "trend analysis available after session 2."

**Returns:**
```python
{
    "baseline": { "date": "2026-03-29", "session_number": 1, ... },
    "latest": { "date": "...", "session_number": N, ... },
    "sessions_count": N,
    "weeks_elapsed": float,

    "deltas_from_baseline": {
        "waist_navel_in": -2.5,          # negative = smaller = progress on trunk
        "waist_narrowest_in": -2.0,
        "hips_in": -1.5,
        "bicep_relaxed_left_in": 0.25,   # positive on limbs = preserved muscle
        "thigh_left_in": 0.0,
        # ... all 13 measurements
        "waist_height_ratio": -0.036,
    },

    "rate_of_change_per_4_weeks": {
        "waist_navel_in": -1.25,          # inches per 4-week cycle
        "waist_height_ratio": -0.018,
    },

    "recomposition_score": {
        # per session: True if trunk shrinking AND limbs holding (>= -0.25" delta)
        "sessions": [{"date": "...", "recomposition": True}, ...],
        "recomposition_rate": 0.75,      # 75% of sessions were recomposition-positive
        "verdict": "Strong — trunk reducing while limbs hold",
    },

    "bilateral_symmetry_trend": {
        "bicep": [{"date": "...", "delta_in": 1.0}, ...],
        "flag": True,   # True if latest > 1.0 and growing
    },

    "projection": {
        # only if include_projection=True and >=2 sessions
        "waist_height_ratio_current": 0.7536,
        "waist_height_ratio_target": 0.5,
        "ratio_remaining": 0.2536,
        "rate_per_week": -0.004,
        "weeks_to_target": 63,
        "projected_date": "2027-07-15",
        "confidence": "low",   # low until >=4 sessions
        "note": "Projection requires >=4 sessions for reliable confidence. Based on 2 sessions.",
    },

    "withings_correlation_note": str,  # if Withings lean mass data available in same window

    "board_assessment": {
        "attia": str,
        "norton": str,
        "sarah_chen": str,
        "okafor": str,
    }
}
```

---

### Body Comp Snapshot Injection

**File:** `mcp/tools_health.py` (or wherever `get_body_composition_snapshot` lives)

In `get_body_composition_snapshot`, after fetching Withings and DEXA data:

```python
# Inject measurements context if recent session exists (within 60 days)
measurements_record = get_latest_measurements_record(table, user_id, within_days=60)
if measurements_record:
    result["tape_measure"] = {
        "session_date": measurements_record["sk"].replace("DATE#", ""),
        "waist_height_ratio": float(measurements_record.get("waist_height_ratio", 0)),
        "waist_navel_in": float(measurements_record.get("waist_navel_in", 0)),
        "waist_narrowest_in": float(measurements_record.get("waist_narrowest_in", 0)),
        "trunk_sum_in": float(measurements_record.get("trunk_sum_in", 0)),
        "attia_note": f"Waist-to-height ratio: {float(measurements_record.get('waist_height_ratio', 0)):.3f} (target <0.500)",
    }
```

---

## 6. Website Updates

### Platform page — data sources list

Add `measurements` to the data sources list on the platform/observatory page. Label: **"Tape Measure Check-ins"** (not "Body Measurements").

### public_stats.json / site-stats-refresh

The `data_sources` count should increment from 25 → 26 once measurements is live. Confirm `site-stats-refresh` Lambda (or whichever Lambda writes `public_stats.json`) picks up the new source. If it reads from the `SOURCES` dict in freshness_checker or a config file, adding `measurements` there is sufficient. If it's hardcoded, update the count.

**CloudFront invalidation required after site update:**
```bash
aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths "/site/public_stats.json" "/platform/*"
```

### Phase 2 (after session 2 — not part of this build):
Surface waist-to-height ratio trend card on the Live Stats or homepage. Not in scope now.

---

## 7. CDK — IAM Role

**Stack:** LifePlatformIngestion  
**Role name:** `MeasurementsIngestionRole`  
**Policy:**
```python
# DynamoDB write — scoped to measurements partition
dynamodb.grant_write_data(measurements_ingestion_fn)

# S3 read — scoped to imports/measurements/ prefix only
bucket.grant_read(measurements_ingestion_fn, "imports/measurements/*")

# Also needs read of profile for height_inches — use existing pattern
# (same as other ingestion Lambdas that read profile)
```

**S3 trigger:**
```python
measurements_ingestion_fn.add_event_source(
    S3EventSource(
        bucket,
        events=[s3.EventType.OBJECT_CREATED],
        filters=[s3.NotificationKeyFilter(prefix="imports/measurements/")]
    )
)
```

---

## 8. Day 1 Seed Data

Session 1 measurements from 2026-03-29 (captured today by Brittany):

| Measurement | Value (in) |
|---|---|
| Neck | 17.0 |
| Chest | 49.0 |
| Waist (narrowest) | 49.5 |
| Waist (navel) | 52.0 |
| Hips | 55.5 |
| Bicep relaxed left | 16.0 |
| Bicep relaxed right | 17.0 |
| Bicep flexed left | 17.5 |
| Bicep flexed right | 18.0 |
| Calf left | 19.0 |
| Calf right | 19.0 |
| Thigh left | 30.5 |
| Thigh right | 30.0 |

**Derived fields for verification:**
- `waist_height_ratio` = 52.0 / 69 = **0.7536** (target: <0.500)
- `bilateral_symmetry_bicep_in` = |17.0 - 16.0| = **1.0** (Norton flag threshold)
- `bilateral_symmetry_thigh_in` = |30.0 - 30.5| = **0.5**
- `trunk_sum_in` = 52.0 + 49.5 = **101.5**
- `limb_avg_in` = (16.0 + 17.0 + 30.5 + 30.0) / 4 = **23.375**

The seed can be done two ways — either:
1. Upload the CSV to `s3://matthew-life-platform/imports/measurements/2026-03-29.csv` and let the Lambda trigger fire, OR
2. Write a `seeds/seed_measurements.py` script that writes directly to DynamoDB (useful for testing before the Lambda is deployed)

Recommend option 2 first (seed script) to validate the schema, then option 1 to test the full import pipeline.

---

## 9. Documentation Updates Required

After implementation, update these docs:

| Doc | What to update |
|---|---|
| `docs/SCHEMA.md` | Add `measurements` source section with full field reference |
| `docs/ARCHITECTURE.md` | Update data source count (25 → 26), add measurements to ingest layer table |
| `docs/MCP_TOOL_CATALOG.md` | Add `get_measurements` and `get_measurement_trends` entries |
| `CHANGELOG.md` | Add version entry (suggest v4.4.0 — new data source) |
| `ci/lambda_map.json` | Add `measurements-ingestion` Lambda entry |
| `docs/DECISIONS.md` | Add ADR: measurements as periodic manual import, CSV/S3 pattern, no API |

---

## 10. Testing Checklist

```bash
# 1. Unit tests
python3 -m pytest tests/ -v

# 2. MCP registry — REQUIRED before MCP deploy
python3 -m pytest tests/test_mcp_registry.py -v

# 3. Manual verification after seed
# Run get_measurements via MCP — should return session 1 with all derived fields
# Verify waist_height_ratio = 0.7536
# Verify session_number = 1

# 4. Freshness checker — verify measurements appears in output
# Trigger freshness_checker manually and confirm "Tape measure check-ins" appears as fresh

# 5. Source count — verify public_stats.json shows data_sources: 26
```

---

## 11. Build Sequence (in order)

1. `seeds/seed_measurements.py` — write Day 1 data directly to DynamoDB. Validate schema.
2. `lambdas/measurements_ingestion_lambda.py` — full Lambda with S3 trigger support.
3. `deploy/deploy_lambda.sh measurements-ingestion` — deploy Lambda.
4. Update CDK stack — add S3 trigger + IAM role. `cdk deploy LifePlatformIngestion`.
5. `lambdas/freshness_checker_lambda.py` — add source + threshold + field checks. Deploy.
6. `mcp/tools_measurements.py` — two tools. Register in TOOLS dict.
7. `python3 -m pytest tests/test_mcp_registry.py -v` — must pass before MCP deploy.
8. MCP deploy (manual zip).
9. `mcp/tools_health.py` — inject measurements context into `get_body_composition_snapshot`.
10. MCP redeploy.
11. Platform page + public_stats.json update → site deploy → CloudFront invalidation.
12. Verify: data source count = 26 on live site.
13. Update all docs. `CHANGELOG.md` → `sync_doc_metadata.py --apply` → git commit.

---

## Reference: Platform Context

- **DynamoDB table:** `life-platform` (us-west-2)
- **S3 bucket:** `matthew-life-platform`
- **CloudFront distribution:** `E3S424OXQZ8NBE`
- **MCP Lambda:** `life-platform-mcp` — manual zip deploy only (never via `deploy_lambda.sh`)
- **Height in profile:** `height_inches = 69` (confirmed in DynamoDB 2026-03-29)
- **Profile key:** `pk=USER#matthew, sk=PROFILE#v1`
- **MacroFactor import pattern** (S3 trigger reference): `lambdas/macrofactor_data_ingestion_lambda.py`
- **Food delivery pattern** (periodic source with custom stale threshold reference): `freshness_checker_lambda.py` `SOURCE_STALE_HOURS["food_delivery"]`
- **Platform version:** v4.3.1 at time of this spec

---

*Spec prepared: 2026-03-29. All-boards convening: Personal Board (Attia, Norton, Sarah Chen, Okafor, Maya, Murthy), Technical Board (Architecture, Observability, MCP, Security, Cost), Product Board (Product, UX, Content, Data Intelligence).*
