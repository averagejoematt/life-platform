"""
Measurements Ingestion Lambda — periodic body tape measurements via CSV/Excel file drop.

Trigger: S3 ObjectCreated on matthew-life-platform, prefix imports/measurements/
Cadence: every 4-8 weeks (manual upload by Brittany)
Schema: USER#matthew#SOURCE#measurements / DATE#YYYY-MM-DD
"""
import csv
import io
import json
import os
import re
import logging
import boto3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

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
    "neck_in", "chest_in", "waist_narrowest_in", "waist_navel_in", "hips_in",
    "bicep_relaxed_left_in", "bicep_relaxed_right_in",
    "bicep_flexed_left_in", "bicep_flexed_right_in",
    "calf_left_in", "calf_right_in", "thigh_left_in", "thigh_right_in",
]


def _to_decimal(val):
    """Convert a value to Decimal, return None if invalid."""
    if val is None or str(val).strip() == "":
        return None
    try:
        return Decimal(str(val).strip())
    except (InvalidOperation, ValueError):
        return None


def _parse_csv(content: str) -> dict:
    """Parse CSV content into a measurement dict."""
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        raise ValueError("CSV has no data rows")
    row = rows[0]  # Only first data row

    result = {}
    for field in MEASUREMENT_FIELDS:
        val = _to_decimal(row.get(field))
        if val is not None:
            result[field] = val

    result["date"] = row.get("date", "").strip() or None
    result["notes"] = row.get("notes", "").strip() or None
    return result


def _parse_xlsx(content_bytes: bytes) -> dict:
    """Parse Excel file into a measurement dict."""
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
    values = rows[1]

    row_dict = {headers[i]: values[i] for i in range(min(len(headers), len(values)))}

    result = {}
    for field in MEASUREMENT_FIELDS:
        val = _to_decimal(row_dict.get(field))
        if val is not None:
            result[field] = val

    result["date"] = str(row_dict.get("date", "")).strip() or None
    result["notes"] = str(row_dict.get("notes", "")).strip() or None
    return result


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


def lambda_handler(event, context):
    if hasattr(logger, 'set_date'):
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

    # Infer date from filename
    filename = source_key.split("/")[-1]
    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", filename)
    filename_date = date_match.group(1) if date_match else None

    # Read file
    resp = s3.get_object(Bucket=bucket, Key=source_key)
    content_bytes = resp["Body"].read()

    # Parse based on extension
    if source_key.lower().endswith(".xlsx"):
        measurements = _parse_xlsx(content_bytes)
    else:
        measurements = _parse_csv(content_bytes.decode("utf-8"))

    # Determine session date
    session_date = measurements.pop("date", None) or filename_date
    if not session_date:
        return {"statusCode": 400, "body": "Cannot determine session date from CSV or filename"}

    notes = measurements.pop("notes", None)

    # Validate required fields
    for field in REQUIRED_FIELDS:
        if field not in measurements:
            return {"statusCode": 400, "body": f"Missing required field: {field}"}

    # Fetch height from profile
    try:
        profile = table.get_item(Key={"pk": f"USER#{USER_ID}", "sk": "PROFILE#v1"}).get("Item", {})
        height_in = int(profile.get("height_inches", 69))
    except Exception:
        height_in = 69

    # Compute session number
    try:
        count_resp = table.query(
            KeyConditionExpression=boto3.dynamodb.conditions.Key("pk").eq(PK),
            Select="COUNT",
        )
        session_number = count_resp.get("Count", 0) + 1
    except Exception:
        session_number = 1

    # Compute derived fields
    derived = _compute_derived(measurements, height_in)

    # Build item
    item = {
        "pk": PK,
        "sk": f"DATE#{session_date}",
        "date": session_date,
        "unit": "in",
        "session_number": session_number,
        "measured_by": "brittany",
        **measurements,
        **derived,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "source_file": f"s3://{bucket}/{source_key}",
    }
    if notes:
        item["notes"] = notes

    table.put_item(Item=item)

    logger.info(f"Session {session_number} written: DATE#{session_date}")
    logger.info(f"  waist_height_ratio: {derived.get('waist_height_ratio', '?')}")
    logger.info(f"  trunk_sum: {derived.get('trunk_sum_in', '?')}")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "session_date": session_date,
            "session_number": session_number,
            "waist_height_ratio": str(derived.get("waist_height_ratio", "")),
            "fields_captured": len(measurements),
        }),
    }
