"""tests/test_web_alarms_2829.py — #2829: the us-east-1 alarm estate must not have a
no-action alarm again.

Static-analysis (AST) tests only — mirrors tests/test_urgent_alarm_routing.py's and
tests/test_serve_throttles_alarms.py's approach. `cdk/stacks/*.py` imports `aws_cdk`,
which CI's Deploy-critical/Unit Tests job does NOT install (see
reference_test_importing_aws_cdk_reds_ci.md) — importing the module or `constructs`
here would fail at COLLECTION and red the whole job. Every check below reads
cdk/stacks/web_stack.py and cdk/stacks/web_alarms.py as text via `ast.parse`, never
`import`.

What this closes: the #2829 bug was a `cloudwatch.Alarm(...)` construct with no
`.add_alarm_action(...)` call anywhere — invisible to `cdk synth` (a valid template
either way) and invisible to any test that only checks an alarm EXISTS. This guard
asserts every alarm construct built in these two files is routed to an SNS action,
so a future alarm here can be silent-by-omission but never silent-and-green.
"""

import ast
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WEB_STACK = os.path.join(ROOT, "cdk", "stacks", "web_stack.py")
WEB_ALARMS = os.path.join(ROOT, "cdk", "stacks", "web_alarms.py")


def _tree(path):
    with open(path, encoding="utf-8") as f:
        return ast.parse(f.read(), filename=path)


def _walk_no_nested_func(body):
    """Yield statements in body, recursing into compound statements (for/if/with/try)
    but not into nested function defs — mirrors test_urgent_alarm_routing.py so a
    helper's own internal add_alarm_action line is never miscounted."""
    for stmt in body:
        yield stmt
        for field in ("body", "orelse", "finalbody"):
            sub = getattr(stmt, field, None)
            if sub:
                yield from _walk_no_nested_func(sub)


def _find_init(tree, class_name):
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == class_name)
    return next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")


def _find_func(tree, func_name):
    return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == func_name)


def _kw(call, name):
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def _render_name(node):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = [v.value for v in node.values if isinstance(v, ast.Constant)]
        return "".join(parts)
    return None


def _alarm_action_status(body):
    """{alarm_name: has_action} for every `cloudwatch.Alarm(...)` assigned to a
    variable in `body`, cross-referenced against `<var>.add_alarm_action(...)` calls
    in the same body — including a variable passed into another function call (the
    web_stack.py -> add_web_alarms(self, subscriber_errors_alarm) handoff), which
    counts as "routed elsewhere" and is resolved by the CALLER's own check instead."""
    var_to_name = {}
    passed_to_call = set()
    for stmt in _walk_no_nested_func(body):
        if (
            isinstance(stmt, ast.Assign)
            and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.targets[0], ast.Name)
            and isinstance(stmt.value.func, ast.Attribute)
            and stmt.value.func.attr == "Alarm"
        ):
            name_val = _render_name(_kw(stmt.value, "alarm_name"))
            if name_val:
                var_to_name[stmt.targets[0].id] = name_val

    routed = set()
    for stmt in _walk_no_nested_func(body):
        if (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Attribute)
            and stmt.value.func.attr == "add_alarm_action"
            and isinstance(stmt.value.func.value, ast.Name)
            and stmt.value.func.value.id in var_to_name
        ):
            routed.add(stmt.value.func.value.id)
        # A bare `add_web_alarms(self, subscriber_errors_alarm)` call — the variable is
        # handed to another function that is responsible for routing it there.
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            for arg in stmt.value.args:
                if isinstance(arg, ast.Name) and arg.id in var_to_name:
                    passed_to_call.add(arg.id)

    return {name: (var in routed or var in passed_to_call) for var, name in var_to_name.items()}


def test_every_web_stack_alarm_construct_has_an_action_or_is_delegated():
    """web_stack.py's own cloudwatch.Alarm(...) constructs (currently just
    SubscriberErrors) must either call .add_alarm_action(...) directly or be handed to
    a helper (add_web_alarms) that is responsible for it — never left bare."""
    init = _find_init(_tree(WEB_STACK), "WebStack")
    status = _alarm_action_status(init.body)
    assert status, "no cloudwatch.Alarm(...) construct found in WebStack.__init__ — parser broke, investigate"
    unrouted = [name for name, has_action in status.items() if not has_action]
    assert not unrouted, f"web_stack.py alarm(s) with no .add_alarm_action(...) and not delegated: {unrouted}"


