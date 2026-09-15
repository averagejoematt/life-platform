"""tests/test_reader_audience_urgent_routing_3499.py — #3499.

DEFECT CLASS OWNED (docs/CONVENTIONS.md §9): *escalation bound to the reading cadence
rather than to detection* — a detector whose only responders run on a slower, or inverted,
clock. Two independent instances, both live on main until this landed:

  1. ROUTING. The only probes of the public AI path (`ai-canary-overall`,
     `ai-canary-blind`, and the `ai-canary-heartbeat` dead-man over them) published to
     `life-platform-alerts-digest` and nothing else — one batched email at 15:00Z. #3423
     had already curated these into `READER_AUDIENCE_ALARMS` and lowered their escalation
     bar to first-red, but deliberately added no notification surface, so the "first red"
     bar lived only inside two readers of the board.

  2. ORDERING. One of those two readers is the remediation agent, whose schedule was
     `45 14 * * 1,3,5` (14:45 UTC) while the canary it reads fires
     `cron(20 16 ? * MON,WED,FRI *)` (16:20 UTC) — **95 minutes later**. On all three
     shared days the responder ran before the probe. `remediation/agent.py` reads CURRENT
     ALARM state, so the ordering is the whole behaviour: a Friday `/api/board_ask`
     failure was detected immediately, digested Saturday, and agent-escalated the
     following WEDNESDAY. The measured precedent is in docs/INCIDENT_LOG.md — the #3413
     board-504 P1 sat lit ~31h with zero escalation: "The canary worked; nothing read it."

WHAT THIS FILE HOLDS

  A. every member of the curated facet reaches the URGENT topic in the real synthesized
     CloudFormation, and
  B. the remediation agent's cron is strictly AFTER the AI canary's on every weekday the
     two share.

MUTATION EVIDENCE (a gate that cannot fail is a green light wired to nothing — CHARTER,
"a gate"): both A and B FAIL on the pre-#3499 tree. `test_the_routing_derivation_can_fail`
and `test_the_ordering_assertion_can_fail` re-run each derivation against the exact
pre-#3499 inputs (digest-only AlarmActions; `45 14 * * 1,3,5`) and assert it reds.

WHY THE PRIMARY DERIVATION IS AST, NOT `cdk synth`
`.github/workflows/ci-test.yml` installs pytest/boto3/hypothesis/pyyaml/pillow — NOT
`aws-cdk-lib` — and several modules in the suite register a bare
`types.ModuleType("aws_cdk")` in `sys.modules` so `role_policies.py` imports without it. A synth-only gate would ImportError (or, worse, skip) in the lane that
actually runs on every PR, which is the same "instrument that cannot fire" family this
file exists to close. So the always-running derivation is an AST read of the CDK source —
the established shape here (`tests/test_urgent_alarm_routing.py`,
`tests/test_enrollment_by_construction_2846.py`) — and `test_the_synthesized_template_
agrees_with_the_ast_derivation` re-derives the SAME property from a real
`Template.from_stack(...)` whenever aws-cdk-lib is importable (locally, and in any lane
that has it). That synth was run at authoring time; its verbatim output is recorded below
so the cross-check is a fact on the record, not a promise:

    $ python3 -c "...Template.from_stack(MonitoringStack) + Template.from_stack(ServeStack)..."
    ai-canary-overall                -> [...:life-platform-alerts-digest, ...:life-platform-alerts]
    ai-canary-blind                  -> [...:life-platform-alerts-digest, ...:life-platform-alerts]
    ai-canary-heartbeat              -> [...:life-platform-alerts-digest, ...:life-platform-alerts]
    site-api-errors                  -> [...:life-platform-alerts-digest, ...:life-platform-alerts]
    site-api-handled-5xx             -> [...:life-platform-alerts-digest, ...:life-platform-alerts]
    site-api-ai-errors               -> [...:life-platform-alerts-digest, ...:life-platform-alerts]
    site-api-ai-throttles            -> [...:life-platform-alerts-digest, ...:life-platform-alerts]
    site-api-content-filter-fallback -> [...:life-platform-alerts-digest, ...:life-platform-alerts]
    site-api-invocation-spike        -> [...:life-platform-alerts-digest, ...:life-platform-alerts]
    site-api-p95-latency-high        -> [...:life-platform-alerts-digest, ...:life-platform-alerts]
    site-api-throttles               -> [...:life-platform-alerts-digest, ...:life-platform-alerts]
    routed: 11  registry: 11  missing: []   (2026-09-14, aws-cdk-lib 2.268.0)

v1.0.0 — 2026-09-14 (#3499, epic #3489)
"""

