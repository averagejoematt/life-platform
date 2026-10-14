#!/usr/bin/env python3
"""scripts/load_clinical_record.py — load the owner clinical record into DynamoDB + S3.

WHY (ADR-155 amendment, 2026-10-12)
  The owner ruled that his clinical record may enter the AI coaches' context at
  `TIER_INTERNAL` — never on a public surface. The record is kept in a JSON file OUTSIDE
  this public repository; this script is the only writer of the `clinical` partition, and
  it never echoes a value: the dry run prints sort keys and field NAMES only.

USAGE
    python3 scripts/load_clinical_record.py <path-to-json>                  # dry run (default)
    python3 scripts/load_clinical_record.py <path-to-json> --apply          # write DDB + upload docs
    python3 scripts/load_clinical_record.py <path-to-json> --docs-dir DIR   # where documents[] live (default ~/Downloads)

INPUT SHAPE -> SORT KEYS  (pk `USER#matthew#SOURCE#clinical`)
    events[]               -> EVENT#<date>#<slug>   (the entry's own `sk` when it is well-formed)
    medications[]          -> MED#<slug>            (likewise)
    ecg_recordings[]       -> ECG#<YYYY-MM-DDTHH:MM:SS>#<device-slug>
    labs_<anything>{}      -> LABS#<collection_date>
    patient_history_<YYYY_MM_DD>{} -> HISTORY#<YYYY-MM-DD>
    coach_guidance{}       -> GUIDANCE#current
    documents[]            -> s3://matthew-life-platform/raw/matthew/clinical/<YYYY-MM-DD>/<file>
  Every item gets `source="clinical"`, `schema_version=1`, `updated_at`; floats become
  Decimal. A document whose filename matches an ECG/EVENT item's `source_file` sets that
  item's `s3_key` and dates its upload folder; otherwise the folder is the document's own
  `date`, else the file's `prepared` date (or today). Every document also gets an index
  row `DOC#<date>#<slug>` (kind, s3_key, content_type, sha256, bytes); the bytes stay in S3.

IDEMPOTENT: `put_item` on a deterministic key, and an S3 PUT on a deterministic key — a
re-run overwrites with the same content. Stdlib + boto3 only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

TABLE_NAME = "life-platform"
REGION = "us-west-2"
BUCKET = "matthew-life-platform"
USER_ID = "matthew"
SOURCE = "clinical"
PK = f"USER#{USER_ID}#SOURCE#{SOURCE}"
RAW_PREFIX = f"raw/{USER_ID}/{SOURCE}"
SCHEMA_VERSION = 1

_EVENT_SK = re.compile(r"^EVENT#\d{4}-\d{2}-\d{2}#[a-z0-9_-]+$")
_MED_SK = re.compile(r"^MED#[a-z0-9_-]+$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def slugify(text: Any) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return slug or "unnamed"


def to_dynamo(value: Any) -> Any:
    """Floats -> Decimal (via str, so 0.1 stays 0.1), recursively; drops None values,
    which DynamoDB rejects inside maps only by convention here (an absent field reads the same)."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {str(k): to_dynamo(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [to_dynamo(v) for v in value]
    return value


def _stamp(sk: str, body: dict, now: str) -> dict:
    item = {k: v for k, v in body.items() if k != "sk"}
    item.update(pk=PK, sk=sk, source=SOURCE, schema_version=SCHEMA_VERSION, updated_at=now)
    return to_dynamo(item)


def _event_sk(e: dict) -> str:
    sk = str(e.get("sk") or "")
    if _EVENT_SK.match(sk):
        return sk
    date = str(e.get("date") or "")[:10]
    if not _DATE.match(date):
        raise ValueError("an event has no usable `sk` and no YYYY-MM-DD `date`")
    return f"EVENT#{date}#{slugify(e.get('title') or e.get('type'))}"


def _med_sk(m: dict) -> str:
    sk = str(m.get("sk") or "")
    return sk if _MED_SK.match(sk) else f"MED#{slugify(m.get('name'))}"


def _ecg_sk(r: dict) -> str:
    ts = str(r.get("recorded_at_local") or "")[:19]
    if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$", ts):
        raise ValueError("an ECG recording has no YYYY-MM-DDTHH:MM:SS `recorded_at_local`")
    return f"ECG#{ts}#{slugify(r.get('device'))}"


def build_items(record: dict, now: Optional[str] = None) -> list:
    """The DynamoDB items for one record file, in a stable order. Pure."""
    now = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    items = []
    for e in record.get("events") or []:
        items.append(_stamp(_event_sk(e), e, now))
    for m in record.get("medications") or []:
        items.append(_stamp(_med_sk(m), m, now))
    for r in record.get("ecg_recordings") or []:
        items.append(_stamp(_ecg_sk(r), r, now))
    for key, body in record.items():
        if key.startswith("labs_") and isinstance(body, dict):
            date = str(body.get("collection_date") or "")[:10]
            if not _DATE.match(date):
                raise ValueError(f"{key}: no YYYY-MM-DD `collection_date`")
            items.append(_stamp(f"LABS#{date}", body, now))
        elif key.startswith("patient_history_") and isinstance(body, dict):
            m = re.search(r"(\d{4})_(\d{2})_(\d{2})$", key)
            if not m:
                raise ValueError(f"{key}: the key does not end in _YYYY_MM_DD")
            items.append(_stamp(f"HISTORY#{m.group(1)}-{m.group(2)}-{m.group(3)}", body, now))
    guidance = record.get("coach_guidance")
    if isinstance(guidance, dict):
        items.append(_stamp("GUIDANCE#current", guidance, now))
    seen: set = set()
    for it in items:
        if it["sk"] in seen:
            raise ValueError(f"duplicate sort key {it['sk']} — two entries would overwrite each other")
        seen.add(it["sk"])
    return items