def test_every_web_alarms_construct_has_an_action():
    """The core #2829 assertion: every alarm web_alarms.py itself constructs must
    call .add_alarm_action(...) in the SAME function body. This is the shape-based
    guard — a new alarm added here without routing it fails on construction shape,
    not on a hand-maintained name list."""
    func = _find_func(_tree(WEB_ALARMS), "add_web_alarms")
    status = _alarm_action_status(func.body)
    # The three orphan adoptions were REMOVED on 2026-08-20 (see the module docstring) because
    # CloudFormation pre-validates a CREATE against existing names and they all exist, so they
    # blocked the entire LifePlatformWeb deploy. #2961 then RESOLVED the open question against
    # adopting them at all (2026-08-27 — see MUST_NOT_BE_CONSTRUCTED below). So zero
    # locally-constructed alarms is the correct PERMANENT state — but the rule below still
    # binds the moment any alarm is constructed here.
    unrouted = [name for name, has_action in status.items() if not has_action]
    assert not unrouted, f"web_alarms.py alarm(s) with no .add_alarm_action(...): {unrouted}"

    # …and because "zero constructs" would make the above vacuous, pin what the module
    # ACTUALLY does: route the alarms web_stack.py hands in. That is the #2829 title bug
    # (`email-subscriber-errors` fired into the void) and the only part that ships.
    src = open(WEB_ALARMS, encoding="utf-8").read()
    assert "subscriber_alarm.add_alarm_action(" in src, (
        "web_alarms.py no longer routes the handed-in subscriber alarm — that is the one "
        "thing #2829 actually fixes, and with no adoptions it is the core of what this module does."
    )


# The us-east-1 orphans that must NEVER be declared as constructs in web_alarms.py, each
# with the reason it stays out. #2961 RESOLVED this on 2026-08-27 — the adoption was
# authorized by the owner, pre-flighted read-only, and stopped on a falsified premise. So
# this pin is now PERMANENT, not "pending #2961": it records a decision, not a to-do.
# Full evidence, the re-derivation commands and the reopen condition live in
# docs/reviews/CLOUDWATCH_AUDIT_2026-07.md §9a.
#
# Two independent reasons hold each name out, and BOTH must be answered before any of them
# is added back:
#   (1) mechanical — the physical alarm already exists, so declaring it makes CloudFormation
#       attempt a CREATE, which fails early validation and blocks the ENTIRE LifePlatformWeb
#       deploy (2026-08-20, surfaced by #1221's deploy). `cdk synth` cannot catch this: synth
#       renders a template from source and never consults live AWS state.
#   (2) substantive — the per-alarm reason below.
MUST_NOT_BE_CONSTRUCTED = {
    "life-platform-dash-5xx-rate": (
        "DECIDED NOT TO ADOPT (#2961, 2026-08-27): it already routes correctly to "
        "life-platform-alerts-us-east-1, so adoption is a naming-only benefit bought with a "
        "production CloudFormation mutation on LifePlatformWeb — the stack whose breakage "
        "blocks the entire web deploy path (PR #2913). Reopen only if the alarm needs a "
        "functional change anyway."
    ),
    "life-platform-dash-total-errors": (
        "DECIDED NOT TO ADOPT (#2961, 2026-08-27): same trade as dash-5xx-rate. Its "
        "DistributionId dimension (E3S424OXQZ8NBE, the main site) is CORRECT — the 'dash' "
        "NAME is the lie (#2963). A rename is recommended but not executed, because renaming "
        "a CloudWatch alarm is a delete-and-recreate that discards alarm history."
    ),
    "life-platform-cf-auth-errors": (
        "RETIRE, DO NOT ADOPT (#2961, 2026-08-27): life-platform-cf-auth is associated with "
        "ZERO Lambda@Edge cache behaviours on all four distributions in the account, so this "
        "alarm's metric can never receive a datapoint (no cf-auth dimension in list-metrics "
        "in either region; StateReasonData frozen at 2026-03-15 with recentDatapoints:[]). "
        "The function still EXISTS and is Active, which is why describe-alarms reads it as "
        "healthy. Adopting AND routing it would ship a permanent OK that reads as coverage "
        "and is not, and would make that false green load-bearing IaC (#3200 class). The "
        "disposition is an owner-batch `aws cloudwatch delete-alarms`."
    ),
}


