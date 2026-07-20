"""tests/test_qa_smoke_metrics.py — #1445: qa-smoke emits fail/warn metrics
+ heartbeat alarm; the remediation agent ingests qa-smoke results.

Before this fix, qa_smoke_lambda.py only ever spoke by SENDING AN EMAIL, and
only on a real FAILURE. A green run and a dead Lambda produced identical
(zero) external signal — no metric, no heartbeat, nothing for the
remediation agent to see, and a warnings-only run was fully silent (no
email, no alarm, nothing in the digest).

Three tests here:
  1. `emf_summary_line()` is a pure function — call it directly and assert
     the EMF document shape (functional, not just AST).
  2. AST-check that `lambda_handler` calls it UNCONDITIONALLY (before the
     `if not fails:` branch that gates the direct failure email) — a
     regression here would silently reintroduce "only speaks on failure."
  3. AST-check monitoring_stack.py declares the three LifePlatform/QaSmoke
     alarms (heartbeat + failures + warnings, both routed digest — matching
     the dispatcher's own "the daily sweep already handles routine ... QA
     smoke" posture, ADR-050) that make qa-smoke results a queryable
     CloudWatch alarm the remediation agent's existing
     `describe_alarms(StateValue="ALARM")` sweep already ingests.

All three FAIL on the pre-#1445 tree.
"""

import ast
import inspect
import json
import os
import sys

# qa_smoke_lambda reads these at import time (conftest supplies fake AWS creds).
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import qa_smoke_lambda as qa  # noqa: E402

MONITORING = os.path.join(os.path.dirname(__file__), "..", "cdk", "stacks", "monitoring_stack.py")


# ---------------------------------------------------------------------------
# 1. emf_summary_line() — functional
# ---------------------------------------------------------------------------


def test_emf_summary_line_is_valid_emf_and_always_reports_run_completed():
    assert hasattr(qa, "emf_summary_line"), "qa_smoke_lambda.emf_summary_line missing — #1445 metric emission not implemented"

    line = qa.emf_summary_line(passed=5, warned=2, failed=1, paused=3, timestamp_ms=1_700_000_000_000)
    doc = json.loads(line)  # must be pure JSON, one line — CloudWatch EMF requires this

    aws = doc["_aws"]
    assert aws["Timestamp"] == 1_700_000_000_000
    metric_def = aws["CloudWatchMetrics"][0]
    assert metric_def["Namespace"] == "LifePlatform/QaSmoke"
    metric_names = {m["Name"] for m in metric_def["Metrics"]}
    assert metric_names >= {"PassCount", "WarnCount", "FailCount", "PausedCount", "RunCompleted"}

    assert doc["PassCount"] == 5
    assert doc["WarnCount"] == 2
    assert doc["FailCount"] == 1
    assert doc["PausedCount"] == 3
    # RunCompleted is the heartbeat target: it must be 1 REGARDLESS of the
    # other counts, including on a run with zero of everything (e.g. every
    # check somehow paused) — its only job is proving the Lambda reached
    # this line at all.
    assert doc["RunCompleted"] == 1


def test_emf_summary_line_all_green_run_still_emits():
    """The AC's literal wording: 'on EVERY run, including green.' An
    all-pass, zero-fail, zero-warn run must still produce a valid metric
    document (not an early return / no-op)."""
    line = qa.emf_summary_line(passed=12, warned=0, failed=0, paused=1, timestamp_ms=1_700_000_000_000)
    doc = json.loads(line)
    assert doc["FailCount"] == 0
    assert doc["WarnCount"] == 0
    assert doc["RunCompleted"] == 1


# ---------------------------------------------------------------------------
# 2. lambda_handler calls emf_summary_line unconditionally
# ---------------------------------------------------------------------------


