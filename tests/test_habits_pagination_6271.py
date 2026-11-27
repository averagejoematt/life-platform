"""#6271 — `/api/habits` reads its whole Habitify window, every page.

The route read its Habitify window (oldest first) with ONE `table.query`. A Habitify row is ~14 KB, so the window passes
DynamoDB's 1 MB page and the query silently returned only the oldest rows: the newest days of the heatmap, the dot strip
and the per-habit adherence were missing (measured live 2026-11-27: the first page ended a week before today). The read
now goes through `common.query_pages`.

These tests run the handler on a fake table that pages on the BYTES READ, before the filter and any projection, as
DynamoDB does. `_old_habits` is the handler as it stood before the fix: the same code with the Habitify read limited to
its first page. The clock is pinned; no date is computed at import.
"""

from __future__ import annotations

import copy
import json
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lambdas"))

from common import (
    activity_publication as AP,  # noqa: E402
    restraint_publication as RP,  # noqa: E402
)
from common.query_pages import query_pages as _real_query_pages  # noqa: E402
from experiment import phase_filter  # noqa: E402
from web import site_api_habits as H  # noqa: E402
from web.site_api_common import USER_ID, USER_PREFIX  # noqa: E402

U = f"USER#{USER_ID}"
HAB = f"{USER_PREFIX}habitify"
TODAY = "2026-03-15"
INSTANT = datetime(2026, 3, 15, 19, 0, tzinfo=timezone.utc)  # noon Pacific on TODAY
CURRENT_PHASE = phase_filter.PHASE_FILTER_VALUES[":phase_experiment"]
RESTRAINT_GROUP = sorted(RP.RESTRAINT_GROUPS)[0]
JOURNAL_ID = sorted(h for h, fam in AP.HABIT_FAMILIES.items() if fam[1] == "journal_presence")[0]
ORDINARY = ("habit_a", "habit_b", "habit_c")


def _day(offset: int) -> str:
    return (date.fromisoformat(TODAY) - timedelta(days=offset)).isoformat()


def _size(item: dict) -> int:
    return len(json.dumps(item, default=str))


class PagingTable:
    """Habitify query pages end where the BYTES READ would pass ``page_bytes`` (at least one item a page), before the
    filter and any projection, as DynamoDB's 1 MB page does. ``fail_page`` raises on that Habitify page. The route's
    other partitions are served whole: measured live, each fits one page for this window (the PR body has the sizes)."""

    def __init__(self, rows, page_bytes: int = 10**9, fail_page: int | None = None):
        self.rows = [json.loads(json.dumps(r, default=str), parse_float=Decimal) for r in rows]
        self.page_bytes = page_bytes
        self.fail_page = fail_page
        self.pages: dict = {}

    def get_item(self, Key=None, **_kw):  # noqa: N803 — boto3's spelling
        for r in self.rows:
            if r["pk"] == Key["pk"] and r["sk"] == Key["sk"]:
                return {"Item": copy.deepcopy(r)}
        return {}

    def query(self, KeyConditionExpression=None, ScanIndexForward=True, Limit=None, ExclusiveStartKey=None, **kw):
        expr = KeyConditionExpression.get_expression()
        parts = expr["values"] if expr["operator"] == "AND" else [KeyConditionExpression]
        pk, lo, hi = None, "", "￿"
        for p in parts:
            e = p.get_expression()
            if e["values"][0].name == "pk":
                pk = e["values"][1]
            elif e["operator"] == "=":
                lo = hi = e["values"][1]
            else:
                lo, hi = e["values"][1], e["values"][2]
        n = self.pages[pk] = self.pages.get(pk, 0) + 1
        if pk == HAB and self.fail_page == n:
            raise RuntimeError("simulated page failure")
        items = sorted((r for r in self.rows if r["pk"] == pk and lo <= r["sk"] <= hi), key=lambda r: r["sk"], reverse=not ScanIndexForward)
        if ExclusiveStartKey:
            sks = [r["sk"] for r in items]
            items = items[sks.index(ExclusiveStartKey["sk"]) + 1 :]
        cap = self.page_bytes if pk == HAB else 10**12
        page, used = [], 0
        for r in items:
            if page and used + _size(r) > cap:
                break
            if Limit and len(page) >= int(Limit):
                break
            page.append(r)
            used += _size(r)
        more = len(page) < len(items)
        last = page[-1] if page else None
        if "#phase" in str(kw.get("FilterExpression") or ""):
            page = [r for r in page if r.get("phase") in (None, CURRENT_PHASE)]
        resp = {"Items": copy.deepcopy(page), "Count": len(page)}
        if more and last:
            resp["LastEvaluatedKey"] = {"pk": last["pk"], "sk": last["sk"]}
        return resp


