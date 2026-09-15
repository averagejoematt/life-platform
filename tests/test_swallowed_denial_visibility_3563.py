#!/usr/bin/env python3
"""tests/test_swallowed_denial_visibility_3563.py — the denial nobody tokenized (#3563).

WHAT THIS GUARDS, AND WHY IT IS NOT THE #2654 TWIN
  `tests/test_denied_write_silence_3563.py` pins TWO tokens — CHRONICLE-STATUS-WRITE-FAILED
  and FRESHNESS-SENTINEL-WRITE-FAILED — from both ends. That is the right instrument for a
  swallow site someone has already thought about. It is, by construction, blind to the next
  one: a token can only cover a line a human predicted and edited.

  The #3563 record says how often that prediction is made in time. Denials found in the
  30-day sweep of 2026-09-14, every one inside a fail-soft `except`, every one invisible to
  the only alarm those functions carry (`AWS/Lambda Errors` needs a RAISED exception):

      chronicle-email-sender            3 / 3 sends, 4 weeks, logged at **INFO**
      life-platform-freshness-checker   404 in 30d (155 in the 14d the issue was filed on)
      life-platform-qa-smoke            131 in 30d
      twelve Bedrock-invoking roles     every AI cost datapoint dropped, ongoing that day

  Four separate causes; four separate repairs, each made weeks late by a human reading
  logs. THE REPAIR IS NOT THE INSTRUMENT. This file guards the instrument: one MetricFilter
  per log group in the email + operational family, all publishing ONE dimensionless metric,
  ONE alarm to the digest — so the NEXT denial, in a function nobody has thought about, in
  a path nobody tokenized, reaches the digest within the hour.

THE THREE LEGS
  1. COVERAGE IS DERIVED, BOTH WAYS. `WATCHED_LOG_GROUPS` in
     `cdk/stacks/monitoring_denial_alarms.py` is re-derived here from every
     `create_platform_lambda(function_name=...)` in `email_stack.py` + `operational_stack.py`.
     A new email/checker Lambda missing from the tuple reds; a name in the tuple that is no
     longer a Lambda reds too (a filter on a deleted log group fails the deploy outright).
  2. THE SHAPE IS ONE METRIC AND ONE ALARM. Read out of the CDK module by AST. This is the
     cost argument made testable: the 2026-09-05 forensic RCA rejected a `level=ERROR`
     filter fleet at $1.50–2.90/mo because its price is per DISTINCT METRIC NAME plus an
     alarm each. If a future edit gives filters their own metric names, the bill grows with
     the fleet and this leg reds.
  3. THE PATTERN MATCHES THE WIRE. Real log lines captured read-only from CloudWatch on
     2026-09-14 (`tests/fixtures/denial_visibility/real_denial_log_lines_3563.json`) — the
     actual bytes from all four incidents, including the chronicle sender's at level INFO —
     must match the filter term, and real HEALTHY lines from the same log groups must not.
     A pattern asserted against a hand-written approximation of a log line is a pattern
     asserted against nothing.

WHAT IT DOES NOT PROVE (stated, not left to the reader)
  That the alarm FIRES. That needs a live denial and a deploy of LifePlatformMonitoring;
  it is the live output #3563 closes on, named in the PR body. This file proves the alarm
  is wired to the whole family and watches the string the platform actually prints.

Run:  python3 -m pytest tests/test_swallowed_denial_visibility_3563.py -v
"""

from __future__ import annotations

import ast
import json
import os
import sys

import pytest

# #416 / ADR-117: deploy-critical lane — a monitoring gate on a deploy-shaped defect.
pytestmark = pytest.mark.deploy_critical

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CDK_STACKS = os.path.join(ROOT, "cdk", "stacks")
DENIAL_MODULE = os.path.join(CDK_STACKS, "monitoring_denial_alarms.py")
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "denial_visibility", "real_denial_log_lines_3563.json")

