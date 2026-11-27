"""scripts/backfill_public_variant_backup.py — the public recompute's durable pre-image backup (#6224, owner 2026-11-27).

Owner conditions: "backup before writes", "verified rollback", "Verify backup and conditional-write preconditions". The
public tool's pre-image export used to exist only as a local file in ``--out``; it now meets the private tool's standard
(``recompute_character_private_apply.export_and_verify``, mirrored here — that helper is bound to the private export
schema and its store, so it is not reused):

  * under ``--apply``, BEFORE the first DynamoDB write of each phase, the export is written locally (+ ``.sha256``),
    re-read and hashed, then put to S3 at ``backups/character-public-recompute/<public_plan_id>/export_<phase>.json``
    with a CONDITIONAL put (``IfNoneMatch='*'``: an existing backup for this plan id is never overwritten), read back and
    hashed; only then does the apply write. Any failure ABORTS with zero writes.
  * a refused put (the key exists) is a RESUMED apply only when the existing object's CONTENT digest (the export without
    its run stamp ``taken_at``) equals the export about to be used; otherwise it stops. A resume after a partial apply
    therefore stops (its live pre-images differ): roll back from the backup first.
  * the sha256 of the uploaded body is also put (conditionally) beside it as ``export_<phase>.json.sha256`` and written to
    ``apply_result.json``; ``--rollback`` accepts the local file or the ``s3://`` copy and verifies that sha256 first.

The backup holds private per-date values. ``backups/`` is not anonymously readable: ``deploy/bucket_policy.json`` grants
public ``s3:GetObject`` only on ``site/*`` and named ``generated/*`` paths (``PublicReadSite`` / ``PublicReadGenerated``),
and no statement names ``backups/``. Never write it under ``site/`` or ``generated/``.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Optional

BACKUP_PREFIX = "backups/character-public-recompute"
UNVERIFIABLE = [
    "the conditional put (IfNoneMatch='*') itself, and the role's s3:PutObject / dynamodb:UpdateItem / dynamodb:PutItem "
    "at request time (a read proves neither)"
]


class BackupError(RuntimeError):
    """The pre-image backup could not be written or verified: the apply makes no write."""


class BackupExists(RuntimeError):
    """The conditional put was refused: an object already exists at the key."""


class S3Backups:
    """The S3 surface the backup needs (boto3 client): a conditional put, a get, a list and the versioning status."""

    def __init__(self, s3: Any, bucket: str):
        self.s3, self.bucket = s3, bucket

    def put_new(self, key: str, body: bytes) -> None:
        try:
            self.s3.put_object(Bucket=self.bucket, Key=key, Body=body, IfNoneMatch="*", ContentType="application/json")
        except Exception as exc:  # noqa: BLE001 — botocore ClientError; a 412 is "the key exists"
            code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
            if code in ("PreconditionFailed", "412", "ConditionalRequestConflict"):
                raise BackupExists(key) from exc
            raise

    def get(self, key: str) -> bytes:
        return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def list(self, prefix: str) -> list:
        return [o["Key"] for o in self.s3.list_objects_v2(Bucket=self.bucket, Prefix=prefix, MaxKeys=1000).get("Contents", [])]

    def versioning(self) -> Optional[str]:
        return self.s3.get_bucket_versioning(Bucket=self.bucket).get("Status")


def backup_key(public_plan_id: str, phase: str) -> str:
    key = f"{BACKUP_PREFIX}/{public_plan_id}/export_{phase}.json"
    assert key.startswith("backups/") and "/site/" not in key and "/generated/" not in key
    return key


def body_of(export: dict) -> bytes:
    return json.dumps({k: v for k, v in export.items() if not k.startswith("_")}, sort_keys=True, indent=1, default=str).encode()


def content_digest(body: bytes) -> str:
    """The export's content, its run stamp aside — equal for two exports of the same pre-images."""
    doc = json.loads(body)
    doc.pop("taken_at", None)
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()


