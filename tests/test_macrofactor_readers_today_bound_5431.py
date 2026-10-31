"""#5431 box 2: every reader of the MacroFactor intake partition is bounded at the Pacific today.

MacroFactor's export carries projected values for days that have not happened. The writer no longer stores them
(`_is_future`, boxes 1/4) and the owner deleted the two that existed (box 3) — but a reader must not depend on
the writer: a stored future-dated row reads as intake. This file plants a future-dated row in a fake table and
asserts each reader, range and "latest" alike, ignores it, and that a window wholly in the future reads nothing.

The clock is pinned (a fixed Pacific day) so nothing here reaches the live clock. Every value is synthetic.
Mutation control (run once, recorded in the PR): removing the `intake_window` / `latest_day_condition` call from
any one reader reds that reader's test and the AST census below.
"""

import ast
import importlib
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in (ROOT, os.path.join(ROOT, "lambdas")):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "test@example.com")

from common import macrofactor_fields as mff  # noqa: E402

TODAY = "2026-10-30"
PAST = "2026-10-29"
FUTURE = "2026-10-31"
FUTURE2 = "2026-11-01"
PK = "USER#matthew#SOURCE#macrofactor"


def _row(day, kcal):
    return {"pk": PK, "sk": f"DATE#{day}", "date": day, "source": "macrofactor", "total_calories_kcal": kcal, "total_protein_g": 150}


ROWS = [_row("2026-10-28", 1900), _row(PAST, 2000), _row(TODAY, 2100), _row(FUTURE, 2650), _row(FUTURE2, 2650)]


class FakeTable:
    """Evaluates the key conditions the readers mint — string expressions and boto3 `Key` objects alike —
    over a list of rows, honouring ScanIndexForward and Limit. Filter/projection expressions are not applied
    (the planted rows carry no `phase`, so the ADR-058 filter passes them either way)."""

    def __init__(self, rows):
        self.rows = [dict(r) for r in rows]
        self.calls = []

    @staticmethod
    def _bounds(kw):
        kce = kw["KeyConditionExpression"]
        if isinstance(kce, str):
            v = kw["ExpressionAttributeValues"]
            if "BETWEEN" in kce:
                return v.get(":s", v.get(":lo", v.get(":pfx"))), v.get(":e", v.get(":hi"))
            if "begins_with" in kce:
                return v[":pfx"], v[":pfx"] + "￿"
            return "", "￿"
        lo, hi = "", "￿"
        stack = [kce]
        while stack:
            c = stack.pop().get_expression()
            op, vals = c["operator"], c["values"]
            if op == "AND":
                stack.extend(vals)
            elif op == "BETWEEN":
                lo, hi = vals[1], vals[2]
            elif op == "begins_with":
                lo, hi = vals[1], vals[1] + "￿"
        return lo, hi

    def query(self, **kw):
        self.calls.append(kw)
        lo, hi = self._bounds(kw)
        items = [dict(r) for r in sorted(self.rows, key=lambda r: r["sk"]) if lo <= r["sk"] <= hi]
        if kw.get("ScanIndexForward") is False:
            items.reverse()
        if kw.get("Limit"):
            items = items[: kw["Limit"]]
        return {"Items": items}


@pytest.fixture(autouse=True)
def pinned_day(monkeypatch):
    """Pin the Pacific day in the clock module AND in every already-imported module that bound
    `pacific_today` by name at import (suite order decides which those are — the test must not)."""
    import common.pacific_time as pt

    original = pt.pacific_today
    pinned = lambda: TODAY  # noqa: E731
    monkeypatch.setattr(pt, "pacific_today", pinned)
    for mod in list(sys.modules.values()):
        for attr in ("pacific_today", "_pacific_today_5431"):
            if getattr(mod, attr, None) is original:
                monkeypatch.setattr(mod, attr, pinned)


def _days(result):
    if isinstance(result, dict):
        return sorted(result)
    return sorted({str(r.get("date") or r.get("sk", "")[5:15]) for r in result})


def _assert_no_future(days):
    assert days, "the reader returned nothing — the fixture, not the bound, is under test"
    assert all(d <= TODAY for d in days), f"a future day reached the reader: {days}"


# ── the shared helper ──────────────────────────────────────────────────────────────────────────