def _status(done: bool, group: str = "Core", hid: str = "") -> dict:
    st = {"status": "completed" if done else "not_completed", "scheduled_today": True, "group": group, "periodicity": "daily"}
    st.update({"current_value": Decimal(1), "notes": "synthetic private note", "aliases": ["synthetic alias"]})
    if hid:
        st["habit_id"] = hid
    return st


def _registry() -> dict:
    reg = {n: {"tier": 0, "publication": "public", "group": "Core"} for n in ORDINARY}
    reg["restraint_a"] = {"tier": 0, "publication": "public", RP.REGISTRY_FLAG: True}
    reg["journal_a"] = {"tier": 0, "habitify_id": JOURNAL_ID}
    return reg


def _statuses(offset: int, *, restraint_done: bool = True, journal_done: bool = True) -> dict:
    st = {n: _status((offset + i) % 3 != 0) for i, n in enumerate(ORDINARY)}
    st["restraint_a"] = _status(restraint_done, group=RESTRAINT_GROUP)
    st["restraint_b"] = _status(restraint_done, group=RESTRAINT_GROUP.title())  # its tracker group alone
    st["journal_a"] = _status(journal_done, hid=JOURNAL_ID)
    return st


def _rows(n_days: int = 40, *, missing=(), statuses=None) -> list:
    rows = [{"pk": U, "sk": "PROFILE#v1", "habit_registry": _registry()}]
    for o in range(n_days):
        d = _day(o)
        rows.append(
            {"pk": f"{USER_PREFIX}habit_scores", "sk": f"DATE#{d}", "date": d, "phase": CURRENT_PHASE, "tier0_done": 2, "tier0_total": 3}
        )
        if o in missing:
            continue
        st = (statuses or _statuses)(o)
        rows.append(
            {
                "pk": HAB,
                "sk": f"DATE#{d}",
                "date": d,
                "phase": CURRENT_PHASE,
                "habit_statuses": st,
                "by_group": {"Core": Decimal(60)},
                "habits": ["synthetic roll-up"],
            }
        )
    return rows


def _window_bytes(table: PagingTable) -> list:
    start = _day(89)
    return [_size(r) for r in sorted(table.rows, key=lambda r: r["sk"]) if r["pk"] == HAB and start <= r["sk"][5:] <= TODAY]


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return INSTANT if tz is None else INSTANT.astimezone(tz)

    monkeypatch.setattr(H, "datetime", _Frozen)


def _g(table) -> dict:
    return {"table": table, "_experiment_date": lambda n: _day(n - 1)}


def _body(resp: dict) -> dict:
    body = json.loads(resp["body"])
    body.pop("_meta", None)
    return {"status": resp["statusCode"], "body": body}


def _new(table) -> dict:
    return _body(H.habits(_g=_g(table)))


def _old(table, monkeypatch) -> dict:
    """The handler before #6271: its Habitify window read was one ``table.query`` (the first page only)."""

    def first_page_for_habitify(tbl, **kw):
        if kw["KeyConditionExpression"].get_expression()["values"][0].get_expression()["values"][1] == HAB:
            return tbl.query(**kw)
        return _real_query_pages(tbl, **kw)

    with monkeypatch.context() as m:
        m.setattr(H, "query_pages", first_page_for_habitify)
        return _body(H.habits(_g=_g(table)))


def _strip(body: dict, day: str) -> set:
    return {d["status"] for p in body["body"]["per_habit"] for d in p["days"] if d["date"] == day}


# ── the page boundary ────────────────────────────────────────────────────────────────────────────────


def test_a_window_of_exactly_one_page_is_byte_identical_to_the_old_route(monkeypatch):
    probe = PagingTable(_rows())
    t_old, t_new = PagingTable(_rows(), page_bytes=sum(_window_bytes(probe))), PagingTable(_rows(), page_bytes=sum(_window_bytes(probe)))
    old, new = _old(t_old, monkeypatch), _new(t_new)
    assert t_new.pages[HAB] == 1
    assert json.dumps(old, sort_keys=True) == json.dumps(new, sort_keys=True)


