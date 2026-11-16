"""tests/test_challenge_checkin_isolation_6087.py — a public check-in can never modify or replace the
owner's challenge record (#6087, owner ruling 2026-11-16).

Before #6087 `POST /api/challenge_checkin` read Matthew's own challenge row, dropped the entry for the
request's date and wrote the list back unconditionally: an anonymous caller could replace his check-in
for any day of any active challenge, and concurrent posts lost entries. The contract now:

  A. The switch. `site_api_social_challenges.PUBLIC_CHECKIN_LIVE` ships False; while it is off the door
     answers 403 for every payload and writes NOTHING (no item, no rate bucket).
  B. Switch on, the reader door writes ONLY its own partition (`CHALLENGE_CHECKINS#<id>`), one item per
     reader x challenge x day under a conditional put. Every old payload shape (reader-chosen id, past /
     future date, same-date replace, a note), a replay, duplicates and N concurrent requests leave the
     owner row byte-identical; no lost update is possible because nothing reads-then-writes a list.
  C. The public read derives progress from the owner's entries only; never a reader's tap.
  D. IAM: the Site API role's write scope no longer covers the owner's challenges partition.
  E. The owner's path (`log_challenge_checkin`, MCP): a same-date replace under a version condition,
     so a concurrent write is retried on a fresh read and never lost.

The class guard over every public write door is tests/test_public_owner_write_class_6087.py.
"""

from __future__ import annotations

import copy
import json
import os
import sys
import threading
from datetime import datetime, timezone
from fnmatch import fnmatch

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _k, _v in (
    ("TABLE_NAME", "life-platform"),
    ("AWS_REGION", "us-west-2"),
    ("AWS_DEFAULT_REGION", "us-west-2"),
    ("S3_BUCKET", "matthew-life-platform"),
    ("USER_ID", "matthew"),
):
    os.environ.setdefault(_k, _v)
