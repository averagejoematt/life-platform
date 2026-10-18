#!/usr/bin/env python3
"""scripts/ingest_lab_report.py — the one path a blood draw or a DEXA scan takes onto the platform (#4639).

WHY
  Before this script nothing wrote `USER#matthew#SOURCE#labs` or `SOURCE#dexa` (epic #4625,
  the 2026-10-04 data-source sweep): every stored draw and scan was typed in by a session,
  with no validator, no unit contract and no record of where a figure came from. The owner
  ruled yes (Q37 on #4644, 2026-10-17): build upload -> review -> store before the next draw.

THE CONTRACT (the issue's acceptance boxes, in order)
  1. The source document is archived to the raw zone BEFORE anything is written to
     DynamoDB — under the source's own `raw_layout` facet in `ingestion.source_registry`
     (`raw/matthew/labs/<draw-date>/<file>`, `raw/matthew/dexa/<scan-date>/<file>`); the key
     is read from the facet, never constructed here. A back-fill whose document the owner no
     longer holds says so: `--document-unavailable "<reason>"` is recorded on the row.
  2. The write REFUSES a marker or a unit that is not in the schema
     (`health.lab_units.LAB_UNITS` / `DEXA_FIELDS`). The table grows by a reviewed PR.
  3. Every row carries `provenance` — the archived document keys + sha256, the lab or
     scanner, the drawn/scanned date, the extraction method, the reviewer, `ingested_at` —
     and a REVIEW STEP sits between extraction and write: the default run prints the review
     table and writes nothing; only `--apply` writes.

USAGE
  python3 scripts/ingest_lab_report.py labs <report.csv|report.json> --draw-date YYYY-MM-DD \
      --lab-provider function_health --lab-network quest_diagnostics \
      --document ~/Downloads/standard_panel.pdf [--document ...] [--fasting] [--physician NAME]
  python3 scripts/ingest_lab_report.py dexa <scan.csv|scan.json> --scan-date YYYY-MM-DD \
      --provider dexafit_seattle --document ~/Downloads/dexa_report.pdf
  ... then re-run the SAME command with --apply once the review table reads right.
  Options: --reviewer (default: matthew) · --overwrite (replace an existing row / a changed
  archive object; refused otherwise) · --no-previous (skip the read of the prior draw/scan)
  · --document-unavailable "<reason>" (a back-fill with no document to archive).

INPUT SHAPES (the stored wire shapes, so the fixture IS the wire — SCHEMA.md `labs`/`dexa`)
  labs CSV   columns: marker,value,unit,ref_text,flag[,category,panel,note]  (one row per marker)
  labs JSON  {"biomarkers": {"<marker_key>": {"value","unit","ref_text","flag",...}}, ...}
  dexa CSV   columns: field,value[,unit]   (field = dotted leaf path, e.g. body_composition.body_fat_pct)
  dexa JSON  the nested scan record ({"body_composition": {...}, "bone": {...}, ...})

Stdlib + boto3 only; every number becomes Decimal before the write. Read-only against AWS
until --apply; `--apply` does exactly: S3 PutObject per document, then one PutItem.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import mimetypes
import os
import re
import sys
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

from health import labs_schema  # noqa: E402
from health.lab_units import (  # noqa: E402
    DEXA_FIELDS,
    DEXA_REQUIRED,
    LAB_FLAGS,
    LAB_UNITS,
    canonical_marker,
    canonical_unit,
    dexa_unit_for,
    marker_key,
    unit_accepted,
)
from ingestion.source_registry import SOURCE_REGISTRY  # noqa: E402

TABLE_NAME = "life-platform"
REGION = "us-west-2"
BUCKET = "matthew-life-platform"
USER_ID = "matthew"
SCHEMA_VERSION = "v2"  # v1 = the hand-extracted 2026-04-03 row; v2 = written through this path with `provenance`
EXTRACTION_TAG = "scripts/ingest_lab_report.py"

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NUM = r"-?\d+(?:\.\d+)?"
_RANGE = re.compile(rf"^\s*({_NUM})\s*(?:-|–|to)\s*({_NUM})")
_LT = re.compile(rf"^\s*(?:<|≤|<=)\s*({_NUM})")
_GT = re.compile(rf"^\s*(?:>|≥|>=)\s*({_NUM})")
_NUMERIC_VALUE = re.compile(rf"^\s*{_NUM}\s*$")


class Refusal(ValueError):
    """The input is not writable. Every message names the row and the rule it broke."""


# ── shared ──────────────────────────────────────────────────────────────────────────────


def pk_for(source: str) -> str:
    return f"USER#{USER_ID}#SOURCE#{source}"


def raw_document_key(source: str, event_date: str, filename: str) -> str:
    """The archive key for one source document — read off the registry's `raw_layout` facet.

    Both sources use the `date-folder` scheme (one folder per draw/scan date holding N
    documents). `raw_date_key()` in the registry serves the per-day `date-tree` sources and
    raises for this scheme by design, so the folder rule lives here, still fed by the facet.
    """
    layout = SOURCE_REGISTRY[source]["raw_layout"]
    if layout.get("scheme") != "date-folder":
        raise Refusal(f"{source}: raw_layout scheme is {layout.get('scheme')!r}, not date-folder — this script cannot address it")
    if not _DATE.match(event_date):
        raise Refusal(f"{source}: {event_date!r} is not YYYY-MM-DD")
    date.fromisoformat(event_date)
    return f"{layout['prefix']}/{event_date}/{os.path.basename(filename)}"


def to_dynamo(value: Any) -> Any:
    """Floats and ints -> Decimal (via str, so 0.1 stays 0.1), recursively; None dropped."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)) and not isinstance(value, Decimal):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {str(k): to_dynamo(v) for k, v in value.items() if v is not None}
    if isinstance(value, (list, tuple)):
        return [to_dynamo(v) for v in value]
    return value