#: The stacks whose Lambdas are "any email or checker Lambda" in the issue's words.
WATCHED_STACKS = ("email_stack.py", "operational_stack.py")

if CDK_STACKS not in sys.path:
    sys.path.insert(0, CDK_STACKS)


def _module_constants() -> dict:
    """Module-level literals of the CDK module, read by AST.

    Deliberately NOT an import: `monitoring_denial_alarms` imports `aws_cdk`, and the CI
    lane that runs the fast tests has no reason to require the CDK install. The constants
    this file asserts on are plain literals, so the AST is the same truth.
    """
    with open(DENIAL_MODULE, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=DENIAL_MODULE)
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                continue
    return out


def _cdk_tree() -> ast.AST:
    with open(DENIAL_MODULE, encoding="utf-8") as fh:
        return ast.parse(fh.read(), filename=DENIAL_MODULE)


def derive_family_log_groups() -> set:
    """`/aws/lambda/<function_name>` for every Lambda built in the watched stacks.

    Reads `create_platform_lambda(function_name="...")` AND the bare `function_name=`
    kwarg of any other construct call, because `operational_stack.py` builds several
    Lambdas without the helper. Missing those would be the worst possible failure here:
    a silently SMALLER derived set makes the coverage assertion pass by asking less.
    """
    groups = set()
    for stack in WATCHED_STACKS:
        path = os.path.join(CDK_STACKS, stack)
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg == "function_name" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    groups.add(f"/aws/lambda/{kw.value.value}")
    return groups


CONSTANTS = _module_constants()
WATCHED = tuple(CONSTANTS.get("WATCHED_LOG_GROUPS", ()))
DERIVED = derive_family_log_groups()

with open(FIXTURE, encoding="utf-8") as _fh:
    REAL_LINES = json.load(_fh)


def matches(term: str, message: str) -> bool:
    """CloudWatch Logs quoted-term semantics, as this alarm uses them.

    `FilterPattern.literal('"AccessDenied"')` on an unstructured (non-JSON-parsed) log
    event is a SUBSTRING match on the raw event text — which is why one term covers both
    the bare `AccessDenied` (S3, CloudWatch) and `AccessDeniedException` (DynamoDB, SSM,
    Secrets Manager), and why it matches a denial embedded in a JSON-formatted log line
    without any field selector.
    """
    return term in message


# ── leg 1: coverage, derived, both directions ────────────────────────────────────────
def test_the_derivation_is_real():
    """Guard the guard: a broken parse would make the coverage legs pass by asking nothing."""
    assert len(DERIVED) >= 40, f"only {len(DERIVED)} Lambdas derived from {WATCHED_STACKS} — the AST walk broke, the fleet did not shrink"
    for canary in (
        "/aws/lambda/chronicle-email-sender",
        "/aws/lambda/life-platform-freshness-checker",
        "/aws/lambda/life-platform-qa-smoke",
    ):
        assert canary in DERIVED, f"{canary} — an incident function of #3563 — is not in the derived family; the derivation lost a stack"
    assert WATCHED, "WATCHED_LOG_GROUPS read empty out of the CDK module — every assertion below is vacuous"


def test_every_email_and_checker_lambda_is_watched():
    """The rule. A Lambda in this family with no denial filter is a Lambda whose next
    AccessDenied is invisible for as long as nobody happens to read its logs."""
    unwatched = sorted(DERIVED - set(WATCHED))
    assert not unwatched, (
        f"{len(unwatched)} Lambda(s) in the email/operational family have NO permission-denial "
        "filter — a swallowed AccessDenied there reaches nothing (#3563):\n"
        + "\n".join(f"  {name}" for name in unwatched)
        + "\n\nFix: add the log group to WATCHED_LOG_GROUPS in cdk/stacks/monitoring_denial_alarms.py "
        "(metric filters are free and they all publish one metric, so coverage costs nothing)."
    )


