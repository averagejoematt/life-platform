"""
Measurements Ingestion Lambda — periodic body tape measurements via CSV/Excel file drop.

Trigger: S3 ObjectCreated on matthew-life-platform, prefix imports/measurements/
Cadence: every 4-8 weeks (manual upload by Partner)
Schema: USER#matthew#SOURCE#measurements / DATE#YYYY-MM-DD

#473 (B-4/X-12, 2026-07-04): multi-row CSVs now ingest EVERY session row (the old
parser silently used rows[0] only), and session_number derives from the session's
date rank among all stored sessions — stable and monotonic across re-imports (the
old COUNT+1 drifted on every re-import). Records stamp phase (#482/X-6).
"""

import csv
import io
import json
import logging
import os
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import boto3

try:
    from platform_logger import get_logger

    logger = get_logger("measurements-ingestion")
except ImportError:
    logger = logging.getLogger("measurements-ingestion")
    logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TABLE_NAME)
s3 = boto3.client("s3", region_name=REGION)

PK = f"USER#{USER_ID}#SOURCE#measurements"

REQUIRED_FIELDS = ["waist_narrowest_in", "waist_navel_in"]
MEASUREMENT_FIELDS = [
    "neck_in",
    "chest_in",
    "waist_narrowest_in",
    "waist_navel_in",
    "hips_in",
    "bicep_relaxed_left_in",
    "bicep_relaxed_right_in",
    "bicep_flexed_left_in",
    "bicep_flexed_right_in",
    "calf_left_in",
    "calf_right_in",
    "thigh_left_in",
    "thigh_right_in",
]


def _parse_decimal_field(val):
    """Parse a CSV scalar string into a Decimal, return None if blank/invalid.

    Distinct contract from numeric.floats_to_decimal (#1207): this is a scalar
    STRING parser (strips whitespace, treats "" as None, catches InvalidOperation)
    for measurement CSV cells — not a recursive float->Decimal walker, so it is
    deliberately not consolidated into the canonical helper.
    """
    if val is None or str(val).strip() == "":
        return None
    try:
        return Decimal(str(val).strip())
    except (InvalidOperation, ValueError):
        return None


def _row_to_session(row_dict: dict) -> dict:
    """Normalize one parsed row (str keys) into a session dict."""
    result = {}
    for field in MEASUREMENT_FIELDS:
        val = _parse_decimal_field(row_dict.get(field))
        if val is not None:
            result[field] = val
    result["date"] = str(row_dict.get("date") or "").strip() or None
    result["notes"] = str(row_dict.get("notes") or "").strip() or None
    return result


def _parse_csv(content: str) -> list[dict]:
    """Parse CSV content into a list of session dicts — ALL rows (#473/X-12)."""
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        raise ValueError("CSV has no data rows")
    return [_row_to_session(row) for row in rows]


