"""tests/test_urgent_alarm_routing.py — #1444: the urgent SNS topic must have
an IaC-declared email subscription, and the remediation dispatcher's
URGENT_PATTERNS must actually match alarms routed to the topic it subscribes
to (not the digest topic it never receives).

Static-analysis tests (no CDK install / no AWS, mirrors
tests/test_serve_throttles_alarms.py's / tests/test_budget_tier_alarms.py's
approach): AST-parse monitoring_stack.py to derive, for every alarm construct,
whether it is routed to the urgent (`topic`) or digest (`digest`) SNS topic —
via the shared `_alarm()`/`_heartbeat_alarm()` helpers' `to_digest` kwarg, and
via the handful of alarms built directly with `cloudwatch.Alarm(...)` +
`.add_alarm_action(cw_actions.SnsAction(<topic-var>))`. Cross-checked once
against the real `cdk synth` CloudFormation template (2026-07-18): the derived
urgent set (13 static names, expanding to 17 concrete alarms once the
whoop/withings/strava/eightsleep/hevy `ingest-consecutive-failures-{src}`
f-string loop is unrolled) matched exactly.

Both tests FAIL on the pre-#1444 tree: the alerts topic had no email
subscription in IaC, and URGENT_PATTERNS's "canary" / "dlq-depth" /
"site-api-error" / "bedrock-throttle" entries matched zero urgent-topic
alarms (they matched only digest-topic alarms, or nothing at all).
"""

import ast
import os

MONITORING = os.path.join(os.path.dirname(__file__), "..", "cdk", "stacks", "monitoring_stack.py")
OPERATIONAL = os.path.join(os.path.dirname(__file__), "..", "cdk", "stacks", "operational_stack.py")
DISPATCHER = os.path.join(os.path.dirname(__file__), "..", "lambdas", "operational", "remediation_dispatcher_lambda.py")


def _tree(path):
    with open(path) as f:
        return ast.parse(f.read())


def _kw(call, name):
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def _render_name(node):
    """Best-effort static render of an alarm_name expression.

    Constant -> literal value. JoinedStr (f-string, used by the
    ingest-consecutive-failures-{src} loop) -> concatenation of its static
    parts only, dropping the interpolated expression. That's sufficient for
    substring pattern-matching since every reconciled pattern targets the
    static prefix, never the loop variable.
    """
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = [v.value for v in node.values if isinstance(v, ast.Constant)]
        return "".join(parts)
    return None


def _walk_no_nested_func(body):
    """Yield statements in body, recursing into compound statements (for/if/
    with/try) but NOT into nested function defs — so a helper's own internal
    `add_alarm_action` line is never mistaken for a top-level call site."""
    for stmt in body:
        yield stmt
        for field in ("body", "orelse", "finalbody"):
            sub = getattr(stmt, field, None)
            if sub:
                yield from _walk_no_nested_func(sub)


def _extract_alarm_routing():
    """Returns {alarm_name_or_static_prefix: "urgent"|"digest"} derived from
    monitoring_stack.py's MonitoringStack.__init__."""
    tree = _tree(MONITORING)
    init = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "__init__")

    # Step 1: classify the two SNS topic-handle variables.
    topic_class = {}
    for stmt in _walk_no_nested_func(init.body):
        if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
            call = stmt.value
            if (
                isinstance(call.func, ast.Attribute)
                and call.func.attr == "from_topic_arn"
                and len(call.args) >= 3
                and isinstance(call.args[2], ast.Name)
                and isinstance(stmt.targets[0], ast.Name)
            ):
                arn_name = call.args[2].id
                var = stmt.targets[0].id
                if arn_name == "ALERTS_TOPIC_ARN":
                    topic_class[var] = "urgent"
                elif arn_name == "DIGEST_TOPIC_ARN":
                    topic_class[var] = "digest"
    assert topic_class, "no sns.Topic.from_topic_arn(...) assignments found — parser broke, investigate"

    routing = {}

    # Step 2 + 3: alarms built directly with cloudwatch.Alarm(...) assigned to
    # a variable, then routed via <var>.add_alarm_action(cw_actions.SnsAction(<topic-var>)).
    var_to_alarm_name = {}
    for stmt in _walk_no_nested_func(init.body):
        if (
            isinstance(stmt, ast.Assign)
            and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.targets[0], ast.Name)
            and isinstance(stmt.value.func, ast.Attribute)
            and stmt.value.func.attr == "Alarm"
        ):
            name_val = _render_name(_kw(stmt.value, "alarm_name"))
            if name_val:
                var_to_alarm_name[stmt.targets[0].id] = name_val

    for stmt in _walk_no_nested_func(init.body):
        if (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Attribute)
            and stmt.value.func.attr == "add_alarm_action"
            and isinstance(stmt.value.func.value, ast.Name)
            and stmt.value.func.value.id in var_to_alarm_name
        ):
            call = stmt.value
            if call.args and isinstance(call.args[0], ast.Call) and call.args[0].args and isinstance(call.args[0].args[0], ast.Name):
                topic_var = call.args[0].args[0].id
                alarm_name = var_to_alarm_name[stmt.value.func.value.id]
                routing[alarm_name] = topic_class.get(topic_var, "unknown")

    # Step 4: direct _alarm(...) / _heartbeat_alarm(...) helper calls (including
    # inside the whoop/withings/strava/eightsleep/hevy for-loop).
    for stmt in _walk_no_nested_func(init.body):
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            call = stmt.value
            fname = getattr(call.func, "id", None)
            if fname == "_alarm":
                name_val = _render_name(call.args[1]) if len(call.args) >= 2 else _render_name(_kw(call, "alarm_name"))
                to_digest_node = _kw(call, "to_digest")
                to_digest = bool(to_digest_node.value) if isinstance(to_digest_node, ast.Constant) else False
                if name_val:
                    routing[name_val] = "digest" if to_digest else "urgent"
            elif fname == "_heartbeat_alarm":
                name_val = _render_name(call.args[1]) if len(call.args) >= 2 else _render_name(_kw(call, "alarm_name"))
                if name_val:
                    routing[name_val] = "digest"  # _heartbeat_alarm always routes digest

    return routing


