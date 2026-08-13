"""Storage: raw JSON in object storage, normalized records in a key-value table.

Two backends behind one interface, and the KEYS ARE IDENTICAL in both. That is the
teaching point: the local backend is not a toy mode, it is the same pipeline with
the network removed, so you can see the whole loop before you spend a cent.

    LocalStore  — a directory on your disk. Free, offline, no account.
    AwsStore    — S3 + DynamoDB. Real, and billed. See the README's cost section.
"""

import json
import os
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class LocalStore:
    """Filesystem backend. `root/raw/...` mirrors the S3 keys exactly."""

    kind = "local"

    def __init__(self, root: str):
        self.root = root

    def put_raw(self, key: str, payload: dict) -> str:
        path = os.path.join(self.root, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
        return path

    def _table_path(self, pk: str) -> str:
        safe = pk.replace("#", "_").replace("/", "_")
        return os.path.join(self.root, "table", f"{safe}.json")

    def _read_table(self, pk: str) -> dict:
        path = self._table_path(pk)
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def put_metric(self, pk: str, sk: str, attributes: dict) -> None:
        rows = self._read_table(pk)
        rows[sk] = {"pk": pk, "sk": sk, "ingested_at": _now(), **attributes}
        path = self._table_path(pk)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=2, sort_keys=True)

    def read_metrics(self, pk: str) -> list[dict]:
        return [self._read_table(pk)[sk] for sk in sorted(self._read_table(pk))]


class AwsStore:
    """S3 + DynamoDB backend. Needs credentials and the stack from infrastructure.yaml."""

    kind = "aws"

    def __init__(self, bucket: str, table: str):
        if not bucket or not table:
            raise ValueError("AWS mode needs SLICE_BUCKET and SLICE_TABLE (see the README)")
        import boto3  # imported lazily so the local path needs no dependency at all

        self.bucket = bucket
        self._s3 = boto3.client("s3")
        self._table = boto3.resource("dynamodb").Table(table)

    def put_raw(self, key: str, payload: dict) -> str:
        self._s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(payload, sort_keys=True).encode("utf-8"),
            ContentType="application/json",
        )
        return f"s3://{self.bucket}/{key}"

    def put_metric(self, pk: str, sk: str, attributes: dict) -> None:
        from decimal import Decimal

        # DynamoDB rejects Python floats. Route every number through Decimal via its
        # string form -- Decimal(0.1) carries binary float noise, Decimal("0.1") does not.
        item = {"pk": pk, "sk": sk, "ingested_at": _now()}
        for name, value in attributes.items():
            item[name] = Decimal(str(value)) if isinstance(value, (int, float)) else value
        self._table.put_item(Item=item)

    def read_metrics(self, pk: str) -> list[dict]:
        from boto3.dynamodb.conditions import Key

        rows, kwargs = [], {"KeyConditionExpression": Key("pk").eq(pk), "ScanIndexForward": True}
        while True:
            page = self._table.query(**kwargs)
            rows.extend(page.get("Items", []))
            token = page.get("LastEvaluatedKey")
            if not token:
                return [{k: (float(v) if hasattr(v, "as_tuple") else v) for k, v in row.items()} for row in rows]
            kwargs["ExclusiveStartKey"] = token


def open_store(cfg, local: bool):
    return LocalStore(cfg.local_root) if local else AwsStore(cfg.bucket, cfg.table)
