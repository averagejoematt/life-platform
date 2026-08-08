#!/usr/bin/env python3
"""tests/test_site_api_status_behavior.py — behavioral contracts of
`lambdas/web/site_api_status.py` (`/api/status` + `/api/status/summary`).

Part of #1658 tranche 2. This module is the platform's public self-report: the
status page renders its four panels, and the single traffic light it computes is
the dot in the site footer. Everything under test here is something a *reader*
sees and is entitled to believe:

  * the freshness -> colour ladder, the lagged-source grace, and the human
    relative-time strings ("today" / "yesterday" / "3d ago" / "current"),
  * the override precedence between a CloudWatch alarm, a failed daily
    health-check probe and ordinary staleness,
  * the 90-day uptime bars (green / red / neutral, and the activity-dependent
    neutralisation),
  * the manual + one-time due-date categories,
  * how per-component statuses roll up into the one traffic light, and that
    `/api/status/summary` cannot disagree with `/api/status`,
  * fail-soft: DynamoDB, CloudWatch, SQS and the cost governor may each be
    unreachable without the endpoint failing,
  * ADR-104 honesty: a component with no data must not be reported healthy on
    the basis of nothing.

Three disciplines this file holds to, each of which has caused an incident here:

  * **Guard the SET, not the instance.** The three component tables
    (`_DATA_SOURCES`, `_COMPUTE_SOURCES`, `_EMAIL_LAMBDAS`) are function-local
    literals that grow. No test hard-codes a source list; the tables are read out
    of the module's own AST and every "which components appear" assertion is a
    property that must hold for *every* row. Where one representative source is
    needed, it is selected by PROPERTY (`pick_data_source(...)`) so the test
    follows the table instead of pinning a name.
  * **No wall clock.** The module calls `datetime.now(timezone.utc)` in five
    places and pins a hard-coded uptime epoch. Time is frozen with a `datetime`
    subclass patched onto the module, and `time.time()` (the response-cache TTL)
    is frozen separately. A fixture date is never combined with the real clock.
  * **Bounded, hand-rolled fakes.** No MagicMock anywhere near a query loop, and
    `boto3` is patched as it is looked up in THIS module, so no test can reach
    AWS.

`_status_cache` / `_status_cache_ts` are MODULE state shared by both handlers.
The autouse `_reset_status_cache` fixture clears it before and after every test —
without it, the first test to run would serve its answer to every later one.

Tests carrying `xfail(strict=False, reason="DEFECT (tranche-2 discovery): ...")`
describe the contract the endpoint OUGHT to hold and currently does not. They are
findings, not fixes. #2220 fixed six of the eleven; #2221 then took the remaining
five and left exactly ONE marked:

  * FIXED — the shared-partition uptime bars (`_uptime_90d` now honours field_check),
    the missed-weekly-run window (the recovery branch is bounded by the sender's own
    cadence, not by red_h), and the unguarded `strptime` (two call sites, not one —
    an unreadable date now reads as unreadable, per ADR-104, instead of 500-ing the
    whole page).
  * FIXED DIFFERENTLY — the unreachable gray idle state. It really was dead code, but
    making it reachable would have masked a missed weekly send as "idle, next: Sun",
    so the state was deleted. `test_a_scheduled_sender_never_reports_the_idle_gray_state`
    is now the ratchet on that, and explains the reasoning in full.
  * STILL MARKED — the inert `yellow_h` column. Confirmed inert, but the repair as
    written contradicts `test_data_from_yesterday_is_still_green` on the same source
    and contradicts the cadence-derived window in `source_registry`. The marker's own
    reason carries the corrected finding.
"""

import ast
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

from web import site_api_status as sas  # noqa: E402
from web.site_api_common import STATUS_CACHE_TTL, USER_PREFIX  # noqa: E402

# ──────────────────────────────────────────────────────────────────────────────
# The module's own component tables, read out of its AST.
#
# They are locals inside `status()`, so they cannot be imported — but they can be
# READ, which is the whole point: every expectation below is derived from the
# same literal the handler iterates. Adding a source to the table extends the
# tests instead of silently escaping them.
# ──────────────────────────────────────────────────────────────────────────────

_SRC = (ROOT / "lambdas" / "web" / "site_api_status.py").read_text()
_TREE = ast.parse(_SRC)


def _module_literal(name):
    for node in ast.walk(_TREE):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return ast.literal_eval(node.value)
    raise AssertionError(f"site_api_status.py no longer defines {name} as a literal — the tests derive from it")


DATA_SOURCES = _module_literal("_DATA_SOURCES")
COMPUTE_SOURCES = _module_literal("_COMPUTE_SOURCES")
EMAIL_LAMBDAS = _module_literal("_EMAIL_LAMBDAS")
LAGGED_SOURCES = _module_literal("_LAGGED_SOURCES")
LAMBDA_TO_SOURCE = _module_literal("_LAMBDA_TO_SOURCE")
DUE_MONTHS = _module_literal("DUE_MONTHS")

SOURCE_TO_LAMBDA = {src: fn for fn, src in LAMBDA_TO_SOURCE.items()}

# The palette the front-end knows how to render. A status outside it is a blank dot.
STATUS_PALETTE = {"green", "yellow", "red", "gray", "blue"}
UPTIME_CODES = {0, 1, 2}


def _row(raw):
    """A `_DATA_SOURCES` tuple as a dict — the rows are 9 or 10 wide."""
    return {
        "id": raw[0],
        "name": raw[1],
        "description": raw[2],
        "yellow_h": raw[3],
        "red_h": raw[4],
        "category": raw[5] if len(raw) > 5 else "auto",
        "group": raw[6] if len(raw) > 6 else "API-Based",
        "activity_dep": raw[7] if len(raw) > 7 else False,
        "source_app": raw[8] if len(raw) > 8 else "",
        "field_check": raw[9] if len(raw) > 9 else None,
        "lagged": raw[0] in LAGGED_SOURCES,
        "alarmable": raw[0] in SOURCE_TO_LAMBDA,
    }


DATA_ROWS = [_row(r) for r in DATA_SOURCES]


def pick_data_source(pred, why):
    """The first row matching a PROPERTY — never a hard-coded source id."""
    for row in DATA_ROWS:
        if pred(row):
            return row
    raise AssertionError(f"_DATA_SOURCES no longer contains {why}; the test needs a new representative")


def pick_email(pred, why):
    for lid, name, desc, exp_dow, yh, rh in EMAIL_LAMBDAS:
        row = {"id": lid, "name": name, "exp_dow": exp_dow, "yellow_h": yh, "red_h": rh}
        if pred(row):
            return row
    raise AssertionError(f"_EMAIL_LAMBDAS no longer contains {why}")


def pick_compute(pred, why):
    for sid, name, desc, yh, rh in COMPUTE_SOURCES:
        row = {"id": sid, "name": name, "yellow_h": yh, "red_h": rh, "alarmable": sid in SOURCE_TO_LAMBDA}
        if pred(row):
            return row
    raise AssertionError(f"_COMPUTE_SOURCES no longer contains {why}")


# ──────────────────────────────────────────────────────────────────────────────
# Frozen time
# ──────────────────────────────────────────────────────────────────────────────

# Mid-afternoon UTC, comfortably past the uptime epoch (2026-03-28) so the bar
# window is the full 90. The time of day matters: a record written for "yesterday"
# is stored as that date's midnight, i.e. ~41.7h old at this instant, which is
# what makes the yellow-threshold test below meaningful.
FROZEN_NOW = datetime(2026, 8, 5, 17, 40, 0, tzinfo=timezone.utc)


def _frozen_datetime(now):
    """A real `datetime` subclass with `now()`/`utcnow()` pinned.

    A subclass rather than a Mock: the module calls `datetime.strptime`, the
    `datetime(...)` constructor and date arithmetic through the same name.
    """

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz is not None else now.replace(tzinfo=None)

        @classmethod
        def utcnow(cls):
            return now.replace(tzinfo=None)

    return _Frozen