def _sha256(path: str) -> Tuple[str, int]:
    with open(path, "rb") as fh:
        blob = fh.read()
    return hashlib.sha256(blob).hexdigest(), len(blob)


def plan_documents(source: str, event_date: str, paths: List[str]) -> List[Dict[str, Any]]:
    """[{file, local, s3_key, sha256, bytes, content_type}] for each document; refuses a missing file."""
    plan = []
    for raw in paths:
        local = os.path.expanduser(raw)
        if not os.path.isfile(local):
            raise Refusal(f"document not found: {raw}")
        digest, size = _sha256(local)
        plan.append(
            {
                "file": os.path.basename(local),
                "local": local,
                "s3_key": raw_document_key(source, event_date, local),
                "sha256": digest,
                "bytes": size,
                "content_type": mimetypes.guess_type(local)[0] or "application/octet-stream",
            }
        )
    return plan


def provenance_block(
    *,
    documents: List[Dict[str, Any]],
    unavailable_reason: Optional[str],
    extraction_method: str,
    reviewer: str,
    now: str,
    **named: str,
) -> Dict[str, Any]:
    """The provenance map every row written here carries (acceptance box 3)."""
    block: Dict[str, Any] = {
        "documents": [{k: v for k, v in d.items() if k != "local"} for d in documents],
        "extraction_method": f"{extraction_method} via {EXTRACTION_TAG}",
        "reviewer": reviewer,
        "ingested_at": now,
    }
    if unavailable_reason:
        block["documents_unavailable_reason"] = unavailable_reason
    block.update(named)
    return block


def parse_numeric(raw: Any) -> Optional[Decimal]:
    """A clean number -> Decimal; anything else (qualitative, "<10", "NEGATIVE") -> None."""
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, (int, float, Decimal)):
        return Decimal(str(raw))
    text = str(raw).strip().replace(",", "")
    if not _NUMERIC_VALUE.match(text):
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


# ── labs ────────────────────────────────────────────────────────────────────────────────


def parse_ref_text(ref_text: str) -> Tuple[Optional[Decimal], Optional[Decimal]]:
    """'a - b' -> (a, b); '<x' -> (None, x); '>x' -> (x, None); anything else -> (None, None)."""
    text = str(ref_text or "")
    m = _RANGE.match(text)
    if m:
        return Decimal(m.group(1)), Decimal(m.group(2))
    m = _LT.match(text)
    if m:
        return None, Decimal(m.group(1))
    m = _GT.match(text)
    if m:
        return Decimal(m.group(1)), None
    return None, None


def derive_flag(value_numeric: Optional[Decimal], ref_low: Optional[Decimal], ref_high: Optional[Decimal]) -> str:
    if value_numeric is None or (ref_low is None and ref_high is None):
        return ""
    if ref_low is not None and value_numeric < ref_low:
        return "low"
    if ref_high is not None and value_numeric > ref_high:
        return "high"
    return "normal"