def test_intake_window_clamps_end_and_empties_a_future_window():
    assert mff.intake_window("macrofactor", "2026-10-01", "2026-12-31") == ("2026-10-01", TODAY)
    assert mff.intake_window("macrofactor", FUTURE, "2026-12-31") is None
    assert mff.intake_window("macrofactor", "2026-10-01", TODAY) == ("2026-10-01", TODAY)  # today is NOT future
    assert mff.intake_window("whoop", "2026-10-01", "2026-12-31") == ("2026-10-01", "2026-12-31")  # other sources untouched


def test_latest_sk_ceiling_only_for_intake():
    assert mff.latest_sk_ceiling("macrofactor") == f"DATE#{TODAY}"
    assert mff.latest_sk_ceiling("withings") is None


# ── range readers: (module, how to call) ────────────────────────────────────────────────────────


def _with_module_table(monkeypatch, modname, fn):
    mod = importlib.import_module(modname)
    t = FakeTable(ROWS)
    monkeypatch.setattr(mod, "table", t)
    return getattr(mod, fn), t


MODULE_TABLE_RANGE_READERS = [
    ("emails.daily_brief_lambda", "fetch_range"),
    ("emails.monthly_digest_lambda", "fetch_range"),
    ("emails.anomaly_detector_lambda", "fetch_range"),
    ("compute.daily_insight_compute_lambda", "fetch_range"),
    ("compute.dashboard_refresh_lambda", "fetch_range"),
    ("emails.monday_compass_lambda", "query_source"),
    ("intelligence.ai_expert_analyzer_lambda", "_query_source"),
    ("intelligence.field_notes_lambda", "_query_source"),
]


@pytest.mark.parametrize("modname,fn", MODULE_TABLE_RANGE_READERS)
def test_module_range_reader_ignores_future_rows(monkeypatch, modname, fn):
    reader, _ = _with_module_table(monkeypatch, modname, fn)
    _assert_no_future(_days(reader("macrofactor", "2026-10-20", "2026-11-30")))
    assert _days(reader("macrofactor", FUTURE, "2026-11-30")) == []  # wholly future: nothing, no inverted BETWEEN


def test_digest_utils_range_readers_ignore_future_rows():
    from common import digest_utils

    t = FakeTable(ROWS)
    _assert_no_future(_days(digest_utils.query_range(t, "macrofactor", "2026-10-20", "2026-11-30")))
    _assert_no_future(_days(digest_utils.query_range_list(t, "macrofactor", "2026-10-20", "2026-11-30")))
    assert digest_utils.query_range(t, "macrofactor", FUTURE, "2026-11-30") == {}
    assert digest_utils.query_range_list(t, "macrofactor", FUTURE, "2026-11-30") == []


def test_table_argument_range_readers_ignore_future_rows():
    from coach import coach_domain_facts
    from content import recap_data

    t = FakeTable(ROWS)
    _assert_no_future(_days(coach_domain_facts._query_source(t, "macrofactor", "2026-10-20", "2026-11-30")))
    _assert_no_future(_days(recap_data._query_range(t, "macrofactor", "2026-10-20", "2026-11-30")))
    assert coach_domain_facts._query_source(t, "macrofactor", FUTURE, "2026-11-30") == []
    assert recap_data._query_range(t, "macrofactor", FUTURE, "2026-11-30") == []


def test_other_sources_are_not_clamped(monkeypatch):
    from common import digest_utils

    t = FakeTable([dict(r, pk="USER#matthew#SOURCE#withings") for r in ROWS])
    assert FUTURE in _days(digest_utils.query_range(t, "withings", "2026-10-20", "2026-11-30"))


# ── "latest" readers ────────────────────────────────────────────────────────────────────────────


def test_latest_readers_skip_future_rows(monkeypatch):
    from common import input_manifest
    from operational import continuity_watch

    t = FakeTable(ROWS)
    assert input_manifest.latest_source_day(t, "macrofactor", user_id="matthew") == TODAY
    assert continuity_watch._last_partition_day(t, "matthew", "macrofactor") == ("ok", TODAY)

    mod = importlib.import_module("operational.coherence_sentinel_lambda")
    monkeypatch.setattr(mod, "table", FakeTable(ROWS))
    assert mod._latest("macrofactor")["date"] == TODAY

    ai = importlib.import_module("intelligence.ai_expert_analyzer_lambda")
    monkeypatch.setattr(ai, "table", FakeTable(ROWS))
    assert ai._latest_item("macrofactor")["date"] == TODAY


