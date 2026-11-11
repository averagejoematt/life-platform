"""tests/test_public_brief_schedule.py — the public-safe brief's Monday run is wired (owner ruling 2026-11-09, third, E).

The schedule row, the CDK schedule that carries the ``{"mode": "public_brief"}`` input to ``coach-history-summarizer``,
and the handler's dispatch must agree; the weekly compression run must not reach the brief.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

KEY = "coach-history-summarizer#PublicBrief"


def test_the_schedule_row_runs_monday_morning_on_the_summarizer():
    row = json.load(open(os.path.join(_REPO, "config", "schedules.json")))["schedules"][KEY]
    assert row["function"] == "coach-history-summarizer" and row["stack"] == "LifePlatformCompute"
    assert row["expression"] == "cron(0 9 ? * MON *)"


def test_the_cdk_schedule_carries_the_mode():
    src = open(os.path.join(_REPO, "cdk", "stacks", "compute_stack.py")).read()
    assert f'table_schedule("{KEY}")' in src
    assert 'schedule_input={"mode": "public_brief"}' in src


def test_the_handler_dispatches_the_mode_and_only_the_mode(monkeypatch):
    from coach import coach_history_summarizer as CHS, public_brief

    seen = []
    monkeypatch.setattr(public_brief, "run", lambda table, **kw: seen.append(kw) or {"status": "ok"})
    assert CHS.lambda_handler({"mode": "public_brief", "dry_run": True}, None) == {"status": "ok"}
    assert seen == [{"coach_ids": None, "persist": False}]
    monkeypatch.setattr(CHS, "ALL_COACH_IDS", [])
    CHS.lambda_handler({"coach_ids": []}, None)  # the Sunday compression run
    assert len(seen) == 1
