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
  * its journal page (the row's ``draft_journal_post_key``, which must be the chapter's ``…/posts/<chapter>/index.html``;
    #6193 B1: a row written before that field existed — the prologue and the early weeks — has none, so the key is
    derived from the chapter's page id, ``generated/journal/posts/<chapter>/index.html``, and accepted ONLY when that
    object exists and its page title is the row's title; otherwise the backup is refused);
  * the v9 chapter page at the root (``site/story/<chapter>/index.html``) when it exists.

SAFETY. Dry-run by default: reads only, prints the plan. ``--apply``: every copy is a conditional put (``IfNoneMatch``)
under ``backups/chronicle-editions/<chapter>/<stamp>/`` — never over an existing object, never under ``site/`` or
``generated/`` — then read back and compared by sha256; only then is the pointer written, under
``attribute_not_exists(sk)`` (a chapter's first edition is backed up once). Nothing is deleted or changed in place.

    python3 scripts/chronicle_edition_backup.py --chapter week-04 --row-sk DATE#2026-09-08
    python3 scripts/chronicle_edition_backup.py --chapter week-04 --row-sk DATE#2026-09-08 --apply

RESTORE REHEARSAL (owner ruling 2026-11-22, rehearsal §6: "Verify the restore path, not merely the presence of backup
files"). ``--verify-restore`` reads every object the pointer names back from the private prefix, proves each is byte for
byte what was captured (its recorded sha256), rebuilds the row item from its DynamoDB JSON and proves the rebuilt item
serialises to exactly the captured bytes (item equality), and prints the exact restore commands. Read-only by itself;
with ``--apply`` it then writes the ``…#01#restore`` record once — ``approve_edition`` refuses, and the public view
withholds, every edition of a chapter without it. ``--apply`` on a new backup runs the same rehearsal right after the
pointer is written.

    python3 scripts/chronicle_edition_backup.py --chapter week-04 --verify-restore
    python3 scripts/chronicle_edition_backup.py --chapter week-04 --verify-restore --apply

Exit: 0 ok · 2 refused (nothing written) · 3 a copy did not read back equal, or the restore rehearsal failed (no record
written). The --apply run is an S3 + DynamoDB write: owner-attended (CLAUDE.md, the ask list).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import re
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


JOURNAL_PREFIX = "generated/journal/posts/"
_PAGE_TITLE = re.compile(r"<title>([\s\S]*?)</title>", re.IGNORECASE)


def _page_title(body: bytes) -> Optional[str]:
    m = _PAGE_TITLE.search(body.decode("utf-8", errors="replace"))
    return " ".join(html.unescape(m.group(1)).split()) if m else None


def _title_matches(page_title: Optional[str], row_title: str) -> bool:
    """The journal page's <title> is "<row title> — The Measured Life" (emails/chronicle_render.py)."""
    want = CE.title_key(row_title)
    got = CE.title_key(page_title or "")
    return bool(want) and (got == want or got.startswith(f"{want} — "))


def journal_page(chapter_id: str, row_sk: str, row: dict, s3, bucket: str) -> tuple:
    """``(key, body)`` of the chapter's journal page: the row's recorded key, or (#6193 B1) the key derived from the
    chapter's page id when the row records none — verified to exist and to carry the row's title. Raises ``Refused``."""
    recorded = str(row.get("draft_journal_post_key") or "")
    if recorded:
        if not recorded.endswith(f"/{chapter_id}/index.html"):
            raise Refused(f"{row_sk} is not {chapter_id}'s row (its journal page is {recorded}); page address and chapter differ")
        body = _get(s3, bucket, recorded)
        if body is None:
            raise Refused(f"the journal page {recorded} could not be read")
        return recorded, body
    derived = f"{JOURNAL_PREFIX}{chapter_id}/index.html"
    body = _get(s3, bucket, derived)
    if body is None:
        raise Refused(f"{row_sk} records no journal page and {derived} does not exist; nothing to derive it from")
    title = str(row.get("title") or "")
    if not _title_matches(_page_title(body), title):
        raise Refused(
            f"{row_sk} records no journal page, and {derived} is titled {_page_title(body)!r}, not the row's {title!r}; "
            "page address and chapter differ"
        )
    return derived, body


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
    journal_key, journal_body = journal_page(chapter_id, row_sk, row, s3, bucket)
    stamp = datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prefix = f"{CE.BACKUP_ROOT}{chapter_id}/{stamp}/"
    captured = ddb_json(row).encode("utf-8")
    if ddb_json(rebuild_row(captured)).encode("utf-8") != captured:  # the restore path, rehearsed before anything is written
        raise Refused(f"{row_sk} would not rebuild exactly from its captured DynamoDB JSON; a backup that cannot be restored is not taken")
    objects = [{"source": f"ddb:{row_sk}", "backup_key": ddb_backup_key(prefix, pk, row_sk), "body": captured}]
    objects.append({"source": f"s3:{journal_key}", "backup_key": s3_backup_key(prefix, journal_key), "body": journal_body})
    v9_key = f"site/story/{chapter_id}/index.html"
    v9 = _get(s3, bucket, v9_key)
    if v9 is not None:  # the v9 page is built from the journal page; a chapter without one has nothing more to keep
        objects.append({"source": f"s3:{v9_key}", "backup_key": s3_backup_key(prefix, v9_key), "body": v9})
    for o in objects:
        o["sha256"] = hashlib.sha256(o["body"]).hexdigest()
    return {
        "chapter_id": chapter_id,
        "row_sk": row_sk,
        "prefix": prefix,
        "objects": objects,
        "now": now,
        "pk": pk,
        "journal_key_derived": not row.get("draft_journal_post_key"),
    }


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


def rebuild_row(body: bytes) -> dict:
    """The row item a restore would write, from the captured DynamoDB JSON (``{"Item": {...}}``)."""
    from boto3.dynamodb.types import TypeDeserializer  # noqa: PLC0415

    des = TypeDeserializer()

    def unfix(v):
        if isinstance(v, dict) and set(v) == {"B"}:
            return {"B": base64.b64decode(v["B"])}
        if isinstance(v, dict) and set(v) == {"BS"}:
            return {"BS": [base64.b64decode(x) for x in v["BS"]]}
        if isinstance(v, dict) and set(v) == {"M"}:
            return {"M": {k: unfix(x) for k, x in v["M"].items()}}
        if isinstance(v, dict) and set(v) == {"L"}:
            return {"L": [unfix(x) for x in v["L"]]}
        return v

    doc = json.loads(body.decode("utf-8"))
    return {k: des.deserialize(unfix(v)) for k, v in doc["Item"].items()}


def verify_restore(chapter_id: str, s3, table, *, bucket: str = BUCKET, user_id: str = USER_ID) -> tuple:
    """``(pointer, problems, commands)``: every backed-up object read back and matched to its recorded sha256, the row
    rebuilt and re-serialised to the captured bytes, and the exact restore commands. Read-only."""
    pk = CE.pk(user_id)
    pointer = table.get_item(Key={"pk": pk, "sk": CE.sk_original(chapter_id)}, ConsistentRead=True).get("Item")
    try:
        CE.validate_original(pointer)
    except CE.EditionError as exc:
        raise Refused(f"{chapter_id} has no first-edition backup pointer to rehearse ({exc}); run the backup first") from exc
    problems, commands = [], []
    for o in pointer["objects"]:
        body = _get(s3, bucket, o["backup_key"])
        if body is None:
            problems.append(f"{o['backup_key']}: missing")
            continue
        if hashlib.sha256(body).hexdigest() != o["sha256"]:
            problems.append(f"{o['backup_key']}: does not match the sha256 captured at backup")
            continue
        src = str(o["source"])
        if src.startswith("ddb:"):
            try:
                item = rebuild_row(body)
            except Exception as exc:  # noqa: BLE001
                problems.append(f"{o['backup_key']}: the row cannot be rebuilt ({type(exc).__name__})")
                continue
            if ddb_json(item).encode("utf-8") != body or item.get("pk") != pk or f"ddb:{item.get('sk')}" != src:
                problems.append(f"{o['backup_key']}: the rebuilt row is not the captured item")
                continue
            commands.append(
                f"aws s3 cp s3://{bucket}/{o['backup_key']} - | jq '.Item' > row.json && "
                f"aws dynamodb put-item --region us-west-2 --table-name {TABLE} --item file://row.json"
            )
        else:
            commands.append(f"aws s3 cp s3://{bucket}/{o['backup_key']} s3://{bucket}/{src[3:]}")
    return pointer, problems, commands


def record_restore(chapter_id: str, s3, table, *, bucket: str = BUCKET, user_id: str = USER_ID, now: str, log: Callable = print) -> dict:
    """Rehearse the restore; only if every check passed, write the ``…#01#restore`` record once. Raises ``Unverified``."""
    pointer, problems, _cmds = verify_restore(chapter_id, s3, table, bucket=bucket, user_id=user_id)
    if problems:
        raise Unverified("; ".join(problems) + " — no restore record written")
    item = CE.restore_record(original=pointer, verified_at=now, user_id=user_id)
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(sk)")
    except Exception as exc:  # noqa: BLE001
        raise Refused(f"the restore record could not be written once ({type(exc).__name__})") from exc
    log(f"restore rehearsal passed and recorded: {item['sk']} ({len(item['objects'])} object(s))")
    return item


def _main_restore(args, s3, table, now: str) -> int:
    try:
        _pointer, problems, commands = verify_restore(args.chapter, s3, table, bucket=args.bucket)
    except Refused as exc:
        print(f"REFUSED: {exc}. Nothing was written.", file=sys.stderr)
        return 2
    for p in problems:
        print(f"✗ {p}")
    if problems:
        print("UNVERIFIED: the restore path does not hold; nothing written.", file=sys.stderr)
        return 3
    print(f"✓ every backed-up object of {args.chapter} reads back byte-identical, and the row rebuilds to the captured item")
    print("restore commands (owner-attended; NOT run here):")
    for c in commands:
        print(f"  {c}")
    if not args.apply:
        print("dry run: no restore record written. Re-run with --apply to record that the rehearsal passed.")
        return 0
    try:
        record_restore(args.chapter, s3, table, bucket=args.bucket, now=now)
    except (Unverified, Refused) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3
    return 0


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Back up a chapter's first edition, privately and write-once, before a later edition.")
    ap.add_argument("--chapter", required=True, help="the v9 chapter id, week-NN (the page address, not the program week)")
    ap.add_argument("--row-sk", help="the chronicle row's key, DATE#YYYY-MM-DD (required for a backup)")
    ap.add_argument("--apply", action="store_true", help="write the backup and the pointer (owner-attended)")
    ap.add_argument("--verify-restore", action="store_true", help="rehearse the restore of an existing backup (read-only without --apply)")
    ap.add_argument("--bucket", default=BUCKET)
    ap.add_argument("--table", default=TABLE)
    args = ap.parse_args(argv)
    import boto3  # noqa: PLC0415

    s3 = boto3.client("s3", region_name="us-west-2")
    table = boto3.resource("dynamodb", region_name="us-west-2").Table(args.table)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if args.verify_restore:
        return _main_restore(args, s3, table, now)
    if not args.row_sk:
        ap.error("--row-sk is required for a backup")
    try:
        p = plan(args.chapter, args.row_sk, s3, table, bucket=args.bucket, now=now)
    except Refused as exc:
        print(f"REFUSED: {exc}. Nothing was written.", file=sys.stderr)
        return 2
    if p["journal_key_derived"]:
        print(f"journal page derived from the page id (the row records none); its title matches the row: {p['objects'][1]['source'][3:]}")
    for o in p["objects"]:
        print(
            f"{'COPY' if args.apply else 'would copy'} {o['source']} ({len(o['body'])} bytes, sha256 {o['sha256'][:12]}…) -> {o['backup_key']}"
        )
    if not args.apply:
        print("restore path rehearsed in memory: the row rebuilds exactly from its captured DynamoDB JSON")
        print("dry run: nothing written. Re-run with --apply (owner-attended).")
        return 0
    try:
        apply(p, s3, table, bucket=args.bucket)
        record_restore(args.chapter, s3, table, bucket=args.bucket, now=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
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
