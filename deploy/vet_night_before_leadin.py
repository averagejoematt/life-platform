#!/usr/bin/env python3
"""
vet_night_before_leadin.py — date-agnostic vet pass for the DATE#2026-07-21
chronicle record ("The Night Before Everything") ahead of its promotion to the
PRELAUNCH_CALENDAR (cycle-11 reset, 2026-07-26 — Matthew's rule: prequel
chronicle articles always roll t-minus the genesis date).

The calendar re-dates this record to genesis−1 every reset, so its prose must
be DATE-AGNOSTIC (restart_chronicle_handler.py calendar docstring): the
original text was anchored to a Tuesday→Wednesday launch (cycle 10) and quoted
the cycle-10 starting weight. Edits below neutralize weekdays, drop the
"for the first time" claim (false from the second staging onward), and
generalize the start-weight figure so the piece never contradicts the live
cycle's baseline (ADR-104 — the goal figure 185 is durable and stays).

Same discipline as restart_leadin_repair.py:
  - ORIGINAL record backed up FIRST to /tmp/leadin_backups/<sk>.json (local)
    AND s3://matthew-life-platform/remediation-log/leadin-backups/<sk>.json;
    an existing backup is NEVER overwritten (first backup = pre-repair truth).
  - Each edit must match EXACTLY ONCE in each content field or the run aborts.
  - Idempotent: if every old string is absent and every new string present,
    the record is reported already-vetted and left untouched.

Usage:
    python3 deploy/vet_night_before_leadin.py            # dry-run
    python3 deploy/vet_night_before_leadin.py --apply    # backup + write DDB
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
SK = "DATE#2026-07-21"
LOCAL_BACKUP_DIR = Path("/tmp") / "leadin_backups"
S3_BACKUP_PREFIX = "remediation-log/leadin-backups/"

# (old, new) — applied to BOTH content_markdown and content_html.
# Every `old` must occur exactly once per field.
VET_EDITS: list[tuple[str, str]] = [
    (
        "The habit tracker logged a 2 out of 100 on Tuesday.",
        "The habit tracker logged a 2 out of 100 on the eve of genesis.",
    ),
    (
        "Tuesday wasn't a collapse. Tuesday was the last night of the old life,",
        "It wasn't a collapse. It was the last night of the old life,",
    ),
    (
        "The starting weight is 321.38 pounds. The goal is 185. "
        "The distance between those two numbers — 136 pounds, roughly the weight of a person — is not a gap",
        "The goal is 185 pounds. The distance between the starting weight and that goal — roughly the weight of a person — is not a gap",
    ),
    (
        "It's part of what makes the Tuesday number so interesting:",
        "It's part of what makes the eve-of-genesis number so interesting:",
    ),
    (
        "The Tuesday before genesis — the 2 out of 100 —",
        "The day before genesis — the 2 out of 100 —",
    ),
    (
        "The question isn't whether he can do better than Tuesday. Of course he can. "
        "The question is whether the system he's built can hold him accountable when Tuesday comes again — because it will.",
        "The question isn't whether he can do better than the bad night. Of course he can. "
        "The question is whether the system he's built can hold him accountable when the bad night comes again — because it will.",
    ),
    (
        "Right now, a Tuesday like the one he just had can spiral.",
        "Right now, a night like the one he just had can spiral.",
    ),
    (
        "Tomorrow, for the first time, that system goes live.",
        "Tomorrow, that system goes live.",
    ),
    (
        "ready to log whatever Wednesday brings.",
        "ready to log whatever Day 1 brings.",
    ),
    (
        "What Wednesday actually brings —",
        "What Day 1 actually brings —",
    ),
]

FORBIDDEN_AFTER = ["Tuesday", "Wednesday", "321.38", "for the first time"]


def apply_edits(text: str, field: str) -> str:
    """Apply VET_EDITS to one content field, exactly-once per edit, or abort."""
    for old, new in VET_EDITS:
        n = text.count(old)
        if n != 1:
            print(f"  ABORT: edit matched {n}x (expected 1) in {field}: {old[:60]!r}…")
            sys.exit(1)
        text = text.replace(old, new)
    for tok in FORBIDDEN_AFTER:
        if tok in text:
            print(f"  ABORT: forbidden token {tok!r} still present in {field} after edits")
            sys.exit(1)
    return text


def already_vetted(text: str) -> bool:
    return all(old not in text for old, _ in VET_EDITS) and all(new in text for _, new in VET_EDITS)


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
    if already_vetted(md) and already_vetted(html):
        print(f"{SK}: already vetted — nothing to do.")
        return

    new_md = apply_edits(md, "content_markdown")
    new_html = apply_edits(html, "content_html")
    print(f"{SK}: {len(VET_EDITS)} edits verified exactly-once in both fields.")
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
            ":r": "date-agnostic vet for PRELAUNCH_CALENDAR promotion (cycle-11 reset)",
        },
    )
    print(f"  wrote vetted content to {SK}.")


if __name__ == "__main__":
    main()
