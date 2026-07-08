"""Tests for #475 — the Hevy edit/delete lifecycle (review findings C-7/C-8).

Covers the four legs of the fix:
  1. tombstone consumption — DELETE#WORKOUT# markers finally get their reader
     (resolve_tombstones): matching records removed, marker stamped resolved;
  2. start-time-edit relocation — write_normalized cleans up the old sk;
  3. local-date keying — records key by the workout's Pacific calendar day
     (strava start_date_local parity), not UTC;
  4. cursor behavior — a MAX_PAGES-truncated walk does NOT advance `since`.

Plus the migration script (scripts/migrate_hevy_local_date_keys.py):
dry-run-by-default, idempotent re-keying, collision handling.

No AWS calls: hevy_common._table is replaced by a FakeTable with a minimal
boto3-conditions evaluator (eq / begins_with / AND — exactly what the lifecycle
queries use).
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "ingestion"))

HEVY_PK = "USER#matthew#SOURCE#hevy"


# ── Fake DDB table with a tiny key-condition evaluator ───────────────────────


def _match(cond, item) -> bool:
    """Evaluate the subset of boto3 conditions the lifecycle code uses."""
    exp = cond.get_expression()
    op = exp["operator"]
    vals = exp["values"]
    if op == "AND":
        return _match(vals[0], item) and _match(vals[1], item)
    attr, val = vals
    name = attr.name
    if op == "=":
        return item.get(name) == val
    if op == "begins_with":
        return str(item.get(name, "")).startswith(val)
    raise NotImplementedError(f"FakeTable does not evaluate operator {op!r}")


class FakeTable:
    def __init__(self, items=None):
        self.items: dict[tuple, dict] = {}
        for it in items or []:
            self.items[(it["pk"], it["sk"])] = dict(it)
        self.puts: list[dict] = []
        self.deletes: list[str] = []
        self.updates: list[tuple] = []
        self.fail_put_skts: set = set()  # sks whose put_item raises (failure injection)

    def put_item(self, Item):
        if Item.get("sk") in self.fail_put_skts:
            raise RuntimeError(f"injected put failure for {Item['sk']}")
        self.puts.append(dict(Item))
        self.items[(Item["pk"], Item["sk"])] = dict(Item)
        return {}

    def get_item(self, Key):
        it = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(it)} if it else {}

    def delete_item(self, Key):
        self.deletes.append(Key["sk"])
        self.items.pop((Key["pk"], Key["sk"]), None)
        return {}

    def update_item(self, Key, UpdateExpression=None, ExpressionAttributeValues=None, **kw):
        self.updates.append((Key["sk"], UpdateExpression, ExpressionAttributeValues))
        it = self.items.get((Key["pk"], Key["sk"]))
        if it is not None and UpdateExpression and UpdateExpression.startswith("SET "):
            for clause in UpdateExpression[len("SET ") :].split(","):  # noqa: E203
                name, _, placeholder = clause.strip().partition(" = ")
                it[name.strip()] = ExpressionAttributeValues[placeholder.strip()]
        return {}

    def query(self, KeyConditionExpression=None, **kw):
        out = [dict(it) for sk_key, it in sorted(self.items.items()) if _match(KeyConditionExpression, it)]
        return {"Items": out}


def _workout_item(wid: str, date: str, **extra) -> dict:
    return {
        "pk": HEVY_PK,
        "sk": f"DATE#{date}#WORKOUT#{wid}",
        "date": date,
        "source": "hevy",
        "source_workout_id": wid,
        "start_time": extra.pop("start_time", f"{date}T15:00:00Z"),
        **extra,
    }


@pytest.fixture
def hevy_common():
    import hevy_common as hc

    return hc


@pytest.fixture
def fake_table(hevy_common, monkeypatch):
    tbl = FakeTable()
    monkeypatch.setattr(hevy_common, "_table", tbl)
    return tbl


# ── 3 · Local-date keying (C-8) ───────────────────────────────────────────────


def test_evening_lift_keys_to_pacific_day(hevy_common):
    """03:30 UTC = 20:30 PDT the PREVIOUS day — the C-8 latent bug case."""
    rec = hevy_common.normalize_workout(
        {"workout": {"id": "w_eve", "start_time": "2026-07-02T03:30:00Z", "end_time": "2026-07-02T04:15:00Z", "exercises": []}}
    )
    assert rec["date"] == "2026-07-01"
    assert rec["sk"] == "DATE#2026-07-01#WORKOUT#w_eve"


def test_morning_lift_date_unchanged(hevy_common):
    """16:00 UTC = 09:00 PDT same day — UTC and local agree for morning lifts."""
    rec = hevy_common.normalize_workout({"workout": {"id": "w_am", "start_time": "2026-07-02T16:00:00Z", "exercises": []}})
    assert rec["date"] == "2026-07-02"


def test_winter_pst_offset(hevy_common):
    """DST-awareness: January is PST (UTC-8), so 05:59 UTC is still yesterday."""
    rec = hevy_common.normalize_workout({"workout": {"id": "w_jan", "start_time": "2026-01-15T05:59:00Z", "exercises": []}})
    assert rec["date"] == "2026-01-14"


def test_naive_start_assumed_utc(hevy_common):
    assert hevy_common.local_date_of_start(datetime(2026, 7, 2, 3, 30)) == "2026-07-01"


def test_schema_version_bumped(hevy_common):
    """The keying change is a schema semantic change — v2 per the module contract."""
    assert hevy_common.SCHEMA_VERSION == 2


# ── 2 · Start-time-edit relocation (C-7) ─────────────────────────────────────


def test_write_normalized_relocates_on_cross_date_edit(hevy_common, fake_table):
    """An edit that moves start_time across a date boundary must move the record,
    not duplicate it — old sk deleted, new sk present."""
    fake_table.put_item(Item=_workout_item("w1", "2026-07-02"))
    fake_table.puts.clear()

    rec = _workout_item("w1", "2026-07-01", start_time="2026-07-02T03:30:00Z")
    hevy_common.write_normalized(dict(rec))

    assert "DATE#2026-07-02#WORKOUT#w1" in fake_table.deletes
    assert (HEVY_PK, "DATE#2026-07-01#WORKOUT#w1") in fake_table.items
    assert (HEVY_PK, "DATE#2026-07-02#WORKOUT#w1") not in fake_table.items


def test_write_normalized_same_sk_is_pure_upsert(hevy_common, fake_table):
    """Re-ingesting an unmoved workout deletes nothing (idempotent upsert)."""
    fake_table.put_item(Item=_workout_item("w1", "2026-07-01"))
    hevy_common.write_normalized(_workout_item("w1", "2026-07-01"))
    assert fake_table.deletes == []


def test_relocation_does_not_touch_other_workouts(hevy_common, fake_table):
    fake_table.put_item(Item=_workout_item("other", "2026-07-02"))
    hevy_common.write_normalized(_workout_item("w1", "2026-07-01"))
    assert (HEVY_PK, "DATE#2026-07-02#WORKOUT#other") in fake_table.items
    assert fake_table.deletes == []


def test_relocation_id_match_is_exact_not_prefix(hevy_common, fake_table):
    """sk-suffix matching must not treat workout id 'w1' as matching 'xw1'."""
    fake_table.put_item(Item=_workout_item("xw1", "2026-07-02"))
    hevy_common.write_normalized(_workout_item("w1", "2026-07-01"))
    assert (HEVY_PK, "DATE#2026-07-02#WORKOUT#xw1") in fake_table.items
    assert fake_table.deletes == []


# ── 1 · Tombstone consumption (C-7) ──────────────────────────────────────────


def _marker(wid: str, **extra) -> dict:
    return {"pk": HEVY_PK, "sk": f"DELETE#WORKOUT#{wid}", "tombstone": True, "tombstoned_at": "2026-07-08T00:00:00Z", **extra}


def test_resolve_tombstones_removes_record_and_stamps_marker(hevy_common, fake_table):
    fake_table.put_item(Item=_workout_item("w9", "2026-06-20"))
    fake_table.put_item(Item=_workout_item("w8", "2026-06-20"))
    fake_table.put_item(Item=_marker("w9"))

    result = hevy_common.resolve_tombstones()

    assert result == {"markers_seen": 1, "resolved": 1, "records_removed": 1, "failures": 0}
    assert (HEVY_PK, "DATE#2026-06-20#WORKOUT#w9") not in fake_table.items
    assert (HEVY_PK, "DATE#2026-06-20#WORKOUT#w8") in fake_table.items  # untouched
    marker = fake_table.items[(HEVY_PK, "DELETE#WORKOUT#w9")]
    assert marker["resolved_at"]
    assert marker["resolved_sks"] == ["DATE#2026-06-20#WORKOUT#w9"]


def test_resolve_tombstones_is_idempotent(hevy_common, fake_table):
    fake_table.put_item(Item=_workout_item("w9", "2026-06-20"))
    fake_table.put_item(Item=_marker("w9"))
    hevy_common.resolve_tombstones()
    deletes_after_first = list(fake_table.deletes)

    second = hevy_common.resolve_tombstones()
    assert second["resolved"] == 0
    assert fake_table.deletes == deletes_after_first  # nothing new deleted


def test_resolve_tombstones_marker_without_record(hevy_common, fake_table):
    """A delete for a never-ingested (or already-removed) workout resolves cleanly."""
    fake_table.put_item(Item=_marker("ghost"))
    result = hevy_common.resolve_tombstones()
    assert result["resolved"] == 1
    assert result["records_removed"] == 0
    assert fake_table.items[(HEVY_PK, "DELETE#WORKOUT#ghost")]["resolved_sks"] == []


def test_resolve_tombstones_handles_multi_date_duplicates(hevy_common, fake_table):
    """A workout duplicated across dates (pre-fix cross-date edit) is fully removed."""
    fake_table.put_item(Item=_workout_item("w9", "2026-06-20"))
    fake_table.put_item(Item=_workout_item("w9", "2026-06-21"))
    fake_table.put_item(Item=_marker("w9"))
    result = hevy_common.resolve_tombstones()
    assert result["records_removed"] == 2
    assert not any("#WORKOUT#w9" in sk for (_, sk) in fake_table.items if sk.startswith("DATE#"))


def test_resolve_tombstones_never_raises(hevy_common, monkeypatch):
    class ExplodingTable:
        def query(self, **kw):
            raise RuntimeError("ddb down")

    monkeypatch.setattr(hevy_common, "_table", ExplodingTable())
    result = hevy_common.resolve_tombstones()
    assert result["failures"] == 1


def test_markers_structurally_excluded_from_date_reads(monkeypatch):
    """Read paths query begins_with('DATE#') / between('DATE#a','DATE#b~') or an
    unbounded gte('DATE#…') guarded by source_workout_id. Markers must (a) not
    match the DATE# prefix, (b) sort AFTER every possible DATE# key, and (c) not
    carry source_workout_id."""
    marker_sk = "DELETE#WORKOUT#abc"
    assert not marker_sk.startswith("DATE#")
    assert marker_sk > "DATE#9999-12-31#WORKOUT#￿"  # lexical: 'DE' > 'DA'

    import hevy_backfill_lambda as mod

    tbl = FakeTable()
    monkeypatch.setattr(mod, "_table", tbl)
    mod._tombstone_deleted("abc")
    marker = tbl.items[(HEVY_PK, "DELETE#WORKOUT#abc")]
    assert "source_workout_id" not in marker  # exercise_history's gte-scan guard


# ── 4 · Cursor behavior + handler wiring ─────────────────────────────────────


@pytest.fixture
def backfill(monkeypatch):
    import hevy_backfill_lambda as mod

    tbl = FakeTable()
    calls = {"save_since": [], "written": [], "tombstones_runs": 0}

    monkeypatch.setattr(mod, "_table", tbl)
    monkeypatch.setattr(mod, "_INGEST_HEALTH_AVAILABLE", False)
    monkeypatch.setattr(mod, "load_since", lambda: "2026-07-01T00:00:00Z")
    monkeypatch.setattr(mod, "save_since", lambda ts: calls["save_since"].append(ts))
    monkeypatch.setattr(mod, "archive_raw", lambda wid, raw: f"s3://x/raw/hevy/{wid}.json")
    monkeypatch.setattr(mod, "write_normalized", lambda rec: calls["written"].append(rec["sk"]))
    monkeypatch.setattr(mod, "_derive_training_notes", lambda rec: None)
    monkeypatch.setattr(mod, "_attach_adherence", lambda rec, raw: None)

    def fake_resolve():
        calls["tombstones_runs"] += 1
        return {"markers_seen": 0, "resolved": 0, "records_removed": 0, "failures": 0}

    monkeypatch.setattr(mod, "resolve_tombstones", fake_resolve)
    return mod, tbl, calls


def _updated_event(wid: str, start: str = "2026-07-02T16:00:00Z") -> dict:
    return {"type": "updated", "workout": {"id": wid, "start_time": start, "exercises": []}}


def test_truncated_walk_does_not_advance_cursor(backfill, monkeypatch):
    mod, _, calls = backfill
    monkeypatch.setattr(mod, "MAX_PAGES_PER_RUN", 2)

    def pages(since, page=1, page_size=10):
        return {"page": page, "page_count": 5, "events": [_updated_event(f"w{page}")]}

    monkeypatch.setattr(mod, "fetch_events_page", pages)
    resp = mod.lambda_handler({}, None)
    body = json.loads(resp["body"])

    assert calls["save_since"] == []  # the C-7 leg-3 fix: cursor frozen
    assert body["truncated"] is True
    assert body["new_since"] == "2026-07-01T00:00:00Z"
    assert body["pages_walked"] == 2
    assert body["errors"] == 0


def test_complete_walk_advances_cursor(backfill, monkeypatch):
    mod, _, calls = backfill
    monkeypatch.setattr(
        mod, "fetch_events_page", lambda since, page=1, page_size=10: {"page": page, "page_count": 1, "events": [_updated_event("w1")]}
    )
    resp = mod.lambda_handler({}, None)
    body = json.loads(resp["body"])
    assert len(calls["save_since"]) == 1
    assert body["truncated"] is False
    assert body["new_since"] == calls["save_since"][0]


def test_walk_exactly_at_cap_is_not_truncated(backfill, monkeypatch):
    """page_count == MAX_PAGES: the full feed fits — the cursor must advance."""
    mod, _, calls = backfill
    monkeypatch.setattr(mod, "MAX_PAGES_PER_RUN", 2)
    monkeypatch.setattr(
        mod,
        "fetch_events_page",
        lambda since, page=1, page_size=10: {"page": page, "page_count": 2, "events": [_updated_event(f"w{page}")]},
    )
    body = json.loads(mod.lambda_handler({}, None)["body"])
    assert body["truncated"] is False
    assert len(calls["save_since"]) == 1


def test_event_error_blocks_cursor(backfill, monkeypatch):
    mod, _, calls = backfill

    def boom(rec):
        raise RuntimeError("write failed")

    monkeypatch.setattr(mod, "write_normalized", boom)
    monkeypatch.setattr(
        mod, "fetch_events_page", lambda since, page=1, page_size=10: {"page": page, "page_count": 1, "events": [_updated_event("w1")]}
    )
    body = json.loads(mod.lambda_handler({}, None)["body"])
    assert body["errors"] == 1
    assert calls["save_since"] == []


def test_deleted_event_with_event_level_id(backfill, monkeypatch):
    """Hevy delete events may carry {type, id} with no workout object."""
    mod, tbl, calls = backfill
    monkeypatch.setattr(
        mod,
        "fetch_events_page",
        lambda since, page=1, page_size=10: {"page": page, "page_count": 1, "events": [{"type": "deleted", "id": "w_gone"}]},
    )
    body = json.loads(mod.lambda_handler({}, None)["body"])
    assert body["deleted"] == 1
    assert (HEVY_PK, "DELETE#WORKOUT#w_gone") in tbl.items
    assert calls["tombstones_runs"] == 1  # the consumer ran this poll


def test_deleted_event_with_workout_object(backfill, monkeypatch):
    mod, tbl, _ = backfill
    monkeypatch.setattr(
        mod,
        "fetch_events_page",
        lambda since, page=1, page_size=10: {"page": page, "page_count": 1, "events": [{"type": "deleted", "workout": {"id": "w_obj"}}]},
    )
    body = json.loads(mod.lambda_handler({}, None)["body"])
    assert body["deleted"] == 1
    assert (HEVY_PK, "DELETE#WORKOUT#w_obj") in tbl.items


def test_failed_tombstone_write_blocks_cursor(backfill, monkeypatch):
    """A lost delete marker would be a permanent ghost record — the write must
    count as an event error so the window is retried."""
    mod, tbl, calls = backfill
    tbl.fail_put_skts.add("DELETE#WORKOUT#w_gone")
    monkeypatch.setattr(
        mod,
        "fetch_events_page",
        lambda since, page=1, page_size=10: {"page": page, "page_count": 1, "events": [{"type": "deleted", "id": "w_gone"}]},
    )
    body = json.loads(mod.lambda_handler({}, None)["body"])
    assert body["errors"] == 1
    assert body["deleted"] == 0
    assert calls["save_since"] == []


def test_tombstones_consumed_every_run_even_when_feed_empty(backfill, monkeypatch):
    """The consumer is the backlog healer — it must run on quiet polls too."""
    mod, _, calls = backfill
    monkeypatch.setattr(mod, "fetch_events_page", lambda since, page=1, page_size=10: {"page": page, "page_count": 0, "events": []})
    mod.lambda_handler({}, None)
    assert calls["tombstones_runs"] == 1


# ── Migration script ─────────────────────────────────────────────────────────


@pytest.fixture
def migration():
    path = os.path.join(ROOT, "scripts", "migrate_hevy_local_date_keys.py")
    spec = importlib.util.spec_from_file_location("migrate_hevy_local_date_keys", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_plan_finds_only_evening_records(migration):
    items = [
        _workout_item("w_eve", "2026-07-02", start_time="2026-07-02T03:30:00Z"),  # 20:30 PDT 07-01 → move
        _workout_item("w_am", "2026-07-02", start_time="2026-07-02T16:00:00Z"),  # 09:00 PDT same day → keep
        _workout_item("w_nostart", "2026-07-02", start_time=""),  # unparseable → skip
    ]
    moves, skipped = migration.plan_moves(items)
    assert [m["workout_id"] for m in moves] == ["w_eve"]
    assert moves[0]["new_sk"] == "DATE#2026-07-01#WORKOUT#w_eve"
    assert len(skipped) == 1 and "w_nostart" in skipped[0]


def test_migration_apply_rekeys_and_is_idempotent(migration):
    tbl = FakeTable([_workout_item("w_eve", "2026-07-02", start_time="2026-07-02T03:30:00Z")])
    moves, _ = migration.plan_moves(migration.scan_workout_records(tbl))
    result = migration.apply_moves(tbl, moves)

    assert result == {"migrated": 1, "collisions": 0}
    assert (HEVY_PK, "DATE#2026-07-02#WORKOUT#w_eve") not in tbl.items
    new = tbl.items[(HEVY_PK, "DATE#2026-07-01#WORKOUT#w_eve")]
    assert new["date"] == "2026-07-01"
    assert new["migrated_from_sk"] == "DATE#2026-07-02#WORKOUT#w_eve"
    assert new["schema_version"] == 2

    # Idempotency: a second pass finds nothing to move.
    moves2, _ = migration.plan_moves(migration.scan_workout_records(tbl))
    assert moves2 == []


def test_migration_collision_keeps_target_deletes_utc_copy(migration):
    """Both keyings present (post-deploy re-ingest raced the migration): keep the
    correctly-keyed record untouched, drop the UTC copy."""
    target = _workout_item("w_eve", "2026-07-01", start_time="2026-07-02T03:30:00Z", marker="fresh")
    utc_copy = _workout_item("w_eve", "2026-07-02", start_time="2026-07-02T03:30:00Z")
    tbl = FakeTable([target, utc_copy])
    moves, _ = migration.plan_moves(migration.scan_workout_records(tbl))
    assert len(moves) == 1  # only the UTC copy mismatches

    result = migration.apply_moves(tbl, moves)
    assert result["collisions"] == 1
    assert (HEVY_PK, "DATE#2026-07-02#WORKOUT#w_eve") not in tbl.items
    kept = tbl.items[(HEVY_PK, "DATE#2026-07-01#WORKOUT#w_eve")]
    assert kept.get("marker") == "fresh"  # target not overwritten
    assert "migrated_from_sk" not in kept


def test_migration_dry_run_default_makes_no_writes(migration, monkeypatch, capsys):
    import boto3

    tbl = FakeTable([_workout_item("w_eve", "2026-07-02", start_time="2026-07-02T03:30:00Z")])

    class FakeResource:
        def Table(self, name):
            return tbl

    monkeypatch.setattr(boto3, "resource", lambda *a, **kw: FakeResource())

    rc = migration.main([])
    assert rc == 0
    assert tbl.deletes == [] and tbl.puts == []  # dry-run: zero mutations
    assert "Dry-run only" in capsys.readouterr().out

    rc = migration.main(["--apply"])
    assert rc == 0
    assert (HEVY_PK, "DATE#2026-07-01#WORKOUT#w_eve") in tbl.items
    assert (HEVY_PK, "DATE#2026-07-02#WORKOUT#w_eve") not in tbl.items