class Clock:
    """`time.time()` for the response cache. Advanced explicitly by TTL tests."""

    def __init__(self, t=1_000_000.0):
        self.t = t

    def time(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def days_ago(n, now=FROZEN_NOW):
    return (now.date() - timedelta(days=n)).isoformat()


# ──────────────────────────────────────────────────────────────────────────────
# Bounded fakes — no MagicMock, no AWS
# ──────────────────────────────────────────────────────────────────────────────


def _flatten_condition(cond):
    """boto3 ConditionBase -> [(attr_name, operator, args)]."""
    expr = cond.get_expression()
    if expr["operator"] == "AND":
        out = []
        for value in expr["values"]:
            out.extend(_flatten_condition(value))
        return out
    return [(expr["values"][0].name, expr["operator"], tuple(expr["values"][1:]))]


class FakeTable:
    """A DynamoDB Table stand-in keyed exactly the way this module keys the real one.

    Honours the three query shapes `site_api_status` issues:
      * `pk = :pk` (health-check probe, one-time genome import),
      * `pk = :pk AND begins_with(sk, "DATE#")` (+ optional `attribute_exists`
        FilterExpression for a shared partition's sub-source),
      * `pk = :pk AND sk BETWEEN :a AND :b` (the uptime window).

    Limit is applied BEFORE FilterExpression, as DynamoDB really does — the
    sub-source lookup relies on that ordering, so the fake must not flatter it.
    """

    def __init__(self, items):
        self.items = list(items)
        self.queries = []
        self.error = None  # raise on every query
        self.error_pks = set()  # raise only for these partitions
        self.error_on_between = False  # raise only for the uptime-window query
        self.error_when = None  # callable(kwargs) -> bool: raise only for matching queries

    def query(self, **kwargs):
        self.queries.append(kwargs)
        if self.error is not None:
            raise self.error
        if self.error_when is not None and self.error_when(kwargs):
            raise RuntimeError("ProvisionedThroughputExceeded")

        conds = _flatten_condition(kwargs["KeyConditionExpression"])
        pk = next(args[0] for name, op, args in conds if name == "pk" and op == "=")
        if pk in self.error_pks:
            raise RuntimeError(f"ProvisionedThroughputExceeded on {pk}")

        rows = [i for i in self.items if i["pk"] == pk]
        for name, op, args in conds:
            if name != "sk":
                continue
            if op == "begins_with":
                rows = [r for r in rows if r["sk"].startswith(args[0])]
            elif op == "BETWEEN":
                if self.error_on_between:
                    raise RuntimeError("uptime window query failed")
                rows = [r for r in rows if args[0] <= r["sk"] <= args[1]]
            else:  # pragma: no cover — the module issues no other sk operator
                raise AssertionError(f"unhandled sk operator {op}")

        rows.sort(key=lambda r: r["sk"], reverse=not kwargs.get("ScanIndexForward", True))
        limit = kwargs.get("Limit")
        if limit is not None:
            rows = rows[:limit]

        filt = kwargs.get("FilterExpression")
        if filt is not None:
            for name, op, _args in _flatten_condition(filt):
                assert op == "attribute_exists", f"unhandled filter operator {op}"
                rows = [r for r in rows if name in r]

        return {"Items": rows}


class TableBuilder:
    """Accumulates DDB rows keyed (pk, sk); repeated adds merge fields."""

    def __init__(self):
        self._rows = {}

    def add(self, source_id, date, **fields):
        key = (f"{USER_PREFIX}{source_id}", f"DATE#{date}")
        self._rows.setdefault(key, {"pk": key[0], "sk": key[1]}).update(fields)
        return self

    def add_days(self, source_id, day_numbers, now=FROZEN_NOW, **fields):
        for n in day_numbers:
            self.add(source_id, days_ago(n, now), **fields)
        return self

    def clear(self, source_id):
        pk = f"{USER_PREFIX}{source_id}"
        self._rows = {k: v for k, v in self._rows.items() if k[0] != pk}
        return self

    def build(self):
        return FakeTable(self._rows.values())


def healthy_platform(now=FROZEN_NOW, history_days=14):
    """Every component of every table flowing normally, derived from the tables.

    Recurring sources get `history_days` of daily records (enough for the
    "was flowing regularly" history probe); manual/one-time sources get a single
    recent record so they sit inside their due window.
    """
    b = TableBuilder()
    recurring = range(history_days)
    for row in DATA_ROWS:
        if row["category"] == "onetime":
            b.add(row["id"], "2026-01-15")
            continue
        fields = {row["field_check"]: Decimal("1")} if row["field_check"] else {}
        if row["category"] == "manual":
            b.add(row["id"], days_ago(5, now), **fields)
        else:
            b.add_days(row["id"], recurring, now=now, **fields)
    for sid, *_ in COMPUTE_SOURCES:
        b.add_days(sid, recurring, now=now)
    for lid, *_ in EMAIL_LAMBDAS:
        b.add_days(f"email_log#{lid}", recurring, now=now)
    return b


class FakeCloudWatch:
    def __init__(self, alarms=(), error=None):
        self.alarms = list(alarms)
        self.error = error

    def describe_alarms(self, **kwargs):
        if self.error is not None:
            raise self.error
        return {"MetricAlarms": self.alarms}


class FakeSQS:
    def __init__(self, depth=None, error=None):
        self.depth = depth
        self.error = error

    def get_queue_attributes(self, **kwargs):
        if self.error is not None or self.depth is None:
            raise self.error or RuntimeError("queue unreachable")
        return {"Attributes": {"ApproximateNumberOfMessages": str(self.depth)}}


class FakeBoto3:
    def __init__(self, cloudwatch, sqs):
        self._clients = {"cloudwatch": cloudwatch, "sqs": sqs}

    def client(self, name, region_name=None, **kwargs):
        try:
            return self._clients[name]
        except KeyError:  # pragma: no cover — the module builds no other client
            raise AssertionError(f"site_api_status built an unexpected boto3 client: {name}")


def alarm_on(function_name, alarm_name="ingestion-errors"):
    return {"AlarmName": alarm_name, "Dimensions": [{"Name": "FunctionName", "Value": function_name}]}


def alarm_for_source(source_id):
    assert source_id in SOURCE_TO_LAMBDA, f"{source_id} has no Lambda in _LAMBDA_TO_SOURCE — pick an alarmable component"
    return alarm_on(SOURCE_TO_LAMBDA[source_id])


# ──────────────────────────────────────────────────────────────────────────────
# Driver
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_status_cache():
    """`_status_cache` / `_status_cache_ts` are MODULE state shared by both
    handlers. Left alone, the first test's answer would be served to every later
    test in the file (and to any other test file that touches these handlers)."""
    sas._status_cache = {}
    sas._status_cache_ts = 0
    yield
    sas._status_cache = {}
    sas._status_cache_ts = 0


class Harness:
    """Drives the real handlers against injected state, with time frozen."""

    def __init__(self, monkeypatch, table, *, now=FROZEN_NOW, alarms=(), cw_error=None, dlq=None, sqs_error=None, cost=None):
        self.table = table
        self.now = now
        self.clock = Clock()
        self.cost = {} if cost is None else cost
        self.cloudwatch = FakeCloudWatch(alarms, cw_error)
        self.sqs = FakeSQS(dlq, sqs_error)
        monkeypatch.setattr(sas, "datetime", _frozen_datetime(now))
        monkeypatch.setattr(sas, "time", self.clock)
        monkeypatch.setattr(sas, "boto3", FakeBoto3(self.cloudwatch, self.sqs))
        self._g = {"table": table, "_budget_cost_block": lambda: dict(self.cost)}

    def status(self):
        return sas.status(_g=self._g)

    def summary(self):
        return sas.status_summary(_g=self._g)

    def body(self):
        return json.loads(self.status()["body"])

    def summary_body(self):
        return json.loads(self.summary()["body"])


def groups(body):
    return {g["id"]: g for g in body["groups"]}


def components(body, group_id):
    return groups(body)[group_id]["components"]


def all_pipeline_components(body):
    """Data sources + compute + email — the three panels the rollup reads."""
    return [c for gid in ("data_sources", "compute", "email") for c in components(body, gid)]


def by_name(body, group_id, name):
    for c in components(body, group_id):
        if c["name"] == name:
            return c
    raise AssertionError(f"no component named {name!r} in group {group_id}")


def by_id(body, group_id, cid):
    matches = [c for c in components(body, group_id) if c["id"] == cid]
    assert matches, f"no component with id {cid!r} in group {group_id}"
    return matches[0]


# ══════════════════════════════════════════════════════════════════════════════
# 1. The response envelope and the panels the status page renders
# ══════════════════════════════════════════════════════════════════════════════


def test_status_answers_200_with_a_one_minute_cache_header(monkeypatch):
    resp = Harness(monkeypatch, healthy_platform().build()).status()
    assert resp["statusCode"] == 200
    assert resp["headers"]["Cache-Control"] == "public, max-age=60, s-maxage=60"


def test_the_page_publishes_the_four_panels_the_status_page_renders(monkeypatch):
    body = Harness(monkeypatch, healthy_platform().build()).body()
    assert [g["id"] for g in body["groups"]] == ["data_sources", "compute", "email", "infrastructure"]
    for group in body["groups"]:
        assert group["label"] and group["subtitle"], "every panel needs a heading a reader can read"


def test_the_page_publishes_a_traffic_light_a_timestamp_and_a_probe_summary(monkeypatch):
    body = Harness(monkeypatch, healthy_platform().build()).body()
    assert body["overall"] in STATUS_PALETTE
    assert body["generated_at"] == FROZEN_NOW.isoformat(), "the page must date itself from the clock, not a literal"
    assert "health_check" in body and "cost" in body


def test_every_published_component_carries_an_id_a_name_and_a_renderable_status(monkeypatch):
    """A property of EVERY row, so a new source cannot slip past this file."""
    body = Harness(monkeypatch, healthy_platform().build()).body()
    seen = 0
    for group in body["groups"]:
        for c in group["components"]:
            seen += 1
            assert c["id"], f"component without an id in {group['id']}"
            assert c["name"], f"component {c['id']} has no display name"
            assert c["status"] in STATUS_PALETTE, f"{c['name']} published unrenderable status {c['status']!r}"
    assert seen == len(DATA_SOURCES) + len(COMPUTE_SOURCES) + len(EMAIL_LAMBDAS) + len(components(body, "infrastructure"))


def test_each_pipeline_component_reports_when_it_last_produced_data(monkeypatch):
    body = Harness(monkeypatch, healthy_platform().build()).body()
    for c in all_pipeline_components(body):
        assert c["last_sync_relative"], f"{c['name']} published no relative age at all"


def test_the_data_source_panel_publishes_one_component_per_row_of_the_modules_table(monkeypatch):
    """Derived from the module's own table — never a frozen list of names."""
    body = Harness(monkeypatch, healthy_platform().build()).body()
    published = [(c["id"], c["name"]) for c in components(body, "data_sources")]
    assert published == [(r["id"], r["name"]) for r in DATA_ROWS]


def test_the_compute_and_email_panels_publish_one_component_per_table_row(monkeypatch):
    body = Harness(monkeypatch, healthy_platform().build()).body()
    assert [c["id"] for c in components(body, "compute")] == [r[0] for r in COMPUTE_SOURCES]
    assert [c["id"] for c in components(body, "email")] == [r[0] for r in EMAIL_LAMBDAS]


def test_the_data_source_subtitle_counts_the_feeds_it_labels(monkeypatch):
    """The subtitle states a number to the reader; it must be the real one."""
    body = Harness(monkeypatch, healthy_platform().build()).body()
    panel = groups(body)["data_sources"]
    assert panel["subtitle"].startswith(f"{len(panel['components'])} feeds")


def test_every_data_source_names_the_app_it_came_from(monkeypatch):
    """The panel separates the DATA type from the vendor; both are reader-facing."""
    body = Harness(monkeypatch, healthy_platform().build()).body()
    for c in components(body, "data_sources"):
        assert c["group"], f"{c['name']} has no panel group"
        assert c["source_app"], f"{c['name']} does not say which app it comes from"


# ══════════════════════════════════════════════════════════════════════════════
# 2. The response cache — and that the footer dot cannot contradict the page
# ══════════════════════════════════════════════════════════════════════════════


def test_a_second_call_inside_the_cache_window_does_not_touch_dynamodb(monkeypatch):
    h = Harness(monkeypatch, healthy_platform().build())
    h.status()
    queries_after_first = len(h.table.queries)
    assert queries_after_first > 0
    h.status()
    assert len(h.table.queries) == queries_after_first, "the cached page must not re-query the table"


def test_the_cached_page_is_served_verbatim(monkeypatch):
    h = Harness(monkeypatch, healthy_platform().build())
    first = h.body()
    second = h.body()
    assert first["generated_at"] == second["generated_at"]
    assert first["groups"] == second["groups"]


def test_the_cache_expires_and_the_next_call_rebuilds_from_the_table(monkeypatch):
    h = Harness(monkeypatch, healthy_platform().build())
    h.status()
    queries_after_first = len(h.table.queries)
    h.clock.advance(STATUS_CACHE_TTL + 1)
    h.status()
    assert len(h.table.queries) > queries_after_first


def test_the_cache_holds_right_up_to_the_ttl_boundary(monkeypatch):
    h = Harness(monkeypatch, healthy_platform().build())
    h.status()
    queries_after_first = len(h.table.queries)
    h.clock.advance(STATUS_CACHE_TTL - 1)
    h.status()
    assert len(h.table.queries) == queries_after_first


def test_the_footer_dot_reports_the_same_traffic_light_as_the_full_page(monkeypatch):
    h = Harness(monkeypatch, healthy_platform().build())
    page = h.body()
    dot = h.summary_body()
    assert dot["overall"] == page["overall"]
    assert dot["generated_at"] == page["generated_at"]


def test_the_footer_dot_is_lightweight_and_publishes_no_component_detail(monkeypatch):
    h = Harness(monkeypatch, healthy_platform().build())
    dot = h.summary_body()
    assert set(dot) - {"_meta"} == {"overall", "generated_at"}


def test_the_footer_dot_builds_the_page_when_the_cache_is_cold(monkeypatch):
    h = Harness(monkeypatch, healthy_platform().build())
    dot = h.summary_body()
    assert h.table.queries, "a cold summary must actually compute the status"
    assert dot["overall"] in STATUS_PALETTE


def test_the_footer_dot_reuses_a_warm_cache_rather_than_recomputing(monkeypatch):
    h = Harness(monkeypatch, healthy_platform().build())
    h.status()
    queries_after_page = len(h.table.queries)
    h.summary()
    assert len(h.table.queries) == queries_after_page


def test_the_footer_dot_can_lag_the_truth_by_at_most_the_cache_ttl(monkeypatch):
    """The dot is deliberately eventually-consistent — but bounded by the TTL,
    and the page it disagrees with is equally stale, so the two never conflict."""
    table = healthy_platform().build()
    h = Harness(monkeypatch, table)
    assert h.body()["overall"] == "green"

    # A pipeline dies while the cache is warm.
    dead = pick_data_source(lambda r: r["category"] == "auto" and not r["activity_dep"], "an always-on auto source")
    table.items = [i for i in table.items if i["pk"] != f"{USER_PREFIX}{dead['id']}"]

    assert h.summary_body()["overall"] == "green", "inside the TTL the dot holds its cached verdict"
    h.clock.advance(STATUS_CACHE_TTL + 1)
    assert h.summary_body()["overall"] != "green", "once the TTL lapses the dot must tell the truth"


# ══════════════════════════════════════════════════════════════════════════════
# 3. The freshness -> colour ladder
# ══════════════════════════════════════════════════════════════════════════════


def _plain_source():
    """An always-on source that owns its own partition and gets no lag grace —
    the cleanest window onto the raw freshness ladder."""
    return pick_data_source(
        lambda r: r["category"] == "auto" and not r["activity_dep"] and not r["lagged"] and r["field_check"] is None,
        "an auto, non-activity-dependent, non-lagged source with its own partition",
    )


def _source_aged(row, age_days, *, history=1, now=FROZEN_NOW):
    b = healthy_platform(now=now).clear(row["id"])
    for i in range(history):
        b.add(row["id"], days_ago(age_days + i, now))
    return b.build()


@pytest.mark.parametrize("age,expected_rel", [(0, "today"), (1, "yesterday"), (2, "2d ago"), (5, "5d ago")])
def test_the_relative_age_string_is_the_one_a_human_reads(monkeypatch, age, expected_rel):
    row = _plain_source()
    body = Harness(monkeypatch, _source_aged(row, age)).body()
    assert by_name(body, "data_sources", row["name"])["last_sync_relative"] == expected_rel


def test_data_arriving_today_is_green(monkeypatch):
    row = _plain_source()
    c = by_name(Harness(monkeypatch, _source_aged(row, 0)).body(), "data_sources", row["name"])
    assert c["status"] == "green"
    assert c["comment"] is None, "a healthy source needs no explanation"


def test_data_from_yesterday_is_still_green(monkeypatch):
    """Overnight ingestion means 'yesterday' is normal, not degraded."""
    row = _plain_source()
    assert by_name(Harness(monkeypatch, _source_aged(row, 1)).body(), "data_sources", row["name"])["status"] == "green"


def test_two_day_old_data_is_yellow_and_says_it_is_being_watched(monkeypatch):
    row = _plain_source()
    c = by_name(Harness(monkeypatch, _source_aged(row, 2)).body(), "data_sources", row["name"])
    assert c["status"] == "yellow"
    assert "monitoring" in c["comment"]


def test_data_past_the_red_threshold_is_red_and_names_the_threshold(monkeypatch):
    row = _plain_source()
    c = by_name(Harness(monkeypatch, _source_aged(row, 6)).body(), "data_sources", row["name"])
    assert c["status"] == "red"
    assert "STALE" in c["comment"]
    assert str(row["red_h"]) in c["comment"], "a reader must be able to see WHICH threshold was blown"


def test_an_always_on_source_with_no_records_at_all_is_red_and_says_never(monkeypatch):
    """ADR-104: absence is reported as absence, not smoothed into health."""
    row = _plain_source()
    table = healthy_platform().clear(row["id"]).build()
    c = by_name(Harness(monkeypatch, table).body(), "data_sources", row["name"])
    assert c["status"] == "red"
    assert c["last_sync_relative"] == "never"
    assert "No records" in c["comment"]


def test_the_colour_ladder_is_monotonic_in_staleness(monkeypatch):
    """Older data can never be reported as healthier than newer data."""
    row = _plain_source()
    severity = {"green": 0, "yellow": 1, "red": 2}
    seen = []
    for age in (0, 1, 2, 3, 10):
        body = Harness(monkeypatch, _source_aged(row, age)).body()
        sas._status_cache = {}  # the harness caches per call; each age needs its own build
        sas._status_cache_ts = 0
        seen.append(severity[by_name(body, "data_sources", row["name"])["status"]])
    assert seen == sorted(seen), f"staleness ladder went backwards: {seen}"


# ── The lagged-source grace ───────────────────────────────────────────────────


def _lagged_source():
    return pick_data_source(
        lambda r: r["lagged"] and r["category"] == "auto" and not r["activity_dep"] and r["field_check"] is None,
        "a lagged (wake-date keyed) source",
    )


def test_a_lagged_source_gets_exactly_one_extra_day_of_green(monkeypatch):
    """Sleep/recovery data is keyed by wake date, so 'yesterday' IS current."""
    lagged, plain = _lagged_source(), _plain_source()
    lagged_c = by_name(Harness(monkeypatch, _source_aged(lagged, 2)).body(), "data_sources", lagged["name"])
    sas._status_cache, sas._status_cache_ts = {}, 0
    plain_c = by_name(Harness(monkeypatch, _source_aged(plain, 2)).body(), "data_sources", plain["name"])
    assert lagged_c["status"] == "green"
    assert plain_c["status"] == "yellow", "the grace must be granted to lagged sources only"


def test_a_lagged_source_reads_current_rather_than_a_misleading_day_count(monkeypatch):
    row = _lagged_source()
    for age in (1, 2):
        body = Harness(monkeypatch, _source_aged(row, age)).body()
        sas._status_cache, sas._status_cache_ts = {}, 0
        assert by_name(body, "data_sources", row["name"])["last_sync_relative"] == "current"


def test_a_lagged_sources_own_day_of_data_still_reads_today(monkeypatch):
    row = _lagged_source()
    c = by_name(Harness(monkeypatch, _source_aged(row, 0)).body(), "data_sources", row["name"])
    assert c["last_sync_relative"] == "today"
    assert c["status"] == "green"


def test_the_lag_grace_runs_out_and_a_lagged_source_does_go_yellow(monkeypatch):
    row = _lagged_source()
    c = by_name(Harness(monkeypatch, _source_aged(row, 3)).body(), "data_sources", row["name"])
    assert c["status"] == "yellow"
    assert c["last_sync_relative"] == "3d ago", "once genuinely stale it must stop saying 'current'"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "DEFECT (tranche-2 discovery, CAUSE CORRECTED and DELIBERATELY LEFT by #2221). The premise "
        "is confirmed: _comp_status() takes yellow_h and never reads it — the yellow boundary is "
        "hard-coded at effective_days <= 1, so every yellow_h column in _DATA_SOURCES / "
        "_COMPUTE_SOURCES / _EMAIL_LAMBDAS is inert. But the prescribed repair — start enforcing the "
        "configured hours — cannot be shipped as written, for two measured reasons. (1) It "
        "CONTRADICTS test_data_from_yesterday_is_still_green in this same file, on the SAME row: "
        "_plain_source() and this test's picker differ only by `yellow_h < 41`, and both resolve to "
        "`weather`. One asserts yesterday->green, the other asserts yesterday (41.7h at the frozen "
        "clock, yellow_h=25) -> yellow. Both cannot hold. (2) The 25h is a PICKED number that "
        "disagrees with the platform's own cadence-derived window: source_registry['weather'] sets "
        "stale_hours=None -> the 48h default, commented 'comfortably covers the 2x-daily cron "
        "without false-staling' — under which 41.7h IS green. So the real finding is one level up: "
        "_DATA_SOURCES hand-types freshness windows that duplicate and contradict "
        "lambdas/ingestion/source_registry.py, and then does not read them. The fix is to derive "
        "these columns from the registry (freshness windows come from the writer's cron, never "
        "picked) and retire whichever of the two sibling contracts loses — a threshold decision "
        "about the reader-facing traffic light, not a code change. Half-enforcing a picked number "
        "would trade a dead column for a false yellow."
    ),
)
def test_a_source_past_its_own_yellow_threshold_is_not_reported_green(monkeypatch):
    row = pick_data_source(
        lambda r: r["category"] == "auto" and not r["activity_dep"] and not r["lagged"] and r["field_check"] is None and r["yellow_h"] < 41,
        "an auto source whose configured yellow threshold is under 41h",
    )
    # A record dated 'yesterday' is stored at that date's midnight — with the clock
    # frozen at 17:40 UTC that is 41.7h old, past this source's own yellow_h.
    hours_old = (FROZEN_NOW - datetime(2026, 8, 4, tzinfo=timezone.utc)).total_seconds() / 3600
    assert hours_old > row["yellow_h"], "sanity: the fixture really is past the configured threshold"
    c = by_name(Harness(monkeypatch, _source_aged(row, 1)).body(), "data_sources", row["name"])
    assert c["status"] == "yellow"


