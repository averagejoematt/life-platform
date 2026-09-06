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
`.add_alarm_action(cw_actions.SnsAction(<topic-var>))` — plus, since #2116,
`cloudwatch.CompositeAlarm(...)` the same way (its name kwarg is
`composite_alarm_name`, not `alarm_name`). Cross-checked once against the real
`cdk synth` CloudFormation template (2026-07-18): the derived urgent set (13
static names, expanding to 17 concrete alarms once the
whoop/withings/strava/eightsleep/hevy `ingest-consecutive-failures-{src}`
f-string loop is unrolled) matched exactly. #2116 (verified against a fresh
local synth, see that PR) replaced the raw `ai-tokens-platform-daily-total`
alarm's direct SNS action with two composite alarms
(`ai-tokens-platform-daily-total-urgent` -> urgent,
`ai-tokens-platform-daily-total-genesis-window` -> digest) gated on a
genesis-rebuild-window gauge; the raw alarm itself now carries no action.

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


def _kw_first(call, names):
    """First matching keyword value across a list of candidate kwarg names —
    `cloudwatch.Alarm(...)` names its alarm via `alarm_name`, but
    `cloudwatch.CompositeAlarm(...)` (#2116) uses `composite_alarm_name`."""
    for name in names:
        v = _kw(call, name)
        if v is not None:
            return v
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
    """Returns {alarm_name_or_static_prefix: "urgent"|"digest"} for every alarm the
    monitoring stack declares — including the ones declared for it by an extraction
    sibling (see `_extract_sibling_routing`)."""
    routing = _extract_stack_routing()
    for module, fn_name in _EXTRACTION_SIBLINGS:
        routing.update(_extract_sibling_routing(module, fn_name))
    return routing


# ── #3505: the extraction siblings ───────────────────────────────────────────────
#
# monitoring_stack.py sits at the module-size ratchet, so alarm surface lands in
# cohesive siblings (`monitoring_token_alarms.py`, `monitoring_budget_alarms.py`, …)
# invoked from the same scope. This derivation used to parse ONE named file, so the
# moment the AI token/spend family moved, "ai-daily-spend" and "ai-tokens-platform"
# would have matched zero urgent alarms and the reconciliation this file exists to
# perform would have been silently over a smaller board (#2703: a guard reading a file
# that no longer holds its subject still runs and still passes on the half it can see).
#
# A sibling takes its SNS topics as PARAMETERS rather than building them from an ARN, so
# each entry names the function and its topic parameters are classified by position via
# the module's own signature: `(scope, topic, digest)` -> topic=urgent, digest=digest.
# `test_the_sibling_derivation_sees_its_subject` asserts the sweep is not empty.
_EXTRACTION_SIBLINGS = (("monitoring_token_alarms", "add_token_alarms"),)
_SIBLING_TOPIC_PARAM_CLASS = {"topic": "urgent", "digest": "digest"}


def _extract_sibling_routing(module: str, fn_name: str):
    """{alarm_name: "urgent"|"digest"} for an extraction sibling's declaring function.

    Same three shapes as the in-stack derivation below, with the topic variables
    resolved from the function's own parameter names instead of from
    `sns.Topic.from_topic_arn(...)` assignments.
    """
    path = os.path.join(os.path.dirname(__file__), "..", "cdk", "stacks", f"{module}.py")
    assert os.path.isfile(path), f"extraction sibling {module}.py is gone — update _EXTRACTION_SIBLINGS or the extraction moved again"
    tree = _tree(path)
    fn = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == fn_name), None)
    assert fn is not None, f"{module}.{fn_name} not found — the sibling's entrypoint was renamed"
    topic_class = {a.arg: _SIBLING_TOPIC_PARAM_CLASS[a.arg] for a in fn.args.args if a.arg in _SIBLING_TOPIC_PARAM_CLASS}
    assert topic_class, f"{module}.{fn_name} takes neither a `topic` nor a `digest` parameter — cannot classify its routing"
    return _routing_from_body(fn.body, topic_class)