def read_lab_rows(path: str) -> Tuple[List[Dict[str, Any]], str]:
    """The per-marker rows off a CSV or a JSON report, plus the extraction method name."""
    p = Path(os.path.expanduser(path))
    if p.suffix.lower() == ".json":
        doc = json.loads(p.read_text(encoding="utf-8"))
        markers = doc.get("biomarkers") if isinstance(doc, dict) else None
        if not isinstance(markers, dict) or not markers:
            raise Refusal("labs JSON: no `biomarkers` map (SCHEMA.md: the draw record stores its values ONLY there)")
        rows = [{"marker": k, **(v if isinstance(v, dict) else {"value": v})} for k, v in markers.items()]
        return rows, "json"
    with p.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = {"marker", "value"} - set(h.strip() for h in (reader.fieldnames or []))
        if missing:
            raise Refusal(f"labs CSV: header is missing {sorted(missing)} (need marker,value[,unit,ref_text,flag,category,panel,note])")
        rows = [{k.strip(): (v or "").strip() for k, v in row.items() if k} for row in reader]
    if not rows:
        raise Refusal("labs CSV: no marker rows")
    return rows, "csv"


def validate_marker(row: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """One report row -> (marker_key, marker object in the SCHEMA.md shape). Refuses off-schema input."""
    key = canonical_marker(marker_key(row.get("marker") or row.get("name") or ""))
    if not key:
        raise Refusal("a row has no marker name")
    if key not in LAB_UNITS:
        raise Refusal(f"{key}: marker not in health.lab_units.LAB_UNITS — add it by PR, the write will not invent it")
    accepted, category, kind = LAB_UNITS[key]
    unit = str(row.get("unit") or "")
    if not unit_accepted(key, unit):
        raise Refusal(f"{key}: unit {unit!r} not in the schema (accepted: {list(accepted)})")
    raw_value = row.get("value")
    if raw_value is None or str(raw_value).strip() == "":
        raise Refusal(f"{key}: empty value")
    value_numeric = parse_numeric(raw_value)
    if kind == "numeric" and value_numeric is None and not re.match(r"^\s*[<>≤≥]", str(raw_value)):
        raise Refusal(f"{key}: numeric marker but value {raw_value!r} is not a number (a '<x'/'>x' censored result is allowed)")
    ref_text = str(row.get("ref_text") or "")
    ref_low, ref_high = parse_ref_text(ref_text)
    flag = str(row.get("flag") or "").strip().lower() or derive_flag(value_numeric, ref_low, ref_high)
    if flag not in LAB_FLAGS:
        raise Refusal(f"{key}: flag {flag!r} not one of {list(LAB_FLAGS)}")
    entry: Dict[str, Any] = {
        "value": value_numeric if value_numeric is not None else str(raw_value).strip(),
        "value_numeric": value_numeric,
        "unit": canonical_unit(key, unit) if unit else "",
        "ref_text": ref_text,
        "ref_low": ref_low,
        "ref_high": ref_high,
        "flag": flag,
        "category": str(row.get("category") or category),
    }
    for extra in ("panel", "note", "fh_category"):
        if row.get(extra):
            entry[extra] = str(row[extra])
    return key, entry


def build_labs_item(
    rows: List[Dict[str, Any]],
    *,
    draw_date: str,
    lab_provider: str,
    lab_network: str,
    documents: List[Dict[str, Any]],
    unavailable_reason: Optional[str],
    extraction_method: str,
    reviewer: str,
    fasting: Optional[bool] = None,
    physician: Optional[str] = None,
    previous: Optional[Dict[str, Any]] = None,
    now: Optional[str] = None,
) -> Dict[str, Any]:
    """The draw record (SCHEMA.md `labs`), Decimal-typed, with `provenance`. Pure."""
    if not _DATE.match(draw_date):
        raise Refusal(f"--draw-date {draw_date!r} is not YYYY-MM-DD")
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    biomarkers: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        key, entry = validate_marker(row)
        if key in biomarkers:
            raise Refusal(f"{key}: listed twice in the report")
        biomarkers[key] = entry
    if previous:
        prev_date = str(previous.get("draw_date") or previous.get("sk", "")[5:])
        for key, entry in biomarkers.items():
            prev_num = labs_schema.marker_numeric(labs_schema.biomarker_entry(previous, key))
            if prev_num is not None:
                entry["previous_value"] = Decimal(str(prev_num))
                entry["previous_date"] = prev_date
    out_of_range = sorted(k for k, e in biomarkers.items() if e["flag"] in ("high", "low"))
    item: Dict[str, Any] = {
        "pk": pk_for("labs"),
        "sk": f"DATE#{draw_date}",
        "source": "labs",
        "schema_version": SCHEMA_VERSION,
        "draw_date": draw_date,
        "collection_date": draw_date,
        "lab_provider": lab_provider,
        "lab_network": lab_network,
        "biomarkers": biomarkers,
        "out_of_range": out_of_range,
        "out_of_range_count": len(out_of_range),
        "total_biomarkers": len(biomarkers),
        "ingested_at": now,
        "ingestion_method": f"{extraction_method} via {EXTRACTION_TAG}",
        "updated_at": now,
        "provenance": provenance_block(
            documents=documents,
            unavailable_reason=unavailable_reason,
            extraction_method=extraction_method,
            reviewer=reviewer,
            now=now,
            lab=lab_provider,
            lab_network=lab_network,
            drawn_date=draw_date,
        ),
    }
    if fasting is not None:
        item["fasting"] = fasting
    if physician:
        item["physician"] = physician
    return to_dynamo(item)


# ── dexa ────────────────────────────────────────────────────────────────────────────────


def _flatten(node: Any, prefix: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in (node or {}).items():
        path = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, path + "."))
        else:
            out[path] = v
    return out


