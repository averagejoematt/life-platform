#!/usr/bin/env python3
"""scripts/chronicle_edition_backup.py — keep a chapter's first edition privately and immutably before a later edition (#6193).

WHY (owner ruling 2026-11-22 §3). "Keep the original evidence privately and immutably." A second edition never changes
the chronicle row or its pages (``lambdas/content/chapter_editions.py``), but the canonical address stops serving the
first edition, and the row itself may later be revised by ``scripts/chronicle_revision_apply.py``. So before Matthew's
approval of ANY later edition can be recorded, the first edition as it stands is copied, byte for byte, to a private
write-once prefix, read back and checked, and a pointer record (``CHAPTER_EDITION#<chapter>#01``: keys and sha256s, no
text) is written once. ``approve_edition`` refuses without that record, and the public view withholds an edition
approved before it.

WHAT IS COPIED (the revision tool's backup forms, reused: ``ddb_json`` / ``ddb_backup_key`` / ``s3_backup_key``):
  * the chronicle row (``DATE#…``), whole, as lossless DynamoDB JSON;
  * its journal page (the row's ``draft_journal_post_key``, which must be the chapter's ``…/posts/<chapter>/index.html``);
  * the v9 chapter page at the root (``site/story/<chapter>/index.html``) when it exists.

SAFETY. Dry-run by default: reads only, prints the plan. ``--apply``: every copy is a conditional put (``IfNoneMatch``)
under ``backups/chronicle-editions/<chapter>/<stamp>/`` — never over an existing object, never under ``site/`` or
``generated/`` — then read back and compared by sha256; only then is the pointer written, under
``attribute_not_exists(sk)`` (a chapter's first edition is backed up once). Nothing is deleted or changed in place.

    python3 scripts/chronicle_edition_backup.py --chapter week-04 --row-sk DATE#2026-09-08
    python3 scripts/chronicle_edition_backup.py --chapter week-04 --row-sk DATE#2026-09-08 --apply

Exit: 0 ok · 2 refused (nothing written) · 3 a copy did not read back equal (no pointer written).
The --apply run is an S3 + DynamoDB write: owner-attended (CLAUDE.md, the ask list).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from datetime import datetime, timezone
from typing import Callable, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "lambdas"))
sys.path.insert(0, _HERE)
from chronicle_revision_apply import ddb_backup_key, ddb_json, s3_backup_key  # noqa: E402 — the revision tool's backup forms
from content import chapter_editions as CE  # noqa: E402

BUCKET = "matthew-life-platform"
TABLE = "life-platform"
USER_ID = "matthew"


class Refused(Exception):
    """The backup cannot be taken as asked — nothing was written."""


class Unverified(Exception):
    """A copy did not read back equal — no pointer was written."""


def _get(s3, bucket: str, key: str) -> Optional[bytes]:
    try:
        return s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception as exc:  # noqa: BLE001
        if "NoSuchKey" in type(exc).__name__ or "NoSuchKey" in str(exc) or "404" in str(exc):
            return None
        raise


def plan(chapter_id: str, row_sk: str, s3, table, *, bucket: str = BUCKET, user_id: str = USER_ID, now: str) -> dict:
    """What would be copied, from reads only. Raises ``Refused``."""
    if not CE.CHAPTER_ID.match(chapter_id):
        raise Refused("--chapter must be the v9 id, week-NN")
    pk = CE.pk(user_id)
    if table.get_item(Key={"pk": pk, "sk": CE.sk_original(chapter_id)}, ConsistentRead=True).get("Item"):
        raise Refused(f"{chapter_id}'s first edition is already backed up (its pointer record exists); a backup is taken once")
    row = table.get_item(Key={"pk": pk, "sk": row_sk}, ConsistentRead=True).get("Item")
    if not row:
        raise Refused(f"no chronicle row {row_sk}")
    journal_key = str(row.get("draft_journal_post_key") or "")
    if not journal_key.endswith(f"/{chapter_id}/index.html"):
        raise Refused(
            f"{row_sk} is not {chapter_id}'s row (its journal page is {journal_key or 'unrecorded'}); page address and chapter differ"
        )
    stamp = datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prefix = f"{CE.BACKUP_ROOT}{chapter_id}/{stamp}/"
    objects = [{"source": f"ddb:{row_sk}", "backup_key": ddb_backup_key(prefix, pk, row_sk), "body": ddb_json(row).encode("utf-8")}]
    for key in (journal_key, f"site/story/{chapter_id}/index.html"):
        body = _get(s3, bucket, key)
        if body is None:
            if key == journal_key:
                raise Refused(f"the journal page {key} could not be read")
            continue  # the v9 page is built from the journal page; a chapter without one has nothing more to keep
        objects.append({"source": f"s3:{key}", "backup_key": s3_backup_key(prefix, key), "body": body})
    for o in objects:
        o["sha256"] = hashlib.sha256(o["body"]).hexdigest()
    return {"chapter_id": chapter_id, "row_sk": row_sk, "prefix": prefix, "objects": objects, "now": now, "pk": pk}


def apply(p: dict, s3, table, *, bucket: str = BUCKET, user_id: str = USER_ID, log: Callable = print) -> dict:
    """Copy (write-once), read back, then write the pointer once. Raises ``Unverified`` / ``Refused``."""
    for o in p["objects"]:
        s3.put_object(
            Bucket=bucket,
            Key=o["backup_key"],
            Body=o["body"],
            IfNoneMatch="*",  # never over an existing object: a backup is immutable
            ContentType="application/json" if o["source"].startswith("ddb:") else "text/html; charset=utf-8",
            Metadata={"source": o["source"][:200], "sha256": o["sha256"]},
        )
        back = _get(s3, bucket, o["backup_key"])
        if back is None or hashlib.sha256(back).hexdigest() != o["sha256"]:
            raise Unverified(f"{o['backup_key']} did not read back equal; no pointer written")
        log(f"kept {o['source']} -> s3://{bucket}/{o['backup_key']} (sha256 {o['sha256'][:12]}…)")
    item = CE.original_record(
        chapter_id=p["chapter_id"],
        row_sk=p["row_sk"],
        backup_prefix=p["prefix"],
        objects=[{k: o[k] for k in ("source", "backup_key", "sha256")} for o in p["objects"]],
        backed_up_at=p["now"],
        user_id=user_id,
    )
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(sk)")
    except Exception as exc:  # noqa: BLE001
        raise Refused(f"the pointer record could not be written once ({type(exc).__name__}); the copies stay where they are") from exc
    log(f"pointer {item['sk']} written: {len(item['objects'])} object(s), backed up at {item['backed_up_at']}")
    return item


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Back up a chapter's first edition, privately and write-once, before a later edition.")
    ap.add_argument("--chapter", required=True, help="the v9 chapter id, week-NN (the page address, not the program week)")
    ap.add_argument("--row-sk", required=True, help="the chronicle row's key, DATE#YYYY-MM-DD")
    ap.add_argument("--apply", action="store_true", help="write the backup and the pointer (owner-attended)")
    ap.add_argument("--bucket", default=BUCKET)
    ap.add_argument("--table", default=TABLE)
    args = ap.parse_args(argv)
    import boto3  # noqa: PLC0415

    s3 = boto3.client("s3", region_name="us-west-2")
    table = boto3.resource("dynamodb", region_name="us-west-2").Table(args.table)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        p = plan(args.chapter, args.row_sk, s3, table, bucket=args.bucket, now=now)
    except Refused as exc:
        print(f"REFUSED: {exc}. Nothing was written.", file=sys.stderr)
        return 2
    for o in p["objects"]:
        print(
            f"{'COPY' if args.apply else 'would copy'} {o['source']} ({len(o['body'])} bytes, sha256 {o['sha256'][:12]}…) -> {o['backup_key']}"
        )
    if not args.apply:
        print("dry run: nothing written. Re-run with --apply (owner-attended).")
        return 0
    try:
        apply(p, s3, table, bucket=args.bucket)
    except Unverified as exc:
        print(f"UNVERIFIED: {exc}", file=sys.stderr)
        return 3
    except Refused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "deploy"))
    from lib.prod_write_guard import install_prod_write_guard  # #6116: under a test runner, no real AWS write

    install_prod_write_guard()
    sys.exit(main())
