"""#6271 — the /api/ask watch block reads its whole 30-day window, every page.

`web.site_api_ai_context._recent_day_rows` read the trailing window of Apple Health day rows (oldest first) with ONE
`query`. A row there is up to ~90 KB, so the window passes DynamoDB's 1 MB page and the query returned only the oldest
days (measured live 2026-11-27: 21 of 30 rows, the page ending nine days before today). The watch signals are dated
and go stale, so the public Ask context lost every watch signal. The read now goes through `common.query_pages`.

The fake table pages on the BYTES READ, before the phase filter, as DynamoDB does. `_old_rows` is the read as it stood
before the fix (the first page only). Dates are literals; nothing here reads the clock.
"""

from __future__ import annotations

import copy
import json
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lambdas"))

from health import watch_signals  # noqa: E402
from web import site_api_ai_context as A  # noqa: E402
from web.site_api_common import USER_PREFIX  # noqa: E402

WINDOW_END = "2026-03-15"
PK = f"{USER_PREFIX}{watch_signals.APPLE}"


def _day(offset: int) -> str:
    return (date.fromisoformat(WINDOW_END) - timedelta(days=offset)).isoformat()


def _size(item: dict) -> int:
    return len(json.dumps(item, default=str))


class PagingTable:
    """Pages end where the BYTES READ would pass ``page_bytes`` (at least one item a page), before any filter.
    ``fail_page`` raises on that page."""

    def __init__(self, rows, page_bytes: int = 10**9, fail_page: int | None = None):
        self.rows = [json.loads(json.dumps(r, default=str), parse_float=Decimal) for r in rows]
        self.page_bytes, self.fail_page, self.calls = page_bytes, fail_page, 0

    def query(self, KeyConditionExpression=None, ScanIndexForward=True, ExclusiveStartKey=None, **_kw):
        self.calls += 1
        if self.fail_page == self.calls:
            raise RuntimeError("simulated page failure")
        expr = KeyConditionExpression.get_expression()
        pk_e, sk_e = (p.get_expression() for p in expr["values"])
        pk, lo, hi = pk_e["values"][1], sk_e["values"][1], sk_e["values"][2]
        items = sorted((r for r in self.rows if r["pk"] == pk and lo <= r["sk"] <= hi), key=lambda r: r["sk"], reverse=not ScanIndexForward)
        if ExclusiveStartKey:
            items = items[[r["sk"] for r in items].index(ExclusiveStartKey["sk"]) + 1 :]
        page, used = [], 0
        for r in items:
            if page and used + _size(r) > self.page_bytes:
                break
            page.append(r)
            used += _size(r)
        resp = {"Items": copy.deepcopy(page), "Count": len(page)}
        if len(page) < len(items):
            resp["LastEvaluatedKey"] = {"pk": page[-1]["pk"], "sk": page[-1]["sk"]}
        return resp


def _rows(n_days: int = 30, *, missing=()) -> list:
    """Synthetic Apple Health day rows: a padded blob stands in for the heavy per-day payload."""
    out = []
    for o in range(n_days + 5):  # five rows before the window, which must never be read
        if o in missing:
            continue
        d = _day(o)
        out.append({"pk": PK, "sk": f"DATE#{d}", "date": d, "resting_heart_rate": Decimal(50 + o % 7), "padding": "x" * 2000})
    out.append({"pk": f"{USER_PREFIX}other", "sk": f"DATE#{WINDOW_END}", "date": WINDOW_END})
    return out


def _read(table, monkeypatch) -> list:
    monkeypatch.setattr(A, "_table", lambda: table)
    return A._recent_day_rows(watch_signals.APPLE, watch_signals.ARC_DAYS, WINDOW_END)


def _old_rows(table, monkeypatch) -> list:
    """The read before #6271: one ``query``, its first page only."""
    with monkeypatch.context() as m:
        m.setattr(A, "query_pages", lambda tbl, **kw: tbl.query(**kw))
        return _read(table, monkeypatch)


def _dates(rows) -> list:
    return [r["sk"][5:] for r in rows]


def _window_bytes() -> int:
    return sum(_size(r) for r in _rows() if r["pk"] == PK and _day(watch_signals.ARC_DAYS - 1) <= r["date"] <= WINDOW_END)


def test_a_window_of_one_page_reads_the_same_rows_as_before(monkeypatch):
    t_old, t_new = PagingTable(_rows(), page_bytes=_window_bytes()), PagingTable(_rows(), page_bytes=_window_bytes())
    old, new = _old_rows(t_old, monkeypatch), _read(t_new, monkeypatch)
    assert json.dumps(old, sort_keys=True, default=str) == json.dumps(new, sort_keys=True, default=str)
    assert t_new.calls == 1 and len(new) == watch_signals.ARC_DAYS


def test_one_item_over_the_boundary_the_newest_day_was_lost_and_is_now_read(monkeypatch):
    limit = _window_bytes() - 1
    old = _old_rows(PagingTable(_rows(), page_bytes=limit), monkeypatch)
    new = _read(PagingTable(_rows(), page_bytes=limit), monkeypatch)
    assert WINDOW_END not in _dates(old)  # the defect: the newest day sat on the second page
    assert _dates(new) == _dates(_read(PagingTable(_rows()), monkeypatch))
    assert _dates(new)[-1] == WINDOW_END and _dates(new) == sorted(_dates(new))


def test_many_pages_keep_the_order_and_the_window(monkeypatch):
    t = PagingTable(_rows(missing={4}), page_bytes=5000)
    new = _read(t, monkeypatch)
    assert t.calls > 3
    assert _dates(new) == [_day(o) for o in range(watch_signals.ARC_DAYS - 1, -1, -1) if o != 4]


def test_a_failed_page_raises_so_the_block_is_dropped_not_served_partial(monkeypatch):
    """``_ask_fetch_context`` runs the watch block through ``_soft_block``: a raise omits the whole block (the existing
    shape for a failed read); a partial window is never served."""
    with pytest.raises(RuntimeError):
        _read(PagingTable(_rows(), page_bytes=5000, fail_page=2), monkeypatch)
    ctx: dict = {}

    def block() -> None:
        ctx["watch"] = _read(PagingTable(_rows(), page_bytes=5000, fail_page=2), monkeypatch)

    A._soft_block("watch", block)
    assert "watch" not in ctx


def test_an_empty_window(monkeypatch):
    assert _read(PagingTable([]), monkeypatch) == []