def test_lambda_handler_emits_emf_metric_before_the_fail_gate():
    """The pre-#1445 bug: qa-smoke only spoke on failure. Statically prove
    the EMF emission happens at the TOP LEVEL of the handler's try-block
    (not nested inside `if not fails:` or any other conditional) and BEFORE
    that gate — so it always runs regardless of outcome."""
    src = inspect.getsource(qa.lambda_handler)
    tree = ast.parse(src)
    func = tree.body[0]
    assert isinstance(func, ast.FunctionDef) and func.name == "lambda_handler"

    # lambda_handler's body is a single try/except; walk the try body's
    # direct statements only (top level of the try, no descending into any
    # nested `if`) looking for the emf_summary_line call and the `if not
    # fails:` gate, in source order.
    try_node = next(n for n in func.body if isinstance(n, ast.Try))

    emf_call_index = None
    fail_gate_index = None
    for i, stmt in enumerate(try_node.body):
        # Direct top-level `if` matching `if not fails:`
        if (
            fail_gate_index is None
            and isinstance(stmt, ast.If)
            and isinstance(stmt.test, ast.UnaryOp)
            and isinstance(stmt.test.op, ast.Not)
            and isinstance(stmt.test.operand, ast.Name)
            and stmt.test.operand.id == "fails"
        ):
            fail_gate_index = i
        # A top-level Expr statement whose call graph contains emf_summary_line
        if emf_call_index is None and isinstance(stmt, ast.Expr):
            for sub in ast.walk(stmt):
                if isinstance(sub, ast.Name) and sub.id == "emf_summary_line":
                    emf_call_index = i
                    break

    assert emf_call_index is not None, "lambda_handler never calls emf_summary_line() at the top level of its try-block (#1445)"
    assert fail_gate_index is not None, "lambda_handler's `if not fails:` gate not found — parser broke, investigate"
    assert emf_call_index < fail_gate_index, (
        "emf_summary_line() is called AFTER (or is nested inside) the `if not fails:` gate — "
        "it must run unconditionally, before any branch that could skip it (#1445)"
    )


def test_lambda_handler_logs_itemized_fails_and_warns_before_the_fail_gate():
    """#1610: the specific failing check must reach stdout (CloudWatch), not just
    the failure email. Statically prove the handler iterates `fails` AND `warns`
    at the top level of its try-block, printing each, BEFORE the `if not fails:`
    gate — so a latched FailCount alarm is diagnosable from logs even on a
    warnings-only run (which early-returns at that gate) and without inbox access."""
    src = inspect.getsource(qa.lambda_handler)
    tree = ast.parse(src)
    func = tree.body[0]
    try_node = next(n for n in func.body if isinstance(n, ast.Try))

    fail_gate_index = None
    fails_loop_index = None
    warns_loop_index = None
    for i, stmt in enumerate(try_node.body):
        if (
            fail_gate_index is None
            and isinstance(stmt, ast.If)
            and isinstance(stmt.test, ast.UnaryOp)
            and isinstance(stmt.test.op, ast.Not)
            and isinstance(stmt.test.operand, ast.Name)
            and stmt.test.operand.id == "fails"
        ):
            fail_gate_index = i
        # a top-level `for c in fails:` / `for c in warns:` whose body prints
        if isinstance(stmt, ast.For) and isinstance(stmt.iter, ast.Name):
            prints = any(isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "print" for sub in ast.walk(stmt))
            if prints and stmt.iter.id == "fails" and fails_loop_index is None:
                fails_loop_index = i
            if prints and stmt.iter.id == "warns" and warns_loop_index is None:
                warns_loop_index = i

    assert fails_loop_index is not None, "lambda_handler never prints each item of `fails` at the top level of its try-block (#1610)"
    assert warns_loop_index is not None, "lambda_handler never prints each item of `warns` at the top level of its try-block (#1610)"
    assert fail_gate_index is not None, "lambda_handler's `if not fails:` gate not found — parser broke, investigate"
    assert fails_loop_index < fail_gate_index and warns_loop_index < fail_gate_index, (
        "the itemized fail/warn logging is AFTER the `if not fails:` gate — it must run before it so "
        "a warnings-only run (which returns at that gate) still logs its warns (#1610)"
    )