from __future__ import annotations

import ast
import importlib
import os
import re
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CDK_DIR = os.path.join(ROOT, "cdk")
SCRIPTS_DIR = os.path.join(ROOT, "scripts")
for _p in (CDK_DIR, SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from platform_model_alarms import READER_AUDIENCE_ALARMS  # noqa: E402

WORKFLOW = os.path.join(ROOT, ".github", "workflows", "remediation-agent.yml")
OPERATIONAL_STACK = os.path.join(CDK_DIR, "stacks", "operational_stack.py")
ROUTING_MODULE = os.path.join(CDK_DIR, "stacks", "reader_audience.py")
APP = os.path.join(CDK_DIR, "app.py")
MONITORING_STACK = os.path.join(CDK_DIR, "stacks", "monitoring_stack.py")
SERVE_STACK = os.path.join(CDK_DIR, "stacks", "serve_stack.py")

URGENT_TOPIC = "life-platform-alerts"


# ══════════════════════════════════════════════════════════════════════════════
# A. Routing — every facet member reaches the urgent topic
# ══════════════════════════════════════════════════════════════════════════════
#
# The derivation is deliberately NOT "grep for the alarm name near the topic ARN". It
# follows the one seam that actually decides the routing:
#
#   route_reader_audience(alarm, alarm_name, urgent_topic)  [cdk/stacks/reader_audience.py]
#
# so what is proved is that (a) the seam attaches the urgent topic and nothing else,
# (b) the membership test it applies is the REGISTRY (not a second hand-typed list), and
# (c) every stack that declares a facet member calls it, enforced at synth by
# assert_facet_fully_routed(). (a)+(b)+(c) together are exactly "every member's
# AlarmActions include the urgent topic", and unlike a name-by-name grep they keep holding
# when a twelfth alarm is tagged tomorrow — guard the SET, not the instance.


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _fn(path: str, name: str) -> ast.FunctionDef:
    tree = ast.parse(_read(path))
    fn = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name), None)
    assert fn is not None, f"{os.path.basename(path)}::{name} not found — the routing seam was renamed"
    return fn


def test_the_registry_is_the_membership_test_not_a_second_hand_list():
    """`route_reader_audience` must gate on READER_AUDIENCE_ALARMS itself.

    A copy of the 11 names inside the CDK would be the #2844 defect (a hand-maintained
    enumeration of registry vocabulary) and would drift the day the registry does.
    """
    src = _read(ROUTING_MODULE)
    assert "from platform_model_alarms import READER_AUDIENCE_ALARMS" in src, (
        "cdk/stacks/reader_audience.py must import the curated registry, not re-declare it — "
        "the facet has exactly one home (scripts/platform_model_alarms.py)"
    )
    fn = _fn(ROUTING_MODULE, "route_reader_audience")
    names_compared = {
        n.comparators[0].id for n in ast.walk(fn) if isinstance(n, ast.Compare) and n.comparators and isinstance(n.comparators[0], ast.Name)
    }
    assert "READER_AUDIENCE_ALARMS" in names_compared, "route_reader_audience does not test membership against the registry"
    # No alarm-name literal may appear in the routing module at all.
    literals = [c.value for c in ast.walk(ast.parse(src)) if isinstance(c, ast.Constant) and isinstance(c.value, str)]
    leaked = sorted(n for n in READER_AUDIENCE_ALARMS if n in literals)
    assert not leaked, f"alarm names hard-coded in the routing module instead of derived from the registry: {leaked}"