def _extract_stack_routing():
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
    return _routing_from_body(init.body, topic_class)


def _routing_from_body(body, topic_class):
    """{alarm_name: "urgent"|"digest"} for one declaring body, given its topic vars.

    Split out of `_extract_stack_routing` by #3505 so the identical three shapes are
    derived for an extraction sibling as for the stack itself — one implementation, so
    the two can never disagree about what "routed urgent" means.
    """
    routing = {}

    # Step 2 + 3: alarms built directly with cloudwatch.Alarm(...) OR
    # cloudwatch.CompositeAlarm(...) (#2116 — the token-alarm genesis-window
    # composite) assigned to a variable, then routed via
    # <var>.add_alarm_action(cw_actions.SnsAction(<topic-var>)).
    var_to_alarm_name = {}
    for stmt in _walk_no_nested_func(body):
        if (
            isinstance(stmt, ast.Assign)
            and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.targets[0], ast.Name)
            and isinstance(stmt.value.func, ast.Attribute)
            and stmt.value.func.attr in ("Alarm", "CompositeAlarm")
        ):
            name_val = _render_name(_kw_first(stmt.value, ("alarm_name", "composite_alarm_name")))
            if name_val:
                var_to_alarm_name[stmt.targets[0].id] = name_val

    for stmt in _walk_no_nested_func(body):
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

    # Step 4: single-alarm factory calls — `_alarm(...)` / `_heartbeat_alarm(...)` in the
    # stack, `_token_alarm(...)` in the #3505 sibling (including the whoop/withings/
    # strava/eightsleep/hevy for-loop). Matched on the `*_alarm` SHAPE rather than on one
    # hardcoded name: the sibling's helper had to be renamed to keep factory names unique
    # across modules (tests/test_boot_contract_3314.py::test_stack_helper_names_are_unique),
    # and a name-matched rule would have gone blind on exactly that rename.
    for stmt in _walk_no_nested_func(body):
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            call = stmt.value
            fname = getattr(call.func, "id", None)
            if fname == "_heartbeat_alarm":
                name_val = _render_name(call.args[1]) if len(call.args) >= 2 else _render_name(_kw(call, "alarm_name"))
                if name_val:
                    routing[name_val] = "digest"  # _heartbeat_alarm always routes digest
            elif fname and fname.endswith("_alarm"):
                name_val = _render_name(call.args[1]) if len(call.args) >= 2 else _render_name(_kw(call, "alarm_name"))
                to_digest_node = _kw(call, "to_digest")
                to_digest = bool(to_digest_node.value) if isinstance(to_digest_node, ast.Constant) else False
                if name_val:
                    routing[name_val] = "digest" if to_digest else "urgent"

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


def test_the_sibling_derivation_sees_its_subject():
    """FLOOR (#3505). `_extract_sibling_routing` returning {} would make every assertion
    above pass over a smaller board without saying so — the vacuous-empty shape. So assert
    the sibling sweep actually resolves the alarms it was widened for, by name, and that
    the composite pair's two sides land on the two different topics."""
    for module, fn_name in _EXTRACTION_SIBLINGS:
        sibling = _extract_sibling_routing(module, fn_name)
        assert sibling, f"{module}.{fn_name} resolved ZERO alarms — the derivation went blind, not the module empty"
    combined = _extract_alarm_routing()
    assert combined.get("ai-daily-spend-high-urgent") == "urgent", "the paging half of the #3505 spend composite pair is not urgent-routed"
    assert combined.get("ai-daily-spend-high-genesis-window") == "digest", "the in-window half must record to the digest"
    assert combined.get("ai-tokens-platform-daily-total-urgent") == "urgent"
    assert combined.get("ai-tokens-daily-brief-runaway") == "digest"
    assert "ai-daily-spend-high" not in combined, "the raw spend alarm must carry no routing of its own (#3505) — only its composites route"


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