def _parse_xlsx(content_bytes: bytes) -> list[dict]:
    """Parse Excel file into a list of session dicts — ALL rows (#473/X-12)."""
    try:
        import openpyxl
    except ImportError:
        raise ImportError("openpyxl not available — upload as CSV instead")

    wb = openpyxl.load_workbook(io.BytesIO(content_bytes), read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 2:
        raise ValueError("Excel file needs header row + at least one data row")

    headers = [str(h).strip().lower() if h else "" for h in rows[0]]
    sessions = []
    for values in rows[1:]:
        if values is None or all(v is None or str(v).strip() == "" for v in values):
            continue  # skip blank trailing rows
        row_dict = {headers[i]: values[i] for i in range(min(len(headers), len(values)))}
        sessions.append(_row_to_session(row_dict))
    if not sessions:
        raise ValueError("Excel file has no non-empty data rows")
    return sessions


def _compute_derived(measurements: dict, height_in: int) -> dict:
    """Compute derived fields from raw measurements."""
    derived = {}

    waist_navel = float(measurements.get("waist_navel_in", 0))
    waist_narrow = float(measurements.get("waist_narrowest_in", 0))

    if waist_navel > 0 and height_in > 0:
        derived["waist_height_ratio"] = Decimal(str(round(waist_navel / height_in, 4)))

    bl = float(measurements.get("bicep_relaxed_left_in", 0))
    br = float(measurements.get("bicep_relaxed_right_in", 0))
    if bl > 0 and br > 0:
        derived["bilateral_symmetry_bicep_in"] = Decimal(str(round(abs(br - bl), 2)))

    tl = float(measurements.get("thigh_left_in", 0))
    tr = float(measurements.get("thigh_right_in", 0))
    if tl > 0 and tr > 0:
        derived["bilateral_symmetry_thigh_in"] = Decimal(str(round(abs(tr - tl), 2)))

    limbs = [v for v in [bl, br, tl, tr] if v > 0]
    if limbs:
        derived["limb_avg_in"] = Decimal(str(round(sum(limbs) / len(limbs), 3)))

    if waist_navel > 0 and waist_narrow > 0:
        derived["trunk_sum_in"] = Decimal(str(round(waist_navel + waist_narrow, 2)))

    return derived


def _existing_session_dates() -> set[str]:
    """All stored session dates (DATE#-keyed), for date-rank numbering."""
    dates = set()
    kwargs = {
        "KeyConditionExpression": boto3.dynamodb.conditions.Key("pk").eq(PK) & boto3.dynamodb.conditions.Key("sk").begins_with("DATE#"),
        "ProjectionExpression": "sk",
    }
    while True:
        resp = table.query(**kwargs)
        for it in resp.get("Items", []):
            dates.add(it["sk"].replace("DATE#", "")[:10])
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return dates


def _phase_for(date_str: str) -> str:
    """#482/X-6: standalone writer stamps phase like the framework does."""
    try:
        from ingestion_framework import phase_for_date

        return phase_for_date(date_str)
    except ImportError:  # pragma: no cover — layer unavailable locally
        return "experiment"


def lambda_handler(event, context):
    if hasattr(logger, "set_date"):
        logger.set_date(datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    # Parse S3 event
    if "Records" in event:
        record = event["Records"][0]
        bucket = record["s3"]["bucket"]["name"]
        source_key = record["s3"]["object"]["key"]
    elif "bucket" in event and "key" in event:
        bucket, source_key = event["bucket"], event["key"]
    else:
        return {"statusCode": 400, "body": "No S3 record in event"}

    logger.info(f"Processing s3://{bucket}/{source_key}")

    # Infer date from filename (fallback for single-session files without a date column)
    filename = source_key.split("/")[-1]
    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", filename)
    filename_date = date_match.group(1) if date_match else None

    # Read file
    resp = s3.get_object(Bucket=bucket, Key=source_key)
    content_bytes = resp["Body"].read()

    # Parse based on extension — ALL rows (#473/X-12)
    if source_key.lower().endswith(".xlsx"):
        sessions = _parse_xlsx(content_bytes)
    else:
        sessions = _parse_csv(content_bytes.decode("utf-8"))

    # Fetch height from profile
    try:
        profile = table.get_item(Key={"pk": f"USER#{USER_ID}", "sk": "PROFILE#v1"}).get("Item", {})
        height_in = int(profile.get("height_inches", 69))
    except Exception:
        height_in = 69

    # #473/X-12: session_number = the session date's rank among ALL sessions
    # (stored + this file), 1-indexed by date. Stable across re-imports —
    # re-uploading the same file yields the same numbers, and a backfilled
    # older session renumbers correctly instead of appending COUNT+1.
    try:
        all_dates = _existing_session_dates()
    except Exception as e:
        logger.warning(f"session-date query failed ({e}) — ranking within this file only")
        all_dates = set()

    written = []
    errors = []
    for idx, session in enumerate(sessions):
        session = dict(session)
        session_date = session.pop("date", None) or (filename_date if len(sessions) == 1 else None)
        if not session_date:
            errors.append(f"row {idx + 1}: no date column and no filename date")
            continue
        notes = session.pop("notes", None)
        missing = [f for f in REQUIRED_FIELDS if f not in session]
        if missing:
            errors.append(f"row {idx + 1} ({session_date}): missing required {missing}")
            continue
        all_dates.add(session_date)
        written.append((session_date, session, notes))

    if not written:
        return {"statusCode": 400, "body": json.dumps({"error": "no ingestible rows", "row_errors": errors})}

    date_rank = {d: i + 1 for i, d in enumerate(sorted(all_dates))}

    results = []
    for session_date, measurements, notes in written:
        derived = _compute_derived(measurements, height_in)
        item = {
            "pk": PK,
            "sk": f"DATE#{session_date}",
            "date": session_date,
            "unit": "in",
            "session_number": date_rank[session_date],
            "measured_by": "partner",
            **measurements,
            **derived,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "source_file": f"s3://{bucket}/{source_key}",
            "phase": _phase_for(session_date),
        }
        if notes:
            item["notes"] = notes

        table.put_item(Item=item)
        logger.info(f"Session {date_rank[session_date]} written: DATE#{session_date}")
        results.append(
            {
                "session_date": session_date,
                "session_number": date_rank[session_date],
                "waist_height_ratio": str(derived.get("waist_height_ratio", "")),
                "fields_captured": len(measurements),
            }
        )

    if errors:
        logger.warning(f"Rows skipped: {errors}")

    return {
        "statusCode": 200,
        "body": json.dumps({"sessions_written": len(results), "sessions": results, "row_errors": errors}),
    }