# ══════════════════════════════════════════════════════════════════════════════
# 4. Override precedence: CloudWatch alarm > health-check probe > staleness
# ══════════════════════════════════════════════════════════════════════════════


def _alarmable_fresh_source():
    return pick_data_source(
        lambda r: r["alarmable"] and r["category"] == "auto" and not r["activity_dep"] and r["field_check"] is None,
        "an alarmable auto source with its own partition",
    )


def test_an_alarm_over_fresh_data_reads_as_recovering_not_as_failure(monkeypatch):
    """The documented 'alarm recovering' case: a 24h-window alarm still firing
    while data has already resumed. Yellow, not red — and it says why."""
    row = _alarmable_fresh_source()
    h = Harness(monkeypatch, healthy_platform().build(), alarms=[alarm_for_source(row["id"])])
    c = by_name(h.body(), "data_sources", row["name"])
    assert c["status"] == "yellow"
    assert "recovering" in c["comment"]


def test_an_alarm_over_stale_data_is_red_and_names_the_lambda_errors(monkeypatch):
    row = _alarmable_fresh_source()
    h = Harness(monkeypatch, _source_aged(row, 6), alarms=[alarm_for_source(row["id"])])
    c = by_name(h.body(), "data_sources", row["name"])
    assert c["status"] == "red"
    assert "alarm firing" in c["comment"]