def test_no_watched_log_group_is_stale():
    """The other direction, and it is not cosmetic: `logs.MetricFilter` on a log group that
    no longer exists FAILS THE DEPLOY of LifePlatformMonitoring. A retired Lambda must be
    removed from the tuple in the same PR that retires it."""
    stale = sorted(set(WATCHED) - DERIVED)
    assert not stale, (
        "these watched log groups are no longer Lambdas in the email/operational family — "
        "delete them, or the next LifePlatformMonitoring deploy fails on a missing log group:\n  " + "\n  ".join(stale)
    )


def test_the_watched_tuple_has_no_duplicates():
    """Two filters on one log group double-count every denial AND collide on construct id."""
    duplicates = sorted({name for name in WATCHED if list(WATCHED).count(name) > 1})
    assert not duplicates, f"duplicate entries in WATCHED_LOG_GROUPS: {duplicates}"


# ── leg 2: one metric, one alarm — the cost argument, made testable ──────────────────
def test_every_filter_publishes_the_same_single_metric():
    """N filters on ONE dimensionless metric is what makes the bill independent of N.

    Give the filters distinct metric names and the price becomes $0.30 × N + $0.10 × N —
    the shape the 2026-09-05 forensic RCA rejected at $1.50–2.90/mo. This leg reds first.
    """
    tree = _cdk_tree()
    metric_names, namespaces = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "MetricFilter":
            kwargs = {kw.arg: kw.value for kw in node.keywords}
            for key, sink in (("metric_name", metric_names), ("metric_namespace", namespaces)):
                node_value = kwargs.get(key)
                if isinstance(node_value, ast.Constant):
                    sink.add(node_value.value)
                elif isinstance(node_value, ast.Name):
                    sink.add(CONSTANTS.get(node_value.id, f"<unresolved {node_value.id}>"))
    assert metric_names == {
        CONSTANTS["DENIAL_METRIC"]
    }, f"filters publish {sorted(metric_names)} — the class must collapse onto one metric name"
    assert namespaces == {CONSTANTS["DENIAL_NAMESPACE"]}, f"filters publish into {sorted(namespaces)} — one namespace, one metric"


def test_exactly_one_alarm_with_a_literal_name_routed_to_the_digest():
    """One alarm for the class, its name a LITERAL (deploy/alarm_discovery.py and
    scripts/generate_platform_model.py both resolve alarm names statically and both go
    blind on a templated one — the #2977 lesson), and it must actually notify."""
    tree = _cdk_tree()
    alarms = [
        node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "Alarm"
    ]
    assert len(alarms) == 1, f"expected exactly one Alarm in the denial module, found {len(alarms)}"
    kwargs = {kw.arg: kw.value for kw in alarms[0].keywords}
    name_node = kwargs.get("alarm_name")
    resolved = name_node.value if isinstance(name_node, ast.Constant) else CONSTANTS.get(getattr(name_node, "id", ""), None)
    assert resolved == CONSTANTS["DENIAL_ALARM_NAME"], f"alarm_name resolved to {resolved!r}"
    source = open(DENIAL_MODULE, encoding="utf-8").read()
    assert (
        "add_alarm_action(cw_actions.SnsAction(digest))" in source
    ), "the class alarm is not routed to the digest topic — it would fire into nothing"
    assert "NOT_BREACHING" in source, "missing data must be NOT_BREACHING: absence of a denial is health, not an unknown"


def test_the_stack_actually_calls_it():
    """A monitoring module nothing calls is a file, not an alarm. #3563's whole class is
    instruments that exist and do not run."""
    monitoring = open(os.path.join(CDK_STACKS, "monitoring_stack.py"), encoding="utf-8").read()
    assert "from stacks.monitoring_denial_alarms import add_denial_alarms" in monitoring
    assert "add_denial_alarms(self, digest)" in monitoring, "MonitoringStack never calls add_denial_alarms — nothing is deployed"