def _item_date(item: dict) -> str:
    sk = item["sk"]
    if sk.startswith("ECG#"):
        return sk.split("#")[1][:10]
    if sk.startswith("EVENT#"):
        return sk.split("#")[1]
    return ""


def plan_uploads(record: dict, items: list, docs_dir: str) -> list:
    """[(local_path, s3_key, matched_item_or_None)] for every listed document. Sets
    `s3_key` on each item whose `source_file` names the document. Pure apart from that."""
    by_file: dict = {}
    for it in items:
        if it.get("source_file"):
            by_file.setdefault(str(it["source_file"]), []).append(it)
    fallback = str(record.get("prepared") or "")[:10]
    if not _DATE.match(fallback):
        fallback = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    plan = []
    for doc in record.get("documents") or []:
        name = str(doc.get("file") or "")
        if not name:
            continue
        # `path` overrides the docs dir: a directory holding `file`, or the file itself.
        override = os.path.expanduser(str(doc.get("path") or ""))
        if override and (os.path.isdir(override) or override.endswith("/")):
            local = os.path.join(override, name)
        else:
            local = override or os.path.join(docs_dir, name)
        matched = by_file.get(name) or []
        own = str(doc.get("date") or "")[:10]
        date = own if _DATE.match(own) else next((d for d in (_item_date(it) for it in matched) if d), fallback)
        key = f"{RAW_PREFIX}/{date}/{os.path.basename(name)}"
        for it in matched:
            it["s3_key"] = key
        plan.append((local, key, matched[0] if matched else None))
        # Every document also gets its own DynamoDB index row, so the engine can list the
        # whole record (screenshots and PDFs alike) without listing the bucket. The file
        # itself stays in S3 — an image or PDF can exceed the 400 KB item limit.
        doc_row = {k: v for k, v in doc.items() if k not in ("file", "path")}
        doc_row.update({"file": os.path.basename(name), "s3_key": key, "content_type": _content_type(name)})
        if os.path.isfile(local):
            with open(local, "rb") as fh:
                blob = fh.read()
            doc_row.update({"sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)})
        sk = f"DOC#{date}#{slugify(os.path.splitext(os.path.basename(name))[0])}"
        if any(it["sk"] == sk for it in items):
            raise ValueError(f"duplicate sort key {sk} — two documents would overwrite each other")
        items.append(_stamp(sk, doc_row, str(items[0].get("updated_at") or "") if items else ""))
    return plan


def _content_type(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def describe(items: list, plan: list) -> list:
    """Dry-run lines: sort keys and field NAMES only — never a value."""
    lines = [f"DynamoDB {TABLE_NAME} ({REGION}) pk={PK}: {len(items)} item(s)"]
    for it in items:
        fields = sorted(k for k in it if k not in ("pk", "sk"))
        lines.append(f"  {it['sk']}  fields: {', '.join(fields)}")
    lines.append(f"S3 uploads to s3://{BUCKET}/{RAW_PREFIX}/: {len(plan)} document(s)")
    for local, key, matched in plan:
        state = "found" if os.path.isfile(local) else "MISSING"
        link = f" -> s3_key on {matched['sk']}" if matched else ""
        lines.append(f"  [{state}] {os.path.basename(local)} => {key}{link}")
    return lines


def _bucket_sse(s3) -> dict:
    """ExtraArgs that restate the bucket's default encryption (read-only lookup). Empty on
    any failure — the bucket default then applies anyway."""
    try:
        rules = s3.get_bucket_encryption(Bucket=BUCKET)["ServerSideEncryptionConfiguration"]["Rules"]
        default = rules[0]["ApplyServerSideEncryptionByDefault"]
        args = {"ServerSideEncryption": default["SSEAlgorithm"]}
        if default.get("KMSMasterKeyID"):
            args["SSEKMSKeyId"] = default["KMSMasterKeyID"]
        return args
    except Exception as e:  # noqa: BLE001
        print(f"  (bucket encryption lookup failed — relying on the bucket default: {type(e).__name__})")
        return {}


def apply(items: list, plan: list) -> int:
    import boto3

    missing = [local for local, _k, _m in plan if not os.path.isfile(local)]
    if missing:
        print(f"REFUSING: {len(missing)} listed document(s) not found: {', '.join(os.path.basename(m) for m in missing)}")
        return 1
    s3 = boto3.client("s3", region_name=REGION)
    sse = _bucket_sse(s3)
    for local, key, _m in plan:
        s3.upload_file(local, BUCKET, key, ExtraArgs=dict(sse, ContentType=_content_type(local)))
        print(f"  uploaded {key}")
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    for it in items:
        table.put_item(Item=it)
        print(f"  put {it['sk']}")
    print(f"done: {len(items)} item(s), {len(plan)} document(s)")
    return 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Load the owner clinical record (dry run unless --apply).")
    ap.add_argument("path", help="the clinical record JSON (kept outside the repo)")
    ap.add_argument("--apply", action="store_true", help="write to DynamoDB and upload documents to S3")
    ap.add_argument("--docs-dir", default="~/Downloads", help="where documents[] files live (default ~/Downloads)")
    args = ap.parse_args(argv)
    with open(os.path.expanduser(args.path), encoding="utf-8") as fh:
        record = json.load(fh)
    items = build_items(record)
    plan = plan_uploads(record, items, os.path.expanduser(args.docs_dir))
    for line in describe(items, plan):
        print(line)
    if not args.apply:
        print("DRY RUN — nothing written. Re-run with --apply to write.")
        return 0
    return apply(items, plan)


if __name__ == "__main__":
    sys.exit(main())