def test_an_alarm_reaches_a_source_only_through_the_function_name_dimension(monkeypatch):
    row = _alarmable_fresh_source()
    baseline = Harness(monkeypatch, healthy_platform().build()).body()
    sas._status_cache, sas._status_cache_ts = {}, 0
    dimensionless = {"AlarmName": f"ingestion-error-{row['id']}", "Dimensions": []}
    escalated = Harness(monkeypatch, healthy_platform().build(), alarms=[dimensionless]).body()
    assert escalated["groups"] == baseline["groups"], "an alarm name alone must not be inferred onto a source"


def test_an_alarm_on_an_unmapped_lambda_changes_nothing(monkeypatch):
    baseline = Harness(monkeypatch, healthy_platform().build()).body()
    sas._status_cache, sas._status_cache_ts = {}, 0
    other = Harness(monkeypatch, healthy_platform().build(), alarms=[alarm_on("some-unrelated-lambda")]).body()
    assert other["groups"] == baseline["groups"]


def test_an_alarm_never_escalates_a_component_that_was_never_imported(monkeypatch):
    """Blue means 'not applicable yet'. Escalating it would invent a failure."""
    row = pick_data_source(lambda r: r["category"] == "manual" and r["alarmable"], "an alarmable manual source")
    table = healthy_platform().clear(row["id"]).build()
    c = by_name(Harness(monkeypatch, table, alarms=[alarm_for_source(row["id"])]).body(), "data_sources", row["name"])
    assert c["status"] == "blue"


def test_a_failed_daily_health_check_turns_its_source_red(monkeypatch):
    """The active probe outranks freshness: data can look current while the
    pipeline that produced it is broken."""
    row = _plain_source()
    b = healthy_platform()
    b.add(
        "health_check",
        days_ago(0),
        checked_at=FROZEN_NOW.isoformat(),
        passed=Decimal("20"),
        failed=Decimal("1"),
        failures=json.dumps([{"source_id": row["id"]}]),
    )
    c = by_name(Harness(monkeypatch, b.build()).body(), "data_sources", row["name"])
    assert c["status"] == "red"
    assert "health check failed" in c["comment"]


def test_a_cloudwatch_alarm_outranks_a_failed_health_check(monkeypatch):
    """Both fire on the same source; the alarm's wording is what a reader gets."""
    row = _alarmable_fresh_source()
    b = healthy_platform()
    b.add(
        "health_check",
        days_ago(0),
        checked_at=FROZEN_NOW.isoformat(),
        passed=Decimal("20"),
        failed=Decimal("1"),
        failures=json.dumps([{"source_id": row["id"]}]),
    )
    c = by_name(Harness(monkeypatch, b.build(), alarms=[alarm_for_source(row["id"])]).body(), "data_sources", row["name"])
    assert "alarm" in c["comment"]
    assert "health check" not in c["comment"]