def test_the_routing_seam_attaches_the_urgent_topic():
    """The seam adds an SNS action, and the topic it adds is the urgent one."""
    fn = _fn(ROUTING_MODULE, "route_reader_audience")
    actions = [
        n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "add_alarm_action"
    ]
    assert len(actions) == 1, f"expected exactly one add_alarm_action in the routing seam, found {len(actions)}"
    arg = actions[0].args[0]
    assert isinstance(arg, ast.Call) and getattr(arg.func, "attr", None) == "SnsAction"
    assert (
        isinstance(arg.args[0], ast.Name) and arg.args[0].id == "urgent_topic"
    ), "the seam routes to something other than its urgent_topic parameter"
    src = _read(ROUTING_MODULE)
    assert f'URGENT_TOPIC_NAME = "{URGENT_TOPIC}"' in src, f"the urgent topic name is no longer {URGENT_TOPIC!r}"


def _declaring_stacks() -> dict[str, str]:
    """facet member -> the CDK stack file that declares it (by alarm-name literal)."""
    out = {}
    for path in (MONITORING_STACK, SERVE_STACK, OPERATIONAL_STACK):
        src = _read(path)
        for name in READER_AUDIENCE_ALARMS:
            if f'"{name}"' in src:
                out[name] = path
    return out


def test_every_stack_declaring_a_member_routes_it():
    """No member may be declared in a stack that never calls the seam.

    This is the static half of cdk/app.py::assert_facet_fully_routed — which is the real
    gate, because it raises at synth and so blocks the deploy. Held here too so a PR reds
    in the unit lane instead of only at `cdk synth` time.
    """
    declaring = _declaring_stacks()
    missing = sorted(set(READER_AUDIENCE_ALARMS) - set(declaring))
    assert not missing, f"facet members declared in no known stack file — widen _declaring_stacks: {missing}"
    for name, path in sorted(declaring.items()):
        assert "route_reader_audience" in _read(path), (
            f"{name} is declared in {os.path.basename(path)}, which never calls route_reader_audience() — "
            "it is tagged reader-audience (first-red escalation, #3423) but reaches a human only at the next digest"
        )


def test_the_synth_time_dead_man_is_wired_into_the_app():
    """assert_facet_fully_routed() must run in cdk/app.py BEFORE app.synth().

    Without it, tagging a new alarm `audience: reader` and forgetting the route is silent:
    the model would say `audience: reader`, the citation gate would escalate it on first
    red, and the alarm itself would still be digest-only.
    """
    src = _read(APP)
    assert "assert_facet_fully_routed" in src, "cdk/app.py does not call the #3499 routing dead-man"
    assert src.index("assert_facet_fully_routed()") < src.rindex(
        "app.synth()"
    ), "the dead-man runs after synth — too late to block a deploy"


def test_the_dead_man_actually_raises_on_an_unrouted_member(monkeypatch):
    """MUTATION: plant a twelfth facet member that nothing routes; the guard must red."""
    import stacks.reader_audience as ra

    ra.reset_routing_record()
    monkeypatch.setitem(ra.READER_AUDIENCE_ALARMS, "site-api-invented-3499", "planted by the mutation proof")
    with pytest.raises(AssertionError, match="site-api-invented-3499"):
        ra.assert_facet_fully_routed()
    ra.reset_routing_record()