# ---------------------------------------------------------------------------
# 3. monitoring_stack.py declares the three LifePlatform/QaSmoke alarms
# ---------------------------------------------------------------------------


def _tree(path):
    with open(path) as f:
        return ast.parse(f.read())


def _kw(call, name):
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def _walk_no_nested_func(body):
    for stmt in body:
        yield stmt
        for field in ("body", "orelse", "finalbody"):
            sub = getattr(stmt, field, None)
            if sub:
                yield from _walk_no_nested_func(sub)


def _monitoring_alarm_calls():
    """Returns {alarm_name: {"fn": "_alarm"|"_heartbeat_alarm", "namespace":..,
    "metric_name":.., "to_digest": bool}} for every direct helper call in
    MonitoringStack.__init__."""
    tree = _tree(MONITORING)
    init = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "__init__")

    out = {}
    for stmt in _walk_no_nested_func(init.body):
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            call = stmt.value
            fname = getattr(call.func, "id", None)
            if fname not in ("_alarm", "_heartbeat_alarm"):
                continue
            name_node = call.args[1] if len(call.args) >= 2 else _kw(call, "alarm_name")
            namespace_node = call.args[2] if len(call.args) >= 3 else _kw(call, "namespace")
            metric_node = call.args[3] if len(call.args) >= 4 else _kw(call, "metric_name")
            if not (
                isinstance(name_node, ast.Constant) and isinstance(namespace_node, ast.Constant) and isinstance(metric_node, ast.Constant)
            ):
                continue
            to_digest_node = _kw(call, "to_digest")
            to_digest = bool(to_digest_node.value) if isinstance(to_digest_node, ast.Constant) else (fname == "_heartbeat_alarm")
            out[name_node.value] = {
                "fn": fname,
                "namespace": namespace_node.value,
                "metric_name": metric_node.value,
                "to_digest": to_digest,
            }
    return out


def test_qa_smoke_heartbeat_alarm_declared():
    alarms = _monitoring_alarm_calls()
    assert "qa-smoke-heartbeat" in alarms, "qa-smoke-heartbeat alarm missing from monitoring_stack.py (#1445 AC2)"
    a = alarms["qa-smoke-heartbeat"]
    assert (
        a["fn"] == "_heartbeat_alarm"
    ), "qa-smoke-heartbeat must use the _heartbeat_alarm helper (absence=BREACHING, mirrors the REL-01 heartbeats)"
    assert a["namespace"] == "LifePlatform/QaSmoke"
    assert a["metric_name"] == "RunCompleted"


def test_qa_smoke_failures_and_warnings_alarms_declared():
    alarms = _monitoring_alarm_calls()

    assert "qa-smoke-failures" in alarms, "qa-smoke-failures alarm missing from monitoring_stack.py (#1445 AC1/AC3)"
    fails = alarms["qa-smoke-failures"]
    assert fails["namespace"] == "LifePlatform/QaSmoke"
    assert fails["metric_name"] == "FailCount"

    assert "qa-smoke-warnings" in alarms, "qa-smoke-warnings alarm missing — warnings-only runs must surface in the digest (#1445 AC4)"
    warns = alarms["qa-smoke-warnings"]
    assert warns["namespace"] == "LifePlatform/QaSmoke"
    assert warns["metric_name"] == "WarnCount"
    # Digest, not urgent: matches remediation_dispatcher_lambda.py's own
    # philosophy that routine QA findings are the daily-sweep's job, and
    # means a warnings-only run appears in the digest, not a full alert.
    assert (
        warns["to_digest"] is True
    ), "qa-smoke-warnings must route to the digest topic, not urgent (#1445 AC4: 'not a full alert, but visible')"
