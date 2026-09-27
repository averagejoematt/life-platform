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

import boto3

from training.routine_ir import RoutineSpec, deserialize, serialize

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


def _version_sk(version) -> str:
    # DDB round-trips Decimal -> float in deserialize, so `version` may arrive
    # as 1.0 rather than 1. Cast defensively.
    return f"VERSION#{int(version):06d}"


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
    # DDB round-trip may have turned version into a float; coerce.
    ir.version = int(ir.version)
    if ir.parent_version is not None:
        ir.parent_version = int(ir.parent_version)
    attempted_version = ir.version
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
        # #3115: the caller bumps `ir.version` BEFORE calling us (`ir.parent_version =
        # ir.version; ir.version += 1`), so a refused write used to leave the in-memory
        # IR one version ahead of the store — the counter advanced on a write that never
        # happened, and the next attempt skipped a version number for no reason. Rewind
        # to the version this object actually has persisted before surfacing the conflict.
        if ir.parent_version is not None and ir.parent_version < attempted_version:
            ir.version = int(ir.parent_version)
        raise RoutineConflict(f"VERSION#{attempted_version:06d} for routine {ir.routine_id} already exists") from e

    pointer_item = {**body, "pk": pk, "sk": "VERSION#current"}
    _table.put_item(Item=pointer_item)
    # Date-sorted index for list_by_date_range; idempotent put (same routine
    # writes the same index sk every time).
    _table.put_item(
        Item={
            "pk": INDEX_PK,
            "sk": f"DATE#{ir.target_date}#ROUTINE#{ir.routine_id}",
            "routine_id": ir.routine_id,
            "target_date": ir.target_date,
            "archetype": ir.archetype,
            "variant": ir.variant,
            "status": ir.status,
            # Hevy routine id (set once the routine is pushed) — lets routine_title
            # resolve a performed workout's type by the EXACT routine it came from
            # (workout.hevy_routine_id), not just nearest-date. Empty until commit.
            "hevy_routine_id": ir.hevy_routine_id or "",
        }
    )
    return ir


def draft_versioned(ir: RoutineSpec) -> RoutineSpec:
    """Persist a DRAFT idempotently (#3115) — the entry point every drafting path uses.

    `routine_id` is now derived from `(target_date, archetype, variant)` rather than a
    `uuid4` (`routine_generator._new_routine_id`), so a re-run of the authoring cron or
    a retried `manage_hevy_routine draft` lands on the SAME partition. A bare
    `put_versioned` at `version=1` would then hit the `attribute_not_exists` guard and
    raise `RoutineConflict`, which is not the answer either — a re-draft is legitimate.

    So adopt the stored routine: write the new draft as the NEXT version of it, and
    carry the Hevy linkage forward so the following commit takes the UPDATE branch
    instead of POSTing a second remote routine. That is the actual cure for "a replay
    of a fresh draft creates a second remote routine".

    An ARCHIVED predecessor's Hevy link is deliberately NOT carried: that routine has
    been renamed `[archived …]` and moved to the Archive folder in Hevy, so pointing a
    new draft at it would resurrect an archived routine rather than create today's.
    """
    existing = get_current(ir.routine_id)
    if not existing:
        return put_versioned(ir)
    ir.parent_version = int(existing.version)
    ir.version = int(existing.version) + 1
    if existing.status != "archived":
        ir.hevy_routine_id = ir.hevy_routine_id or existing.hevy_routine_id
        ir.hevy_updated_at = ir.hevy_updated_at or existing.hevy_updated_at
        ir.hevy_folder_id = ir.hevy_folder_id or existing.hevy_folder_id
        ir.hevy_pushed_at = ir.hevy_pushed_at or existing.hevy_pushed_at
    logger.info(f"re-draft of {ir.routine_id} adopted as version {ir.version} (hevy={ir.hevy_routine_id or 'unpushed'})")
    return put_versioned(ir)