def test_mcp_get_latest_and_data_availability_skip_future_rows(monkeypatch):
    from mcp import tools_data

    monkeypatch.setattr(tools_data, "table", FakeTable([dict(r) for r in ROWS]))
    monkeypatch.setattr(tools_data, "pacific_today", lambda: TODAY)
    out = tools_data._get_latest({"sources": ["macrofactor"]})
    assert out["macrofactor"]["date"] == TODAY


def test_mcp_core_query_source_still_ignores_future_rows(monkeypatch):
    from mcp import core

    monkeypatch.setattr(core, "table", FakeTable(ROWS))
    monkeypatch.setattr(core, "pacific_today", lambda: TODAY)
    _assert_no_future(_days(core.query_source("macrofactor", "2026-10-20", "2026-11-30")))


# ── the set: every reader named in the PR carries the bound (AST census) ──────────────────────

BOUNDED = {
    "lambdas/common/digest_utils.py": ["query_range", "query_range_list"],
    "lambdas/emails/daily_brief_lambda.py": ["fetch_range"],
    "lambdas/emails/monthly_digest_lambda.py": ["fetch_range"],
    "lambdas/emails/anomaly_detector_lambda.py": ["fetch_range"],
    "lambdas/compute/daily_insight_compute_lambda.py": ["fetch_range"],
    "lambdas/compute/dashboard_refresh_lambda.py": ["fetch_range"],
    "lambdas/emails/monday_compass_lambda.py": ["query_source"],
    "lambdas/intelligence/ai_expert_analyzer_lambda.py": ["_query_source", "_latest_item"],
    "lambdas/intelligence/field_notes_lambda.py": ["_query_source"],
    "lambdas/coach/coach_domain_facts.py": ["_query_source"],
    "lambdas/content/recap_data.py": ["_query_range"],
    "lambdas/health/milestone_ledger.py": ["_range"],
    "lambdas/common/input_manifest.py": ["latest_source_day"],
    "lambdas/operational/coherence_sentinel_lambda.py": ["_latest"],
    "lambdas/operational/continuity_watch.py": ["_day_key_condition"],
    "lambdas/emails/freshness_checker_lambda.py": ["lambda_handler"],
    "lambdas/web/site_api_status.py": ["_last_sync"],
    "lambdas/web/site_api_pulse.py": ["_workout_evidence"],
    "mcp/tools_data.py": ["_get_latest", "_get_daily_summary", "tool_get_sources"],
    "mcp/tools_labs.py": ["tool_get_freshness_status"],
    "mcp/core.py": ["query_source"],
    "lambdas/web/site_api_common.py": ["_query_source", "_latest_item", "_latest_item_asof"],
}
_MARKERS = ("intake_window", "latest_day_condition", "latest_sk_ceiling", "_NO_FUTURE_SOURCES", "_pacific_today_5431", "pacific_today")


def _functions(path):
    tree = ast.parse(open(os.path.join(ROOT, path)).read())
    return {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


@pytest.mark.parametrize("path", sorted(BOUNDED))
def test_every_named_reader_carries_the_today_bound(path):
    fns = _functions(path)
    missing = []
    for name in BOUNDED[path]:
        if name not in fns:
            missing.append(f"{name} (not found — rename it in BOUNDED)")
            continue
        src = ast.unparse(fns[name])
        if not any(m in src for m in _MARKERS):
            missing.append(name)
    assert not missing, f"{path}: readers without the #5431 today-bound: {missing}"


def test_site_api_latest_readers_skip_future_rows(monkeypatch):
    import web.site_api_common as common

    monkeypatch.setattr(common, "table", FakeTable(ROWS))
    monkeypatch.setattr(common, "_pacific_today_5431", lambda: TODAY)
    assert common._latest_item("macrofactor")["date"] == TODAY
    assert common._latest_item_asof("macrofactor", "2026-12-31")["date"] == TODAY
