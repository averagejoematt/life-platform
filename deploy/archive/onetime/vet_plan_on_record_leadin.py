#!/usr/bin/env python3
"""
vet_plan_on_record_leadin.py — date-agnostic vet pass for the DATE#2026-08-02
chronicle record ("The Plan, On the Record") ahead of its carry into cycle 13
as a pre-genesis lead-in (--keep-chronicle, cycle-13 reset, genesis 2026-08-10).

The record was written for the cycle-12 genesis (2026-08-03) and opens with
"This morning — August 3, 2026 — a scale … recorded the first number" — a
present-tense anchor to the OUTGOING genesis. Re-dated as a Prologue lead-in,
that opening is temporally false (and its "August 3" is exactly the
outgoing-genesis prose token restart_verify_rendered forbids — it surfaced in
the /journal/posts.json excerpt at the cycle-13 reset). The edit below
neutralizes only that opening: timeless present ("records") is true in every
phase, and "before that number existed" still coheres pre-genesis.

Deliberately NOT edited: "Claims frozen and fingerprinted August 3, 2026" — a
true, verifiable historical statement about the sealed cycle-12 prereg (it sits
beside the artifact's SHA-256; the frozen-artifact discipline keeps its figure).
Same for the two content-addressed genesis-2026-08-03.json artifact URLs.

Same discipline as vet_night_before_leadin.py / restart_leadin_repair.py:
  - ORIGINAL record backed up FIRST to /tmp/leadin_backups/<sk>.json (local)
    AND s3://matthew-life-platform/remediation-log/leadin-backups/<sk>.json;
    an existing backup is NEVER overwritten (first backup = pre-repair truth).
  - Each edit must match EXACTLY ONCE in each content field or the run aborts.
  - Idempotent: if every old string is absent and every new string present,
    the record is reported already-vetted and left untouched.

Usage:
    python3 deploy/vet_plan_on_record_leadin.py            # dry-run
    python3 deploy/vet_plan_on_record_leadin.py --apply    # backup + write DDB
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REGION = "us-west-2"
S3_BUCKET = "matthew-life-platform"
TABLE = "life-platform"
CHRONICLE_PK = "USER#matthew#SOURCE#chronicle"
SK = "DATE#2026-08-02"
LOCAL_BACKUP_DIR = Path("/tmp") / "leadin_backups"
S3_BACKUP_PREFIX = "remediation-log/leadin-backups/"

# (old, new) — applied to BOTH content_markdown and content_html.
# Every `old` must occur exactly once per field.
VET_EDITS: list[tuple[str, str]] = [
    (
        "This morning — August 3, 2026 — a scale in a quiet bathroom recorded the first number of a twelve-month experiment.",
        "On the first morning, a scale in a quiet bathroom records the first number of a twelve-month experiment.",
    ),
]

# The historical freeze-date sentence legitimately keeps "August 3, 2026"
# (see module docstring) — so the forbidden-after list checks the FALSE form
# only, not the bare month-day token.
FORBIDDEN_AFTER = ["This morning — August 3"]

ROUNDS: list[tuple[str, list[tuple[str, str]], list[str]]] = [
    ("round1-date-agnostic-opening", VET_EDITS, FORBIDDEN_AFTER),
]


def apply_round(text: str, field: str, edits: list[tuple[str, str]], forbidden: list[str]) -> str:
    """Apply one round's edits to one content field, exactly-once per edit, or abort."""
    for old, new in edits:
        n = text.count(old)
        if n != 1:
            print(f"  ABORT: edit matched {n}x (expected 1) in {field}: {old[:60]!r}…")
            sys.exit(1)
        text = text.replace(old, new)
    for tok in forbidden:
        if tok in text:
            print(f"  ABORT: forbidden token {tok!r} still present in {field} after edits")
            sys.exit(1)
    return text


def round_applied(text: str, edits: list[tuple[str, str]]) -> bool:
    return all(old not in text for old, _ in edits) and all(new in text for _, new in edits)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    ddb = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    s3 = boto3.client("s3", region_name=REGION)

    item = ddb.get_item(Key={"pk": CHRONICLE_PK, "sk": SK}).get("Item")
    if not item:
        print(f"ABORT: {SK} not found")
        sys.exit(1)

    md, html = item.get("content_markdown", ""), item.get("content_html", "")
    new_md, new_html = md, html
    applied_rounds = []
    for name, edits, forbidden in ROUNDS:
        if round_applied(new_md, edits) and round_applied(new_html, edits):
            print(f"{SK}: {name} already applied — skipping.")
            continue
        new_md = apply_round(new_md, "content_markdown", edits, forbidden)
        new_html = apply_round(new_html, "content_html", edits, forbidden)
        applied_rounds.append(name)
        print(f"{SK}: {name} — {len(edits)} edits verified exactly-once in both fields.")
    if not applied_rounds:
        print(f"{SK}: already vetted (all rounds) — nothing to do.")
        return
    print(f"  md {len(md)} → {len(new_md)} chars; html {len(html)} → {len(new_html)} chars")

    if not args.apply:
        print("(dry-run) — pass --apply to backup + write.")
        return

    # Backup FIRST — local + private S3; never overwrite an existing backup.
    LOCAL_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    local = LOCAL_BACKUP_DIR / f"{SK}.json"
    payload = json.dumps(item, default=str, indent=2)
    if not local.exists():
        local.write_text(payload)
        print(f"  backed up → {local}")
    s3_key = f"{S3_BACKUP_PREFIX}{SK}.json"
    try:
        s3.head_object(Bucket=S3_BUCKET, Key=s3_key)
        print(f"  s3 backup exists (kept): s3://{S3_BUCKET}/{s3_key}")
    except ClientError:
        s3.put_object(Bucket=S3_BUCKET, Key=s3_key, Body=payload.encode())
        print(f"  backed up → s3://{S3_BUCKET}/{s3_key}")

    ddb.update_item(
        Key={"pk": CHRONICLE_PK, "sk": SK},
        UpdateExpression="SET content_markdown = :md, content_html = :html, vetted_at = :ts, vetted_reason = :r",
        ExpressionAttributeValues={
            ":md": new_md,
            ":html": new_html,
            ":ts": datetime.now(timezone.utc).isoformat(),
            ":r": "date-agnostic vet of the opening for the cycle-13 --keep-chronicle carry (genesis 2026-08-10)",
        },
    )
    print(f"  wrote vetted content to {SK}.")


if __name__ == "__main__":
    main()