# ── leg 3: the pattern matches the wire ──────────────────────────────────────────────
def test_the_fixture_is_the_wire_and_covers_every_incident():
    """The fixture must be REAL captured lines, and must span the incidents — otherwise
    'the pattern matches' is a claim about one convenient example."""
    lines = REAL_LINES["lines"]
    assert len(lines) >= 5, f"only {len(lines)} captured denial lines — the fixture lost its coverage"
    groups = {line["log_group"] for line in lines}
    for required in (
        "/aws/lambda/chronicle-email-sender",
        "/aws/lambda/life-platform-freshness-checker",
        "/aws/lambda/life-platform-qa-smoke",
    ):
        assert required in groups, f"the captured set no longer includes {required} — one of the four #3563 incidents is unrepresented"
    sender = next(line for line in lines if line["log_group"] == "/aws/lambda/chronicle-email-sender")
    assert '"level":"INFO"' in sender["message"], (
        "the chronicle sender's captured line is the reason this alarm does not key on a log LEVEL — "
        "the four-week denial was logged at INFO. If that line was replaced, re-derive the design."
    )


@pytest.mark.parametrize("line", REAL_LINES["lines"], ids=lambda line: f"{line['log_group'].rsplit('/', 1)[-1]}@{line['observed_at']}")
def test_the_filter_term_matches_every_real_denial(line):
    """Each real line, from the real wire, against the real term."""
    assert matches(CONSTANTS["DENIAL_TERM"], line["message"]), (
        f"the filter term {CONSTANTS['DENIAL_TERM']!r} does not match a REAL denial logged by "
        f"{line['log_group']} at {line['observed_at']} — the alarm would have stayed silent through it."
    )


@pytest.mark.parametrize("line", REAL_LINES["healthy_lines"], ids=lambda line: line["log_group"].rsplit("/", 1)[-1])
def test_the_filter_term_does_not_match_a_healthy_line(line):
    """The negative control. A term that matches everything is an alarm that means nothing —
    and at threshold=1 over 5 minutes it would page on every invocation."""
    assert not matches(CONSTANTS["DENIAL_TERM"], line["message"]), f"the filter term matches a HEALTHY line from {line['log_group']}"


def test_the_term_covers_both_botocore_spellings():
    """`AccessDenied` (S3, CloudWatch) and `AccessDeniedException` (DynamoDB, SSM, Secrets
    Manager) are both real; the second contains the first, which is why ONE term suffices.
    If the term is ever narrowed to the Exception spelling, the S3/CloudWatch half of the
    measured set goes dark — and that half is 12 of the 16 roles."""
    term = CONSTANTS["DENIAL_TERM"]
    assert matches(term, "An error occurred (AccessDenied) when calling the PutMetricData operation")
    assert matches(term, "An error occurred (AccessDeniedException) when calling the PutItem operation")


# ── mutation controls ────────────────────────────────────────────────────────────────
def test_MUTATION_an_unwatched_family_lambda_reds():
    """Positive control for leg 1. Without it the coverage assertion could be a check that
    cannot fail — the #3563 class's own failure mode."""
    planted = DERIVED | {"/aws/lambda/brand-new-checker"}
    assert sorted(planted - set(WATCHED)) == ["/aws/lambda/brand-new-checker"], "a new unwatched family Lambda would not be reported"


def test_MUTATION_a_stale_watched_group_reds():
    """Positive control for the other direction."""
    assert sorted({"/aws/lambda/retired-fn"} - DERIVED) == ["/aws/lambda/retired-fn"], "a retired log group would not be reported"


def test_MUTATION_the_pattern_leg_can_fail():
    """Positive control for leg 3: `matches` must be able to say no."""
    assert not matches("AccessDenied", "[INFO] daily brief sent to 4 subscribers")
    assert matches("AccessDenied", "is not authorized to perform: dynamodb:PutItem (AccessDeniedException)")