def test_one_item_over_the_boundary_the_newest_day_was_lost_and_is_now_served(monkeypatch):
    probe = PagingTable(_rows())
    limit = sum(_window_bytes(probe)) - 1
    old, new = _old(PagingTable(_rows(), page_bytes=limit), monkeypatch), _new(PagingTable(_rows(), page_bytes=limit))
    full = _new(PagingTable(_rows()))
    assert _strip(old, TODAY) == {"absent"}  # the defect: the newest day sat on the second page
    assert _strip(new, TODAY) <= {"done", "missed"} and _strip(new, TODAY)
    assert new == full
    assert old != new


@pytest.mark.parametrize("pages", [2, 3, 7])
def test_many_pages_give_the_one_page_answer_in_the_same_order(pages):
    probe = PagingTable(_rows())
    limit = sum(_window_bytes(probe)) // pages + 1
    t = PagingTable(_rows(), page_bytes=limit)
    new = _new(t)
    assert t.pages[HAB] >= pages
    assert new == _new(PagingTable(_rows()))
    hist = [d["date"] for d in new["body"]["history"]]
    assert hist == sorted(hist) and hist[-1] == TODAY
    for p in new["body"]["per_habit"]:
        strip = [d["date"] for d in p["days"]]
        assert strip == sorted(strip) and strip[-1] == TODAY


def test_a_missing_day_in_the_middle_stays_absent_on_every_page_size():
    rows = _rows(missing={12})
    small = _new(PagingTable(rows, page_bytes=3000))
    assert small == _new(PagingTable(rows))
    assert _strip(small, _day(12)) == {"absent"}
    assert _strip(small, _day(11)) <= {"done", "missed"}


def test_an_empty_window(monkeypatch):
    rows = [r for r in _rows() if r["pk"] != HAB]
    old, new = _old(PagingTable(rows, page_bytes=3000), monkeypatch), _new(PagingTable(rows, page_bytes=3000))
    assert old == new and new["status"] == 200
    assert all(d["status"] == "absent" for p in new["body"]["per_habit"] for d in p["days"])


def test_a_failed_page_mid_window_raises_and_serves_no_partial_window():
    """The route has no partial answer: the page failure propagates, and ``site_api_lambda.lambda_handler`` turns any
    handler exception into its 500 error shape."""
    t = PagingTable(_rows(), page_bytes=3000, fail_page=2)
    with pytest.raises(RuntimeError):
        H.habits(_g=_g(t))


def test_the_schema_is_unchanged():
    one, many = _new(PagingTable(_rows())), _new(PagingTable(_rows(), page_bytes=3000))

    def shape(node):
        if isinstance(node, dict):
            return {k: shape(v) for k, v in node.items()}
        if isinstance(node, list):
            return [shape(node[0])] if node else []
        return type(node).__name__

    assert shape(one) == shape(many)


# ── privacy on the newly visible days ────────────────────────────────────────────────────────────────


def test_newly_visible_days_go_through_the_same_public_predicate():
    """A restraint habit (registry flag, or its tracker group alone) and the private journal, on days that only a
    later page holds: no name reaches the body, and kept vs missed moves nothing."""

    def statuses(done: bool):
        return lambda o: _statuses(o, restraint_done=done if o < 10 else True, journal_done=done if o < 10 else True)

    kept = _new(PagingTable(_rows(statuses=statuses(True)), page_bytes=3000))
    missed = _new(PagingTable(_rows(statuses=statuses(False)), page_bytes=3000))
    assert kept == missed
    blob = json.dumps(kept).lower()
    for name in ("restraint_a", "restraint_b", "journal_a", "synthetic private note", "synthetic alias"):
        assert name not in blob
    assert {p["name"] for p in kept["body"]["per_habit"]} == set(ORDINARY)
    # control: an ordinary habit missed on those same days does move the body
    ordinary_missed = _new(
        PagingTable(_rows(statuses=lambda o: {**_statuses(o), "habit_a": _status(False)} if o < 10 else _statuses(o)), page_bytes=3000)
    )
    assert ordinary_missed != kept