def read_dexa_leaves(path: str) -> Tuple[Dict[str, Tuple[Any, str]], str]:
    """{dotted path: (raw value, unit-or-'')} off a CSV (field,value[,unit]) or a nested JSON scan."""
    p = Path(os.path.expanduser(path))
    if p.suffix.lower() == ".json":
        doc = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or not doc:
            raise Refusal("dexa JSON: expected the nested scan record")
        skip = {
            "pk",
            "sk",
            "scan_date",
            "scan_type",
            "provider",
            "provider_address",
            "updated_at",
            "provenance",
            "source",
            "schema_version",
        }
        return {k: (v, "") for k, v in _flatten(doc).items() if k.split(".")[0] not in skip}, "json"
    with p.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames or {"field", "value"} - set(h.strip() for h in reader.fieldnames):
            raise Refusal("dexa CSV: header must be field,value[,unit]")
        leaves = {}
        for row in reader:
            row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
            if row.get("field"):
                leaves[row["field"]] = (row.get("value"), row.get("unit") or "")
    if not leaves:
        raise Refusal("dexa CSV: no rows")
    return leaves, "csv"


def validate_dexa_leaves(leaves: Dict[str, Tuple[Any, str]]) -> Dict[str, Any]:
    """Every leaf must be a known DEXA field of the right kind with the right unit; the core four must be present."""
    nested: Dict[str, Any] = {}
    for path, (raw, unit) in leaves.items():
        kind = DEXA_FIELDS.get(path)
        if kind is None:
            raise Refusal(f"{path}: not a DEXA field in health.lab_units.DEXA_FIELDS — add it by PR, the write will not invent it")
        if kind == "number":
            value: Any = parse_numeric(raw)
            if value is None:
                raise Refusal(f"{path}: expected a number, got {raw!r}")
            expected = dexa_unit_for(path)
            if unit and expected and re.sub(r"\s+", "", unit).lower() != re.sub(r"\s+", "", expected).lower():
                raise Refusal(f"{path}: unit {unit!r} but the field carries {expected!r} (its suffix is the unit)")
        else:
            value = str(raw).strip()
            if not value:
                raise Refusal(f"{path}: empty")
        node = nested
        parts = path.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    missing = [p for p in DEXA_REQUIRED if p not in leaves]
    if missing:
        raise Refusal(f"scan is missing the fields every reader depends on: {missing}")
    return nested


