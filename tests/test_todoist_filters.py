"""
tests/test_todoist_filters.py — #478 / ADR-122.

Locks the three fixes:
  1. Ingestion `get_filtered_tasks` hits the server-side filter endpoint
     (/tasks/filter?query=...), NOT /tasks?filter=... which the v1 API ignores.
  2. Ingestion `get_active_tasks` follows next_cursor (paginates past 200).
  3. MCP `_list_all_tasks` routes a filter to /tasks/filter?query=..., and the
     unfiltered call still uses /tasks.
  4. The decision-fatigue detector measures pressing load (overdue + due_today),
     not active + overdue — so a large active backlog no longer inflates the signal.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "compute"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas", "ingestion"))

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("DYNAMODB_TABLE", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")

import todoist_lambda as tl  # noqa: E402

# ── 1 & 2: ingestion endpoint + pagination ─────────────────────────────────────


class _FakeApi:
    """Records (path, params) calls and replays scripted paged responses keyed by path."""

    def __init__(self, pages_by_path):
        self.pages_by_path = pages_by_path  # {path: [page_dict, ...]}
        self.calls = []

    def __call__(self, path, api_token, params=None):
        self.calls.append((path, dict(params or {})))
        pages = self.pages_by_path.get(path, [{"results": []}])
        # Serve pages in order per path, driven by the cursor param.
        cursor = (params or {}).get("cursor")
        idx = 0 if cursor is None else int(cursor)
        return pages[idx] if idx < len(pages) else {"results": []}


def test_get_filtered_tasks_uses_filter_endpoint_with_query_param(monkeypatch):
    fake = _FakeApi({"/tasks/filter": [{"results": [{"id": "1"}, {"id": "2"}], "next_cursor": None}]})
    monkeypatch.setattr(tl, "api_get", fake)

    tasks = tl.get_filtered_tasks("tok", "overdue")

    assert len(tasks) == 2
    path, params = fake.calls[0]
    assert path == "/tasks/filter", "must use the server-side filter endpoint, not /tasks"
    assert params.get("query") == "overdue", "filter string goes in `query`, not `filter`"
    assert "filter" not in params, "the ignored /tasks `filter` param must not be sent"


def test_get_filtered_tasks_paginates(monkeypatch):
    fake = _FakeApi(
        {
            "/tasks/filter": [
                {"results": [{"id": "a"}], "next_cursor": "1"},
                {"results": [{"id": "b"}], "next_cursor": None},
            ]
        }
    )
    monkeypatch.setattr(tl, "api_get", fake)
    tasks = tl.get_filtered_tasks("tok", "overdue")
    assert [t["id"] for t in tasks] == ["a", "b"]
    assert len(fake.calls) == 2  # followed the cursor to page 2


def test_get_active_tasks_paginates_past_page_cap(monkeypatch):
    # Two full pages then a short page — the old single-page fetch truncated at 200.
    fake = _FakeApi(
        {
            "/tasks": [
                {"results": [{"id": str(i)} for i in range(200)], "next_cursor": "1"},
                {"results": [{"id": str(200 + i)} for i in range(70)], "next_cursor": None},
            ]
        }
    )
    monkeypatch.setattr(tl, "api_get", fake)
    tasks = tl.get_active_tasks("tok")
    assert len(tasks) == 270, "must follow next_cursor rather than stop at the 200 page-cap"
    # /tasks fetched without a filter/query param
    assert all("filter" not in p and "query" not in p for _, p in fake.calls)


# ── 3: MCP tool routing ─────────────────────────────────────────────────────────


def test_mcp_list_all_tasks_routes_filter_to_filter_endpoint(monkeypatch):
    import mcp.tools_todoist as tt

    calls = []

    def fake_request(method, path, payload=None):
        calls.append(path)
        return {"results": [{"id": "1"}], "next_cursor": None}

    monkeypatch.setattr(tt, "_todoist_request", fake_request)

    tt._list_all_tasks("today")
    assert calls[0].startswith("/tasks/filter?"), "filter query must hit /tasks/filter"
    assert "query=today" in calls[0]
    assert "filter=today" not in calls[0]

    calls.clear()
    tt._list_all_tasks()  # unfiltered
    assert calls[0].startswith("/tasks?"), "unfiltered list still uses /tasks"
    assert "query=" not in calls[0] and "filter=" not in calls[0]


# ── 4: decision-fatigue measures pressing load, not the backlog ─────────────────


import daily_insight_compute_lambda as di  # noqa: E402


class _FakeTable:
    def __init__(self, todoist_item):
        self._item = todoist_item

    def query(self, **kwargs):
        return {"Items": [self._item]}


def _run_fatigue(monkeypatch, *, active, overdue, due_today, habit_pct):
    monkeypatch.setattr(
        di,
        "table",
        _FakeTable({"active_count": active, "overdue_count": overdue, "due_today_count": due_today}),
    )
    # 7 days of habit records at a fixed T0 completion rate.
    habit_7d = [{"tier0_pct": habit_pct} for _ in range(7)]
    return di._compute_decision_fatigue_alert("2026-07-05", habit_7d)


def test_large_active_backlog_does_not_fire_fatigue(monkeypatch):
    # The failure this fixes: a huge active backlog used to force the load
    # condition true every day. With a clear pressing pile it must stay silent
    # even when habits are poor.
    fired, alert = _run_fatigue(monkeypatch, active=270, overdue=2, due_today=1, habit_pct=0.30)
    assert fired is False, "active backlog must not inflate the pressing-load signal"
    assert alert == ""


def test_high_pressing_load_plus_bad_habits_fires(monkeypatch):
    fired, alert = _run_fatigue(monkeypatch, active=270, overdue=184, due_today=0, habit_pct=0.30)
    assert fired is True
    assert "184 overdue" in alert and "due today" in alert
    assert "active+overdue" not in alert  # old framing gone


def test_high_pressing_load_but_good_habits_does_not_fire(monkeypatch):
    fired, _ = _run_fatigue(monkeypatch, active=270, overdue=184, due_today=0, habit_pct=0.90)
    assert fired is False, "load alone must not fire without the habit slippage"
