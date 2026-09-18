"""
Measurements Ingestion Lambda — periodic body tape measurements via CSV/Excel file drop.

Trigger: S3 ObjectCreated on matthew-life-platform, prefix imports/measurements/
Cadence: every 4-8 weeks (manual upload by Partner)
Schema: USER#matthew#SOURCE#measurements / DATE#YYYY-MM-DD

#473 (B-4/X-12, 2026-07-04): multi-row CSVs now ingest EVERY session row (the old
parser silently used rows[0] only), and session_number derives from the session's
date rank among all stored sessions — stable and monotonic across re-imports (the
old COUNT+1 drifted on every re-import). Records stamp phase (#482/X-6).

#3662: `measured_by` is read from an optional `measured_by` CSV/Excel column
(alongside `date`/`notes` — never a MEASUREMENT_FIELDS numeric). A row that
doesn't carry the column falls back to the literal string `"unrecorded"` — never
to a fabricated identity (ADR-104: an unknown measurer must read as unknown, not
be papered over with a plausible-sounding default). The prior code hard-coded
`"partner"` unconditionally, which the CSV parser could never override and which
was flatly false on the one session actually ingested this way (self-measured,
corrected by hand in DDB after the fact — see that row's own `notes`).

#3663: an unmodelled CSV/Excel column is a NAMED FAILURE, not a silent drop.
`_row_to_session` reads only `MEASUREMENT_FIELDS`, so any other numeric column
used to vanish with no warning and an exit-0 "success" — the 2026-09-06 session
measured 19 sites into a 13-site schema and the six surplus values survived only
because a human pasted them into `notes` by hand. Capture-unfiltered is the FIRST
ordered step of docs/NEW_SIGNAL_PLAYBOOK.md (ADR-154), so the six measured sites
are now modelled, and `_unmodelled_columns` names every header the parser cannot
store; the handler refuses the file (422) listing them rather than writing a
partial row and reporting a clean success. Nothing is written on that path, so
re-uploading the same object after the schema is widened is a clean re-ingest.

The derived fields that enumerate limbs now STATE their sites (`LIMB_AVG_SITES`,
`BILATERAL_SYMMETRY_PAIRS`) instead of implying them from four inline locals, and
each written row stamps `limb_avg_sites` so a stored average says what it averaged.
Adding a site to MEASUREMENT_FIELDS (as #3663 does, twice for limbs) therefore
cannot silently redefine `limb_avg_in`: the six new sites are deliberately NOT in
`LIMB_AVG_SITES`, so the number stays the same four-site mean the 2026-03-29 and
2026-09-06 rows already carry and the series remains comparable.
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
from boto3.dynamodb.conditions import Key
from common.pacific_time import pacific_today  # #2811: THE Pacific day helper — DATE# keys are Pacific days

try:
    from common.platform_logger import get_logger

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
MEASURED_BY_UNRECORDED = "unrecorded"  # #3662: stated absence, never a fabricated identity (ADR-104)
MEASUREMENT_FIELDS = [
    "neck_in",
    "shoulder_width_in",  # #3663
    "chest_in",
    "waist_narrowest_in",
    "waist_navel_in",
    "waist_iliac_crest_in",  # #3663 — the third standard waist landmark
    "hips_in",
    "bicep_relaxed_left_in",
    "bicep_relaxed_right_in",
    "bicep_flexed_left_in",
    "bicep_flexed_right_in",
    "forearm_max_left_in",  # #3663
    "forearm_max_right_in",  # #3663
    "calf_left_in",
    "calf_right_in",
    "thigh_left_in",  # mid-thigh
    "thigh_right_in",  # mid-thigh
    "thigh_upper_left_in",  # #3663 — a DIFFERENT site from thigh_left_in (mid)
    "thigh_upper_right_in",  # #3663
]

# Columns a measurements file may carry that are NOT a stored numeric site.
# Everything else in a header row must be a MEASUREMENT_FIELDS name or the file
# is refused by name (#3663) — `_row_to_session` can only read the fields it knows.
NON_MEASUREMENT_COLUMNS = frozenset({"date", "notes", "measured_by"})

# ── The derived limb enumerations, STATED (#3663) ────────────────────────────
# These four sites, and only these four, are what `limb_avg_in` averages. They
# are named here rather than implied by four inline locals so that adding a site
# to MEASUREMENT_FIELDS cannot silently change what an existing stored average
# means. #3663 adds four limb sites (both forearms, both upper thighs) and
# deliberately leaves them OUT: `limb_avg_in` stays the bicep-relaxed + mid-thigh
# mean that every stored row already carries, so the series stays comparable.
# Widening it is a deliberate act that must renumber history, not a side effect.
# `tests/test_measurement_columns_3663.py` asserts both the membership (every
# named site is a field actually stored) and the arithmetic.
LIMB_AVG_SITES = (
    "bicep_relaxed_left_in",
    "bicep_relaxed_right_in",
    "thigh_left_in",
    "thigh_right_in",
)

# Each bilateral-symmetry number names its own (left, right) pair — same reason.
BILATERAL_SYMMETRY_PAIRS = {
    "bilateral_symmetry_bicep_in": ("bicep_relaxed_left_in", "bicep_relaxed_right_in"),
    "bilateral_symmetry_thigh_in": ("thigh_left_in", "thigh_right_in"),
}


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
    # #3662: read from the row if the column exists; a blank/missing column is a
    # stated "unrecorded", never the old hard-coded "partner" the CSV couldn't override.
    result["measured_by"] = str(row_dict.get("measured_by") or "").strip() or MEASURED_BY_UNRECORDED
    return result


def _unmodelled_columns(headers) -> list[str]:
    """Header names this parser cannot store, in file order (#3663).

    A column that is neither a MEASUREMENT_FIELDS site nor one of the
    NON_MEASUREMENT_COLUMNS is a value that was measured and would be dropped.
    Blank/None header cells (trailing commas, empty spreadsheet columns) carry
    no value and are not reported. Names are returned so the caller can say
    WHICH columns it refused — a count alone is not a named failure.

    Headers are compared EXACTLY as `_row_to_session` will key the row dict — no
    case-folding or trimming here — because a header this function normalises
    into a match that `row_dict.get(field)` then misses is the silent drop all
    over again. `Neck_in` or `neck_in ` are genuinely unstorable and are named.
    (`_parse_xlsx` lower-cases its headers before this call, so the spreadsheet
    path is normalised once, in the place that also builds the row dict.)
    """
    seen, out = set(), []
    for h in headers or []:
        name = "" if h is None else str(h)
        if not name.strip() or name in seen:
            continue
        seen.add(name)
        if name not in NON_MEASUREMENT_COLUMNS and name not in MEASUREMENT_FIELDS:
            out.append(name)
    return out


class UnmodelledColumnsError(ValueError):
    """Raised when a file carries a column the schema cannot store (#3663)."""

    def __init__(self, columns: list[str]):
        self.columns = columns
        super().__init__("unmodelled columns: " + ", ".join(columns))


def _parse_csv(content: str) -> list[dict]:
    """Parse CSV content into a list of session dicts — ALL rows (#473/X-12)."""
    reader = csv.DictReader(io.StringIO(content))
    rows = list(reader)
    if not rows:
        raise ValueError("CSV has no data rows")
    unmodelled = _unmodelled_columns(reader.fieldnames)
    if unmodelled:
        raise UnmodelledColumnsError(unmodelled)
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
    unmodelled = _unmodelled_columns(headers)
    if unmodelled:
        raise UnmodelledColumnsError(unmodelled)
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
    """Compute derived fields from raw measurements.

    The limb-enumerating numbers read their sites from LIMB_AVG_SITES /
    BILATERAL_SYMMETRY_PAIRS (#3663) — the enumeration is the contract, not an
    inline list of locals that a later schema addition could quietly widen.
    `limb_avg_sites` is stamped alongside `limb_avg_in` so a stored average
    carries the names of what it averaged.
    """
    derived = {}

    waist_navel = float(measurements.get("waist_navel_in", 0))
    waist_narrow = float(measurements.get("waist_narrowest_in", 0))

    if waist_navel > 0 and height_in > 0:
        derived["waist_height_ratio"] = Decimal(str(round(waist_navel / height_in, 4)))

    for out_field, (left_field, right_field) in BILATERAL_SYMMETRY_PAIRS.items():
        left = float(measurements.get(left_field, 0))
        right = float(measurements.get(right_field, 0))
        if left > 0 and right > 0:
            derived[out_field] = Decimal(str(round(abs(right - left), 2)))

    limb_sites = [f for f in LIMB_AVG_SITES if float(measurements.get(f, 0)) > 0]
    if limb_sites:
        limbs = [float(measurements[f]) for f in limb_sites]
        derived["limb_avg_in"] = Decimal(str(round(sum(limbs) / len(limbs), 3)))
        derived["limb_avg_sites"] = limb_sites

    if waist_navel > 0 and waist_narrow > 0:
        derived["trunk_sum_in"] = Decimal(str(round(waist_navel + waist_narrow, 2)))

    return derived


def _existing_session_dates() -> set[str]:
    """All stored session dates (DATE#-keyed), for date-rank numbering."""
    dates = set()
    kwargs = {
        "KeyConditionExpression": Key("pk").eq(PK) & Key("sk").begins_with("DATE#"),
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
        from ingestion.ingestion_framework import phase_for_date

        return phase_for_date(date_str)
    except ImportError:  # pragma: no cover — layer unavailable locally
        return "experiment"


def lambda_handler(event, context):
    if hasattr(logger, "set_date"):
        logger.set_date(pacific_today())

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
    # #3663: a column the schema cannot store ends the run by NAME. The old code
    # dropped it in `_row_to_session` and still returned 200 with the remaining
    # fields, so a measured value could disappear with nothing saying so. Nothing
    # is written on this path — widen MEASUREMENT_FIELDS (+ docs/SCHEMA.md) and
    # re-drop the same object to ingest it cleanly.
    try:
        if source_key.lower().endswith(".xlsx"):
            sessions = _parse_xlsx(content_bytes)
        else:
            sessions = _parse_csv(content_bytes.decode("utf-8"))
    except UnmodelledColumnsError as e:
        named = ", ".join(e.columns)
        logger.error(f"UNMODELLED COLUMNS in s3://{bucket}/{source_key} — refused, nothing written: {named}")
        return {
            "statusCode": 422,
            "body": json.dumps(
                {
                    "error": "unmodelled columns",
                    "unmodelled_columns": e.columns,
                    "sessions_written": 0,
                    "message": (
                        f"{len(e.columns)} column(s) in {source_key} are not stored by this schema ({named}). "
                        "Values were measured and would have been dropped — add them to MEASUREMENT_FIELDS "
                        "and docs/SCHEMA.md, then re-upload. Nothing was written."
                    ),
                }
            ),
        }

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
        measured_by = session.pop("measured_by", None) or MEASURED_BY_UNRECORDED
        missing = [f for f in REQUIRED_FIELDS if f not in session]
        if missing:
            errors.append(f"row {idx + 1} ({session_date}): missing required {missing}")
            continue
        all_dates.add(session_date)
        written.append((session_date, session, notes, measured_by))

    if not written:
        return {"statusCode": 400, "body": json.dumps({"error": "no ingestible rows", "row_errors": errors})}

    date_rank = {d: i + 1 for i, d in enumerate(sorted(all_dates))}

    results = []
    for session_date, measurements, notes, measured_by in written:
        derived = _compute_derived(measurements, height_in)
        item = {
            "pk": PK,
            "sk": f"DATE#{session_date}",
            "date": session_date,
            "unit": "in",
            "session_number": date_rank[session_date],
            "measured_by": measured_by,
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