def test_the_health_check_probe_summary_is_republished_for_the_reader(monkeypatch):
    b = healthy_platform()
    b.add(
        "health_check",
        days_ago(0),
        checked_at="2026-08-05T06:00:00+00:00",
        passed=Decimal("22"),
        failed=Decimal("3"),
        failures=json.dumps([]),
    )
    hc = Harness(monkeypatch, b.build()).body()["health_check"]
    assert hc == {"checked_at": "2026-08-05T06:00:00+00:00", "passed": 22, "failed": 3}


def test_only_the_most_recent_health_check_run_is_published(monkeypatch):
    b = healthy_platform()
    for n, passed in ((3, "5"), (0, "22")):
        b.add("health_check", days_ago(n), checked_at=days_ago(n), passed=Decimal(passed), failed=Decimal("0"), failures="[]")
    assert Harness(monkeypatch, b.build()).body()["health_check"]["passed"] == 22


def test_a_malformed_failure_list_still_publishes_the_probe_counts(monkeypatch):
    """Half a probe result is better than none — and no source is falsely reddened."""
    b = healthy_platform()
    b.add("health_check", days_ago(0), checked_at="x", passed=Decimal("20"), failed=Decimal("1"), failures="{not json")
    body = Harness(monkeypatch, b.build()).body()
    assert body["health_check"]["passed"] == 20
    assert body["overall"] == "green"


def test_a_dynamodb_failure_on_the_probe_read_is_not_fatal(monkeypatch):
    table = healthy_platform().build()
    table.error_pks.add(f"{USER_PREFIX}health_check")
    h = Harness(monkeypatch, table)
    assert h.status()["statusCode"] == 200
    assert h.body()["health_check"] == {}, "an unreadable probe publishes nothing, never a guess"


def test_cloudwatch_being_unreachable_does_not_break_the_page(monkeypatch):
    h = Harness(monkeypatch, healthy_platform().build(), cw_error=RuntimeError("AccessDenied on DescribeAlarms"))
    body = h.body()
    assert h.status()["statusCode"] == 200
    assert body["overall"] == "green"


# ══════════════════════════════════════════════════════════════════════════════
# 5. The 90-day uptime bars
# ══════════════════════════════════════════════════════════════════════════════


def test_uptime_bars_use_only_the_three_codes_the_front_end_can_draw(monkeypatch):
    body = Harness(monkeypatch, healthy_platform().build()).body()
    for c in all_pipeline_components(body):
        assert set(c["uptime_90d"]) <= UPTIME_CODES, f"{c['name']} published an undrawable bar code"


def test_the_bar_window_is_ninety_days_once_the_epoch_is_that_far_behind(monkeypatch):
    body = Harness(monkeypatch, healthy_platform().build()).body()
    row = _plain_source()
    assert len(by_name(body, "data_sources", row["name"])["uptime_90d"]) == 90


def test_the_bar_window_never_starts_before_the_platforms_own_epoch(monkeypatch):
    """Two weeks after the epoch there are fourteen days of history — not ninety
    bars of invented past."""
    early = datetime(2026, 4, 10, 12, 0, tzinfo=timezone.utc)
    row = _plain_source()
    table = healthy_platform(now=early).build()
    body = Harness(monkeypatch, table, now=early).body()
    assert len(by_name(body, "data_sources", row["name"])["uptime_90d"]) == 14


def test_before_the_epoch_the_bars_collapse_to_a_single_neutral(monkeypatch):
    pre = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    row = _plain_source()
    body = Harness(monkeypatch, healthy_platform(now=pre).build(), now=pre).body()
    assert by_name(body, "data_sources", row["name"])["uptime_90d"] == [2]


def test_a_day_with_data_is_green_and_an_older_empty_day_is_red(monkeypatch):
    """The bar is the reader's evidence that the pipeline ran. Gaps must show."""
    row = _plain_source()
    table = healthy_platform().clear(row["id"]).add_days(row["id"], [0, 1, 2, 4, 5]).build()
    bars = by_name(Harness(monkeypatch, table).body(), "data_sources", row["name"])["uptime_90d"]
    assert bars[-1] == 1 and bars[-3] == 1, "days with data are green"
    assert bars[-4] == 0, "an older day with no data is a red bar"
    assert bars[-6] == 1


def test_today_and_yesterday_are_neutral_rather_than_red_while_data_may_still_land(monkeypatch):
    row = _plain_source()
    table = healthy_platform().clear(row["id"]).add_days(row["id"], range(2, 10)).build()
    bars = by_name(Harness(monkeypatch, table).body(), "data_sources", row["name"])["uptime_90d"]
    assert bars[-1] == 2 and bars[-2] == 2, "the two open days must not be scored as failures"
    assert bars[-3] == 1


def test_an_activity_dependent_source_shows_neutral_rather_than_red_for_quiet_days(monkeypatch):
    """A day the human did not log is not a system failure."""
    row = pick_data_source(
        lambda r: r["activity_dep"] and r["category"] == "auto" and r["field_check"] is None,
        "an activity-dependent auto source",
    )
    table = healthy_platform().clear(row["id"]).add_days(row["id"], [0, 1, 2, 20]).build()
    bars = by_name(Harness(monkeypatch, table).body(), "data_sources", row["name"])["uptime_90d"]
    assert 0 not in bars, "activity-dependent gaps must never be drawn as outages"
    assert 1 in bars


def test_a_failed_uptime_query_degrades_to_a_single_neutral_bar(monkeypatch):
    """Better one honest 'unknown' bar than ninety invented ones."""
    table = healthy_platform().build()
    table.error_on_between = True
    h = Harness(monkeypatch, table)
    body = h.body()
    assert h.status()["statusCode"] == 200
    for c in all_pipeline_components(body):
        assert c["uptime_90d"] in ([2], []), f"{c['name']} invented bars after a query failure"


def test_manual_and_onetime_sources_publish_no_daily_bars(monkeypatch):
    """A quarterly CSV import has no daily uptime to draw."""
    body = Harness(monkeypatch, healthy_platform().build()).body()
    for row in DATA_ROWS:
        if row["category"] in ("manual", "onetime"):
            assert by_name(body, "data_sources", row["name"])["uptime_90d"] == []


def test_a_sub_source_uptime_bar_reflects_that_sub_sources_own_data(monkeypatch):
    """#2221 (was a tranche-2 xfail): _uptime_90d now takes the row's field_check and
    filters server-side, so a sub-source of a shared partition draws its OWN bars."""
    shared = [r for r in DATA_ROWS if r["field_check"]]
    assert len(shared) >= 2, "this contract only exists while a partition is shared by sub-sources"
    target, other = shared[0], shared[1]
    assert target["id"] == other["id"], "the shared-partition premise no longer holds"

    b = healthy_platform().clear(target["id"])
    # Only the OTHER sub-source ever wrote to the shared partition.
    b.add_days(target["id"], range(30), **{other["field_check"]: Decimal("1")})
    c = by_name(Harness(monkeypatch, b.build()).body(), "data_sources", target["name"])
    assert c["last_sync_relative"] == "never", "sanity: this sub-source really has no data"
    assert 1 not in c["uptime_90d"], "a green bar claims data this sub-source never produced"


# ══════════════════════════════════════════════════════════════════════════════
# 6. The manual and one-time categories
# ══════════════════════════════════════════════════════════════════════════════


def _manual_source(min_due_months=0):
    return pick_data_source(
        lambda r: r["category"] == "manual" and DUE_MONTHS.get(r["id"], 6) >= min_due_months and r["field_check"] is None,
        f"a manual source with a cadence of at least {min_due_months} months",
    )


def _manual_aged(row, age_days):
    return healthy_platform().clear(row["id"]).add(row["id"], days_ago(age_days)).build()


def test_a_manual_source_inside_its_cadence_is_green_and_names_the_next_due_date(monkeypatch):
    row = _manual_source()
    due_mo = DUE_MONTHS.get(row["id"], 6)
    c = by_name(Harness(monkeypatch, _manual_aged(row, 10)).body(), "data_sources", row["name"])
    assert c["status"] == "green"
    assert "Next due:" in c["comment"]
    expected_due = (FROZEN_NOW - timedelta(days=10) + timedelta(days=due_mo * 30)).strftime("%b %Y")
    assert expected_due in c["comment"], "the due date must be its own cadence past the last import"


def test_a_manual_source_past_its_cadence_is_yellow_and_asks_for_a_refresh(monkeypatch):
    row = _manual_source()
    due_mo = DUE_MONTHS.get(row["id"], 6)
    c = by_name(Harness(monkeypatch, _manual_aged(row, int(due_mo * 30 * 1.1))).body(), "data_sources", row["name"])
    assert c["status"] == "yellow"
    assert "Due for refresh" in c["comment"]


def test_a_manual_source_far_past_its_cadence_says_overdue(monkeypatch):
    row = _manual_source()
    due_mo = DUE_MONTHS.get(row["id"], 6)
    c = by_name(Harness(monkeypatch, _manual_aged(row, int(due_mo * 30 * 2))).body(), "data_sources", row["name"])
    assert c["status"] == "yellow"
    assert "Overdue" in c["comment"]