def build_dexa_item(
    leaves: Dict[str, Tuple[Any, str]],
    *,
    scan_date: str,
    provider: str,
    documents: List[Dict[str, Any]],
    unavailable_reason: Optional[str],
    extraction_method: str,
    reviewer: str,
    provider_address: Optional[str] = None,
    now: Optional[str] = None,
) -> Dict[str, Any]:
    """The scan record (SCHEMA.md `dexa`), Decimal-typed, with `provenance`. Pure."""
    if not _DATE.match(scan_date):
        raise Refusal(f"--scan-date {scan_date!r} is not YYYY-MM-DD")
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    item: Dict[str, Any] = {
        "pk": pk_for("dexa"),
        "sk": f"DATE#{scan_date}",
        "source": "dexa",
        "schema_version": SCHEMA_VERSION,
        "scan_date": scan_date,
        "scan_type": "dexa",
        "provider": provider,
        "updated_at": now,
        "ingested_at": now,
        "ingestion_method": f"{extraction_method} via {EXTRACTION_TAG}",
        **validate_dexa_leaves(leaves),
        "provenance": provenance_block(
            documents=documents,
            unavailable_reason=unavailable_reason,
            extraction_method=extraction_method,
            reviewer=reviewer,
            now=now,
            scanner=provider,
            scanned_date=scan_date,
        ),
    }
    if provider_address:
        item["provider_address"] = provider_address
    return to_dynamo(item)


# ── review + apply ──────────────────────────────────────────────────────────────────────


def review_lines(item: Dict[str, Any], documents: List[Dict[str, Any]]) -> List[str]:
    """The review table the owner reads before --apply. Values ARE shown: this is his terminal."""
    lines = [f"{item['pk']} / {item['sk']}  (schema {item['schema_version']}, {item['ingestion_method']})"]
    for d in documents:
        lines.append(f"  archive  {d['file']} -> s3://{BUCKET}/{d['s3_key']}  sha256 {d['sha256'][:12]}… {d['bytes']} B")
    if item["provenance"].get("documents_unavailable_reason"):
        lines.append(f"  archive  NONE — documents unavailable: {item['provenance']['documents_unavailable_reason']}")
    if "biomarkers" in item:
        lines.append(f"  {'marker':34} {'value':>12} {'unit':14} {'ref':18} {'flag':8} previous")
        for key, e in sorted(item["biomarkers"].items()):
            prev = f"{e['previous_value']} ({e['previous_date']})" if e.get("previous_value") is not None else ""
            lines.append(
                f"  {key:34} {str(e['value']):>12} {e.get('unit', ''):14} {e.get('ref_text', '')[:18]:18} {e.get('flag', ''):8} {prev}"
            )
        lines.append(
            f"  {item['total_biomarkers']} markers, {item['out_of_range_count']} out of range: {', '.join(item['out_of_range']) or '-'}"
        )
    else:
        for path, value in sorted(_flatten({k: v for k, v in item.items() if isinstance(v, dict) and k != "provenance"}).items()):
            lines.append(f"  {path:44} {value!s:>12} {dexa_unit_for(path) or ''}")
    return lines


def fetch_previous(source: str) -> Optional[Dict[str, Any]]:
    """The newest existing DATE# row of the partition (read-only), or None if unreachable."""
    try:
        import boto3
        from boto3.dynamodb.conditions import Key
        from botocore.config import Config

        table = boto3.resource("dynamodb", region_name=REGION, config=Config(read_timeout=60, retries={"max_attempts": 1})).Table(
            TABLE_NAME
        )
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(pk_for(source)) & Key("sk").begins_with("DATE#"),
            ScanIndexForward=False,
            Limit=1,
        )
        items = [it for it in resp.get("Items", []) if labs_schema.is_draw_record(it)]
        return items[0] if items else None
    except Exception as e:  # noqa: BLE001 — a dry run must still print the review table offline
        print(f"  (previous {source} row unavailable — {type(e).__name__}; comparisons skipped)")
        return None