for _p in (_REPO, os.path.join(_REPO, "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common import challenge_checkins as cc  # noqa: E402
from web import site_api_social as social, site_api_social_challenges as chal  # noqa: E402

import mcp.tools_challenges as tch  # noqa: E402

OWNER_PK = "USER#matthew#SOURCE#challenges"
CID = "cold-shower-finish_2026-05-04"
OWNER_SK = f"CHALLENGE#{CID}"
TODAY = "2026-05-10"
NOW = datetime(2026, 5, 10, 17, 40, 0, tzinfo=timezone.utc)  # 10:40 Pacific, same calendar day


class _Frozen(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


class ConditionalCheckFailedException(Exception):
    pass


class Table:
    """A thread-safe in-memory table with real `attribute_not_exists(pk)` and `checkin_rev` conditions.

    Records every write so a test can assert which partitions were touched at all."""

    def __init__(self, items=()):
        self.store = {(i["pk"], i["sk"]): copy.deepcopy(i) for i in items}
        self.writes: list = []
        self.lock = threading.Lock()
        self.before_update = None  # hook: runs between a reader's get and its update (the race window)

    def get_item(self, Key, **_kw):
        with self.lock:
            item = self.store.get((Key["pk"], Key["sk"]))
            return {"Item": copy.deepcopy(item)} if item is not None else {}

    def put_item(self, Item, ConditionExpression=None, **_kw):
        with self.lock:
            key = (Item["pk"], Item["sk"])
            self.writes.append(("put", key))
            if ConditionExpression == "attribute_not_exists(pk)" and key in self.store:
                raise ConditionalCheckFailedException("ConditionalCheckFailedException")
            assert ConditionExpression in (None, "attribute_not_exists(pk)"), ConditionExpression
            self.store[key] = copy.deepcopy(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, ConditionExpression=None, **_kw):
        if self.before_update:
            hook, self.before_update = self.before_update, None
            hook()
        with self.lock:
            key = (Key["pk"], Key["sk"])
            self.writes.append(("update", key))
            item = self.store.get(key)
            # The two shapes this module has ever written: the pre-#6087 unconditional list write, and the
            # owner tool's version-conditioned one. Anything else is a test-double gap, so it fails loudly.
            assert UpdateExpression in ("SET daily_checkins = :cl", "SET daily_checkins = :cl, checkin_rev = :next"), UpdateExpression
            if ConditionExpression is not None:
                assert ConditionExpression == "attribute_exists(pk) AND (attribute_not_exists(checkin_rev) OR checkin_rev = :rev)"
                if item is None or ("checkin_rev" in item and item["checkin_rev"] != ExpressionAttributeValues[":rev"]):
                    raise ConditionalCheckFailedException("ConditionalCheckFailedException")
            item = self.store.setdefault(key, {"pk": key[0], "sk": key[1]})
            item["daily_checkins"] = copy.deepcopy(ExpressionAttributeValues[":cl"])
            if ":next" in ExpressionAttributeValues:
                item["checkin_rev"] = ExpressionAttributeValues[":next"]

    def rows(self, prefix):
        return {k: v for k, v in self.store.items() if k[0].startswith(prefix)}


def _owner_row(checkins=None, status="active"):
    return {
        "pk": OWNER_PK,
        "sk": OWNER_SK,
        "name": "Cold shower finish",
        "status": status,
        "duration_days": 7,
        "daily_checkins": checkins if checkins is not None else [{"date": TODAY, "completed": True, "source": cc.OWNER_SOURCE}],
    }


def _post(body, ip="203.0.113.7"):
    return {"body": json.dumps(body) if not isinstance(body, str) else body, "headers": {"cloudfront-viewer-address": f"{ip}:1234"}}


@pytest.fixture
def door(monkeypatch):
    """Wire the facade over a fresh table; returns (table, rate_calls). The switch is left as shipped."""
    table = Table([_owner_row()])
    rate_calls: list = []

    def _rate(endpoint, ip_hash, limit, window_seconds, fail_open=True):
        rate_calls.append((endpoint, ip_hash))
        return True, limit, 0

    monkeypatch.setattr(social, "table", table)
    monkeypatch.setattr(social, "_rate_check", _rate)
    monkeypatch.setattr(social, "salted_ip_hash", lambda ip, _logger: f"h{abs(hash(ip)) % 10**8}" if ip else None)
    monkeypatch.setattr(social, "datetime", _Frozen)
    return table, rate_calls


def _open(monkeypatch):
    monkeypatch.setattr(chal, "PUBLIC_CHECKIN_LIVE", True)


# The old payload shapes — what the pre-#6087 door accepted and wrote into the owner row.
OLD_SHAPES = [
    {"challenge_id": CID, "completed": False},  # reader-chosen id, today
    {"challenge_id": CID, "completed": False, "date": TODAY},  # same-date replace of the owner's entry
    {"challenge_id": CID, "completed": False, "date": "2026-05-01"},  # a past day
    {"challenge_id": CID, "completed": False, "date": "2026-06-01"},  # a future day
    {"challenge_id": CID, "completed": True, "note": "<b>reader text</b>"},  # a note
    {"challenge_id": f"CHALLENGE#{CID}", "completed": False},  # a key-shaped id
    {"challenge_id": "../" + CID, "completed": False},
    "not-an-object",
]


# ── A. the switch ─────────────────────────────────────────────────────────────


def test_the_reader_door_ships_shut():
    """The committed switch. Flipping it is the owner's later one-line PR, not this one."""
    assert chal.PUBLIC_CHECKIN_LIVE is False
    assert chal.reader_checkins_open() is False


def test_while_shut_every_payload_is_refused_and_nothing_is_written(door):
    table, rate_calls = door
    before = copy.deepcopy(table.store)
    offenders = [b for b in OLD_SHAPES if social._handle_challenge_checkin(_post(b))["statusCode"] != 403]
    assert offenders == [], f"a shut door answered something other than 403 for {offenders}"
    assert table.writes == [] and rate_calls == [], "a shut door must write nothing — not even a rate bucket"
    assert table.store == before


def test_the_public_payload_says_the_door_is_shut(door, monkeypatch):
    monkeypatch.setattr(social, "_challenges_cache", {"challenges": []})
    monkeypatch.setattr(social, "_challenges_cache_at", None)
    monkeypatch.setattr(social, "with_phase_filter", lambda kw: kw)
    table, _ = door
    table.query = lambda **_kw: {"Items": [copy.deepcopy(table.store[(OWNER_PK, OWNER_SK)])]}
    assert json.loads(social.handle_challenges()["body"])["reader_checkins_open"] is False
    _open(monkeypatch)
    assert json.loads(social.handle_challenges()["body"])["reader_checkins_open"] is True


# ── B. switch on: the owner row is never touched ─────────────────────────────


def test_open_no_old_payload_shape_modifies_the_owner_row(door, monkeypatch):
    _open(monkeypatch)
    table, _ = door
    owner_before = copy.deepcopy(table.store[(OWNER_PK, OWNER_SK)])
    for body in OLD_SHAPES:
        social._handle_challenge_checkin(_post(body))
        assert table.store[(OWNER_PK, OWNER_SK)] == owner_before, f"the owner row changed under {body!r}"
    assert all(not k[0].startswith("USER#") for _op, k in table.writes), table.writes


def test_open_a_check_in_lands_in_the_reader_partition_without_a_note(door, monkeypatch):
    _open(monkeypatch)
    table, _ = door
    resp = social._handle_challenge_checkin(_post({"challenge_id": CID, "completed": True, "note": "felt strong"}))
    assert resp["statusCode"] == 200
    rows = table.rows(cc.READER_CHECKIN_PK_PREFIX)
    assert len(rows) == 1
    (pk, sk), item = next(iter(rows.items()))
    assert pk == f"CHALLENGE_CHECKINS#{CID}" and sk.startswith("READER#") and sk.endswith(f"#DATE#{TODAY}")
    assert "note" not in item and item["completed"] is True and item["ttl"] > 0


def test_open_past_and_future_dates_are_refused(door, monkeypatch):
    _open(monkeypatch)
    table, _ = door
    for day in ("2026-05-09", "2026-05-11", "2025-01-01", "not-a-date"):
        assert social._handle_challenge_checkin(_post({"challenge_id": CID, "completed": True, "date": day}))["statusCode"] == 400
    assert table.writes == []


def test_open_an_inactive_or_unknown_challenge_is_refused_without_a_write(door, monkeypatch):
    _open(monkeypatch)
    table, _ = door
    table.store[(OWNER_PK, "CHALLENGE#done")] = {**_owner_row(status="completed"), "sk": "CHALLENGE#done"}
    assert social._handle_challenge_checkin(_post({"challenge_id": "done", "completed": True}))["statusCode"] == 400
    assert social._handle_challenge_checkin(_post({"challenge_id": "ghost", "completed": True}))["statusCode"] == 404
    assert table.writes == []


def test_open_a_replay_is_a_no_op_and_the_first_answer_stands(door, monkeypatch):
    _open(monkeypatch)
    table, _ = door
    first = json.loads(social._handle_challenge_checkin(_post({"challenge_id": CID, "completed": True}))["body"])
    second = json.loads(social._handle_challenge_checkin(_post({"challenge_id": CID, "completed": True}))["body"])
    flipped = json.loads(social._handle_challenge_checkin(_post({"challenge_id": CID, "completed": False}))["body"])
    assert first["duplicate"] is False and second["duplicate"] is True and flipped["duplicate"] is True
    rows = table.rows(cc.READER_CHECKIN_PK_PREFIX)
    assert len(rows) == 1 and next(iter(rows.values()))["completed"] is True


def test_open_n_concurrent_duplicates_write_one_item_and_never_the_owner_row(door, monkeypatch):
    _open(monkeypatch)
    table, _ = door
    owner_before = copy.deepcopy(table.store[(OWNER_PK, OWNER_SK)])
    statuses: list = []
    barrier = threading.Barrier(16)

    def _one():
        barrier.wait()
        statuses.append(social._handle_challenge_checkin(_post({"challenge_id": CID, "completed": False}))["statusCode"])

    threads = [threading.Thread(target=_one) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert statuses == [200] * 16
    assert len(table.rows(cc.READER_CHECKIN_PK_PREFIX)) == 1
    assert table.store[(OWNER_PK, OWNER_SK)] == owner_before


def test_open_n_concurrent_distinct_readers_lose_no_check_in(door, monkeypatch):
    """No lost update: each reader is its own item, so there is no list to race on."""
    _open(monkeypatch)
    table, _ = door
    owner_before = copy.deepcopy(table.store[(OWNER_PK, OWNER_SK)])
    barrier = threading.Barrier(24)

    def _one(i):
        barrier.wait()
        social._handle_challenge_checkin(_post({"challenge_id": CID, "completed": bool(i % 2)}, ip=f"198.51.100.{i}"))

    threads = [threading.Thread(target=_one, args=(i,)) for i in range(24)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(table.rows(cc.READER_CHECKIN_PK_PREFIX)) == 24
    assert table.store[(OWNER_PK, OWNER_SK)] == owner_before


# ── C. the public read: owner entries only ────────────────────────────────────


def test_progress_derives_from_owner_entries_only(door, monkeypatch):
    _open(monkeypatch)
    table, _ = door
    table.store[(OWNER_PK, OWNER_SK)]["daily_checkins"] = [
        {"date": "2026-05-08", "completed": True, "source": cc.OWNER_SOURCE},
        {"date": "2026-05-09", "completed": False, "source": cc.PUBLIC_DOOR_SOURCE, "note": "a stranger's text"},
    ]
    for i in range(5):  # reader taps in their own partition must not move his figures either
        social._handle_challenge_checkin(_post({"challenge_id": CID, "completed": False}, ip=f"192.0.2.{i}"))
    monkeypatch.setattr(social, "_challenges_cache", {"challenges": []})
    monkeypatch.setattr(social, "_challenges_cache_at", None)
    monkeypatch.setattr(social, "with_phase_filter", lambda kw: kw)
    table.query = lambda **_kw: {"Items": [copy.deepcopy(table.store[(OWNER_PK, OWNER_SK)])]}
    body = json.loads(social.handle_challenges()["body"])
    live = next(c for c in body["challenges"] if c.get("origin") == "live")
    assert live["progress"]["checkin_days"] == 1 and live["progress"]["completed_days"] == 1
    assert "a stranger's text" not in json.dumps(body)


def test_achievement_rules_count_owner_entries_only():
    from health import achievement_rules as ar

    stranger = {"date": "2026-05-09", "completed": False, "source": cc.PUBLIC_DOOR_SOURCE}
    row = {"status": "completed", "daily_checkins": [{"date": "2026-05-08", "completed": True}, stranger]}
    assert ar._completed_challenge_stats([row]) == (1, 1)


# ── D. IAM ────────────────────────────────────────────────────────────────────


def test_the_site_api_role_cannot_write_the_owner_challenges_partition():
    sys.path.insert(0, os.path.join(_REPO, "tests"))
    from test_site_api_write_scope import _site_api_leadingkeys

    patterns = _site_api_leadingkeys()
    assert not any(fnmatch(OWNER_PK, p) for p in patterns), sorted(patterns)
    assert any(fnmatch(cc.reader_checkin_key(CID, "h1", TODAY)["pk"], p) for p in patterns), sorted(patterns)


# ── E. the owner's path (MCP) ─────────────────────────────────────────────────


@pytest.fixture
def owner(monkeypatch):
    table = Table([_owner_row(checkins=[])])
    monkeypatch.setattr(tch, "_table_ref", table)
    monkeypatch.setattr(tch, "pacific_today", lambda: TODAY)
    return table


def test_the_owner_tool_writes_his_row_and_replaces_the_same_day(owner):
    assert tch.tool_log_challenge_checkin({"challenge_id": CID, "completed": False})["stored"] is True
    out = tch.tool_log_challenge_checkin({"challenge_id": CID, "completed": True})
    entries = owner.store[(OWNER_PK, OWNER_SK)]["daily_checkins"]
    assert out["checkin_days"] == 1 and len(entries) == 1
    assert entries[0]["completed"] is True and entries[0]["source"] == cc.OWNER_SOURCE


def test_the_owner_tool_loses_no_update_under_a_concurrent_write(owner):
    """A second write lands between the tool's read and its write: the version condition fails, the tool
    re-reads and retries, and BOTH days survive."""

    def _concurrent():
        owner.before_update = None
        with owner.lock:
            row = owner.store[(OWNER_PK, OWNER_SK)]
            row["daily_checkins"] = [{"date": "2026-05-09", "completed": True, "source": cc.OWNER_SOURCE}]
            row["checkin_rev"] = int(row.get("checkin_rev") or 0) + 1

    owner.before_update = _concurrent
    out = tch.tool_log_challenge_checkin({"challenge_id": CID, "completed": True})
    assert out["stored"] is True
    assert {c["date"] for c in owner.store[(OWNER_PK, OWNER_SK)]["daily_checkins"]} == {"2026-05-09", TODAY}


def test_the_owner_tool_refuses_bad_input_without_a_write(owner):
    bad = [
        {"challenge_id": CID, "completed": True, "date": "2026-05-11"},  # future
        {"challenge_id": CID, "completed": "yes"},
        {"challenge_id": "Bad Id", "completed": True},
        {"challenge_id": "ghost", "completed": True},
    ]
    accepted = [a for a in bad if "error" not in tch.tool_log_challenge_checkin(a)]
    assert accepted == [] and owner.writes == []


def test_the_owner_tool_refuses_an_inactive_challenge(owner):
    owner.store[(OWNER_PK, OWNER_SK)]["status"] = "candidate"
    assert "error" in tch.tool_log_challenge_checkin({"challenge_id": CID, "completed": True})
    assert owner.writes == []


def test_the_owner_tool_is_registered_as_a_write_with_replay_semantics():
    from mcp import audit, idempotency
    from mcp.registry import TOOLS

    assert TOOLS["log_challenge_checkin"]["fn"] is tch.tool_log_challenge_checkin
    assert audit.is_write_tool("log_challenge_checkin")
    assert idempotency.REPLAY_SEMANTICS["log_challenge_checkin"][0] == idempotency.DETERMINISTIC_KEY