def test_a_never_imported_manual_source_is_blue_not_red(monkeypatch):
    """An appointment never booked is not a broken pipeline."""
    row = _manual_source()
    table = healthy_platform().clear(row["id"]).build()
    c = by_name(Harness(monkeypatch, table).body(), "data_sources", row["name"])
    assert c["status"] == "blue"
    assert c["last_sync_relative"] == "never"
    assert "No data yet" in c["comment"]


@pytest.mark.parametrize("age,expected", [(0, "today"), (1, "yesterday"), (29, "29d ago"), (65, "2mo ago")])
def test_manual_relative_time_switches_from_days_to_months_at_thirty(monkeypatch, age, expected):
    row = _manual_source(min_due_months=6)
    c = by_name(Harness(monkeypatch, _manual_aged(row, age)).body(), "data_sources", row["name"])
    assert c["last_sync_relative"] == expected


def test_each_manual_source_is_graded_against_its_own_cadence(monkeypatch):
    """One shared age; the source due every N months and the one due every M
    must not be graded the same."""
    cadences = sorted({DUE_MONTHS.get(r["id"], 6) for r in DATA_ROWS if r["category"] == "manual"})
    assert len(cadences) >= 2, "the manual sources no longer have distinct cadences"
    short = pick_data_source(lambda r: r["category"] == "manual" and DUE_MONTHS.get(r["id"], 6) == cadences[0], "the shortest cadence")
    long = pick_data_source(lambda r: r["category"] == "manual" and DUE_MONTHS.get(r["id"], 6) == cadences[-1], "the longest cadence")
    # An age between the two cadences: overdue for one, comfortably fine for the other.
    age = int(((cadences[0] + cadences[-1]) / 2) * 30)
    table = healthy_platform().clear(short["id"]).clear(long["id"]).add(short["id"], days_ago(age)).add(long["id"], days_ago(age)).build()
    body = Harness(monkeypatch, table).body()
    assert by_name(body, "data_sources", short["name"])["status"] == "yellow"
    assert by_name(body, "data_sources", long["name"])["status"] == "green"


def test_a_onetime_import_on_file_is_green_and_says_so(monkeypatch):
    row = pick_data_source(lambda r: r["category"] == "onetime", "a one-time import")
    c = by_name(Harness(monkeypatch, healthy_platform().build()).body(), "data_sources", row["name"])
    assert c["status"] == "green"
    assert c["last_sync_relative"] == "imported"
    assert "One-time import" in c["comment"]


def test_an_absent_onetime_import_is_blue_and_awaiting_rather_than_failed(monkeypatch):
    row = pick_data_source(lambda r: r["category"] == "onetime", "a one-time import")
    table = healthy_platform().clear(row["id"]).build()
    c = by_name(Harness(monkeypatch, table).body(), "data_sources", row["name"])
    assert c["status"] == "blue"
    assert c["last_sync_relative"] == "not imported"
    assert "Awaiting" in c["comment"]


def test_a_onetime_import_is_never_aged_out(monkeypatch):
    """A genome does not go stale. Its status must not depend on a clock."""
    row = pick_data_source(lambda r: r["category"] == "onetime", "a one-time import")
    later = FROZEN_NOW + timedelta(days=400)
    table = healthy_platform(now=later).build()
    c = by_name(Harness(monkeypatch, table, now=later).body(), "data_sources", row["name"])
    assert c["status"] == "green"


# ══════════════════════════════════════════════════════════════════════════════
# 7. The activity-dependent adjustment — "user didn't log" vs "pipeline broke"
# ══════════════════════════════════════════════════════════════════════════════


def _activity_source(group_is_api):
    return pick_data_source(
        lambda r: (
            r["activity_dep"] and r["category"] == "auto" and r["field_check"] is None and ((r["group"] == "API-Based") == group_is_api)
        ),
        f"an activity-dependent auto source {'in' if group_is_api else 'outside'} the API-Based group",
    )


def test_an_api_source_with_a_multi_day_gap_is_flagged_not_excused(monkeypatch):
    """An API poller writes every day by construction, so a gap means the fetch
    failed (expired auth) — never 'the user was quiet'."""
    row = _activity_source(group_is_api=True)
    table = healthy_platform().clear(row["id"]).add_days(row["id"], [2, 3]).build()
    c = by_name(Harness(monkeypatch, table).body(), "data_sources", row["name"])
    assert c["status"] == "yellow"
    assert "Check auth/webhook" in c["comment"]


def test_a_source_that_flowed_daily_and_then_stopped_is_flagged_for_attention(monkeypatch):
    row = _activity_source(group_is_api=False)
    table = healthy_platform().clear(row["id"]).add_days(row["id"], range(5, 15)).build()
    c = by_name(Harness(monkeypatch, table).body(), "data_sources", row["name"])
    assert c["status"] == "yellow"
    assert "was flowing regularly but stopped" in c["comment"]


def test_a_source_that_was_always_sporadic_is_excused_as_missing_activity(monkeypatch):
    """The contract that makes the flag above meaningful: a source with no
    regular history is not accused of breaking."""
    row = _activity_source(group_is_api=False)
    table = healthy_platform().clear(row["id"]).add_days(row["id"], [5, 6]).build()
    c = by_name(Harness(monkeypatch, table).body(), "data_sources", row["name"])
    assert c["status"] == "green"
    assert "awaiting user activity" in c["comment"]
    assert c["last_sync_relative"] == "5d ago", "the excuse must still publish the real age"


def test_an_alarming_source_is_never_excused_as_missing_activity(monkeypatch):
    row = pick_data_source(
        lambda r: r["activity_dep"] and r["category"] == "auto" and r["field_check"] is None and r["alarmable"],
        "an alarmable activity-dependent source",
    )
    table = healthy_platform().clear(row["id"]).add_days(row["id"], [5, 6]).build()
    c = by_name(Harness(monkeypatch, table, alarms=[alarm_for_source(row["id"])]).body(), "data_sources", row["name"])
    assert c["status"] == "red"
    assert "alarm firing" in c["comment"]


def test_a_throttled_history_probe_falls_back_instead_of_failing_the_page(monkeypatch):
    """The "was it flowing regularly?" probe is a second, larger read. If DynamoDB
    throttles it the page must still answer — degraded to the excuse, not a 500."""
    row = _activity_source(group_is_api=False)
    table = healthy_platform().clear(row["id"]).add_days(row["id"], range(5, 15)).build()
    # Fail only the multi-record history probe; the single-record freshness read
    # and the uptime-window read still succeed.
    table.error_when = lambda kw: kw.get("Limit") not in (None, 1)
    h = Harness(monkeypatch, table)
    assert h.status()["statusCode"] == 200
    c = by_name(h.body(), "data_sources", row["name"])
    assert c["status"] in STATUS_PALETTE
    assert c["last_sync_relative"] == "5d ago", "the real age survives the degraded probe"


def test_a_source_that_has_never_produced_data_is_not_reported_green(monkeypatch):
    """ADR-104 / #2220: the "awaiting user activity" excuse needs a record to excuse.
    A feed nothing has ever arrived on cannot be distinguished from a working one if
    it publishes green."""
    row = _activity_source(group_is_api=False)
    table = healthy_platform().clear(row["id"]).build()
    c = by_name(Harness(monkeypatch, table).body(), "data_sources", row["name"])
    assert c["status"] != "green", f"published green with comment {c['comment']!r}"
    assert c["last_sync_relative"] == "never"


# ══════════════════════════════════════════════════════════════════════════════
# 8. The compute layer
# ══════════════════════════════════════════════════════════════════════════════


def test_a_compute_component_that_ran_today_is_green(monkeypatch):
    row = pick_compute(lambda r: True, "any compute component")
    c = by_id(Harness(monkeypatch, healthy_platform().build()).body(), "compute", row["id"])
    assert c["status"] == "green"
    assert c["last_sync_relative"] == "today"


def test_an_alarming_compute_component_is_red_whatever_its_freshness(monkeypatch):
    row = pick_compute(lambda r: r["alarmable"], "an alarmable compute component")
    c = by_id(Harness(monkeypatch, healthy_platform().build(), alarms=[alarm_for_source(row["id"])]).body(), "compute", row["id"])
    assert c["status"] == "red"
    assert "alarm firing" in c["comment"]


def test_a_compute_component_that_stopped_running_is_not_reported_green(monkeypatch):
    """ADR-104 / #2220: a silently-failing (non-erroring) daily compute used to be
    invisible — staleness could never redden a compute row, only a CloudWatch alarm
    could. The "runs daily when new data arrives" excuse is now bounded by the row's
    own red threshold."""
    row = pick_compute(lambda r: True, "any compute component")
    table = healthy_platform().clear(row["id"]).add_days(row["id"], range(45, 55)).build()
    c = by_id(Harness(monkeypatch, table).body(), "compute", row["id"])
    assert c["status"] != "green", f"45-day-old compute published green: {c['comment']!r}"
    assert c["last_sync_relative"] == "45d ago", "the real age must survive"