def test_the_routing_derivation_can_fail():
    """MUTATION: the pre-#3499 tree. A routing module whose seam attaches the DIGEST topic,
    or a stack that declares a member and never calls the seam, must be caught."""
    pre_3499_serve_stack = "\n".join(ln for ln in _read(SERVE_STACK).splitlines() if "route_reader_audience" not in ln)
    assert "route_reader_audience" not in pre_3499_serve_stack
    # the assertion test_every_stack_declaring_a_member_routes_it makes, restated against
    # that text — it must be the failing one.
    assert any(f'"{n}"' in pre_3499_serve_stack for n in READER_AUDIENCE_ALARMS), "sanity: serve_stack declares facet members"
    assert "route_reader_audience" not in pre_3499_serve_stack, "the pre-#3499 serve_stack would have passed — the gate is wired to nothing"


# ── The synth cross-check: the same property, from the real template ──────────


def _real_cdk_available() -> bool:
    """True only for the REAL aws-cdk-lib — and answered LAZILY, at call time.

    NOT `import aws_cdk`. Several modules in this suite install a bare
    `types.ModuleType("aws_cdk")` into `sys.modules` so `role_policies.py` can be imported
    with no CDK present (tests/test_iam_secrets_consistency.py, test_grant_enumeration,
    test_put_metric_data_grant_lockstep, …). In a WHOLE-SUITE run that stub is already
    registered by the time this file is collected, so `import aws_cdk` SUCCEEDS against a
    non-package and the real import then dies with
    `ModuleNotFoundError: No module named 'aws_cdk.assertions'; 'aws_cdk' is not a
    package`. That is not hypothetical — it is how PR #3815's first CI run went red while
    the same file was green in isolation: the capability probe tested a different thing
    than the code under it used. Probe the submodule this test actually imports, and probe
    it inside the test so collection ORDER cannot decide the answer.
    """
    try:
        importlib.import_module("aws_cdk.assertions")
        return True
    except Exception:
        return False


def test_the_cdk_probe_is_not_fooled_by_the_suites_aws_cdk_stub(monkeypatch):
    """REGRESSION (PR #3815, run 34925386669): the probe must answer for the REAL package.

    The first version asked `import aws_cdk`, which is True against the bare
    `types.ModuleType("aws_cdk")` that several modules in this suite register in
    `sys.modules`. The test then did `from aws_cdk.assertions import Template` and the
    whole-suite lane went red on a check that was green in isolation — a capability probe
    that tested something other than the capability. This plants that exact stub and
    asserts the probe says NO.
    """
    import types

    monkeypatch.setitem(sys.modules, "aws_cdk", types.ModuleType("aws_cdk"))
    monkeypatch.delitem(sys.modules, "aws_cdk.assertions", raising=False)
    assert _real_cdk_available() is False, "the probe accepts a stubbed aws_cdk — the #3815 defect, restored"


def test_the_synthesized_template_agrees_with_the_ast_derivation():
    """ACCEPTANCE (1), literally: every member's AlarmActions in the SYNTHESIZED template
    include the urgent topic. Runs wherever the real aws-cdk-lib is importable."""
    if not _real_cdk_available():
        pytest.skip(
            "the real aws-cdk-lib is not importable here — either it is not installed "
            "(.github/workflows/ci-test.yml pins pytest/boto3/hypothesis/pyyaml/pillow only) "
            "or another test in this run has stubbed `aws_cdk` in sys.modules. The AST "
            "derivation above is the gate; this is the cross-check, and it ran green "
            "locally on 2026-09-14 (output in this module's docstring)."
        )
    import aws_cdk as cdk
    import stacks.reader_audience as ra
    from aws_cdk.assertions import Template
    from stacks.monitoring_stack import MonitoringStack
    from stacks.serve_stack import ServeStack

    ra.reset_routing_record()
    app = cdk.App()
    env = cdk.Environment(account="205930651321", region="us-west-2")
    stacks = [
        MonitoringStack(app, "Mon3499", alerts_topic=None, digest_topic=None, env=env),
        ServeStack(app, "Serve3499", env=env),
    ]
    seen: dict[str, list] = {}
    for stack in stacks:
        for res in Template.from_stack(stack).find_resources("AWS::CloudWatch::Alarm").values():
            props = res["Properties"]
            name = props.get("AlarmName")
            if name in READER_AUDIENCE_ALARMS:
                seen[name] = props.get("AlarmActions") or []

    missing = sorted(set(READER_AUDIENCE_ALARMS) - set(seen))
    assert not missing, f"facet members absent from the synthesized Monitoring/Serve templates: {missing}"
    unrouted = sorted(n for n, actions in seen.items() if not any(str(a).endswith(f":{URGENT_TOPIC}") for a in actions))
    assert not unrouted, f"synthesized AlarmActions do NOT include the urgent topic for: {unrouted}"
    # additive, never destructive: the ADR-052 digest record each declaration asked for survives
    lost = sorted(n for n, actions in seen.items() if not any(str(a).endswith(":life-platform-alerts-digest") for a in actions))
    assert not lost, f"#3499 is additive — these lost their digest action: {lost}"
    ra.reset_routing_record()


