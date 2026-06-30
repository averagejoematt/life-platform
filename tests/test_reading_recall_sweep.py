"""tests/test_reading_recall_sweep.py — the daily recall sweep (Phase D)."""

from __future__ import annotations

import json
import os

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

import pytest  # noqa: E402
from reading import (
    reading_recall_sweep_lambda as sweep,  # noqa: E402
    reading_store as rs,  # noqa: E402
)
from reading_fakes import FakeTable  # noqa: E402


@pytest.fixture(autouse=True)
def wired(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(rs, "table", t)

    class _CW:
        def __init__(self):
            self.calls = []

        def put_metric_data(self, **kw):
            self.calls.append(kw)

    cw = _CW()
    monkeypatch.setattr(sweep, "_cw", cw)
    return t, cw


def test_sweep_writes_snapshot_and_metric(wired):
    table, cw = wired
    bid = rs.add_book({"title": "T", "author": "A"}, enricher=lambda m: {})
    rs.put_recall(bid, prompt_id="due", prompt="what stuck?", next_due="2026-06-01T00:00:00")  # past → due
    rs.put_recall(bid, prompt_id="future", prompt="later", next_due="2099-01-01T00:00:00")
    resp = sweep.lambda_handler({})
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200 and body["due_count"] == 1
    snap = table.store.get((sweep.NUDGE_PK, sweep.NUDGE_SK))
    assert snap and snap["dueCount"] == 1 and snap["prompts"][0]["promptId"] == "due"
    assert cw.calls and cw.calls[0]["MetricData"][0]["Value"] == 1.0


def test_sweep_empty_is_clean(wired):
    table, cw = wired
    resp = sweep.lambda_handler({})
    assert resp["statusCode"] == 200 and json.loads(resp["body"])["due_count"] == 0
    assert table.store[(sweep.NUDGE_PK, sweep.NUDGE_SK)]["dueCount"] == 0