def apply(item: Dict[str, Any], documents: List[Dict[str, Any]], *, overwrite: bool, s3=None, table=None) -> int:
    """Archive first, then write. Refuses to clobber an existing row or a changed archive object without --overwrite."""
    if s3 is None or table is None:
        import boto3
        from botocore.config import Config

        cfg = Config(read_timeout=60, retries={"max_attempts": 1})
        s3 = s3 or boto3.client("s3", region_name=REGION, config=cfg)
        table = table or boto3.resource("dynamodb", region_name=REGION, config=cfg).Table(TABLE_NAME)
    for d in documents:
        try:
            head = s3.head_object(Bucket=BUCKET, Key=d["s3_key"])
            same = str(head.get("Metadata", {}).get("sha256", "")) == d["sha256"]
            if not same and not overwrite:
                print(f"REFUSING: s3://{BUCKET}/{d['s3_key']} already exists with different content (pass --overwrite to replace)")
                return 1
            if same:
                print(f"  archived already (same sha256): {d['s3_key']}")
                continue
        except Exception as e:  # noqa: BLE001 — a 404 means "not archived yet", which is the normal first run
            if "404" not in str(e) and "Not Found" not in str(e) and type(e).__name__ not in ("ClientError", "NoSuchKey"):
                raise
        with open(d["local"], "rb") as fh:
            s3.put_object(Bucket=BUCKET, Key=d["s3_key"], Body=fh.read(), ContentType=d["content_type"], Metadata={"sha256": d["sha256"]})
        print(f"  archived {d['s3_key']}")
    kwargs: Dict[str, Any] = {"Item": item}
    if not overwrite:
        kwargs["ConditionExpression"] = "attribute_not_exists(sk)"
    try:
        table.put_item(**kwargs)
    except Exception as e:  # noqa: BLE001
        if "ConditionalCheckFailed" in str(e) or type(e).__name__ == "ConditionalCheckFailedException":
            print(f"REFUSING: {item['sk']} already exists in {item['pk']} (pass --overwrite to replace it)")
            return 1
        raise
    print(f"  put {item['pk']} {item['sk']}")
    return 0


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Ingest a lab draw or a DEXA scan (dry run unless --apply).")
    sub = ap.add_subparsers(dest="source", required=True)
    for name in ("labs", "dexa"):
        sp = sub.add_parser(name)
        sp.add_argument("report", help="the exported CSV or JSON")
        sp.add_argument("--document", action="append", default=[], help="source document to archive first (repeatable)")
        sp.add_argument("--document-unavailable", default=None, help="a back-fill with no document: say why, it is recorded on the row")
        sp.add_argument("--reviewer", default=USER_ID)
        sp.add_argument("--apply", action="store_true", help="archive the documents, then write the row")
        sp.add_argument("--overwrite", action="store_true", help="replace an existing row or a changed archive object")
        sp.add_argument("--no-previous", action="store_true", help="skip the read-only lookup of the prior row")
    labs = sub.choices["labs"]
    labs.add_argument("--draw-date", required=True)
    labs.add_argument("--lab-provider", required=True, help="e.g. function_health, gp_panel")
    labs.add_argument("--lab-network", required=True, help="e.g. quest_diagnostics")
    labs.add_argument("--fasting", action="store_true", default=None)
    labs.add_argument("--physician", default=None)
    dexa = sub.choices["dexa"]
    dexa.add_argument("--scan-date", required=True)
    dexa.add_argument("--provider", required=True, help="e.g. dexafit_seattle")
    dexa.add_argument("--provider-address", default=None)
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = _parser().parse_args(argv)
    if not args.document and not args.document_unavailable:
        print("REFUSING: no --document to archive and no --document-unavailable reason — the archive comes first (#4639 box 2)")
        return 2
    event_date = args.draw_date if args.source == "labs" else args.scan_date
    try:
        documents = plan_documents(args.source, event_date, args.document)
        common = dict(documents=documents, unavailable_reason=args.document_unavailable, reviewer=args.reviewer)
        if args.source == "labs":
            rows, method = read_lab_rows(args.report)
            previous = None if args.no_previous else fetch_previous("labs")
            item = build_labs_item(
                rows,
                draw_date=args.draw_date,
                lab_provider=args.lab_provider,
                lab_network=args.lab_network,
                extraction_method=method,
                fasting=args.fasting,
                physician=args.physician,
                previous=previous,
                **common,
            )
        else:
            leaves, method = read_dexa_leaves(args.report)
            item = build_dexa_item(
                leaves,
                scan_date=args.scan_date,
                provider=args.provider,
                provider_address=args.provider_address,
                extraction_method=method,
                **common,
            )
    except Refusal as e:
        print(f"REFUSING: {e}")
        return 2
    for line in review_lines(item, documents):
        print(line)
    if not args.apply:
        print("DRY RUN — nothing archived, nothing written. Re-run with --apply once the table above reads right.")
        return 0
    return apply(item, documents, overwrite=args.overwrite)


if __name__ == "__main__":
    sys.exit(main())