def backup_export(store: Any, export: dict, public_plan_id: str, phase: str, local_path: str) -> dict:
    """Write and verify the pre-image backup (local + S3) BEFORE any write. Raises BackupError (no write) on any failure.

    The local copy is STAGED as ``<local_path>.pending`` (no ``.sha256`` beside it, so ``load_export`` refuses it) and
    becomes ``<local_path>`` + ``.sha256`` only once the S3 copy is written and read back to its hash — a failed or
    refused put never leaves a local file that looks like a completed backup (the same rule as the private tool's
    ``put_verified_backup``)."""
    body = body_of(export)
    sha = hashlib.sha256(body).hexdigest()
    pending = local_path + ".pending"
    try:
        with open(pending, "wb") as fh:
            fh.write(body)
        with open(pending, "rb") as fh:
            if hashlib.sha256(fh.read()).hexdigest() != sha:
                raise BackupError("the staged local export does not read back to its hash — no write made")
    except OSError as exc:
        raise BackupError(f"the local export could not be staged ({exc}) — no write made") from exc
    key = backup_key(public_plan_id, phase)
    resumed = False
    try:
        store.put_new(key, body)
    except BackupExists:
        existing = store.get(key)
        if content_digest(existing) != content_digest(body):
            raise BackupError(f"a DIFFERENT backup already exists at {key} — stop (roll back from it, or re-plan) — no write made")
        resumed, body, sha = True, existing, hashlib.sha256(existing).hexdigest()
        with open(pending, "wb") as fh:  # the backup of record is the existing one: the local copy follows it
            fh.write(body)
    except Exception as exc:  # noqa: BLE001 — any put failure aborts
        raise BackupError(f"the S3 backup put failed ({exc}) — no write made") from exc
    try:
        if hashlib.sha256(store.get(key)).hexdigest() != sha:
            raise BackupError("the S3 backup does not read back to the export's hash — no write made")
        if not resumed:
            store.put_new(key + ".sha256", (sha + "\n").encode())
    except BackupExists:
        if store.get(key + ".sha256").decode().strip() != sha:
            raise BackupError("the S3 backup's recorded sha256 does not match — no write made")
    except BackupError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise BackupError(f"the S3 backup could not be verified ({exc}) — no write made") from exc
    os.replace(pending, local_path)  # the S3 copy verified: only now does the local file claim a backup
    with open(local_path + ".sha256", "w", encoding="utf-8") as fh:
        fh.write(sha + "\n")
    return {"key": key, "sha256": sha, "local": local_path, "resumed": resumed}


def load_export(ref: str, store: Optional[Any]) -> dict:
    """The export to roll back from — a local file or ``s3://bucket/key`` — after verifying its recorded sha256 (the
    ``.sha256`` beside it). Raises BackupError on a missing or mismatched hash."""
    if ref.startswith("s3://"):
        if store is None:
            raise BackupError("an s3:// rollback needs the S3 client")
        key = ref.split("/", 3)[3]
        body, recorded = store.get(key), store.get(key + ".sha256").decode().strip()
    else:
        with open(ref, "rb") as fh:
            body = fh.read()
        side = ref + ".sha256"
        if not os.path.exists(side):
            raise BackupError(f"{ref} has no recorded sha256 ({side}) — refusing to roll back from an unverifiable export")
        recorded = open(side, encoding="utf-8").read().strip()
    if hashlib.sha256(body).hexdigest() != recorded:
        raise BackupError(f"{ref} does not match its recorded sha256 — refusing")
    return json.loads(body)


def preflight(store: Any, public_plan_id: str) -> dict:
    """Read-only backup preconditions (the private tool's shape): no backup yet under this plan id's prefix
    (ListObjectsV2) and the bucket is versioned (GetBucketVersioning). Nothing is written."""
    prefix = f"{BACKUP_PREFIX}/{public_plan_id}/"
    existing = store.list(prefix)
    versioning = store.versioning()
    return {
        "ok": not existing and versioning == "Enabled",
        "verified_read_only": {
            "backup_prefix": prefix,
            "no_backup_under_prefix_yet": not existing,
            "existing_keys": existing[:10],
            "bucket_versioning": versioning,
        },
        "unverifiable_without_a_write": UNVERIFIABLE,
    }


def apply_phase(
    table: Any, store: Any, export: dict, phase_plan: list, public_plan_id: str, phase: str, out: str, ledger_item: Optional[dict]
) -> dict:
    """Backup FIRST (local + conditional S3 put, both verified), then the phase's writes. Raises BackupError with zero
    writes made when the backup cannot be written or verified."""
    import backfill_public_variant as B

    local = os.path.join(out, f"export_{phase}_{public_plan_id}.json")
    backup = backup_export(store, export, public_plan_id, phase, local)
    result = B.apply_plan(table, phase_plan, export)
    if ledger_item is not None:
        B.put_public_ledger(table, ledger_item)
    result["backup"] = backup
    return result