def test_a_compute_component_still_inside_its_threshold_keeps_the_ingestion_excuse(monkeypatch):
    """The excuse itself is legitimate and survives #2220: compute follows ingestion,
    so a gap shorter than the row's own red threshold is expected, not a failure."""
    row = pick_compute(lambda r: True, "any compute component")
    table = healthy_platform().clear(row["id"]).add_days(row["id"], range(2, 12)).build()
    c = by_id(Harness(monkeypatch, table).body(), "compute", row["id"])
    assert c["status"] == "green"
    assert "runs daily when new data arrives" in c["comment"]


def test_a_compute_component_that_never_ran_is_not_reported_green(monkeypatch):
    """ADR-104 / #2220: 'verified' is not an observation. This row used to publish
    green with last_sync_relative='verified' and 'Smoke-tested OK — awaiting first
    scheduled run (April 1+)' — an assertion about a pre-launch smoke run of a
    superseded experiment cycle, standing in for output that does not exist."""
    row = pick_compute(lambda r: True, "any compute component")
    table = healthy_platform().clear(row["id"]).build()
    c = by_id(Harness(monkeypatch, table).body(), "compute", row["id"])
    assert c["status"] != "green", f"published {c['last_sync_relative']!r} / {c['comment']!r}"
    assert c["last_sync_relative"] == "never"


def test_every_compute_row_names_a_partition_a_compute_lambda_actually_uses():
    """#2220's root cause for the one live 'never ran' row. `_COMPUTE_SOURCES` carried
    the id `insights`, but daily-insight-compute writes to `computed_insights` —
    SOURCE#insights exists only as INSIGHT#<timestamp> records, so the DATE# freshness
    probe could never match it. That row read "never" permanently, and the green
    rewrite this issue removes is the only reason nobody saw it.

    Guard the SET, not the instance: every id in the table must be a partition some
    module under lambdas/compute/ names, in one of the two forms those modules build a
    pk with. A typo'd or renamed partition reddens this test instead of silently
    publishing a component that can never report."""
    sources = sorted((ROOT / "lambdas" / "compute").glob("*.py"))
    assert sources, "lambdas/compute/ is where the compute writers live"
    texts = [p.read_text() for p in sources]
    for sid, *_ in COMPUTE_SOURCES:
        assert any(
            f'USER_PREFIX + "{sid}"' in t or f'SOURCE#{sid}"' in t for t in texts
        ), f"no module under lambdas/compute/ names SOURCE#{sid} — the freshness probe cannot ever match this row"


def test_compute_gaps_are_drawn_neutral_because_compute_follows_ingestion(monkeypatch):
    row = pick_compute(lambda r: True, "any compute component")
    table = healthy_platform().clear(row["id"]).add_days(row["id"], [0, 1, 2, 20]).build()
    bars = by_id(Harness(monkeypatch, table).body(), "compute", row["id"])["uptime_90d"]
    assert 0 not in bars


# ══════════════════════════════════════════════════════════════════════════════
# 9. The email senders
# ══════════════════════════════════════════════════════════════════════════════


def _weekly_email():
    return pick_email(lambda r: r["exp_dow"] >= 0, "a weekly (day-scheduled) sender")


def _daily_email():
    return pick_email(lambda r: r["exp_dow"] < 0, "a daily sender")


def test_an_email_sent_today_is_green(monkeypatch):
    row = _daily_email()
    c = by_id(Harness(monkeypatch, healthy_platform().build()).body(), "email", row["id"])
    assert c["status"] == "green"


def test_a_weekly_email_sent_inside_its_window_is_green_and_names_the_send(monkeypatch):
    row = _weekly_email()
    table = healthy_platform().clear(f"email_log#{row['id']}").add(f"email_log#{row['id']}", days_ago(6)).build()
    c = by_id(Harness(monkeypatch, table).body(), "email", row["id"])
    assert c["status"] == "green"
    assert "Last sent" in c["comment"] and "6d ago" in c["comment"]


def test_a_daily_email_silent_for_a_month_is_red(monkeypatch):
    """The daily brief is the platform's loudest promise; its silence must show."""
    row = _daily_email()
    table = healthy_platform().clear(f"email_log#{row['id']}").add(f"email_log#{row['id']}", days_ago(30)).build()
    c = by_id(Harness(monkeypatch, table).body(), "email", row["id"])
    assert c["status"] == "red"
    assert "STALE" in c["comment"]


def test_a_weekly_email_past_its_red_threshold_is_red(monkeypatch):
    row = _weekly_email()
    age = int(row["red_h"] / 24) + 3
    table = healthy_platform().clear(f"email_log#{row['id']}").add(f"email_log#{row['id']}", days_ago(age)).build()
    c = by_id(Harness(monkeypatch, table).body(), "email", row["id"])
    assert c["status"] == "red"


def test_an_alarming_email_sender_is_red(monkeypatch):
    row = pick_email(lambda r: r["id"] in SOURCE_TO_LAMBDA, "an alarmable sender")
    c = by_id(Harness(monkeypatch, healthy_platform().build(), alarms=[alarm_for_source(row["id"])]).body(), "email", row["id"])
    assert c["status"] == "red"
    assert "alarm firing" in c["comment"]


def test_a_never_sent_email_does_not_publish_a_fabricated_uptime_history(monkeypatch):
    """ADR-104 / #2220: a sender with no send log used to publish `uptime_90d = [1] * 90`
    — a perfect three-month delivery record built from zero records — plus a green dot
    and last_sync_relative='verified'."""
    row = _weekly_email()
    table = healthy_platform().clear(f"email_log#{row['id']}").build()
    c = by_id(Harness(monkeypatch, table).body(), "email", row["id"])
    assert set(c["uptime_90d"]) != {1}, f"{len(c['uptime_90d'])} green bars invented from no send log"
    assert c["status"] != "green"
    assert c["last_sync_relative"] == "never"


def test_a_weekly_email_that_missed_its_last_scheduled_run_is_not_green(monkeypatch):
    """#2221 (was a tranche-2 xfail): the recovery branch is bounded by the sender's own
    cadence (one week) instead of red_h, which had rewritten up to ~17 days of silence
    to "next run scheduled"."""
    row = _weekly_email()
    table = healthy_platform().clear(f"email_log#{row['id']}").add(f"email_log#{row['id']}", days_ago(10)).build()
    c = by_id(Harness(monkeypatch, table).body(), "email", row["id"])
    assert c["status"] != "green", f"a sender ten days silent on a weekly cadence published green: {c['comment']!r}"


def test_a_scheduled_sender_never_reports_the_idle_gray_state(monkeypatch):
    """#2221 — the finding was right, the prescribed repair was not.

    The tranche-2 marker read "the schedule-aware gray state is unreachable dead code"
    and asked for it to be made REACHABLE. It was indeed unreachable (`_sched_aware`
    only ran when status was neither green nor red, and every earlier branch had
    already forced one of those). But reaching it would have been a regression, not a
    fix: the only status that can now arrive at that point is the yellow a MISSED
    weekly slot produces (the test above), and `_sched_aware` would have repainted it
    "gray / next: Sun" on the six days a week that are not the send day — an honest
    signal turned into a shrug, the exact ADR-104 failure this endpoint exists to
    avoid. So the dead state was DELETED instead. A scheduled sender is fully described
    by green (inside its cadence, and the comment already names the next run), yellow
    (a whole cycle with no delivery) and red (past its threshold).

    This test is the ratchet on that decision: no age from 0 to 30 days may produce
    gray, and the helper may not come back.
    """
    # `_sched_aware` was a function LOCAL to status(), never a module attribute, so a
    # hasattr() check here would be vacuous — it would pass against the very code that
    # still has the helper. Read the source instead.
    assert "_sched_aware" not in _SRC, "the deleted idle-state helper is back in the module"
    row = _weekly_email()
    seen = set()
    for age in range(0, 31):
        sas._status_cache, sas._status_cache_ts = {}, 0
        table = healthy_platform().clear(f"email_log#{row['id']}").add(f"email_log#{row['id']}", days_ago(age)).build()
        seen.add(by_id(Harness(monkeypatch, table).body(), "email", row["id"])["status"])
    assert "gray" not in seen, f"the idle gray state is back and can mask a missed send: {sorted(seen)}"
    assert seen <= {"green", "yellow", "red"}, f"unexpected colour from a scheduled sender: {sorted(seen)}"


# ══════════════════════════════════════════════════════════════════════════════
# 10. Infrastructure
# ══════════════════════════════════════════════════════════════════════════════


def test_the_dead_letter_queue_depth_is_measured_and_published(monkeypatch):
    body = Harness(monkeypatch, healthy_platform().build(), dlq=0).body()
    dlq = by_id(body, "infrastructure", "dlq")
    assert dlq["status"] == "green"
    assert dlq["description"] == "0 messages"