def list_by_date_range(start_date: str, end_date: str, limit: int = 100) -> list[RoutineSpec]:
    """Query the date-sorted index partition (cheap), then GetItem each
    current-version pointer. Replaces an earlier Scan that hit the whole
    table and missed records when Limit cut off the page before the matches.
    """
    from boto3.dynamodb.conditions import Key

    resp = _table.query(
        KeyConditionExpression=Key("pk").eq(INDEX_PK) & Key("sk").between(f"DATE#{start_date}", f"DATE#{end_date}#￿"),
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


def _live_genesis() -> str | None:
    """The current cycle's genesis as a day key, read at CALL time (a re-anchor or a test
    monkeypatch lands without a module reload — the same shape as
    `phase_taxonomy.cycle_read_floor`). None when the constant is unavailable, and a None
    genesis means NOTHING is pre-genesis: the census falls back to counting every stale draft,
    which is the conservative direction (a widened census, never a silently narrowed one)."""
    try:
        from common import constants as _c

        g = str(getattr(_c, "EXPERIMENT_START_DATE", "") or "")
    except Exception:  # noqa: BLE001 — fail-soft: never break a census over the constant
        return None
    return g or None


def stale_draft_census(older_than_days: int = 7, lookback_days: int = 120, today: str | None = None, genesis: str | None = None) -> dict:
    """#4183: the orphan-draft census, partitioned by the genesis.

    #3772's question was "which drafts did the soft-timeout leave behind that nobody knows
    about?" — and the answer it computed was "every draft older than `older_than_days`
    inside the lookback", which on 2026-09-20 (the leg's FIRST night) was 22: eighteen of
    them June 2026 drafts from a cycle the 2026-09-06 reset had already closed. A draft whose
    target day is BEFORE the genesis is history — nobody can commit it to Hevy for a day the
    experiment does not count, and the reset never tombstones the ROUTINE# partition (it is
    SYSTEM_STATE by ruling, see phase_taxonomy), so the leg has to read the genesis itself.

    The routine rows carry no `phase`/`cycle` stamp (SYSTEM_STATE rows never do — verified
    on the wire 2026-09-26), so the ONE discriminator is the row's own `target_date`
    against the live genesis, compared as ISO day-key strings (#3609: never fromisoformat).

    Returns a dict, never a bare list, so the caller can NAME the window it used:
      live        — stale drafts targeting a day on/after the genesis (the actionable set)
      pre_genesis — stale drafts targeting a day before it (history, excluded by name)
      window      — {start, end, cutoff, genesis, today} exactly as the Query walked them
    Both lists are sorted oldest-created first. Read-only: one bounded index Query. This
    REPLACES #3772's `list_stale_drafts` (the unpartitioned list; its only caller was the leg).
    The listing a human asks for is `list_for_tool` (`manage_hevy_routine list`), unpartitioned.
    """
    from common.pacific_time import pacific_today, shift_day_key

    # #3609: day keys move through the platform's one day-key shifter, never a hand-rolled fromisoformat
    today_key = today or pacific_today()
    start = shift_day_key(today_key, -lookback_days)
    end = shift_day_key(today_key, 7)  # a draft may target a day still ahead
    cutoff = shift_day_key(today_key, -older_than_days)
    genesis_key = genesis if genesis is not None else _live_genesis()
    live: list[RoutineSpec] = []
    pre_genesis: list[RoutineSpec] = []
    for ir in list_by_date_range(start, end, limit=500):
        created = str(ir.created_at or "")[:10]
        if not (ir.status == "draft" and created and created <= cutoff):
            continue
        # A None genesis partitions nothing into history (see _live_genesis) — the widened
        # census is the honest failure, a narrowed one is the silent failure.
        if genesis_key and str(ir.target_date or "") < genesis_key:
            pre_genesis.append(ir)
        else:
            live.append(ir)
    order = lambda r: (str(r.created_at or ""), r.routine_id)  # noqa: E731
    return {
        "live": sorted(live, key=order),
        "pre_genesis": sorted(pre_genesis, key=order),
        "window": {"start": start, "end": end, "cutoff": cutoff, "genesis": genesis_key, "today": today_key},
    }


def list_for_tool(args: dict) -> dict:
    """#3772: the `manage_hevy_routine list` payload — date range plus `status` / `older_than_days` filters.
    Lives beside the listing it filters (and out of the 1000-line tool module)."""
    start = args.get("start_date") or args.get("date") or "2026-05-31"
    end = args.get("end_date") or args.get("date") or start
    items = list_by_date_range(start, end, limit=int(args.get("limit") or 50))
    # #3772: `status` and `older_than_days` filters, so orphaned drafts can be listed at all
    # (a draft the #3765 soft-timeout left behind was invisible to every caller).
    status_filter = (args.get("status") or "").strip().lower()
    if status_filter:
        items = [ir for ir in items if (ir.status or "").lower() == status_filter]
    older = args.get("older_than_days")
    if older is not None and str(older).strip() != "":
        from common.pacific_time import pacific_today, shift_day_key

        cutoff = shift_day_key(pacific_today(), -int(older))  # #3609: no hand-rolled fromisoformat
        items = [ir for ir in items if str(ir.created_at or "")[:10] and str(ir.created_at or "")[:10] <= cutoff]
    return {
        "status": "ok",
        "count": len(items),
        "filters": {k: v for k, v in (("status", status_filter or None), ("older_than_days", older)) if v is not None},
        "routines": [
            {
                "routine_id": ir.routine_id,
                "target_date": ir.target_date,
                "archetype": ir.archetype,
                "variant": ir.variant,
                "status": ir.status,
                "hevy_routine_id": ir.hevy_routine_id,
                "version": ir.version,
                "created_at": ir.created_at,
            }
            for ir in items
        ],
    }


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
        raise RoutineConflict(f"id-map already present for routine_id={routine_id} / hevy={hevy_routine_id}") from e


def lookup_hevy_id(routine_id: str) -> str | None:
    resp = _table.get_item(Key={"pk": ID_MAP_PK, "sk": f"PLATFORM#{routine_id}"})
    item = resp.get("Item")
    return item.get("hevy_routine_id") if item else None


def lookup_routine_id(hevy_routine_id: str) -> str | None:
    resp = _table.get_item(Key={"pk": ID_MAP_PK, "sk": f"HEVY#{hevy_routine_id}"})
    item = resp.get("Item")
    return item.get("routine_id") if item else None