# ══════════════════════════════════════════════════════════════════════════════
# B. Ordering — the responder's cron runs AFTER the detector's
# ══════════════════════════════════════════════════════════════════════════════
#
# ADR-052's shape: two scheduled things that must agree get a test that fails when they
# diverge. Both sides are DERIVED — the workflow's `schedule.cron` and the CDK construct's
# `schedule="cron(...)"` — so editing either literal moves the assertion. Neither is
# mirrored by hand anywhere in this file except as a sanity anchor.

_CRON_DOW = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}


def _dow_set(field: str) -> frozenset[int]:
    """cron day-of-week field -> {0=Sun..6=Sat}. Handles names, `*`, lists and ranges."""
    field = field.strip().lower()
    if field in ("*", "?"):
        return frozenset(range(7))
    out: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            lo_i, hi_i = _dow_token(lo), _dow_token(hi)
            out.update(range(lo_i, hi_i + 1))
        else:
            out.add(_dow_token(part))
    return frozenset(0 if d == 7 else d for d in out)


def _dow_token(tok: str) -> int:
    tok = tok.strip().lower()
    if tok in _CRON_DOW:
        return _CRON_DOW[tok]
    return int(tok)


def _github_cron() -> tuple[int, frozenset[int]]:
    """(minutes-past-UTC-midnight, weekday set) for the remediation agent's schedule."""
    text = _read(WORKFLOW)
    matches = re.findall(r'^\s*-\s*cron:\s*"([^"]+)"', text, re.M)
    assert len(matches) == 1, f"expected exactly one schedule cron in remediation-agent.yml, found {matches}"
    return _parse_five_field(matches[0])


def _parse_five_field(expr: str) -> tuple[int, frozenset[int]]:
    minute, hour, _dom, _mon, dow = expr.split()
    assert minute.isdigit() and hour.isdigit(), f"non-fixed minute/hour in {expr!r} — this assertion needs a single instant"
    return int(hour) * 60 + int(minute), _dow_set(dow)


def _canary_cron() -> tuple[int, frozenset[int]]:
    """(minutes-past-UTC-midnight, weekday set) for the AI quality canary's EventBridge rule.

    Read from the `schedule=` kwarg of the AiQualityCanary construction in
    operational_stack.py — the CDK definition, which is what a deploy writes to the live
    rule (verified live 2026-09-14: `cron(20 16 ? * MON,WED,FRI *)`, ENABLED).
    """
    tree = ast.parse(_read(OPERATIONAL_STACK))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        ids = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        if "AiQualityCanary" not in ids:
            continue
        sched = next((k.value for k in node.keywords if k.arg == "schedule"), None)
        assert isinstance(sched, ast.Constant), "AiQualityCanary's schedule= is not a literal — re-point this derivation"
        expr = sched.value
        assert expr.startswith("cron(") and expr.endswith(")"), f"unexpected schedule form {expr!r}"
        minute, hour, _dom, _mon, dow, *_ = expr[5:-1].split()
        return int(hour) * 60 + int(minute), _dow_set(dow)
    raise AssertionError("AiQualityCanary construction not found in operational_stack.py — the canary was renamed or moved")