def test_a_shallow_dead_letter_queue_is_yellow_and_a_deep_one_is_red(monkeypatch):
    shallow = by_id(Harness(monkeypatch, healthy_platform().build(), dlq=3).body(), "infrastructure", "dlq")
    sas._status_cache, sas._status_cache_ts = {}, 0
    deep = by_id(Harness(monkeypatch, healthy_platform().build(), dlq=42).body(), "infrastructure", "dlq")
    assert shallow["status"] == "yellow" and "3 messages" in shallow["comment"]
    assert deep["status"] == "red" and "42 messages" in deep["comment"]


def test_an_unreachable_queue_does_not_break_the_page(monkeypatch):
    h = Harness(monkeypatch, healthy_platform().build(), sqs_error=RuntimeError("AccessDenied"))
    assert h.status()["statusCode"] == 200
    assert by_id(h.body(), "infrastructure", "dlq")["status"] == "green"


def test_a_red_dead_letter_queue_reaches_the_traffic_light(monkeypatch):
    """#2220: the infrastructure panel was excluded from the rollup WHOLESALE, so
    ingestion actively dropping messages left the footer dot green."""
    body = Harness(monkeypatch, healthy_platform().build(), dlq=250).body()
    assert by_id(body, "infrastructure", "dlq")["status"] == "red", "sanity: the DLQ really is red"
    assert body["overall"] != "green"


def test_a_shallow_dead_letter_queue_does_not_move_the_traffic_light(monkeypatch):
    """Proportionality survives: a handful of retryable messages is yellow, and yellow
    has never driven the dot."""
    body = Harness(monkeypatch, healthy_platform().build(), dlq=3).body()
    assert by_id(body, "infrastructure", "dlq")["status"] == "yellow"
    assert body["overall"] == "green"


def test_the_published_mcp_tool_count_matches_the_registry(monkeypatch):
    """#2220: the panel published a hand-typed 'MCP server · 116 tools' while the
    registry held 76. The count now comes from PLATFORM_STATS, which
    `deploy/sync_doc_metadata.py --apply` rewrites from this same AST parse — the site-api
    bundle cannot import mcp/ at runtime (build_bundle stages only lambdas/), so
    PLATFORM_STATS is the seam, and this test is what keeps the seam honest."""
    import re

    registry = ast.parse((ROOT / "mcp" / "registry.py").read_text())
    tool_count = None
    for node in ast.walk(registry):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "TOOLS" for t in node.targets):
            tool_count = len(node.value.keys)
    assert tool_count, "mcp/registry.py no longer defines TOOLS as a dict literal"

    desc = by_id(Harness(monkeypatch, healthy_platform().build()).body(), "infrastructure", "mcp_server")["description"]
    published = re.search(r"(\d+)\s+tools", desc)
    assert published, f"the MCP row stopped publishing a tool count: {desc!r}"
    assert int(published.group(1)) == tool_count


# ══════════════════════════════════════════════════════════════════════════════
# 11. The rollup — one traffic light
# ══════════════════════════════════════════════════════════════════════════════


def _always_on_sources():
    """Sources whose staleness can actually redden them (not activity-excused)."""
    return [r for r in DATA_ROWS if r["category"] == "auto" and not r["activity_dep"] and r["field_check"] is None]


def test_a_healthy_platform_reports_a_green_traffic_light(monkeypatch):
    assert Harness(monkeypatch, healthy_platform().build()).body()["overall"] == "green"


def test_one_dead_pipeline_degrades_the_light_to_yellow_not_red(monkeypatch):
    """Proportional severity: one failure is degraded, not down."""
    dead = _always_on_sources()[0]
    body = Harness(monkeypatch, healthy_platform().clear(dead["id"]).build()).body()
    assert [c["status"] for c in all_pipeline_components(body)].count("red") == 1
    assert body["overall"] == "yellow"


def test_two_dead_pipelines_are_still_yellow(monkeypatch):
    always_on = _always_on_sources()
    assert len(always_on) >= 3, "this contract needs at least three always-on sources to distinguish the bands"
    b = healthy_platform()
    for row in always_on[:2]:
        b.clear(row["id"])
    body = Harness(monkeypatch, b.build()).body()
    assert [c["status"] for c in all_pipeline_components(body)].count("red") == 2
    assert body["overall"] == "yellow"


def test_three_dead_pipelines_turn_the_light_red(monkeypatch):
    always_on = _always_on_sources()
    assert len(always_on) >= 3
    b = healthy_platform()
    for row in always_on[:3]:
        b.clear(row["id"])
    body = Harness(monkeypatch, b.build()).body()
    assert [c["status"] for c in all_pipeline_components(body)].count("red") >= 3
    assert body["overall"] == "red"


def test_the_light_is_computed_only_from_red_components(monkeypatch):
    """Yellow components — an overdue lab, a source needing an auth check — are
    degradation, not outage, and must not flip the dot on their own."""
    yellow_target = _plain_source()  # non-lagged, so two days old really is yellow
    table = healthy_platform().clear(yellow_target["id"]).add(yellow_target["id"], days_ago(2)).build()
    body = Harness(monkeypatch, table).body()
    statuses = [c["status"] for c in all_pipeline_components(body)]
    assert "yellow" in statuses and "red" not in statuses
    assert body["overall"] == "green"


def test_never_imported_manual_and_onetime_components_never_drive_the_light(monkeypatch):
    """Blue is 'not applicable', and a platform whose optional imports are empty
    is not a platform that is down.

    The skip is a fixture correction, not a loosened assertion (#2220). `clear()` is
    PARTITION-level while the rows are field-level, so clearing the manual "Blood
    Pressure Data" row — which shares the `apple_health` partition with seven automated
    sub-feeds — also emptied all seven. That over-clear was invisible while an
    activity-dependent source with zero records was rewritten green; now those seven
    correctly report red, which is a different scenario from the one this test is about.
    Both assertions below are unchanged."""
    shared_with_auto = {r["id"] for r in DATA_ROWS if r["category"] == "auto"}
    b = healthy_platform()
    for row in DATA_ROWS:
        if row["category"] in ("manual", "onetime") and row["id"] not in shared_with_auto:
            b.clear(row["id"])
    body = Harness(monkeypatch, b.build()).body()
    blues = [c for c in components(body, "data_sources") if c["status"] == "blue"]
    assert blues, "sanity: the manual/one-time sources really did go blue"
    assert body["overall"] == "green"


def test_one_unparseable_sort_key_does_not_take_down_the_whole_status_page(monkeypatch):
    """#2221 (was a tranche-2 xfail, ADR-104): the strptime is guarded and reports the
    row as unreadable — non-green, never a pass, and never a 500 out of the handler.
    Correction to the marker: there were TWO unguarded call sites, not one — the manual
    (due-date) branch had the same shape and is guarded too."""
    row = _plain_source()
    table = healthy_platform().clear(row["id"]).add(row["id"], "latest").build()
    assert Harness(monkeypatch, table).status()["statusCode"] == 200


def test_a_total_dynamodb_outage_still_answers_two_hundred(monkeypatch):
    table = healthy_platform().build()
    table.error = RuntimeError("ResourceNotFoundException: table life-platform")
    h = Harness(monkeypatch, table)
    resp = h.status()
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert len(components(body, "data_sources")) == len(DATA_SOURCES)


def test_a_total_dynamodb_outage_is_visible_in_the_traffic_light(monkeypatch):
    """Fail-soft must not mean fail-silent: if nothing can be read, the page
    cannot claim the platform is healthy."""
    table = healthy_platform().build()
    table.error = RuntimeError("ResourceNotFoundException")
    body = Harness(monkeypatch, table).body()
    for row in _always_on_sources():
        assert by_name(body, "data_sources", row["name"])["status"] == "red"
    assert body["overall"] == "red"


# ══════════════════════════════════════════════════════════════════════════════
# 12. The cost block
# ══════════════════════════════════════════════════════════════════════════════


def test_the_governors_cost_block_is_republished_untouched(monkeypatch):
    """/api/status must not re-derive spend — #1909 was exactly that bug."""
    block = {"mtd": 12.5, "projected": 48.0, "budget": 85.0, "tier": 0, "status": "green", "pct_of_budget": 56}
    body = Harness(monkeypatch, healthy_platform().build(), cost=block).body()
    assert body["cost"] == block


def test_an_unavailable_cost_block_publishes_nothing_rather_than_a_guess(monkeypatch):
    """ADR-104: when the governor has stated no number, neither does the page."""
    body = Harness(monkeypatch, healthy_platform().build(), cost={}).body()
    assert body["cost"] == {}
    assert body["overall"] == "green", "a missing cost block is not a pipeline failure"


def test_the_cost_block_does_not_participate_in_the_traffic_light(monkeypatch):
    """Budget pressure is a spending signal, not a pipeline outage — the dot
    must not turn red because Bedrock spend is at tier 3."""
    block = {"mtd": 84.0, "projected": 120.0, "budget": 85.0, "tier": 3, "status": "red"}
    body = Harness(monkeypatch, healthy_platform().build(), cost=block).body()
    assert body["cost"]["status"] == "red"
    assert body["overall"] == "green"
