"""tests/test_coaching_dashboard_data_phase_3519.py — #3519 (AIQ-8): `data_phase`
on /api/coaching-dashboard used to be a hand-typed constant (`"established"`,
the ONLY assignment) — live on Day 0 every coach carried it, including three
whose drafts were HELD by the coach-quality-gate and served `analysis_generated_at
== ""`. An ADR-104 mislabel: a constant masquerading as a derived phase.

`data_phase` is now derived from the SAME shared phase context every other
narrative surface grounds on (`ai.ai_context.build_experiment_phase_context`,
#1086) — pre-start genesis -> "pre_start"; inside the cannot-exist-yet window
(`early_phase`, <=14 days in) -> "early"; otherwise -> "established". A
pre-start date must never serve "established".

Offline: no AWS, no SSM — the fake table serves nothing and every inner read
falls through its own try/except to the shaped-empty branches (mirrors
test_coaching_dashboard_paused_1971.py's harness).
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

from ai import (
    ai_context,  # noqa: E402
    budget_guard,  # noqa: E402
)
from fakes import FakeDdbTable  # noqa: E402
from web import site_api_lambda as L  # noqa: E402

_EVENT = {"rawPath": "/api/coaching-dashboard", "requestContext": {"http": {"method": "GET"}}}


def _dashboard_body(monkeypatch):
    monkeypatch.setattr(L, "table", FakeDdbTable())
    monkeypatch.setattr(L, "_integrator_digest", lambda: None)
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    resp = L.lambda_handler(dict(_EVENT), None)
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


def test_pre_start_date_never_serves_established(monkeypatch):
    monkeypatch.setattr(ai_context, "EXPERIMENT_START_DATE", "2099-01-01")
    body = _dashboard_body(monkeypatch)
    phases = {c["data_phase"] for c in body["coaches"]}
    assert phases, "expected at least one coach"
    assert "established" not in phases
    assert phases == {"pre_start"}


def test_genesis_day_is_early_not_established(monkeypatch):
    # Genesis == today: days_in == 1, inside the 14-day early-phase guardrail.
    from common.pacific_time import pacific_now

    today_str = pacific_now().date().isoformat()
    monkeypatch.setattr(ai_context, "EXPERIMENT_START_DATE", today_str)
    body = _dashboard_body(monkeypatch)
    phases = {c["data_phase"] for c in body["coaches"]}
    assert phases, "expected at least one coach"
    assert phases == {"early"}
    assert "established" not in phases
    assert "pre_start" not in phases
