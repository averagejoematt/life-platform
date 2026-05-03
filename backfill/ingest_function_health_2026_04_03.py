#!/usr/bin/env python3
"""
ingest_function_health_2026_04_03.py — One-off ingestion of the April 2026 Function Health draw.

Imports structured biomarker data from `draw_2026_04_03.py` (carefully extracted from PDFs),
validates against known protocol reference values, then writes:

  1. A single DynamoDB item under USER#matthew#SOURCE#labs / DATE#2026-04-03
     containing all 133 biomarkers + provenance metadata + S3 key references.

  2. Six raw artifact files to S3 under raw/matthew/labs/2026-04-03/:
       - standard_panel.pdf
       - nfl_panel.pdf
       - galleri_corrected.pdf  (canonical Quest corrected report)
       - galleri_grail_original.pdf  (patient-facing GRAIL report)
       - clinician_notes.pdf
       - function_data_trends.pdf
       - supplement_protocol_v2.md

Schema matches the existing labs schema exactly (see mcp/labs_helpers.py and tools_labs.py).
This is the 8th draw — preceded by 7 historical draws from 2019-05-01 to 2025-04-17.

Usage:
  python3 backfill/ingest_function_health_2026_04_03.py --dry-run    # preview
  python3 backfill/ingest_function_health_2026_04_03.py              # commit (interactive prompt)
"""

import argparse
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Key

# --- Repo-relative import of the data file ---
SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))
import draw_2026_04_03 as draw

# --- AWS config ---
TABLE_NAME = "life-platform"
S3_BUCKET = "matthew-life-platform"
REGION = "us-west-2"
USER_ID = "matthew"
PK = f"USER#{USER_ID}#SOURCE#labs"
SK = f"DATE#{draw.DRAW_DATE}"

# --- Source PDF paths (local filesystem) ---
DATADROP = Path.home() / "Documents/Claude/life-platform/datadrops/functionhealth_drop"
SOURCE_FILES = {
    "standard_panel.pdf":          DATADROP / "Lab Results of Record.pdf",
    "cardio_iq_nfl_panel.pdf":     DATADROP / "Lab Results of Record (4).pdf",
    "galleri_corrected.pdf":       DATADROP / "Lab Results of Record (3).pdf",
    "galleri_grail_original.pdf":  DATADROP / "Lab Results of Record (1).pdf",
    "clinician_notes.pdf":         DATADROP / "2026-Clinician Notes.pdf",
    "function_data_trends.pdf":    DATADROP / "Function-Data Trends.pdf",
    "supplement_protocol_v2.md":   DATADROP / "Supplement_Protocol_2026-05_v2.md",
}
S3_PREFIX = f"raw/{USER_ID}/labs/{draw.DRAW_DATE}/"


# ─────────────────────────────────────────────────────────────────────────────
# VALIDATION — gate before any writes happen
# ─────────────────────────────────────────────────────────────────────────────

def validate_data():
    """Cross-check structured data against the supplement protocol's known values.

    Uses the VALIDATION_REFERENCES dict from draw_2026_04_03.py (15 reference values)
    rather than maintaining a duplicate list here.
    """
    errors = []
    refs = getattr(draw, "VALIDATION_REFERENCES", {})
    if not refs:
        errors.append("  ✗ draw.VALIDATION_REFERENCES is missing or empty")

    for key, expected in refs.items():
        bm = draw.BIOMARKERS.get(key)
        if not bm:
            errors.append(f"  ✗ MISSING biomarker: {key}")
            continue
        actual = bm.get("value_numeric")
        if actual != expected:
            errors.append(f"  ✗ {key}: extracted {actual}, expected {expected} (from supplement protocol)")

    if errors:
        print("VALIDATION FAILED — extracted data does not match supplement protocol references:")
        for err in errors:
            print(err)
        sys.exit(1)

    # Additional sanity checks
    if len(draw.BIOMARKERS) < 100:
        print(f"VALIDATION FAILED — only {len(draw.BIOMARKERS)} biomarkers extracted, expected 100+")
        sys.exit(1)

    # Ensure source PDFs exist
    missing_files = [k for k, v in SOURCE_FILES.items() if not v.exists()]
    if missing_files:
        print("VALIDATION FAILED — source files missing:")
        for f in missing_files:
            print(f"  ✗ {SOURCE_FILES[f]}")
        sys.exit(1)

    print(f"✓ All {len(refs)} protocol reference values match")
    print(f"✓ {len(draw.BIOMARKERS)} biomarkers structured")
    print(f"✓ All {len(SOURCE_FILES)} source files present")


# ─────────────────────────────────────────────────────────────────────────────
# DECIMAL CONVERSION (DDB requires Decimal for numbers, not float)
# ─────────────────────────────────────────────────────────────────────────────

