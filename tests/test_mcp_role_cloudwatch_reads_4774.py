"""tests/test_mcp_role_cloudwatch_reads_4774.py — #4774: the MCP role must grant the
CloudWatch reads the site-api handlers it runs in-process make.

THE INCIDENT
------------
2026-10-10T05:38:49Z, MCP `get_platform_cost` returned
``"inference_receipt": {"error": "Inference receipt temporarily unavailable."}``. The
public `/api/inference_receipt` was serving 200 the whole time. The cause, from the
``[inference_receipt] failed:`` line in /aws/lambda/life-platform-mcp:

    An error occurred (AccessDenied) when calling the ListMetrics operation: User:
    arn:aws:sts::205930651321:assumed-role/LifePlatformMcp-McpServerRoleA1D35EE2-.../life-platform-mcp
    is not authorized to perform: cloudwatch:ListMetrics because no identity-based policy
    allows the cloudwatch:ListMetrics action

The surface waiter (``mcp/tools_surfaces._dispatch``) runs the site-api handler IN the MCP
Lambda, so it executes under ``role_policies_serve.mcp_server()``, which had no CloudWatch
read at all. The same request logged ``[receipts] typical day unavailable`` and ``history
unavailable`` (GetMetricStatistics AccessDenied) — the envelope looked fine but was
silently missing two of its blocks.

WHAT IS GUARDED
---------------
1. The failing shape, reproduced: the receipt run against a CloudWatch client that
   enforces a role's granted actions, answering a denied call with the live wire error.
   Under the pre-fix MCP role it 503s with the exact message; under the current role it
   serves a populated table.
2. The set, not the specimen: every CloudWatch API the ``lambdas/web/`` handler modules
   call (derived by AST, never hand-listed) must be granted to the MCP role. A handler that
   adds a new CloudWatch read reds here before it 503s through MCP.
"""

from __future__ import annotations

import ast
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import test_role_family_write_scope as family  # the stubbed role_policies* import (#2604-safe)
from botocore.exceptions import ClientError

_REPO = Path(__file__).resolve().parent.parent
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
sys.path.insert(0, str(_REPO / "lambdas"))

from web import site_api_budget as budget  # noqa: E402

_WEB_DIR = _REPO / "lambdas" / "web"

# boto3 CloudWatch method -> the IAM action it needs. A web module calling a CloudWatch
# method missing from this map fails test_every_cloudwatch_call_is_mapped, so the map
# cannot go quietly stale.
_CW_METHOD_ACTION = {
    "describe_alarms": "cloudwatch:DescribeAlarms",
    "describe_alarm_history": "cloudwatch:DescribeAlarmHistory",
    "get_metric_data": "cloudwatch:GetMetricData",
    "get_metric_statistics": "cloudwatch:GetMetricStatistics",
    "list_metrics": "cloudwatch:ListMetrics",
    "put_metric_data": "cloudwatch:PutMetricData",
}

# The fields of the live AccessDenied (fixture is the wire, 2026-10-10T05:38:49Z).
_ROLE_ARN = "arn:aws:sts::205930651321:assumed-role/LifePlatformMcp-McpServerRoleA1D35EE2-wJuRyjhOVioW/life-platform-mcp"

_NOW = datetime(2026, 10, 10, 5, 38, 49, tzinfo=timezone.utc)
_DAY_START = _NOW.replace(hour=0, minute=0, second=0, microsecond=0)


class _FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return _NOW.astimezone(tz) if tz else _NOW.replace(tzinfo=None)


def _access_denied(operation: str, action: str) -> ClientError:
    return ClientError(
        {
            "Error": {
                "Code": "AccessDenied",
                "Message": (
                    f"User: {_ROLE_ARN} is not authorized to perform: {action} "
                    f"because no identity-based policy allows the {action} action"
                ),
            }
        },
        operation,
    )


class _RoleEnforcingCW:
    """A CloudWatch client that only answers the calls the given role grants."""

    def __init__(self, granted: set):
        self.granted = granted

    def _check(self, method: str, operation: str):
        action = _CW_METHOD_ACTION[method]
        if action not in self.granted:
            raise _access_denied(operation, action)

    def list_metrics(self, Namespace, MetricName, **kw):
        self._check("list_metrics", "ListMetrics")
        if Namespace == "AWS/Bedrock":
            return {"Metrics": [{"Dimensions": [{"Name": "ModelId", "Value": "us.anthropic.claude-sonnet-4-6"}]}]}
        return {"Metrics": [{"Dimensions": [{"Name": "LambdaFunction", "Value": "daily-brief"}]}]}

    def get_metric_data(self, MetricDataQueries, **kw):
        self._check("get_metric_data", "GetMetricData")
        return {
            "MetricDataResults": [
                {"Id": q["Id"], "Timestamps": [_DAY_START, _DAY_START - timedelta(days=1)], "Values": [1000.0, 2000.0]}
                for q in MetricDataQueries
            ]
        }

    def get_metric_statistics(self, **kw):
        self._check("get_metric_statistics", "GetMetricStatistics")
        return {"Datapoints": []}