def _urgent_topic_alarm_names():
    routing = _extract_alarm_routing()
    urgent = {name for name, cls in routing.items() if cls == "urgent"}
    assert urgent, "no urgent-topic alarms derived from monitoring_stack.py — parser broke, investigate"
    return urgent


def _dispatcher_urgent_patterns():
    tree = _tree(DISPATCHER)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "_DEFAULT_PATTERNS" for t in node.targets):
            value = _render_name(node.value)
            assert value, "_DEFAULT_PATTERNS is not a static string literal — parser broke, investigate"
            return tuple(p.strip().lower() for p in value.split(",") if p.strip())
    raise AssertionError("_DEFAULT_PATTERNS assignment not found in remediation_dispatcher_lambda.py")


def test_every_urgent_pattern_matches_a_real_urgent_topic_alarm():
    """AC: 'A unit/CDK test asserts each URGENT_PATTERN matches >=1 alarm
    routed to a topic the dispatcher actually subscribes to.' The dispatcher
    is SNS-subscribed only to the urgent (alerts) topic — a pattern matching
    only a digest-topic alarm (or nothing at all) is dead and must not exist.
    """
    urgent_names = _urgent_topic_alarm_names()
    patterns = _dispatcher_urgent_patterns()
    assert patterns, "URGENT_PATTERNS parsed empty — investigate remediation_dispatcher_lambda.py"

    dead = []
    for pattern in patterns:
        if not any(pattern in name.lower() for name in urgent_names):
            dead.append(pattern)
    assert not dead, f"URGENT_PATTERNS entries with zero matching urgent-topic alarm (dead patterns): {dead}"


def test_high_severity_urgent_alarm_classes_are_covered():
    """Reconciliation isn't just 'no dead patterns' — the classes of alarm
    that motivated the fast urgent topic in the first place (OAuth-token
    death, auth-suppressed ingestion, DynamoDB throttling, DLQ pileup, a cost
    runaway, the digest watchdog's own death) must each have >=1 matching
    pattern, not just the two survivors (budget-tier, slo-) from the old list.
    """
    urgent_names = _urgent_topic_alarm_names()
    patterns = _dispatcher_urgent_patterns()

    must_cover = [
        "ingest-consecutive-failures",  # the Whoop 49-consecutive-failure OAuth-death class
        "ingest-auth-unhealthy",  # breaker-tripped auth suppression
        "ddb-throttled",  # silent data loss
        "ingestion-dlq",  # async failures piling up
        "ai-daily-spend",  # cost runaway
        "alert-digest",  # the digest watchdog's own delivery path (#1229)
    ]
    for expected_name_fragment in must_cover:
        assert any(
            expected_name_fragment in name.lower() for name in urgent_names
        ), f"expected an urgent-topic alarm containing {expected_name_fragment!r} — monitoring_stack.py routing changed, update this test"
        assert any(
            p in expected_name_fragment or expected_name_fragment.startswith(p) for p in patterns
        ), f"no URGENT_PATTERN covers the {expected_name_fragment!r} alarm class"


def test_alerts_topic_has_an_iac_email_subscription():
    """AC: 'The email subscription is codified in monitoring_stack.py either
    way (import or create).' It landed in operational_stack.py instead (same
    file that already wires the dispatcher's LambdaSubscription to the same
    local_alerts_topic handle) — assert both subscriptions exist on it.
    """
    tree = _tree(OPERATIONAL)
    init = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "__init__")

    subscription_kinds = []
    for stmt in _walk_no_nested_func(init.body):
        if (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Attribute)
            and stmt.value.func.attr == "add_subscription"
            and isinstance(stmt.value.func.value, ast.Name)
            and stmt.value.func.value.id == "local_alerts_topic"
        ):
            sub_call = stmt.value.args[0] if stmt.value.args else None
            if isinstance(sub_call, ast.Call) and isinstance(sub_call.func, ast.Attribute):
                subscription_kinds.append(sub_call.func.attr)

    assert "LambdaSubscription" in subscription_kinds, "local_alerts_topic lost its dispatcher LambdaSubscription"
    assert "EmailSubscription" in subscription_kinds, (
        "local_alerts_topic has no EmailSubscription — the urgent SNS topic's human fast path "
        "must be codified in IaC, not left as a manual console-only subscription (#1444)"
    )
