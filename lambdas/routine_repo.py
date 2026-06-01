"""
routine_repo.py — DynamoDB CRUD for the ROUTINE# partition.

Keys (per SPEC §SCHEMA addition):
  pk: USER#matthew#ROUTINE#<routine_id>
  sk: VERSION#<padded_version>      (e.g. VERSION#000001)
  sk: VERSION#current               (current-version pointer)

ID map:
  pk: USER#matthew#SOURCE#hevy_id_map
  sk: PLATFORM#<routine_id>         (value: hevy_routine_id)
  sk: HEVY#<hevy_routine_id>        (reverse lookup)

Writes are versioned; bump version + write a new VERSION#<n> item, then
update VERSION#current. The id-map write is conditional (no overwrite) so
two concurrent first-push attempts can't collide.
"""
from __future__ import annotations

import logging
import os
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from routine_ir import RoutineSpec, deserialize, serialize

logger = logging.getLogger("routine_repo")

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
PK_PREFIX = f"USER#{USER_ID}#ROUTINE#"
ID_MAP_PK = f"USER#{USER_ID}#SOURCE#hevy_id_map"
INDEX_PK = f"USER#{USER_ID}#SOURCE#routine_index"

_ddb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-west-2"))
_table = _ddb.Table(TABLE_NAME)


class RoutineConflict(Exception):
    """Concurrent write detected via conditional check."""


def _pk(routine_id: str) -> str:
    return f"{PK_PREFIX}{routine_id}"


def _version_sk(version: int) -> str:
    return f"VERSION#{version:06d}"


def get_current(routine_id: str) -> RoutineSpec | None:
    resp = _table.get_item(Key={"pk": _pk(routine_id), "sk": "VERSION#current"})
    item = resp.get("Item")
    return deserialize(item) if item else None


def get_version(routine_id: str, version: int) -> RoutineSpec | None:
    resp = _table.get_item(Key={"pk": _pk(routine_id), "sk": _version_sk(version)})
    item = resp.get("Item")
    return deserialize(item) if item else None


def put_versioned(ir: RoutineSpec) -> RoutineSpec:
    """Write a new immutable VERSION#<n> item and update VERSION#current.

    On first write (version=1), parent_version is None. On subsequent writes
    the caller is responsible for setting ir.parent_version = previous version
    and bumping ir.version. Refuses to overwrite an existing VERSION#<n>.
    """
    body = serialize(ir)
    pk = _pk(ir.routine_id)
    history_sk = _version_sk(ir.version)

    history_item = {**body, "pk": pk, "sk": history_sk}
    try:
        _table.put_item(
            Item=history_item,
            ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)",
        )
    except _ddb.meta.client.exceptions.ConditionalCheckFailedException as e:
        raise RoutineConflict(
            f"VERSION#{ir.version:06d} for routine {ir.routine_id} already exists"
        ) from e

    pointer_item = {**body, "pk": pk, "sk": "VERSION#current"}
    _table.put_item(Item=pointer_item)
    # Date-sorted index for list_by_date_range; idempotent put (same routine
    # writes the same index sk every time).
    _table.put_item(Item={
        "pk": INDEX_PK,
        "sk": f"DATE#{ir.target_date}#ROUTINE#{ir.routine_id}",
        "routine_id": ir.routine_id,
        "target_date": ir.target_date,
        "archetype": ir.archetype,
        "variant": ir.variant,
        "status": ir.status,
    })
    return ir


def list_by_date_range(start_date: str, end_date: str, limit: int = 100) -> list[RoutineSpec]:
    """Query the date-sorted index partition (cheap), then GetItem each
    current-version pointer. Replaces an earlier Scan that hit the whole
    table and missed records when Limit cut off the page before the matches.
    """
    from boto3.dynamodb.conditions import Key
    resp = _table.query(
        KeyConditionExpression=Key("pk").eq(INDEX_PK)
            & Key("sk").between(f"DATE#{start_date}", f"DATE#{end_date}#￿"),
        Limit=limit,
    )
    routines: list[RoutineSpec] = []
    seen: set[str] = set()
    for idx in resp.get("Items", []):
        rid = idx.get("routine_id")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        ir = get_current(rid)
        if ir:
            routines.append(ir)
    return routines


def upsert_id_map(routine_id: str, hevy_routine_id: str) -> None:
    """Persist platform <-> Hevy id mapping. Conditional on neither side present."""
    try:
        _table.put_item(
            Item={
                "pk": ID_MAP_PK,
                "sk": f"PLATFORM#{routine_id}",
                "hevy_routine_id": hevy_routine_id,
                "routine_id": routine_id,
            },
            ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)",
        )
        _table.put_item(
            Item={
                "pk": ID_MAP_PK,
                "sk": f"HEVY#{hevy_routine_id}",
                "routine_id": routine_id,
                "hevy_routine_id": hevy_routine_id,
            },
            ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)",
        )
    except _ddb.meta.client.exceptions.ConditionalCheckFailedException as e:
        raise RoutineConflict(
            f"id-map already present for routine_id={routine_id} / hevy={hevy_routine_id}"
        ) from e


def lookup_hevy_id(routine_id: str) -> str | None:
    resp = _table.get_item(Key={"pk": ID_MAP_PK, "sk": f"PLATFORM#{routine_id}"})
    item = resp.get("Item")
    return item.get("hevy_routine_id") if item else None


def lookup_routine_id(hevy_routine_id: str) -> str | None:
    resp = _table.get_item(Key={"pk": ID_MAP_PK, "sk": f"HEVY#{hevy_routine_id}"})
    item = resp.get("Item")
    return item.get("routine_id") if item else None