def to_ddb(obj):
    """Recursively convert floats to Decimal for DynamoDB."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: to_ddb(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_ddb(v) for v in obj]
    if obj is None:
        return None
    return obj


# ─────────────────────────────────────────────────────────────────────────────
# BUILD DDB ITEM — matches existing schema in labs_helpers.py
# ─────────────────────────────────────────────────────────────────────────────

def build_ddb_item():
    """Build the single DynamoDB item for this draw."""
    oor = draw.out_of_range_keys()

    item = {
        "pk": PK,
        "sk": SK,
        "draw_date": draw.DRAW_DATE,
        "collection_timestamp_utc": draw.COLLECTION_TIMESTAMP_UTC,
        "lab_provider": draw.PROVIDER,            # field name matches existing helper
        "lab_network": draw.LAB_NETWORK,
        "physician": draw.PHYSICIAN,
        "fasting": draw.FASTING,
        "accession_number": draw.ACCESSION,

        # The biomarker map — field shape matches existing tool_get_lab_results
        "biomarkers": draw.BIOMARKERS,

        # Summary fields — used by tool_get_lab_results for the listing view
        "total_biomarkers": len(draw.BIOMARKERS),
        "out_of_range_count": len(oor),
        "out_of_range": oor,

        # Curated key findings for daily brief / coaching context
        "key_findings": draw.KEY_FINDINGS,

        # S3 artifact references — qualitative content lives in S3, pointers in DDB
        "clinician_notes_s3_key": draw.S3_ARTIFACTS["clinician_notes_2026_pdf"],
        "supplement_protocol_s3_key": draw.S3_ARTIFACTS["supplement_protocol_md"],
        "function_data_trends_s3_key": draw.S3_ARTIFACTS["function_data_trends_pdf"],
        "standard_panel_s3_key": draw.S3_ARTIFACTS["standard_panel_pdf"],
        "cardio_iq_nfl_s3_key": draw.S3_ARTIFACTS["cardio_iq_nfl_pdf"],
        "galleri_corrected_s3_key": draw.S3_ARTIFACTS["galleri_corrected_pdf"],
        "galleri_grail_original_s3_key": draw.S3_ARTIFACTS["galleri_grail_original_pdf"],

        # Provenance
        "source": "labs",
        "schema_version": "v1",
        "ingested_at": draw.COLLECTION_TIMESTAMP_UTC,
        "ingestion_method": "hand_extracted_from_pdfs",
    }

    return to_ddb(item)


# ─────────────────────────────────────────────────────────────────────────────
# DRY RUN / COMMIT
# ─────────────────────────────────────────────────────────────────────────────

def print_dry_run(item):
    """Print the item plan without writing."""
    print()
    print("═" * 70)
    print("DRY RUN — Function Health 2026-04-03 ingest plan")
    print("═" * 70)
    print()
    print(f"DynamoDB target:")
    print(f"  Table: {TABLE_NAME} ({REGION})")
    print(f"  PK:    {PK}")
    print(f"  SK:    {SK}")
    print()
    print(f"Item summary:")
    print(f"  draw_date:           {item['draw_date']}")
    print(f"  lab_provider:        {item['lab_provider']}")
    print(f"  lab_network:         {item['lab_network']}")
    print(f"  fasting:             {item['fasting']}")
    print(f"  total_biomarkers:    {item['total_biomarkers']}")
    print(f"  out_of_range_count:  {item['out_of_range_count']}")
    print(f"  key_findings:        {len(item['key_findings'])} curated findings")
    print()
    print(f"Out-of-range biomarkers ({len(item['out_of_range'])}):")
    for k in item["out_of_range"]:
        bm = draw.BIOMARKERS[k]
        print(f"  [{bm['flag']:4}] {k}: {bm['value']} {bm['unit']} (ref: {bm['ref_text']})")
    print()
    print(f"S3 archive plan:")
    print(f"  Bucket: {S3_BUCKET}")
    print(f"  Prefix: {S3_PREFIX}")
    for s3_filename, local_path in SOURCE_FILES.items():
        size_kb = local_path.stat().st_size // 1024
        exists = "✓" if local_path.exists() else "✗"
        print(f"  {exists} {s3_filename:35s}  ←  {local_path.name:50s}  ({size_kb} KB)")
    print()
    print(f"Sample biomarker (apob):")
    apob_sample = {k: (str(v) if isinstance(v, Decimal) else v)
                   for k, v in item["biomarkers"]["apob"].items()}
    print(json.dumps(apob_sample, indent=2, default=str))
    print()


def commit(item, *, skip_s3=False, skip_ddb=False):
    """Actually write to DDB and S3."""
    s3 = boto3.client("s3", region_name=REGION)
    ddb = boto3.resource("dynamodb", region_name=REGION)
    table = ddb.Table(TABLE_NAME)

    if not skip_s3:
        print()
        print("Uploading source artifacts to S3...")
        for s3_filename, local_path in SOURCE_FILES.items():
            s3_key = f"{S3_PREFIX}{s3_filename}"
            ext = local_path.suffix.lower()
            content_type = {
                ".pdf": "application/pdf",
                ".md": "text/markdown",
            }.get(ext, "application/octet-stream")
            s3.upload_file(
                str(local_path), S3_BUCKET, s3_key,
                ExtraArgs={"ContentType": content_type},
            )
            print(f"  ✓ s3://{S3_BUCKET}/{s3_key}")

    if not skip_ddb:
        print()
        print("Writing DynamoDB item...")
        table.put_item(Item=item)
        print(f"  ✓ Wrote {PK} / {SK}")

    print()
    print("✓ Ingestion complete.")


def confirm(prompt):
    resp = input(prompt).strip().lower()
    return resp in ("y", "yes")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="Validate and print plan, no writes")
    ap.add_argument("--skip-s3", action="store_true", help="Skip S3 archive (DDB only)")
    ap.add_argument("--skip-ddb", action="store_true", help="Skip DDB write (S3 only)")
    args = ap.parse_args()

    print("Function Health draw ingestion — 2026-04-03")
    print("─" * 70)
    print()
    print("Validating data integrity...")
    validate_data()

    item = build_ddb_item()
    print_dry_run(item)

    if args.dry_run:
        print("DRY RUN — no writes performed. Re-run without --dry-run to commit.")
        return

    if not confirm("Commit this ingest? [y/N] "):
        print("Aborted.")
        return

    commit(item, skip_s3=args.skip_s3, skip_ddb=args.skip_ddb)


if __name__ == "__main__":
    main()