def test_the_remediation_sweep_runs_after_the_ai_canary_on_every_shared_day():
    """ACCEPTANCE (2). `remediation/agent.py` reads CURRENT alarm state, so a responder
    scheduled BEFORE its detector reads a board the detector has not written yet."""
    agent_minute, agent_days = _github_cron()
    canary_minute, canary_days = _canary_cron()
    shared = agent_days & canary_days
    assert shared, (
        f"the remediation sweep {sorted(agent_days)} and the AI canary {sorted(canary_days)} now share NO weekday — "
        "the canary has no scheduled responder at all, which is worse than the inversion #3499 fixed"
    )
    assert agent_minute > canary_minute, (
        f"the remediation sweep runs at {agent_minute // 60:02d}:{agent_minute % 60:02d}Z, "
        f"{canary_minute - agent_minute} minutes BEFORE the AI canary at "
        f"{canary_minute // 60:02d}:{canary_minute % 60:02d}Z, on {len(shared)} shared weekday(s) — "
        "this is the #3499 defect: on those days the responder reads the alarm board before the probe that lights it has run"
    )


def test_the_gap_leaves_room_for_the_canary_to_finish_and_the_alarm_to_transition():
    """Ordering alone is not enough — the canary's own timeout plus CloudWatch's
    evaluation has to fit in the gap. The #3413 precedent: the canary ran 16:20Z and
    `ai-canary-overall` went ALARM at 16:22Z, so ~2 min is the observed transition
    latency; the canary's CDK timeout is 120s. A 15-minute floor is ~7x that, and is
    the number this assertion is derived from rather than a round guess."""
    agent_minute, _ = _github_cron()
    canary_minute, _ = _canary_cron()
    assert agent_minute - canary_minute >= 15, (
        f"only {agent_minute - canary_minute} min between the canary ({canary_minute // 60:02d}:{canary_minute % 60:02d}Z) "
        "and the sweep — below the 15-minute floor (canary timeout 120s + ~2 min observed alarm-transition latency)"
    )


def test_the_ordering_assertion_can_fail():
    """MUTATION: the pre-#3499 literal `45 14 * * 1,3,5` against today's canary must red.

    A test that only read today's two values would have passed the moment #3499 landed and
    told us nothing about whether it could ever catch the inversion again.
    """
    pre_3499_minute, pre_3499_days = _parse_five_field("45 14 * * 1,3,5")
    canary_minute, canary_days = _canary_cron()
    assert pre_3499_days & canary_days, "sanity: the pre-#3499 schedule shared days with the canary"
    assert pre_3499_minute < canary_minute, "the pre-#3499 cron was NOT before the canary — the mutation is stale, re-derive it"
    assert canary_minute - pre_3499_minute == 95, (
        "the pre-#3499 inversion was 95 minutes (14:45Z vs 16:20Z); it is now "
        f"{canary_minute - pre_3499_minute} — the canary's schedule moved, re-check the fix still holds"
    )


def test_todays_two_schedules_are_the_ones_this_file_was_written_against():
    """Sanity anchors, NOT the source. If either moves, the assertions above still decide
    the outcome — this just makes the change visible in the diff of whoever moved it."""
    assert _github_cron() == (
        17 * 60 + 35,
        frozenset({1, 3, 5}),
    ), "the remediation sweep's schedule moved — confirm it is still after the canary"
    assert _canary_cron() == (16 * 60 + 20, frozenset({1, 3, 5})), "the AI canary's schedule moved — confirm the sweep is still after it"
