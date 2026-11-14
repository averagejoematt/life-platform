#!/usr/bin/env python3
"""tests/test_status_board_registry_5930.py — #5930 (and #5527 part b): the public status board
reads each feed to the END before it says "never", and its rows derive from the source registry.

The live defect (2026-11-13 /review full, integrations-1/2/4): `_last_sync` made ONE query with a
FilterExpression and no LastEvaluatedKey loop, so page 1 came back empty (Count 0 / ScannedCount 51,
the 1 MB ceiling) while the record sat on a later page — and /api/status printed CGM, Breathwork and
Mindful Minutes red "never" for feeds with history. Every exception also rendered "never". The
board's rows were a hand list: the frozen `macrofactor_workouts` archive said "Check auth/webhook",
the live `hevy` source had no row, the seven apple_health sub-feeds all published id `apple_health`,
and two rows tracked `mindful_minutes`.

Every fake here is a PAGING fake: it cuts pages the way DynamoDB does (page size first, filter
after, LastEvaluatedKey while anything remains), so a single-page reader fails these tests the way
it failed live. Time is frozen (no wall clock — #4848).
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "lambdas", ROOT / "lambdas" / "web"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

from ingestion import source_registry as reg  # noqa: E402
from operational import week_agreement_qa as wq  # noqa: E402
from web import site_api_status as sas  # noqa: E402
from web.site_api_common import USER_PREFIX  # noqa: E402

FROZEN_NOW = datetime(2026, 11, 14, 19, 0, 0, tzinfo=timezone.utc)
PAGE = 5  # items per page — small so "longer than one page" is cheap to build


def _day(n: int) -> str:
    return (FROZEN_NOW.date() - timedelta(days=n)).isoformat()


def _flatten(cond):
    expr = cond.get_expression()
    if expr["operator"] == "AND":
        return [c for v in expr["values"] for c in _flatten(v)]
    return [(expr["values"][0].name, expr["operator"], tuple(expr["values"][1:]))]


class PagingTable:
    """DynamoDB's paging, faithfully enough to catch a one-page reader: the page is cut by
    `min(Limit, PAGE)` BEFORE the FilterExpression runs, and LastEvaluatedKey is returned while
    any key-matching item remains after the page."""

    def __init__(self, items, page=PAGE):
        self.items = list(items)
        self.page = page
        self.queries: list = []
        self.fail_on_call = None  # 1-based index of the query that raises
        self.endless = False  # always hand back a LastEvaluatedKey (a partition that never ends)

    def query(self, **kw):
        self.queries.append(kw)
        if self.fail_on_call is not None and len(self.queries) == self.fail_on_call:
            raise RuntimeError("ProvisionedThroughputExceededException")
        conds = _flatten(kw["KeyConditionExpression"])
        pk = next(a[0] for n, op, a in conds if n == "pk")
        rows = [i for i in self.items if i["pk"] == pk]
        for n, op, a in conds:
            if n != "sk":
                continue
            if op == "begins_with":
                rows = [r for r in rows if r["sk"].startswith(a[0])]
            elif op == "BETWEEN":
                rows = [r for r in rows if a[0] <= r["sk"] <= a[1]]
            else:  # pragma: no cover
                raise AssertionError(op)
        rows.sort(key=lambda r: r["sk"], reverse=not kw.get("ScanIndexForward", True))
        start = kw.get("ExclusiveStartKey")
        if start:
            idx = next((i for i, r in enumerate(rows) if r["sk"] == start["sk"]), None)
            rows = [] if idx is None else rows[idx + 1 :]
        size = min(kw.get("Limit") or self.page, self.page)
        page, rest = rows[:size], rows[size:]
        filt = kw.get("FilterExpression")
        if filt is not None:
            for n, op, _a in _flatten(filt):
                assert op == "attribute_exists"
                page = [r for r in page if n in r]
        out = {"Items": page}
        if (rest or self.endless) and rows[:size]:
            out["LastEvaluatedKey"] = {"pk": pk, "sk": rows[:size][-1]["sk"]}
        elif self.endless:
            out["LastEvaluatedKey"] = {"pk": pk, "sk": "DATE#0000"}
        return out


def _row(source, day, **fields):
    return {"pk": f"{USER_PREFIX}{source}", "sk": f"DATE#{day}", **fields}


class _Frozen(datetime):
    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW.astimezone(tz) if tz is not None else FROZEN_NOW.replace(tzinfo=None)


class _Clock:
    t = 2_000_000.0

    def time(self):
        return self.t


class _NoAws:
    def client(self, *a, **k):
        raise RuntimeError("no AWS in tests")


@pytest.fixture(autouse=True)
def _frozen(monkeypatch):
    monkeypatch.setattr(sas, "datetime", _Frozen)
    clock = _Clock()
    monkeypatch.setattr(sas, "time", clock)
    monkeypatch.setattr(sas, "boto3", _NoAws())
    sas._status_cache = {}
    sas._status_cache_ts = 0
    sas._exhausted_memo.clear()
    yield clock
    sas._status_cache = {}
    sas._status_cache_ts = 0
    sas._exhausted_memo.clear()


def _payload(table):
    resp = sas.status(_g={"table": table, "_budget_cost_block": lambda: {}})
    return json.loads(resp["body"])


def _ds(body):
    return next(g for g in body["groups"] if g["id"] == "data_sources")["components"]


def _by_name(body, name):
    hits = [c for c in _ds(body) if c["name"] == name]
    assert len(hits) == 1, f"{len(hits)} components named {name!r}"
    return hits[0]


def _board_name(sid, field_check=None):
    for r in sas._board_rows():
        if r[0] == sid and (r[9] if len(r) > 9 else None) == field_check:
            return r[1]
    raise AssertionError(f"no board row for {sid}/{field_check}")


# ── box 1: page to the end; "never" only after the end; a failed read is "unreadable" ──────────────


def test_the_record_on_a_later_page_is_found_when_page_one_is_empty():
    """The live shape: the newest rows do not carry the field, the record is pages down."""
    items = [_row("apple_health", _day(n), steps=Decimal(1)) for n in range(0, 3 * PAGE)]
    items.append(_row("apple_health", _day(3 * PAGE + 2), blood_glucose_avg=Decimal(101)))
    table = PagingTable(items)
    assert sas._last_sync(table, "apple_health", "blood_glucose_avg") == _day(3 * PAGE + 2)
    assert len(table.queries) == 4, "the reader must page past three empty pages to the fourth"
    first = table.queries[0]
    assert table.query(**first)["Items"] == [], "fixture premise: page one really is empty"


def test_never_is_returned_only_after_the_partition_is_exhausted():
    items = [_row("apple_health", _day(n), steps=Decimal(1)) for n in range(0, 2 * PAGE + 3)]
    table = PagingTable(items)
    assert sas._last_sync(table, "apple_health", "breathwork_minutes") is None
    last = table.queries[-1]
    assert "LastEvaluatedKey" not in table.query(**last), "None was returned before the last page"


def test_a_read_that_fails_mid_partition_is_unreadable_not_never():
    items = [_row("apple_health", _day(n), steps=Decimal(1)) for n in range(0, 3 * PAGE)]
    table = PagingTable(items)
    table.fail_on_call = 2
    assert sas._last_sync(table, "apple_health", "blood_glucose_avg") == sas.LAST_SYNC_UNREADABLE


def test_a_partition_past_the_page_cap_is_unreadable_not_never():
    table = PagingTable([_row("apple_health", _day(1), steps=Decimal(1))])
    table.endless = True
    assert sas._last_sync(table, "apple_health", "blood_glucose_avg") == sas.LAST_SYNC_UNREADABLE
    assert len(table.queries) == sas._STATUS_MAX_PAGES


def test_the_never_memo_still_sees_a_record_that_arrives_after_it():
    """The exhaustive read is remembered (it is the whole partition) — but a new record still shows."""
    items = [_row("apple_health", _day(n), steps=Decimal(1)) for n in range(0, 2 * PAGE)]
    table = PagingTable(items)
    assert sas._last_sync(table, "apple_health", "breathwork_minutes") is None
    full = len(table.queries)
    table.items.append(_row("apple_health", _day(0), steps=Decimal(1), breathwork_minutes=Decimal(10)))
    assert sas._last_sync(table, "apple_health", "breathwork_minutes") == _day(0)
    assert len(table.queries) - full == 1, "inside the memo TTL the re-read is the bounded recent window"
    # A different table is never served another table's memo.
    other = PagingTable([_row("apple_health", _day(40), breathwork_minutes=Decimal(5))])
    assert sas._last_sync(other, "apple_health", "breathwork_minutes") == _day(40)


def _subfeed_table():
    """apple_health: steps every day for longer than one page; glucose only far down; mindful far
    down; breathwork never; plus the rest of the board flowing so only the sub-feeds are under test."""
    items = [_row("apple_health", _day(n), steps=Decimal(1), water_intake_ml=Decimal(1)) for n in range(0, 4 * PAGE)]
    items.append(_row("apple_health", _day(4 * PAGE + 1), blood_glucose_avg=Decimal(100)))
    items.append(_row("apple_health", _day(4 * PAGE + 3), mindful_minutes=Decimal(10)))
    for r in sas._board_rows():
        if r[0] != "apple_health":
            items += [_row(r[0], _day(n)) for n in range(3)]
    return PagingTable(items)


def test_the_status_payload_reports_the_real_last_date_for_a_feed_silent_longer_than_one_page():
    body = _payload(_subfeed_table())
    cgm = _by_name(body, _board_name("apple_health", "blood_glucose_avg"))
    assert cgm["last_sync_relative"] == f"{4 * PAGE + 1}d ago", cgm
    mindful = _by_name(body, _board_name("apple_health", "mindful_minutes"))
    assert mindful["last_sync_relative"] == f"{4 * PAGE + 3}d ago", mindful
    breath = _by_name(body, _board_name("apple_health", "breathwork_minutes"))
    assert breath["last_sync_relative"] == "never"  # the partition was read to its end


def test_an_unreadable_feed_renders_unreadable_and_never_never():
    table = _subfeed_table()
    real_query = table.query

    def failing(**kw):
        if kw.get("FilterExpression") is not None:
            raise RuntimeError("throttled")
        return real_query(**kw)

    table.query = failing
    body = _payload(table)
    for field in ("blood_glucose_avg", "mindful_minutes", "breathwork_minutes"):
        c = _by_name(body, _board_name("apple_health", field))
        assert c["last_sync_relative"] == "unreadable", c
        assert "never" not in (c["comment"] or "").lower() and "No record has ever arrived" not in (c["comment"] or "")


def test_the_uptime_bars_see_a_record_past_the_first_page_of_the_window():
    body = _payload(_subfeed_table())
    cgm = _by_name(body, _board_name("apple_health", "blood_glucose_avg"))
    assert cgm["uptime_90d"][-1 - (4 * PAGE + 1)] == 1, "the glucose day on page five must draw a green bar"


# ── box 3: board rows derive from the registry ─────────────────────────────────────────────────


def test_every_registry_board_source_has_a_component():
    published = {c["source"] for c in _ds(_payload(_subfeed_table()))}
    owed = sas.board_source_ids()
    assert "hevy" in owed
    assert owed <= published, f"registry board sources with no component: {sorted(owed - published)}"


def test_a_source_the_presentation_table_forgets_still_gets_a_registry_row(monkeypatch):
    """MUST-FAIL control for the derivation: drop hevy from the hand table — it must still appear."""
    monkeypatch.setattr(sas, "_DATA_SOURCES", [r for r in sas._DATA_SOURCES if r[0] != "hevy"])
    rows = {r[0]: r for r in sas._board_rows()}
    assert "hevy" in rows
    assert rows["hevy"][1] == reg.SOURCE_REGISTRY["hevy"]["label"]


def test_the_board_rule_excludes_exactly_what_its_facets_say():
    base = dict(reg.SOURCE_REGISTRY["whoop"])
    planted = {
        "whoop": base,
        "garmin": {**base, "paused": True},  # paused: not owed a row
        "strava": {**base, "partition": False},  # a transport pipe: nothing to age
        "withings": {**base, "social_channel": True},  # an engagement channel, not a health feed
        "notion": base,  # owner-only (activity_publication): never newly public
    }
    assert sas.board_source_ids(planted) == {"whoop"}


def test_private_sources_never_reach_the_board():
    from common import activity_publication as ap

    published = {c["source"] for c in _ds(_payload(_subfeed_table()))}
    assert not [s for s in published if not ap.source_is_public(s)]
    fields = {c["field_check"] for c in _ds(_payload(_subfeed_table())) if c.get("field_check")}
    assert not [f for f in fields if not ap.field_is_public("apple_health", f)]


def test_a_row_that_is_not_a_registry_source_is_a_dispositioned_onetime_or_archive_partition():
    for r in sas._DATA_SOURCES:
        if r[0] in reg.SOURCE_REGISTRY:
            continue
        assert r[0] in reg.UNREGISTERED_PARTITIONS, f"{r[0]}: neither a registry source nor a dispositioned partition"
        assert r[5] in ("onetime", "archive"), f"{r[0]}: a non-source partition rendered as {r[5]!r} would read as a broken feed"


def test_the_frozen_archive_renders_archive_prose_not_check_auth():
    items = [_row("macrofactor_workouts", _day(n)) for n in range(250, 270)]
    table = _subfeed_table()
    table.items = [i for i in table.items if i["pk"] != f"{USER_PREFIX}macrofactor_workouts"] + items
    body = _payload(table)
    c = next(c for c in _ds(body) if c["source"] == "macrofactor_workouts")
    assert c["status"] == "blue" and c["uptime_90d"] == []
    assert "Frozen archive" in c["comment"] and "250d ago" in c["comment"]
    assert "auth" not in c["comment"].lower() and "attention" not in c["comment"].lower()


# ── box 4: unique ids, no two rows on one (source, field_check) ─────────────────────────────────


def _duplicates(components):
    ids, keys, dup = set(), set(), []
    for c in components:
        key = (c["source"], c.get("field_check"))
        if c["id"] in ids:
            dup.append(f"id {c['id']}")
        if key in keys:
            dup.append(f"(source, field_check) {key}")
        ids.add(c["id"])
        keys.add(key)
    return dup


def test_component_ids_are_unique_and_no_two_rows_share_a_source_and_field():
    body = _payload(_subfeed_table())
    assert _duplicates(_ds(body)) == []
    every = [c for g in body["groups"] if g["id"] != "infrastructure" for c in g["components"]]
    assert len({c["id"] for c in every}) == len(every)


def test_the_uniqueness_check_fails_on_the_pre_5930_breathwork_row(monkeypatch):
    """MUST-FAIL control: put Breathwork back on `mindful_minutes` and the payload check must red."""
    rows = [r[:9] + ("mindful_minutes",) if len(r) > 9 and r[9] == "breathwork_minutes" else r for r in sas._DATA_SOURCES]
    monkeypatch.setattr(sas, "_DATA_SOURCES", rows)
    dup = _duplicates(_ds(_payload(_subfeed_table())))
    assert dup and any("mindful_minutes" in d for d in dup), dup


# ── #5527 box 3: week_agreement_qa sees every component ─────────────────────────────────────────


def test_week_agreement_sees_every_apple_health_component_under_its_registry_id():
    body = _payload(_subfeed_table())
    rows = wq._extract_status_components(body)
    published = [c for c in _ds(body) if c["source"] == "apple_health"]
    assert len(published) >= 6
    assert [r["label"] for r in rows["apple_health"]] == [c["name"] for c in published]
    judged = sum(len(v) for v in rows.values())
    every = sum(len(g["components"]) for g in body["groups"])
    assert judged == every, "a component the absence gate cannot see"


def test_an_unreadable_rendering_narrates_no_absence_to_judge():
    rows = wq._extract_status_components(
        {"groups": [{"components": [{"id": "garmin", "source": "garmin", "status": "red", "last_sync_relative": "unreadable"}]}]}
    )
    assert rows["garmin"][0]["narrating_absence"] is False
