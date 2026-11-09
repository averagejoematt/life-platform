"""tests/test_mcp_auth_alarm_concurrency_5541.py — MCP auth failures are alarmed, and ADR-010's
reserved concurrency is what CDK declares (#5541).

Defect class: an emitted security metric with no alarm (`LifePlatform/MCP AuthFailures` ran 2-28/day
for 14 days, describe-alarms on the namespace empty), and an ADR stating a control the infrastructure
does not carry (ADR-010 says reserved concurrency 10; get-function-concurrency was empty live).

Read by AST/regex — CI's unit lane does not install aws_cdk. The alarm's metric identity is checked
against the EMF line `mcp/handler.py` actually prints (the wire), not against a copied literal.
"""

from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_REPO = Path(__file__).resolve().parent.parent
_MONITORING = _REPO / "cdk" / "stacks" / "monitoring_stack.py"
_MCP_STACK = _REPO / "cdk" / "stacks" / "mcp_stack.py"
_ADR = _REPO / "docs" / "DECISIONS.md"

DIGEST_ROUTE = "to_digest"
#: Measured 2026-11-08 (14 days): hourly Sum max 8 over 100 non-empty hours. The threshold must sit
#: well clear of the normal trickle or the digest learns to ignore it.
MEASURED_WORST_HOUR = 8
#: Measured 2026-11-08 (14 days): life-platform-mcp ConcurrentExecutions daily Max peaked at 4.
MEASURED_PEAK_CONCURRENCY = 4


def _calls(path: Path):
    return [n for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(n, ast.Call)]


def _const(node):
    return node.value if isinstance(node, ast.Constant) else None


def _auth_alarm_call():
    hits = [c for c in _calls(_MONITORING) if c.args and len(c.args) >= 2 and _const(c.args[1]) == "mcp-auth-failures"]
    assert len(hits) == 1, f"exactly one mcp-auth-failures alarm in monitoring_stack.py, found {len(hits)}"
    return hits[0]


def _emitted_auth_failure(capsys):
    from mcp import handler as h

    h._emit_auth_failure_metric()
    line = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip().startswith("{")][-1]
    return json.loads(line)


def test_the_auth_alarm_watches_the_metric_the_handler_emits(capsys):
    call = _auth_alarm_call()
    _id, _name, namespace, metric, period, stat, threshold, _op = (_const(a) if isinstance(a, ast.Constant) else a for a in call.args)
    kw = {k.arg: k.value for k in call.keywords}
    emf = _emitted_auth_failure(capsys)
    spec = emf["_aws"]["CloudWatchMetrics"][0]
    assert namespace == spec["Namespace"]
    assert metric == spec["Metrics"][0]["Name"]
    dims = ast.literal_eval(kw["dims"])
    assert set(dims) == set(spec["Dimensions"][0]), "the alarm's dimension set must equal the EMF line's, or it watches nothing"
    for k, v in dims.items():
        assert emf[k] == v
    assert period == 3600 and stat == "Sum", "the issue's contract: within the hour"
    assert threshold > 5 * MEASURED_WORST_HOUR, "threshold too close to the measured normal trickle"
    assert threshold <= 100, "a threshold this high would sleep through a real probing burst"
    assert DIGEST_ROUTE in kw and _const(kw[DIGEST_ROUTE]) is True, "ADR-050: auth failures route to the digest topic"


def _mcp_reserved_overrides():
    out = []
    for c in _calls(_MCP_STACK):
        if getattr(c.func, "attr", "") == "add_property_override" and c.args and _const(c.args[0]) == "ReservedConcurrentExecutions":
            target = c.func.value
            while isinstance(target, ast.Attribute):
                target = target.value
            out.append((getattr(target, "id", None), c.args[1]))
    return out


def test_adr_010_reserved_concurrency_is_declared_on_the_request_serving_function():
    overrides = _mcp_reserved_overrides()
    assert [t for t, _ in overrides] == ["mcp"], f"one override, on the request-serving `mcp` function only: {overrides}"
    src = _MCP_STACK.read_text(encoding="utf-8")
    m = re.search(r"^MCP_RESERVED_CONCURRENCY\s*=\s*(\d+)", src, re.M)
    assert m, "MCP_RESERVED_CONCURRENCY constant missing"
    declared = int(m.group(1))
    value = overrides[0][1]
    assert isinstance(value, ast.Name) and value.id == "MCP_RESERVED_CONCURRENCY"
    adr = _ADR.read_text(encoding="utf-8")
    section = adr[adr.index("## ADR-010") : adr.index("## ADR-011")]
    stated = re.search(r"\*\*Outcome:\*\*\s*Reserved concurrency = (\d+)", section)
    assert stated and int(stated.group(1)) == declared, "ADR-010's stated reserved concurrency and the CDK declaration disagree"
    assert declared > MEASURED_PEAK_CONCURRENCY, "the cap would bind on a normal day"


def test_the_cap_is_observable():
    names = [_const(k.value) for c in _calls(_MCP_STACK) for k in c.keywords if k.arg == "alarm_name"]
    assert "mcp-throttles" in names
    src = _MCP_STACK.read_text(encoding="utf-8")
    block = src[src.index('alarm_name="mcp-throttles"') :][:1200]
    assert 'metric_name="Throttles"' in block and '"FunctionName": MCP_FUNCTION_NAME' in block