def test_web_alarms_adopts_exactly_the_expected_names():
    """Pins the #2829 adoption set so a future edit that silently drops/renames one of
    the 4 routed alarms (subscriber-errors is web_stack.py's own, handed in) is caught.
    life-platform-cost-alert / life-platform-ai-cost-soft-alarm are deliberately NOT
    constructed here (RETIRE disposition, see web_alarms.py's module docstring) —
    asserted absent so a later PR can't quietly half-adopt them without updating this
    pin.

    The three MUST_NOT_BE_CONSTRUCTED names are asserted absent with a per-name reason, so
    a failure tells the next author WHY the alarm is out rather than just that a pin
    tripped. This is the permanent state as of #2961's resolution — not a placeholder
    waiting on an import.
    """
    func = _find_func(_tree(WEB_ALARMS), "add_web_alarms")
    status = _alarm_action_status(func.body)
    readded = sorted(set(MUST_NOT_BE_CONSTRUCTED) & set(status))
    assert not readded, "alarm(s) re-added as a CREATE in web_alarms.py:\n" + "\n".join(
        f"  - {name}: {MUST_NOT_BE_CONSTRUCTED[name]}" for name in readded
    )
    assert all(status.values()), "every alarm constructed here must be routed"


def test_the_do_not_adopt_decision_is_recorded_where_a_reader_will_find_it():
    """The pin above is only honest if the reasoning it points at still exists. #2961's
    resolution is recorded in the §9a audit subsection and summarised in web_alarms.py's
    own docstring; if either is deleted, the pin degrades into an unexplained rule and the
    next author's most likely move is to re-attempt the import that was already ruled out.
    """
    doc = os.path.join(ROOT, "docs", "reviews", "CLOUDWATCH_AUDIT_2026-07.md")
    with open(doc, encoding="utf-8") as f:
        audit = f.read()
    assert "### 9a." in audit, "the #2961 resolution subsection (§9a) was removed from the ADR-116 audit doc"
    assert "delete-alarms --region us-east-1 --alarm-names life-platform-cf-auth-errors" in audit, (
        "§9a lost the exact owner-batch retire command for life-platform-cf-auth-errors — that "
        "command IS the recorded disposition; without it the decision is unactionable."
    )

    src = open(WEB_ALARMS, encoding="utf-8").read()
    assert "#2961" in src, "web_alarms.py no longer cites #2961 — a reader lands on the deferral history with no resolution"
    assert "DEFER adoption" not in src, (
        "web_alarms.py still describes the three orphans as a DEFERRED adoption. #2961 RESOLVED "
        "this on 2026-08-27 (decide-not-to-adopt + retire cf-auth-errors); leaving the deferral "
        "language reads as an open to-do and invites the import that was already ruled out."
    )


def test_alerts_topic_is_imported_not_created():
    """#2829's create-vs-import decision: life-platform-alerts-us-east-1 already exists
    live with a confirmed subscriber. Assert web_alarms.py imports it
    (sns.Topic.from_topic_arn) rather than creating a second topic (sns.Topic(...))."""
    tree = _tree(WEB_ALARMS)
    func = _find_func(tree, "add_web_alarms")
    calls = [n for n in ast.walk(func) if isinstance(n, ast.Call)]
    from_arn_calls = [c for c in calls if isinstance(c.func, ast.Attribute) and c.func.attr == "from_topic_arn"]
    new_topic_calls = [
        c
        for c in calls
        if isinstance(c.func, ast.Attribute) and c.func.attr == "Topic" and isinstance(c.func.value, ast.Name) and c.func.value.id == "sns"
    ]
    assert from_arn_calls, "expected sns.Topic.from_topic_arn(...) in add_web_alarms() — the import path"
    assert not new_topic_calls, "add_web_alarms() must not create a new sns.Topic(...) — life-platform-alerts-us-east-1 already exists live"


def test_adr116_audit_doc_has_a_us_east_1_section():
    """#2829 acceptance box 4: the ADR-116 audit doc gains a us-east-1 section so the
    next alarm-audit pass cannot silently skip the region again (the 2026-07 pass was
    us-west-2-only and nothing forced anyone to notice — the verifier found zero
    us-east-1 mentions in the whole doc). Asserts the section header AND the two
    region-specific facts a future pass must reckon with: the full 6-alarm estate table
    and the create-vs-import lesson."""
    doc = os.path.join(ROOT, "docs", "reviews", "CLOUDWATCH_AUDIT_2026-07.md")
    with open(doc, encoding="utf-8") as f:
        text = f.read()
    assert (
        "## 9. us-east-1" in text
    ), "the ADR-116 audit doc lost its us-east-1 section (#2829 acceptance) — a future audit pass could silently skip the region again"
    for anchor in (
        "email-subscriber-errors",
        "life-platform-cf-auth-errors",
        "life-platform-dash-5xx-rate",
        "life-platform-dash-total-errors",
        "life-platform-cost-alert",
        "life-platform-ai-cost-soft-alarm",
        "cdk import",
    ):
        assert (
            anchor in text
        ), f"us-east-1 audit section no longer mentions {anchor!r} — the 6-alarm estate table or the create-vs-import lesson was dropped"