class _FakeSSM:
    def get_parameter(self, Name):
        if Name == "/life-platform/budget-tier":
            return {"Parameter": {"Value": "0"}}
        return {"Parameter": {"Value": json.dumps({"ceiling": budget._ADR133_BASE_CEILING_USD, "surge_active": False})}}


def _mcp_granted() -> set:
    return family.granted_actions(family.policy_statements("mcp_server"))


def _run_receipt(monkeypatch, granted: set) -> dict:
    cw = _RoleEnforcingCW(granted)
    monkeypatch.setattr(budget, "datetime", _FrozenDateTime)
    monkeypatch.setattr(budget.boto3, "client", lambda service, **kw: cw if service == "cloudwatch" else _FakeSSM())
    return budget.inference_receipt()


# ── 1. the failing shape ──────────────────────────────────────────────────────────────


def test_the_pre_fix_mcp_role_reproduces_the_live_503(monkeypatch):
    """The 2026-10-10 state: the MCP role without any CloudWatch read. Must fail EXACTLY as
    live did — this is the control that proves the harness can see the bug."""
    pre_fix = {a for a in _mcp_granted() if not (a.startswith("cloudwatch:") and a != "cloudwatch:PutMetricData")}
    resp = _run_receipt(monkeypatch, pre_fix)
    assert resp["statusCode"] == 503
    assert json.loads(resp["body"])["error"] == "Inference receipt temporarily unavailable."


def test_the_mcp_role_serves_a_populated_receipt(monkeypatch):
    """#4774: through the MCP role the receipt is a table, not the catch-all 503."""
    resp = _run_receipt(monkeypatch, _mcp_granted())
    assert resp["statusCode"] == 200, resp
    body = json.loads(resp["body"])
    assert body["models"], "no per-model rows"
    assert body["features"], "no per-feature rows"
    assert body["models"][0]["month"]["est_cost_usd"] is not None
    assert body["features"][0]["month_est_cost_usd"] is not None


# ── 2. the set: every CloudWatch call in lambdas/web/ ─────────────────────────────────


def _web_handler_modules() -> list:
    """lambdas/web/*.py that the site-api router can reach in-process — i.e. not some
    OTHER Lambda's entrypoint (site_api_ai_lambda is its own function with its own role)."""
    out = []
    for path in sorted(_WEB_DIR.glob("*.py")):
        if path.name.endswith("_lambda.py") and path.name != "site_api_lambda.py":
            continue
        out.append(path)
    return out


def _cloudwatch_calls(path: Path) -> set:
    """Method names called on a CloudWatch client in a module that constructs one."""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    builds_cw = any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "client"
        and n.args
        and isinstance(n.args[0], ast.Constant)
        and n.args[0].value == "cloudwatch"
        for n in ast.walk(tree)
    )
    if not builds_cw:
        return set()
    known_cw = set(_CW_METHOD_ACTION) | {"get_paginator"}
    return {
        n.func.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and (n.func.attr in known_cw or n.func.attr.startswith(("describe_alarm", "list_metric", "get_metric")))
    }


def _required_actions() -> dict:
    """{iam action: [module, ...]} across the in-process handler modules."""
    need: dict = {}
    for path in _web_handler_modules():
        for method in _cloudwatch_calls(path):
            need.setdefault(_CW_METHOD_ACTION.get(method, f"UNMAPPED:{method}"), []).append(path.name)
    return need


def test_every_cloudwatch_call_is_mapped():
    unmapped = {a: m for a, m in _required_actions().items() if a.startswith("UNMAPPED:")}
    assert not unmapped, f"add these CloudWatch methods to _CW_METHOD_ACTION: {unmapped}"


def test_the_derivation_sees_the_specimen():
    """Non-vacuity: the scan must find the call that 503'd live, in the module that made it."""
    need = _required_actions()
    assert "site_api_budget.py" in need.get("cloudwatch:ListMetrics", [])
    assert "site_api_status.py" in need.get("cloudwatch:DescribeAlarms", [])


def test_the_mcp_role_grants_every_cloudwatch_call_its_waiter_can_make():
    granted = _mcp_granted()
    missing = {a: sorted(set(mods)) for a, mods in _required_actions().items() if a not in granted}
    assert not missing, (
        "the MCP surface waiter runs these lambdas/web/ handlers under role_policies_serve.mcp_server(), "
        f"which does not grant: {missing}. Through MCP each call is AccessDenied (#4774)."
    )


def test_MUTATION_dropping_the_grant_is_caught(monkeypatch):
    """The set gate must red when the #4774 statement is removed."""
    real = family.policy_statements("mcp_server")
    stripped = [s for s in real if s.sid != "SurfaceWaiterCloudWatchRead"]
    assert len(stripped) == len(real) - 1, "#4774's statement is gone from mcp_server() — re-derive this control"
    granted = family.granted_actions(stripped)
    missing = {a for a in _required_actions() if a not in granted}
    assert {"cloudwatch:ListMetrics", "cloudwatch:GetMetricData", "cloudwatch:GetMetricStatistics", "cloudwatch:DescribeAlarms"} <= missing
